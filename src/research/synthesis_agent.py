"""Synthesis agents: outline planner and per-section writer."""

from agents import Agent, Model

from research.context import ResearchContext
from research.prompts import (
    SECTION_WRITER_INSTRUCTIONS,
    SYNTHESIS_AGENT_INSTRUCTIONS,
    SYNTHESIS_MANAGER_INSTRUCTIONS,
)
from research.tools import (
    get_all_evidence,
    get_citation_list,
    submit_outline,
)


def create_synthesis_agent(model: str | Model) -> Agent[ResearchContext]:
    """Create the legacy single-shot synthesis agent."""
    return Agent[ResearchContext](
        name="synthesis_agent",
        instructions=SYNTHESIS_AGENT_INSTRUCTIONS,
        model=model,
        tools=[get_all_evidence, get_citation_list],
    )


def create_synthesis_manager(model: str | Model) -> Agent[ResearchContext]:
    """Create the synthesis manager that plans the report outline."""
    return Agent[ResearchContext](
        name="synthesis_manager",
        instructions=SYNTHESIS_MANAGER_INSTRUCTIONS,
        model=model,
        tools=[get_all_evidence, get_citation_list, submit_outline],
    )


def create_section_writer(model: str | Model) -> Agent[ResearchContext]:
    """Create the section writer agent (no tools — everything via prompt)."""
    return Agent[ResearchContext](
        name="section_writer",
        instructions=SECTION_WRITER_INSTRUCTIONS,
        model=model,
        tools=[],
    )
