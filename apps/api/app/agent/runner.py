"""The agent loop.

A bounded read-evaluate cycle: ask the provider, run whichever allow-listed tool
it names, hand back the result, repeat until it answers or the budget runs out.

Three properties this loop guarantees, none of which depend on the model
cooperating:

- **It terminates.** ``agent_max_tool_calls`` and ``agent_timeout_seconds`` are
  enforced here, not requested of the model. Hitting either produces an answer
  saying so rather than a hang.
- **Every claim is traceable.** Each tool call is recorded with its validated
  arguments, its duration, and the result the model saw. The API returns those
  records, so a user can check the answer against the evidence rather than
  trusting it (SOUL.md §9).
- **Nothing unnamed runs.** The loop dispatches through
  :func:`app.agent.tools.execute`, which refuses any name outside the registry.

The run is persisted to ``agent_runs`` as tool calls and timings only — never
hidden reasoning, which we do not collect and would not store.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pymongo.asynchronous.database import AsyncDatabase

from app.agent import tools as tool_registry
from app.agent.prompts import ANSWER_SCHEMA_INSTRUCTION, SYSTEM_PROMPT
from app.agent.provider import LLMProvider, Message, ProviderError
from app.db import collections
from app.observability import scrub

logger = logging.getLogger(__name__)

#: Kinds a claim may carry. Anything else the model invents is downgraded to the
#: weakest, because an unrecognised label must never read as stronger than it is.
CLAIM_KINDS = ("observed", "derived", "heuristic", "interpretation")
WEAKEST_KIND = "interpretation"

#: A tool result larger than this is truncated before it reaches the model. The
#: tools are already bounded; this is a backstop, and it is reported when it
#: fires rather than silently trimming evidence.
MAX_RESULT_CHARS = 8_000


@dataclass
class ToolInvocation:
    """One executed tool call, as the user will see it."""

    name: str
    arguments: dict[str, Any]
    ok: bool
    duration_ms: float
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class AgentResult:
    """Everything one question produced."""

    run_id: str
    question: str
    answer: str
    claims: list[dict[str, str]] = field(default_factory=list)
    limitations: str = ""
    evidence: list[ToolInvocation] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    truncated: bool = False
    duration_ms: float = 0.0
    usage: dict[str, int] = field(default_factory=dict)


def tool_specs() -> list[dict[str, Any]]:
    """The tool catalogue, in the shape providers expect."""
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.json_schema(),
        }
        for tool in tool_registry.TOOLS
    ]


def _serialise(value: Any) -> str:
    return json.dumps(value, default=str)


def _parse_answer(content: str) -> tuple[str, list[dict[str, str]], str]:
    """Read the model's final message.

    A model that ignores the response shape still produces a usable answer: the
    prose is kept and the claim list is empty, which understates rather than
    overstates what was established.
    """
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return content.strip(), [], ""
    if not isinstance(payload, dict):
        return content.strip(), [], ""

    claims: list[dict[str, str]] = []
    for claim in payload.get("claims") or []:
        if not isinstance(claim, dict) or not claim.get("text"):
            continue
        kind = str(claim.get("kind", "")).lower()
        claims.append(
            {
                "text": str(claim["text"]),
                "kind": kind if kind in CLAIM_KINDS else WEAKEST_KIND,
            }
        )
    return (
        str(payload.get("answer") or "").strip(),
        claims,
        str(payload.get("limitations") or "").strip(),
    )


async def run(
    database: AsyncDatabase[dict[str, Any]],
    provider: LLMProvider,
    question: str,
    *,
    max_tool_calls: int,
    timeout_seconds: int,
) -> AgentResult:
    """Answer one question, within a hard budget."""
    run_id = uuid4().hex
    started = time.perf_counter()
    deadline = started + timeout_seconds

    messages: list[Message] = [
        Message(role="system", content=SYSTEM_PROMPT + "\n" + ANSWER_SCHEMA_INSTRUCTION),
        # The user's question is passed as data in a user turn. It never becomes
        # part of the system prompt, so it cannot rewrite the rules above it.
        Message(role="user", content=question),
    ]
    specs = tool_specs()
    evidence: list[ToolInvocation] = []
    usage: dict[str, int] = {}
    truncated = False
    answer = ""
    claims: list[dict[str, str]] = []
    limitations = ""

    while True:
        if len(evidence) >= max_tool_calls or time.perf_counter() > deadline:
            truncated = True
            break

        completion = await provider.complete(messages, tools=specs)
        for key, value in completion.usage.items():
            usage[key] = usage.get(key, 0) + value

        if not completion.tool_calls:
            answer, claims, limitations = _parse_answer(completion.content)
            break

        messages.append(
            Message(role="assistant", content=completion.content, tool_calls=completion.tool_calls)
        )

        for call in completion.tool_calls:
            call_started = time.perf_counter()
            try:
                tool_result = await tool_registry.execute(database, call.name, call.arguments)
                invocation = ToolInvocation(
                    name=call.name,
                    arguments=call.arguments,
                    ok=True,
                    duration_ms=round((time.perf_counter() - call_started) * 1000, 2),
                    result=tool_result,
                )
                payload = _serialise(tool_result)
                if len(payload) > MAX_RESULT_CHARS:
                    payload = payload[:MAX_RESULT_CHARS]
                    payload += '... [truncated by NaviSight; ask for a smaller limit]"'
            except tool_registry.ToolError as exc:
                invocation = ToolInvocation(
                    name=call.name,
                    arguments=call.arguments,
                    ok=False,
                    duration_ms=round((time.perf_counter() - call_started) * 1000, 2),
                    error=str(exc),
                )
                payload = _serialise({"error": str(exc)})

            evidence.append(invocation)
            messages.append(Message(role="tool", content=payload, tool_call_id=call.id))

            logger.info(
                "agent_tool_call",
                extra={
                    "run_id": run_id,
                    "tool": call.name,
                    "ok": invocation.ok,
                    "duration_ms": invocation.duration_ms,
                },
            )

    if truncated and not answer:
        answer = (
            "I stopped before reaching an answer: this question needed more tool calls "
            f"than the configured budget of {max_tool_calls} allows, or ran past "
            f"{timeout_seconds} seconds. The evidence gathered so far is listed below."
        )
        limitations = limitations or "The run was cut short by its budget, so this is incomplete."

    result = AgentResult(
        run_id=run_id,
        question=question,
        answer=answer or "The model returned no answer.",
        claims=claims,
        limitations=limitations,
        evidence=evidence,
        provider=provider.name,
        model=provider.model,
        truncated=truncated,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
        usage=usage,
    )
    await _persist(database, result)
    return result


async def _persist(database: AsyncDatabase[dict[str, Any]], result: AgentResult) -> None:
    """Store the trace. Tool calls and timings only.

    A failure to write a trace must not lose the user's answer, so this is the
    one place a broad catch is right — and it is logged, not swallowed.
    """
    try:
        await database[collections.AGENT_RUNS].insert_one(
            {
                "_id": result.run_id,
                "createdAt": datetime.now(UTC),
                "question": result.question,
                "provider": result.provider,
                "model": result.model,
                "durationMs": result.duration_ms,
                "truncated": result.truncated,
                "usage": result.usage,
                "toolCalls": [
                    {
                        "name": call.name,
                        "arguments": call.arguments,
                        "ok": call.ok,
                        "durationMs": call.duration_ms,
                        "error": call.error,
                    }
                    for call in result.evidence
                ],
            }
        )
    except Exception as exc:
        logger.warning(
            "agent_trace_not_stored",
            extra={"run_id": result.run_id, "error": scrub(str(exc))},
        )


def provider_error_message(exc: ProviderError) -> str:
    """A provider failure, phrased for a user rather than a stack trace."""
    return str(exc)
