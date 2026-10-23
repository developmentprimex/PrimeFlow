import assert from "node:assert/strict"
import { test } from "node:test"
import { readFileSync } from "node:fs"
import { chromium } from "@playwright/test"
import ts from "typescript"

test("real MediaRecorder keeps one playable recording through sharing stop and restart", async () => {
  const browser = await chromium.launch({ headless: true, channel: process.env.RECORDINGS_BROWSER_CHANNEL || "chrome" })
  try {
    const page = await browser.newPage()
    await page.route("http://localhost/", route => route.fulfill({ contentType: "text/html", body: "<html><body></body></html>" }))
    await page.goto("http://localhost/")
    const source = readFileSync(new URL("../src/lib/recording-capture.ts", import.meta.url), "utf8")
    const { outputText } = ts.transpileModule(source.replace(/export /g, ""), {
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None },
    })
    await page.addScriptTag({ content: outputText + "\nwindow.RecordingCapture = RecordingCapture" })
    const results = await page.evaluate(async () => {
      const wait = ms => new Promise(resolve => setTimeout(resolve, ms))
      const results = []
      for (const microphone of [true, false]) {
        const sound = new AudioContext()
        await sound.resume()
        const oscillator = sound.createOscillator(), mic = sound.createMediaStreamDestination()
        oscillator.frequency.value = 880; oscillator.connect(mic); oscillator.start()
        const makeDisplay = color => {
          const canvas = document.createElement("canvas"); canvas.width = 320; canvas.height = 180
          const ctx = canvas.getContext("2d")
          const draw = () => { ctx.fillStyle = color; ctx.fillRect(0, 0, 320, 180) }
          draw()
          const timer = setInterval(draw, 50)
          return { stream: canvas.captureStream(15), timer }
        }
        const first = makeDisplay("red"), second = makeDisplay("blue")
        let selected = first.stream
        Object.defineProperty(navigator.mediaDevices, "getDisplayMedia", { configurable: true, value: async () => selected })
        Object.defineProperty(navigator.mediaDevices, "getUserMedia", { configurable: true, value: async () => mic.stream })
        const chunks = [], errors = []
        let stopped = 0
        const capture = new window.RecordingCapture({ change() {}, chunk: blob => chunks.push(blob), stopped: () => stopped++, error: error => errors.push(error.message) })
        await capture.prepare(microphone ? "" : false, "browser"); await capture.start()
        await wait(1200)
        const track = first.stream.getVideoTracks()[0]
        track.stop(); track.dispatchEvent(new Event("ended"))
        await wait(1200)
        const afterSharingStop = { state: capture.state, sharing: capture.screenSharing, stopped, microphone: capture.inputStatus.microphone }
        selected = second.stream
        await capture.shareScreen("browser")
        await wait(1200)
        await capture.stop()
        const blob = new Blob(chunks, { type: capture.info.mime })
        const video = document.createElement("video")
        video.muted = true
        const url = URL.createObjectURL(blob)
        video.src = url
        try { await video.play() } catch (error) {
          throw new Error(JSON.stringify({ microphone, errors, state: capture.state, bytes: blob.size, mime: capture.info.mime, chunks: chunks.length, message: String(error) }))
        }
        const canvas = document.createElement("canvas"); canvas.width = 320; canvas.height = 180
        const ctx = canvas.getContext("2d")
        const pixelAt = async time => {
          video.currentTime = time
          await new Promise(resolve => video.addEventListener("seeked", resolve, { once: true }))
          ctx.drawImage(video, 0, 0, 320, 180)
          return [...ctx.getImageData(10, 10, 1, 1).data]
        }
        const pixels = []
        for (const time of [0.7, 1.8, 3.1]) pixels.push(await pixelAt(time))
        const decoded = await sound.decodeAudioData(await blob.arrayBuffer())
        const samples = decoded.getChannelData(0).slice(Math.floor(decoded.sampleRate * 1.5), Math.floor(decoded.sampleRate * 2))
        const rms = Math.sqrt(samples.reduce((sum, x) => sum + x * x, 0) / samples.length)
        results.push({ microphone, afterSharingStop, stopped, errors, pixels, duration: decoded.duration, rms, bytes: blob.size })
        video.pause(); video.src = ""; URL.revokeObjectURL(url)
        clearInterval(first.timer); clearInterval(second.timer)
        first.stream.getTracks().forEach(t => t.stop()); second.stream.getTracks().forEach(t => t.stop())
        mic.stream.getTracks().forEach(t => t.stop()); await sound.close()
      }
      return results
    })
    for (const result of results) {
      assert.deepEqual(result.errors, [])
      assert.equal(result.afterSharingStop.state, "recording")
      assert.equal(result.afterSharingStop.sharing, false)
      assert.equal(result.afterSharingStop.stopped, 0)
      assert.equal(result.stopped, 1)
      assert.ok(result.duration > 3.2)
      assert.ok(result.pixels[0][0] > 200, "screen before stop is red")
      assert.ok(result.pixels[1][0] < 50 && result.pixels[1][2] < 70, "no old screen remains after sharing stops")
      assert.ok(result.pixels[2][2] > 200, "new screen is blue in the same file")
      if (result.microphone) assert.ok(result.rms > 0.1, "microphone audio continues without screen sharing")
      else assert.ok(result.rms < 0.001, "no microphone produces silence")
    }
  } finally { await browser.close() }
})
