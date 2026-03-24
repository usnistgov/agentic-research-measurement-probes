"""Programmatic research pipeline.

Drives the multi-agent workflow in code rather than relying on
model-initiated handoffs, which local models handle unreliably.
Each agent runs independently with only its own tools, avoiding
cross-agent tool confusion.

Flow:
  1. Manager agent decomposes the question into sub-questions (submit_plan tool).
  2. Exhaustive scanner evaluates every corpus chunk against all questions.
  3a. Synthesis manager plans the report outline (submit_outline tool).
  3b. Section writer writes each section with its assigned evidence.
  3c. Assemble final report from sections + references.
"""

from __future__ import annotations

import json
import re

from agents import Model, Runner
from pydantic import BaseModel, ValidationError, model_validator

from research.context import ResearchContext
from research.exhaustive_scanner import exhaustive_scan
from research.manager import create_manager_agent
from research.sanitizing_model import SanitizingModel
from research.synthesis_agent import (
    create_section_writer,
    create_synthesis_manager,
)
from research.tools import format_all_evidence, format_outline_md
from models import ReportOutline, SectionPlan, SectionResult
from probes import run_probes


# ---------------------------------------------------------------------------
# Pydantic models for fallback parsing of LLM text output
# ---------------------------------------------------------------------------


class _SubQuestionsPayload(BaseModel):
    """Parses sub-questions from JSON the manager may emit as text."""

    questions: list[str]

    @model_validator(mode="before")
    @classmethod
    def _extract(cls, data):
        if isinstance(data, list):
            return {"questions": data}
        if isinstance(data, dict):
            for key in ("sub_questions", "sub-questions", "questions"):
                if key in data and isinstance(data[key], list):
                    return {"questions": data[key]}
        raise ValueError("No sub-questions list found")


class _RawSection(BaseModel):
    """Lenient section schema that normalizes common key variants."""

    section_title: str = ""
    section_instructions: str = ""
    citation_ids: list[int]
    order: int = 0

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data):
        if not isinstance(data, dict):
            return data
        # Accept "title" as alias for "section_title"
        if "title" in data and "section_title" not in data:
            data["section_title"] = data.pop("title")
        # Accept "instructions" as alias for "section_instructions"
        if "instructions" in data and "section_instructions" not in data:
            data["section_instructions"] = data.pop("instructions")
        return data


class _OutlinePayload(BaseModel):
    """Parses an outline from JSON the synthesis manager may emit as text."""

    sections: list[_RawSection]

    @model_validator(mode="before")
    @classmethod
    def _extract(cls, data):
        if isinstance(data, list):
            return {"sections": data}
        if isinstance(data, dict):
            for key in ("sections", "outline"):
                if key in data and isinstance(data[key], list):
                    return {"sections": data[key]}
        raise ValueError("No sections list found")


def build_model(context: ResearchContext) -> SanitizingModel:
    """Build a SanitizingModel wrapping OpenAIChatCompletionsModel.

    Reuses the shared AsyncOpenAI client and model_name from context.infra.
    """
    from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel

    inner = OpenAIChatCompletionsModel(
        model=context.infra.model_name, openai_client=context.infra.openai_client
    )
    return SanitizingModel(inner)


async def run_research_pipeline(
    question: str,
    context: ResearchContext,
    *,
    relevance_threshold: float = 0.5,
    batch_size: int = 4,
    prefilter: bool = False,
    max_synthesis_turns: int = 4,
    all_evidence_per_section: bool = False,
    verbose: bool = False,
) -> str:
    """Run the full research pipeline and return the final Markdown report."""

    model = build_model(context)

    # --- Step 1: Decompose question into sub-questions ---
    if verbose:
        print("[pipeline] Step 1: Decomposing research question...")

    manager = create_manager_agent(model)
    result = await Runner.run(
        manager,
        input=question,
        context=context,
        max_turns=5,
    )

    sub_questions = context.state.sub_questions
    if not sub_questions:
        # Fallback: parse sub-questions from text output
        sub_questions = _parse_sub_questions(result.final_output)
        context.state.sub_questions = sub_questions
        print(
            f"[pipeline] WARNING: Manager did not call submit_plan. "
            f"Parsed {len(sub_questions)} sub-questions from text output."
        )

    if not sub_questions:
        # Last resort: use the original question as the sole sub-question
        sub_questions = [question]
        context.state.sub_questions = sub_questions
        print(
            "[pipeline] WARNING: No sub-questions parsed. "
            "Using the original question as the sole sub-question."
        )

    if verbose:
        print(f"[pipeline] Sub-questions ({len(sub_questions)}):")
        for i, sq in enumerate(sub_questions, 1):
            print(f"  {i}. {sq}")

    # --- Step 2: Exhaustive relevance scan ---
    if verbose:
        print("\n[pipeline] Step 2: Exhaustive corpus scan...")

    scan_result = await exhaustive_scan(
        context,
        question,
        relevance_threshold=relevance_threshold,
        batch_size=batch_size,
        prefilter=prefilter,
        verbose=verbose,
    )

    if verbose:
        print(
            f"\n[pipeline] Scan complete. "
            f"{scan_result.relevant_count}/{scan_result.total_judgments} pairs relevant, "
            f"{len(context.state.evidence)} evidence items."
        )

    # --- Debug dump: full context snapshot for inspection ---
    _dump_context(context, "context_state.json")

    # --- Step 3a: Plan the report outline ---
    if verbose:
        print("\n[pipeline] Step 3a: Planning report outline...")

    synthesis_manager = create_synthesis_manager(model)

    sub_q_list = "\n".join(f"  {i}. {sq}" for i, sq in enumerate(context.state.sub_questions, 1))
    outline_prompt = (
        f"Research question: {question}\n\n"
        f"Sub-questions investigated:\n{sub_q_list}\n\n"
        f"Use get_all_evidence to see all the gathered research evidence, "
        f"then use get_citation_list to see the references. "
        f"Plan a report outline with 3-7 sections that covers the research question "
        f"and all sub-questions, then call submit_outline."
    )

    result = await Runner.run(
        synthesis_manager,
        input=outline_prompt,
        context=context,
        max_turns=max_synthesis_turns,
    )

    outline = context.state.report_outline
    if outline is None or not outline.sections:
        raise RuntimeError("Agent failed to create report outline")

    # Write debug artifacts to index dir
    index_dir = context.infra.document_store.index_dir
    (index_dir / "all_evidence.md").write_text(
        format_all_evidence(context), encoding="utf-8"
    )
    refs = context.infra.citation_tracker.format_references()
    if refs:
        (index_dir / "all_references.md").write_text(refs, encoding="utf-8")
    (index_dir / "report_outline.md").write_text(
        format_outline_md(outline.sections), encoding="utf-8"
    )

    if verbose:
        print(f"[pipeline] Report outline ({len(outline.sections)} sections):")
        for s in outline.sections:
            print(f"  {s.order}. {s.section_title} (citations: {s.citation_ids})")

    # --- Step 3b: Write each section ---
    if verbose:
        print("\n[pipeline] Step 3b: Writing sections...")

    section_writer = create_section_writer(model)
    section_results: list[SectionResult] = []

    for section_plan in sorted(outline.sections, key=lambda s: s.order):
        if verbose:
            print(f"  Writing: {section_plan.section_title}")

        # Filter findings for this section
        if all_evidence_per_section:
            section_findings = context.state.evidence
        else:
            section_findings = _filter_evidence_for_section(context, section_plan)

        # Build self-contained prompt with findings as JSON
        section_prompt = _build_section_prompt(
            question, sub_q_list, section_plan, section_findings,
            prior_sections=section_results,
        )

        # Write section prompt to index dir for human review
        prompt_path = context.infra.document_store.index_dir / f'section_prompt_{section_plan.order}.md'
        with open(prompt_path, 'w') as fh:
            fh.write(section_prompt)

        result = await Runner.run(
            section_writer,
            input=section_prompt,
            context=context,
            max_turns=3,
        )

        section_result = SectionResult(
            section_title=section_plan.section_title,
            content=result.final_output,
            citations_used=_extract_citation_ids(result.final_output),
            order=section_plan.order,
        )

        # ============ MEASUREMENT PROBE HOOK ============
        section_result = await run_probes(
            section_result, section_findings, context
        )
        if verbose:
            print(f"    Probe results for section '{section_result.section_title}':")
            for probe_name, probe_result in section_result.probe_results.items():
                checked = probe_result.get("summary", {}).get("num_citations_checked", 0)
                mean_score = probe_result.get("mean_score", 0.0)
                print(f"      Probe: {checked} citations checked. mean {probe_name}={mean_score:.2f}")
        # ================================================

        section_results.append(section_result)

    context.state.section_results = section_results

    # --- Step 3c: Assemble final report ---
    if verbose:
        print("\n[pipeline] Step 3c: Assembling final report...")

    report = _assemble_report(context, section_results)

    _dump_context(context, "context_state.json")

    return report


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _filter_evidence_for_section(context, section_plan):
    """Return findings whose citation_id is in the section's citation_ids."""
    target_ids = set(section_plan.citation_ids)
    return [f for f in context.state.evidence if f.citation_id in target_ids]


def _build_section_prompt(question, sub_q_list, section_plan, section_findings,
                          *, prior_sections: list[SectionResult] | None = None):
    """Build a self-contained prompt for the section writer."""
    lines = [
        f"Research question: {question}\n",
        f"  Research sub-questions: \n{sub_q_list}\n\n",
    ]

    # Include previously written sections so the writer can build on them
    if prior_sections:
        lines.append("# Previously written sections (for context — do NOT repeat this content):")
        lines.append("")
        for ps in sorted(prior_sections, key=lambda s: s.order):
            lines.append(ps.content)
            lines.append("")
        lines.append("---")
        lines.append("")

    lines.extend([
        f"# Section to write: {section_plan.section_title}",
        f"Instructions: {section_plan.section_instructions}",
        "",
        "# Evidence for this section:",
        "",
    ])

    if not section_findings:
        lines.append("(No specific evidence assigned — write based on general context.)")
    else:
        lines.append("```json")
        lines.append(json.dumps([f.model_dump() for f in section_findings], indent=2))
        lines.append("```")

    lines.append("")
    lines.append("Write this section now. Use [^citation_id] citations for every factual claim supported by the evidence.")  # Use [^n]

    return "\n".join(lines)


def _extract_citation_ids(text):
    """Extract all [^N] citation IDs from text."""
    return sorted(set(int(m) for m in re.findall(r"\[\^(\d+)\]", text)))


def _parse_outline(text, context):
    """Try to parse an outline from text when the LLM didn't call submit_outline."""
    all_citation_ids = context.infra.citation_tracker.all_citation_ids()

    # Try JSON parsing
    outline = _try_parse_outline_json(text, all_citation_ids)
    if outline:
        return outline

    # Try parsing numbered/headed sections from text
    sections = []
    # Match patterns like "1. Title" or "## Title" or "**Title**"
    section_patterns = [
        re.compile(r"^\s*(\d+)\.\s*\*?\*?(.+?)\*?\*?\s*$", re.MULTILINE),
        re.compile(r"^\s*#{1,3}\s+(.+?)\s*$", re.MULTILINE),
    ]

    for pattern in section_patterns:
        matches = list(pattern.finditer(text))
        if len(matches) >= 2:
            for i, m in enumerate(matches):
                title = m.group(m.lastindex).strip().strip("*")
                sections.append(
                    SectionPlan(
                        section_title=title,
                        section_instructions="",
                        citation_ids=all_citation_ids,  # assign all citations as fallback
                        order=i,
                    )
                )
            break

    if sections:
        return ReportOutline(sections=sections)

    return None


def _try_parse_outline_json(text, all_citation_ids):
    """Try to extract outline from JSON in text."""
    # Try code blocks first
    for m in re.finditer(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL):
        result = _parse_outline_json_str(m.group(1), all_citation_ids)
        if result:
            return result

    # Try whole text
    return _parse_outline_json_str(text, all_citation_ids)


def _parse_outline_json_str(text, all_citation_ids):
    """Parse a JSON string into a ReportOutline using Pydantic validation."""
    try:
        payload = _OutlinePayload.model_validate_json(text.strip())
    except (ValidationError, ValueError):
        return None

    known_ids = set(all_citation_ids)
    sections = []
    for i, raw in enumerate(payload.sections):
        valid_ids = [cid for cid in raw.citation_ids if cid in known_ids]
        sections.append(
            SectionPlan(
                section_title=raw.section_title or f"Section {i + 1}",
                section_instructions=raw.section_instructions,
                citation_ids=valid_ids,
                order=raw.order if raw.order != 0 else i,
            )
        )

    if sections:
        return ReportOutline(sections=sections)
    return None


def _assemble_report(context, section_results):
    """Concatenate sections in order and append references."""
    parts = []
    for sr in sorted(section_results, key=lambda s: s.order):
        parts.append(sr.content)

    # Add references section
    refs = context.infra.citation_tracker.format_references()
    if refs:
        parts.append(refs)

    return "\n\n".join(parts)


def _dump_context(context: ResearchContext, filename: str) -> None:
    """Write a full JSON snapshot of the research context to the corpus index dir."""
    index_dir = context.infra.document_store.index_dir
    out_path = index_dir / filename

    payload = context.state.model_dump()
    # Add citation tracker data (lives on infra, not state)
    payload["citation_ids"] = context.infra.citation_tracker.all_citation_ids()
    payload["citation_usage_counts"] = context.infra.citation_tracker.all_usage_counts()

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"[pipeline] Context snapshot written to {out_path}")


def _parse_sub_questions(text: str) -> list[str]:
    """Best-effort extraction of sub-questions from manager text output.

    Handles several formats local models produce:
      - Raw JSON with a "sub_questions" key
      - JSON embedded in markdown code blocks
      - Numbered/bulleted lists
      - Markdown table rows
    """
    # --- Try JSON parsing first (model may output the tool call as text) ---
    questions = _try_parse_json(text)
    if questions:
        return questions

    # --- Try numbered list patterns: "1. ...", "1) ...", "- ..." ---
    questions = []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^(?:\d+[\.\)]\s*|[-*]\s+)(.*\?)\s*$", line)
        if m:
            questions.append(m.group(1).strip())
    if questions:
        return questions

    # --- Try bold patterns from markdown tables ---
    for m in re.finditer(r"\*\*[^*]+\*\*[:\s]*([^|]+\?)", text):
        questions.append(m.group(1).strip())

    return questions


def _try_parse_json(text: str) -> list[str]:
    """Try to extract sub_questions from JSON in the text."""
    # Try the whole text as JSON
    parsed = _safe_json(text)
    if parsed:
        return parsed

    # Try extracting JSON from markdown code blocks
    for m in re.finditer(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL):
        parsed = _safe_json(m.group(1))
        if parsed:
            return parsed

    # Try extracting any JSON object in the text
    for m in re.finditer(r"\{[^{}]*\"sub_questions\"[^{}]*\[.*?\][^{}]*\}", text, re.DOTALL):
        parsed = _safe_json(m.group(0))
        if parsed:
            return parsed

    return []


def _safe_json(text: str) -> list[str]:
    """Parse text as JSON and extract a list of sub-question strings."""
    try:
        payload = _SubQuestionsPayload.model_validate_json(text.strip())
        return payload.questions
    except (ValidationError, ValueError):
        return []
