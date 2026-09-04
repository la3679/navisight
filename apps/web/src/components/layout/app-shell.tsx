/**
 * The application shell: navigation rail, header, and content region.
 *
 * A compact left rail on desktop keeps horizontal space for the map, which is
 * the product on the operations screen. On small screens it collapses to a
 * bottom bar rather than a shrunken sidebar, because a 64px rail on a phone is
 * wasted width.
 *
 * The header carries the dataset date permanently. That is deliberate: the
 * data is a single historical day and the interface must say so where the user
 * is actually looking, not in a tooltip (ADR-0008).
 */

"use client";

import {
  Activity,
  Anchor,
  Database,
  LayoutDashboard,
  Map as MapIcon,
  Ship,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

import { cn } from "@/lib/utils";
import { DatasetBadge } from "./dataset-badge";
import { GlobalSearch } from "./global-search";
import { ThemeToggle } from "./theme-toggle";

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  /** Short label for the mobile bar, where horizontal room is scarce. */
  short: string;
};

const NAV: NavItem[] = [
  { href: "/", label: "Overview", short: "Home", icon: LayoutDashboard },
  { href: "/operations", label: "Operations", short: "Map", icon: MapIcon },
  { href: "/vessels", label: "Vessels", short: "Ships", icon: Ship },
  { href: "/analytics", label: "Analytics", short: "Stats", icon: Activity },
  { href: "/ports", label: "Ports", short: "Ports", icon: Anchor },
  { href: "/copilot", label: "Copilot", short: "AI", icon: Sparkles },
  { href: "/data", label: "Dataset", short: "Data", icon: Database },
];

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-dvh flex-col bg-[var(--ns-bg)]">
      <a href="#main" className="skip-link text-sm">
        Skip to main content
      </a>

      <div className="flex flex-1 flex-col md:flex-row">
        {/* Desktop navigation rail */}
        <nav
          aria-label="Primary"
          className={cn(
            "sticky top-0 z-30 hidden h-dvh w-[68px] shrink-0 flex-col items-center gap-1",
            "border-r border-[var(--ns-border)] bg-[var(--ns-surface)] py-3 md:flex",
          )}
        >
          <Link
            href="/"
            className="mb-3 flex size-10 items-center justify-center rounded-lg
                       bg-[color-mix(in_oklab,var(--ns-accent)_14%,transparent)]"
            aria-label="NaviSight home"
          >
            <Ship className="size-5 text-[var(--ns-accent)]" aria-hidden="true" />
          </Link>

          {NAV.map((item) => {
            const active = isActive(pathname, item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "group relative flex w-full flex-col items-center gap-1 px-1 py-2",
                  "text-[10px] font-medium transition-colors",
                  active
                    ? "text-[var(--ns-accent)]"
                    : "text-[var(--ns-text-muted)] hover:text-[var(--ns-text)]",
                )}
              >
                {/* Active state is carried by an indicator bar as well as
                    colour, so it is not colour-alone (SOUL.md §12). */}
                <span
                  aria-hidden="true"
                  className={cn(
                    "absolute left-0 top-1/2 h-7 w-[3px] -translate-y-1/2 rounded-r",
                    active ? "bg-[var(--ns-accent)]" : "bg-transparent",
                  )}
                />
                <Icon className="size-[18px]" aria-hidden="true" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="flex min-w-0 flex-1 flex-col">
          <header
            className={cn(
              "sticky top-0 z-20 flex h-14 items-center gap-3 border-b",
              "border-[var(--ns-border)] bg-[color-mix(in_oklab,var(--ns-surface)_92%,transparent)]",
              "px-3 backdrop-blur md:px-4",
            )}
          >
            <Link href="/" className="flex items-center gap-2 md:hidden" aria-label="NaviSight home">
              <Ship className="size-5 text-[var(--ns-accent)]" aria-hidden="true" />
            </Link>

            <div className="min-w-0 flex-1">
              <GlobalSearch />
            </div>

            <DatasetBadge />
            <ThemeToggle />
          </header>

          <main id="main" className="min-w-0 flex-1">
            {children}
          </main>
        </div>
      </div>

      {/* Mobile navigation */}
      <nav
        aria-label="Primary"
        className={cn(
          "sticky bottom-0 z-30 grid grid-cols-7 border-t border-[var(--ns-border)]",
          "bg-[var(--ns-surface)] md:hidden",
        )}
      >
        {NAV.map((item) => {
          const active = isActive(pathname, item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex flex-col items-center gap-0.5 py-2 text-[10px] font-medium",
                active ? "text-[var(--ns-accent)]" : "text-[var(--ns-text-muted)]",
              )}
            >
              <Icon className="size-[18px]" aria-hidden="true" />
              {item.short}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
