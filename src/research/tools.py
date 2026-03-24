"""Agent tools decorated with @function_tool from the agents package."""

from __future__ import annotations

import json

from agents import RunContextWrapper, function_tool

from research.context import ResearchContext
from models import Finding, QueryRelevance, ReportOutline, SectionPlan


@function_tool
def submit_plan(ctx: RunContextWrapper[ResearchContext], sub_questions: list[str]) -> str:
    """Submit a research plan consisting of focused sub-questions.

    The manager must call this tool with a list of 3-5 sub-questions that
    together cover the full scope of the research question.
    """
    ctx.context.state.sub_questions = sub_questions
    formatted = "\n".join(f"  {i}. {q}" for i, q in enumerate(sub_questions, 1))
    return f"Plan submitted with {len(sub_questions)} sub-questions:\n{formatted}"


@function_tool
def get_chunk_text(ctx: RunContextWrapper[ResearchContext], chunk_id: str) -> str:
    """Retrieve the full text of a specific chunk by its ID.

    Use this to read the complete content of a chunk found during search.
    """
    chunk = ctx.context.infra.document_store.get_chunk(chunk_id)
    if chunk is None:
        return f"Chunk not found: {chunk_id}"

    return (
        f"Source: {chunk.source_file}\n"
        f"Heading: {chunk.heading}\n"
        f"Chunk ID: {chunk.chunk_id}\n"
        f"---\n"
        f"{chunk.text}"
    )


@function_tool
def record_evidence(
    ctx: RunContextWrapper[ResearchContext],
    sub_question: str,
    findings: str,
    chunk_ids: list[str],
    relevance_score: float = 0.8,
) -> str:
    """Record evidence gathered from the corpus.

    Creates or updates findings for each referenced chunk, appending the
    query relevance to existing findings if the chunk was already recorded.
    """
    recorded_ids: list[int] = []
    evidence_list = ctx.context.state.evidence
    # Index existing findings by chunk_id for fast lookup
    existing: dict[str, Finding] = {f.chunk_id: f for f in evidence_list}

    for cid in chunk_ids:
        chunk = ctx.context.infra.document_store.get_chunk(cid)
        if not chunk:
            continue

        citation_id = ctx.context.infra.citation_tracker.add_citation(chunk)
        qr = QueryRelevance(
            query=sub_question,
            relevance_score=relevance_score,
            rationale=findings,
        )

        if chunk.chunk_id in existing:
            existing[chunk.chunk_id].relevance.append(qr)
        else:
            finding = Finding(
                citation_id=citation_id,
                chunk_id=chunk.chunk_id,
                source_file=chunk.source_file,
                heading=chunk.heading,
                text=chunk.text,
                relevance=[qr],
            )
            evidence_list.append(finding)
            existing[chunk.chunk_id] = finding

        recorded_ids.append(citation_id)

    cite_refs = ", ".join(f"[{cid}]" for cid in recorded_ids)
    return f"Evidence recorded for '{sub_question}' with citations: {cite_refs}"


@function_tool
def get_all_evidence(ctx: RunContextWrapper[ResearchContext]) -> str:
    """Get all accumulated research evidence for synthesis.

    Returns formatted evidence with findings and citation references.
    """
    if not ctx.context.state.evidence:
        return "No evidence has been recorded yet."

    return format_all_evidence(ctx.context)


@function_tool
def submit_outline(ctx: RunContextWrapper[ResearchContext], sections: list[SectionPlan]) -> str:
    """Submit a report outline defining the structure of the final report.

    The synthesis manager must call this tool to define the report structure.
    Each section needs a section_title, section_instructions describing what to cover,
    citation_ids as a list of [^N] citation IDs to include, and an order number.
    """
    known_ids = set(ctx.context.infra.citation_tracker.all_citation_ids())
    validated: list[SectionPlan] = []

    for i, s in enumerate(sections):
        valid_ids = [cid for cid in s.citation_ids if cid in known_ids]
        validated.append(
            SectionPlan(
                section_title=s.section_title,
                section_instructions=s.section_instructions,
                citation_ids=valid_ids,
                order=s.order if s.order != 0 else i,
            )
        )

    outline = ReportOutline(sections=validated)
    ctx.context.state.report_outline = outline

    summary = "\n".join(
        f"  {s.order}. {s.section_title} (citations: {s.citation_ids})"
        for s in validated
    )

    return f"Outline submitted with {len(validated)} sections:\n{summary}"


@function_tool
def get_citation_list(ctx: RunContextWrapper[ResearchContext]) -> str:
    """Get the formatted references section for the final report.

    Returns a Markdown-formatted references list with [N] citation numbers.
    """
    refs = ctx.context.infra.citation_tracker.format_references()
    if not refs:
        return "No citations recorded yet."
    return refs


# ---------------------------------------------------------------------------
# Formatting helpers (pure functions, no file I/O)
# ---------------------------------------------------------------------------


def format_all_evidence(context: ResearchContext) -> str:
    """Format all evidence into a readable string."""
    lines = [f"Research question: {context.state.research_question}\n"]
    lines.append(f"Total findings: {len(context.state.evidence)}\n")

    for finding in context.state.evidence:
        queries = ", ".join(f"'{r.query}'" for r in finding.relevance)
        lines.append(
            f"--- [^{finding.citation_id}] {finding.source_file} ---\n"
            f"Heading: {finding.heading}\n"
            f"Responsive queries: {queries}\n"
            f"Relevance scores: {json.dumps([r.model_dump() for r in finding.relevance], indent=2)}\n\n"
        )

    return "\n".join(lines)


def format_outline_md(sections: list[SectionPlan]) -> str:
    """Format an outline as Markdown for human review."""
    md_lines = [f"# Report Outline ({len(sections)} sections)", ""]
    for s in sorted(sections, key=lambda s: s.order):
        md_lines.append(f"## {s.order}. {s.section_title}")
        md_lines.append(f"**Instructions:** {s.section_instructions}")
        md_lines.append(f"**Citation IDs:** {s.citation_ids}")
        md_lines.append("")
    return "\n".join(md_lines)
