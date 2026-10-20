"use client"

import * as React from "react"
import Link from "next/link"
import { useAuth } from "@/lib/auth"
import { recordingJson } from "@/lib/recording-outbox"
import { recordingTime } from "@/lib/recording-types"
import { Button } from "@/components/ui/button"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"

type Action = { id: string; segment_index: number; title: string; description: string; evidence: string; assignee_text: string | null; deadline_text: string | null; created_task_id: string | null; confirmed_at: string | null }
type Segment = { index: number; start_seconds: number; duration_seconds: number; text: string; decisions: string[] }
type Analysis = { configured: boolean; can_manage: boolean; analysis: null | { status: string; language: string; total_segments: number; segments_done: number; summary: string | null; error_message: string | null }; segments: Segment[]; actions: Action[] }
type Person = { id: string; full_name: string; department_id: string | null }
type Department = { id: string; name: string }
const STATUS: Record<string, string> = { QUEUED: "Në pritje të përpunimit", TRANSCRIBING: "Duke transkriptuar", SUMMARIZING: "Duke përgatitur përmbledhjen dhe propozimet", READY: "Përpunimi përfundoi", FAILED: "Përpunimi dështoi" }
const selectClass = "h-9 w-full rounded-md border border-input bg-background px-3 text-sm"

function ActionReview({ action, recordingId, people, departments, canManage, onCreated }: { action: Action; recordingId: string; people: Person[]; departments: Department[]; canManage: boolean; onCreated: () => Promise<void> }) {
  const { apiFetch, user } = useAuth()
  const [title, setTitle] = React.useState(action.title)
  const [description, setDescription] = React.useState(action.description)
  const [department, setDepartment] = React.useState(user?.department_id || "")
  const [assignee, setAssignee] = React.useState("")
  const [due, setDue] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState("")
  const [createdId, setCreatedId] = React.useState<string | null>(action.created_task_id)
  const submit = async () => {
    if (busy) return
    setBusy(true); setError("")
    try {
      const result: { task_id: string } = await recordingJson(await apiFetch(`/meeting-recordings/${recordingId}/actions/${action.id}/task`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, description, department_id: department, assigned_to: assignee || null, due_date: due ? new Date(due).toISOString() : null }),
      }))
      setCreatedId(result.task_id)
      await onCreated()
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  return <div className="space-y-3 rounded-md border p-4">
    <p className="text-sm text-muted-foreground">Segmenti {action.segment_index + 1} · Propozim AI — kontrolloje para krijimit</p>
    <blockquote className="border-l-2 pl-3 text-sm">{action.evidence}</blockquote>
    {(action.assignee_text || action.deadline_text) && <p className="text-sm">Në bisedë: {action.assignee_text && `përgjegjësi: ${action.assignee_text}`} {action.deadline_text && `· afati: ${action.deadline_text}`}. Zgjidhi dhe konfirmoji më poshtë.</p>}
    {createdId ? <p className="text-sm text-green-700"><Link className="underline" href={`/tasks/${createdId}`}>Hap detyrën e krijuar</Link></p>
      : action.confirmed_at ? <p className="text-sm">Detyra e konfirmuar është fshirë nga Tasks.</p>
      : canManage ? <fieldset disabled={busy} className="space-y-3">
        <div><Label htmlFor={`title-${action.id}`}>Titulli i detyrës</Label><Input id={`title-${action.id}`} value={title} maxLength={200} onChange={e => setTitle(e.target.value)} /></div>
        <div><Label htmlFor={`description-${action.id}`}>Përshkrimi</Label><Textarea id={`description-${action.id}`} value={description} maxLength={5000} onChange={e => setDescription(e.target.value)} /></div>
        <div className="grid gap-3 md:grid-cols-3">
          <div><Label htmlFor={`department-${action.id}`}>Departamenti</Label><select id={`department-${action.id}`} className={selectClass} value={department} onChange={e => setDepartment(e.target.value)}><option value="">Zgjidh departamentin</option>{departments.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></div>
          <div><Label htmlFor={`assignee-${action.id}`}>Përgjegjësi</Label><select id={`assignee-${action.id}`} className={selectClass} value={assignee} onChange={e => { setAssignee(e.target.value); const person = people.find(p => p.id === e.target.value); if (person?.department_id) setDepartment(person.department_id) }}><option value="">Pa përgjegjës</option>{people.map(p => <option key={p.id} value={p.id}>{p.full_name}</option>)}</select></div>
          <div><Label htmlFor={`due-${action.id}`}>Afati (opsional)</Label><Input id={`due-${action.id}`} type="datetime-local" value={due} onChange={e => setDue(e.target.value)} /></div>
        </div>
        <Button disabled={!department || title.trim().length < 2 || busy} onClick={() => void submit()}>{busy ? "Duke krijuar…" : "Konfirmo dhe krijo detyrën"}</Button>
      </fieldset> : <p className="text-sm">Autori i regjistrimit mund ta konfirmojë detyrën.</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </div>
}

export function RecordingAnalysisPanel({ recordingId }: { recordingId: string }) {
  const { apiFetch } = useAuth()
  const [data, setData] = React.useState<Analysis | null>(null)
  const [language, setLanguage] = React.useState("sq")
  const [consent, setConsent] = React.useState(false)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState("")
  const [people, setPeople] = React.useState<Person[]>([])
  const [departments, setDepartments] = React.useState<Department[]>([])
  const load = React.useCallback(async () => {
    const next: Analysis = await recordingJson(await apiFetch(`/meeting-recordings/${recordingId}/analysis`, { cache: "no-store" }))
    setData(next)
    if (next.analysis) setLanguage(next.analysis.language)
  }, [apiFetch, recordingId])
  React.useEffect(() => { void load().catch(e => setError(String(e))) }, [load])
  const processing = Boolean(data?.analysis && ["QUEUED", "TRANSCRIBING", "SUMMARIZING"].includes(data.analysis.status))
  React.useEffect(() => {
    if (!processing) return
    const timer = setInterval(() => { void load().then(() => setError("")).catch(e => setError(String(e))) }, 5000)
    return () => clearInterval(timer)
  }, [processing, load])
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
  return <Card><CardHeader><CardTitle>Transkripti, përmbledhja dhe detyrat</CardTitle></CardHeader><CardContent className="space-y-5">
    {!data && !error && <p role="status">Duke ngarkuar…</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {data && <>
      {!data.configured && <p role="alert" className="text-sm text-amber-700 dark:text-amber-300">Shërbimi AI nuk është konfiguruar. Administratori duhet të vendosë OPENAI_API_KEY në server dhe të nisë worker-in e përpunimit.</p>}
      {data.analysis && <div role="status" className="space-y-2">
        <p>{STATUS[data.analysis.status]} · {data.analysis.segments_done}/{data.analysis.total_segments} pjesë</p>
        <progress className="w-full" max={data.analysis.total_segments} value={data.analysis.segments_done} aria-label="Progresi i transkriptimit" />
        {processing && <p className="text-sm text-muted-foreground">Mund ta mbyllësh faqen. Përpunimi vazhdon në server; rifresko për të parë progresin.</p>}
        {data.analysis.error_message && <p role="alert" className="text-sm text-destructive">{data.analysis.error_message}</p>}
      </div>}
      {data.can_manage && (!data.analysis || data.analysis.status === "FAILED") && <div className="space-y-3 rounded-md border p-4">
        <div className="max-w-xs"><Label htmlFor="transcript-language">Gjuha e bisedës</Label><select id="transcript-language" className={selectClass} value={language} disabled={Boolean(data.analysis)} onChange={e => setLanguage(e.target.value)}><option value="sq">Shqip</option><option value="en">English</option><option value="de">Deutsch</option><option value="auto">Zbulo automatikisht / e përzier</option></select></div>
        <p className="text-sm">Audioja ndahet në pjesë dhe dërgohet te OpenAI për transkriptim; teksti përdoret për përmbledhjen në shqip dhe propozimet. Rezultatet AI duhen kontrolluar. Detyrat krijohen vetëm pasi t’i konfirmosh.</p>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} />Kam autorizimin për këtë përpunim të audios dhe të dhënave të pjesëmarrësve.</label>
        <Button disabled={!data.configured || !consent || busy} onClick={() => void start()}>{busy ? "Duke nisur…" : data.analysis ? "Riprovo përpunimin" : "Transkripto dhe përmblidh"}</Button>
      </div>}
      {data.analysis?.summary && <section className="space-y-2"><h3 className="font-semibold">Përmbledhja</h3><p className="whitespace-pre-wrap text-sm">{data.analysis.summary}</p></section>}
      {data.actions.length > 0 && <section className="space-y-3"><h3 className="font-semibold">Detyrat e propozuara ({data.actions.length})</h3>{data.actions.map(action => <ActionReview key={action.id} action={action} recordingId={recordingId} people={people} departments={departments} canManage={data.can_manage} onCreated={load} />)}</section>}
      {data.analysis?.status === "READY" && !data.actions.length && <p className="text-sm">Nuk u gjetën veprime të konfirmuara për t’u kthyer në detyra.</p>}
      {data.segments.length > 0 && <details className="rounded-md border p-4"><summary className="cursor-pointer font-semibold">Transkripti ({data.segments.length} pjesë)</summary><div className="mt-3 max-h-[32rem] space-y-4 overflow-auto">{data.segments.map(s => <div key={s.index}><p className="text-xs text-muted-foreground">{recordingTime(s.start_seconds)} – {recordingTime(s.start_seconds + s.duration_seconds)}</p><p className="whitespace-pre-wrap text-sm">{s.text || "Nuk u dallua të folur në këtë pjesë."}</p></div>)}</div></details>}
    </>}
  </CardContent></Card>
}
