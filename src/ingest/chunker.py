"""Heading-aware chunking with merge and sliding window."""

from __future__ import annotations

import hashlib
import re

from models import Chunk, Document


def split_by_headings(md_text: str) -> list[tuple[int, str, str]]:
    """Split markdown text on headings.

    Returns list of (level, heading_text, body_text) tuples.
    Level 0 means content before the first heading.
    """
    pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    sections: list[tuple[int, str, str]] = []

    matches = list(pattern.finditer(md_text))
    if not matches:
        return [(0, "", md_text.strip())]

    # Content before first heading
    pre = md_text[: matches[0].start()].strip()
    if pre:
        sections.append((0, "", pre))

    for i, match in enumerate(matches):
        level = len(match.group(1))
        heading = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md_text)
        body = md_text[start:end].strip()
        sections.append((level, heading, body))

    return sections


def merge_small_sections(
    sections: list[tuple[int, str, str]], min_chars: int = 2000
) -> list[tuple[int, str, str]]:
    """Merge consecutive small sections until they meet the minimum size."""
    if not sections:
        return sections

    merged: list[tuple[int, str, str]] = []
    current_level, current_heading, current_body = sections[0]

    for level, heading, body in sections[1:]:
        combined = current_body + "\n\n" + body if current_body else body
        if len(current_body) < min_chars:
            # Merge into current
            if heading and not current_heading:
                current_heading = heading
                current_level = level
            current_body = combined
        else:
            merged.append((current_level, current_heading, current_body))
            current_level, current_heading, current_body = level, heading, body

    merged.append((current_level, current_heading, current_body))
    return merged


def window_chunk(text: str, max_chars: int = 2500, overlap: int = 200) -> list[str]:
    """Sliding window chunking for text that exceeds max_chars."""
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunk = text[start:end]
        chunks.append(chunk.strip())
        start = end - overlap

    return chunks


def _make_chunk_id(doc_id: str, chunk_index: int) -> str:
    """Create a stable chunk ID from document ID and index."""
    raw = f"{doc_id}::{chunk_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def chunk_document(
    doc: Document,
    min_chars: int = 2000,
    max_chars: int = 2500,
    overlap: int = 200,
) -> list[Chunk]:
    """Full chunking pipeline: split by headings, merge small, window large."""
    sections = split_by_headings(doc.content)
    sections = merge_small_sections(sections, min_chars=min_chars)

    chunks: list[Chunk] = []
    chunk_index = 0

    for level, heading, body in sections:
        if not body.strip():
            continue

        windows = window_chunk(body, max_chars=max_chars, overlap=overlap)
        for window_text in windows:
            chunk_id = _make_chunk_id(doc.doc_id, chunk_index)
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    doc_id=doc.doc_id,
                    source_file=doc.source_file,
                    heading=heading,
                    heading_level=level,
                    text=window_text,
                    char_len=len(window_text),
                    chunk_index=chunk_index,
                )
            )
            chunk_index += 1

    return chunks
