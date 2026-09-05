import type { Metadata } from "next";
import { Suspense } from "react";

import { Skeleton } from "@/components/ui/primitives";
import { OperationsView } from "./operations-view";

export const metadata: Metadata = {
  title: "Operations",
  description:
    "Explore historical AIS vessel positions on a map, filter by type and speed, and replay an archived day.",
};

/**
 * The operations workspace.
 *
 * Wrapped in Suspense because the view reads URL search params, which Next 16
 * requires a Suspense boundary for during static rendering.
 */
export default function OperationsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-[calc(100dvh-3.5rem)] w-full rounded-none" />}>
      <OperationsView />
    </Suspense>
  );
}
