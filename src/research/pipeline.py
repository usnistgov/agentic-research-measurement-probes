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
import time
from collections.abc import Awaitable, Callable
from typing import Any

from agents import Runner, ModelSettings, RunConfig
from openai.types.shared import Reasoning
from openai import AsyncOpenAI

from config import Config
from research.context import ResearchContext
from research.exhaustive_scanner import exhaustive_scan
from research.manager import create_manager_agent
from research.sanitizing_model import SanitizingModel
from research.synthesis_agent import (
    create_section_writer,
    create_synthesis_manager,
)
from research.tools import format_all_evidence, format_outline_md
from models import SectionResult
from probes import run_probes


def _validate_openai_config(client: AsyncOpenAI) -> None:
    """Validate that OpenAI API is properly configured.

    Raises:
        RuntimeError: If API key is missing.
    """
    if not client.api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. "
            "Copy .env.example to .env and configure your API key."
        )


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
    max_synthesis_turns: int = 10,
    all_evidence_per_section: bool = False,
    verbose: bool = False,
    on_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> str:
    """Run the full research pipeline and return the final Markdown report.

    Args:
        question: The research question.
        context: The research context.
        relevance_threshold: Minimum relevance score for a chunk to be considered relevant.
        batch_size: Concurrency limit for exhaustive scanner LLM calls.
        prefilter: Whether to use BM25 prefilter to reduce chunks before LLM evaluation.
            Keeps chunks with BM25 score >= corpus mean score (adaptive threshold).
        max_synthesis_turns: Max agent turns for the synthesis manager.
        all_evidence_per_section: When True, gives every section writer all evidence.
        verbose: Whether to print progress messages.
        on_event: Optional async callback for pipeline events.
    """

    async def emit(event_type: str, stage: str, data: dict[str, Any] | None = None) -> None:
        if on_event is not None:
            await on_event({"type": event_type, "stage": stage, "timestamp": time.time(), "data": data or {}})

    model = build_model(context)

    # Validate that OpenAI API is properly configured before proceeding
    _validate_openai_config(context.infra.openai_client)

    # --- Step 1: Decompose question into sub-questions ---
    await emit("stage_start", "manager", {"question": question})
    if verbose:
        print("[pipeline] Step 1: Decomposing research question...")

    manager = create_manager_agent(model)
    result = await Runner.run(
        manager,
        input=question,
        context=context,
        max_turns=5,
        run_config=RunConfig(model_settings=ModelSettings(temperature=0.2, reasoning=Reasoning(effort=Config().synthesis_reasoning_effort))),
    )

    sub_questions = context.state.sub_questions
    if not sub_questions:
        raise RuntimeError("Manager agent did not call submit_plan")

    await emit("stage_complete", "manager", {"sub_questions": sub_questions})

    if verbose:
        print(f"[pipeline] Sub-questions ({len(sub_questions)}):")
        for i, sq in enumerate(sub_questions, 1):
            print(f"  {i}. {sq}")

    # --- Step 2: Exhaustive relevance scan ---
    await emit("stage_start", "scanner", {"total_chunks": len(context.infra.document_store.all_chunks()), "num_questions": len(sub_questions)})
    if verbose:
        print("\n[pipeline] Step 2: Exhaustive corpus scan...")

    async def _scanner_progress(completed: int, total: int, relevant: int) -> None:
        await emit("scanner_progress", "scanner", {"completed": completed, "total": total, "relevant_so_far": relevant})

    async def _scanner_prefilter(kept: int, total: int) -> None:
        await emit("scanner_prefilter", "scanner", {"kept": kept, "total": total})

    scan_result = await exhaustive_scan(
        context,
        question,
        relevance_threshold=relevance_threshold,
        batch_size=batch_size,
        prefilter=prefilter,
        verbose=verbose,
        on_progress=_scanner_progress if on_event else None,
        on_prefilter=_scanner_prefilter if on_event else None,
    )

    await emit("stage_complete", "scanner", {"total_chunks": scan_result.total_chunks, "relevant_count": scan_result.relevant_count, "evidence_count": scan_result.evidence_count})

    if verbose:
        print(
            f"\n[pipeline] Scan complete. "
            f"{scan_result.relevant_count}/{scan_result.total_judgments} pairs relevant, "
            f"{len(context.state.evidence)} evidence items."
        )

    # --- Debug dump: full context snapshot for inspection ---
    _dump_context(context, "context_state.json")

    # --- Step 3a: Plan the report outline ---
    await emit("stage_start", "synthesis_manager")
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
        run_config=RunConfig(model_settings=ModelSettings(temperature=0.2, reasoning=Reasoning(effort=Config().synthesis_reasoning_effort))),
    )

    outline = context.state.report_outline
    if outline is None or not outline.sections:
        raise RuntimeError("Synthesis manager did not call submit_outline")

    sorted_sections = sorted(outline.sections, key=lambda s: s.order)
    await emit("stage_complete", "synthesis_manager", {"num_sections": len(sorted_sections), "sections": [{"title": s.section_title, "order": s.order} for s in sorted_sections]})

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
        await emit("section_start", "section_writer", {"section_title": section_plan.section_title, "order": section_plan.order, "total_sections": len(outline.sections)})
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
            run_config=RunConfig(model_settings=ModelSettings(temperature=0.2, reasoning=Reasoning(effort=Config().synthesis_reasoning_effort))),
        )

        section_result = SectionResult(
            section_title=section_plan.section_title,
            content=result.final_output,
            citations_used=_extract_citation_ids(result.final_output),
            order=section_plan.order,
        )
        await emit("section_complete", "section_writer", {"section_title": section_plan.section_title, "order": section_plan.order, "citations_used": section_result.citations_used})
        if verbose:
            print(f"    Section '{section_plan.section_title}' written. Starting evaluation probes...")

        # ============ EVALUATION PROBE HOOK ============
        await emit("probe_start", "probes", {"section_title": section_plan.section_title, "order": section_plan.order})

        async def _probe_event(event_type: str, data: dict) -> None:
            await emit(event_type, "probes", data)

        section_result = await run_probes(
            section_result, section_findings, context,
            on_probe_event=_probe_event if on_event else None,
        )
        if verbose:
            print(f"    Probe results for section '{section_result.section_title}':")
            for probe_name, probe_result in section_result.probe_results.items():
                checked = probe_result.get("summary", {}).get("num_citations_checked", 0)
                mean_score = probe_result.get("mean_score", 0.0)
                print(f"      Probe: {checked} citations checked. mean {probe_name}={mean_score:.2f}")
        await emit("probe_complete", "probes", {"section_title": section_plan.section_title, "results": section_result.probe_results})
        # ================================================

        section_results.append(section_result)

    context.state.section_results = section_results

    # --- Step 3c: Assemble final report ---
    await emit("stage_start", "assembly")
    if verbose:
        print("\n[pipeline] Step 3c: Assembling final report...")

    report = _assemble_report(context, section_results)
    await emit("stage_complete", "assembly", {"report_length": len(report)})

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


