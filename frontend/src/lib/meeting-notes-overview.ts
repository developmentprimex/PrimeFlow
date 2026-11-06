import type { Meeting } from "./types"
import { isManualInternalMeeting, meetingLegendTone } from "./meeting-tone"

/** PARA/PAS are excluded from Takimet even when optional categories are shown. */
export function isIncludedOverviewMeeting(meeting: Meeting): boolean {
  return meeting.meeting_type !== "internal" || isManualInternalMeeting(meeting)
}

/** Physical external meetings remain available on request via the existing colours. */
export function isOptionalOverviewMeeting(meeting: Meeting): boolean {
  if (meeting.meeting_type === "internal") return false

  return meetingLegendTone({
    categories: meeting.calendar_categories,
    recurrenceType: meeting.recurrence_type,
    meetingType: "external",
    calendarImported: Boolean(meeting.calendar_imported || meeting.microsoft_event_id),
  }) === "outlook-blue"
}
