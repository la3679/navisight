# ADR-0012: Give the copilot tools, not a query language

- **Status:** Accepted
- **Date:** 2026-09-04

## Context

NaviSight's copilot answers natural-language questions about a 5.9M-document
AIS archive. The obvious implementation — and the one most "AI + database"
demos ship — is text-to-query: hand the model the schema, let it write a
MongoDB aggregation pipeline, execute it, summarise the result.

That approach has a property worth stating plainly: **the model's output is
executed**. Everything protecting the database is then a filter applied after
the model has already decided what to run. Every such filter is a blocklist —
reject `$where`, reject `$function`, reject writes, cap `$limit` — and a
blocklist is a claim that the author enumerated every dangerous construct in a
query language that has hundreds and gains more with each release. `$lookup`
into an unintended collection, `$merge` writing results back out, `$out`
replacing a collection, an unindexed `$regex` over 5.9M documents: each is a
separate thing to have remembered.

It also breaks the product's central promise. SOUL.md §9 requires every figure
shown to a user to be traceable to something that was measured. A generated
pipeline is auditable only by someone who reads MongoDB aggregation syntax, and
a subtly wrong `$group` produces a confidently wrong number that looks exactly
like a right one.

## Decision

**The model selects from a fixed registry of typed functions. It never authors
a query.**

`app/agent/tools.py` declares eleven tools. Each has a Pydantic argument model,
and the loop in `app/agent/runner.py` dispatches only through
`tools.execute()`, which refuses any name not in the registry before anything
is dispatched.

The load-bearing part is what the argument models *do not contain*. No tool
accepts a filter document, an aggregation pipeline, a projection, a sort, a
collection name, a field path, a file path, a URL, or a string that is
evaluated. There is nowhere to put a query. That is a property of the types,
not a check performed at runtime — the forbidden thing is unrepresentable
rather than merely disallowed, so it cannot be forgotten during a later edit.

Bounds are declared the same way. `MAX_ROWS = 25` and `MAX_RADIUS_KM = 100`
appear in the field constraints, so an out-of-range argument fails validation
before reaching a service, and the failure is reported back to the model as a
tool error it can act on.

Two further consequences of the shape:

- **Tools call the same service layer as the HTTP API** (`app/services/`), so
  the copilot cannot see data a normal user could not, and it cannot reach it
  by a path that skipped a bound.
- **Tools return bounded, structured data, not rows.** `get_vessel_track_summary`
  returns a count, a time span, a bounding box, and speed min/max/mean — never
  the 1,305 raw points. Sending a track through a language model would cost a
  fortune in tokens and invite exactly the arithmetic the system prompt
  forbids.

The evidence trail falls out of this for free: the registry is a closed list of
named operations with typed arguments, so `POST /api/v1/agent/ask` can return
every call it made, with its arguments and its result, and a user can check the
prose against them. `tests/integration/test_agent.py` asserts the property over
the whole registry, so adding a tool with a `pipeline` field fails the suite.

## Alternatives considered

**Text-to-query with a validator.** Rejected. The security argument is above;
the practical one is that the validator is never finished. Each new MongoDB
operator is a new thing to have anticipated, and a missed one is a breach, not
a bug. The version where the property holds by construction is also *less*
code.

**A read-only database user, with the model free to query.** Genuinely
attractive, and it does close the write vector. Rejected because it closes only
that one: a read-only user can still issue a `$regex` collection scan that
pins the server, or a `$lookup` that assembles data no endpoint exposes. It
also leaves the traceability problem untouched — the answer is still backed by
a pipeline the user cannot read. Worth adopting *in addition* in a deployment;
not a substitute.

**A larger, more general tool set** — a generic "aggregate by field X grouped by
field Y". Rejected: `field` is a query language with two words in it. Once the
model chooses field paths, every argument needs an allow-list, and the
allow-list is a schema written twice.

**Let the model do arithmetic on tool results.** Rejected, and the system prompt
forbids it explicitly. A model asked "how many cargo vessels" will add up a
list it was shown and be subtly wrong. Every count in this system comes from a
tool that counted.

## Consequences

**Accepted costs:**

- **The copilot can only answer questions someone anticipated.** "How many
  vessels changed course by more than 90° in an hour?" has no tool, so the
  honest answer is that it cannot be answered — which the prompt requires it to
  say rather than approximate. This is a real capability ceiling and the demo
  is smaller for it.
- **Every new question shape is a code change**, with a schema, a test, and a
  review. Slower than a prompt edit, deliberately.
- **Eleven tool schemas are sent on every provider turn**, costing input tokens
  on each step of the loop.
- **The registry is a second surface that can drift** from the services it
  wraps. It is thin, and mypy `--strict` covers it, but it is duplication.

**Benefits realised:**

- No model-authored query can reach MongoDB, because there is no argument that
  could carry one — asserted over the whole registry in
  `test_no_tool_accepts_a_query_pipeline_or_field_path`.
- Every number in an answer traces to a named call with visible arguments,
  which is what `/copilot`'s evidence list renders.
- The agent's behaviour is testable without a model: 42 integration tests run
  against the deterministic provider and assert the bounds, the refusals, the
  claim labelling, and the trace.
- Prompt injection through dataset text is contained by shape rather than by
  detection. A vessel named `IGNORE PREVIOUS INSTRUCTIONS…` is a string in a
  tool result; the worst it can request is another allow-listed call with
  validated arguments.

## References

- [`../ai/AI_SAFETY.md`](../ai/AI_SAFETY.md) — the full threat treatment.
- `apps/api/app/agent/tools.py` — the registry.
- `apps/api/app/agent/prompts.py` — the grounding rules the tools enforce.
- SOUL.md §8 (AI is a feature, not the point) and §9 (evidence over fluency).
