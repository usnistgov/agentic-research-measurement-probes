# CLAUDE.md

## Project Overview

Open Deep Research is an agentic AI-powered research tool that operates on **local PDF and Markdown document corpora** (not the open internet). Given a research question, it orchestrates AI agents to exhaustively evaluate, synthesize, and verify information, producing a Markdown report with inline citations.

Built on the OpenAI Agents SDK, compatible with OpenAI, Ollama, vLLM, or any OpenAI-compatible API endpoint.

## Memory

Session memories and user preferences are stored in `memory/` at the project root. See @MEMORY.md for the index.

## Development Setup

### Prerequisites

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) package manager

### Installation

```shell
uv venv --python=3.12
source .venv/bin/activate
uv pip install -r requirements.txt
```

### Configuration

Copy `.env.example` to `.env` and configure:
- `OPENAI_API_KEY` - API key for the model server
- `OPENAI_BASE_URL` - Base URL (default: OpenAI, or set to local server)
- `ODR_MODEL` - Model name (default: `gpt-oss-120b`)

## Entry Point

```shell
python example.py
```

Edit the `question` variable in `example.py` (~line 51) to change the research question. Set `corpus_dir` (~line 36) to point at your document directory.

## Architecture

The system uses a **programmatic pipeline** (not LLM-driven handoffs) for reliability with local models. Four stages:

1. **Manager Agent** (`research/manager.py`) -- Decomposes the question into sub-questions via `submit_plan` tool
2. **Exhaustive Scanner** (`research/exhaustive_scanner.py`) -- Evaluates every corpus chunk against all sub-questions using batch LLM calls. Optional BM25 prefilter for faster debugging.
3. **Synthesis Pipeline** (`research/synthesis_agent.py` + `research/pipeline.py`):
   - 3a. Synthesis Manager plans report outline, assigns citation IDs to sections
   - 3b. Section Writer writes each section with its assigned evidence
   - 3c. Assembly concatenates sections + references
4. **Evaluation Probes** (`probes/`) -- LM-judge evaluators run after each section, scoring quality. Results stored on `SectionResult.probe_results`.

All agents share a `ResearchContext` (`research/context.py`) with immutable `ResearchInfrastructure` and mutable `ResearchState`.

**Detailed references:** @docs/pipeline.md (pipeline flow, modules, tools, persistence), @docs/models.md (data models, context), @docs/probes.md (probe registry, design patterns, planned probes).

## NIST Privacy Requirements

- Tracing is disabled (`set_tracing_disabled(True)`) in `example.py`
- No telemetry sent to external services
- Only communicates with configured `OPENAI_BASE_URL` endpoint

## Coding Conventions

- Use async/await throughout (all agents and tools are async)
- All data models use Pydantic BaseModel with type hints
- Configuration via environment variables with `ODR_` prefix
- Use `uv` for dependency management, not pip directly
- Deterministic chunk IDs derived from `doc_id` and `chunk_index`
- `src/` is added to `sys.path` in `example.py` -- no pip install needed for imports
