"use client"

import * as React from "react"
import Link from "next/link"
import { useParams } from "next/navigation"
import { ArrowLeft, ImagePlus, ListTodo } from "lucide-react"
import { toast } from "sonner"
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
  const [capturing, setCapturing] = React.useState(false)
  // Takimet: save the current video frame as a meeting note with the screenshot attached.
  const captureFrame = async () => {
    const video = videoRef.current
    if (!video || !row?.meeting_id || capturing) return
    setCapturing(true)
    try {
      const canvas = document.createElement("canvas")
      canvas.width = video.videoWidth || 1280
      canvas.height = video.videoHeight || 720
      canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height)
      const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, "image/png"))
      if (!blob) throw new Error("Screenshot-i nuk u krijua.")
      const seconds = Math.floor(video.currentTime || 0)
      const form = new FormData()
      form.append("file", new File([blob], `screenshot-${recordingTime(seconds).replaceAll(":", "-")}.png`, { type: "image/png" }))
      form.append("seconds", String(seconds))
      await recordingJson(await apiFetch(`/meeting-notes/recordings/${id}/screenshot`, { method: "POST", body: form }))
      toast.success(`Screenshot-i (${recordingTime(seconds)}) u ruajt te takimi.`)
    } catch (e) { toast.error(e instanceof Error ? e.message : String(e)) }
    finally { setCapturing(false) }
  }
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
    <div className="flex items-center">
      <Button asChild variant="outline" size="sm" className="gap-2">
        <Link href="/meeting-recordings"><ArrowLeft className="size-4" aria-hidden="true" />Regjistrimet e takimeve</Link>
      </Button>
    </div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {!row && !error && <p role="status">Duke ngarkuar…</p>}
    {row && <Card><CardHeader><CardTitle>{row.title}</CardTitle></CardHeader><CardContent className="space-y-4">
      <p>{row.description}</p><p className="text-sm text-muted-foreground">{new Date(row.created_at).toLocaleString("sq-AL")} · {row.recorded_by_name} · {RECORDING_STATUS[row.status]}</p>
      {row.project_id && <p className="text-sm">Projekti: <Link className="underline" href={`/projects/${row.project_id}`}>{row.project_title || row.project_id}</Link></p>}
      {!row.meeting_id && <LinkMeeting recording={row} onLinked={setRow} />}
      {row.meeting_id ? <p className="text-sm">Takimi: <Link className="font-medium underline" href={`/meetings/${row.meeting_id}?date=${new Date(row.recording_started_at).toLocaleDateString("sv-SE")}`}>{row.meeting_title || "Hap takimin"}</Link></p>
        : row.meeting_title && <p className="text-sm">Takimi: {row.meeting_title}</p>}
      {row.is_partial && <p role="alert" className="text-sm text-amber-700 dark:text-amber-300">Pjesë e rikuperuar nga një regjistrim i ndërprerë. Fundi i takimit mund të mungojë.</p>}
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-sm">{recordingTime(row.duration_seconds)} · {recordingSize(row.size_bytes)} · {row.mime_type} · {row.video_width} × {row.video_height}</p>
        {row.status === "READY" && <Button asChild className="shadow-sm">
          <a href="#recording-tasks"><ListTodo aria-hidden="true" />Shiko detyrat</a>
        </Button>}
      </div>
      {authorized && row.status === "READY" && row.media_available !== false && <>
        <video ref={videoRef} key={id} className="aspect-video w-full rounded-md bg-black" src={`/api/meeting-recordings/${id}/stream`} controls preload="metadata" playsInline
          onLoadedMetadata={event => { const t = Number(new URLSearchParams(window.location.search).get("t")); if (t > 0) event.currentTarget.currentTime = t }}
          onError={() => setError("Videoja nuk mund të hapet. Rifreskoni faqen për të rinovuar autorizimin.")} />
        <div className="flex flex-wrap items-center gap-2">
          <Button asChild><a href={`/api/meeting-recordings/${id}/download`} download>Shkarko regjistrimin</a></Button>
          {row.meeting_id ? <Button variant="outline" disabled={capturing} onClick={() => void captureFrame()}><ImagePlus aria-hidden="true" />{capturing ? "Duke ruajtur…" : "Screenshot nga videoja"}</Button>
            : <span className="text-sm text-muted-foreground">Lidhe regjistrimin me një takim për të ruajtur screenshots te takimi.</span>}
        </div>
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

/** Takimet: link a recording made without a meeting to the right meeting. */
function LinkMeeting({ recording, onLinked }: { recording: MeetingRecording; onLinked: (row: MeetingRecording) => void }) {
  const { apiFetch } = useAuth()
  const [meetings, setMeetings] = React.useState<{ id: string; title: string }[]>([])
  const [meetingId, setMeetingId] = React.useState("")
  const [saving, setSaving] = React.useState(false)
  React.useEffect(() => {
    let active = true
    void apiFetch("/meeting-notes/overview").then(async response => {
      if (!response.ok) return
      const rows = (await response.json()) as { meeting: { id: string; title: string } }[]
      if (active) setMeetings(rows.map(r => r.meeting).sort((a, b) => a.title.localeCompare(b.title, "sq")))
    }).catch(() => {})
    return () => { active = false }
  }, [apiFetch])
  const link = async () => {
    if (!meetingId) return
    setSaving(true)
    try {
      onLinked(await recordingJson(await apiFetch(`/meeting-recordings/${recording.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: recording.title, meeting_id: meetingId }),
      })))
      toast.success("Regjistrimi u lidh me takimin.")
    } catch (e) { toast.error(e instanceof Error ? e.message : String(e)) }
    finally { setSaving(false) }
  }
  return <div className="flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm">
    <label htmlFor="link-meeting" className="text-muted-foreground">Takimi:</label>
    <select id="link-meeting" className="h-9 min-w-64 rounded-md border bg-background px-3 text-sm" value={meetingId} onChange={e => setMeetingId(e.target.value)}>
      <option value="">Zgjidh takimin…</option>{meetings.map(m => <option key={m.id} value={m.id}>{m.title}</option>)}
    </select>
    <Button size="sm" variant="outline" disabled={!meetingId || saving} onClick={() => void link()}>Lidh</Button>
  </div>
}
