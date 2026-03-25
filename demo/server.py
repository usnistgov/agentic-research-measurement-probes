"""Demo visualization server for the research pipeline.

Serves a web UI that shows real-time pipeline stage activity via WebSocket.
Usage:
    python demo/server.py
    # Open http://localhost:8765 in browser
"""

import asyncio
import json
import sys
from pathlib import Path

import aiohttp
from aiohttp import web

# Add src/ to path so we can import project modules directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from config import Config

STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_QUESTION = (
    "Analyze the architectural requirements and scalability of in memory computing "
    "for data-intensive applications. Specifically, evaluate how modern memory "
    "management techniques enable the processing of massive datasets entirely "
    "within RAM, and identify existing enterprise technologies that implement this model."
)
DEFAULT_CORPUS_DIR = str(PROJECT_ROOT / "example-corpus")

connected_clients: set[web.WebSocketResponse] = set()
pipeline_running = False


async def broadcast(event: dict) -> None:
    """Send an event to all connected WebSocket clients."""
    msg = json.dumps(event)
    disconnected = set()
    for ws in connected_clients:
        try:
            await ws.send_str(msg)
        except (ConnectionError, ConnectionResetError):
            disconnected.add(ws)
    connected_clients.difference_update(disconnected)


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    global pipeline_running
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    connected_clients.add(ws)

    await ws.send_str(json.dumps({"type": "server_config", "data": {"model": Config().model}}))

    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("action") == "start":
                    if pipeline_running:
                        await ws.send_str(json.dumps({"type": "error", "data": {"message": "Pipeline already running"}}))
                        continue

                    pipeline_running = True
                    try:
                        await _run_pipeline(data.get("question", DEFAULT_QUESTION), data.get("corpus_dir", DEFAULT_CORPUS_DIR), data.get("model") or Config().model)
                    except Exception as exc:
                        await broadcast({"type": "error", "data": {"message": str(exc)}})
                    finally:
                        pipeline_running = False

            elif msg.type == aiohttp.WSMsgType.ERROR:
                break
    finally:
        connected_clients.discard(ws)

    return ws


async def _run_pipeline(question: str, corpus_dir: str, model: str) -> None:
    """Set up ResearchContext and run the pipeline with event broadcasting."""
    from agents import set_default_openai_api, set_tracing_disabled
    from openai import AsyncOpenAI

    from research.context import ResearchContext, ResearchInfrastructure, ResearchState
    from research.pipeline import run_research_pipeline
    from citations.tracker import CitationTracker
    from config import Config
    from ingest.pipeline import ingest_corpus
    from store.document_store import DocumentStore

    set_default_openai_api("chat_completions")
    set_tracing_disabled(True)

    config = Config()
    corpus_path = Path(corpus_dir).resolve()

    store = DocumentStore(corpus_path)
    ingest_corpus(corpus_path, store, config)

    client = AsyncOpenAI()
    infra = ResearchInfrastructure(
        document_store=store,
        citation_tracker=CitationTracker(),
        openai_client=client,
        model_name=model,
    )
    state = ResearchState(research_question=question)
    context = ResearchContext(infra=infra, state=state)

    report = await run_research_pipeline(
        question=question,
        context=context,
        verbose=True,
        on_event=broadcast,
        prefilter=True,
        batch_size=config.batch_size,
    )

    await broadcast({"type": "pipeline_complete", "stage": "done", "data": {"report_length": len(report)}})


async def index_handler(request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_static("/static/", STATIC_DIR, name="static")
    return app


if __name__ == "__main__":
    print("Starting demo server at http://localhost:8765")
    web.run_app(create_app(), port=8765)
