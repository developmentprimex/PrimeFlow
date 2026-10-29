import { defineConfig } from "@playwright/test"

export default defineConfig({
  testDir: "./tests/browser", testMatch: /ga-personal\.spec\.ts/, workers: 1,
  timeout: 60_000, expect: { timeout: 20_000 },
  use: { baseURL: "http://127.0.0.1:3105", headless: true,
    launchOptions: { executablePath: process.env.RECORDINGS_CHROMIUM_EXECUTABLE } },
  webServer: {
    reuseExistingServer: Boolean(process.env.GA_PERSONAL_REUSE_SERVER),
    command: "node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 3105",
    url: "http://127.0.0.1:3105/login", timeout: 180_000,
    env: { NEXT_PUBLIC_API_BASE_URL: "http://127.0.0.1:8015", NEXT_DIST_DIR: ".next-recorder-test/ga-personal" },
  },
})
