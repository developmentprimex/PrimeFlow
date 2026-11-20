// Kujtesa e Mira-s: the shapes served by /mira-memory and how the page words them.

export type MemoryStatus = "OPEN" | "CLOSED" | "WRONG"
export type MemoryTab = "open" | "closed" | "all"
export const memoryKindLabels = {
  TASK: "Detyrë", TOPIC: "Temë", DECISION: "Vendim", INFO: "Informacion",
  ACTION: "Veprim", INSTRUCTION: "Udhëzim", OPEN_QUESTION: "Pyetje e hapur",
  BLOCKER: "Pengesë", FOLLOW_UP: "Për t’u ndjekur", IMPORTANT_INFO: "Informacion i rëndësishëm",
} as const

export type MemoryListItem = {
  id: string
  title: string
  kind: keyof typeof memoryKindLabels
  status: MemoryStatus
  quiet: boolean
  mention_count: number
  last_mentioned_at: string | null
}

export type MemoryEvent = {
  kind: "MENTION" | "CHANGE" | "CLOSE" | "REOPEN" | "EDIT" | "WRONG" | "ANSWER"
  text: string
  created_at: string
  meeting_title: string | null
  meeting_id?: string | null
  user_name: string | null
  partial: boolean
}

export type MemoryDetail = MemoryListItem & {
  description: string
  people: string[]
  version: number
  human_edited: boolean
  events: MemoryEvent[]
}

export type MemoryList = {
  items: MemoryListItem[]
  counts: { open: number; closed: number }
  failed_meetings: number
}

const APP_TIMEZONE = "Europe/Budapest"

export function shortDate(iso: string, timeZone = APP_TIMEZONE): string {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(new Date(iso))
  const part = (type: string) => parts.find((p) => p.type === type)?.value ?? ""
  return `${part("day")}.${part("month")}, ${part("hour")}:${part("minute")}`
}

const BY_PERSON: Record<string, string> = {
  EDIT: "Korrigjuar nga",
  CLOSE: "Mbyllur nga",
  REOPEN: "Rihapur nga",
  WRONG: "Shënuar si e gabuar nga",
  ANSWER: "Sqaruar nga",
}

export function eventLabel(event: MemoryEvent): string {
  const when = shortDate(event.created_at)
  if (event.user_name) return `${BY_PERSON[event.kind] ?? "Ndryshuar nga"} ${event.user_name} · ${when}`
  const meeting = event.meeting_title || "Takim"
  if (event.kind === "CLOSE") return `Mbyllur në takim, ${meeting} · ${when}`
  if (event.kind === "CHANGE") return `Ndryshuar në takim, ${meeting} · ${when}`
  return `${meeting} · ${when}`
}

export function mentionText(count: number): string {
  return count === 1 ? "1 takim" : `${count} takime`
}
