"""Shared LM-judge calling infrastructure for measurement probes."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel

if TYPE_CHECKING:
    from openai import AsyncOpenAI

T = TypeVar("T", bound=BaseModel)


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
