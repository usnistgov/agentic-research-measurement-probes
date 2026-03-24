"""Ingestion pipeline: discover files -> parse -> chunk -> persist."""

from __future__ import annotations

import hashlib
from pathlib import Path

from config import Config
from ingest.chunker import chunk_document
from ingest.parsers import SUPPORTED_EXTENSIONS, parse_file
from models import Document
from store.document_store import DocumentStore, INDEX_DIR_NAME


def _make_doc_id(path: Path, corpus_dir: Path) -> str:
    """Create a stable document ID from the relative path."""
    rel = path.relative_to(corpus_dir)
    return hashlib.sha256(str(rel).encode()).hexdigest()[:16]


def discover_files(corpus_dir: Path) -> list[Path]:
    """Find all supported files in the corpus directory.

    - Skips ``.pdf.md`` cache files produced by the PDF parser.
    - If a PDF has a cached ``.pdf.md`` alongside it, the PDF is
      replaced by the cached Markdown so docling conversion is skipped
      entirely.
    """
    files = []
    for ext in SUPPORTED_EXTENSIONS:
        for f in corpus_dir.rglob(f"*{ext}"):
            if INDEX_DIR_NAME in str(f.absolute):
                continue
            if f.name.endswith(".pdf.md"):
                continue
            if ext == ".pdf":
                cached = f.with_suffix(f.suffix + ".md")
                if cached.exists():
                    files.append(cached)
                    continue
            files.append(f)
    return sorted(files)


def ingest_corpus(
    corpus_dir: str | Path,
    store: DocumentStore,
    config: Config,
) -> int:
    """Run the full ingestion pipeline.

    Discovers files, parses them, chunks them, and persists to disk.
    Returns the number of chunks created.
    """
    corpus_dir = Path(corpus_dir)
    if not corpus_dir.is_dir():
        raise FileNotFoundError(f"Corpus directory not found: {corpus_dir}")

    files = discover_files(corpus_dir)
    if not files:
        raise FileNotFoundError(
            f"No supported files found in {corpus_dir}. "
            f"Supported extensions: {SUPPORTED_EXTENSIONS}"
        )

    print(f"Found {len(files)} files to ingest")

    all_chunks = []
    for file_path in files:
        print(f"  Parsing: {file_path.name}")
        content = parse_file(file_path)
        doc_id = _make_doc_id(file_path, corpus_dir)
        doc = Document(
            doc_id=doc_id,
            source_file=str(file_path.relative_to(corpus_dir)),
            content=content,
        )
        chunks = chunk_document(
            doc,
            min_chars=config.chunk_min_chars,
            max_chars=config.chunk_max_chars,
            overlap=config.chunk_overlap,
        )
        all_chunks.extend(chunks)
        print(f"    -> {len(chunks)} chunks")

    store.add_chunks(all_chunks)
    print(f"Total chunks: {len(all_chunks)}")

    print("Saving to disk...")
    store.save()

    print(f"Done! Index saved to {store.index_dir}")
    return len(all_chunks)
