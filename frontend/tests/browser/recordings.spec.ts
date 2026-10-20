import { test, expect, type Page } from "@playwright/test"
import fs from "node:fs"
import path from "node:path"
import ts from "typescript"

const fixture = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../../../tmp/recorder-fixture.json"), "utf8"))
const source = (name: string) => ts.transpileModule(fs.readFileSync(path.resolve(__dirname, `../../src/lib/${name}.ts`), "utf8"), { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
  .replace(/^export /gm, "")

async function login(page: Page) {
  await page.addInitScript(({ token, id }) => {
    localStorage.setItem("primex_access_token", token)
    localStorage.setItem("primex_user", JSON.stringify({ id, email: "owner@recorder.invalid", full_name: "owner", role: "STAFF", is_active: true }))
  }, fixture.owner)
  // Only unrelated app-shell data are stubbed. Capture, recording API, storage,
  // remux, playback authorization and HTTP Range all use the implementation.
  await page.route("http://127.0.0.1:8012/api/**", async route => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.startsWith("/api/meeting-recordings") || pathname === "/api/auth/me" || pathname === "/api/meetings") return route.continue()
    return route.fulfill({ json: pathname.includes("count") ? { count: 0 } : [] })
  })
  await page.goto("/meeting-recordings")
  await expect(page.getByRole("heading", { name: "Regjistrimet e takimeve", exact: true })).toBeVisible()
}

test("Chromium display-capture API with test device → chunks → remux → reload → authorized range playback and download", async ({ page, request }) => {
  await login(page)
  await page.getByLabel("Titulli", { exact: true }).fill("Chromium native capture verification")
  await page.getByLabel("Mikrofoni", { exact: true }).selectOption("none")
  await page.getByLabel("Konfirmoj se kam njoftuar", { exact: false }).check()
  await page.getByRole("button", { name: "Zgjidh ekranin", exact: true }).click()
  const start = page.getByRole("button", { name: /Fillo regjistrimin|Vazhdo pa audio sistemi/ })
  await expect(start).toBeVisible()
  await start.click()
  await expect(page.getByRole("button", { name: "Pauzë", exact: true })).toBeVisible()
  await page.waitForTimeout(4500)
  await page.getByRole("button", { name: "Pauzë", exact: true }).click()
  await expect(page.getByRole("button", { name: "Vazhdo", exact: true })).toBeVisible()
  await page.getByRole("button", { name: "Vazhdo", exact: true }).click()
  await page.waitForTimeout(1200)
  await page.getByRole("button", { name: "Ndalo", exact: true }).click()
  await expect(page.getByText("Serveri konfirmoi ruajtjen.", { exact: false })).toBeVisible()
  await page.getByRole("link", { name: "Hap regjistrimin", exact: true }).click()
  await expect(page.locator("video")).toBeVisible()
  await expect.poll(() => page.locator("video").evaluate((v: HTMLVideoElement) => Number.isFinite(v.duration) && v.duration > 0)).toBe(true)
  const id = new URL(page.url()).pathname.split("/").pop()!
  await page.reload()
  await expect(page.locator("video")).toBeVisible()
  await expect.poll(() => page.locator("video").evaluate((v: HTMLVideoElement) => v.readyState)).toBeGreaterThanOrEqual(1)
  const partial = await page.request.get(`/api/meeting-recordings/${id}/stream`, { headers: { Range: "bytes=0-31" } })
  expect(partial.status()).toBe(206); expect((await partial.body()).length).toBe(32)
  const denied = await request.get(`http://127.0.0.1:8012/api/meeting-recordings/${id}/stream`)
  expect(denied.status()).toBe(401)
  const download = await page.request.get(`/api/meeting-recordings/${id}/download`)
  expect(download.status()).toBe(200); expect(download.headers()["content-disposition"]).toContain("attachment")
  await page.screenshot({ path: "test-results/recording-detail.png", fullPage: true })
})

test("real MediaRecorder mixes two synthetic audio sources and durable IndexedDB retries interrupted uploads", async ({ page }) => {
  await login(page)
  // No MediaRecorder or AudioContext mocks: synthetic sources let us measure
  // the real mixer without claiming that a Teams/OS loopback was verified.
  await page.addScriptTag({ content: source("recording-capture") + "\nwindow.RecordingCapture = RecordingCapture;" })
  await page.addScriptTag({ content: source("recording-outbox") + "\nwindow.IndexedRecordingOutbox=IndexedRecordingOutbox; window.RecordingUploader=RecordingUploader;" })
  const result = await page.evaluate(async ({ token, meetingId }) => {
    const globals = window as unknown as { RecordingCapture: new (events: object) => { prepare: (id: string, type: string) => Promise<void>; start: () => Promise<void>; stop: () => Promise<void>; info: { system: boolean; microphone: boolean } }; IndexedRecordingOutbox: new () => { create: (value: object) => Promise<void>; append: (id: string, blob: Blob) => Promise<void>; stop: (id: string) => Promise<void>; get: (id: string) => Promise<{ count: number; acknowledged: number }>; list: (id: string) => Promise<unknown[]> }; RecordingUploader: new (id: string, outbox: unknown, api: unknown, change: () => void, sleep: () => Promise<void>) => { pump: () => Promise<void>; complete: () => Promise<{ status: string; id: string }> } }
    const originalDisplay = navigator.mediaDevices.getDisplayMedia.bind(navigator.mediaDevices)
    const originalMic = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
    const canvas = document.createElement("canvas"); canvas.width = 320; canvas.height = 180
    const ctx = canvas.getContext("2d")!
    const timer = setInterval(() => { ctx.fillStyle = `hsl(${Date.now() % 360},80%,50%)`; ctx.fillRect(0, 0, 320, 180) }, 50)
    const sound = new AudioContext(); await sound.resume()
    const makeSound = (frequency: number) => {
      const oscillator = sound.createOscillator(), destination = sound.createMediaStreamDestination()
      oscillator.frequency.value = frequency; oscillator.connect(destination); oscillator.start()
      return destination.stream
    }
    const display = canvas.captureStream(10), system = makeSound(440), mic = makeSound(880)
    display.addTrack(system.getAudioTracks()[0])
    Object.defineProperty(navigator.mediaDevices, "getDisplayMedia", { configurable: true, value: async () => display })
    Object.defineProperty(navigator.mediaDevices, "getUserMedia", { configurable: true, value: async () => mic })
    const api = async (route: string, init: RequestInit = {}) => fetch("http://127.0.0.1:8012/api" + route, { ...init, headers: { ...Object.fromEntries(new Headers(init.headers)), Authorization: "Bearer " + token } })
    const created = await api("/meeting-recordings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: "Two synthetic audio inputs", meeting_id: meetingId, mime_type: "video/webm", capture_source_type: "browser", has_microphone_audio: true, has_system_audio: true, consent_acknowledged: true }) })
    const session = await created.json()
    if (!created.ok) throw new Error(JSON.stringify(session))
    const outbox = new globals.IndexedRecordingOutbox()
    await outbox.create({ id: session.id, userId: "synthetic-test", title: "Synthetic", count: 0, acknowledged: 0, bytes: 0, uploadedBytes: 0, stopped: false })
    let tail = Promise.resolve(), captureError = ""
    const capture = new globals.RecordingCapture({ change() {}, chunk(blob: Blob) { tail = tail.then(() => outbox.append(session.id, blob)) }, stopped() {}, error(error: Error) { captureError = error.message } })
    await capture.prepare("", "browser"); await capture.start()
    await new Promise(resolve => setTimeout(resolve, 5100))
    await capture.stop(); await tail; await outbox.stop(session.id)
    const before = await outbox.get(session.id)
    let attempts = 0
    const uploader = new globals.RecordingUploader(session.id, new globals.IndexedRecordingOutbox(), async (route: string, init: RequestInit) => {
      if (route.includes("/chunks/") && attempts++ === 0) return new Response(null, { status: 503 })
      return api(route, init)
    }, () => {}, async () => {})
    const saved = await uploader.complete()
    clearInterval(timer); await sound.close()
    Object.defineProperty(navigator.mediaDevices, "getDisplayMedia", { configurable: true, value: originalDisplay })
    Object.defineProperty(navigator.mediaDevices, "getUserMedia", { configurable: true, value: originalMic })
    return { saved, before, attempts, info: capture.info, captureError, pending: (await outbox.list("synthetic-test")).length }
  }, { token: fixture.owner.token, meetingId: fixture.meeting_id })
  expect(result.captureError).toBe(""); expect(result.info.system).toBe(true); expect(result.info.microphone).toBe(true)
  expect(result.before.count).toBeGreaterThanOrEqual(2); expect(result.before.acknowledged).toBe(0)
  expect(result.saved.status).toBe("READY"); expect(result.attempts).toBeGreaterThan(2); expect(result.pending).toBe(0)
  const media = await page.request.get(`http://127.0.0.1:8012/api/meeting-recordings/${result.saved.id}/download`, { headers: { Authorization: "Bearer " + fixture.owner.token } })
  expect(media.status()).toBe(200)
  await media.body().then(bytes => fs.writeFileSync(path.resolve(__dirname, "../../test-results/two-audio-inputs.webm"), bytes))
})

test("playback cookie rejects cross-origin writes and anonymous media requests", async ({ page }) => {
  await login(page)
  const id = fixture.meeting_id
  const response = await page.request.post(`/api/meeting-recordings/${id}/playback`, { headers: { Origin: "https://untrusted.invalid" }, data: { token: "x".repeat(60) } })
  expect(response.status()).toBe(403)
  expect((await page.request.get(`/api/meeting-recordings/${id}/stream`)).status()).toBe(401)
})

test("IndexedDB enforces fragment and pending-byte limits across outbox instances", async ({ page }) => {
  await login(page)
  await page.addScriptTag({ content: source("recording-outbox") + "\nwindow.IndexedRecordingOutbox=IndexedRecordingOutbox;" })
  const result = await page.evaluate(async () => {
    const globals = window as unknown as { IndexedRecordingOutbox: new () => { create: (m: object) => Promise<void>; append: (id: string, b: Blob) => Promise<void>; get: (id: string) => Promise<{ bytes: number; count: number }>; remove: (id: string) => Promise<void> } }
    const id = crypto.randomUUID(), outbox = new globals.IndexedRecordingOutbox()
    await outbox.create({ id, userId: "bounds-test", title: "Bounds", count: 0, acknowledged: 0, bytes: 0, uploadedBytes: 0, stopped: false })
    const fragment = new Blob([new Uint8Array(32 * 1024 * 1024)])
    let oversized = false, backlog = false
    try { await outbox.append(id, new Blob([fragment, "x"])) } catch { oversized = true }
    for (let n = 0; n < 3; n++) await outbox.append(id, fragment)
    try { await outbox.append(id, new Blob(["x"])) } catch { backlog = true }
    const durable = await new globals.IndexedRecordingOutbox().get(id)
    await outbox.remove(id)
    return { oversized, backlog, durable }
  })
  expect(result.oversized).toBe(true); expect(result.backlog).toBe(true)
  expect(result.durable.bytes).toBe(96 * 1024 * 1024); expect(result.durable.count).toBe(3)
})
