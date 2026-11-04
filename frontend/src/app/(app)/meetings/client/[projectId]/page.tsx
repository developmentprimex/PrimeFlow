"use client"

import * as React from "react"
import Link from "next/link"
import { useParams } from "next/navigation"
import { Mic } from "lucide-react"
import { useAuth } from "@/lib/auth"
import { clock, dmy, isoDate, KIND_LABEL, readError, type MeetingKind, type MeetingNote } from "@/lib/meeting-notes"
import { NotesTable } from "@/components/meeting-notes/notes-table"
import { StatusLegend } from "@/components/meeting-notes/status-legend"
import { useUsersMap } from "@/components/meeting-notes/use-lookups"

type Period = "week" | "month" | "quarter"
type Source = "all" | "manual" | "recording"
type HistorySession = {
  meeting: { id: string; title: string; meeting_type: string; kind: MeetingKind }
  date: string
  status: string | null
  recordings: { id: string; duration_seconds: number | null }[]
  notes: MeetingNote[]
}
type History = { project: { id: string; title: string | null }; meetings: { id: string; title: string; kind: MeetingKind }[]; sessions: HistorySession[] }

const PERIODS: [Period, string, number][] = [["week", "Java e fundit", 7], ["month", "Muaji i fundit", 31], ["quarter", "3 muajt e fundit", 92]]

export default function ClientHistoryPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const { apiFetch } = useAuth()
  const users = useUsersMap()
  const [period, setPeriod] = React.useState<Period>("month")
  const [source, setSource] = React.useState<Source>("all")
  const [data, setData] = React.useState<History | null>(null)
  const [error, setError] = React.useState("")
  const [loading, setLoading] = React.useState(true)
  const days = PERIODS.find(([key]) => key === period)?.[2] ?? 31
  const to = isoDate(new Date())
  const from = isoDate(new Date(Date.now() - days * 86_400_000))

  const load = React.useCallback(async () => {
    setLoading(true)
    try {
      const response = await apiFetch(`/meeting-notes/client-history?project_id=${projectId}&date_from=${from}&date_to=${to}`, { cache: "no-store" })
      if (!response.ok) throw new Error(await readError(response, "Historia nuk u ngarkua."))
      setData((await response.json()) as History)
      setError("")
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setLoading(false) }
  }, [apiFetch, from, projectId, to])
  React.useEffect(() => { void load() }, [load])

  const replaceNote = (note: MeetingNote) => setData((current) => current && ({
    ...current, sessions: current.sessions.map((s) => ({ ...s, notes: s.notes.map((n) => n.id === note.id ? note : n) })),
  }))
  const removeNote = (noteId: string) => setData((current) => current && ({
    ...current, sessions: current.sessions.map((s) => ({ ...s, notes: s.notes.filter((n) => n.id !== noteId) })),
  }))

  const all = data?.sessions.flatMap((s) => s.notes) ?? []
  const pass = (note: MeetingNote) => source === "all" || (source === "recording" ? note.source === "RECORDING" : note.source === "MANUAL")
  const shown = all.filter(pass)
  const recN = all.filter((n) => n.source === "RECORDING").length
  const held = data?.sessions.filter((s) => s.status !== "canceled").length ?? 0
  const canceled = data?.sessions.filter((s) => s.status === "canceled").length ?? 0
  const count = (status: string) => shown.filter((n) => n.task_status === status).length
  const chips: [string, number, string][] = [
    [`Seanca (${canceled} anuluar)`, held, "bg-white rounded-md border-neutral-200"],
    ["Manuale", shown.filter((n) => n.source === "MANUAL").length, "bg-white rounded-md border-neutral-200"],
    ["Nga regjistrimi", shown.filter((n) => n.source === "RECORDING").length, "bg-violet-50 text-violet-800 rounded-md border-neutral-200"],
    ["TODO", count("TODO"), "bg-pink-200 border-slate-600"],
    ["IN PROGRESS", count("IN_PROGRESS"), "bg-yellow-200 border-slate-600"],
    ["WFE", count("WAITING_CLIENT"), "bg-[#E2C15B] text-[#4F3A00] border-slate-600"],
    ["DONE", count("DONE"), "bg-emerald-200 border-slate-600"],
  ]

  return <div className="w-full space-y-4">
    <div className="space-y-1">
      <Link href="/meetings" className="text-sm text-muted-foreground">← Takimet</Link>
      <h1 className="text-2xl font-semibold">{data?.project.title || "Klienti"} · Historia e klientit</h1>
      <p className="text-muted-foreground">Shënimet dhe detyrat nga të gjitha takimet me këtë klient, sipas seancës.</p>
    </div>

    <div className="flex flex-wrap items-center gap-3">
      <div role="tablist" aria-label="Periudha" className="inline-flex flex-wrap gap-0.5 rounded-xl bg-muted p-[3px]">
        {PERIODS.map(([key, label]) => <button key={key} type="button" role="tab" aria-selected={period === key} onClick={() => setPeriod(key)}
          className={`h-[30px] rounded-[9px] px-3 text-sm font-medium ${period === key ? "bg-white shadow-sm" : "text-neutral-600"}`}>{label}</button>)}
      </div>
      <span className="tabular-nums text-muted-foreground">{dmy(from)} – {dmy(to)}</span>
      <div className="inline-flex flex-wrap gap-1.5" aria-label="Burimi">
        {([["all", "Të gjitha", all.length], ["manual", "Manuale", all.length - recN], ["recording", "Nga regjistrimi", recN]] as [Source, string, number][]).map(([key, label, n]) =>
          <button key={key} type="button" aria-pressed={source === key} onClick={() => setSource(key)}
            className={`h-8 rounded-full border px-3 text-[13px] font-medium ${source === key ? key === "recording" ? "border-violet-600 bg-violet-100 text-violet-800" : "border-neutral-900 bg-muted" : "bg-white"}`}>{label} <span className="opacity-70">{n}</span></button>)}
      </div>
    </div>

    <div className="flex flex-wrap gap-1">{chips.map(([label, n, cls]) => <span key={label} className={`border px-2 py-1 text-xs font-bold ${cls}`}>{label} {n}</span>)}</div>

    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {loading ? <p role="status" className="text-sm text-muted-foreground">Duke ngarkuar…</p> : <div className="space-y-5">
      {data?.sessions.map((s) => {
        const notes = s.notes.filter(pass)
        if (!notes.length && s.status !== "canceled") return null
        return <section key={`${s.meeting.id}-${s.date}`} className="space-y-2">
          <div className={`flex flex-wrap items-center gap-x-3.5 gap-y-1 rounded-md border px-3 py-2 ${s.status === "canceled" ? "bg-muted text-muted-foreground" : "bg-slate-50"}`}>
            <strong className="tabular-nums">{dmy(s.date)}</strong>
            <Link href={`/meetings/${s.meeting.id}?date=${s.date}`} className="underline">{s.meeting.title}</Link>
            <span className="rounded-md border px-1.5 text-xs font-semibold">{KIND_LABEL[s.meeting.kind]}</span>
            <span className="text-[13px] text-neutral-600">{s.status === "canceled" ? "Anuluar → shënimet e hapura kaluan te seanca e radhës" : s.status === "held" ? "Mbajtur" : ""}</span>
            {s.recordings.map((rec) => <Link key={rec.id} href={`/meeting-recordings/${rec.id}`} className="inline-flex items-center gap-1 text-[13px] text-violet-800 underline"><Mic className="size-3.5" aria-hidden="true" />Regjistrimi {clock(rec.duration_seconds)}</Link>)}
          </div>
          {notes.length > 0 && <NotesTable notes={notes} kind={s.meeting.kind} users={users} onChanged={replaceNote} onRemoved={removeNote} onTasksChanged={() => void load()} />}
        </section>
      })}
      {!shown.length && <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">Nuk ka shënime për këtë periudhë.</p>}
    </div>}
    <StatusLegend />
  </div>
}
