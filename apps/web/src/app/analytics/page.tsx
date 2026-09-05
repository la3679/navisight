import type { Metadata } from "next";

import { AnalyticsView } from "./analytics-view";

export const metadata: Metadata = {
  title: "Analytics",
  description:
    "Aggregate traffic, fleet composition, navigational status, and speed distribution across the archived AIS day.",
};

export default function AnalyticsPage() {
  return <AnalyticsView />;
}
