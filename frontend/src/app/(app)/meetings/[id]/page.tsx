"use client"

import * as React from "react"
import Link from "next/link"
import { useParams } from "next/navigation"
import { ImagePlus, Mic } from "lucide-react"
import { toast } from "sonner"
import { useAuth } from "@/lib/auth"
import {
  clock, dmy, isNoteDone, KIND_LABEL, readError, shortDm, STATUS_STYLE,
  type MeetingDetail, type MeetingNote, type MeetingNoteTaskStatus,
} from "@/lib/meeting-notes"
import { NotesTable } from "@/components/meeting-notes/notes-table"
import { PendingThumb } from "@/components/meeting-notes/attachment-thumb"
import { StatusLegend } from "@/components/meeting-notes/status-legend"
import { useProjectTitles, useUsersMap } from "@/components/meeting-notes/use-lookups"
import { Button } from "@/components/ui/button"

type SourceFilter = "all" | "manual" | "recording"

function frequencyText(detail: MeetingDetail) {
  const meeting = detail.meeting
  const type = (meeting.recurrence_type || "").toLowerCase()
  const days = ["e hënë", "e martë", "e mërkurë", "e enjte", "e premte", "e shtunë", "e diel"]
  const time = meeting.starts_at ? new Date(meeting.starts_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }) : ""
  if (type === "weekly") return `Weekly, ${(meeting.recurrence_days_of_week || []).map((d) => days[d]).join(", ")} ${time}`.trim()
  if (type === "monthly") return `Monthly, dita ${(meeting.recurrence_days_of_month || []).join(", ")} ${time}`.trim()
  return `Njëherë${meeting.starts_at ? `, ${dmy(meeting.starts_at.slice(0, 10))} ${time}` : ""}`
}

export default function MeetingPage() {
  const { id } = useParams<{ id: string }>()
  const { apiFetch } = useAuth()
  const users = useUsersMap()
  const projects = useProjectTitles()
  const [detail, setDetail] = React.useState<MeetingDetail | null>(null)
  const [session, setSession] = React.useState<string | null>(null)
  const [notes, setNotes] = React.useState<MeetingNote[]>([])
  const [error, setError] = React.useState("")
  const [loadingNotes, setLoadingNotes] = React.useState(false)
  const [source, setSource] = React.useState<SourceFilter>("all")
  const [showDone, setShowDone] = React.useState(false)
  const [selected, setSelected] = React.useState<Set<string>>(new Set())
  const [text, setText] = React.useState("")
  const [isQuestion, setIsQuestion] = React.useState(false)
  const [files, setFiles] = React.useState<File[]>([])
  const [saving, setSaving] = React.useState(false)
  const [bulkBusy, setBulkBusy] = React.useState(false)
  const fileInput = React.useRef<HTMLInputElement>(null)

  const loadDetail = React.useCallback(async () => {
    const response = await apiFetch(`/meeting-notes/meetings/${id}`, { cache: "no-store" })
    if (!response.ok) throw new Error(await readError(response, "Takimi nuk u ngarkua."))
    const data = (await response.json()) as MeetingDetail
    setDetail(data)
    setSession((current) => {
      if (current) return current
      const wanted = new URLSearchParams(window.location.search).get("date")
      const dates = data.sessions.map((s) => s.date)
      if (wanted && dates.includes(wanted)) return wanted
      if (dates.includes(data.today)) return data.today
      const past = dates.filter((d) => d <= data.today)
      return past[past.length - 1] || dates[0] || data.today
    })
  }, [apiFetch, id])

  const loadNotes = React.useCallback(async (day: string) => {
    setLoadingNotes(true)
    try {
      const response = await apiFetch(`/meeting-notes/meetings/${id}/notes?session=${day}&scope=session`, { cache: "no-store" })
      if (!response.ok) throw new Error(await readError(response, "Shënimet nuk u ngarkuan."))
      setNotes((await response.json()) as MeetingNote[])
      setSelected(new Set())
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setLoadingNotes(false) }
  }, [apiFetch, id])

  React.useEffect(() => { void loadDetail().catch((e) => setError(e instanceof Error ? e.message : String(e))) }, [loadDetail])
  React.useEffect(() => { if (session) void loadNotes(session) }, [session, loadNotes])

  const replaceNote = (note: MeetingNote) => setNotes((current) => current.map((item) => item.id === note.id ? note : item))
  const removeNote = (noteId: string) => setNotes((current) => current.filter((item) => item.id !== noteId))

  const addNote = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!session || (!text.trim() && !files.length)) return
    setSaving(true)
    try {
      const response = await apiFetch(`/meeting-notes/meetings/${id}/notes`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ occurrence_date: session, content: text.trim() || "Screenshot", kind: isQuestion ? "QUESTION" : "NOTE" }),
      })
      if (!response.ok) throw new Error(await readError(response, "Shënimi nuk u ruajt."))
      let note = (await response.json()) as MeetingNote
      if (files.length) {
        const form = new FormData()
        files.forEach((file) => form.append("files", file))
        const upload = await apiFetch(`/meeting-notes/${note.id}/attachments`, { method: "POST", body: form })
        if (upload.ok) note = (await upload.json()) as MeetingNote
        else toast.error(await readError(upload, "Shënimi u ruajt, por screenshot-i jo."))
      }
      setNotes((current) => [note, ...current])
      setText(""); setFiles([]); setIsQuestion(false)
    } catch (e) { toast.error(e instanceof Error ? e.message : String(e)) }
    finally { setSaving(false) }
  }

  const onPaste = (event: React.ClipboardEvent<HTMLInputElement>) => {
    const pasted = [...event.clipboardData.files].filter((file) => file.type.startsWith("image/"))
    if (!pasted.length) return
    event.preventDefault()
    setFiles((current) => [...current, ...pasted.map((file, index) => new File([file], `screenshot-${new Date().toTimeString().slice(0, 8).replaceAll(":", "-")}${index ? `-${index}` : ""}.png`, { type: file.type }))])
  }

  const sendSelected = async (merge: boolean) => {
    const ids = notes.filter((note) => selected.has(note.id)).map((note) => note.id)
    if (!ids.length) return
    setBulkBusy(true)
    try {
      const response = await apiFetch("/meeting-notes/send-to-px", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ note_ids: ids, merge }) })
      if (!response.ok) throw new Error(await readError(response, "Shënimet nuk u dërguan në PX Notes."))
      const updated = (await response.json()) as MeetingNote[]
      const byId = new Map(updated.map((note) => [note.id, note]))
      setNotes((current) => current.map((note) => byId.get(note.id) || note))
      setSelected(new Set())
      toast.success(merge ? "U krijua 1 shënim në PX Notes. Krijo detyrën atje." : `${updated.length} shënime u dërguan në PX Notes.`)
    } catch (e) { toast.error(e instanceof Error ? e.message : String(e)) }
    finally { setBulkBusy(false) }
  }

  const closeSelected = async () => {
    setBulkBusy(true)
    try {
      for (const noteId of selected) {
        const response = await apiFetch(`/meeting-notes/${noteId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_closed: true }) })
        if (response.ok) replaceNote((await response.json()) as MeetingNote)
      }
      setSelected(new Set())
    } finally { setBulkBusy(false) }
  }

  const toggleTraining = async () => {
    if (!detail) return
    const next = !detail.meeting.is_training
    const response = await apiFetch(`/meeting-notes/meetings/${id}/training`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_training: next }) })
    if (!response.ok) { toast.error("Nuk u ndryshua."); return }
    await loadDetail()
  }

  if (error && !detail) return <p role="alert" className="text-sm text-destructive">{error}</p>
  if (!detail) return <p role="status" className="text-sm text-muted-foreground">Duke ngarkuar…</p>

  const visibleNotes = notes.filter((note) => {
    if (!showDone && isNoteDone(note)) return false
    if (source === "manual") return note.source === "MANUAL"
    if (source === "recording") return note.source === "RECORDING"
    return true
  })
  const scoped = notes.filter((note) => showDone || !isNoteDone(note))
  const recordingCount = scoped.filter((note) => note.source === "RECORDING").length
  const statusCounts = (["TODO", "IN_PROGRESS", "WAITING_CLIENT", "DONE"] as MeetingNoteTaskStatus[]).map((status) => ({
    status, count: notes.filter((note) => note.task_status === status).length,
  }))
  const currentSession = detail.sessions.find((s) => s.date === session)
  const client = detail.project?.title || (detail.meeting.project_id ? projects.get(detail.meeting.project_id) : null)
  const canceled = detail.sessions.filter((s) => s.status === "canceled")
  const selectableCount = notes.filter((note) => selected.has(note.id)).length

  return <div className="w-full space-y-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="space-y-1">
        <Link href="/meetings" className="text-sm text-muted-foreground">← Takimet</Link>
        <h1 className="text-2xl font-semibold">{detail.meeting.title}</h1>
        <p className="text-muted-foreground">{KIND_LABEL[detail.kind]} · {frequencyText(detail)}{client ? ` · Klienti ${client}` : ""} · {detail.meeting.participant_ids?.length || 0} pjesëmarrës</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {detail.meeting.project_id && <Button asChild variant="outline"><Link href={`/meetings/client/${detail.meeting.project_id}`}>Historia e klientit</Link></Button>}
        <Button variant="ghost" onClick={() => void toggleTraining()}>{detail.meeting.is_training ? "Hiq nga trajnimet" : "Shëno si trajnim"}</Button>
      </div>
    </div>

    <div className="flex flex-wrap items-center gap-2.5">
      <div role="tablist" aria-label="Seancat" className="inline-flex flex-wrap gap-0.5 rounded-xl bg-muted p-[3px]">
        {detail.sessions.map((s) => <button key={s.date} type="button" role="tab" aria-selected={session === s.date} onClick={() => setSession(s.date)}
          className={`h-[30px] rounded-[9px] px-3 text-sm font-semibold ${session === s.date ? "bg-white shadow-sm" : ""} ${s.status === "canceled" ? "text-neutral-400 line-through" : ""}`}
          title={s.status === "canceled" ? "Anuluar" : s.status === "planned" ? "E planifikuar" : undefined}>
          {shortDm(s.date)}{s.is_today ? " · Sot" : ""}
        </button>)}
      </div>
      {canceled.length > 0 && <span className="text-xs text-muted-foreground">Seancat e anuluara: shënimet e hapura kalojnë vetë te seanca e radhës.</span>}
    </div>

    <div className="flex flex-wrap items-center gap-4 rounded-[10px] border px-3.5 py-2.5">
      <div className="flex gap-1">{statusCounts.map(({ status, count }) => <span key={status} className={`border border-slate-600 px-2 py-1 text-xs font-bold ${STATUS_STYLE[status].cell}`}>{STATUS_STYLE[status].label} {count}</span>)}</div>
      <span className="h-5 w-px bg-border" aria-hidden="true" />
      {currentSession?.recordings.length ? currentSession.recordings.map((rec) => <Link key={rec.id} href={`/meeting-recordings/${rec.id}`} className="inline-flex items-center gap-1.5 font-medium text-violet-800">
        <Mic className="size-4" aria-hidden="true" /><span className="underline">Regjistrimi {shortDm(session || "")} · {clock(rec.duration_seconds)}</span>
      </Link>) : <Link href={`/meeting-recordings?meeting_id=${detail.meeting.id}`} className="inline-flex items-center gap-1.5 text-sm text-muted-foreground underline"><Mic className="size-4" aria-hidden="true" />Nis regjistrimin për këtë takim</Link>}
    </div>

    <form onSubmit={(e) => void addNote(e)} className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <label className="flex h-10 flex-[1_1_360px] items-center gap-2 rounded-md border border-neutral-400 px-3">
          <span className="sr-only">Shënim i ri</span>
          <input value={text} onChange={(e) => setText(e.target.value)} onPaste={onPaste} placeholder="Shkruaj pyetje ose shënim… (Ctrl+V për screenshot)" className="flex-1 bg-transparent text-sm outline-none" />
        </label>
        <Button type="button" variant="outline" className="h-10" onClick={() => fileInput.current?.click()}><ImagePlus aria-hidden="true" />Screenshot</Button>
        <input ref={fileInput} type="file" accept="image/*" multiple className="sr-only" onChange={(e) => { setFiles((current) => [...current, ...(e.target.files ? [...e.target.files] : [])]); e.target.value = "" }} />
        <Button type="button" variant={isQuestion ? "default" : "outline"} className="h-10" aria-pressed={isQuestion} onClick={() => setIsQuestion((v) => !v)}>? Pyetje</Button>
        <Button type="submit" className="h-10" disabled={saving || !session || (!text.trim() && !files.length)}>{saving ? "Duke ruajtur…" : "Shto shënim"}</Button>
      </div>
      {files.length > 0 && <div className="flex flex-wrap items-center gap-2">
        {files.map((file, index) => <PendingThumb key={`${file.name}-${index}`} file={file} onRemove={() => setFiles((current) => current.filter((_, i) => i !== index))} />)}
        <span className="text-xs text-muted-foreground">Ruhet si bashkëngjitje te shënimi</span>
      </div>}
    </form>

    <div className="flex flex-wrap items-center justify-between gap-2.5">
      <div className="inline-flex flex-wrap gap-1.5" aria-label="Burimi">
        {([["all", "Të gjitha", scoped.length], ["manual", "Manuale", scoped.length - recordingCount], ["recording", "Nga regjistrimi", recordingCount]] as [SourceFilter, string, number][]).map(([key, label, n]) =>
          <button key={key} type="button" onClick={() => setSource(key)} aria-pressed={source === key}
            className={`h-8 rounded-full border px-3 text-[13px] font-medium ${source === key ? key === "recording" ? "border-violet-600 bg-violet-100 text-violet-800" : "border-neutral-900 bg-muted" : "bg-white"}`}>
            {label} <span className="opacity-70">{n}</span>
          </button>)}
      </div>
      <label className="inline-flex items-center gap-2 text-sm text-neutral-600"><input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} />Shfaq edhe të mbyllurat</label>
    </div>

    {selectableCount > 0 && <div className="flex flex-wrap items-center gap-2 rounded-[10px] border bg-neutral-50 px-3 py-2">
      <span className="mr-1.5 font-semibold">{selectableCount} të zgjedhura</span>
      <Button size="sm" disabled={bulkBusy || selectableCount < 2} title={selectableCount < 2 ? "Zgjidh të paktën 2 shënime" : undefined} onClick={() => void sendSelected(true)}>Bashko në 1 shënim PX</Button>
      <Button size="sm" variant="outline" disabled={bulkBusy} onClick={() => void sendSelected(false)}>Dërgo në PX veç e veç</Button>
      <Button size="sm" variant="outline" disabled={bulkBusy} onClick={() => void closeSelected()}>Mbyll</Button>
      <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setSelected(new Set())}>Anulo</Button>
    </div>}

    {loadingNotes ? <p role="status" className="text-sm text-muted-foreground">Duke ngarkuar…</p>
      : visibleNotes.length ? <NotesTable notes={visibleNotes} kind={detail.kind} users={users} selected={selected}
        onToggleSelect={(noteId) => setSelected((current) => { const next = new Set(current); if (next.has(noteId)) next.delete(noteId); else next.add(noteId); return next })}
        onChanged={replaceNote} onRemoved={removeNote} onTasksChanged={() => { if (session) void loadNotes(session) }} />
      : <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">Nuk ka shënime për këtë seancë ende.</p>}
    <StatusLegend />
  </div>
}
