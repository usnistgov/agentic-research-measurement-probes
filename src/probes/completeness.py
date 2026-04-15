"""Citation completeness evaluation probe.

Evaluates the Representational Delta between each cited source passage and
the text that cites it. Unlike the faithfulness probe (which checks whether
the source supports the claim at all), this probe checks whether the citing
text accurately and completely represents what the source actually says —
its full message, epistemic weight, and boundaries.

Catches: missing hedges, scope erasure, statistical asymmetry, trade-off
erasure, proportionality skew, and any other material distortion.
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
from probes._prompts import CITATION_COMPLETENESS_PROMPT

if TYPE_CHECKING:
    from research.context import ResearchContext


# ---------------------------------------------------------------------------
# Verdict scores
# ---------------------------------------------------------------------------

_VERDICT_SCORES = {
    "COMPLETE": 1.0,
    "MINOR_OMISSION": 0.7,
    "SIGNIFICANT_OMISSION": 0.3,
    "MISREPRESENTATION": 0.0,
}


# ---------------------------------------------------------------------------
# Judge response schema (Chain-of-Thought enforced)
# ---------------------------------------------------------------------------


class _JudgeResponse(BaseModel):
    """Structured output schema enforcing analysis-before-verdict ordering."""

    source_key_claims: str
    alignment_analysis: str
    rationale: str
    omissions: list[str]
    verdict: Literal["COMPLETE", "MINOR_OMISSION", "SIGNIFICANT_OMISSION", "MISREPRESENTATION"]


# ---------------------------------------------------------------------------
# LM judge
# ---------------------------------------------------------------------------


async def _judge_citation_completeness(
    triple: CitationTriple,
    finding: Finding,
    section_result: SectionResult,
    context: ResearchContext,
) -> CitationVerdict:
    """Ask the LM judge to evaluate one citation for completeness."""
    marked_context = mark_sentence_in_context(section_result.content, triple.raw_sentence)

    prompt = CITATION_COMPLETENESS_PROMPT.format(
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
        omissions = parsed.omissions
        score = _VERDICT_SCORES[verdict]
    except Exception as exc:
        verdict = "PARSE_ERROR"
        score = 0.0
        rationale = f"Judge call failed: {exc}"
        omissions = []

    return CitationVerdict(
        citation_id=triple.citation_id,
        citing_sentence=triple.clean_sentence,
        source_chunk_text=finding.text,
        source_file=finding.source_file,
        source_heading=finding.heading,
        verdict=verdict,
        score=score,
        rationale=rationale,
        omissions=omissions,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@register_probe
async def run_citation_completeness_probe(
    section_result: SectionResult,
    section_evidence: list[Finding],
    context: ResearchContext,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> ProbeResult:
    """Run the citation completeness probe on a single section.

    Extracts all [^N] citations, resolves each to its source chunk,
    and asks an LM judge whether the citing text accurately and completely
    represents what the source actually says.
    """
    triples = extract_citation_triples(section_result.content)

    if not triples:
        return ProbeResult(
            probe_name="citation_completeness",
            section_title=section_result.section_title,
        )

    verdicts: list[CitationVerdict] = []
    tasks: list = []

    for triple in triples:
        finding = find_evidence(
            triple.citation_id, section_evidence, context.state.evidence
        )

        if finding is None:
            verdicts.append(
                CitationVerdict(
                    citation_id=triple.citation_id,
                    citing_sentence=triple.clean_sentence,
                    source_chunk_text="",
                    source_file="",
                    source_heading="",
                    verdict="NOT_FOUND",
                    score=0.0,
                    rationale=f"Citation ID {triple.citation_id} not found in evidence.",
                )
            )
        else:
            tasks.append(
                _judge_citation_completeness(
                    triple, finding, section_result, context
                )
            )

    if tasks:
        judged = await gather_with_progress(tasks, on_progress)
        verdicts.extend(judged)

    total = len(verdicts)
    mean_score = sum(v.score for v in verdicts) / total if total else 0.0

    return ProbeResult(
        probe_name="citation_completeness",
        section_title=section_result.section_title,
        verdicts=verdicts,
        mean_score=mean_score,
        summary={
            "num_complete": sum(1 for v in verdicts if v.verdict == "COMPLETE"),
            "num_minor_omission": sum(1 for v in verdicts if v.verdict == "MINOR_OMISSION"),
            "num_significant_omission": sum(1 for v in verdicts if v.verdict == "SIGNIFICANT_OMISSION"),
            "num_misrepresentation": sum(1 for v in verdicts if v.verdict == "MISREPRESENTATION"),
            "num_not_found": sum(1 for v in verdicts if v.verdict == "NOT_FOUND"),
            "num_parse_error": sum(1 for v in verdicts if v.verdict == "PARSE_ERROR"),
            "num_citations_checked": total,
        },
    )
