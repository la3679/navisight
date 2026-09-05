import type { Metadata } from "next";
import Link from "next/link";

import { Card, CardBody } from "@/components/ui/primitives";

/**
 * The 404 page.
 *
 * Next.js ships a default one, and inside NaviSight's shell it rendered as
 * near-invisible grey text on a grey ground — a contrast failure on the one
 * screen whose whole job is to orient someone who is already lost. This page
 * uses the same tokens as every other surface, and it does the thing a
 * not-found page should do beyond apologising: it lists where the reader can
 * actually go.
 *
 * The destinations are written out rather than imported from the navigation's
 * own list, because this page must still render if that module is what failed.
 */

export const metadata: Metadata = {
  title: "Page not found",
  description: "No such page in NaviSight.",
};

const DESTINATIONS = [
  { href: "/", label: "Overview", hint: "What this archive holds, and where to start." },
  {
    href: "/operations",
    label: "Operations map",
    hint: "Every vessel's last archived position.",
  },
  { href: "/vessels", label: "Vessels", hint: "Search by name, MMSI, IMO, or call sign." },
  { href: "/analytics", label: "Analytics", hint: "Traffic, fleet composition, and speed." },
  { href: "/copilot", label: "Copilot", hint: "Ask a question and check the evidence." },
  { href: "/data", label: "Dataset", hint: "What was imported, and what it cannot tell you." },
] as const;

export default function NotFound() {
  return (
    <div className="mx-auto max-w-3xl space-y-5 p-4 md:p-6">
      <header>
        <p className="font-[family-name:var(--font-mono)] text-xs tracking-wider text-[var(--ns-text-muted)] uppercase">
          404
        </p>
        <h1 className="mt-1 text-xl font-semibold tracking-tight">This page does not exist</h1>
        <p className="mt-1 max-w-2xl text-sm text-[var(--ns-text-secondary)]">
          The address you followed is not one of NaviSight&rsquo;s screens. A vessel link may be
          the cause: an MMSI that is not in this archive resolves to a vessel page that reports
          the miss, but a malformed one lands here.
        </p>
      </header>

      <Card>
        <CardBody>
          <ul className="divide-y divide-[var(--ns-border)]">
            {DESTINATIONS.map((destination) => (
              <li key={destination.href}>
                <Link
                  href={destination.href}
                  className="-mx-2 flex flex-col gap-0.5 rounded-md px-2 py-2.5 transition-colors hover:bg-[var(--ns-surface-raised)]"
                >
                  <span className="text-sm font-medium text-[var(--ns-text)]">
                    {destination.label}
                  </span>
                  <span className="text-xs text-[var(--ns-text-secondary)]">
                    {destination.hint}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </CardBody>
      </Card>
    </div>
  );
}
