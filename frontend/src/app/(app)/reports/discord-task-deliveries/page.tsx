"use client"

import { useEffect, useRef, useState } from "react"
import { ExternalLink, RefreshCw } from "lucide-react"
import { DiscordDeliveryDetails, type DiscordDelivery } from "@/components/discord-delivery-details"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { useAuth } from "@/lib/auth"
import { getPlainMarkedText } from "@/lib/note-markup"

type Slot = "M2" | "M3"
type Status = DiscordDelivery["status"]
type Row = {
  id: string
  person: string
  initials: string
  department: string
  project: string
  am_pm: string
  task_type: string
  title: string
  symbol: string
  fill: string
  foreground: string
  eight_am: boolean
  comment: string
  deliveries: Partial<Record<Slot, DiscordDelivery>>
}
type Report = {
  report_date: string
  today: string
  checked_at: string
  timezone: string
  discord_source: "live" | "archive" | "unavailable" | "not_needed"
  comments_available: boolean
  deadlines: Record<Slot, string>
  rows: Row[]
  reporting_differences?: ReportingDifference[]
  missing_slots?: MissingSlotRow[]
  missing_slot_date?: string
  missing_morning_coverage?: { id: string; initials: string; person: string; department: string }[]
}
type TaskAppearance = { fill?: string; foreground?: string; eight_am?: boolean }
type MissingSlotRow = TaskAppearance & {
  id: string
  task_title: string
  person: string
  initials: string
  department: string
  project: string
  am_pm: string
  symbol: string
}
type ReportingDifference = TaskAppearance & {
  id: string
  field: "slot" | "marker"
  task_title: string
  person: string
  initials: string
  actor?: string
  label: string
  previous: string | null
  peers: { person: string; initials: string; label: string }[]
  reason: string
  date: string
  changed_at: string | null
}

const slots: Slot[] = ["M2", "M3"]
const eightAmBorder = "[&>*]:border-y-[3px] [&>*]:border-y-[#dc2626] [&>*:first-child]:border-l-[3px] [&>*:first-child]:border-l-[#dc2626] [&>*:last-child]:border-r-[3px] [&>*:last-child]:border-r-[#dc2626]"
const groups = [
  { id: "m2", label: "M2", slots: ["M2"] },
  { id: "m2-m3", label: "M2/3", slots: ["M2", "M3"] },
  { id: "m3", label: "M3", slots: ["M3"] },
] as const
const statusLabels: Record<Status, string> = {
  on_time: "Po",
  late: "Po · me vonesë",
  missing: "Jo",
  pending: "Në pritje",
  unlinked: "Pa lidhje Discord",
  unavailable: "I paverifikuar",
  ambiguous: "Titull i paqartë",
}

function DeliveryCell({ delivery, formatTime, label, className }: { delivery?: DiscordDelivery; formatTime: (value: string) => string; label: string; className: string }) {
  const status = delivery?.status
  const tone = status === "on_time" || status === "late" ? "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200"
    : status === "missing" ? "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200"
    : "bg-card text-muted-foreground"
  return (
    <td className={`${className} ${tone}`}>
      <span className="whitespace-nowrap text-xs font-semibold">{status ? statusLabels[status] : "—"}</span>
      {delivery?.url && delivery.verified_at && (
        <a href={delivery.url} target="_blank" rel="noreferrer"
          aria-label={`Hap mesazhin në Discord për ${label}`}
          className="mt-1 flex min-h-6 w-fit items-center gap-1 text-xs font-medium underline underline-offset-2">
          {formatTime(delivery.verified_at)} <ExternalLink className="size-3" aria-hidden="true" />
        </a>
      )}
      <DiscordDeliveryDetails delivery={delivery} label={label} />
    </td>
  )
}

function CommentCell({ row, available, save }: { row: Row; available: boolean; save: (id: string, text: string) => Promise<void> }) {
  const [draft, setDraft] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [feedback, setFeedback] = useState<{ error: boolean; text: string } | null>(null)
  if (!available) return <span className="text-xs text-muted-foreground">Ruajtja nuk është aktive.</span>

  async function submit() {
    if (draft === null || saving) return
    setSaving(true)
    setFeedback(null)
    try {
      await save(row.id, draft.trim())
      setDraft(null)
      setFeedback({ error: false, text: "U ruajt." })
    } catch {
      setFeedback({ error: true, text: "Komenti nuk u ruajt. Provo përsëri." })
    } finally {
      setSaving(false)
    }
  }

  return <div className="space-y-1.5">
    <Textarea aria-label={`Komenti për ${row.initials} · ${row.title}`} value={draft ?? row.comment ?? ""}
      rows={2} maxLength={2000} disabled={saving} placeholder="Shëno koment"
      onChange={(event) => { setDraft(event.target.value); setFeedback(null) }} />
    {(saving || (draft !== null && draft.trim() !== row.comment)) && (
      <Button size="sm" variant="outline" disabled={saving} onClick={() => void submit()}>
        {saving ? "Duke ruajtur…" : "Ruaj komentin"}
      </Button>
    )}
    {feedback && <p role={feedback.error ? "alert" : "status"} className={`text-xs ${feedback.error ? "text-destructive" : "text-muted-foreground"}`}>
      {feedback.text}
    </p>}
  </div>
}

function DeliveryTable({ group, rows, deadlines, formatTime, commentsAvailable, saveComment }: {
  group: (typeof groups)[number]
  rows: Row[]
  deadlines: Report["deadlines"]
  formatTime: (value: string) => string
  commentsAvailable: boolean
  saveComment: (rowId: string, comment: string) => Promise<void>
}) {
  const headingId = `discord-delivery-${group.id}`
  return (
    <section className="border-t">
      <h3 id={headingId} className="px-4 pt-3 text-sm font-semibold sm:px-5">Detyrat {group.label}</h3>
      {rows.length === 0 ? (
        <p className="px-4 pb-3 pt-1 text-xs text-muted-foreground sm:px-5">Asnjë detyrë për datën e zgjedhur.</p>
      ) : (
        <div className="mt-3 overflow-x-auto border-t focus-visible:outline-2 focus-visible:outline-ring" tabIndex={0} role="region" aria-labelledby={headingId}>
          <table aria-labelledby={headingId} className="w-full min-w-[62rem] border-collapse text-left text-sm">
            <thead className="bg-muted/65 text-xs font-semibold">
              <tr>
                {["Nr.", "Kush", "Dep.", "Projekti", "AM/PM", "Lloji", "Simboli", "Titulli"].map((heading) => (
                  <th key={heading} scope="col" className="whitespace-nowrap border-r px-3 py-2.5 last:border-r-0">{heading}</th>
                ))}
                {group.slots.map((slot) => (
                  <th key={slot} scope="col" className="whitespace-nowrap border-r px-3 py-2">
                    <span className="block">Po/Jo · {slot}</span>
                    <span className="font-normal text-muted-foreground">{deadlines[slot]}</span>
                  </th>
                ))}
                <th scope="col" className="min-w-52 px-3 py-2.5">Komenti</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => {
                const title = row.title.replace(/\b0?8:00\b/g, "08:00")
                const cell = "border-t border-r border-slate-500/30 px-3 py-2"
                return (
                  <tr key={row.id}
                        className={`align-top ${row.eight_am ? eightAmBorder : ""}`}
                    style={{ backgroundColor: row.fill, color: row.foreground }}>
                    <td className={`${cell} tabular-nums`}>{index + 1}</td>
                    <td className={`${cell} font-semibold`} title={row.person}>{row.initials}</td>
                    <td className={cell}>{row.department}</td>
                    <td className={`${cell} max-w-44 break-words`}>{row.project}</td>
                    <td className={`${cell} whitespace-nowrap`}>{row.am_pm}</td>
                    <td className={cell}>{row.task_type}</td>
                    <td data-task-symbol="true" className={`${cell} whitespace-nowrap font-bold`}>{row.symbol}</td>
                    <th scope="row" className={`${cell} min-w-48 break-words font-medium`}>
                      {row.eight_am && !/\b08:00\b/.test(title) && <strong className="mr-1.5">08:00</strong>}
                      {title}
                    </th>
                    {group.slots.map((slot) => <DeliveryCell key={slot} className={cell} delivery={row.deliveries[slot]}
                      formatTime={formatTime} label={`${slot} · ${row.title} · ${row.person}`} />)}
                    <td className={`${cell} min-w-52 bg-card text-card-foreground last:border-r-0`}>
                      <CommentCell row={row} available={commentsAvailable} save={saveComment} />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function ReportTaskTitle({ row }: { row: { task_title: string; eight_am?: boolean } }) {
  const [firstLine, ...lines] = getPlainMarkedText(row.task_title).trim().split(/\r?\n/)
  const heading = firstLine.trim().replace(/\b0?8:00\b/g, "08:00")
  const title = row.eight_am && !/\b08:00\b/.test(heading) ? `08:00 ${heading}` : heading || "Pa titull"
  const details = lines.join("\n").trim()
  if (!details) return title
  return <details className="group">
    <summary className="flex cursor-pointer list-none items-start gap-2 break-words focus-visible:outline-2 [&::-webkit-details-marker]:hidden">
      <span aria-hidden="true" className="inline-flex size-6 shrink-0 items-center justify-center rounded border border-current font-semibold leading-none">
        <span className="group-open:hidden">+</span><span className="hidden group-open:inline">−</span>
      </span>
      <span className="min-w-0 [overflow-wrap:anywhere]">{title}</span>
    </summary>
    <div className="mt-2 max-h-64 overflow-y-auto rounded border bg-card p-2 whitespace-pre-wrap text-card-foreground [overflow-wrap:anywhere]"
      role="region" aria-label={`Detajet për ${title}`} tabIndex={0}>{details}</div>
  </details>
}

function DifferenceTable({ field, rows, formatTime }: {
  field: ReportingDifference["field"]; rows: ReportingDifference[]; formatTime: (value: string) => string
}) {
  const id = `reporting-differences-${field}`
  const cell = "border-r border-t border-slate-500/30 px-3 py-2 align-top last:border-r-0"
  const choice = field === "slot" ? "Sloti" : "Simboli"
  return <section className="border-t">
    <h3 id={id} className="px-4 py-3 text-sm font-semibold sm:px-5">
      {field === "slot" ? "Dallimet në slote" : "Dallimet në simbole"}
    </h3>
    {rows.length === 0 ? (
      <p className="border-t px-4 py-4 text-sm text-muted-foreground sm:px-5">Asnjë dallim për datën e zgjedhur.</p>
    ) : (
      <div className="overflow-x-auto focus-visible:outline-2 focus-visible:outline-ring" tabIndex={0}
        role="region" aria-labelledby={id}>
        <table className="w-full min-w-[54rem] border-collapse text-left text-sm" aria-labelledby={id}>
          <thead className="bg-muted/65 text-xs font-semibold">
            <tr>{["Nr.", "Kush", "Titulli", choice, "Zgjedhjet e kolegëve", "Arsyeja", "Data / ora"].map((heading) => (
              <th key={heading} scope="col" className={`${cell} whitespace-nowrap`}>{heading}</th>
            ))}</tr>
          </thead>
          <tbody>{rows.map((row, index) => (
            <tr key={row.id}
              className={row.eight_am ? eightAmBorder : ""}
              style={{ backgroundColor: row.fill, color: row.foreground }}>
              <td className={cell}>{index + 1}</td>
              <td className={cell} title={row.person}>
                {row.initials}
                {row.actor && row.actor !== row.person && <span className="block text-xs">
                  Ndryshoi {row.actor}
                </span>}
              </td>
              <th scope="row" className={`${cell} w-[35%] min-w-48 max-w-80 break-words font-medium`}><ReportTaskTitle row={row} /></th>
              <td className={`${cell} min-w-24`}>{row.previous && <span>{row.previous} → </span>}<strong>{row.label}</strong></td>
              <td className={`${cell} bg-card text-card-foreground`}>
                <ul className="space-y-0.5">{row.peers.map((peer, peerIndex) => (
                  <li key={peerIndex} title={peer.person}>{peer.initials} · {peer.label}</li>
                ))}</ul>
              </td>
              <td className={`${cell} min-w-44 whitespace-pre-wrap break-words bg-card text-card-foreground`}>{row.reason || <span className="text-muted-foreground">Pa koment të regjistruar</span>}</td>
              <td className={`${cell} whitespace-nowrap tabular-nums bg-card text-card-foreground`}>
                {row.date.split("-").reverse().join(".")}
                {row.changed_at && <span className="block text-xs text-muted-foreground">Regjistruar në {formatTime(row.changed_at)}</span>}
              </td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    )}
  </section>
}

function ReportingDifferences({ rows, formatTime }: { rows: ReportingDifference[]; formatTime: (value: string) => string }) {
  return <section aria-labelledby="reporting-differences" className="min-w-0 overflow-hidden rounded-xl border bg-card">
    <h2 id="reporting-differences" className="px-4 py-4 text-base font-semibold sm:px-5">2. Dallimet në slote dhe simbole</h2>
    <DifferenceTable field="slot" rows={rows.filter((row) => row.field === "slot")} formatTime={formatTime} />
    <DifferenceTable field="marker" rows={rows.filter((row) => row.field === "marker")} formatTime={formatTime} />
  </section>
}

function MissingSlotTable({ rows, slotDate }: { rows: MissingSlotRow[]; slotDate?: string }) {
  const cell = "border-r border-t border-slate-500/30 px-3 py-2 align-top last:border-r-0"
  return <section aria-labelledby="missing-slot-tasks" className="min-w-0 overflow-hidden rounded-xl border bg-card">
    <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-4 sm:px-5">
      <h2 id="missing-slot-tasks" className="text-base font-semibold">3. Detyrat 1H pa slot</h2>
      {slotDate && <span className="text-xs text-muted-foreground">Data e slotit {slotDate.split("-").reverse().join(".")}</span>}
    </div>
    {rows.length === 0 ? (
      <p className="border-t px-4 py-4 text-sm text-muted-foreground sm:px-5">Asnjë detyrë 1H pa slot për datën e zgjedhur.</p>
    ) : (
      <div className="overflow-x-auto focus-visible:outline-2 focus-visible:outline-ring" tabIndex={0}
        role="region" aria-labelledby="missing-slot-tasks">
        <table className="w-full min-w-[44rem] border-collapse text-left text-sm" aria-labelledby="missing-slot-tasks">
          <thead className="bg-muted/65 text-xs font-semibold">
            <tr>{["Nr.", "Kush", "Dep.", "Projekti", "AM/PM", "Simboli", "Titulli"].map((heading) => (
              <th key={heading} scope="col" className={`${cell} whitespace-nowrap`}>{heading}</th>
            ))}</tr>
          </thead>
          <tbody>{rows.map((row, index) => (
            <tr key={row.id} className={row.eight_am ? eightAmBorder : ""}
              style={{ backgroundColor: row.fill, color: row.foreground }}>
              <td className={`${cell} tabular-nums`}>{index + 1}</td>
              <td className={`${cell} font-semibold`} title={row.person}>{row.initials}</td>
              <td className={cell}>{row.department}</td>
              <td className={`${cell} max-w-44 break-words`}>{row.project}</td>
              <td className={`${cell} whitespace-nowrap`}>{row.am_pm}</td>
              <td className={`${cell} whitespace-nowrap font-bold`}>{row.symbol || "—"}</td>
              <th scope="row" className={`${cell} w-1/2 min-w-48 break-words font-medium`}><ReportTaskTitle row={row} /></th>
            </tr>
          ))}</tbody>
        </table>
      </div>
    )}
  </section>
}

function MissingMorningCoverage({ rows }: { rows: NonNullable<Report["missing_morning_coverage"]> }) {
  const cell = "border-r border-t border-slate-500/30 px-3 py-2 text-left align-top last:border-r-0"
  return <section aria-labelledby="missing-morning-coverage" className="min-w-0 overflow-hidden rounded-xl border bg-card">
    <div className="space-y-1 px-4 py-4 sm:px-5">
      <h2 id="missing-morning-coverage" className="text-base font-semibold">4. Punonjësit pa detyrë për 10:00 / AM</h2>
      <p className="text-sm text-muted-foreground">Pa asnjërën nga këto detyra: 1H në 10:00, personale me dikë në AM ose me simbolin F në AM.</p>
    </div>
    {rows.length === 0 ? (
      <p className="border-t px-4 py-4 text-sm text-muted-foreground sm:px-5">Asnjë punonjës për datën e zgjedhur.</p>
    ) : (
      <table className="w-full table-fixed border-collapse text-sm" aria-labelledby="missing-morning-coverage">
        <colgroup>
          <col className="w-14" />
          <col className="w-20" />
          <col />
        </colgroup>
        <thead className="bg-muted/65 text-xs font-semibold">
          <tr>{["Nr.", "Kush", "Dep."].map((heading) => (
            <th key={heading} scope="col" className={`${cell} whitespace-nowrap`}>{heading}</th>
          ))}</tr>
        </thead>
        <tbody>{rows.map((row, index) => (
          <tr key={row.id} className="bg-red-50 text-red-950 dark:bg-red-950/60 dark:text-red-100">
            <td className={`${cell} tabular-nums`}>{index + 1}</td>
            <th scope="row" className={`${cell} font-bold text-red-700 dark:text-red-200`} title={row.person}>{row.initials}</th>
            <td className={`${cell} break-words`}>{row.department}</td>
          </tr>
        ))}</tbody>
      </table>
    )}
  </section>
}

export default function DiscordTaskDeliveriesPage() {
  const { user, loading: authLoading, apiFetch } = useAuth()
  const allowed = !!user
  const [day, setDay] = useState("")
  const [refresh, setRefresh] = useState(0)
  const [report, setReport] = useState<Report | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const commentRevision = useRef(0)

  useEffect(() => {
    if (!allowed) return
    let active = true
    let inFlight = false
    let currentDay = ""
    async function load() {
      if (inFlight) return
      inFlight = true
      const revision = commentRevision.current
      try {
        const query = day ? `?report_date=${encodeURIComponent(day)}` : ""
        const response = await apiFetch(`/discord-task-deliveries${query}`, { cache: "no-store" })
        if (!response.ok) throw new Error()
        const value: Report = await response.json()
        currentDay = value.today
        if (active) {
          if (revision === commentRevision.current) setReport(value)
          setError("")
        }
      } catch {
        if (active) setError("Raporti nuk u ngarkua. Provo përsëri me Rifresko.")
      } finally {
        inFlight = false
        if (active) setLoading(false)
      }
    }
    void load()
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible" && (!day || !currentDay || day === currentDay)) void load()
    }, 60_000)
    return () => { active = false; window.clearInterval(timer) }
  }, [allowed, apiFetch, day, refresh])

  if (authLoading) return <p className="p-6 text-sm text-muted-foreground" role="status">Duke u ngarkuar…</p>
  if (!allowed) return <p className="p-6 text-sm">Identifikohu në PrimeFlow për të hapur raportin.</p>

  const timeFormatter = new Intl.DateTimeFormat("sq-AL", {
    hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: report?.timezone,
  })
  const formatTime = (value: string) => timeFormatter.format(new Date(value))
  const groupedRows: Record<(typeof groups)[number]["id"], Row[]> = { m2: [], "m2-m3": [], m3: [] }
  for (const row of report?.rows ?? []) {
    const group = row.deliveries.M2 ? (row.deliveries.M3 ? "m2-m3" : "m2") : "m3"
    groupedRows[group].push(row)
  }
  async function saveComment(rowId: string, comment: string) {
    const reportDay = report?.report_date
    if (!reportDay) throw new Error("Missing report date")
    const response = await apiFetch(`/discord-task-deliveries/${reportDay}/comments/${encodeURIComponent(rowId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ comment }),
    })
    if (!response.ok) throw new Error("Comment save failed")
    const saved: { comment: string } = await response.json()
    commentRevision.current += 1
    setReport((current) => current?.report_date === reportDay
      ? { ...current, rows: current.rows.map((row) => row.id === rowId ? { ...row, comment: saved.comment } : row) }
      : current)
  }

  return (
    <main className="min-w-0 space-y-5 p-4 sm:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">BZ M3</h1>
          <p className="text-sm text-muted-foreground">Kontrolli ditor i detyrave M2, M2/3 dhe M3 në #det-nga-stafi-per-ga.</p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="space-y-1">
            <label htmlFor="discord-delivery-day" className="block text-sm font-medium">Data e raportit</label>
            <Input id="discord-delivery-day" type="date" value={day || report?.report_date || ""}
              max={report?.today} className="w-auto text-base sm:text-sm" onChange={(event) => {
                setLoading(true)
                setReport(null)
                setError("")
                setDay(event.target.value)
              }} />
          </div>
          <Button variant="outline" disabled={loading} onClick={() => { setLoading(true); setRefresh((value) => value + 1) }}>
            <RefreshCw className="size-4" aria-hidden="true" /> Rifresko
          </Button>
        </div>
      </header>
      {error && <p role="alert" className="rounded-md border border-destructive/40 p-3 text-sm">{error}</p>}
      {loading && <p role="status" className="text-sm text-muted-foreground">Duke kontrolluar dorëzimet…</p>}
      {report && (
        <section aria-labelledby="delivery-section" className="min-w-0 overflow-hidden rounded-xl border bg-card">
          <div className="space-y-2 p-4 sm:p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 id="delivery-section" className="text-base font-semibold">1. A janë dorëzuar detyrat?</h2>
              <div className="flex flex-wrap gap-2 text-xs font-medium tabular-nums">
                {slots.map((slot) => {
                  const deliveries = report.rows.flatMap((row) => row.deliveries[slot] ? [row.deliveries[slot]] : [])
                  return <span key={slot} className="rounded bg-muted px-2.5 py-1.5">
                    {slot} · {deliveries.filter(({ status }) => status === "on_time").length}/{deliveries.length} në kohë
                  </span>
                })}
              </div>
            </div>
            <p className="text-sm text-muted-foreground">
              Për M2/3 kontrollohen dy postime, një deri në {report.deadlines.M2} dhe një pas tij deri në {report.deadlines.M3}.
            </p>
            <p className="text-xs text-muted-foreground">Kontrolli i fundit {formatTime(report.checked_at)}</p>
            {report.discord_source === "archive" && <p role="status" className="text-sm text-muted-foreground">
              Burimi është arkivi i Discord-it. Rezultatet pa postim të gjetur mbeten të paverifikuara.
            </p>}
            {report.discord_source === "unavailable" && <p role="status" className="text-sm font-medium">
              Mesazhet e kanalit nuk u lexuan. Rifresko për të riprovuar.
            </p>}
          </div>
          {groups.map((group) => (
            <DeliveryTable key={`${report.report_date}:${group.id}`} group={group} rows={groupedRows[group.id]}
              deadlines={report.deadlines} formatTime={formatTime} commentsAvailable={report.comments_available} saveComment={saveComment} />
          ))}
        </section>
      )}
      {report && <ReportingDifferences rows={report.reporting_differences ?? []} formatTime={formatTime} />}
      {report && <MissingSlotTable rows={report.missing_slots ?? []} slotDate={report.missing_slot_date} />}
      {report && <MissingMorningCoverage rows={report.missing_morning_coverage ?? []} />}
    </main>
  )
}
