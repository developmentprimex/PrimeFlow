import { defineConfig } from "@playwright/test"

export default defineConfig({
  testDir: "./tests/browser",
  testMatch: "task-postponement.spec.ts",
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 30_000 },
  use: { baseURL: "http://127.0.0.1:3102", headless: true,
    launchOptions: { executablePath: process.env.RECORDINGS_CHROMIUM_EXECUTABLE }, trace: "retain-on-failure" },
  webServer: {
    command: "node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 3102",
    url: "http://127.0.0.1:3102/login",
    env: { NEXT_PUBLIC_API_BASE_URL: "http://127.0.0.1:8013", NEXT_DIST_DIR: ".next-recorder-test/postponements" },
    timeout: 120_000,
    reuseExistingServer: Boolean(process.env.POSTPONEMENT_REUSE_SERVER),
  },
})
