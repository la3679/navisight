"use client";

import { Circle, Compass, Lightbulb, Ruler } from "lucide-react";
import * as React from "react";

import type { AgentClaim, AgentClaimKind } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * Claims, each labelled with how strongly it is supported.
 *
 * The four kinds are not decoration. An AIS archive records where a vessel was
 * and what it broadcast about itself; it does not record why, whether it
 * berthed, what it carried, or where it was going. The difference between "the
 * vessel reported 0.1 knots" and "the vessel was probably moored" is the whole
 * epistemic distance this product cares about (SOUL.md §9), and rendering both
 * as plain prose would erase it.
 *
 * So the label is always visible, never a tooltip, and it is carried by a word,
 * an icon, and a colour together — never colour alone (SOUL.md §12).
 *
 * The order below is deliberate: strongest first, so the visual weight
 * decreases exactly as the epistemic weight does.
 */

type KindMeta = {
  label: string;
  meaning: string;
  icon: React.ComponentType<{ className?: string }>;
  /** Tint for the border and background. A status hue, never a series colour. */
  color: string;
  /** Text colour, contrast-checked against a 12% tint of `color`. */
  textColor: string;
};

export const CLAIM_KINDS: Record<AgentClaimKind, KindMeta> = {
  observed: {
    label: "Observed",
    meaning: "Read directly from a record in the archive.",
    icon: Circle,
    color: "var(--ns-good)",
    textColor: "var(--ns-good-on-tint)",
  },
  derived: {
    label: "Derived",
    meaning: "Computed by a tool from observations — a count, a mean, a bucket.",
    icon: Ruler,
    color: "var(--ns-info)",
    textColor: "var(--ns-info-on-tint)",
  },
  heuristic: {
    label: "Heuristic",
    meaning: "A signal that suggests something without establishing it.",
    icon: Compass,
    color: "var(--ns-warning)",
    textColor: "var(--ns-warning-on-tint)",
  },
  interpretation: {
    label: "Interpretation",
    meaning: "The model's reading of the evidence. The weakest kind, and its own.",
    icon: Lightbulb,
    color: "var(--ns-text-muted)",
    textColor: "var(--ns-text-muted-on-tint)",
  },
};

/** Strongest first. Also the order the legend and the sort use. */
export const KIND_ORDER: AgentClaimKind[] = [
  "observed",
  "derived",
  "heuristic",
  "interpretation",
];

export function ClaimKindBadge({ kind }: { kind: AgentClaimKind }) {
  const meta = CLAIM_KINDS[kind];
  const Icon = meta.icon;
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-medium tracking-wide uppercase"
      style={{
        color: meta.textColor,
        borderColor: `color-mix(in oklab, ${meta.color} 40%, transparent)`,
        backgroundColor: `color-mix(in oklab, ${meta.color} 12%, transparent)`,
      }}
      title={meta.meaning}
    >
      <Icon className="size-2.5" aria-hidden="true" />
      {meta.label}
    </span>
  );
}

export function ClaimList({ claims }: { claims: AgentClaim[] }) {
  if (claims.length === 0) {
    return (
      <p className="text-xs leading-relaxed text-[var(--ns-text-muted)]">
        The model did not label any claims for this answer. Read it as unattributed prose and
        check it against the evidence below.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {claims.map((claim, index) => (
        <li
          key={`${index}-${claim.text.slice(0, 24)}`}
          className="flex flex-wrap items-baseline gap-x-2 gap-y-1"
        >
          <ClaimKindBadge kind={claim.kind} />
          <span className="min-w-0 flex-1 text-sm leading-relaxed text-[var(--ns-text-secondary)]">
            {claim.text}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** What the four labels mean, shown where the user meets them. */
export function ClaimKindLegend({ className }: { className?: string }) {
  return (
    <dl className={cn("grid gap-2 sm:grid-cols-2", className)}>
      {KIND_ORDER.map((kind) => (
        <div key={kind} className="flex items-baseline gap-2">
          <dt>
            <ClaimKindBadge kind={kind} />
          </dt>
          <dd className="min-w-0 flex-1 text-[11px] leading-relaxed text-[var(--ns-text-muted)]">
            {CLAIM_KINDS[kind].meaning}
          </dd>
        </div>
      ))}
    </dl>
  );
}
