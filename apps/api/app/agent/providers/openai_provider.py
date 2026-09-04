"""The OpenAI provider.

Credential handling, which is the part worth reading carefully:

- The key is read **once, from the backend environment variable
  ``OPENAI_API_KEY``**, through the settings object. There is no default, no
  literal, and no other source.
- It is never logged. The exception path below scrubs the message before it can
  reach a log line or an API response, because SDK errors sometimes echo request
  headers.
- It never leaves the API process. Nothing in ``app/api`` serializes it, and it
  is structurally impossible to reach the browser: a ``NEXT_PUBLIC_*`` variable
  is a *frontend* build-time value, and this one is only ever read here.
- With no key configured, this provider is never constructed. The application
  starts, every non-AI route works, and the copilot reports "not configured".

The SDK is an optional dependency (``uv sync --extra ai``). It is imported
inside the constructor rather than at module scope so that importing the agent
package never requires it.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.agent.provider import Completion, Message, ProviderError, ToolCall

NAME = "openai"

#: Used when LLM_MODEL is not set. Small, fast, and inexpensive — appropriate
#: for a tool-calling loop over pre-computed figures.
DEFAULT_MODEL = "gpt-4o-mini"

#: Anything shaped like an API key, scrubbed before an error is shown or logged.
_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")


def redact(text: str) -> str:
    """Remove anything key-shaped from a string bound for a log or a response."""
    return _KEY_PATTERN.sub("sk-***", text)


class OpenAIProvider:
    """Tool-calling against the OpenAI Chat Completions API."""

    name = NAME

    def __init__(self, *, api_key: str, model: str = "", timeout_seconds: int = 60) -> None:
        if not api_key:
            # Reaching here means the caller skipped the configuration check.
            raise ProviderError(
                "OPENAI_API_KEY is not set. Set it in the backend environment; "
                "it must never be exposed to the browser."
            )
        try:
            from openai import AsyncOpenAI
        except ModuleNotFoundError as exc:  # pragma: no cover - depends on extras
            raise ProviderError(
                "The OpenAI SDK is not installed. Install the AI extra with `uv sync --extra ai`."
            ) from exc

        self.model = model or DEFAULT_MODEL
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout_seconds)

    async def complete(self, messages: list[Message], *, tools: list[dict[str, Any]]) -> Completion:
        payload = [_to_openai(message) for message in messages]
        tool_specs = [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                },
            }
            for tool in tools
        ]

        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=payload,  # type: ignore[arg-type]
                tools=tool_specs or None,  # type: ignore[arg-type]
                # Deterministic-leaning: this agent reports figures a tool
                # produced, so there is nothing for sampling variety to add.
                temperature=0.0,
            )
        except Exception as exc:
            # Re-raised as a typed error. `from None` deliberately drops the
            # chain: an SDK traceback can echo request headers, and this message
            # reaches a user.
            raise ProviderError(f"The OpenAI request failed: {redact(str(exc))}") from None

        choice = response.choices[0]
        calls = tuple(
            ToolCall(
                id=call.id,
                name=call.function.name,
                arguments=_parse_arguments(call.function.arguments),
            )
            for call in (choice.message.tool_calls or [])
            if call.type == "function"
        )
        usage = (
            {
                "promptTokens": response.usage.prompt_tokens,
                "completionTokens": response.usage.completion_tokens,
                "totalTokens": response.usage.total_tokens,
            }
            if response.usage
            else {}
        )
        return Completion(content=choice.message.content or "", tool_calls=calls, usage=usage)


def _parse_arguments(raw: str | None) -> dict[str, Any]:
    """Decode tool arguments, tolerating a model that emits malformed JSON.

    An empty dict here is not a silent failure: the tool's Pydantic model will
    reject it and the loop tells the model what was wrong, which is a better
    outcome than raising and losing the run.
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _to_openai(message: Message) -> dict[str, Any]:
    if message.role == "tool":
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id,
            "content": message.content,
        }
    if message.role == "assistant" and message.tool_calls:
        return {
            "role": "assistant",
            "content": message.content or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
                for call in message.tool_calls
            ],
        }
    return {"role": message.role, "content": message.content}
