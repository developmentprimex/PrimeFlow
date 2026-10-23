import { defineConfig } from "@playwright/test"

export default defineConfig({
  testDir: "./tests/browser",
  testMatch: "one-h-strike-filter.spec.ts",
  workers: 1,
  use: { headless: true, launchOptions: {
    executablePath: process.env.RECORDINGS_CHROMIUM_EXECUTABLE ||
      (process.platform === "win32" ? "C:/Program Files/Google/Chrome/Application/chrome.exe" : undefined),
  } },
})
