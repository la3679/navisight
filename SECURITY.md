# Security Policy

NaviSight is a personal portfolio project. It is not a hosted service and has
no production deployment, so there is no live system to compromise. The
policies below still apply to the code, because the code is public and because
the design choices are part of what the project is demonstrating.

## Reporting a vulnerability

Open a **private security advisory** on the repository
(`Security` → `Report a vulnerability`) rather than a public issue. Please
include what you did, what happened, and what you expected.

There is no bounty and no formal SLA. Reports are handled on a best-effort
basis.

## Security model in brief

The full threat model lives in
[`docs/security/THREAT_MODEL.md`](docs/security/THREAT_MODEL.md). The
load-bearing decisions:

- **The browser never reaches MongoDB.** The API is the only database client.
  There is no client-side connection string, and no database credential is ever
  sent to a browser.
- **No secret is exposed to the client.** `NEXT_PUBLIC_*` variables carry only
  values that are safe to publish (for example the API base URL).
- **All input is bounded.** Result limits, geospatial radii, time ranges, page
  sizes, and trajectory point counts have enforced server-side maximums. There
  is no way to ask the API for an unbounded scan.
- **No user string becomes a query operator.** Filters are constructed from
  validated, typed values; user input never supplies a MongoDB operator key,
  and `$where` / JavaScript evaluation is not used anywhere.
- **The LLM cannot query the database.** The AI copilot selects from a fixed
  allow-list of typed application functions with validated arguments. It cannot
  author a query or an aggregation pipeline, cannot execute code, and has no
  shell, filesystem, or outbound network access. See
  [`docs/ai/AI_SAFETY.md`](docs/ai/AI_SAFETY.md).
- **Dataset text is data, not instruction.** Vessel names, call signs, and port
  names are untrusted content. Text arriving from the database cannot alter
  system rules, tool constraints, or grounding requirements — prompt-injection
  attempts through AIS metadata are an explicitly tested case.
- **Secrets stay out of Git.** Only `.env.example` is tracked; `.env` and key
  material are ignored. CI runs a secret scan.

## Handling the dataset

The AIS source file is public data, but it is still treated carefully:

- It is never committed, and `.gitignore` blocks `ais-*.csv` by name.
- It is read-only input. No tool in this repository writes to it.
- Only derived aggregate statistics are published, under `docs/data/`.

## Supported versions

The `main` branch is the only supported version.
