"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import * as React from "react";

import { CategoryBarChart, type Category } from "@/components/charts/category-bar-chart";
import { ChartCard } from "@/components/charts/chart-card";
import { ChartTable } from "@/components/charts/chart-kit";
import { TimeSeriesChart } from "@/components/charts/time-series-chart";
import { Badge, Button, Card, CardBody, Skeleton } from "@/components/ui/primitives";
import { ErrorState, LoadingPanel, NoDataState } from "@/components/ui/states";
import { api } from "@/lib/api/client";
import type { SpeedDistribution } from "@/lib/api/types";
import { formatCount, formatDate, formatPercent, formatTimeOfDay } from "@/lib/format";
import { OTHER_COLOR, seriesColor } from "@/lib/viz/palette";

/**
 * Analytics over the archived day.
 *
 * Two things shape this page beyond the usual chart hygiene.
 *
 * **The range comes from the data, not from the clock.** The API's time-window
 * default is the last 24 hours, which is the right default for a service whose
 * data is current and the wrong one here: the archive is a day in the past, so
 * every request on this page carries the coverage window explicitly. The
 * control row says which window is in force rather than implying "now".
 *
 * **Basis is never implied.** Some figures count *vessels* and some count
 * *observations*, and the difference is large — a moored vessel broadcasting
 * all day is one vessel and hundreds of observations. Every panel prints which
 * one it is, taken from the API's own `basis` and `note` fields rather than
 * restated here where it could drift.
 */

/** How many categories get their own bar before the tail is folded up. */
const TYPE_ROWS = 9;
const STATUS_ROWS = 8;

/**
 * Fold a long tail into one honestly-labelled bucket.
 *
 * Labelled "Remaining", not "Other": the AIS type taxonomy already has a
 * genuine "Other" family, and two rows called Other in one chart would be read
 * as a duplicate rather than as two different things. The count of folded
 * categories is in the label, and the table view still lists every one.
 */
function withTail(categories: Category[], keep: number): { rows: Category[]; folded: number } {
  if (categories.length <= keep + 1) return { rows: categories, folded: 0 };
  const head = categories.slice(0, keep);
  const tail = categories.slice(keep);
  const count = tail.reduce((sum, category) => sum + category.count, 0);
  return {
    rows: [...head, { key: "__tail", label: `Remaining ${tail.length} categories`, count }],
    folded: tail.length,
  };
}

const TAIL_KEYS = new Set(["__tail"]);

function speedRows(data: SpeedDistribution): Category[] {
  return data.buckets.map((bucket) => ({
    key: bucket.label,
    label: bucket.label,
    count: bucket.count,
  }));
}

export function AnalyticsView() {
  const [interval, setInterval] = React.useState<"hour" | "15min">("hour");

  const dataset = useQuery({ queryKey: ["dataset", "status"], queryFn: api.datasetStatus });

  const start = dataset.data?.coverage.start ?? null;
  const end = dataset.data?.coverage.end ?? null;
  const hasWindow = start !== null && end !== null;

  const traffic = useQuery({
    queryKey: ["analytics", "traffic", start, end, interval],
    queryFn: () => api.traffic({ start: start!, end: end!, interval }),
    enabled: hasWindow,
  });

  const speed = useQuery({
    queryKey: ["analytics", "speed", start, end],
    queryFn: () => api.speedDistribution({ start: start!, end: end! }),
    enabled: hasWindow,
  });

  const types = useQuery({ queryKey: ["analytics", "vessel-types"], queryFn: api.vesselTypes });
  const status = useQuery({ queryKey: ["analytics", "nav-status"], queryFn: api.navStatus });
  const transceivers = useQuery({
    queryKey: ["analytics", "transceivers"],
    queryFn: api.transceivers,
  });

  const active = useQuery({
    queryKey: ["analytics", "active-vessels", start, end],
    queryFn: () => api.activeVessels({ start: start!, end: end!, limit: 12 }),
    enabled: hasWindow,
  });

  if (dataset.isPending) {
    return (
      <div className="mx-auto max-w-6xl p-4 md:p-6">
        <LoadingPanel />
      </div>
    );
  }
  if (dataset.isError) {
    return (
      <div className="mx-auto max-w-6xl p-4 md:p-6">
        <ErrorState error={dataset.error} onRetry={() => dataset.refetch()} />
      </div>
    );
  }
  if (!dataset.data.hasData) {
    return (
      <div className="mx-auto max-w-6xl p-4 md:p-6">
        <NoDataState />
      </div>
    );
  }

  const typeRows = types.data ? withTail(types.data.categories, TYPE_ROWS) : null;
  const statusRows = status.data ? withTail(status.data.categories, STATUS_ROWS) : null;

  return (
    <div className="mx-auto max-w-6xl space-y-5 p-4 md:p-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Analytics</h1>
        <p className="mt-1 max-w-2xl text-sm text-[var(--ns-text-secondary)]">
          Aggregate patterns across the archived day. Every figure is computed by the API
          against stored observations — nothing on this page is sampled or estimated.
        </p>
      </header>

      {/* Controls sit in one row above everything they scope. The window is
          fixed because the archive is one day; saying so is more useful than a
          date picker with one legal answer. */}
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-[var(--ns-border)] bg-[var(--ns-surface)] px-3 py-2">
        <div className="flex items-center gap-2 text-xs">
          <span className="text-[11px] tracking-wide text-[var(--ns-text-muted)] uppercase">
            Window
          </span>
          <Badge tone="info">
            {formatDate(start)} · {formatTimeOfDay(start)} — {formatTimeOfDay(end)}
          </Badge>
          <span className="hidden text-[var(--ns-text-muted)] sm:inline">
            the full extent of the imported archive
          </span>
        </div>

        <fieldset className="ml-auto flex items-center gap-1.5">
          <legend className="sr-only">Time bucket</legend>
          <span className="mr-1 text-[11px] tracking-wide text-[var(--ns-text-muted)] uppercase">
            Bucket
          </span>
          {(
            [
              { value: "hour", label: "Hourly" },
              { value: "15min", label: "15 minutes" },
            ] as const
          ).map((option) => (
            <Button
              key={option.value}
              size="sm"
              variant={interval === option.value ? "primary" : "ghost"}
              aria-pressed={interval === option.value}
              onClick={() => setInterval(option.value)}
            >
              {option.label}
            </Button>
          ))}
        </fieldset>
      </div>

      {/* --------------------------------------------------- Hero figure */}
      <Card>
        <CardBody className="flex flex-wrap items-end gap-x-10 gap-y-4 pt-4">
          <div>
            <p className="text-xs font-medium text-[var(--ns-text-secondary)]">
              Position reports in this window
            </p>
            {traffic.isPending ? (
              <Skeleton className="mt-1 h-12 w-52" />
            ) : traffic.isError ? (
              <p className="mt-1 text-sm text-[var(--ns-critical)]">Could not be loaded</p>
            ) : (
              <p className="mt-0.5 text-4xl font-semibold text-[var(--ns-text)] md:text-5xl">
                {formatCount(traffic.data.totalObservations)}
              </p>
            )}
          </div>
          <div>
            <p className="text-xs font-medium text-[var(--ns-text-secondary)]">
              Distinct vessels seen
            </p>
            <p className="mt-0.5 text-2xl font-semibold text-[var(--ns-text)]">
              {formatCount(dataset.data.counts.vessels)}
            </p>
          </div>
          <p className="max-w-sm text-[11px] leading-relaxed text-[var(--ns-text-muted)]">
            A vessel contributes one report per broadcast, so a moored ship reporting all day
            counts many times here and once as a vessel. The two figures answer different
            questions.
          </p>
        </CardBody>
      </Card>

      {/* -------------------------------------------------- Traffic pair */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ChartCard
          title="Position reports over the day"
          description="How many AIS broadcasts were recorded in each bucket."
          query={traffic}
          isEmpty={traffic.data?.buckets.length === 0}
          emptyHint="No observations fall inside the coverage window."
          basis={
            <>
              Counts observations in vessel_positions, bucketed by broadcast time in UTC.
              {traffic.data?.computedAt
                ? " Served from the API's precomputed rollup; the figures are identical to a live aggregation."
                : null}
            </>
          }
          chart={
            <TimeSeriesChart
              points={(traffic.data?.buckets ?? []).map((bucket) => ({
                at: bucket.bucket,
                value: bucket.observations,
              }))}
              color={seriesColor(0)}
              valueLabel="Position reports"
              formatX={formatTimeOfDay}
            />
          }
          table={
            <ChartTable
              caption="Position reports per bucket"
              rows={traffic.data?.buckets ?? []}
              columns={[
                { header: "Bucket (UTC)", cell: (row) => formatTimeOfDay(row.bucket) },
                {
                  header: "Position reports",
                  numeric: true,
                  cell: (row) => formatCount(row.observations),
                },
              ]}
            />
          }
        />

        <ChartCard
          title="Distinct vessels reporting"
          description="How many different vessels broadcast at least once in each bucket."
          query={traffic}
          isEmpty={traffic.data?.buckets.length === 0}
          basis="Counts distinct MMSIs per bucket. A vessel silent for a bucket is absent from it, which is not the same as absent from the water."
          chart={
            <TimeSeriesChart
              points={(traffic.data?.buckets ?? []).map((bucket) => ({
                at: bucket.bucket,
                value: bucket.distinctVessels ?? 0,
              }))}
              color={seriesColor(1)}
              valueLabel="Distinct vessels"
              formatX={formatTimeOfDay}
            />
          }
          table={
            <ChartTable
              caption="Distinct vessels per bucket"
              rows={traffic.data?.buckets ?? []}
              columns={[
                { header: "Bucket (UTC)", cell: (row) => formatTimeOfDay(row.bucket) },
                {
                  header: "Distinct vessels",
                  numeric: true,
                  cell: (row) => formatCount(row.distinctVessels),
                },
              ]}
            />
          }
        />
      </div>

      {/* -------------------------------------------- Composition panels */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ChartCard
          title="Fleet composition"
          description="Vessel types across every vessel in the archive."
          query={types}
          height={300}
          basis={
            types.data
              ? `Basis: ${types.data.basis}. ${formatCount(types.data.total)} vessels across ` +
                `${types.data.categories.length} type families; the table view lists every one.`
              : undefined
          }
          chart={
            typeRows ? (
              <CategoryBarChart
                categories={typeRows.rows}
                total={types.data!.total}
                color={seriesColor(0)}
                mutedKeys={TAIL_KEYS}
                mutedColor={OTHER_COLOR}
              />
            ) : null
          }
          table={
            <ChartTable
              caption="Vessel types"
              rows={types.data?.categories ?? []}
              columns={[
                { header: "Type", cell: (row) => row.label },
                { header: "Vessels", numeric: true, cell: (row) => formatCount(row.count) },
                {
                  header: "Share",
                  numeric: true,
                  cell: (row) =>
                    formatPercent((row.count / Math.max(1, types.data?.total ?? 1)) * 100),
                },
              ]}
            />
          }
        />

        <ChartCard
          title="Navigational status"
          description="What vessels reported they were doing, at their latest observation."
          query={status}
          height={300}
          basis={
            status.data
              ? `Basis: ${status.data.basis}. Status is self-reported and frequently left unset, which is why "Not reported" is a category rather than a gap.`
              : undefined
          }
          chart={
            statusRows ? (
              <CategoryBarChart
                categories={statusRows.rows}
                total={status.data!.total}
                color={seriesColor(2)}
                mutedKeys={TAIL_KEYS}
                mutedColor={OTHER_COLOR}
              />
            ) : null
          }
          table={
            <ChartTable
              caption="Navigational status"
              rows={status.data?.categories ?? []}
              columns={[
                { header: "Status", cell: (row) => row.label },
                { header: "Vessels", numeric: true, cell: (row) => formatCount(row.count) },
              ]}
            />
          }
        />

        <ChartCard
          title="Speed at time of report"
          description="Every observation placed in a speed band."
          query={speed}
          height={240}
          basis={speed.data?.note}
          chart={
            speed.data ? (
              <CategoryBarChart
                categories={speedRows(speed.data)}
                total={speed.data.total}
                color={seriesColor(3)}
              />
            ) : null
          }
          table={
            <ChartTable
              caption="Speed distribution"
              rows={speed.data?.buckets ?? []}
              columns={[
                { header: "Band", cell: (row) => row.label },
                {
                  header: "Observations",
                  numeric: true,
                  cell: (row) => formatCount(row.count),
                },
              ]}
            />
          }
        />

        <ChartCard
          title="Transceiver class"
          description="Class A is carried by larger commercial vessels; Class B by smaller craft."
          query={transceivers}
          height={240}
          basis={
            transceivers.data
              ? `Basis: ${transceivers.data.basis}. ${formatCount(transceivers.data.total)} vessels.`
              : undefined
          }
          chart={
            transceivers.data ? (
              <CategoryBarChart
                categories={transceivers.data.categories}
                total={transceivers.data.total}
                color={seriesColor(4)}
              />
            ) : null
          }
          table={
            <ChartTable
              caption="Transceiver class"
              rows={transceivers.data?.categories ?? []}
              columns={[
                { header: "Class", cell: (row) => row.label },
                { header: "Vessels", numeric: true, cell: (row) => formatCount(row.count) },
              ]}
            />
          }
        />
      </div>

      {/* -------------------------------------------- Most active vessels */}
      <ChartCard
        title="Most frequently reporting vessels"
        description="Which vessels broadcast most often in the window. Reporting rate reflects transceiver class and activity, not importance."
        query={active}
        isEmpty={active.data?.length === 0}
        height={280}
        basis="Counts observations per MMSI. Class A transceivers report far more often than Class B, so this ranking is dominated by them."
        chart={
          <ol className="space-y-1">
            {(active.data ?? []).map((entry, index) => (
              <li key={entry.vessel.mmsi}>
                <Link
                  href={`/vessels/${entry.vessel.mmsi}`}
                  className="flex items-center gap-3 rounded-md px-2 py-1.5 text-xs hover:bg-[var(--ns-surface-raised)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--ns-accent)]"
                >
                  <span className="tabular w-5 shrink-0 text-right font-[family-name:var(--font-mono)] text-[var(--ns-text-muted)]">
                    {index + 1}
                  </span>
                  <span className="min-w-0 flex-1 truncate font-medium text-[var(--ns-text)]">
                    {entry.vessel.name ?? `MMSI ${entry.vessel.mmsi}`}
                  </span>
                  <span className="hidden shrink-0 text-[var(--ns-text-muted)] sm:inline">
                    {entry.vessel.vesselType.label}
                  </span>
                  <span className="tabular w-20 shrink-0 text-right font-[family-name:var(--font-mono)] text-[var(--ns-text)]">
                    {formatCount(entry.observations)}
                  </span>
                </Link>
              </li>
            ))}
          </ol>
        }
        table={
          <ChartTable
            caption="Most frequently reporting vessels"
            rows={active.data ?? []}
            columns={[
              { header: "Vessel", cell: (row) => row.vessel.name ?? "—" },
              { header: "MMSI", cell: (row) => row.vessel.mmsi },
              { header: "Type", cell: (row) => row.vessel.vesselType.label },
              {
                header: "Observations",
                numeric: true,
                cell: (row) => formatCount(row.observations),
              },
            ]}
          />
        }
      />
    </div>
  );
}
