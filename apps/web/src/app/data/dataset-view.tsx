"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, ExternalLink, History, Info } from "lucide-react";

import {
  Badge,
  Card,
  CardBody,
  CardDescription,
  CardHeader,
  CardTitle,
  Field,
} from "@/components/ui/primitives";
import {
  ErrorState,
  LoadingPanel,
  NoDataState,
  NotConfiguredState,
} from "@/components/ui/states";
import { api } from "@/lib/api/client";
import { formatCount, formatDate, formatPercent, formatTimestamp } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Fields whose absence materially changes what the product can show. */
const NOTABLE_FIELDS = new Set(["heading", "imo", "draft", "status", "cargo", "cog"]);

export function DatasetView() {
  const status = useQuery({ queryKey: ["dataset", "status"], queryFn: api.datasetStatus });
  const quality = useQuery({
    queryKey: ["dataset", "quality"],
    queryFn: api.dataQuality,
    retry: false,
  });

  if (status.isPending) {
    return (
      <div className="mx-auto max-w-5xl p-4 md:p-6">
        <LoadingPanel />
      </div>
    );
  }

  if (status.isError) {
    return (
      <div className="mx-auto max-w-5xl p-4 md:p-6">
        <ErrorState error={status.error} onRetry={() => status.refetch()} />
      </div>
    );
  }

  const data = status.data;

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 md:p-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Dataset</h1>
        <p className="mt-1 max-w-2xl text-sm text-[var(--ns-text-secondary)]">
          What NaviSight has loaded, where it came from, and what it can and cannot tell you.
        </p>
      </header>

      {/* The historical disclaimer, stated once, prominently, in plain words. */}
      <Card className="border-[color-mix(in_oklab,var(--ns-info)_35%,transparent)] bg-[color-mix(in_oklab,var(--ns-info)_7%,transparent)]">
        <CardBody className="flex gap-3 pt-4">
          <History className="mt-0.5 size-5 shrink-0 text-[var(--ns-info)]" aria-hidden="true" />
          <div className="space-y-1.5 text-sm">
            <p className="font-medium text-[var(--ns-text)]">
              This is a historical archive, not a live feed.
            </p>
            <p className="text-[var(--ns-text-secondary)]">
              Every position NaviSight shows was broadcast on{" "}
              <strong className="text-[var(--ns-text)]">
                {formatDate(data.coverage.start)}
              </strong>{" "}
              and recorded by the U.S. Coast Guard&rsquo;s AIS network. Nothing here reflects
              where a vessel is now. Where the interface says &ldquo;latest observation&rdquo;,
              it means the newest record in this file — which may be many months old.
            </p>
            <p className="text-[var(--ns-text-secondary)]">
              The publisher filters this data to{" "}
              <strong className="text-[var(--ns-text)]">one-minute resolution</strong>, so a
              track is a sequence of samples, not continuous telemetry. NaviSight never
              interpolates between them.
            </p>
          </div>
        </CardBody>
      </Card>

      {!data.hasData ? (
        <NoDataState />
      ) : (
        <>
          <section className="grid gap-4 sm:grid-cols-3">
            <Card>
              <CardBody className="pt-4">
                <p className="text-[11px] uppercase tracking-wide text-[var(--ns-text-muted)]">
                  Position observations
                </p>
                <p className="mt-1 text-2xl font-semibold tabular">
                  {formatCount(data.counts.positions)}
                </p>
              </CardBody>
            </Card>
            <Card>
              <CardBody className="pt-4">
                <p className="text-[11px] uppercase tracking-wide text-[var(--ns-text-muted)]">
                  Distinct vessels
                </p>
                <p className="mt-1 text-2xl font-semibold tabular">
                  {formatCount(data.counts.vessels)}
                </p>
              </CardBody>
            </Card>
            <Card>
              <CardBody className="pt-4">
                <p className="text-[11px] uppercase tracking-wide text-[var(--ns-text-muted)]">
                  Coverage (UTC)
                </p>
                <p className="mt-1 text-sm font-medium tabular">
                  {formatTimestamp(data.coverage.start, { seconds: false })}
                </p>
                <p className="text-sm font-medium tabular">
                  {formatTimestamp(data.coverage.end, { seconds: false })}
                </p>
              </CardBody>
            </Card>
          </section>

          <Card>
            <CardHeader>
              <CardTitle>Source</CardTitle>
              <CardDescription>
                NaviSight does not own this data and does not redistribute it. The raw file is
                not part of the repository.
              </CardDescription>
            </CardHeader>
            <CardBody>
              <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <Field label="Dataset" value={data.dataset} />
                <Field
                  label="File"
                  value={data.lastIngestion?.sourceFile ?? "—"}
                  mono
                />
                <Field
                  label="Publisher"
                  value={
                    <a
                      href="https://marinecadastre.gov/accessais/"
                      target="_blank"
                      rel="noreferrer noopener"
                      className="inline-flex items-center gap-1 text-[var(--ns-accent)] hover:underline"
                    >
                      MarineCadastre
                      <ExternalLink className="size-3" aria-hidden="true" />
                    </a>
                  }
                />
                <Field label="Time basis" value="UTC" hint="Per the AIS data dictionary" />
              </dl>
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Last import</CardTitle>
              <CardDescription>
                Counts are reconciled against an independent profiling pass over the source
                file, so a lossy import cannot be reported as a successful one.
              </CardDescription>
            </CardHeader>
            <CardBody>
              {data.lastIngestion ? (
                <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <Field
                    label="Status"
                    value={
                      <Badge tone={data.lastIngestion.status === "completed" ? "accent" : "warning"}>
                        {data.lastIngestion.status === "completed" ? (
                          <CheckCircle2 className="size-3" aria-hidden="true" />
                        ) : null}
                        {data.lastIngestion.status ?? "unknown"}
                      </Badge>
                    }
                  />
                  <Field
                    label="Rows read"
                    value={formatCount(data.lastIngestion.rowsRead)}
                    mono
                  />
                  <Field
                    label="Stored"
                    value={formatCount(data.lastIngestion.positionsInserted)}
                    hint="After collapsing exact duplicates"
                    mono
                  />
                  <Field
                    label="Rejected"
                    value={formatCount(data.lastIngestion.rowsRejected)}
                    hint="Rows that could not yield a position"
                    mono
                  />
                  <Field
                    label="Duplicates collapsed"
                    value={formatCount(data.lastIngestion.positionsDuplicate)}
                    hint="Identical broadcasts, stored once"
                    mono
                  />
                  <Field
                    label="Completed"
                    value={formatTimestamp(data.lastIngestion.completedAt, { seconds: false })}
                    mono
                  />
                </dl>
              ) : (
                <p className="text-sm text-[var(--ns-text-muted)]">
                  No ingestion run has been recorded.
                </p>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Field completeness</CardTitle>
              <CardDescription>
                Measured across the source file by the profiler, including rows the import
                rejected. AIS metadata is self-reported and frequently absent — this table is
                why the interface shows an em dash rather than a zero.
              </CardDescription>
            </CardHeader>
            <CardBody>
              {quality.isPending ? (
                <LoadingPanel />
              ) : quality.isError ? (
                <NotConfiguredState title="No profile report available">
                  Run <code>uv run navisight-data profile</code> in <code>apps/api</code> to
                  generate the field-completeness report.
                </NotConfiguredState>
              ) : (
                <>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <caption className="sr-only">
                        Completeness of each AIS field in the source file
                      </caption>
                      <thead>
                        <tr className="border-b border-[var(--ns-border)] text-left">
                          <th scope="col" className="py-2 pr-4 font-medium text-[var(--ns-text-secondary)]">
                            Field
                          </th>
                          <th scope="col" className="py-2 pr-4 text-right font-medium text-[var(--ns-text-secondary)]">
                            Present
                          </th>
                          <th scope="col" className="py-2 pr-4 text-right font-medium text-[var(--ns-text-secondary)]">
                            Missing
                          </th>
                          <th scope="col" className="py-2 text-right font-medium text-[var(--ns-text-secondary)]">
                            Missing %
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {quality.data.fields.map((field) => {
                          const notable = NOTABLE_FIELDS.has(field.field) && field.missingPercent > 10;
                          return (
                            <tr
                              key={field.field}
                              className="border-b border-[var(--ns-border)] last:border-0"
                            >
                              <th
                                scope="row"
                                className="py-1.5 pr-4 text-left font-[family-name:var(--font-mono)] text-xs font-normal"
                              >
                                {field.field}
                              </th>
                              <td className="py-1.5 pr-4 text-right tabular text-[var(--ns-text-secondary)]">
                                {formatCount(field.present)}
                              </td>
                              <td className="py-1.5 pr-4 text-right tabular text-[var(--ns-text-secondary)]">
                                {formatCount(field.missing)}
                              </td>
                              <td
                                className={cn(
                                  "py-1.5 text-right tabular",
                                  notable
                                    ? "font-medium text-[var(--ns-warning)]"
                                    : "text-[var(--ns-text-secondary)]",
                                )}
                              >
                                {formatPercent(field.missingPercent, 2)}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <p className="mt-3 flex items-start gap-1.5 text-[11px] text-[var(--ns-text-muted)]">
                    <Info className="mt-px size-3 shrink-0" aria-hidden="true" />
                    <span>
                      Profiled {formatCount(quality.data.rowsRead)} rows from{" "}
                      <code>{quality.data.source}</code>
                      {quality.data.generatedAt
                        ? ` on ${formatTimestamp(quality.data.generatedAt, { seconds: false })}`
                        : null}
                      . {formatCount(quality.data.rowsRejected)} rejected;{" "}
                      {formatCount(quality.data.exactDuplicates)} exact duplicate broadcasts
                      collapsed.
                    </span>
                  </p>
                </>
              )}
            </CardBody>
          </Card>
        </>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Known limitations</CardTitle>
          <CardDescription>
            Things this data cannot tell you, stated so you do not have to find out the hard
            way.
          </CardDescription>
        </CardHeader>
        <CardBody>
          <ul className="space-y-2 text-sm text-[var(--ns-text-secondary)]">
            {[
              "AIS is self-reported. Vessel names, dimensions, draft, and destination are entered by crew and are sometimes wrong, stale, or blank.",
              "Coverage is terrestrial-receiver dependent. A gap in a track usually means no receiver heard the vessel, not that it stopped broadcasting.",
              "The publisher filters to one-minute resolution, so fast manoeuvres between samples are invisible.",
              "MMSI identifies a transceiver, not a hull. It can be reassigned, shared, or misconfigured.",
              "Anomaly indicators in this product are deterministic heuristics over movement, not confirmed events. They are labelled as candidates throughout.",
              "NaviSight is not a navigation, collision-avoidance, or safety-critical system, and must not be used as one.",
            ].map((item) => (
              <li key={item} className="flex gap-2">
                <span aria-hidden="true" className="mt-2 size-1 shrink-0 rounded-full bg-[var(--ns-text-muted)]" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </CardBody>
      </Card>

      <section className="grid gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Port reference data</CardTitle>
          </CardHeader>
          <CardBody>
            {data.portsConfigured ? (
              <p className="text-sm text-[var(--ns-text-secondary)]">
                Port reference data is loaded. Port proximity and estimated visit features are
                available.
              </p>
            ) : (
              <NotConfiguredState title="Not configured" className="min-h-0 border-0 px-0 py-2">
                Port features are optional. Load a port reference dataset with{" "}
                <code>uv run navisight-data ports load</code> to enable them.
              </NotConfiguredState>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>AI copilot</CardTitle>
          </CardHeader>
          <CardBody>
            {data.aiConfigured ? (
              <p className="text-sm text-[var(--ns-text-secondary)]">
                A model provider is configured. The copilot answers using allow-listed data
                tools and shows its evidence.
              </p>
            ) : (
              <NotConfiguredState title="Not configured" className="min-h-0 border-0 px-0 py-2">
                Set <code>LLM_PROVIDER</code>, <code>LLM_MODEL</code>, and{" "}
                <code>LLM_API_KEY</code> in <code>.env</code>, or use{" "}
                <code>LLM_PROVIDER=mock</code> for an offline demo.
              </NotConfiguredState>
            )}
          </CardBody>
        </Card>
      </section>
    </div>
  );
}
