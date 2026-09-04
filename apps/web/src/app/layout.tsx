import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

import { AppShell } from "@/components/layout/app-shell";
import { Providers } from "./providers";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

// Monospace is used for identifiers and numeric readouts — MMSI, coordinates,
// timestamps — where column alignment and digit distinction matter.
const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://navisight.local"),
  title: {
    default: "NaviSight — Maritime Vessel & Port Intelligence",
    template: "%s · NaviSight",
  },
  description:
    "Explore historical AIS vessel movement, investigate traffic patterns, and " +
    "query the data through an evidence-grounded copilot.",
  applicationName: "NaviSight",
  keywords: ["AIS", "maritime", "vessel tracking", "MongoDB", "geospatial"],
  openGraph: {
    title: "NaviSight — Maritime Vessel & Port Intelligence",
    description:
      "Explore historical AIS vessel movement, investigate traffic patterns, and " +
      "query the data through an evidence-grounded copilot.",
    type: "website",
  },
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0a111a" },
    { media: "(prefers-color-scheme: light)", color: "#eef2f6" },
  ],
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    // suppressHydrationWarning is required by next-themes: it writes the
    // data-theme attribute before React hydrates, which is the whole point —
    // it prevents a flash of the wrong theme.
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.variable} ${jetbrainsMono.variable} antialiased`}>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
