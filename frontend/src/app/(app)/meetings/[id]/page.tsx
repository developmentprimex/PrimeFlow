"use client"

import { meetingTranslator } from "@/lib/meeting-notes-language"

import * as React from "react"
import Link from "next/link"
import { useParams } from "next/navigation"
import { ImagePlus, Mic } from "lucide-react"
import { toast } from "sonner"
import { useAuth } from "@/lib/auth"
import {
  clock, dmy, isNoteDone, readError, shortDm, STATUS_STYLE,
  type MeetingDetail, type MeetingNote, type MeetingNoteTaskStatus,
} from "@/lib/meeting-notes"
import { NotesTable } from "@/components/meeting-notes/notes-table"
import { MeetingClientPicker, type MeetingClientSelection } from "@/components/meeting-notes/client-picker"
import { PendingThumb } from "@/components/meeting-notes/attachment-thumb"
import { StatusLegend } from "@/components/meeting-notes/status-legend"
import { useUsersMap } from "@/components/meeting-notes/use-lookups"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { useSidebar } from "@/components/sidebar-context"

type SourceFilter = "all" | "manual" | "recording"

export default function MeetingPage() {
  const { id } = useParams<{ id: string }>()
  const { apiFetch } = useAuth()
  const users = useUsersMap()
  const [detail, setDetail] = React.useState<MeetingDetail | null>(null)
  const english = detail?.kind === "EXTERNAL"
  const { collapseForPage } = useSidebar()
  React.useEffect(() => {
    if (english) return collapseForPage()
  }, [english, collapseForPage])
  const t = meetingTranslator(english)
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
  const [clientDraft, setClientDraft] = React.useState<MeetingClientSelection | null | undefined>(undefined)
  const [savingClient, setSavingClient] = React.useState(false)
  const savingClientRef = React.useRef(false)
  const fileInput = React.useRef<HTMLInputElement>(null)

  const loadDetail = React.useCallback(async () => {
    const response = await apiFetch(`/meeting-notes/meetings/${id}`, { cache: "no-store" })
    if (!response.ok) throw new Error(await readError(response, t("Takimi nuk u ngarkua.")))
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
  }, [apiFetch, id, t])

  const loadNotes = React.useCallback(async (day: string) => {
    setLoadingNotes(true)
    try {
      const response = await apiFetch(`/meeting-notes/meetings/${id}/notes?session=${day}&scope=session`, { cache: "no-store" })
      if (!response.ok) throw new Error(await readError(response, t("Shënimet nuk u ngarkuan.")))
      setNotes((await response.json()) as MeetingNote[])
      setSelected(new Set())
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setLoadingNotes(false) }
  }, [apiFetch, id, t])

  React.useEffect(() => { void loadDetail().catch((e) => setError(e instanceof Error ? e.message : String(e))) }, [loadDetail])
  React.useEffect(() => { if (session) void loadNotes(session) }, [session, loadNotes])

  const replaceNote = (note: MeetingNote) => setNotes((current) => current.map((item) => item.id === note.id ? note : item))
  const removeNote = (noteId: string) => {
    setNotes((current) => current.filter((item) => item.id !== noteId))
    setSelected((current) => { const next = new Set(current); next.delete(noteId); return next })
  }

  const addNote = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!session || (!text.trim() && !files.length)) return
    setSaving(true)
    try {
      const response = await apiFetch(`/meeting-notes/meetings/${id}/notes`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ occurrence_date: session, content: text.trim() || "Screenshot", kind: isQuestion ? "QUESTION" : "NOTE" }),
      })
      if (!response.ok) throw new Error(await readError(response, t("Shënimi nuk u ruajt.")))
      let note = (await response.json()) as MeetingNote
      if (files.length) {
        const form = new FormData()
        files.forEach((file) => form.append("files", file))
        const upload = await apiFetch(`/meeting-notes/${note.id}/attachments`, { method: "POST", body: form })
        if (upload.ok) note = (await upload.json()) as MeetingNote
        else toast.error(await readError(upload, t("Shënimi u ruajt, por screenshot-i jo.")))
      }
      setNotes((current) => [note, ...current])
      setText(""); setFiles([]); setIsQuestion(false)
    } catch (e) { toast.error(e instanceof Error ? e.message : String(e)) }
    finally { setSaving(false) }
  }

  const onPaste = (event: React.ClipboardEvent<HTMLTextAreaElement>) => {
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
      if (!response.ok) throw new Error(await readError(response, t("Shënimet nuk u dërguan në PX Notes.")))
      const updated = (await response.json()) as MeetingNote[]
      const byId = new Map(updated.map((note) => [note.id, note]))
      setNotes((current) => current.map((note) => byId.get(note.id) || note))
      setSelected(new Set())
      toast.success(merge ? t("U krijua 1 shënim në PX Notes. Krijo detyrën atje.") : english ? `${updated.length} notes sent to PX Notes.` : `${updated.length} shënime u dërguan në PX Notes.`)
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

  const saveClient = async (selectedClient: MeetingClientSelection | null) => {
    if (!detail || savingClientRef.current) return
    if (selectedClient && !selectedClient.name.trim()) {
      toast.error(t("Shkruaj emrin e klientit të ri."))
      return
    }
    savingClientRef.current = true
    setSavingClient(true)
    try {
      const response = await apiFetch(`/meeting-notes/meetings/${id}/client`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client_id: selectedClient?.id || null, client_name: selectedClient?.name.trim() || null }),
      })
      if (!response.ok) throw new Error(await readError(response, t("Klienti nuk u ruajt.")))
      const saved = await response.json() as { client_id: string | null; client_name: string | null }
      setDetail((current) => current ? { ...current, meeting: { ...current.meeting, client_id: saved.client_id, client_name: saved.client_name } } : current)
      setClientDraft(undefined)
      toast.success(t("Klienti u ruajt."))
    } catch (e) {
      if (!selectedClient || selectedClient.id) setClientDraft(undefined)
      toast.error(e instanceof Error ? e.message : String(e))
    }
    finally { savingClientRef.current = false; setSavingClient(false) }
  }

  const changeClient = (selection: MeetingClientSelection | null) => {
    setClientDraft(selection)
    if (!selection || selection.id) void saveClient(selection)
  }

  if (error && !detail) return <p role="alert" className="text-sm text-destructive">{error}</p>
  if (!detail) return <p role="status" className="text-sm text-muted-foreground">{t("Duke ngarkuar…")}</p>

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
  const client = detail.meeting.client_name
  const savedClient = client ? { id: detail.meeting.client_id || null, name: client } : null
  const selectedClient = clientDraft === undefined ? savedClient : clientDraft
  const canceled = detail.sessions.filter((s) => s.status === "canceled")
  const selectableCount = notes.filter((note) => selected.has(note.id)).length

  return <div className="min-w-0 w-full space-y-2">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div className="space-y-2">
        <Link href="/meetings" className="text-xs text-muted-foreground">{t("← Takimet")}</Link>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <h1 className="text-xl font-semibold leading-tight">{detail.meeting.title}</h1>
          <div aria-busy={savingClient} className="w-56 max-w-full [&_select]:h-8 [&_select]:text-xs [&_input]:h-8 [&_input]:text-xs">
            <MeetingClientPicker english={english} id="meeting-client" value={selectedClient} onChange={changeClient} onCommit={(selection) => void saveClient(selection)} disabled={savingClient} />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <div role="tablist" aria-label={t("Seancat")} className="inline-flex flex-wrap gap-0.5 rounded-xl bg-muted p-[3px]">
            {detail.sessions.map((s) => <button key={s.date} type="button" role="tab" aria-selected={session === s.date} onClick={() => setSession(s.date)}
              className={`h-[30px] rounded-[9px] px-3 text-sm font-semibold ${session === s.date ? "bg-white shadow-sm" : ""} ${s.status === "canceled" ? "text-neutral-400 line-through" : ""}`}
              title={s.status === "canceled" ? t("Anuluar") : s.status === "planned" ? t("E planifikuar") : undefined}>
              {dmy(s.date)}{s.is_today ? (english ? " · Today" : " · Sot") : ""}
            </button>)}
          </div>
          {canceled.length > 0 && <span className="text-xs text-muted-foreground">{t("Seancat e anuluara: shënimet e hapura kalojnë vetë te seanca e radhës.")}</span>}
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        {detail.meeting.project_id && <Button asChild size="sm" variant="outline"><Link href={`/meetings/client/${detail.meeting.project_id}`}>{t("Historia e projektit")}</Link></Button>}
      </div>
    </div>

    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <div className="inline-flex flex-wrap gap-1.5" aria-label={t("Burimi")}>
        {([["all", t("Të gjitha"), scoped.length], ["manual", t("Manuale"), scoped.length - recordingCount], ["recording", t("Nga regjistrimi"), recordingCount]] as [SourceFilter, string, number][]).map(([key, label, n]) =>
          <button key={key} type="button" onClick={() => setSource(key)} aria-pressed={source === key}
            className={`h-8 rounded-full border px-3 text-[13px] font-medium ${source === key ? key === "recording" ? "border-violet-600 bg-violet-100 text-violet-800" : "border-neutral-900 bg-muted" : "bg-white"}`}>
            {label} <span className="opacity-70">{n}</span>
          </button>)}
      </div>
      <Button type="button" size="sm" variant={showDone ? "default" : "outline"} aria-pressed={showDone} className="h-8 rounded-full px-3 text-[13px]" onClick={() => setShowDone((current) => !current)}>{t("Shfaq edhe të mbyllurat")}</Button>
      <div className="flex flex-wrap items-center gap-3 sm:ml-4">
        {currentSession?.recordings.length ? currentSession.recordings.map((rec) => <Link key={rec.id} href={`/meeting-recordings/${rec.id}`} className="inline-flex items-center gap-1.5 text-xs font-medium text-violet-800">
          <Mic className="size-4" aria-hidden="true" /><span className="underline">{english ? "Recording" : "Regjistrimi"} {shortDm(session || "")} · {clock(rec.duration_seconds)}</span>
        </Link>) : <Button asChild size="sm" className="h-9 px-3 font-semibold shadow-sm"><Link href={`/meeting-recordings?meeting_id=${detail.meeting.id}`}><Mic className="size-4" aria-hidden="true" />{t("Nis regjistrimin")}</Link></Button>}
      </div>
    </div>

    <form onSubmit={(e) => void addNote(e)} className="space-y-2">
      <div className="flex flex-wrap items-end gap-2">
        <Textarea id="meeting-new-note" aria-label={t("Shënim i ri")} rows={3} value={text} onChange={(e) => setText(e.target.value)} onPaste={onPaste} placeholder={t("Shkruaj pyetje ose shënim… (Ctrl+V për screenshot)")} className="min-h-24 min-w-0 flex-[1_1_360px] resize-y border-neutral-400 bg-white px-3 py-2.5 text-base placeholder:text-slate-500 md:text-base" />
        <Button type="button" variant="outline" className="h-10" onClick={() => fileInput.current?.click()}><ImagePlus aria-hidden="true" />Screenshot</Button>
        <input ref={fileInput} type="file" accept="image/*" multiple className="sr-only" onChange={(e) => { setFiles((current) => [...current, ...(e.target.files ? [...e.target.files] : [])]); e.target.value = "" }} />
        <Button type="button" variant={isQuestion ? "default" : "outline"} className="h-10" aria-pressed={isQuestion} onClick={() => setIsQuestion((v) => !v)}>{t("? Pyetje")}</Button>
        <Button type="submit" className="h-10" disabled={saving || !session || (!text.trim() && !files.length)}>{saving ? t("Duke ruajtur…") : t("Shto shënim")}</Button>
      </div>
      {files.length > 0 && <div className="flex flex-wrap items-center gap-2">
        {files.map((file, index) => <PendingThumb english={english} key={`${file.name}-${index}`} file={file} onRemove={() => setFiles((current) => current.filter((_, i) => i !== index))} />)}
        <span className="text-xs text-muted-foreground">{t("Ruhet si bashkëngjitje te shënimi")}</span>
      </div>}
    </form>

    {selectableCount > 0 && <div className="flex flex-wrap items-center gap-2 rounded-[10px] border bg-neutral-50 px-3 py-2">
      <span className="mr-1.5 font-semibold">{selectableCount} {english ? "selected" : "të zgjedhura"}</span>
      <Button size="sm" disabled={bulkBusy || selectableCount < 2} title={selectableCount < 2 ? t("Zgjidh të paktën 2 shënime") : undefined} onClick={() => void sendSelected(true)}>{t("Bashko në 1 shënim PX")}</Button>
      <Button size="sm" variant="outline" disabled={bulkBusy} onClick={() => void sendSelected(false)}>{t("Dërgo në PX veç e veç")}</Button>
      <Button size="sm" variant="outline" disabled={bulkBusy} onClick={() => void closeSelected()}>{t("Mbyll")}</Button>
      <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setSelected(new Set())}>{t("Anulo")}</Button>
    </div>}

    {loadingNotes ? <p role="status" className="text-sm text-muted-foreground">{t("Duke ngarkuar…")}</p>
      : visibleNotes.length ? <NotesTable notes={visibleNotes} kind={detail.kind} users={users} selected={selected}
        onToggleSelect={(noteId) => setSelected((current) => { const next = new Set(current); if (next.has(noteId)) next.delete(noteId); else next.add(noteId); return next })}
        onChanged={replaceNote} onRemoved={removeNote} onTasksChanged={() => { if (session) void loadNotes(session) }} />
      : <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">{t("Nuk ka shënime për këtë seancë ende.")}</p>}
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <StatusLegend english={english} withStatuses={false} />
      <div className="flex flex-wrap gap-1" aria-label={english ? "Task totals" : "Numërimet e detyrave"}>
        {statusCounts.map(({ status, count }) => <span key={status} className={`border border-slate-600 px-1.5 py-0.5 text-xs font-bold ${STATUS_STYLE[status].cell}`}>{STATUS_STYLE[status].label} {count}</span>)}
      </div>
    </div>
  </div>
}
