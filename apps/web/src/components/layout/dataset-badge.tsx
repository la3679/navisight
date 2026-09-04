/**
 * The permanent dataset indicator.
 *
 * This exists because of ADR-0008. The data is one archived day of AIS
 * broadcasts; a map full of vessels reads as live unless the interface says
 * otherwise, continuously and where the user is looking.
 *
 * It also doubles as the system-status light: if the API or database is down,
 * this is the component that says so.
 */

"use client";

import { useQuery } from "@tanstack/react-query";
import { CircleAlert, CircleOff, History } from "lucide-react";
import Link from "next/link";

import { api } from "@/lib/api/client";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

export function DatasetBadge() {
  const { data, isPending, isError } = useQuery({
    queryKey: ["dataset", "status"],
    queryFn: api.datasetStatus,
    staleTime: 60_000,
  });

  const base =
    "flex h-8 items-center gap-1.5 rounded-full border px-2.5 text-[11px] font-medium transition-colors";

  if (isPending) {
    return (
      <span
        className={cn(base, "border-[var(--ns-border)] text-[var(--ns-text-muted)]")}
        aria-live="polite"
      >
        <History className="size-3.5" aria-hidden="true" />
        <span className="hidden sm:inline">Checking dataset…</span>
      </span>
    );
  }

  if (isError) {
    return (
      <Link
        href="/data"
        className={cn(
          base,
          "border-[color-mix(in_oklab,var(--ns-critical)_45%,transparent)]",
          "bg-[color-mix(in_oklab,var(--ns-critical)_12%,transparent)] text-[var(--ns-critical)]",
        )}
      >
        <CircleOff className="size-3.5" aria-hidden="true" />
        <span className="hidden sm:inline">API unavailable</span>
        <span className="sm:hidden">Offline</span>
      </Link>
    );
  }

  if (!data.hasData) {
    return (
      <Link
        href="/data"
        className={cn(
          base,
          "border-[color-mix(in_oklab,var(--ns-warning)_45%,transparent)]",
          "bg-[color-mix(in_oklab,var(--ns-warning)_12%,transparent)] text-[var(--ns-warning)]",
        )}
      >
        <CircleAlert className="size-3.5" aria-hidden="true" />
        <span className="hidden sm:inline">No data imported</span>
        <span className="sm:hidden">No data</span>
      </Link>
    );
  }

  const start = formatDate(data.coverage.start);
  const end = formatDate(data.coverage.end);
  const span = start === end ? start : `${start} – ${end}`;

  return (
    <Link
      href="/data"
      className={cn(
        base,
        "border-[var(--ns-border)] bg-[var(--ns-surface-raised)] text-[var(--ns-text-secondary)]",
        "hover:border-[var(--ns-border-strong)] hover:text-[var(--ns-text)]",
      )}
      // The accessible name states plainly what the visual badge implies.
      aria-label={`Historical AIS data covering ${span} UTC. Not a live feed. View dataset details.`}
      title="NaviSight replays archived AIS observations. It is not a live vessel feed."
    >
      <History className="size-3.5 shrink-0" aria-hidden="true" />
      <span className="hidden md:inline">Historical</span>
      <span className="tabular">{span}</span>
      <span className="hidden text-[var(--ns-text-muted)] lg:inline">UTC</span>
    </Link>
  );
}
