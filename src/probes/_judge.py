"""Shared LM-judge calling infrastructure for evaluation probes."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel

if TYPE_CHECKING:
    from openai import AsyncOpenAI

T = TypeVar("T", bound=BaseModel)


async def gather_with_progress(
    tasks: list[Coroutine],
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> list:
    """Run coroutines concurrently, calling on_progress(completed, total) as each finishes."""
    total = len(tasks)
    if not tasks:
        return []

    completed = 0
    results = [None] * total

    async def _tracked(index: int, coro: Coroutine):
        nonlocal completed
        results[index] = await coro
        completed += 1
        if on_progress:
            await on_progress(completed, total)

    await asyncio.gather(*[_tracked(i, t) for i, t in enumerate(tasks)])
    return results


async def call_judge(
    client: AsyncOpenAI,
    model: str,
    prompt: str,
    response_schema: type[T],
    temperature: float = 0.0,
) -> T:
    """Call an LM judge and return a parsed Pydantic response.

    Uses the OpenAI structured output API (beta.chat.completions.parse)
    to constrain the model's output to the given Pydantic schema.

    Raises on API errors or parse failures — callers should handle
    exceptions and produce appropriate error verdicts.
    """
    response = await client.beta.chat.completions.parse(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        response_format=response_schema,
    )
    parsed = response.choices[0].message.parsed
    if parsed is None:
        raise ValueError(
            f"Judge returned no parsed output. "
            f"Refusal: {response.choices[0].message.refusal or 'none'}"
        )
    return parsed
