"use client";

/**
 * The frame every chart sits in.
 *
 * It owns the four things a chart panel must always have and that are easy to
 * forget one at a time: a title that names what is plotted, the loading and
 * error states, the chart/table switch, and the note explaining what the
 * figures are counted over. SOUL.md §11 requires all of them; making them the
 * frame's job means omitting one takes deliberate effort.
 */

import { Table2, TrendingUp } from "lucide-react";
import * as React from "react";

import { Button, Card, CardBody, CardHeader, CardTitle, Skeleton } from "@/components/ui/primitives";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { cn } from "@/lib/utils";

export function ChartCard({
  title,
  description,
  /** What the figures are counted over. Shown under the chart, always. */
  basis,
  query,
  isEmpty,
  emptyHint,
  height = 220,
  chart,
  table,
  className,
}: {
  title: string;
  description?: string;
  basis?: React.ReactNode;
  query: { isPending: boolean; isError: boolean; error: unknown; refetch: () => void };
  isEmpty?: boolean;
  emptyHint?: React.ReactNode;
  height?: number;
  chart: React.ReactNode;
  table: React.ReactNode;
  className?: string;
}) {
  const [view, setView] = React.useState<"chart" | "table">("chart");
  const headingId = React.useId();

  return (
    <Card className={className}>
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div className="min-w-0">
          <CardTitle id={headingId}>{title}</CardTitle>
          {description ? (
            <p className="mt-0.5 text-xs leading-relaxed text-[var(--ns-text-secondary)]">
              {description}
            </p>
          ) : null}
        </div>
        {!query.isPending && !query.isError && !isEmpty ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setView((current) => (current === "chart" ? "table" : "chart"))}
            aria-pressed={view === "table"}
            aria-describedby={headingId}
          >
            {view === "chart" ? (
              <Table2 aria-hidden="true" />
            ) : (
              <TrendingUp aria-hidden="true" />
            )}
            <span className="hidden sm:inline">
              {view === "chart" ? "Table" : "Chart"}
            </span>
          </Button>
        ) : null}
      </CardHeader>

      <CardBody>
        {query.isPending ? (
          <Skeleton className={cn("w-full")} style={{ height }} />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={query.refetch} />
        ) : isEmpty ? (
          <EmptyState title="Nothing to plot for this range" hint={emptyHint} />
        ) : view === "chart" ? (
          chart
        ) : (
          table
        )}

        {basis && !query.isPending && !query.isError ? (
          <p className="mt-2.5 text-[11px] leading-relaxed text-[var(--ns-text-muted)]">
            {basis}
          </p>
        ) : null}
      </CardBody>
    </Card>
  );
}
