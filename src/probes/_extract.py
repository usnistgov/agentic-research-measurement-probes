"""Shared citation extraction utilities for evaluation probes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import Finding

CITATION_RE = re.compile(r"\[\^(\d+)\]")
STRIP_CITATIONS_RE = re.compile(r"\[\^\d+\]")

# Sentence boundary: period/question/exclamation followed by whitespace or newline,
# but not after common abbreviations (e.g., Dr., Mr., etc.)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])(?:\s+|\n)")


@dataclass
class CitationTriple:
    """One citation instance in a sentence."""

    citation_id: int
    raw_sentence: str
    clean_sentence: str  # citation markers stripped


def extract_citation_triples(content: str) -> list[CitationTriple]:
    """Extract all (citation_id, sentence) pairs from section markdown."""
    sentences = SENTENCE_SPLIT_RE.split(content)

    triples: list[CitationTriple] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        citation_ids = [int(m) for m in CITATION_RE.findall(sentence)]
        if not citation_ids:
            continue

        clean = STRIP_CITATIONS_RE.sub("", sentence).strip()
        clean = re.sub(r"  +", " ", clean)

        for cid in set(citation_ids):  # deduplicate within same sentence
            triples.append(
                CitationTriple(
                    citation_id=cid,
                    raw_sentence=sentence,
                    clean_sentence=clean,
                )
            )

    return triples


def mark_sentence_in_context(section_content: str, raw_sentence: str) -> str:
    """Wrap the target sentence in <mark> tags within the section content.

    If the exact sentence is not found (e.g., due to whitespace differences),
    falls back to returning the section content with the sentence appended
    in a marked block.
    """
    idx = section_content.find(raw_sentence)
    if idx != -1:
        return section_content[:idx] + "<mark>" + raw_sentence + "</mark>" + section_content[idx + len(raw_sentence):]
    return section_content + "\n\n<mark>" + raw_sentence + "</mark>"


def find_evidence(
    citation_id: int,
    section_evidence: list[Finding],
    all_evidence: list[Finding],
) -> Finding | None:
    """Find the Finding for a citation_id, preferring section evidence."""
    for f in section_evidence:
        if f.citation_id == citation_id:
            return f
    for f in all_evidence:
        if f.citation_id == citation_id:
            return f
    return None
