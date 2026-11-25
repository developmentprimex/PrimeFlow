export type MeetingTone =
  | "outlook-manual"
  | "outlook-violet"
  | "outlook-blue"
  | "outlook-teal"
  | "outlook-yellow"
  | "outlook-brown"
  | "outlook-orange"
  | "outlook-red"

type MeetingToneInput = {
  categories?: string[]
  recurrenceType?: string | null
  meetingType: "external" | "internal"
  calendarImported?: boolean
}

export type InternalMeetingToneInput = {
  recurrenceType?: string | null
  recurrence_type?: string | null
  pairedExternalMeetingId?: string | null
  paired_external_meeting_id?: string | null
  preExternalMeetingId?: string | null
  pre_external_meeting_id?: string | null
  linkedExternalCalendarCategories?: string[]
  linked_external_calendar_categories?: string[]
  linkedExternalCalendarImported?: boolean
  linked_external_calendar_imported?: boolean
  linkedExternalRecurrenceType?: string | null
  linked_external_recurrence_type?: string | null
}

export const isManualInternalMeeting = (meeting: InternalMeetingToneInput): boolean =>
  !(
    meeting.pairedExternalMeetingId ??
    meeting.paired_external_meeting_id ??
    meeting.preExternalMeetingId ??
    meeting.pre_external_meeting_id
  )

export const isCalendarLinkedInternalMeeting = (meeting: InternalMeetingToneInput): boolean =>
  !isManualInternalMeeting(meeting) &&
  Boolean(meeting.linkedExternalCalendarImported ?? meeting.linked_external_calendar_imported)

export const internalMeetingRelation = (meeting: InternalMeetingToneInput): "PARA" | "PAS" | undefined => {
  if (meeting.preExternalMeetingId || meeting.pre_external_meeting_id) return "PARA"
  if (meeting.pairedExternalMeetingId || meeting.paired_external_meeting_id) return "PAS"
  return undefined
}

export const meetingLegendTone = ({
  categories,
  recurrenceType,
  meetingType,
  calendarImported,
}: MeetingToneInput): MeetingTone => {
  const values = (categories || []).map((category) => category.trim().toLowerCase())
  const normalizedRecurrence = (recurrenceType || "").trim().toLowerCase()

  if (
    values.some(
      (category) =>
        category.includes("daily") ||
        category.includes("weekly") ||
        category.includes("standup") ||
        category.includes("brown")
    )
  )
    return "outlook-brown"
  if (values.some((category) => category.includes("red") || category.includes("online"))) return "outlook-red"
  if (values.some((category) => category === "tak int" || category.includes("yellow"))) return "outlook-yellow"
  if (values.some((category) => category.includes("orange"))) return "outlook-orange"
  if (values.some((category) => category.includes("event") || category.includes("evvent") || category.includes("fizik")))
    return "outlook-teal"
  if (values.some((category) => category.includes("purple") || category.includes("violet"))) return "outlook-violet"
  if (values.some((category) => category.includes("blue"))) return "outlook-blue"

  if (calendarImported) return "outlook-red"
  if (meetingType === "internal") return "outlook-blue"
  if (["weekly", "daily"].includes(normalizedRecurrence)) return "outlook-brown"
  return "outlook-blue"
}

export const internalMeetingLegendTone = (meeting: InternalMeetingToneInput): MeetingTone => {
  const isLinked = !isManualInternalMeeting(meeting)
  if (!isLinked) return "outlook-manual"

  return meetingLegendTone({
    categories: meeting.linkedExternalCalendarCategories ?? meeting.linked_external_calendar_categories,
    recurrenceType: isLinked
      ? meeting.linkedExternalRecurrenceType ?? meeting.linked_external_recurrence_type
      : meeting.recurrenceType ?? meeting.recurrence_type,
    meetingType: "external",
    calendarImported: Boolean(
      meeting.linkedExternalCalendarImported ?? meeting.linked_external_calendar_imported
    ),
  })
}
