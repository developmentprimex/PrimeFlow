import { defineConfig } from "@playwright/test"

export default defineConfig({
  testDir: "./tests/browser",
  testMatch: "one-h-report-toolbar.spec.ts",
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 20_000 },
  use: { baseURL: "http://127.0.0.1:3105", headless: true, launchOptions: {
    executablePath: process.env.RECORDINGS_CHROMIUM_EXECUTABLE ||
      (process.platform === "win32" ? "C:/Program Files/Google/Chrome/Application/chrome.exe" : undefined),
  } },
  webServer: {
    command: "node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 3105",
    url: "http://127.0.0.1:3105/login",
    env: { NEXT_PUBLIC_API_BASE_URL: "http://127.0.0.1:8027", NEXT_DIST_DIR: ".next-recorder-test/one-h-toolbar" },
    timeout: 120_000,
    reuseExistingServer: Boolean(process.env.ONE_H_FILTER_REUSE_SERVER),
  },
})
