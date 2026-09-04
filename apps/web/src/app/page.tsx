import type { Metadata } from "next";

import { HomeView } from "./home-view";

export const metadata: Metadata = {
  title: "Overview",
  description:
    "NaviSight reconstructs a day of maritime movement from recorded AIS broadcasts: a map, vessel records, and analytics over a historical archive.",
};

export default function HomePage() {
  return <HomeView />;
}
