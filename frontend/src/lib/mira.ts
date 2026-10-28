export type MiraTab = "takimet" | "shenimet" | "knowledge" | "kujtesa" | "cilesimet"

export type TurnPerson = { initials: string; status: string }

export type MeetingRow = {
  id: string
  date: string
  slot: string
  status: "PREP" | "GA_PHASE" | "STAFF_PHASE" | "DONE" | "ABORTED" | "DISCORD_REPORT"
  started_at: string | null
  staff_started_at: string | null
  ended_at: string | null
  duration_minutes: number | null
  summary_status: string | null
  has_summary: boolean
  error: string | null
  people: TurnPerson[]
}

export type Turn = {
  id: string
  user_id: string
  name: string
  initials: string
  status: "WAITING" | "ACTIVE" | "DONE" | "SKIPPED"
  order: number
  invited_at: string | null
  started_at: string | null
  ended_at: string | null
  notes: string
}

export type TranscriptLine = { at: string; role: "mira" | "staff"; speaker: string; text: string }

export type MeetingEvent = {
  kind: string
  user: string | null
  initials: string | null
  data: Record<string, unknown>
  at: string | null
}

export type MeetingDetail = MeetingRow & {
  discord_reports?: DiscordSlotReport[]
  turns: Turn[]
  summary: string | null
  transcript: TranscriptLine[]
  events: MeetingEvent[]
  mentions: { kind: "DONE" | "STRIKE"; text: string; task_id: string }[]
  recorder: {
    id: string | null
    status: string | null
    notes: string | null
    segments: { speaker: string; start_ms: number; text: string }[]
  } | null
}

export type DiscordReportHistory = {
  kind: "ANSWER" | "SKIP" | "ACTION"
  at: string
  question?: string
  answer?: string
  expected_at?: string | null
  instruction?: string
  status?: string
  message?: string
  selected_tasks?: DiscordContinuationTask[]
}

export type DiscordContinuationTask = { id: string; title: string; slot: string; status: string; group: string }

export type DiscordSlotReport = {
  id: string
  user_id: string
  name: string
  state: "WAITING" | "PARTIAL" | "DONE"
  created_at: string
  sent_at: string | null
  tasks: {
    id: string
    title: string
    planned_status: string
    question?: string | null
    comment?: string | null
    progress_percentage?: number | null
    status: string
    available: boolean
    answer: string | null
    expected_at: string | null
    skipped: boolean
    history: DiscordReportHistory[]
    postponements?: { id: string; status: string; label: string; comment: string; proposed_dates: Record<string, string>; at: string }[]
  }[]
  next: { answer: string | null; expected_at: string | null; history: DiscordReportHistory[];
    selected_tasks?: DiscordContinuationTask[]; selection_kind?: "TASKS" | "OTHER" | "NONE" | null }
}

export type MiraNote = {
  id: string
  kind: "1H" | "PX_NOTE"
  title: string
  content: string
  status: string
  created_at: string | null
  url: string
  meeting_id: string | null
}

export type KnowledgeCategory = "STRUKTURA" | "RREGULLORE" | "DEFINIME" | "PROCESE" | "TJETER"

export type KnowledgeItem = {
  id: string
  title: string
  category: KnowledgeCategory
  content_text: string
  source: "MANUAL" | "FILE"
  file_name: string | null
  is_active: boolean
  sort_order: number
  chars: number
  updated_at: string | null
}

export type GaParticipant = { name: string; fallback?: string | null }

export type HostStatus = {
  enabled: boolean
  enabled_until: string | null
  ga_participants: GaParticipant[]
  protocol_text: string
  target_minutes_per_person: number
  knowledge_char_budget: number
  configured: boolean
  slots: string[]
  live: MeetingRow | null
}

export const CATEGORY_LABELS: Record<KnowledgeCategory, string> = {
  STRUKTURA: "Struktura e Primex",
  RREGULLORE: "Rregulloret",
  DEFINIME: "Definimet",
  PROCESE: "Proceset",
  TJETER: "Tjetër",
}

export const STATUS_LABELS: Record<MeetingRow["status"], string> = {
  PREP: "Në përgatitje",
  GA_PHASE: "Faza GA",
  STAFF_PHASE: "Radha e stafit",
  DONE: "Përfundoi",
  ABORTED: "U ndërpre",
  DISCORD_REPORT: "Raportimi në Discord",
}

export async function json<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    throw new Error(typeof body?.detail === "string" ? body.detail : "Kërkesa dështoi. Provo përsëri.")
  }
  return body as T
}

export function clock(value: string | null | undefined): string {
  if (!value) return "–"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? "–" : date.toLocaleTimeString("sq-AL", { hour: "2-digit", minute: "2-digit" })
}

export function dayLabel(value: string): string {
  const [year, month, day] = value.split("-")
  return `${day}.${month}.${year}`
}

export function minutesBetween(start: string | null, end: string | null): number | null {
  if (!start || !end) return null
  return Math.max(0, Math.round((new Date(end).getTime() - new Date(start).getTime()) / 60000))
}

export function eventText(event: MeetingEvent): string {
  const data = event.data as Record<string, string | string[] | boolean | null>
  switch (event.kind) {
    case "TASK_CREATED": {
      const parts = [String(data.title ?? ""), (data.assignees as string[] | undefined)?.join("/"), data.due ? `afati ${dayLabel(String(data.due))}` : null,
        data.period, data.symbol ? `simboli ${data.symbol}` : null, data.deadline ? "DEADLINE" : null, `1H ${data.slot}`]
      return "Detyrë e re nga PX Notes: " + parts.filter(Boolean).join(" · ")
    }
    case "BRIEF": return `Protokolli dhe detyrat iu dërguan ${event.initials ?? ""} (5 min para)`
    case "GA_CALL": return `${event.initials ?? ""} u thirr në 1H (2 min para)`
    case "GA_FALLBACK": return `Zëvendësim i mundshëm: ${event.initials ?? ""} (thirret vetëm nëse mungon kolegia)`
    case "NOTE": return `Shënim: ${String(data.text ?? "")}`
    case "PX_NOTE": return `Shënim i ri në PX Notes: ${String(data.text ?? "")}${data.symbol ? ` · simboli ${data.symbol}` : ""}`
    default: return event.kind
  }
}

export type NoteTranscript = {
  note_id: string
  title: string
  status: string
  partial: boolean
  started_at: string | null
  stopped_at: string | null
  passages: { speaker: string; time: string; text: string }[]
}
