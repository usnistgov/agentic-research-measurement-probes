"""Chunk storage and retrieval with JSONL persistence."""

from __future__ import annotations

import json
from pathlib import Path

from models import Chunk

INDEX_DIR_NAME = "ldr_index"
CHUNKS_FILE = "chunks.jsonl"
METADATA_FILE = "metadata.json"


class DocumentStore:
    """Manages chunks in memory with JSONL persistence in ldr_index/."""

    def __init__(self, corpus_dir: str | Path):
        self.corpus_dir = Path(corpus_dir)
        self.index_dir = self.corpus_dir / INDEX_DIR_NAME
        self._chunks: dict[str, Chunk] = {}

    def add_chunks(self, chunks: list[Chunk]) -> None:
        """Add chunks to the store."""
        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        """Retrieve a chunk by ID."""
        return self._chunks.get(chunk_id)

    def all_chunks(self) -> list[Chunk]:
        """Return all stored chunks."""
        return list(self._chunks.values())

    @property
    def is_indexed(self) -> bool:
        """Check if the corpus has been indexed."""
        return (self.index_dir / CHUNKS_FILE).exists()

    def save(self) -> None:
        """Persist chunks to JSONL on disk."""
        self.index_dir.mkdir(parents=True, exist_ok=True)

        # Write chunks as JSONL
        chunks_path = self.index_dir / CHUNKS_FILE
        with open(chunks_path, "w", encoding="utf-8") as f:
            for chunk in self._chunks.values():
                f.write(chunk.model_dump_json() + "\n")

        # Write metadata
        meta_path = self.index_dir / METADATA_FILE
        meta = {
            "num_chunks": len(self._chunks),
            "corpus_dir": str(self.corpus_dir),
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    def load(self) -> None:
        """Load chunks from JSONL on disk."""
        chunks_path = self.index_dir / CHUNKS_FILE
        if not chunks_path.exists():
            raise FileNotFoundError(
                f"No index found at {self.index_dir}. Run ingestion first."
            )

        self._chunks.clear()
        with open(chunks_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    chunk = Chunk.model_validate_json(line)
                    self._chunks[chunk.chunk_id] = chunk
