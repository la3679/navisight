import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/**
 * Unit and component tests.
 *
 * `jsdom` rather than a real browser: these tests cover logic and rendered
 * markup. Anything that needs WebGL — the map, the 3D scenes — is verified by
 * Playwright against a real browser instead, because a headless DOM cannot
 * tell you whether a GPU layer actually drew.
 *
 * `.mts` so the config is loaded as ESM, and `resolve.tsconfigPaths` rather
 * than the `vite-tsconfig-paths` plugin, which Vite now supersedes.
 */
export default defineConfig({
  plugins: [react()],
  resolve: { tsconfigPaths: true },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    restoreMocks: true,
  },
});
