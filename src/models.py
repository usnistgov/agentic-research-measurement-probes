"""Pydantic data models for documents, chunks, search results, and citations."""

from __future__ import annotations

from pydantic import BaseModel, Field, SerializeAsAny


class Document(BaseModel):
    """A parsed source file."""

    doc_id: str
    source_file: str
    content: str
    metadata: dict = Field(default_factory=dict)


class Chunk(BaseModel):
    """A chunk derived from a Document."""

    chunk_id: str
    doc_id: str
    source_file: str
    heading: str = ""
    heading_level: int = 0
    text: str
    char_len: int
    chunk_index: int
    page_estimate: int | None = None


class SearchResult(BaseModel):
    """A single search hit."""

    chunk: Chunk
    score: float
    rank: int


class QueryRelevance(BaseModel):
    """Why a specific chunk is relevant to a specific query."""

    query: str
    relevance_score: float = 0.0
    rationale: str = ""


class Finding(BaseModel):
    """A chunk found relevant to one or more research queries.

    One Finding per unique chunk (citation_id). The relevance list
    tracks which queries found it relevant and why.
    """

    citation_id: int
    chunk_id: str
    source_file: str
    heading: str = ""
    text: str = ""
    relevance: list[QueryRelevance] = Field(default_factory=list)


class ChunkRelevanceJudgment(BaseModel):
    """Relevance judgment for a single (chunk, question) pair from exhaustive scanning."""

    chunk_id: str
    question_index: int
    is_relevant: bool
    relevance_score: float  # 0.0–1.0
    rationale: str


class ScanResult(BaseModel):
    """Summary returned by exhaustive_scan for pipeline inspection."""

    questions: list[str]
    total_chunks: int
    total_judgments: int
    relevant_count: int
    evidence_count: int


class SectionPlan(BaseModel):
    """Plan for a single report section."""

    section_title: str
    section_instructions: str  # What to cover
    citation_ids: list[int] = Field(default_factory=list)  # 1-based citation IDs to include
    order: int = 0  # Position in final report


class ReportOutline(BaseModel):
    """Full outline produced by the synthesis manager."""

    sections: list[SectionPlan] = Field(default_factory=list)


class BaseVerdict(BaseModel):
    """Base class for all probe verdict types.

    Every verdict has a score (0.0–1.0), a categorical verdict string,
    and a rationale explaining the judgment.
    """

    verdict: str
    score: float
    rationale: str


class CitationVerdict(BaseVerdict):
    """Verdict for a single citation checked against its source."""

    citation_id: int
    citing_sentence: str  # Clean sentence, citation markers removed
    source_chunk_text: str
    source_file: str
    source_heading: str
    omissions: list[str] = Field(default_factory=list)


class SectionVerdict(BaseVerdict):
    """Verdict scoped to an entire section (e.g., coverage, argument strength)."""

    details: dict = Field(default_factory=dict)


class ProbeResult(BaseModel):
    """Aggregated result of an evaluation probe on a section."""

    probe_name: str
    section_title: str
    verdicts: list[SerializeAsAny[BaseVerdict]] = Field(default_factory=list)
    mean_score: float = 0.0
    summary: dict = Field(default_factory=dict)


class SectionResult(BaseModel):
    """Output from writing a single section."""

    section_title: str
    content: str  # Markdown content
    citations_used: list[int] = Field(default_factory=list)  # citation_ids referenced
    order: int = 0
    probe_results: dict = Field(default_factory=dict)  # Hook for evaluation probes
