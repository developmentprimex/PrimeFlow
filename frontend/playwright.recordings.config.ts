import { defineConfig } from "@playwright/test"
import path from "node:path"

const root = path.resolve(__dirname, "..")
const testEnvironment = {
  RECORDINGS_TEST_DATABASE_URL: process.env.RECORDINGS_TEST_DATABASE_URL || "",
  MEETING_RECORDINGS_FFMPEG: process.env.MEETING_RECORDINGS_FFMPEG || "ffmpeg",
  MEETING_RECORDINGS_FFPROBE: process.env.MEETING_RECORDINGS_FFPROBE || "ffprobe",
  MEETING_RECORDINGS_ROOT: path.join(root, "tmp/recorder-browser-storage"),
}
export default defineConfig({
  testDir: "./tests/browser",
  testMatch: "recordings.spec.ts",
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 30_000 },
  use: { baseURL: "http://127.0.0.1:3100", headless: true, launchOptions: { executablePath: process.env.RECORDINGS_CHROMIUM_EXECUTABLE, args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--auto-select-desktop-capture-source=Entire screen", "--allow-http-screen-capture"] } },
  webServer: [
    { command: ".venv\\Scripts\\python.exe tests/serve_recordings_test.py", cwd: path.join(root, "backend"), url: "http://127.0.0.1:8012/docs", env: testEnvironment, timeout: 60_000 },
    { command: "node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 3100", url: "http://127.0.0.1:3100/login", env: { NEXT_PUBLIC_API_BASE_URL: "http://127.0.0.1:8012", MEETING_RECORDINGS_API_URL: "http://127.0.0.1:8012/api", NEXT_DIST_DIR: ".next-recorder-test" }, timeout: 120_000 },
  ],
})
