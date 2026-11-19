import { defineConfig } from "@playwright/test";

// End-to-end tests run against the real backend and a production build of the frontend.
// OTST_PYTHON selects the Python interpreter (default "python"); PW_CHANNEL can select an installed
// browser (e.g. "msedge" or "chrome") instead of Playwright's bundled Chromium.
const python = process.env.OTST_PYTHON ?? "python";

export default defineConfig({
  testDir: "./e2e",
  timeout: 180_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
    channel: process.env.PW_CHANNEL || undefined,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `${python} -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000`,
      cwd: "../backend",
      url: "http://127.0.0.1:8000/api/health",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: { OTST_DATABASE_URL: "sqlite:///./data/e2e.db", OTST_AUTOSTART: "true" },
    },
    {
      command: "npx vite build && npx vite preview --port 4173 --strictPort",
      url: "http://127.0.0.1:4173",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
