import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import vm from "node:vm"
import { test } from "node:test"
import ts from "typescript"

function harness({ system = true, state = "prepared", locked = false } = {}) {
  const requests = [], captures = []
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
    constructor() { captures.push(this) }
    async prepare() { this.state = state }
    async start() { this.starts = (this.starts || 0) + 1; this.state = "recording" }
    cancel() { this.state = "idle" }
  }
  class Outbox {
    async list() { return [] }
    async create(manifest) { this.manifest = manifest }
    async get() { return this.manifest }
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
    "@/lib/recording-outbox": { IndexedRecordingOutbox: Outbox, RecordingUploader: class {}, recordingJson: async value => value },
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
  return { recorder, requests, captures }
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

for (const options of [{ state: "error" }, { state: "idle" }, { locked: true }]) {
  test(`failed or cancelled sharing never starts a session: ${JSON.stringify(options)}`, async () => {
    const { recorder, requests } = harness(options)
    await recorder.prepare("", "monitor", details)
    assert.equal(requests.length, 0)
  })
}
