import { defineConfig } from "@playwright/test"

export default defineConfig({
  testDir: "./tests/browser",
  testMatch: "mailbox.spec.ts",
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 30_000 },
  use: { baseURL: "http://127.0.0.1:3109", headless: true, launchOptions: { executablePath: process.env.MAILBOX_CHROMIUM_EXECUTABLE } },
  webServer: {
    command: "node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 3109",
    url: "http://127.0.0.1:3109/login",
    env: { NEXT_PUBLIC_API_BASE_URL: "http://127.0.0.1:8019", NEXT_DIST_DIR: ".next-mailbox-test" },
    timeout: 120_000,
  },
})
