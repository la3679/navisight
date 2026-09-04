"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Database,
  History,
  Map as MapIcon,
  Search,
  Ship,
  Sparkles,
} from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import * as React from "react";

import { Badge, Card, CardBody, Skeleton } from "@/components/ui/primitives";
import { ErrorState, NoDataState } from "@/components/ui/states";
import { useWebGLSupport } from "@/hooks/client-env";
import { api } from "@/lib/api/client";
import { formatCount, formatDate, formatTimeOfDay } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * The overview.
 *
 * This is the first screen anyone sees, so it has one job beyond navigation:
 * establish immediately and unmistakably that the data is a **single archived
 * day**, not a live feed (SOUL.md §4, ADR-0008). The dataset date is in the
 * hero, not a footnote.
 *
 * Every figure on this page comes from `/dataset/status` — the same counts the
 * database actually holds. Nothing here is illustrative, and there is no
 * placeholder number waiting to be replaced.
 */

/**
 * three.js is ~600 KB and useless on the server, so the scene loads on demand.
 * The skeleton reserves the hero's height, so nothing reflows when it arrives.
 */
const HarbourScene = dynamic(
  () => import("@/components/three/harbour-scene").then((m) => m.HarbourScene),
  { ssr: false, loading: () => <Skeleton className="size-full rounded-none" /> },
);

type Destination = {
  href: string;
  title: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
};

const DESTINATIONS: Destination[] = [
  {
    href: "/operations",
    title: "Operations map",
    description:
      "Every vessel's last known position in the archive, aggregated when zoomed out and individually selectable when zoomed in. Replay the day hour by hour.",
    icon: MapIcon,
  },
  {
    href: "/vessels",
    title: "Vessel search",
    description:
      "Find a ship by name, MMSI, IMO, or call sign, then open its full record: identity, dimensions, every observation, and its track.",
    icon: Search,
  },
  {
    href: "/analytics",
    title: "Analytics",
    description:
      "Traffic through the day, the composition of the fleet, how much of it was moving, and which vessels reported most often.",
    icon: Sparkles,
  },
  {
    href: "/data",
    title: "Dataset",
    description:
      "What was imported, what the source does and does not contain, and the measured completeness of every field.",
    icon: Database,
  },
];

/** A headline figure. The label carries the unit; the number never stands alone. */
function Statistic({ value, label, hint }: { value: string; label: string; hint: string }) {
  // Inside a <dl>, so this has to be a dt/dd pair — a <dl> of <p> elements is
  // a definition list containing no definitions, which is what a screen reader
  // is told it is getting. The label reads as the term and the figure as its
  // description; the visual order is reversed with `order`, because sighted
  // readers scan the number first.
  return (
    <div className="flex flex-col">
      <dt className="order-2 mt-0.5 text-xs font-medium text-[var(--ns-text-secondary)]">
        {label}
      </dt>
      <dd className="tabular order-1 font-[family-name:var(--font-mono)] text-2xl font-semibold text-[var(--ns-text)] md:text-3xl">
        {value}
      </dd>
      <dd className="order-3 mt-0.5 text-[11px] leading-snug text-[var(--ns-text-muted)]">
        {hint}
      </dd>
    </div>
  );
}

export function HomeView() {
  const webgl = useWebGLSupport();
  const status = useQuery({ queryKey: ["dataset", "status"], queryFn: api.datasetStatus });

  const coverageStart = status.data?.coverage.start ?? null;
  const coverageEnd = status.data?.coverage.end ?? null;

  return (
    <div className="mx-auto max-w-6xl space-y-8 p-4 md:p-6">
      {/* ---------------------------------------------------------- Hero */}
      <section className="overflow-hidden rounded-xl border border-[var(--ns-border)] bg-[var(--ns-surface)]">
        <div className="relative h-[220px] w-full md:h-[300px]">
          {webgl ? (
            <HarbourScene />
          ) : (
            /* No WebGL is not an error and not a blank box: the scene was
               decorative, so its absence costs nothing and is stated. */
            <div className="flex size-full items-center justify-center bg-[var(--ns-bg)] px-6 text-center">
              <p className="max-w-sm text-xs text-[var(--ns-text-muted)]">
                The decorative harbour scene needs WebGL, which this browser does not provide.
                Nothing else on NaviSight depends on it.
              </p>
            </div>
          )}

          {/* The scene is scenery. Saying so beside it is the difference between
              atmosphere and a false claim about the data (SOUL.md §3). */}
          <p className="pointer-events-none absolute right-3 bottom-2 text-[10px] text-[var(--ns-text-muted)]">
            Illustrative scene, generated in code. Not dataset positions.
          </p>

          {/* The scrim only covers the band the text sits in. A full-height
              wash would flatten the scene it exists to make readable. */}
          <div className="pointer-events-none absolute inset-x-0 top-1/3 bottom-0 flex flex-col justify-end bg-gradient-to-t from-[var(--ns-surface)] via-[color-mix(in_oklab,var(--ns-surface)_86%,transparent)] to-transparent p-4 md:p-6">
            <div className="pointer-events-auto max-w-2xl">
              <Badge tone="info">
                <History className="size-3" aria-hidden="true" />
                Historical AIS archive
              </Badge>
              <h1 className="mt-2 text-2xl font-semibold tracking-tight md:text-3xl">
                What vessels did, where, and when.
              </h1>
              <p className="mt-1.5 text-sm leading-relaxed text-[var(--ns-text-secondary)]">
                NaviSight reconstructs a day of maritime movement from recorded AIS broadcasts.{" "}
                {coverageStart ? (
                  <>
                    This deployment holds{" "}
                    <strong className="text-[var(--ns-text)]">
                      {formatDate(coverageStart)}
                    </strong>
                    , from {formatTimeOfDay(coverageStart)} to {formatTimeOfDay(coverageEnd)}.
                  </>
                ) : (
                  <>Nothing has been imported into this deployment yet.</>
                )}{" "}
                It is an archive, not a live feed — no position here reflects where a ship is
                now.
              </p>
            </div>
          </div>
        </div>

        {/* ----------------------------------------------------- Figures */}
        <div className="border-t border-[var(--ns-border)] p-4 md:p-6">
          {status.isPending ? (
            <div
              className="grid grid-cols-2 gap-6 md:grid-cols-4"
              aria-label="Loading"
              role="status"
            >
              {Array.from({ length: 4 }, (_, index) => (
                <div key={index} className="space-y-2">
                  <Skeleton className="h-8 w-24" />
                  <Skeleton className="h-3 w-20" />
                </div>
              ))}
              <span className="sr-only">Loading dataset figures…</span>
            </div>
          ) : status.isError ? (
            <ErrorState error={status.error} onRetry={() => status.refetch()} />
          ) : !status.data.hasData ? (
            <NoDataState />
          ) : (
            <dl className="grid grid-cols-2 gap-6 md:grid-cols-4">
              <Statistic
                value={formatCount(status.data.counts.positions)}
                label="Position reports"
                hint="Individual AIS broadcasts stored"
              />
              <Statistic
                value={formatCount(status.data.counts.vessels)}
                label="Distinct vessels"
                hint="Unique MMSIs seen in the day"
              />
              <Statistic
                value={formatCount(status.data.counts.latestStates)}
                label="Latest states"
                hint="One current position per vessel"
              />
              <Statistic
                value={formatDate(coverageStart)}
                label="Coverage"
                hint="A single archived day, UTC"
              />
            </dl>
          )}
        </div>
      </section>

      {/* --------------------------------------------------- Destinations */}
      <section aria-labelledby="explore-heading">
        <h2 id="explore-heading" className="text-sm font-semibold tracking-tight">
          Where to start
        </h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {DESTINATIONS.map((destination) => {
            const Icon = destination.icon;
            return (
              <Link
                key={destination.href}
                href={destination.href}
                className={cn(
                  "group rounded-lg border border-[var(--ns-border)] bg-[var(--ns-surface)] p-4",
                  "transition-colors hover:border-[var(--ns-border-strong)]",
                  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
                  "focus-visible:outline-[var(--ns-accent)]",
                )}
              >
                <div className="flex items-center gap-2">
                  <Icon className="size-4 text-[var(--ns-accent)]" aria-hidden="true" />
                  <span className="text-sm font-medium">{destination.title}</span>
                  <ArrowRight
                    className="ml-auto size-4 text-[var(--ns-text-muted)] transition-transform group-hover:translate-x-0.5"
                    aria-hidden="true"
                  />
                </div>
                <p className="mt-1.5 text-xs leading-relaxed text-[var(--ns-text-secondary)]">
                  {destination.description}
                </p>
              </Link>
            );
          })}
        </div>
      </section>

      {/* ------------------------------------------------------ Honesty */}
      <section aria-labelledby="limits-heading">
        <h2 id="limits-heading" className="text-sm font-semibold tracking-tight">
          What this cannot tell you
        </h2>
        <Card className="mt-3">
          <CardBody className="pt-4 text-sm leading-relaxed text-[var(--ns-text-secondary)]">
            <ul className="space-y-2">
              <li className="flex gap-2">
                <Ship
                  className="mt-0.5 size-4 shrink-0 text-[var(--ns-text-muted)]"
                  aria-hidden="true"
                />
                <span>
                  <strong className="text-[var(--ns-text)]">Where a ship is now.</strong> The
                  archive ends at its last recorded broadcast and never advances.
                </span>
              </li>
              <li className="flex gap-2">
                <History
                  className="mt-0.5 size-4 shrink-0 text-[var(--ns-text-muted)]"
                  aria-hidden="true"
                />
                <span>
                  <strong className="text-[var(--ns-text)]">
                    What happened between broadcasts.
                  </strong>{" "}
                  The source is filtered to one-minute resolution and NaviSight never
                  interpolates, so a track is a sequence of samples.
                </span>
              </li>
              <li className="flex gap-2">
                <Database
                  className="mt-0.5 size-4 shrink-0 text-[var(--ns-text-muted)]"
                  aria-hidden="true"
                />
                <span>
                  <strong className="text-[var(--ns-text)]">
                    Anything a vessel did not broadcast.
                  </strong>{" "}
                  AIS fields are self-reported and often blank. A missing heading is shown as
                  missing, never as zero — see the{" "}
                  <Link
                    href="/data"
                    className="text-[var(--ns-accent)] underline underline-offset-2"
                  >
                    measured field completeness
                  </Link>
                  .
                </span>
              </li>
            </ul>
          </CardBody>
        </Card>
      </section>
    </div>
  );
}
