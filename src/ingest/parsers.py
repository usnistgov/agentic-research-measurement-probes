"""File parsers for PDF and Markdown documents."""

from __future__ import annotations

from pathlib import Path

SUPPORTED_EXTENSIONS = {".pdf", ".md"}


def parse_pdf(path: Path) -> str:
    """Convert a PDF file to Markdown text using docling.

    A cached ``.md`` copy is saved next to the original PDF
    (e.g. ``paper.pdf`` -> ``paper.pdf.md``).  If the cached file
    already exists and is newer than the PDF, it is returned directly
    to avoid the expensive conversion.
    """
    path = Path(path)
    cached = path.with_suffix(path.suffix + ".md")

    if cached.exists() and cached.stat().st_mtime >= path.stat().st_mtime:
        return cached.read_text(encoding="utf-8")

    try:
        from docling.document_converter import DocumentConverter
    except ImportError:
        raise ImportError(
            "PDF parsing requires the 'docling' package. "
            "Install it with: uv pip install docling"
        )

    converter = DocumentConverter()
    result = converter.convert(str(path))
    md_text = result.document.export_to_markdown()

    cached.write_text(md_text, encoding="utf-8")
    return md_text


def parse_markdown(path: Path) -> str:
    """Read a Markdown file directly."""
    return path.read_text(encoding="utf-8")


def parse_file(path: Path) -> str:
    """Route to the appropriate parser based on file extension."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".pdf":
        return parse_pdf(path)
    elif ext == ".md":
        return parse_markdown(path)
    else:
        raise ValueError(f"Unsupported file type: {ext!r}. Supported: {SUPPORTED_EXTENSIONS}")
