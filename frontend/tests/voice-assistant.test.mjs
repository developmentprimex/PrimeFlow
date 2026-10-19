import assert from "node:assert/strict"
import { test } from "node:test"
import { readFileSync } from "node:fs"
import vm from "node:vm"
import ts from "typescript"

const source = readFileSync(new URL("../src/lib/useVoiceAssistant.ts", import.meta.url), "utf8")
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } })
const flush = () => new Promise(resolve => setImmediate(resolve))

function harness({ apiFetch = async () => new Response("sdp-answer"), getUserMedia } = {}) {
  const slots = [], cleanups = [], sent = [], requests = [], refreshes = []
  let cursor = 0, first = true, peer, stopped = false
  const track = { enabled: true, stop() { stopped = true } }
  const stream = { getTracks: () => [track], getAudioTracks: () => [track] }
  const react = {
    useState(initial) {
      const index = cursor++
      if (first) slots[index] = initial
      return [slots[index], value => { slots[index] = typeof value === "function" ? value(slots[index]) : value }]
    },
    useRef(value) { const index = cursor++; if (first) slots[index] = { current: value }; return slots[index] },
    useCallback(fn) { return fn },
    useEffect(fn) { if (first) cleanups.push(fn()) },
  }
  class Peer {
    constructor() {
      peer = this
      this.dc = {
        readyState: "connecting",
        send(value) { sent.push(JSON.parse(value)) },
        close() { this.readyState = "closed"; this.onclose?.() },
      }
    }
    addTrack() {}
    createDataChannel() { return this.dc }
    async createOffer() { return { sdp: "browser-sdp-offer" } }
    async setLocalDescription() {}
    async setRemoteDescription(answer) { assert.equal(answer.sdp, "sdp-answer") }
    close() { this.connectionState = "closed"; this.onconnectionstatechange?.() }
  }
  const loadedModule = { exports: {} }
  const timers = new Map()
  vm.runInNewContext(outputText, {
    module: loadedModule, exports: loadedModule.exports,
    require(name) { return name === "react" ? react : { useAuth: () => ({ apiFetch: async (...args) => { requests.push(args); return apiFetch(...args) } }) } },
    navigator: { mediaDevices: { getUserMedia: getUserMedia || (async () => stream) } },
    RTCPeerConnection: Peer, MediaStream: class {}, AbortController, DOMException, Response,
    crypto: { randomUUID: () => String(Math.random()) },
    window: { dispatchEvent(event) { refreshes.push(event.type) } }, Event,
    setTimeout(fn, delay) { const id = Symbol(); timers.set(id, { fn, delay }); return id },
    clearTimeout(id) { timers.delete(id) },
  })
  return {
    sent, requests, refreshes, track, stream,
    render() { cursor = 0; const result = loadedModule.exports.useVoiceAssistant(); first = false; return result },
    open() { peer.dc.readyState = "open"; peer.dc.onopen() },
    emit(event) { peer.dc.onmessage({ data: JSON.stringify(event) }) },
    stopped: () => stopped,
    unmount() { cleanups.forEach(fn => fn?.()) },
    timerCount: () => timers.size,
  }
}

test("connects through our authenticated backend, greets, mutes and releases the microphone", async () => {
  const h = harness()
  await h.render().start()
  assert.equal(h.requests[0][0], "/voice-assistant/session")
  assert.equal(JSON.parse(h.requests[0][1].body).sdp, "browser-sdp-offer")
  h.open()
  assert.equal(h.sent[0].type, "response.create")
  assert.equal(h.render().phase, "listening")
  h.render().toggleMute()
  assert.equal(h.track.enabled, false)
  assert.equal(h.render().muted, true)
  h.render().stop()
  assert.equal(h.stopped(), true)
  assert.equal(h.timerCount(), 0)
  assert.equal(h.render().phase, "idle")
})

test("stopping while permission is pending releases a late microphone without creating a session", async () => {
  let resolve
  const h = harness({ getUserMedia: () => new Promise(done => { resolve = done }) })
  const start = h.render().start()
  h.render().stop()
  resolve(h.stream)
  await start
  assert.equal(h.stopped(), true)
  assert.equal(h.requests.length, 0)
})

test("deduplicates function calls, returns results to the model and refreshes changed tasks", async () => {
  const h = harness({ apiFetch: async path => path.endsWith("/session") ? new Response("sdp-answer") : Response.json({ success: true, changed: true, applied: ["U ruajt"] }) })
  await h.render().start(); h.open()
  const event = { type: "response.done", response: { output: [{ type: "function_call", call_id: "call-1", name: "set_task_status", arguments: '{"task_id":"test"}' }] } }
  h.emit(event); h.emit(event)
  await flush()
  assert.equal(h.requests.filter(([path]) => path.includes("/tools/")).length, 1)
  const output = h.sent.find(event => event.item?.type === "function_call_output")
  assert.equal(output.item.call_id, "call-1")
  assert.equal(JSON.parse(output.item.output).success, true)
  assert.deepEqual(h.refreshes, ["primex:tasks-changed"])
  assert.equal(h.render().messages.length, 0) // Tool details stay out of the chat.
  h.unmount()
})

test("keeps transcripts and returns schedule results to the model for follow-up commands", async () => {
  const h = harness({ apiFetch: async path => path.endsWith("/session") ? new Response("sdp-answer") : Response.json({ tasks: [{ id: "task-1", title: "Raporti", status: "TODO", one_h_report_slot: "10:00" }] }) })
  await h.render().start(); h.open()
  h.emit({ type: "conversation.item.input_audio_transcription.completed", item_id: "user-1", transcript: "Çfarë kam në 1H të orës 10?" })
  h.emit({ type: "response.done", response: { output: [{ type: "function_call", call_id: "schedule", name: "list_my_schedule", arguments: "{}" }] } })
  await flush()
  h.emit({ type: "response.output_audio_transcript.delta", item_id: "answer", delta: "Ke një " })
  h.emit({ type: "response.output_audio_transcript.delta", item_id: "answer", delta: "detyrë." })
  assert.equal(h.render().messages[1].text, "Ke një detyrë.")
  const output = h.sent.find(event => event.item?.type === "function_call_output")
  assert.equal(JSON.parse(output.item.output).tasks[0].one_h_report_slot, "10:00")
  assert.equal(h.render().sendText("Mbylle atë"), true)
  assert.equal(h.sent.at(-2).item.content[0].text, "Mbylle atë")
  h.unmount()
})

test("reserves the spoken user's bubble before an answer even when transcription is late", async () => {
  const h = harness()
  await h.render().start(); h.open()
  h.emit({ type: "input_audio_buffer.speech_started", item_id: "user-1" })
  assert.equal(h.render().messages[0].pending, true)
  h.emit({ type: "response.output_audio_transcript.delta", item_id: "answer-1", delta: "Ke dy detyra." })
  h.emit({ type: "conversation.item.input_audio_transcription.completed", item_id: "user-1", transcript: "Çfarë detyra kam?" })
  assert.deepEqual(Array.from(h.render().messages, message => message.id), ["user-1", "answer-1"])
  assert.equal(h.render().messages[0].text, "Çfarë detyra kam?")
  assert.equal(h.render().messages[0].pending, false)
  h.unmount()
})

test("out-of-order transcriptions across multiple turns keep each answer after its question", async () => {
  const h = harness()
  await h.render().start(); h.open()
  for (const turn of [1, 2]) {
    h.emit({ type: "input_audio_buffer.speech_started", item_id: `user-${turn}` })
    h.emit({ type: "input_audio_buffer.committed", item_id: `user-${turn}`, previous_item_id: turn === 1 ? null : "answer-1" })
    h.emit({ type: "conversation.item.added", previous_item_id: `user-${turn}`, item: { id: `answer-${turn}`, type: "message", role: "assistant", content: [] } })
    h.emit({ type: "response.output_audio_transcript.delta", item_id: `answer-${turn}`, delta: `Answer ${turn}` })
  }
  h.emit({ type: "conversation.item.input_audio_transcription.completed", item_id: "user-2", transcript: "Question 2" })
  h.emit({ type: "conversation.item.input_audio_transcription.completed", item_id: "user-1", transcript: "Question 1" })
  assert.deepEqual(Array.from(h.render().messages, message => message.text), ["Question 1", "Answer 1", "Question 2", "Answer 2"])
  h.unmount()
})

test("conversation predecessors repair ordering through invisible tool items if speech events were missed", async () => {
  const h = harness()
  await h.render().start(); h.open()
  h.emit({ type: "response.output_audio_transcript.delta", item_id: "answer", delta: "U mbyll." })
  h.emit({ type: "conversation.item.added", previous_item_id: "tool-result", item: { id: "answer", type: "message", role: "assistant", content: [] } })
  h.emit({ type: "conversation.item.added", previous_item_id: "tool-call", item: { id: "tool-result", type: "function_call_output" } })
  h.emit({ type: "conversation.item.added", previous_item_id: "user", item: { id: "tool-call", type: "function_call" } })
  h.emit({ type: "conversation.item.created", previous_item_id: null, item: { id: "user", type: "message", role: "user", content: [] } })
  h.emit({ type: "conversation.item.input_audio_transcription.completed", item_id: "user", transcript: "Mbylle detyrën" })
  assert.deepEqual(Array.from(h.render().messages, message => message.id), ["user", "answer"])
  assert.equal(h.render().messages[1].text, "U mbyll.")
  h.unmount()
})

test("typed messages use the same item ID as their server echo and appear only once", async () => {
  const h = harness()
  await h.render().start(); h.open()
  h.render().sendText("Mbylle detyrën")
  const item = h.sent.find(event => event.item?.role === "user").item
  assert.equal(h.render().messages[0].id, item.id)
  h.emit({ type: "response.output_audio_transcript.delta", item_id: "answer", delta: "U mbyll." })
  h.emit({ type: "conversation.item.added", previous_item_id: null, item })
  h.emit({ type: "conversation.item.created", previous_item_id: null, item })
  assert.deepEqual(Array.from(h.render().messages, message => message.text), ["Mbylle detyrën", "U mbyll."])
  h.unmount()
})

test("failed transcription fills the reserved bubble and delayed metadata cannot erase text", async () => {
  const h = harness()
  await h.render().start(); h.open()
  h.emit({ type: "input_audio_buffer.speech_started", item_id: "user" })
  h.emit({ type: "response.output_audio_transcript.delta", item_id: "answer", delta: "Nuk të kuptova." })
  h.emit({ type: "conversation.item.input_audio_transcription.failed", item_id: "user" })
  h.emit({ type: "conversation.item.created", item: { id: "user", type: "message", role: "user", content: [] } })
  const messages = h.render().messages
  assert.equal(messages[0].role, "user")
  assert.equal(messages[0].pending, false)
  assert.equal(messages[0].text, "Transkripti nuk u përfundua.")
  assert.equal(messages[1].text, "Nuk të kuptova.")
  h.unmount()
})

test("stopped sessions cannot start queued writes or resume speaking", async () => {
  const h = harness()
  await h.render().start(); h.open()
  h.emit({ type: "response.done", response: { output: [{ type: "function_call", call_id: "late", name: "set_task_status", arguments: "{}" }] } })
  h.render().stop()
  await flush()
  assert.equal(h.requests.length, 1)
  assert.equal(h.render().phase, "idle")
})

test("a denied tool is returned as an error and is never announced as completed", async () => {
  const h = harness({ apiFetch: async path => path.endsWith("/session") ? new Response("sdp-answer") : Response.json({ detail: "Forbidden" }, { status: 403 }) })
  await h.render().start(); h.open()
  h.emit({ type: "response.done", response: { output: [{ type: "function_call", call_id: "denied", name: "set_task_points", arguments: "{}" }] } })
  await flush()
  const output = h.sent.find(event => event.item?.type === "function_call_output")
  assert.equal(JSON.parse(output.item.output).error, "Forbidden")
  assert.equal(h.render().messages.length, 0)
  assert.equal(h.refreshes.length, 0)
  h.unmount()
})
