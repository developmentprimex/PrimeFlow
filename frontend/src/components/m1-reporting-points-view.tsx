"use client"

import type { ReactNode } from "react"
import { Badge } from "@/components/ui/badge"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { TaskOneHMarkerFromLabel } from "@/components/task-one-h-marker"
import { getPlainMarkedText, renderMarkedNoteContent } from "@/lib/note-markup"
import { reportDate, reportTime } from "@/components/m3-reporting-points-view"
import type { TaskRow as GaTaskRow } from "@/components/m3-reporting-points-view"

export { reportDate, reportTime }
export type ManualKey = "plan_changes" | "reorganization"
export type ManualAnswers = Partial<Record<ManualKey, string>>

type AttendanceRow = { id: string; person: string; note?: string | null; from?: string; to?: string; start?: string; until?: string }
type NoteRow = { id: string; author?: string; content: string; created_at: string }
type TaskRow = { id: string; title: string; status: string; created_at: string; start_date?: string | null; assignees?: string; department?: string; am_pm?: string; task_type?: string; marker?: string; planned_for?: string }
export type ReportingPointsReport = {
  id: string; report_date: string; subject: string; status: string
  manual_answers: ManualAnswers
  data: { captured_until?: string; absences?: AttendanceRow[]; delays?: AttendanceRow[]; notes?: NoteRow[]; tasks?: TaskRow[]; ga_progress?: GaTaskRow[]; delivery?: GaTaskRow[] }
  generated_at: string | null; sent_at: string | null; last_error: string | null
}

const STATUS_COLORS: Record<string, string> = {
  TODO: "#FFC4ED", IN_PROGRESS: "#FFFF00", DONE: "#C4FDC4",
  WAITING_CLIENT: "#E2C15B", WAITING_CONFIRMATION: "#FFEDD5",
}
const cellClass = "border border-black px-2 py-2 whitespace-pre-wrap break-words"
const taskTitle = (value: string) => getPlainMarkedText(value).split(/\r?\n/).find((line) => line.trim())?.trim() || "—"
const noteAuthorInitials = (value?: string) => {
  const name = value?.trim() || ""
  if (/^[A-Z]{1,4}$/.test(name)) return name
  return (name.match(/\p{L}+/gu) || []).map((part) => part[0]).join("").toUpperCase() || "—"
}

function Point({ id, title, count, description, children }: {
  id: string; title: string; count?: number; description?: string; children: ReactNode
}) {
  return <section className="overflow-hidden rounded-xl border bg-card" aria-labelledby={id}>
    <div className="border-b bg-slate-50 px-5 py-4">
      <div className="flex items-center gap-3"><h3 id={id} className="font-semibold text-slate-950">{title}</h3>{count != null ? <Badge variant="secondary">{count}</Badge> : null}</div>
      {description ? <p className="mt-1 text-xs text-muted-foreground">{description}</p> : null}
    </div>
    {children}
  </section>
}

function Grid({ labels, widths, rows, empty, name, compact = false, flexColumnIndex = widths.length - 1 }: {
  labels: string[]; widths: number[]; rows: { id: string; fill: string; cells: ReactNode[] }[]; empty: string; name: string; compact?: boolean; flexColumnIndex?: number
}) {
  if (!rows.length) return <p className="px-5 py-6 text-sm text-muted-foreground">{empty}</p>
  return <div className="mx-3 my-3 overflow-x-auto sm:mx-5"><table className="table-fixed border-collapse border border-black text-xs leading-5 text-slate-950" style={{ width: compact ? widths.reduce((sum, width) => sum + width, 0) : "100%", minWidth: widths.reduce((sum, width) => sum + width, 0) }} aria-label={name}>
    <colgroup>{widths.map((width, index) => <col key={index} style={index === flexColumnIndex ? undefined : { width }} />)}</colgroup>
    <thead className="bg-slate-200"><tr>{labels.map((label, index) => <th key={label} dir={index < 2 ? "ltr" : undefined} className={`border border-black px-2 py-1.5 text-left text-[11px] font-semibold ${index < 2 ? "align-bottom" : "align-top"}`}>{label}</th>)}</tr></thead>
    <tbody>{rows.map((row) => <tr key={row.id} style={{ backgroundColor: row.fill }}>
      {row.cells.map((cell, index) => <td key={index} dir={index < 2 ? "ltr" : undefined} className={`${cellClass} ${index < 2 ? "align-bottom text-left" : "align-top"} ${index === 0 ? "font-semibold" : ""}`}>{cell}</td>)}
    </tr>)}</tbody>
  </table></div>
}

function Attendance({ rows, kind }: { rows: AttendanceRow[]; kind: "absence" | "delay" }) {
  return <Grid name={kind === "absence" ? "Mungesat" : "Vonesat"} labels={["NR", "PERSONI", "ORA"]} widths={[32, 120, 120]} compact
    empty={kind === "absence" ? "Asnjë mungesë për këtë datë." : "Asnjë vonesë për këtë datë."}
    rows={rows.map((row, index) => ({ id: row.id, fill: kind === "absence" ? "#fee2e2" : "#fef3c7", cells: [
      index + 1, <strong key="person">{row.person}</strong>,
      kind === "absence" ? `${row.from || "08:00"}–${row.to || "23:00"}` : `${row.start || "08:00"}–${row.until || "09:00"}`,
    ] }))} />
}

function Created({ rows, kind }: { rows: NoteRow[] | TaskRow[]; kind: "note" | "task" }) {
  return <Grid name={kind === "note" ? "Notes të reja" : "Detyrat e reja"} flexColumnIndex={kind === "note" ? 2 : 5}
    labels={kind === "note" ? ["NR", "KUSH", "NOTE", "KRIJUAR"] : ["NR", "KUSH", "DEP", "AM/PM", "LLOJI", "DETYRA", "SIMBOLI", "PËR KUR", "KRIJUAR"]}
    widths={kind === "note" ? [32, 48, 510, 150] : [32, 58, 55, 65, 65, 510, 60, 100, 150]}
    empty={kind === "note" ? "Asnjë note e re në këtë interval." : "Asnjë detyrë e krijuar në këtë interval."}
    rows={rows.map((row, index) => ({ id: row.id, fill: kind === "note" ? "#dbeafe" : STATUS_COLORS[(row as TaskRow).status] || "#ffffff", cells: kind === "note" ? [
      index + 1, <strong key="author">{noteAuthorInitials((row as NoteRow).author)}</strong>,
      <div key="note" className="whitespace-pre-wrap">{renderMarkedNoteContent((row as NoteRow).content)}</div>,
      `${reportDate(row.created_at)} ${reportTime(row.created_at)}`,
    ] : [
      index + 1, (row as TaskRow).assignees || "—", (row as TaskRow).department || "—",
      (row as TaskRow).am_pm || "—", (row as TaskRow).task_type || "—",
      <strong key="task">{taskTitle((row as TaskRow).title)}</strong>,
      <TaskOneHMarkerFromLabel key="marker" label={(row as TaskRow).marker} />,
      (row as TaskRow).planned_for || "—",
      `${reportDate(row.created_at)} ${reportTime(row.created_at)}`,
    ] }))} />
}

export function M1ReportingPointsView({ report, answers, disabled, onAnswerChange }: {
  report: ReportingPointsReport; answers: ManualAnswers; disabled: boolean
  onAnswerChange: (key: ManualKey, value: string) => void
}) {
  const cutoffTime = report.data.captured_until ? reportTime(report.data.captured_until) : "08:30"
  const tasks = report.data.tasks || []
  const todayTasks = tasks.filter((task) => task.start_date === report.report_date)
  const otherTasks = tasks.filter((task) => task.start_date !== report.report_date)
  const manual = (key: ManualKey, title: string) => <Point id={`m1-${key}`} title={title}>
    <div className="space-y-2 p-5"><Label htmlFor={`m1-answer-${key}`} className="text-sm">Përgjigjja / komenti</Label>
      <Textarea id={`m1-answer-${key}`} value={answers[key] || ""} disabled={disabled} maxLength={10000} autoResize
        className="min-h-24 bg-white" placeholder="Shëno përgjigjen dhe komentin." onChange={(event) => onAnswerChange(key, event.target.value)} />
    </div>
  </Point>
  return <div className="space-y-5">
    <div><h2 className="text-xl font-bold">PIKAT PËR RAPORTIM M1</h2><p className="mt-1 text-sm text-muted-foreground">Gjendja për {reportDate(report.report_date)} deri në {cutoffTime}.</p></div>
    <Point id="m1-absences" title="1. MUNGESA" count={(report.data.absences || []).length}><Attendance rows={report.data.absences || []} kind="absence" /></Point>
    <Point id="m1-delays" title="2. VONESA" count={(report.data.delays || []).length}><Attendance rows={report.data.delays || []} kind="delay" /></Point>
    {manual("plan_changes", "3. A KA NDRYSHIM TË PLANIT / PRIORITETEVE?")}
    <Point id="m1-notes" title="4. NOTES TË REJA?" count={(report.data.notes || []).length} description={`Të krijuara nga dje 16:30 deri sot ${cutoffTime}.`}><Created rows={report.data.notes || []} kind="note" /></Point>
    <Point id="m1-tasks" title="5. DETYRA TË REJA TË KRIJUARA SOT?" count={tasks.length} description={`Të krijuara sot nga 00:00 deri në ${cutoffTime}.`}>
      {([
        ["1. TË KRIJUARA SOT ME START DATE SOT", todayTasks],
        ["2. TË KRIJUARA SOT ME START DATE NË DITË TJETËR", otherTasks],
      ] as const).map(([title, rows]) => <div key={title}>
        <div className="flex items-center gap-3 border-y bg-slate-50 px-5 py-3"><h4 className="text-sm font-semibold">{title}</h4><Badge variant="secondary">{rows.length}</Badge></div>
        {rows === otherTasks && rows.some((task) => !task.start_date) ? <p className="px-5 pt-3 text-xs text-muted-foreground">Përfshihen edhe detyrat pa Start Date.</p> : null}
        <Created rows={rows} kind="task" />
      </div>)}
    </Point>
    {manual("reorganization", "6. A DUHET RIORGANIZIM?")}
    {(["ga_progress", "delivery"] as const).map((key) => <Point key={key} id={`m1-${key}`}
      title={key === "ga_progress" ? "7. DET ME GA: PERSONALISHT DHE ME SIMBOLE F, GA" : "8. SA PER DOREZIM M2?"}
      count={(report.data[key] || []).length}
      description={key === "ga_progress" ? "Detyrat AM dhe AM/PM personale me GA ose me simbolet F/GA, brenda intervalit start–due." : "Detyrat me simbolet M2 dhe M2/3, AM dhe PM, brenda intervalit start–due, si te M2."}>
      <Grid name={key === "ga_progress" ? "Detyrat me GA" : "Detyrat për dorëzim M2"} labels={["NR", "KUSH", "DEP", "PRJK", "AM/PM", "LLOJI", "SIMBOLI", "TITULLI"]}
        widths={[32, 58, 55, 96, 65, 65, 60, 450]} empty="Asnjë detyrë."
        rows={(report.data[key] || []).map((row, index) => ({ id: row.task_id,
          fill: row.deadline_important ? "#dc2626" : STATUS_COLORS[row.status] || "#ffffff",
          cells: [index + 1, row.assignees || "—", row.department || "—", row.project || "—", row.am_pm || "—",
            row.task_type || "—", <TaskOneHMarkerFromLabel key="marker" label={row.marker} />, <strong key="title">{row.title}</strong>]
            .map((cell, column) => <span key={column} style={{ color: row.deadline_important ? "white" : "black" }}>{cell}</span>),
        }))} />
    </Point>)}
  </div>
}
