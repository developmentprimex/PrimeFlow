import type { MeetingOverviewRow } from "./meeting-notes"

export function isRecurringOverviewMeeting(row: MeetingOverviewRow): boolean {
  return ["weekly", "monthly", "yearly"].includes((row.meeting.recurrence_type || "").toLowerCase())
}

/** Match the local clock used throughout the calendar, preserving the occurrence date. */
export function meetingOverviewDateTime(row: MeetingOverviewRow): string {
  if (!row.meeting.starts_at) return "—"
  const start = new Date(row.meeting.starts_at)
  if (!Number.isFinite(start.getTime())) return "—"
  const localDay = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, "0")}-${String(start.getDate()).padStart(2, "0")}`
  const day = isRecurringOverviewMeeting(row) ? row.next_session || row.last_session || localDay : localDay
  const [year, month, date] = day.split("-")
  const time = start.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false })
  return `${date}.${month}.${year} · ${time}`
}
