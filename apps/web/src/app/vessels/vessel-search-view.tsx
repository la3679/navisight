"use client";

import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { VesselResultRow } from "@/components/vessel/vessel-bits";
import { Button, Card, CardBody, Input } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingRows } from "@/components/ui/states";
import { api } from "@/lib/api/client";
import { formatCount } from "@/lib/format";

const PAGE_SIZE = 25;

/** Vessel-type filters, keyed by the API's numeric codes. */
const TYPE_FILTERS: { label: string; code?: number }[] = [
  { label: "All types" },
  { label: "Cargo", code: 70 },
  { label: "Tanker", code: 80 },
  { label: "Passenger", code: 60 },
  { label: "Tug", code: 52 },
  { label: "Fishing", code: 30 },
  { label: "Sailing", code: 36 },
  { label: "Pleasure craft", code: 37 },
];

/**
 * Vessel search.
 *
 * Filter state lives in the URL so an investigation is shareable and the back
 * button behaves (SOUL.md §11 / the filters-in-URL requirement).
 */
export function VesselSearchView() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const query = searchParams.get("q") ?? "";
  const typeParam = searchParams.get("type");
  const vesselType = typeParam ? Number(typeParam) : undefined;
  const page = Math.max(0, Number(searchParams.get("page") ?? "0"));

  // Local editing state for the input, resynced when the URL changes (e.g. the
  // user hits Back). This is React's documented "adjust state during render"
  // pattern rather than an effect: it settles before paint, so there is no
  // cascading render and no flash of the stale value.
  const [draft, setDraft] = React.useState(query);
  const [syncedQuery, setSyncedQuery] = React.useState(query);
  if (query !== syncedQuery) {
    setSyncedQuery(query);
    setDraft(query);
  }

  const updateParams = React.useCallback(
    (changes: Record<string, string | undefined>) => {
      const next = new URLSearchParams(searchParams.toString());
      for (const [key, value] of Object.entries(changes)) {
        if (value === undefined || value === "") next.delete(key);
        else next.set(key, value);
      }
      router.replace(next.size ? `/vessels?${next}` : "/vessels", { scroll: false });
    },
    [router, searchParams],
  );

  const trimmed = query.trim();
  // Mirrors the API's server-side allow-list, so we never send a term it will
  // reject with a 400.
  const isSafe = trimmed === "" || /^[A-Za-z0-9 ._@/&()'-]{1,64}$/.test(trimmed);

  const { data, isPending, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["vessels", "list", trimmed, vesselType ?? null, page],
    queryFn: () =>
      api.searchVessels({
        q: trimmed || undefined,
        vesselType,
        limit: PAGE_SIZE,
        skip: page * PAGE_SIZE,
      }),
    enabled: isSafe,
  });

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 md:p-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Vessels</h1>
        <p className="mt-1 text-sm text-[var(--ns-text-secondary)]">
          Every vessel that broadcast at least once in the imported dataset.
        </p>
      </header>

      <form
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          updateParams({ q: draft.trim() || undefined, page: undefined });
        }}
        className="flex gap-2"
      >
        <label htmlFor="vessel-search" className="sr-only">
          Search vessels by name, MMSI, IMO, or call sign
        </label>
        <div className="relative flex-1">
          <Search
            aria-hidden="true"
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--ns-text-muted)]"
          />
          <Input
            id="vessel-search"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Name prefix, or exact MMSI / IMO / call sign"
            className="pl-9"
            maxLength={64}
          />
        </div>
        <Button type="submit" variant="primary">
          Search
        </Button>
      </form>

      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by vessel type">
        {TYPE_FILTERS.map((filter) => {
          const active = filter.code === vesselType;
          return (
            <Button
              key={filter.label}
              size="sm"
              variant={active ? "primary" : "ghost"}
              aria-pressed={active}
              onClick={() =>
                updateParams({
                  type: filter.code === undefined ? undefined : String(filter.code),
                  page: undefined,
                })
              }
            >
              {filter.label}
            </Button>
          );
        })}
      </div>

      {!isSafe ? (
        <EmptyState
          title="That search term cannot be used"
          hint="Search terms may only contain letters, digits, spaces, and basic punctuation."
        />
      ) : isPending ? (
        <LoadingRows rows={8} />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => refetch()} />
      ) : data.length === 0 ? (
        <EmptyState
          title={trimmed ? `No vessel matches “${trimmed}”` : "No vessels found"}
          hint={
            <>
              <p>
                Names match from the start, so “MAERSK” finds a vessel but “ERSK” will not.
                MMSI, IMO, and call sign must match exactly.
              </p>
              {page > 0 ? <p className="mt-2">You may also be past the last page.</p> : null}
            </>
          }
          action={
            page > 0 ? (
              <Button size="sm" onClick={() => updateParams({ page: undefined })}>
                Back to first page
              </Button>
            ) : null
          }
        />
      ) : (
        <>
          <Card>
            <CardBody className="p-1.5" aria-busy={isFetching}>
              <ul className="divide-y divide-[var(--ns-border)]">
                {data.map((vessel) => (
                  <li key={vessel.mmsi}>
                    <VesselResultRow vessel={vessel} />
                  </li>
                ))}
              </ul>
            </CardBody>
          </Card>

          <nav className="flex items-center justify-between" aria-label="Pagination">
            <Button
              size="sm"
              disabled={page === 0}
              onClick={() => updateParams({ page: page > 1 ? String(page - 1) : undefined })}
            >
              Previous
            </Button>
            <span className="text-xs text-[var(--ns-text-muted)] tabular">
              Showing {formatCount(page * PAGE_SIZE + 1)}–
              {formatCount(page * PAGE_SIZE + data.length)}
            </span>
            <Button
              size="sm"
              disabled={data.length < PAGE_SIZE}
              onClick={() => updateParams({ page: String(page + 1) })}
            >
              Next
            </Button>
          </nav>
        </>
      )}
    </div>
  );
}
