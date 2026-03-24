"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Load .env once at module import time
load_dotenv()


def _env(key: str, default: str) -> str:
    return os.getenv(key, default)


def _env_int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)))


@dataclass
class Config:
    """Application configuration.

    All fields default to values from environment variables (ODR_ prefix,
    with OPENAI_API_KEY / OPENAI_BASE_URL as fallbacks).  Values passed
    explicitly to the constructor take precedence over environment variables.
    """

    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY", ""))
    openai_base_url: str = field(
        default_factory=lambda: _env("OPENAI_BASE_URL", "https://api.openai.com/v1")
    )
    model: str = field(default_factory=lambda: _env("ODR_MODEL", "gpt-oss-120b"))
    corpus_dir: str = field(default_factory=lambda: _env("ODR_CORPUS_DIR", "./corpus/"))
    chunk_min_chars: int = field(
        default_factory=lambda: _env_int("ODR_CHUNK_MIN_CHARS", 2000)
    )
    chunk_max_chars: int = field(
        default_factory=lambda: _env_int("ODR_CHUNK_MAX_CHARS", 3000)
    )
    chunk_overlap: int = field(
        default_factory=lambda: _env_int("ODR_CHUNK_OVERLAP", 200)
    )
    batch_size: int = field(
        default_factory=lambda: _env_int("ODR_BATCH_SIZE", 16)
    )
    search_reasoning_effort: str = field(
        default_factory=lambda: _env("ODR_SEARCH_REASONING_EFFORT", "low")
    )
    synthesis_reasoning_effort: str = field(
        default_factory=lambda: _env("ODR_SYNTHESIS_REASONING_EFFORT", "medium")
    )
