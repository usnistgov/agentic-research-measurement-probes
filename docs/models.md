# Data Models Reference

Detailed reference for Pydantic data models in `models.py` and `research/context.py`.

## Core Domain Models

### Document & Chunk

- `Document` -- A parsed source file: `doc_id`, `source_file`, `content`, `metadata`.
- `Chunk` -- A chunk derived from a Document: `chunk_id`, `doc_id`, `source_file`, `heading`, `heading_level`, `text`, `char_len`, `chunk_index`, `page_estimate`.

### Evidence Models

- `QueryRelevance` -- Why a chunk is relevant to a specific query: `query`, `relevance_score`, `rationale`.
- `Finding` -- One per unique corpus chunk. Contains `citation_id`, `chunk_id`, `source_file`, `heading`, `text`, and `relevance: list[QueryRelevance]` tracking all queries that found it relevant and why. This is the unified evidence unit -- there are no separate Citation or ResearchEvidence models.
- `ChunkRelevanceJudgment` -- Relevance judgment for a single (chunk, question) pair from exhaustive scanning: `chunk_id`, `question_index`, `is_relevant`, `relevance_score`, `rationale`.
- `ScanResult` -- Summary returned by `exhaustive_scan`: `questions`, `total_chunks`, `total_judgments`, `relevant_count`, `evidence_count`.

### Report Models

- `SectionPlan` -- Defines a report section: `section_title`, `section_instructions`, `citation_ids` (1-based `[^N]` IDs), `order`.
- `ReportOutline` -- List of `SectionPlan` objects produced by the synthesis manager.
- `SectionResult` -- Output from writing a section: `section_title`, `content`, `citations_used`, `order`, `probe_results` dict.

### Citation ID Conventions

Citation IDs are 1-based integers assigned sequentially by `CitationTracker`. The `citation_ids` field on `SectionPlan` uses these same IDs -- there are no 0-based evidence indices anywhere.

`context.state.evidence` is `list[Finding]` -- one entry per unique chunk, deduplicated at scan time. Each Finding's `relevance` list accumulates all responsive queries. Section writer prompts serialize findings as JSON blocks for clarity.

## Verdict Models (Probe Infrastructure)

- `BaseVerdict` -- Base class with `verdict: str`, `score: float`, `rationale: str`. All verdict types inherit from this.
- `CitationVerdict(BaseVerdict)` -- Adds `citation_id`, `citing_sentence`, `source_chunk_text`, `source_file`, `source_heading`. Used by per-citation probes.
- `SectionVerdict(BaseVerdict)` -- Adds `details: dict`. Used by per-section probes.
- `ProbeResult` -- Aggregated result: `probe_name`, `section_title`, `verdicts: list[BaseVerdict]`, `mean_score: float`, `summary: dict` (probe-specific aggregate metrics).

## Shared Context (`research/context.py`)

All agents share a `ResearchContext` object containing:
- `ResearchInfrastructure` (immutable dataclass) -- `document_store`, `citation_tracker`, `openai_client`, `model_name`.
- `ResearchState` (mutable Pydantic `BaseModel` with `validate_assignment=True`) -- `research_question`, `sub_questions`, `evidence` (`list[Finding]`), `chunk_relevance_judgments`, `report_outline`, `section_results`.

Context is threaded through tool calls via the SDK's `RunContextWrapper[ResearchContext]`.
