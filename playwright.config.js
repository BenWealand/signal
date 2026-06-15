import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:5174",
    trace: "on-first-retry",
  },
  webServer: {
    command: "npx vite --host 127.0.0.1 --port 5174",
    url: "http://127.0.0.1:5174",
    reuseExistingServer: false,
    env: {
      VITE_SIGNAL_FALLBACK_DELAY_MS: "75",
    },
  },
});
