import { defineConfig } from "@playwright/test";

const externalBaseUrl = process.env.PLAYWRIGHT_BASE_URL || "";

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  use: {
    baseURL: externalBaseUrl || "http://127.0.0.1:5174",
    trace: "on-first-retry",
  },
  webServer: externalBaseUrl ? undefined : {
    command: "npx vite --host 127.0.0.1 --port 5174",
    url: "http://127.0.0.1:5174",
    reuseExistingServer: false,
    env: {
      VITE_SIGNAL_API_URL: "",
      VITE_SIGNAL_OFFLINE_PREVIEW_DELAY_MS: "75",
    },
  },
});
