"""Manager agent: decomposes research question into sub-questions."""

from agents import Agent, Model

from research.context import ResearchContext
from research.prompts import MANAGER_INSTRUCTIONS
from research.tools import submit_plan


def create_manager_agent(model: str | Model) -> Agent[ResearchContext]:
    """Create the manager agent configured with the specified model.

    The manager decomposes the research question into sub-questions
    using the submit_plan tool.  The pipeline then drives the remaining
    workflow (search, synthesis) programmatically.
    """
    return Agent[ResearchContext](
        name="manager",
        instructions=MANAGER_INSTRUCTIONS,
        model=model,
        tools=[submit_plan],
    )
