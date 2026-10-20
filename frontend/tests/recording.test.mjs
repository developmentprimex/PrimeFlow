import assert from "node:assert/strict"
import { test } from "node:test"
import { readFileSync } from "node:fs"
import vm from "node:vm"
import ts from "typescript"
import { webcrypto } from "node:crypto"

function load(name, globals = {}) {
  const source = readFileSync(new URL(`../src/lib/${name}.ts`, import.meta.url), "utf8")
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } })
  const module = { exports: {} }
  vm.runInNewContext(outputText, { module, exports: module.exports, Response, Blob, AbortSignal, crypto: webcrypto, setTimeout, performance, ...globals })
  return module.exports
}

function captureHarness({ system = true, micDenied = false, displayDenied = false, delayedMic } = {}) {
  class Track extends EventTarget {
    constructor(kind) { super(); this.kind = kind; this.readyState = "live"; this.enabled = true; this.muted = false }
    stop() { this.readyState = "ended" }
    getSettings() { return { displaySurface: "browser" } }
    end() { this.stop(); this.dispatchEvent(new Event("ended")) }
  }
  class Stream {
    constructor(tracks) { this.tracks = tracks }
    getTracks() { return this.tracks }
    getAudioTracks() { return this.tracks.filter(t => t.kind === "audio") }
    getVideoTracks() { return this.tracks.filter(t => t.kind === "video") }
    addTrack(t) { this.tracks.push(t) }
  }
  const video = new Track("video"), sys = new Track("audio"), mic = new Track("audio")
  const display = new Stream(system ? [video, sys] : [video]), microphone = new Stream([mic])
  const connections = [], contexts = [], chunks = [], errors = []
  class Node {
    constructor() { this.gain = { value: 1 } }
    connect(to) { connections.push(to); return to }
    disconnect() { this.disconnected = true }
  }
  class Context {
    constructor() { this.destination = new Node(); this.closed = false; contexts.push(this) }
    resume() { return Promise.resolve() }
    createMediaStreamDestination() { const n = new Node(); n.stream = new Stream([new Track("audio")]); return n }
    createMediaStreamSource() { return new Node() }
    createGain() { return new Node() }
    close() { this.closed = true; return Promise.resolve() }
  }
  class Recorder {
    static isTypeSupported(type) { return type.startsWith("video/webm") }
    constructor(stream, options) { this.stream = stream; this.options = options; Recorder.last = this }
    start(timeslice) { this.timeslice = timeslice; this.state = "recording" }
    pause() { this.state = "paused" }
    resume() { this.state = "recording" }
    stop() { this.state = "inactive"; queueMicrotask(() => { this.ondataavailable?.({ data: new Blob(["last fragment"]) }); this.onstop?.() }) }
  }
  let stopped = 0
  const { RecordingCapture } = load("recording-capture", { MediaStream: Stream, MediaRecorder: Recorder, AudioContext: Context, navigator: { mediaDevices: {
    async getDisplayMedia() { if (displayDenied) throw new Error("Screen denied"); return display },
    async getUserMedia() { if (micDenied) throw new Error("Microphone denied"); if (delayedMic) await delayedMic; return microphone },
  } } })
  const capture = new RecordingCapture({ change() {}, chunk: blob => chunks.push(blob), stopped: () => stopped++, error: error => errors.push(error.message) })
  return { capture, video, sys, mic, contexts, connections, chunks, errors, Recorder, stopped: () => stopped }
}

test("capture mixes actual microphone/system tracks without speaker playback and cleans up after stop", async () => {
  const h = captureHarness()
  await h.capture.prepare("", "browser")
  assert.equal(h.capture.state, "prepared")
  assert.equal(h.capture.info.system, true)
  await h.capture.start()
  assert.equal(h.Recorder.last.stream.getVideoTracks().length, 1)
  assert.equal(h.Recorder.last.stream.getAudioTracks().length, 1)
  assert.equal(h.Recorder.last.timeslice, 4000)
  assert.ok(!h.connections.includes(h.contexts[0].destination))
  await h.capture.stop()
  assert.equal(h.stopped(), 1)
  assert.equal(h.chunks.length, 1)
  for (const t of [h.video, h.sys, h.mic]) assert.equal(t.readyState, "ended")
  assert.ok(h.contexts[0].closed)
})
test("missing system audio is reported before start; microphone can be omitted", async () => {
  const h = captureHarness({ system: false })
  await h.capture.prepare(false, "window")
  assert.equal(h.capture.info.system, false)
  assert.equal(h.capture.info.microphone, false)
  assert.equal(h.capture.state, "prepared")
  h.capture.cancel()
  assert.equal(h.video.readyState, "ended")
})
test("microphone denial releases screen and does not start a silent recording", async () => {
  const h = captureHarness({ micDenied: true })
  await h.capture.prepare("", "monitor")
  assert.equal(h.capture.state, "error")
  assert.equal(h.video.readyState, "ended")
  assert.equal(h.Recorder.last, undefined)
  assert.match(h.errors[0], /Microphone denied/)
})
test("screen permission denial creates no recorder", async () => {
  const h = captureHarness({ displayDenied: true })
  await h.capture.prepare("", "monitor")
  assert.equal(h.capture.state, "error")
  assert.equal(h.Recorder.last, undefined)
})
test("native sharing stop finalizes exactly once, including overlapping stop calls", async () => {
  const h = captureHarness()
  await h.capture.prepare("", "browser"); await h.capture.start()
  h.video.end()
  await Promise.all([h.capture.stop(), h.capture.stop()])
  assert.equal(h.stopped(), 1)
  assert.equal(h.capture.state, "stopped")
})
test("native stop during microphone setup cancels and stops the late microphone", async () => {
  let release
  const delayedMic = new Promise(resolve => { release = resolve })
  const h = captureHarness({ delayedMic })
  const preparation = h.capture.prepare("", "browser")
  await new Promise(resolve => setImmediate(resolve))
  h.video.end(); release(); await preparation
  assert.equal(h.capture.state, "idle")
  assert.equal(h.mic.readyState, "ended")
  assert.equal(h.Recorder.last, undefined)
})
test("pause/resume and independent microphone/system toggles", async () => {
  const h = captureHarness()
  await h.capture.prepare("", "browser"); await h.capture.start()
  h.capture.pause(); h.capture.pause(); assert.equal(h.capture.state, "paused")
  h.capture.toggle("microphone"); assert.equal(h.mic.enabled, false); assert.equal(h.sys.enabled, true)
  h.capture.toggle("system"); assert.equal(h.sys.enabled, false)
  h.capture.resume(); assert.equal(h.capture.state, "recording")
  await h.capture.stop()
})

class MemoryOutbox {
  manifest = { id: "session", count: 0, acknowledged: 0, bytes: 0, uploadedBytes: 0, stopped: false }
  chunks = []
  async get() { return { ...this.manifest } }
  async append(_, blob) { this.chunks.push(blob); this.manifest.count++; this.manifest.bytes += blob.size }
  async next() { return this.chunks[this.manifest.acknowledged] }
  async acknowledge(_, bytes) { this.chunks[this.manifest.acknowledged] = undefined; this.manifest.acknowledged++; this.manifest.uploadedBytes += bytes }
  async remove() { this.removed = true }
}
const { RecordingUploader } = load("recording-outbox")
function receipt(index, options) { return Response.json({ index, sha256: options.headers["X-Chunk-SHA256"], size_bytes: options.body.size }) }
test("chunk retry uses exponential backoff and identical sequential index/hash", async () => {
  const outbox = new MemoryOutbox(), attempts = [], delays = []
  await outbox.append("session", new Blob(["chunk"]))
  const uploader = new RecordingUploader("session", outbox, async (path, init) => {
    attempts.push([path, init.headers["X-Chunk-SHA256"]])
    if (attempts.length <= 2) return new Response(null, { status: 503 })
    return receipt(0, init)
  }, () => {}, async ms => { delays.push(ms) })
  await uploader.pump()
  assert.deepEqual(delays, [1000, 2000]); assert.deepEqual(attempts[0], attempts[2])
  assert.equal(outbox.manifest.acknowledged, 1)
})
test("failed upload never finalizes or deletes durable pending data; explicit retry recovers", async () => {
  const outbox = new MemoryOutbox(); await outbox.append("session", new Blob(["chunk"]))
  outbox.manifest.stopped = true
  let online = false, completed = false
  const uploader = new RecordingUploader("session", outbox, async (path, init) => {
    if (path.endsWith("complete")) { completed = true; return Response.json({ status: "READY" }) }
    return online ? receipt(0, init) : new Response(null, { status: 503 })
  }, () => {}, async () => {})
  await assert.rejects(uploader.complete())
  assert.equal(completed, false); assert.equal(outbox.removed, undefined); assert.ok(outbox.chunks[0])
  online = true; await uploader.complete()
  assert.ok(completed); assert.ok(outbox.removed)
})
test("unfinished capture, mismatched receipts and non-READY completion never report saved", async () => {
  const outbox = new MemoryOutbox()
  const uploader = new RecordingUploader("session", outbox, async () => Response.json({ status: "FINALIZING" }), () => {})
  await assert.rejects(uploader.complete(), /paplotë/)
  await outbox.append("session", new Blob(["chunk"]))
  await assert.rejects(uploader.pump(), /përputhet/)
  assert.equal(outbox.manifest.acknowledged, 0)
  outbox.manifest.acknowledged = 1; outbox.manifest.stopped = true
  await assert.rejects(uploader.complete(), /konfirmoi/)
  assert.equal(outbox.removed, undefined)
})
test("fatal local capture failure cannot upload or complete a misleading partial recording", async () => {
  const outbox = new MemoryOutbox(); await outbox.append("session", new Blob(["partial"]))
  outbox.manifest.stopped = true; outbox.manifest.fatal = "Local storage failed"
  let calls = 0
  const uploader = new RecordingUploader("session", outbox, async () => { calls++; return Response.json({ status: "READY" }) }, () => {})
  await assert.rejects(uploader.complete(), /Local storage failed/)
  assert.equal(calls, 0); assert.equal(outbox.removed, undefined)
})
test("long upload processes 1500 sequential fragments and keeps only the current upload in flight", async () => {
  const outbox = new MemoryOutbox()
  for (let i = 0; i < 1500; i++) await outbox.append("session", new Blob([String(i)]))
  let index = 0, inflight = 0, maxInflight = 0
  const uploader = new RecordingUploader("session", outbox, async (path, init) => {
    inflight++; maxInflight = Math.max(inflight, maxInflight)
    assert.ok(path.endsWith(`/chunks/${index}`)); const result = receipt(index++, init); inflight--; return result
  }, () => {})
  await Promise.all([uploader.pump(), uploader.pump()])
  assert.equal(index, 1500); assert.equal(maxInflight, 1); assert.equal(outbox.manifest.acknowledged, 1500)
})
