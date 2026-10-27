"use client"

import * as React from "react"
import { toast } from "sonner"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"
import {
  STATUS_LABELS, clock, dayLabel, eventText, json, minutesBetween,
  type MeetingDetail, type MeetingRow, type Turn,
  type DiscordSlotReport, type DiscordReportHistory,
} from "@/lib/mira"

const ACCENT = "#2f5d8a"

// Mira's notes use **bold** section titles and "-" lists; nothing else is rendered as markup.
export function Summary({ text }: { text: string }) {
  return (
    <div className="max-w-[70ch] space-y-1.5 text-sm leading-relaxed">
      {text.split("\n").map((line, index) => (
        <p key={index} className={cn(!line.trim() && "h-2")}>
          {line.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
            part.startsWith("**") && part.endsWith("**")
              ? <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>
              : <React.Fragment key={i}>{part}</React.Fragment>)}
        </p>
      ))}
    </div>
  )
}

function TurnRow({ turn }: { turn: Turn }) {
  const minutes = minutesBetween(turn.started_at, turn.ended_at)
  return (
    <li className="grid grid-cols-[3rem_1fr_auto] items-baseline gap-3 py-2.5 text-sm">
      <span className={cn("font-semibold", turn.status === "SKIPPED" && "text-muted-foreground line-through")}>{turn.initials}</span>
      <span className="min-w-0">
        <span className="block truncate">{turn.name}</span>
        {turn.notes && <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">{turn.notes}</span>}
      </span>
      <span className="whitespace-nowrap text-xs tabular-nums text-muted-foreground">
        {turn.status === "SKIPPED" ? "nuk raportoi" : (
          <>
            {clock(turn.started_at)}–{turn.status === "ACTIVE" ? <span style={{ color: ACCENT }}>tani</span> : clock(turn.ended_at)}
            {minutes !== null && <span className="ml-2">{minutes} min</span>}
          </>
        )}
      </span>
    </li>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-8">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
      {children}
    </section>
  )
}

const REPORT_STATES = { WAITING: "Pa përgjigje", PARTIAL: "Pjesërisht i raportuar", DONE: "I raportuar" }
const TASK_STATES: Record<string, string> = {
  TODO: "🩷 Pa progres", IN_PROGRESS: "🟡 Në proces", DONE: "✅ E kryer",
  WAITING_CLIENT: "⏸ WFE", WAITING_CONFIRMATION: "Në pritje konfirmimi",
}

function ReportHistory({ history }: { history: DiscordReportHistory[] }) {
  if (!history.length) return null
  return <details className="mt-2 text-xs text-muted-foreground">
    <summary className="cursor-pointer">Historiku · {history.length}</summary>
    <ol className="mt-2 space-y-2 border-l pl-3">
      {history.map((event, i) => <li key={i}>
        <span className="tabular-nums">{clock(event.at)}</span>{" · "}
        {event.kind === "ANSWER" ? <>
          <span className="block">{event.question}</span>
          <span className="whitespace-pre-wrap text-foreground">{event.answer}</span>
          {event.expected_at && <span className="block">Vazhdimi / përfundimi: {event.expected_at}</span>}
        </> : event.kind === "SKIP" ? "Pyetja u kalua pa përgjigje" : <>
          <span className="whitespace-pre-wrap">{event.instruction}</span>
          <span className="block">{event.status === "DONE" ? "✓ " : "⚠ "}{event.message}</span>
        </>}
      </li>)}
    </ol>
  </details>
}

function DiscordReports({ reports }: { reports: DiscordSlotReport[] }) {
  return <Section title="Raportimet nga Discord">
    <div className="space-y-4">
      {reports.map(report => <article key={report.id} className="rounded-lg border">
        <header className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/30 px-4 py-3">
          <h4 className="text-sm font-semibold">{report.name}</h4>
          <span className={cn("rounded-full px-2 py-1 text-xs", report.state === "DONE" ? "bg-green-50 text-green-800" : "bg-muted text-muted-foreground")}>
            {REPORT_STATES[report.state]}
          </span>
          <p className="w-full text-xs text-muted-foreground">{report.sent_at ? `Dërguar në ${clock(report.sent_at)}` : "Në pritje të dërgimit"}</p>
        </header>
        <ul className="divide-y px-4">
          {report.tasks.map(task => <li key={task.id} className="py-3 text-sm">
            <a href={`/tasks/${task.id}`} className="whitespace-pre-wrap break-words font-medium underline-offset-4 hover:underline">{task.title}</a>
            <p className="mt-1 text-xs text-muted-foreground">
              {TASK_STATES[task.status] ?? task.status}
              {task.planned_status !== task.status && ` · në fillim: ${TASK_STATES[task.planned_status] ?? task.planned_status}`}
              {!task.available && " · jashtë listës aktuale"}
            </p>
            {task.question && !task.history.some(event => event.kind === "ANSWER") && <p className="mt-2 text-xs text-muted-foreground">Pyetja e dërguar: {task.question}</p>}
            {task.answer ? <p className="mt-2 whitespace-pre-wrap">{task.answer}</p> :
              ["TODO", "IN_PROGRESS"].includes(task.status) && task.available ? <p className="mt-2 text-xs text-muted-foreground">{task.skipped ? "E kaluar pa përgjigje" : "Pa përgjigje"}</p> : null}
            {task.expected_at && <p className="mt-1 text-xs"><span className="font-medium">Vazhdimi / përfundimi:</span> {task.expected_at}</p>}
            {task.progress_percentage != null && <p className="mt-1 text-xs">Progresi: {task.progress_percentage}%</p>}
            {task.comment && <p className="mt-1 whitespace-pre-wrap break-words text-xs"><span className="font-medium">Komenti:</span> {task.comment}</p>}
            {task.postponements?.map(request => <div key={request.id} className="mt-2 rounded bg-muted/40 p-2 text-xs">
              <p className="font-medium">Shtyrje · {request.label}</p>
              <p className="mt-1 whitespace-pre-wrap">{request.comment}</p>
              {Object.entries(request.proposed_dates).map(([field, date]) => <p key={field}>
                {field === "start_date" ? "Fillimi i propozuar" : "Afati i propozuar"}: {dayLabel(date.slice(0, 10))}
              </p>)}
            </div>)}
            <ReportHistory history={task.history} />
          </li>)}
        </ul>
        {(report.next.answer || report.tasks.every(task => task.status === "DONE")) && <div className="border-t px-4 py-3 text-sm">
          <p className="font-medium">Me çka ke me vazhdu në slotin tjetër?</p>
          <p className="mt-1 whitespace-pre-wrap">{report.next.answer ?? "Pa përgjigje"}</p>
          <ReportHistory history={report.next.history} />
        </div>}
      </article>)}
    </div>
  </Section>
}

function Detail({ detail, onBack, onResummarize, canManage }: {
  detail: MeetingDetail; onBack: () => void; onResummarize: () => void; canManage: boolean
}) {
  const [showRecorder, setShowRecorder] = React.useState(false)
  const created = detail.events.filter((e) => e.kind === "TASK_CREATED" || e.kind === "PX_NOTE")
  const invitations = detail.events.filter((e) => ["BRIEF", "GA_CALL", "GA_FALLBACK", "NOTE"].includes(e.kind))
  const done = detail.mentions.filter((m) => m.kind === "DONE")
  const strikes = detail.mentions.filter((m) => m.kind === "STRIKE")
  return (
    <article>
      <button type="button" onClick={onBack} className="mb-4 text-sm text-muted-foreground underline-offset-4 hover:underline md:hidden">
        Kthehu te lista
      </button>
      <h2 className="text-lg font-semibold">1H {detail.slot} · {dayLabel(detail.date)}</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        {STATUS_LABELS[detail.status]}{detail.status !== "DISCORD_REPORT" && <> · filloi {clock(detail.started_at)}, stafi {clock(detail.staff_started_at)}, mbaroi {clock(detail.ended_at)}</>}
        {detail.duration_minutes !== null && ` · ${detail.duration_minutes} min`}
      </p>
      {detail.error && <p className="mt-1 text-xs text-muted-foreground">Arsyeja: {detail.error}</p>}

      {!!detail.discord_reports?.length && <DiscordReports reports={detail.discord_reports} />}

      {detail.status !== "DISCORD_REPORT" && <>
      <Section title="Përmbledhja">
        {detail.summary ? <Summary text={detail.summary} /> : (
          <p className="text-sm text-muted-foreground">
            {detail.summary_status === "PENDING" ? "Mira po e shkruan përmbledhjen…" :
              detail.summary_status === "FAILED" ? "Përmbledhja nuk u krijua." : "Nuk ka përmbledhje."}
            {canManage && detail.summary_status === "FAILED" && (
              <button type="button" onClick={onResummarize} className="ml-2 text-foreground underline underline-offset-4">Provo përsëri</button>
            )}
          </p>
        )}
      </Section>

      <Section title="Radha e stafit">
        {detail.turns.length ? <ol className="divide-y">{detail.turns.map((t) => <TurnRow key={t.id} turn={t} />)}</ol>
          : <p className="text-sm text-muted-foreground">Askush nuk kishte detyra 1H në këtë slot.</p>}
      </Section>

      {(created.length > 0 || done.length > 0 || strikes.length > 0) && (
        <Section title="Çka u vendos dhe u raportua">
          <ul className="space-y-1.5 text-sm">
            {created.map((e, i) => <li key={`c${i}`}>{eventText(e)}</li>)}
            {done.map((m, i) => <li key={`d${i}`}><span className="text-muted-foreground">Done:</span> {m.text}</li>)}
            {strikes.map((m, i) => <li key={`s${i}`}><span className="text-muted-foreground">Strike:</span> {m.text}</li>)}
          </ul>
        </Section>
      )}

      <Section title="Transkripti i bisedës">
        {detail.transcript.length ? (
          <ol className="max-h-[480px] space-y-2 overflow-y-auto pr-2 text-sm">
            {detail.transcript.map((line, i) => (
              <li key={i} className="grid grid-cols-[3rem_7rem_1fr] gap-2">
                <span className="text-xs tabular-nums text-muted-foreground">{clock(line.at)}</span>
                <span className={cn("truncate text-xs font-medium", line.role === "mira" ? "" : "text-muted-foreground")}
                  style={line.role === "mira" ? { color: ACCENT } : undefined}>{line.speaker}</span>
                <span className="leading-relaxed">{line.text}</span>
              </li>
            ))}
          </ol>
        ) : <p className="text-sm text-muted-foreground">Nuk ka transkript.</p>}
      </Section>

      {detail.recorder && detail.recorder.segments.length > 0 && (
        <Section title="Regjistrimi i heshtur (për folës)">
          <button type="button" onClick={() => setShowRecorder(!showRecorder)} className="text-sm underline underline-offset-4">
            {showRecorder ? "Fshih" : `Shfaq ${detail.recorder.segments.length} segmente`}
          </button>
          {showRecorder && (
            <ol className="mt-3 max-h-[420px] space-y-1.5 overflow-y-auto pr-2 text-sm">
              {detail.recorder.segments.map((s, i) => (
                <li key={i}><span className="font-medium">{s.speaker}:</span> {s.text}</li>
              ))}
            </ol>
          )}
        </Section>
      )}

      {invitations.length > 0 && (
        <Section title="Njoftimet">
          <ul className="space-y-1 text-xs text-muted-foreground">
            {invitations.map((e, i) => <li key={i}><span className="tabular-nums">{clock(e.at)}</span> · {eventText(e)}</li>)}
          </ul>
        </Section>
      )}
      </>}
    </article>
  )
}

export function MeetingsTab({ canManage }: { canManage: boolean }) {
  const { apiFetch } = useAuth()
  const [rows, setRows] = React.useState<MeetingRow[] | null>(null)
  const [selected, setSelected] = React.useState<string | null>(null)
  const [detail, setDetail] = React.useState<MeetingDetail | null>(null)

  const load = React.useCallback(async () => {
    try {
      setRows((await json<{ items: MeetingRow[] }>(await apiFetch("/mira/meetings?limit=100"))).items)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }, [apiFetch])

  const loadDetail = React.useCallback(async (id: string) => {
    try {
      setDetail(await json<MeetingDetail>(await apiFetch(`/mira/meetings/${id}`)))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }, [apiFetch])

  React.useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), 30000)
    return () => window.clearInterval(timer)
  }, [load])
  React.useEffect(() => { if (selected) void loadDetail(selected) }, [selected, loadDetail])
  // A detail still loading for a newly selected meeting is never shown for the previous one.
  const shown = detail && detail.id === selected ? detail : null

  // A live meeting refreshes itself so the turns can be followed from PrimeFlow.
  const today = new Date().toLocaleDateString("en-CA", { timeZone: "Europe/Budapest" })
  const live = shown && (shown.status === "GA_PHASE" || shown.status === "STAFF_PHASE" || shown.summary_status === "PENDING" || shown.date === today)
  React.useEffect(() => {
    if (!live || !selected) return
    const timer = window.setInterval(() => { void loadDetail(selected); void load() }, 10000)
    return () => window.clearInterval(timer)
  }, [live, selected, loadDetail, load])

  const resummarize = async () => {
    if (!detail) return
    try {
      await json(await apiFetch(`/mira/meetings/${detail.id}/summarize`, { method: "POST" }))
      toast.success("Përmbledhja po krijohet përsëri.")
      await loadDetail(detail.id)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  if (rows && rows.length === 0) {
    return (
      <p className="py-16 text-center text-sm text-muted-foreground">Takimet dhe raportimet nga Discord do të shfaqen këtu në fillim të sloteve 1H.</p>
    )
  }

  let lastDay = ""
  return (
    <div className="grid md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
      <ul className={cn("py-3 md:border-r md:pr-4", selected && "hidden md:block")}>
        {rows?.map((row) => {
          const header = row.date !== lastDay ? dayLabel(row.date) : null
          lastDay = row.date
          return (
            <React.Fragment key={row.id}>
              {header && <li className="px-3 pb-1 pt-4 text-xs font-semibold text-muted-foreground first:pt-0">{header}</li>}
              <li>
                <button type="button" onClick={() => setSelected(row.id)} aria-current={selected === row.id}
                  className={cn("flex w-full items-baseline gap-3 rounded-md px-3 py-2.5 text-left text-sm outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                    selected === row.id ? "bg-muted" : "hover:bg-muted/60")}>
                  <span className="w-12 shrink-0 font-semibold tabular-nums">{row.slot}</span>
                  <span className="min-w-0 flex-1 truncate text-muted-foreground">
                    {row.status === "DISCORD_REPORT" ? "Raportimet e stafit" : row.people.length ? row.people.map((p) => p.initials).join(" → ") : "pa staf"}
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {(row.status === "GA_PHASE" || row.status === "STAFF_PHASE")
                      ? <span style={{ color: ACCENT }}>● live</span>
                      : row.duration_minutes !== null ? `${row.duration_minutes} min` : STATUS_LABELS[row.status]}
                  </span>
                </button>
              </li>
            </React.Fragment>
          )
        })}
      </ul>
      <section className={cn("min-w-0 py-5 md:pl-8", !selected && "hidden md:block")} aria-live="polite">
        {shown ? <Detail detail={shown} onBack={() => setSelected(null)} onResummarize={resummarize} canManage={canManage} />
          : <p className="pt-10 text-sm text-muted-foreground">Zgjidh një takim për të parë radhën, transkriptin dhe përmbledhjen.</p>}
      </section>
    </div>
  )
}
