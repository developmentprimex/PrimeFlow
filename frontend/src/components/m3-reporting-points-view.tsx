"use client"

import * as React from "react"
import { Badge } from "@/components/ui/badge"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"

export const MANUAL_POINTS = {
  underload: "1. NËNNGARKESË",
  overload: "2. MBINGARKESË",
  reorganization: "3. RIORGANIZIM NESER?",
} as const

export type ManualKey = keyof typeof MANUAL_POINTS | `meeting_plan:${string}`
export type ManualAnswers = Partial<Record<ManualKey, string>>
export type TaskRow = {
  task_id: string
  title: string
  assignees: string
  department: string
  project: string
  status: string
  progress: number
  am_pm?: string
  task_type?: string
  is_system_task?: boolean
  deadline_important?: boolean
  eight_am?: boolean
  marker?: string
  postponement_kind?: "start_due" | "due" | "start"
  created_date?: string | null
  start_date?: string | null
  due_date?: string | null
  old_start_date?: string | null
  old_due_date?: string | null
  comment?: string
  reason?: string
  risk?: "OK" | "RREZIK"
  category?: string
  completed_today?: number
  completed_value?: number | null
  total_value?: number | null
}

export type UnheldMeetingRow = {
  meeting_id: string; occurrence_date: string; meeting_type: "INT" | "EXT"
  title: string; time: string; participants?: string; department?: string
  origin?: "CAL" | "MANUAL" | ""; fill?: string; highlighted?: boolean
  meeting_relation?: "PARA" | "PAS" | null
  status: string; status_label: string
}

export type ReportingPointsReport = {
  id: string
  report_date: string
  subject: string
  status: string
  manual_answers: ManualAnswers
  data: Partial<Record<"postponed" | "untouched" | "same_day" | "ga_postponed", TaskRow[]>> & { unheld_meetings?: UnheldMeetingRow[] }
  realization: {
    percent: number | null
    employees: number
    comment: string
    baseline_available: boolean
    people: { user_id: string; name: string; percent: number | null }[]
    departments?: { department_id: string; code: string; name: string; percent: number | null; employees: number; comment: string }[]
  } | null
  realization_captured_at: string | null
  generated_at: string | null
  sent_at: string | null
  last_error: string | null
}

export function reportDate(value?: string | null) {
  if (!value) return "—"
  const [year, month, day] = value.slice(0, 10).split("-")
  return `${day}.${month}.${year}`
}

export function reportTime(value?: string | null) {
  if (!value) return "—"
  return new Intl.DateTimeFormat("sq-AL", { timeZone: "Europe/Tirane", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(value))
}

const STATUS_COLORS: Record<string, string> = {
  TODO: "#FFC4ED", IN_PROGRESS: "#FFFF00", WAITING_CLIENT: "#E2C15B",
  WAITING_CONFIRMATION: "#FFEDD5", DONE: "#C4FDC4",
}

function taskTitle(value: string) {
  const lines = value.replace(/\[\[\s*\/?\s*(?:added|done)\s*\]\]/gi, "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
  const title = lines.find((line) => /^[A-Z]{1,4}(?:\/[A-Z]{1,4})?\s*:\s*/i.test(line)) || lines.find((line) => !/^\d+\./.test(line)) || "—"
  return title.replace(/\s+due\s+\d{1,2}:\d{2}\s*$/i, "").replace(/\s+/g, " ").trim()
}

type TableKind = "postponed" | "untouched" | "same_day" | "ga_postponed"
type Movement = "start_due" | "due" | "start"
type Column = { key: keyof TaskRow | "nr" | "from" | "to"; label: string; width: number }

function postponementKind(row: TaskRow): Movement {
  if (row.postponement_kind) return row.postponement_kind
  const start = row.old_start_date && row.start_date && row.start_date > row.old_start_date
  const due = row.old_due_date && row.due_date && row.due_date > row.old_due_date
  return start && due ? "start_due" : start ? "start" : "due"
}

function columnsFor(kind: TableKind, movement?: Movement): Column[] {
  const columns: Column[] = [
    { key: "nr", label: "NR", width: 28 }, { key: "assignees", label: "KUSH", width: 42 },
    { key: "department", label: "DEP", width: 44 }, { key: "project", label: "PRJK", width: 96 },
    { key: "am_pm", label: "AM/PM", width: 48 }, { key: "task_type", label: "LLOJI", width: 48 },
  ]
  const moved = kind === "postponed" || kind === "ga_postponed"
  if (moved) {
    const width = movement === "start_due" ? 124 : 88
    columns.push({ key: "from", label: "NGA", width }, { key: "to", label: "NE", width })
  }
  columns.push({ key: "title", label: "TITULLI", width: 360 })
  if (movement !== "due") {
    columns.push({ key: "reason", label: "ARSYEJA", width: 124 }, { key: "comment", label: "KOMENTI", width: 160 })
  }
  if (moved) columns.push({ key: "risk", label: "VLERËSIMI", width: 80 })
  if (kind === "ga_postponed") columns.push({ key: "category", label: "KUSHTI", width: 100 })
  return columns
}

function dateRange(row: TaskRow, to: boolean, movement?: Movement) {
  const start = reportDate(to ? row.start_date : row.old_start_date)
  const due = reportDate(to ? row.due_date : row.old_due_date)
  if (movement === "start_due") return <>
    <span className="mb-0.5 block border-b-[3px] border-black pb-0.5">START: {start}</span>
    <span className="block pt-0.5">DUE: {due}</span>
  </>
  return movement === "start" ? start : due
}

function TaskGrid({ rows, kind, movement }: { rows: TaskRow[]; kind: TableKind; movement?: Movement }) {
  const orderedRows = kind === "same_day" ? rows.filter((row) => row.status !== "DONE") : rows
  if (!orderedRows.length) return <p className="px-5 py-6 text-sm text-muted-foreground">Asnjë detyrë për këtë pikë.</p>
  const columns = columnsFor(kind, movement)
  const cell = (row: TaskRow, column: Column, index: number) => {
    if (column.key === "nr") return index + 1
    if (column.key === "title") return <div className="w-full whitespace-normal break-words font-medium">{row.marker ? <strong className={`mr-1 text-sm font-black ${row.deadline_important || row.category?.includes("Deadline Important") ? "text-white" : "text-red-600"}`} data-task-symbol="true">{row.marker}</strong> : null}{taskTitle(row.title)}</div>
    if (column.key === "from" || column.key === "to") return dateRange(row, column.key === "to", movement)
    if (column.key.endsWith("_date")) return reportDate(row[column.key as "created_date" | "start_date" | "due_date"])
    return row[column.key] || "—"
  }
  return <div className="mx-3 my-3 overflow-x-auto sm:mx-5">
    <table className="w-full table-fixed border-collapse border border-black text-xs leading-5 text-slate-950" style={{ minWidth: columns.reduce((sum, column) => sum + column.width, 0) }} aria-label={kind === "untouched" ? "Detyrat TODO për datën e raportit" : kind === "same_day" ? "Detyrat sot për sot" : "Detyrat e shtyra"}>
      <colgroup>{columns.map((column) => <col key={column.key} style={column.key === "title" ? undefined : { width: column.width }} />)}</colgroup>
      <thead className="bg-slate-200"><tr>{columns.map((column) => <th key={column.key} className="border border-black px-1 py-1.5 text-left align-top text-[11px] font-semibold">{column.label}</th>)}</tr></thead>
      <tbody>{orderedRows.map((row, index) => {
        const deadline = row.deadline_important || row.category?.includes("Deadline Important")
        const system = row.is_system_task || row.task_type === "SYS"
        const eightAm = row.eight_am || /\b0?8:00\b/.test(row.title) || (!system && /\bEM\b/i.test(row.title))
        return <tr key={row.task_id} style={{ backgroundColor: deadline ? "#dc2626" : STATUS_COLORS[row.status] || "#FFFFFF", color: deadline ? "#ffffff" : "#000000" }}>
        {columns.map((column, columnIndex) => <td key={column.key} style={eightAm ? { borderTop: "3px solid #dc2626", borderBottom: "3px solid #dc2626", ...(columnIndex === 0 ? { borderLeft: "3px solid #dc2626" } : {}), ...(columnIndex === columns.length - 1 ? { borderRight: "3px solid #dc2626" } : {}) } : undefined} className={`border border-black px-1 py-1.5 align-top ${column.key === "risk" ? `font-bold ${row.risk === "RREZIK" ? "bg-red-100 text-red-900" : "bg-green-100 text-green-900"}` : "whitespace-pre-wrap break-words"}`}>
          {cell(row, column, index)}
        </td>)}
      </tr>})}</tbody>
    </table>
  </div>
}

export function ReportingTaskTable({ rows, kind }: { rows: TaskRow[]; kind: TableKind }) {
  if (kind === "untouched") return <div>{[
    { label: "DET FT DHE PRJK PA PROGRES", system: false }, { label: "DETYRAT E SISTEMIT PA PROGRES", system: true },
  ].map(({ label, system }) => <div key={label}><h4 className="border-b bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-950">{label}:</h4><TaskGrid rows={rows.filter((row) => !!(row.is_system_task || row.task_type === "SYS") === system)} kind={kind} /></div>)}</div>
  if (kind !== "postponed" && kind !== "ga_postponed") return <TaskGrid rows={rows} kind={kind} />
  const groups: { label: string; movement: Movement }[] = [
    { label: "SHTYER START DHE DUE DATE", movement: "start_due" }, { label: "SHTYER DUE DATE", movement: "due" },
  ]
  if (rows.some((row) => postponementKind(row) === "start")) groups.push({ label: "SHTYER START DATE", movement: "start" })
  return <div>{groups.map(({ label, movement }) => <div key={movement}>
    <h4 className="border-b bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-950">{label}:</h4>
    <TaskGrid rows={rows.filter((row) => postponementKind(row) === movement)} kind={kind} movement={movement} />
  </div>)}</div>
}

function Point({ title, note, rows, kind }: { title: string; note: React.ReactNode; rows: TaskRow[]; kind: Parameters<typeof ReportingTaskTable>[0]["kind"] }) {
  return <section className="overflow-hidden rounded-xl border bg-card">
    <div className="border-b px-5 py-4"><div className="flex items-center gap-3"><h3 className="font-semibold">{title}</h3><Badge variant="secondary">{rows.length}</Badge></div><p className={kind === "postponed" ? "mt-2 text-sm font-bold leading-6 text-slate-950" : "mt-1 text-xs text-muted-foreground"}>{note}</p></div>
    <ReportingTaskTable rows={rows} kind={kind} />
  </section>
}

function UnheldMeetings({ rows, reportDay, answers, disabled, onAnswerChange }: {
  rows: UnheldMeetingRow[]; reportDay: string; answers: ManualAnswers; disabled: boolean
  onAnswerChange: (key: ManualKey, value: string) => void
}) {
  const meetings = rows.filter((row) => ["canceled", "cancelled"].includes(row.status.trim().toLowerCase()) && row.occurrence_date === reportDay)
  const groups = [{ label: "TAK EXTERNE", type: "EXT" }, { label: "TAK INTERNE", type: "INT" }]
  return <section className="overflow-hidden rounded-xl border bg-card" aria-labelledby="m3-unheld-meetings">
    <div className="border-b px-5 py-4">
      <div className="flex items-center gap-3"><h3 id="m3-unheld-meetings" className="font-semibold">4. TAK INT/EXT TË ANULUARA</h3><Badge variant="secondary">{meetings.length}</Badge></div>
      <p className="mt-1 text-xs text-muted-foreground">Vetëm takimet e planifikuara për datën e raportit me status Anuluar. Shëno kur planifikohen.</p>
    </div>
    <div className="mx-3 my-3 max-w-[884px] overflow-hidden rounded-lg border sm:mx-5">{groups.map((group) => {
      const groupRows = meetings.filter((row) => row.meeting_type === group.type)
      return <div key={group.type}>
        <h4 className="bg-slate-50 px-3 py-2 text-xs font-semibold">{group.label}</h4>
        <div><table className="w-full min-w-0 table-fixed border-collapse text-xs leading-5 text-slate-950" aria-label={group.label}>
          <colgroup><col style={{ width: "4%" }} /><col style={{ width: "6%" }} /><col style={{ width: "9%" }} /><col style={{ width: "47%" }} /><col style={{ width: "34%" }} /></colgroup>
          <thead className="bg-slate-200"><tr>{["NR", "KOHA", "MBAJTUR?", "TITULLI", "KUR PLANIFIKOHEN?"].map((label) => <th key={label} className="border border-slate-200 px-2 py-1.5 text-left font-semibold">{label}</th>)}</tr></thead>
          <tbody>{groupRows.map((row, index) => {
            const key: ManualKey = `meeting_plan:${row.meeting_id}`
            const frame = row.highlighted ? "border-y-[3px] border-y-blue-600" : ""
            const cell = `border-b border-r border-slate-200 px-2 py-1.5 align-top whitespace-pre-wrap break-words ${frame}`
            return <tr key={row.meeting_id} style={{ backgroundColor: row.fill || (row.meeting_type === "INT" ? "#FFF4CC" : "#DCECFF") }}>
              <td className={`${cell} ${row.highlighted ? "border-l-[3px] border-l-blue-600" : ""}`}>{index + 1}</td>
              <td className={cell}>{row.time}</td>
              <td className={`${cell} bg-red-100 text-center font-bold text-red-800`} aria-label="Anuluar">✕</td>
              <td className={`${cell} ${row.highlighted ? "text-blue-700 font-semibold" : ""}`}>{row.meeting_relation ? <span className="mr-1.5 inline-flex rounded-full border border-slate-700 bg-white px-1.5 py-0.5 text-[9px] font-bold leading-none text-slate-950" title={row.meeting_relation === "PARA" ? "Para takimit extern" : "Pas takimit extern"}>{row.meeting_relation}</span> : null}{row.origin ? <strong className={`mr-1.5 inline-flex rounded-full px-1.5 py-0.5 text-[9px] font-bold leading-none ${row.origin === "CAL" ? "bg-teal-600 text-white" : "border border-[#D6B44C] bg-[#FFF4CC] text-amber-900"}`}>{row.origin}</strong> : null}{row.title}</td>
              <td className={`${cell} ${row.highlighted ? "border-r-[3px] border-r-blue-600" : ""}`}><Textarea aria-label={`Kur planifikohen? ${row.title}`} value={answers[key] || ""} disabled={disabled} maxLength={10000} rows={1} autoResize className="min-h-9 min-w-0 bg-white/80 py-1.5" placeholder="Shëno datën/orën e planifikuar." onChange={(event) => onAnswerChange(key, event.target.value)} /></td>
            </tr>
          })}</tbody>
        </table>{!groupRows.length ? <p className="px-3 py-4 text-sm text-muted-foreground">Asnjë takim i anuluar për këtë datë.</p> : null}</div>
      </div>
    })}</div>
  </section>
}

export function M3ReportingPointsView({ report, answers, onAnswerChange, disabled = false, meetingCommentsDisabled = disabled }: {
  report: ReportingPointsReport
  answers: ManualAnswers
  onAnswerChange: (key: ManualKey, value: string) => void
  disabled?: boolean
  meetingCommentsDisabled?: boolean
}) {
  const data = report.data
  const realization = report.realization
  const realizationDepartments = (realization?.departments || []).filter((item) => !["GA", "HR"].includes(item.code.trim().toUpperCase()))
  const manual = (key: keyof typeof MANUAL_POINTS) => <div key={key} className="space-y-2">
    <Label htmlFor={`point-${key}`} className="text-sm leading-6">{MANUAL_POINTS[key]}</Label>
    <Textarea id={`point-${key}`} value={answers[key] || ""} onChange={(event) => onAnswerChange(key, event.target.value)}
      placeholder="Shkruaj përgjigjen…" disabled={disabled} maxLength={10000} autoResize className="min-h-24" />
  </div>
  return <div className="space-y-10">
    <section className="space-y-5" aria-labelledby="m3-points-title">
      <div><h2 id="m3-points-title" className="text-xl font-bold">PIKAT PËR RAPORTIM M3</h2><p className="mt-1 text-sm text-muted-foreground">Përgjigjet manuale dhe gjendja e detyrave për {reportDate(report.report_date)}.</p></div>
      <div className="space-y-5 rounded-xl border bg-card p-5">
        {manual("underload")}{manual("overload")}{manual("reorganization")}
      </div>
      <Point title="1. DET QË JANË SHTY NGA KJO JAVË NË JAVËN TJETËR / BRENDA JAVËS" note={<>Shtyrjet e bëra gjatë ditës. <span className="rounded bg-green-100 px-1 py-0.5 text-green-900">Brenda javës: OK.</span>{" "}<span className="rounded bg-red-100 px-1 py-0.5 text-red-900">Për të premten ose javën tjetër: RREZIK.</span></>} rows={data.postponed || []} kind="postponed" />
      <Point title="2. PSE PA PREK TËRË DITËN?" note="Detyrat TODO ku data e raportit është brenda intervalit Start–Due, pavarësisht progresit të mëparshëm." rows={data.untouched || []} kind="untouched" />
      <Point title="3. SOT PËR SOT/DEADLINE - PROGRESI?" note="Vetëm detyrat që nuk janë DONE dhe kanë Creation Date, Start Date dhe Due Date në datën e këtij raporti." rows={(data.same_day || []).filter((row) => row.status !== "DONE")} kind="same_day" />
      <UnheldMeetings rows={data.unheld_meetings || []} reportDay={report.report_date} answers={answers} disabled={meetingCommentsDisabled} onAnswerChange={onAnswerChange} />
      <section className="rounded-xl border bg-card p-5" aria-labelledby="m3-realization-title">
        <h3 id="m3-realization-title" className="font-semibold">5. REALIZIMI — A MBËRRIHET?</h3>
        <p className="mt-1 text-xs text-muted-foreground">PLAN RLZ total dhe ndarja sipas departamenteve, si te Realization. Ruhet në 16:15 dhe sa herë gjenerohet raporti pas 16:15.</p>
        {realization ? <div className="mt-5 flex flex-wrap items-center gap-5">
          <div className={`rounded-xl px-5 py-3 text-3xl font-bold ${realization.percent == null ? "bg-muted" : realization.percent < 50 ? "bg-red-100 text-red-900" : "bg-green-100 text-green-900"}`}>
            <span className="mb-1 block text-xs font-semibold">PLAN RLZ TOTAL</span>
            {realization.percent == null ? "Pa të dhëna" : `${realization.percent}%`}
          </div>
          <div><p className="font-medium">{realization.comment}</p><p className="mt-1 text-xs text-muted-foreground">{realization.employees} persona · {report.realization_captured_at ? `Marrë në ${reportTime(report.realization_captured_at)}` : <><span className="rounded bg-blue-100 px-1 py-0.5 font-semibold text-blue-800">LIVE</span> në {reportTime(report.generated_at)} · ende pa u ruajtur, ruhet pas 16:15</>}</p></div>
        </div> : <p className="mt-5 rounded-lg bg-muted px-4 py-3 text-sm">Nuk ka ende një vlerë të ruajtur për orën 16:15 të kësaj date.</p>}
        {realizationDepartments.length ? <div className="mt-5 overflow-x-auto"><table className="w-auto border-collapse text-sm">
          <thead className="bg-slate-200"><tr>{["DEP", "REALIZIMI", "VLERËSIMI"].map((label) => <th key={label} className="whitespace-nowrap border border-black p-2 text-left">{label}</th>)}</tr></thead>
          <tbody>{realizationDepartments.map((item) => <tr key={item.department_id}>
            <td className="whitespace-nowrap border border-black p-2 font-semibold">{item.code}</td>
            <td className={`whitespace-nowrap border border-black p-2 font-bold ${item.percent == null ? "bg-muted" : item.percent < 50 ? "bg-red-100 text-red-900" : "bg-green-100 text-green-900"}`}>{item.percent == null ? "Pa të dhëna" : `${item.percent}%`}</td>
            <td className="border border-black p-2">{item.percent == null ? item.comment : item.percent === 50 ? "Jemi në 50%" : `Jemi ${item.percent < 50 ? "nën" : "mbi"} 50%`}</td>
          </tr>)}</tbody>
        </table></div> : realization ? <p className="mt-4 text-sm text-muted-foreground">Nuk ka ndarje sipas departamentit të ruajtur për këtë datë.</p> : null}
      </section>
    </section>
  </div>
}
