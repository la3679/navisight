"use client";

import { useQuery } from "@tanstack/react-query";
import { Filter, Info, PanelRightClose, PanelRightOpen, X } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { ReplayControls } from "@/components/map/replay-controls";
import type { MapFilters } from "@/components/map/operations-map";
import { Badge, Button, Skeleton } from "@/components/ui/primitives";
import { ErrorState, LoadingPanel, NoDataState } from "@/components/ui/states";
import { LatestObservationSummary, VesselName } from "@/components/vessel/vessel-bits";
import { api } from "@/lib/api/client";
import type { MapVessel } from "@/lib/api/types";
import { formatCount, formatSpeed } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * MapLibre and deck.gl together are the heaviest code in the application and
 * are useless on the server, so this route loads them on demand rather than
 * putting them in the shared bundle (SOUL.md §13).
 */
const OperationsMap = dynamic(
  () => import("@/components/map/operations-map").then((m) => m.OperationsMap),
  {
    ssr: false,
    loading: () => <Skeleton className="size-full rounded-none" />,
  },
);

const TYPE_OPTIONS = [
  { label: "All", value: undefined },
  { label: "Cargo", value: 70 },
  { label: "Tanker", value: 80 },
  { label: "Passenger", value: 60 },
  { label: "Tug", value: 52 },
  { label: "Fishing", value: 30 },
] as const;

const SPEED_OPTIONS = [
  { label: "Any speed", min: undefined, max: undefined },
  { label: "Stopped (< 0.5 kn)", min: undefined, max: 0.5 },
  { label: "Manoeuvring (0.5–5)", min: 0.5, max: 5 },
  { label: "Under way (> 5 kn)", min: 5, max: undefined },
] as const;

export function OperationsView() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [selected, setSelected] = React.useState<MapVessel | null>(null);
  const [panelOpen, setPanelOpen] = React.useState(true);
  const [filtersOpen, setFiltersOpen] = React.useState(false);
  const [replayAt, setReplayAt] = React.useState<string | null>(null);
  const [status, setStatus] = React.useState({
    total: 0,
    shown: 0,
    mode: "vessels",
    truncated: false,
  });

  // Filters live in the URL so an investigation is shareable.
  const vesselType = searchParams.get("type") ? Number(searchParams.get("type")) : undefined;
  const speedIndex = Number(searchParams.get("speed") ?? "0");
  const speed = SPEED_OPTIONS[speedIndex] ?? SPEED_OPTIONS[0];
  const transceiver = (searchParams.get("tx") as "A" | "B" | null) ?? undefined;

  const focusLon = searchParams.get("lon");
  const focusLat = searchParams.get("lat");
  // Memoised on the raw strings: the map flies to this on identity change, so
  // a fresh object every render would restart the animation on every render.
  const focus = React.useMemo(
    () =>
      focusLon && focusLat ? { longitude: Number(focusLon), latitude: Number(focusLat) } : null,
    [focusLon, focusLat],
  );
  const focusMmsi = searchParams.get("focus");

  const filters: MapFilters = React.useMemo(
    () => ({
      vesselType,
      transceiver,
      minSpeed: speed.min,
      maxSpeed: speed.max,
    }),
    [vesselType, transceiver, speed],
  );

  const updateParams = React.useCallback(
    (changes: Record<string, string | undefined>) => {
      const next = new URLSearchParams(searchParams.toString());
      for (const [key, value] of Object.entries(changes)) {
        if (value === undefined) next.delete(key);
        else next.set(key, value);
      }
      router.replace(next.size ? `/operations?${next}` : "/operations", { scroll: false });
    },
    [router, searchParams],
  );

  const dataset = useQuery({ queryKey: ["dataset", "status"], queryFn: api.datasetStatus });

  const selectedMmsi = selected?.mmsi ?? focusMmsi ?? null;

  const detail = useQuery({
    queryKey: ["vessel", selectedMmsi],
    queryFn: () => api.vessel(selectedMmsi!),
    enabled: selectedMmsi !== null,
  });

  const latest = useQuery({
    queryKey: ["vessel", selectedMmsi, "latest"],
    queryFn: () => api.latestObservation(selectedMmsi!),
    enabled: selectedMmsi !== null,
  });

  const activeFilterCount =
    (vesselType !== undefined ? 1 : 0) + (speedIndex > 0 ? 1 : 0) + (transceiver ? 1 : 0);

  if (dataset.isPending) {
    return <LoadingPanel className="m-6" />;
  }
  if (dataset.isError) {
    return (
      <div className="p-6">
        <ErrorState error={dataset.error} onRetry={() => dataset.refetch()} />
      </div>
    );
  }
  if (!dataset.data.hasData) {
    return (
      <div className="p-6">
        <NoDataState />
      </div>
    );
  }

  const coverage = dataset.data.coverage;

  return (
    <div className="flex h-[calc(100dvh-3.5rem)] flex-col">
      {/* Visually hidden, but present. The map is the whole screen here, so
          there is no room for a visible page title — and a page whose topmost
          heading is an h2 gives a screen-reader user a broken outline to
          navigate by. Every other route has an h1; this one has to as well
          (SOUL.md §12). */}
      <h1 className="sr-only">Operations map</h1>

      {/* Filter bar: primary filters visible, nothing hidden behind a menu that
          the user has to discover. */}
      <div className="flex flex-wrap items-center gap-2 border-b border-[var(--ns-border)] bg-[var(--ns-surface)] px-3 py-2">
        <Button
          size="sm"
          variant={filtersOpen ? "primary" : "secondary"}
          onClick={() => setFiltersOpen((open) => !open)}
          aria-expanded={filtersOpen}
        >
          <Filter aria-hidden="true" />
          Filters
          {activeFilterCount > 0 ? (
            <span className="ml-0.5 rounded-full bg-[var(--ns-accent-contrast)] px-1.5 text-[10px] text-[var(--ns-accent)]">
              {activeFilterCount}
            </span>
          ) : null}
        </Button>

        <div className="flex items-center gap-2 text-xs text-[var(--ns-text-muted)]">
          <span className="tabular">
            {status.mode === "clusters"
              ? `${formatCount(status.total)} vessels, aggregated into ${formatCount(status.shown)} cells`
              : `${formatCount(status.shown)} of ${formatCount(status.total)} vessels in view`}
          </span>
          {status.truncated ? (
            <Badge tone="warning">
              <Info className="size-3" aria-hidden="true" />
              Truncated
            </Badge>
          ) : null}
          {status.mode === "clusters" ? (
            <Badge tone="neutral">Zoom in for individual vessels</Badge>
          ) : null}
        </div>

        <div className="ml-auto">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setPanelOpen((open) => !open)}
            aria-expanded={panelOpen}
          >
            {panelOpen ? (
              <PanelRightClose aria-hidden="true" />
            ) : (
              <PanelRightOpen aria-hidden="true" />
            )}
            <span className="hidden sm:inline">Details</span>
          </Button>
        </div>
      </div>

      {filtersOpen ? (
        <div className="flex flex-wrap items-center gap-4 border-b border-[var(--ns-border)] bg-[var(--ns-surface)] px-3 py-2.5">
          <fieldset className="flex flex-wrap items-center gap-1.5">
            <legend className="sr-only">Vessel type</legend>
            <span className="mr-1 text-[11px] tracking-wide text-[var(--ns-text-muted)] uppercase">
              Type
            </span>
            {TYPE_OPTIONS.map((option) => (
              <Button
                key={option.label}
                size="sm"
                variant={option.value === vesselType ? "primary" : "ghost"}
                aria-pressed={option.value === vesselType}
                onClick={() =>
                  updateParams({
                    type: option.value === undefined ? undefined : String(option.value),
                  })
                }
              >
                {option.label}
              </Button>
            ))}
          </fieldset>

          <fieldset className="flex flex-wrap items-center gap-1.5">
            <legend className="sr-only">Speed</legend>
            <span className="mr-1 text-[11px] tracking-wide text-[var(--ns-text-muted)] uppercase">
              Speed
            </span>
            {SPEED_OPTIONS.map((option, index) => (
              <Button
                key={option.label}
                size="sm"
                variant={index === speedIndex ? "primary" : "ghost"}
                aria-pressed={index === speedIndex}
                onClick={() => updateParams({ speed: index === 0 ? undefined : String(index) })}
              >
                {option.label}
              </Button>
            ))}
          </fieldset>

          <fieldset className="flex flex-wrap items-center gap-1.5">
            <legend className="sr-only">Transceiver class</legend>
            <span className="mr-1 text-[11px] tracking-wide text-[var(--ns-text-muted)] uppercase">
              Transceiver
            </span>
            {(["A", "B"] as const).map((value) => (
              <Button
                key={value}
                size="sm"
                variant={transceiver === value ? "primary" : "ghost"}
                aria-pressed={transceiver === value}
                onClick={() => updateParams({ tx: transceiver === value ? undefined : value })}
              >
                Class {value}
              </Button>
            ))}
          </fieldset>

          {activeFilterCount > 0 ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => updateParams({ type: undefined, speed: undefined, tx: undefined })}
            >
              <X aria-hidden="true" />
              Clear
            </Button>
          ) : null}
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1">
          <OperationsMap
            filters={filters}
            replayAt={replayAt}
            selectedMmsi={selectedMmsi}
            onSelect={setSelected}
            onStatus={setStatus}
            focus={focus}
          />
        </div>

        {panelOpen ? (
          <aside
            className="hidden w-[320px] shrink-0 overflow-y-auto border-l border-[var(--ns-border)] bg-[var(--ns-surface)] lg:block"
            aria-label="Selected vessel"
          >
            {selectedMmsi === null ? (
              <div className="p-4">
                <h2 className="text-sm font-semibold">No vessel selected</h2>
                <p className="mt-1.5 text-xs leading-relaxed text-[var(--ns-text-secondary)]">
                  Click a vessel on the map to see its identity, latest observation, and a link
                  to its full history.
                </p>
                <p className="mt-3 text-xs leading-relaxed text-[var(--ns-text-muted)]">
                  Marks show each vessel&rsquo;s newest known position in the archived data. Use
                  the replay controls below to step back through the day.
                </p>
              </div>
            ) : (
              <div className="space-y-4 p-4">
                <div className="flex items-start justify-between gap-2">
                  <h2 className="min-w-0 text-sm font-semibold">
                    {detail.data ? (
                      <VesselName vessel={detail.data} />
                    ) : (
                      <span className="font-[family-name:var(--font-mono)]">
                        {selectedMmsi}
                      </span>
                    )}
                  </h2>
                  <Button
                    size="icon"
                    variant="ghost"
                    onClick={() => {
                      setSelected(null);
                      updateParams({ focus: undefined, lon: undefined, lat: undefined });
                    }}
                    aria-label="Clear selection"
                  >
                    <X aria-hidden="true" />
                  </Button>
                </div>

                {latest.isPending ? (
                  <LoadingPanel className="p-0" />
                ) : latest.isError ? (
                  <ErrorState error={latest.error} onRetry={() => latest.refetch()} />
                ) : (
                  <LatestObservationSummary observation={latest.data} />
                )}

                {detail.data ? (
                  <dl className="grid grid-cols-2 gap-2 border-t border-[var(--ns-border)] pt-3 text-xs">
                    <div>
                      <dt className="text-[10px] text-[var(--ns-text-muted)] uppercase">
                        Type
                      </dt>
                      <dd>{detail.data.vesselType.label}</dd>
                    </div>
                    <div>
                      <dt className="text-[10px] text-[var(--ns-text-muted)] uppercase">
                        Observations
                      </dt>
                      <dd className="tabular">{formatCount(detail.data.observationCount)}</dd>
                    </div>
                  </dl>
                ) : null}

                <Link
                  href={`/vessels/${selectedMmsi}`}
                  className={cn(
                    "flex h-9 w-full items-center justify-center rounded-md",
                    "bg-[var(--ns-accent)] text-sm font-medium text-[var(--ns-accent-contrast)]",
                    "transition-colors hover:bg-[var(--ns-accent-strong)]",
                  )}
                >
                  Open full vessel record
                </Link>
              </div>
            )}
          </aside>
        ) : null}
      </div>

      {/* Mobile selection sheet: the panel is hidden on small screens, so the
          selection still needs somewhere to go. */}
      {selectedMmsi && !panelOpen ? null : null}
      {selectedMmsi ? (
        <div className="border-t border-[var(--ns-border)] bg-[var(--ns-surface)] px-3 py-2 lg:hidden">
          <div className="flex items-center gap-3">
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">
                {detail.data ? <VesselName vessel={detail.data} /> : selectedMmsi}
              </p>
              <p className="tabular text-[11px] text-[var(--ns-text-muted)]">
                {formatSpeed(latest.data?.navigation.speedOverGroundKnots ?? null)}
              </p>
            </div>
            <Link
              href={`/vessels/${selectedMmsi}`}
              className="text-xs font-medium text-[var(--ns-accent)]"
            >
              Open
            </Link>
          </div>
        </div>
      ) : null}

      {coverage.start && coverage.end ? (
        <ReplayControls
          coverageStart={coverage.start}
          coverageEnd={coverage.end}
          value={replayAt}
          onChange={setReplayAt}
        />
      ) : null}
    </div>
  );
}
