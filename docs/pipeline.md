# Pipeline & Module Structure Reference

Detailed reference for the research pipeline flow, module layout, and implementation details.

## Pipeline Flow

`research/pipeline.py::run_research_pipeline()`:
1. Create Manager agent, run to get sub-questions (or parse from text output as fallback)
2. Run exhaustive scanner across all chunks -- produces one `Finding` per relevant chunk, with `QueryRelevance` entries for each responsive sub-question
3a. Create Synthesis Manager, run to get report outline (assigns citation IDs to sections)
3b. For each section in order: filter findings by citation_id, serialize as JSON, include prior written sections; run Section Writer; collect `SectionResult`
3c. Assemble final report from sections + references
4. Dump context snapshot to `ldr_index/context_state.json` for debugging

### Pipeline Parameters

- `relevance_threshold` (default `0.5`) -- Minimum relevance score for a chunk to be considered relevant to a question.
- `batch_size` (default `32`) -- Concurrency limit for exhaustive scanner LLM calls.
- `all_evidence_per_section` (default `False`) -- When `True`, gives every section writer all evidence instead of just its assigned citations. Useful for comparing filtered vs. full-evidence section quality.
- `prefilter` (default `False`) -- Pre-filter chunks by BM25 score before LLM evaluation (faster for debugging).
- `max_synthesis_turns` (default `10`) -- Max agent turns for the synthesis manager.

## Agent Tools

Six tools available to agents (`research/tools.py`):
- `submit_plan(sub_questions)` -- Submit research decomposition (manager only)
- `get_chunk_text(chunk_id)` -- Retrieve full chunk content
- `record_evidence(sub_question, findings, chunk_ids, relevance_score)` -- Store evidence with citations
- `get_all_evidence()` -- Retrieve all accumulated evidence (synthesis manager)
- `get_citation_list()` -- Get formatted references section (synthesis manager)
- `submit_outline(sections)` -- Submit report outline with `SectionPlan` objects (synthesis manager only)

## Module Structure

### Core Modules

- `config.py` -- Configuration loaded from environment variables
- `models.py` -- Pydantic data models (see @docs/models.md)

### Ingestion Pipeline (`ingest/`)

- `parsers.py` -- Parse PDF (via docling) and Markdown files into `Document` objects
- `chunker.py` -- Heading-aware chunking with sliding window for large sections
- `pipeline.py` -- Orchestrates parsing, chunking, and persistence

Chunking strategy:
1. Split by Markdown headings (`# ... ######`)
2. Merge consecutive sections smaller than `ODR_CHUNK_MIN_CHARS` (default: 2000)
3. Apply sliding window with `ODR_CHUNK_OVERLAP` (default: 200) to sections exceeding `ODR_CHUNK_MAX_CHARS` (default: 3000)

### Document Store (`store/`)

- `document_store.py` -- Manages chunk persistence (`chunks.jsonl`), loading, and querying

### Citations (`citations/`)

- `tracker.py` -- `CitationTracker` assigns sequential 1-based citation IDs, deduplicates by chunk_id, returns `int` from `add_citation()`. Uses a lightweight internal `_CitationRecord` dataclass for reference formatting. Maintains usage counts.

## Local Model Compatibility

- Uses **Chat Completions API** (`set_default_openai_api("chat_completions")`) not Responses API
- `SanitizingModel` wrapper (`research/sanitizing_model.py`) strips `<|...|>` artifacts from tool names, drops unknown tool calls, and wraps bare `ResponseOutputText` in `ResponseOutputMessage` to avoid SDK warnings
- Exhaustive scanner batches chunk evaluations to minimize LLM calls
- Pipeline has fallback parsing for sub-questions when manager doesn't call `submit_plan`
- Pipeline has fallback parsing for outlines when synthesis manager doesn't call `submit_outline`

## Persistence

All artifacts stored in `<corpus_dir>/ldr_index/`:
- `chunks.jsonl` -- One JSON-serialized Chunk per line
- `metadata.json` -- Corpus metadata
- `context_state.json` -- Debug snapshot of research run state (includes evidence, outline, section results)
- `all_evidence.md` -- Formatted evidence dump
- `all_references.md` -- Formatted citation list
- `report_outline.md` -- Report outline with section plans
- `section_prompt_{order}.md` -- Per-section writer prompts for human review
