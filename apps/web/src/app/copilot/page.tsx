import type { Metadata } from "next";

import { CopilotView } from "./copilot-view";

export const metadata: Metadata = {
  title: "Copilot",
  description:
    "Ask questions about the archived AIS data. Every answer shows the tool calls it was built from, and labels how strongly each claim is supported.",
};

export default function CopilotPage() {
  return <CopilotView />;
}
