import { defineConfig } from "@playwright/test"

export default defineConfig({
  testDir: "./tests/browser",
  testMatch: "task-marker-per-assignee.spec.ts",
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  use: { baseURL: "http://127.0.0.1:3106", headless: true, launchOptions: {
    executablePath: process.env.RECORDINGS_CHROMIUM_EXECUTABLE ||
      (process.platform === "win32" ? "C:/Program Files/Google/Chrome/Application/chrome.exe" : undefined),
  } },
  webServer: {
    command: "node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 3106",
    url: "http://127.0.0.1:3106/login",
    env: { NEXT_PUBLIC_API_BASE_URL: "http://127.0.0.1:8028", NEXT_DIST_DIR: ".next-recorder-test/task-markers" },
    timeout: 120_000,
  },
})
