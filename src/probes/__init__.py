"""Measurement probes for research pipeline outputs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Awaitable, Callable

from models import Finding, ProbeResult, SectionResult

if TYPE_CHECKING:
    from research.context import ResearchContext

# ---------------------------------------------------------------------------
# Probe registry
# ---------------------------------------------------------------------------

ProbeFunc = Callable[
    [SectionResult, list[Finding], "ResearchContext"],
    Awaitable[ProbeResult],
]

_PROBE_REGISTRY: list[ProbeFunc] = []


def register_probe(func: ProbeFunc) -> ProbeFunc:
    """Register a probe function. Use as a decorator."""
    _PROBE_REGISTRY.append(func)
    return func


# Import probe modules to trigger registration (must come after register_probe)
from probes import faithfulness as _faithfulness  # noqa: F401, E402
from probes import completeness as _completeness  # noqa: F401, E402
from probes import sufficiency as _sufficiency  # noqa: F401, E402

# Log registered probes
print(f"Registered {len(_PROBE_REGISTRY)} probes: {[func.__name__ for func in _PROBE_REGISTRY]}")


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


async def run_probes(
    section_result: SectionResult,
    section_evidence: list[Finding],
    context: ResearchContext,
    on_probe_event: Callable[[str, dict], Awaitable[None]] | None = None,
) -> SectionResult:
    """Run all registered measurement probes on a section.

    Returns the section_result with probe_results populated.
    on_probe_event receives (event_type, data) for each individual probe.
    """
    from probes._extract import extract_citation_triples
    total_citations = len(extract_citation_triples(section_result.content))

    for probe_func in _PROBE_REGISTRY:
        probe_name = probe_func.__name__.replace("run_", "").replace("_probe", "")
        if on_probe_event:
            await on_probe_event("probe_metric_start", {"probe_name": probe_name, "section_title": section_result.section_title, "total_citations": total_citations})

        async def _progress(completed: int, total: int) -> None:
            if on_probe_event:
                await on_probe_event("probe_metric_progress", {"probe_name": probe_name, "section_title": section_result.section_title, "completed": completed, "total": total})

        result = await probe_func(section_result, section_evidence, context, on_progress=_progress if on_probe_event else None)
        section_result.probe_results[result.probe_name] = result.model_dump()
        if on_probe_event:
            await on_probe_event("probe_metric_complete", {"probe_name": probe_name, "section_title": section_result.section_title, "mean_score": result.mean_score})

    return section_result
