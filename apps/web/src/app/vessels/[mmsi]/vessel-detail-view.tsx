"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, MapPin, Route } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import * as React from "react";

import {
  Badge,
  Button,
  Card,
  CardBody,
  CardDescription,
  CardHeader,
  CardTitle,
  Field,
  Skeleton,
} from "@/components/ui/primitives";
import {
  EmptyState,
  ErrorState,
  LoadingPanel,
  PartialDataNotice,
} from "@/components/ui/states";
import { LatestObservationSummary, VesselName } from "@/components/vessel/vessel-bits";
import { api, ApiClientError } from "@/lib/api/client";
import {
  EM_DASH,
  formatBearing,
  formatCoordinates,
  formatCount,
  formatDraft,
  formatImo,
  formatMeters,
  formatSpeed,
  formatTimestamp,
} from "@/lib/format";
import { mapFamilyColor } from "@/lib/viz/palette";

/**
 * The 3D inspector is lazy-loaded and client-only.
 *
 * Three.js and React Three Fiber are a large bundle and WebGL cannot render on
 * the server, so this route must not ship them until the panel is actually
 * shown (SOUL.md §13). `ssr: false` requires a Client Component in Next 16.
 */
const VesselInspector3D = dynamic(
  () => import("@/components/three/vessel-inspector").then((m) => m.VesselInspector),
  {
    ssr: false,
    loading: () => <Skeleton className="h-[280px] w-full" />,
  },
);

/**
 * The track map is also lazy-loaded: MapLibre is heavy and is not needed until
 * the user reaches a vessel that has one.
 */
const VesselTrackMap = dynamic(
  () => import("@/components/map/vessel-track-map").then((m) => m.VesselTrackMap),
  {
    ssr: false,
    loading: () => <Skeleton className="h-[360px] w-full" />,
  },
);

export function VesselDetailView({ mmsi }: { mmsi: string }) {
  const vessel = useQuery({
    queryKey: ["vessel", mmsi],
    queryFn: () => api.vessel(mmsi),
  });

  const latest = useQuery({
    queryKey: ["vessel", mmsi, "latest"],
    queryFn: () => api.latestObservation(mmsi),
    enabled: vessel.isSuccess,
  });

  const track = useQuery({
    queryKey: ["vessel", mmsi, "track"],
    queryFn: () => api.track(mmsi, { max_points: 1000 }),
    enabled: vessel.isSuccess,
  });

  const positions = useQuery({
    queryKey: ["vessel", mmsi, "positions"],
    queryFn: () => api.positions(mmsi, { limit: 25 }),
    enabled: vessel.isSuccess,
  });

  if (vessel.isPending) {
    return (
      <div className="mx-auto max-w-6xl p-4 md:p-6">
        <LoadingPanel />
      </div>
    );
  }

  if (vessel.isError) {
    const notFound =
      vessel.error instanceof ApiClientError && vessel.error.kind === "not_found";
    return (
      <div className="mx-auto max-w-6xl space-y-4 p-4 md:p-6">
        <Link
          href="/vessels"
          className="inline-flex items-center gap-1.5 text-sm text-[var(--ns-text-secondary)] hover:text-[var(--ns-text)]"
        >
          <ArrowLeft className="size-4" aria-hidden="true" />
          All vessels
        </Link>
        {notFound ? (
          <EmptyState
            title={`No vessel with MMSI ${mmsi}`}
            hint="This MMSI did not broadcast during the period covered by the imported dataset."
            action={
              <Button size="sm" onClick={() => window.history.back()}>
                Go back
              </Button>
            }
          />
        ) : (
          <ErrorState error={vessel.error} onRetry={() => vessel.refetch()} />
        )}
      </div>
    );
  }

  const data = vessel.data;
  const dimensions = data.dimensions;

  return (
    <div className="mx-auto max-w-6xl space-y-5 p-4 md:p-6">
      <div>
        <Link
          href="/vessels"
          className="inline-flex items-center gap-1.5 text-sm text-[var(--ns-text-secondary)] hover:text-[var(--ns-text)]"
        >
          <ArrowLeft className="size-4" aria-hidden="true" />
          All vessels
        </Link>
      </div>

      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight">
            <VesselName vessel={data} />
          </h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 text-sm text-[var(--ns-text-secondary)]">
              <span
                aria-hidden="true"
                className="size-2.5 rounded-full"
                style={{ backgroundColor: mapFamilyColor(data.vesselType.family) }}
              />
              {data.vesselType.label}
            </span>
            <Badge tone="neutral">MMSI {data.mmsi}</Badge>
            {data.imo ? <Badge tone="neutral">{formatImo(data.imo)}</Badge> : null}
          </div>
        </div>

        {latest.isSuccess ? (
          <Link
            href={
              `/operations?focus=${data.mmsi}` +
              `&lon=${latest.data.coordinates.longitude}` +
              `&lat=${latest.data.coordinates.latitude}`
            }
            className="inline-flex h-9 items-center gap-1.5 rounded-md border border-[var(--ns-border)] bg-[var(--ns-surface-raised)] px-3.5 text-sm font-medium transition-colors hover:border-[var(--ns-border-strong)] hover:bg-[var(--ns-surface-overlay)]"
          >
            <MapPin className="size-4" aria-hidden="true" />
            Show on map
          </Link>
        ) : null}
      </header>

      <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
        <div className="min-w-0 space-y-5">
          <Card>
            <CardHeader>
              <CardTitle>Track</CardTitle>
              <CardDescription>
                Every observation recorded for this vessel in the dataset, in chronological
                order.
              </CardDescription>
            </CardHeader>
            <CardBody>
              {track.isPending ? (
                <Skeleton className="h-[360px] w-full" />
              ) : track.isError ? (
                <ErrorState error={track.error} onRetry={() => track.refetch()} />
              ) : track.data.points.length === 0 ? (
                <EmptyState title="No positions recorded" />
              ) : (
                <>
                  <VesselTrackMap track={track.data} />
                  <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-[var(--ns-text-muted)]">
                    <span className="inline-flex items-center gap-1.5">
                      <Route className="size-3.5" aria-hidden="true" />
                      {formatCount(track.data.meta.rawPointCount)} observations
                    </span>
                    <span className="tabular">
                      {formatTimestamp(track.data.meta.start, { seconds: false })} →{" "}
                      {formatTimestamp(track.data.meta.end, { seconds: false })}
                    </span>
                  </div>
                  {/* Honesty about simplification is required, not optional. */}
                  {track.data.meta.simplified ? (
                    <PartialDataNotice className="mt-2">
                      Showing {formatCount(track.data.meta.returnedPointCount)} of{" "}
                      {formatCount(track.data.meta.rawPointCount)} observations. The path was
                      simplified for rendering using{" "}
                      {track.data.meta.method === "douglas_peucker"
                        ? "Douglas–Peucker line simplification, which keeps turns and drops redundant straight-line points"
                        : "uniform sampling"}
                      . No position is invented or interpolated.
                    </PartialDataNotice>
                  ) : null}
                </>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Recent observations</CardTitle>
              <CardDescription>
                The 25 most recent AIS broadcasts from this vessel, newest first.
              </CardDescription>
            </CardHeader>
            <CardBody>
              {positions.isPending ? (
                <LoadingPanel />
              ) : positions.isError ? (
                <ErrorState error={positions.error} onRetry={() => positions.refetch()} />
              ) : positions.data.items.length === 0 ? (
                <EmptyState title="No observations" />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <caption className="sr-only">
                      Recent AIS observations for MMSI {data.mmsi}
                    </caption>
                    <thead>
                      <tr className="border-b border-[var(--ns-border)] text-left text-[var(--ns-text-secondary)]">
                        <th scope="col" className="py-1.5 pr-3 font-medium">
                          Time (UTC)
                        </th>
                        <th scope="col" className="py-1.5 pr-3 font-medium">
                          Position
                        </th>
                        <th scope="col" className="py-1.5 pr-3 text-right font-medium">
                          Speed
                        </th>
                        <th scope="col" className="py-1.5 pr-3 text-right font-medium">
                          Course
                        </th>
                        <th scope="col" className="py-1.5 font-medium">
                          Status
                        </th>
                      </tr>
                    </thead>
                    <tbody className="font-[family-name:var(--font-mono)]">
                      {positions.data.items.map((item) => (
                        <tr
                          key={`${item.timestamp}-${item.coordinates.longitude}`}
                          className="border-b border-[var(--ns-border)] last:border-0"
                        >
                          <td className="tabular py-1.5 pr-3">
                            {formatTimestamp(item.timestamp)}
                          </td>
                          <td className="tabular py-1.5 pr-3 text-[var(--ns-text-secondary)]">
                            {formatCoordinates(
                              item.coordinates.longitude,
                              item.coordinates.latitude,
                            )}
                          </td>
                          <td className="tabular py-1.5 pr-3 text-right">
                            {formatSpeed(item.navigation.speedOverGroundKnots)}
                          </td>
                          <td className="tabular py-1.5 pr-3 text-right">
                            {formatBearing(item.navigation.courseOverGroundDegrees)}
                          </td>
                          <td className="py-1.5 font-[family-name:var(--font-sans)] text-[var(--ns-text-secondary)]">
                            {item.navigation.statusLabel}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardBody>
          </Card>
        </div>

        <aside className="space-y-5">
          <Card>
            <CardHeader>
              <CardTitle>Latest observation</CardTitle>
            </CardHeader>
            <CardBody>
              {latest.isPending ? (
                <LoadingPanel className="p-0" />
              ) : latest.isError ? (
                <ErrorState error={latest.error} onRetry={() => latest.refetch()} />
              ) : (
                <LatestObservationSummary observation={latest.data} />
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Vessel</CardTitle>
              <CardDescription>
                Self-reported over AIS. Blank fields were never broadcast.
              </CardDescription>
            </CardHeader>
            <CardBody>
              <dl className="grid grid-cols-2 gap-3">
                <Field label="MMSI" value={data.mmsi} mono />
                <Field label="IMO" value={data.imo ? formatImo(data.imo) : EM_DASH} mono />
                <Field label="Call sign" value={data.callSign ?? EM_DASH} mono />
                <Field label="Type" value={data.vesselType.label} />
                <Field label="Length" value={formatMeters(dimensions?.lengthMeters)} />
                <Field label="Beam" value={formatMeters(dimensions?.widthMeters)} />
                <Field label="Draft" value={formatDraft(dimensions?.draftMeters)} />
                <Field label="Observations" value={formatCount(data.observationCount)} mono />
                <Field
                  label="First seen"
                  value={formatTimestamp(data.firstSeenAt, { seconds: false })}
                  mono
                />
                <Field
                  label="Last seen"
                  value={formatTimestamp(data.lastSeenAt, { seconds: false })}
                  mono
                />
              </dl>
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Representative visualisation</CardTitle>
              <CardDescription>
                A generic hull shaped by this vessel&rsquo;s reported dimensions and oriented to
                its last known heading. It is not a model of the actual ship.
              </CardDescription>
            </CardHeader>
            <CardBody>
              <VesselInspector3D
                lengthMeters={dimensions?.lengthMeters ?? null}
                widthMeters={dimensions?.widthMeters ?? null}
                draftMeters={dimensions?.draftMeters ?? null}
                family={data.vesselType.family}
                headingDegrees={
                  latest.data?.navigation.headingDegrees ??
                  latest.data?.navigation.courseOverGroundDegrees ??
                  null
                }
                vesselName={data.name}
              />
            </CardBody>
          </Card>
        </aside>
      </div>
    </div>
  );
}
