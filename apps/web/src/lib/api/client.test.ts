/**
 * The API client's failure classification.
 *
 * The whole reason `ApiClientError` carries a `kind` is that the UI branches on
 * it to choose a state: a 503 with `AI_NOT_CONFIGURED` renders setup
 * instructions, a 503 from a dead database renders "start MongoDB", and a
 * thrown fetch renders "start the API". Get the classification wrong and the
 * user is told to fix the wrong thing — so it is asserted here rather than
 * assumed from reading the switch.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiClientError, api } from "./client";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function apiError(code: string, message = "message"): unknown {
  return { error: { code, message, requestId: "req-1" } };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("failure classification", () => {
  it("reads an unconfigured copilot as not_configured, not as an outage", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(503, apiError("AI_NOT_CONFIGURED"))),
    );

    const failure = await api.ask("anything at all").catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiClientError);
    // 503 would otherwise fall through to "unavailable", which would tell the
    // user to restart a database that is working perfectly well.
    expect((failure as ApiClientError).kind).toBe("not_configured");
    expect((failure as ApiClientError).isRetryable).toBe(false);
  });

  it("reads a dead database as unavailable, and as worth retrying", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(503, apiError("DATABASE_UNAVAILABLE"))),
    );

    const failure = (await api
      .agentStatus()
      .catch((error: unknown) => error)) as ApiClientError;

    expect(failure.kind).toBe("unavailable");
    expect(failure.isRetryable).toBe(true);
  });

  it("reads an unreachable API as a network failure, and names the fix", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    const failure = (await api
      .agentStatus()
      .catch((error: unknown) => error)) as ApiClientError;

    expect(failure.kind).toBe("network");
    expect(failure.message).toContain("NEXT_PUBLIC_API_BASE_URL");
  });

  it("reports a response that does not match the schema, naming the field", async () => {
    // `configured` is required and a boolean. A string is exactly the kind of
    // drift that would otherwise surface three components deep.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(200, {
          configured: "yes",
          provider: "openai",
          model: "gpt-4o-mini",
          deterministic: false,
          maxToolCalls: 8,
          timeoutSeconds: 60,
          tools: [],
        }),
      ),
    );

    const failure = (await api
      .agentStatus()
      .catch((error: unknown) => error)) as ApiClientError;

    expect(failure.kind).toBe("contract");
    expect(failure.message).toContain("configured");
  });
});

describe("abort", () => {
  it("rethrows an abort instead of blaming the network", async () => {
    // The user cancelling a slow question is not an outage, and reporting it as
    // "could not reach the API" would blame the network for their own click.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new DOMException("The operation was aborted.", "AbortError")),
    );

    const failure = await api
      .ask("a slow question", AbortSignal.abort())
      .catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(DOMException);
    expect((failure as DOMException).name).toBe("AbortError");
    expect(failure).not.toBeInstanceOf(ApiClientError);
  });
});

describe("asking", () => {
  it("sends the question as a JSON body, never as a query parameter", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, {
        runId: "abc",
        question: "q",
        answer: "a",
        claims: [{ text: "t", kind: "observed" }],
        limitations: "",
        evidence: [],
        provider: "mock",
        model: "deterministic-stub",
        truncated: false,
        durationMs: 12,
        usage: {},
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const answer = await api.ask("How many vessels?");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/agent/ask");
    expect(url).not.toContain("How");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ question: "How many vessels?" });
    expect(answer.claims[0]?.kind).toBe("observed");
  });

  it("rejects a claim kind outside the four the product defines", async () => {
    // The server downgrades an unrecognised kind before it ever gets here. If
    // one arrives anyway, the honest outcome is a contract error rather than a
    // label the UI has no meaning for.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(200, {
          runId: "abc",
          question: "q",
          answer: "a",
          claims: [{ text: "t", kind: "certain" }],
          limitations: "",
          evidence: [],
          provider: "mock",
          model: "",
          truncated: false,
          durationMs: 1,
          usage: {},
        }),
      ),
    );

    const failure = (await api.ask("q").catch((error: unknown) => error)) as ApiClientError;

    expect(failure.kind).toBe("contract");
  });
});
