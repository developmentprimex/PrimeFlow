"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Summary } from "@/components/mira/meetings-tab"
import { useAuth } from "@/lib/auth"
import { json } from "@/lib/mira"
import { memoryKindLabels, type MemoryListItem } from "@/lib/mira-memory"

const sections = {
  discussion: "U diskutua",
  decisions: "U vendos",
  actions: "U kërkua të bëhet",
  open_points: "Mbeti e hapur",
  follow_up: "Për takimin tjetër",
} as const

type Meeting = { id: string; title: string; started_at: string; partial: boolean }
type Source = { id: string; speaker: string; start_ms: number; end_ms: number }
type MemoryPoint = Pick<MemoryListItem, "id" | "title" | "kind" | "status"> & {
  text: string
  correction: string | null
  project: string | null
  project_id?: string | null
  requested_by: string | null
  assignee: string | null
  deadline_text: string | null
  deadline_date: string | null
  questions: string[]
  answers: Record<string, string>
  sources: Source[]
  needs_follow_up: boolean
  discussion_state?: "NEW" | "REPEATED" | "RESOLVED"
}
type PreviousPoint = { id: string; title: string; text: string; meeting_id: string; meeting_title: string; date: string; status?: MemoryListItem["status"] }
type MeetingDetail = Meeting & {
  quick_summary: Record<keyof typeof sections, string[]> | null
  quick_summary_pending?: boolean
  full_notes: string | null
  error: string | null
  transcript: (Source & { text: string })[]
  memory?: { points: MemoryPoint[]; previous: PreviousPoint[]; status?: string | null }
}

const base = "/mira?tab=notetaker"
const endpoint = "/mira/notetaker/meetings"
const pageSize = 30
const views = {
  quick: "Përmbledhja e shpejtë",
  full: "Shënimet e plota",
  transcript: "Transkripti",
  open: "Pikat e hapura",
  history: "Historiku i takimeve",
  memory: "Kujtesa e takimit",
} as const

function meetingView(value: string | null): keyof typeof views {
  return value && Object.hasOwn(views, value) ? value as keyof typeof views : "quick"
}
const dateTime = new Intl.DateTimeFormat("sq-AL", { dateStyle: "medium", timeStyle: "short" })

function timestamp(ms: number) {
  const minutes = Math.floor(ms / 60_000)
  const seconds = Math.floor(ms / 1_000) % 60
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
}

function PreviousPoints({ points, title }: { points: PreviousPoint[]; title: string }) {
  if (!points.length) return null
  return <section className="space-y-2 text-sm">
    <h3 className="font-semibold">{title}</h3>
    <ul className="divide-y rounded-md border">
      {points.map((point) => <li key={point.id} className="space-y-1 px-3 py-2">
        <p className="font-medium">{point.title}{point.status === "CLOSED" && <span className="ml-2 text-xs text-muted-foreground">Mbyllur</span>}</p>
        <p>{point.text}</p>
        <Link className="text-xs underline" href={`${base}&meeting=${point.meeting_id}&view=memory`}>{point.meeting_title} · {dateTime.format(new Date(point.date))}</Link>
      </li>)}
    </ul>
  </section>
}

function Clarifications({ detail, onAnswer }: {
  detail: MeetingDetail
  onAnswer: (itemId: string, question: string, answer: string) => void
}) {
  const { apiFetch } = useAuth()
  const [editing, setEditing] = useState<{ itemId: string; question: string } | null>(null)
  const [answer, setAnswer] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const points = detail.memory?.points.filter((point) => point.questions.length > 0) ?? []
  if (!points.length) return null

  async function submit() {
    if (!editing || !answer.trim() || busy) return
    setBusy(true)
    setError("")
    try {
      const result = await json<{ question: string; answer: string }>(await apiFetch(`/mira-memory/items/${editing.itemId}/clarifications`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ meeting_id: detail.id, question: editing.question, answer }),
      }))
      onAnswer(editing.itemId, result.question, result.answer)
      setEditing(null)
    } catch (error) {
      setError(error instanceof Error ? error.message : "Përgjigjja nuk u ruajt.")
    } finally {
      setBusy(false)
    }
  }

  return <section className="text-sm">
      <h3 className="font-semibold">Kërkohet sqarim</h3>
      <ul className="mt-2 space-y-2">
        {points.map((point) => <li key={point.id}>
          <Link className="font-medium underline" href={`/mira?tab=kujtesa&item=${point.id}`}>{point.title}</Link>
          <ul className="ml-5 list-disc">{point.questions.map((question) => <li key={question}>
            {question} <button type="button" disabled={busy} className="ml-2 text-xs underline" onClick={() => {
              setEditing({ itemId: point.id, question }); setAnswer(""); setError("")
            }}>Përgjigju</button>
            {editing?.itemId === point.id && editing.question === question && <form className="my-2 max-w-lg space-y-2"
              onSubmit={(event) => { event.preventDefault(); void submit() }}>
              <Textarea aria-label={question} value={answer} maxLength={2000} rows={2} disabled={busy}
                onChange={(event) => setAnswer(event.target.value)} />
              <Button type="submit" size="sm" disabled={busy || !answer.trim()}>Ruaj sqarimin</Button>
              {error && <p role="alert">{error}</p>}
            </form>}
          </li>)}</ul>
        </li>)}
      </ul>
    </section>
}

function MeetingMemory({ detail, openOnly = false }: { detail: MeetingDetail; openOnly?: boolean }) {
  const points = (detail.memory?.points ?? []).filter((point) => !openOnly || point.needs_follow_up)
  if (!points.length) {
    const status = detail.memory?.status
    const message = status === "PENDING" || status === "RUNNING" ? "MIRA po përpunon pikat e takimit."
      : status === "FAILED" ? "Përpunimi i kujtesës dështoi."
        : openOnly ? "Nuk ka pika të hapura të ruajtura për këtë takim." : "Kujtesa e këtij takimi nuk ka pika për të shfaqur."
    return <p className="text-sm">{message}</p>
  }
  return <section className="space-y-2 text-sm">
      <h3 className="font-semibold">{openOnly ? "Çështjet që mbeten për t’u ndjekur" : "Pikat e takimit"}</h3>
      <ul className="divide-y rounded-md border">
        {points.map((point) => <li key={point.id} className="space-y-1 px-3 py-2">
          <Link className="font-medium underline" href={`/mira?tab=kujtesa&item=${point.id}`}>{point.title}</Link>
          <p className="text-xs text-muted-foreground">
            {memoryKindLabels[point.kind]} · {point.status === "OPEN" ? "Hapur" : "Mbyllur"}
            {point.discussion_state === "NEW" && " · Pikë e re"}
            {point.discussion_state === "REPEATED" && " · Diskutuar më parë"}
            {point.discussion_state === "RESOLVED" && " · Zgjidhur në këtë takim"}
          </p>
          <p>{point.text}</p>
          {point.correction && <p><strong>Korrigjimi</strong> {point.correction}</p>}
          {Object.entries(point.answers).map(([question, answer]) => <div key={question}>
            <p className="font-medium">{question}</p><p>{answer}</p>
          </div>)}
          {(point.project || point.requested_by || point.assignee || point.deadline_text) && <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
            {point.project && <div><dt className="inline font-medium">Projekti ose klienti</dt> <dd className="inline">
              {point.project_id ? <Link className="underline" href={`/projects/${point.project_id}`}>{point.project}</Link> : point.project}
            </dd></div>}
            {point.requested_by && <div><dt className="inline font-medium">Kërkuar nga</dt> <dd className="inline">{point.requested_by}</dd></div>}
            {point.assignee && <div><dt className="inline font-medium">Përgjegjës</dt> <dd className="inline">{point.assignee}</dd></div>}
            {point.deadline_text && <div><dt className="inline font-medium">Afati</dt> <dd className="inline">{point.deadline_date ?? point.deadline_text}</dd></div>}
          </dl>}
          {point.sources.length > 0 && <ul className="flex flex-wrap gap-x-3 text-xs">
            {point.sources.map((source) => <li key={source.id}>
              <Link className="underline" href={`${base}&meeting=${detail.id}&view=transcript#segment-${source.id}`}>
                {source.speaker} · {timestamp(source.start_ms)}–{timestamp(source.end_ms)}
              </Link>
            </li>)}
          </ul>}
        </li>)}
      </ul>
    </section>
}

export function NotetakerTab({ meetingId, view }: { meetingId: string | null; view: string | null }) {
  const { apiFetch, user } = useAuth()
  const [offset, setOffset] = useState(0)
  const [items, setItems] = useState<Meeting[] | null>(null)
  const [detail, setDetail] = useState<MeetingDetail | null>(null)
  const [followUp, setFollowUp] = useState<{ query: string; points: PreviousPoint[] } | null>(null)
  const [queryDraft, setQueryDraft] = useState("")
  const [followUpQuery, setFollowUpQuery] = useState("")
  const [error, setError] = useState<{ key: string; message: string } | null>(null)
  const [summaryRequest, setSummaryRequest] = useState<{ id: string; error?: string } | null>(null)
  const [transcriptAnchor, setTranscriptAnchor] = useState("")
  const selected = meetingView(view)
  const requestKey = meetingId ?? `page-${offset}`

  useEffect(() => {
    let ignore = false
    async function load() {
      try {
        if (meetingId) {
          const record = await json<MeetingDetail>(await apiFetch(`${endpoint}/${encodeURIComponent(meetingId)}`))
          if (!ignore) {
            setDetail(record)
            setError(null)
          }
        } else {
          const params = new URLSearchParams({ limit: String(pageSize + 1), offset: String(offset) })
          if (followUpQuery) params.set("follow_up_query", followUpQuery)
          const result = await json<{ items: Meeting[]; follow_up?: PreviousPoint[] }>(await apiFetch(`${endpoint}?${params}`))
          if (!ignore) {
            setItems(result.items)
            setFollowUp({ query: followUpQuery, points: result.follow_up ?? [] })
            setError(null)
          }
        }
      } catch {
        if (!ignore) setError({ key: requestKey, message: meetingId ? "Takimi nuk mund të hapet." : "Takimet nuk u ngarkuan." })
      }
    }
    void load()
    return () => { ignore = true }
  }, [apiFetch, meetingId, offset, requestKey, followUpQuery])

  useEffect(() => {
    if (selected !== "transcript" || detail?.id !== meetingId) return
    function showSource() {
      const anchor = window.location.hash.slice(1)
      setTranscriptAnchor(anchor)
      if (anchor.startsWith("segment-")) document.getElementById(anchor)?.scrollIntoView({ block: "start" })
    }
    showSource()
    window.addEventListener("hashchange", showSource)
    return () => window.removeEventListener("hashchange", showSource)
  }, [detail, meetingId, selected])

  const pendingMeetingId = detail?.id === meetingId && detail.quick_summary_pending ? detail.id : null
  useEffect(() => {
    if (!pendingMeetingId) return
    let ignore = false
    let timer: number
    async function poll() {
      try {
        const status = await json<MeetingDetail>(await apiFetch(`${endpoint}/${pendingMeetingId}`))
        if (ignore) return
        setDetail((current) => current?.id === pendingMeetingId
          ? { ...current, quick_summary: status.quick_summary, quick_summary_pending: status.quick_summary_pending } : current)
        if (!status.quick_summary_pending) {
          if (!status.quick_summary && pendingMeetingId) {
            setSummaryRequest({ id: pendingMeetingId, error: "Përmbledhja nuk u krijua. Mund të provohet përsëri." })
          }
          return
        }
      } catch {
        // A transient request error can recover on the next poll.
      }
      if (!ignore) timer = window.setTimeout(poll, 5000)
    }
    timer = window.setTimeout(poll, 5000)
    return () => { ignore = true; window.clearInterval(timer) }
  }, [apiFetch, pendingMeetingId])

  async function requestSummary(id: string) {
    setSummaryRequest({ id })
    try {
      await json(await apiFetch(`${endpoint}/${id}/summarize`, { method: "POST" }))
      setDetail((current) => current?.id === id ? { ...current, quick_summary_pending: true } : current)
      setSummaryRequest(null)
    } catch (error) {
      setSummaryRequest({ id, error: error instanceof Error ? error.message : "Përmbledhja nuk u kërkua." })
    }
  }

  if (error?.key === requestKey) return <p role="alert" className="mt-4 text-sm">{error.message} {meetingId && <Link className="underline" href={base}>Kthehu te takimet</Link>}</p>

  if (!meetingId) return (
    <section className="mt-5 space-y-3">
      {offset === 0 && (Boolean(followUp?.points.length) || followUpQuery) && <div className="space-y-3">
        <form className="flex max-w-md gap-2" onSubmit={(event) => { event.preventDefault(); setFollowUpQuery(queryDraft.trim()) }}>
          <Input value={queryDraft} maxLength={100} onChange={(event) => setQueryDraft(event.target.value)}
            aria-label="Kërko pika të hapura sipas projektit ose temës" placeholder="Projekti ose tema" />
          <Button type="submit" variant="outline">Kërko</Button>
        </form>
        {followUp?.query === followUpQuery && (followUp.points.length
          ? <PreviousPoints points={followUp.points} title="Pika të hapura për takimet e radhës" />
          : <p className="text-sm">Nuk u gjetën pika të hapura për këtë kërkim.</p>)}
      </div>}
      {items === null ? <p role="status">Po ngarkohen takimet…</p> : items.length === 0 ? <p>Nuk ka takime për të shfaqur.</p> : (
        <ul className="divide-y rounded-md border text-sm">
          {items.slice(0, pageSize).map((item) => (
            <li key={item.id}>
              <Link href={`${base}&meeting=${item.id}`} className="flex flex-wrap justify-between gap-2 px-4 py-3 hover:bg-muted/40">
                <span className="font-medium">{item.title}</span>
                <span className="text-muted-foreground">{dateTime.format(new Date(item.started_at))}{item.partial ? " · Regjistrim i pjesshëm" : ""}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {(offset > 0 || (items?.length ?? 0) > pageSize) && <div className="flex gap-2">
        <Button variant="outline" disabled={offset === 0} onClick={() => { setItems(null); setOffset(offset - pageSize) }}>Para</Button>
        <Button variant="outline" disabled={(items?.length ?? 0) <= pageSize} onClick={() => { setItems(null); setOffset(offset + pageSize) }}>Tjetër</Button>
      </div>}
    </section>
  )

  if (!detail || detail.id !== meetingId) return <p className="mt-4 text-sm" role="status">Po ngarkohet takimi…</p>
  const quick = detail.quick_summary
  return (
    <section className="mt-5 space-y-4">
      <Link href={base} className="text-sm underline">Kthehu te takimet</Link>
      <header>
        <h2 className="text-lg font-semibold">{detail.title}</h2>
        <p className="text-sm text-muted-foreground">{dateTime.format(new Date(detail.started_at))}</p>
      </header>
      {detail.partial && <p className="rounded-md border border-amber-500/50 px-3 py-2 text-sm">Regjistrimi ose transkripti është i pjesshëm.</p>}
      <nav aria-label="Pamjet e takimit" className="flex flex-wrap gap-4 border-b pb-2 text-sm">
        {Object.entries(views).map(([key, label]) => (
          <Link key={key} href={`${base}&meeting=${detail.id}&view=${key}`} aria-current={selected === key ? "page" : undefined} className={selected === key ? "font-semibold underline" : "text-muted-foreground"}>{label}</Link>
        ))}
      </nav>
      {selected === "quick" && (quick ? Object.entries(sections).map(([key, label]) => {
        const points = quick[key as keyof typeof sections]
        return <div key={key} className="text-sm"><h3 className="font-semibold">{label}</h3>{points.length ? (
          <ul className="ml-5 mt-1 list-disc space-y-1">{points.map((point, index) => <li key={index}>{point}</li>)}</ul>
        ) : <p className="text-muted-foreground">—</p>}</div>
      }) : <div className="space-y-2 text-sm">
        {detail.quick_summary_pending ? <p role="status">MIRA po përgatit përmbledhjen nga transkripti.</p>
          : <p>{detail.transcript.length
            ? "Ky takim ka transkript të ruajtur. Përmbledhja e shpejtë ende mungon."
            : "Nuk ka të folur të transkriptuar nga i cili të krijohet përmbledhja."}</p>}
        {detail.transcript.length > 0 && <div className="flex flex-wrap items-center gap-3">
          {(user?.role === "ADMIN" || user?.role === "MANAGER") && !detail.quick_summary_pending &&
            <Button size="sm" variant="outline" disabled={summaryRequest?.id === detail.id && !summaryRequest.error}
              onClick={() => void requestSummary(detail.id)}>Gjenero përmbledhjen</Button>}
          {detail.full_notes && <Link className="underline" href={`${base}&meeting=${detail.id}&view=full`}>Hap shënimet e plota</Link>}
          <Link className="underline" href={`${base}&meeting=${detail.id}&view=transcript`}>Hap transkriptin</Link>
        </div>}
        {summaryRequest?.id === detail.id && summaryRequest.error && <p role="alert">{summaryRequest.error}</p>}
      </div>)}
      {selected === "full" && (detail.full_notes ? <Summary text={detail.full_notes} /> : <p className="text-sm">{detail.error || "Shënimet nuk janë të disponueshme."}</p>)}
      {(selected === "quick" || selected === "open" || selected === "memory") && <Clarifications key={detail.id} detail={detail}
        onAnswer={(itemId, question, answer) => setDetail((current) => {
          if (!current?.memory || current.id !== detail.id) return current
          return { ...current, memory: { ...current.memory, points: current.memory.points.map((point) => point.id === itemId
            ? { ...point, questions: point.questions.filter((value) => value !== question), answers: { ...point.answers, [question]: answer } }
            : point) } }
        })} />}
      {selected === "memory" && <MeetingMemory detail={detail} />}
      {selected === "open" && <MeetingMemory detail={detail} openOnly />}
      {selected === "history" && (detail.memory?.previous.length
        ? <PreviousPoints points={detail.memory.previous} title="Diskutimet e mëparshme" />
        : <p className="text-sm">{detail.memory?.status === "PENDING" || detail.memory?.status === "RUNNING"
          ? "MIRA po kontrollon lidhjet me takimet e mëparshme."
          : detail.memory?.status === "FAILED" ? "Përpunimi i historikut dështoi."
            : "Nuk ka diskutime të mëparshme të lidhura me këtë takim."}</p>)}
      {selected === "transcript" && (detail.transcript.length ? <ul className="divide-y rounded-md border text-sm">
        {detail.transcript.map((segment) => <li id={`segment-${segment.id}`} key={segment.id}
          data-source={transcriptAnchor === `segment-${segment.id}` ? "true" : undefined}
          className="scroll-mt-20 break-words px-4 py-2 data-[source=true]:bg-muted">
          <p className="font-medium">{segment.speaker} <span className="font-normal text-muted-foreground">{timestamp(segment.start_ms)}–{timestamp(segment.end_ms)}</span></p>
          <p className="whitespace-pre-wrap">{segment.text}</p>
        </li>)}
      </ul> : <p className="text-sm">Nuk ka segmente të transkriptuara.</p>)}
    </section>
  )
}
