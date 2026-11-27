import { parseTimeValue } from "@/lib/calendar-meeting-time"

type ApiFetch = (path: string, init?: RequestInit) => Promise<Response>

export type MeetingAvailability = {
  can_create: boolean
  errors: string[]
  warnings: string[]
  conflicts: Array<{
    source: string
    title: string
    starts_at: string
    ends_at: string
    participant_ids?: string[]
  }>
  suggested_slot?: { starts_at: string; ends_at: string } | null
}

export function computeNextOccurrenceDate(params: {
  recurrenceType: "weekly" | "monthly" | "yearly"
  daysOfWeek: number[]
  daysOfMonth: number[]
  timeValue: string
  monthOfYear?: number
}) {
  const parsedTime = parseTimeValue(params.timeValue)
  if (!parsedTime) return null
  const now = new Date()
  const { hours, minutes } = parsedTime

  if (params.recurrenceType === "weekly") {
    if (!params.daysOfWeek.length) return null
    const daySet = new Set(params.daysOfWeek.map((d) => (d + 1) % 7))
    for (let offset = 0; offset < 14; offset++) {
      const candidate = new Date(now)
      candidate.setDate(now.getDate() + offset)
      candidate.setHours(hours, minutes, 0, 0)
      if (!daySet.has(candidate.getDay())) continue
      if (offset === 0 && candidate.getTime() < now.getTime()) continue
      return candidate
    }
    return null
  }

  if (params.recurrenceType === "monthly") {
    if (!params.daysOfMonth.length) return null
    const sortedDays = [...new Set(params.daysOfMonth)].sort((a, b) => a - b)
    for (let monthOffset = 0; monthOffset < 12; monthOffset++) {
      const base = new Date(now.getFullYear(), now.getMonth() + monthOffset, 1)
      const year = base.getFullYear()
      const month = base.getMonth()
      const daysInMonth = new Date(year, month + 1, 0).getDate()
      for (const day of sortedDays) {
        if (day < 1 || day > daysInMonth) continue
        if (monthOffset === 0 && day < now.getDate()) continue
        const candidate = new Date(year, month, day, hours, minutes, 0, 0)
        if (monthOffset === 0 && day === now.getDate() && candidate.getTime() < now.getTime()) {
          continue
        }
        return candidate
      }
    }
  }

  if (params.recurrenceType === "yearly") {
    const day = params.daysOfMonth[0]
    const month = params.monthOfYear ?? 0
    if (!day || month < 0 || month > 11) return null
    const makeCandidate = (year: number) => {
      const daysInMonth = new Date(year, month + 1, 0).getDate()
      if (day < 1 || day > daysInMonth) return null
      return new Date(year, month, day, hours, minutes, 0, 0)
    }
    const current = makeCandidate(now.getFullYear())
    if (current && current.getTime() >= now.getTime()) return current
    return makeCandidate(now.getFullYear() + 1)
  }

  return null
}

export async function checkMeetingAvailability(apiFetch: ApiFetch, params: {
  title: string
  meetingType: "internal" | "external"
  startsAt: Date
  departmentId: string
  participantIds: string[]
}): Promise<MeetingAvailability | null> {
  if (!params.departmentId || params.participantIds.length === 0 || Number.isNaN(params.startsAt.getTime())) return null
  const durationMinutes = params.meetingType === "internal" ? 30 : 60
  const endsAt = new Date(params.startsAt.getTime() + durationMinutes * 60_000)
  const response = await apiFetch("/meeting-scheduler/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: params.title.trim() || `Kontroll TAK ${params.meetingType === "internal" ? "INT" : "EXT"}`,
      meeting_type: params.meetingType,
      starts_at: params.startsAt.toISOString(),
      ends_at: endsAt.toISOString(),
      platform: params.meetingType === "external" ? "Teams" : null,
      notes: null,
      department_id: params.departmentId,
      project_id: null,
      standard_id: null,
      participant_ids: params.participantIds,
      check_all_meetings: params.meetingType === "internal",
    }),
  })
  if (!response.ok) return null
  return (await response.json()) as MeetingAvailability
}

