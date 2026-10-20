"use client"

import * as React from "react"
import Link from "next/link"
import { useAuth } from "@/lib/auth"
import { RecordingCapture, type CaptureInfo, type CaptureState } from "@/lib/recording-capture"
import { IndexedRecordingOutbox, PAUSE_PENDING_BYTES, RecordingUploader, recordingJson, type RecordingManifest } from "@/lib/recording-outbox"
import { recordingTime } from "@/lib/recording-types"
import { Button } from "@/components/ui/button"

type View = {
  state: CaptureState; info: CaptureInfo; inputs: { microphone: string; system: string }; seconds: number
  manifest: RecordingManifest | null; recoveries: RecordingManifest[]; error: string | null
  busy: boolean; saving: boolean; savedId: string | null; backpressure: boolean; available: boolean
}
type RecorderContextValue = View & {
  prepare: (device: string | false, source: string) => Promise<void>
  start: (title: string, meetingId: string, description: string) => Promise<void>
  cancel: () => void; stop: () => void; pause: () => void; resume: () => void
  toggle: (input: "microphone" | "system") => void
  retry: (id?: string, partial?: boolean) => Promise<void>; discard: (id: string) => Promise<void>
}
const RecorderContext = React.createContext<RecorderContextValue | null>(null)
const initial: View = { state: "idle", info: { source: "unknown", microphone: false, system: false, mime: "" }, inputs: { microphone: "unavailable", system: "unavailable" }, seconds: 0, manifest: null, recoveries: [], error: null, busy: false, saving: false, savedId: null, backpressure: false, available: false }

export function RecorderProvider({ children }: { children: React.ReactNode }) {
  const { user, apiFetch } = useAuth()
  const api = React.useRef(apiFetch)
  api.current = apiFetch
  const [view, setView] = React.useState<View>(initial)
  const runtime = React.useRef<{
    capture: RecordingCapture; outbox: IndexedRecordingOutbox; uploader?: RecordingUploader; id?: string
    tail: Promise<void>; stagingBytes: number; fatal?: string; starting: boolean; finishing: boolean; lockRelease?: () => void
  } | null>(null)
  const refresh = React.useCallback(async () => {
    const r = runtime.current
    if (!r || !user) return
    try {
      const [manifest, all] = await Promise.all([r.id ? r.outbox.get(r.id).catch(() => null) : null, r.outbox.list(user.id)])
      if (runtime.current !== r) return
      setView(v => ({ ...v, manifest, recoveries: all.filter(m => m.id !== r.id) }))
    } catch (error) { setView(v => ({ ...v, error: String(error), available: false })) }
  }, [user])
  const finish = React.useRef<() => Promise<void>>(async () => {})
  finish.current = async () => {
    const r = runtime.current
    if (!r?.id || r.finishing) return
    r.finishing = true
    setView(v => ({ ...v, saving: true, error: r.fatal || null }))
    try {
      await r.tail
      await r.outbox.stop(r.id, r.fatal)
      if (r.fatal) throw new Error(r.fatal)
      await r.uploader!.complete()
      const savedId = r.id
      setView(v => ({ ...v, savedId, manifest: null, error: null }))
      r.id = undefined
    } catch (error) {
      setView(v => ({ ...v, error: error instanceof Error ? error.message : String(error) }))
    } finally {
      r.finishing = false
      r.lockRelease?.(); r.lockRelease = undefined
      setView(v => ({ ...v, saving: false }))
      await refresh()
    }
  }

  React.useEffect(() => {
    if (!user) return
    let disposed = false
    const outbox = new IndexedRecordingOutbox()
    const r: NonNullable<typeof runtime.current> = {
      outbox, tail: Promise.resolve(), stagingBytes: 0, starting: false, finishing: false,
      capture: new RecordingCapture({
        change: () => {
          if (disposed) return
          if (r.capture.state === "idle" && !r.id) { r.lockRelease?.(); r.lockRelease = undefined }
          setView(v => ({ ...v, state: r.capture.state, info: { ...r.capture.info }, inputs: r.capture.inputStatus, seconds: r.capture.seconds }))
        },
        error: error => {
          if (r.id) r.fatal = error.message
          if (!disposed) setView(v => ({ ...v, error: error.message }))
        },
        stopped: () => { if (r.id) void finish.current() },
        chunk: blob => {
          if (r.fatal) return
          // Reserve synchronously, before the IndexedDB write can stall. Even
          // a blocked disk must not grow an unbounded promise/Blob RAM queue.
          if (blob.size > 32 * 1024 * 1024 || r.stagingBytes + blob.size > 64 * 1024 * 1024) {
            r.fatal = "Fragmenti tejkaloi kufirin lokal. Regjistrimi nuk u ruajt plotësisht."
            if (!disposed) setView(v => ({ ...v, error: r.fatal! }))
            void r.capture.stop()
            return
          }
          r.stagingBytes += blob.size
          if (r.stagingBytes >= 16 * 1024 * 1024) {
            r.capture.pause()
            if (!disposed) setView(v => ({ ...v, backpressure: true }))
          }
          r.tail = r.tail.then(async () => {
            if (!r.id || r.fatal) return
            await outbox.append(r.id, blob)
            const manifest = await outbox.get(r.id)
            if (manifest.bytes - manifest.uploadedBytes >= PAUSE_PENDING_BYTES || manifest.count - manifest.acknowledged >= 12) {
              r.capture.pause()
              if (!disposed) setView(v => ({ ...v, backpressure: true }))
            }
            await refresh()
            void r.uploader!.pump().catch(error => {
              r.capture.pause()
              if (!disposed) setView(v => ({ ...v, backpressure: true, error: error.message }))
            })
          }).catch(async error => {
            r.fatal = `Ruajtja lokale dështoi: ${error instanceof Error ? error.message : String(error)}`
            if (!disposed) setView(v => ({ ...v, error: r.fatal! }))
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
    const pageHide = () => { if (["recording", "paused"].includes(r.capture.state)) void r.capture.stop(); else r.capture.cancel() }
    window.addEventListener("beforeunload", beforeUnload)
    window.addEventListener("pagehide", pageHide)
    return () => {
      disposed = true
      clearInterval(timer)
      window.removeEventListener("beforeunload", beforeUnload)
      window.removeEventListener("pagehide", pageHide)
      r.capture.cancel()
      r.lockRelease?.()
      if (runtime.current === r) runtime.current = null
    }
  // A refresh of the bearer token must not tear down capture.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id])

  const prepare = async (device: string | false, source: string) => {
    const r = runtime.current
    if (!r || r.starting || r.id || r.finishing) return
    setView(v => ({ ...v, error: null, savedId: null, backpressure: false }))
    r.starting = true
    try {
      if (!navigator.locks) throw new Error("Ky shfletues nuk mbështet bllokimin e sigurt të sesionit. Përdorni Chrome ose Edge.")
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
  }
  const start = async (title: string, meetingId: string, description: string) => {
    const r = runtime.current
    if (!r || !user || r.starting || r.id || r.capture.state !== "prepared") return
    r.starting = true
    setView(v => ({ ...v, busy: true, error: null }))
    try {
      const session = await recordingJson(await api.current("/meeting-recordings", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
          title, description: description || null, meeting_id: meetingId || null, capture_source_type: r.capture.info.source,
          mime_type: r.capture.info.mime.split(";")[0], has_microphone_audio: r.capture.info.microphone,
          has_system_audio: r.capture.info.system, consent_acknowledged: true,
        }), signal: AbortSignal.timeout(30_000),
      }))
      r.id = session.id
      r.fatal = undefined
      await r.outbox.create({ id: session.id, userId: user.id, title, count: 0, acknowledged: 0, bytes: 0, uploadedBytes: 0, stopped: false })
      r.uploader = new RecordingUploader(session.id, r.outbox, (...args) => api.current(...args), () => { void refresh() })
      await r.capture.start()
      await refresh()
    } catch (error) {
      r.fatal = error instanceof Error ? error.message : String(error)
      r.capture.cancel()
      if (r.id) {
        await r.outbox.stop(r.id, r.fatal).catch(() => {})
        await api.current(`/meeting-recordings/${r.id}/fail`, { method: "POST" }).catch(() => {})
      }
      r.lockRelease?.(); r.lockRelease = undefined
      setView(v => ({ ...v, error: r.fatal! }))
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
      try { await r.uploader!.pump(); setView(v => ({ ...v, error: null })); await refresh() }
      catch (error) { setView(v => ({ ...v, error: String(error) })) }
      return
    }
    r.finishing = true
    setView(v => ({ ...v, saving: true, error: null }))
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
        if (!partial) throw new Error("Regjistrimi u ndërpre. Konfirmoni rikuperimin e pjesës së disponueshme.")
        await r.outbox.stop(target, undefined, true)
      }
      const uploader = new RecordingUploader(target, r.outbox, (...args) => api.current(...args), () => { void refresh() })
      await uploader.complete()
      if (r.id === target) r.id = undefined
      setView(v => ({ ...v, savedId: target, error: null }))
    } catch (error) { setView(v => ({ ...v, error: error instanceof Error ? error.message : String(error) })) }
    finally { releaseRecoveryLock?.(); r.finishing = false; setView(v => ({ ...v, saving: false })); await refresh() }
  }
  const discard = async (id: string) => {
    const r = runtime.current
    if (!r || r.finishing || r.starting || ["recording", "paused", "stopping"].includes(r.capture.state)) return
    try {
      await navigator.locks.request("primeflow-screen-recorder", { ifAvailable: true }, async lock => {
        if (!lock) throw new Error("Një skedë tjetër ka një regjistrim aktiv.")
        const response = await api.current(`/meeting-recordings/${id}/fail`, { method: "POST" })
        if (!response.ok) throw new Error("Serveri nuk konfirmoi mbylljen e sesionit.")
        await r.outbox.remove(id)
        if (r.id === id) r.id = undefined
        setView(v => ({ ...v, error: null }))
        await refresh()
      })
    } catch (error) { setView(v => ({ ...v, error: String(error) })) }
  }
  const value: RecorderContextValue = { ...view, prepare, start, cancel, retry, discard,
    stop: () => { void runtime.current?.capture.stop() }, pause: () => runtime.current?.capture.pause(),
    resume: () => { if (!view.error && !view.saving && (!view.manifest || view.manifest.bytes - view.manifest.uploadedBytes < PAUSE_PENDING_BYTES)) { runtime.current?.capture.resume(); setView(v => ({ ...v, backpressure: false })) } },
    toggle: input => runtime.current?.capture.toggle(input),
  }
  const active = ["recording", "paused", "stopping", "prepared", "selecting"].includes(view.state) || view.saving
  return <RecorderContext.Provider value={value}>
    {active && <div role="status" aria-live="polite" className="sticky top-0 z-50 flex flex-wrap items-center gap-3 border-b border-red-300 bg-red-50 px-4 py-2 text-sm text-red-950 dark:bg-red-950 dark:text-red-100">
      <span className="h-3 w-3 rounded-full bg-red-600 motion-safe:animate-pulse" />
      <Link href="/meeting-recordings" className="font-semibold underline">{view.state === "recording" ? "Duke regjistruar" : view.state === "paused" ? "Regjistrimi në pauzë" : view.saving ? "Duke ruajtur regjistrimin" : "Ndarja e ekranit"}</Link>
      <span className="tabular-nums">{recordingTime(view.seconds)}</span>
      {["recording", "paused"].includes(view.state) && <Button size="sm" variant="destructive" onClick={value.stop}>Ndalo regjistrimin</Button>}
    </div>}
    {children}
  </RecorderContext.Provider>
}
export function useRecorder() { const context = React.useContext(RecorderContext); if (!context) throw new Error("RecorderProvider missing"); return context }
