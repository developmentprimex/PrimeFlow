import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import vm from "node:vm"
import { test } from "node:test"
import ts from "typescript"

function harness({ system = true, state = "prepared", locked = false, fragmentLimit = Infinity } = {}) {
  const requests = [], captures = [], completed = []
  const react = {
    createContext: () => ({ Provider: "provider" }),
    useRef: current => ({ current }),
    useState: initial => [initial, () => {}],
    useCallback: callback => callback,
    useEffect: effect => effect(),
  }
  class Capture {
    state = "idle"
    info = { source: "monitor", system, microphone: true, mime: "video/webm;codecs=vp9,opus" }
    constructor(events) { this.events = events; captures.push(this) }
    async prepare() { this.state = state }
    async start() { this.starts = (this.starts || 0) + 1; this.state = "recording" }
    cancel() { this.state = "idle" }
    async stop() { this.state = "stopped"; this.events.stopped() }
  }
  class Outbox {
    fragments = []
    async list() { return this.manifest ? [this.manifest] : [] }
    async create(manifest) { this.manifest = manifest }
    async get() { return this.manifest }
    async append(_id, blob) {
      if (this.fragments.length >= fragmentLimit) throw new Error("Quota exceeded")
      this.fragments.push(await blob.text())
    }
    async stop(_id, fatal, partial) { Object.assign(this.manifest, { stopped: true, fatal, partial }) }
  }
  class Uploader {
    constructor(_id, outbox) { this.outbox = outbox }
    async pump() {}
    async complete() {
      completed.push({ partial: this.outbox.manifest.partial, fragments: [...this.outbox.fragments] })
      return { is_partial: this.outbox.manifest.partial }
    }
  }
  const apiFetch = async (url, init) => {
    requests.push({ url, body: JSON.parse(init.body) })
    return { id: "session-id" }
  }
  const modules = {
    react,
    "react/jsx-runtime": { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) },
    "next/link": { default: "link" },
    "@/lib/auth": { useAuth: () => ({ user: { id: "user-id" }, apiFetch }) },
    "@/lib/recording-capture": { RecordingCapture: Capture },
    "@/lib/recording-outbox": { IndexedRecordingOutbox: Outbox, MAX_CHUNK_BYTES: 32 * 1024 * 1024,
      RecordingUploader: Uploader, RetryableRecordingUploadError: class extends Error {}, recordingJson: async value => value },
    "@/lib/recording-types": { recordingTime: () => "00:00" },
    "@/components/ui/button": { Button: "button" },
  }
  const source = readFileSync(new URL("../src/components/meeting-recordings/recorder-provider.tsx", import.meta.url), "utf8")
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } })
  const exports = {}
  vm.runInNewContext(outputText, {
    exports, require: name => { assert.ok(modules[name], name); return modules[name] },
    navigator: { locks: { request: async (_name, _options, callback) => callback(locked ? null : {}) } },
    window: { addEventListener() {}, removeEventListener() {} },
    setInterval() {}, clearInterval() {}, AbortSignal,
  })
  const recorder = exports.RecorderProvider({ children: null }).props.value
  return { recorder, requests, captures, completed }
}

const details = { title: "Takimi", meetingId: "meeting-id", description: "Përshkrimi" }

test("sharing with system audio starts once automatically with the entered details", async () => {
  const { recorder, requests, captures } = harness()
  await recorder.prepare("", "monitor", details)
  assert.equal(captures[0].state, "recording")
  assert.equal(captures[0].starts, 1)
  assert.equal(requests.length, 1)
  assert.equal(requests[0].body.title, details.title)
  assert.equal(requests[0].body.meeting_id, details.meetingId)
  assert.equal(requests[0].body.description, details.description)
  assert.equal(requests[0].body.has_system_audio, true)
  await recorder.start(details.title, details.meetingId, details.description)
  assert.equal(requests.length, 1)
})

test("missing system audio waits for explicit continuation", async () => {
  const { recorder, requests, captures } = harness({ system: false })
  await recorder.prepare(false, "monitor", details)
  assert.equal(captures[0].state, "prepared")
  assert.equal(requests.length, 0)
  await recorder.start(details.title, details.meetingId, details.description)
  assert.equal(captures[0].state, "recording")
})

test("project association reaches creation for automatic and explicit start", async () => {
  for (const system of [true, false]) {
    const { recorder, requests } = harness({ system })
    await recorder.prepare("", "monitor", { ...details, projectId: "project-id" })
    if (!system) await recorder.start(details.title, details.meetingId, details.description, "project-id")
    assert.equal(requests.length, 1)
    assert.equal(requests[0].body.project_id, "project-id")
  }
})

test("exhausting local storage saves only the contiguous prefix and marks it partial", async () => {
  const { recorder, captures, completed } = harness({ fragmentLimit: 2 })
  await recorder.prepare("", "monitor", details)
  const capture = captures[0]
  for (const fragment of ["header", "captured", "quota failure", "must be excluded"]) {
    capture.events.chunk(new Blob([fragment]))
  }
  await new Promise(setImmediate)
  assert.equal(capture.state, "stopped")
  assert.deepEqual(completed, [{ partial: true, fragments: ["header", "captured"] }])
})

for (const options of [{ state: "error" }, { state: "idle" }, { locked: true }]) {
  test(`failed or cancelled sharing never starts a session: ${JSON.stringify(options)}`, async () => {
    const { recorder, requests } = harness(options)
    await recorder.prepare("", "monitor", details)
    assert.equal(requests.length, 0)
  })
}
