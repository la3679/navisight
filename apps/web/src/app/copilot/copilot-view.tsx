"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Clock,
  CornerDownLeft,
  FlaskConical,
  Send,
  Sparkles,
  Wrench,
  X,
} from "lucide-react";
import * as React from "react";

import {
  Badge,
  Button,
  Card,
  CardBody,
  CardDescription,
  CardHeader,
  CardTitle,
  Separator,
  Skeleton,
} from "@/components/ui/primitives";
import { ErrorState, LoadingPanel, NotConfiguredState } from "@/components/ui/states";
import { ApiClientError, api } from "@/lib/api/client";
import type { AgentAnswer, AgentStatus } from "@/lib/api/types";
import { cn } from "@/lib/utils";
import { ClaimKindLegend, ClaimList } from "./claim-list";
import { EvidenceList } from "./evidence-list";

/**
 * The maritime intelligence copilot.
 *
 * The screen is built around one idea: **an answer is worth exactly as much as
 * the evidence under it**. So the layout does not present prose and then bury
 * the workings — the answer, the labelled claims, the limitations, and the tool
 * calls are one continuous artefact, in that order, and none of them is opt-in.
 *
 * What that rules out, deliberately:
 *
 * - **No chat transcript.** A scrolling conversation invites the reader to
 *   accumulate trust across turns and stop checking. Each question produces one
 *   self-contained, inspectable result.
 * - **No streaming token animation.** It performs thinking. The tools are what
 *   is actually happening, and there is no honest way to animate a database
 *   aggregation as a typing effect.
 * - **No hidden reasoning.** Not collected, not stored, not displayed. What is
 *   shown is what ran.
 *
 * The not-configured state is the shipped default and gets real design, not a
 * greyed-out box: the copilot is optional (SOUL.md §8), the rest of NaviSight
 * works without it, and a user should be able to read exactly what it would be
 * allowed to do before deciding to turn it on.
 */

const EXAMPLE_QUESTIONS = [
  "What does this archive contain, and what period does it cover?",
  "Which vessel types are most common?",
  "How did traffic vary across the day?",
  "How do observations divide across speed bands?",
] as const;

const QUESTION_MAX_LENGTH = 1_000;

function isNotConfigured(error: unknown): boolean {
  return error instanceof ApiClientError && error.kind === "not_configured";
}

/* ------------------------------------------------------------- Not configured */

function NotConfigured({ status }: { status: AgentStatus | undefined }) {
  return (
    <div className="space-y-5">
      <NotConfiguredState title="No model provider is configured">
        <p>
          The copilot is optional. Every other part of NaviSight — the map, the vessel history,
          the analytics, the dataset report — works without it, and nothing here is degraded by
          leaving it off.
        </p>
        <p className="mt-2">
          Set a provider in <code>.env</code> at the repository root and restart the API:
        </p>
        <pre className="mt-2 overflow-x-auto rounded bg-[var(--ns-surface-raised)] p-2 text-left font-[family-name:var(--font-mono)] text-[11px]">
          {`# a real model
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=...

# or, offline and free, for a deterministic stub
LLM_PROVIDER=mock`}
        </pre>
        <p className="mt-2">
          The key is read only by the backend. It is never logged, never returned in a response,
          and never reaches the browser.
        </p>
      </NotConfiguredState>

      {status ? <ToolCatalogue status={status} /> : null}
    </div>
  );
}

/* ------------------------------------------------------------ Tool catalogue */

function ToolCatalogue({ status }: { status: AgentStatus }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Wrench aria-hidden="true" className="size-4 text-[var(--ns-text-muted)]" />
          What the copilot is allowed to do
        </CardTitle>
        <CardDescription>
          The complete list — {status.tools.length} functions, published so you can read the
          boundary rather than infer it from what gets refused. The model chooses a name from
          this list and supplies arguments the server validates. It cannot write a database
          query: no tool accepts a filter, a pipeline, a field path, or a URL, so there is
          nowhere to put one.
        </CardDescription>
      </CardHeader>
      <CardBody>
        <dl className="space-y-2.5">
          {status.tools.map((tool) => (
            <div key={tool.name} className="grid gap-0.5 sm:grid-cols-[15rem_1fr] sm:gap-3">
              <dt className="font-[family-name:var(--font-mono)] text-xs text-[var(--ns-accent)]">
                {tool.name}
              </dt>
              <dd className="text-xs leading-relaxed text-[var(--ns-text-muted)]">
                {tool.description}
              </dd>
            </div>
          ))}
        </dl>

        <Separator className="my-4" />

        <p className="text-[11px] leading-relaxed text-[var(--ns-text-muted)]">
          Every run is capped at <strong>{status.maxToolCalls} tool calls</strong> and{" "}
          <strong>{status.timeoutSeconds} seconds</strong>. Those limits are enforced by the
          server, not requested of the model, so a run that reaches one stops and says so.
        </p>
      </CardBody>
    </Card>
  );
}

/* -------------------------------------------------------------- Provider note */

function ProviderNotice({ status }: { status: AgentStatus }) {
  if (status.deterministic) {
    return (
      <div
        role="note"
        className="flex items-start gap-2 rounded-md border border-[color-mix(in_oklab,var(--ns-warning)_35%,transparent)] bg-[color-mix(in_oklab,var(--ns-warning)_10%,transparent)] px-3 py-2.5"
      >
        <FlaskConical
          aria-hidden="true"
          className="mt-0.5 size-4 shrink-0 text-[var(--ns-warning)]"
        />
        <p className="text-xs leading-relaxed text-[var(--ns-text-secondary)]">
          <strong className="text-[var(--ns-text)]">
            A deterministic stub is answering, not a model.
          </strong>{" "}
          It matches a keyword, calls one tool, and reports the result verbatim. It never
          paraphrases, never interprets, and never produces a number the tools did not — so it
          cannot answer a multi-step question. Everything below is still real data from real
          tool calls.
        </p>
      </div>
    );
  }

  return (
    <p className="text-[11px] text-[var(--ns-text-muted)]">
      Answered by <span className="text-[var(--ns-text-secondary)]">{status.provider}</span>
      {status.model ? (
        <>
          {" "}
          / <span className="font-[family-name:var(--font-mono)]">{status.model}</span>
        </>
      ) : null}
      . Language models make confident mistakes; the evidence under each answer is how you check
      this one.
    </p>
  );
}

/* -------------------------------------------------------------------- Answer */

function AnswerCard({ answer }: { answer: AgentAnswer }) {
  const seconds = (answer.durationMs / 1000).toFixed(1);
  const tokens = answer.usage.total_tokens ?? answer.usage.totalTokens ?? null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-normal text-[var(--ns-text-secondary)]">
          <span className="text-[var(--ns-text-muted)]">You asked:</span> {answer.question}
        </CardTitle>
      </CardHeader>

      <CardBody className="space-y-5">
        {answer.truncated ? (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-[color-mix(in_oklab,var(--ns-warning)_35%,transparent)] bg-[color-mix(in_oklab,var(--ns-warning)_10%,transparent)] px-3 py-2.5"
          >
            <AlertTriangle
              aria-hidden="true"
              className="mt-0.5 size-4 shrink-0 text-[var(--ns-warning)]"
            />
            <p className="text-xs leading-relaxed text-[var(--ns-text-secondary)]">
              This run stopped on its budget rather than because it finished. The answer is
              incomplete, and the evidence below is everything it managed to gather.
            </p>
          </div>
        ) : null}

        <p className="text-sm leading-relaxed whitespace-pre-wrap text-[var(--ns-text)]">
          {answer.answer}
        </p>

        <section aria-labelledby={`claims-${answer.runId}`}>
          <h3
            id={`claims-${answer.runId}`}
            className="mb-2 text-[11px] tracking-wide text-[var(--ns-text-muted)] uppercase"
          >
            Claims, and how strongly each is supported
          </h3>
          <ClaimList claims={answer.claims} />
        </section>

        {answer.limitations ? (
          <section aria-labelledby={`limits-${answer.runId}`}>
            <h3
              id={`limits-${answer.runId}`}
              className="mb-1.5 text-[11px] tracking-wide text-[var(--ns-text-muted)] uppercase"
            >
              What this answer cannot establish
            </h3>
            <p className="text-xs leading-relaxed text-[var(--ns-text-secondary)]">
              {answer.limitations}
            </p>
          </section>
        ) : null}

        <section aria-labelledby={`evidence-${answer.runId}`}>
          <h3
            id={`evidence-${answer.runId}`}
            className="mb-2 flex flex-wrap items-baseline gap-x-2 text-[11px] tracking-wide text-[var(--ns-text-muted)] uppercase"
          >
            Evidence
            <span className="tracking-normal normal-case">
              — {answer.evidence.length} tool{answer.evidence.length === 1 ? "" : "s"} ran. Open
              any one to see exactly what it was asked and what it returned.
            </span>
          </h3>
          <EvidenceList evidence={answer.evidence} />
        </section>

        <footer className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-[var(--ns-border)] pt-3 text-[10px] text-[var(--ns-text-muted)]">
          <span className="inline-flex items-center gap-1">
            <Clock aria-hidden="true" className="size-3" />
            {seconds} s
          </span>
          <span>
            {answer.provider}
            {answer.model ? ` / ${answer.model}` : ""}
          </span>
          {tokens !== null ? <span>{tokens.toLocaleString()} tokens</span> : null}
          <span className="font-[family-name:var(--font-mono)]">
            run {answer.runId.slice(0, 12)}
          </span>
        </footer>
      </CardBody>
    </Card>
  );
}

/* ---------------------------------------------------------------- Ask form */

function AskForm({
  status,
  pending,
  onAsk,
  onCancel,
}: {
  status: AgentStatus;
  pending: boolean;
  onAsk: (question: string) => void;
  onCancel: () => void;
}) {
  const [question, setQuestion] = React.useState("");
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  const trimmed = question.trim();
  const tooLong = question.length > QUESTION_MAX_LENGTH;
  const canSubmit = trimmed.length >= 3 && !tooLong && !pending;

  function submit() {
    if (!canSubmit) return;
    onAsk(trimmed);
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      className="space-y-2"
    >
      <label htmlFor="copilot-question" className="sr-only">
        Ask a question about the archived AIS data
      </label>
      <textarea
        id="copilot-question"
        ref={textareaRef}
        value={question}
        onChange={(event) => setQuestion(event.target.value)}
        onKeyDown={(event) => {
          // Enter sends; Shift+Enter is a newline. Both are announced below.
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
        rows={3}
        maxLength={QUESTION_MAX_LENGTH + 100}
        disabled={pending}
        placeholder="Ask about the archived day — what it holds, which vessels, what traffic looked like…"
        aria-describedby="copilot-question-hint"
        className={cn(
          "w-full resize-y rounded-md border border-[var(--ns-border)] bg-[var(--ns-surface-raised)]",
          "px-3 py-2.5 text-sm leading-relaxed text-[var(--ns-text)]",
          "transition-colors placeholder:text-[var(--ns-text-muted)]",
          "hover:border-[var(--ns-border-strong)] disabled:opacity-60",
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--ns-accent)]",
          tooLong && "border-[var(--ns-critical)]",
        )}
      />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <p id="copilot-question-hint" className="text-[11px] text-[var(--ns-text-muted)]">
          <CornerDownLeft aria-hidden="true" className="mr-1 inline size-3 align-[-2px]" />
          Enter to ask, Shift+Enter for a new line. Capped at {status.maxToolCalls} tool calls
          and {status.timeoutSeconds} s.
          {tooLong ? (
            <span className="ml-1 text-[var(--ns-critical)]">
              {question.length} of {QUESTION_MAX_LENGTH} characters — too long to send.
            </span>
          ) : null}
        </p>

        <div className="flex items-center gap-2">
          {pending ? (
            <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
              <X aria-hidden="true" />
              Cancel
            </Button>
          ) : null}
          <Button type="submit" variant="primary" size="sm" disabled={!canSubmit}>
            <Send aria-hidden="true" />
            {pending ? "Asking…" : "Ask"}
          </Button>
        </div>
      </div>
    </form>
  );
}

/* ------------------------------------------------------------------- Pending */

function PendingAnswer() {
  return (
    <Card>
      <CardBody className="space-y-3" role="status" aria-live="polite">
        <p className="text-xs text-[var(--ns-text-muted)]">
          Calling tools. Nothing is being generated yet — the archive is being read.
        </p>
        <Skeleton className="h-4 w-5/6" />
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-16 w-full" />
        <span className="sr-only">Waiting for the copilot…</span>
      </CardBody>
    </Card>
  );
}

/* ---------------------------------------------------------------------- View */

export function CopilotView() {
  const controllerRef = React.useRef<AbortController | null>(null);

  const status = useQuery({
    queryKey: ["agent", "status"],
    queryFn: () => api.agentStatus(),
    retry: false,
  });

  const ask = useMutation({
    mutationFn: (question: string) => {
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      return api.ask(question, controller.signal);
    },
    retry: false,
  });

  React.useEffect(() => () => controllerRef.current?.abort(), []);

  const header = (
    <header>
      <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
        <Sparkles aria-hidden="true" className="size-5 text-[var(--ns-accent)]" />
        Copilot
      </h1>
      <p className="mt-1 max-w-2xl text-sm text-[var(--ns-text-secondary)]">
        Ask about the archived AIS day. Every answer shows the tool calls it was built from and
        labels how strongly each claim is supported, so you can check it rather than trust it.
      </p>
    </header>
  );

  if (status.isLoading) {
    return (
      <div className="mx-auto max-w-4xl space-y-5 p-4 md:p-6">
        {header}
        <LoadingPanel />
      </div>
    );
  }

  if (status.isError) {
    return (
      <div className="mx-auto max-w-4xl space-y-5 p-4 md:p-6">
        {header}
        <ErrorState error={status.error} onRetry={() => void status.refetch()} />
      </div>
    );
  }

  const agent = status.data;

  if (!agent || !agent.configured) {
    return (
      <div className="mx-auto max-w-4xl space-y-5 p-4 md:p-6">
        {header}
        <NotConfigured status={agent} />
      </div>
    );
  }

  // An abort is the user's own cancellation, not a failure worth an error card.
  const failure =
    ask.error instanceof DOMException && ask.error.name === "AbortError" ? null : ask.error;

  return (
    <div className="mx-auto max-w-4xl space-y-5 p-4 md:p-6">
      {header}

      <ProviderNotice status={agent} />

      <AskForm
        status={agent}
        pending={ask.isPending}
        onAsk={(question) => ask.mutate(question)}
        onCancel={() => controllerRef.current?.abort()}
      />

      {!ask.isPending && !ask.data && !failure ? (
        <Card>
          <CardHeader>
            <CardTitle>Questions the tools can answer</CardTitle>
            <CardDescription>
              The copilot can only answer what a tool covers. A question outside that — “why did
              this vessel slow down?”, “where was it heading?” — has no tool, and the honest
              answer is that it cannot be established from AIS.
            </CardDescription>
          </CardHeader>
          <CardBody className="space-y-4">
            <ul className="flex flex-wrap gap-2">
              {EXAMPLE_QUESTIONS.map((example) => (
                <li key={example} className="max-w-full">
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    onClick={() => ask.mutate(example)}
                    // These chips carry whole sentences, not labels. The Button
                    // primitive is nowrap by default, which is right for a button
                    // and wrong here: at 375 px the longest one pushed the page
                    // 20 px wider than the viewport and the whole document
                    // scrolled sideways.
                    className="h-auto max-w-full py-1.5 text-left whitespace-normal"
                  >
                    {example}
                  </Button>
                </li>
              ))}
            </ul>

            <Separator />

            <div>
              <p className="mb-2 text-[11px] tracking-wide text-[var(--ns-text-muted)] uppercase">
                Every claim carries one of four labels
              </p>
              <ClaimKindLegend />
            </div>
          </CardBody>
        </Card>
      ) : null}

      {ask.isPending ? <PendingAnswer /> : null}

      {failure ? (
        isNotConfigured(failure) ? (
          <NotConfigured status={agent} />
        ) : (
          <ErrorState error={failure} onRetry={() => ask.reset()} />
        )
      ) : null}

      {ask.data && !ask.isPending ? <AnswerCard answer={ask.data} /> : null}

      {ask.data || failure ? <ToolCatalogue status={agent} /> : null}

      <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-[var(--ns-text-muted)]">
        <Badge tone="neutral" className="shrink-0">
          archive
        </Badge>
        <span>
          The copilot reads one recorded day and nothing else. It has no live feed, no outside
          knowledge of these vessels, and no way to say where a ship is now — only where it was
          observed, and when.
        </span>
      </p>
    </div>
  );
}
