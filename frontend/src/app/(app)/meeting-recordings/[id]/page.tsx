"use client"

import * as React from "react"
import Link from "next/link"
import { useParams } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useAuth } from "@/lib/auth"
import { RecordingAnalysisPanel } from "@/components/meeting-recordings/analysis-panel"
import { recordingJson } from "@/lib/recording-outbox"
import { RECORDING_STATUS, recordingSize, recordingTime, type MeetingRecording } from "@/lib/recording-types"

export default function RecordingDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { apiFetch } = useAuth()
  const videoRef = React.useRef<HTMLVideoElement>(null)
  const [row, setRow] = React.useState<MeetingRecording | null>(null)
  const [authorized, setAuthorized] = React.useState(false)
  const [error, setError] = React.useState("")
  React.useEffect(() => {
    let active = true
    const authorize = async () => {
      try {
        const recording: MeetingRecording = await recordingJson(await apiFetch(`/meeting-recordings/${id}`, { cache: "no-store" }))
        if (!active) return
        setRow(recording)
        if (recording.media_available === false) {
          setAuthorized(false)
          throw new Error("Skedari i videos nuk është i arritshëm. Kontaktoni administratorin për rikthimin e tij.")
        }
        if (recording.status !== "READY") return
        const grant = await recordingJson(await apiFetch(`/meeting-recordings/${id}/playback`, { method: "POST" }))
        const response = await fetch(`/api/meeting-recordings/${id}/playback`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(grant) })
        if (!response.ok) throw new Error("Autorizimi i videos dështoi.")
        if (active) { setAuthorized(true); setError("") }
      } catch (e) { if (active) setError(e instanceof Error ? e.message : String(e)) }
    }
    void authorize()
    const timer = setInterval(() => { void authorize() }, 5 * 60_000)
    return () => { active = false; clearInterval(timer) }
  }, [id, apiFetch])
  return <div className="w-full min-w-0 space-y-4">
    <Link className="text-sm underline" href="/meeting-recordings">← Regjistrimet e takimeve</Link>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {!row && !error && <p role="status">Duke ngarkuar…</p>}
    {row && <Card><CardHeader><CardTitle>{row.title}</CardTitle></CardHeader><CardContent className="space-y-4">
      <p>{row.description}</p><p className="text-sm text-muted-foreground">{new Date(row.created_at).toLocaleString("sq-AL")} · {row.recorded_by_name} · {RECORDING_STATUS[row.status]}</p>
      {row.meeting_title && <p className="text-sm">Takimi: {row.meeting_title}</p>}
      {row.is_partial && <p role="alert" className="text-sm text-amber-700 dark:text-amber-300">Pjesë e rikuperuar nga një regjistrim i ndërprerë. Fundi i takimit mund të mungojë.</p>}
      <p className="text-sm">{recordingTime(row.duration_seconds)} · {recordingSize(row.size_bytes)} · {row.mime_type} · {row.video_width} × {row.video_height}</p>
      {authorized && row.status === "READY" && row.media_available !== false && <>
        <video ref={videoRef} key={id} className="aspect-video w-full rounded-md bg-black" src={`/api/meeting-recordings/${id}/stream`} controls preload="metadata" playsInline onError={() => setError("Videoja nuk mund të hapet. Rifreskoni faqen për të rinovuar autorizimin.")} />
        <Button asChild><a href={`/api/meeting-recordings/${id}/download`} download>Shkarko regjistrimin</a></Button>
      </>}
      {row.status !== "READY" && <p className="text-sm">{row.error_message || "Ngarkimi dhe verifikimi nuk kanë përfunduar. Hapni faqen e regjistrimeve për rikuperim."}</p>}
    </CardContent></Card>}
    {row?.status === "READY" && <RecordingAnalysisPanel key={id} recordingId={id} onSeek={authorized ? seconds => {
      const video = videoRef.current
      if (!video) return
      video.currentTime = Math.max(0, seconds - 0.25)
      video.scrollIntoView({ behavior: "smooth", block: "center" })
      void video.play().catch(() => setError("Shtyp luaj për të dëgjuar citimin."))
    } : undefined} />}
  </div>
}
