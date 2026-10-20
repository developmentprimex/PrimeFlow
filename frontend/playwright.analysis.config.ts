import { defineConfig } from "@playwright/test"

export default defineConfig({
  testDir: "./tests/browser",
  testMatch: "recording-analysis.spec.ts",
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 30_000 },
  use: { baseURL: "http://127.0.0.1:3101", headless: true, launchOptions: { executablePath: process.env.RECORDINGS_CHROMIUM_EXECUTABLE } },
  webServer: {
    command: "node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 3101",
    url: "http://127.0.0.1:3101/login",
    env: { NEXT_PUBLIC_API_BASE_URL: "http://127.0.0.1:8012", NEXT_DIST_DIR: ".next-recorder-test/analysis-browser" },
    timeout: 120_000,
    reuseExistingServer: Boolean(process.env.RECORDING_ANALYSIS_REUSE_SERVER),
  },
})
