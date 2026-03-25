# Open Deep Research

An **agentic AI measurement tool** for deep research over **local corpora of PDF and Markdown documents**. Given a research question, it orchestrates a programmatic AI pipeline to exhaustively evaluate, synthesize, and verify information from your documents, producing a **Markdown report with inline footnote citations** -- then automatically measures the quality of every citation using **LM-judge measurement probes**.

The probes are a first-class feature, not an afterthought. After each report section is written, three mutually exclusive probe evaluators run automatically, scoring every citation along distinct quality dimensions: **faithfulness** (does the source support the claim?), **completeness** (is the source's full message represented without cherry-picking?), and **sufficiency** (does the source carry the evidentiary burden the claim requires, or does the author overreach?). Probe results are stored alongside the report as a structured audit trail, enabling quantitative measurement of AI-generated research quality.

This makes Open Deep Research useful not just as a research assistant, but as a **platform for AI measurement science** -- studying how well LLMs synthesize, cite, and represent evidence from a grounded document corpus.

Built on the [OpenAI Agents SDK](https://github.com/openai/openai-agents-python), it works with any OpenAI-compatible API endpoint (OpenAI, Ollama, vLLM, or other self-hosted model servers).

## How It Works

Open Deep Research follows a two-step workflow:

1. **Ingest** -- Parse your documents (PDF/Markdown), split them into searchable chunks, and persist them.
2. **Research** -- Ask a question. A programmatic pipeline decomposes it into sub-questions, exhaustively evaluates every corpus chunk, synthesizes a cited report, and scores each section with measurement probes.

### Pipeline Architecture

The system uses a **programmatic pipeline** (not LLM-driven handoffs) for reliability with local models. Each stage runs independently:

```
+------------------+
|  Manager Agent   |  Decomposes question -> sub-questions (submit_plan tool)
+--------+---------+
         |
+--------v---------+
| Exhaustive       |  Evaluates EVERY corpus chunk against all sub-questions
| Scanner          |  via batched LLM calls; produces Finding objects with
|                  |  relevance scores and rationales
+--------+---------+
         |
+--------v---------+
| Synthesis        |  Plans report outline, assigns citation IDs to sections
| Manager          |  (submit_outline tool)
+--------+---------+
         |
+--------v---------+
| Section Writers  |  One writer per section; receives its assigned evidence
|                  |  as JSON; writes Markdown with [^N] footnote citations
+--------+---------+
         |
+--------v---------+
| Measurement      |  LM-judge probes run after each section:
| Probes           |  faithfulness, completeness, sufficiency
+------------------+
```

- **Manager** -- Decomposes the research question into focused sub-questions via a single `submit_plan` tool call.
- **Exhaustive Scanner** -- Evaluates every chunk in the corpus against all sub-questions using batched concurrent LLM calls. Guarantees complete coverage: no chunk is skipped. Produces one `Finding` per relevant chunk with structured relevance judgments. Optionally pre-filters chunks via BM25 scoring to speed up debugging runs.
- **Synthesis Manager** -- Reviews all accumulated evidence and citations, then plans the report outline (3-7 sections) via `submit_outline`, assigning specific citation IDs to each section.
- **Section Writers** -- Each section is written independently with its assigned evidence serialized as JSON. Writers use `[^N]` footnote citations and receive prior sections for context continuity.
- **Measurement Probes** -- LM-judge evaluators run automatically after each section is written, scoring citation quality along three dimensions: faithfulness (does the source support the claim?), completeness (is the source's full message represented?), and sufficiency (does the source carry the burden of proof the claim requires?). Results are stored on each section and in the audit trail.

All agents share a `ResearchContext` containing immutable `ResearchInfrastructure` (document store, citation tracker, OpenAI client) and mutable `ResearchState` (sub-questions, evidence, outline, section results). Context is threaded through all tool calls via the SDK's `RunContextWrapper`.

## Installation

### Prerequisites

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

### Install from source

```shell
# Clone the repository
git clone https://github.com/usnistgov/open-deep-research.git
cd open-deep-research

# Create and activate virtual environment
uv venv --python=3.12
source .venv/bin/activate

# Install dependencies
uv pip install -r requirements.txt

# Optional: PDF support (adds docling for PDF-to-Markdown conversion)
uv pip install docling
```

## Configuration

Configuration is loaded from environment variables (with a `.env` file). Copy the example and edit:

```shell
cp .env.example .env
```

### Environment Variables

OpenAI credentials use the standard `OPENAI_API_KEY` and `OPENAI_BASE_URL` variables (shared with the agents SDK). Other settings use the `ODR_` prefix.

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | _(none)_ | API key for the OpenAI-compatible endpoint |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Base URL for the model server |
| `ODR_MODEL` | `gpt-oss-120b` | Model name for agent conversations |
| `ODR_CORPUS_DIR` | `./corpus/` | Default corpus directory |
| `ODR_CHUNK_MIN_CHARS` | `2000` | Minimum characters before a section is emitted as its own chunk |
| `ODR_CHUNK_MAX_CHARS` | `3000` | Maximum characters per chunk (triggers sliding window) |
| `ODR_CHUNK_OVERLAP` | `200` | Character overlap between sliding window chunks |
| `ODR_SEARCH_REASONING_EFFORT` | `low` | Reasoning effort for the exhaustive scanner (`low`, `medium`, `high`) |
| `ODR_SYNTHESIS_REASONING_EFFORT` | `medium` | Reasoning effort for the manager, synthesis, and section writer agents (`low`, `medium`, `high`) |

### Example `.env` for OpenAI

```env
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
ODR_MODEL=gpt-4.1
```

### Example `.env` for a self-hosted model server (Ollama, vLLM)

```env
OPENAI_API_KEY=not-needed
OPENAI_BASE_URL=https://your-server.example.com/v1
ODR_MODEL=llama3
```

The system uses the Chat Completions API (`set_default_openai_api("chat_completions")`) rather than the Responses API, which ensures compatibility with local model servers that don't implement the Responses API.

## Usage

Edit and run `example.py` as the single entry point:

```shell
python example.py
```

This will:
1. Discover all `.pdf` and `.md` files in the corpus directory.
2. Parse each file (PDFs are converted to Markdown via docling).
3. Split content into chunks using heading-aware chunking with sliding window.
4. Persist chunks to `ldr_index/` inside the corpus directory.
5. Run the full research pipeline (manager -> exhaustive scan -> synthesis -> probes).
6. Save the final report to `report.md`.

Edit the `question` variable in `example.py` (~line 51) to change the research question. Set `corpus_dir` (~line 36) to point at your document directory.

### Output format

The pipeline produces a Markdown report like:

```markdown
## Executive Summary

The documents describe several approaches to... [^1] [^2]

## Methodology

The primary methods identified include... [^3]

## Key Findings

Classification accuracy reached 95% using transformer models [^1],
compared to 78% for rule-based approaches [^4].

## References

[^1] paper1.md -- Section: "Results"
[^2] paper2.md -- Section: "Introduction"
[^3] paper1.md -- Section: "Methods"
[^4] paper2.md -- Section: "Applications"
```

Citations use Markdown footnote syntax (`[^N]`). Each reference maps to the source file and section heading of the cited chunk.

## Chunking Strategy

Documents are chunked using a three-step heading-aware pipeline:

1. **Split by headings** -- Markdown headings (`# ... ######`) are used as split points. Each section becomes a `(level, heading_text, body_text)` tuple.
2. **Merge small sections** -- Consecutive sections smaller than `ODR_CHUNK_MIN_CHARS` (default: 2000) are merged together to avoid fragments that lack context.
3. **Window large sections** -- Sections exceeding `ODR_CHUNK_MAX_CHARS` (default: 3000) are split using a sliding window with `ODR_CHUNK_OVERLAP` (default: 200) characters of overlap between windows.

Each chunk retains its source file path, heading, heading level, and a deterministic ID derived from the document ID and chunk index.

## Data Models

Defined in `src/models.py` using Pydantic:

| Model | Description |
|---|---|
| `Document` | A parsed source file (`doc_id`, `source_file`, `content`, `metadata`) |
| `Chunk` | A section of a document (`chunk_id`, `doc_id`, `source_file`, `heading`, `heading_level`, `text`, `char_len`, `chunk_index`, `page_estimate`) |
| `QueryRelevance` | Why a chunk is relevant to a specific query (`query`, `relevance_score`, `rationale`) |
| `Finding` | One per unique relevant chunk; accumulates all `QueryRelevance` entries across sub-questions (`citation_id`, `chunk_id`, `source_file`, `heading`, `text`, `relevance`) |
| `ChunkRelevanceJudgment` | Raw judgment for a single (chunk, question) pair from the exhaustive scan (`chunk_id`, `question_index`, `is_relevant`, `relevance_score`, `rationale`) |
| `ScanResult` | Summary of an exhaustive scan run (`questions`, `total_chunks`, `total_judgments`, `relevant_count`, `evidence_count`) |
| `SectionPlan` | A planned report section with assigned citation IDs (`section_title`, `section_instructions`, `citation_ids`, `order`) |
| `ReportOutline` | The full outline produced by the synthesis manager (list of `SectionPlan`) |
| `SectionResult` | Output of a section writer (`section_title`, `content`, `citations_used`, `order`, `probe_results`) |
| `BaseVerdict` | Base class for probe verdicts (`verdict`, `score`, `rationale`) |
| `CitationVerdict` | Per-citation probe verdict; adds `citation_id`, `citing_sentence`, `source_chunk_text`, `source_file`, `source_heading` |
| `SectionVerdict` | Per-section probe verdict; adds `details` dict |
| `ProbeResult` | Aggregated probe output (`probe_name`, `section_title`, `verdicts`, `mean_score`, `summary`) |

## Agent Tools

Six tools are available to the agents, defined in `src/research/tools.py`. Each is decorated with `@function_tool` and receives the shared `ResearchContext` via `RunContextWrapper`.

| Tool | Used By | Description |
|---|---|---|
| `submit_plan(sub_questions)` | Manager | Submits the research decomposition (list of sub-questions) |
| `submit_outline(sections)` | Synthesis Manager | Submits the report outline as a list of `SectionPlan` objects with assigned citation IDs |
| `get_all_evidence()` | Synthesis Manager | Returns all accumulated `Finding` objects formatted for outline planning |
| `get_citation_list()` | Synthesis Manager | Returns the formatted `## References` section with `[^N]` citation entries |
| `get_chunk_text(chunk_id)` | (available) | Retrieves the full text of a specific chunk by ID |
| `record_evidence(sub_question, findings, chunk_ids, relevance_score)` | (available) | Records evidence with citations manually (exhaustive scanner does this automatically) |

The exhaustive scanner (`research/exhaustive_scanner.py`) operates outside the agent tool system: it directly calls the OpenAI API in batched concurrent calls and writes `Finding` objects to `context.state.evidence`.

## Persistence

All artifacts are stored in a `ldr_index/` directory inside the corpus directory:

| File | Format | Contents |
|---|---|---|
| `chunks.jsonl` | JSONL | One JSON-serialized `Chunk` per line |
| `metadata.json` | JSON | Corpus metadata (chunk count, directory path) |
| `context_state.json` | JSON | Full research run state snapshot (evidence, outline, section results, probe results, citation usage counts) |
| `all_evidence.md` | Markdown | Formatted dump of all `Finding` objects for human review |
| `all_references.md` | Markdown | Formatted references section |
| `report_outline.md` | Markdown | Report outline with section plans and assigned citation IDs |
| `section_prompt_N.md` | Markdown | Per-section writer prompt for human review (one file per section) |

## Measurement Probes

After each section is written, measurement probes run automatically as LM-judge evaluators. Each probe is registered via `@register_probe` in `probes/` and called by the dispatcher in `probes/__init__.py`.

Three probes are implemented, covering mutually exclusive dimensions of citation quality:

| Probe | Module | Question |
|---|---|---|
| **Faithfulness** | `probes/faithfulness.py` | Does the source passage actually support the claim? (anti-hallucination) |
| **Completeness** | `probes/completeness.py` | Does the citing text accurately represent the source's full message, epistemic weight, and scope? (anti-cherry-picking) |
| **Sufficiency** | `probes/sufficiency.py` | Does the source carry the burden of proof the claim requires, or does the author overreach? (anti-overreaching) |

Probe results are stored on `SectionResult.probe_results` (keyed by probe name) and serialized to `context_state.json` as part of the audit trail.

## Web Demo

A browser-based visualization shows each pipeline stage as a rectangle that glows when active, with animated connector arrows and a live event log.

### Running the demo

```shell
python demo/server.py
# Open http://localhost:8765
```

Enter a research question and the path to a corpus directory, then click **Run Pipeline**. The UI updates in real time as each stage executes:

- **Stage rectangles** start dimmed; they glow blue while active and turn green when complete.
- **Connector arrows** animate with flowing dashes as data passes between stages.
- **Scanner progress bar** fills live as corpus chunks are evaluated.
- **Section mini-cards** cycle through states: pending → writing (blue) → probing (yellow) → done (green), with color-coded probe score badges (green ≥ 0.7, yellow ≥ 0.4, red < 0.4).
- **Event log** (right panel) streams every pipeline event with timestamps.

The demo server broadcasts pipeline events over a WebSocket using `aiohttp`. The frontend is vanilla HTML/CSS/JS with no build step.

## Project Structure

```
src/
  config.py              # Configuration from environment variables
  models.py              # Pydantic data models
  research/
    pipeline.py           # Main research pipeline orchestrator
    manager.py            # Manager agent (question decomposition)
    exhaustive_scanner.py # Batch LLM chunk evaluation
    synthesis_agent.py    # Synthesis manager + section writer agents
    tools.py              # @function_tool definitions
    context.py            # ResearchContext, ResearchInfrastructure, ResearchState
    prompts.py            # Agent instruction strings
    sanitizing_model.py   # SanitizingModel wrapper for local model compatibility
  ingest/
    pipeline.py           # Ingestion orchestrator (parse, chunk, persist)
    parsers.py            # PDF (via docling) and Markdown parsers
    chunker.py            # Heading-aware chunking with sliding window
  store/
    document_store.py     # Chunk persistence (JSONL) and retrieval
  citations/
    tracker.py            # CitationTracker (sequential IDs, deduplication)
  probes/
    __init__.py           # Probe registry and dispatcher
    faithfulness.py       # Citation faithfulness probe
    completeness.py       # Citation completeness probe
    sufficiency.py        # Citation sufficiency probe
    _judge.py             # Shared LM-judge call helper
    _extract.py           # Citation extraction utilities
    _prompts.py           # Probe prompt templates
example.py               # Single entry point: ingest + research
demo/
  server.py               # aiohttp WebSocket server for the web demo
  static/
    index.html            # Pipeline visualization UI
    style.css             # Dark-theme styles
    app.js                # WebSocket client and stage state management
scripts/
  docling_converter.py    # Standalone PDF-to-Markdown converter
```

## Privacy

Tracing is disabled by default (`set_tracing_disabled(True)`) to prevent telemetry from being sent to external services. The tool only communicates with the configured `OPENAI_BASE_URL` endpoint -- no other external calls are made.

## License

This software was developed at the National Institute of Standards and Technology (NIST). See [LICENSE](LICENSE) for full terms.
