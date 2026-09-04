/**
 * Application providers: server state and theme.
 *
 * Server state lives in TanStack Query and nowhere else. There is no global
 * store mirroring API data — duplicating server state into client state is how
 * "why is this stale?" bugs start (SOUL.md §5).
 */

"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import * as React from "react";

import { ApiClientError } from "@/lib/api/client";

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // The dataset is a fixed historical archive: once fetched, a vessel's
        // track for a given window cannot change. Long staleness is correct
        // here rather than merely convenient.
        staleTime: 5 * 60_000,
        gcTime: 30 * 60_000,
        refetchOnWindowFocus: false,
        // Retry only what retrying can fix. A 404 or a validation error will
        // fail identically three more times and just delay the message.
        retry: (failureCount, error) => {
          if (error instanceof ApiClientError) {
            return error.isRetryable && failureCount < 2;
          }
          return failureCount < 1;
        },
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
      },
    },
  });
}

let browserQueryClient: QueryClient | undefined;

function getQueryClient() {
  if (typeof window === "undefined") return makeQueryClient();
  // One client for the browser session, created lazily so a Suspense-driven
  // re-render during hydration cannot discard an in-flight cache.
  browserQueryClient ??= makeQueryClient();
  return browserQueryClient;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const queryClient = getQueryClient();

  return (
    <ThemeProvider
      attribute="data-theme"
      defaultTheme="dark"
      enableSystem
      disableTransitionOnChange
    >
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </ThemeProvider>
  );
}
