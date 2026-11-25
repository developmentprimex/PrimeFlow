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

const formatTime = (date: Date) =>
  date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true })

export const parseTimeValue = (value: string) => {
  const match = /^(\d{2}):(\d{2})$/.exec(value)
  if (!match) return null
  const hours = Number(match[1])
  const minutes = Number(match[2])
  if (Number.isNaN(hours) || Number.isNaN(minutes)) return null
  if (hours < 0 || hours > 23 || minutes < 0 || minutes > 59) return null
  return { hours, minutes }
}

export const formatTimeLabel = (value?: string): string => {
  if (!value) return ""
  const normalized = value.trim().replace(/\s*\(\+\d+d\)/g, "")
  if (!normalized || normalized.toLowerCase() === "tbd") return normalized
  if (/^\d{2}:\d{2} - \d{2}:\d{2}(?: \(\+\d+d\))?$/.test(normalized)) return normalized
  if (/am|pm/i.test(normalized)) return normalized
  if (normalized.includes("-")) {
    const [startRaw, endRaw] = normalized.split("-").map((part) => part.trim())
    const startLabel: string = formatTimeLabel(startRaw)
    const endLabel: string = formatTimeLabel(endRaw)
    if (startLabel && endLabel) return `${startLabel} - ${endLabel}`
    return normalized
  }
  const parsed = parseTimeValue(normalized)
  if (!parsed) return normalized
  const temp = new Date()
  temp.setHours(parsed.hours, parsed.minutes, 0, 0)
  return formatTime(temp)
}
