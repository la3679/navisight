/**
 * Base UI primitives.
 *
 * Written in the shadcn/ui idiom — owned components rather than a dependency —
 * but only the pieces this product actually uses. Radix is used underneath for
 * anything with real accessibility semantics (dialog, tooltip); hand-rolling a
 * focus-trapped modal correctly is not a good use of effort, and getting it
 * wrong is an accessibility defect (SOUL.md §12).
 */

"use client";

import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

/* ---------------------------------------------------------------- Button */

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm " +
    "font-medium transition-colors duration-150 disabled:pointer-events-none " +
    "disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary:
          "bg-[var(--ns-accent)] text-[var(--ns-accent-contrast)] hover:bg-[var(--ns-accent-strong)]",
        secondary:
          "bg-[var(--ns-surface-raised)] text-[var(--ns-text)] border border-[var(--ns-border)] " +
          "hover:border-[var(--ns-border-strong)] hover:bg-[var(--ns-surface-overlay)]",
        ghost:
          "text-[var(--ns-text-secondary)] hover:bg-[var(--ns-surface-raised)] hover:text-[var(--ns-text)]",
        danger:
          "bg-[var(--ns-critical)] text-white hover:opacity-90",
      },
      size: {
        sm: "h-8 px-2.5 text-xs [&_svg]:size-3.5",
        md: "h-9 px-3.5 [&_svg]:size-4",
        lg: "h-11 px-5 [&_svg]:size-4",
        icon: "h-9 w-9 [&_svg]:size-4",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />
  ),
);
Button.displayName = "Button";

/* ------------------------------------------------------------------ Card */

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-lg border border-[var(--ns-border)] bg-[var(--ns-surface)]",
        className,
      )}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-4 pt-4 pb-2", className)} {...props} />;
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3
      className={cn("text-sm font-semibold tracking-tight text-[var(--ns-text)]", className)}
      {...props}
    />
  );
}

export function CardDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return (
    <p className={cn("mt-1 text-xs text-[var(--ns-text-muted)]", className)} {...props} />
  );
}

export function CardBody({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-4 pb-4", className)} {...props} />;
}

/* ----------------------------------------------------------------- Badge */

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium",
  {
    variants: {
      tone: {
        neutral:
          "border-[var(--ns-border)] bg-[var(--ns-surface-raised)] text-[var(--ns-text-secondary)]",
        // Text uses the *-on-tint variant, never the base hue. A hue that
        // clears 4.5:1 against the surface does not necessarily clear it
        // against a 12% tint of itself — light-mode `good` measured 2.83:1.
        // See globals.css.
        accent:
          "border-[color-mix(in_oklab,var(--ns-accent)_40%,transparent)] " +
          "bg-[color-mix(in_oklab,var(--ns-accent)_12%,transparent)] text-[var(--ns-accent-on-tint)]",
        info: "border-[color-mix(in_oklab,var(--ns-info)_40%,transparent)] bg-[color-mix(in_oklab,var(--ns-info)_12%,transparent)] text-[var(--ns-info-on-tint)]",
        warning:
          "border-[color-mix(in_oklab,var(--ns-warning)_40%,transparent)] bg-[color-mix(in_oklab,var(--ns-warning)_12%,transparent)] text-[var(--ns-warning-on-tint)]",
        critical:
          "border-[color-mix(in_oklab,var(--ns-critical)_40%,transparent)] bg-[color-mix(in_oklab,var(--ns-critical)_12%,transparent)] text-[var(--ns-critical-on-tint)]",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export function Badge({
  className,
  tone,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

/* -------------------------------------------------------------- Skeleton */

export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("ns-skeleton rounded-md", className)}
      aria-hidden="true"
      {...props}
    />
  );
}

/* ----------------------------------------------------------------- Input */

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-9 w-full rounded-md border border-[var(--ns-border)] bg-[var(--ns-surface-raised)]",
        "px-3 text-sm text-[var(--ns-text)] placeholder:text-[var(--ns-text-muted)]",
        "transition-colors hover:border-[var(--ns-border-strong)] disabled:opacity-50",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

/* ---------------------------------------------------------------- Fields */

/**
 * A labelled value.
 *
 * The single place a missing value is rendered, so "not reported" looks the
 * same everywhere and can never leak a raw `null`.
 */
export function Field({
  label,
  value,
  hint,
  mono = false,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  mono?: boolean;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] uppercase tracking-wide text-[var(--ns-text-muted)]">
        {label}
      </dt>
      <dd
        className={cn(
          "mt-0.5 truncate text-sm text-[var(--ns-text)]",
          mono && "font-[family-name:var(--font-mono)] tabular",
        )}
        title={typeof value === "string" ? value : undefined}
      >
        {value}
      </dd>
      {/* A second <dd>, not a <p>. This component is used inside <dl>, and a
          <div> there may contain only <dt> and <dd> — a <p> makes the list
          invalid, which is a real defect rather than pedantry: assistive
          technology pairs terms with descriptions using that structure. */}
      {hint ? (
        <dd className="mt-0.5 text-[11px] text-[var(--ns-text-muted)]">{hint}</dd>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------ Separator */

export function Separator({ className }: { className?: string }) {
  return <hr className={cn("border-t border-[var(--ns-border)]", className)} />;
}
