# ADR-0013: A hand-written agent loop instead of an orchestration framework

- **Status:** Accepted
- **Date:** 2026-09-04

## Context

[ADR-0012](0012-give-the-copilot-tools-not-a-query-language.md) settled *what*
the copilot may do: select from a fixed registry of typed functions, never
author a query. This record settles the separate question of *what runs that
loop* — LangGraph, LangChain, the OpenAI Agents SDK, or application code.

The expectation is worth naming, because a reader scanning this repository for
"agentic AI" will look for LangGraph and not find it. That is a decision, not an
omission, and this file is where it is argued rather than assumed.

What the loop actually has to do is small and completely specified:

1. Send the conversation and the tool schemas to a provider.
2. If it named tools, run each allow-listed one and append its result.
3. Stop at `AGENT_MAX_TOOL_CALLS` or `AGENT_TIMEOUT_SECONDS`, whichever comes
   first, and say so in the answer.
4. Parse the final message into an answer, labelled claims, and limitations.
5. Record every call — name, validated arguments, duration, result — and persist
   the trace as tool calls and timings only.

That is `app/agent/runner.py`: 290 lines including its docstrings, over a
provider protocol (`app/agent/provider.py`) that is 79 lines and has one method.

## Decision

**No orchestration framework. The loop is application code, and the provider SDK
is the only AI dependency.**

`apps/api/pyproject.toml` declares the AI extra as exactly one package,
`openai>=1.60`. Swapping providers means writing one class against the
`LLMProvider` protocol; two already exist, and one of them —
`providers/mock.py` — is deterministic and offline, which is what makes the
copilot's behaviour testable at all.

## Rationale

**The guarantees are the product, and they must be readable.** Termination under
a budget, allow-listing, and a complete evidence trail are the three things this
feature claims. Each is a handful of lines in one file that a reviewer can read
end to end in a few minutes. Expressed as a graph of nodes with a checkpointer
and a state schema, the same guarantees become properties of a framework's
execution semantics — still true, probably, but no longer *shown*. A reviewer
would have to trust the framework's recursion limit rather than read ours.

**The failure this project actually hit was a framework hiding a failure.** The
blank map ([ADR-0010](0010-serve-the-maplibre-worker-from-our-own-origin.md))
was a `new Worker()` on a 404 that did not throw, inside a library, announcing
itself only as one console line. The lesson recorded then was that an
abstraction which swallows a failure mode costs more than the code it saved.

**A framework earns its place at a complexity this loop does not have.** The
cases for LangGraph are real ones: cyclic multi-agent graphs, human-in-the-loop
interrupts, durable execution resumed across processes, time-travel over a
persisted state graph. NaviSight has one agent, one linear tool-calling cycle,
no interrupts, and a run that lives for at most sixty seconds inside a single
request. Adopting a graph runtime for a `while` loop would be the exact move
SOUL.md §5 and §15 forbid: adding a dependency to look experienced.

**It is a dependency the deployment does not need.** The AI extra installs one
package. LangGraph brings `langchain-core` and its transitive graph, which the
non-AI ninety per cent of NaviSight would carry for nothing.

## Alternatives considered

**LangGraph.** Rejected for the reasons above, and one more: its value is
concentrated in durable, resumable, multi-actor state, and this run is
stateless, single-actor, and shorter than a request timeout. Nothing here would
use the parts that make it good.

**LangChain (agent executors).** Rejected more firmly. It solves prompt and tool
plumbing that Pydantic and the provider's own tool-calling API already solve
here, and its abstraction layers are precisely what would make the bounds harder
to audit.

**The OpenAI Agents SDK.** Rejected because it would tie the loop to one vendor
at the exact layer this design keeps vendor-neutral. The provider boundary
exists so that swapping the model cannot weaken the tool registry, the bounds,
or the evidence collection; a vendor's agent runtime moves the loop *inside* the
vendor.

## Consequences

**Accepted costs:**

- **Things a framework gives free are not implemented.** No streaming of partial
  answers, no persisted resumable state, no built-in retry or backoff, no
  parallel tool execution, no tracing integration. Each would be a deliberate
  addition here.
- **The retry story is thin.** A transient provider error ends the run with a
  503 and a message. A framework would have retried.
- **This is one more loop in the world that a maintainer has to read**, rather
  than a shape they might already know.
- **The recruiter-facing cost is real**, and stated plainly: "LangGraph" is a
  keyword people search for, and this repository does not contain it.

**Benefits realised:**

- The budget is enforced in code you can point at — and that mattered: the real
  OpenAI provider returns *parallel* tool calls, and a cap checked only between
  turns let one turn run ten tools against a budget of eight. It was a
  four-line fix in a loop that is readable, with a regression test
  (`TestParallelToolCallsRespectTheBudget`) that pins the shape.
- 42 integration tests exercise the loop against a deterministic provider, with
  no key, no network, and no spend.
- The AI extra is one package, and the application starts, serves, and passes
  its whole non-AI suite without it installed.

## References

- `apps/api/app/agent/runner.py` — the loop.
- `apps/api/app/agent/provider.py` — the boundary a provider implements.
- [ADR-0012](0012-give-the-copilot-tools-not-a-query-language.md) — what the
  loop is allowed to run.
- SOUL.md §5 (justify every moving part) and §15 (dependency discipline).
