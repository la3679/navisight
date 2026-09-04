"use client";

import { useQuery } from "@tanstack/react-query";
import { Anchor, Info, MapPin, Search } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Badge, Button, Card, CardBody, Input, Skeleton } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingRows, NotConfiguredState } from "@/components/ui/states";
import { ApiClientError, api } from "@/lib/api/client";
import type { Port } from "@/lib/api/types";
import { formatCoordinates, formatDistance, formatSpeed, formatTimestamp } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Port intelligence.
 *
 * NaviSight ships no port gazetteer, and this page says so rather than
 * pretending otherwise. The AIS source contains no port information — it is a
 * stream of vessel broadcasts — so a port list has to come from a registry the
 * operator loads. Inventing one to fill the screen would put fabricated place
 * names beside real vessel positions, which is the failure SOUL.md §9 calls the
 * worst possible one for this product.
 *
 * With a gazetteer loaded, the question this page answers is **proximity**:
 * which vessels' last archived position sits within a radius of a port. That is
 * deliberately not called a port call. AIS says where a vessel was, not that it
 * berthed, loaded, or was even bound there — a vessel transiting past at 12
 * knots appears on the same footing as one alongside, and the page says that
 * where the reader can see it.
 */

const RADIUS_OPTIONS = [5, 15, 40] as const;

function isNotConfigured(error: unknown): boolean {
  return error instanceof ApiClientError && error.kind === "not_configured";
}

function PortRow({
  port,
  selected,
  onSelect,
}: {
  port: Port;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-current={selected ? "true" : undefined}
        className={cn(
          "flex w-full items-baseline gap-3 rounded-md px-2.5 py-2 text-left transition-colors",
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--ns-accent)]",
          selected
            ? "bg-[color-mix(in_oklab,var(--ns-accent)_14%,transparent)]"
            : "hover:bg-[var(--ns-surface-raised)]",
        )}
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-[var(--ns-text)]">
            {port.name}
          </span>
          <span className="block truncate text-[11px] text-[var(--ns-text-muted)]">
            {[port.country, port.unlocode].filter(Boolean).join(" · ") || "—"}
          </span>
        </span>
        <span className="shrink-0 font-[family-name:var(--font-mono)] text-[10px] tabular text-[var(--ns-text-muted)]">
          {formatCoordinates(port.coordinates.longitude, port.coordinates.latitude)}
        </span>
      </button>
    </li>
  );
}

export function PortsView() {
  const [query, setQuery] = React.useState("");
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [radiusKm, setRadiusKm] = React.useState<number>(15);

  const deferredQuery = React.useDeferredValue(query);

  const ports = useQuery({
    queryKey: ["ports", deferredQuery],
    queryFn: () => api.ports({ q: deferredQuery || undefined, limit: 100 }),
    retry: false,
  });

  const activity = useQuery({
    queryKey: ["ports", selectedId, "activity", radiusKm],
    queryFn: () => api.portActivity(selectedId!, { radiusKm, limit: 50 }),
    enabled: selectedId !== null,
  });

  const header = (
    <header>
      <h1 className="text-xl font-semibold tracking-tight">Ports</h1>
      <p className="mt-1 max-w-2xl text-sm text-[var(--ns-text-secondary)]">
        Port reference data is optional and supplied by you. NaviSight does not ship a
        gazetteer — the AIS archive contains no port information.
      </p>
    </header>
  );

  if (ports.isError && isNotConfigured(ports.error)) {
    return (
      <div className="mx-auto max-w-4xl space-y-5 p-4 md:p-6">
        {header}
        <NotConfiguredState title="No port reference data has been loaded">
          <p>
            NaviSight ships no port list. Inventing one would place fabricated place names
            beside real vessel positions, so this surface stays empty until you load a
            registry you trust.
          </p>
          <pre className="mt-3 overflow-x-auto rounded bg-[var(--ns-surface-raised)] p-2 text-left font-[family-name:var(--font-mono)] text-[11px]">
            {`cd apps/api
uv run navisight-data ports load <file>`}
          </pre>
          <p className="mt-3">
            A CSV needs <code>id</code>, <code>name</code>, <code>latitude</code>, and{" "}
            <code>longitude</code>; <code>country</code>, <code>unlocode</code>,{" "}
            <code>harbourSize</code> and <code>harbourType</code> are used when present, and
            any other column is ignored. A GeoJSON <code>FeatureCollection</code> of points
            works too. The U.S. NGA World Port Index is public domain and maps onto this
            schema directly.
          </p>
        </NotConfiguredState>

        <Card>
          <CardBody className="pt-4">
            <h2 className="text-sm font-semibold">What loading one enables</h2>
            <ul className="mt-2 space-y-1.5 text-xs leading-relaxed text-[var(--ns-text-secondary)]">
              <li>
                Search a registry by name, country, or UN/LOCODE and jump to a port&rsquo;s
                position on the operations map.
              </li>
              <li>
                List the vessels whose <em>last archived position</em> sits within a chosen
                radius of a port, with the measured distance to each.
              </li>
            </ul>
            <p className="mt-3 text-[11px] leading-relaxed text-[var(--ns-text-muted)]">
              Proximity is not a port call. AIS records where a vessel was, not that it
              berthed, loaded, or was bound anywhere — NaviSight will not infer one from the
              other.
            </p>
          </CardBody>
        </Card>
      </div>
    );
  }

  const selected = activity.data?.port ?? null;

  return (
    <div className="mx-auto max-w-6xl space-y-5 p-4 md:p-6">
      {header}

      <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
        {/* ------------------------------------------------------- registry */}
        <Card className="min-w-0">
          <CardBody className="space-y-3 pt-4">
            <label className="relative block">
              <span className="sr-only">Search ports</span>
              <Search
                aria-hidden="true"
                className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-[var(--ns-text-muted)]"
              />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Name, country, or UN/LOCODE"
                className="pl-8"
              />
            </label>

            {ports.isPending ? (
              <LoadingRows rows={6} />
            ) : ports.isError ? (
              <ErrorState error={ports.error} onRetry={() => ports.refetch()} />
            ) : ports.data.length === 0 ? (
              <EmptyState
                title="No ports matched"
                hint={
                  query
                    ? `Nothing in the loaded registry matches “${query}”.`
                    : "The loaded registry is empty."
                }
              />
            ) : (
              <>
                <p className="text-[11px] text-[var(--ns-text-muted)]">
                  {ports.data.length} port{ports.data.length === 1 ? "" : "s"}
                  {ports.data.length === 100 ? " (first 100)" : ""} · source{" "}
                  <span className="font-[family-name:var(--font-mono)]">
                    {ports.data[0]?.source}
                  </span>
                </p>
                <ul className="max-h-[520px] space-y-0.5 overflow-y-auto">
                  {ports.data.map((port) => (
                    <PortRow
                      key={port.id}
                      port={port}
                      selected={port.id === selectedId}
                      onSelect={() => setSelectedId(port.id)}
                    />
                  ))}
                </ul>
              </>
            )}
          </CardBody>
        </Card>

        {/* ------------------------------------------------------- activity */}
        <Card className="min-w-0">
          <CardBody className="pt-4">
            {selectedId === null ? (
              <EmptyState
                title="Select a port"
                hint="Choose a port to see which vessels' last archived position was near it."
              />
            ) : (
              <div className="space-y-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="flex items-center gap-2 text-sm font-semibold">
                      <Anchor className="size-4 text-[var(--ns-accent)]" aria-hidden="true" />
                      {selected?.name ?? <Skeleton className="h-4 w-40" />}
                    </h2>
                    {selected ? (
                      <p className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-[var(--ns-text-muted)]">
                        <span className="font-[family-name:var(--font-mono)] tabular">
                          {formatCoordinates(
                            selected.coordinates.longitude,
                            selected.coordinates.latitude,
                          )}
                        </span>
                        {selected.country ? <span>{selected.country}</span> : null}
                        {selected.unlocode ? <Badge>{selected.unlocode}</Badge> : null}
                        {selected.harbourSize ? (
                          <Badge>{selected.harbourSize} harbour</Badge>
                        ) : null}
                      </p>
                    ) : null}
                  </div>

                  {selected ? (
                    <Link
                      href={`/operations?lon=${selected.coordinates.longitude}&lat=${selected.coordinates.latitude}`}
                      className="inline-flex h-8 items-center gap-1.5 rounded-md border
                                 border-[var(--ns-border)] px-2.5 text-xs font-medium
                                 hover:bg-[var(--ns-surface-raised)]"
                    >
                      <MapPin className="size-3.5" aria-hidden="true" />
                      Show on map
                    </Link>
                  ) : null}
                </div>

                <fieldset className="flex flex-wrap items-center gap-1.5">
                  <legend className="sr-only">Search radius</legend>
                  <span className="mr-1 text-[11px] uppercase tracking-wide text-[var(--ns-text-muted)]">
                    Radius
                  </span>
                  {RADIUS_OPTIONS.map((option) => (
                    <Button
                      key={option}
                      size="sm"
                      variant={option === radiusKm ? "primary" : "ghost"}
                      aria-pressed={option === radiusKm}
                      onClick={() => setRadiusKm(option)}
                    >
                      {option} km
                    </Button>
                  ))}
                </fieldset>

                {/* The interpretation boundary, stated where it is being crossed. */}
                <p className="flex items-start gap-1.5 rounded-md bg-[var(--ns-surface-raised)] px-2.5 py-2 text-[11px] leading-relaxed text-[var(--ns-text-secondary)]">
                  <Info
                    className="mt-px size-3.5 shrink-0 text-[var(--ns-info)]"
                    aria-hidden="true"
                  />
                  <span>
                    These are vessels whose <strong>last observation in the archive</strong>{" "}
                    fell inside the radius. That is proximity, not a port call — a vessel
                    passing at speed appears here alongside one that was alongside.
                  </span>
                </p>

                {activity.isPending ? (
                  <LoadingRows rows={5} />
                ) : activity.isError ? (
                  <ErrorState error={activity.error} onRetry={() => activity.refetch()} />
                ) : activity.data.vessels.length === 0 ? (
                  <EmptyState
                    title="No vessels within this radius"
                    hint="No vessel's final archived position falls inside the selected radius. Try a wider one."
                  />
                ) : (
                  <div className="overflow-x-auto rounded-md border border-[var(--ns-border)]">
                    <table className="w-full text-xs">
                      <caption className="sr-only">
                        Vessels within {radiusKm} km of {selected?.name}
                      </caption>
                      <thead className="bg-[var(--ns-surface-raised)]">
                        <tr>
                          <th scope="col" className="px-2.5 py-1.5 text-left font-medium">
                            Vessel
                          </th>
                          <th scope="col" className="px-2.5 py-1.5 text-left font-medium">
                            Type
                          </th>
                          <th scope="col" className="px-2.5 py-1.5 text-right font-medium">
                            Distance
                          </th>
                          <th scope="col" className="px-2.5 py-1.5 text-right font-medium">
                            Speed
                          </th>
                          <th scope="col" className="px-2.5 py-1.5 text-right font-medium">
                            Last seen (UTC)
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {activity.data.vessels.map((entry) => (
                          <tr
                            key={entry.vessel.mmsi}
                            className="border-t border-[var(--ns-border)]"
                          >
                            <td className="px-2.5 py-1.5">
                              <Link
                                href={`/vessels/${entry.vessel.mmsi}`}
                                className="font-medium text-[var(--ns-accent)] hover:underline"
                              >
                                {entry.vessel.name ?? `MMSI ${entry.vessel.mmsi}`}
                              </Link>
                            </td>
                            <td className="px-2.5 py-1.5 text-[var(--ns-text-secondary)]">
                              {entry.vessel.vesselType.label}
                            </td>
                            <td className="px-2.5 py-1.5 text-right font-[family-name:var(--font-mono)] tabular">
                              {formatDistance(entry.distanceKm)}
                            </td>
                            <td className="px-2.5 py-1.5 text-right font-[family-name:var(--font-mono)] tabular">
                              {formatSpeed(entry.speedOverGroundKnots)}
                            </td>
                            <td className="px-2.5 py-1.5 text-right font-[family-name:var(--font-mono)] tabular text-[var(--ns-text-muted)]">
                              {formatTimestamp(entry.timestamp)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {activity.data?.truncated ? (
                  <p className="text-[11px] text-[var(--ns-warning)]">
                    More vessels were inside this radius than are listed. Narrow the radius
                    to see a complete set.
                  </p>
                ) : null}
              </div>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
