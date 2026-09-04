"use client";

import { AlertTriangle, ChevronRight, Check } from "lucide-react";
import * as React from "react";

import { Badge } from "@/components/ui/primitives";
import type { AgentToolCall } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * The evidence behind an answer: every tool call, its arguments, its result.
 *
 * This is the component that makes the copilot checkable rather than merely
 * fluent. An answer without it is a claim about a 5.9M-document archive that
 * the reader has no way to verify, which is precisely the failure SOUL.md §9
 * calls the worst one for this product.
 *
 * Three choices worth stating:
 *
 * - **Nothing is hidden behind a summary.** Arguments and results render in
 *   full, as JSON. Prettifying them into prose would mean paraphrasing
 *   evidence, and a paraphrase is the thing being checked.
 * - **Collapsed by default, but present.** The list of calls is always visible;
 *   only each payload folds away. A user learns that four tools ran without
 *   opening anything, and can open any one of them.
 * - **Failures are shown, not filtered.** A refused tool call is evidence too —
 *   it is how a reader sees that the model asked for something outside the
 *   registry and was told no.
 *
 * `<details>`/`<summary>` rather than a custom disclosure: it is keyboard
 * operable, announced correctly, and findable by the browser's own in-page
 * search when collapsed.
 */

function Payload({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="min-w-0">
      <p className="mb-1 text-[10px] uppercase tracking-wide text-[var(--ns-text-muted)]">
        {label}
      </p>
      <pre
        className="max-h-64 overflow-auto rounded border border-[var(--ns-border)]
                   bg-[var(--ns-bg)] p-2 font-[family-name:var(--font-mono)]
                   text-[11px] leading-relaxed text-[var(--ns-text-secondary)]"
      >
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

function ToolCallRow({ call, index }: { call: AgentToolCall; index: number }) {
  return (
    <li>
      <details className="group rounded-md border border-[var(--ns-border)] bg-[var(--ns-surface)]">
        <summary
          className={cn(
            "flex cursor-pointer list-none items-center gap-2 rounded-md px-3 py-2",
            "hover:bg-[var(--ns-surface-raised)]",
            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--ns-accent)]",
          )}
        >
          <ChevronRight
            aria-hidden="true"
            className="size-3.5 shrink-0 text-[var(--ns-text-muted)] transition-transform
                       group-open:rotate-90"
          />
          <span className="shrink-0 font-[family-name:var(--font-mono)] text-[11px] tabular text-[var(--ns-text-muted)]">
            {index + 1}
          </span>
          <span className="min-w-0 flex-1 truncate font-[family-name:var(--font-mono)] text-xs text-[var(--ns-text)]">
            {call.name}
          </span>
          {call.ok ? (
            <Check aria-hidden="true" className="size-3.5 shrink-0 text-[var(--ns-good)]" />
          ) : (
            <Badge tone="warning">refused</Badge>
          )}
          <span className="shrink-0 font-[family-name:var(--font-mono)] text-[10px] tabular text-[var(--ns-text-muted)]">
            {call.durationMs.toFixed(0)} ms
          </span>
        </summary>

        <div className="space-y-3 border-t border-[var(--ns-border)] px-3 py-3">
          <Payload label="Arguments" value={call.arguments} />
          {call.ok ? (
            <Payload label="Result" value={call.result} />
          ) : (
            <div>
              <p className="mb-1 text-[10px] uppercase tracking-wide text-[var(--ns-text-muted)]">
                Why it was refused
              </p>
              <p className="text-xs leading-relaxed text-[var(--ns-warning)]">{call.error}</p>
            </div>
          )}
        </div>
      </details>
    </li>
  );
}

export function EvidenceList({ evidence }: { evidence: AgentToolCall[] }) {
  if (evidence.length === 0) {
    return (
      <p className="flex items-start gap-1.5 text-xs leading-relaxed text-[var(--ns-text-muted)]">
        <AlertTriangle
          aria-hidden="true"
          className="mt-px size-3 shrink-0 text-[var(--ns-warning)]"
        />
        <span>
          No tool ran for this answer, so nothing in it was read from the archive. Treat it
          as unsupported.
        </span>
      </p>
    );
  }

  return (
    <ul className="space-y-1.5">
      {evidence.map((call, index) => (
        <ToolCallRow key={`${call.name}-${index}`} call={call} index={index} />
      ))}
    </ul>
  );
}
