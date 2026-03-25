"""Exhaustive relevance scanner.

Instead of search-based retrieval, iterates every chunk in the corpus and
asks the LLM to score its relevance against all research questions in a
single call per chunk.  Results are stored on the ResearchContext for
downstream metrics and converted to Findings for synthesis.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from pydantic import BaseModel
from tqdm.asyncio import tqdm

from models import (
    ChunkRelevanceJudgment,
    Finding,
    QueryRelevance,
    ScanResult,
)

from config import Config

if TYPE_CHECKING:
    from research.context import ResearchContext
    from models import Chunk


# ---------------------------------------------------------------------------
# Structured-output models (never exposed outside this module)
# ---------------------------------------------------------------------------

class _QuestionRelevance(BaseModel):
    relevance_score: float
    rationale: str


class _ChunkRelevanceResponse(BaseModel):
    question_relevances: list[_QuestionRelevance]


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SCANNER_PROMPT = """\
You are a relevance assessor for a research corpus.

Given a text chunk and an ordered list of research questions, score how \
relevant and responsive the chunk is to each question.

For each question provide:
- relevance_score: a float from 0.0 to 1.0 using this scale:
    0.0  - No bearing on the question whatsoever.
    0.25 - Tangentially related; mentions a related topic but provides no useful context.
    0.5  - Provides background context, definitions, or foundational information that \
helps a reader understand the question or its subject matter.
    0.75 - Substantially relevant; contains clear, directly useful information \
that addresses the question or a key aspect of it.
    1.0  - Directly and comprehensively addresses the question.
- rationale: a brief (1-2 sentence) explanation of the score.

IMPORTANT: Background and contextual information matters. A chunk that explains \
what a concept is, how a system works, or provides historical/definitional context \
for the subject of a question should score at least 0.5, even if it does not \
directly answer the question. A well-written research report needs both direct \
answers and the background context that makes those answers understandable.

Return exactly one entry per question, in the same order as listed.
"""


def _user_prompt(chunk: "Chunk", questions: list[str]) -> str:
    heading_line = f"Section: {chunk.heading}\n" if chunk.heading else ""
    numbered = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions))
    return f"<chunk>\n{heading_line}{chunk.text}\n</chunk>\n\nQuestions:\n{numbered}"


# ---------------------------------------------------------------------------
# Per-chunk async evaluation
# ---------------------------------------------------------------------------

async def _evaluate_chunk(
    semaphore: asyncio.Semaphore,
    context: "ResearchContext",
    chunk: "Chunk",
    questions: list[str],
    relevance_threshold: float,
) -> list[ChunkRelevanceJudgment]:
    """Evaluate a single chunk against all questions under the concurrency semaphore."""
    try:
        async with semaphore:
            response = await context.infra.openai_client.beta.chat.completions.parse(
                model=context.infra.model_name,
                messages=[
                    {"role": "system", "content": _SCANNER_PROMPT},
                    {"role": "user", "content": _user_prompt(chunk, questions)},
                ],
                temperature=0.0,
                reasoning_effort=Config().search_reasoning_effort,
                response_format=_ChunkRelevanceResponse,
            )

        parsed: _ChunkRelevanceResponse = response.choices[0].message.parsed

        if parsed is None:
            print(f"[scanner] WARNING: No parsed output for {chunk.chunk_id}, skipping")
            return []

        judgments: list[ChunkRelevanceJudgment] = []
        for i, qr in enumerate(parsed.question_relevances):
            if i >= len(questions):
                break
            score = max(0.0, min(1.0, qr.relevance_score))
            judgments.append(
                ChunkRelevanceJudgment(
                    chunk_id=chunk.chunk_id,
                    question_index=i,
                    is_relevant=score >= relevance_threshold,
                    relevance_score=score,
                    rationale=qr.rationale,
                )
            )

        return judgments
    except Exception as exc:
        print(
            f"[scanner] WARNING: Chunk evaluation failed for {chunk.chunk_id} "
            f"(source={chunk.source_file}, heading={chunk.heading!r}): {exc}"
        )
        return []


# ---------------------------------------------------------------------------
# BM25 prefilter
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Lowercase split on non-alphanumeric, filter short tokens."""
    tokens = re.split(r"[^a-z0-9]+", text.lower())
    return [t for t in tokens if len(t) >= 3]


def _prefilter_chunks(
    chunks: list["Chunk"],
    questions: list[str],
    verbose: bool,
) -> list["Chunk"]:
    """Keep chunks with a positive BM25 score at or above the mean of positive scorers.

    BM25 scores are right-skewed with a spike at zero: chunks sharing no tokens
    with the query score exactly 0 and are clearly irrelevant.  Using a global
    mean or median is unreliable because a majority-zero distribution collapses
    the median to zero (keeping everything) and inflates the mean via outliers.

    Instead we use a two-step threshold:
      1. Drop score-zero chunks (no query-term overlap at all).
      2. Of the remaining positive-scoring chunks, keep those >= mean + 1σ.

    Mean + 1σ keeps only chunks that are genuinely above the pack (~16% of
    positive scorers for a normal distribution, typically fewer for the
    right-skewed BM25 distribution).  Falls back to mean alone if the positive
    scores are so tightly clustered that mean+1σ would return nothing.
    Adaptive to the corpus and query; no fixed hyperparameter.
    Uses a lightweight in-process BM25 so no API calls are needed.
    """
    from rank_bm25 import BM25Okapi

    corpus = [_tokenize(c.text) for c in chunks]
    bm25 = BM25Okapi(corpus)

    max_scores = [0.0] * len(chunks)
    for q in questions:
        scores = bm25.get_scores(_tokenize(q))
        for i, s in enumerate(scores):
            if s > max_scores[i]:
                max_scores[i] = s

    positive_scores = [s for s in max_scores if s > 0.0]
    if not positive_scores:
        return chunks  # no query-term overlap anywhere; pass everything through

    mean_positive = sum(positive_scores) / len(positive_scores)
    variance = sum((s - mean_positive) ** 2 for s in positive_scores) / len(positive_scores)
    std_positive = variance ** 0.5
    threshold = mean_positive + std_positive

    kept = [c for i, c in enumerate(chunks) if max_scores[i] >= threshold]

    if not kept:
        # Degenerate case: all positive scorers are tightly clustered; fall back to mean
        kept = [c for i, c in enumerate(chunks) if max_scores[i] >= mean_positive]
        threshold = mean_positive

    if verbose:
        print(
            f"[scanner] BM25 prefilter: {len(positive_scores)}/{len(chunks)} chunks had "
            f"positive score; kept {len(kept)} with score >= mean+1σ ({threshold:.3f})"
        )

    return kept


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def exhaustive_scan(
    context: "ResearchContext",
    original_question: str,
    *,
    relevance_threshold: float = 0.5,
    batch_size: int = 32,
    prefilter: bool = False,
    verbose: bool = False,
    on_progress: Callable[[int, int, int], Awaitable[None]] | None = None,
    on_prefilter: Callable[[int, int], Awaitable[None]] | None = None,
) -> ScanResult:
    """Scan every corpus chunk against all questions and record evidence.

    Evaluates each chunk against deduplicated [original_question] + sub_questions
    in a single LLM call per chunk.

    Stores all ChunkRelevanceJudgment objects on context.state.chunk_relevance_judgments
    and converts relevant chunks into Findings on context.state.evidence
    with actual chunk text in findings for downstream synthesis.

    Returns a ScanResult for pipeline inspection.
    """
    # Build deduplicated question list (original first, then sub-questions)
    questions: list[str] = [original_question]
    for sq in context.state.sub_questions:
        if sq != original_question:
            questions.append(sq)

    all_chunks = context.infra.document_store.all_chunks()

    if prefilter:
        total_before = len(all_chunks)
        all_chunks = _prefilter_chunks(all_chunks, questions, verbose)
        if on_prefilter is not None:
            await on_prefilter(len(all_chunks), total_before)

    if verbose:
        print(
            f"[scanner] {len(all_chunks)} chunks (with {len(questions)} questions evaluated per-chunk)"
            f" | batch={batch_size} | threshold={relevance_threshold}"
        )

    semaphore = asyncio.Semaphore(batch_size)

    tasks = [
        _evaluate_chunk(
            semaphore, context, chunk, questions, relevance_threshold
        )
        for chunk in all_chunks
    ]
    if on_progress is not None:
        completed_count = 0
        results_by_index: list[list[ChunkRelevanceJudgment] | None] = [None] * len(tasks)

        async def _tracked(index: int, coro):
            nonlocal completed_count
            result = await coro
            results_by_index[index] = result
            completed_count += 1
            if completed_count % 5 == 0 or completed_count == len(tasks):
                relevant_so_far = sum(1 for r in results_by_index if r is not None for j in r if j.is_relevant)
                await on_progress(completed_count, len(tasks), relevant_so_far)
            return result

        await asyncio.gather(*[_tracked(i, t) for i, t in enumerate(tasks)])
        results: list[list[ChunkRelevanceJudgment]] = [r for r in results_by_index if r is not None]
    else:
        results: list[list[ChunkRelevanceJudgment]] = await tqdm.gather(
            *tasks, desc="Scanning chunks", unit="chunk"
        )

    # Flatten and persist all judgments
    all_judgments: list[ChunkRelevanceJudgment] = [j for chunk_js in results for j in chunk_js]
    context.state.chunk_relevance_judgments = all_judgments

    relevant_count = sum(1 for j in all_judgments if j.is_relevant)
    if verbose:
        print(f"[scanner] {relevant_count}/{len(all_judgments)} (chunk, question) pairs relevant")

    # --- Convert relevant judgments to Findings (one per unique chunk) ---
    chunk_by_id: dict[str, "Chunk"] = {c.chunk_id: c for c in all_chunks}

    # Group relevant judgments by chunk_id, collecting all query relevances
    findings_by_chunk: dict[str, Finding] = {}
    for j in all_judgments:
        if not j.is_relevant:
            continue
        chunk = chunk_by_id.get(j.chunk_id)
        if not chunk:
            continue

        if j.chunk_id not in findings_by_chunk:
            citation_id = context.infra.citation_tracker.add_citation(chunk)
            findings_by_chunk[j.chunk_id] = Finding(
                citation_id=citation_id,
                chunk_id=chunk.chunk_id,
                source_file=chunk.source_file,
                heading=chunk.heading,
                text=chunk.text,
                relevance=[],
            )

        findings_by_chunk[j.chunk_id].relevance.append(
            QueryRelevance(
                query=questions[j.question_index],
                relevance_score=j.relevance_score,
                rationale=j.rationale,
            )
        )

    # Store sorted by citation_id
    context.state.evidence = sorted(findings_by_chunk.values(), key=lambda f: f.citation_id)

    evidence_count = len(context.state.evidence)
    if verbose:
        print(f"[scanner] Recorded {evidence_count} evidence items.")

    return ScanResult(
        questions=questions,
        total_chunks=len(all_chunks),
        total_judgments=len(all_judgments),
        relevant_count=relevant_count,
        evidence_count=evidence_count,
    )
