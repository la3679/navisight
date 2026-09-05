# Threat model

What could go wrong, what prevents it, and — where a control is weaker than it
looks — a plain statement of that.

Every entry names the mechanism and, where one exists, the test that holds it in
place. Controls that are **shapes in the type system** and controls that are
**rules in a prompt** are marked as such, because those are very different
strengths of guarantee and conflating them is how security claims become
marketing.

---

## Scope

NaviSight is a personal portfolio project. **There is no production deployment,
no hosted instance, and no user data.** The threat model still matters, because
the code is public and the design choices are part of what the project is
demonstrating — and because a system that would be unsafe if deployed is not
made safe by not deploying it.

### Assets

| Asset | Why it matters |
|---|---|
| MongoDB instance | Holds the archive; a hostile query can exhaust it |
| `OPENAI_API_KEY` | A real credential with real billing attached |
| The archive's integrity | A fabricated figure is the product's worst failure |
| Developer machine | Where the CLI, the import, and the tests run |

### Not in scope

Physical access to the developer's machine, a compromised MongoDB host, supply
-chain compromise of a pinned dependency, and anything requiring an attacker who
already has shell access. Also out of scope: AIS itself is unauthenticated by
design — vessels self-report and anyone with a transceiver can broadcast
anything. NaviSight treats every field as claimed rather than verified, but it
cannot fix the protocol.

### Trust boundaries

```
browser ──HTTP──▶ FastAPI ──driver──▶ MongoDB
                     │
                     └──HTTPS──▶ OpenAI     (optional, off by default)
```

The browser **never** reaches MongoDB. The API is the only database client;
there is no client-side connection string and no database credential is ever
sent to a browser.

---

## 1. Injection into the database

### 1.1 A user string becoming a query operator

**Mechanism: typed values, not string interpolation.** Every filter is built
from values that passed a Pydantic model or a FastAPI `Query` constraint. No
user input supplies a MongoDB **operator key**, no filter is assembled by string
concatenation, and `$where` and server-side JavaScript are not used anywhere in
the codebase.

MMSI is the worst case, because it reaches a path parameter. It is constrained
to `^[0-9]{1,16}$` at the route, so it is not a string that could carry an
operator at all.

**Strength: structural.** There is no code path where a user-supplied string is
placed in an operator position.

### 1.2 Regex denial of service

**Partial.** Vessel name search uses an **anchored prefix** regex `/^QUERY/`
against the uppercased `nameNormalized` field, over 16,294 documents. The query
string is length-capped and the collection is small — a scan of it measures
0.99 ms.

**Stated weakness:** the input is not escaped for regex metacharacters. A query
containing `(a+)+` is passed through. The bound that makes this acceptable is
the collection size and the length cap, not the pattern — so if `vessels` ever
grows by orders of magnitude, escape the input. Recorded here rather than
assumed away.

---

## 2. Resource exhaustion

**Mechanism: every bound is declared once, in `app/api/deps.py`, and reused.**
An endpoint cannot be added without them, which is the mechanical form of
SOUL.md §10 rather than a rule someone has to remember.

| Input | Cap |
|---|---|
| Result limit | 200 |
| Map viewport limit | 5,000 |
| Track points | 5,000, then simplified |
| Geo radius | 100 km |
| Time range | `MAX_TIME_RANGE_HOURS` |
| Copilot question | 1,000 characters |
| Copilot tool calls | 8 per run |
| Copilot wall clock | 60 s per run |

A request exceeding a bound gets a 422 naming the parameter, not a truncated
answer.

The most expensive shape — whole-archive analytics — is not reachable as a live
query at all: it is served from four precomputed documents
([ADR-0011](../adr/0011-precompute-whole-archive-analytics.md)).

**Stated weakness: there is no rate limiting and no authentication.** Nothing
stops one client from issuing many bounded requests in parallel. For a local
portfolio project that is acceptable; **for any deployment it is not**, and a
reverse proxy with rate limiting would be the first thing to add. Concurrency
behaviour is also unmeasured — see
[`../performance/BENCHMARKS.md`](../performance/BENCHMARKS.md#5-what-is-not-measured-here).

---

## 3. The AI copilot

Treated in full in [`../ai/AI_SAFETY.md`](../ai/AI_SAFETY.md). The summary, with
the strength of each control:

| Threat | Control | Strength |
|---|---|---|
| Model authors a query | No argument model has a field that could hold one | **structural** |
| Model calls something unlisted | Allow-list checked before dispatch | **structural** |
| Unbounded or expensive call | Field constraints; summaries not rows | **structural** |
| Run never terminates | Budgets enforced by the loop, not requested | **structural** |
| Injection via dataset text | Nothing reachable behind the wall but more allow-listed calls | **structural** |
| Injection via dataset text | Prompt says such text is inert | *prompt only* |
| Fabricated figure | Prompt forbids arithmetic; claims labelled; evidence shown | *prompt + presentation* |
| Credential leak | Read only in the backend; redacted from errors | **structural** |

The load-bearing claim is that **there is no capability behind the wall for an
injection to reach**. The worst an instruction embedded in a vessel name can
achieve is another allow-listed call with validated arguments — which the model
could have made anyway.

**Stated weakness:** a model can still write a fluent sentence that misdescribes
a number a tool returned correctly. The evidence list under every answer is the
control, and it works only if a reader opens it. This is not solved.

The whole feature is **off by default**. With no `LLM_PROVIDER`, nothing reaches
the network.

---

## 4. Secrets

**Mechanism.**

- `OPENAI_API_KEY` is read in exactly one place, `app/config.py`, in the backend
  process only.
- It is never serialized into a response. `agent_factory.describe()` returns a
  provider *name* and model, and nothing else.
- It cannot reach the browser: `NEXT_PUBLIC_*` is a frontend build-time
  namespace, and this variable is never read there.
- SDK errors are passed through `redact()` before they can reach a log or a
  response, because they sometimes echo request headers.
- `.env` is git-ignored; only `.env.example` is tracked, with every value blank.
- **CI runs `gitleaks` over full history** — a credential removed in a later
  commit is still in the repository.

**Tests:** `test_the_message_never_names_a_credential_value`,
`test_status_carries_no_credential_field`,
`test_the_key_is_not_stored_on_a_public_attribute`, plus four redaction tests
asserting the diagnostic survives while the credential does not.

---

## 5. Log injection

**Mechanism: `observability.scrub()`** strips non-printable characters and
truncates to 200 characters before any untrusted value enters a log line. A
crafted vessel name containing newlines cannot forge a log record.

An inbound `X-Request-ID` is honoured so a trace can span frontend and backend —
and is scrubbed and length-capped first, because it is attacker-controlled.

---

## 6. Information disclosure through errors

**Mechanism: one error envelope, and nothing internal in it.** Every failure
returns `{code, message, requestId, details?}`. `message` is written for a person
to read; it never carries a stack trace, a driver error string, or a query.

An unexpected exception is logged **in full server-side** and reported to the
client as a generic `INTERNAL_ERROR` plus the request id to correlate against.

**Tested:** the standard-envelope tests assert the shape and that a 404 for an
unknown vessel leaks nothing beyond the MMSI that was asked for.

---

## 7. Browser-side risks

**No `dangerouslySetInnerHTML` anywhere.** All dataset text — vessel names, call
signs, port names — renders as React children, which escapes by construction.

**CORS is an allow-list**, from `WEB_ORIGIN`, not `*`. Methods and headers are
enumerated rather than wildcarded.

**No third-party map tiles and no third-party 3D models.** The basemap is
bundled Natural Earth data served from our own origin; the harbour scene is
procedural geometry. This avoids a licensing question and a privacy one at the
same time — no viewer's IP address is disclosed to a tile provider by looking at
a map. [`../THIRD_PARTY_ASSETS.md`](../THIRD_PARTY_ASSETS.md).

**Stated weakness: no Content-Security-Policy header is set.** For a local
development app with no third-party script origins that is a small gap, but it
is a gap, and it is the second thing to add before any deployment.

---

## 8. Supply chain

Lockfiles are committed and CI installs with `--frozen-lockfile` / `uv sync`, so
a build cannot silently pick up a new version. Dependencies are deliberately
few — no Redis, no Kafka, no Elasticsearch, no vector database, no agent
framework — because each one is attack surface that must earn its place
(SOUL.md §5, §15).

**Not in scope**, as stated above: a compromise of a pinned dependency itself.
There is no SBOM and no automated vulnerability scanning of dependencies. That
is a real gap for a deployed system.

---

## 9. The dataset

Public data, still handled carefully:

- Never committed. `.gitignore` blocks `ais-*.csv` by name
  ([ADR-0007](../adr/0007-keep-large-ais-data-out-of-git.md)).
- Read-only input. No tool in this repository writes to it.
- Only derived aggregate statistics are published, under `docs/data/`.
- No test ever touches it; integration and E2E tests use synthetic fixtures.

AIS is a public broadcast of vessel positions, not personal data — but small
vessels can be individually identifiable, which is why nothing here republishes
raw positions and why the copilot's tools return bounded summaries rather than
raw tracks.

---

## What would change before a deployment

Stated together so absence is not read as a pass:

1. **Rate limiting and authentication.** Neither exists.
2. **A Content-Security-Policy header.** Not set.
3. **Concurrency measurement.** Every performance figure is a single client
   against an idle server.
4. **Dependency vulnerability scanning and an SBOM.** Neither exists.
5. **Regex escaping in vessel search**, if `vessels` ever grows past the size
   that currently makes it a non-issue.
6. **A read-only MongoDB user for the API.** It does not write outside the
   ingest path and the copilot has no write tool, but least privilege should be
   enforced by the database rather than by the application's good behaviour.

---

## See also

- [`../../SECURITY.md`](../../SECURITY.md) — reporting policy.
- [`../ai/AI_SAFETY.md`](../ai/AI_SAFETY.md) — the copilot in full.
- [ADR-0012](../adr/0012-give-the-copilot-tools-not-a-query-language.md) — why
  the model cannot author a query.
- [ADR-0008](../adr/0008-use-historical-replay-not-live-simulation.md) — why the
  data is never presented as live.
