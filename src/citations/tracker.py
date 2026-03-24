"""Citation tracking: assigns [N] numbers, deduplicates, formats references."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from models import Chunk


@dataclass
class _CitationRecord:
    """Internal record for reference formatting."""
    citation_id: int
    chunk_id: str
    source_file: str
    heading: str


class CitationTracker:
    """Tracks citations, assigns sequential [N] IDs, deduplicates by chunk_id.

    Maintains a usage count so metrology tools can see how many times
    each chunk was referenced across different questions/evidence items.
    """

    def __init__(self):
        self._records: dict[str, _CitationRecord] = {}  # chunk_id -> record
        self._next_id: int = 1
        self._usage_counts: dict[str, int] = defaultdict(int)  # chunk_id -> count

    def add_citation(self, chunk: Chunk) -> int:
        """Register a chunk and return its citation_id (1-based).

        Deduplicates by chunk_id. Always increments the usage count.
        """
        self._usage_counts[chunk.chunk_id] += 1

        if chunk.chunk_id in self._records:
            return self._records[chunk.chunk_id].citation_id

        record = _CitationRecord(
            citation_id=self._next_id,
            chunk_id=chunk.chunk_id,
            source_file=chunk.source_file,
            heading=chunk.heading,
        )
        self._records[chunk.chunk_id] = record
        self._next_id += 1
        return record.citation_id

    def get_citation_id(self, chunk_id: str) -> int | None:
        """Get the citation_id for a chunk_id, or None if not tracked."""
        rec = self._records.get(chunk_id)
        return rec.citation_id if rec else None

    def usage_count(self, chunk_id: str) -> int:
        """How many times a chunk has been cited across all evidence items."""
        return self._usage_counts.get(chunk_id, 0)

    def all_usage_counts(self) -> dict[str, int]:
        """Return all usage counts (chunk_id -> count)."""
        return dict(self._usage_counts)

    def all_citation_ids(self) -> list[int]:
        """Return all citation IDs in order."""
        return sorted(r.citation_id for r in self._records.values())

    def format_references(self) -> str:
        """Produce a Markdown references section."""
        records = sorted(self._records.values(), key=lambda r: r.citation_id)
        if not records:
            return ""

        lines = ["## References", ""]
        for r in records:
            parts = [f"[^{r.citation_id}] {r.source_file}"]
            if r.heading:
                parts.append(f'Section: "{r.heading}"')
            lines.append(" -- ".join(parts))
            lines.append("")

        return "\n".join(lines)
