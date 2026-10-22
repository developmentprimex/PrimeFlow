import type { Meeting } from "./types"

export type InternalMeetingListFilter = "next" | "past" | "all" | "this_week" | "next_week"

export function internalMeetingWeekDate(
  meeting: Meeting,
  filter: InternalMeetingListFilter,
  now = new Date(),
): Date | null {
  if (filter !== "this_week" && filter !== "next_week") return null
  const monday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  monday.setDate(monday.getDate() - (monday.getDay() + 6) % 7 + (filter === "next_week" ? 7 : 0))
  const end = new Date(monday)
  end.setDate(end.getDate() + 7)
  return internalMeetingDateInRange(meeting, monday, end)
}

export function internalMeetingDateOn(meeting: Meeting, date: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return null
  const [year, month, day] = date.split("-").map(Number)
  const start = new Date(year, month - 1, day)
  if (start.getFullYear() !== year || start.getMonth() !== month - 1 || start.getDate() !== day) return null
  const end = new Date(start)
  end.setDate(end.getDate() + 1)
  return internalMeetingDateInRange(meeting, start, end)
}

function internalMeetingDateInRange(meeting: Meeting, from: Date, end: Date): Date | null {
  const start = new Date(meeting.starts_at || meeting.created_at || "")
  if (Number.isNaN(start.getTime())) return null
  const recurrence = meeting.recurrence_type
  if (!recurrence || recurrence === "none") return start >= from && start < end ? start : null
  for (let offset = 0; offset < 7; offset++) {
    const candidate = new Date(from)
    candidate.setDate(candidate.getDate() + offset)
    if (candidate >= end) break
    candidate.setHours(start.getHours(), start.getMinutes(), start.getSeconds(), 0)
    const matches = recurrence === "weekly"
      ? meeting.recurrence_days_of_week?.includes((candidate.getDay() + 6) % 7)
      : recurrence === "monthly"
        ? meeting.recurrence_days_of_month?.includes(candidate.getDate())
        : recurrence === "yearly" && candidate.getMonth() === start.getMonth()
          && candidate.getDate() === (meeting.recurrence_days_of_month?.[0] ?? start.getDate())
    if (matches) return candidate
  }
  return null
}
