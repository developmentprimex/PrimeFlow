"use client"

import { useEffect, useState } from "react"
import Image from "next/image"
import Link from "next/link"
import { ChevronRight, Pencil } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { HostMeetingPanel, Summary } from "@/components/mira/meetings-tab"
import { MeetingNotes, type MeetingNote } from "@/components/mira/notes-tab"
import { useAuth } from "@/lib/auth"
import { formatDateDMY } from "@/lib/dates"
import { dayLabel, groupTranscriptBySpeaker, json, STATUS_LABELS, transcriptTime as timestamp, type MeetingDetail as HostDetail } from "@/lib/mira"
import { memoryKindLabels, type MemoryDetail, type MemoryListItem } from "@/lib/mira-memory"
import { DEVELOPMENT_MEETING_NAME, developmentMeetingTitle } from "@/lib/mira-note-groups"
import { cn } from "@/lib/utils"

const sections = {
  discussion: "U diskutua",
  decisions: "U vendos",
  actions: "U kërkua të bëhet",
  open_points: "Mbeti e hapur",
  follow_up: "Për takimin tjetër",
} as const

export type MeetingSource = "discord" | "host" | "desktop"
type MeetingGroup = "1H" | "AI_AGENT" | "OTHER"
type Meeting = {
  id: string; source: MeetingSource; title: string; started_at: string; partial: boolean;
  group: MeetingGroup; status: string; open_count: number
  recorder?: string | null
  has_custom_title?: boolean
  created_task_count?: number
  created_note_count?: number
}
type Source = { id: string; speaker: string; start_ms: number; end_ms: number }
type TranscriptSegment = Source & { text: string; speaker_key?: number }
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
  version?: number
  needs_follow_up: boolean
  discussion_state?: "NEW" | "REPEATED" | "RESOLVED"
}
type PreviousPoint = { id: string; title: string; text: string; meeting_id: string; meeting_title: string; date: string; status?: MemoryListItem["status"] }
type MeetingDetail = Pick<Meeting, "id" | "source" | "title" | "has_custom_title"> & {
  started_at?: string
  status?: string
  partial?: boolean
  quick_summary: Record<keyof typeof sections, string[]> | null
  quick_summary_pending?: boolean
  full_notes: string | null
  error: string | null
  transcript: TranscriptSegment[]
  memory?: { points: MemoryPoint[]; previous: PreviousPoint[]; status?: string | null }
  host?: HostDetail
  host_ids: string[]
  notes: MeetingNote[]
  created_tasks?: {
    id: string; title: string; assignees: string[]; assignee_initials: string[];
    start_date: string | null; due_date: string | null
  }[]
  desktop_transcript?: string | null
  transcript_allowed?: boolean
}

const base = "/mira?tab=takimet"
const endpoint = "/mira/notetaker/meetings"
const catalog = "/mira/meeting-catalog"
const pageSize = 30
const groups = { "1H": "1H", AI_AGENT: DEVELOPMENT_MEETING_NAME, OTHER: "Të tjera" } as const
const groupColors = {
  "1H": "bg-blue-100 text-blue-900 dark:bg-blue-950 dark:text-blue-200",
  AI_AGENT: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  OTHER: "bg-violet-100 text-violet-900 dark:bg-violet-950 dark:text-violet-200",
}
const sources = { discord: "Discord", host: "1H", desktop: "Mira Desktop" }
const recordingStatuses: Record<string, string> = {
  ...STATUS_LABELS, READY: "Gati", SAVED: "Ruajtur", FAILED: "Përpunimi dështoi",
  CAPTURING: "Po regjistrohet", LISTENING: "Po regjistrohet", PROCESSING: "Po përpunohet",
}
const views = {
  quick: "Përmbledhja",
  full: "Shënimet dhe transkripti",
  memory: "Pikat e takimit",
  report: "Raportimi 1H",
} as const

export function miraMeetingUrl(id: string, source: MeetingSource = "discord", view?: string, anchor?: string) {
  return `${base}&meeting=${encodeURIComponent(id)}&source=${source}${view ? `&view=${view}` : ""}${anchor ? `#${encodeURIComponent(anchor)}` : ""}`
}

function meetingView(value: string | null): keyof typeof views {
  if (value === "transcript") return "full"
  if (value === "open" || value === "history") return "memory"
  return value && Object.hasOwn(views, value) ? value as keyof typeof views : "quick"
}

const dateTime = new Intl.DateTimeFormat("sq-AL", { dateStyle: "medium", timeStyle: "short" })
const meetingDateTime = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Budapest", day: "2-digit", month: "2-digit", year: "numeric",
  hour: "2-digit", minute: "2-digit", hourCycle: "h23",
})

function meetingDisplayTitle(meeting: Pick<MeetingDetail, "source" | "title" | "started_at" | "has_custom_title">) {
  // The recording time already appears separately when the API supplies it.
  if (meeting.has_custom_title || meeting.source !== "discord" || !meeting.started_at) return meeting.title
  return meeting.title.replace(/\s+·\s+\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}$/, "") || meeting.title
}

function meetingDisplayDate(value: string) {
  const parts = Object.fromEntries(meetingDateTime.formatToParts(new Date(value)).map(part => [part.type, part.value]))
  return `${parts.day}.${parts.month}.${parts.year} ${parts.hour}:${parts.minute}`
}

function DiscordTranscript({ segments, anchor }: { segments: TranscriptSegment[]; anchor: string }) {
  const visibleSegments = segments.filter(segment => segment.text.trim())
  if (!visibleSegments.length) return <p className="text-sm">Nuk ka segmente të transkriptuara.</p>
  const turns = groupTranscriptBySpeaker(visibleSegments, segment => segment.speaker_key ?? segment.speaker)
  return <ul className="divide-y text-sm">
    {turns.map(turn => {
      const first = turn[0]
      const end = turn.reduce((latest, segment) => Math.max(latest, segment.end_ms), first.end_ms)
      return <li key={first.id} className="grid gap-x-3 px-2 py-2 [overflow-wrap:anywhere] sm:grid-cols-[7rem_minmax(0,1fr)]">
        <span className="text-xs font-medium tabular-nums text-violet-800 dark:text-violet-200">{timestamp(first.start_ms)}–{timestamp(end)}</span>
        <div>
          <p className="font-medium">{first.speaker}</p>
          <p className="whitespace-pre-wrap">
            {turn.map((segment, index) => <span key={segment.id}>
              {index > 0 && " "}
              <span id={`segment-${segment.id}`} data-source={anchor === `segment-${segment.id}` ? "true" : undefined}
                className="scroll-mt-20 rounded-sm target:bg-violet-100 data-[source=true]:bg-violet-100 dark:target:bg-violet-950 dark:data-[source=true]:bg-violet-950">
                {segment.text}
              </span>
            </span>)}
          </p>
        </div>
      </li>
    })}
  </ul>
}

function PreviousPoints({ points, title }: { points: PreviousPoint[]; title: string }) {
  if (!points.length) return null
  return <section className="space-y-2 text-sm">
    <h3 className="font-semibold">{title}</h3>
    <ul className="divide-y rounded-md border">
      {points.map((point) => <li key={point.id} className="space-y-1 px-3 py-2">
        <p className="font-medium">{point.title}{point.status === "CLOSED" && <span className="ml-2 text-xs text-muted-foreground">Mbyllur</span>}</p>
        <p>{point.text}</p>
        <Link className="text-xs underline" href={miraMeetingUrl(point.meeting_id, "discord", "memory", `point-${point.id}`)}>{point.meeting_title} · {dateTime.format(new Date(point.date))}</Link>
      </li>)}
    </ul>
  </section>
}

function Clarifications({ detail, onAnswer }: {
  detail: MeetingDetail
  onAnswer: (itemId: string, question: string, answer: string, version?: number) => void
}) {
  const { apiFetch } = useAuth()
  const [editing, setEditing] = useState<{ itemId: string; question: string } | null>(null)
  const [answer, setAnswer] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const points = detail.memory?.points.filter((point) => point.status === "OPEN" && point.questions.length > 0) ?? []
  if (!points.length) return null

  async function submit() {
    if (!editing || !answer.trim() || busy) return
    setBusy(true)
    setError("")
    try {
      const result = await json<{ question: string; answer: string; version?: number }>(await apiFetch(`/mira-memory/items/${editing.itemId}/clarifications`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ meeting_id: detail.id, question: editing.question, answer }),
      }))
      onAnswer(editing.itemId, result.question, result.answer, result.version)
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

function MeetingMemory({ detail, filter, closing, onClose }: {
  detail: MeetingDetail
  filter: string
  closing: Set<string>
  onClose: (point: MemoryPoint) => void
}) {
  const points = (detail.memory?.points ?? []).filter((point) => filter !== "open" || point.needs_follow_up)
  if (!points.length) {
    const status = detail.memory?.status
    const message = status === "PENDING" || status === "RUNNING" ? "MIRA po përpunon pikat e takimit."
      : status === "FAILED" ? "Përpunimi i kujtesës dështoi."
        : filter === "open" ? "Nuk ka pika të hapura të ruajtura për këtë takim." : "Kujtesa e këtij takimi nuk ka pika për të shfaqur."
    return <p className="text-sm">{message}</p>
  }
  return <section className="space-y-2 text-sm">
      <ul className="divide-y rounded-md border">
        {points.map((point) => <li key={point.id} id={`point-${point.id}`} className="scroll-mt-24 space-y-1 px-3 py-2 target:bg-muted">
          <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
            <Link className="min-w-0 break-words font-medium underline" href={`/mira?tab=kujtesa&item=${point.id}`}>{point.title}</Link>
            {point.status === "OPEN" && <Button type="button" size="sm" variant="outline"
              aria-label={`Mbyll pikën ${point.title}`} disabled={closing.has(point.id)}
              onClick={() => onClose(point)}>
              {closing.has(point.id) ? "Po mbyllet…" : "Mbyll pikën"}
            </Button>}
          </div>
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
              <Link className="underline" href={miraMeetingUrl(detail.id, "discord", "transcript", `segment-${source.id}`)}>
                {source.speaker} · {timestamp(source.start_ms)}–{timestamp(source.end_ms)}
              </Link>
            </li>)}
          </ul>}
        </li>)}
      </ul>
    </section>
}

export function NotetakerTab({ meetingId, source, view, filter }: {
  meetingId: string | null; source: MeetingSource; view: string | null; filter: string | null
}) {
  const { apiFetch, user } = useAuth()
  const [offset, setOffset] = useState(0)
  const [list, setList] = useState<{ items: Meeting[]; total: number; follow_up: PreviousPoint[]; has_unlinked_notes: boolean } | null>(null)
  const [detail, setDetail] = useState<MeetingDetail | null>(null)
  const [loadedKey, setLoadedKey] = useState("")
  const [group, setGroup] = useState<MeetingGroup | "">("")
  const [search, setSearch] = useState("")
  const [query, setQuery] = useState("")
  const [showFollowUp, setShowFollowUp] = useState(false)
  const [queryDraft, setQueryDraft] = useState("")
  const [followUpQuery, setFollowUpQuery] = useState("")
  const [error, setError] = useState<{ key: string; message: string } | null>(null)
  const [reload, setReload] = useState(0)
  const [closingPoints, setClosingPoints] = useState(() => new Set<string>())
  const [summaryRequest, setSummaryRequest] = useState<{ id: string; error?: string } | null>(null)
  const [transcriptAnchor, setTranscriptAnchor] = useState("")
  const [editingTitle, setEditingTitle] = useState<{ id: string; title: string } | null>(null)
  const [savingTitle, setSavingTitle] = useState(false)
  const selected = view === null && (detail?.source === "host" || detail?.source === "desktop")
    ? detail.source === "host" ? "report" : "full"
    : meetingView(view)
  const pointFilter = filter ?? (view === "open" || view === "history" ? view : "")
  const requestKey = meetingId ? `${source}:${meetingId}` : `page-${offset}`
  const canManage = user?.role === "ADMIN" || user?.role === "MANAGER"

  useEffect(() => {
    let ignore = false
    async function load() {
      try {
        if (meetingId) {
          const record = await json<MeetingDetail>(await apiFetch(`${catalog}/${source}/${encodeURIComponent(meetingId)}`))
          if (!ignore) {
            setDetail(record)
            setLoadedKey(requestKey)
            setError(null)
          }
        } else {
          const params = new URLSearchParams({ limit: String(pageSize), offset: String(offset), query })
          if (group) params.set("group", group)
          if (followUpQuery) params.set("follow_up_query", followUpQuery)
          const result = await json<NonNullable<typeof list>>(await apiFetch(`${catalog}?${params}`))
          if (!ignore) {
            setList(result)
            setError(null)
          }
        }
      } catch {
        if (!ignore) setError({ key: requestKey, message: meetingId ? "Takimi nuk mund të hapet." : "Takimet nuk u ngarkuan." })
      }
    }
    void load()
    const timer = !meetingId && offset === 0 ? window.setInterval(() => void load(), 30_000) : undefined
    return () => { ignore = true; window.clearInterval(timer) }
  }, [apiFetch, meetingId, source, offset, requestKey, followUpQuery, group, query, reload])

  useEffect(() => {
    if (!detail || !meetingId || loadedKey !== requestKey) return
    function showSource() {
      const anchor = window.location.hash.slice(1) || (view === "transcript" ? "transkripti" : "")
      setTranscriptAnchor(anchor)
      document.getElementById(anchor)?.scrollIntoView({ block: "start" })
    }
    showSource()
    window.addEventListener("hashchange", showSource)
    return () => window.removeEventListener("hashchange", showSource)
  }, [detail, meetingId, selected, view, pointFilter, loadedKey, requestKey])

  const pendingMeetingId = meetingId && loadedKey === requestKey && detail?.quick_summary_pending ? detail.id : null
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

  async function saveMeetingTitle() {
    if (!editingTitle || !editingTitle.title.trim() || savingTitle) return
    const { id, title } = editingTitle
    setSavingTitle(true)
    try {
      const updated = await json<{ title: string }>(await apiFetch(`${catalog}/discord/${encodeURIComponent(id)}/title`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: title.trim() }),
      }))
      setList(current => current && { ...current, items: current.items.map(item => item.id === id && item.source === "discord"
        ? { ...item, title: updated.title, has_custom_title: true } : item) })
      setReload(current => current + 1)
      setEditingTitle(null)
      toast.success("Titulli u ruajt.")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Titulli nuk u ruajt.")
    } finally {
      setSavingTitle(false)
    }
  }

  async function closePoint(point: MemoryPoint) {
    if (!detail || closingPoints.has(point.id)) return
    const detailId = detail.id
    const path = `/mira-memory/items/${point.id}`
    setClosingPoints(current => new Set(current).add(point.id))
    try {
      // Older catalog responses can omit the version during a rolling release.
      let version = point.version
      if (version === undefined) {
        const latest = await json<MemoryDetail>(await apiFetch(path))
        if (latest.status !== "OPEN") {
          setReload(current => current + 1)
          return
        }
        version = latest.version
      }
      const response = await apiFetch(`${path}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "close", version }),
      })
      if (response.status === 409) setReload(current => current + 1)
      const closed = await json<MemoryDetail>(response)
      setDetail(current => {
        if (!current?.memory || current.id !== detailId) return current
        return { ...current, memory: {
          ...current.memory,
          points: current.memory.points.map(item => item.id === point.id
            ? { ...item, status: closed.status, version: closed.version, needs_follow_up: false } : item),
          previous: current.memory.previous.map(item => item.id === point.id
            ? { ...item, status: closed.status } : item),
        } }
      })
      toast.success("Pika u mbyll.")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Pika nuk u mbyll. Provo përsëri.")
    } finally {
      setClosingPoints(current => {
        const next = new Set(current)
        next.delete(point.id)
        return next
      })
    }
  }

  if (error?.key === requestKey) return <p role="alert" className="mt-4 text-sm">{error.message}{" "}
    <button type="button" className="underline" onClick={() => { setError(null); setReload(value => value + 1) }}>Provo përsëri</button>
    {meetingId && <> · <Link className="underline" href={base}>Kthehu te takimet</Link></>}
  </p>

  if (!meetingId) return (
    <section className="mt-5 space-y-3">
      <Dialog open={editingTitle !== null} onOpenChange={(open) => { if (!open && !savingTitle) setEditingTitle(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Redakto titullin e takimit</DialogTitle>
            <DialogDescription>Titulli shfaqet te Mira → Takimet.</DialogDescription>
          </DialogHeader>
          {editingTitle && <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); void saveMeetingTitle() }}>
            <Input aria-label="Titulli i takimit" value={editingTitle.title} maxLength={200} required disabled={savingTitle}
              onChange={(event) => setEditingTitle({ ...editingTitle, title: event.target.value })} />
            <DialogFooter>
              <Button type="button" variant="outline" disabled={savingTitle} onClick={() => setEditingTitle(null)}>Anulo</Button>
              <Button type="submit" disabled={savingTitle || !editingTitle.title.trim()}>{savingTitle ? "Po ruhet…" : "Ruaj"}</Button>
            </DialogFooter>
          </form>}
        </DialogContent>
      </Dialog>
      <div className="flex flex-wrap items-center gap-2">
        <form className="flex max-w-md flex-1 gap-2" onSubmit={(event) => {
          event.preventDefault(); setOffset(0); setQuery(search.trim())
        }}>
          <Input value={search} maxLength={200} onChange={(event) => setSearch(event.target.value)}
            aria-label="Kërko takime" placeholder="Kërko takime ose shënime" />
          <Button type="submit" variant="outline">Kërko</Button>
        </form>
        <Button type="button" variant={showFollowUp ? "default" : "outline"} aria-expanded={showFollowUp}
          onClick={() => { setOffset(0); setShowFollowUp(value => !value) }}>Për t’u ndjekur</Button>
        {list?.has_unlinked_notes && <Link className="text-sm underline" href={`${base}&archive=1`}>Shënime pa takim të lidhur</Link>}
      </div>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Lloji i takimit">
        {(["", "1H", "AI_AGENT", "OTHER"] as const).map(value =>
          <Button key={value} type="button" size="sm" variant={group === value ? "default" : "outline"}
            className={value && group !== value ? groupColors[value] : undefined}
            aria-pressed={group === value} onClick={() => { setOffset(0); setGroup(value) }}>
            {value ? groups[value] : "Të gjitha"}
          </Button>)}
      </div>
      {showFollowUp && <div className="space-y-3 rounded-md border p-3">
        <form className="flex max-w-md gap-2" onSubmit={(event) => { event.preventDefault(); setOffset(0); setFollowUpQuery(queryDraft.trim()) }}>
          <Input value={queryDraft} maxLength={100} onChange={(event) => setQueryDraft(event.target.value)}
            aria-label="Kërko pika të hapura sipas projektit ose temës" placeholder="Projekti ose tema" />
          <Button type="submit" variant="outline">Kërko</Button>
        </form>
        {list && (list.follow_up.length
          ? <PreviousPoints points={list.follow_up} title="Pika të hapura për takimet e radhës" />
          : <p className="text-sm">Nuk u gjetën pika të hapura.</p>)}
      </div>}
      {list === null ? <p role="status">Po ngarkohen takimet…</p> : list.items.length === 0 ? <p>Nuk ka takime për të shfaqur.</p> : (
        <ul className="divide-y overflow-hidden rounded-lg border text-sm">
          {list.items.map((item) => {
            const aiAgent = item.recorder === "ai_agent" || item.group === "AI_AGENT"
            const title = aiAgent && !item.has_custom_title ? developmentMeetingTitle(meetingDisplayTitle(item)) : meetingDisplayTitle(item)
            const tasks = item.created_task_count ?? 0
            const notes = item.created_note_count ?? 0
            return (
            <li key={`${item.source}:${item.id}`} className={cn("flex items-center",
                aiAgent ? "bg-emerald-50/70 hover:bg-emerald-100/70 dark:bg-emerald-950/25 dark:hover:bg-emerald-900/40"
                  : "bg-blue-50/70 hover:bg-blue-100/70 dark:bg-blue-950/25 dark:hover:bg-blue-900/40"
              )}>
              <Link href={miraMeetingUrl(item.id, item.source)} className="group grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 px-3 py-3 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring lg:grid-cols-[minmax(0,22rem)_8.5rem_minmax(0,1fr)_auto]">
                <span className="flex min-w-0 items-center gap-3 font-medium">
                  <Image src={aiAgent ? "/mira-ai-agent-avatar.png" : "/mira-avatar.png"} alt="" width={34} height={34}
                    className={cn("shrink-0 rounded-full border", aiAgent ? "border-emerald-400" : "border-blue-400")} />
                  <span className="min-w-0">
                    <span className="block break-words">{title}</span>
                    {(tasks > 0 || notes > 0) && <span className="mt-1 flex flex-wrap gap-x-2 gap-y-1 text-xs">
                      {tasks > 0 && <span className="rounded-full bg-blue-100 px-2 py-0.5 text-blue-900 dark:bg-blue-950 dark:text-blue-200">
                        {tasks} {tasks === 1 ? "detyrë e krijuar" : "detyra të krijuara"}
                      </span>}
                      {notes > 0 && <span className="rounded-full bg-violet-100 px-2 py-0.5 text-violet-900 dark:bg-violet-950 dark:text-violet-200">
                        {notes} {notes === 1 ? "shënim i krijuar" : "shënime të krijuara"}
                      </span>}
                    </span>}
                  </span>
                </span>
                <time dateTime={item.started_at} className="col-start-1 row-start-2 whitespace-nowrap pl-11 text-xs font-medium tabular-nums text-foreground lg:col-start-2 lg:row-start-1 lg:pl-0">
                  {meetingDisplayDate(item.started_at)}
                </time>
                <span className="col-start-1 row-start-3 flex flex-wrap items-center gap-x-2 gap-y-1 pl-11 text-xs text-muted-foreground lg:col-start-3 lg:row-start-1 lg:justify-end lg:pl-0">
                  {item.source === "desktop" && <span>{sources.desktop}</span>}
                  {recordingStatuses[item.status] && <span>{recordingStatuses[item.status]}</span>}
                  {item.partial && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-amber-900 dark:bg-amber-950 dark:text-amber-200">Regjistrim i pjesshëm</span>}
                  {item.open_count > 0 && <span className="rounded-full bg-orange-100 px-2 py-0.5 text-orange-900 dark:bg-orange-950 dark:text-orange-200">{item.open_count} {item.open_count === 1 ? "pikë e hapur" : "pika të hapura"}</span>}
                </span>
                <ChevronRight aria-hidden className="col-start-2 row-start-1 size-4 text-muted-foreground group-hover:translate-x-0.5 lg:col-start-4" />
              </Link>
              {canManage && item.source === "discord" && <Button type="button" size="icon" variant="ghost" className="mr-2 size-8 shrink-0"
                aria-label={`Redakto titullin: ${title}`} title="Redakto titullin"
                onClick={() => setEditingTitle({ id: item.id, title })}><Pencil aria-hidden className="size-4" /></Button>}
            </li>
          )})}
        </ul>
      )}
      {!showFollowUp && (offset > 0 || (list?.total ?? 0) > pageSize) && <div className="flex gap-2">
        <Button variant="outline" disabled={offset === 0} onClick={() => { setList(null); setOffset(offset - pageSize) }}>Para</Button>
        <Button variant="outline" disabled={offset + pageSize >= (list?.total ?? 0)} onClick={() => { setList(null); setOffset(offset + pageSize) }}>Tjetër</Button>
      </div>}
    </section>
  )

  if (!detail || loadedKey !== requestKey) return <p className="mt-4 text-sm" role="status">Po ngarkohet takimi…</p>
  const quick = detail.quick_summary
  const hostIds = detail.host ? [detail.host.id] : detail.host_ids
  const available = (Object.keys(views) as (keyof typeof views)[]).filter((key) =>
    key === "report" ? hostIds.length > 0 :
    key === "quick" || key === "memory" ? detail.source === "discord" :
    detail.host?.status !== "DISCORD_REPORT")
  const active = available.includes(selected) ? selected : available[0]
  const url = (key: string) => miraMeetingUrl(detail.id, detail.source, key)
  const navigation = available.flatMap(key => key === "memory" ? [
    { label: views.memory, href: url("memory"), current: active === "memory" && !pointFilter },
    { label: "Pikat e hapura", href: url("memory") + "&filter=open", current: active === "memory" && pointFilter === "open" },
    { label: "Historiku i takimeve", href: url("memory") + "&filter=history", current: active === "memory" && pointFilter === "history" },
  ] : [{ label: views[key], href: url(key), current: active === key }])
  const title = meetingDisplayTitle(detail)
  const createdNotes = detail.notes.filter(note => note.created_during_meeting)
  const createdTasks = detail.created_tasks ?? []
  return (
    <section className="mt-5 space-y-4">
      <Link href={base} className="text-sm underline">Kthehu te takimet</Link>
      <header>
        <h2 className="text-xl font-semibold">
          {detail.source === "discord" && !detail.has_custom_title ? developmentMeetingTitle(title) : title}
          {detail.started_at ? <> · <time dateTime={detail.started_at} className="whitespace-nowrap tabular-nums">
            {meetingDisplayDate(detail.started_at)}
          </time></> : detail.host && ` · ${dayLabel(detail.host.date)}`}
        </h2>
        <p className="text-sm text-muted-foreground">
          {sources[detail.source]}
          {detail.status && recordingStatuses[detail.status] && ` · ${recordingStatuses[detail.status]}`}
        </p>
      </header>
      {detail.partial && <p className="rounded-md border border-amber-500/50 px-3 py-2 text-sm">Regjistrimi ose transkripti është i pjesshëm.</p>}
      {(createdTasks.length > 0 || createdNotes.length > 0) && <section className="space-y-2 rounded-lg border border-violet-200 bg-violet-50/60 p-3 dark:border-violet-900 dark:bg-violet-950/30">
        <h3 className="text-sm font-semibold">Detyra dhe shënime nga takimi</h3>
        <Table aria-label="Detyra dhe shënime nga takimi"
          containerClassName="rounded-md border border-violet-200 dark:border-violet-900"
          className="min-w-[36rem] table-fixed bg-background">
          <TableHeader className="bg-violet-100/60 dark:bg-violet-950/60">
            <TableRow>
              <TableHead scope="col" className="w-24">Lloji</TableHead>
              <TableHead scope="col">Përmbajtja</TableHead>
              <TableHead scope="col" className="w-1/4">Përgjegjësi</TableHead>
              <TableHead scope="col" className="w-32">Data e fillimit</TableHead>
              <TableHead scope="col" className="w-28">Afati</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {createdTasks.map(task => <TableRow key={`task-${task.id}`}>
              <TableCell className="font-medium text-blue-800 dark:text-blue-200">Detyrë</TableCell>
              <TableCell className="whitespace-normal [overflow-wrap:anywhere]">
                <Link href={`/tasks/${task.id}`} className="underline underline-offset-2">{task.title}</Link>
              </TableCell>
              <TableCell className="whitespace-normal [overflow-wrap:anywhere]" title={task.assignees?.join(", ")}>
                {task.assignee_initials?.filter(Boolean).join(", ") || "—"}
              </TableCell>
              <TableCell className="tabular-nums">{formatDateDMY(task.start_date, "—")}</TableCell>
              <TableCell className="tabular-nums">{formatDateDMY(task.due_date, "—")}</TableCell>
            </TableRow>)}
            {createdNotes.map(note => <TableRow key={`note-${note.id}`}>
              <TableCell className="font-medium text-violet-800 dark:text-violet-200">Shënim</TableCell>
              <TableCell className="whitespace-normal [overflow-wrap:anywhere]">
                <Link href={miraMeetingUrl(detail.id, detail.source, "full", `note-${note.note_id ?? note.id}`)}
                  className="underline underline-offset-2">{note.content.trim().split("\n")[0]?.slice(0, 140) || note.title}</Link>
              </TableCell>
              <TableCell>—</TableCell>
              <TableCell>—</TableCell>
              <TableCell>—</TableCell>
            </TableRow>)}
          </TableBody>
        </Table>
      </section>}
      <nav aria-label="Pamjet e takimit" className="flex flex-wrap gap-4 border-b pb-2 text-sm">
        {navigation.map(({ label, href, current }) => (
          <Link key={label} href={href} aria-current={current ? "page" : undefined} className={cn("rounded-md px-3 py-1.5", current
            ? "bg-violet-100 font-semibold text-violet-900 dark:bg-violet-950 dark:text-violet-200"
            : "text-muted-foreground hover:bg-violet-50 dark:hover:bg-violet-950/40")}>{label}</Link>
        ))}
      </nav>
      {active === "quick" && (quick ? Object.entries(sections).map(([key, label]) => {
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
          {canManage && !detail.quick_summary_pending &&
            <Button size="sm" variant="outline" disabled={summaryRequest?.id === detail.id && !summaryRequest.error}
              onClick={() => void requestSummary(detail.id)}>Gjenero përmbledhjen</Button>}
          {detail.full_notes && <Link className="underline" href={url("full")}>Hap shënimet e plota</Link>}
          <Link className="underline" href={url("transcript")}>Hap transkriptin</Link>
        </div>}
        {summaryRequest?.id === detail.id && summaryRequest.error && <p role="alert">{summaryRequest.error}</p>}
      </div>)}
      {active === "report" && hostIds.map(id => <HostMeetingPanel key={id} id={id} initial={detail.host} canManage={canManage} />)}
      {active === "full" && <>
        {detail.error && <p className="text-sm">{detail.error}</p>}
        <MeetingNotes key={detail.id} notes={detail.notes} draft={detail.full_notes ?? detail.host?.recorder?.notes}
          inlineTranscript={detail.source === "discord" && detail.transcript.length > 0}
          transcript={<section id="transkripti" className="scroll-mt-20 space-y-2 rounded-lg border border-violet-200 bg-background p-3 dark:border-violet-900">
            <h3 className="text-sm font-semibold">Transkripti me kohë</h3>
            {detail.source === "discord" && <DiscordTranscript segments={detail.transcript} anchor={transcriptAnchor} />}
            {hostIds.map(id => <HostMeetingPanel key={id} id={id} initial={detail.host}
              canManage={canManage} transcript includeRecorder={detail.source === "host"} />)}
            {detail.source === "desktop" && <p className="whitespace-pre-wrap break-words text-sm">
              {detail.transcript_allowed === false ? "Pronari i regjistrimit mund të hapë transkriptin e Mira Desktop."
                : detail.desktop_transcript || "Nuk ka segmente të transkriptuara."}
            </p>}
          </section>} />
      </>}
      {(active === "quick" || (active === "memory" && pointFilter !== "history")) && <Clarifications key={detail.id} detail={detail}
        onAnswer={(itemId, question, answer, version) => setDetail((current) => {
          if (!current?.memory || current.id !== detail.id) return current
          return { ...current, memory: { ...current.memory, points: current.memory.points.map((point) => point.id === itemId
            ? { ...point, version, questions: point.questions.filter((value) => value !== question), answers: { ...point.answers, [question]: answer } }
            : point) } }
        })} />}
      {active === "memory" && pointFilter !== "history" && <MeetingMemory detail={detail} filter={pointFilter}
        closing={closingPoints} onClose={closePoint} />}
      {active === "memory" && pointFilter === "history" && (detail.memory?.previous.length
        ? <PreviousPoints points={detail.memory.previous} title="Diskutimet e mëparshme" />
        : <p className="text-sm">{detail.memory?.status === "PENDING" || detail.memory?.status === "RUNNING"
          ? "MIRA po kontrollon lidhjet me takimet e mëparshme."
          : detail.memory?.status === "FAILED" ? "Përpunimi i historikut dështoi."
            : "Nuk ka diskutime të mëparshme të lidhura me këtë takim."}</p>)}
    </section>
  )
}
