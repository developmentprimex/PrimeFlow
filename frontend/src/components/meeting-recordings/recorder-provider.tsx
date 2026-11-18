"use client"

import * as React from "react"
import Link from "next/link"
import { useAuth } from "@/lib/auth"
import { RecordingCapture, type CaptureInfo, type CaptureState } from "@/lib/recording-capture"
import { IndexedRecordingOutbox, MAX_CHUNK_BYTES, RecordingUploader, RetryableRecordingUploadError, recordingJson, type RecordingManifest } from "@/lib/recording-outbox"
import { recordingTime } from "@/lib/recording-types"
import { Button } from "@/components/ui/button"

type View = {
  screenSharing: boolean; selectingScreen: boolean; sharingError?: string | null
  state: CaptureState; info: CaptureInfo; inputs: { microphone: string; system: string }; seconds: number
  manifest: RecordingManifest | null; recoveries: RecordingManifest[]; error: string | null
  busy: boolean; saving: boolean; savedId: string | null; savedPartial: boolean; available: boolean
  uploadWaiting: boolean; uploadError: string | null; interruption: string | null
}
type RecorderContextValue = View & {
  shareScreen: (source?: string) => Promise<void>
  prepare: (device: string | false, source: string, recording: { title: string; meetingId: string; description: string; projectId?: string }) => Promise<void>
  start: (title: string, meetingId: string, description: string, projectId?: string) => Promise<void>
  cancel: () => void; stop: () => void; pause: () => void; resume: () => void
  toggle: (input: "microphone" | "system") => void
  retry: (id?: string, partial?: boolean) => Promise<void>; discard: (id: string) => Promise<void>
}
const RecorderContext = React.createContext<RecorderContextValue | null>(null)
const initial: View = { screenSharing: false, selectingScreen: false, state: "idle", info: { source: "unknown", microphone: false, system: false, mime: "" }, inputs: { microphone: "unavailable", system: "unavailable" }, seconds: 0, manifest: null, recoveries: [], error: null, busy: false, saving: false, savedId: null, savedPartial: false, available: false, uploadWaiting: false, uploadError: null, interruption: null }

type Runtime = {
  capture: RecordingCapture; outbox: IndexedRecordingOutbox; uploader?: RecordingUploader; id?: string
  tail: Promise<void>; stagingBytes: number; starting: boolean; finishing: boolean; lockRelease?: () => void
  interruption?: string; dropChunks?: boolean; writeFailed?: boolean
  pumping?: boolean; pumpRequested?: boolean; uploadBlocked?: boolean; retryTimer?: number
}

function clearUploadRetry(r: Runtime) {
  if (r.retryTimer !== undefined) window.clearTimeout(r.retryTimer)
  r.retryTimer = undefined
}

export function RecorderProvider({ children }: { children: React.ReactNode }) {
  const { user, apiFetch } = useAuth()
  const api = React.useRef(apiFetch)
  api.current = apiFetch
  const [view, setView] = React.useState<View>(initial)
  const runtime = React.useRef<Runtime | null>(null)
  const refresh = React.useCallback(async () => {
    const r = runtime.current
    if (!r || !user) return
    try {
      const id = r.id
      const all = await r.outbox.list(user.id)
      if (runtime.current !== r || r.id !== id) return
      setView(v => ({ ...v, manifest: all.find(m => m.id === id) || null, recoveries: all.filter(m => m.id !== id) }))
    } catch (error) { setView(v => ({ ...v, error: String(error), available: false })) }
  }, [user])
  const finish = React.useRef<() => Promise<void>>(async () => {})
  const pump = React.useRef<() => Promise<void>>(async () => {})
  const retryPending = (r: Runtime) => {
    if (runtime.current !== r || !r.id || r.retryTimer !== undefined) return
    setView(v => ({ ...v, uploadWaiting: true, uploadError: null }))
    r.retryTimer = window.setTimeout(() => {
      r.retryTimer = undefined
      if (runtime.current !== r) return
      if (navigator.onLine === false) { retryPending(r); return }
      if (r.capture.state === "stopped") void finish.current()
      else void pump.current()
    }, 5000)
  }
  pump.current = async () => {
    const r = runtime.current
    if (!r?.uploader || !r.id || r.finishing || r.uploadBlocked || r.retryTimer !== undefined) return
    if (r.pumping) { r.pumpRequested = true; return }
    if (navigator.onLine === false) { retryPending(r); return }
    r.pumping = true
    try {
      await r.uploader.pump()
      if (runtime.current === r && !r.finishing) setView(v => ({ ...v, uploadWaiting: false, uploadError: null }))
    } catch (error) {
      if (runtime.current !== r || r.finishing) return
      if (error instanceof RetryableRecordingUploadError) retryPending(r)
      else {
        r.uploadBlocked = true
        setView(v => ({ ...v, uploadWaiting: false, uploadError: error instanceof Error ? error.message : String(error) }))
      }
    } finally {
      r.pumping = false
      if (r.pumpRequested && runtime.current === r) {
        r.pumpRequested = false
        void pump.current()
      }
    }
  }
  finish.current = async () => {
    const r = runtime.current
    if (!r?.id || !r.uploader || r.finishing) return
    clearUploadRetry(r)
    r.finishing = true
    const id = r.id
    setView(v => ({ ...v, saving: true, uploadWaiting: false, uploadError: null }))
    try {
      await r.tail
      await r.outbox.stop(id, undefined, Boolean(r.interruption))
      if (runtime.current !== r) return
      if (navigator.onLine === false) throw new RetryableRecordingUploadError("Lidhja me serverin është në pritje.")
      const saved = await r.uploader.complete()
      r.id = undefined
      r.uploader = undefined
      if (runtime.current === r) setView(v => ({ ...v, savedId: id, savedPartial: !!saved.is_partial, manifest: null, uploadError: null }))
    } catch (error) {
      if (runtime.current !== r) return
      if (error instanceof RetryableRecordingUploadError) retryPending(r)
      else setView(v => ({ ...v, uploadError: error instanceof Error ? error.message : String(error) }))
    } finally {
      r.finishing = false
      if (r.retryTimer === undefined) { r.lockRelease?.(); r.lockRelease = undefined }
      if (runtime.current === r) {
        setView(v => ({ ...v, saving: false }))
        await refresh()
      }
    }
  }

  React.useEffect(() => {
    if (!user) return
    let disposed = false
    const outbox = new IndexedRecordingOutbox()
    const interrupt = (message: string) => {
      r.interruption ||= message
      if (!disposed) setView(v => ({ ...v, interruption: r.interruption! }))
    }
    const r: Runtime = {
      outbox, tail: Promise.resolve(), stagingBytes: 0, starting: false, finishing: false,
      capture: new RecordingCapture({
        change: () => {
          if (disposed) return
          if (r.capture.state === "idle" && !r.id) { r.lockRelease?.(); r.lockRelease = undefined }
          setView(v => ({ ...v, state: r.capture.state, screenSharing: r.capture.screenSharing, selectingScreen: r.capture.selectingScreen, info: { ...r.capture.info }, inputs: r.capture.inputStatus, seconds: r.capture.seconds }))
        },
        error: error => {
          if (r.id) interrupt(error.message)
          else if (!disposed) setView(v => ({ ...v, error: error.message }))
        },
        stopped: () => { if (r.id && runtime.current === r) void finish.current() },
        chunk: blob => {
          if (r.writeFailed || r.dropChunks) return
          // Reserve synchronously, before the IndexedDB write can stall. Even
          // a blocked disk must not grow an unbounded promise/Blob RAM queue.
          if (blob.size > MAX_CHUNK_BYTES || r.stagingBytes + blob.size > 64 * 1024 * 1024) {
            r.dropChunks = true
            interrupt("Regjistrimi u ndërpre sepse u arrit kufiri i ruajtjes lokale.")
            void r.capture.stop()
            return
          }
          r.stagingBytes += blob.size
          r.tail = r.tail.then(async () => {
            if (!r.id || r.writeFailed) return
            await outbox.append(r.id, blob)
            if (disposed) return
            void refresh()
            void pump.current()
          }).catch(error => {
            r.writeFailed = true
            interrupt(`Regjistrimi u ndërpre gjatë ruajtjes lokale. ${error instanceof Error ? error.message : String(error)}`)
            void r.capture.stop()
          }).finally(() => { r.stagingBytes -= blob.size })
        },
      }),
    }
    runtime.current = r
    void outbox.list(user.id).then(recoveries => { if (!disposed) setView(v => ({ ...v, recoveries, available: true })) })
      .catch(() => { if (!disposed) setView(v => ({ ...v, error: "IndexedDB nuk është i disponueshëm. Lejoni ruajtjen lokale përpara regjistrimit." })) })
    const timer = setInterval(() => { if (!disposed && r.capture.state === "recording") setView(v => ({ ...v, seconds: r.capture.seconds })) }, 500)
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (r.id || ["prepared", "recording", "paused", "stopping", "selecting"].includes(r.capture.state)) { event.preventDefault(); event.returnValue = "" }
    }
    const pageHide = () => {
      if (["recording", "paused"].includes(r.capture.state)) {
        interrupt("Shfletuesi e ndërpreu regjistrimin.")
        void r.capture.stop()
      } else if (["prepared", "selecting"].includes(r.capture.state)) r.capture.cancel()
    }
    const online = () => {
      if (!r.id || r.retryTimer === undefined) return
      clearUploadRetry(r)
      if (r.capture.state === "stopped") void finish.current()
      else void pump.current()
    }
    window.addEventListener("beforeunload", beforeUnload)
    window.addEventListener("pagehide", pageHide)
    window.addEventListener("online", online)
    return () => {
      disposed = true
      clearInterval(timer)
      window.removeEventListener("beforeunload", beforeUnload)
      window.removeEventListener("pagehide", pageHide)
      window.removeEventListener("online", online)
      clearUploadRetry(r)
      r.capture.cancel()
      r.lockRelease?.()
      if (runtime.current === r) runtime.current = null
    }
  // A refresh of the bearer token must not tear down capture.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id])

  const prepare = async (device: string | false, source: string, recording: { title: string; meetingId: string; description: string; projectId?: string }) => {
    const r = runtime.current
    if (!r || r.starting || r.id || r.finishing) return
    setView(v => ({ ...v, error: null, savedId: null, savedPartial: false, uploadWaiting: false, uploadError: null, interruption: null }))
    r.starting = true
    try {
      if (!navigator.locks) throw new Error("Ky shfletues nuk mbështet sesionin e regjistrimit. Përdorni një version të përditësuar të Safari, Chrome ose Edge.")
      await new Promise<void>((resolve, reject) => {
        void navigator.locks.request("primeflow-screen-recorder", { ifAvailable: true }, async lock => {
          if (!lock) { reject(new Error("Një skedë tjetër ka një regjistrim aktiv.")); return }
          const held = new Promise<void>(release => { r.lockRelease = release })
          try { await r.capture.prepare(device, source); resolve() } catch (error) { reject(error) }
          if (r.capture.state !== "prepared") { r.lockRelease?.(); r.lockRelease = undefined }
          await held
        }).catch(reject)
      })
    } catch (error) { setView(v => ({ ...v, error: error instanceof Error ? error.message : String(error) })) }
    finally { r.starting = false }
    if (runtime.current === r && r.capture.state === "prepared" && (r.capture.info.system || r.capture.info.source === "microphone")) {
      await start(recording.title, recording.meetingId, recording.description, recording.projectId)
    }
  }
  const start = async (title: string, meetingId: string, description: string, projectId?: string) => {
    const r = runtime.current
    if (!r || !user || r.starting || r.id || r.capture.state !== "prepared") return
    r.starting = true
    setView(v => ({ ...v, busy: true, error: null }))
    try {
      const session = await recordingJson(await api.current("/meeting-recordings", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
          title, description: description || null, meeting_id: meetingId || null, project_id: projectId || null, capture_source_type: r.capture.info.source,
          mime_type: r.capture.info.mime.split(";")[0], has_microphone_audio: r.capture.info.microphone,
          has_system_audio: r.capture.info.system, consent_acknowledged: true,
        }), signal: AbortSignal.timeout(30_000),
      }))
      r.id = session.id
      r.interruption = undefined
      r.writeFailed = r.dropChunks = r.uploadBlocked = false
      await r.outbox.create({ id: session.id, userId: user.id, title, count: 0, acknowledged: 0, bytes: 0, uploadedBytes: 0, stopped: false })
      r.uploader = new RecordingUploader(session.id, r.outbox, (...args) => api.current(...args), () => { void refresh() })
      await r.capture.start()
      await refresh()
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      r.capture.cancel()
      if (r.id) {
        await r.outbox.stop(r.id, message).catch(() => {})
        await api.current(`/meeting-recordings/${r.id}/fail`, { method: "POST" }).catch(() => {})
        r.id = undefined
        r.uploader = undefined
      }
      r.lockRelease?.(); r.lockRelease = undefined
      setView(v => ({ ...v, error: message }))
      await refresh()
    } finally { r.starting = false; setView(v => ({ ...v, busy: false })) }
  }
  const cancel = () => { const r = runtime.current; if (!r || r.starting) return; r.capture.cancel(); r.lockRelease?.(); r.lockRelease = undefined }
  const retry = async (id?: string, partial = false) => {
    const r = runtime.current
    if (!r || r.finishing || r.starting) return
    const target = id || r.id
    if (!target) return
    if (target === r.id && ["recording", "paused"].includes(r.capture.state)) {
      r.uploadBlocked = false
      clearUploadRetry(r)
      await pump.current()
      return
    }
    if (target === r.id && r.lockRelease) {
      await finish.current()
      return
    }
    r.finishing = true
    setView(v => ({ ...v, saving: true, uploadError: null }))
    let releaseRecoveryLock: (() => void) | undefined
    try {
      await new Promise<void>((resolve, reject) => {
        void navigator.locks.request("primeflow-screen-recorder", { ifAvailable: true }, async lock => {
          if (!lock) { reject(new Error("Një skedë tjetër po regjistron ose rikuperon. Ndaloje atje përpara rikuperimit.")); return }
          const held = new Promise<void>(release => { releaseRecoveryLock = release })
          resolve()
          await held
        }).catch(reject)
      })
      const m = await r.outbox.get(target)
      if (!m.stopped) {
        if (!partial && !(target === r.id && r.interruption)) throw new Error("Regjistrimi u ndërpre. Konfirmoni rikuperimin e pjesës së disponueshme.")
        await r.outbox.stop(target, undefined, true)
      }
      const uploader = new RecordingUploader(target, r.outbox, (...args) => api.current(...args), () => { void refresh() })
      const saved = await uploader.complete()
      if (r.id === target) { r.id = undefined; r.uploader = undefined }
      setView(v => ({ ...v, savedId: target, savedPartial: !!saved.is_partial, uploadError: null }))
    } catch (error) { setView(v => ({ ...v, uploadError: error instanceof Error ? error.message : String(error) })) }
    finally { releaseRecoveryLock?.(); r.finishing = false; setView(v => ({ ...v, saving: false })); await refresh() }
  }
  const discard = async (id: string) => {
    const r = runtime.current
    if (!r || r.finishing || r.starting || ["recording", "paused", "stopping"].includes(r.capture.state)) return
    r.finishing = true
    setView(v => ({ ...v, error: null, uploadError: null }))
    const ownsSession = r.id === id && !!r.lockRelease
    const retryWasPending = ownsSession && r.retryTimer !== undefined
    if (ownsSession) clearUploadRetry(r)
    const discardSession = async () => {
      const response = await api.current(`/meeting-recordings/${id}/fail`, { method: "POST" })
      if (!response.ok) throw new Error("Serveri nuk konfirmoi mbylljen e sesionit.")
      await r.outbox.remove(id)
      if (r.id === id) {
        r.id = undefined
        r.uploader = undefined
        r.lockRelease?.(); r.lockRelease = undefined
      }
      setView(v => ({ ...v, uploadWaiting: false, uploadError: null, interruption: null }))
      await refresh()
    }
    try {
      if (ownsSession) await discardSession()
      else await navigator.locks.request("primeflow-screen-recorder", { ifAvailable: true }, async lock => {
        if (!lock) throw new Error("Një skedë tjetër ka një regjistrim aktiv.")
        await discardSession()
      })
    } catch (error) {
      if (retryWasPending) retryPending(r)
      setView(v => ({ ...v, uploadError: error instanceof Error ? error.message : String(error) }))
    } finally { r.finishing = false }
  }
  const value: RecorderContextValue = { ...view, prepare, start, cancel, retry, discard,
    shareScreen: async source => {
      setView(v => ({ ...v, sharingError: null }))
      try { await runtime.current?.capture.shareScreen(source) }
      catch (error) { setView(v => ({ ...v, sharingError: error instanceof Error ? error.message : String(error) })) }
    },
    stop: () => { void runtime.current?.capture.stop() }, pause: () => runtime.current?.capture.pause(),
    resume: () => runtime.current?.capture.resume(),
    toggle: input => runtime.current?.capture.toggle(input),
  }
  const active = ["recording", "paused", "stopping", "prepared", "selecting"].includes(view.state) || view.saving || view.uploadWaiting || (!!view.interruption && !view.savedId)
  const capturing = view.state === "recording" || view.state === "paused"
  const audioOnly = view.info.source === "microphone"
  return <RecorderContext.Provider value={value}>
    {active && <div role="status" aria-live="polite" className="sticky top-0 z-50 flex flex-wrap items-center gap-3 border-b border-red-300 bg-red-50 px-4 py-2 text-sm text-red-950 dark:bg-red-950 dark:text-red-100">
      <span className="h-3 w-3 rounded-full bg-red-600 motion-safe:animate-pulse" />
      <Link href="/meeting-recordings" className="font-semibold underline">{view.state === "recording" ? audioOnly ? "Duke regjistruar audio" : "Duke regjistruar" : view.state === "paused" ? "Regjistrimi në pauzë" : view.saving || view.state === "stopping" ? "Duke ruajtur regjistrimin" : view.interruption ? "Regjistrimi u ndërpre" : view.uploadWaiting ? "Ngarkimi në pritje" : "Duke përgatitur regjistrimin"}</Link>
      <span className="tabular-nums">{recordingTime(view.seconds)}</span>
      {view.sharingError && <span role="alert">Ndarja e ekranit dështoi: {view.sharingError}</span>}
      {view.interruption && <span role="alert">{view.interruption}</span>}
      {capturing && view.uploadWaiting && <span>Ngarkimi në pritje</span>}
      {capturing && !audioOnly && !view.screenSharing && <>
        <span>{view.state === "paused" ? "Ekrani nuk po ndahet. Regjistrimi është në pauzë." : "Regjistrimi vazhdon — ekrani nuk po ndahet."}</span>
        {view.inputs.microphone !== "on" && <span role="alert">Mikrofoni nuk është aktiv; biseda nuk po regjistrohet.</span>}
        <Button size="sm" variant="outline" disabled={view.selectingScreen} onClick={() => void value.shareScreen()}>Ndaj ekranin përsëri</Button>
      </>}
      {capturing && audioOnly && view.inputs.microphone !== "on" && <span role="alert">Mikrofoni nuk është aktiv; biseda nuk po regjistrohet.</span>}
      {capturing && <Button size="sm" variant="destructive" onClick={value.stop}>Ndalo regjistrimin</Button>}
    </div>}
    {children}
  </RecorderContext.Provider>
}
export function useRecorder() { const context = React.useContext(RecorderContext); if (!context) throw new Error("RecorderProvider missing"); return context }
