"""Example: full end-to-end ingest + research pipeline with measurement probes."""

import asyncio
import sys
from pathlib import Path

# Add src/ to the Python path so modules can be imported directly
sys.path.insert(0, str(Path(__file__).parent / "src"))

from openai import AsyncOpenAI
from dotenv import load_dotenv
load_dotenv()

from config import Config


async def main() -> None:
    from agents import set_default_openai_api, set_tracing_disabled

    from research.context import (
        ResearchContext,
        ResearchInfrastructure,
        ResearchState,
    )
    from research.pipeline import run_research_pipeline
    from citations.tracker import CitationTracker
    from ingest.pipeline import ingest_corpus
    from store.document_store import DocumentStore

    # Use Chat Completions API (compatible with local model servers)
    set_default_openai_api("chat_completions")
    # Disable tracing (NIST privacy requirement)
    set_tracing_disabled(True)

    config = Config()
    # Warn if OpenAI API key is not set or if using default OpenAI URL without a key
    if not config.openai_api_key:
        if config.openai_base_url == "https://api.openai.com/v1":
            print("Warning: OPENAI_API_KEY is not set. Using default OpenAI API URL but no API key provided.", file=sys.stderr)
        else:
            print("Warning: OPENAI_API_KEY is not set. The OpenAI API client may fail to initialize.", file=sys.stderr)

    corpus_dir = Path("./example-corpus").resolve()
    config.corpus_dir = str(corpus_dir)

    # -- Ingest: parse documents, chunk, and persist --
    store = DocumentStore(corpus_dir)

    try:
        ingest_corpus(corpus_dir, store, config)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # -- Research: run the full pipeline --
    client = AsyncOpenAI()

    question = (
        "Analyze the architectural requirements and scalability of in memory computing "
        "for data-intensive applications. Specifically, evaluate how modern memory "
        "management techniques enable the processing of massive datasets entirely "
        "within RAM, and identify existing enterprise technologies that implement this model."
    )
    verbose = True

    infra = ResearchInfrastructure(
        document_store=store,
        citation_tracker=CitationTracker(),
        openai_client=client,
        model_name=config.model,
    )
    state = ResearchState(research_question=question)
    context = ResearchContext(infra=infra, state=state)

    report = await run_research_pipeline(
        question=question,
        context=context,
        verbose=verbose,
        prefilter=True,
        batch_size=config.batch_size,
        relevance_threshold=0.5,
    )

    Path("report.md").write_text(report, encoding="utf-8")
    print(f"Report saved to report.md")


if __name__ == "__main__":
    asyncio.run(main())
