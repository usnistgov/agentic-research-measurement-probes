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
) -> SectionResult:
    """Run all registered measurement probes on a section.

    Returns the section_result with probe_results populated.
    """
    for probe_func in _PROBE_REGISTRY:
        result = await probe_func(section_result, section_evidence, context)
        section_result.probe_results[result.probe_name] = result.model_dump()

    return section_result
