"""Citation sufficiency measurement probe.

Evaluates the Evidentiary Delta between a cited source passage and the
claim it is asked to support. Unlike faithfulness (does the source say
what the text claims?) or completeness (did the text capture the source's
full message?), sufficiency asks: does the source possess the evidentiary
weight to fully carry the burden of proof required by the claim?

Catches: scope/sample extrapolation, magnitude/rhetorical inflation,
causal escalation, and compound claim partiality.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from models import CitationVerdict, Finding, ProbeResult, SectionResult
from probes import register_probe
from probes._extract import CitationTriple, extract_citation_triples, find_evidence, mark_sentence_in_context
from probes._judge import call_judge
from probes._prompts import CITATION_SUFFICIENCY_PROMPT

if TYPE_CHECKING:
    from research.context import ResearchContext


# ---------------------------------------------------------------------------
# Verdict scores
# ---------------------------------------------------------------------------

_VERDICT_SCORES = {
    "FULLY_SUFFICIENT": 1.0,
    "MINOR_OVERREACH": 0.7,
    "SIGNIFICANT_OVERREACH": 0.3,
    "UNSUPPORTED_FIG_LEAF": 0.0,
}


# ---------------------------------------------------------------------------
# Judge response schema (Chain-of-Thought enforced)
# ---------------------------------------------------------------------------


class _JudgeResponse(BaseModel):
    """Structured output schema enforcing analysis-before-verdict ordering."""

    claim_burden_analysis: str
    evidence_capacity_analysis: str
    evidentiary_gap_analysis: str
    unsupported_elements: list[str]
    verdict: Literal["FULLY_SUFFICIENT", "MINOR_OVERREACH", "SIGNIFICANT_OVERREACH", "UNSUPPORTED_FIG_LEAF"]


# ---------------------------------------------------------------------------
# LM judge
# ---------------------------------------------------------------------------


async def _judge_citation_sufficiency(
    triple: CitationTriple,
    finding: Finding,
    section_result: SectionResult,
    context: ResearchContext,
) -> CitationVerdict:
    """Ask the LM judge to evaluate one citation for sufficiency."""
    marked_context = mark_sentence_in_context(section_result.content, triple.raw_sentence)

    prompt = CITATION_SUFFICIENCY_PROMPT.format(
        citation_id=triple.citation_id,
        citing_sentence=triple.clean_sentence,
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
        rationale = parsed.evidentiary_gap_analysis
        unsupported = parsed.unsupported_elements
        score = _VERDICT_SCORES[verdict]
    except Exception as exc:
        verdict = "PARSE_ERROR"
        score = 0.0
        rationale = f"Judge call failed: {exc}"
        unsupported = []

    return CitationVerdict(
        citation_id=triple.citation_id,
        citing_sentence=triple.clean_sentence,
        source_chunk_text=finding.text,
        source_file=finding.source_file,
        source_heading=finding.heading,
        verdict=verdict,
        score=score,
        rationale=rationale,
        omissions=unsupported,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@register_probe
async def run_citation_sufficiency_probe(
    section_result: SectionResult,
    section_evidence: list[Finding],
    context: ResearchContext,
) -> ProbeResult:
    """Run the citation sufficiency probe on a single section.

    Extracts all [^N] citations, resolves each to its source chunk,
    and asks an LM judge whether the source carries the burden of proof
    required by the claim.
    """
    triples = extract_citation_triples(section_result.content)

    if not triples:
        return ProbeResult(
            probe_name="citation_sufficiency",
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
                _judge_citation_sufficiency(
                    triple, finding, section_result, context
                )
            )

    if tasks:
        judged = await asyncio.gather(*tasks)
        verdicts.extend(judged)

    total = len(verdicts)
    mean_score = sum(v.score for v in verdicts) / total if total else 0.0

    return ProbeResult(
        probe_name="citation_sufficiency",
        section_title=section_result.section_title,
        verdicts=verdicts,
        mean_score=mean_score,
        summary={
            "num_fully_sufficient": sum(1 for v in verdicts if v.verdict == "FULLY_SUFFICIENT"),
            "num_minor_overreach": sum(1 for v in verdicts if v.verdict == "MINOR_OVERREACH"),
            "num_significant_overreach": sum(1 for v in verdicts if v.verdict == "SIGNIFICANT_OVERREACH"),
            "num_unsupported_fig_leaf": sum(1 for v in verdicts if v.verdict == "UNSUPPORTED_FIG_LEAF"),
            "num_not_found": sum(1 for v in verdicts if v.verdict == "NOT_FOUND"),
            "num_parse_error": sum(1 for v in verdicts if v.verdict == "PARSE_ERROR"),
            "num_citations_checked": total,
        },
    )
