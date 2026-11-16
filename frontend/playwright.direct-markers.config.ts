import { defineConfig } from "@playwright/test"
export default defineConfig({
  testDir: "./tests/browser", testMatch: "direct-task-markers.spec.ts", workers: 1,
  outputDir: "test-results/direct-markers",
  timeout: 60_000, expect: { timeout: 15_000 },
  use: { baseURL: "http://127.0.0.1:3107", headless: true,
    launchOptions: { executablePath: process.env.RECORDINGS_CHROMIUM_EXECUTABLE ||
      (process.platform === "win32" ? "C:/Program Files/Google/Chrome/Application/chrome.exe" : undefined) } },
  webServer: { command: "node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 3107",
    url: "http://127.0.0.1:3107/login", timeout: 120_000,
    env: { NEXT_PUBLIC_API_BASE_URL: "http://127.0.0.1:8029", NEXT_DIST_DIR: ".next-recorder-test/direct-markers" } },
})
