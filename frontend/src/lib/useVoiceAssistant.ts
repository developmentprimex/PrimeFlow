"use client"

import * as React from "react"
import { useAuth } from "@/lib/auth"

export type VoiceMessage = { id: string; role: "user" | "assistant" | "activity"; text: string }
export type VoiceTask = { id: string; title: string; status: string; one_h_report_slot?: string | null }
type Phase = "idle" | "connecting" | "listening" | "thinking" | "speaking" | "working"
type ToolCall = { type: string; call_id: string; name: string; arguments: string }
type RealtimeEvent = {
  type: string; item_id?: string; delta?: string; transcript?: string; text?: string;
  error?: { message?: string; code?: string };
  response?: { status?: string; output?: ToolCall[]; status_details?: { error?: { message?: string } } };
}

const allowedTools = new Set(["search_tasks", "list_my_schedule", "get_task", "set_task_status", "set_task_points", "set_checklist_item"])
const labels: Record<string, string> = {
  search_tasks: "Po kërkoj detyrat…", list_my_schedule: "Po shoh planifikimin tënd…", get_task: "Po lexoj detyrën…",
  set_task_status: "Po ndryshoj statusin…", set_task_points: "Po përditësoj pikat…", set_checklist_item: "Po përditësoj checklistën…",
}

export function useVoiceAssistant() {
  const { apiFetch } = useAuth()
  const [phase, setPhase] = React.useState<Phase>("idle")
  const [messages, setMessages] = React.useState<VoiceMessage[]>([])
  const [tasks, setTasks] = React.useState<VoiceTask[]>([])
  const [error, setError] = React.useState("")
  const [muted, setMuted] = React.useState(false)
  const [activity, setActivity] = React.useState("")
  const [audioBlocked, setAudioBlocked] = React.useState(false)
  const audioRef = React.useRef<HTMLAudioElement>(null)
  const connection = React.useRef<RTCPeerConnection | null>(null)
  const channel = React.useRef<RTCDataChannel | null>(null)
  const microphone = React.useRef<MediaStream | null>(null)
  const generation = React.useRef(0)
  const timeout = React.useRef<ReturnType<typeof setTimeout> | null>(null)
  const deadline = React.useRef<ReturnType<typeof setTimeout> | null>(null)
  const request = React.useRef<AbortController | null>(null)

  const message = React.useCallback((id: string, role: VoiceMessage["role"], text: string, append = false) => {
    setMessages(previous => {
      const existing = previous.find(m => m.id === id)
      if (existing) return previous.map(m => m.id === id ? { ...m, text: append ? m.text + text : text } : m)
      return [...previous.slice(-149), { id, role, text }]
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
    setActivity("")
  }, [release])

  React.useEffect(() => () => release(), [release])

  const start = React.useCallback(async () => {
    if (connection.current) return
    release()
    const current = generation.current
    const active = () => generation.current === current
    setError("")
    setMessages([])
    setTasks([])
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
          if (active()) { setAudioBlocked(true); setError("Shtyp Play për të dëgjuar Mirën.") }
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
        for (const call of calls) {
          if (!active()) return
          setPhase("working")
          setActivity(labels[call.name] || "Po punoj…")
          let output: Record<string, unknown>
          try {
            if (!allowedTools.has(call.name)) throw new Error("Veprimi nuk mbështetet.")
            const args = JSON.parse(call.arguments)
            const result = await apiFetch(`/voice-assistant/tools/${call.name}`, {
              method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(args),
            })
            const body = await result.json().catch(() => ({}))
            output = result.ok ? body : { success: false, error: typeof body.detail === "string" ? body.detail : "Veprimi u refuzua. Lexo gjendjen para riprovimit." }
          } catch {
            output = { success: false, error: "Rezultati i veprimit nuk u konfirmua. Lexo gjendjen përpara se të riprovosh." }
          }
          // A started write may finish after the microphone is stopped. Always
          // refresh its result; never start another tool from an ended session.
          if (output.changed) window.dispatchEvent(new Event("primex:tasks-changed"))
          if (!active()) return
          const found = Array.isArray(output.tasks) ? output.tasks : output.task ? [output.task] : null
          if (found) setTasks(found.filter((t): t is VoiceTask => !!t && typeof t === "object" && typeof t.id === "string" && typeof t.title === "string"))
          if (output.changed) {
            const applied = Array.isArray(output.applied) ? output.applied.join(" · ") : "Ndryshimi u ruajt"
            message(`tool-${call.call_id}`, "activity", applied + (output.success === false ? " · Veprimi u përfundua pjesërisht." : ""))
          }
          send({ type: "conversation.item.create", item: { type: "function_call_output", call_id: call.call_id, output: JSON.stringify(output) } })
        }
        if (active()) { setActivity(""); setPhase("thinking"); respond() }
      }
      dc.onopen = () => {
        if (!active()) return
        if (timeout.current) clearTimeout(timeout.current)
        setPhase("listening")
        respond()
        deadline.current = setTimeout(() => {
          if (active()) { stop(); message(crypto.randomUUID(), "activity", "Biseda u mbyll pas 10 minutash. Mund të nisësh një bisedë të re.") }
        }, 10 * 60 * 1000)
      }
      dc.onclose = () => {
        if (active()) { stop(); setError("Biseda u shkëput. Lidhe përsëri për të vazhduar.") }
      }
      dc.onmessage = ({ data }) => {
        if (!active()) return
        let event: RealtimeEvent
        try { event = JSON.parse(data) } catch { return }
        if (event.type === "input_audio_buffer.speech_started") setPhase("listening")
        if (event.type === "input_audio_buffer.speech_stopped") setPhase("thinking")
        if (event.type === "conversation.item.input_audio_transcription.completed" && event.transcript) {
          message(event.item_id || crypto.randomUUID(), "user", event.transcript)
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
        body: JSON.stringify({ sdp: offer.sdp }), signal: controller.signal,
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
    dc.send(JSON.stringify({ type: "response.cancel" }))
    dc.send(JSON.stringify({ type: "conversation.item.create", item: { type: "message", role: "user", content: [{ type: "input_text", text: text.trim() }] } }))
    dc.send(JSON.stringify({ type: "response.create" }))
    message(crypto.randomUUID(), "user", text.trim())
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

  return { phase, messages, tasks, error, muted, activity, audioBlocked, audioRef, start, stop, sendText, toggleMute }
}
