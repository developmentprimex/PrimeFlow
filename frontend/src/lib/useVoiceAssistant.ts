"use client"

import * as React from "react"
import { useAuth } from "@/lib/auth"

export type VoiceMessage = { id: string; role: "user" | "assistant"; text: string; pending: boolean }
type Phase = "idle" | "connecting" | "listening" | "thinking" | "speaking" | "working"
type ToolCall = { type: string; call_id: string; name: string; arguments: string }
type RealtimeEvent = {
  type: string; item_id?: string; previous_item_id?: string | null; delta?: string; transcript?: string; text?: string;
  item?: { id: string; type: string; role?: "user" | "assistant"; content?: { text?: string; transcript?: string }[] };
  error?: { message?: string; code?: string };
  response?: { status?: string; output?: ToolCall[]; status_details?: { error?: { message?: string } } };
}

const allowedTools = new Set(["search_tasks", "list_my_schedule", "get_task", "set_task_status", "set_task_points", "set_checklist_item"])
const notesTools = new Set(["notes_get_context", "notes_edit", "notes_select", "notes_new", "notes_save"])
type VoiceOptions = {
  mode?: "tasks" | "px_notes"
  onToolCall?: (name: string, arguments_: Record<string, unknown>) => Promise<Record<string, unknown>>
}
// Transcription is asynchronous. Follow conversation predecessors, including
// invisible function items, instead of ordering bubbles by transcript arrival.
function orderMessages(messages: VoiceMessage[], predecessors: Map<string, string | null>) {
  const byId = new Map(messages.map(message => [message.id, message]))
  const visited = new Set<string>()
  const ordered: VoiceMessage[] = []
  const visit = (id: string) => {
    if (visited.has(id)) return
    visited.add(id)
    const parent = predecessors.get(id)
    if (parent) visit(parent)
    const entry = byId.get(id)
    if (entry) ordered.push(entry)
  }
  messages.forEach(message => visit(message.id))
  return ordered
}

export function useVoiceAssistant(options: VoiceOptions = {}) {
  const { apiFetch } = useAuth()
  const [phase, setPhase] = React.useState<Phase>("idle")
  const [messages, setMessages] = React.useState<VoiceMessage[]>([])
  const [error, setError] = React.useState("")
  const [muted, setMuted] = React.useState(false)
  const [audioBlocked, setAudioBlocked] = React.useState(false)
  const audioRef = React.useRef<HTMLAudioElement>(null)
  const connection = React.useRef<RTCPeerConnection | null>(null)
  const channel = React.useRef<RTCDataChannel | null>(null)
  const microphone = React.useRef<MediaStream | null>(null)
  const generation = React.useRef(0)
  const timeout = React.useRef<ReturnType<typeof setTimeout> | null>(null)
  const deadline = React.useRef<ReturnType<typeof setTimeout> | null>(null)
  const request = React.useRef<AbortController | null>(null)
  const predecessors = React.useRef(new Map<string, string | null>())
  const optionsRef = React.useRef(options)
  React.useEffect(() => { optionsRef.current = options }, [options])

  const message = React.useCallback((id: string, role: VoiceMessage["role"], text?: string, append = false) => {
    setMessages(previous => {
      const existing = previous.find(m => m.id === id)
      const next = existing
        ? previous.map(m => m.id === id && text !== undefined ? { ...m, text: append ? m.text + text : text, pending: false } : m)
        : [...previous.slice(-149), { id, role, text: text || "", pending: text === undefined }]
      return orderMessages(next, predecessors.current)
    })
  }, [])

  const release = React.useCallback(() => {
    generation.current += 1
    if (timeout.current) clearTimeout(timeout.current)
    if (deadline.current) clearTimeout(deadline.current)
    request.current?.abort()
    request.current = null
    microphone.current?.getTracks().forEach(track => track.stop())
    microphone.current = null
    const dc = channel.current
    const pc = connection.current
    channel.current = null
    connection.current = null
    dc?.close()
    pc?.close()
    if (audioRef.current) audioRef.current.srcObject = null
  }, [])

  const stop = React.useCallback(() => {
    release()
    setPhase("idle")
    setMuted(false)
    setAudioBlocked(false)
  }, [release])

  React.useEffect(() => () => release(), [release])

  const start = React.useCallback(async () => {
    if (connection.current) return
    release()
    const current = generation.current
    const active = () => generation.current === current
    const mode = optionsRef.current.mode || "tasks"
    setError("")
    setMessages([])
    predecessors.current.clear()
    setMuted(false)
    setPhase("connecting")
    if (!navigator.mediaDevices?.getUserMedia || typeof RTCPeerConnection === "undefined") {
      setError("Mikrofoni kërkon HTTPS ose localhost dhe një shfletues që mbështet WebRTC.")
      setPhase("idle")
      return
    }
    const controller = new AbortController()
    request.current = controller
    timeout.current = setTimeout(() => {
      if (active()) { stop(); setError("Lidhja zgjati tepër. Provo përsëri.") }
    }, 45000)
    try {
      const pc = new RTCPeerConnection()
      connection.current = pc
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
      if (!active()) { stream.getTracks().forEach(track => track.stop()); return }
      microphone.current = stream
      stream.getAudioTracks().forEach(track => pc.addTrack(track, stream))
      pc.ontrack = event => {
        if (!active() || !audioRef.current) return
        audioRef.current.srcObject = new MediaStream([event.track])
        void audioRef.current.play().catch(() => {
          if (active()) { setAudioBlocked(true); setError("Shtyp Start përsëri për të aktivizuar zërin.") }
        })
      }
      pc.onconnectionstatechange = () => {
        if (active() && ["failed", "closed", "disconnected"].includes(pc.connectionState)) {
          stop(); setError("Lidhja zanore u ndërpre. Mund të lidhesh përsëri.")
        }
      }
      const dc = pc.createDataChannel("oai-events")
      channel.current = dc
      const handled = new Set<string>()
      let responseActive = false
      let pendingResponse = false
      let toolQueue = Promise.resolve()
      const send = (value: object) => {
        if (active() && dc.readyState === "open") dc.send(JSON.stringify(value))
      }
      const respond = () => {
        if (responseActive) pendingResponse = true
        else { pendingResponse = false; responseActive = true; send({ type: "response.create" }) }
      }
      const runTools = async (calls: ToolCall[]) => {
        let silent = mode === "px_notes"
        for (const call of calls) {
          if (!active()) return
          setPhase("working")
          let output: Record<string, unknown>
          try {
            const args = JSON.parse(call.arguments)
            if (mode === "px_notes") {
              if (!notesTools.has(call.name) || !optionsRef.current.onToolCall) throw new Error("Veprimi nuk mbështetet.")
              output = await optionsRef.current.onToolCall(call.name, args)
            } else {
              if (!allowedTools.has(call.name)) throw new Error("Veprimi nuk mbështetet.")
              const result = await apiFetch(`/voice-assistant/tools/${call.name}`, {
                method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(args),
              })
              const body = await result.json().catch(() => ({}))
              output = result.ok ? body : { success: false, error: typeof body.detail === "string" ? body.detail : "Veprimi u refuzua. Lexo gjendjen para riprovimit." }
            }
          } catch {
            output = { success: false, error: "Rezultati i veprimit nuk u konfirmua. Lexo gjendjen përpara se të riprovosh." }
          }
          // A started write may finish after the microphone is stopped. Always
          // refresh its result; never start another tool from an ended session.
          if (output.changed) window.dispatchEvent(new Event("primex:tasks-changed"))
          if (output.silent !== true) silent = false
          if (!active()) return
          send({ type: "conversation.item.create", item: { type: "function_call_output", call_id: call.call_id, output: JSON.stringify(output) } })
        }
        if (active()) {
          setPhase(silent ? "listening" : "thinking")
          if (!silent) respond()
        }
      }
      dc.onopen = () => {
        if (!active()) return
        if (timeout.current) clearTimeout(timeout.current)
        setPhase("listening")
        if (mode !== "px_notes") respond()
        deadline.current = setTimeout(() => {
          if (active()) { stop(); setError("Biseda u mbyll pas 10 minutash. Shtyp Start për të vazhduar.") }
        }, 10 * 60 * 1000)
      }
      dc.onclose = () => {
        if (active()) { stop(); setError("Biseda u shkëput. Lidhe përsëri për të vazhduar.") }
      }
      dc.onmessage = ({ data }) => {
        if (!active()) return
        let event: RealtimeEvent
        try { event = JSON.parse(data) } catch { return }
        if (["conversation.item.added", "conversation.item.created"].includes(event.type) && event.item) {
          if (event.previous_item_id !== undefined) predecessors.current.set(event.item.id, event.previous_item_id)
          if (event.item.type === "message" && event.item.role) {
            const text = event.item.content?.map(content => content.text || content.transcript || "").join("")
            message(event.item.id, event.item.role, text || undefined)
          } else {
            setMessages(previous => orderMessages(previous, predecessors.current))
          }
        }
        if (["input_audio_buffer.speech_started", "input_audio_buffer.committed"].includes(event.type) && event.item_id) {
          if (event.previous_item_id !== undefined) predecessors.current.set(event.item_id, event.previous_item_id)
          message(event.item_id, "user")
        }
        if (event.type === "input_audio_buffer.speech_started") setPhase("listening")
        if (event.type === "input_audio_buffer.speech_stopped") setPhase("thinking")
        if (event.type === "conversation.item.input_audio_transcription.completed" && event.item_id) {
          message(event.item_id, "user", event.transcript || "Audio pa tekst të kuptueshëm.")
        }
        if (event.type === "conversation.item.input_audio_transcription.failed" && event.item_id) {
          message(event.item_id, "user", "Transkripti nuk u përfundua.")
        }
        if (["response.output_audio_transcript.delta", "response.output_text.delta"].includes(event.type) && event.delta) {
          message(event.item_id || "assistant", "assistant", event.delta, true)
        }
        if (event.type === "response.output_audio_transcript.done" && event.transcript) {
          message(event.item_id || "assistant", "assistant", event.transcript)
        }
        if (event.type === "response.created") { responseActive = true; setPhase("thinking") }
        if (event.type === "output_audio_buffer.started") setPhase("speaking")
        if (["output_audio_buffer.stopped", "output_audio_buffer.cleared"].includes(event.type)) setPhase("listening")
        if (event.type === "response.done") {
          responseActive = false
          const calls = (event.response?.output || []).filter(item => item.type === "function_call" && !handled.has(item.call_id))
          calls.forEach(item => handled.add(item.call_id))
          if (calls.length) toolQueue = toolQueue.then(() => runTools(calls))
          else if (pendingResponse) respond()
          else if (event.response?.status === "failed") {
            setError("Mira nuk arriti të përgjigjet. Provo përsëri."); setPhase("listening")
          }
        }
        if (event.type === "error") {
          if (event.error?.code === "response_cancel_not_active") return
          if (event.error?.code === "conversation_already_has_active_response") { responseActive = true; pendingResponse = true; return }
          setError("Shërbimi zanor hasi një problem. Mbylle dhe lidhu përsëri.")
        }
      }
      const offer = await pc.createOffer()
      await pc.setLocalDescription(offer)
      if (!active()) return
      const result = await apiFetch("/voice-assistant/session", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sdp: offer.sdp, mode }), signal: controller.signal,
      })
      if (!active()) return
      if (!result.ok) {
        const body = await result.json().catch(() => ({}))
        throw new Error(typeof body.detail === "string" ? body.detail : "Nuk u hap biseda zanore.")
      }
      await pc.setRemoteDescription({ type: "answer", sdp: await result.text() })
    } catch (err) {
      if (!active()) return
      stop()
      setError(err instanceof DOMException && err.name === "NotAllowedError"
        ? "Lejo mikrofonin në shfletues për të folur me Mirën."
        : err instanceof Error ? err.message : "Nuk u hap biseda zanore.")
    }
  }, [apiFetch, message, release, stop])

  const sendText = React.useCallback((text: string) => {
    const dc = channel.current
    if (!text.trim() || dc?.readyState !== "open") return false
    const id = `msg_${crypto.randomUUID().replace(/-/g, "").slice(0, 24)}`
    message(id, "user", text.trim())
    dc.send(JSON.stringify({ type: "response.cancel" }))
    dc.send(JSON.stringify({ type: "conversation.item.create", item: { id, type: "message", role: "user", content: [{ type: "input_text", text: text.trim() }] } }))
    dc.send(JSON.stringify({ type: "response.create" }))
    setPhase("thinking")
    return true
  }, [message])

  const toggleMute = React.useCallback(() => {
    const tracks = microphone.current?.getAudioTracks() || []
    if (!tracks.length) return
    const next = tracks[0].enabled
    tracks.forEach(track => { track.enabled = !next })
    setMuted(next)
  }, [])

  const resumeAudio = React.useCallback(async () => {
    try {
      await audioRef.current?.play()
      setAudioBlocked(false)
      setError("")
    } catch { setError("Zëri është bllokuar nga shfletuesi. Lejo audion dhe shtyp Start.") }
  }, [])

  return { phase, messages, error, muted, audioBlocked, audioRef, start, stop, sendText, toggleMute, resumeAudio }
}
