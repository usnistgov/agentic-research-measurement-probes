"""Model wrapper that sanitizes tool call names from local model servers.

Some local models (vLLM, Ollama) append artifacts like ``<|channel|>commentary``
to function call names or hallucinate tool names that don't exist.  This wrapper
strips artifacts and drops unknown tool calls so the agents SDK doesn't crash.
"""

from __future__ import annotations

import re
from typing import AsyncIterator

from agents import Model, ModelResponse, ModelSettings, ModelTracing
from agents.agent_output import AgentOutputSchemaBase
from agents.handoffs import Handoff
from agents.tool import Tool
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseStreamEvent,
)


# Matches <|...|> tokens and everything after them in a tool name
_ARTIFACT_RE = re.compile(r"<\|.*$")


def _sanitize_name(name: str) -> str:
    """Strip model artifacts from a tool/function name."""
    return _ARTIFACT_RE.sub("", name).strip()


class SanitizingModel(Model):
    """Wraps another Model and cleans up tool call names in responses.

    - Strips ``<|...|>`` artifacts from tool call names.
    - Silently drops tool calls whose names don't match any registered
      tool or handoff, preventing ``ModelBehaviorError`` crashes.
    """

    def __init__(self, inner: Model) -> None:
        self._inner = inner
        self.sanitized_count: int = 0
        self.dropped_count: int = 0
        self.dropped_names: list[str] = []

    async def get_response(
        self,
        system_instructions: str | None,
        input,
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None = None,
        conversation_id: str | None = None,
        prompt=None,
    ) -> ModelResponse:
        response = await self._inner.get_response(
            system_instructions,
            input,
            model_settings,
            tools,
            output_schema,
            handoffs,
            tracing,
            previous_response_id=previous_response_id,
            conversation_id=conversation_id,
            prompt=prompt,
        )

        # Build set of known tool/handoff names
        known_names: set[str] = set()
        for t in tools:
            known_names.add(t.name)
        for h in handoffs:
            known_names.add(h.tool_name)

        # Sanitize names and drop unknown tool calls
        cleaned: list = []
        text_items: list = []
        for item in response.output:
            if isinstance(item, ResponseFunctionToolCall):
                original_name = item.name
                item.name = _sanitize_name(item.name)
                if original_name != item.name:
                    self.sanitized_count += 1
                    print(f"[sanitizer] Cleaned tool name: {original_name!r} -> {item.name!r}")
                if item.name not in known_names:
                    self.dropped_count += 1
                    self.dropped_names.append(original_name)
                    print(f"[sanitizer] Dropped unknown tool call: {original_name!r}")
                    continue
                cleaned.append(item)
            elif isinstance(item, ResponseOutputText):
                text_items.append(item)
            else:
                cleaned.append(item)

        has_tools = any(isinstance(item, ResponseFunctionToolCall) for item in cleaned)

        if has_tools:
            # When tool calls are present, the SDK only expects tool calls —
            # drop text items to avoid "Unexpected output type" warnings.
            for t in text_items:
                if t.text and t.text.strip():
                    preview = t.text.strip()[:200]
                    print(f"[sanitizer] Dropped model text (tool calls present): {preview!r}")
        elif text_items:
            # No tool calls — wrap bare ResponseOutputText in a ResponseOutputMessage
            # so the SDK recognizes them (it expects ResponseOutputMessage, not raw
            # ResponseOutputText in response.output).
            msg = ResponseOutputMessage(
                id="msg_sanitized",
                type="message",
                role="assistant",
                content=text_items,
                status="completed",
            )
            cleaned.append(msg)

        # If we dropped ALL tool calls and there's no text output left,
        # inject an empty text output so the SDK doesn't get an empty response
        has_content = any(
            isinstance(item, (ResponseOutputMessage, ResponseOutputText))
            for item in cleaned
        )
        if not has_content and not has_tools:
            cleaned.append(
                ResponseOutputMessage(
                    id="msg_empty",
                    type="message",
                    role="assistant",
                    content=[ResponseOutputText(type="output_text", text="", annotations=[])],
                    status="completed",
                )
            )

        response.output = cleaned
        return response

    def stream_response(
        self,
        system_instructions: str | None,
        input,
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None = None,
        conversation_id: str | None = None,
        prompt=None,
    ) -> AsyncIterator[ResponseStreamEvent]:
        return self._inner.stream_response(
            system_instructions,
            input,
            model_settings,
            tools,
            output_schema,
            handoffs,
            tracing,
            previous_response_id=previous_response_id,
            conversation_id=conversation_id,
            prompt=prompt,
        )
