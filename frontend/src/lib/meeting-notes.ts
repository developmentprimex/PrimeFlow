import type { Meeting } from "@/lib/types"

export type MeetingKind = "EXTERNAL" | "INTERNAL" | "TRAINING"
export type MeetingNoteTaskStatus = "TODO" | "IN_PROGRESS" | "WAITING_CLIENT" | "WAITING_CONFIRMATION" | "DONE"

export type MeetingNoteAttachment = { id: string; original_filename: string; content_type: string | null; size_bytes: number; created_at: string }

export type MeetingNote = {
  id: string
  meeting_id: string
  occurrence_date: string
  kind: "NOTE" | "QUESTION"
  reference: string | null
  content: string
  answer: string | null
  source: "MANUAL" | "RECORDING"
  recording_id: string | null
  recording_action_id: string | null
  recording_seconds: number | null
  assignee_user_id: string | null
  due_date: string | null
  ga_note_id: string | null
  is_closed: boolean
  created_by: string | null
  created_at: string
  updated_at: string
  attachments: MeetingNoteAttachment[]
  task_status: MeetingNoteTaskStatus | null
  task_ids: string[]
}

export type MeetingOverviewRow = {
  meeting: Meeting
  kind: MeetingKind
  last_session: string | null
  next_session: string | null
  counts: { open_notes: number; TODO: number; IN_PROGRESS: number; WAITING: number; DONE: number }
}

export type MeetingSession = {
  date: string
  status: "planned" | "held" | "canceled" | string | null
  is_today: boolean
  recordings: { id: string; title: string; status: string; duration_seconds: number | null }[]
}

export type MeetingDetail = {
  meeting: Meeting
  kind: MeetingKind
  project: { id: string; title: string | null } | null
  sessions: MeetingSession[]
  today: string
}

export type LookupUser = { id: string; full_name?: string | null; username?: string | null; email?: string | null }

export const KIND_LABEL: Record<MeetingKind, string> = { EXTERNAL: "EXT", INTERNAL: "INT", TRAINING: "TRAJNIM" }

/** Same colours as PX Notes (see px-notes-workspace shenimiCellClass). */
export const STATUS_STYLE: Record<MeetingNoteTaskStatus, { label: string; cell: string }> = {
  TODO: { label: "TODO", cell: "bg-pink-200 text-slate-900" },
  IN_PROGRESS: { label: "IN PROGRESS", cell: "bg-yellow-200 text-slate-900" },
  WAITING_CLIENT: { label: "WFE", cell: "bg-[#E2C15B] text-[#4F3A00]" },
  WAITING_CONFIRMATION: { label: "WFC", cell: "bg-amber-50 text-slate-900" },
  DONE: { label: "DONE", cell: "bg-emerald-200 text-slate-900" },
}

export const MANUAL_NOTE_CELL = "bg-sky-200 text-slate-900"
export const RECORDING_NOTE_CELL = "bg-violet-100 text-slate-900"

/** Statuses a user can pick for a single linked task (manual, like PX Notes). */
export const PICKABLE_STATUSES: MeetingNoteTaskStatus[] = ["TODO", "IN_PROGRESS", "WAITING_CLIENT", "DONE"]

export function noteCellClass(note: MeetingNote): string {
  if (note.is_closed) return "bg-slate-300 text-slate-700"
  if (note.task_status) return STATUS_STYLE[note.task_status].cell
  return note.source === "RECORDING" ? RECORDING_NOTE_CELL : MANUAL_NOTE_CELL
}

export function isNoteDone(note: MeetingNote): boolean {
  return note.is_closed || note.task_status === "DONE"
}

export function userName(users: Map<string, LookupUser>, id: string | null | undefined): string {
  if (!id) return "—"
  const user = users.get(id)
  return user?.full_name || user?.username || user?.email || "—"
}

export function userInitials(users: Map<string, LookupUser>, id: string | null | undefined): string {
  const name = userName(users, id)
  if (name === "—") return "—"
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("")
}

export function dmy(value: string | null | undefined): string {
  if (!value) return "—"
  const [y, m, d] = value.slice(0, 10).split("-")
  return y && m && d ? `${d}.${m}.${y}` : value
}

/** Manual meeting-note deadline: DDMMYYYY or DD.MM.YYYY; undefined means invalid. */
export function parseMeetingNoteDueDate(value: string): string | null | undefined {
  const text = value.trim()
  if (!text) return null
  const match = /^(\d{2})(\d{2})(\d{4})$/.exec(text) || /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(text)
  if (!match) return undefined
  const [, day, month, year] = match
  const d = Number(day), m = Number(month), y = Number(year)
  if (y < 1 || m < 1 || m > 12 || d < 1) return undefined
  const leap = y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0)
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
  if (d > days[m - 1]) return undefined
  return `${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`
}

export function shortDm(value: string): string {
  const [, m, d] = value.slice(0, 10).split("-")
  return `${d}.${m}`
}

export function clock(seconds: number | null | undefined): string {
  const n = Math.max(0, Math.floor(seconds || 0))
  return `${String(Math.floor(n / 3600)).padStart(2, "0")}:${String(Math.floor(n / 60) % 60).padStart(2, "0")}:${String(n % 60).padStart(2, "0")}`
}

export function isoDate(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`
}

export async function readError(response: Response, fallback: string): Promise<string> {
  try {
    const data = await response.json()
    if (typeof data?.detail === "string") return data.detail
  } catch {
    // keep fallback
  }
  return fallback
}

/** Column titles: EXT meetings show the client-facing English headers. */
export function noteColumns(kind: MeetingKind) {
  return kind === "EXTERNAL"
    ? { nr: "NO.", source: "SOURCE", note: "QUESTION / CASE", answer: "ANSWER", owner: "OWNER", due: "DEADLINE", status: "STATUS" }
    : { nr: "NR", source: "BURIMI", note: "SHËNIMI / PYETJA", answer: "PËRSHKRIMI / PËRGJIGJA", owner: "KUSH", due: "AFATI", status: "STATUSI" }
}
