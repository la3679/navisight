"""The LLM provider boundary.

One narrow protocol sits between the agent loop and whichever model answers.
Everything above it — the tool registry, the bounds, the evidence collection,
the grounding rules — is provider-independent, so swapping the model cannot
weaken any of it.

Two implementations ship:

- :mod:`app.agent.providers.mock` — deterministic, offline, no key. Tests and
  local development run against it, which is what keeps the agent's behaviour
  assertable rather than merely plausible.
- :mod:`app.agent.providers.openai_provider` — the real one.

The provider sees the conversation and the tool *schemas*. It never sees a
database handle, and it never executes anything: it returns either a message or
a request to call a named tool, and the loop decides what happens next.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class ToolCall:
    """A model's request to run one tool. Not yet validated, not yet run."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Message:
    """One turn of the conversation, in provider-neutral form."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    #: Set on ``tool`` messages, linking a result back to its request.
    tool_call_id: str | None = None


@dataclass(frozen=True)
class Completion:
    """What a provider returned for one step."""

    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    #: Provider-reported token usage, when it reports any. Never a guess.
    usage: dict[str, int] = field(default_factory=dict)


class ProviderError(RuntimeError):
    """The provider could not be reached or refused the request.

    Carries a message safe to show a user. Implementations must ensure nothing
    in it can contain a credential — see the redaction in the OpenAI provider.
    """


@runtime_checkable
class LLMProvider(Protocol):
    """What the agent loop needs from a model. Deliberately small."""

    #: Shown to the user so they know what answered them.
    name: str
    model: str

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]],
    ) -> Completion:
        """One turn: either a message, or a request to call tools."""
        ...
