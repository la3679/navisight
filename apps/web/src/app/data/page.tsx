import type { Metadata } from "next";

import { DatasetView } from "./dataset-view";

export const metadata: Metadata = {
  title: "Dataset",
  description:
    "Provenance, coverage, completeness, and known limitations of the AIS data NaviSight has imported.",
};

/**
 * The dataset page.
 *
 * This page is the product's conscience. It states where the data came from,
 * what period it covers, how complete it is, and what it cannot tell you. If a
 * user ever wonders "is this live?", this is the page that answers plainly.
 */
export default function DataPage() {
  return <DatasetView />;
}
