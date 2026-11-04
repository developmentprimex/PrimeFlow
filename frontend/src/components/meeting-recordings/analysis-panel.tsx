"use client"

import * as React from "react"
import { ChevronDown, Clock3, FileText, ListTodo, Pencil, Plus } from "lucide-react"
import Link from "next/link"
import { MarkedTaskBlock } from "@/lib/note-markup"
import type { Task } from "@/lib/types"
import { useAuth } from "@/lib/auth"
import { recordingJson } from "@/lib/recording-outbox"
import { recordingTime } from "@/lib/recording-types"
import { Button } from "@/components/ui/button"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { RecordingTaskDialog } from "./task-dialog"
import { RecordingProtocolPanel } from "./protocol-panel"
import { RecordingSummaryContent } from "./summary-content"
import { transcriptParagraphs } from "@/lib/recording-transcript"
import { Label } from "@/components/ui/label"
import { Table, TableHeader, TableHead, TableBody, TableRow, TableCell } from "@/components/ui/table"

export type RecordingAction = { id: string; segment_index: number; title: string; description: string; evidence: string; assignee_text: string | null; deadline_text: string | null; suggested_assignee_id: string | null; suggested_due_date: string | null; created_task_id: string | null; confirmed_at: string | null; dismissed_at?: string | null; meeting_note_id?: string | null }
type Segment = { index: number; start_seconds: number; duration_seconds: number; text: string }
type CitationTime = { start: number | null; end: number | null; approximate: boolean }
type Timing = { status: string; completed?: number; total?: number; error?: string | null; results?: Record<string, CitationTime> }
type Analysis = { timing_configured?: boolean; timing?: Timing | null; configured: boolean; can_manage: boolean; can_start_analysis: boolean; analysis: null | { status: string; language: string; total_segments: number; segments_done: number; summary: string | null; error_message: string | null; decisions: string[] }; segments: Segment[]; actions: RecordingAction[]; meeting_id?: string | null }
export type RecordingPerson = { id: string; full_name: string; department_id: string | null; role?: "ADMIN" | "MANAGER" | "STAFF" }
export type RecordingDepartment = { id: string; name: string }
const STATUS: Record<string, string> = { QUEUED: "Në pritje të përpunimit", TRANSCRIBING: "Duke transkriptuar", SUMMARIZING: "Duke përgatitur përmbledhjen dhe propozimet", READY: "Përpunimi përfundoi", FAILED: "Përpunimi dështoi" }
const selectClass = "h-9 w-full rounded-md border border-input bg-background px-3 text-sm"

function ActionReview({ action, number, recordingId, meetingId, people, departments, canManage, onCreated, timing, timingStatus, onSeek }: { timing?: CitationTime; timingStatus?: string; onSeek?: (seconds: number) => void; action: RecordingAction; number: number; recordingId: string; meetingId?: string | null; people: RecordingPerson[]; departments: RecordingDepartment[]; canManage: boolean; onCreated: () => Promise<void> }) {
  const { apiFetch } = useAuth()
  // Takimet: keep a proposal as a meeting note or ignore it, without a task.
  const [noteId, setNoteId] = React.useState<string | null>(action.meeting_note_id || null)
  const [dismissed, setDismissed] = React.useState(Boolean(action.dismissed_at))
  const [reviewBusy, setReviewBusy] = React.useState(false)
  const keepAsNote = async () => {
    setReviewBusy(true); setEditError("")
    try {
      const note = await recordingJson(await apiFetch(`/meeting-notes/recordings/${recordingId}/actions/${action.id}/note`, { method: "POST" })) as { id: string }
      setNoteId(note.id); setDismissed(false)
    } catch (error) { setEditError(error instanceof Error ? error.message : String(error)) }
    finally { setReviewBusy(false) }
  }
  const setDismiss = async (value: boolean) => {
    setReviewBusy(true); setEditError("")
    try {
      await recordingJson(await apiFetch(`/meeting-notes/recordings/${recordingId}/actions/${action.id}/dismiss`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ dismissed: value }) }))
      setDismissed(value)
      if (!value) setNoteId(null)
    } catch (error) { setEditError(error instanceof Error ? error.message : String(error)) }
    finally { setReviewBusy(false) }
  }
  const [open, setOpen] = React.useState(false)
  const [createdId, setCreatedId] = React.useState<string | null>(action.created_task_id)
  const [editor, setEditor] = React.useState<{ task: Task; people: RecordingPerson[]; departments: RecordingDepartment[] } | null>(null)
  const [loadingTask, setLoadingTask] = React.useState(false)
  const [editError, setEditError] = React.useState("")
  const [savedTask, setSavedTask] = React.useState<Task | null>(null)
  React.useEffect(() => {
    if (!createdId) return
    let active = true
    void apiFetch(`/tasks/${createdId}`, { cache: "no-store" }).then(recordingJson).then((task: Task) => { if (active) setSavedTask(task) }).catch(() => {})
    return () => { active = false }
  }, [apiFetch, createdId])
  const openCreated = async () => {
    if (!createdId || loadingTask) return
    setLoadingTask(true); setEditError("")
    try {
      const [task, users, teams] = await Promise.all([
        apiFetch(`/tasks/${createdId}`, { cache: "no-store" }).then(recordingJson) as Promise<Task>,
        apiFetch("/users/lookup").then(recordingJson) as Promise<RecordingPerson[]>,
        apiFetch("/departments").then(recordingJson) as Promise<RecordingDepartment[]>,
      ])
      setSavedTask(task)
      setEditor({ task, people: users, departments: teams })
    } catch (error) { setEditError(error instanceof Error ? error.message : String(error)) }
    finally { setLoadingTask(false) }
  }
  const responsible = savedTask ? (savedTask.assignees || []).map(person => person.full_name || person.email).filter(Boolean).join(", ") || people.find(person => person.id === savedTask.assigned_to)?.full_name || "Pa përgjegjës" : people.find(person => person.id === action.suggested_assignee_id)?.full_name || action.assignee_text || "Pa përgjegjës"
  const description = (savedTask ? savedTask.description || "" : action.description).split(/\n\s*Burimi: regjistrimi /)[0].replace(/<br\s*\/?\s*>/gi, " ").replace(/<[^>]+>/g, "").replace(/\s+/g, " ")
  const taskContent = savedTask ? [savedTask.title, !savedTask.title.includes("\n") ? description : ""].filter(Boolean).join("\n") : [action.title.toLocaleUpperCase("sq-AL"), action.description].filter(Boolean).join("\n")
  const due = savedTask ? savedTask.due_date : action.suggested_due_date
  const taskStatus = savedTask ? ({ TODO: "Për t’u bërë", IN_PROGRESS: "Në progres", WAITING_CLIENT: "WFE", WAITING_CONFIRMATION: "Në konfirmim", DONE: "E përfunduar" }[savedTask.status || "TODO"] || savedTask.status) : createdId ? "E krijuar" : action.confirmed_at ? "E fshirë" : noteId ? "Shënim te takimi" : dismissed ? "Injoruar" : "Propozim AI"
  return <><TableRow className="align-top">
    <TableCell className="font-bold tabular-nums text-muted-foreground">{number}</TableCell>
    <TableCell className="whitespace-normal">
      <MarkedTaskBlock content={taskContent} headingLevel={4} />
      <details className="mt-3 text-xs text-muted-foreground"><summary className="w-fit cursor-pointer rounded-sm hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring">Nga biseda</summary><blockquote className="mt-2 rounded-r-md border-l-2 bg-muted/40 px-3 py-2 text-sm leading-6">{action.evidence}</blockquote></details>
      {timing?.start != null ? <button type="button" disabled={!onSeek} className="mt-2 text-xs text-primary underline disabled:opacity-50" onClick={() => onSeek?.(timing.start!)}>▶ Rreth {recordingTime(timing.start)}</button> : timing || timingStatus === "READY" ? <p className="mt-2 text-xs text-muted-foreground">Koha nuk u përcaktua për këtë citim.</p> : null}
    </TableCell>
    <TableCell className={`whitespace-normal ${responsible === "Pa përgjegjës" ? "text-muted-foreground" : "font-medium"}`}>{responsible}</TableCell>
    <TableCell className="tabular-nums text-muted-foreground">{due ? new Date(due).toLocaleDateString("sq-AL") : action.deadline_text || "—"}</TableCell>
    <TableCell><span className={`inline-flex items-center gap-1.5 rounded-md border px-1.5 py-0.5 text-xs font-medium ${createdId ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200" : "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200"}`}><span aria-hidden="true" className="size-1.5 rounded-full bg-current" />{taskStatus}</span></TableCell>
    <TableCell className="text-center">
    {createdId ? <Button variant="outline" size="sm" className="h-7 text-xs" disabled={loadingTask} onClick={() => void openCreated()}><Pencil aria-hidden="true" />{loadingTask ? "Duke ngarkuar…" : "Edito detyrë"}</Button>
      : action.confirmed_at ? <p className="text-sm">Detyra e konfirmuar është fshirë nga Tasks.</p>
      : noteId ? <div className="space-y-1"><p className="text-sm text-violet-800">Shënim te takimi ✓</p><button type="button" className="text-xs text-muted-foreground underline" disabled={reviewBusy} onClick={() => void setDismiss(false)}>Zhbëj</button></div>
      : dismissed ? <div className="space-y-1"><p className="text-sm text-muted-foreground">Injoruar</p><button type="button" className="text-xs underline" disabled={reviewBusy} onClick={() => void setDismiss(false)}>Zhbëj</button></div>
      : <div className="flex flex-wrap justify-center gap-1.5">
        {canManage ? <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => setOpen(true)}><Plus aria-hidden="true" />Detyrë</Button> : <p className="text-sm">Autori i regjistrimit mund ta konfirmojë detyrën.</p>}
        {meetingId && <Button variant="outline" size="sm" className="h-7 text-xs" disabled={reviewBusy} onClick={() => void keepAsNote()}>Shënim</Button>}
        {canManage && <Button variant="ghost" size="sm" className="h-7 text-xs text-muted-foreground" disabled={reviewBusy} onClick={() => void setDismiss(true)}>Injoro</Button>}
      </div>}
    {savedTask?.ga_note_origin_id && <Link className="mt-2 block text-sm underline" href="/ga-ka-notes">Hap në PX Notes</Link>}
    {editError && <p role="alert" className="mt-2 max-w-48 whitespace-normal text-sm text-destructive">{editError}</p>}
    </TableCell>
  </TableRow>
    {open && !createdId && <RecordingTaskDialog action={action} recordingId={recordingId} people={people} departments={departments} onClose={() => setOpen(false)} onCreated={async id => { setCreatedId(id); setOpen(false); await onCreated() }} />}
    {editor && <RecordingTaskDialog action={action} recordingId={recordingId} task={editor.task} people={editor.people} departments={editor.departments} onClose={() => setEditor(null)} onCreated={async id => { const task: Task = await recordingJson(await apiFetch(`/tasks/${id}`, { cache: "no-store" })); setSavedTask(task); await onCreated(); setEditor(null) }} />}
  </>
}

export function RecordingAnalysisPanel({ recordingId, onSeek }: { recordingId: string; onSeek?: (seconds: number) => void }) {
  const { apiFetch } = useAuth()
  const [data, setData] = React.useState<Analysis | null>(null)
  const [language, setLanguage] = React.useState("sq")
  const [consent, setConsent] = React.useState(false)
  const [transcriptOpen, setTranscriptOpen] = React.useState(false)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState("")
  const [people, setPeople] = React.useState<RecordingPerson[]>([])
  const [departments, setDepartments] = React.useState<RecordingDepartment[]>([])
  const load = React.useCallback(async () => {
    const next: Analysis = await recordingJson(await apiFetch(`/meeting-recordings/${recordingId}/analysis`, { cache: "no-store" }))
    setData(next)
    if (next.analysis) setLanguage(next.analysis.language)
  }, [apiFetch, recordingId])
  React.useEffect(() => { void Promise.resolve().then(load).catch(e => setError(String(e))) }, [load])
  const processing = Boolean(data?.analysis && ["QUEUED", "TRANSCRIBING", "SUMMARIZING"].includes(data.analysis.status))
  const timingProcessing = Boolean(data?.timing && ["QUEUED", "RUNNING"].includes(data.timing.status))
  React.useEffect(() => {
    if (!processing && !timingProcessing) return
    const timer = setInterval(() => { void load().then(() => setError("")).catch(e => setError(String(e))) }, 5000)
    return () => clearInterval(timer)
  }, [processing, timingProcessing, load])
  const needLookups = Boolean(data?.can_manage && data.actions.length)
  React.useEffect(() => {
    if (!needLookups) return
    void Promise.all([
      apiFetch("/users/lookup").then(recordingJson).then(setPeople),
      apiFetch("/departments").then(recordingJson).then(setDepartments),
    ]).catch(e => setError(String(e)))
  }, [apiFetch, needLookups])
  const start = async () => {
    if (busy) return
    setBusy(true); setError("")
    try {
      await recordingJson(await apiFetch(`/meeting-recordings/${recordingId}/analysis`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ language, consent_acknowledged: consent }) }))
      await load()
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  const requestTimes = async () => {
    if (busy || timingProcessing) return
    setBusy(true); setError("")
    try {
      await recordingJson(await apiFetch(`/meeting-recordings/${recordingId}/citation-times`, { method: "POST" }))
      await load()
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  return <Card><CardHeader><CardTitle>Transkripti, përmbledhja dhe detyrat</CardTitle></CardHeader><CardContent className="space-y-5">
    {!data && !error && <p role="status">Duke ngarkuar…</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {data && <>
      {!data.configured && <p role="alert" className="text-sm text-amber-700 dark:text-amber-300">Shërbimi AI nuk është konfiguruar. Administratori duhet të vendosë OPENAI_API_KEY në server dhe të nisë worker-in e përpunimit.</p>}
      {data.analysis && <div role="status" className="space-y-2">
        <p>{STATUS[data.analysis.status]} · {data.analysis.segments_done}/{data.analysis.total_segments} pjesë</p>
        {processing && <progress className="w-full" max={data.analysis.total_segments} value={data.analysis.segments_done} aria-label="Progresi i transkriptimit" />}
        {processing && <p className="text-sm text-muted-foreground">Mund ta mbyllësh faqen. Përpunimi vazhdon në server; rifresko për të parë progresin.</p>}
        {data.analysis.error_message && <p role="alert" className="text-sm text-destructive">{data.analysis.error_message}</p>}
      </div>}
      {data.segments.length > 0 && <div className="space-y-3">
        <Button variant="outline" aria-expanded={transcriptOpen} aria-controls="recording-transcript" onClick={() => setTranscriptOpen(open => !open)}>
          <FileText aria-hidden="true" />{transcriptOpen ? "Fshih transkriptin" : "Shiko transkriptin"}<ChevronDown aria-hidden="true" className={transcriptOpen ? "rotate-180" : ""} />
        </Button>
        {transcriptOpen && <section id="recording-transcript" aria-label="Transkripti" className="max-h-[32rem] space-y-4 overflow-y-auto rounded-md border bg-muted/20 p-4" tabIndex={0}>
        <h3 className="font-semibold">Transkripti ({data.segments.length} pjesë)</h3>
        {data.segments.map(segment => <div key={segment.index} className="space-y-3">
          <p className="text-xs text-muted-foreground">{recordingTime(segment.start_seconds)} – {recordingTime(segment.start_seconds + segment.duration_seconds)}</p>
          {transcriptParagraphs(segment.text, data.actions.filter(action => action.segment_index === segment.index).map(action => action.evidence)).map((paragraph, i) => <p key={i} className="text-sm leading-relaxed">{paragraph}</p>)}
          {!segment.text && <p className="text-sm text-muted-foreground">Nuk u dallua të folur në këtë pjesë.</p>}
        </div>)}
      </section>}
      </div>}
      {data.can_start_analysis && (!data.analysis || data.analysis.status === "FAILED") && <div className="space-y-3 rounded-md border p-4">
        <div className="max-w-xs"><Label htmlFor="transcript-language">Gjuha e bisedës</Label><select id="transcript-language" className={selectClass} value={language} disabled={Boolean(data.analysis)} onChange={e => setLanguage(e.target.value)}><option value="sq">Shqip</option><option value="en">English</option><option value="de">Deutsch</option><option value="auto">Zbulo automatikisht / e përzier</option></select></div>
        <p className="text-sm text-muted-foreground">Audioja përpunohet nga OpenAI. Kontrollo rezultatet para se të krijosh detyrat.</p>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} />Kam autorizimin për këtë përpunim të audios dhe të dhënave të pjesëmarrësve.</label>
        <Button disabled={!data.configured || !consent || busy} onClick={() => void start()}>{busy ? "Duke nisur…" : data.analysis ? "Riprovo përpunimin" : "Transkripto dhe përmblidh"}</Button>
      </div>}
      {(data.analysis?.summary || (data.analysis?.decisions?.length ?? 0) > 0) && <section aria-label="Përmbledhja e takimit" className="space-y-5 rounded-lg border bg-muted/20 p-5">
        {data.analysis?.summary && <div className="space-y-3"><h3 className="flex items-center gap-2 font-semibold"><FileText aria-hidden="true" className="size-4 text-muted-foreground" />Përmbledhja</h3><RecordingSummaryContent text={data.analysis.summary} /></div>}
        {(data.analysis?.decisions?.length ?? 0) > 0 && <div className="space-y-3 border-t pt-4"><h3 className="font-semibold">Vendimet</h3><ul className="list-disc space-y-2 pl-5 text-sm leading-7 marker:text-muted-foreground">{data.analysis!.decisions.map((d, i) => <li key={i}><RecordingSummaryContent text={d} /></li>)}</ul></div>}
      </section>}
      {data.analysis?.status === "READY" && <RecordingProtocolPanel recordingId={recordingId} configured={data.configured} />}
      {data.analysis?.status === "READY" && data.actions.length > 0 && <section aria-label="Kohët e citimeve" className="space-y-2 rounded-md border p-4">
        {data.can_manage && (!data.timing || data.timing.status === "FAILED") && <>
          <Button className="h-10 px-5 shadow-sm" disabled={busy || !data.timing_configured || data.analysis.language !== "sq"} onClick={() => void requestTimes()}><Clock3 aria-hidden="true" />{busy ? "Duke nisur…" : data.timing?.status === "FAILED" ? "Riprovo gjetjen e kohëve" : "Gjej kohët e citimeve"}</Button>
          {!data.timing_configured && <p className="text-sm text-muted-foreground">Gjetja e kohëve nuk është aktivizuar ende.</p>}
          {data.analysis.language !== "sq" && <p className="text-sm text-muted-foreground">Aktualisht mbështeten regjistrimet në shqip.</p>}
        </>}
        {timingProcessing && <p role="status">{data.timing?.status === "QUEUED" ? "Në radhë për gjetjen e kohëve…" : `Duke gjetur kohët… ${data.timing?.completed ?? 0}/${data.timing?.total ?? 0} pjesë` }</p>}
        {data.timing?.status === "READY" && <p role="status" className="text-sm text-muted-foreground">Kliko kohën pranë citimit për ta dëgjuar (e përafërt).</p>}
        {data.timing?.error && <p role="alert" className="text-sm text-destructive">{data.timing.error}</p>}
      </section>}
      <div id="recording-tasks" tabIndex={-1} className="scroll-mt-24">
      {data.actions.length > 0 && <section className="space-y-4"><h3 className="flex items-center gap-2 font-semibold"><ListTodo aria-hidden="true" className="size-4 text-muted-foreground" />Detyrat e propozuara <span className="rounded-md bg-muted px-2 py-0.5 text-xs tabular-nums text-muted-foreground">{data.actions.length}</span></h3><div className="overflow-hidden rounded-md border-2 border-slate-700 bg-background"><Table aria-label="Detyrat e regjistrimit" className="min-w-[960px] table-fixed border-collapse [&_td]:border [&_td]:border-slate-600 [&_td]:p-2 [&_td]:align-bottom [&_th]:border [&_th]:border-slate-600 [&_th]:px-2 [&_th]:align-bottom"><TableHeader className="bg-background [&_th]:h-10 [&_th]:font-medium [&_th]:uppercase"><TableRow><TableHead className="w-10">NR</TableHead><TableHead className="w-[44%]">Detyra</TableHead><TableHead className="w-[18%]">Përgjegjësi</TableHead><TableHead className="w-28">Afati</TableHead><TableHead className="w-32">Statusi</TableHead><TableHead className="w-40 text-center">Veprime</TableHead></TableRow></TableHeader><TableBody>{data.actions.map((action, index) => <ActionReview key={`${action.id}-${people.length > 0}`} action={action} number={index + 1} recordingId={recordingId} meetingId={data.meeting_id} people={people} departments={departments} canManage={data.can_manage} onCreated={load} timing={data.timing?.results?.[action.id]} timingStatus={data.timing?.status} onSeek={onSeek} />)}</TableBody></Table></div></section>}
      {data.analysis?.status === "READY" && !data.actions.length && <p className="text-sm">Nuk u gjetën veprime të konfirmuara për t’u kthyer në detyra.</p>}
      </div>

    </>}
  </CardContent></Card>
}
