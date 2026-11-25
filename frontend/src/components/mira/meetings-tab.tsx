"use client"

import * as React from "react"
import { toast } from "sonner"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"
import {
  STATUS_LABELS, clock, dayLabel, eventText, groupTranscriptBySpeaker, json, minutesBetween, transcriptTime,
  type MeetingDetail, type Turn,
  type DiscordSlotReport, type DiscordReportHistory,
  type DiscordContinuationTask,
} from "@/lib/mira"

const ACCENT = "#2f5d8a"

// Mira's notes use **bold** section titles and "-" lists; nothing else is rendered as markup.
export function Summary({ text }: { text: string }) {
  return (
    <div className="max-w-[70ch] space-y-1.5 break-words text-sm leading-relaxed">
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
        {turn.status === "SKIPPED" ? "nuk raportoi" : turn.status === "TIMEOUT" ? "koha përfundoi · kërkon sqarim" : turn.status === "DEFERRED" ? "në pritje të kyçjes" : (
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
  WAITING_CLIENT: "⏸ WFE", WAITING_CONFIRMATION: "WFC INT",
}

function ContinuationTasks({ tasks }: { tasks: DiscordContinuationTask[] }) {
  return <ul className="mt-1 space-y-1">
    {tasks.map(task => <li key={task.id}>
      <a href={`/tasks/${task.id}`} className="break-words underline-offset-4 hover:underline">{task.title}</a>
      <span className="ml-2 text-xs text-muted-foreground">{TASK_STATES[task.status] ?? task.status} · {task.slot}</span>
    </li>)}
  </ul>
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
          {event.selected_tasks?.length ? <ContinuationTasks tasks={event.selected_tasks} /> : <span className="whitespace-pre-wrap text-foreground">{event.answer}</span>}
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
        <div className="border-b px-4 py-3 text-sm">
          <p className="font-medium">Me çka ke me vazhdu në slotin tjetër?</p>
          {report.next.selected_tasks?.length ? <ContinuationTasks tasks={report.next.selected_tasks} /> :
            <p className="mt-1 whitespace-pre-wrap">{report.next.answer ?? "Pa përgjigje"}</p>}
          <ReportHistory history={report.next.history} />
        </div>
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
      </article>)}
    </div>
  </Section>
}

function Detail({ detail, onResummarize, canManage }: {
  detail: MeetingDetail; onResummarize: () => void; canManage: boolean
}) {
  const created = detail.events.filter((e) => e.kind === "TASK_CREATED" || e.kind === "PX_NOTE")
  const invitations = detail.events.filter((e) => ["BRIEF", "GA_CALL", "GA_FALLBACK", "NOTE"].includes(e.kind))
  const done = detail.mentions.filter((m) => m.kind === "DONE")
  const strikes = detail.mentions.filter((m) => m.kind === "STRIKE")
  const replyTimes = detail.events.filter(e => e.kind === "PERFORMANCE" && e.data.kind === "generated_audio")
    .map(e => Number(e.data.duration_ms)).filter(Number.isFinite).sort((a, b) => a - b)
  const unclear = detail.events.filter(e => e.kind === "DISCUSSION" && e.data.unclear === true)
  return (
    <article>
      <h2 className="text-lg font-semibold">{detail.is_test && "🧪 TEST · "}1H {detail.slot} · {dayLabel(detail.date)}</h2>
      {detail.is_test && <p className="mt-2 text-sm text-muted-foreground">
        Provë zanore për këtë slot. Takimi real mbetet i pandryshuar; krijimet e detyrave dhe PX Notes janë të simuluara.
      </p>}
      <p className="mt-1 text-sm text-muted-foreground">
        {STATUS_LABELS[detail.status]}{detail.status !== "DISCORD_REPORT" && <> · filloi {clock(detail.started_at)}, stafi {clock(detail.staff_started_at)}, mbaroi {clock(detail.ended_at)}</>}
        {detail.duration_minutes !== null && ` · ${detail.duration_minutes} min`}
      </p>
      {detail.error && <p className="mt-1 text-xs text-muted-foreground">Arsyeja: {detail.error}</p>}

      {!!detail.discord_reports?.length && <DiscordReports reports={detail.discord_reports} />}

      {detail.status !== "DISCORD_REPORT" && <>
      {canManage && replyTimes.length > 0 && <p className="mt-3 text-xs text-muted-foreground">
        Pritja deri te audio e gjeneruar: mesatarisht {(replyTimes.reduce((a, b) => a + b, 0) / replyTimes.length / 1000).toFixed(1)} s
        {" · "}95% brenda {(replyTimes[Math.ceil(replyTimes.length * 0.95) - 1] / 1000).toFixed(1)} s
        {" · "}{replyTimes.length} matje. Koha e transmetimit dhe riprodhimit shtohet më pas.
      </p>}
      {unclear.length > 0 && <div className="mt-3 text-sm text-muted-foreground">
        <p>{unclear.length} raportime kërkojnë sqarim pas takimit:</p>
        <ul className="mt-1 list-disc pl-5">{unclear.map((event, i) => <li key={i}>
          {event.initials && `${event.initials}: `}{String(event.data.task_title ?? "Raportim i paqartë")}
        </li>)}</ul>
      </div>}
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

export function HostTranscript({ detail, includeRecorder = true }: { detail: MeetingDetail; includeRecorder?: boolean }) {
  const [showRecorder, setShowRecorder] = React.useState(false)
  const turns = groupTranscriptBySpeaker(detail.transcript, line => `${line.role}:${line.speaker}`)
  return <>
      <Section title="Transkripti i bisedës">
        {detail.transcript.length ? (
          <ol className="max-h-[480px] space-y-2 overflow-y-auto pr-2 text-sm">
            {turns.map(([line, ...continuation], i) => (
              <li key={i} className="grid grid-cols-[3rem_7rem_1fr] gap-2">
                <span className="text-xs tabular-nums text-muted-foreground">{clock(line.at)}</span>
                <span className={cn("truncate text-xs font-medium", line.role === "mira" ? "" : "text-muted-foreground")}
                  style={line.role === "mira" ? { color: ACCENT } : undefined}>{line.speaker}</span>
                <span className="whitespace-pre-wrap leading-relaxed [overflow-wrap:anywhere]">
                  {[line, ...continuation].map(part => part.text).join(" ")}
                </span>
              </li>
            ))}
          </ol>
        ) : <p className="text-sm text-muted-foreground">Nuk ka transkript.</p>}
      </Section>

      {includeRecorder && detail.recorder && detail.recorder.segments.length > 0 && (
        <Section title="Regjistrimi i heshtur (për folës)">
          <button type="button" onClick={() => setShowRecorder(!showRecorder)} className="text-sm underline underline-offset-4">
            {showRecorder ? "Fshih" : `Shfaq ${detail.recorder.segments.length} segmente`}
          </button>
          {showRecorder && (
            <ol className="mt-3 max-h-[420px] space-y-1.5 overflow-y-auto pr-2 text-sm">
              {groupTranscriptBySpeaker(detail.recorder.segments, segment => segment.speaker).map(([s, ...continuation], i) => (
                <li key={i}>
                  <span className="mr-2 text-xs tabular-nums text-violet-800 dark:text-violet-200">
                    {transcriptTime(s.start_ms)}
                  </span>
                  <span className="font-medium">{s.speaker}:</span> {[s, ...continuation].map(part => part.text).join(" ")}
                </li>
              ))}
            </ol>
          )}
        </Section>
      )}

  </>
}

export function HostMeetingPanel({ id, initial, canManage, transcript = false, includeRecorder = true }: {
  id: string; initial?: MeetingDetail; canManage: boolean; transcript?: boolean; includeRecorder?: boolean
}) {
  const { apiFetch } = useAuth()
  const [detail, setDetail] = React.useState(initial)
  const [error, setError] = React.useState("")
  const load = React.useCallback(async () => {
    try {
      setDetail(await json<MeetingDetail>(await apiFetch(`/mira/meetings/${id}`)))
      setError("")
    } catch (error) {
      setError(error instanceof Error ? error.message : "Takimi nuk u ngarkua.")
    }
  }, [apiFetch, id])

  const today = new Date().toLocaleDateString("en-CA", { timeZone: "Europe/Budapest" })
  const live = detail && (detail.status === "GA_PHASE" || detail.status === "STAFF_PHASE"
    || detail.summary_status === "PENDING" || detail.date === today)
  React.useEffect(() => {
    if (!initial) void load()
  }, [initial, load])
  React.useEffect(() => {
    if (!live) return
    const timer = window.setInterval(() => void load(), 10_000)
    return () => window.clearInterval(timer)
  }, [live, load])

  async function resummarize() {
    try {
      await json(await apiFetch(`/mira/meetings/${id}/summarize`, { method: "POST" }))
      toast.success("Përmbledhja po krijohet përsëri.")
      await load()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Përmbledhja nuk u kërkua.")
    }
  }

  return <>
    {error && <p role="alert">{error} <button type="button" className="underline" onClick={() => void load()}>Provo përsëri</button></p>}
    {detail ? (transcript
      ? detail.status !== "DISCORD_REPORT" && <HostTranscript detail={detail} includeRecorder={includeRecorder} />
      : <Detail detail={detail} canManage={canManage} onResummarize={resummarize} />)
      : !error && <p role="status">Po ngarkohet raportimi 1H…</p>}
  </>
}
