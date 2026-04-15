"""Citation faithfulness evaluation probe.

Extracts every [^N] citation from a written section, resolves the cited
source chunk, and asks an LM judge whether the source actually supports
the claim made in the citing sentence.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from models import CitationVerdict, Finding, ProbeResult, SectionResult
from probes import register_probe
from probes._extract import CitationTriple, extract_citation_triples, find_evidence, mark_sentence_in_context
from probes._judge import call_judge, gather_with_progress
from probes._prompts import CITATION_FAITHFULNESS_PROMPT

if TYPE_CHECKING:
    from research.context import ResearchContext


# ---------------------------------------------------------------------------
# LM judge
# ---------------------------------------------------------------------------

_VERDICT_SCORES = {
    "SUPPORTED": 1.0,
    "PARTIALLY_SUPPORTED": 0.5,
    "NOT_SUPPORTED": 0.0,
}


class _JudgeResponse(BaseModel):
    """Structured output schema enforcing analysis-before-verdict ordering."""

    source_claims: str
    claim_identified: str
    rationale: str
    verdict: Literal["SUPPORTED", "PARTIALLY_SUPPORTED", "NOT_SUPPORTED"]



async def _judge_citation(
    triple: CitationTriple,
    finding: Finding,
    section_result: SectionResult,
    context: ResearchContext,
) -> CitationVerdict:
    """Ask the LM judge to evaluate one citation triple."""
    marked_context = mark_sentence_in_context(section_result.content, triple.raw_sentence)

    prompt = CITATION_FAITHFULNESS_PROMPT.format(
        source_file=finding.source_file,
        source_heading=finding.heading,
        source_chunk_text=finding.text,
        marked_section_context=marked_context,
    )

    try:
        parsed = await call_judge(
            context.infra.openai_client, context.infra.model_name, prompt, _JudgeResponse
        )
        verdict = parsed.verdict
        rationale = parsed.rationale
        score = _VERDICT_SCORES[verdict]
    except Exception as exc:
        verdict = "PARSE_ERROR"
        score = 0.0
        rationale = f"Judge call failed: {exc}"

    return CitationVerdict(
        citation_id=triple.citation_id,
        citing_sentence=triple.clean_sentence,
        source_chunk_text=finding.text,
        source_file=finding.source_file,
        source_heading=finding.heading,
        verdict=verdict,
        score=score,
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@register_probe
async def run_citation_faithfulness_probe(
    section_result: SectionResult,
    section_evidence: list[Finding],
    context: ResearchContext,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> ProbeResult:
    """Run the citation faithfulness probe on a single section.

    Extracts all [^N] citations, resolves each to its source chunk,
    and asks an LM judge whether the source supports the claim.
    """
    triples = extract_citation_triples(section_result.content)

    if not triples:
        return ProbeResult(
            probe_name="citation_faithfulness",
            section_title=section_result.section_title,
        )

    verdicts: list[CitationVerdict] = []
    tasks: list = []

    for triple in triples:
        finding = find_evidence(
            triple.citation_id, section_evidence, context.state.evidence
        )

        if finding is None:
            # Citation ID not found in any evidence — automatic NOT_SUPPORTED
            verdicts.append(
                CitationVerdict(
                    citation_id=triple.citation_id,
                    citing_sentence=triple.clean_sentence,
                    source_chunk_text="",
                    source_file="",
                    source_heading="",
                    verdict="NOT_SUPPORTED",
                    score=0.0,
                    rationale=f"Citation ID {triple.citation_id} not found in evidence.",
                )
            )
        else:
            tasks.append(
                _judge_citation(
                    triple, finding, section_result, context
                )
            )

    # Run all judge calls concurrently with progress tracking
    if tasks:
        judged = await gather_with_progress(tasks, on_progress)
        verdicts.extend(judged)

    # Aggregate
    total = len(verdicts)
    mean_score = sum(v.score for v in verdicts) / total if total else 0.0

    return ProbeResult(
        probe_name="citation_faithfulness",
        section_title=section_result.section_title,
        verdicts=verdicts,
        mean_score=mean_score,
        summary={
            "num_supported": sum(1 for v in verdicts if v.verdict == "SUPPORTED"),
            "num_partially_supported": sum(
                1 for v in verdicts if v.verdict == "PARTIALLY_SUPPORTED"
            ),
            "num_not_supported": sum(
                1 for v in verdicts if v.verdict in ("NOT_SUPPORTED", "PARSE_ERROR")
            ),
            "num_citations_checked": total,
        },
    )
