import type { Metadata } from "next";

import { PortsView } from "./ports-view";

export const metadata: Metadata = {
  title: "Ports",
  description:
    "Optional port reference data, and which vessels' last archived position was near a given port.",
};

export default function PortsPage() {
  return <PortsView />;
}
