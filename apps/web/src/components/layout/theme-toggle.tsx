/**
 * Light/dark toggle.
 *
 * Renders a stable placeholder until mounted: `next-themes` cannot know the
 * resolved theme during SSR, and rendering the wrong icon then swapping it is
 * a visible flicker on every page load.
 */

"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import * as React from "react";

import { Button } from "@/components/ui/primitives";
import { useIsMounted } from "@/hooks/client-env";

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const mounted = useIsMounted();

  if (!mounted) {
    return <Button variant="ghost" size="icon" aria-hidden="true" tabIndex={-1} />;
  }

  const isDark = resolvedTheme === "dark";

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
    >
      {isDark ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
    </Button>
  );
}
