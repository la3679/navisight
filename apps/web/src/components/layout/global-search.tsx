/**
 * Global vessel search, also serving as the command palette (Ctrl/Cmd-K).
 *
 * Search is the primary way into this product — a user arrives knowing a
 * vessel name or an MMSI — so it sits in the header on every route rather than
 * being buried on a dedicated page.
 *
 * Results are honest about what matching is available: the API does anchored
 * prefix matching on name plus exact matching on MMSI, IMO, and call sign, and
 * the empty state says so instead of leaving the user to guess why a substring
 * found nothing.
 */

"use client";

import { useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import { Loader2, Search, Ship } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";

import { api, ApiClientError } from "@/lib/api/client";
import { EM_DASH } from "@/lib/format";
import { cn } from "@/lib/utils";

const NAVIGATION = [
  { label: "Operations map", href: "/operations" },
  { label: "Analytics", href: "/analytics" },
  { label: "Ports", href: "/ports" },
  { label: "Maritime Intelligence Copilot", href: "/copilot" },
  { label: "Dataset & data quality", href: "/data" },
];

/** Debounce so typing does not fire a request per keystroke. */
function useDebounced<T>(value: T, delay = 220): T {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    // The update happens in a timeout callback, not synchronously in the
    // effect body, so it does not cause a cascading render.
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

export function GlobalSearch() {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const debouncedQuery = useDebounced(query);

  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setOpen((previous) => !previous);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  // The API rejects regex metacharacters, so we do not send terms it will
  // refuse — the user sees a clean empty state rather than a 400.
  const searchable = debouncedQuery.trim();
  const isSafe = searchable.length >= 2 && /^[A-Za-z0-9 ._@/&()'-]+$/.test(searchable);

  const { data, isFetching, error } = useQuery({
    queryKey: ["vessels", "search", searchable],
    queryFn: () => api.searchVessels({ q: searchable, limit: 8 }),
    enabled: open && isSafe,
    staleTime: 60_000,
  });

  const go = React.useCallback(
    (href: string) => {
      setOpen(false);
      setQuery("");
      router.push(href);
    },
    [router],
  );

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn(
          "flex h-9 w-full max-w-md items-center gap-2 rounded-md border",
          "border-[var(--ns-border)] bg-[var(--ns-surface-raised)] px-3 text-left",
          "text-sm text-[var(--ns-text-muted)] transition-colors",
          "hover:border-[var(--ns-border-strong)]",
        )}
      >
        <Search className="size-4 shrink-0" aria-hidden="true" />
        <span className="flex-1 truncate">Search vessels by name, MMSI, IMO, or call sign</span>
        <kbd className="hidden rounded border border-[var(--ns-border)] px-1.5 py-0.5 font-[family-name:var(--font-mono)] text-[10px] sm:inline">
          Ctrl K
        </kbd>
      </button>

      <Command.Dialog
        open={open}
        onOpenChange={setOpen}
        label="Search vessels and navigate"
        className={cn(
          "fixed top-[12vh] left-1/2 z-50 w-[min(92vw,560px)] -translate-x-1/2",
          "overflow-hidden rounded-xl border border-[var(--ns-border-strong)]",
          "bg-[var(--ns-surface-overlay)] shadow-2xl",
        )}
        overlayClassName="fixed inset-0 z-40 bg-black/50 backdrop-blur-[2px]"
      >
        <div className="flex items-center gap-2 border-b border-[var(--ns-border)] px-3">
          <Search className="size-4 text-[var(--ns-text-muted)]" aria-hidden="true" />
          <Command.Input
            value={query}
            onValueChange={setQuery}
            placeholder="Vessel name, MMSI, IMO, call sign…"
            className="h-12 flex-1 bg-transparent text-sm text-[var(--ns-text)] outline-none placeholder:text-[var(--ns-text-muted)]"
          />
          {isFetching ? (
            <Loader2
              className="size-4 animate-spin text-[var(--ns-text-muted)]"
              aria-label="Searching"
            />
          ) : null}
        </div>

        <Command.List className="max-h-[52vh] overflow-y-auto p-2">
          {searchable.length >= 2 && !isSafe ? (
            <p className="px-2 py-6 text-center text-xs text-[var(--ns-text-muted)]">
              Search terms may only contain letters, digits, spaces, and basic punctuation.
            </p>
          ) : null}

          {error instanceof ApiClientError ? (
            <p className="px-2 py-6 text-center text-xs text-[var(--ns-critical)]">
              {error.message}
            </p>
          ) : null}

          {isSafe && !isFetching && data?.length === 0 ? (
            <div className="px-2 py-6 text-center">
              <p className="text-xs text-[var(--ns-text-muted)]">
                No vessel matches “{searchable}”.
              </p>
              <p className="mx-auto mt-2 max-w-xs text-[11px] leading-relaxed text-[var(--ns-text-muted)]">
                Names match from the start, so “MAERSK” finds a vessel but “ERSK” will not.
                MMSI, IMO, and call sign must match exactly.
              </p>
            </div>
          ) : null}

          {data && data.length > 0 ? (
            <Command.Group
              heading="Vessels"
              className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:tracking-wide [&_[cmdk-group-heading]]:text-[var(--ns-text-muted)] [&_[cmdk-group-heading]]:uppercase"
            >
              {data.map((vessel) => (
                <Command.Item
                  key={vessel.mmsi}
                  value={`${vessel.mmsi} ${vessel.name ?? ""} ${vessel.callSign ?? ""}`}
                  onSelect={() => go(`/vessels/${vessel.mmsi}`)}
                  className={cn(
                    "flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 text-sm",
                    "data-[selected=true]:bg-[var(--ns-surface-raised)]",
                  )}
                >
                  <Ship
                    className="size-4 shrink-0 text-[var(--ns-text-muted)]"
                    aria-hidden="true"
                  />
                  <span className="min-w-0 flex-1 truncate text-[var(--ns-text)]">
                    {vessel.name ?? EM_DASH}
                  </span>
                  <span className="tabular shrink-0 font-[family-name:var(--font-mono)] text-[11px] text-[var(--ns-text-muted)]">
                    {vessel.mmsi}
                  </span>
                  <span className="hidden shrink-0 text-[11px] text-[var(--ns-text-muted)] sm:inline">
                    {vessel.vesselType.label}
                  </span>
                </Command.Item>
              ))}
            </Command.Group>
          ) : null}

          <Command.Group
            heading="Go to"
            className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:tracking-wide [&_[cmdk-group-heading]]:text-[var(--ns-text-muted)] [&_[cmdk-group-heading]]:uppercase"
          >
            {NAVIGATION.map((item) => (
              <Command.Item
                key={item.href}
                value={item.label}
                onSelect={() => go(item.href)}
                className={cn(
                  "cursor-pointer rounded-md px-2 py-2 text-sm text-[var(--ns-text-secondary)]",
                  "data-[selected=true]:bg-[var(--ns-surface-raised)] data-[selected=true]:text-[var(--ns-text)]",
                )}
              >
                {item.label}
              </Command.Item>
            ))}
          </Command.Group>
        </Command.List>
      </Command.Dialog>
    </>
  );
}
