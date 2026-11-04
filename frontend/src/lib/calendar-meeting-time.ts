import type { Meeting } from "@/lib/types"

/** The calendar's planned start and end clocks. */
export function calendarMeetingTimeRange(meeting: Pick<Meeting, "meeting_type" | "calendar_imported" | "microsoft_event_id" | "starts_at" | "ends_at">): string | null {
  if (meeting.meeting_type !== "external" || !(meeting.calendar_imported || meeting.microsoft_event_id)) return null
  if (!meeting.starts_at || !meeting.ends_at) return null
  const start = new Date(meeting.starts_at)
  const end = new Date(meeting.ends_at)
  if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || end <= start) return null
  const clock = (date: Date) => date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false })
  return `${clock(start)} - ${clock(end)}`
}

export function meetingTimeColumns(value?: string | null): { from: string; to: string } {
  const clean = (value || "").replace(/\s*\(\+\d+d\)/g, "").trim()
  const parts = clean.split(/\s*[-–—]\s*/, 2)
  return { from: parts[0] || "-", to: parts[1] || "-" }
}
