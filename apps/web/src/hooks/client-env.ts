"use client";

/**
 * Client-environment hooks.
 *
 * All three answer "what is true in this browser?" — a question the server
 * cannot answer, so each must return a stable server value and switch after
 * hydration without a mismatch.
 *
 * They use `useSyncExternalStore` rather than the more familiar
 * `useState` + `useEffect(() => setX(...))`. That pattern causes a cascading
 * render on every mount and is exactly what React's
 * `react-hooks/set-state-in-effect` rule flags; `useSyncExternalStore` is the
 * purpose-built API for reading an external value during render safely.
 */

import * as React from "react";

const noopSubscribe = () => () => {};

/**
 * Whether the component has hydrated.
 *
 * Used where server and client would otherwise disagree — for example the
 * theme toggle, which cannot know the resolved theme until it runs.
 */
export function useIsMounted(): boolean {
  return React.useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false,
  );
}

/** Cached so the detection canvas is created at most once per page. */
let webglSupport: boolean | null = null;

function detectWebGL(): boolean {
  if (webglSupport !== null) return webglSupport;
  try {
    const canvas = document.createElement("canvas");
    webglSupport = Boolean(
      window.WebGLRenderingContext &&
      (canvas.getContext("webgl") || canvas.getContext("experimental-webgl")),
    );
  } catch {
    webglSupport = false;
  }
  return webglSupport;
}

/**
 * Whether this browser can render WebGL.
 *
 * Returns `false` on the server so 3D content is never server-rendered, and
 * the real answer after hydration. A `false` result must produce a labelled
 * fallback, never a blank box (SOUL.md §11).
 */
export function useWebGLSupport(): boolean {
  return React.useSyncExternalStore(noopSubscribe, detectWebGL, () => false);
}

/**
 * Whether the user has asked for reduced motion.
 *
 * Subscribes to the media query, so a change in system settings takes effect
 * without a reload. Every animation in the application honours this, including
 * 3D auto-rotation (SOUL.md §12).
 */
export function usePrefersReducedMotion(): boolean {
  const subscribe = React.useCallback((onChange: () => void) => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  return React.useSyncExternalStore(
    subscribe,
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    // Assume no preference on the server; the client corrects it immediately.
    () => false,
  );
}
