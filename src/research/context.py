"""Shared research state threaded through all agent tool calls."""

from __future__ import annotations

from dataclasses import dataclass

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from citations.tracker import CitationTracker
from models import (
    ChunkRelevanceJudgment,
    Finding,
    ReportOutline,
    SectionResult,
)
from store.document_store import DocumentStore


@dataclass
class ResearchInfrastructure:
    """Immutable infrastructure injected once at startup."""

    document_store: DocumentStore
    citation_tracker: CitationTracker
    openai_client: AsyncOpenAI
    model_name: str = ""


class ResearchState(BaseModel):
    """Mutable state accumulated during a research run."""

    model_config = ConfigDict(validate_assignment=True)

    research_question: str = ""
    sub_questions: list[str] = Field(default_factory=list)
    evidence: list[Finding] = Field(default_factory=list)
    chunk_relevance_judgments: list[ChunkRelevanceJudgment] = Field(default_factory=list)
    report_outline: ReportOutline | None = None
    section_results: list[SectionResult] = Field(default_factory=list)


@dataclass
class ResearchContext:
    """Container passed via RunContextWrapper[ResearchContext].

    Separates immutable infrastructure from mutable accumulated state.
    """

    infra: ResearchInfrastructure
    state: ResearchState
