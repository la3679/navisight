/**
 * The non-success states, as first-class components.
 *
 * SOUL.md §11 requires every meaningful surface to implement loading, error,
 * empty, partial-data, and not-configured. Making each one a component means
 * the alternative — a blank panel — takes more effort than doing it properly.
 *
 * Error states are specific: a network failure, a missing database, and an
 * unconfigured AI provider are different problems with different fixes, and
 * telling the user which one they have is the whole point.
 */

"use client";

import {
  AlertTriangle,
  DatabaseZap,
  Inbox,
  PlugZap,
  RefreshCw,
  ServerCrash,
  WifiOff,
} from "lucide-react";
import * as React from "react";

import { ApiClientError } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import { Button, Skeleton } from "./primitives";

function Shell({
  icon,
  title,
  children,
  action,
  tone = "neutral",
  className,
}: {
  icon: React.ReactNode;
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
  tone?: "neutral" | "warning" | "critical";
  className?: string;
}) {
  const toneColor = {
    neutral: "text-[var(--ns-text-muted)]",
    warning: "text-[var(--ns-warning)]",
    critical: "text-[var(--ns-critical)]",
  }[tone];

  return (
    <div
      className={cn(
        "flex min-h-[180px] flex-col items-center justify-center gap-3 rounded-lg",
        "border border-dashed border-[var(--ns-border)] px-6 py-10 text-center",
        className,
      )}
      role={tone === "neutral" ? undefined : "alert"}
    >
      <div className={cn("[&_svg]:size-6", toneColor)}>{icon}</div>
      <div>
        <p className="text-sm font-medium text-[var(--ns-text)]">{title}</p>
        {children ? (
          <div className="mx-auto mt-1.5 max-w-md text-xs leading-relaxed text-[var(--ns-text-muted)]">
            {children}
          </div>
        ) : null}
      </div>
      {action}
    </div>
  );
}

/** Nothing matched. Not an error — say what would change the outcome. */
export function EmptyState({
  title = "No results",
  hint,
  action,
  className,
}: {
  title?: string;
  hint?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <Shell icon={<Inbox />} title={title} action={action} className={className}>
      {hint}
    </Shell>
  );
}

/**
 * A failed request, described in terms of what actually went wrong.
 *
 * Branches on `ApiClientError.kind` so the user is told whether the API is
 * unreachable, the database is down, or their request was invalid — each of
 * which has a different fix.
 */
export function ErrorState({
  error,
  onRetry,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}) {
  const retry = onRetry ? (
    <Button variant="secondary" size="sm" onClick={onRetry}>
      <RefreshCw aria-hidden="true" />
      Try again
    </Button>
  ) : null;

  if (error instanceof ApiClientError) {
    if (error.kind === "network") {
      return (
        <Shell
          icon={<WifiOff />}
          title="Cannot reach the API"
          tone="critical"
          action={retry}
          className={className}
        >
          <p>{error.message}</p>
          <p className="mt-2">
            Start it with{" "}
            <code className="rounded bg-[var(--ns-surface-raised)] px-1 py-0.5 font-[family-name:var(--font-mono)]">
              uv run uvicorn app.main:app --reload
            </code>{" "}
            in <code>apps/api</code>.
          </p>
        </Shell>
      );
    }

    if (error.kind === "unavailable") {
      return (
        <Shell
          icon={<DatabaseZap />}
          title="The database is unavailable"
          tone="critical"
          action={retry}
          className={className}
        >
          <p>{error.message}</p>
          <p className="mt-2">
            Start MongoDB with{" "}
            <code className="rounded bg-[var(--ns-surface-raised)] px-1 py-0.5 font-[family-name:var(--font-mono)]">
              docker compose up -d mongodb
            </code>
            .
          </p>
        </Shell>
      );
    }

    if (error.kind === "contract") {
      return (
        <Shell
          icon={<ServerCrash />}
          title="API response did not match the expected shape"
          tone="warning"
          action={retry}
          className={className}
        >
          <p>{error.message}</p>
        </Shell>
      );
    }

    return (
      <Shell
        icon={<AlertTriangle />}
        title="That request could not be completed"
        tone="warning"
        action={retry}
        className={className}
      >
        <p>{error.message}</p>
        {error.requestId ? (
          <p className="mt-2 font-[family-name:var(--font-mono)] text-[10px]">
            request {error.requestId}
          </p>
        ) : null}
      </Shell>
    );
  }

  return (
    <Shell
      icon={<AlertTriangle />}
      title="Something went wrong"
      tone="warning"
      action={retry}
      className={className}
    >
      <p>{error instanceof Error ? error.message : "An unexpected error occurred."}</p>
    </Shell>
  );
}

/**
 * A capability that exists but has not been set up.
 *
 * Distinct from an error: nothing is broken, something is simply not
 * configured, and the fix is a setup step rather than a retry.
 */
export function NotConfiguredState({
  title,
  children,
  className,
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Shell icon={<PlugZap />} title={title} className={className}>
      {children}
    </Shell>
  );
}

/** Shown when the database is reachable but nothing has been imported. */
export function NoDataState({ className }: { className?: string }) {
  return (
    <Shell
      icon={<DatabaseZap />}
      title="No AIS data has been imported yet"
      className={className}
    >
      <p>Run the import to populate the database:</p>
      <pre className="mt-2 overflow-x-auto rounded bg-[var(--ns-surface-raised)] p-2 text-left font-[family-name:var(--font-mono)] text-[11px]">
        {`cd apps/api
uv run navisight-data import`}
      </pre>
      <p className="mt-2">
        See <code>data/README.md</code> for how to obtain the source file.
      </p>
    </Shell>
  );
}

/**
 * A result that is real but incomplete, labelled as such.
 *
 * Used where the server truncated a response or simplified a track — the user
 * is told rather than shown a partial answer as though it were whole.
 */
export function PartialDataNotice({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <p
      className={cn(
        "flex items-start gap-1.5 text-[11px] leading-relaxed text-[var(--ns-text-muted)]",
        className,
      )}
    >
      <AlertTriangle
        aria-hidden="true"
        className="mt-px size-3 shrink-0 text-[var(--ns-warning)]"
      />
      <span>{children}</span>
    </p>
  );
}

/* --------------------------------------------------------------- Loading */

export function LoadingRows({ rows = 5, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)} role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} className="h-11 w-full" />
      ))}
      <span className="sr-only">Loading…</span>
    </div>
  );
}

export function LoadingPanel({ className }: { className?: string }) {
  return (
    <div className={cn("space-y-3 p-4", className)} role="status" aria-label="Loading">
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-4 w-2/3" />
      <span className="sr-only">Loading…</span>
    </div>
  );
}
