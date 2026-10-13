"use client"

import * as React from "react"
import { useVisibleRefresh } from "@/lib/use-visible-refresh"
import { toast } from "sonner"

import { useConfirm } from "@/components/providers/confirm-dialog-provider"
import { DiamondAward, TaskReviewDialog } from "@/components/task-review-dialog"
import { TaskOneHMarkerEditor } from "@/components/task-one-h-marker-editor"
import { TaskMarkerComment } from "@/components/task-marker-comment"
import { MeetingDetailsDialog } from "@/components/meeting-details-dialog"
import { useAuth } from "@/lib/auth"
import { COMMON_VIEW_AGGREGATE_ENABLED } from "@/lib/config"
import { formatDateDMY, formatDateTimeDMY } from "@/lib/dates"
import { getPlainMarkedText, parseMarkedNoteContent, renderMarkedNoteContent } from "@/lib/note-markup"
import { resolveProjectTitle } from "@/lib/project-display-title"
import { buildRepeatedTaskFirstDateMap, isRepeatedTaskInstance } from "@/lib/repeated-task-visibility"
import {
  internalMeetingLegendTone,
  isCalendarLinkedInternalMeeting,
  isManualInternalMeeting,
  meetingLegendTone,
} from "@/lib/meeting-tone"
import type {
  User,
  Task,
  CommonEntry,
  Project,
  Meeting,
  MeetingOccurrenceStatus,
  Department,
  SystemTaskTemplate,
  TaskReview,
  TaskReviewOverview,
  TaskReviewOverviewRow,
} from "@/lib/types"

function canCreateAgentTestTaskForMeeting(meeting: Meeting): boolean {
  if (meeting.external_agent_test_task_requested) return false
  const recurrence = (meeting.recurrence_type || "").trim().toLowerCase()
  const isOneTime = !recurrence || recurrence === "none"
  return isOneTime && Boolean(meeting.starts_at)
}

function canCreatePimImageTestTaskForMeeting(meeting: Meeting): boolean {
  if (meeting.external_pim_image_test_task_requested) return false
  const recurrence = (meeting.recurrence_type || "").trim().toLowerCase()
  const isOneTime = !recurrence || recurrence === "none"
  return isOneTime && Boolean(meeting.starts_at)
}

type PersonalTaskGroup = "GA" | "KA" | "GENT" | "PX"
type PersonalRowId = "personalGA" | "personalKA" | "personalGENT" | "personalPX"
type OneHMarker = "EXCLAMATION" | "QUESTION" | "KA" | "GENT" | "FLAG" | "F" | "BZ1N1" | "M2" | "M3" | "M2_M3" | "MONITOR" | "CLOSE" | "CLIENT_URGENT" | "SHARE"
type OneHMarkerFilter = "none" | OneHMarker

const ONE_H_MARKER_OPTIONS: Array<{ value: OneHMarker; label: string }> = [
  { value: "QUESTION", label: "?" },
  { value: "EXCLAMATION", label: "!" },
  { value: "CLIENT_URGENT", label: "!!!" },
  { value: "SHARE", label: "SHARE" },
  { value: "MONITOR", label: "👁" },
  { value: "CLOSE", label: "X" },
  { value: "M2", label: "M2" },
  { value: "M3", label: "M3" },
  { value: "M2_M3", label: "M2/3" },
  { value: "GENT", label: "GENT" },
  { value: "KA", label: "KA" },
  { value: "FLAG", label: "GA" },
  { value: "F", label: "F" },
  { value: "BZ1N1", label: "BZ1N1" },
]
const ONE_H_MARKER_VALUES = ONE_H_MARKER_OPTIONS.map((option) => option.value)

const getOneHMarkerLabel = (value?: OneHMarker | null) =>
  ONE_H_MARKER_OPTIONS.find((option) => option.value === value)?.label || ""

type CommonType =
  | "late"
  | "absent"
  | "leave"
  | "externalHoliday"
  | "blocked"
  | "oneH"
  | "oneH10"
  | "oneH11"
  | "oneH1150"
  | "oneH1420"
  | "oneH1550"
  | "oneHNoSlot"
  | "waitingClient"
  | "personal"
  | PersonalRowId
  | "external"
  | "internal"
  | "r1"
  | "problem"
  | "feedback"
  | "priority"
  | "diamond"
  | "bz"

const PERSONAL_ROW_IDS: readonly PersonalRowId[] = ["personalGA", "personalKA", "personalGENT", "personalPX"]
const PERSONAL_ROW_SCHEDULES: Readonly<Record<PersonalRowId, string>> = {
  personalGA: "08:15 / 13:15",
  personalKA: "08:30 / 13:15",
  personalGENT: "",
  personalPX: "08:45 / 14:00",
}
const DEFAULT_OPEN_SWIMLANE_TITLE_ROWS: CommonType[] = ["oneH10", "oneH11", "oneH1150", "oneH1420", "oneH1550", "oneHNoSlot", "r1", ...PERSONAL_ROW_IDS]
const TITLE_EXPANDABLE_SWIMLANE_ROWS: CommonType[] = ["oneH10", "oneH11", "oneH1150", "oneH1420", "oneH1550", "oneHNoSlot", "r1", ...PERSONAL_ROW_IDS, "feedback"]
const COMMON_PRINT_ROW_ORDER: readonly CommonType[] = [
  "late",
  "absent",
  "leave",
  "externalHoliday",
  "external",
  "internal",
  "bz",
  "waitingClient",
  "oneH10",
  "oneH11",
  "oneH1150",
  "oneH1420",
  "oneH",
  "blocked",
  "oneH1550",
  "oneHNoSlot",
  "r1",
  ...PERSONAL_ROW_IDS,
  "priority",
  "diamond",
  "problem",
  "feedback",
]
const COMMON_FAST_PRINT_ROW_IDS: readonly CommonType[] = [
  "waitingClient",
  "oneH10",
  "oneH11",
  "oneH1150",
  "oneH1420",
  "blocked",
  "oneH1550",
  "oneHNoSlot",
  "r1",
  ...PERSONAL_ROW_IDS,
]
const COMMON_MEETING_PRINT_ROW_IDS: readonly CommonType[] = ["external", "internal"]
const getCommonPrintRowRank = (id: CommonType) => {
  const rank = COMMON_PRINT_ROW_ORDER.indexOf(id)
  return rank === -1 ? COMMON_PRINT_ROW_ORDER.length : rank
}
const orderCommonRowsForPrint = <T extends { id: CommonType }>(rows: readonly T[]) =>
  rows
    .map((row, index) => ({ row, index }))
    .sort((a, b) => getCommonPrintRowRank(a.row.id) - getCommonPrintRowRank(b.row.id) || a.index - b.index)
    .map(({ row }) => row)
const getCommonPrintRowSubtext = (id: CommonType) => {
  if (id === "blocked") return "14:30 - 16:00\nRAP 16:10"
  if (isPersonalRowId(id)) {
    return PERSONAL_ROW_SCHEDULES[id]
  }
  return ""
}

const ONE_H_PRINT_CHECKLISTS = [
  {
    title: "STAFF - HAPAT PER 1H",
    questions: [
      { question: "Hap doc dhe det", description: "", isExtra: false },
      { question: "Share screen side by side DET/REZULTATIN", description: "", isExtra: false },
      { question: "Sqaro slotin paraprak pastaj aktual", description: "", isExtra: false },
      { question: "BZ Det nga Stafi per GA", description: "Komunikimi GA teams Det nga Stafi/ KA email", isExtra: false },
    ],
  },
  {
    title: "PYETJET PER 1H - BORD",
    questions: [
      { question: "Slotin paraprak/aktual", description: "", isExtra: false },
      { question: "A ke filluar me slotin aktual?", description: "", isExtra: false },
      { question: "Nese jo, kur?", description: "", isExtra: false },
      { question: "A kryhet sot?", description: "", isExtra: false },
      { question: "A kryhet kete jave?", description: "", isExtra: false },
      { question: "A arrihet RLZ javor?", description: "", isExtra: false },
      { question: "Notes te reja? Data? AM/PM? Kujt", description: "", isExtra: false },
      { question: "Done? / Strikes?", description: "", isExtra: false },
      { question: "BZ Det nga Stafi per GA", description: "Komunikimi GA teams Det nga Stafi/ KA email", isExtra: false },
      { question: "BZ Notes", description: "Secili i lexon vet para BZ me GA", isExtra: false },
    ],
  },
] as const

const THURSDAY_ONE_H_STAFF_QUESTIONS = [
  { question: "Emails per missing info, per me vazhdu javen tjeter", description: "", isExtra: true },
  { question: "Shikohen det qe mbesin vetem per neser (te premten)", description: "", isExtra: true },
] as const

const THURSDAY_ONE_H_BOARD_QUESTIONS = [
  { question: "Planifikimi javor short", description: "", isExtra: true },
] as const

const FRIDAY_ONE_H_STAFF_QUESTIONS = [
  { question: "BZ PERSONALISHT ME GA: KOMENTET TEK OPEN TASKS EXCEL", description: "", isExtra: true },
  { question: "BZ PERSONALISHT ME GA: DET GA TEK PER/NGA STAFI PER GA TEAMS", description: "", isExtra: true },
  { question: "Barazimi i planifikimit javor - next week", description: "", isExtra: true },
  { question: "Barazimi i realizimit javor - this week", description: "", isExtra: true },
  { question: "Emails per missing info, per me vazhdu javen tjeter", description: "", isExtra: true },
] as const

const BOARD_PRIMARY_QUESTION_COUNT = 6

const oneHPrintChecklistsForDate = (reportDay: Date) =>
  ONE_H_PRINT_CHECKLISTS.map((checklist, index) => ({
    ...checklist,
    questions:
      reportDay.getDay() === 4
        ? index === 0
          ? [...checklist.questions, ...THURSDAY_ONE_H_STAFF_QUESTIONS]
          : [...checklist.questions, ...THURSDAY_ONE_H_BOARD_QUESTIONS]
        : reportDay.getDay() === 5 && index === 0
          ? [...checklist.questions, ...FRIDAY_ONE_H_STAFF_QUESTIONS]
          : [...checklist.questions],
  }))

const oneHDaySpecificQuestionLabel = (reportDay: Date) =>
  reportDay.getDay() === 4
    ? "E ENJTE- PYETJET E TE ENJTES"
    : reportDay.getDay() === 5
      ? "E PREMTE"
      : "PYETJET SHTESE: 0"

const oneHExtraQuestionNumber = (reportDay: Date, question: string, index: number) => {
  const thursdayReportCodes: Record<string, "M1" | "M3"> = {
    "Emails per missing info, per me vazhdu javen tjeter": "M1",
    "Shikohen det qe mbesin vetem per neser (te premten)": "M3",
    "Planifikimi javor short": "M1",
  }
  const fridayReportCodes: Record<string, "M1"> = {
    "BZ PERSONALISHT ME GA: KOMENTET TEK OPEN TASKS EXCEL": "M1",
    "BZ PERSONALISHT ME GA: DET GA TEK PER/NGA STAFI PER GA TEAMS": "M1",

    "Barazimi i planifikimit javor - next week": "M1",
    "Barazimi i realizimit javor - this week": "M1",
    "Emails per missing info, per me vazhdu javen tjeter": "M1",
  }
  const reportCode = reportDay.getDay() === 4
    ? thursdayReportCodes[question]
    : reportDay.getDay() === 5
      ? fridayReportCodes[question]
      : undefined
  return reportCode ? `${reportCode} - ${index + 1}.` : `${index + 1}.`
}

const getNextWorkingDay = (from: Date) => {
  const next = new Date(from.getFullYear(), from.getMonth(), from.getDate())
  next.setDate(next.getDate() + 1)
  while (next.getDay() === 0 || next.getDay() === 6) {
    next.setDate(next.getDate() + 1)
  }
  return next
}

const getMeetingStartOneHourLater = (value: string) => {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value)
  if (!match) return null

  const [, year, month, day, hours, minutes] = match
  const shifted = new Date(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hours) + 1,
    Number(minutes),
  )
  if (Number.isNaN(shifted.getTime())) return null

  const pad = (part: number) => String(part).padStart(2, "0")
  return {
    date: `${shifted.getFullYear()}-${pad(shifted.getMonth() + 1)}-${pad(shifted.getDate())}`,
    time: `${pad(shifted.getHours())}:${pad(shifted.getMinutes())}`,
  }
}

const getMeetingTimeOneHourLater = (value: string) => {
  const match = /^(\d{2}):(\d{2})$/.exec(value)
  if (!match) return ""

  const hours = (Number(match[1]) + 1) % 24
  return `${String(hours).padStart(2, "0")}:${match[2]}`
}

const escapePrintHtml = (value: string) =>
  value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\"/g, "&quot;").replace(/'/g, "&#039;")

const oneHPrintChecklistsHtml = (reportDay: Date) =>
  `<section class="one-h-print-checklists">${oneHDaySpecificQuestionLabel(reportDay)
    ? `<div class="one-h-print-checklist-day-label"><strong style="margin-right:12px;font-weight:900;">${escapePrintHtml(oneHDaySpecificQuestionLabel(reportDay))}</strong>${oneHPrintChecklistsForDate(reportDay).flatMap(({ questions }) => questions.filter(({ isExtra }) => isExtra).map(({ question, description }, index) => `<span><strong>${oneHExtraQuestionNumber(reportDay, question, index)} ${escapePrintHtml(question)}</strong>${description ? ` (${escapePrintHtml(description)})` : ""}</span>`)).join(' <strong style="font-size:20px;font-weight:900;line-height:1;vertical-align:-2px;padding:0 5px;"> / </strong> ')}</div>`
    : ""}${oneHPrintChecklistsForDate(reportDay).map(
    ({ title, questions }) => {
      const regularQuestions = questions.filter(({ isExtra }) => !isExtra)
      const regularGroups = title === "PYETJET PER 1H - BORD"
        ? [regularQuestions.slice(BOARD_PRIMARY_QUESTION_COUNT), regularQuestions.slice(0, BOARD_PRIMARY_QUESTION_COUNT)]
        : [regularQuestions]
      const regularContent = regularGroups.map((group, groupIndex) =>
        `<div class="one-h-print-checklist-items" data-board-checklist-section="${groupIndex === 0 && regularGroups.length > 1 ? "follow-up" : "primary"}">${group
          .map(({ question, description }, index) =>
            `<span class="one-h-print-checklist-item"><strong>${index + 1}. ${escapePrintHtml(question)}</strong>${
              description ? ` <span class="one-h-print-checklist-description">(${escapePrintHtml(description)})</span>` : ""
            }</span>`
          )
          .join('<span class="one-h-print-checklist-separator"> / </span>')}</div>`
      ).join("")
      return `<div class="one-h-print-checklist"><div class="one-h-print-checklist-title">${escapePrintHtml(title)}</div>${regularContent}</div>`
    }
  ).join("")}</section>`

const oneHMarkerLegendHtml = () =>
  `<div class="one-h-marker-legend"><strong>LEGJENDA:</strong><span><b>?</b> - PYETJE/PAQARTESI</span><i aria-hidden="true">/</i><span><b>!</b> - DYSHIM/ NUK KUPTOHET DET</span><i aria-hidden="true">/</i><span><b>!!!</b> - KLIENT/URGJENT</span><i aria-hidden="true">/</i><span><b class="compact-marker">SHARE</b> - DET QE DUHET SCREENSHARE ME GA</span><i aria-hidden="true">/</i><span><b>👁</b> - KËRKON MONITORIM NGA DIKUSH TJETËR</span><i aria-hidden="true">/</i><span><b>X</b> - MBYLL DETYREN</span><i aria-hidden="true">/</i><span><b class="compact-marker">M2</b> - DOREZIM DERI NE PAUZE</span><i aria-hidden="true">/</i><span><b class="compact-marker">M3</b> - DOREZIM DERI NE FUND TE DITES</span><i aria-hidden="true">/</i><span><b class="compact-marker">M2/3</b> - DOREZIM EDHE NE M2 EDHE M3</span><i aria-hidden="true">/</i><span><b class="compact-marker">GENT</b> - PYETJE/SQARIM ME GENTIN</span><i aria-hidden="true">/</i><span><b class="compact-marker">KA</b> - PYETJE/SQARIM ME KA</span><i aria-hidden="true">/</i><span><b class="compact-marker">GA</b> - PYETJE/SQARIM ME GA</span><i aria-hidden="true">/</i><span><b>F</b> - DET FIZIKISHT</span><i aria-hidden="true">/</i><span><b class="compact-marker">BZ1N1</b></span></div>`

function OneHPrintChecklists({ reportDay }: { reportDay: Date }) {
  return (
    <section className="one-h-print-checklists">
      {oneHDaySpecificQuestionLabel(reportDay) ? (
        <div className="one-h-print-checklist-day-label">
          <strong style={{ marginRight: 12, fontWeight: 900 }}>{oneHDaySpecificQuestionLabel(reportDay)}</strong>
          {oneHPrintChecklistsForDate(reportDay).flatMap(({ questions }) =>
            questions.filter(({ isExtra }) => isExtra).map((question, index) => ({ ...question, number: index }))
          ).map(({ question, description, number }, index) => (
              <React.Fragment key={question}>
                {index > 0 ? <strong style={{ fontSize: 20, fontWeight: 900, lineHeight: 1, verticalAlign: -2, padding: "0 5px" }}> / </strong> : null}
                <span><strong>{oneHExtraQuestionNumber(reportDay, question, number)} {question}</strong>
                  {description ? <span className="one-h-print-checklist-description"> ({description})</span> : null}
                </span>
              </React.Fragment>
          ))}
        </div>
      ) : null}
      {oneHPrintChecklistsForDate(reportDay).map(({ title, questions }) => (
        <div key={title} className="one-h-print-checklist">
          <div className="one-h-print-checklist-title">{title}</div>
          {(title === "PYETJET PER 1H - BORD"
            ? [questions.filter(({ isExtra }) => !isExtra).slice(BOARD_PRIMARY_QUESTION_COUNT), questions.filter(({ isExtra }) => !isExtra).slice(0, BOARD_PRIMARY_QUESTION_COUNT)]
            : [questions.filter(({ isExtra }) => !isExtra)]
          ).map((group, groupIndex) => (
            <div key={`${title}-${groupIndex}`} className="one-h-print-checklist-items" data-board-checklist-section={title === "PYETJET PER 1H - BORD" && groupIndex === 0 ? "follow-up" : "primary"}>
              {group.map(({ question, description }, index) => (
                <React.Fragment key={question}>
                  {index > 0 ? <span className="one-h-print-checklist-separator"> / </span> : null}
                  <span className="one-h-print-checklist-item">
                    <strong>{index + 1}. {question}</strong>
                    {description ? <span className="one-h-print-checklist-description"> ({description})</span> : null}
                  </span>
                </React.Fragment>
              ))}
            </div>
          ))}
        </div>
      ))}
    </section>
  )
}

function OneHMarkerLegend() {
  return (
    <div className="one-h-marker-legend">
      <strong>LEGJENDA:</strong>
      <span><b>?</b> - PYETJE/PAQARTESI</span>
      <i aria-hidden="true">/</i>
      <span><b>!</b> - DYSHIM/ NUK KUPTOHET DET</span>
      <i aria-hidden="true">/</i>
      <span><b>!!!</b> - KLIENT/URGJENT</span>
      <i aria-hidden="true">/</i>
      <span><b className="text-xs">SHARE</b> - DET QE DUHET SCREENSHARE ME GA</span>
      <i aria-hidden="true">/</i>
      <span><b>👁</b> - KËRKON MONITORIM NGA DIKUSH TJETËR</span>
      <i aria-hidden="true">/</i>
      <span><b>X</b> - MBYLL DETYREN</span>
      <i aria-hidden="true">/</i>
      <span><b className="compact-marker">M2</b> - DOREZIM DERI NE PAUZE</span>
      <i aria-hidden="true">/</i>
      <span><b className="compact-marker">M3</b> - DOREZIM DERI NE FUND TE DITES</span>
      <i aria-hidden="true">/</i>
      <span><b className="compact-marker">M2/3</b> - DOREZIM EDHE NE M2 EDHE M3</span>
      <i aria-hidden="true">/</i>
      <span><b className="compact-marker">GENT</b> - PYETJE/SQARIM ME GENTIN</span>
      <i aria-hidden="true">/</i>
      <span><b className="compact-marker">KA</b> - PYETJE/SQARIM ME KA</span>
      <i aria-hidden="true">/</i>
      <span><b className="compact-marker">GA</b> - PYETJE/SQARIM ME GA</span>
      <i aria-hidden="true">/</i>
      <span><b>F</b> - DET FIZIKISHT</span>
      <i aria-hidden="true">/</i>
      <span><b className="compact-marker">BZ1N1</b></span>
    </div>
  )
}

type LateItem = { entryId?: string; person: string; date: string; until: string; start?: string; note?: string }
type AbsentItem = { entryId?: string; person: string; date: string; from: string; to: string; note?: string; userId?: string }
type LeaveItem = {
  entryId?: string
  person: string
  startDate: string
  endDate: string
  fullDay: boolean
  from?: string
  to?: string
  note?: string
  isAllUsers?: boolean
  userId?: string
}
type ExternalHolidayItem = { entryId?: string; title: string; date: string; note?: string }
type InternalMeetingParticipantConflict = {
  userId: string
  userName: string
  reasons: string[]
}
type MeetingAvailability = {
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
type FastTaskItemMeta = {
  taskId?: string
  userId?: string
  departmentId?: string
  fastTaskOrder?: number | null
  finishPeriod?: "AM" | "PM" | null
  oneHReportSlot?: OneHReportSlot | null
  oneHMarker?: OneHMarker | null
  oneHMarkerByGa?: boolean
  oneHMarkerComment?: string | null
  isDeadlineImportant?: boolean
  dueDate?: string | null
  startDate?: string | null
  createdAt?: string | null
  completedAt?: string | null
  dateIsToday?: boolean
  confirmationOwner?: "KA" | "GENT" | null
  isPersonalTask?: boolean
  isSystemTask?: boolean
}
type BlockedItem = {
  title: string
  person: string
  date: string
  note?: string
  assignees?: string[]
  status?: string
  isDone?: boolean
} & FastTaskItemMeta
type OneHItem = {
  title: string
  person: string
  date: string
  note?: string
  assignees?: string[]
  departmentId?: string
  status?: string
  isDone?: boolean
} & FastTaskItemMeta
type PersonalItem = {
  title: string
  person: string
  date: string
  note?: string
  assignees?: string[]
  departmentId?: string
  status?: string
  isDone?: boolean
} & FastTaskItemMeta
type ExternalItem = {
  id?: string
  title: string
  date: string
  time: string
  platform: string
  owner: string
  assignees?: string[]
  department?: string
  recurrenceType?: string | null
  recurrence_type?: string | null
  calendarCategories?: string[]
  calendarImported?: boolean
  calendar_categories?: string[]
  calendar_imported?: boolean
  microsoft_event_id?: string | null
}
type InternalItem = {
  id?: string
  title: string
  date: string
  time: string
  platform: string
  owner: string
  assignees?: string[]
  department?: string
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

const internalMeetingRelation = (meeting: InternalItem): "PARA" | "PAS" | undefined => {
  if (meeting.preExternalMeetingId || meeting.pre_external_meeting_id) return "PARA"
  if (meeting.pairedExternalMeetingId || meeting.paired_external_meeting_id) return "PAS"
  return undefined
}

const expandExternalMeetingDates = (meeting: Meeting, start: Date | null): Date[] => {
  if (!start) return []
  if (
    (meeting.recurrence_type && meeting.recurrence_type !== "none") ||
    !meeting.ends_at
  ) {
    return [start]
  }

  const end = new Date(meeting.ends_at)
  if (Number.isNaN(end.getTime()) || end.getTime() <= start.getTime()) return [start]

  const durationMs = end.getTime() - start.getTime()
  const dayMs = 24 * 60 * 60 * 1000
  const midnightWholeDays =
    durationMs % dayMs === 0 &&
    start.getUTCHours() === 0 &&
    start.getUTCMinutes() === 0 &&
    start.getUTCSeconds() === 0 &&
    end.getUTCHours() === 0 &&
    end.getUTCMinutes() === 0 &&
    end.getUTCSeconds() === 0
  const inclusiveEnd = new Date(end)
  if (midnightWholeDays) {
    inclusiveEnd.setUTCDate(inclusiveEnd.getUTCDate() - 1)
  } else {
    inclusiveEnd.setTime(inclusiveEnd.getTime() - 1)
  }

  const dates: Date[] = []
  const cursor = new Date(start.getFullYear(), start.getMonth(), start.getDate(), 12)
  const last = new Date(inclusiveEnd.getFullYear(), inclusiveEnd.getMonth(), inclusiveEnd.getDate(), 12)
  while (cursor.getTime() <= last.getTime()) {
    dates.push(new Date(cursor))
    cursor.setDate(cursor.getDate() + 1)
  }
  return dates.length ? dates : [start]
}

const isCalendarAnnualLeave = (title?: string, categories?: string[]) =>
  (categories || []).some((category) => category.trim().toLowerCase() === "pv") ||
  /(^|[^a-z0-9])pv([^a-z0-9]|$)/i.test(title || "")
type R1Item = {
  title: string
  date: string
  owner: string
  note?: string
  assignees?: string[]
  departmentId?: string
  status?: string
  isDone?: boolean
} & FastTaskItemMeta
type ProblemItem = {
  entryId?: string
  title: string
  person: string
  date: string
  note?: string
  everyday?: boolean
  createdDate?: string
}
type FeedbackItem = {
  entryId?: string
  title: string
  person: string
  date: string
  note?: string
  everyday?: boolean
  createdDate?: string
}
type PriorityItem = {
  project: string
  date: string
  assignees: string[]
  department_id?: string | null
  department_name?: string | null
}
type BzItem = {
  title: string
  date: string
  time: string
  assignees?: string[]
  bzWithLabel?: string
  taskId?: string
}
type DiamondItem = {
  reviewId: string
  taskId: string | null
  userId: string
  person: string
  taskTitle: string
  date: string
  review: TaskReview
}

type PvTaskShiftPreview = {
  task: Task
  startDateInLeave: boolean
  dueDateInLeave: boolean
}
type PendingPvTaskShift = {
  assigneeId: string
  person: string
  startDate: string
  endDate: string
  moveToDate: string
  tasks: PvTaskShiftPreview[]
}

type CommonBucket =
  | "late"
  | "absent"
  | "leave"
  | "externalHoliday"
  | "blocked"
  | "oneH"
  | "personal"
  | "external"
  | "internal"
  | "r1"
  | "problems"
  | "feedback"
  | "priority"
  | "bz"
type FastTaskRowId = "blocked" | "oneH" | "personal" | PersonalRowId | "r1" | "waitingClient"
type OneHSlotRowId = "oneH" | "oneH10" | "oneH11" | "oneH1150" | "oneH1420" | "oneH1550" | "oneHNoSlot"
type FastTaskEntry = BlockedItem | OneHItem | PersonalItem | R1Item
type CommonWeekTableEntry =
  | LateItem
  | AbsentItem
  | LeaveItem
  | ExternalHolidayItem
  | BlockedItem
  | OneHItem
  | PersonalItem
  | ExternalItem
  | InternalItem
  | BzItem
  | R1Item
  | ProblemItem
  | FeedbackItem
  | PriorityItem
  | DiamondItem
type CommonViewCounts = Record<CommonBucket, number>
type CommonViewGuardrails = {
  max_items_per_bucket: number
  truncated: Record<CommonBucket, boolean>
}
type CommonViewPayload = {
  schema_version: number
  generated_at: string
  week_start: string
  week_end: string
  requested: string[]
  included: string[]
  missing: string[]
  counts: CommonViewCounts
  items: {
    late: LateItem[]
    absent: AbsentItem[]
    leave: LeaveItem[]
    externalHoliday: ExternalHolidayItem[]
    blocked: BlockedItem[]
    oneH: OneHItem[]
    personal: PersonalItem[]
    external: ExternalItem[]
    internal: InternalItem[]
    r1: R1Item[]
    problems: ProblemItem[]
    feedback: FeedbackItem[]
    priority: PriorityItem[]
    bz: BzItem[]
  }
  guardrails: CommonViewGuardrails
  trace_id: string
  timings_ms?: Record<string, number> | null
  users?: User[]
  departments?: Department[]
}

const COMMON_VIEW_CACHE = new Map<
  string,
  { etag: string | null; payload: CommonViewPayload; cachedAt: number }
>()
const COMMON_VIEW_FREEZE_ONE_H_SLOTS_KEY = "commonViewFreezeOneHSlots"

const normalizeCommonTaskStatus = (status?: string | null, isDone?: boolean) => {
  const normalized = (status || "")
    .trim()
    .toUpperCase()
    .replace(/\s+/g, "_")

  if (normalized === "TO_DO") return "TODO"
  if (normalized === "INPROGRESS") return "IN_PROGRESS"
  if (["WFE", "WAITINGCLIENT", "WAITING_FOR_CLIENT"].includes(normalized)) return "WAITING_CLIENT"
  if (normalized) return normalized
  return isDone ? "DONE" : "TODO"
}

const isWaitingClientTask = (entry: { status?: string | null; isDone?: boolean }) =>
  normalizeCommonTaskStatus(entry.status, entry.isDone) === "WAITING_CLIENT"

const isCommonTaskDone = (status?: string | null, isDone?: boolean) =>
  normalizeCommonTaskStatus(status, isDone) === "DONE"

const normalizeCommonDateOnly = (value?: string | null) => {
  if (!value) return null
  const raw = String(value).trim()
  const exact = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw)
  if (exact) return raw
  const parsed = new Date(raw)
  if (Number.isNaN(parsed.getTime())) return null
  const year = parsed.getFullYear()
  const month = String(parsed.getMonth() + 1).padStart(2, "0")
  const day = String(parsed.getDate()).padStart(2, "0")
  return `${year}-${month}-${day}`
}

const isCommonTaskStartingOnDate = (entry: { startDate?: string | null; date?: string | null; entryDate?: string | null }) => {
  const startDate = normalizeCommonDateOnly(entry.startDate)
  const targetDate = normalizeCommonDateOnly(entry.date ?? entry.entryDate)
  return Boolean(startDate && targetDate && startDate === targetDate)
}

const isCommonTaskStartToday = (entry: {
  createdAt?: string | null
  startDate?: string | null
  dueDate?: string | null
}, targetDate?: string | null) => {
  const target = normalizeCommonDateOnly(targetDate)
  return Boolean(
    target &&
    normalizeCommonDateOnly(entry.createdAt) === target &&
    normalizeCommonDateOnly(entry.startDate) === target &&
    normalizeCommonDateOnly(entry.dueDate) === target
  )
}

const isCommonTaskCreatedDayBeforeTarget = (entry: {
  createdAt?: string | null
  date?: string | null
  entryDate?: string | null
}) => {
  const createdDate = normalizeCommonDateOnly(entry.createdAt)
  const targetDate = normalizeCommonDateOnly(entry.date ?? entry.entryDate)
  if (!createdDate || !targetDate) return false

  const previousDay = new Date(`${targetDate}T12:00:00`)
  previousDay.setDate(previousDay.getDate() - 1)
  return createdDate === normalizeCommonDateOnly(previousDay.toISOString())
}

const getCommonWeekStart = (value?: string | null) => {
  const normalized = normalizeCommonDateOnly(value)
  if (!normalized) return null
  const parsed = new Date(`${normalized}T12:00:00`)
  const day = parsed.getDay()
  parsed.setDate(parsed.getDate() - (day === 0 ? 6 : day - 1))
  return normalizeCommonDateOnly(parsed.toISOString())
}

type CommonTaskNewCategory = "created-day-before" | "created-this-week" | "created-last-week"

const COMMON_TASK_NEW_CATEGORY_OPTIONS: ReadonlyArray<{
  value: CommonTaskNewCategory
  label: string
}> = [
  { value: "created-day-before", label: "Dje" },
  { value: "created-this-week", label: "Këtë javë" },
  { value: "created-last-week", label: "Javën e kaluar" },
]

const getCommonTaskNewCategory = (entry: {
  startDate?: string | null
  createdAt?: string | null
  date?: string | null
  entryDate?: string | null
}): CommonTaskNewCategory | null => {
  if (!isCommonTaskStartingOnDate(entry)) return null
  if (isCommonTaskCreatedDayBeforeTarget(entry)) return "created-day-before"

  const createdWeekStart = getCommonWeekStart(entry.createdAt)
  const targetWeekStart = getCommonWeekStart(entry.date ?? entry.entryDate)
  if (!createdWeekStart || !targetWeekStart) return null
  if (createdWeekStart === targetWeekStart) return "created-this-week"

  const previousWeekStart = new Date(`${targetWeekStart}T12:00:00`)
  previousWeekStart.setDate(previousWeekStart.getDate() - 7)
  if (createdWeekStart === normalizeCommonDateOnly(previousWeekStart.toISOString())) {
    return "created-last-week"
  }

  return null
}

const isCommonTaskDeadlineActiveOnDate = (entry: {
  status?: string | null
  isDone?: boolean
  isDeadlineImportant?: boolean
  startDate?: string | null
  date?: string | null
  entryDate?: string | null
}) => {
  if (!entry.isDeadlineImportant) return false
  if (isCommonTaskDone(entry.status, entry.isDone)) return false
  const startDate = normalizeCommonDateOnly(entry.startDate)
  const targetDate = normalizeCommonDateOnly(entry.date ?? entry.entryDate)
  return Boolean(startDate && targetDate && targetDate >= startDate)
}

const commonTaskHighlightClassName = (entry: {
  status?: string | null
  isDone?: boolean
  isDeadlineImportant?: boolean
  dueDate?: string | null
  startDate?: string | null
  createdAt?: string | null
  date?: string | null
  entryDate?: string | null
}) => {
  if (isCommonTaskDeadlineActiveOnDate(entry)) return "deadline-important"
  const newCategory = getCommonTaskNewCategory(entry)
  if (newCategory) {
    return [
      "new-task-emphasis",
      newCategory,
    ].filter(Boolean).join(" ")
  }
  return ""
}

const commonTaskStateClassName = (status?: string | null, isDone?: boolean) => {
  if (status == null && typeof isDone !== "boolean") return ""

  const normalized = normalizeCommonTaskStatus(status, isDone)

  if (normalized === "DONE") return "task-state-done"
  if (normalized === "IN_PROGRESS") return "task-state-in-progress"
  if (normalized === "WAITING_CONFIRMATION") return "task-state-waiting"
  if (normalized === "WAITING_CLIENT") return "task-state-waiting-client"
  if (normalized === "TODO") return "task-state-todo"
  return ""
}

const renderCommonTaskStatusIndicator = (
  entry: { status?: string | null; isDone?: boolean; isDeadlineImportant?: boolean },
  isPersonal = false,
) => {
  if (!entry.isDeadlineImportant && !isPersonal) return null
  if (entry.status == null && typeof entry.isDone !== "boolean") return null
  const status = normalizeCommonTaskStatus(entry.status, entry.isDone)
  const indicators: Record<string, { label: string; symbol: string; tone: string }> = {
    TODO: { label: "To do", symbol: "○", tone: "todo" },
    IN_PROGRESS: { label: "In progress", symbol: "◔", tone: "in-progress" },
    DONE: { label: "Done", symbol: "✓", tone: "done" },
    WAITING_CONFIRMATION: { label: "Waiting confirmation", symbol: "◷", tone: "waiting" },
    WAITING_CLIENT: { label: "Waiting client", symbol: "◷", tone: "waiting-client" },
  }
  const indicator = indicators[status]
  if (!indicator) return null
  return (
    <span className={`common-task-status-indicator status-${indicator.tone}`} title={`Status: ${indicator.label}`} aria-label={`Status: ${indicator.label}`}>
      {indicator.label}
    </span>
  )
}

type CommonColorFilter = "all" | "pink" | "yellow" | "red" | "green" | "orange" | "gold"
type CommonTaskFocusFilter = "all" | "new" | "eightAm" | "deadline" | "startToday"

const getCommonTaskColor = (entry: {
  status?: string | null
  isDone?: boolean
  isDeadlineImportant?: boolean
  startDate?: string | null
  date?: string | null
  entryDate?: string | null
}): Exclude<CommonColorFilter, "all"> | null => {
  const normalized = normalizeCommonTaskStatus(entry.status, entry.isDone)
  if (normalized === "DONE") return "green"
  if (isCommonTaskDeadlineActiveOnDate(entry)) return "red"
  if (normalized === "IN_PROGRESS") return "yellow"
  if (normalized === "WAITING_CONFIRMATION") return "orange"
  if (normalized === "WAITING_CLIENT") return "gold"
  if (normalized === "TODO") return "pink"
  return null
}

const commonTaskSortRank = (status?: string | null, isDone?: boolean) => {
  const normalized = normalizeCommonTaskStatus(status, isDone)

  if (normalized === "DONE") return 3
  if (normalized === "WAITING_CONFIRMATION") return 2
  if (normalized === "IN_PROGRESS") return 1
  return 0
}

type SwimlaneCell = {
  title: string
  meetingTimeLabel?: string
  meetingRelation?: "PARA" | "PAS"
  isManualInternalMeeting?: boolean
  isCalendarMeeting?: boolean
  subtitle?: string
  dateLabel?: string
  note?: string
  accentClass?: string
  assignees?: string[]
  assigneeLabels?: string[]
  placeholder?: boolean
  entryId?: string
  number?: number
  entryDate?: string
  status?: string
  isDone?: boolean
  taskId?: string
  userId?: string
  fastTaskOrder?: number | null
  finishPeriod?: "AM" | "PM" | null
  oneHReportSlot?: OneHReportSlot | null
  oneHMarker?: OneHMarker | null
  oneHMarkerByGa?: boolean
  oneHMarkerComment?: string | null
  isDeadlineImportant?: boolean
  dueDate?: string | null
  startDate?: string | null
  createdAt?: string | null
  completedAt?: string | null
  dateIsToday?: boolean
  recurrenceType?: string | null
  meetingId?: string
  isSystemTask?: boolean
}
type SwimlaneRow = {
  id: CommonType
  label: string
  count: number
  countLabel?: string
  headerClass: string
  badgeClass: string
  badges?: { value: number; className: string; label?: string }[]
  headerBreakdown?: { value: number; label: string; className?: string }[]
  missingOneHUsers?: { id: string; label: string; initials: string; hasBlockedTask: boolean }[]
  missingBlockedUsers?: { id: string; label: string; initials: string; hasOneHAt16: boolean }[]
  items: SwimlaneCell[]
}

const COMMON_COLOR_FILTER_OPTIONS: {
  value: CommonColorFilter
  label: string
  swatch: string
}[] = [
  { value: "pink", label: "Pink", swatch: "#fbcfe8" },
  { value: "yellow", label: "Yellow", swatch: "#fef3c7" },
  { value: "red", label: "Red", swatch: "#dc2626" },
  { value: "green", label: "Green", swatch: "#d4ffe1" },
  { value: "orange", label: "Orange", swatch: "#ffedd5" },
  { value: "gold", label: "Gold", swatch: "#E2C15B" },
]

type MeetingColumnKey = "nr" | "day" | "topic" | "check" | "owner" | "time"
type MeetingColumn = { key: MeetingColumnKey; label: string; width?: string }
type MeetingCheckStatus = "none" | "check" | "x" | "o"
type MeetingRow = {
  id: string
  nr: number
  day?: string
  topic: string
  owner?: string
  time?: string
  isChecked?: boolean
  checkStatus?: MeetingCheckStatus
  comment?: string
}
type MeetingTemplate = {
  id: string
  title: string
  note?: string
  groupKey?: string
  columns: MeetingColumn[]
  rows: MeetingRow[]
  defaultOwner?: string
  defaultTime?: string
  position?: number
}

type MeetingChecklist = {
  id: string
  title: string
  note?: string | null
  default_owner?: string | null
  default_time?: string | null
  group_key?: string | null
  columns?: MeetingColumn[] | null
  position?: number | null
  items?: {
    id: string
    position: number
    title?: string | null
    day?: string | null
    owner?: string | null
    time?: string | null
    comment?: string | null
    is_checked?: boolean | null
  }[]
}

const DEFAULT_MEETING_COLUMNS: MeetingColumn[] = [
  { key: "nr", label: "NR", width: "52px" },
  { key: "topic", label: "M1 PIKAT", width: "860px" },
  { key: "check", label: "", width: "48px" },
  { key: "owner", label: "WHO", width: "90px" },
  { key: "time", label: "WHEN", width: "90px" },
]

const ALL_USERS_VALUE = "__all__"
const ALL_USERS_LABEL = "All users"
const ALL_USERS_INITIALS = "ALL"
const ALL_USERS_MARKER = "[ALL_USERS]"
const FEEDBACK_DAILY_MARKER = "[EVERYDAY]"
const MEETING_CHECK_STATUS_RE = /\[MEETING_CHECK_STATUS:(CHECK|X|O)\]/i
const ONE_H_REPORT_SLOT_OPTIONS = ["10:00", "11:00", "11:50", "14:20", "16:00"] as const
type OneHReportSlot = typeof ONE_H_REPORT_SLOT_OPTIONS[number]
const ONE_H_REPORT_SLOT_SET = new Set<string>(ONE_H_REPORT_SLOT_OPTIONS)
const ONE_H_SLOT_ROWS: Array<{ id: OneHSlotRowId; slot: OneHReportSlot | null; label: string }> = [
  { id: "oneH10", slot: "10:00", label: "1H 10:00" },
  { id: "oneH11", slot: "11:00", label: "1H 11:00" },
  { id: "oneH1150", slot: "11:50", label: "1H 11:50" },
  { id: "oneH1420", slot: "14:20", label: "1H 14:20" },
  { id: "oneH1550", slot: "16:00", label: "1H 16:00" },
  { id: "oneHNoSlot", slot: null, label: "1H NO SLOT" },
]
const toLocalDateTimeInput = (value: string | Date) => {
  const date = value instanceof Date ? value : new Date(value)
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}
const toLocalTimeInput = (value: string | Date) => toLocalDateTimeInput(value).slice(11, 16)

const normalizeOneHReportSlot = (value?: string | null): OneHReportSlot | null => {
  const normalized = (value || "").trim()
  return ONE_H_REPORT_SLOT_SET.has(normalized) ? (normalized as OneHReportSlot) : null
}

const oneHReportSlotRank = (value?: string | null) => {
  const normalized = normalizeOneHReportSlot(value)
  if (!normalized) return ONE_H_REPORT_SLOT_OPTIONS.length
  const index = ONE_H_REPORT_SLOT_OPTIONS.indexOf(normalized)
  return index >= 0 ? index : ONE_H_REPORT_SLOT_OPTIONS.length
}

const getOneHReportSlotLabel = (value?: string | null) => normalizeOneHReportSlot(value) || "No slot"
const isOneHSlotRowId = (rowId: CommonType): rowId is OneHSlotRowId =>
  rowId === "oneH" || rowId === "oneH10" || rowId === "oneH11" || rowId === "oneH1150" || rowId === "oneH1420" || rowId === "oneH1550" || rowId === "oneHNoSlot"
const getOneHSlotRowSlot = (rowId: CommonType): OneHReportSlot | null | undefined =>
  ONE_H_SLOT_ROWS.find((row) => row.id === rowId)?.slot

const getMeetingCheckStatus = (isChecked?: boolean | null, comment?: string | null): MeetingCheckStatus => {
  const match = (comment || "").match(MEETING_CHECK_STATUS_RE)
  const markerValue = match?.[1]?.toUpperCase()
  if (markerValue === "X") return "x"
  if (markerValue === "O") return "o"
  if (markerValue === "CHECK") return "check"
  return isChecked ? "check" : "none"
}

const buildMeetingCheckComment = (status: MeetingCheckStatus, comment?: string | null) => {
  const cleaned = (comment || "").replace(MEETING_CHECK_STATUS_RE, "").trim()
  if (status === "none" || status === "check") return cleaned
  const marker = status === "x" ? "[MEETING_CHECK_STATUS:X]" : "[MEETING_CHECK_STATUS:O]"
  return cleaned ? `${cleaned}\n${marker}` : marker
}

const parseFeedbackNote = (note: string | null | undefined) => {
  const raw = note || ""
  const everyday = raw.includes(FEEDBACK_DAILY_MARKER)
  const cleaned = raw.split(FEEDBACK_DAILY_MARKER).join("").trim()
  return { note: cleaned || undefined, everyday }
}

const parseFilenameFromDisposition = (headerValue: string | null) => {
  if (!headerValue) return ""
  const match =
    /filename\*=(?:UTF-8'')?([^;]+)/i.exec(headerValue) || /filename=\"?([^\";]+)\"?/i.exec(headerValue)
  if (!match) return ""
  try {
    return decodeURIComponent(match[1].trim().replace(/^\"|\"$/g, ""))
  } catch {
    return match[1].trim().replace(/^\"|\"$/g, "")
  }
}

const initials = (name: string) => {
  const cleaned = name.trim()
  if (!cleaned) return "?"
  if (cleaned.replace(/\s+/g, " ").toLocaleLowerCase() === "haris shaqiri") return "HSH"
  const parts = cleaned.split(/\s+/)
  const first = parts[0]?.[0] || ""
  const last = parts.length > 1 ? parts[parts.length - 1]?.[0] || "" : ""
  return `${first}${last}`.toUpperCase()
}
const getKaGentiConfirmationOwner = (
  confirmationUser?: Pick<User, "full_name" | "username" | "email"> | null
): "KA" | "GENT" | null => {
  if (!confirmationUser) return null
  const fullName = (confirmationUser.full_name || "").trim()
  const firstName = fullName.match(/[^\W\d_]+/u)?.[0]?.toLowerCase()
  if (firstName === "gent" || firstName === "genti") return "GENT"
  if (initials(fullName) === "KA") return "KA"

  const username = (confirmationUser.username || "").trim().toLowerCase()
  const email = (confirmationUser.email || "").trim().toLowerCase()
  if (username === "gent.arifaj" || email === "g.arifaj@primexeu.com") return "GENT"
  if (username === "kosove.arifaj" || email === "kosove.arifaj@ht-furniture.de") return "KA"
  return null
}
const stripInitialsPrefix = (value: string) => {
  return value
}
const commonPrintTitleLine = (value: string) =>
  getPlainMarkedText(stripInitialsPrefix(value))
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find(Boolean) || ""
const stripTaskInitialsPrefix = (value: string) =>
  value.replace(/^[A-Z]{1,4}(?:\/[A-Z]{1,4})*:\s*/, "")
const commonPrintTaskTitle = (entry: { title: string; assignees?: string[]; person?: string; owner?: string }) => {
  const title = stripTaskInitialsPrefix(commonPrintTitleLine(entry.title))
  const assigneeInitials = entryAssignees(entry).map((name) => initials(name)).filter(Boolean)
  return assigneeInitials.length ? `${assigneeInitials.join("/")}: ${title}` : title
}
const commonPrintPersonalTaskTitle = (entry: { title: string }) => commonPrintTitleLine(entry.title)
const renderWfcText = (value: string) =>
  value.split(/(\bWFC\b)/gi).map((part, index) =>
    /^WFC$/i.test(part) ? (
      <span key={`wfc-${index}`} className="task-title-wfc">{part}</span>
    ) : (
      part
    )
  )
const highlightWfcReactNode = (node: React.ReactNode): React.ReactNode => {
  if (typeof node === "string") return renderWfcText(node)
  if (Array.isArray(node)) return node.map((child) => highlightWfcReactNode(child))
  if (React.isValidElement<{ children?: React.ReactNode }>(node)) {
    return React.cloneElement(node, undefined, highlightWfcReactNode(node.props.children))
  }
  return node
}
const commonPrintTitleHtml = (value: string) =>
  value
    .split(/(\bWFC\b)/gi)
    .map((part) =>
      /^WFC$/i.test(part)
        ? `<span class="task-title-wfc" style="color:#DC2626;font-weight:800;">${escapePrintHtml(part)}</span>`
        : escapePrintHtml(part)
    )
    .join("")
const getPersonalTaskGroup = (entry: { title: string }): PersonalTaskGroup => {
  const titlePrefix = commonPrintPersonalTaskTitle(entry).trim().toUpperCase()
  const match = titlePrefix.match(/^[A-Z]{1,5}(?:\s*[:/]\s*[A-Z]{1,5})*(?=\s|:|\/|$)/)
  const participants = (match?.[0] || "").split(/[:/]/).map((value) => value.trim())
  if (participants.some((value) => ["GENT", "GENTI", "GT"].includes(value))) return "GENT"
  if (participants.includes("KA")) return "KA"
  if (participants.includes("GA")) return "GA"
  return "PX"
}
const getPersonalRowGroup = (rowId: PersonalRowId): PersonalTaskGroup =>
  rowId === "personalGA" ? "GA" : rowId === "personalKA" ? "KA" : rowId === "personalGENT" ? "GENT" : "PX"
const isPersonalRowId = (rowId: CommonType): rowId is PersonalRowId =>
  PERSONAL_ROW_IDS.includes(rowId as PersonalRowId)
const isWaitingConfirmationTask = (entry: { status?: string | null; isDone?: boolean }) =>
  normalizeCommonTaskStatus(entry.status, entry.isDone) === "WAITING_CONFIRMATION"
const isAppendedWaitingConfirmation = (entry: FastTaskItemMeta & { status?: string | null; isDone?: boolean }) =>
  entry.isPersonalTask === false && isWaitingConfirmationTask(entry) && Boolean(entry.confirmationOwner)
const isRoutedWaitingConfirmation = (entry: FastTaskItemMeta & { status?: string | null; isDone?: boolean }) =>
  isWaitingConfirmationTask(entry) && Boolean(entry.confirmationOwner)
const renderWfcIndicator = (entry: { status?: string | null; isDone?: boolean }) =>
  isWaitingConfirmationTask(entry) ? (
    <span className="wfc-indicator" title="Waiting for confirmation">WFC</span>
  ) : null
const personalTasksForRow = <T extends FastTaskItemMeta & { title: string; status?: string | null; isDone?: boolean }>(
  items: readonly T[],
  rowId: PersonalRowId
) => {
  const group = getPersonalRowGroup(rowId)
  const personal = items.filter(
    (item) => !isAppendedWaitingConfirmation(item) && getPersonalTaskGroup(item) === group
  )
  const waitingConfirmation = items.filter(
    (item) => isAppendedWaitingConfirmation(item) && item.confirmationOwner === group
  )
  return [...personal, ...waitingConfirmation]
}

const getCommonTitleMarkClass = (isDone: boolean, isAdded: boolean) => {
  if (isDone && isAdded) {
    return "rounded bg-blue-100 px-1 text-emerald-900 ring-1 ring-blue-300 line-through decoration-emerald-700 decoration-2"
  }
  if (isAdded) return "rounded bg-blue-200 px-1 text-blue-950 ring-1 ring-blue-300"
  if (isDone) return "rounded bg-emerald-100 px-1 text-emerald-800 line-through decoration-emerald-700 decoration-2"
  return ""
}

const renderCommonMarkedTitleLine = (value: string) => {
  const parsed = parseMarkedNoteContent(stripInitialsPrefix(value))
  const lineMatch = parsed.text.match(/[^\r\n]+/g)?.find((line) => line.trim())
  if (!lineMatch) return ""

  const rawStart = parsed.text.indexOf(lineMatch)
  const leadingTrim = lineMatch.length - lineMatch.trimStart().length
  const trailingTrim = lineMatch.length - lineMatch.trimEnd().length
  const start = rawStart + leadingTrim
  const end = rawStart + lineMatch.length - trailingTrim
  const boundaries = new Set([start, end])

  parsed.doneRanges.forEach((range) => {
    if (range.end > start && range.start < end) {
      boundaries.add(Math.max(start, range.start))
      boundaries.add(Math.min(end, range.end))
    }
  })
  parsed.addedRanges.forEach((range) => {
    if (range.end > start && range.start < end) {
      boundaries.add(Math.max(start, range.start))
      boundaries.add(Math.min(end, range.end))
    }
  })
  for (const match of parsed.text.slice(start, end).matchAll(/\bWFC\b/gi)) {
    const tokenStart = start + (match.index || 0)
    boundaries.add(tokenStart)
    boundaries.add(tokenStart + match[0].length)
  }

  const orderedBoundaries = Array.from(boundaries).sort((a, b) => a - b)
  const parts: React.ReactNode[] = []
  for (let idx = 0; idx < orderedBoundaries.length - 1; idx += 1) {
    const partStart = orderedBoundaries[idx]
    const partEnd = orderedBoundaries[idx + 1]
    const segment = parsed.text.slice(partStart, partEnd)
    if (!segment) continue
    const isDone = parsed.doneRanges.some((range) => range.start <= partStart && range.end >= partEnd)
    const isAdded = parsed.addedRanges.some((range) => range.start <= partStart && range.end >= partEnd)
    const className = getCommonTitleMarkClass(isDone, isAdded)
    const content = /^WFC$/i.test(segment)
      ? <span key={`title-wfc-${idx}-${partStart}`} className="task-title-wfc">{segment}</span>
      : segment
    parts.push(
      className ? (
        <span key={`title-mark-${idx}-${partStart}`} className={className}>
          {content}
        </span>
      ) : (
        content
      )
    )
  }

  return parts.length ? parts : commonPrintTitleLine(value)
}

const normalizeTitle = (t: string) => t.replace(/\s+/g, " ").trim().toLowerCase()
const mergePersonalItems = (items: PersonalItem[]): PersonalItem[] => {
  const merged = new Map<string, PersonalItem>()
  for (const item of items) {
    const key = `${normalizeTitle(item.title)}\0${item.date}`
    const existing = merged.get(key)
    const itemNames = item.assignees?.length
      ? item.assignees
      : item.person
        ? item.person.split(",").map((s) => s.trim()).filter(Boolean)
        : []
    if (existing) {
      const seen = new Set((existing.assignees || []).map((a) => a.toLowerCase()))
      for (const name of itemNames) {
        if (!seen.has(name.toLowerCase())) {
          existing.assignees = [...(existing.assignees || []), name]
          seen.add(name.toLowerCase())
        }
      }
      existing.person = (existing.assignees || []).join(", ")
      if (existing.isDone && !item.isDone) {
        existing.isDone = false
        existing.status = item.status
      }
    } else {
      merged.set(key, { ...item, assignees: [...itemNames] })
    }
  }
  return Array.from(merged.values())
}
const normalizeAssigneeList = (value?: string) =>
  value
    ? value
        .split(",")
        .map((v) => v.trim())
        .filter(Boolean)
    : []
const entryAssignees = (entry: { assignees?: string[]; person?: string; owner?: string }) =>
  entry.assignees && entry.assignees.length
    ? entry.assignees
    : normalizeAssigneeList(entry.person || entry.owner || "")
const isFastTaskRowId = (rowId: CommonType): rowId is FastTaskRowId | OneHSlotRowId =>
  rowId === "blocked" || isOneHSlotRowId(rowId) || rowId === "personal" || isPersonalRowId(rowId) || rowId === "r1" || rowId === "waitingClient"
const isPrintDedupeTaskRowId = (rowId: CommonType) =>
  rowId === "blocked" || isOneHSlotRowId(rowId) || rowId === "personal" || isPersonalRowId(rowId) || rowId === "r1" || rowId === "waitingClient"
const isShtypiTaskRowId = (rowId: CommonType) =>
  rowId === "blocked" || isOneHSlotRowId(rowId) || rowId === "personal" || isPersonalRowId(rowId) || rowId === "r1" || rowId === "waitingClient"

const getFastTaskAssigneeKey = (entry: FastTaskEntry) => {
  const person = "person" in entry ? entry.person : ""
  const owner = "owner" in entry ? entry.owner : ""
  return (entry.userId || person || owner || "").trim().toLowerCase()
}

const getFastTaskEntryDate = (entry: FastTaskEntry | SwimlaneCell) =>
  ("date" in entry ? entry.date : entry.entryDate) || ""

const getPrintTaskDedupeKey = (rowId: CommonType, entry: FastTaskEntry | SwimlaneCell) =>
  [
    rowId,
    normalizeTitle(entry.title || ""),
    getFastTaskEntryDate(entry),
    normalizeOneHReportSlot(entry.oneHReportSlot) || "",
    (entry.finishPeriod || "").trim().toUpperCase(),
    entry.oneHMarker || "",
    normalizeTitle(entry.note || ""),
  ].join("\0")

const mergeAssigneeNames = (current: string[], next: string[]) => {
  const merged = [...current]
  const seen = new Set(merged.map((name) => name.trim().toLowerCase()).filter(Boolean))
  for (const name of next) {
    const trimmed = name.trim()
    if (!trimmed) continue
    const key = trimmed.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(trimmed)
  }
  return merged
}

const mergePrintTaskEntries = <T extends FastTaskEntry | SwimlaneCell>(rowId: CommonType, entries: T[]): T[] => {
  if (!isPrintDedupeTaskRowId(rowId)) return entries

  const merged = new Map<string, T>()
  for (const entry of entries) {
    const key = getPrintTaskDedupeKey(rowId, entry)
    const existing = merged.get(key)
    if (!existing) {
      merged.set(key, { ...entry, assignees: [...entryAssignees(entry)] })
      continue
    }

    const existingRank = commonTaskSortRank(existing.status, existing.isDone)
    const nextRank = commonTaskSortRank(entry.status, entry.isDone)
    const strongestStatus =
      nextRank < existingRank
        ? { status: entry.status, isDone: entry.isDone, completedAt: entry.completedAt }
        : { status: existing.status, isDone: existing.isDone, completedAt: existing.completedAt }

    merged.set(key, {
      ...existing,
      ...strongestStatus,
      assignees: mergeAssigneeNames(entryAssignees(existing), entryAssignees(entry)),
      isDeadlineImportant: Boolean(existing.isDeadlineImportant || entry.isDeadlineImportant),
      dateIsToday: Boolean(existing.dateIsToday || entry.dateIsToday),
      dueDate: existing.dueDate || entry.dueDate,
      startDate: existing.startDate || entry.startDate,
      oneHReportSlot: existing.oneHReportSlot || entry.oneHReportSlot,
      oneHMarker: existing.oneHMarker || entry.oneHMarker,
    })
  }

  return Array.from(merged.values())
}

const getSwimlaneTaskUserKey = (entry: SwimlaneCell | null) => {
  if (!entry || entry.placeholder) return ""
  if (entry.userId) return entry.userId.trim().toLowerCase()
  const assigneeKey = (entry.assignees || entry.assigneeLabels || [])
    .map((name) => name.trim().toLowerCase())
    .filter(Boolean)
    .join("|")
  return assigneeKey || entry.title.trim().toLowerCase()
}

const getFastTaskDisplayNumber = (
  entries: Array<FastTaskEntry | SwimlaneCell>,
  entry: FastTaskEntry | SwimlaneCell
) => {
  if (!entry.userId) return 1
  const peerEntries = entries.filter(
    (item) => item.userId === entry.userId && getFastTaskEntryDate(item) === getFastTaskEntryDate(entry)
  )
  const currentIndex = peerEntries.findIndex((item) => item.taskId === entry.taskId)
  return currentIndex >= 0 ? currentIndex + 1 : 1
}

const hasEightAmIndicator = (title?: string | null, isSystemTask = false) =>
  /\b0?8:00\b/.test(title || "") || (!isSystemTask && /\bEM\b/i.test(title || ""))
const getFinishPeriodIndicatorLabel = (finishPeriod?: string | null) => {
  const normalized = (finishPeriod || "").trim().toUpperCase()
  return normalized === "AM" || normalized === "PM" ? normalized : ""
}

const getCommonTaskPeriodLabel = (finishPeriod?: string | null) =>
  getFinishPeriodIndicatorLabel(finishPeriod) || "AM/PM"

const isOneTimeMeeting = (recurrenceType?: string | null) => {
  const normalized = (recurrenceType || "").trim().toLowerCase()
  return !normalized || normalized === "none"
}

export default function CommonViewPage() {
  const { apiFetch, user, loading: authLoading } = useAuth()
  const confirm = useConfirm()
  const userId = user?.id ?? null
  const isAdmin = user?.role === "ADMIN"
  const isManager = user?.role === "MANAGER"
  const isStaff = user?.role === "STAFF"
  const canManageTaskReviews = Boolean(isAdmin || isManager)
  const canEditMeetingTemplates = Boolean(isAdmin || isManager)
  const canDeleteCommon = Boolean(isAdmin || isManager || isStaff)
  // Common view should show all data for all roles (same as admin)
  const commonDepartmentId = ""
  const printedAt = React.useMemo(() => new Date(), [])
  const printInitials = initials(user?.full_name || user?.username || "")
  const stickyRef = React.useRef<HTMLDivElement | null>(null)
  const [stickyOffset, setStickyOffset] = React.useState("0px")
  const [reorderingTaskId, setReorderingTaskId] = React.useState<string | null>(null)
  const [savingOneHMarkerTaskId, setSavingOneHMarkerTaskId] = React.useState<string | null>(null)

  React.useEffect(() => {
    const node = stickyRef.current
    if (!node) return

    const updateOffset = () => {
      const height = node.getBoundingClientRect().height
      const next = `${Math.ceil(height)}px`
      setStickyOffset((prev) => (prev === next ? prev : next))
    }

    updateOffset()

    let resizeObserver: ResizeObserver | null = null
    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(() => updateOffset())
      resizeObserver.observe(node)
    }

    const handleResize = () => updateOffset()
    window.addEventListener("resize", handleResize)
    return () => {
      resizeObserver?.disconnect()
      window.removeEventListener("resize", handleResize)
    }
  }, [])

  // Utils
  const pad2 = (n: number) => String(n).padStart(2, "0")
  const toISODate = (d: Date) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
  const fromISODate = (s: string) => {
    const [y, m, d] = s.split("-").map(Number)
    return new Date(y, m - 1, d)
  }
  const parseDateOnly = (value?: string | null) => {
    if (!value) return null
    const raw = String(value).trim()
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw)
    if (match) {
      const year = Number(match[1])
      const month = Number(match[2])
      const day = Number(match[3])
      if (Number.isNaN(year) || Number.isNaN(month) || Number.isNaN(day)) return null
      const parsed = new Date(year, month - 1, day)
      return Number.isNaN(parsed.getTime()) ? null : parsed
    }
    const parsed = new Date(raw)
    if (Number.isNaN(parsed.getTime())) return null
    // Use local calendar date to avoid UTC date shifts for ISO timestamps.
    return new Date(parsed.getFullYear(), parsed.getMonth(), parsed.getDate())
  }
  // Convert ISO date (YYYY-MM-DD) to DD/MM/YYYY
  const toDDMMYYYY = (isoDate: string) => {
    if (!isoDate) return ""
    const [y, m, d] = isoDate.split("-").map(Number)
    return `${pad2(d)}/${pad2(m)}/${y}`
  }
  // Convert DD/MM/YYYY to ISO date (YYYY-MM-DD)
  const fromDDMMYYYY = (ddmmyyyy: string) => {
    if (!ddmmyyyy) return ""
    const parts = ddmmyyyy.split("/")
    if (parts.length !== 3) return ""
    const [d, m, y] = parts.map(Number)
    if (isNaN(d) || isNaN(m) || isNaN(y)) return ""
    if (d < 1 || d > 31 || m < 1 || m > 12) return ""
    return `${y}-${pad2(m)}-${pad2(d)}`
  }
  const toDDMMYYYYDot = (isoDate: string) => toDDMMYYYY(isoDate).replaceAll("/", ".")
  const addDays = (d: Date, n: number) => {
    const x = new Date(d)
    x.setDate(x.getDate() + n)
    return x
  }
  const getMonday = (d: Date) => {
    const date = new Date(d.getFullYear(), d.getMonth(), d.getDate())
    const day = date.getDay()
    const diff = (day === 0 ? -6 : 1) - day
    date.setDate(date.getDate() + diff)
    return date
  }
  const getWeekdays = (monday: Date) => [0, 1, 2, 3, 4].map((i) => addDays(monday, i))
  const formatDateHuman = (s: string) => {
    const d = fromISODate(s)
    return `${pad2(d.getDate())}.${pad2(d.getMonth() + 1)}.${d.getFullYear()}`
  }
  const formatTime = (d: Date) =>
    d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true })
  const formatAlignmentTime = (value?: string | null) => {
    if (!value) return "TBD"
    const match = String(value).match(/^(\d{2}:\d{2})/)
    return match ? match[1] : String(value)
  }
  const parseTimeValue = (value: string) => {
    const match = /^(\d{2}):(\d{2})$/.exec(value)
    if (!match) return null
    const hours = Number(match[1])
    const minutes = Number(match[2])
    if (Number.isNaN(hours) || Number.isNaN(minutes)) return null
    if (hours < 0 || hours > 23 || minutes < 0 || minutes > 59) return null
    return { hours, minutes }
  }
  const parseTimeToMinutes = React.useCallback((value?: string | null) => {
    if (!value) return null
    let normalized = value.trim()
    if (!normalized) return null
    normalized = normalized.replace(/[()]/g, "").trim()
    const lower = normalized.toLowerCase()
    if (lower === "tbd" || lower === "n/a" || lower === "na") return null
    if (normalized.includes("–") || normalized.includes("—") || normalized.includes("-")) {
      const separator = normalized.includes("–") ? "–" : normalized.includes("—") ? "—" : "-"
      normalized = normalized.split(separator)[0].trim()
    }
    const amPmMatch = /^(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b/i.exec(normalized)
    if (amPmMatch) {
      let hours = Number(amPmMatch[1])
      const minutes = Number(amPmMatch[2] ?? "0")
      if (Number.isNaN(hours) || Number.isNaN(minutes)) return null
      if (hours < 1 || hours > 12 || minutes < 0 || minutes > 59) return null
      const isPm = amPmMatch[3].toLowerCase() === "pm"
      hours = hours % 12
      if (isPm) hours += 12
      return hours * 60 + minutes
    }
    const timeMatch = /^(\d{1,2}):(\d{2})$/.exec(normalized)
    if (!timeMatch) return null
    const hours = Number(timeMatch[1])
    const minutes = Number(timeMatch[2])
    if (Number.isNaN(hours) || Number.isNaN(minutes)) return null
    if (hours < 0 || hours > 23 || minutes < 0 || minutes > 59) return null
    return hours * 60 + minutes
  }, [])
  const toMeetingTimeValue = (value?: string | null) => {
    if (!value) return ""
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return ""
    const pad2 = (n: number) => String(n).padStart(2, "0")
    return `${pad2(date.getHours())}:${pad2(date.getMinutes())}`
  }
  const formatTimeLabel = (value?: string): string => {
    if (!value) return ""
    const normalized = value.trim()
    if (!normalized || normalized.toLowerCase() === "tbd") return normalized
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
  const formatFastTaskDateLabel = (
    date: string,
    isDone?: boolean,
    completedAt?: string | null,
    startDate?: string | null,
    dueDate?: string | null
  ) => {
    if (isDone && completedAt) {
      const completed = new Date(completedAt)
      if (!Number.isNaN(completed.getTime())) {
        return formatTime(completed)
      }
    }
    const start = parseDateOnly(startDate || date)
    const due = parseDateOnly(dueDate || "")
    const startLabel = start ? formatDateHuman(toISODate(start)) : formatDateHuman(date)
    if (!due) return startLabel

    const dueLabel = formatDateHuman(toISODate(due))
    return `${startLabel} - ${dueLabel}`
  }
  const isFastTaskDateOnTarget = (value?: string | null, targetDate?: string | null) => {
    const normalizedValue = normalizeCommonDateOnly(value)
    const normalizedTarget = normalizeCommonDateOnly(targetDate)
    return Boolean(normalizedValue && normalizedTarget && normalizedValue === normalizedTarget)
  }
  const formatFastTaskCardDate = (value?: string | null, targetDate?: string | null) => {
    const parsed = parseDateOnly(value || "")
    if (!parsed) return null
    const normalizedDate = toISODate(parsed)
    return isFastTaskDateOnTarget(normalizedDate, targetDate)
      ? "SOT"
      : formatDateHuman(normalizedDate)
  }
  const computeNextOccurrenceDate = (params: {
    recurrenceType: "weekly" | "monthly" | "yearly"
    daysOfWeek: number[]
    daysOfMonth: number[]
    timeValue: string
    monthOfYear?: number
  }) => {
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
  const computeNextMeetingOccurrence = (meeting: Meeting) => {
    const recurrenceType = meeting.recurrence_type
    if (!recurrenceType || recurrenceType === "none") return null
    const timeValue = toMeetingTimeValue(meeting.starts_at)
    if (!timeValue) return null
    return computeNextOccurrenceDate({
      recurrenceType: recurrenceType as "weekly" | "monthly" | "yearly",
      daysOfWeek: meeting.recurrence_days_of_week || [],
      daysOfMonth: meeting.recurrence_days_of_month || [],
      timeValue,
      monthOfYear: meeting.starts_at ? new Date(meeting.starts_at).getMonth() : undefined,
    })
  }
  const resolveExternalMeetingDate = (meeting: Meeting) => {
    const next = computeNextMeetingOccurrence(meeting)
    if (next) return next
    if (!meeting.starts_at) return null
    const date = new Date(meeting.starts_at)
    if (Number.isNaN(date.getTime())) return null
    return date
  }
  const formatExternalMeetingWhen = (meeting: Meeting) => {
    const resolvedDate = resolveExternalMeetingDate(meeting)
    const source = resolvedDate ? resolvedDate.toISOString() : meeting.created_at
    if (!source) return "Date TBD"
    const date = resolvedDate ?? new Date(source)
    if (Number.isNaN(date.getTime())) return "Date TBD"
    const dateLabel = formatDateHuman(toISODate(date))
    const timeLabel = resolvedDate ? formatTime(date) : meeting.starts_at ? formatTime(date) : "TBD"
    return `${dateLabel} ${timeLabel}`
  }
  const mapMeetingToCommonItem = React.useCallback(
    (
      meeting: Meeting,
      meetingType: "external" | "internal",
      fallbackOwnerName?: string,
      linkedExternalMeeting?: Meeting | null,
      displayDate?: Date
    ): ExternalItem | InternalItem | null => {
      const resolvedDate = resolveExternalMeetingDate(meeting)
      const createdAt = new Date(meeting.created_at)
      const validCreatedAt = Number.isNaN(createdAt.getTime()) ? null : createdAt
      const dateSource = displayDate ?? resolvedDate ?? validCreatedAt
      if (!dateSource) return null
      return {
        id:
          meetingType === "external"
            ? `meeting:${meeting.id}:${toISODate(dateSource)}`
            : `meeting:${meeting.id}`,
        title: meeting.title || (meetingType === "external" ? "External meeting" : "Internal meeting"),
        date: toISODate(dateSource),
        time: resolvedDate ? formatTime(resolvedDate) : "TBD",
        platform: meeting.platform?.trim() || "TBD",
        owner: fallbackOwnerName || "Unknown",
        recurrenceType: meeting.recurrence_type || "none",
        calendarCategories: meeting.calendar_categories || [],
        calendarImported: Boolean(meeting.calendar_imported || meeting.microsoft_event_id),
        ...(meetingType === "internal"
          ? {
              pairedExternalMeetingId: meeting.paired_external_meeting_id || null,
              preExternalMeetingId: meeting.pre_external_meeting_id || null,
              linkedExternalCalendarCategories: linkedExternalMeeting?.calendar_categories || [],
              linkedExternalCalendarImported: Boolean(
                linkedExternalMeeting?.calendar_imported || linkedExternalMeeting?.microsoft_event_id
              ),
              linkedExternalRecurrenceType: linkedExternalMeeting?.recurrence_type || "none",
            }
          : {}),
      }
    },
    [formatTime, toISODate]
  )
  const alWeekdayShort = (d: Date) => {
    const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    return days[d.getDay()]
  }
  const getDayCode = (d: Date) => {
    const codes = ["H", "M", "MR", "E", "P", "S", "D"] // H=Monday, M=Tuesday, MR=Wednesday, E=Thursday, P=Friday
    return codes[d.getDay() === 0 ? 6 : d.getDay() - 1] || ""
  }

  // State
  const [users, setUsers] = React.useState<User[]>([])
  const [departments, setDepartments] = React.useState<Department[]>([])
  const [diamondItems, setDiamondItems] = React.useState<DiamondItem[]>([])
  const [commonReviewRow, setCommonReviewRow] = React.useState<TaskReviewOverviewRow | null>(null)
  const [commonReviewOpen, setCommonReviewOpen] = React.useState(false)
  const [commonData, setCommonData] = React.useState({
    late: [] as LateItem[],
    absent: [] as AbsentItem[],
    leave: [] as LeaveItem[],
    externalHoliday: [] as ExternalHolidayItem[],
    blocked: [] as BlockedItem[],
    oneH: [] as OneHItem[],
    personal: [] as PersonalItem[],
    external: [] as ExternalItem[],
    internal: [] as InternalItem[],
    r1: [] as R1Item[],
    problems: [] as ProblemItem[],
    feedback: [] as FeedbackItem[],
    priority: [] as PriorityItem[],
    bz: [] as BzItem[],
  })
  const [dataLoaded, setDataLoaded] = React.useState(false)
  const [commonViewMeta, setCommonViewMeta] = React.useState<{
    requested: string[]
    included: string[]
    missing: string[]
    guardrails: CommonViewGuardrails | null
  } | null>(null)

  const [weekStart, setWeekStart] = React.useState<Date>(() => getMonday(new Date()))
  const [selectedDates, setSelectedDates] = React.useState<Set<string>>(() => new Set([toISODate(new Date())]))
  const [multiMode, setMultiMode] = React.useState(false)
  const [typeFilters, setTypeFilters] = React.useState<Set<CommonType>>(new Set())
  const [typeMultiMode, setTypeMultiMode] = React.useState(false)
  const [colorFilter, setColorFilter] = React.useState<CommonColorFilter>("all")
  const [oneHMarkerFilters, setOneHMarkerFilters] = React.useState<Set<OneHMarkerFilter>>(new Set())
  const [oneHMarkerMenuOpen, setOneHMarkerMenuOpen] = React.useState(false)
  const [kaGentFilterActive, setKaGentFilterActive] = React.useState(false)
  const [taskFocusFilter, setTaskFocusFilter] = React.useState<CommonTaskFocusFilter>("all")
  const [newTaskCategoryFilters, setNewTaskCategoryFilters] = React.useState<Set<CommonTaskNewCategory>>(
    () => new Set(COMMON_TASK_NEW_CATEGORY_OPTIONS.map((option) => option.value))
  )
  const [freezeOneHSlots, setFreezeOneHSlots] = React.useState(() => {
    if (typeof window === "undefined") return false
    return window.localStorage.getItem(COMMON_VIEW_FREEZE_ONE_H_SLOTS_KEY) === "true"
  })
  const [selectedCommonUserId, setSelectedCommonUserId] = React.useState("__all__")
  const [commonUserMenuOpen, setCommonUserMenuOpen] = React.useState(false)
  const [printTotalPages, setPrintTotalPages] = React.useState<number>(1)
  const [printOrientationHint, setPrintOrientationHint] = React.useState<"portrait" | "landscape">("landscape")
  const [printingToday, setPrintingToday] = React.useState(false)
  const [printingTomorrow, setPrintingTomorrow] = React.useState(false)
  const weekTablePrintRef = React.useRef<HTMLDivElement | null>(null)
  const weekTablePrintContentRef = React.useRef<HTMLDivElement | null>(null)
  const singleDayPrintRef = React.useRef<HTMLDivElement | null>(null)
  const singleDayPrintContentRef = React.useRef<HTMLDivElement | null>(null)
  const commonUserFilterRef = React.useRef<HTMLDivElement | null>(null)
  const oneHMarkerFilterRef = React.useRef<HTMLDivElement | null>(null)
  const [exportingMeetingExcel, setExportingMeetingExcel] = React.useState(false)

  // Modal state
  const [modalOpen, setModalOpen] = React.useState(false)
  const [formType, setFormType] = React.useState<"late" | "absent" | "leave" | "externalHoliday" | "problem" | "feedback">("late")
  const [formPerson, setFormPerson] = React.useState("")
  const [formDate, setFormDate] = React.useState(toISODate(new Date()))
  const [formDateDisplay, setFormDateDisplay] = React.useState(toDDMMYYYY(toISODate(new Date())))
  const [formDelayStart, setFormDelayStart] = React.useState("08:00")
  const [formUntil, setFormUntil] = React.useState("09:00")
  const [formFrom, setFormFrom] = React.useState("08:00")
  const [formTo, setFormTo] = React.useState("12:00")
  const [formEndDate, setFormEndDate] = React.useState("")
  const [formEndDateDisplay, setFormEndDateDisplay] = React.useState("")
  const [formFullDay, setFormFullDay] = React.useState(false)
  const [formTitle, setFormTitle] = React.useState("")
  const [formNote, setFormNote] = React.useState("")
  const [formError, setFormError] = React.useState("")
  const [pendingPvTaskShift, setPendingPvTaskShift] = React.useState<PendingPvTaskShift | null>(null)
  const [loadingPvTaskShift, setLoadingPvTaskShift] = React.useState(false)
  const [openInfoId, setOpenInfoId] = React.useState<CommonType | null>(null)
  const [openSwimlaneNoteId, setOpenSwimlaneNoteId] = React.useState<string | null>(null)
  const [openSwimlaneTitleRows, setOpenSwimlaneTitleRows] = React.useState<Set<CommonType>>(
    () => new Set(DEFAULT_OPEN_SWIMLANE_TITLE_ROWS)
  )

  React.useEffect(() => {
    window.localStorage.setItem(COMMON_VIEW_FREEZE_ONE_H_SLOTS_KEY, freezeOneHSlots ? "true" : "false")
  }, [freezeOneHSlots])
  const infoPopoverRef = React.useRef<HTMLDivElement | null>(null)
  const [meetingPanelOpen, setMeetingPanelOpen] = React.useState(false)
  const [meetingAutoSelectEnabled, setMeetingAutoSelectEnabled] = React.useState(true)
  const [meetingTemplates, setMeetingTemplates] = React.useState<MeetingTemplate[]>([])
  const [activeMeetingId, setActiveMeetingId] = React.useState("")
  const [deletingMeetingTemplate, setDeletingMeetingTemplate] = React.useState(false)
  const [meetingTemplateGroup, setMeetingTemplateGroup] = React.useState<"board" | "staff">("board")
  const [meetingTemplateTitle, setMeetingTemplateTitle] = React.useState("")
  const [meetingTemplateTopicHeader, setMeetingTemplateTopicHeader] = React.useState("M1 PIKAT")
  const [meetingTemplateNote, setMeetingTemplateNote] = React.useState("")
  const [meetingTemplateDefaultOwner, setMeetingTemplateDefaultOwner] = React.useState("")
  const [meetingTemplateDefaultTime, setMeetingTemplateDefaultTime] = React.useState("")
  const [meetingTemplateTopicLabel, setMeetingTemplateTopicLabel] = React.useState("")
  const [creatingMeetingTemplate, setCreatingMeetingTemplate] = React.useState(false)
  const [meetingTemplateError, setMeetingTemplateError] = React.useState("")
  const [showMeetingTemplateForm, setShowMeetingTemplateForm] = React.useState(false)
  const [externalMeetingsOpen, setExternalMeetingsOpen] = React.useState(false)
  const [externalMeetings, setExternalMeetings] = React.useState<Meeting[]>([])
  const [syncingExternalCalendar, setSyncingExternalCalendar] = React.useState(false)
  const reloadMeetingListsRef = React.useRef<() => Promise<void>>(async () => undefined)
  const [externalMeetingListFilter, setExternalMeetingListFilter] = React.useState<"next" | "past" | "all">("next")
  const [externalMeetingTitle, setExternalMeetingTitle] = React.useState("")
  const [externalMeetingPlatform, setExternalMeetingPlatform] = React.useState("")
  const [externalMeetingStartsAt, setExternalMeetingStartsAt] = React.useState("")
  const [externalMeetingStartTime, setExternalMeetingStartTime] = React.useState("")
  const [externalMeetingInternalStartsAt, setExternalMeetingInternalStartsAt] = React.useState("")
  const [externalMeetingInternalStartTime, setExternalMeetingInternalStartTime] = React.useState("")
  const [externalMeetingCreateInternal, setExternalMeetingCreateInternal] = React.useState(true)
  const [externalMeetingParticipantIds, setExternalMeetingParticipantIds] = React.useState<string[]>([])
  const [externalMeetingPersonsOpen, setExternalMeetingPersonsOpen] = React.useState(false)
  const [externalMeetingPersonSearch, setExternalMeetingPersonSearch] = React.useState("")
  const externalMeetingPersonsRef = React.useRef<HTMLDivElement | null>(null)
  const externalMeetingInternalStartsAtEditedRef = React.useRef(false)
  const externalMeetingInternalStartTimeEditedRef = React.useRef(false)
  const [externalMeetingRecurrenceType, setExternalMeetingRecurrenceType] = React.useState<"none" | "weekly" | "monthly" | "yearly">("none")
  const [externalMeetingRecurrenceDaysOfWeek, setExternalMeetingRecurrenceDaysOfWeek] = React.useState<number[]>([])
  const [externalMeetingRecurrenceDaysOfMonth, setExternalMeetingRecurrenceDaysOfMonth] = React.useState<number[]>([])
  const [externalMeetingRecurrenceMonth, setExternalMeetingRecurrenceMonth] = React.useState("1")
  const [externalMeetingRecurrenceDay, setExternalMeetingRecurrenceDay] = React.useState("1")
  const [externalMeetingDepartmentId, setExternalMeetingDepartmentId] = React.useState("")
  const [internalMeetingsOpen, setInternalMeetingsOpen] = React.useState(false)
  const [internalMeetings, setInternalMeetings] = React.useState<Meeting[]>([])
  const [internalMeetingListFilter, setInternalMeetingListFilter] = React.useState<"next" | "past" | "all">("next")
  const [internalMeetingTitle, setInternalMeetingTitle] = React.useState("")
  const [internalMeetingPlatform, setInternalMeetingPlatform] = React.useState("")
  const [internalMeetingStartsAt, setInternalMeetingStartsAt] = React.useState("")
  const [internalMeetingStartTime, setInternalMeetingStartTime] = React.useState("")
  const [internalMeetingRecurrenceType, setInternalMeetingRecurrenceType] = React.useState<"none" | "weekly" | "monthly" | "yearly">("none")
  const [internalMeetingRecurrenceDaysOfWeek, setInternalMeetingRecurrenceDaysOfWeek] = React.useState<number[]>([])
  const [internalMeetingRecurrenceDaysOfMonth, setInternalMeetingRecurrenceDaysOfMonth] = React.useState<number[]>([])
  const [internalMeetingRecurrenceMonth, setInternalMeetingRecurrenceMonth] = React.useState("1")
  const [internalMeetingRecurrenceDay, setInternalMeetingRecurrenceDay] = React.useState("1")
  const [internalMeetingDepartmentId, setInternalMeetingDepartmentId] = React.useState("")
  const [internalMeetingParticipantIds, setInternalMeetingParticipantIds] = React.useState<string[]>([])
  const [internalMeetingPairExternalId, setInternalMeetingPairExternalId] = React.useState<string | null>(null)
  const [internalMeetingPairExternalTitle, setInternalMeetingPairExternalTitle] = React.useState("")
  const [internalMeetingPersonsOpen, setInternalMeetingPersonsOpen] = React.useState(false)
  const [internalMeetingPersonSearch, setInternalMeetingPersonSearch] = React.useState("")
  const [internalMeetingAvailability, setInternalMeetingAvailability] = React.useState<MeetingAvailability | null>(null)
  const [checkingInternalMeetingAvailability, setCheckingInternalMeetingAvailability] = React.useState(false)
  const internalMeetingPersonsRef = React.useRef<HTMLDivElement | null>(null)
  const [meetingOccurrenceStatuses, setMeetingOccurrenceStatuses] = React.useState<Map<string, MeetingOccurrenceStatus>>(new Map())
  const [savingMeetingStatusKey, setSavingMeetingStatusKey] = React.useState<string | null>(null)
  const syncCommonMeetingBucket = React.useCallback(
    (
      meetingType: "external" | "internal",
      meetings: Meeting[],
      linkedExternalMeetings: Meeting[] = externalMeetings
    ) => {
      const meetingItems = meetings
        .flatMap((meeting) => {
          const owner = meeting.created_by ? users.find((u) => u.id === meeting.created_by) : null
          const ownerName = owner?.full_name || owner?.username || "Unknown"
          const linkedExternalMeeting =
            meetingType === "internal" &&
            (meeting.paired_external_meeting_id || meeting.pre_external_meeting_id)
              ? linkedExternalMeetings.find(
                  (candidate) =>
                    candidate.id ===
                    (meeting.paired_external_meeting_id || meeting.pre_external_meeting_id)
                ) || null
              : null
          const assignees = (meeting.participant_ids || [])
            .map((participantId) => users.find((candidate) => candidate.id === participantId))
            .map((participant) => participant?.full_name || participant?.username || participant?.email || "")
            .filter(Boolean)
          const resolvedDisplayDates =
            meetingType === "external"
              ? expandExternalMeetingDates(meeting, resolveExternalMeetingDate(meeting))
              : [undefined]
          const displayDates: Array<Date | undefined> = resolvedDisplayDates.length
            ? resolvedDisplayDates
            : [undefined]
          return displayDates.map((displayDate) => {
            const item = mapMeetingToCommonItem(
              meeting,
              meetingType,
              ownerName,
              linkedExternalMeeting,
              displayDate
            )
            return item ? { ...item, assignees } : null
          })
        })
        .filter((item) => item !== null)

      setCommonData((prev) => ({
        ...prev,
        [meetingType]: meetingItems,
      }))
    },
    [externalMeetings, mapMeetingToCommonItem, users]
  )
  const commonViewAggregateEnabled = COMMON_VIEW_AGGREGATE_ENABLED
  const commonViewIncludeStages = React.useMemo(
    () => [
      ["users", "departments", "entries"],
      ["meetings", "system_tasks", "tasks"],
    ],
    []
  )
  const includeToBuckets: Record<string, CommonBucket[]> = React.useMemo(
    () => ({
      entries: ["late", "absent", "leave", "externalHoliday", "problems", "feedback"],
      meetings: ["external", "internal"],
      system_tasks: ["bz"],
      tasks: ["blocked", "oneH", "personal", "r1", "priority"],
    }),
    []
  )
  const [showWeekendDays, setShowWeekendDays] = React.useState(false)
  const departmentsById = React.useMemo(() => {
    return new Map(departments.map((d) => [d.id, d]))
  }, [departments])
  const getDepartmentMeta = React.useCallback(
    (departmentId?: string) => {
      const dept = departmentId ? departmentsById.get(departmentId) : undefined
      const name = (dept?.name || "").trim()
      const code = (dept?.code || "").trim().toUpperCase()
      const lower = name.toLowerCase()
      let rank = 3
      if (lower.includes("development")) rank = 0
      else if (lower.includes("graphic design")) rank = 1
      else if (code === "PCM" || lower.includes("project content") || lower.includes("content manager")) rank = 2
      const sortName = name || "ZZZ"
      return { rank, name: sortName }
    },
    [departmentsById]
  )
  const getPersonSortKey = React.useCallback(
    (item: { person?: string; owner?: string; assignees?: string[] }) => {
      const primary = (item.person || item.owner || "").trim()
      if (primary) return primary.toLowerCase()
      const assignees = (item.assignees || [])
        .map((name) => (name || "").trim())
        .filter(Boolean)
        .sort((a, b) => a.localeCompare(b))
      const combined = assignees.join(", ")
      return (combined || "Unknown").trim().toLowerCase()
    },
    []
  )
  const getWeeklyPlannerPersonSortKey = React.useCallback(
    (item: { person?: string; owner?: string; assignees?: string[]; userId?: string }) => {
      const user = item.userId ? users.find((entry) => entry.id === item.userId) : undefined
      const name = getFastTaskAssigneeKey(item as FastTaskEntry) || getPersonSortKey(item)
      if (!user || user.weekly_planner_sort_order == null) return [1, 0, name] as const
      return [0, user.weekly_planner_sort_order, name] as const
    },
    [getPersonSortKey, users]
  )
  const compareTaskOrder = React.useCallback(
    (
      a: {
        status?: string
        isDone?: boolean
        departmentId?: string
        title?: string
        person?: string
        owner?: string
        assignees?: string[]
        userId?: string
        fastTaskOrder?: number | null
        isDeadlineImportant?: boolean
        dueDate?: string | null
        oneHReportSlot?: string | null
        isSystemTask?: boolean
      },
      b: {
        status?: string
        isDone?: boolean
        departmentId?: string
        title?: string
        person?: string
        owner?: string
        assignees?: string[]
        userId?: string
        fastTaskOrder?: number | null
        isDeadlineImportant?: boolean
        dueDate?: string | null
        oneHReportSlot?: string | null
        isSystemTask?: boolean
      }
    ) => {
      const isDoneA = Boolean(a.isDone)
      const isDoneB = Boolean(b.isDone)
      if (isDoneA !== isDoneB) return isDoneA ? 1 : -1
      const metaA = getDepartmentMeta(a.departmentId)
      const metaB = getDepartmentMeta(b.departmentId)
      if (metaA.rank !== metaB.rank) return metaA.rank - metaB.rank
      if (metaA.rank === 3) {
        const nameCmp = metaA.name.localeCompare(metaB.name)
        if (nameCmp) return nameCmp
      }
      const personA = getWeeklyPlannerPersonSortKey(a)
      const personB = getWeeklyPlannerPersonSortKey(b)
      if (personA[0] !== personB[0]) return personA[0] - personB[0]
      if (personA[1] !== personB[1]) return personA[1] - personB[1]
      if (personA[2] !== personB[2]) return personA[2].localeCompare(personB[2])
      const slotRankA = oneHReportSlotRank(a.oneHReportSlot)
      const slotRankB = oneHReportSlotRank(b.oneHReportSlot)
      if (slotRankA !== slotRankB) return slotRankA - slotRankB
      const importantA = Boolean(a.isDeadlineImportant)
      const importantB = Boolean(b.isDeadlineImportant)
      if (importantA !== importantB) return importantA ? -1 : 1
      const eightAmA = hasEightAmIndicator(a.title, a.isSystemTask)
      const eightAmB = hasEightAmIndicator(b.title, b.isSystemTask)
      if (eightAmA !== eightAmB) return eightAmA ? -1 : 1
      const orderA = a.fastTaskOrder ?? Number.MAX_SAFE_INTEGER
      const orderB = b.fastTaskOrder ?? Number.MAX_SAFE_INTEGER
      if (orderA !== orderB) return orderA - orderB
      const statusRankA = commonTaskSortRank(a.status, a.isDone)
      const statusRankB = commonTaskSortRank(b.status, b.isDone)
      if (statusRankA !== statusRankB) return statusRankA - statusRankB
      return (a.title || "").localeCompare(b.title || "")
    },
    [getDepartmentMeta, getWeeklyPlannerPersonSortKey]
  )
  const sortTasksByOrder = React.useCallback(
    <T extends {
      date: string
      status?: string
      isDone?: boolean
      departmentId?: string
      title?: string
      person?: string
      owner?: string
      assignees?: string[]
      userId?: string
      fastTaskOrder?: number | null
      isDeadlineImportant?: boolean
      dueDate?: string | null
      oneHReportSlot?: string | null
      isSystemTask?: boolean
    }>(
      items: T[],
      multiDate: boolean
    ) => {
      const sorted = [...items]
      sorted.sort((a, b) => {
        if (multiDate) {
          const dateCmp = a.date.localeCompare(b.date)
          if (dateCmp) return dateCmp
        }
        return compareTaskOrder(a, b)
      })
      return sorted
    },
    [compareTaskOrder]
  )
  const compareReportPrintOrder = React.useCallback(
    (
      a: {
        departmentId?: string
        person?: string
        owner?: string
        assignees?: string[]
        userId?: string
        title?: string
        fastTaskOrder?: number | null
        isDeadlineImportant?: boolean
        createdAt?: string | null
        isSystemTask?: boolean
      },
      b: {
        departmentId?: string
        person?: string
        owner?: string
        assignees?: string[]
        userId?: string
        title?: string
        fastTaskOrder?: number | null
        isDeadlineImportant?: boolean
        createdAt?: string | null
        isSystemTask?: boolean
      }
    ) => {
      // Keep print-only task ordering aligned with M1/M2/M3's
      // common_view_task_sort_key: Weekly Planner department/person order,
      // then deadline, 08:00, owner, manual order, title, and creation date.
      const metaA = getDepartmentMeta(a.departmentId)
      const metaB = getDepartmentMeta(b.departmentId)
      if (metaA.rank !== metaB.rank) return metaA.rank - metaB.rank
      if (metaA.rank === 3) {
        const nameCmp = metaA.name.localeCompare(metaB.name)
        if (nameCmp) return nameCmp
      }
      const personA = getWeeklyPlannerPersonSortKey(a)
      const personB = getWeeklyPlannerPersonSortKey(b)
      if (personA[0] !== personB[0]) return personA[0] - personB[0]
      if (personA[1] !== personB[1]) return personA[1] - personB[1]
      if (personA[2] !== personB[2]) return personA[2].localeCompare(personB[2])
      if (Boolean(a.isDeadlineImportant) !== Boolean(b.isDeadlineImportant)) {
        return a.isDeadlineImportant ? -1 : 1
      }
      if (hasEightAmIndicator(a.title, a.isSystemTask) !== hasEightAmIndicator(b.title, b.isSystemTask)) {
        return hasEightAmIndicator(a.title, a.isSystemTask) ? -1 : 1
      }
      const ownerA = getPersonSortKey(a)
      const ownerB = getPersonSortKey(b)
      const ownerCmp = ownerA.localeCompare(ownerB)
      if (ownerCmp) return ownerCmp
      const orderA = a.fastTaskOrder ?? Number.MAX_SAFE_INTEGER
      const orderB = b.fastTaskOrder ?? Number.MAX_SAFE_INTEGER
      if (orderA !== orderB) return orderA - orderB
      const titleCmp = (a.title || "").localeCompare(b.title || "")
      if (titleCmp) return titleCmp
      return String(a.createdAt || "").localeCompare(String(b.createdAt || ""))
    },
    [getDepartmentMeta, getPersonSortKey, getWeeklyPlannerPersonSortKey]
  )
  const sortTasksForReportPrint = React.useCallback(
    <T extends {
      departmentId?: string
      person?: string
      owner?: string
      assignees?: string[]
      userId?: string
      title?: string
      fastTaskOrder?: number | null
      isDeadlineImportant?: boolean
      createdAt?: string | null
      isSystemTask?: boolean
    }>(items: T[]) => [...items].sort(compareReportPrintOrder),
    [compareReportPrintOrder]
  )
  const [creatingExternalMeeting, setCreatingExternalMeeting] = React.useState(false)
  const [editingExternalMeetingId, setEditingExternalMeetingId] = React.useState<string | null>(null)
  const [editingExternalMeetingTitle, setEditingExternalMeetingTitle] = React.useState("")
  const [editingExternalMeetingPlatform, setEditingExternalMeetingPlatform] = React.useState("")
  const [editingExternalMeetingStartsAt, setEditingExternalMeetingStartsAt] = React.useState("")
  const [editingExternalMeetingStartTime, setEditingExternalMeetingStartTime] = React.useState("")
  const [editingExternalMeetingRecurrenceType, setEditingExternalMeetingRecurrenceType] = React.useState<"none" | "weekly" | "monthly" | "yearly">("none")
  const [editingExternalMeetingRecurrenceDaysOfWeek, setEditingExternalMeetingRecurrenceDaysOfWeek] = React.useState<number[]>([])
  const [editingExternalMeetingRecurrenceDaysOfMonth, setEditingExternalMeetingRecurrenceDaysOfMonth] = React.useState<number[]>([])
  const [editingExternalMeetingRecurrenceMonth, setEditingExternalMeetingRecurrenceMonth] = React.useState("1")
  const [editingExternalMeetingRecurrenceDay, setEditingExternalMeetingRecurrenceDay] = React.useState("1")
  const [editingExternalMeetingDepartmentId, setEditingExternalMeetingDepartmentId] = React.useState("")
  const [editingExternalMeetingParticipantIds, setEditingExternalMeetingParticipantIds] = React.useState<string[]>([])
  const [editingExternalMeetingPersonsOpen, setEditingExternalMeetingPersonsOpen] = React.useState(false)
  const [editingExternalMeetingPersonSearch, setEditingExternalMeetingPersonSearch] = React.useState("")
  const [meetingDetailsId, setMeetingDetailsId] = React.useState<string | null>(null)
  const [savingMeetingDetails, setSavingMeetingDetails] = React.useState(false)
  const handledMeetingDeepLinkRef = React.useRef(false)
  const editingExternalMeetingPersonsRef = React.useRef<HTMLDivElement | null>(null)
  const [showEditWeekendDays, setShowEditWeekendDays] = React.useState(false)
  const [updatingExternalMeeting, setUpdatingExternalMeeting] = React.useState(false)
  const [deletingExternalMeetingId, setDeletingExternalMeetingId] = React.useState<string | null>(null)
  const [creatingAgentTestTaskMeetingId, setCreatingAgentTestTaskMeetingId] = React.useState<string | null>(null)
  const [creatingPimImageTestTaskMeetingId, setCreatingPimImageTestTaskMeetingId] = React.useState<string | null>(null)
  const [externalMeetingCreateAgentTestTask, setExternalMeetingCreateAgentTestTask] = React.useState(false)
  const [externalMeetingCreatePimImageTestTask, setExternalMeetingCreatePimImageTestTask] = React.useState(false)
  const [showInternalWeekendDays, setShowInternalWeekendDays] = React.useState(false)
  const [creatingInternalMeeting, setCreatingInternalMeeting] = React.useState(false)
  const [editingInternalMeetingId, setEditingInternalMeetingId] = React.useState<string | null>(null)
  const [editingInternalMeetingTitle, setEditingInternalMeetingTitle] = React.useState("")
  const [editingInternalMeetingPlatform, setEditingInternalMeetingPlatform] = React.useState("")
  const [editingInternalMeetingStartsAt, setEditingInternalMeetingStartsAt] = React.useState("")
  const [editingInternalMeetingStartTime, setEditingInternalMeetingStartTime] = React.useState("")
  const [editingInternalMeetingRecurrenceType, setEditingInternalMeetingRecurrenceType] = React.useState<"none" | "weekly" | "monthly" | "yearly">("none")
  const [editingInternalMeetingRecurrenceDaysOfWeek, setEditingInternalMeetingRecurrenceDaysOfWeek] = React.useState<number[]>([])
  const [editingInternalMeetingRecurrenceDaysOfMonth, setEditingInternalMeetingRecurrenceDaysOfMonth] = React.useState<number[]>([])
  const [editingInternalMeetingRecurrenceMonth, setEditingInternalMeetingRecurrenceMonth] = React.useState("1")
  const [editingInternalMeetingRecurrenceDay, setEditingInternalMeetingRecurrenceDay] = React.useState("1")
  const [editingInternalMeetingDepartmentId, setEditingInternalMeetingDepartmentId] = React.useState("")
  const [showInternalEditWeekendDays, setShowInternalEditWeekendDays] = React.useState(false)
  const [updatingInternalMeeting, setUpdatingInternalMeeting] = React.useState(false)
  const [deletingInternalMeetingId, setDeletingInternalMeetingId] = React.useState<string | null>(null)
  const [externalMeetingChecklist, setExternalMeetingChecklist] = React.useState<MeetingChecklist | null>(null)
  const [externalMeetingChecklistItems, setExternalMeetingChecklistItems] = React.useState<
    Map<string, boolean>
  >(new Map())
  const [externalMeetingChecklistOpen, setExternalMeetingChecklistOpen] = React.useState(false)
  const [externalMeetingChecklistLoading, setExternalMeetingChecklistLoading] = React.useState(false)
  const [externalChecklistEditingId, setExternalChecklistEditingId] = React.useState<string | null>(null)
  const [externalChecklistEditTitle, setExternalChecklistEditTitle] = React.useState("")
  const [externalChecklistEditPrefix, setExternalChecklistEditPrefix] = React.useState<string>("")
  const [externalChecklistSavingId, setExternalChecklistSavingId] = React.useState<string | null>(null)
  const [externalChecklistDeletingId, setExternalChecklistDeletingId] = React.useState<string | null>(null)
  const [externalChecklistAddTitle, setExternalChecklistAddTitle] = React.useState("")
  const [externalChecklistAddOrder, setExternalChecklistAddOrder] = React.useState("")
  const [externalChecklistAdding, setExternalChecklistAdding] = React.useState(false)
  const [externalChecklistImageError, setExternalChecklistImageError] = React.useState(false)
  const [editingRowId, setEditingRowId] = React.useState<string | null>(null)
  const [editDraft, setEditDraft] = React.useState({
    nr: "",
    day: "",
    topic: "",
    owner: "",
    time: "",
  })
  const [addDraft, setAddDraft] = React.useState({
    nr: "",
    day: "",
    topic: "",
    owner: "",
    time: "",
  })
  const [isSavingEntry, setIsSavingEntry] = React.useState(false)
  const [editingMeetingTitle, setEditingMeetingTitle] = React.useState(false)
  const [meetingTitleDraft, setMeetingTitleDraft] = React.useState("")
  const [savingMeetingTitle, setSavingMeetingTitle] = React.useState(false)
  const [editingMeetingTopicHeader, setEditingMeetingTopicHeader] = React.useState(false)
  const [meetingTopicHeaderDraft, setMeetingTopicHeaderDraft] = React.useState("")
  const [savingMeetingTopicHeader, setSavingMeetingTopicHeader] = React.useState(false)
  const skipMeetingTopicHeaderBlurRef = React.useRef(false)
  const [exportingExcel, setExportingExcel] = React.useState(false)
  const [exportingAllMeetingTemplatesExcel, setExportingAllMeetingTemplatesExcel] = React.useState(false)

  // Derived
  const weekISOs = React.useMemo(() => getWeekdays(weekStart).map(toISODate), [weekStart])
  const loadDiamonds = React.useCallback(async (options: { active?: () => boolean } = {}) => {
      if (authLoading || !userId || !weekISOs.length) return
      const params = new URLSearchParams({
        date_from: weekISOs[0],
        date_to: weekISOs[weekISOs.length - 1],
        review_status: "reviewed",
      })

      try {
        const res = await apiFetch(`/task-reviews/overview?${params.toString()}`)
        if (!res?.ok) {
          if (options.active?.() ?? true) setDiamondItems([])
          return
        }
        const payload = (await res.json()) as TaskReviewOverview
        const items = payload.rows.flatMap((row): DiamondItem[] => {
          if (!row.review) return []
          const completedAt = new Date(row.completed_at)
          if (Number.isNaN(completedAt.getTime())) return []
          return [{
            reviewId: row.review.id,
            taskId: row.task_id,
            userId: row.reviewee_user_id,
            person: row.reviewee_name,
            taskTitle: row.source === "REALIZATION_PROPOSAL"
              ? `${row.task_title} — ${row.review.comment || ""}`
              : getPlainMarkedText(row.task_title).trim() || "Untitled task",
            date: [
              completedAt.getFullYear(),
              String(completedAt.getMonth() + 1).padStart(2, "0"),
              String(completedAt.getDate()).padStart(2, "0"),
            ].join("-"),
            review: row.review,
          }]
        })
        if (options.active?.() ?? true) setDiamondItems(items)
      } catch {
        if (options.active?.() ?? true) setDiamondItems([])
      }
    }, [apiFetch, authLoading, userId, weekISOs])

  React.useEffect(() => {
    let active = true

    void loadDiamonds({ active: () => active })
    return () => {
      active = false
    }
  }, [loadDiamonds])
  const allDaysSelected = React.useMemo(() => {
    if (selectedDates.size !== weekISOs.length) return false
    return weekISOs.every((iso) => selectedDates.has(iso))
  }, [selectedDates, weekISOs])
  const calendarDateIso = selectedDates.size === 1 ? Array.from(selectedDates)[0] : toISODate(weekStart)
  const activeMeeting = React.useMemo(
    () => meetingTemplates.find((template) => template.id === activeMeetingId) || null,
    [activeMeetingId, meetingTemplates]
  )
  const boardMeetingIds = React.useMemo(
    () => meetingTemplates.filter((m) => m.groupKey === "board").map((m) => m.id),
    [meetingTemplates]
  )
  const staffMeetingIds = React.useMemo(
    () => meetingTemplates.filter((m) => m.groupKey === "staff").map((m) => m.id),
    [meetingTemplates]
  )
  const mergeOwnerColumn = React.useMemo(() => {
    if (!activeMeeting) return false
    const hasOwner = Boolean(activeMeeting.defaultOwner) || activeMeeting.rows.some((row) => row.owner)
    if (!hasOwner) return false
    return activeMeeting.rows.every((row, idx) => !row.owner || idx === 0)
  }, [activeMeeting])

  const startEditMeetingTitle = React.useCallback(() => {
    if (!activeMeeting) return
    setMeetingTitleDraft(activeMeeting.title || "")
    setEditingMeetingTitle(true)
  }, [activeMeeting])

  const cancelEditMeetingTitle = React.useCallback(() => {
    setEditingMeetingTitle(false)
    setMeetingTitleDraft("")
  }, [])

  const saveMeetingTitle = React.useCallback(async () => {
    if (!activeMeeting || !meetingTitleDraft.trim()) return
    setSavingMeetingTitle(true)
    try {
      const res = await apiFetch(`/checklists/${activeMeeting.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: meetingTitleDraft.trim() }),
      })
      if (!res.ok) {
        let detail = "Failed to update meeting title"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // If response is not JSON, try to get status text
          if (res.status === 404) {
            detail = "Meeting template not found. Please refresh the page."
          } else if (res.status === 403) {
            detail = "Only admins and managers can update meeting templates."
          } else {
            detail = `Failed to update meeting title (${res.status})`
          }
        }
        toast.error(detail)
        return
      }
      const updated = (await res.json()) as { id: string; title: string; [key: string]: unknown }
      setMeetingTemplates((prev) =>
        prev.map((meeting) => (meeting.id === activeMeeting.id ? { ...meeting, title: updated.title } : meeting))
      )
      setEditingMeetingTitle(false)
      setMeetingTitleDraft("")
    } catch (err) {
      console.error("Error updating meeting title:", err)
      toast.error("Failed to update meeting title. Please try again.")
    } finally {
      setSavingMeetingTitle(false)
    }
  }, [activeMeeting, meetingTitleDraft, apiFetch])

  const startEditMeetingTopicHeader = React.useCallback(() => {
    if (!activeMeeting) return
    const topicColumn = activeMeeting.columns.find((col) => col.key === "topic")
    setMeetingTopicHeaderDraft(topicColumn?.label || "M1 PIKAT")
    setEditingMeetingTopicHeader(true)
  }, [activeMeeting])

  const cancelEditMeetingTopicHeader = React.useCallback(() => {
    skipMeetingTopicHeaderBlurRef.current = true
    setEditingMeetingTopicHeader(false)
    setMeetingTopicHeaderDraft("")
  }, [])

  const saveMeetingTopicHeader = React.useCallback(async () => {
    if (!activeMeeting || !meetingTopicHeaderDraft.trim()) return
    const nextColumns = activeMeeting.columns.map((col) =>
      col.key === "topic" ? { ...col, label: meetingTopicHeaderDraft.trim() } : col
    )
    setSavingMeetingTopicHeader(true)
    try {
      const res = await apiFetch(`/checklists/${activeMeeting.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ columns: nextColumns }),
      })
      if (!res.ok) {
        let detail = "Failed to update meeting column."
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          detail = `Failed to update meeting column (${res.status}).`
        }
        toast.error(detail)
        return
      }
      const updated = (await res.json()) as { id: string; columns?: MeetingColumn[] | null }
      setMeetingTemplates((prev) =>
        prev.map((meeting) =>
          meeting.id === activeMeeting.id
            ? { ...meeting, columns: updated.columns?.length ? updated.columns : nextColumns }
            : meeting
        )
      )
      setEditingMeetingTopicHeader(false)
      setMeetingTopicHeaderDraft("")
    } catch (err) {
      console.error("Error updating meeting column:", err)
      toast.error("Failed to update meeting column. Please try again.")
    } finally {
      setSavingMeetingTopicHeader(false)
    }
  }, [activeMeeting, meetingTopicHeaderDraft, apiFetch])

  const canSelectExternalDepartment = user?.role !== "STAFF"
  const externalMeetingDepartment = React.useMemo(
    () => departments.find((d) => d.id === externalMeetingDepartmentId) || null,
    [departments, externalMeetingDepartmentId]
  )
  const internalMeetingDepartment = React.useMemo(
    () => departments.find((d) => d.id === internalMeetingDepartmentId) || null,
    [departments, internalMeetingDepartmentId]
  )
  const externalMeetingsSorted = React.useMemo(() => {
    return [...externalMeetings].sort((a, b) => {
      const aResolved = resolveExternalMeetingDate(a)
      const bResolved = resolveExternalMeetingDate(b)
      const aFallback = a.starts_at || a.created_at
      const bFallback = b.starts_at || b.created_at
      const aDate = aResolved ?? (aFallback ? new Date(aFallback) : null)
      const bDate = bResolved ?? (bFallback ? new Date(bFallback) : null)
      const aValid = aDate && !Number.isNaN(aDate.getTime())
      const bValid = bDate && !Number.isNaN(bDate.getTime())
      if (!aValid && !bValid) return a.title.localeCompare(b.title)
      if (!aValid) return 1
      if (!bValid) return -1
      const diff = aDate!.getTime() - bDate!.getTime()
      if (diff !== 0) return diff
      return a.title.localeCompare(b.title)
    })
  }, [externalMeetings])
  const getExternalMeetingListDate = React.useCallback((meeting: Meeting) => {
    const resolved = resolveExternalMeetingDate(meeting)
    if (resolved) return resolved
    if (!meeting.starts_at) return null
    const startsAt = new Date(meeting.starts_at)
    return Number.isNaN(startsAt.getTime()) ? null : startsAt
  }, [])
  const externalMeetingsVisible = React.useMemo(() => {
    const activeMeetings = externalMeetingsSorted.filter(
      (meeting) => meeting.calendar_sync_status !== "cancelled"
    )
    if (selectedDates.size) {
      return activeMeetings.filter((meeting) => {
        const meetingDate = getExternalMeetingListDate(meeting)
        return meetingDate
          ? expandExternalMeetingDates(meeting, meetingDate).some((date) => selectedDates.has(toISODate(date)))
          : false
      })
    }
    if (externalMeetingListFilter === "all") return activeMeetings
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    return activeMeetings.filter((meeting) => {
      const meetingDate = getExternalMeetingListDate(meeting)
      if (!meetingDate) return false
      return externalMeetingListFilter === "past"
        ? meetingDate.getTime() < today.getTime()
        : meetingDate.getTime() >= today.getTime()
    })
  }, [externalMeetingListFilter, externalMeetingsSorted, getExternalMeetingListDate, selectedDates, toISODate])
  const internalMeetingsSorted = React.useMemo(() => {
    return [...internalMeetings].sort((a, b) => {
      const aResolved = resolveExternalMeetingDate(a)
      const bResolved = resolveExternalMeetingDate(b)
      const aFallback = a.starts_at || a.created_at
      const bFallback = b.starts_at || b.created_at
      const aDate = aResolved ?? (aFallback ? new Date(aFallback) : null)
      const bDate = bResolved ?? (bFallback ? new Date(bFallback) : null)
      const aValid = aDate && !Number.isNaN(aDate.getTime())
      const bValid = bDate && !Number.isNaN(bDate.getTime())
      if (!aValid && !bValid) return a.title.localeCompare(b.title)
      if (!aValid) return 1
      if (!bValid) return -1
      const diff = aDate!.getTime() - bDate!.getTime()
      if (diff !== 0) return diff
      return a.title.localeCompare(b.title)
    })
  }, [internalMeetings])
  const internalMeetingsVisible = React.useMemo(() => {
    if (internalMeetingListFilter === "all") return internalMeetingsSorted
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    return internalMeetingsSorted.filter((meeting) => {
      const meetingDate = getExternalMeetingListDate(meeting)
      if (!meetingDate) return false
      return internalMeetingListFilter === "past"
        ? meetingDate.getTime() < today.getTime()
        : meetingDate.getTime() >= today.getTime()
    })
  }, [getExternalMeetingListDate, internalMeetingListFilter, internalMeetingsSorted])

  const meetingStatusDate = React.useMemo(() => {
    if (selectedDates.size === 1) return Array.from(selectedDates)[0]!
    return toISODate(new Date())
  }, [selectedDates])

  const occurrenceStatusKey = React.useCallback((meetingId: string, occurrenceDate: string) => {
    return `${meetingId}|${occurrenceDate}`
  }, [])

  const loadMeetingOccurrenceStatuses = React.useCallback(async () => {
    try {
      const res = await apiFetch(`/meetings/occurrence-statuses?occurrence_date=${meetingStatusDate}`)
      if (!res.ok) {
        setMeetingOccurrenceStatuses(new Map())
        return
      }
      const rows = (await res.json()) as MeetingOccurrenceStatus[]
      setMeetingOccurrenceStatuses(new Map(rows.map((row) => [occurrenceStatusKey(row.meeting_id, row.occurrence_date), row])))
    } catch {
      setMeetingOccurrenceStatuses(new Map())
    }
  }, [apiFetch, meetingStatusDate, occurrenceStatusKey])

  React.useEffect(() => {
    void loadMeetingOccurrenceStatuses()
  }, [loadMeetingOccurrenceStatuses])

  const meetingOccurrenceDateIso = React.useCallback(
    (meeting: Meeting) => {
      const resolved = resolveExternalMeetingDate(meeting)
      return resolved ? toISODate(resolved) : meetingStatusDate
    },
    [meetingStatusDate, resolveExternalMeetingDate]
  )

  const getMeetingOccurrenceStatus = React.useCallback(
    (meeting: Meeting) => {
      const occurrenceDate = meetingOccurrenceDateIso(meeting)
      return meetingOccurrenceStatuses.get(occurrenceStatusKey(meeting.id, occurrenceDate))?.status || ""
    },
    [meetingOccurrenceDateIso, meetingOccurrenceStatuses, occurrenceStatusKey]
  )

  // Marking a TAK INT as held closes its auto 1H tasks on the server; reload tasks afterwards.
  const refreshCommonTasksRef = React.useRef<(() => Promise<void>) | null>(null)

  const updateMeetingOccurrenceStatus = React.useCallback(
    async (meeting: Meeting, status: "" | "held" | "canceled") => {
      const occurrenceDate = meetingOccurrenceDateIso(meeting)
      const key = occurrenceStatusKey(meeting.id, occurrenceDate)
      setSavingMeetingStatusKey(key)
      try {
        const res = await apiFetch(`/meetings/${meeting.id}/occurrence-status`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ occurrence_date: occurrenceDate, status }),
        })
        if (!res.ok) throw new Error(await res.text())
        const row = (await res.json()) as MeetingOccurrenceStatus
        setMeetingOccurrenceStatuses((prev) => new Map(prev).set(occurrenceStatusKey(row.meeting_id, row.occurrence_date), row))
        void refreshCommonTasksRef.current?.()
      } catch (error) {
        toast.error("Meeting status update failed", { description: String(error) })
      } finally {
        setSavingMeetingStatusKey(null)
      }
    },
    [apiFetch, meetingOccurrenceDateIso, occurrenceStatusKey]
  )

  const renderMeetingStatusControl = React.useCallback(
    (meeting: Meeting) => {
      const occurrenceDate = meetingOccurrenceDateIso(meeting)
      const key = occurrenceStatusKey(meeting.id, occurrenceDate)
      return (
        <select
          className="input"
          value={getMeetingOccurrenceStatus(meeting)}
          onChange={(event) => void updateMeetingOccurrenceStatus(meeting, event.target.value as "" | "held" | "canceled")}
          disabled={savingMeetingStatusKey === key}
          title={`Meeting status for ${occurrenceDate}`}
          style={{ width: "120px", minHeight: "32px", padding: "4px 8px", fontSize: "12px" }}
        >
          <option value=""></option>
          <option value="held">Mbajtur</option>
          <option value="canceled">Anuluar</option>
        </select>
      )
    },
    [getMeetingOccurrenceStatus, meetingOccurrenceDateIso, occurrenceStatusKey, savingMeetingStatusKey, updateMeetingOccurrenceStatus]
  )

  const renderSwimlaneMeetingStatusControl = React.useCallback(
    (cell: SwimlaneCell) => {
      if (!cell.meetingId || !cell.entryDate) return null
      const key = occurrenceStatusKey(cell.meetingId, cell.entryDate)
      const status = meetingOccurrenceStatuses.get(key)?.status || ""
      return (
        <select
          className="meeting-status-select"
          value={status}
          onChange={(event) => {
            event.stopPropagation()
            void updateMeetingOccurrenceStatus(
              {
                id: cell.meetingId!,
                title: cell.title,
                starts_at: cell.entryDate,
                meeting_type: null,
                department_id: "",
                created_at: "",
                updated_at: "",
              },
              event.target.value as "" | "held" | "canceled"
            )
          }}
          onClick={(event) => event.stopPropagation()}
          disabled={savingMeetingStatusKey === key}
          title={`Meeting status for ${cell.entryDate}`}
        >
          <option value=""></option>
          <option value="held">Mbajtur</option>
          <option value="canceled">Anuluar</option>
        </select>
      )
    },
    [meetingOccurrenceStatuses, occurrenceStatusKey, savingMeetingStatusKey, updateMeetingOccurrenceStatus]
  )
  const userById = React.useMemo(() => new Map(users.map((u) => [u.id, u])), [users])
  
  const reloadExternalChecklist = React.useCallback(async () => {
    setExternalMeetingChecklistLoading(true)
    try {
      const res = await apiFetch("/checklists?group_key=external&include_items=true")
      if (!res?.ok) return
      const data = (await res.json()) as MeetingChecklist[]
      const checklist = data.length > 0 ? data[0] : null
      setExternalMeetingChecklist(checklist)
      const itemsMap = new Map<string, boolean>()
      if (checklist?.items) {
        for (const item of checklist.items) {
          itemsMap.set(item.id, item.is_checked ?? false)
        }
      }
      setExternalMeetingChecklistItems(itemsMap)
    } catch (err) {
      console.error("Failed to load external meeting checklist", err)
    } finally {
      setExternalMeetingChecklistLoading(false)
    }
  }, [apiFetch])

  // Load external meeting checklist when panel opens
  React.useEffect(() => {
    if (!externalMeetingsOpen) return
    void reloadExternalChecklist()
  }, [externalMeetingsOpen, reloadExternalChecklist])

  const startEditExternalChecklistItem = React.useCallback(
    (itemId: string, currentTitle: string) => {
      const match = (currentTitle || "").match(/^(\d+(?:\.\d+)*)\.\s*(.*)$/)
      const prefix = match?.[1] || ""
      const titleOnly = (match?.[2] ?? currentTitle ?? "").trim()
      setExternalChecklistEditingId(itemId)
      setExternalChecklistEditPrefix(prefix)
      setExternalChecklistEditTitle(titleOnly)
    },
    []
  )

  const cancelEditExternalChecklistItem = React.useCallback(() => {
    setExternalChecklistEditingId(null)
    setExternalChecklistEditTitle("")
    setExternalChecklistEditPrefix("")
  }, [])

  const saveExternalChecklistItemTitle = React.useCallback(
    async (itemId: string) => {
      if (!isAdmin) return
      const nextTitle = externalChecklistEditTitle.trim()
      if (!nextTitle) return
      setExternalChecklistSavingId(itemId)
      try {
        const patchedTitle = externalChecklistEditPrefix ? `${externalChecklistEditPrefix}. ${nextTitle}` : nextTitle
        const res = await apiFetch(`/checklist-items/${itemId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: patchedTitle }),
        })
        if (!res?.ok) return
        await reloadExternalChecklist()
        setExternalChecklistEditingId(null)
        setExternalChecklistEditTitle("")
        setExternalChecklistEditPrefix("")
      } finally {
        setExternalChecklistSavingId(null)
      }
    },
    [apiFetch, externalChecklistEditPrefix, externalChecklistEditTitle, isAdmin, reloadExternalChecklist]
  )

  const deleteExternalChecklistItem = React.useCallback(
    async (itemId: string) => {
      if (!isAdmin) return
      const confirmed = await confirm({
        title: "Delete checklist item",
        description: "Delete this checklist item?",
        confirmLabel: "Delete",
        variant: "destructive",
      })
      if (!confirmed) return
      setExternalChecklistDeletingId(itemId)
      try {
        const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
        if (!res?.ok) return
        await reloadExternalChecklist()
      } finally {
        setExternalChecklistDeletingId(null)
      }
    },
    [apiFetch, confirm, isAdmin, reloadExternalChecklist]
  )

  const addExternalChecklistItem = React.useCallback(async () => {
    if (!isAdmin) return
    const checklistId = externalMeetingChecklist?.id
    const title = externalChecklistAddTitle.trim()
    if (!checklistId || !title) return
    setExternalChecklistAdding(true)
    try {
      const orderNum = Number(externalChecklistAddOrder)
      const hasOrder = externalChecklistAddOrder.trim() !== "" && Number.isFinite(orderNum) && orderNum > 0
      let position: number | undefined
      if (hasOrder && externalMeetingChecklist?.items?.length) {
        // Translate "Order #" (1-based, main items only) into DB integer position (which includes subpoints).
        const sorted = externalMeetingChecklist.items
          .slice()
          .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
        const isSubpoint = (t: string) => /^\d+\.\d+/.test((t || "").trim())
        const mainItems = sorted.filter((it) => !isSubpoint(it.title || ""))
        const insertIdx = Math.floor(orderNum) - 1
        if (insertIdx <= 0) {
          position = (mainItems[0]?.position ?? 0)
        } else if (insertIdx >= mainItems.length) {
          const maxPos = sorted.reduce((m, it) => Math.max(m, it.position ?? 0), 0)
          position = maxPos + 1
        } else {
          position = (mainItems[insertIdx]?.position ?? 0)
        }
      }
      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          checklist_id: checklistId,
          item_type: "CHECKBOX",
          position,
          title,
          is_checked: false,
        }),
      })
      if (!res?.ok) return
      setExternalChecklistAddTitle("")
      setExternalChecklistAddOrder("")
      await reloadExternalChecklist()
    } finally {
      setExternalChecklistAdding(false)
    }
  }, [
    apiFetch,
    externalChecklistAddOrder,
    externalChecklistAddTitle,
    externalMeetingChecklist?.id,
    externalMeetingChecklist?.items,
    isAdmin,
    reloadExternalChecklist,
  ])

  // Reset checklist when panel closes
  React.useEffect(() => {
    if (!externalMeetingsOpen) {
      setExternalMeetingChecklist(null)
      setExternalMeetingChecklistItems(new Map())
      setExternalMeetingChecklistOpen(false)
      setExternalMeetingChecklistLoading(false)
    }
  }, [externalMeetingsOpen])

  const hasExternalMeetingTimes = externalMeetingRecurrenceType === "none"
    ? Boolean(externalMeetingStartsAt)
      && (!externalMeetingCreateInternal || (Boolean(externalMeetingInternalStartsAt) && Boolean(externalMeetingInternalStartTime)))
    : Boolean(externalMeetingStartTime)
      && (!externalMeetingCreateInternal || Boolean(externalMeetingInternalStartTime))
  const canCreateExternalMeeting =
    Boolean(externalMeetingTitle.trim())
    && Boolean(externalMeetingDepartmentId)
    && externalMeetingParticipantIds.length > 0
    && hasExternalMeetingTimes
  const canSelectExternalMeetingAgentTestTask =
    externalMeetingRecurrenceType === "none" && Boolean(externalMeetingStartsAt)

  React.useEffect(() => {
    if (!canSelectExternalMeetingAgentTestTask) {
      setExternalMeetingCreateAgentTestTask(false)
      setExternalMeetingCreatePimImageTestTask(false)
    }
  }, [canSelectExternalMeetingAgentTestTask])
  const canCreateInternalMeeting =
    Boolean(internalMeetingTitle.trim())
    && Boolean(internalMeetingDepartmentId)
    && internalMeetingParticipantIds.length > 0
    && (
      internalMeetingRecurrenceType === "none"
        ? Boolean(internalMeetingStartsAt)
        : Boolean(internalMeetingStartTime)
    )
  const internalOneHConflicts = internalMeetingAvailability?.conflicts.filter((conflict) => conflict.source === "one_h") || []
  const applyInternalSuggestedSlot = () => {
    const suggested = internalMeetingAvailability?.suggested_slot
    if (!suggested) return
    if (internalMeetingRecurrenceType === "none") {
      setInternalMeetingStartsAt(toLocalDateTimeInput(suggested.starts_at))
    } else {
      setInternalMeetingStartTime(toLocalTimeInput(suggested.starts_at))
    }
    setInternalMeetingAvailability(null)
  }

  const reloadMeetingTemplates = React.useCallback(async () => {
    try {
      // Common view should only show the official meeting templates:
      // - group_key=board (BORD/GA)
      // - group_key=staff (STAFF/GA)
      const [boardRes, staffRes] = await Promise.all([
        apiFetch("/checklists?group_key=board&include_items=true"),
        apiFetch("/checklists?group_key=staff&include_items=true"),
      ])
      if (!boardRes?.ok && !staffRes?.ok) return [] as MeetingTemplate[]
      let boardData = boardRes?.ok ? ((await boardRes.json()) as MeetingChecklist[]) : []
      let staffData = staffRes?.ok ? ((await staffRes.json()) as MeetingChecklist[]) : []
      let data = [...boardData, ...staffData]

      const checklistIds = data.map((checklist) => checklist.id)
      if (checklistIds.length) {
        await Promise.allSettled(
          checklistIds.map((checklistId) =>
            apiFetch("/internal-meeting-sessions/ensure", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ checklist_id: checklistId }),
            })
          )
        )

        const [boardResRefresh, staffResRefresh] = await Promise.all([
          apiFetch("/checklists?group_key=board&include_items=true"),
          apiFetch("/checklists?group_key=staff&include_items=true"),
        ])
        if (boardResRefresh?.ok || staffResRefresh?.ok) {
          boardData = boardResRefresh?.ok
            ? ((await boardResRefresh.json()) as MeetingChecklist[])
            : boardData
          staffData = staffResRefresh?.ok
            ? ((await staffResRefresh.json()) as MeetingChecklist[])
            : staffData
          data = [...boardData, ...staffData]
        }
      }

      const templates = data
        .slice()
        .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
        .map((checklist) => {
          const rows = (checklist.items || [])
            .slice()
            .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
            .map((item, index) => ({
              id: item.id,
              nr: index + 1,
              day: item.day || undefined,
              topic: item.title || "",
              owner: item.owner || undefined,
              time: item.time || undefined,
              isChecked: item.is_checked ?? false,
              checkStatus: getMeetingCheckStatus(item.is_checked, item.comment),
              comment: item.comment || undefined,
            }))
          return {
            id: checklist.id,
            title: checklist.title,
            note: checklist.note || undefined,
            groupKey: checklist.group_key || undefined,
            columns: checklist.columns?.length ? checklist.columns : DEFAULT_MEETING_COLUMNS,
            rows,
            defaultOwner: checklist.default_owner || undefined,
            defaultTime: checklist.default_time || undefined,
            position: checklist.position ?? undefined,
          }
        })
      return templates
    } catch (err) {
      console.error("Failed to load meeting checklists", err)
      return [] as MeetingTemplate[]
    }
  }, [apiFetch])

  React.useEffect(() => {
    let mounted = true
    void reloadMeetingTemplates().then((templates) => {
      if (mounted) setMeetingTemplates(templates)
    })
    return () => {
      mounted = false
    }
  }, [reloadMeetingTemplates])

  const canCreateMeetingTemplate = canEditMeetingTemplates && Boolean(meetingTemplateTitle.trim())

  const createMeetingTemplate = React.useCallback(async () => {
    if (!canCreateMeetingTemplate) return
    setCreatingMeetingTemplate(true)
    setMeetingTemplateError("")
    try {
      const baseColumns = (activeMeeting?.columns?.length ? activeMeeting.columns : DEFAULT_MEETING_COLUMNS).map(
        (col) => ({
          ...col,
          label: col.key === "topic" ? meetingTemplateTopicHeader.trim() || "M1 PIKAT" : col.label,
        })
      )
      const topicLabel = meetingTemplateTopicLabel.trim()
      const columns = topicLabel
        ? baseColumns.map((col) => (col.key === "topic" ? { ...col, label: topicLabel } : col))
        : baseColumns
      const maxPosition = meetingTemplates.reduce(
        (max, template) => Math.max(max, template.position ?? -1),
        -1
      )
      const payload = {
        title: meetingTemplateTitle.trim(),
        note: meetingTemplateNote.trim() || null,
        default_owner: meetingTemplateDefaultOwner.trim() || null,
        default_time: meetingTemplateDefaultTime.trim() || null,
        group_key: meetingTemplateGroup,
        columns,
        position: maxPosition + 1,
      }
      const res = await apiFetch("/checklists", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        let detail = "Failed to create meeting checklist."
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          detail = `Failed to create meeting checklist (${res.status}).`
        }
        setMeetingTemplateError(detail)
        return
      }
      const created = (await res.json()) as { id: string }
      const templates = await reloadMeetingTemplates()
      setMeetingTemplates(templates)
      if (created?.id) setActiveMeetingId(created.id)
      setMeetingTemplateTitle("")
      setMeetingTemplateTopicHeader("M1 PIKAT")
      setMeetingTemplateNote("")
      setMeetingTemplateDefaultOwner("")
      setMeetingTemplateDefaultTime("")
      setMeetingTemplateTopicLabel("")
    } catch (err) {
      console.error("Failed to create meeting checklist", err)
      setMeetingTemplateError("Failed to create meeting checklist. Please try again.")
    } finally {
      setCreatingMeetingTemplate(false)
    }
  }, [
    activeMeeting,
    apiFetch,
    canCreateMeetingTemplate,
    meetingTemplateDefaultOwner,
    meetingTemplateDefaultTime,
    meetingTemplateTopicHeader,
    meetingTemplateGroup,
    meetingTemplateNote,
    meetingTemplateTopicLabel,
    meetingTemplateTitle,
    meetingTemplates,
    reloadMeetingTemplates,
  ])

  const deleteMeetingTemplate = React.useCallback(async () => {
    if (!activeMeeting) return
    const confirmed = await confirm({
      title: "Delete checklist",
      description: "Delete this checklist? This action cannot be undone.",
      confirmLabel: "Delete",
      variant: "destructive",
    })
    if (!confirmed) return
    setDeletingMeetingTemplate(true)
    try {
      const res = await apiFetch(`/checklists/${activeMeeting.id}`, { method: "DELETE" })
      if (!res.ok) {
        let detail = "Failed to delete meeting checklist."
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          if (res.status === 404) {
            detail = "Meeting checklist not found. Please refresh the page."
          } else if (res.status === 403) {
            detail = "Only admins and managers can delete meeting checklists."
          } else {
            detail = `Failed to delete meeting checklist (${res.status}).`
          }
        }
        toast.error(detail)
        return
      }

      const sameGroup = meetingTemplates.filter((meeting) => meeting.groupKey === activeMeeting.groupKey)
      const currentIndex = sameGroup.findIndex((meeting) => meeting.id === activeMeeting.id)
      const fallbackNext =
        sameGroup.length > 1 ? sameGroup[currentIndex + 1] || sameGroup[currentIndex - 1] : null
      const nextMeetingId = fallbackNext?.id || ""

      setMeetingTemplates((prev) => prev.filter((meeting) => meeting.id !== activeMeeting.id))
      if (nextMeetingId) {
        setActiveMeetingId(nextMeetingId)
        setMeetingAutoSelectEnabled(true)
      } else {
        setActiveMeetingId("")
        setMeetingAutoSelectEnabled(false)
      }
    } catch (err) {
      console.error("Failed to delete meeting checklist", err)
      toast.error("Failed to delete meeting checklist. Please try again.")
    } finally {
      setDeletingMeetingTemplate(false)
    }
  }, [activeMeeting, apiFetch, confirm, meetingTemplates])

  React.useEffect(() => {
    if (!meetingAutoSelectEnabled) return
    if (!meetingTemplates.length) return
    if (!activeMeetingId || !meetingTemplates.some((meeting) => meeting.id === activeMeetingId)) {
      setActiveMeetingId(meetingTemplates[0].id)
    }
  }, [activeMeetingId, meetingAutoSelectEnabled, meetingTemplates])

  React.useEffect(() => {
    setEditingRowId(null)
    setEditDraft({ nr: "", day: "", topic: "", owner: "", time: "" })
    setAddDraft({ nr: "", day: "", topic: "", owner: "", time: "" })
    setEditingMeetingTopicHeader(false)
    setMeetingTopicHeaderDraft("")
  }, [activeMeetingId])

  React.useEffect(() => {
    if (externalMeetingDepartmentId) return
    if (user?.department_id) {
      setExternalMeetingDepartmentId(user.department_id)
      return
    }
    if (departments.length) {
      setExternalMeetingDepartmentId(departments[0].id)
    }
  }, [departments, externalMeetingDepartmentId, user?.department_id])
  React.useEffect(() => {
    if (internalMeetingDepartmentId) return
    if (user?.department_id) {
      setInternalMeetingDepartmentId(user.department_id)
      return
    }
    if (departments.length) {
      setInternalMeetingDepartmentId(departments[0].id)
    }
  }, [departments, internalMeetingDepartmentId, user?.department_id])

  const applyCommonViewPayload = React.useCallback(
    (payload: CommonViewPayload) => {
      if (payload.users) setUsers(payload.users)
      if (payload.departments) setDepartments(payload.departments)
      setCommonViewMeta({
        requested: payload.requested,
        included: payload.included,
        missing: payload.missing,
        guardrails: payload.guardrails || null,
      })
      const weekStartIso = payload.week_start
      const normalizedFeedback = payload.items.feedback.map((item) => {
        const parsed = parseFeedbackNote(item.note)
        return {
          ...item,
          note: parsed.note,
          everyday: parsed.everyday,
          date: parsed.everyday ? weekStartIso : item.date,
        }
      })
      const normalizedBlocked = payload.items.blocked.map((item: any) => {
        const status = normalizeCommonTaskStatus(item.status, item.isDone)
        return {
          ...item,
          taskId: item.taskId || item.task_id || undefined,
          userId: item.userId || item.user_id || undefined,
          fastTaskOrder:
            typeof (item.fastTaskOrder ?? item.fast_task_order) === "number"
              ? (item.fastTaskOrder ?? item.fast_task_order)
              : undefined,
          finishPeriod: item.finishPeriod || item.finish_period || null,
          oneHReportSlot: normalizeOneHReportSlot(item.oneHReportSlot || item.one_h_report_slot),
          oneHMarker: item.oneHMarker || item.one_h_marker || null,
          oneHMarkerByGa: Boolean(item.oneHMarkerByGa ?? item.one_h_marker_by_ga),
          oneHMarkerComment: item.oneHMarkerComment ?? item.one_h_marker_comment ?? null,
          isDeadlineImportant: Boolean(item.isDeadlineImportant ?? item.is_deadline_important),
          dueDate: item.dueDate || item.due_date || null,
          startDate: item.startDate || item.start_date || null,
          createdAt: item.createdAt || item.created_at || null,
          completedAt: item.completedAt || item.completed_at || null,
          departmentId: item.departmentId || item.department_id || undefined,
          confirmationOwner: item.confirmationOwner || item.confirmation_owner || null,
          isSystemTask: Boolean(item.isSystemTask ?? item.is_system_task),
          status,
          isDone: isCommonTaskDone(status, item.isDone),
        }
      })
      const normalizedOneH = payload.items.oneH.map((item: any) => {
        const status = normalizeCommonTaskStatus(item.status, item.isDone)
        return {
          ...item,
          taskId: item.taskId || item.task_id || undefined,
          userId: item.userId || item.user_id || undefined,
          fastTaskOrder:
            typeof (item.fastTaskOrder ?? item.fast_task_order) === "number"
              ? (item.fastTaskOrder ?? item.fast_task_order)
              : undefined,
          finishPeriod: item.finishPeriod || item.finish_period || null,
          oneHReportSlot: normalizeOneHReportSlot(item.oneHReportSlot || item.one_h_report_slot),
          oneHMarker: item.oneHMarker || item.one_h_marker || null,
          oneHMarkerByGa: Boolean(item.oneHMarkerByGa ?? item.one_h_marker_by_ga),
          oneHMarkerComment: item.oneHMarkerComment ?? item.one_h_marker_comment ?? null,
          isDeadlineImportant: Boolean(item.isDeadlineImportant ?? item.is_deadline_important),
          dueDate: item.dueDate || item.due_date || null,
          startDate: item.startDate || item.start_date || null,
          createdAt: item.createdAt || item.created_at || null,
          completedAt: item.completedAt || item.completed_at || null,
          departmentId: item.departmentId || item.department_id || undefined,
          confirmationOwner: item.confirmationOwner || item.confirmation_owner || null,
          isSystemTask: Boolean(item.isSystemTask ?? item.is_system_task),
          status,
          isDone: isCommonTaskDone(status, item.isDone),
        }
      })
      const normalizedPersonal = payload.items.personal.map((item: any) => {
        const status = normalizeCommonTaskStatus(item.status, item.isDone)
        return {
          ...item,
          taskId: item.taskId || item.task_id || undefined,
          userId: item.userId || item.user_id || undefined,
          fastTaskOrder:
            typeof (item.fastTaskOrder ?? item.fast_task_order) === "number"
              ? (item.fastTaskOrder ?? item.fast_task_order)
              : undefined,
          finishPeriod: item.finishPeriod || item.finish_period || null,
          oneHMarker: item.oneHMarker || item.one_h_marker || null,
          oneHMarkerByGa: Boolean(item.oneHMarkerByGa ?? item.one_h_marker_by_ga),
          oneHMarkerComment: item.oneHMarkerComment ?? item.one_h_marker_comment ?? null,
          isDeadlineImportant: Boolean(item.isDeadlineImportant ?? item.is_deadline_important),
          dueDate: item.dueDate || item.due_date || null,
          startDate: item.startDate || item.start_date || null,
          createdAt: item.createdAt || item.created_at || null,
          completedAt: item.completedAt || item.completed_at || null,
          departmentId: item.departmentId || item.department_id || undefined,
          confirmationOwner: item.confirmationOwner || item.confirmation_owner || null,
          isSystemTask: Boolean(item.isSystemTask ?? item.is_system_task),
          isPersonalTask: item.isPersonalTask ?? item.is_personal_task ?? true,
          status,
          isDone: isCommonTaskDone(status, item.isDone),
        }
      })
      const normalizedR1 = payload.items.r1.map((item: any) => {
        const status = normalizeCommonTaskStatus(item.status, item.isDone)
        return {
          ...item,
          taskId: item.taskId || item.task_id || undefined,
          userId: item.userId || item.user_id || undefined,
          fastTaskOrder:
            typeof (item.fastTaskOrder ?? item.fast_task_order) === "number"
              ? (item.fastTaskOrder ?? item.fast_task_order)
              : undefined,
          finishPeriod: item.finishPeriod || item.finish_period || null,
          oneHReportSlot: normalizeOneHReportSlot(item.oneHReportSlot || item.one_h_report_slot),
          oneHMarker: item.oneHMarker || item.one_h_marker || null,
          oneHMarkerByGa: Boolean(item.oneHMarkerByGa ?? item.one_h_marker_by_ga),
          oneHMarkerComment: item.oneHMarkerComment ?? item.one_h_marker_comment ?? null,
          isDeadlineImportant: Boolean(item.isDeadlineImportant ?? item.is_deadline_important),
          dueDate: item.dueDate || item.due_date || null,
          startDate: item.startDate || item.start_date || null,
          createdAt: item.createdAt || item.created_at || null,
          completedAt: item.completedAt || item.completed_at || null,
          departmentId: item.departmentId || item.department_id || undefined,
          confirmationOwner: item.confirmationOwner || item.confirmation_owner || null,
          isSystemTask: Boolean(item.isSystemTask ?? item.is_system_task),
          status,
          isDone: isCommonTaskDone(status, item.isDone),
        }
      })
      const normalizedProblems = payload.items.problems.map((item) => {
        const parsed = parseFeedbackNote(item.note)
        return {
          ...item,
          note: parsed.note,
          everyday: parsed.everyday,
          date: parsed.everyday ? weekStartIso : item.date,
        }
      })
      const normalizedExternal = payload.items.external
        .map((item) => {
          const calendarCategories = item.calendarCategories ?? item.calendar_categories ?? []
          return {
            ...item,
            recurrenceType: item.recurrenceType ?? item.recurrence_type ?? "none",
            calendarCategories,
            calendarImported: Boolean(
              item.calendarImported ?? item.calendar_imported ?? item.microsoft_event_id
            ),
          } as ExternalItem
        })
        .filter((item) => !isCalendarAnnualLeave(item.title, item.calendarCategories))
      const normalizedInternal = payload.items.internal.map((item) => ({
        ...item,
        recurrenceType: item.recurrenceType ?? item.recurrence_type ?? "none",
        pairedExternalMeetingId:
          item.pairedExternalMeetingId ?? item.paired_external_meeting_id ?? null,
        preExternalMeetingId:
          item.preExternalMeetingId ?? item.pre_external_meeting_id ?? null,
        linkedExternalCalendarCategories:
          item.linkedExternalCalendarCategories ?? item.linked_external_calendar_categories ?? [],
        linkedExternalCalendarImported: Boolean(
          item.linkedExternalCalendarImported ?? item.linked_external_calendar_imported
        ),
        linkedExternalRecurrenceType:
          item.linkedExternalRecurrenceType ?? item.linked_external_recurrence_type ?? "none",
      })) as InternalItem[]
      setCommonData((prev) => {
        let next = { ...prev }
        for (const includeKey of payload.included) {
          const buckets = includeToBuckets[includeKey] || []
          for (const bucket of buckets) {
            if (bucket === "feedback") {
              next = { ...next, feedback: normalizedFeedback }
            } else if (bucket === "blocked") {
              next = { ...next, blocked: normalizedBlocked }
            } else if (bucket === "oneH") {
              next = { ...next, oneH: normalizedOneH }
            } else if (bucket === "personal") {
              next = { ...next, personal: mergePersonalItems(normalizedPersonal) }
            } else if (bucket === "r1") {
              next = { ...next, r1: normalizedR1 }
            } else if (bucket === "problems") {
              next = { ...next, problems: normalizedProblems }
            } else if (bucket === "external") {
              next = { ...next, external: normalizedExternal }
            } else if (bucket === "internal") {
              next = { ...next, internal: normalizedInternal }
            } else {
              next = { ...next, [bucket]: payload.items[bucket] }
            }
          }
        }
        return next
      })
    },
    [includeToBuckets]
  )

  const fetchCommonViewStage = React.useCallback(
    async (weekStartIso: string, includeList: string[]) => {
      const includeKey = includeList.join(",")
      const freezeParam = freezeOneHSlots ? "&freeze_one_h_slots=true" : ""
      const cacheKey = [
        weekStartIso,
        includeKey,
        user?.role || "anon",
        user?.department_id || "",
        commonDepartmentId || "all",
        freezeOneHSlots ? "freeze-1h" : "rollover-1h",
      ].join("|")
      const cached = COMMON_VIEW_CACHE.get(cacheKey)
      if (cached) {
        applyCommonViewPayload(cached.payload)
      }
      const headers: Record<string, string> = {}
      if (cached?.etag) headers["If-None-Match"] = cached.etag
      const deptParam = commonDepartmentId
        ? `&department_id=${encodeURIComponent(commonDepartmentId)}`
        : "&include_all_departments=true"
      const res = await apiFetch(
        `/common-view?week_start=${encodeURIComponent(weekStartIso)}&include=${encodeURIComponent(includeKey)}${deptParam}${freezeParam}`,
        { headers }
      )
      if (res?.status === 304 && cached) {
        applyCommonViewPayload(cached.payload)
        return true
      }
      if (!res?.ok) {
        if (res?.status === 401) {
          throw new Error("common_view_failed_401")
        }
        console.warn(`Aggregate common view failed with status ${res?.status}; falling back to legacy loader.`)
        return false
      }
      const payload = (await res.json()) as CommonViewPayload
      const etag = res.headers.get("ETag")
      COMMON_VIEW_CACHE.set(cacheKey, { etag, payload, cachedAt: Date.now() })
      applyCommonViewPayload(payload)
      return true
    },
    [apiFetch, applyCommonViewPayload, user?.department_id, user?.role, commonDepartmentId, freezeOneHSlots]
  )

  // Load data on mount
  React.useEffect(() => {
    let mounted = true
    async function load() {
      try {
        if (authLoading) return
        if (!userId) {
          if (mounted) setDataLoaded(true)
          return
        }
        if (mounted) setDataLoaded(false)
        if (commonViewAggregateEnabled) {
          const weekStartIso = toISODate(weekStart)
          try {
            if (mounted) {
              setCommonViewMeta(null)
              setCommonData({
                late: [],
                absent: [],
                leave: [],
                externalHoliday: [],
                blocked: [],
                oneH: [],
                personal: [],
                external: [],
                internal: [],
                r1: [],
                problems: [],
                feedback: [],
                priority: [],
                bz: [],
              })
            }
            let aggregateLoaded = true
            for (const includeList of commonViewIncludeStages) {
              const stageLoaded = await fetchCommonViewStage(weekStartIso, includeList)
              if (!stageLoaded) {
                aggregateLoaded = false
                break
              }
            }
            if (aggregateLoaded && mounted) {
              if (selectedDates.size === 0) {
                const todayIso = toISODate(new Date())
                setSelectedDates(new Set([todayIso]))
                setMultiMode(false)
              }
              setDataLoaded(true)
            }
            if (aggregateLoaded) return
          } catch (err) {
            if (!(err instanceof Error && err.message === "common_view_failed_401")) {
              console.error("Failed to load aggregate common view data", err)
            }
          }
        }
        const weekStartIso = toISODate(weekStart)
        const weekEndIso = toISODate(addDays(weekStart, 6))
        const weekDates = getWeekdays(weekStart).map(toISODate)
        // Initialize all data buckets
        const allData = {
          late: [] as LateItem[],
          absent: [] as AbsentItem[],
          leave: [] as LeaveItem[],
          externalHoliday: [] as ExternalHolidayItem[],
          blocked: [] as BlockedItem[],
          oneH: [] as OneHItem[],
          personal: [] as PersonalItem[],
          external: [] as ExternalItem[],
          internal: [] as InternalItem[],
          r1: [] as R1Item[],
          problems: [] as ProblemItem[],
          feedback: [] as FeedbackItem[],
          priority: [] as PriorityItem[],
          bz: [] as BzItem[],
        }

        // Load primary datasets in parallel (week scoped)
        // Use lookup endpoint so STAFF can load all users
        const usersEndpoint = "/users/lookup?include_inactive=false"
        const commonEntriesEndpoint = `/common-entries?from=${encodeURIComponent(weekStartIso)}&to=${encodeURIComponent(weekEndIso)}`
        let tasksEndpoint = commonDepartmentId
          ? `/tasks?include_done=true&department_id=${encodeURIComponent(commonDepartmentId)}`
          : "/tasks?include_done=true&include_all_departments=true"
        const tasksEndpointWithWindow = `${tasksEndpoint}&window_from=${encodeURIComponent(weekStartIso)}&window_to=${encodeURIComponent(weekEndIso)}`
        const meetingsEndpointBase = commonDepartmentId
          ? `/meetings?department_id=${encodeURIComponent(commonDepartmentId)}`
          : "/meetings?include_all_departments=true"

        const systemTasksRequests = weekDates.map((dateStr) => {
          const qs = new URLSearchParams()
          qs.set("occurrence_date", dateStr)
          if (commonDepartmentId) qs.set("department_id", commonDepartmentId)
          return apiFetch(`/system-tasks?${qs.toString()}`)
        })

        const [
          uRes,
          depRes,
          ceRes,
          initialTasksRes,
          externalMeetingsRes,
          internalMeetingsRes,
          ...systemTasksResponses
        ] = await Promise.all([
          apiFetch(usersEndpoint),
          apiFetch("/departments"),
          apiFetch(commonEntriesEndpoint),
          apiFetch(tasksEndpointWithWindow),
          apiFetch(`${meetingsEndpointBase}&meeting_type=external`),
          apiFetch(`${meetingsEndpointBase}&meeting_type=internal`),
          ...systemTasksRequests,
        ])

        let loadedUsers: User[] = []
        if (uRes?.ok) {
          const lookup = (await uRes.json()) as {
            id: string
            username?: string | null
            full_name?: string | null
            role: string
            department_id?: string | null
            is_active: boolean
          }[]
          loadedUsers = lookup.map((u) => ({
            id: u.id,
            email: u.username || u.full_name || "",
            username: u.username,
            full_name: u.full_name,
            role: u.role as any,
            department_id: u.department_id,
            is_active: u.is_active,
          }))
          if (mounted) setUsers(loadedUsers)
        }
        let loadedDepartments: Department[] = []
        if (depRes?.ok) {
          loadedDepartments = (await depRes.json()) as Department[]
          if (mounted) setDepartments(loadedDepartments)
        }
        const normalizeDepartmentName = (name: string) => {
          const trimmed = name.trim()
          const lower = trimmed.toLowerCase()
          if (lower.includes("project content manager")) return "Product Content"
          return trimmed
        }
        const departmentNameById = new Map<string, string>(
          loadedDepartments
            .map((d) => (d.id && d.name ? [d.id, normalizeDepartmentName(d.name)] as [string, string] : null))
            .filter((entry): entry is [string, string] => entry !== null)
        )
        
        // Find Product Content Manager department ID
        let productContentDeptId: string | null = null
        if (loadedDepartments.length > 0) {
          const pcmDept = loadedDepartments.find(
            (d) => d.name?.toLowerCase().includes("project content") || 
                   d.name?.toLowerCase().includes("content manager") ||
                   d.code === "PCM"
          )
          productContentDeptId = pcmDept?.id || null
        }

        // Load common entries
        if (ceRes?.ok) {
          const entries = (await ceRes.json()) as CommonEntry[]

          for (const e of entries) {
            // Prioritize assigned user, fallback to creator, then title
            let user = loadedUsers.find((u) => u.id === e.assigned_to_user_id)
            if (!user) {
              user = loadedUsers.find((u) => u.id === e.created_by_user_id)
            }
            if (commonDepartmentId && user?.department_id && user.department_id !== commonDepartmentId) {
              continue
            }
            const personName = user?.full_name || user?.username || e.title || "Unknown"
            
            // Use entry_date if available, otherwise parse from description or fallback to created_at
            let date = e.entry_date || null
            if (!date) {
              // Try to parse date from description
              const descDateMatch = (e.description || "").match(/Date:\s*(\d{4}-\d{2}-\d{2})/i)
              if (descDateMatch) {
                date = descDateMatch[1]
              } else {
                date = toISODate(new Date(e.created_at))
              }
            }

            if (e.category === "Delays") {
              // Parse until time from description
              let until = "09:00"
              let start = "08:00"
              let note = e.description || ""
              const startMatch = note.match(/Start:\s*(\d{1,2}:\d{2})/i)
              if (startMatch) {
                start = startMatch[1]
                note = note.replace(/Start:\s*\d{1,2}:\d{2}/i, "").trim()
              }
              const untilMatch = note.match(/Until:\s*(\d{1,2}:\d{2})/i)
              if (untilMatch) {
                until = untilMatch[1]
                note = note.replace(/Until:\s*\d{1,2}:\d{2}/i, "").trim()
              }
              // Remove date from note if present
              note = note.replace(/Date:\s*\d{4}-\d{2}-\d{2}/i, "").trim()
              
              allData.late.push({
                entryId: e.id,
                person: personName,
                date,
                until,
                start,
                note: note || undefined,
              })
            } else if (e.category === "Absences") {
              // Parse from/to times from description
              let from = "08:00"
              let to = "23:00"
              let note = e.description || ""
              const fromToMatch = note.match(/From:\s*(\d{1,2}:\d{2})\s*-\s*To:\s*(\d{1,2}:\d{2})/i)
              if (fromToMatch) {
                from = fromToMatch[1]
                to = fromToMatch[2]
                note = note.replace(/From:\s*\d{1,2}:\d{2}\s*-\s*To:\s*\d{1,2}:\d{2}/i, "").trim()
              }
              // Remove date from note if present
              note = note.replace(/Date:\s*\d{4}-\d{2}-\d{2}/i, "").trim()
              
              allData.absent.push({
                entryId: e.id,
                person: personName,
                date,
                from,
                to,
                note: note || undefined,
                userId: e.assigned_to_user_id || e.created_by_user_id || undefined,
              })
            } else if (e.category === "Annual Leave") {
              // Parse leave information from description
              let startDate = date
              let endDate = date
              let fullDay = true
              let from = ""
              let to = ""
              let note = e.description || ""
              const isAllUsers = note.includes(ALL_USERS_MARKER)
              if (isAllUsers) {
                note = note.replace(ALL_USERS_MARKER, "").trim()
              }
              const dateMatches = note.match(/\d{4}-\d{2}-\d{2}/g) || []
              
              // Parse date range
              const dateRangeMatch = note.match(/Date range:\s*(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})/i)
              if (dateRangeMatch) {
                startDate = dateRangeMatch[1]
                endDate = dateRangeMatch[2]
                note = note.replace(/Date range:\s*\d{4}-\d{2}-\d{2}\s+to\s+\d{4}-\d{2}-\d{2}/i, "").trim()
              } else {
                const dateMatch = note.match(/Date:\s*(\d{4}-\d{2}-\d{2})/i)
                if (dateMatch) {
                  startDate = dateMatch[1]
                  endDate = dateMatch[1]
                  note = note.replace(/Date:\s*\d{4}-\d{2}-\d{2}/i, "").trim()
                } else if (dateMatches.length) {
                  const firstDate = dateMatches[0] ?? date
                  const secondDate = dateMatches[1] ?? firstDate
                  startDate = firstDate
                  endDate = secondDate
                }
              }
              
              // Parse full day or time range
              if (note.includes("Full day")) {
                fullDay = true
                note = note.replace(/\(Full day\)/i, "").trim()
              } else {
                const timeMatch = note.match(/\((\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\)/i)
                if (timeMatch) {
                  fullDay = false
                  from = timeMatch[1]
                  to = timeMatch[2]
                  note = note.replace(/\(\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\)/i, "").trim()
                }
              }
              
              allData.leave.push({
                entryId: e.id,
                person: personName,
                startDate,
                endDate,
                fullDay,
                from: from || undefined,
                to: to || undefined,
                note: note || undefined,
                isAllUsers,
                userId: e.assigned_to_user_id || e.created_by_user_id,
              })
            } else if (e.category === "Blocks") {
              allData.blocked.push({
                title: e.title,
                person: personName,
                date,
                note: e.description || undefined,
              })
            } else if (e.category === "External Tasks") {
              allData.external.push({
                title: e.title,
                date,
                time: "14:00",
                platform: "Zoom",
                owner: personName,
              })
            } else if (e.category === "External Holiday") {
              allData.externalHoliday.push({
                entryId: e.id,
                title: e.title,
                date,
                note: e.description || undefined,
              })
            } else if (e.category === "Problems") {
              const parsed = parseFeedbackNote(e.description)
              let note = parsed.note || ""
              note = note.replace(/Date:\s*\d{4}-\d{2}-\d{2}/i, "").trim()
              const problemDate = parsed.everyday ? weekStartIso : date
              const createdDate = e.created_at ? toISODate(new Date(e.created_at)) : undefined
              allData.problems.push({
                entryId: e.id,
                title: e.title,
                person: personName,
                date: problemDate,
                note: note || undefined,
                everyday: parsed.everyday,
                createdDate,
              })
            } else if (e.category === "Complaints" || e.category === "Requests" || e.category === "Proposals") {
              const parsed = parseFeedbackNote(e.description)
              let note = parsed.note || ""
              note = note.replace(/Date:\s*\d{4}-\d{2}-\d{2}/i, "").trim()
              const feedbackDate = parsed.everyday ? weekStartIso : date
              const createdDate = e.created_at ? toISODate(new Date(e.created_at)) : undefined
              allData.feedback.push({
                entryId: e.id,
                title: e.title,
                person: personName,
                date: feedbackDate,
                note: note || undefined,
                everyday: parsed.everyday,
                createdDate,
              })
            }
          }
        }

        let projectNameById = new Map<string, string>()
        const projectInfoById = new Map<string, Project>()

        // Load tasks for blocked, 1H, R1, external, and priority
        // For priority items (PRJK), we want everyone to see the same projects,
        // so try to fetch all tasks first, fallback to user's tasks if 403
        let loadedTasks: Task[] = []
        let tasksRes = initialTasksRes
        if (!tasksRes?.ok && tasksRes?.status === 403 && !commonDepartmentId) {
          tasksRes = await apiFetch(`/tasks?include_done=true&window_from=${encodeURIComponent(weekStartIso)}&window_to=${encodeURIComponent(weekEndIso)}`)
        }

        if (tasksRes?.ok) {
          const tasks = (await tasksRes.json()) as Task[]
          loadedTasks = tasks

          const chunk = <T,>(items: T[], size: number): T[][] => {
            if (size <= 0) return [items]
            const out: T[][] = []
            for (let i = 0; i < items.length; i += size) {
              out.push(items.slice(i, i + size))
            }
            return out
          }
          const fetchProjectLookup = async (ids: string[]) => {
            const uniqueIds = Array.from(new Set(ids.filter(Boolean)))
            const out = new Map<string, Project>()
            for (const batch of chunk(uniqueIds, 50)) {
              const qs = new URLSearchParams()
              for (const id of batch) qs.append("ids", id)
              const res = await apiFetch(`/projects/lookup?${qs.toString()}`)
              if (!res.ok) continue
              const data = (await res.json()) as Array<Project>
              for (const item of data) {
                if (item?.id) out.set(item.id, item)
              }
            }
            return out
          }

          const projectIds = Array.from(
            new Set(tasks.map((t) => t.project_id).filter((id): id is string => Boolean(id)))
          )
          if (projectIds.length) {
            const lookupMap = await fetchProjectLookup(projectIds)
            for (const project of lookupMap.values()) {
              const projectName = resolveProjectTitle(project)
              if (!projectName) continue
              projectNameById.set(project.id, projectName)
              projectInfoById.set(project.id, project)
            }
          }
          
          const today = toISODate(new Date())
          // Group priority items by project_id, tracking assignees per date
          // Participants must be resolved per day only.
          const priorityMap = new Map<string, { 
            project: string; 
            assigneesByDate: Map<string, Set<string>>; // Track assignees per date
            dates: Set<string>;
          }>()

          // Second pass: process tasks for date-specific data and other categories
          for (const t of tasks) {
            const statusValue = (t.status || "").toLowerCase()
            const isDone = Boolean(t.completed_at) || statusValue === "done" || statusValue === "completed"
            const normalizedTaskStatus = normalizeCommonTaskStatus(t.status, isDone)

            const assigneeId = t.assigned_to || t.assignees?.[0]?.id || t.assigned_to_user_id || null
            const assignee = t.assignees?.[0] || (assigneeId ? loadedUsers.find((u) => u.id === assigneeId) : null)
            const confirmationOwner = getKaGentiConfirmationOwner(
              t.confirmation_assignee_id
                ? loadedUsers.find((candidate) => candidate.id === t.confirmation_assignee_id)
                : null
            )
            const ownerName = assignee?.full_name || assignee?.username || null
            const assigneeNames = t.assignees?.length
              ? t.assignees.map((a) => a.full_name || a.username || a.email || "Unknown")
              : ownerName
              ? [ownerName]
              : []
            const assigneeLabel = assigneeNames.length ? assigneeNames.join(", ") : "Unknown"
            const departmentId =
              t.assignees?.find((a) => a.department_id)?.department_id || assignee?.department_id || t.department_id || undefined
            
            const phaseValue = (t.phase || "").toUpperCase()
            const isCheckPhase = phaseValue === "CHECK" || phaseValue === "CONTROL"

            // Helper function to generate dates from start_date to due_date
            // Check/Control phase tasks should be treated as single-day assignments.
            const getTaskDates = (task: Task, singleDayOnly: boolean): string[] => {
              if (singleDayOnly) {
                const dateOnly = parseDateOnly(task.planned_for || task.due_date || task.start_date)
                const resolved = dateOnly ?? (task.created_at ? new Date(task.created_at) : null)
                return resolved ? [toISODate(resolved)] : [today]
              }
              const startDate = parseDateOnly(task.start_date)
              const dueDate = parseDateOnly(task.due_date)
              
              // If both start and due dates exist and are different, generate range
              if (startDate && dueDate && !Number.isNaN(startDate.getTime()) && !Number.isNaN(dueDate.getTime())) {
                const start = new Date(startDate)
                start.setHours(0, 0, 0, 0)
                const end = new Date(dueDate)
                end.setHours(0, 0, 0, 0)
                
                // If start is after end, swap them
                if (start > end) {
                  const temp = start
                  start.setTime(end.getTime())
                  end.setTime(temp.getTime())
                }
                
                const dates: string[] = []
                const current = new Date(start)
                while (current <= end) {
                  const dayOfWeek = current.getDay()
                  // Only include weekdays (Monday=1 to Friday=5)
                  if (dayOfWeek >= 1 && dayOfWeek <= 5) {
                    dates.push(toISODate(current))
                  }
                  current.setDate(current.getDate() + 1)
                }
                return dates.length > 0 ? dates : [toISODate(start)]
              }
              
              // Fallback to single date
              const dateOnly = parseDateOnly(task.planned_for || task.due_date || task.start_date)
              const resolved = dateOnly ?? (task.created_at ? new Date(task.created_at) : null)
              return resolved ? [toISODate(resolved)] : [today]
            }
            
            const taskDates = getTaskDates(t, isCheckPhase).filter(
              (dateStr) => dateStr >= weekStartIso && dateStr <= weekEndIso
            )
            if (!taskDates.length) {
              continue
            }

            // Create entries for each date in the range
            for (const taskDate of taskDates) {
              if (t.is_bllok) {
                allData.blocked.push({
                  taskId: t.id,
                  title: t.title,
                  person: assigneeLabel,
                  assignees: assigneeNames,
                  userId: assigneeId || undefined,
                  date: taskDate,
                  note: t.description || undefined,
                  status: normalizedTaskStatus,
                  isDone: isCommonTaskDone(normalizedTaskStatus, isDone),
                  fastTaskOrder: t.fast_task_order ?? undefined,
                  finishPeriod: t.finish_period || null,
                  oneHReportSlot: normalizeOneHReportSlot(t.one_h_report_slot),
                  oneHMarker: t.one_h_marker || null,
                  isDeadlineImportant: Boolean(t.is_deadline_important),
                  dueDate: t.due_date || null,
                  startDate: t.start_date || null,
                  createdAt: t.created_at || null,
                  completedAt: t.completed_at || null,
                  confirmationOwner,
                  isSystemTask: Boolean(t.system_template_origin_id || t.system_task_slot_id),
                })
              }
              if (t.is_1h_report) {
                allData.oneH.push({
                  taskId: t.id,
                  title: t.title,
                  person: assigneeLabel,
                  assignees: assigneeNames,
                  userId: assigneeId || undefined,
                  date: taskDate,
                  note: t.description || undefined,
                  departmentId,
                  status: normalizedTaskStatus,
                  isDone: isCommonTaskDone(normalizedTaskStatus, isDone),
                  fastTaskOrder: t.fast_task_order ?? undefined,
                  finishPeriod: t.finish_period || null,
                  oneHMarker: t.one_h_marker || null,
                  isDeadlineImportant: Boolean(t.is_deadline_important),
                  dueDate: t.due_date || null,
                  startDate: t.start_date || null,
                  createdAt: t.created_at || null,
                  completedAt: t.completed_at || null,
                  confirmationOwner,
                  isSystemTask: Boolean(t.system_template_origin_id || t.system_task_slot_id),
                })
              }
              if (t.is_personal) {
                allData.personal.push({
                  taskId: t.id,
                  title: t.title,
                  person: assigneeLabel,
                  assignees: assigneeNames,
                  userId: assigneeId || undefined,
                  date: taskDate,
                  note: t.description || undefined,
                  departmentId,
                  status: normalizedTaskStatus,
                  isDone: isCommonTaskDone(normalizedTaskStatus, isDone),
                  fastTaskOrder: t.fast_task_order ?? undefined,
                  finishPeriod: t.finish_period || null,
                  oneHMarker: t.one_h_marker || null,
                  isDeadlineImportant: Boolean(t.is_deadline_important),
                  dueDate: t.due_date || null,
                  startDate: t.start_date || null,
                  createdAt: t.created_at || null,
                  completedAt: t.completed_at || null,
                  confirmationOwner,
                  isSystemTask: Boolean(t.system_template_origin_id || t.system_task_slot_id),
                  isPersonalTask: true,
                })
              }
              if (t.is_r1) {
                allData.r1.push({
                  taskId: t.id,
                  title: t.title,
                  date: taskDate,
                  owner: assigneeLabel,
                  assignees: assigneeNames,
                  userId: assigneeId || undefined,
                  note: t.description || undefined,
                  departmentId,
                  status: normalizedTaskStatus,
                  isDone: isCommonTaskDone(normalizedTaskStatus, isDone),
                  fastTaskOrder: t.fast_task_order ?? undefined,
                  finishPeriod: t.finish_period || null,
                  oneHMarker: t.one_h_marker || null,
                  isDeadlineImportant: Boolean(t.is_deadline_important),
                  dueDate: t.due_date || null,
                  startDate: t.start_date || null,
                  createdAt: t.created_at || null,
                  completedAt: t.completed_at || null,
                  confirmationOwner,
                  isSystemTask: Boolean(t.system_template_origin_id || t.system_task_slot_id),
                })
              }
              if (
                !t.is_personal &&
                !isDone &&
                normalizedTaskStatus === "WAITING_CONFIRMATION" &&
                confirmationOwner
              ) {
                allData.personal.push({
                  taskId: t.id,
                  title: t.title,
                  person: assigneeLabel,
                  assignees: assigneeNames,
                  userId: assigneeId || undefined,
                  date: taskDate,
                  note: t.description || undefined,
                  departmentId,
                  status: normalizedTaskStatus,
                  isDone: false,
                  fastTaskOrder: t.fast_task_order ?? undefined,
                  finishPeriod: t.finish_period || null,
                  oneHReportSlot: normalizeOneHReportSlot(t.one_h_report_slot),
                  oneHMarker: t.one_h_marker || null,
                  isDeadlineImportant: Boolean(t.is_deadline_important),
                  dueDate: t.due_date || null,
                  startDate: t.start_date || null,
                  createdAt: t.created_at || null,
                  completedAt: null,
                  confirmationOwner,
                  isSystemTask: Boolean(t.system_template_origin_id || t.system_task_slot_id),
                  isPersonalTask: false,
                })
              }
            }
            if (t.task_type === "adhoc" && t.project_id) {
              // External tasks use the first date from the range
              const externalDate = taskDates[0] || today
              allData.external.push({
                title: t.title,
                date: externalDate,
                time: "14:00",
                platform: "Zoom",
                owner: assigneeLabel,
                assignees: assigneeNames,
              })
            }

            // Priority items - track dates and date-specific assignees for active tasks
            if (t.project_id) {
              const projectName = projectNameById.get(t.project_id)
              // Skip if project name is not found (project might be deleted or inaccessible)
              if (!projectName) {
                continue
              }
              
              // Use project_id as the key (not project_id-date)
              const projectKey = t.project_id
              
              // Initialize entry if it doesn't exist
              if (!priorityMap.has(projectKey)) {
                priorityMap.set(projectKey, {
                  project: projectName,
                  assigneesByDate: new Map<string, Set<string>>(),
                  dates: new Set<string>(),
                })
              }
              
              const entry = priorityMap.get(projectKey)!
              
              // Add all task dates to the project's dates
              for (const taskDate of taskDates) {
                entry.dates.add(taskDate)
                
                // Track assignees for this specific date
                if (!entry.assigneesByDate.has(taskDate)) {
                  entry.assigneesByDate.set(taskDate, new Set<string>())
                }
                const dateAssignees = entry.assigneesByDate.get(taskDate)!
                
                // Add assignees to this date only
                for (const name of assigneeNames) {
                  dateAssignees.add(name)
                }
              }
            }
          }
          // Expand priority items: create one entry per project-date combination
          // For MST and VS/VL projects in Product Content, show only dates within the selected week
          const expandedPriority: PriorityItem[] = []
          const isInWeek = (dateStr: string) => dateStr >= weekStartIso && dateStr <= weekEndIso
          for (const [projectKey, entry] of priorityMap.entries()) {
            const project = projectInfoById.get(projectKey)
            if (!project) continue // Skip if project info not available
            
            // Check if this is MST or VS/VL project in Product Content Manager
            const isMstByType = project.project_type === "MST"
            const titleUpper = (project.title || "").toUpperCase()
            const isMstByTitle = titleUpper.includes("MST")
            const isMst = isMstByType || isMstByTitle
            const isVsVl = titleUpper.includes("VS") || titleUpper.includes("VL")
            const isProductContent = project.department_id === productContentDeptId
            
            let datesToUse: string[] = []
            
            if ((isMst || isVsVl) && isProductContent) {
              if (project.due_date) {
                // For MST/VS/VL in Product Content with due_date, generate dates within the selected week
                const weekStartDate = fromISODate(weekStartIso)
                const weekEndDate = fromISODate(weekEndIso)
                const dueDate = parseDateOnly(project.due_date)
                if (!dueDate) {
                  continue
                }
                dueDate.setHours(0, 0, 0, 0)
                const startDate = new Date(weekStartDate)
                const endDate = new Date(weekEndDate)

                if (dueDate >= startDate) {
                  if (dueDate < endDate) {
                    endDate.setTime(dueDate.getTime())
                  }
                  const currentDate = new Date(startDate)
                  while (currentDate <= endDate) {
                    const dayOfWeek = currentDate.getDay()
                    if (dayOfWeek >= 1 && dayOfWeek <= 5) {
                      datesToUse.push(toISODate(currentDate))
                    }
                    currentDate.setDate(currentDate.getDate() + 1)
                  }
                }
              } else if (entry.dates.size > 0) {
                // MST/VS/VL without due_date but with tasks - use task dates
                datesToUse = Array.from(entry.dates).sort()
              } else {
                // MST/VS/VL without due_date and no tasks - show on today
                datesToUse = [weekStartIso]
              }
            } else {
              // For other projects, use dates from tasks
              // Only show projects that have actual task dates
              if (entry.dates.size > 0) {
                datesToUse = Array.from(entry.dates).sort()
              } else {
                // Skip projects with no tasks/dates - don't show them
                continue
              }
            }

            // Always include actual task dates to ensure assignees show on their real days.
            if (entry.dates.size > 0) {
              const merged = new Set(datesToUse)
              for (const d of entry.dates) merged.add(d)
              datesToUse = Array.from(merged).sort()
            }
            datesToUse = datesToUse.filter(isInWeek)
            if (!datesToUse.length) {
              continue
            }
            // Create one priority entry per date for this project
            // Participants are derived strictly from tasks on that specific date.
            for (const date of datesToUse) {
              // Get assignees who have tasks specifically on this date
              const dateAssignees = entry.assigneesByDate.get(date) || new Set<string>()
              const departmentId = project.department_id ?? null
              const departmentName = departmentId ? departmentNameById.get(departmentId) || "Other" : "Other"

              expandedPriority.push({
                project: entry.project,
                date: date,
                assignees: Array.from(dateAssignees),
                department_id: departmentId,
                department_name: departmentName,
              })
            }
          }
          
          allData.priority = expandedPriority
        }

        allData.personal = mergePersonalItems(allData.personal)

        let loadedExternalMeetings: Meeting[] = []
        if (externalMeetingsRes?.ok) {
          const meetings = (await externalMeetingsRes.json()) as Meeting[]
          loadedExternalMeetings = meetings
          if (mounted) setExternalMeetings(meetings)
          for (const meeting of meetings) {
            const resolvedDate = resolveExternalMeetingDate(meeting)
            const createdAt = new Date(meeting.created_at)
            const validCreatedAt = Number.isNaN(createdAt.getTime()) ? null : createdAt

            const ownerUser = meeting.created_by
              ? loadedUsers.find((u) => u.id === meeting.created_by)
              : null
            const ownerName = ownerUser?.full_name || ownerUser?.username || "Unknown"

            const displayDates = expandExternalMeetingDates(meeting, resolvedDate)
            const dateSources = displayDates.length ? displayDates : validCreatedAt ? [validCreatedAt] : []
            for (const dateSource of dateSources) {
              allData.external.push({
                id: `meeting:${meeting.id}:${toISODate(dateSource)}`,
                title: meeting.title || "External meeting",
                date: toISODate(dateSource),
                time: resolvedDate ? formatTime(resolvedDate) : "TBD",
                platform: meeting.platform?.trim() || "TBD",
                owner: ownerName,
                assignees: (meeting.participant_ids || [])
                  .map((participantId) => loadedUsers.find((candidate) => candidate.id === participantId))
                  .map((participant) => participant?.full_name || participant?.username || participant?.email || "")
                  .filter(Boolean),
                recurrenceType: meeting.recurrence_type || "none",
                calendarCategories: meeting.calendar_categories || [],
                calendarImported: Boolean(meeting.calendar_imported || meeting.microsoft_event_id),
              })
            }
          }
        }

        if (internalMeetingsRes?.ok) {
          const meetings = (await internalMeetingsRes.json()) as Meeting[]
          if (mounted) setInternalMeetings(meetings)
          for (const meeting of meetings) {
            const linkedExternalMeeting = loadedExternalMeetings.find(
              (candidate) =>
                candidate.id ===
                (meeting.paired_external_meeting_id || meeting.pre_external_meeting_id)
            )
            const resolvedDate = resolveExternalMeetingDate(meeting)
            const createdAt = new Date(meeting.created_at)
            const validCreatedAt = Number.isNaN(createdAt.getTime()) ? null : createdAt
            const dateSource = resolvedDate ?? validCreatedAt
            if (!dateSource) continue

            const ownerUser = meeting.created_by
              ? loadedUsers.find((u) => u.id === meeting.created_by)
              : null
            const ownerName = ownerUser?.full_name || ownerUser?.username || "Unknown"

            allData.internal.push({
              id: `meeting:${meeting.id}`,
              title: meeting.title || "Internal meeting",
              date: toISODate(dateSource),
              time: resolvedDate ? formatTime(resolvedDate) : "TBD",
              platform: meeting.platform?.trim() || "TBD",
              owner: ownerName,
              recurrenceType: meeting.recurrence_type || "none",
              pairedExternalMeetingId: meeting.paired_external_meeting_id || null,
              preExternalMeetingId: meeting.pre_external_meeting_id || null,
              linkedExternalCalendarCategories: linkedExternalMeeting?.calendar_categories || [],
              linkedExternalCalendarImported: Boolean(
                linkedExternalMeeting?.calendar_imported || linkedExternalMeeting?.microsoft_event_id
              ),
              linkedExternalRecurrenceType: linkedExternalMeeting?.recurrence_type || "none",
            })
          }
        }

        const userMap = new Map(loadedUsers.map((u) => [u.id, u]))
        const ganeUserId =
          loadedUsers.find((u) => u.username?.toLowerCase() === "gane.arifaj")?.id || null
        const templateById = new Map<string, SystemTaskTemplate>()
        for (const res of systemTasksResponses) {
          if (!res?.ok) continue
          const templates = (await res.json()) as SystemTaskTemplate[]
          for (const tmpl of templates) {
            const key = tmpl.template_id || tmpl.id
            if (key) templateById.set(key, tmpl)
          }
        }
        const bzMap = new Map<string, BzItem>()
        for (const task of loadedTasks) {
          const maybeActive = (task as Task & { is_active?: boolean }).is_active
          if (maybeActive === false) continue
          if (!task.system_template_origin_id) continue
          const template = templateById.get(task.system_template_origin_id)
          if (!template || !ganeUserId || !template.alignment_user_ids?.includes(ganeUserId)) continue

          const taskDate = parseDateOnly(task.start_date || task.due_date || task.created_at)
          if (!taskDate) continue
          const dateStr = toISODate(taskDate)
          if (dateStr < weekStartIso || dateStr > weekEndIso) continue

          const taskAssignees =
            task.assignees?.length
              ? task.assignees.map((a) => a.full_name || a.username || a.email || "Unknown").filter(Boolean)
              : task.assigned_to
                ? [userMap.get(task.assigned_to)?.full_name || userMap.get(task.assigned_to)?.username || "Unknown"].filter(Boolean)
                : []
          const bzWithNames = (template.alignment_user_ids || [])
            .map((id) => {
              const person = userMap.get(id)
              return person?.full_name || person?.username || ""
            })
            .filter(Boolean)
          const bzWithInitials = bzWithNames.map(initials).filter(Boolean)
          const bzWithLabel =
            bzWithInitials.length > 0
              ? bzWithInitials.join(", ")
              : template.alignment_roles?.length
                ? template.alignment_roles.join(", ")
                : ""
          const mapKey = `${dateStr}:${task.system_template_origin_id}:${(task.title || "-").trim().toLowerCase()}`
          const existing = bzMap.get(mapKey)
          if (!existing) {
            bzMap.set(mapKey, {
              title: task.title || "-",
              date: dateStr,
              time: formatAlignmentTime(template.alignment_time),
              assignees: taskAssignees,
              bzWithLabel,
            })
            continue
          }
          existing.assignees = Array.from(new Set([...(existing.assignees || []), ...taskAssignees]))
          if (!existing.time) existing.time = formatAlignmentTime(template.alignment_time)
          if (!existing.bzWithLabel && bzWithLabel) existing.bzWithLabel = bzWithLabel
        }
        allData.bz = Array.from(bzMap.values())

        // Single state update with all data
        if (mounted) {
          setCommonData(allData)
        }

        // Select today by default
        if (mounted && selectedDates.size === 0) {
          const todayIso = toISODate(new Date())
          setSelectedDates(new Set([todayIso]))
          setMultiMode(false)
        }
        
        // Mark data as loaded
        if (mounted) {
          setDataLoaded(true)
        }
      } catch (err) {
        console.error("Failed to load common view data", err)
      }
    }
    void load()
    return () => {
      mounted = false
    }
  }, [apiFetch, authLoading, userId, user?.role, user?.department_id, weekStart, commonViewAggregateEnabled, commonViewIncludeStages, fetchCommonViewStage])

  useVisibleRefresh(async () => {
    await fetchCommonViewStage(toISODate(weekStart), ["tasks"])
  }, !authLoading && Boolean(userId) && !savingOneHMarkerTaskId)

  refreshCommonTasksRef.current = async () => {
    await fetchCommonViewStage(toISODate(weekStart), ["tasks"])
  }

  const reloadMeetingLists = React.useCallback(async () => {
    const meetingsBase = commonDepartmentId
      ? `/meetings?department_id=${encodeURIComponent(commonDepartmentId)}`
      : "/meetings?include_all_departments=true"
    const [externalRes, internalRes] = await Promise.all([
      apiFetch(`${meetingsBase}&meeting_type=external`),
      apiFetch(`${meetingsBase}&meeting_type=internal`),
    ])
    let refreshedExternalMeetings = externalMeetings
    if (externalRes?.ok) {
      const meetings = (await externalRes.json()) as Meeting[]
      refreshedExternalMeetings = meetings
      setExternalMeetings(meetings)
      syncCommonMeetingBucket(
        "external",
        meetings.filter((meeting) => meeting.calendar_sync_status !== "cancelled")
      )
    }
    if (internalRes?.ok) {
      const meetings = (await internalRes.json()) as Meeting[]
      setInternalMeetings(meetings)
      syncCommonMeetingBucket("internal", meetings, refreshedExternalMeetings)
    }
    COMMON_VIEW_CACHE.clear()
  }, [apiFetch, commonDepartmentId, externalMeetings, syncCommonMeetingBucket])

  React.useEffect(() => {
    reloadMeetingListsRef.current = reloadMeetingLists
  }, [reloadMeetingLists])

  const syncAndReloadExternalMeetings = React.useCallback(async (showFeedback = false) => {
    setSyncingExternalCalendar(true)
    try {
      const syncRes = await apiFetch("/meetings/sync-microsoft-calendar", { method: "POST" })
      if (!syncRes?.ok) {
        if (showFeedback) {
          const detail = await syncRes
            ?.json()
            .then((body) => (typeof body?.detail === "string" ? body.detail : null))
            .catch(() => null)
          toast.error(detail || "Microsoft Calendar sync failed.")
        }
        return
      }
      await reloadMeetingLists()
      if (showFeedback) {
        toast.success("Microsoft Calendar synchronized.")
      }
    } catch (error) {
      console.error("Microsoft Calendar sync failed", error)
      if (showFeedback) toast.error("Microsoft Calendar sync failed.")
    } finally {
      setSyncingExternalCalendar(false)
    }
  }, [apiFetch, reloadMeetingLists])

  React.useEffect(() => {
    if (!externalMeetingsOpen) return
    // The backend scheduler keeps Microsoft Calendar synchronized. Opening the
    // panel should only read persisted meetings instead of starting another
    // potentially long-running calendar import.
    void reloadMeetingListsRef.current()
  }, [externalMeetingsOpen])

  React.useEffect(() => {
    if (!internalMeetingsOpen) return
    const run = async () => {
      const [internalRes, externalRes] = await Promise.all([
        apiFetch("/meetings?include_all_departments=true&meeting_type=internal"),
        apiFetch("/meetings?include_all_departments=true&meeting_type=external"),
      ])
      if (internalRes?.ok) {
        setInternalMeetings((await internalRes.json()) as Meeting[])
      }
      if (externalRes?.ok) {
        setExternalMeetings((await externalRes.json()) as Meeting[])
      }
    }
    void run()
  }, [internalMeetingsOpen, apiFetch])

  // Filter helpers
  const inSelectedDates = (dateStr: string) => !selectedDates.size || selectedDates.has(dateStr)
  const leaveCovers = (leave: LeaveItem, dateStr: string) => {
    return dateStr >= leave.startDate && dateStr <= leave.endDate
  }
  const isDateFullyCovered = (dateStr: string) => {
    const activeUserIds = users.filter((u) => u.is_active).map((u) => u.id)
    if (!activeUserIds.length) return false
    const coveredUsers = new Set(
      commonData.leave
        .filter((x) => x.userId && leaveCovers(x, dateStr))
        .map((x) => x.userId as string)
    )
    return coveredUsers.size >= activeUserIds.length
  }
  const canReorderFastTask = React.useCallback(
    (entry: FastTaskEntry | SwimlaneCell) =>
      Boolean(entry.taskId && entry.userId && !entry.isDone && (isAdmin || isManager || entry.userId === userId)),
    [isAdmin, isManager, userId]
  )
  const applyFastTaskOrderUpdate = React.useCallback((orderMap: Map<string, number>) => {
    if (!orderMap.size) return
    COMMON_VIEW_CACHE.clear()
    const applyOrder = <T extends FastTaskItemMeta>(items: T[]) =>
      items.map((item) =>
        item.taskId && orderMap.has(item.taskId)
          ? { ...item, fastTaskOrder: orderMap.get(item.taskId) ?? item.fastTaskOrder }
          : item
      )
    setCommonData((prev) => ({
      ...prev,
      blocked: applyOrder(prev.blocked),
      oneH: applyOrder(prev.oneH),
      personal: applyOrder(prev.personal),
      r1: applyOrder(prev.r1),
    }))
  }, [])
  const moveFastTaskEntry = React.useCallback(
    async (
      entries: Array<FastTaskEntry | SwimlaneCell>,
      entry: FastTaskEntry | SwimlaneCell,
      direction: "up" | "down"
    ) => {
      if (!entry.taskId || !entry.userId || !canReorderFastTask(entry)) return
      const entryDate = getFastTaskEntryDate(entry)
      const peerEntries = entries.filter(
        (item): item is FastTaskEntry | SwimlaneCell =>
          Boolean(item.taskId) &&
          item.userId === entry.userId &&
          !item.isDone &&
          getFastTaskEntryDate(item) === entryDate
      )
      const currentIndex = peerEntries.findIndex((item) => item.taskId === entry.taskId)
      if (currentIndex < 0) return
      const targetIndex = direction === "up" ? currentIndex - 1 : currentIndex + 1
      if (targetIndex < 0 || targetIndex >= peerEntries.length) return

      const nextPeers = [...peerEntries]
      ;[nextPeers[currentIndex], nextPeers[targetIndex]] = [nextPeers[targetIndex], nextPeers[currentIndex]]

      setReorderingTaskId(entry.taskId)
      try {
        const res = await apiFetch("/tasks/fast-order", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user_id: entry.userId,
            ordered_task_ids: nextPeers.map((item) => item.taskId),
          }),
        })
        if (!res.ok) {
          let detail = "Failed to reorder tasks."
          try {
            const data = (await res.json()) as { detail?: string }
            if (data?.detail) detail = data.detail
          } catch {
            // Ignore non-JSON error payloads.
          }
          toast.error(detail)
          return
        }

        applyFastTaskOrderUpdate(
          new Map(nextPeers.map((item, index) => [item.taskId as string, index + 1]))
        )
      } catch (err) {
        console.error("Failed to reorder tasks", err)
        toast.error("Failed to reorder tasks.")
      } finally {
        setReorderingTaskId((current) => (current === entry.taskId ? null : current))
      }
    },
    [apiFetch, applyFastTaskOrderUpdate, canReorderFastTask]
  )
  const renderFastTaskReorderControls = React.useCallback(
    (entries: Array<FastTaskEntry | SwimlaneCell>, entry: FastTaskEntry | SwimlaneCell) => {
      if (!entry.taskId || !entry.userId || !canReorderFastTask(entry)) return null
      const entryDate = getFastTaskEntryDate(entry)
      const peerEntries = entries.filter(
        (item): item is FastTaskEntry | SwimlaneCell =>
          Boolean(item.taskId) &&
          item.userId === entry.userId &&
          !item.isDone &&
          getFastTaskEntryDate(item) === entryDate
      )
      const currentIndex = peerEntries.findIndex((item) => item.taskId === entry.taskId)
      if (currentIndex < 0) return null
      const isBusy = reorderingTaskId === entry.taskId
      const canMoveUp = currentIndex > 0 && !isBusy
      const canMoveDown = currentIndex < peerEntries.length - 1 && !isBusy
      return (
        <div className="fast-task-order-controls">
          <button
            type="button"
            className="fast-task-order-btn"
            disabled={!canMoveUp}
            onClick={() => void moveFastTaskEntry(entries, entry, "up")}
            aria-label="Move left"
            title="Move left"
          >
            ←
          </button>
          <button
            type="button"
            className="fast-task-order-btn"
            disabled={!canMoveDown}
            onClick={() => void moveFastTaskEntry(entries, entry, "down")}
            aria-label="Move right"
            title="Move right"
          >
            →
          </button>
        </div>
      )
    },
    [canReorderFastTask, moveFastTaskEntry, reorderingTaskId]
  )
  const renderOneHReportSlotControl = React.useCallback(
    (entry: OneHItem | R1Item | SwimlaneCell) => {
      return (
        <span className="oneh-slot-indicator" title="Report time">
          {getOneHReportSlotLabel(entry.oneHReportSlot)}
        </span>
      )
    },
    []
  )
  const updateOneHMarker = React.useCallback(
    async (entry: OneHItem | SwimlaneCell, oneHMarker: OneHMarker | null) => {
      if (!entry.taskId || savingOneHMarkerTaskId) return
      const previousMarker = entry.oneHMarker || null
      const previousMarkerByGa = Boolean(entry.oneHMarkerByGa)
      const applyMarker = (marker: OneHMarker | null, markerByGa: boolean) => {
        const updateItems = <T extends FastTaskItemMeta>(items: T[]) =>
          items.map((item) => item.taskId === entry.taskId
            ? { ...item, oneHMarker: marker, oneHMarkerByGa: markerByGa }
            : item)
        setCommonData((current) => ({
          ...current,
          blocked: updateItems(current.blocked),
          oneH: updateItems(current.oneH),
          personal: updateItems(current.personal),
          r1: updateItems(current.r1),
        }))
      }

      setSavingOneHMarkerTaskId(entry.taskId)
      applyMarker(oneHMarker, Boolean(oneHMarker && user?.email?.trim().toLowerCase() === "ga@primexeu.com"))
      try {
        const response = await apiFetch(`/tasks/${entry.taskId}/one-h-marker`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ one_h_marker: oneHMarker }),
        })
        if (!response?.ok) {
          const detail = await response?.json().catch(() => null)
          throw new Error(typeof detail?.detail === "string" ? detail.detail : "Failed to update the 1H marker.")
        }
        const updated = await response.json() as { one_h_marker_by_ga?: boolean }
        applyMarker(oneHMarker, Boolean(updated.one_h_marker_by_ga))
        COMMON_VIEW_CACHE.clear()
        const weekStartIso = `${weekStart.getFullYear()}-${String(weekStart.getMonth() + 1).padStart(2, "0")}-${String(weekStart.getDate()).padStart(2, "0")}`
        await fetchCommonViewStage(weekStartIso, ["tasks"])
      } catch (error) {
        applyMarker(previousMarker, previousMarkerByGa)
        toast.error(error instanceof Error ? error.message : "Failed to update the 1H marker.")
      } finally {
        setSavingOneHMarkerTaskId(null)
      }
    },
    [apiFetch, fetchCommonViewStage, savingOneHMarkerTaskId, user?.email, weekStart]
  )
  const renderOneHMarkerControl = React.useCallback(
    (entry: OneHItem | SwimlaneCell) => (
      <TaskOneHMarkerEditor
        taskId={entry.taskId}
        marker={entry.oneHMarker}
        markerByGa={entry.oneHMarkerByGa}
        markerComment={entry.oneHMarkerComment}
        className="oneh-marker-select"
      />
    ),
    []
  )

  // Filtered data
  const filtered = React.useMemo(() => {
    const datesToUse = selectedDates.size ? Array.from(selectedDates) : weekISOs
    const activeUserIds = users.filter((u) => u.is_active).map((u) => u.id)
    const fullyCoveredDates = new Set<string>()
    if (activeUserIds.length) {
      for (const dateStr of datesToUse) {
        const coveredUsers = new Set(
          commonData.leave
            .filter((x) => x.userId && leaveCovers(x, dateStr))
            .map((x) => x.userId as string)
        )
        if (coveredUsers.size >= activeUserIds.length) {
          fullyCoveredDates.add(dateStr)
        }
      }
    }

    // Build hidden-users-per-date map for full-day PV/Feste or full-day Mungese.
    // A Mungese is considered full-day when its time range covers the whole work
    // day (from <= 08:00 and to >= 16:30); this also matches the backend default
    // of 08:00-23:00 used when no explicit range is stored.
    const hiddenUsersByDate = new Map<string, Set<string>>()
    const addHidden = (dateStr: string, uid: string | undefined | null) => {
      if (!uid) return
      let set = hiddenUsersByDate.get(dateStr)
      if (!set) {
        set = new Set<string>()
        hiddenUsersByDate.set(dateStr, set)
      }
      set.add(uid)
    }
    for (const lv of commonData.leave) {
      if (!lv.fullDay || !lv.userId) continue
      for (const d of datesToUse) {
        if (d >= lv.startDate && d <= lv.endDate) {
          addHidden(d, lv.userId)
        }
      }
    }
    for (const ab of commonData.absent) {
      if (!ab.userId) continue
      if (ab.from <= "08:00" && ab.to >= "16:30") {
        addHidden(ab.date, ab.userId)
      }
    }

    // Resolve user display names (full_name / username / email) to user IDs so
    // we can hide items that only carry a person name (problems, feedback, and
    // the assignee/owner lists on priority/meetings/bz).
    const nameToUserId = new Map<string, string>()
    for (const u of users) {
      if (!u.id) continue
      if (u.full_name) nameToUserId.set(u.full_name.trim().toLowerCase(), u.id)
      if (u.username) nameToUserId.set(u.username.trim().toLowerCase(), u.id)
      if (u.email) nameToUserId.set(u.email.trim().toLowerCase(), u.id)
    }
    const resolveUserId = (name: string | undefined | null): string | null => {
      if (!name) return null
      return nameToUserId.get(name.trim().toLowerCase()) || null
    }
    const selectedCommonUser = selectedCommonUserId === "__all__"
      ? null
      : users.find((u) => u.id === selectedCommonUserId) || null
    const selectedCommonUserNames = new Set(
      selectedCommonUser
        ? [selectedCommonUser.full_name, selectedCommonUser.username, selectedCommonUser.email]
            .map((name) => (name || "").trim().toLowerCase())
            .filter(Boolean)
        : []
    )
    const hasCommonUserFilter = Boolean(selectedCommonUser)
    const matchesSelectedUserId = (uid?: string | null) =>
      !hasCommonUserFilter || uid === selectedCommonUserId
    const matchesSelectedUserName = (name?: string | null) =>
      !hasCommonUserFilter || selectedCommonUserNames.has((name || "").trim().toLowerCase())
    const selectedAssignees = (names?: string[]) => {
      const source = names || []
      if (!hasCommonUserFilter) return source
      return source.filter((name) => matchesSelectedUserName(name))
    }
    const hasSelectedAssignee = (names?: string[]) =>
      !hasCommonUserFilter || selectedAssignees(names).length > 0
    const matchesSelectedUserEntry = (entry: {
      userId?: string | null
      person?: string | null
      owner?: string | null
      assignees?: string[]
      isAllUsers?: boolean
    }) => {
      if (!hasCommonUserFilter) return true
      if (entry.isAllUsers) return true
      return (
        matchesSelectedUserId(entry.userId) ||
        matchesSelectedUserName(entry.person) ||
        matchesSelectedUserName(entry.owner) ||
        hasSelectedAssignee(entry.assignees)
      )
    }
    const narrowAssigneesForSelectedUser = <T extends { assignees?: string[] }>(entry: T): T => {
      if (!hasCommonUserFilter || !entry.assignees?.length) return entry
      const assignees = selectedAssignees(entry.assignees)
      return assignees.length ? { ...entry, assignees } : entry
    }
    const isUserHiddenOn = (dateStr: string, uid: string | null | undefined): boolean => {
      if (!uid) return false
      const set = hiddenUsersByDate.get(dateStr)
      return !!set && set.has(uid)
    }
    const isNameHiddenOn = (dateStr: string, name: string | undefined | null): boolean => {
      const uid = resolveUserId(name)
      return isUserHiddenOn(dateStr, uid)
    }
    const matchesColorFilter = (entry: FastTaskEntry) =>
      colorFilter === "all" || getCommonTaskColor(entry) === colorFilter
    const matchesOneHMarkerFilter = (entry: FastTaskEntry) => {
      const marker = entry.oneHMarker || null
      if (oneHMarkerFilters.size === 0) return true
      if (marker === null) return oneHMarkerFilters.has("none")
      return oneHMarkerFilters.has(marker)
    }
    const matchesKaGentFilter = (entry: FastTaskEntry, includePersonalGroup = false) => {
      if (!kaGentFilterActive) return true
      if (entry.oneHMarker === "KA" || entry.oneHMarker === "GENT") return true
      if (
        isWaitingConfirmationTask(entry) &&
        (entry.confirmationOwner === "KA" || entry.confirmationOwner === "GENT")
      ) return true
      if (!includePersonalGroup || entry.isPersonalTask === false) return false
      const personalGroup = getPersonalTaskGroup(entry)
      return personalGroup === "KA" || personalGroup === "GENT"
    }
    const matchesTaskFocusFilter = (entry: FastTaskEntry) => {
      if (taskFocusFilter === "new") {
        const category = getCommonTaskNewCategory(entry)
        return Boolean(category && newTaskCategoryFilters.has(category))
      }
      if (taskFocusFilter === "eightAm") return hasEightAmIndicator(entry.title, entry.isSystemTask)
      if (taskFocusFilter === "deadline") return Boolean(entry.isDeadlineImportant)
      if (taskFocusFilter === "startToday") return isCommonTaskStartToday(entry, entry.date)
      return true
    }

    const late = commonData.late
      .filter((x) => inSelectedDates(x.date) && !fullyCoveredDates.has(x.date))
      .filter((x) => matchesSelectedUserEntry(x))
    const absent = commonData.absent
      .filter((x) => inSelectedDates(x.date) && !fullyCoveredDates.has(x.date))
      .filter((x) => matchesSelectedUserEntry(x))
    const externalHoliday = commonData.externalHoliday.filter((x) => inSelectedDates(x.date))
    const leave = commonData.leave.filter((x) => {
      if (!matchesSelectedUserEntry(x)) return false
      const visibleDates = datesToUse.filter((d) => d >= x.startDate && d <= x.endDate)
      if (!visibleDates.length) return false
      return visibleDates.some((d) => !fullyCoveredDates.has(d))
    })
    const blocked = commonData.blocked
      .filter((x) => inSelectedDates(x.date) && !fullyCoveredDates.has(x.date))
      .filter((x) => matchesSelectedUserEntry(x))
      .filter((x) => !isUserHiddenOn(x.date, x.userId))
      .filter(matchesTaskFocusFilter)
      .filter(matchesColorFilter)
      .filter(matchesOneHMarkerFilter)
      .filter((x) => matchesKaGentFilter(x))
      .map(narrowAssigneesForSelectedUser)
    const oneH = commonData.oneH
      .filter((x) => inSelectedDates(x.date) && !fullyCoveredDates.has(x.date))
      .filter((x) => matchesSelectedUserEntry(x))
      .filter((x) => !isUserHiddenOn(x.date, x.userId))
      .filter(matchesTaskFocusFilter)
      .filter(matchesColorFilter)
      .filter(matchesOneHMarkerFilter)
      .filter((x) => matchesKaGentFilter(x))
      .map(narrowAssigneesForSelectedUser)
    const personal = commonData.personal
      .filter((x) => inSelectedDates(x.date) && !fullyCoveredDates.has(x.date))
      .filter((x) => matchesSelectedUserEntry(x))
      .filter((x) => !isUserHiddenOn(x.date, x.userId))
      .filter(matchesTaskFocusFilter)
      .filter(matchesColorFilter)
      .filter(matchesOneHMarkerFilter)
      .filter((x) => matchesKaGentFilter(x, true))
      .map(narrowAssigneesForSelectedUser)
    const r1 = commonData.r1
      .filter((x) => inSelectedDates(x.date) && !fullyCoveredDates.has(x.date))
      .filter((x) => matchesSelectedUserEntry(x))
      .filter((x) => !isUserHiddenOn(x.date, x.userId))
      .filter(matchesTaskFocusFilter)
      .filter(matchesColorFilter)
      .filter(matchesOneHMarkerFilter)
      .filter((x) => matchesKaGentFilter(x))
      .map(narrowAssigneesForSelectedUser)
    const external = commonData.external
      .filter((x) => inSelectedDates(x.date) && !fullyCoveredDates.has(x.date))
      .flatMap((x) => {
        if (!matchesSelectedUserEntry(x)) return []
        const hiddenSet = hiddenUsersByDate.get(x.date)
        const selectedAssigneeList = selectedAssignees(x.assignees)
        const next = hasCommonUserFilter && selectedAssigneeList.length
          ? { ...x, assignees: selectedAssigneeList }
          : x
        if (!hiddenSet || hiddenSet.size === 0) return [next]
        const ownerHidden = isNameHiddenOn(x.date, x.owner)
        const filteredAssignees = (next.assignees || []).filter((n) => !isNameHiddenOn(x.date, n))
        if (ownerHidden && filteredAssignees.length === 0) return []
        if (filteredAssignees.length === (next.assignees?.length || 0)) return [next]
        return [{ ...next, assignees: filteredAssignees }]
      })
    const internal = commonData.internal
      .filter((x) => inSelectedDates(x.date) && !fullyCoveredDates.has(x.date))
      .flatMap((x) => {
        if (!matchesSelectedUserEntry(x)) return []
        const hiddenSet = hiddenUsersByDate.get(x.date)
        const selectedAssigneeList = selectedAssignees(x.assignees)
        const next = hasCommonUserFilter && selectedAssigneeList.length
          ? { ...x, assignees: selectedAssigneeList }
          : x
        if (!hiddenSet || hiddenSet.size === 0) return [next]
        const ownerHidden = isNameHiddenOn(x.date, x.owner)
        const filteredAssignees = (next.assignees || []).filter((n) => !isNameHiddenOn(x.date, n))
        if (ownerHidden && filteredAssignees.length === 0) return []
        if (filteredAssignees.length === (next.assignees?.length || 0)) return [next]
        return [{ ...next, assignees: filteredAssignees }]
      })
    const problems = commonData.problems
      .filter((x) => x.everyday || (inSelectedDates(x.date) && !fullyCoveredDates.has(x.date)))
      .filter((x) => matchesSelectedUserEntry(x))
      .filter((x) => x.everyday || !isNameHiddenOn(x.date, x.person))
    const feedback = commonData.feedback
      .filter((x) => x.everyday || (inSelectedDates(x.date) && !fullyCoveredDates.has(x.date)))
      .filter((x) => matchesSelectedUserEntry(x))
      .filter((x) => x.everyday || !isNameHiddenOn(x.date, x.person))
    const bz = commonData.bz
      .filter((x) => inSelectedDates(x.date) && !fullyCoveredDates.has(x.date))
      .flatMap((x) => {
        if (!matchesSelectedUserEntry(x)) return []
        const hiddenSet = hiddenUsersByDate.get(x.date)
        const selectedAssigneeList = selectedAssignees(x.assignees)
        const next = hasCommonUserFilter && selectedAssigneeList.length
          ? { ...x, assignees: selectedAssigneeList }
          : x
        if (!hiddenSet || hiddenSet.size === 0) return [next]
        const filteredAssignees = (next.assignees || []).filter((n) => !isNameHiddenOn(x.date, n))
        if (filteredAssignees.length === 0) return []
        if (filteredAssignees.length === (next.assignees?.length || 0)) return [next]
        return [{ ...next, assignees: filteredAssignees }]
      })
    const priority = commonData.priority.filter((p) =>
      selectedDates.size ? Array.from(selectedDates).includes(p.date) : true
    )

    const filteredPriority = priority
      .filter((p) => !fullyCoveredDates.has(p.date))
      .filter((p) => matchesSelectedUserEntry(p))
      .flatMap((p) => {
        const hiddenSet = hiddenUsersByDate.get(p.date)
        const selectedAssigneeList = selectedAssignees(p.assignees)
        const next = hasCommonUserFilter && selectedAssigneeList.length
          ? { ...p, assignees: selectedAssigneeList }
          : p
        if (!hiddenSet || hiddenSet.size === 0) return [next]
        const filteredAssignees = (next.assignees || []).filter((n) => !isNameHiddenOn(p.date, n))
        if (filteredAssignees.length === 0) return []
        if (filteredAssignees.length === (next.assignees?.length || 0)) return [next]
        return [{ ...next, assignees: filteredAssignees }]
      })

    return {
      late,
      absent,
      leave,
      externalHoliday,
      blocked,
      oneH,
      personal,
      external,
      internal,
      r1,
      problems,
      feedback,
      bz,
      priority: filteredPriority,
      fullyCoveredDates,
      hiddenUsersByDate,
    }
  }, [colorFilter, commonData, kaGentFilterActive, newTaskCategoryFilters, oneHMarkerFilters, selectedCommonUserId, selectedDates, taskFocusFilter, users, weekISOs])

  const allUsersLeaveByDate = React.useMemo(() => {
    const datesToUse = selectedDates.size ? Array.from(selectedDates) : weekISOs
    const byDate = new Map<string, LeaveItem>()
    for (const iso of datesToUse) {
      const matching = commonData.leave.find((x) => x.isAllUsers && leaveCovers(x, iso))
      if (!matching) continue
      byDate.set(iso, {
        ...matching,
        person: ALL_USERS_INITIALS,
        entryId: undefined,
        startDate: iso,
        endDate: iso,
      })
    }
    return byDate
  }, [commonData.leave, selectedDates, weekISOs])

  // Common people for priority (from users)
  const commonPeople = React.useMemo(() => {
    return users
      .filter((u) => u.role !== "STAFF" || u.department_id)
      .slice(0, 4)
      .map((u) => u.full_name || u.username || "Unknown")
  }, [users])
  const commonUserFilterOptions = React.useMemo(() => {
    return users
      .filter((u) => u.id)
      .map((u) => ({
        id: u.id,
        label: u.full_name || u.username || u.email || "Unknown",
        isActive: u.is_active,
      }))
      .sort((a, b) => {
        if (a.isActive !== b.isActive) return a.isActive ? -1 : 1
        return a.label.localeCompare(b.label)
      })
  }, [users])
  const selectedCommonUserLabel = React.useMemo(() => {
    if (selectedCommonUserId === "__all__") return "All users"
    return commonUserFilterOptions.find((option) => option.id === selectedCommonUserId)?.label || "All users"
  }, [commonUserFilterOptions, selectedCommonUserId])
  const oneHMarkerFilterLabel = React.useMemo(() => {
    if (oneHMarkerFilters.size === 0) return "All"
    const hasEverySymbol = ONE_H_MARKER_VALUES.every((marker) => oneHMarkerFilters.has(marker))
    if (hasEverySymbol && !oneHMarkerFilters.has("none")) return "All with symbols"
    if (oneHMarkerFilters.size === 1) {
      const selected = Array.from(oneHMarkerFilters)[0]
      if (selected === "none") return "No symbol"
      return getOneHMarkerLabel(selected)
    }
    return `${oneHMarkerFilters.size} selected`
  }, [oneHMarkerFilters])
  const filteredDiamondItems = React.useMemo(
    () =>
      diamondItems.filter(
        (item) =>
          (selectedCommonUserId === "__all__" || item.userId === selectedCommonUserId) &&
          (selectedDates.size === 0 || selectedDates.has(item.date))
      ),
    [diamondItems, selectedCommonUserId, selectedDates]
  )
  const diamondReviewByTaskUser = React.useMemo(() => {
    const map = new Map<string, TaskReview>()
    diamondItems.forEach((item) => {
      if (item.taskId) map.set(`${item.taskId}:${item.userId}`, item.review)
    })
    return map
  }, [diamondItems])
  const openCommonTaskReview = React.useCallback((cell: SwimlaneCell) => {
    if (!cell.taskId || !cell.userId || !cell.isDone) return
    const reviewee = users.find((entry) => entry.id === cell.userId)
    const revieweeName =
      reviewee?.full_name ||
      reviewee?.username ||
      reviewee?.email ||
      cell.assignees?.[0] ||
      "Unknown"
    const completedAt =
      cell.completedAt ||
      (cell.entryDate ? `${cell.entryDate}T00:00:00.000Z` : new Date().toISOString())

    setCommonReviewRow({
      task_id: cell.taskId,
      task_title: cell.title,
      reviewee_user_id: cell.userId,
      reviewee_name: revieweeName,
      completed_at: completedAt,
      due_date: cell.dueDate || null,
      is_late: false,
      review: diamondReviewByTaskUser.get(`${cell.taskId}:${cell.userId}`) || null,
    })
    setCommonReviewOpen(true)
  }, [diamondReviewByTaskUser, users])
  const handleCommonReviewSaved = React.useCallback(async () => {
    await loadDiamonds()
  }, [loadDiamonds])

  const isMultiDate = selectedDates.size > 1

  const sortByDate = React.useCallback(
    <T,>(
      items: T[],
      getDateKey: (item: T) => string,
      getTitle: (item: T) => string
    ) => {
      return [...items].sort((a, b) => {
        const aDate = getDateKey(a)
        const bDate = getDateKey(b)
        if (aDate !== bDate) return aDate.localeCompare(bDate)
        return getTitle(a).localeCompare(getTitle(b))
      })
    },
    []
  )
  const sortByTime = React.useCallback(
    <T,>(
      items: T[],
      getTimeKey: (item: T) => string | null | undefined,
      getTitle: (item: T) => string
    ) => {
      return [...items].sort((a, b) => {
        const aMinutes = parseTimeToMinutes(getTimeKey(a))
        const bMinutes = parseTimeToMinutes(getTimeKey(b))
        if (aMinutes === null && bMinutes === null) return getTitle(a).localeCompare(getTitle(b))
        if (aMinutes === null) return 1
        if (bMinutes === null) return -1
        if (aMinutes !== bMinutes) return aMinutes - bMinutes
        return getTitle(a).localeCompare(getTitle(b))
      })
    },
    [parseTimeToMinutes]
  )
  const sortByDateTime = React.useCallback(
    <T,>(
      items: T[],
      getDateKey: (item: T) => string,
      getTimeKey: (item: T) => string | null | undefined,
      getTitle: (item: T) => string
    ) => {
      return [...items].sort((a, b) => {
        const aDate = getDateKey(a)
        const bDate = getDateKey(b)
        if (aDate !== bDate) return aDate.localeCompare(bDate)
        const aMinutes = parseTimeToMinutes(getTimeKey(a))
        const bMinutes = parseTimeToMinutes(getTimeKey(b))
        if (aMinutes === null && bMinutes === null) return getTitle(a).localeCompare(getTitle(b))
        if (aMinutes === null) return 1
        if (bMinutes === null) return -1
        if (aMinutes !== bMinutes) return aMinutes - bMinutes
        return getTitle(a).localeCompare(getTitle(b))
      })
    },
    [parseTimeToMinutes]
  )

  // Handlers
  const toggleDay = (iso: string) => {
    setSelectedDates((prev) => {
      const s = new Set(prev)
      if (!multiMode) {
        s.clear()
      }
      if (s.has(iso)) {
        if (s.size === 1) return s
        s.delete(iso)
      } else {
        s.add(iso)
      }
      return s
    })
  }

  const setTypeFilter = (type: CommonType | "all") => {
    if (type === "all") {
      setTypeFilters(new Set())
    } else if (!typeMultiMode) {
      setTypeFilters(new Set([type]))
    } else {
      setTypeFilters((prev) => {
        const s = new Set(prev)
        if (s.has(type)) {
          s.delete(type)
        } else {
          s.add(type)
        }
        return s
      })
    }
  }

  const toggleOneHMarkerFilter = (filter: OneHMarkerFilter) => {
    setOneHMarkerFilters((previous) => {
      const next = new Set(previous)
      if (next.has(filter)) next.delete(filter)
      else next.add(filter)
      return next
    })
  }

  const toggleAllOneHMarkerFilters = () => {
    setOneHMarkerFilters((previous) => {
      const next = new Set(previous)
      const hasEverySymbol = ONE_H_MARKER_VALUES.every((marker) => next.has(marker))
      for (const marker of ONE_H_MARKER_VALUES) {
        if (hasEverySymbol) next.delete(marker)
        else next.add(marker)
      }
      return next
    })
  }

  const selectAll = () => {
    if (!multiMode) {
      setMultiMode(true)
    }
    setSelectedDates(new Set(weekISOs))
  }

  const selectWeek = (weekStartDate: Date) => {
    const targetWeekIso = toISODate(weekStartDate)
    if (toISODate(weekStart) !== targetWeekIso) {
      setDataLoaded(false)
      setWeekStart(weekStartDate)
    }
    setSelectedDates(new Set(getWeekdays(weekStartDate).map(toISODate)))
    setMultiMode(true)
    resetSwimlaneTitleRowsOpen()
  }

  const selectToday = () => {
    const today = new Date()
    const todayMonday = getMonday(today)
    if (toISODate(weekStart) !== toISODate(todayMonday)) {
      setDataLoaded(false)
      setWeekStart(todayMonday)
    }
    setSelectedDates(new Set([toISODate(today)]))
    setMultiMode(false)
    resetSwimlaneTitleRowsOpen()
  }

  const resetWeekTablePrintFit = React.useCallback(() => {
    const root = weekTablePrintRef.current
    if (!root) return
    root.style.removeProperty("--week-table-print-scale")
  }, [])

  const resetSingleDayPrintFit = React.useCallback(() => {
    singleDayPrintRef.current?.style.removeProperty("--single-day-print-scale")
  }, [])

  const getPrintOrientation = React.useCallback((): "portrait" | "landscape" => {
    const isPortrait =
      window.matchMedia("(orientation: portrait)").matches || window.innerHeight > window.innerWidth
    return isPortrait ? "portrait" : "landscape"
  }, [])

  const computePrintMetrics = React.useCallback((orientation: "portrait" | "landscape") => {
    const dpi = 96
    const marginsIn = { left: 0.35, right: 0.35, top: 0.45, bottom: 0.51 }
    const letterIn = orientation === "portrait" ? { width: 8.5, height: 11 } : { width: 11, height: 8.5 }
    const a4In = orientation === "portrait" ? { width: 8.27, height: 11.69 } : { width: 11.69, height: 8.27 }
    const printableWidthIn = Math.min(
      letterIn.width - marginsIn.left - marginsIn.right,
      a4In.width - marginsIn.left - marginsIn.right
    )
    const printableHeightIn = Math.min(
      letterIn.height - marginsIn.top - marginsIn.bottom,
      a4In.height - marginsIn.top - marginsIn.bottom
    )
    return {
      printableWidthPx: Math.max(1, Math.floor(printableWidthIn * dpi)),
      printableHeightPx: Math.max(1, Math.floor(printableHeightIn * dpi)),
      footerReservePx: 28,
    }
  }, [])

  const calculateAllDaysPortraitPages = React.useCallback(() => {
    const { printableHeightPx, footerReservePx } = computePrintMetrics("portrait")
    const availableHeightPx = Math.max(1, printableHeightPx - footerReservePx)
    const contentHeight = Math.max(
      weekTablePrintContentRef.current?.scrollHeight || 0,
      weekTablePrintRef.current?.scrollHeight || 0,
      document.body.scrollHeight
    )
    return Math.max(1, Math.ceil(contentHeight / availableHeightPx))
  }, [computePrintMetrics])

  const applyWeekTablePrintFit = React.useCallback(() => {
    if (!allDaysSelected) {
      resetWeekTablePrintFit()
      return
    }
    const root = weekTablePrintRef.current
    const content = weekTablePrintContentRef.current
    if (!root || !content) return

    const orientation = getPrintOrientation()
    if (orientation === "portrait") {
      root.style.setProperty("--week-table-print-scale", "1")
      return
    }

    root.style.setProperty("--week-table-print-scale", "1")

    const { printableWidthPx, printableHeightPx, footerReservePx } = computePrintMetrics("landscape")
    const availableHeightPx = Math.max(1, printableHeightPx - footerReservePx)

    const naturalWidth = content.scrollWidth
    const naturalHeight = content.scrollHeight
    if (!naturalWidth || !naturalHeight) {
      return
    }

    const widthFit = printableWidthPx / naturalWidth
    const heightFit = availableHeightPx / naturalHeight
    const fitScale = Math.min(1, widthFit, heightFit)
    const safeScale = Number.isFinite(fitScale) && fitScale > 0 ? fitScale : 1

    root.style.setProperty("--week-table-print-scale", safeScale.toString())
  }, [allDaysSelected, computePrintMetrics, getPrintOrientation, resetWeekTablePrintFit])

  const applySingleDayPrintFit = React.useCallback(() => {
    const root = singleDayPrintRef.current
    const content = singleDayPrintContentRef.current
    if (!root || !content) return

    root.style.setProperty("--single-day-print-scale", "1")
    const { printableWidthPx, printableHeightPx, footerReservePx } = computePrintMetrics("landscape")
    const availableHeightPx = Math.max(1, printableHeightPx - footerReservePx)
    const naturalWidth = content.scrollWidth
    const naturalHeight = content.scrollHeight
    if (!naturalWidth || !naturalHeight) return

    const fitScale = Math.min(1, printableWidthPx / naturalWidth, availableHeightPx / naturalHeight)
    const safeScale = Number.isFinite(fitScale) && fitScale > 0 ? fitScale : 1
    root.style.setProperty("--single-day-print-scale", safeScale.toString())
  }, [computePrintMetrics])

  React.useEffect(() => {
    const syncPrintHintOrientation = () => {
      setPrintOrientationHint(getPrintOrientation())
    }
    syncPrintHintOrientation()
    const orientationMedia = window.matchMedia("(orientation: portrait)")
    window.addEventListener("resize", syncPrintHintOrientation)
    orientationMedia.addEventListener("change", syncPrintHintOrientation)
    return () => {
      window.removeEventListener("resize", syncPrintHintOrientation)
      orientationMedia.removeEventListener("change", syncPrintHintOrientation)
    }
  }, [getPrintOrientation])

  React.useEffect(() => {
    const handleResize = () => {
      if (!allDaysSelected) return
      if (!window.matchMedia("print").matches) return
      applyWeekTablePrintFit()
    }
    window.addEventListener("resize", handleResize)
    return () => {
      window.removeEventListener("resize", handleResize)
    }
  }, [allDaysSelected, applyWeekTablePrintFit])

  React.useEffect(() => {
    const orientationMedia = window.matchMedia("(orientation: portrait)")
    const handleOrientationChange = () => {
      if (!allDaysSelected) return
      if (!window.matchMedia("print").matches) return
      applyWeekTablePrintFit()
    }
    orientationMedia.addEventListener("change", handleOrientationChange)
    return () => {
      orientationMedia.removeEventListener("change", handleOrientationChange)
    }
  }, [allDaysSelected, applyWeekTablePrintFit])

  const handlePrintTomorrow = async () => {
    if (printingTomorrow) return

    // Open synchronously so browsers do not treat the report window as a popup.
    // The Common View itself is never changed while this data is being loaded.
    const printWindow = window.open("", "_blank")
    if (!printWindow) {
      toast.error("The browser blocked the print window. Please allow popups and try again.")
      return
    }

    printWindow.document.write("<!doctype html><title>Loading report…</title><p>Loading tomorrow's report…</p>")
    printWindow.document.close()
    setPrintingTomorrow(true)

    try {
      const deliveryDate = new Date()
      const targetDate = getNextWorkingDay(deliveryDate)
      const targetIso = toISODate(targetDate)
      const targetWeekStartIso = toISODate(getMonday(targetDate))
      const freezeParam = freezeOneHSlots ? "&freeze_one_h_slots=true" : ""
      const res = await apiFetch(
        `/common-view?week_start=${encodeURIComponent(targetWeekStartIso)}&include=tasks,meetings&include_all_departments=true${freezeParam}`
      )
      if (!res?.ok) {
        throw new Error(`Could not load tomorrow's report (${res?.status || "network error"}).`)
      }

      const payload = (await res.json()) as CommonViewPayload
      type PrintTask = FastTaskEntry & { weekly_planner_sort?: unknown; department_id?: string; user_id?: string }
      const normalizeTasks = (items: unknown[]) =>
        items
          .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
          .filter((item) => item.date === targetIso)
          .map(
            (item) =>
              ({
                ...item,
                title: String(item.title || ""),
                person: typeof item.person === "string" ? item.person : "",
                owner: typeof item.owner === "string" ? item.owner : "",
                date: String(item.date || ""),
                assignees: Array.isArray(item.assignees) ? item.assignees.filter((name): name is string => typeof name === "string") : [],
                taskId: typeof item.taskId === "string" ? item.taskId : typeof item.task_id === "string" ? item.task_id : undefined,
                userId: typeof item.userId === "string" ? item.userId : typeof item.user_id === "string" ? item.user_id : undefined,
                departmentId:
                  typeof item.departmentId === "string" ? item.departmentId : typeof item.department_id === "string" ? item.department_id : undefined,
                fastTaskOrder:
                  typeof item.fastTaskOrder === "number"
                    ? item.fastTaskOrder
                    : typeof item.fast_task_order === "number"
                      ? item.fast_task_order
                      : undefined,
                oneHReportSlot: normalizeOneHReportSlot(
                  typeof item.oneHReportSlot === "string"
                    ? item.oneHReportSlot
                    : typeof item.one_h_report_slot === "string"
                      ? item.one_h_report_slot
                      : undefined
                ),
                oneHMarker:
                  typeof item.oneHMarker === "string"
                    ? item.oneHMarker as OneHMarker
                    : typeof item.one_h_marker === "string"
                      ? item.one_h_marker as OneHMarker
                      : null,
                oneHMarkerByGa: Boolean(item.oneHMarkerByGa ?? item.one_h_marker_by_ga),
                oneHMarkerComment: item.oneHMarkerComment ?? item.one_h_marker_comment ?? null,
                isDeadlineImportant: Boolean(item.isDeadlineImportant ?? item.is_deadline_important),
                startDate:
                  typeof item.startDate === "string" ? item.startDate : typeof item.start_date === "string" ? item.start_date : undefined,
                dueDate:
                  typeof item.dueDate === "string" ? item.dueDate : typeof item.due_date === "string" ? item.due_date : undefined,
                createdAt:
                  typeof item.createdAt === "string" ? item.createdAt : typeof item.created_at === "string" ? item.created_at : undefined,
                status: typeof item.status === "string" ? item.status : undefined,
                isDone: Boolean(item.isDone),
                confirmationOwner:
                  item.confirmationOwner === "KA" || item.confirmationOwner === "GENT"
                    ? item.confirmationOwner
                    : item.confirmation_owner === "KA" || item.confirmation_owner === "GENT"
                      ? item.confirmation_owner
                      : null,
                isSystemTask: Boolean(item.isSystemTask ?? item.is_system_task),
                isPersonalTask:
                  typeof item.isPersonalTask === "boolean"
                    ? item.isPersonalTask
                    : typeof item.is_personal_task === "boolean"
                      ? item.is_personal_task
                      : true,
              }) as PrintTask
          )

      const normalizedPersonalTasks = normalizeTasks(payload.items.personal)
      const taskRows: Array<{ id: CommonType; label: string; items: PrintTask[] }> = [
        ...ONE_H_SLOT_ROWS.map((slot) => ({
          id: slot.id,
          label: slot.label,
          items: normalizeTasks(payload.items.oneH)
            .filter((item) => !isRoutedWaitingConfirmation(item))
            .filter((item) =>
              slot.slot === null
                ? !normalizeOneHReportSlot(item.oneHReportSlot)
                : normalizeOneHReportSlot(item.oneHReportSlot) === slot.slot
            ),
        })),
        {
          id: "blocked",
          label: "BLL",
          items: normalizeTasks(payload.items.blocked).filter((item) => !isRoutedWaitingConfirmation(item)),
        },
        {
          id: "r1",
          label: "R1=1H",
          items: normalizeTasks(payload.items.r1).filter((item) => !isRoutedWaitingConfirmation(item)),
        },
        ...PERSONAL_ROW_IDS.map((id) => ({
          id,
          label: `P: ${getPersonalRowGroup(id)}`,
          items: personalTasksForRow(normalizedPersonalTasks, id),
        })),
      ]

      const sortedTaskRows = taskRows.map((row) => ({
        ...row,
        items: mergePrintTaskEntries(row.id, sortTasksForReportPrint(row.items)),
      }))
      const meetingRows = ([
        { id: "external" as const, label: "TAK EXT", items: payload.items.external as unknown as Array<Record<string, unknown>> },
        { id: "internal" as const, label: "TAK INT", items: payload.items.internal as unknown as Array<Record<string, unknown>> },
      ] satisfies Array<{ id: CommonType; label: string; items: Array<Record<string, unknown>> }>).map((row) => ({
        ...row,
        items: row.items
          .filter((item) => item.date === targetIso)
          .sort((a, b) => String(a.time || "").localeCompare(String(b.time || "")) || String(a.title || "").localeCompare(String(b.title || ""))),
      }))

      const printTaskDatesHtml = (item: PrintTask) => {
        const startDate = normalizeCommonDateOnly(item.startDate || item.date)
        const dueDate = normalizeCommonDateOnly(item.dueDate)
        if (!startDate && !dueDate) return ""
        const chip = (value: string, due = false) => {
          const dueToday = due && value === targetIso
          const label = dueToday ? "SOT" : formatDateHuman(value)
          return `<span class="print-task-date${due ? " due" : ""}${dueToday ? " today" : ""}">${escapePrintHtml(label)}</span>`
        }
        const startToday = isCommonTaskStartToday(item, targetIso)
        return `<div class="print-task-dates">${startDate ? `<span class="print-task-start">${startToday ? '<span class="print-task-badge start-today">START SOT</span>' : ""}${chip(startDate)}</span>` : ""}${dueDate ? chip(dueDate, true) : ""}</div>`
      }

      const buildTableRows = (
        rows: Array<{ id: CommonType; label: string; items: Array<PrintTask | Record<string, unknown>> }>,
        isMeetingTable = false
      ) =>
        rows
          .map((row, rowIndex) => {
            const rowItems = row.items
            const chunks = Math.max(1, Math.ceil(rowItems.length / 6))
            const subtext = getCommonPrintRowSubtext(row.id)
            return Array.from({ length: chunks }, (_, chunkIndex) => {
              const cells = rowItems.slice(chunkIndex * 6, chunkIndex * 6 + 6)
              const itemCells = Array.from({ length: 6 }, (_, cellIndex) => {
                const item = cells[cellIndex]
                if (!item) return "<td></td>"
                const meetingItem = item as Record<string, unknown>
                const title = isMeetingTable
                  ? `${commonPrintTitleLine(String(meetingItem.title || ""))}${meetingItem.time ? ` ${String(meetingItem.time)}` : ""}`.trim()
                  : isPersonalRowId(row.id)
                    ? commonPrintPersonalTaskTitle(item as PrintTask)
                    : commonPrintTaskTitle(item as PrintTask)
                const taskBadges = isMeetingTable
                  ? ""
                  : `<span class="print-task-badge period">${escapePrintHtml(getCommonTaskPeriodLabel((item as PrintTask).finishPeriod))}</span>${
                      isWaitingConfirmationTask(item as PrintTask)
                        ? '<span class="print-task-badge wfc">WFC</span>'
                        : ""
                    }${
                      (item as PrintTask).oneHMarker
                        ? `<span class="print-task-badge marker">${escapePrintHtml(
                            (item as PrintTask).oneHMarkerByGa
                              ? `(${getOneHMarkerLabel((item as PrintTask).oneHMarker)})`
                              : getOneHMarkerLabel((item as PrintTask).oneHMarker)
                          )}</span>`
                        : ""
                    }`
                const markerComment = !isMeetingTable && (item as PrintTask).oneHMarkerComment
                  ? `<div class="print-marker-comment" title="${escapePrintHtml((item as PrintTask).oneHMarkerComment || "")}"><strong>COM:</strong> ${escapePrintHtml((item as PrintTask).oneHMarkerComment || "")}</div>`
                  : ""
                const taskNumber = chunkIndex * 6 + cellIndex + 1
                const startToday = !isMeetingTable && isCommonTaskStartToday(item as PrintTask, targetIso)
                const content = isMeetingTable
                  ? `${taskNumber}. ${escapePrintHtml(title)}`
                  : `${taskBadges}${markerComment}<span class="print-task-title">${taskNumber}. ${commonPrintTitleHtml(title)}</span>`
                return `<td class="${isMeetingTable ? "print-meeting-cell" : `print-task-cell${startToday ? " has-start-today" : ""}`}"><div>${content}</div>${isMeetingTable ? "" : printTaskDatesHtml(item as PrintTask)}</td>`
              }).join("")
              const rowHeaders =
                chunkIndex === 0
                  ? `<th class="print-slot-number" rowspan="${chunks}">${rowIndex + 1}</th><th class="print-slot-type" rowspan="${chunks}">${escapePrintHtml(row.label)}${
                      subtext ? `<span class="print-slot-subtext">${escapePrintHtml(subtext)}</span>` : ""
                    }</th>`
                  : ""
              return `<tr class="${chunkIndex === 0 ? "print-slot-start" : "print-slot-continuation"}">${rowHeaders}${itemCells}</tr>`
            }).join("")
          })
          .join("")

      const reportDate = formatDateHuman(targetIso)
      const reportHtml = `<!doctype html>
<html><head><meta charset="utf-8"><title>1H SHTYPI — ${escapePrintHtml(reportDate)}</title>
<style>
  @page { size: landscape; margin: 0.45in 0.35in 0.51in; }
  * { box-sizing: border-box; }
  body { margin: 0; color: #000; font-family: Arial, sans-serif; }
  .print-header { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; margin: 0 0 8px; }
  .print-title { font-size: 16px; font-weight: 700; text-align: center; }
  .print-date { text-align: right; font-size: 10px; }
  .one-h-print-checklists { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:12px; margin:0 0 12px; }
  .one-h-print-checklist-title { background:#eef2ff; border-left:5px solid #2563eb; padding:8px 10px; font-size:11px; font-weight:700; }
  .one-h-print-checklist-items { border:1px solid #64748b; padding:6px 8px; font-size:8px; line-height:1.35; }
  .one-h-print-checklist-day-label { grid-column:1 / -1; margin:0 0 4px; font-weight:800; }
  .one-h-print-checklist-separator { font-size:13px; font-weight:900; line-height:8px; }
  .one-h-print-checklist-description { color:#475569; }
  .one-h-marker-legend { display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin:0 0 10px; padding:6px 9px; border:1px solid #93c5fd; border-radius:5px; background:#eff6ff; color:#0f2a5f; font-size:9px; font-weight:700; }
  .one-h-marker-legend b { color:#dc2626; font-size:14px; font-weight:900; }
  .one-h-marker-legend b.compact-marker { font-size:9px; }
  .one-h-marker-legend i { color:#0f2a5f; font-size:20px; font-style:normal; font-weight:900; line-height:1; }
  table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 9px; line-height: 1.2; }
  table + table { margin-top: 12px; }
  th, td { border: 1px solid #000; padding: 4px 5px; vertical-align: top; overflow-wrap: anywhere; text-align: left; font-weight: 400; }
  thead th { text-align: center; font-weight: 700; vertical-align: middle; }
  tbody tr.print-slot-start > th, tbody tr.print-slot-start > td { border-top: 2px solid #111827; }
  tbody tr.print-slot-continuation > td { border-top: 1px solid #cbd5e1; }
  .print-slot-number, .print-slot-type { font-weight: 700; }
  thead th:first-child, tbody th:first-child { width: 20px; min-width: 20px; padding-left: 3px; padding-right: 3px; white-space: nowrap; }
  col.print-number-column { width: 20px; }
  col.print-label-column { width: 78px; }
  tbody th:nth-child(2) { padding-left: 2px; padding-right: 2px; }
  .print-slot-subtext { display: block; white-space: pre; overflow-wrap: normal !important; word-break: normal !important; font-size: 5.2px; font-weight: 400 !important; line-height: 1.05; }
  .print-task-cell { position:relative; padding-top:8px; padding-bottom:27px; }
  .print-task-cell.has-start-today { padding-bottom:41px; }
  .print-task-title { font-size:17px; line-height:1.25; }
  .print-marker-comment { display:block; width:fit-content; max-width:min(100%,150px); box-sizing:border-box; margin:4px 0; padding:2px 6px; border:1px solid #bfdbfe; border-radius:4px; background:#eff6ff; color:#1e3a8a; font-size:11px; font-weight:500; line-height:1.25; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .print-meeting-cell { padding-top:8px; font-size:13px; line-height:1.3; }
  .print-task-dates { position:absolute; left:5px; right:5px; bottom:4px; display:flex; align-items:flex-end; justify-content:space-between; gap:4px; white-space:nowrap; }
  .print-task-start { display:inline-flex; flex-direction:column; align-items:flex-start; gap:2px; }
  .print-task-date { display:inline-flex; box-sizing:border-box; height:18px; align-items:center; border:1px solid #93c5fd; border-radius:3px; background:#eff6ff; color:#1d4ed8; padding:1px 4px; font-weight:800; line-height:1; }
  .print-task-date.due { border:3px solid #b91c1c; padding:0 2px; }
  .print-task-date.due.today { height:26px; border:1px solid #991b1b; border-radius:4px; background:#dc2626; color:#fff; padding:3px 9px; font-size:14px; font-weight:900; box-shadow:0 1px 3px rgba(127,29,29,.45); }
  .print-task-badge { display:inline-block; margin:0 4px 3px 0; padding:2px 5px; border-radius:999px; font-size:8px; font-weight:800; line-height:1; white-space:nowrap; }
  .print-task-badge.period { background:#e0f2fe; border:1px solid #bae6fd; color:#0369a1; }
  .print-task-badge.start-today { margin:0; background:#dbeafe; border:1px solid #60a5fa; color:#1d4ed8; }
  .print-task-badge.wfc { background:#ffedd5; border:1px solid #fb923c; color:#c2410c; }
  .print-task-badge.marker { padding:2px 7px; background:#eff6ff; border:1px solid #93c5fd; color:#dc2626; font-size:14px; font-weight:900; text-shadow:0 0 0 currentColor; }
</style></head><body>
  <div class="print-header"><div></div><div class="print-title">1H SHTYPI — ${escapePrintHtml(reportDate)}</div><div class="print-date">${escapePrintHtml(formatDateTimeDMY(new Date()))}</div></div>
  ${oneHPrintChecklistsHtml(deliveryDate)}
  ${oneHMarkerLegendHtml()}
  <table><colgroup><col class="print-number-column"><col class="print-label-column"><col span="6"></colgroup><thead><tr><th>NR</th><th>LLoji dhe sloti</th><th colspan="6">Tasks</th></tr></thead><tbody>${buildTableRows(sortedTaskRows)}</tbody></table>
  <table><colgroup><col class="print-number-column"><col class="print-label-column"><col span="6"></colgroup><thead><tr><th>NR</th><th>LLoji</th><th colspan="6">Meeting</th></tr></thead><tbody>${buildTableRows(meetingRows, true)}</tbody></table>
</body></html>`

      printWindow.document.open()
      printWindow.document.write(reportHtml)
      printWindow.document.close()
      printWindow.focus()
      window.setTimeout(() => printWindow.print(), 100)
    } catch (err) {
      console.error("Failed to print tomorrow's Common View report", err)
      printWindow.close()
      toast.error(err instanceof Error ? err.message : "Failed to load tomorrow's report.")
    } finally {
      setPrintingTomorrow(false)
    }
  }

  const handlePrint = async () => {
    if (allDaysSelected) {
      const orientation = getPrintOrientation()
      if (orientation === "landscape") {
        setPrintTotalPages(1)
        applyWeekTablePrintFit()
      } else {
        resetWeekTablePrintFit()
        setPrintTotalPages(calculateAllDaysPortraitPages())
      }
      window.print()
      return
    }
    if (printingToday) return

    const reportDate = Array.from(selectedDates)[0] || toISODate(new Date())
    const printWindow = window.open("", "_blank")
    if (!printWindow) {
      toast.error("The browser blocked the print window. Please allow popups and try again.")
      setPrintTotalPages(1)
      applySingleDayPrintFit()
      window.print()
      return
    }

    printWindow.document.write("<!doctype html><title>Loading report...</title><p>Loading 1H SHTYPI SOT (Shiko simbolet)...</p>")
    printWindow.document.close()
    setPrintingToday(true)
    try {
      const response = await apiFetch(`/today-print-report/print-preview?report_date=${encodeURIComponent(reportDate)}`)
      if (!response?.ok) {
        throw new Error(`Could not load the 1H SHTYPI SOT (Shiko simbolet) report (${response?.status || "network error"}).`)
      }
      const report = (await response.json()) as { html?: string; subject?: string }
      if (!report.html) throw new Error("The 1H SHTYPI SOT (Shiko simbolet) report was empty.")

      printWindow.document.open()
      printWindow.document.write(report.html)
      printWindow.document.close()
      printWindow.document.title = report.subject || `1H SHTYPI SOT (Shiko simbolet) - ${reportDate}`

      const style = printWindow.document.createElement("style")
      style.textContent = `
        @page { size: landscape; margin: 0.25in; }
        html, body { margin: 0 !important; padding: 0 !important; background: #fff !important; }
        *, *::before, *::after {
          box-sizing: border-box;
          -webkit-print-color-adjust: exact !important;
          print-color-adjust: exact !important;
        }
        .common-view-today-print-fit { width: 100%; transform-origin: top left; }
      `
      printWindow.document.head.appendChild(style)

      const wrapper = printWindow.document.createElement("div")
      wrapper.className = "common-view-today-print-fit"
      while (printWindow.document.body.firstChild) {
        wrapper.appendChild(printWindow.document.body.firstChild)
      }
      printWindow.document.body.appendChild(wrapper)
      printWindow.focus()
      await printWindow.document.fonts?.ready
      await new Promise<void>((resolve) => printWindow.setTimeout(resolve, 100))

      const dpi = 96
      const printableWidthPx = (11 - 0.5) * dpi
      const printableHeightPx = (8.27 - 0.5) * dpi
      const naturalWidth = Math.max(1, wrapper.scrollWidth)
      const naturalHeight = Math.max(1, wrapper.scrollHeight)
      const fitScale = Math.min(1, printableWidthPx / naturalWidth, printableHeightPx / naturalHeight)
      wrapper.style.setProperty("zoom", String(Number.isFinite(fitScale) && fitScale > 0 ? fitScale : 1))
      printWindow.print()
    } catch (error) {
      console.error("Failed to print the canonical Today report", error)
      printWindow.close()
      toast.error(error instanceof Error ? error.message : "Failed to load the 1H SHTYPI SOT (Shiko simbolet) report.")
      setPrintTotalPages(1)
      applySingleDayPrintFit()
      window.print()
    } finally {
      setPrintingToday(false)
    }
  }

  // Calculate total pages for print footer
  React.useEffect(() => {
    const handleBeforePrint = () => {
      if (allDaysSelected) {
        window.requestAnimationFrame(() => {
          window.requestAnimationFrame(() => {
            const orientation = getPrintOrientation()
            if (orientation === "landscape") {
              setPrintTotalPages(1)
              applyWeekTablePrintFit()
              return
            }
            resetWeekTablePrintFit()
            setPrintTotalPages(calculateAllDaysPortraitPages())
          })
        })
        return
      }
      window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => {
          setPrintTotalPages(1)
          applySingleDayPrintFit()
        })
      })
    }
    const handleAfterPrint = () => {
      setPrintTotalPages(1)
      resetWeekTablePrintFit()
      resetSingleDayPrintFit()
    }
    window.addEventListener("beforeprint", handleBeforePrint)
    window.addEventListener("afterprint", handleAfterPrint)
    return () => {
      window.removeEventListener("beforeprint", handleBeforePrint)
      window.removeEventListener("afterprint", handleAfterPrint)
    }
  }, [
    allDaysSelected,
    applySingleDayPrintFit,
    applyWeekTablePrintFit,
    calculateAllDaysPortraitPages,
    getPrintOrientation,
    resetSingleDayPrintFit,
    resetWeekTablePrintFit,
  ])

  const today = new Date()
  const todayIso = toISODate(today)
  const thisWeekMonday = getMonday(today)
  const thisWeekMondayIso = toISODate(thisWeekMonday)
  const isOpenTaskStartingToday = (isDone?: boolean, startDate?: string | null) => {
    if (isDone || !startDate) return false
    const start = parseDateOnly(startDate)
    return Boolean(start && toISODate(start) === todayIso)
  }

  const buildCommonViewExportPayload = () => {
    const exportISOsBase = allDaysSelected ? weekISOs : weekISOs.filter((iso) => selectedDates.has(iso))
    const exportISOs = exportISOsBase.length ? exportISOsBase : weekISOs

    const dailyFeedback = filtered.feedback.filter((x) => x.everyday)
    const dailyProblems = filtered.problems.filter((x) => x.everyday)

    const dataByDay: Record<
      string,
      {
        late: LateItem[]
        absent: AbsentItem[]
        leave: LeaveItem[]
        externalHoliday: ExternalHolidayItem[]
        waitingClient: FastTaskEntry[]
        blocked: BlockedItem[]
        oneH: OneHItem[]
        personal: PersonalItem[]
        external: ExternalItem[]
        internal: InternalItem[]
        bz: BzItem[]
        r1: R1Item[]
        problems: ProblemItem[]
        feedback: FeedbackItem[]
        priority: PriorityItem[]
      }
    > = {}

    exportISOs.forEach((iso) => {
      if (filtered.fullyCoveredDates.has(iso)) {
        const allUsersLeave = allUsersLeaveByDate.get(iso)
        dataByDay[iso] = {
          late: [],
          absent: [],
          leave: [
            allUsersLeave || {
              person: ALL_USERS_INITIALS,
              startDate: iso,
              endDate: iso,
              fullDay: true,
              isAllUsers: true,
            },
          ],
          externalHoliday: filtered.externalHoliday.filter((x) => x.date === iso),
          waitingClient: [],
          blocked: [],
          oneH: [],
          personal: [],
          external: [],
          internal: [],
          bz: [],
          r1: [],
          problems: dailyProblems,
          feedback: dailyFeedback,
          priority: [],
        }
        return
      }
      dataByDay[iso] = {
        late: filtered.late.filter((x) => x.date === iso),
        absent: filtered.absent.filter((x) => x.date === iso),
        leave: filtered.leave.filter((x) => iso >= x.startDate && iso <= x.endDate),
        externalHoliday: filtered.externalHoliday.filter((x) => x.date === iso),
        waitingClient: sortTasksByOrder(
          [...filtered.blocked, ...filtered.oneH, ...filtered.personal, ...filtered.r1].filter(
            (x) => x.date === iso && isWaitingClientTask(x)
          ),
          false
        ),
        blocked: sortTasksByOrder(
          filtered.blocked.filter(
            (x) => x.date === iso && !isWaitingClientTask(x) && !isRoutedWaitingConfirmation(x)
          ),
          false
        ),
        oneH: sortTasksByOrder(
          filtered.oneH.filter(
            (x) => x.date === iso && !isWaitingClientTask(x) && !isRoutedWaitingConfirmation(x)
          ),
          false
        ),
        personal: sortTasksByOrder(filtered.personal.filter((x) => x.date === iso && !isWaitingClientTask(x)), false),
        external: sortByTime(filtered.external.filter((x) => x.date === iso), (x) => x.time, (x) => x.title),
        internal: sortByTime(filtered.internal.filter((x) => x.date === iso), (x) => x.time, (x) => x.title),
        bz: sortByTime(filtered.bz.filter((x) => x.date === iso), (x) => x.time, (x) => x.title),
        r1: sortTasksByOrder(
          filtered.r1.filter(
            (x) => x.date === iso && !isWaitingClientTask(x) && !isRoutedWaitingConfirmation(x)
          ),
          false
        ),
        problems: [
          ...filtered.problems.filter((x) => !x.everyday && x.date === iso),
          ...dailyProblems,
        ],
        feedback: [
          ...filtered.feedback.filter((x) => !x.everyday && x.date === iso),
          ...dailyFeedback,
        ],
        priority: filtered.priority.filter((x) => x.date === iso),
      }
    })

    const assigneesSuffix = (entry: { assignees?: string[]; person?: string; owner?: string }) => {
      const initialsList = entryAssignees(entry).map((name: string) => initials(name)).filter(Boolean)
      return initialsList.length ? ` (${initialsList.join(", ")})` : ""
    }

    const getOneHEntriesForRow = (entries: OneHItem[], rowId: CommonType) => {
      const slot = getOneHSlotRowSlot(rowId)
      if (slot === undefined) return entries
      return entries.filter((entry) =>
        slot === null ? !normalizeOneHReportSlot(entry.oneHReportSlot) : normalizeOneHReportSlot(entry.oneHReportSlot) === slot
      )
    }

    const renderCellLines = (rowId: CommonType, iso: string) => {
      const dayData = dataByDay[iso]
      if (!dayData) return []
      const entries =
        rowId === "late"
          ? dayData.late
          : rowId === "absent"
            ? dayData.absent
            : rowId === "leave"
              ? dayData.leave
              : rowId === "externalHoliday"
                ? dayData.externalHoliday
                : rowId === "waitingClient"
                  ? dayData.waitingClient
                  : rowId === "blocked"
                    ? dayData.blocked
                    : isOneHSlotRowId(rowId)
                      ? getOneHEntriesForRow(dayData.oneH, rowId)
                      : rowId === "r1"
                        ? dayData.r1
                        : isPersonalRowId(rowId)
                          ? personalTasksForRow(dayData.personal, rowId)
                          : rowId === "external"
                            ? dayData.external
                            : rowId === "internal"
                              ? dayData.internal
                              : rowId === "bz"
                                ? dayData.bz
                                : rowId === "priority"
                                  ? dayData.priority
                                  : rowId === "problem"
                                    ? dayData.problems
                                    : rowId === "feedback"
                                      ? dayData.feedback
                                      : []
      if (!entries.length) return []
      const markerCommentPrefix = (entry: { oneHMarkerComment?: string | null }) =>
        entry.oneHMarkerComment?.trim() ? `COM: ${entry.oneHMarkerComment.trim()}\n` : ""

      if (rowId === "late") {
        return (entries as LateItem[]).map((e, idx: number) => `${idx + 1}. ${e.start || "08:00"}-${e.until}${assigneesSuffix(e)}`)
      }
      if (rowId === "absent") {
        return (entries as AbsentItem[]).map((e, idx: number) => `${idx + 1}. ${e.from} - ${e.to}${assigneesSuffix(e)}`)
      }
      if (rowId === "leave") {
        return (entries as LeaveItem[]).map((e, idx: number) => {
          const isAllUsers = Boolean(e.isAllUsers || e.person === ALL_USERS_INITIALS)
          const timeLabel = e.fullDay ? "08:00-16:30" : `${e.from}-${e.to}`
          const label = isAllUsers ? `${timeLabel} ALL` : timeLabel
          return `${idx + 1}. ${label}${isAllUsers ? "" : assigneesSuffix(e)}`
        })
      }
      if (rowId === "externalHoliday") {
        return (entries as ExternalHolidayItem[]).map((e, idx: number) => `${idx + 1}. ${e.title}${e.note ? ` - ${e.note}` : ""}`)
      }
      if (rowId === "waitingClient") {
        return (entries as FastTaskEntry[]).map(
          (e, idx: number) => `${markerCommentPrefix(e)}${idx + 1}. ${commonPrintTitleLine(e.title)}${assigneesSuffix(e)}`
        )
      }
      if (rowId === "blocked") {
        return (entries as BlockedItem[]).map(
          (e) => `${markerCommentPrefix(e)}${getFastTaskDisplayNumber(entries as FastTaskEntry[], e)}. ${commonPrintTitleLine(e.title)}${assigneesSuffix(e)}`
        )
      }
      if (isOneHSlotRowId(rowId) || rowId === "r1") {
        return (entries as (OneHItem | R1Item)[]).map(
          (e: OneHItem | R1Item) =>
            `${markerCommentPrefix(e)}${getFastTaskDisplayNumber(entries as FastTaskEntry[], e)}. ${
              isOneHSlotRowId(rowId) ? `[${getOneHReportSlotLabel((e as OneHItem).oneHReportSlot)}] ` : ""
            }[${getCommonTaskPeriodLabel(e.finishPeriod)}] ${isWaitingConfirmationTask(e) ? "[WFC] " : ""}${
              isOneHSlotRowId(rowId) && (e as OneHItem).oneHMarker
                ? `${(e as OneHItem).oneHMarkerByGa
                    ? `(${getOneHMarkerLabel((e as OneHItem).oneHMarker)})`
                    : `[${getOneHMarkerLabel((e as OneHItem).oneHMarker)}]`} `
                : ""
            }${commonPrintTitleLine(e.title)}${assigneesSuffix(e)}`
        )
      }
      if (isPersonalRowId(rowId)) {
        return (entries as PersonalItem[]).map(
          (e) => `${markerCommentPrefix(e)}${getFastTaskDisplayNumber(entries as FastTaskEntry[], e)}. `
            + `[${getCommonTaskPeriodLabel(e.finishPeriod)}] ${isWaitingConfirmationTask(e) ? "[WFC] " : ""}`
            + `${commonPrintPersonalTaskTitle(e)}${assigneesSuffix(e)}`
        )
      }
      if (rowId === "external") {
        return (entries as ExternalItem[]).map((e, idx: number) => `${idx + 1}. ${`${commonPrintTitleLine(e.title)} ${formatTimeLabel(e.time)}`.trim()}${assigneesSuffix(e)}`)
      }
      if (rowId === "internal") {
        return (entries as InternalItem[]).map((e, idx: number) => `${idx + 1}. ${`${commonPrintTitleLine(e.title)} ${formatTimeLabel(e.time)}`.trim()}${assigneesSuffix(e)}`)
      }
      if (rowId === "bz") {
        return (entries as BzItem[]).map((e, idx: number) => {
          const bzLabel = e.bzWithLabel ? ` - BZ: ${e.bzWithLabel}` : ""
          return `${idx + 1}. ${commonPrintTitleLine(`${formatTimeLabel(e.time)} ${e.title}`.trim())}${bzLabel}${assigneesSuffix(e)}`
        })
      }
      if (rowId === "priority") {
        return (entries as PriorityItem[]).map((e, idx: number) => `${idx + 1}. ${e.project}${assigneesSuffix(e)}`)
      }
      if (rowId === "problem" || rowId === "feedback") {
        return (entries as (ProblemItem | FeedbackItem)[]).map((e, idx: number) => {
          const dateLabel = e.createdDate ? formatDateHuman(e.createdDate) : formatDateHuman(e.date)
          const noteLabel = e.note ? ` - ${e.note}` : ""
          return `${idx + 1}. ${e.title} - ${dateLabel}${noteLabel}${assigneesSuffix(e)}`
        })
      }
      return []
    }

    const visibleRows = swimlaneRows.filter((row) => showCard(row.id, row.items.length))
    const columns = ["NR", "LLOJI", ...exportISOs.map((iso) => `${getDayCode(fromISODate(iso))} = ${formatDateHuman(iso)}`)]
    const rows = visibleRows.map((row, rowIndex) => [
      String(rowIndex + 1),
      row.label.toUpperCase(),
      ...exportISOs.map((iso) => renderCellLines(row.id as CommonType, iso).join("\n")),
    ])
    const weekTitleRange =
      exportISOs.length >= 2
        ? `${formatDateHuman(exportISOs[0])} - ${formatDateHuman(exportISOs[exportISOs.length - 1])}`
        : exportISOs.length === 1
          ? formatDateHuman(exportISOs[0])
          : ""
    return {
      title: `COMMON VIEW - WEEK PLAN${weekTitleRange ? ` (${weekTitleRange})` : ""}`,
      columns,
      rows,
    }
  }

  const handleExportExcel = async () => {
    if (exportingExcel) return
    setExportingExcel(true)
    try {
      const payload = buildCommonViewExportPayload()
      const res = await apiFetch(`/exports/common-view.xlsx`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res?.ok) {
        const detail = await res.text()
        toast.error(detail || "Failed to export Excel.")
        return
      }
      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      const filename = parseFilenameFromDisposition(res.headers.get("content-disposition"))
      if (filename) {
        link.download = filename
      } else {
        const dd = String(weekStart.getDate()).padStart(2, "0")
        const mm = String(weekStart.getMonth() + 1).padStart(2, "0")
        const yy = String(weekStart.getFullYear()).slice(-2)
        const initialsValue = (printInitials || "USER").toUpperCase()
        link.download = `COMMON VIEW ${dd}_${mm}_${yy}_EF (${initialsValue}).xlsx`
      }
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (err) {
      console.error("Failed to export common view Excel", err)
      toast.error("Failed to export Excel.")
    } finally {
      setExportingExcel(false)
    }
  }

  const handleExportMeetingExcel = async () => {
    if (exportingMeetingExcel) return
    if (!activeMeeting?.id) return
    setExportingMeetingExcel(true)
    try {
      const res = await apiFetch(`/exports/meeting-template.xlsx?checklist_id=${encodeURIComponent(activeMeeting.id)}`)
      if (!res?.ok) {
        const detail = await res.text()
        toast.error(detail || "Failed to export Excel.")
        return
      }
      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      const filename = parseFilenameFromDisposition(res.headers.get("content-disposition"))
      if (filename) {
        link.download = filename
      } else {
        const dd = String(weekStart.getDate()).padStart(2, "0")
        const mm = String(weekStart.getMonth() + 1).padStart(2, "0")
        const yy = String(weekStart.getFullYear()).slice(-2)
        const initialsValue = (printInitials || "USER").toUpperCase()
        link.download = `MEETING ${dd}_${mm}_${yy}_EF (${initialsValue}).xlsx`
      }
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (err) {
      console.error("Failed to export meeting Excel", err)
      toast.error("Failed to export Excel.")
    } finally {
      setExportingMeetingExcel(false)
    }
  }

  const handleExportAllMeetingTemplatesExcel = async () => {
    if (exportingAllMeetingTemplatesExcel) return
    setExportingAllMeetingTemplatesExcel(true)
    try {
      const res = await apiFetch(`/exports/meeting-templates.xlsx`)
      if (!res?.ok) {
        const detail = await res.text()
        toast.error(detail || "Failed to export all meetings.")
        return
      }
      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      const filename = parseFilenameFromDisposition(res.headers.get("content-disposition"))
      link.download = filename || "MEETING_ALL.xlsx"
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (err) {
      console.error("Failed to export all meeting checklists", err)
      toast.error("Failed to export all meetings.")
    } finally {
      setExportingAllMeetingTemplatesExcel(false)
    }
  }

  const setWeek = (dateStr: string) => {
    const base = dateStr ? fromISODate(dateStr) : new Date()
    const monday = getMonday(base)
    if (toISODate(weekStart) !== toISODate(monday)) {
      setDataLoaded(false)
      setWeekStart(monday)
    }
    setSelectedDates(new Set([toISODate(base)]))
    setMultiMode(false)
    resetSwimlaneTitleRowsOpen()
  }

  const openModal = () => {
    setModalOpen(true)
  }

  const closeModal = () => {
    setModalOpen(false)
    // Reset form
    setFormType("late")
    setFormPerson("")
    setFormDate(toISODate(new Date()))
    setFormDateDisplay(toDDMMYYYY(toISODate(new Date())))
    setFormDelayStart("08:00")
    setFormUntil("09:00")
    setFormFrom("08:00")
    setFormTo("12:00")
    setFormEndDate("")
    setFormEndDateDisplay("")
    setFormFullDay(false)
    setFormTitle("")
    setFormNote("")
    setFormError("")
    setPendingPvTaskShift(null)
  }

  const nextWeekdayAfter = (isoDate: string) => {
    let next = addDays(fromISODate(isoDate), 1)
    while (next.getDay() === 0 || next.getDay() === 6) {
      next = addDays(next, 1)
    }
    return toISODate(next)
  }

  const nextWeekdayOptionsAfter = (isoDate: string, count = 5) => {
    const options: string[] = []
    let cursor = addDays(fromISODate(isoDate), 1)
    while (options.length < count) {
      if (cursor.getDay() !== 0 && cursor.getDay() !== 6) {
        options.push(toISODate(cursor))
      }
      cursor = addDays(cursor, 1)
    }
    return options
  }

  const taskDateInRange = (value: string | null | undefined, startDate: string, endDate: string) => {
    const parsed = parseDateOnly(value)
    if (!parsed) return false
    const iso = toISODate(parsed)
    return iso >= startDate && iso <= endDate
  }

  const loadPvAffectedTasks = async (assigneeId: string, startDate: string, endDate: string) => {
    const params = new URLSearchParams({
      include_done: "false",
      assigned_to: assigneeId,
      include_all_departments: "true",
    })
    const res = await apiFetch(`/tasks?${params.toString()}`)
    if (!res?.ok) throw new Error("failed_to_load_tasks")
    const taskList = (await res.json()) as Task[]
    return taskList
      .map((task) => ({
        task,
        startDateInLeave: taskDateInRange(task.start_date, startDate, endDate),
        dueDateInLeave: taskDateInRange(task.due_date, startDate, endDate),
      }))
      .filter((item) => item.startDateInLeave || item.dueDateInLeave)
  }

  const movePvAffectedTasks = async (pending: PendingPvTaskShift) => {
    const moveToIso = new Date(`${pending.moveToDate}T00:00:00`).toISOString()
    const moveToDate = fromISODate(pending.moveToDate)
    const results = await Promise.all(
      pending.tasks.map(({ task, startDateInLeave, dueDateInLeave }) => {
        const dueDate = parseDateOnly(task.due_date)
        const payload: { start_date?: string; due_date?: string } = {}
        if (startDateInLeave) payload.start_date = moveToIso
        if (dueDateInLeave || (startDateInLeave && dueDate && dueDate < moveToDate)) {
          payload.due_date = moveToIso
        }
        if (!payload.start_date && !payload.due_date) return Promise.resolve({ ok: true })
        return apiFetch(`/tasks/${task.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        })
      })
    )
    return {
      moved: results.filter((result) => result.ok).length,
      failed: results.filter((result) => !result.ok).length,
    }
  }

  const submitForm = async (
    e?: React.FormEvent,
    options: { skipPvTaskPrompt?: boolean; movePvTasks?: boolean } = {}
  ) => {
    e?.preventDefault()
    if (isSavingEntry) return
    setIsSavingEntry(true)

    try {
      setFormError("")
      if ((formType === "late" || formType === "absent") && formDate && isDateFullyCovered(formDate)) {
        setFormError("All users are on leave for this date, so VONS/MUNG entries are hidden.")
        return
      }
      let category: string
      if (formType === "late") category = "Delays"
      else if (formType === "absent") category = "Absences"
      else if (formType === "leave") category = "Annual Leave"
      else if (formType === "externalHoliday") category = "External Holiday"
      else if (formType === "problem") category = "Problems"
      else category = "Requests"

      const isAllUsersLeave = formType === "leave" && formPerson === ALL_USERS_VALUE

      // Find the user by name if person is selected
      let assignedUserId: string | null = null
      if (formPerson && formType !== "feedback" && formType !== "externalHoliday" && !isAllUsersLeave) {
        const selectedUser = users.find(
          (u) =>
            u.full_name === formPerson ||
            u.username === formPerson ||
            u.email === formPerson ||
            `${u.full_name || ""}`.trim() === formPerson
        )
        if (selectedUser) {
          assignedUserId = selectedUser.id
        }
      }

      // Build description with all relevant information
      let description = formNote || ""
      
      // Add time/date information based on type
      if (formType === "late") {
        const startTime = formDelayStart || "08:00"
        const startLine = `Start: ${startTime}`
        const endLine = formUntil ? `Until: ${formUntil}` : ""
        const delayLines = endLine ? `${startLine}\n${endLine}` : startLine
        description = description ? `${description}\n\n${delayLines}` : delayLines
      } else if (formType === "absent" && formFrom && formTo) {
        description = description ? `${description}\n\nFrom: ${formFrom} - To: ${formTo}` : `From: ${formFrom} - To: ${formTo}`
        } else if (formType === "leave") {
          const leaveInfo =
            formEndDate && formEndDate !== formDate
              ? `Date range: ${formDate} to ${formEndDate}`
              : `Date: ${formDate}`
          const timeInfo = formFullDay ? "(Full day)" : `(${formFrom || "--:--"} - ${formTo || "--:--"})`
          const combinedLeaveInfo = `${leaveInfo} ${timeInfo}`.trim()
          description = description ? `${description}\n\n${combinedLeaveInfo}` : combinedLeaveInfo
      }
      
      // Add date information
      if (formDate && formType !== "leave" && formType !== "feedback" && formType !== "problem" && formType !== "externalHoliday") {
        description = description ? `${description}\nDate: ${formDate}` : `Date: ${formDate}`
      }
      if (formType === "feedback" || formType === "problem") {
        description = description ? `${description}\n${FEEDBACK_DAILY_MARKER}` : FEEDBACK_DAILY_MARKER
      }

      if (
        formType === "leave" &&
        formFullDay &&
        assignedUserId &&
        formDate &&
        !options.skipPvTaskPrompt
      ) {
        const endDate = formEndDate || formDate
        setLoadingPvTaskShift(true)
        try {
          const affectedTasks = await loadPvAffectedTasks(assignedUserId, formDate, endDate)
          if (affectedTasks.length > 0) {
            setPendingPvTaskShift({
              assigneeId: assignedUserId,
              person: formPerson || "Selected person",
              startDate: formDate,
              endDate,
              moveToDate: nextWeekdayAfter(endDate),
              tasks: affectedTasks,
            })
            return
          }
        } finally {
          setLoadingPvTaskShift(false)
        }
      }

      if (isAllUsersLeave) {
        const activeUsers = users.filter((u) => u.is_active)
        const descriptionWithMarker = description
          ? `${description}\n${ALL_USERS_MARKER}`
          : ALL_USERS_MARKER
        const payloadBase = {
          category,
          description: descriptionWithMarker || null,
          entry_date: formDate || null,
        }
        const results = await Promise.all(
          activeUsers.map((u) =>
            apiFetch("/common-entries", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                ...payloadBase,
                title: u.full_name || u.username || u.email || "Untitled",
                assigned_to_user_id: u.id,
              }),
            })
          )
        )
        if (results.every((r) => r.ok)) {
          // Trigger a reload
          window.location.reload()
        }
      } else {
        // Create the entry
        const res = await apiFetch("/common-entries", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            category,
            title: formType === "feedback" || formType === "problem" || formType === "externalHoliday" ? formTitle : formPerson || "Untitled",
            description: description || null,
            entry_date: formType === "feedback" || formType === "problem" ? null : formDate || null,
            assigned_to_user_id: formType === "externalHoliday" ? null : assignedUserId || null,
          }),
        })

        if (res.ok) {
          if (options.movePvTasks && pendingPvTaskShift) {
            const result = await movePvAffectedTasks(pendingPvTaskShift)
            if (result.failed > 0) {
              toast.error(`${result.failed} task${result.failed === 1 ? "" : "s"} could not be moved.`)
            } else if (result.moved > 0) {
              toast.success(`${result.moved} task${result.moved === 1 ? "" : "s"} moved to ${formatDateHuman(pendingPvTaskShift.moveToDate)}.`)
            }
          }
          // Trigger a reload
          window.location.reload()
        }
      }
      closeModal()
    } catch (err) {
      console.error("Failed to submit form", err)
    } finally {
      setIsSavingEntry(false)
    }
  }

  const showCard = (type: CommonType, itemCount?: number) => {
    if (taskFocusFilter !== "all" && !isFastTaskRowId(type)) return false
    if (taskFocusFilter === "startToday" && itemCount === 0) return false
    if (oneHMarkerFilters.size > 0 || kaGentFilterActive) {
      if (!isFastTaskRowId(type)) return false
      if (itemCount === 0) return false
    }
    if (type === "waitingClient") {
      if (typeFilters.size === 0) return true
      return (["blocked", "oneH", "personal", "r1"] as CommonType[]).some((taskType) => typeFilters.has(taskType))
    }
    const matchesType =
      typeFilters.size === 0 ||
      typeFilters.has(type) ||
      (isOneHSlotRowId(type) && typeFilters.has("oneH")) ||
      (isPersonalRowId(type) && typeFilters.has("personal"))
    if (!matchesType) return false
    if (colorFilter === "all") return true
    return isFastTaskRowId(type)
  }

  const deleteCommonEntry = React.useCallback(
    async (entryId: string) => {
      if (!canDeleteCommon) return
      const confirmed = await confirm({
        title: "Delete common entry",
        description: "Delete this common entry? This action cannot be undone.",
        confirmLabel: "Delete",
        variant: "destructive",
      })
      if (!confirmed) return
      try {
        const res = await apiFetch(`/common-entries/${entryId}`, { method: "DELETE" })
        if (!res?.ok) {
          console.error("Failed to delete common entry", res?.status)
          return
        }
        window.location.reload()
      } catch (err) {
        console.error("Failed to delete common entry", err)
      }
    },
    [apiFetch, canDeleteCommon, confirm]
  )

  const deleteAllUsersLeaveForDay = React.useCallback(
    async (dayIso: string) => {
      if (!isAdmin) return
      const confirmed = await confirm({
        title: "Delete all annual leave",
        description: "Delete ALL annual leave entries for this day? This removes annual leave for every user on this day.",
        confirmLabel: "Delete all",
        variant: "destructive",
      })
      if (!confirmed) return
      try {
        const entryIdsMarked = Array.from(
          new Set(
            commonData.leave
              .filter((x) => x.isAllUsers && x.entryId && leaveCovers(x, dayIso))
              .map((x) => x.entryId as string)
          )
        )
        const entryIdsFallback = Array.from(
          new Set(
            commonData.leave
              .filter((x) => x.entryId && leaveCovers(x, dayIso))
              .map((x) => x.entryId as string)
          )
        )
        const entryIds = entryIdsMarked.length ? entryIdsMarked : entryIdsFallback
        if (!entryIds.length) return
        const results = await Promise.all(
          entryIds.map((entryId) => apiFetch(`/common-entries/${entryId}`, { method: "DELETE" }))
        )
        if (results.every((r) => r?.ok)) {
          window.location.reload()
        }
      } catch (err) {
        console.error("Failed to delete all-users annual leave entries", err)
      }
    },
    [apiFetch, commonData.leave, confirm, isAdmin]
  )

  const toggleChecklistItem = React.useCallback(
    async (itemId: string) => {
      const currentChecked = externalMeetingChecklistItems.get(itemId) ?? false
      const newChecked = !currentChecked
      
      // Optimistically update UI
      setExternalMeetingChecklistItems((prev) => {
        const next = new Map(prev)
        next.set(itemId, newChecked)
        return next
      })

      try {
        const res = await apiFetch(`/checklist-items/${itemId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_checked: newChecked }),
        })
        if (!res?.ok) {
          // Revert on error
          setExternalMeetingChecklistItems((prev) => {
            const next = new Map(prev)
            next.set(itemId, currentChecked)
            return next
          })
          console.error("Failed to update checklist item", res?.status)
        }
      } catch (err) {
        // Revert on error
        setExternalMeetingChecklistItems((prev) => {
          const next = new Map(prev)
          next.set(itemId, currentChecked)
          return next
        })
        console.error("Failed to update checklist item", err)
      }
    },
    [apiFetch, externalMeetingChecklistItems]
  )

  const requestMeetingAvailability = React.useCallback(async (params: {
    title: string
    meetingType: "internal" | "external"
    startsAt: Date
    departmentId: string
    participantIds: string[]
  }): Promise<MeetingAvailability | null> => {
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
      }),
    })
    if (!response.ok) return null
    return (await response.json()) as MeetingAvailability
  }, [apiFetch])

  const submitExternalMeeting = React.useCallback(async () => {
    if (!externalMeetingTitle.trim()) return
    if (!externalMeetingParticipantIds.length) {
      toast.error("Select at least one person for the meeting.")
      return
    }
    const departmentId = externalMeetingDepartmentId || user?.department_id
    if (!departmentId) {
      console.error("Department is required to create a meeting.")
      return
    }
    const shouldCreateAgentTestTask = externalMeetingCreateAgentTestTask
    const shouldCreatePimImageTestTask = externalMeetingCreatePimImageTestTask
    if ((shouldCreateAgentTestTask || shouldCreatePimImageTestTask) && (externalMeetingRecurrenceType !== "none" || !externalMeetingStartsAt)) {
      toast.error("Test tasks are available only for one-time meetings with a start date.")
      return
    }
    setCreatingExternalMeeting(true)
    try {
      let startsAt: string | null = null
      let internalStartsAt: string | null = null
      if (externalMeetingRecurrenceType === "none") {
        if (!externalMeetingStartsAt) {
          toast.error("Add the date and time for TAK EXT.")
          return
        }
        if (externalMeetingCreateInternal && (!externalMeetingInternalStartsAt || !externalMeetingInternalStartTime)) {
          toast.error("Add the date and time for TAK INT.")
          return
        }
        startsAt = new Date(externalMeetingStartsAt).toISOString()
        if (externalMeetingCreateInternal) {
          internalStartsAt = new Date(
            `${externalMeetingInternalStartsAt}T${externalMeetingInternalStartTime}`
          ).toISOString()
        }
      } else {
        if (!externalMeetingStartTime) {
          toast.error("Time is required for TAK EXT.")
          return
        }
        if (externalMeetingCreateInternal && !externalMeetingInternalStartTime) {
          toast.error("Time is required for TAK INT.")
          return
        }
        if (externalMeetingRecurrenceType === "weekly" && externalMeetingRecurrenceDaysOfWeek.length === 0) {
          toast.error("Select at least one day.")
          return
        }
        if (externalMeetingRecurrenceType === "monthly" && externalMeetingRecurrenceDaysOfMonth.length === 0) {
          toast.error("Select at least one day.")
          return
        }
        if (externalMeetingRecurrenceType === "yearly") {
          if (!externalMeetingRecurrenceMonth || !externalMeetingRecurrenceDay) {
            toast.error("Select month and date.")
            return
          }
        }
        const next = computeNextOccurrenceDate({
          recurrenceType: externalMeetingRecurrenceType,
          daysOfWeek: externalMeetingRecurrenceDaysOfWeek,
          daysOfMonth:
            externalMeetingRecurrenceType === "yearly"
              ? [Number(externalMeetingRecurrenceDay)]
              : externalMeetingRecurrenceDaysOfMonth,
          timeValue: externalMeetingStartTime,
          monthOfYear:
            externalMeetingRecurrenceType === "yearly"
              ? Math.max(0, Math.min(11, Number(externalMeetingRecurrenceMonth) - 1))
              : undefined,
        })
        if (!next) {
          toast.error("Failed to compute next occurrence.")
          return
        }
        startsAt = next.toISOString()
        if (externalMeetingCreateInternal) {
          const internalNext = computeNextOccurrenceDate({
            recurrenceType: externalMeetingRecurrenceType,
            daysOfWeek: externalMeetingRecurrenceDaysOfWeek,
            daysOfMonth:
              externalMeetingRecurrenceType === "yearly"
                ? [Number(externalMeetingRecurrenceDay)]
                : externalMeetingRecurrenceDaysOfMonth,
            timeValue: externalMeetingInternalStartTime,
            monthOfYear:
              externalMeetingRecurrenceType === "yearly"
                ? Math.max(0, Math.min(11, Number(externalMeetingRecurrenceMonth) - 1))
                : undefined,
          })
          if (!internalNext) {
            toast.error("Failed to compute the TAK INT occurrence.")
            return
          }
          internalStartsAt = internalNext.toISOString()
        }
      }
      const externalAvailability = await requestMeetingAvailability({
        title: externalMeetingTitle,
        meetingType: "external",
        startsAt: new Date(startsAt),
        departmentId,
        participantIds: externalMeetingParticipantIds,
      })
      const pairedInternalAvailability = internalStartsAt
        ? await requestMeetingAvailability({
            title: externalMeetingTitle,
            meetingType: "internal",
            startsAt: new Date(internalStartsAt),
            departmentId,
            participantIds: externalMeetingParticipantIds,
          })
        : null
      const oneHConflicts = [
        ...(externalAvailability?.conflicts.filter((conflict) => conflict.source === "one_h") || []),
        ...(pairedInternalAvailability?.conflicts.filter((conflict) => conflict.source === "one_h") || []),
      ]
      let allowOneHConflict = false
      if (oneHConflicts.length) {
        allowOneHConflict = await confirm({
          title: "Konflikt me orarin 1H",
          description: "Ky orar përputhet me 1H.",
          confirmLabel: "Aprovo gjithsesi",
          cancelLabel: "Ndrysho",
        })
        if (!allowOneHConflict) return
      }
      const payload = {
        title: externalMeetingTitle.trim(),
        platform: externalMeetingPlatform.trim() || null,
        starts_at: startsAt,
        internal_starts_at: internalStartsAt,
        create_internal_meeting: externalMeetingCreateInternal,
        meeting_type: "external",
        recurrence_type: externalMeetingRecurrenceType === "none" ? null : externalMeetingRecurrenceType,
        recurrence_days_of_week:
          externalMeetingRecurrenceType === "weekly" && externalMeetingRecurrenceDaysOfWeek.length > 0
            ? externalMeetingRecurrenceDaysOfWeek
            : null,
        recurrence_days_of_month:
          externalMeetingRecurrenceType === "monthly" && externalMeetingRecurrenceDaysOfMonth.length > 0
            ? externalMeetingRecurrenceDaysOfMonth
            : externalMeetingRecurrenceType === "yearly" && externalMeetingRecurrenceDay
              ? [Number(externalMeetingRecurrenceDay)]
              : null,
        department_id: departmentId,
        project_id: null,
        participant_ids: externalMeetingParticipantIds,
        allow_one_h_conflict: allowOneHConflict,
      }
      const res = await apiFetch("/meetings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res?.ok) {
        const body = await res.json().catch(() => null)
        const message = body?.detail?.message || body?.detail || "Failed to create meeting."
        toast.error(typeof message === "string" ? message : "Failed to create meeting.")
        console.error("Failed to create meeting", res?.status)
        return
      }
      const created = (await res.json()) as Meeting
      const pairedInternalMeeting = created.paired_internal_meeting || null
      if (externalMeetingCreateInternal && !pairedInternalMeeting) {
        toast.error("The TAK EXT meeting was created, but TAK INT was not returned.")
        return
      }
      let meetingForList = created
      if (shouldCreateAgentTestTask) {
        const taskRes = await apiFetch(`/meetings/${created.id}/agent-test-task`, {
          method: "POST",
        })
        if (!taskRes?.ok) {
          const detail = await taskRes
            .json()
            .then((body) => (typeof body?.detail === "string" ? body.detail : null))
            .catch(() => null)
          toast.error(detail || "Meeting created, but failed to create Testimi i agentave task.")
        } else {
          meetingForList = (await taskRes.json()) as Meeting
          toast.success("Meeting and Testimi i agentave task created.")
        }
      }
      if (shouldCreatePimImageTestTask) {
        const taskRes = await apiFetch(`/meetings/${created.id}/pim-image-test-task`, {
          method: "POST",
        })
        if (!taskRes?.ok) {
          const detail = await taskRes
            .json()
            .then((body) => (typeof body?.detail === "string" ? body.detail : null))
            .catch(() => null)
          toast.error(detail || "Meeting created, but failed to create Testimi i PIM image task.")
        } else {
          meetingForList = (await taskRes.json()) as Meeting
          toast.success("Meeting and Testimi i PIM image task created.")
        }
      }
      setExternalMeetings((prev) => [meetingForList, ...prev])
      if (pairedInternalMeeting) {
        setInternalMeetings((prev) => [pairedInternalMeeting, ...prev])
      }
      COMMON_VIEW_CACHE.clear()
      const ownerName = user?.full_name || user?.username || user?.email || "Unknown"
      const mappedExternal = mapMeetingToCommonItem(meetingForList, "external", ownerName)
      const mappedInternal = pairedInternalMeeting
        ? mapMeetingToCommonItem(pairedInternalMeeting, "internal", ownerName, meetingForList)
        : null
      if (mappedExternal || mappedInternal) {
        setCommonData((prev) => ({
          ...prev,
          external: mappedExternal ? [...prev.external, mappedExternal] : prev.external,
          internal: mappedInternal ? [...prev.internal, mappedInternal] : prev.internal,
        }))
      }
      setExternalMeetingTitle("")
      setExternalMeetingPlatform("")
      setExternalMeetingStartsAt("")
      setExternalMeetingStartTime("")
      setExternalMeetingInternalStartsAt("")
      setExternalMeetingInternalStartTime("")
      setExternalMeetingCreateInternal(true)
      setExternalMeetingParticipantIds([])
      setExternalMeetingPersonsOpen(false)
      setExternalMeetingPersonSearch("")
      externalMeetingInternalStartsAtEditedRef.current = false
      externalMeetingInternalStartTimeEditedRef.current = false
      setExternalMeetingRecurrenceType("none")
      setExternalMeetingRecurrenceDaysOfWeek([])
      setExternalMeetingRecurrenceDaysOfMonth([])
      setExternalMeetingRecurrenceMonth("1")
      setExternalMeetingRecurrenceDay("1")
      setExternalMeetingCreateAgentTestTask(false)
      setExternalMeetingCreatePimImageTestTask(false)
      if (!shouldCreateAgentTestTask && !shouldCreatePimImageTestTask) {
        toast.success(externalMeetingCreateInternal ? "TAK EXT and TAK INT created." : "TAK EXT created.")
      }
      // Reset checklist after successful creation
      if (externalMeetingChecklist?.items) {
        const resetMap = new Map<string, boolean>()
        for (const item of externalMeetingChecklist.items) {
          resetMap.set(item.id, false)
        }
        setExternalMeetingChecklistItems(resetMap)
      }
    } finally {
      setCreatingExternalMeeting(false)
    }
  }, [
    apiFetch,
    externalMeetingTitle,
    externalMeetingPlatform,
    externalMeetingStartsAt,
    externalMeetingStartTime,
    externalMeetingInternalStartsAt,
    externalMeetingInternalStartTime,
    externalMeetingCreateInternal,
    externalMeetingParticipantIds,
    externalMeetingRecurrenceType,
    externalMeetingRecurrenceDaysOfWeek,
    externalMeetingRecurrenceDaysOfMonth,
    externalMeetingRecurrenceMonth,
    externalMeetingRecurrenceDay,
    externalMeetingCreateAgentTestTask,
    externalMeetingCreatePimImageTestTask,
    externalMeetingDepartmentId,
    user?.department_id,
    user?.email,
    user?.full_name,
    user?.username,
    formatTime,
    toISODate,
    externalMeetingChecklist,
    requestMeetingAvailability,
  ])

  const canEditExternalMeeting = React.useCallback((meeting: Meeting) => {
    if (!user) return false
    // Allow admin, manager, or the person that created it
    if (isAdmin || isManager) return true
    if (meeting.created_by && meeting.created_by === user.id) return true
    return false
  }, [user, isAdmin, isManager])

  const activeMeetingDetails = React.useMemo(
    () => externalMeetings.find((meeting) => meeting.id === meetingDetailsId)
      || internalMeetings.find((meeting) => meeting.id === meetingDetailsId)
      || null,
    [externalMeetings, internalMeetings, meetingDetailsId]
  )

  const openMeetingDetails = React.useCallback((meeting: Meeting) => {
    setMeetingDetailsId(meeting.id)
  }, [])

  const openMeetingDetailsById = React.useCallback((meetingId?: string) => {
    if (!meetingId) return
    const meeting = externalMeetings.find((candidate) => candidate.id === meetingId)
      || internalMeetings.find((candidate) => candidate.id === meetingId)
    if (meeting) openMeetingDetails(meeting)
  }, [externalMeetings, internalMeetings, openMeetingDetails])

  React.useEffect(() => {
    if (handledMeetingDeepLinkRef.current || typeof window === "undefined") return
    const meetingId = new URLSearchParams(window.location.search).get("meeting")
    if (!meetingId) return
    const meeting = externalMeetings.find((candidate) => candidate.id === meetingId)
      || internalMeetings.find((candidate) => candidate.id === meetingId)
    if (!meeting) return
    handledMeetingDeepLinkRef.current = true
    if (meeting.meeting_type === "internal") setInternalMeetingsOpen(true)
    else setExternalMeetingsOpen(true)
    openMeetingDetails(meeting)
  }, [externalMeetings, internalMeetings, openMeetingDetails])

  const closeMeetingDetails = React.useCallback(() => {
    if (savingMeetingDetails) return
    setMeetingDetailsId(null)
  }, [savingMeetingDetails])

  const saveMeetingDetails = React.useCallback(async (
    participantIds: string[],
    reminderMinutes: number | null,
  ) => {
    if (!meetingDetailsId) return
    setSavingMeetingDetails(true)
    try {
      const response = await apiFetch(`/meetings/${meetingDetailsId}/reminder-settings`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          participant_ids: participantIds,
          reminder_minutes_before: reminderMinutes,
        }),
      })
      if (!response.ok) {
        toast.error("Could not save PrimeFlow participants and reminder settings.")
        return
      }
      const updated = (await response.json()) as Meeting
      const meetingType = updated.meeting_type === "internal" ? "internal" : "external"
      if (meetingType === "internal") {
        setInternalMeetings((current) => current.map((meeting) => meeting.id === updated.id ? updated : meeting))
        syncCommonMeetingBucket("internal", [
          ...internalMeetings.filter((meeting) => meeting.id !== updated.id),
          updated,
        ])
      } else {
        setExternalMeetings((current) => current.map((meeting) => meeting.id === updated.id ? updated : meeting))
        syncCommonMeetingBucket("external", [
          ...externalMeetings.filter((meeting) => meeting.id !== updated.id),
          updated,
        ])
      }
      COMMON_VIEW_CACHE.clear()
      toast.success("Meeting participants and reminder saved.")
      setMeetingDetailsId(null)
    } catch (error) {
      console.error("Failed to save meeting reminder settings", error)
      toast.error("Could not save PrimeFlow participants and reminder settings.")
    } finally {
      setSavingMeetingDetails(false)
    }
  }, [
    apiFetch,
    externalMeetings,
    internalMeetings,
    meetingDetailsId,
    syncCommonMeetingBucket,
  ])

  const canManageMeetingParticipants = React.useCallback((meeting: Meeting) => {
    if (!user) return false
    if (isAdmin || isManager) return true
    if (meeting.created_by === user.id) return true
    return Boolean(user.department_id && user.department_id === meeting.department_id)
  }, [isAdmin, isManager, user])

  const startLinkedInternalMeeting = React.useCallback((meeting: Meeting) => {
    setInternalMeetingPairExternalId(meeting.id)
    setInternalMeetingPairExternalTitle(meeting.title || "External meeting")
    setInternalMeetingTitle(meeting.title || "")
    setInternalMeetingPlatform(meeting.platform || "")
    setInternalMeetingDepartmentId(meeting.department_id || "")
    setInternalMeetingParticipantIds(meeting.participant_ids || [])
    setExternalMeetingsOpen(false)
    setInternalMeetingsOpen(true)
  }, [])

  const startEditExternalMeeting = React.useCallback((meeting: Meeting) => {
    if (!canEditExternalMeeting(meeting)) return
    setEditingExternalMeetingId(meeting.id)
    setEditingExternalMeetingTitle(meeting.title || "")
    setEditingExternalMeetingPlatform(meeting.platform || "")
    if (meeting.starts_at) {
      const date = new Date(meeting.starts_at)
      const localDateTime = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
        .toISOString()
        .slice(0, 16)
      setEditingExternalMeetingStartsAt(localDateTime)
      setEditingExternalMeetingStartTime(toMeetingTimeValue(meeting.starts_at))
    } else {
      setEditingExternalMeetingStartsAt("")
      setEditingExternalMeetingStartTime("")
    }
    setEditingExternalMeetingRecurrenceType(
      (meeting.recurrence_type as "none" | "weekly" | "monthly" | "yearly") || "none"
    )
    setEditingExternalMeetingRecurrenceDaysOfWeek(meeting.recurrence_days_of_week || [])
    setEditingExternalMeetingRecurrenceDaysOfMonth(meeting.recurrence_days_of_month || [])
    if (meeting.starts_at) {
      const startDate = new Date(meeting.starts_at)
      if (!Number.isNaN(startDate.getTime())) {
        setEditingExternalMeetingRecurrenceMonth(String(startDate.getMonth() + 1))
        setEditingExternalMeetingRecurrenceDay(String(startDate.getDate()))
      }
    }
    setShowEditWeekendDays(
      (meeting.recurrence_days_of_week || []).some((day) => day >= 5)
    )
    setEditingExternalMeetingDepartmentId(meeting.department_id || "")
    setEditingExternalMeetingParticipantIds(meeting.participant_ids || [])
  }, [canEditExternalMeeting])

  const cancelEditExternalMeeting = React.useCallback(() => {
    setEditingExternalMeetingId(null)
    setEditingExternalMeetingTitle("")
    setEditingExternalMeetingPlatform("")
    setEditingExternalMeetingStartsAt("")
    setEditingExternalMeetingStartTime("")
    setEditingExternalMeetingRecurrenceType("none")
    setEditingExternalMeetingRecurrenceDaysOfWeek([])
    setEditingExternalMeetingRecurrenceDaysOfMonth([])
    setEditingExternalMeetingRecurrenceMonth("1")
    setEditingExternalMeetingRecurrenceDay("1")
    setEditingExternalMeetingDepartmentId("")
    setEditingExternalMeetingParticipantIds([])
    setEditingExternalMeetingPersonsOpen(false)
    setEditingExternalMeetingPersonSearch("")
    setShowEditWeekendDays(false)
  }, [])

  const saveExternalMeeting = React.useCallback(async () => {
    if (!editingExternalMeetingId || !editingExternalMeetingTitle.trim()) return
    setUpdatingExternalMeeting(true)
    try {
      let startsAt: string | null = null
      if (editingExternalMeetingRecurrenceType === "none") {
        startsAt = editingExternalMeetingStartsAt
          ? new Date(editingExternalMeetingStartsAt).toISOString()
          : null
      } else {
        if (!editingExternalMeetingStartTime) {
          toast.error("Time is required for recurring meetings.")
          return
        }
        if (editingExternalMeetingRecurrenceType === "weekly" && editingExternalMeetingRecurrenceDaysOfWeek.length === 0) {
          toast.error("Select at least one day.")
          return
        }
        if (editingExternalMeetingRecurrenceType === "monthly" && editingExternalMeetingRecurrenceDaysOfMonth.length === 0) {
          toast.error("Select at least one day.")
          return
        }
        if (editingExternalMeetingRecurrenceType === "yearly") {
          if (!editingExternalMeetingRecurrenceMonth || !editingExternalMeetingRecurrenceDay) {
            toast.error("Select month and date.")
            return
          }
        }
        const next = computeNextOccurrenceDate({
          recurrenceType: editingExternalMeetingRecurrenceType,
          daysOfWeek: editingExternalMeetingRecurrenceDaysOfWeek,
          daysOfMonth:
            editingExternalMeetingRecurrenceType === "yearly"
              ? [Number(editingExternalMeetingRecurrenceDay)]
              : editingExternalMeetingRecurrenceDaysOfMonth,
          timeValue: editingExternalMeetingStartTime,
          monthOfYear:
            editingExternalMeetingRecurrenceType === "yearly"
              ? Math.max(0, Math.min(11, Number(editingExternalMeetingRecurrenceMonth) - 1))
              : undefined,
        })
        if (!next) {
          toast.error("Failed to compute next occurrence.")
          return
        }
        startsAt = next.toISOString()
      }
      const payload = {
        title: editingExternalMeetingTitle.trim(),
        platform: editingExternalMeetingPlatform.trim() || null,
        starts_at: startsAt,
        meeting_type: "external",
        recurrence_type: editingExternalMeetingRecurrenceType === "none" ? null : editingExternalMeetingRecurrenceType,
        recurrence_days_of_week:
          editingExternalMeetingRecurrenceType === "weekly" && editingExternalMeetingRecurrenceDaysOfWeek.length > 0
            ? editingExternalMeetingRecurrenceDaysOfWeek
            : null,
        recurrence_days_of_month:
          editingExternalMeetingRecurrenceType === "monthly" && editingExternalMeetingRecurrenceDaysOfMonth.length > 0
            ? editingExternalMeetingRecurrenceDaysOfMonth
            : editingExternalMeetingRecurrenceType === "yearly" && editingExternalMeetingRecurrenceDay
              ? [Number(editingExternalMeetingRecurrenceDay)]
              : null,
        department_id: editingExternalMeetingDepartmentId || null,
        participant_ids: editingExternalMeetingParticipantIds,
      }
      const res = await apiFetch(`/meetings/${editingExternalMeetingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res?.ok) {
        console.error("Failed to update meeting", res?.status)
        toast.error("Failed to update meeting. Only admins, managers, and the meeting creator can edit meetings.")
        return
      }
      const updated = (await res.json()) as Meeting
      setExternalMeetings((prev) =>
        prev.map((m) => (m.id === editingExternalMeetingId ? updated : m))
      )
      COMMON_VIEW_CACHE.clear()
      cancelEditExternalMeeting()
      // Reload external meetings to update the list
      const meetingsBase = commonDepartmentId
        ? `/meetings?department_id=${encodeURIComponent(commonDepartmentId)}`
        : "/meetings?include_all_departments=true"
      const meetingsRes = await apiFetch(`${meetingsBase}&meeting_type=external`)
      if (meetingsRes?.ok) {
        const meetings = (await meetingsRes.json()) as Meeting[]
        setExternalMeetings(meetings)
        syncCommonMeetingBucket("external", meetings)
      }
    } catch (err) {
      console.error("Error updating meeting:", err)
      toast.error("Failed to update meeting. Please try again.")
    } finally {
      setUpdatingExternalMeeting(false)
    }
  }, [
    editingExternalMeetingId,
    editingExternalMeetingTitle,
    editingExternalMeetingPlatform,
    editingExternalMeetingStartsAt,
    editingExternalMeetingStartTime,
    editingExternalMeetingRecurrenceType,
    editingExternalMeetingRecurrenceDaysOfWeek,
    editingExternalMeetingRecurrenceDaysOfMonth,
    editingExternalMeetingRecurrenceMonth,
    editingExternalMeetingRecurrenceDay,
    editingExternalMeetingDepartmentId,
    editingExternalMeetingParticipantIds,
    commonDepartmentId,
    apiFetch,
    cancelEditExternalMeeting,
    syncCommonMeetingBucket,
  ])

  const deleteExternalMeeting = React.useCallback(
    async (meetingId: string) => {
      if (!isAdmin) return
      const confirmed = await confirm({
        title: "Delete external meeting",
        description: "Delete this external meeting? This action cannot be undone.",
        confirmLabel: "Delete",
        variant: "destructive",
      })
      if (!confirmed) return
      setDeletingExternalMeetingId(meetingId)
      try {
        const res = await apiFetch(`/meetings/${meetingId}`, {
          method: "DELETE",
        })
        if (!res?.ok) {
          console.error("Failed to delete meeting", res?.status)
          toast.error("Failed to delete meeting. Only admins can delete meetings.")
          return
        }
        COMMON_VIEW_CACHE.clear()
        setExternalMeetings((prev) => prev.filter((m) => m.id !== meetingId))
        // Reload external meetings to update the list
        const meetingsBase = commonDepartmentId
          ? `/meetings?department_id=${encodeURIComponent(commonDepartmentId)}`
          : "/meetings?include_all_departments=true"
        const meetingsRes = await apiFetch(`${meetingsBase}&meeting_type=external`)
        if (meetingsRes?.ok) {
          const meetings = (await meetingsRes.json()) as Meeting[]
          setExternalMeetings(meetings)
          syncCommonMeetingBucket("external", meetings)
        }
      } catch (err) {
        console.error("Error deleting meeting:", err)
        toast.error("Failed to delete meeting. Please try again.")
      } finally {
        setDeletingExternalMeetingId(null)
      }
    },
    [isAdmin, apiFetch, commonDepartmentId, confirm, syncCommonMeetingBucket]
  )

  const createAgentTestTaskForExternalMeeting = React.useCallback(
    async (meetingId: string) => {
      if (!isAdmin && !isManager) return
      setCreatingAgentTestTaskMeetingId(meetingId)
      try {
        const res = await apiFetch(`/meetings/${meetingId}/agent-test-task`, {
          method: "POST",
        })
        if (!res?.ok) {
          const detail = await res
            .json()
            .then((body) => (typeof body?.detail === "string" ? body.detail : null))
            .catch(() => null)
          toast.error(detail || "Failed to create Testimi i agentave task.")
          return
        }
        const updated = (await res.json()) as Meeting
        COMMON_VIEW_CACHE.clear()
        setExternalMeetings((prev) => {
          const next = prev.map((meeting) => (meeting.id === updated.id ? updated : meeting))
          syncCommonMeetingBucket("external", next)
          return next
        })
        toast.success("Testimi i agentave task created.")
      } catch (err) {
        console.error("Error creating agent test task:", err)
        toast.error("Failed to create Testimi i agentave task.")
      } finally {
        setCreatingAgentTestTaskMeetingId(null)
      }
    },
    [apiFetch, isAdmin, isManager, syncCommonMeetingBucket]
  )

  const createPimImageTestTaskForExternalMeeting = React.useCallback(
    async (meetingId: string) => {
      if (!isAdmin && !isManager) return
      setCreatingPimImageTestTaskMeetingId(meetingId)
      try {
        const res = await apiFetch(`/meetings/${meetingId}/pim-image-test-task`, {
          method: "POST",
        })
        if (!res?.ok) {
          const detail = await res
            .json()
            .then((body) => (typeof body?.detail === "string" ? body.detail : null))
            .catch(() => null)
          toast.error(detail || "Failed to create Testimi i PIM image task.")
          return
        }
        const updated = (await res.json()) as Meeting
        COMMON_VIEW_CACHE.clear()
        setExternalMeetings((prev) => {
          const next = prev.map((meeting) => (meeting.id === updated.id ? updated : meeting))
          syncCommonMeetingBucket("external", next)
          return next
        })
        toast.success("Testimi i PIM image task created for Graphic Design.")
      } catch (err) {
        console.error("Error creating PIM image test task:", err)
        toast.error("Failed to create Testimi i PIM image task.")
      } finally {
        setCreatingPimImageTestTaskMeetingId(null)
      }
    },
    [apiFetch, isAdmin, isManager, syncCommonMeetingBucket]
  )

  const internalMeetingProposedStart = React.useMemo(() => {
    if (internalMeetingRecurrenceType === "none") {
      if (!internalMeetingStartsAt) return null
      const value = new Date(internalMeetingStartsAt)
      return Number.isNaN(value.getTime()) ? null : value
    }
    if (!internalMeetingStartTime) return null
    return computeNextOccurrenceDate({
      recurrenceType: internalMeetingRecurrenceType,
      daysOfWeek: internalMeetingRecurrenceDaysOfWeek,
      daysOfMonth: internalMeetingRecurrenceType === "yearly"
        ? [Number(internalMeetingRecurrenceDay)]
        : internalMeetingRecurrenceDaysOfMonth,
      timeValue: internalMeetingStartTime,
      monthOfYear: internalMeetingRecurrenceType === "yearly"
        ? Math.max(0, Math.min(11, Number(internalMeetingRecurrenceMonth) - 1))
        : undefined,
    })
  }, [
    internalMeetingRecurrenceDay,
    internalMeetingRecurrenceDaysOfMonth,
    internalMeetingRecurrenceDaysOfWeek,
    internalMeetingRecurrenceMonth,
    internalMeetingRecurrenceType,
    internalMeetingStartTime,
    internalMeetingStartsAt,
  ])

  React.useEffect(() => {
    const departmentId = internalMeetingDepartmentId || user?.department_id || ""
    if (!internalMeetingProposedStart || !departmentId || !internalMeetingParticipantIds.length) {
      setInternalMeetingAvailability(null)
      return
    }
    let active = true
    const timeout = window.setTimeout(() => {
      setCheckingInternalMeetingAvailability(true)
      void requestMeetingAvailability({
        title: internalMeetingTitle,
        meetingType: "internal",
        startsAt: internalMeetingProposedStart,
        departmentId,
        participantIds: internalMeetingParticipantIds,
      }).then((result) => {
        if (active) setInternalMeetingAvailability(result)
      }).finally(() => {
        if (active) setCheckingInternalMeetingAvailability(false)
      })
    }, 450)
    return () => {
      active = false
      window.clearTimeout(timeout)
    }
  }, [
    internalMeetingDepartmentId,
    internalMeetingParticipantIds,
    internalMeetingProposedStart,
    internalMeetingTitle,
    requestMeetingAvailability,
    user?.department_id,
  ])

  const findInternalMeetingParticipantConflicts = React.useCallback(
    (proposedStart: Date): InternalMeetingParticipantConflict[] => {
      if (Number.isNaN(proposedStart.getTime())) return []

      const meetingDurationMinutes = 30
      const proposedEnd = new Date(proposedStart.getTime() + meetingDurationMinutes * 60 * 1000)
      const dateKey = (value: Date) =>
        `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`
      const targetDate = dateKey(proposedStart)
      const meetingMinute = proposedStart.getHours() * 60 + proposedStart.getMinutes()
      const meetingEndMinute = meetingMinute + meetingDurationMinutes
      const selectedParticipantIds = new Set(internalMeetingParticipantIds)
      const conflicts = new Map<string, InternalMeetingParticipantConflict>()

      const displayName = (participant: User) =>
        participant.full_name || participant.username || participant.email || "Unknown user"
      const selectedUsers = internalMeetingParticipantIds
        .map((participantId) => users.find((candidate) => candidate.id === participantId))
        .filter((participant): participant is User => Boolean(participant))
      const addConflict = (participant: User, reason: string) => {
        const current = conflicts.get(participant.id) || {
          userId: participant.id,
          userName: displayName(participant),
          reasons: [],
        }
        if (!current.reasons.includes(reason)) current.reasons.push(reason)
        conflicts.set(participant.id, current)
      }
      const entryMatchesUser = (
        entry: { userId?: string; person?: string },
        participant: User
      ) => {
        if (entry.userId && entry.userId === participant.id) return true
        const person = (entry.person || "").trim().toLocaleLowerCase()
        if (!person) return false
        return [participant.full_name, participant.username, participant.email]
          .some((value) => (value || "").trim().toLocaleLowerCase() === person)
      }
      const timeRangeCovers = (
        from: string | undefined,
        to: string | undefined,
        defaultFrom: string,
        defaultTo: string
      ) => {
        const fromMinute = parseTimeToMinutes(from) ?? parseTimeToMinutes(defaultFrom)
        const toMinute = parseTimeToMinutes(to) ?? parseTimeToMinutes(defaultTo)
        if (fromMinute == null || toMinute == null) return true
        return fromMinute < meetingEndMinute && meetingMinute < toMinute
      }
      const rangeLabel = (from?: string, to?: string) =>
        from && to ? `${from}–${to}` : "gjithë ditën"
      const clockLabel = (value: Date) =>
        `${String(value.getHours()).padStart(2, "0")}:${String(value.getMinutes()).padStart(2, "0")}`

      for (const participant of selectedUsers) {
        for (const leave of commonData.leave) {
          if (targetDate < leave.startDate || targetDate > leave.endDate) continue
          if (!leave.isAllUsers && !entryMatchesUser(leave, participant)) continue
          if (
            leave.fullDay
            || timeRangeCovers(leave.from, leave.to, "00:00", "23:59")
          ) {
            addConflict(
              participant,
              `PV/FESTË — ${leave.fullDay ? "gjithë ditën" : rangeLabel(leave.from, leave.to)}`
            )
          }
        }
        for (const absence of commonData.absent) {
          if (absence.date !== targetDate || !entryMatchesUser(absence, participant)) continue
          if (timeRangeCovers(absence.from, absence.to, "08:00", "23:00")) {
            addConflict(participant, `Mungesë — ${rangeLabel(absence.from, absence.to)}`)
          }
        }
        for (const late of commonData.late) {
          if (late.date !== targetDate || !entryMatchesUser(late, participant)) continue
          if (timeRangeCovers(late.start, late.until, "08:00", "09:00")) {
            addConflict(participant, `Vonesë — deri në ${late.until || "09:00"}`)
          }
        }
        for (const holiday of commonData.externalHoliday) {
          if (holiday.date === targetDate) {
            addConflict(participant, `Festë zyrtare — ${holiday.title}`)
          }
        }
      }

      const meetingsToCheck = [
        ...internalMeetings.map((meeting) => ({ meeting, label: "TAK INT" })),
        ...externalMeetings.map((meeting) => ({ meeting, label: "TAK EXT" })),
      ]
      for (const { meeting, label } of meetingsToCheck) {
        if (
          !meeting.starts_at
          || meeting.calendar_sync_status === "cancelled"
          || !(meeting.participant_ids || []).some((participantId) => selectedParticipantIds.has(participantId))
        ) {
          continue
        }
        const sourceStart = new Date(meeting.starts_at)
        if (Number.isNaN(sourceStart.getTime())) continue
        const recurrence = (meeting.recurrence_type || "none").toLocaleLowerCase()
        const mondayBasedWeekday = (proposedStart.getDay() + 6) % 7
        const occursOnDate = recurrence === "weekly"
          ? Boolean(meeting.recurrence_days_of_week?.includes(mondayBasedWeekday))
          : recurrence === "monthly"
            ? Boolean(meeting.recurrence_days_of_month?.includes(proposedStart.getDate()))
            : recurrence === "yearly"
              ? sourceStart.getMonth() === proposedStart.getMonth()
                && (meeting.recurrence_days_of_month?.[0] || sourceStart.getDate()) === proposedStart.getDate()
              : dateKey(sourceStart) === targetDate
        if (!occursOnDate) continue

        const occurrenceStart = new Date(
          proposedStart.getFullYear(),
          proposedStart.getMonth(),
          proposedStart.getDate(),
          sourceStart.getHours(),
          sourceStart.getMinutes(),
          0,
          0
        )
        const sourceEnd = meeting.ends_at ? new Date(meeting.ends_at) : null
        const externalDurationMs = label === "TAK EXT" && sourceEnd
          ? sourceEnd.getTime() - sourceStart.getTime()
          : 0
        const durationMs = externalDurationMs > 0
          ? externalDurationMs
          : meetingDurationMinutes * 60 * 1000
        const occurrenceEnd = new Date(occurrenceStart.getTime() + durationMs)
        if (!(proposedStart < occurrenceEnd && occurrenceStart < proposedEnd)) continue
        if (meetingOccurrenceStatuses.get(occurrenceStatusKey(meeting.id, targetDate))?.status === "canceled") {
          continue
        }

        for (const participantId of meeting.participant_ids || []) {
          if (!selectedParticipantIds.has(participantId)) continue
          const participant = users.find((candidate) => candidate.id === participantId)
          if (!participant) continue
          addConflict(
            participant,
            `Në ${label} “${meeting.title}” (${clockLabel(occurrenceStart)}–${clockLabel(occurrenceEnd)})`
          )
        }
      }

      return internalMeetingParticipantIds
        .map((participantId) => conflicts.get(participantId))
        .filter((conflict): conflict is InternalMeetingParticipantConflict => Boolean(conflict))
    },
    [
      commonData.absent,
      commonData.externalHoliday,
      commonData.late,
      commonData.leave,
      externalMeetings,
      internalMeetingParticipantIds,
      internalMeetings,
      meetingOccurrenceStatuses,
      occurrenceStatusKey,
      parseTimeToMinutes,
      users,
    ]
  )


  const submitInternalMeeting = React.useCallback(async () => {
    if (!internalMeetingTitle.trim()) return
    if (!internalMeetingParticipantIds.length) {
      toast.error("Select at least one person for the meeting.")
      return
    }
    const departmentId = internalMeetingDepartmentId || user?.department_id
    if (!departmentId) {
      console.error("Department is required to create a meeting.")
      return
    }
    setCreatingInternalMeeting(true)
    try {
      let startsAt: string | null = null
      if (internalMeetingRecurrenceType === "none") {
        if (!internalMeetingStartsAt) {
          toast.error("Date and time are required for the meeting.")
          return
        }
        startsAt = new Date(internalMeetingStartsAt).toISOString()
      } else {
        if (!internalMeetingStartTime) {
          toast.error("Time is required for recurring meetings.")
          return
        }
        if (internalMeetingRecurrenceType === "weekly" && internalMeetingRecurrenceDaysOfWeek.length === 0) {
          toast.error("Select at least one day.")
          return
        }
        if (internalMeetingRecurrenceType === "monthly" && internalMeetingRecurrenceDaysOfMonth.length === 0) {
          toast.error("Select at least one day.")
          return
        }
        if (internalMeetingRecurrenceType === "yearly") {
          if (!internalMeetingRecurrenceMonth || !internalMeetingRecurrenceDay) {
            toast.error("Select month and date.")
            return
          }
        }
        const next = computeNextOccurrenceDate({
          recurrenceType: internalMeetingRecurrenceType,
          daysOfWeek: internalMeetingRecurrenceDaysOfWeek,
          daysOfMonth:
            internalMeetingRecurrenceType === "yearly"
              ? [Number(internalMeetingRecurrenceDay)]
              : internalMeetingRecurrenceDaysOfMonth,
          timeValue: internalMeetingStartTime,
          monthOfYear:
            internalMeetingRecurrenceType === "yearly"
              ? Math.max(0, Math.min(11, Number(internalMeetingRecurrenceMonth) - 1))
              : undefined,
        })
        if (!next) {
          toast.error("Failed to compute next occurrence.")
          return
        }
        startsAt = next.toISOString()
      }
      const participantConflicts = findInternalMeetingParticipantConflicts(new Date(startsAt))
      const availability = await requestMeetingAvailability({
        title: internalMeetingTitle,
        meetingType: "internal",
        startsAt: new Date(startsAt),
        departmentId,
        participantIds: internalMeetingParticipantIds,
      })
      const oneHConflicts = availability?.conflicts.filter((conflict) => conflict.source === "one_h") || []
      let allowOneHConflict = false
      if (oneHConflicts.length) {
        setInternalMeetingAvailability(availability)
      }
      if (participantConflicts.length || oneHConflicts.length) {
        const approved = await confirm({
          title: participantConflicts.length ? "Konflikte për pjesëmarrësit" : "Konflikt me orarin 1H",
          description: (
            <span className="block space-y-3 text-left">
              {oneHConflicts.length > 0 && (
                <span className="block rounded-md border border-red-200 bg-red-50 px-3 py-2 text-red-950">
                  Ky orar përputhet me 1H.
                </span>
              )}
              {participantConflicts.length > 0 && (
                <span className="block">
                  Personat e mëposhtëm nuk janë të lirë në orarin e zgjedhur. Kontrolloji para se të vazhdosh.
                </span>
              )}
              {participantConflicts.map((conflict) => (
                <span
                  key={conflict.userId}
                  className="block rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-amber-950"
                >
                  <strong className="block">{conflict.userName}</strong>
                  {conflict.reasons.map((reason) => (
                    <span key={reason} className="mt-1 block text-xs">
                      • {reason}
                    </span>
                  ))}
                </span>
              ))}
              <span className="block text-xs text-slate-500">
                “Aprovo gjithsesi” e krijon takimin me këta persona; “Ndrysho” e mban formularin hapur.
              </span>
            </span>
          ),
          confirmLabel: "Aprovo gjithsesi",
          cancelLabel: "Ndrysho",
        })
        if (!approved) return
        allowOneHConflict = oneHConflicts.length > 0
      }
      const payload = {
        title: internalMeetingTitle.trim(),
        platform: internalMeetingPlatform.trim() || null,
        starts_at: startsAt,
        meeting_type: "internal",
        recurrence_type: internalMeetingRecurrenceType === "none" ? null : internalMeetingRecurrenceType,
        recurrence_days_of_week:
          internalMeetingRecurrenceType === "weekly" && internalMeetingRecurrenceDaysOfWeek.length > 0
            ? internalMeetingRecurrenceDaysOfWeek
            : null,
        recurrence_days_of_month:
          internalMeetingRecurrenceType === "monthly" && internalMeetingRecurrenceDaysOfMonth.length > 0
            ? internalMeetingRecurrenceDaysOfMonth
            : internalMeetingRecurrenceType === "yearly" && internalMeetingRecurrenceDay
              ? [Number(internalMeetingRecurrenceDay)]
              : null,
        department_id: departmentId,
        project_id: null,
        participant_ids: internalMeetingParticipantIds,
        paired_external_meeting_id: internalMeetingPairExternalId,
        allow_one_h_conflict: allowOneHConflict,
      }
      const res = await apiFetch("/meetings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res?.ok) {
        const body = await res.json().catch(() => null)
        const message = body?.detail?.message || body?.detail || "Failed to create meeting."
        toast.error(typeof message === "string" ? message : "Failed to create meeting.")
        console.error("Failed to create meeting", res?.status)
        return
      }
      const created = (await res.json()) as Meeting
      setInternalMeetings((prev) => [created, ...prev])
      COMMON_VIEW_CACHE.clear()
      const ownerName = user?.full_name || user?.username || user?.email || "Unknown"
      const linkedExternalMeeting = internalMeetingPairExternalId
        ? externalMeetings.find((meeting) => meeting.id === internalMeetingPairExternalId) || null
        : null
      const mapped = mapMeetingToCommonItem(created, "internal", ownerName, linkedExternalMeeting)
      if (mapped) {
        setCommonData((prev) => ({
          ...prev,
          internal: [...prev.internal, mapped],
        }))
      }
      setInternalMeetingTitle("")
      setInternalMeetingPlatform("")
      setInternalMeetingStartsAt("")
      setInternalMeetingStartTime("")
      setInternalMeetingRecurrenceType("none")
      setInternalMeetingRecurrenceDaysOfWeek([])
      setInternalMeetingRecurrenceDaysOfMonth([])
      setInternalMeetingRecurrenceMonth("1")
      setInternalMeetingRecurrenceDay("1")
      setInternalMeetingParticipantIds([])
      setInternalMeetingPairExternalId(null)
      setInternalMeetingPairExternalTitle("")
      setInternalMeetingPersonsOpen(false)
      setInternalMeetingPersonSearch("")
      setInternalMeetingAvailability(null)
    } finally {
      setCreatingInternalMeeting(false)
    }
  }, [
    apiFetch,
    internalMeetingTitle,
    internalMeetingPlatform,
    internalMeetingStartsAt,
    internalMeetingStartTime,
    internalMeetingRecurrenceType,
    internalMeetingRecurrenceDaysOfWeek,
    internalMeetingRecurrenceDaysOfMonth,
    internalMeetingRecurrenceMonth,
    internalMeetingRecurrenceDay,
    internalMeetingDepartmentId,
    internalMeetingParticipantIds,
    internalMeetingPairExternalId,
    confirm,
    externalMeetings,
    findInternalMeetingParticipantConflicts,
    requestMeetingAvailability,
    user?.department_id,
    user?.email,
    user?.full_name,
    user?.username,
    mapMeetingToCommonItem,
  ])

  const canEditInternalMeeting = React.useCallback((meeting: Meeting) => {
    if (!user) return false
    if (isAdmin || isManager) return true
    if (meeting.created_by && meeting.created_by === user.id) return true
    return false
  }, [user, isAdmin, isManager])

  const startEditInternalMeeting = React.useCallback((meeting: Meeting) => {
    if (!canEditInternalMeeting(meeting)) return
    setEditingInternalMeetingId(meeting.id)
    setEditingInternalMeetingTitle(meeting.title || "")
    setEditingInternalMeetingPlatform(meeting.platform || "")
    if (meeting.starts_at) {
      const date = new Date(meeting.starts_at)
      const localDateTime = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
        .toISOString()
        .slice(0, 16)
      setEditingInternalMeetingStartsAt(localDateTime)
      setEditingInternalMeetingStartTime(toMeetingTimeValue(meeting.starts_at))
    } else {
      setEditingInternalMeetingStartsAt("")
      setEditingInternalMeetingStartTime("")
    }
    setEditingInternalMeetingRecurrenceType(
      (meeting.recurrence_type as "none" | "weekly" | "monthly" | "yearly") || "none"
    )
    setEditingInternalMeetingRecurrenceDaysOfWeek(meeting.recurrence_days_of_week || [])
    setEditingInternalMeetingRecurrenceDaysOfMonth(meeting.recurrence_days_of_month || [])
    if (meeting.starts_at) {
      const startDate = new Date(meeting.starts_at)
      if (!Number.isNaN(startDate.getTime())) {
        setEditingInternalMeetingRecurrenceMonth(String(startDate.getMonth() + 1))
        setEditingInternalMeetingRecurrenceDay(String(startDate.getDate()))
      }
    }
    setShowInternalEditWeekendDays(
      (meeting.recurrence_days_of_week || []).some((day) => day >= 5)
    )
    setEditingInternalMeetingDepartmentId(meeting.department_id || "")
  }, [canEditInternalMeeting])

  const cancelEditInternalMeeting = React.useCallback(() => {
    setEditingInternalMeetingId(null)
    setEditingInternalMeetingTitle("")
    setEditingInternalMeetingPlatform("")
    setEditingInternalMeetingStartsAt("")
    setEditingInternalMeetingStartTime("")
    setEditingInternalMeetingRecurrenceType("none")
    setEditingInternalMeetingRecurrenceDaysOfWeek([])
    setEditingInternalMeetingRecurrenceDaysOfMonth([])
    setEditingInternalMeetingRecurrenceMonth("1")
    setEditingInternalMeetingRecurrenceDay("1")
    setEditingInternalMeetingDepartmentId("")
    setShowInternalEditWeekendDays(false)
  }, [])

  const saveInternalMeeting = React.useCallback(async () => {
    if (!editingInternalMeetingId || !editingInternalMeetingTitle.trim()) return
    setUpdatingInternalMeeting(true)
    try {
      let startsAt: string | null = null
      if (editingInternalMeetingRecurrenceType === "none") {
        startsAt = editingInternalMeetingStartsAt
          ? new Date(editingInternalMeetingStartsAt).toISOString()
          : null
      } else {
        if (!editingInternalMeetingStartTime) {
          toast.error("Time is required for recurring meetings.")
          return
        }
        if (editingInternalMeetingRecurrenceType === "weekly" && editingInternalMeetingRecurrenceDaysOfWeek.length === 0) {
          toast.error("Select at least one day.")
          return
        }
        if (editingInternalMeetingRecurrenceType === "monthly" && editingInternalMeetingRecurrenceDaysOfMonth.length === 0) {
          toast.error("Select at least one day.")
          return
        }
        if (editingInternalMeetingRecurrenceType === "yearly") {
          if (!editingInternalMeetingRecurrenceMonth || !editingInternalMeetingRecurrenceDay) {
            toast.error("Select month and date.")
            return
          }
        }
        const next = computeNextOccurrenceDate({
          recurrenceType: editingInternalMeetingRecurrenceType,
          daysOfWeek: editingInternalMeetingRecurrenceDaysOfWeek,
          daysOfMonth:
            editingInternalMeetingRecurrenceType === "yearly"
              ? [Number(editingInternalMeetingRecurrenceDay)]
              : editingInternalMeetingRecurrenceDaysOfMonth,
          timeValue: editingInternalMeetingStartTime,
          monthOfYear:
            editingInternalMeetingRecurrenceType === "yearly"
              ? Math.max(0, Math.min(11, Number(editingInternalMeetingRecurrenceMonth) - 1))
              : undefined,
        })
        if (!next) {
          toast.error("Failed to compute next occurrence.")
          return
        }
        startsAt = next.toISOString()
      }
      const payload = {
        title: editingInternalMeetingTitle.trim(),
        platform: editingInternalMeetingPlatform.trim() || null,
        starts_at: startsAt,
        meeting_type: "internal",
        recurrence_type: editingInternalMeetingRecurrenceType === "none" ? null : editingInternalMeetingRecurrenceType,
        recurrence_days_of_week:
          editingInternalMeetingRecurrenceType === "weekly" && editingInternalMeetingRecurrenceDaysOfWeek.length > 0
            ? editingInternalMeetingRecurrenceDaysOfWeek
            : null,
        recurrence_days_of_month:
          editingInternalMeetingRecurrenceType === "monthly" && editingInternalMeetingRecurrenceDaysOfMonth.length > 0
            ? editingInternalMeetingRecurrenceDaysOfMonth
            : editingInternalMeetingRecurrenceType === "yearly" && editingInternalMeetingRecurrenceDay
              ? [Number(editingInternalMeetingRecurrenceDay)]
              : null,
        department_id: editingInternalMeetingDepartmentId || null,
      }
      const res = await apiFetch(`/meetings/${editingInternalMeetingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res?.ok) {
        console.error("Failed to update meeting", res?.status)
        toast.error("Failed to update meeting. Only admins, managers, and the meeting creator can edit meetings.")
        return
      }
      const updated = (await res.json()) as Meeting
      setInternalMeetings((prev) =>
        prev.map((m) => (m.id === editingInternalMeetingId ? updated : m))
      )
      COMMON_VIEW_CACHE.clear()
      cancelEditInternalMeeting()
      const meetingsBase = commonDepartmentId
        ? `/meetings?department_id=${encodeURIComponent(commonDepartmentId)}`
        : "/meetings?include_all_departments=true"
      const meetingsRes = await apiFetch(`${meetingsBase}&meeting_type=internal`)
      if (meetingsRes?.ok) {
        const meetings = (await meetingsRes.json()) as Meeting[]
        setInternalMeetings(meetings)
        syncCommonMeetingBucket("internal", meetings)
      }
    } catch (err) {
      console.error("Error updating meeting:", err)
      toast.error("Failed to update meeting. Please try again.")
    } finally {
      setUpdatingInternalMeeting(false)
    }
  }, [
    editingInternalMeetingId,
    editingInternalMeetingTitle,
    editingInternalMeetingPlatform,
    editingInternalMeetingStartsAt,
    editingInternalMeetingStartTime,
    editingInternalMeetingRecurrenceType,
    editingInternalMeetingRecurrenceDaysOfWeek,
    editingInternalMeetingRecurrenceDaysOfMonth,
    editingInternalMeetingRecurrenceMonth,
    editingInternalMeetingRecurrenceDay,
    editingInternalMeetingDepartmentId,
    commonDepartmentId,
    apiFetch,
    cancelEditInternalMeeting,
    syncCommonMeetingBucket,
  ])

  const deleteInternalMeeting = React.useCallback(
    async (meetingId: string) => {
      if (!isAdmin) return
      const confirmed = await confirm({
        title: "Delete internal meeting",
        description: "Delete this internal meeting? This action cannot be undone.",
        confirmLabel: "Delete",
        variant: "destructive",
      })
      if (!confirmed) return
      setDeletingInternalMeetingId(meetingId)
      try {
        const res = await apiFetch(`/meetings/${meetingId}`, {
          method: "DELETE",
        })
        if (!res?.ok) {
          console.error("Failed to delete meeting", res?.status)
          toast.error("Failed to delete meeting. Only admins can delete meetings.")
          return
        }
        COMMON_VIEW_CACHE.clear()
        setInternalMeetings((prev) => prev.filter((m) => m.id !== meetingId))
        const meetingsBase = commonDepartmentId
          ? `/meetings?department_id=${encodeURIComponent(commonDepartmentId)}`
          : "/meetings?include_all_departments=true"
        const meetingsRes = await apiFetch(`${meetingsBase}&meeting_type=internal`)
        if (meetingsRes?.ok) {
          const meetings = (await meetingsRes.json()) as Meeting[]
          setInternalMeetings(meetings)
          syncCommonMeetingBucket("internal", meetings)
        }
      } catch (err) {
        console.error("Error deleting meeting:", err)
        toast.error("Failed to delete meeting. Please try again.")
      } finally {
        setDeletingInternalMeetingId(null)
      }
    },
    [isAdmin, apiFetch, commonDepartmentId, confirm, syncCommonMeetingBucket]
  )

  const buildSwimlaneCells = (items: SwimlaneCell[], targetCount: number) => {
    const baseItems = items.length ? items : [{ title: "No data available.", placeholder: true }]
    const minimumCells = Math.max(3, Math.ceil(baseItems.length / 3) * 3)
    const totalCells = Math.max(minimumCells, targetCount)
    return [
      ...baseItems,
      ...Array.from({ length: totalCells - baseItems.length }, () => null),
    ]
  }

  const getSwimlaneDividerClass = React.useCallback(
    (rowId: CommonType, cells: Array<SwimlaneCell | null>, index: number) => {
      if (!isFastTaskRowId(rowId) || index === 0) return ""
      const currentCell = cells[index]
      const previousCell = cells[index - 1]
      if (!currentCell || currentCell.placeholder || !previousCell || previousCell.placeholder) return ""

      const currentUserKey = getSwimlaneTaskUserKey(currentCell)
      const previousUserKey = getSwimlaneTaskUserKey(previousCell)
      if (!currentUserKey || !previousUserKey || currentUserKey === previousUserKey) return ""

      return "swimlane-cell-user-break"
    },
    []
  )

  const swimlaneInfoText: Record<CommonType, string> = {
    late: "Vonese",
    absent: "Mungese",
    leave: "Pushim vjetor ose feste",
    externalHoliday: "Festa zyrtare / External holiday",
    waitingClient: "Detyra qe jane ne pritje te veprimit, informacionit ose konfirmimit nga klienti.",
    blocked: "JANE DETYRA ME PRIORITET TE LARTE MERRET VETËM ME ATË DETYRË ",
    oneH: "CDO DETYRE NGA GA KA STATUS 1H - THIRRET ÇDO 1 ORË NË TEAMS. THIRRET GA DHE PËRGJEGJËSAT. RAPORTOHET PROGRESI.",
    oneH10: "CDO DETYRE NGA GA KA STATUS 1H - THIRRET ÇDO 1 ORË NË TEAMS. THIRRET GA DHE PËRGJEGJËSAT. RAPORTOHET PROGRESI.",
    oneH11: "CDO DETYRE NGA GA KA STATUS 1H - THIRRET ÇDO 1 ORË NË TEAMS. THIRRET GA DHE PËRGJEGJËSAT. RAPORTOHET PROGRESI.",
    oneH1150: "CDO DETYRE NGA GA KA STATUS 1H - THIRRET ÇDO 1 ORË NË TEAMS. THIRRET GA DHE PËRGJEGJËSAT. RAPORTOHET PROGRESI.",
    oneH1420: "CDO DETYRE NGA GA KA STATUS 1H - THIRRET ÇDO 1 ORË NË TEAMS. THIRRET GA DHE PËRGJEGJËSAT. RAPORTOHET PROGRESI.",
    oneH1550: "CDO DETYRE NGA GA KA STATUS 1H - THIRRET ÇDO 1 ORË NË TEAMS. THIRRET GA DHE PËRGJEGJËSAT. RAPORTOHET PROGRESI.",
    oneHNoSlot: "DETYRA 1H QE NUK KANE SLOT TE CAKTUAR.",
    personal: "JANË DETYRA TË VENDOSURA NGA GA/KA DHE PERGJEGJESIT BARAZOHEMI VETËM ME TA ORA PËR BZ: 16:00",
    personalGA: "DETYRA PERSONALE ME GA.",
    personalKA: "DETYRA PERSONALE ME KA.",
    personalGENT: "DETYRA PERSONALE ME GENTIN.",
    personalPX: "DETYRA PERSONALE ME PX TJERË.",
    external: "Takime externe",
    internal: "Takime interne",
    r1: "DETYRË E RE. THIRRET ÇDO 1 ORË DERISA TË SQAROHET. PASI SQAROHET NDERROHET STATUSI NE 1H",
    problem: "Probleme",
    feedback: "Feedback Note",
    priority: "Projektet me prioritet- qe kane taska",
    diamond: "Review-t e përfunduara me diamant",
    bz: "Barazime - AM: 08:00-09:00/ 10:00-10:30/ 11:30-12:15 / PM:13:30-14:00/ 14:30-15:00 (VETEM PER URGJENCA)",
  }

  const toggleNewTaskCategoryFilter = (category: CommonTaskNewCategory) => {
    if (taskFocusFilter !== "new") {
      setNewTaskCategoryFilters(new Set([category]))
      setTaskFocusFilter("new")
      return
    }

    setTaskFocusFilter("new")
    setNewTaskCategoryFilters((previous) => {
      const next = new Set(previous)
      if (next.has(category)) {
        // Keep at least one category selected so the active filter never shows an accidental empty view.
        if (next.size > 1) next.delete(category)
      } else {
        next.add(category)
      }
      return next
    })
  }

  const swimlaneHeaderSubtext: Partial<Record<CommonType, string>> = {
    bz:
      "AM: 8-9/10-10:30/11:30-12:15/\nPM: 13:30-14/14:30-15 (URGJ)",
    oneH10: "10:00",
    oneH11: "11:00",
    oneH1150: "11:50",
    oneH1420: "14:20",
    oneH1550: "16:00",
    oneHNoSlot: "PA SLOT",
    r1:"AM: 08:50/10:00/11:00-11:50)\nPM: 14:30/16:00",
    blocked: "NUK PENGOHET.",
    ...PERSONAL_ROW_SCHEDULES,
    personal:"NGA GA/KA/\nPERGJEGJESIT BARAZOHEMI VETËM ME TA. BZ 16:00."
  }

  const toggleInfo = (rowId: CommonType) => {
    setOpenInfoId((prev) => (prev === rowId ? null : rowId))
  }

  const toggleSwimlaneTitleRow = (rowId: CommonType) => {
    setOpenSwimlaneTitleRows((prev) => {
      const next = new Set(prev)
      if (next.has(rowId)) {
        next.delete(rowId)
      } else {
        next.add(rowId)
      }
      return next
    })
  }

  const resetSwimlaneTitleRowsOpen = () => {
    setOpenSwimlaneTitleRows(new Set(DEFAULT_OPEN_SWIMLANE_TITLE_ROWS))
  }

  React.useEffect(() => {
    if (!openInfoId) return
    const handlePointerDown = (event: MouseEvent) => {
      if (!infoPopoverRef.current) return
      if (infoPopoverRef.current.contains(event.target as Node)) return
      setOpenInfoId(null)
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpenInfoId(null)
      }
    }
    document.addEventListener("mousedown", handlePointerDown)
    document.addEventListener("keydown", handleKeyDown)
    return () => {
      document.removeEventListener("mousedown", handlePointerDown)
      document.removeEventListener("keydown", handleKeyDown)
    }
  }, [openInfoId])

  React.useEffect(() => {
    if (!commonUserMenuOpen) return
    const handlePointerDown = (event: MouseEvent) => {
      const menu = commonUserFilterRef.current
      if (!menu) return
      if (menu.contains(event.target as Node)) return
      setCommonUserMenuOpen(false)
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setCommonUserMenuOpen(false)
      }
    }
    document.addEventListener("mousedown", handlePointerDown)
    document.addEventListener("keydown", handleKeyDown)
    return () => {
      document.removeEventListener("mousedown", handlePointerDown)
      document.removeEventListener("keydown", handleKeyDown)
    }
  }, [commonUserMenuOpen])

  React.useEffect(() => {
    if (!oneHMarkerMenuOpen) return
    const handlePointerDown = (event: MouseEvent) => {
      const menu = oneHMarkerFilterRef.current
      if (!menu || menu.contains(event.target as Node)) return
      setOneHMarkerMenuOpen(false)
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOneHMarkerMenuOpen(false)
    }
    document.addEventListener("mousedown", handlePointerDown)
    document.addEventListener("keydown", handleKeyDown)
    return () => {
      document.removeEventListener("mousedown", handlePointerDown)
      document.removeEventListener("keydown", handleKeyDown)
    }
  }, [oneHMarkerMenuOpen])

  React.useEffect(() => {
    if (!externalMeetingPersonsOpen) return
    const closePersonsMenu = () => {
      setExternalMeetingPersonsOpen(false)
      setExternalMeetingPersonSearch("")
    }
    const handlePointerDown = (event: MouseEvent) => {
      const picker = externalMeetingPersonsRef.current
      if (!picker || picker.contains(event.target as Node)) return
      closePersonsMenu()
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closePersonsMenu()
    }
    document.addEventListener("mousedown", handlePointerDown)
    document.addEventListener("keydown", handleKeyDown)
    return () => {
      document.removeEventListener("mousedown", handlePointerDown)
      document.removeEventListener("keydown", handleKeyDown)
    }
  }, [externalMeetingPersonsOpen])

  React.useEffect(() => {
    if (!editingExternalMeetingPersonsOpen) return
    const closePersonsMenu = () => {
      setEditingExternalMeetingPersonsOpen(false)
      setEditingExternalMeetingPersonSearch("")
    }
    const handlePointerDown = (event: MouseEvent) => {
      const picker = editingExternalMeetingPersonsRef.current
      if (!picker || picker.contains(event.target as Node)) return
      closePersonsMenu()
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closePersonsMenu()
    }
    document.addEventListener("mousedown", handlePointerDown)
    document.addEventListener("keydown", handleKeyDown)
    return () => {
      document.removeEventListener("mousedown", handlePointerDown)
      document.removeEventListener("keydown", handleKeyDown)
    }
  }, [editingExternalMeetingPersonsOpen])

  React.useEffect(() => {
    if (!internalMeetingPersonsOpen) return
    const closePersonsMenu = () => {
      setInternalMeetingPersonsOpen(false)
      setInternalMeetingPersonSearch("")
    }
    const handlePointerDown = (event: MouseEvent) => {
      const picker = internalMeetingPersonsRef.current
      if (!picker || picker.contains(event.target as Node)) return
      closePersonsMenu()
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closePersonsMenu()
    }
    document.addEventListener("mousedown", handlePointerDown)
    document.addEventListener("keydown", handleKeyDown)
    return () => {
      document.removeEventListener("mousedown", handlePointerDown)
      document.removeEventListener("keydown", handleKeyDown)
    }
  }, [internalMeetingPersonsOpen])


  const swimlaneRows = React.useMemo<SwimlaneRow[]>(() => {
    const includeOneH = typeFilters.size === 0 || typeFilters.has("oneH")
    const includeR1 = typeFilters.size === 0 || typeFilters.has("r1")
    const includeBlocked = typeFilters.size === 0 || typeFilters.has("blocked")
    const includePersonal = typeFilters.size === 0 || typeFilters.has("personal")
    const waitingClientSource = sortTasksByOrder(
      [
        ...(includeBlocked ? filtered.blocked : []),
        ...(includeOneH ? filtered.oneH : []),
        ...(includePersonal ? filtered.personal : []),
        ...(includeR1 ? filtered.r1 : []),
      ].filter(isWaitingClientTask),
      isMultiDate
    )
    const activeOneH = filtered.oneH.filter(
      (entry) => !isWaitingClientTask(entry) && !isRoutedWaitingConfirmation(entry)
    )
    const activeR1 = filtered.r1.filter(
      (entry) => !isWaitingClientTask(entry) && !isRoutedWaitingConfirmation(entry)
    )
    const oneHTotal = activeOneH.length
    const r1Total = activeR1.length
    const oneHDone = activeOneH.filter((x) => x.isDone).length
    const r1Done = activeR1.filter((x) => x.isDone).length

    const lateSource = isMultiDate
      ? sortByDate(filtered.late, (x) => x.date, (x) => x.person)
      : filtered.late
    const lateItems: SwimlaneCell[] = lateSource.map((x) => ({
      title: x.person,
      subtitle: `${toDDMMYYYYDot(x.date)} - ${x.start || "08:00"}-${x.until}${x.note ? ` - ${x.note}` : ""}`,
      dateLabel: formatDateHuman(x.date),
      accentClass: "swimlane-accent delay",
      entryId: x.entryId,
    }))

    const absentSource = isMultiDate
      ? sortByDate(filtered.absent, (x) => x.date, (x) => x.person)
      : filtered.absent
    const absentItems: SwimlaneCell[] = absentSource.map((x) => ({
      title: x.person,
      subtitle: `${toDDMMYYYYDot(x.date)} - ${x.from}-${x.to}${x.note ? ` - ${x.note}` : ""}`,
      dateLabel: formatDateHuman(x.date),
      accentClass: "swimlane-accent absence",
      entryId: x.entryId,
    }))
    const rawLeaveSource = isMultiDate
      ? sortByDate(filtered.leave, (x) => x.startDate, (x) => x.person)
      : filtered.leave
    const leaveAllUsersSeen = new Set<string>()
    const leaveSource: LeaveItem[] = rawLeaveSource.reduce((acc, x) => {
      if (!x.isAllUsers) {
        acc.push(x)
        return acc
      }
      const key = [
        x.startDate,
        x.endDate,
        x.fullDay ? "1" : "0",
        x.from || "",
        x.to || "",
        x.note || "",
      ].join("|")
      if (leaveAllUsersSeen.has(key)) {
        return acc
      }
      leaveAllUsersSeen.add(key)
      acc.push({
        ...x,
        person: ALL_USERS_INITIALS,
        entryId: undefined,
      })
      return acc
    }, [] as LeaveItem[])
    const datesToUse = selectedDates.size ? Array.from(selectedDates) : weekISOs
    const syntheticAllUsers = datesToUse
      .filter((d) => filtered.fullyCoveredDates.has(d))
      .map((d) =>
        allUsersLeaveByDate.get(d) || {
          person: ALL_USERS_INITIALS,
          startDate: d,
          endDate: d,
          fullDay: true,
          isAllUsers: true,
        }
      )
    const syntheticKeys = new Set<string>(
      leaveSource.map((x) =>
        [x.startDate, x.endDate, x.fullDay ? "1" : "0", x.from || "", x.to || "", x.note || "", x.person].join("|")
      )
    )
    for (const item of syntheticAllUsers) {
      const key = [item.startDate, item.endDate, "1", "", "", "", item.person].join("|")
      if (syntheticKeys.has(key)) continue
      syntheticKeys.add(key)
      leaveSource.push(item)
    }
    const leaveItems: SwimlaneCell[] = leaveSource.map((x) => {
      const isRange = x.endDate && x.endDate !== x.startDate
      const dateLabel = isRange
        ? `${toDDMMYYYYDot(x.startDate)} - ${toDDMMYYYYDot(x.endDate)}`
        : toDDMMYYYYDot(x.startDate)
      const timeLabel = x.fullDay
        ? "Full day"
        : `${x.from || ""}${x.from && x.to ? "-" : ""}${x.to || ""}`.trim()
      return {
        title: x.person,
        subtitle: `${dateLabel} - ${timeLabel}${x.note ? ` - ${x.note}` : ""}`,
        dateLabel,
        accentClass: "swimlane-accent leave",
        entryId: x.entryId,
        entryDate: x.startDate,
      }
    })

    const externalHolidaySource = isMultiDate
      ? sortByDate(filtered.externalHoliday, (x) => x.date, (x) => x.title)
      : filtered.externalHoliday
    const externalHolidayItems: SwimlaneCell[] = externalHolidaySource.map((x) => ({
      title: x.title,
      subtitle: `${formatDateHuman(x.date)}${x.note ? ` - ${x.note}` : ""}`,
      dateLabel: formatDateHuman(x.date),
      accentClass: "swimlane-accent externalHoliday",
      entryId: x.entryId,
      entryDate: x.date,
    }))

    const blockedSource = sortTasksByOrder(
      filtered.blocked.filter(
        (entry) => !isWaitingClientTask(entry) && !isRoutedWaitingConfirmation(entry)
      ),
      isMultiDate
    )
    const blockedItems: SwimlaneCell[] = blockedSource.map((x) => ({
      title: x.title,
      assignees: x.assignees || (x.person ? [x.person] : []),
      subtitle: `${formatFastTaskDateLabel(x.date, x.isDone, x.completedAt, x.startDate, x.dueDate)}${x.note ? ` - ${x.note}` : ""}`,
      dateLabel: formatFastTaskDateLabel(x.date, x.isDone, x.completedAt, x.startDate, x.dueDate),
      accentClass: "swimlane-accent blocked",
      status: x.status,
      isDone: x.isDone,
      number: getFastTaskDisplayNumber(blockedSource, x),
      taskId: x.taskId,
      userId: x.userId,
      departmentId: x.departmentId,
      fastTaskOrder: x.fastTaskOrder,
      finishPeriod: x.finishPeriod,
      oneHReportSlot: x.oneHReportSlot,
      oneHMarker: x.oneHMarker,
      entryDate: x.date,
      isDeadlineImportant: x.isDeadlineImportant,
      dueDate: x.dueDate,
      startDate: x.startDate,
      createdAt: x.createdAt,
      completedAt: x.completedAt,
      dateIsToday: isCommonTaskStartingOnDate(x),
      isSystemTask: x.isSystemTask,
    }))

    const oneHSource = includeOneH ? sortTasksByOrder(activeOneH, isMultiDate) : []
    const oneHItems: SwimlaneCell[] = oneHSource.map((x) => ({
      title: x.title,
      assignees: x.assignees || (x.person ? [x.person] : []),
      subtitle: `${formatFastTaskDateLabel(x.date, x.isDone, x.completedAt, x.startDate, x.dueDate)}${x.note ? ` - ${x.note}` : ""}`,
      dateLabel: formatFastTaskDateLabel(x.date, x.isDone, x.completedAt, x.startDate, x.dueDate),
      accentClass: "swimlane-accent oneh",
      status: x.status,
      isDone: x.isDone,
      number: getFastTaskDisplayNumber(oneHSource, x),
      taskId: x.taskId,
      userId: x.userId,
      departmentId: x.departmentId,
      fastTaskOrder: x.fastTaskOrder,
      finishPeriod: x.finishPeriod,
      oneHReportSlot: x.oneHReportSlot,
      oneHMarker: x.oneHMarker,
      entryDate: x.date,
      isDeadlineImportant: x.isDeadlineImportant,
      dueDate: x.dueDate,
      startDate: x.startDate,
      createdAt: x.createdAt,
      completedAt: x.completedAt,
      dateIsToday: isCommonTaskStartingOnDate(x),
      isSystemTask: x.isSystemTask,
    }))

    const personalSource = sortTasksByOrder(filtered.personal.filter((entry) => !isWaitingClientTask(entry)), isMultiDate)
    const buildPersonalItems = (group: PersonalTaskGroup): SwimlaneCell[] => {
      const rowId = PERSONAL_ROW_IDS.find((candidate) => getPersonalRowGroup(candidate) === group)
      const groupSource = rowId ? personalTasksForRow(personalSource, rowId) : []
      return groupSource.map((x) => ({
        title: x.title,
        assignees: x.assignees || (x.person ? [x.person] : []),
        subtitle: `${formatFastTaskDateLabel(x.date, x.isDone, x.completedAt, x.startDate, x.dueDate)}${x.note ? ` - ${x.note}` : ""}`,
        dateLabel: formatFastTaskDateLabel(x.date, x.isDone, x.completedAt, x.startDate, x.dueDate),
        accentClass: "swimlane-accent personal",
        status: x.status,
        isDone: x.isDone,
        number: getFastTaskDisplayNumber(groupSource, x),
        taskId: x.taskId,
        userId: x.userId,
        departmentId: x.departmentId,
        fastTaskOrder: x.fastTaskOrder,
        finishPeriod: x.finishPeriod,
        oneHMarker: x.oneHMarker,
        entryDate: x.date,
        isDeadlineImportant: x.isDeadlineImportant,
        dueDate: x.dueDate,
        startDate: x.startDate,
        createdAt: x.createdAt,
        completedAt: x.completedAt,
        dateIsToday: isCommonTaskStartingOnDate(x),
        isSystemTask: x.isSystemTask,
      }))
    }
    const personalItemsByGroup: Record<PersonalTaskGroup, SwimlaneCell[]> = {
      GA: buildPersonalItems("GA"),
      KA: buildPersonalItems("KA"),
      GENT: buildPersonalItems("GENT"),
      PX: buildPersonalItems("PX"),
    }

    const externalSource = isMultiDate
      ? sortByDateTime(filtered.external, (x) => x.date, (x) => x.time, (x) => x.title)
      : sortByTime(filtered.external, (x) => x.time, (x) => x.title)
    const externalItems: SwimlaneCell[] = externalSource.map((x) => ({
      title: x.title,
      meetingTimeLabel: formatTimeLabel(x.time) || undefined,
      isCalendarMeeting: Boolean(x.calendarImported),
      subtitle: x.department || "Department TBD",
      dateLabel: formatDateHuman(x.date),
      accentClass: [
        "swimlane-accent external",
        meetingLegendTone({
          categories: x.calendarCategories,
          recurrenceType: x.recurrenceType ?? x.recurrence_type,
          meetingType: "external",
          calendarImported: x.calendarImported,
        }),
        isOneTimeMeeting(x.recurrenceType ?? x.recurrence_type) ? "one-time-meeting" : "",
      ]
        .filter(Boolean)
        .join(" "),
      recurrenceType: x.recurrenceType ?? x.recurrence_type,
      entryDate: x.date,
      meetingId: String(x.id || "").startsWith("meeting:") ? String(x.id).split(":")[1] : undefined,
    }))
    const internalSource = isMultiDate
      ? sortByDateTime(filtered.internal, (x) => x.date, (x) => x.time, (x) => x.title)
      : sortByTime(filtered.internal, (x) => x.time, (x) => x.title)
    const internalItems: SwimlaneCell[] = internalSource.map((x) => ({
      title: x.title,
      meetingRelation: internalMeetingRelation(x),
      meetingTimeLabel: formatTimeLabel(x.time) || undefined,
      isManualInternalMeeting: isManualInternalMeeting(x),
      isCalendarMeeting: isCalendarLinkedInternalMeeting(x),
      subtitle: x.department || "Department TBD",
      dateLabel: formatDateHuman(x.date),
      accentClass: [
        "swimlane-accent internal",
        internalMeetingLegendTone(x),
        isManualInternalMeeting(x) ? "manual-internal-meeting" : "",
        isOneTimeMeeting(x.recurrenceType ?? x.recurrence_type) ? "one-time-meeting" : "",
      ]
        .filter(Boolean)
        .join(" "),
      recurrenceType: x.recurrenceType ?? x.recurrence_type,
      entryDate: x.date,
      meetingId: String(x.id || "").startsWith("meeting:") ? String(x.id).split(":")[1] : undefined,
    }))

    const bzSource = isMultiDate
      ? sortByDateTime(filtered.bz, (x) => x.date, (x) => x.time, (x) => x.title)
      : sortByTime(filtered.bz, (x) => x.time, (x) => x.title)
    const bzItems: SwimlaneCell[] = bzSource.map((x) => ({
      title: x.title,
      subtitle: `${formatTimeLabel(x.time)}${x.bzWithLabel ? ` - BZ: ${x.bzWithLabel}` : ""}`.trim(),
      dateLabel: formatDateHuman(x.date),
      accentClass: "swimlane-accent bz",
      assignees: x.assignees,
    }))

    const r1Source = includeR1 ? sortTasksByOrder(activeR1, isMultiDate) : []
    const r1Items: SwimlaneCell[] = r1Source.map((x) => ({
      title: x.title,
      assignees: x.assignees || (x.owner ? [x.owner] : []),
      subtitle: `${formatFastTaskDateLabel(x.date, x.isDone, x.completedAt, x.startDate, x.dueDate)}${x.note ? ` - ${x.note}` : ""}`,
      dateLabel: formatFastTaskDateLabel(x.date, x.isDone, x.completedAt, x.startDate, x.dueDate),
      accentClass: "swimlane-accent r1",
      status: x.status,
      isDone: x.isDone,
      number: getFastTaskDisplayNumber(r1Source, x),
      taskId: x.taskId,
      userId: x.userId,
      departmentId: x.departmentId,
      fastTaskOrder: x.fastTaskOrder,
      finishPeriod: x.finishPeriod,
      oneHReportSlot: x.oneHReportSlot,
      oneHMarker: x.oneHMarker,
      entryDate: x.date,
      isDeadlineImportant: x.isDeadlineImportant,
      dueDate: x.dueDate,
      startDate: x.startDate,
      createdAt: x.createdAt,
      completedAt: x.completedAt,
      dateIsToday: isCommonTaskStartingOnDate(x),
      isSystemTask: x.isSystemTask,
    }))

    const problemSource = isMultiDate
      ? sortByDate(filtered.problems, (x) => x.date, (x) => x.title)
      : filtered.problems
    const problemItems: SwimlaneCell[] = problemSource.map((x) => {
      const createdLabel = x.createdDate ? formatDateHuman(x.createdDate) : formatDateHuman(x.date)
      return {
        title: x.title,
        subtitle: `${x.person} - Date Created: ${createdLabel}`,
        dateLabel: `Date Created: ${createdLabel}`,
        note: x.note,
        accentClass: "swimlane-accent problem",
        entryId: x.entryId,
        assignees: x.person ? [x.person] : undefined,
      }
    })

    const feedbackSource = isMultiDate
      ? sortByDate(filtered.feedback, (x) => x.date, (x) => x.title)
      : filtered.feedback
    const feedbackItems: SwimlaneCell[] = feedbackSource.map((x) => {
      const createdLabel = x.createdDate ? formatDateHuman(x.createdDate) : formatDateHuman(x.date)
      return {
        title: x.title,
        subtitle: `${x.person} - Date Created: ${createdLabel}`,
        dateLabel: `Date Created: ${createdLabel}`,
        note: x.note,
        accentClass: "swimlane-accent feedback",
        entryId: x.entryId,
        assignees: x.person ? [x.person] : undefined,
      }
    })

    const prioritySource = isMultiDate
      ? sortByDate(filtered.priority, (x) => x.date, (x) => x.project)
      : filtered.priority
    const priorityItems: SwimlaneCell[] = prioritySource.map((p, idx) => ({
      title: p.project,
      assignees: p.assignees,
      accentClass: "swimlane-accent priority",
      number: idx + 1,
      dateLabel: formatDateHuman(p.date),
    }))
    const diamondSource = isMultiDate
      ? sortByDate(filteredDiamondItems, (x) => x.date, (x) => x.person)
      : filteredDiamondItems
    const diamondCells: SwimlaneCell[] = diamondSource.map((item) => ({
      title: `${item.person} — ${item.taskTitle}`,
      dateLabel: formatDateHuman(item.date),
      accentClass: "swimlane-accent diamond",
      taskId: item.taskId ?? undefined,
      userId: item.userId,
      entryDate: item.date,
    }))
    const waitingClientItems: SwimlaneCell[] = waitingClientSource.map((entry, index) => ({
      title: entry.title,
      assignees: entryAssignees(entry),
      subtitle: `${formatFastTaskDateLabel(entry.date, entry.isDone, entry.completedAt, entry.startDate, entry.dueDate)}${entry.note ? ` - ${entry.note}` : ""}`,
      dateLabel: formatFastTaskDateLabel(entry.date, entry.isDone, entry.completedAt, entry.startDate, entry.dueDate),
      accentClass: "swimlane-accent waiting-client",
      status: entry.status,
      isDone: entry.isDone,
      number: index + 1,
      taskId: entry.taskId,
      userId: entry.userId,
      departmentId: entry.departmentId,
      fastTaskOrder: entry.fastTaskOrder,
      finishPeriod: entry.finishPeriod,
      oneHReportSlot: entry.oneHReportSlot,
      oneHMarker: entry.oneHMarker,
      entryDate: entry.date,
      isDeadlineImportant: entry.isDeadlineImportant,
      dueDate: entry.dueDate,
      startDate: entry.startDate,
      createdAt: entry.createdAt,
      completedAt: entry.completedAt,
      dateIsToday: isCommonTaskStartingOnDate(entry),
      isSystemTask: entry.isSystemTask,
    }))

    const buildFastHeaderBreakdown = (items: SwimlaneCell[]) => {
      const eightAmCount = items.filter((item) => hasEightAmIndicator(item.title, item.isSystemTask)).length
      const deadlineCount = items.filter((item) => item.isDeadlineImportant).length
      return [
        ...(eightAmCount > 0 ? [{ value: eightAmCount, label: "08:00", className: "swimlane-badge-sub swimlane-badge-sub-time" }] : []),
        ...(deadlineCount > 0 ? [{ value: deadlineCount, label: "dl", className: "swimlane-badge-sub swimlane-badge-sub-deadline" }] : []),
      ]
    }

    const blockedHeaderBreakdown = buildFastHeaderBreakdown(blockedItems)
    const buildOneHSlotItems = (slot: OneHReportSlot | null) =>
      oneHItems.filter((item) =>
        slot === null ? !normalizeOneHReportSlot(item.oneHReportSlot) : normalizeOneHReportSlot(item.oneHReportSlot) === slot
      )
    const selectedOneHDate = selectedDates.size === 1 ? Array.from(selectedDates)[0] : null
    const oneHUserIdByName = new Map<string, string>()
    for (const userEntry of users) {
      if (userEntry.full_name) oneHUserIdByName.set(userEntry.full_name.trim().toLowerCase(), userEntry.id)
      if (userEntry.username) oneHUserIdByName.set(userEntry.username.trim().toLowerCase(), userEntry.id)
      if (userEntry.email) oneHUserIdByName.set(userEntry.email.trim().toLowerCase(), userEntry.id)
    }
    const allOneHUsersOnLeave = selectedOneHDate
      ? commonData.leave.some(
          (leaveEntry) =>
            leaveEntry.isAllUsers &&
            selectedOneHDate >= leaveEntry.startDate &&
            selectedOneHDate <= leaveEntry.endDate
        )
      : false
    const oneHUsersOnLeave = new Set(
      selectedOneHDate
        ? commonData.leave
            .filter(
              (leaveEntry) =>
                leaveEntry.userId &&
                selectedOneHDate >= leaveEntry.startDate &&
                selectedOneHDate <= leaveEntry.endDate
            )
            .map((leaveEntry) => leaveEntry.userId as string)
        : []
    )
    const oneHEligibleUsers = selectedOneHDate
      ? users
          .filter((userEntry) => userEntry.is_active)
          .filter((userEntry) => userEntry.role !== "ADMIN")
          .filter((userEntry) => {
            const identityValues = [
              userEntry.full_name,
              userEntry.username?.replace(/[._-]+/g, " "),
              userEntry.email?.split("@")[0]?.replace(/[._-]+/g, " "),
            ].filter((value): value is string => Boolean(value?.trim()))
            return !identityValues.some((value) => ["GA", "KA", "HV", "HS"].includes(initials(value)))
          })
          .filter((userEntry) => selectedCommonUserId === "__all__" || userEntry.id === selectedCommonUserId)
          .filter(() => !allOneHUsersOnLeave)
          .filter((userEntry) => !oneHUsersOnLeave.has(userEntry.id))
          .filter((userEntry) => !filtered.hiddenUsersByDate.get(selectedOneHDate)?.has(userEntry.id))
          .sort((a, b) => {
            const aDepartment = getDepartmentMeta(a.department_id || undefined)
            const bDepartment = getDepartmentMeta(b.department_id || undefined)
            if (aDepartment.rank !== bDepartment.rank) return aDepartment.rank - bDepartment.rank
            if (aDepartment.rank === 3) {
              const departmentNameComparison = aDepartment.name.localeCompare(bDepartment.name)
              if (departmentNameComparison) return departmentNameComparison
            }
            const aOrder = a.weekly_planner_sort_order
            const bOrder = b.weekly_planner_sort_order
            if (aOrder != null || bOrder != null) {
              if (aOrder == null) return 1
              if (bOrder == null) return -1
              if (aOrder !== bOrder) return aOrder - bOrder
            }
            const aLabel = a.full_name || a.username || a.email || ""
            const bLabel = b.full_name || b.username || b.email || ""
            return aLabel.localeCompare(bLabel)
          })
      : []
    const usersWithOneHSlot = (slot: OneHReportSlot) => {
      const usersWithSlot = new Set<string>()
      for (const item of commonData.oneH) {
        if (item.date !== selectedOneHDate || isWaitingClientTask(item)) continue
        if (normalizeOneHReportSlot(item.oneHReportSlot) !== slot) continue
        if (item.userId) usersWithSlot.add(item.userId)
        for (const assignee of entryAssignees(item)) {
          const assigneeId = oneHUserIdByName.get(assignee.trim().toLowerCase())
          if (assigneeId) usersWithSlot.add(assigneeId)
        }
      }
      return usersWithSlot
    }
    const usersWithBlockedTask = new Set<string>()
    for (const item of commonData.blocked) {
      if (item.date !== selectedOneHDate || isWaitingClientTask(item)) continue
      if (item.userId) usersWithBlockedTask.add(item.userId)
      for (const assignee of entryAssignees(item)) {
        const assigneeId = oneHUserIdByName.get(assignee.trim().toLowerCase())
        if (assigneeId) usersWithBlockedTask.add(assigneeId)
      }
    }
    const buildMissingOneHUsers = (slot: OneHReportSlot | null) => {
      if (!selectedOneHDate || !slot) return []
      const usersWithSlot = usersWithOneHSlot(slot)
      return oneHEligibleUsers
        .filter((userEntry) => !usersWithSlot.has(userEntry.id))
        .map((userEntry) => {
          const label = userEntry.full_name || userEntry.username || userEntry.email || "Unknown"
          return { id: userEntry.id, label, initials: initials(label), hasBlockedTask: slot === "16:00" && usersWithBlockedTask.has(userEntry.id) }
        })
    }
    const missingBlockedUsers = selectedOneHDate
      ? (() => {
          const usersWithOneHAt16 = usersWithOneHSlot("16:00")
          return oneHEligibleUsers
            .filter((userEntry) => !usersWithBlockedTask.has(userEntry.id))
            .map((userEntry) => {
              const label = userEntry.full_name || userEntry.username || userEntry.email || "Unknown"
              return { id: userEntry.id, label, initials: initials(label), hasOneHAt16: usersWithOneHAt16.has(userEntry.id) }
            })
        })()
      : []
    const oneHRows = isMultiDate
      ? [
          {
            id: "oneH" as const,
            label: "1H",
            count: oneHTotal,
            countLabel: oneHTotal === 0 ? "0" : `${oneHTotal}/${oneHDone}`,
            headerClass: "swimlane-header oneh",
            badgeClass: "swimlane-badge oneh",
            headerBreakdown: buildFastHeaderBreakdown(oneHItems),
            items: oneHItems,
          },
        ]
      : ONE_H_SLOT_ROWS.map((slotRow) => {
          const items = buildOneHSlotItems(slotRow.slot)
          const doneCount = items.filter((item) => item.isDone).length
          return {
            id: slotRow.id,
            label: slotRow.label,
            count: items.length,
            countLabel: items.length === 0 ? "0" : `${items.length}/${doneCount}`,
            headerClass: "swimlane-header oneh",
            badgeClass: "swimlane-badge oneh",
            headerBreakdown: buildFastHeaderBreakdown(items),
            missingOneHUsers: buildMissingOneHUsers(slotRow.slot),
            items,
          }
        })
    const r1HeaderBreakdown = buildFastHeaderBreakdown(r1Items)
    const personalHeaderBreakdownByGroup: Record<PersonalTaskGroup, ReturnType<typeof buildFastHeaderBreakdown>> = {
      GA: buildFastHeaderBreakdown(personalItemsByGroup.GA),
      KA: buildFastHeaderBreakdown(personalItemsByGroup.KA),
      GENT: buildFastHeaderBreakdown(personalItemsByGroup.GENT),
      PX: buildFastHeaderBreakdown(personalItemsByGroup.PX),
    }

    return [
      {
        id: "late",
        label: "VONS",
        count: filtered.late.length,
        headerClass: "swimlane-header delay",
        badgeClass: "swimlane-badge delay",
        items: lateItems,
      },
      {
        id: "absent",
        label: "MUNG",
        count: filtered.absent.length,
        headerClass: "swimlane-header absence",
        badgeClass: "swimlane-badge absence",
        items: absentItems,
      },
      {
        id: "leave",
        label: "PV/FESTE",
        count: leaveSource.length,
        headerClass: "swimlane-header leave",
        badgeClass: "swimlane-badge leave",
        items: leaveItems,
      },
      {
        id: "externalHoliday",
        label: "FESTA EXT",
        count: filtered.externalHoliday.length,
        headerClass: "swimlane-header externalHoliday",
        badgeClass: "swimlane-badge externalHoliday",
        items: externalHolidayItems,
      },
      {
        id: "external",
        label: "TAK EXT",
        count: filtered.external.length,
        headerClass: "swimlane-header external",
        badgeClass: "swimlane-badge external",
        items: externalItems,
      },
      {
        id: "internal",
        label: "TAK INT",
        count: filtered.internal.length,
        headerClass: "swimlane-header internal",
        badgeClass: "swimlane-badge internal",
        items: internalItems,
      },
      {
        id: "bz",
        label: "BZ GA",
        count: filtered.bz.length,
        headerClass: "swimlane-header bz",
        badgeClass: "swimlane-badge bz",
        items: bzItems,
      },
      {
        id: "waitingClient",
        label: "WFE",
        count: waitingClientItems.length,
        headerClass: "swimlane-header waiting-client",
        badgeClass: "swimlane-badge waiting-client",
        headerBreakdown: buildFastHeaderBreakdown(waitingClientItems),
        items: waitingClientItems,
      },
      {
        id: "blocked",
        label: "BLL",
        count: blockedItems.length,
        headerClass: "swimlane-header blocked",
        badgeClass: "swimlane-badge blocked",
        headerBreakdown: blockedHeaderBreakdown,
        missingBlockedUsers,
        items: blockedItems,
      },
      ...oneHRows,
      {
        id: "r1",
        label: "R1=1H",
        count: r1Total,
        countLabel: r1Total === 0 ? "0" : `${r1Total}/${r1Done}`,
        headerClass: "swimlane-header r1",
        badgeClass: "swimlane-badge r1",
        headerBreakdown: r1HeaderBreakdown,
        items: r1Items,
      },
      ...PERSONAL_ROW_IDS.map((id) => {
        const group = getPersonalRowGroup(id)
        const items = personalItemsByGroup[group]
        return {
          id,
          label: `P: ${group}`,
          count: items.length,
          headerClass: "swimlane-header personal",
          badgeClass: "swimlane-badge personal",
          headerBreakdown: personalHeaderBreakdownByGroup[group],
          items,
        }
      }),
      {
        id: "priority",
        label: "PRJK",
        count: filtered.priority.length,
        headerClass: "swimlane-header priority",
        badgeClass: "swimlane-badge priority",
        items: priorityItems,
      },
      {
        id: "diamond",
        label: "DIAMANT",
        count: diamondCells.length,
        headerClass: "swimlane-header diamond",
        badgeClass: "swimlane-badge diamond",
        items: diamondCells,
      },
      {
        id: "problem",
        label: "PRBL",
        count: filtered.problems.length,
        headerClass: "swimlane-header problem",
        badgeClass: "swimlane-badge problem",
        items: problemItems,
      },
      {
        id: "feedback",
        label: "ANK/KRK/PRZ",
        count: filtered.feedback.length,
        headerClass: "swimlane-header feedback",
        badgeClass: "swimlane-badge feedback",
        items: feedbackItems,
      },
    ]
  }, [commonData.oneH, filtered, filteredDiamondItems, getDepartmentMeta, isMultiDate, selectedCommonUserId, sortByDate, sortByDateTime, sortByTime, selectedDates, typeFilters, users, weekISOs])

  const swimlaneColumnCount = React.useMemo(() => {
    if (!swimlaneRows.length) return 3
    const counts = swimlaneRows.map((row) => {
      const length = row.items.length || 1
      return Math.max(3, Math.ceil(length / 3) * 3)
    })
    return Math.max(...counts)
  }, [swimlaneRows])

  // Organize data by day for table view
  const tableDataByDay = React.useMemo(() => {
    if (!allDaysSelected) return null
    
    const dataByDay: Record<string, {
      late: LateItem[]
      absent: AbsentItem[]
      leave: LeaveItem[]
      externalHoliday: ExternalHolidayItem[]
      waitingClient: FastTaskEntry[]
      blocked: BlockedItem[]
      oneH: OneHItem[]
      personal: PersonalItem[]
      external: ExternalItem[]
      internal: InternalItem[]
      bz: BzItem[]
      r1: R1Item[]
      problems: ProblemItem[]
      feedback: FeedbackItem[]
      priority: PriorityItem[]
      diamond: DiamondItem[]
    }> = {}
    const dailyFeedback = filtered.feedback.filter((x) => x.everyday)
    const dailyProblems = filtered.problems.filter((x) => x.everyday)
    
    weekISOs.forEach((iso) => {
      if (filtered.fullyCoveredDates.has(iso)) {
        const allUsersLeave = allUsersLeaveByDate.get(iso)
        dataByDay[iso] = {
          late: [],
          absent: [],
          leave: [
            allUsersLeave || {
              person: ALL_USERS_INITIALS,
              startDate: iso,
              endDate: iso,
              fullDay: true,
              isAllUsers: true,
            },
          ],
          externalHoliday: filtered.externalHoliday.filter((x) => x.date === iso),
          waitingClient: [],
          blocked: [],
          oneH: [],
          personal: [],
          external: [],
          internal: [],
          bz: [],
          r1: [],
          problems: dailyProblems,
          feedback: dailyFeedback,
          priority: [],
          diamond: filteredDiamondItems.filter((x) => x.date === iso),
        }
        return
      }
      dataByDay[iso] = {
        late: filtered.late.filter((x) => x.date === iso),
        absent: filtered.absent.filter((x) => x.date === iso),
        leave: filtered.leave.filter((x) => iso >= x.startDate && iso <= x.endDate),
        externalHoliday: filtered.externalHoliday.filter((x) => x.date === iso),
        waitingClient: sortTasksByOrder(
          [...filtered.blocked, ...filtered.oneH, ...filtered.personal, ...filtered.r1].filter(
            (x) => x.date === iso && isWaitingClientTask(x)
          ),
          false
        ),
        blocked: sortTasksByOrder(filtered.blocked.filter((x) => x.date === iso && !isWaitingClientTask(x)), false),
        oneH: sortTasksByOrder(filtered.oneH.filter((x) => x.date === iso && !isWaitingClientTask(x)), false),
        personal: sortTasksByOrder(filtered.personal.filter((x) => x.date === iso && !isWaitingClientTask(x)), false),
        external: sortByTime(filtered.external.filter((x) => x.date === iso), (x) => x.time, (x) => x.title),
        internal: sortByTime(filtered.internal.filter((x) => x.date === iso), (x) => x.time, (x) => x.title),
        bz: sortByTime(filtered.bz.filter((x) => x.date === iso), (x) => x.time, (x) => x.title),
        r1: sortTasksByOrder(filtered.r1.filter((x) => x.date === iso && !isWaitingClientTask(x)), false),
        problems: [
          ...filtered.problems.filter((x) => !x.everyday && x.date === iso),
          ...dailyProblems,
        ],
        feedback: [
          ...filtered.feedback.filter((x) => !x.everyday && x.date === iso),
          ...dailyFeedback,
        ],
        priority: filtered.priority.filter((x) => x.date === iso),
        diamond: filteredDiamondItems.filter((x) => x.date === iso),
      }
    })
    
    return dataByDay
  }, [allDaysSelected, weekISOs, filtered, filteredDiamondItems, sortByTime, sortTasksByOrder])

  const swimlaneRowRefs = React.useRef<Record<string, HTMLDivElement | null>>({})
  const scrollSwimlaneRow = React.useCallback((rowId: CommonType, direction: "left" | "right") => {
    const node = swimlaneRowRefs.current[rowId]
    if (!node) return
    const delta = direction === "left" ? -320 : 320
    node.scrollBy({ left: delta, behavior: "smooth" })
  }, [])

  const updateMeetingCheckStatus = React.useCallback((meetingId: string, itemId: string, nextStatus: MeetingCheckStatus) => {
    setMeetingTemplates((prev) =>
      prev.map((meeting) => {
        if (meeting.id !== meetingId) return meeting
        return {
          ...meeting,
          rows: meeting.rows.map((row) =>
            row.id === itemId ? { ...row, isChecked: nextStatus === "check", checkStatus: nextStatus } : row
          ),
        }
      })
    )
  }, [])

  const changeMeetingCheckStatus = React.useCallback(
    async (meetingId: string, itemId: string, nextStatus: MeetingCheckStatus) => {
      const currentRow =
        meetingTemplates
          .find((meeting) => meeting.id === meetingId)
          ?.rows.find((row) => row.id === itemId)
      const currentStatus = currentRow?.checkStatus ?? (currentRow?.isChecked ? "check" : "none")
      updateMeetingCheckStatus(meetingId, itemId, nextStatus)
      try {
        const res = await apiFetch(`/checklist-items/${itemId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            is_checked: nextStatus === "check",
            comment: buildMeetingCheckComment(nextStatus, currentRow?.comment),
          }),
        })
        if (!res.ok) {
          updateMeetingCheckStatus(meetingId, itemId, currentStatus)
        }
      } catch {
        updateMeetingCheckStatus(meetingId, itemId, currentStatus)
      }
    },
    [apiFetch, meetingTemplates, updateMeetingCheckStatus]
  )

  const startEditMeetingRow = React.useCallback((row: MeetingRow) => {
    setEditingRowId(row.id)
    setEditDraft({
      nr: String(row.nr || ""),
      day: row.day || "",
      topic: row.topic || "",
      owner: row.owner || "",
      time: row.time || "",
    })
  }, [])

  const cancelEditMeetingRow = React.useCallback(() => {
    setEditingRowId(null)
    setEditDraft({ nr: "", day: "", topic: "", owner: "", time: "" })
  }, [])

  const saveMeetingRow = React.useCallback(
    async (meetingId: string, rowId: string) => {
      const meeting = meetingTemplates.find((template) => template.id === meetingId)
      const previousRows = meeting?.rows || []
      const previous = previousRows.find((row) => row.id === rowId)
      if (!meeting || !previous) return
      const parsedNr = Number(editDraft.nr)
      if (!Number.isFinite(parsedNr) || parsedNr < 1) {
        toast.error("Enter a valid row number.")
        return
      }
      const nextNr = Math.min(Math.floor(parsedNr), previousRows.length)
      const payload = {
        position: nextNr,
        title: editDraft.topic.trim().toUpperCase(),
        day: editDraft.day.trim() || null,
        owner: editDraft.owner.trim() || null,
        time: editDraft.time.trim() || null,
      }
      if (!payload.title) return
      const updatedRow: MeetingRow = {
        ...previous,
        day: payload.day ?? undefined,
        topic: payload.title,
        owner: payload.owner ?? undefined,
        time: payload.time ?? undefined,
      }
      const orderedRows = previousRows.slice().sort((a, b) => a.nr - b.nr || a.id.localeCompare(b.id))
      const withoutCurrent = orderedRows.filter((row) => row.id !== rowId)
      withoutCurrent.splice(nextNr - 1, 0, updatedRow)
      const nextRows = withoutCurrent.map((row, index) => ({ ...row, nr: index + 1 }))
      setMeetingTemplates((prev) =>
        prev.map((meeting) => {
          if (meeting.id !== meetingId) return meeting
          return {
            ...meeting,
            rows: nextRows,
          }
        })
      )
      setEditingRowId(null)
      try {
        const res = await apiFetch(`/checklist-items/${rowId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        })
        if (!res.ok) {
          setMeetingTemplates((prev) =>
            prev.map((meeting) => (meeting.id === meetingId ? { ...meeting, rows: previousRows } : meeting))
          )
          return
        }
        const templates = await reloadMeetingTemplates()
        setMeetingTemplates(templates)
      } catch {
        setMeetingTemplates((prev) =>
          prev.map((meeting) => (meeting.id === meetingId ? { ...meeting, rows: previousRows } : meeting))
        )
      }
    },
    [apiFetch, editDraft, meetingTemplates, reloadMeetingTemplates]
  )

  const deleteMeetingRow = React.useCallback(
    async (meetingId: string, rowId: string) => {
      const confirmed = await confirm({
        title: "Delete checklist item",
        description: "Delete this checklist item? This action cannot be undone.",
        confirmLabel: "Delete",
        variant: "destructive",
      })
      if (!confirmed) return
      const previousRows = meetingTemplates.find((meeting) => meeting.id === meetingId)?.rows || []
      setMeetingTemplates((prev) =>
        prev.map((meeting) => {
          if (meeting.id !== meetingId) return meeting
          return {
            ...meeting,
            rows: meeting.rows.filter((row) => row.id !== rowId),
          }
        })
      )
      try {
        const res = await apiFetch(`/checklist-items/${rowId}`, {
          method: "DELETE",
        })
        if (!res.ok) {
          setMeetingTemplates((prev) =>
            prev.map((meeting) => {
              if (meeting.id !== meetingId) return meeting
              return {
                ...meeting,
                rows: previousRows,
              }
            })
          )
          return
        }
        const remainingRows = previousRows
          .filter((row) => row.id !== rowId)
          .sort((a, b) => a.nr - b.nr || a.id.localeCompare(b.id))
          .map((row, index) => ({ ...row, nr: index + 1 }))
        setMeetingTemplates((prev) =>
          prev.map((meeting) => (meeting.id === meetingId ? { ...meeting, rows: remainingRows } : meeting))
        )
        const templates = await reloadMeetingTemplates()
        setMeetingTemplates(templates)
      } catch {
        setMeetingTemplates((prev) =>
          prev.map((meeting) => {
            if (meeting.id !== meetingId) return meeting
            return {
              ...meeting,
              rows: previousRows,
            }
          })
        )
      }
    },
    [apiFetch, confirm, meetingTemplates, reloadMeetingTemplates]
  )

  const addMeetingRow = React.useCallback(
    async (meetingId: string) => {
      const topic = addDraft.topic.trim().toUpperCase()
      if (!topic) return
      const meeting = meetingTemplates.find((template) => template.id === meetingId)
      if (!meeting) return
      const parsedNr = Number(addDraft.nr)
      const requestedNr = Number.isFinite(parsedNr) && parsedNr > 0 ? Math.floor(parsedNr) : null
      const sortedRows = meeting.rows.slice().sort((a, b) => a.nr - b.nr || a.id.localeCompare(b.id))
      const insertIndex = requestedNr === null ? sortedRows.length : Math.min(requestedNr - 1, sortedRows.length)
      const nextPosition =
        requestedNr === null ? Math.max(0, ...meeting.rows.map((row) => row.nr || 0)) + 1 : insertIndex + 1
      const payload = {
        checklist_id: meetingId,
        item_type: "CHECKBOX",
        position: nextPosition,
        title: topic,
        day: addDraft.day.trim() || null,
        owner: null,
        time: null,
        is_checked: false,
      }
      try {
        const res = await apiFetch("/checklist-items", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        })
        if (!res.ok) return
        const created = await res.json()
        const createdRow: MeetingRow = {
          id: created.id,
          nr: requestedNr || created.position || nextPosition,
          day: created.day || undefined,
          topic: created.title || topic,
          owner: created.owner || undefined,
          time: created.time || undefined,
          isChecked: created.is_checked ?? false,
          checkStatus: getMeetingCheckStatus(created.is_checked, created.comment),
          comment: created.comment || undefined,
        }
        const baseRows = meeting?.rows || []
        const orderedBaseRows = baseRows.slice().sort((a, b) => a.nr - b.nr || a.id.localeCompare(b.id))
        const nextRows = orderedBaseRows
          .slice(0, insertIndex)
          .concat(createdRow, orderedBaseRows.slice(insertIndex))
          .map((row, index) => ({ ...row, nr: index + 1 }))
        setMeetingTemplates((prev) =>
          prev.map((template) => {
            if (template.id !== meetingId) return template
            return {
              ...template,
              rows: nextRows,
            }
          })
        )
        setAddDraft({ nr: "", day: "", topic: "", owner: "", time: "" })
        const templates = await reloadMeetingTemplates()
        setMeetingTemplates(templates)
      } catch (err) {
        console.error("Failed to add meeting item", err)
      }
    },
    [addDraft, apiFetch, meetingTemplates, reloadMeetingTemplates]
  )

  const renderSingleDayPrintRows = (rowIds: readonly CommonType[]) =>
    orderCommonRowsForPrint(
      swimlaneRows
        .filter((row) => showCard(row.id, row.items.length))
        .filter((row) => rowIds.includes(row.id))
    )
      .flatMap((row, rowIndex) => {
        const items = mergePrintTaskEntries(
          row.id,
          sortTasksForReportPrint(row.items.filter((item) => !item.placeholder))
        )
        const rowCount = Math.max(1, Math.ceil(items.length / 6))
        return Array.from({ length: rowCount }, (_, chunkIndex) => {
          const taskCells = items.slice(chunkIndex * 6, chunkIndex * 6 + 6)
          return (
            <tr key={`${row.id}-${chunkIndex}`}>
              {chunkIndex === 0 ? (
                <>
                  <th rowSpan={rowCount} scope="row">{rowIndex + 1}</th>
                  <th rowSpan={rowCount}>
                    <span>{row.label}</span>
                    {getCommonPrintRowSubtext(row.id) ? (
                      <span className="week-table-label-subtext">{getCommonPrintRowSubtext(row.id)}</span>
                    ) : null}
                  </th>
                </>
              ) : null}
              {Array.from({ length: 6 }, (_, cellIndex) => {
                const item = taskCells[cellIndex]
                const isPersonalTaskForGa = Boolean(item && row.id === "personalGA")
                return (
                  <td
                    key={`${row.id}-${chunkIndex}-${cellIndex}`}
                    className={[
                      item ? "single-day-print-task-cell" : "",
                      isPersonalTaskForGa ? "single-day-print-cell-personal-ga" : "",
                    ].filter(Boolean).join(" ") || undefined}
                  >
                    {item ? (
                      <div className="single-day-print-task-content">
                        <div>
                          {chunkIndex * 6 + cellIndex + 1}.{" "}
                          {renderWfcText(
                            isPersonalRowId(row.id)
                              ? commonPrintPersonalTaskTitle(item)
                              : commonPrintTaskTitle(item)
                          )}
                        </div>
                        <div className="single-day-print-task-dates">
                          {formatFastTaskCardDate(item.startDate || item.entryDate) ? (
                            <span>{formatFastTaskCardDate(item.startDate || item.entryDate)}</span>
                          ) : null}
                          {formatFastTaskCardDate(item.dueDate, item.entryDate) ? (
                            <span className={isFastTaskDateOnTarget(item.dueDate, item.entryDate) ? "due today" : "due"}>
                              {formatFastTaskCardDate(item.dueDate, item.entryDate)}
                            </span>
                          ) : null}
                        </div>
                      </div>
                    ) : ""}
                  </td>
                )
              })}
            </tr>
          )
        })
      })

  return (
    <div
      className="common-view-page-root"
      style={{
        display: "flex",
        flexDirection: "column",
        minHeight: "100vh",
        background: "#ffffff",
        ["--common-sticky-offset" as any]: stickyOffset,
      }}
    >
      <style>{`
        * { box-sizing: border-box; }
        :root {
          --swim-border: #d7dbe3;
          --swim-text: #0f172a;
          --swim-muted: #6b7280;
          --delay-bg: #fff4e6;
          --delay-accent: #f59e0b;
          --absence-bg: #ffe9e9;
          --absence-accent: #ef4444;
          --leave-bg: #e9f9ef;
          --leave-accent: #22c55e;
          --blocked-bg: #ffe7ea;
          --blocked-accent: #be123c;
          --oneh-bg: #e0f2fe;
          --oneh-accent: #0ea5e9;
          --personal-bg: #f3e8ff;
          --personal-accent: #a855f7;
          --external-bg: #e0f2fe;
          --external-accent: #0284c7;
          --internal-bg: #f1f5f9;
          --internal-accent: #475569;
          --bz-bg: #e6fffb;
          --bz-accent: #14b8a6;
          --r1-bg: #dcfce7;
          --r1-accent: #16a34a;
          --problem-bg: #ecfeff;
          --problem-accent: #0891b2;
          --feedback-bg: #e2e8f0;
          --feedback-accent: #64748b;
          --externalHoliday-bg: #fce7f3;
          --externalHoliday-accent: #ec4899;
          --priority-bg: #fef3c7;
          --priority-accent: #d97706;
          --diamond-bg: #cffafe;
          --diamond-accent: #0891b2;
          --cell-bg: #ffffff;
          --cell-tint: #f9fafb;
          --swim-col-width: 280px;
        }
        
        /* Modern Header */
        .common-sticky {
          position: sticky;
          top: 0;
          z-index: 20;
          background: #ffffff;
        }
        .top-header { 
          background: linear-gradient(135deg, #94a3b8 0%, #64748b 100%);
          padding: 12px 24px; 
          display: flex; 
          justify-content: space-between; 
          align-items: center; 
          flex-shrink: 0;
          box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }
        .page-title h1 { 
          font-size: 20px; 
          margin-bottom: 2px; 
          color: white;
          font-weight: 700;
          letter-spacing: -0.5px;
        }
        .page-title p { 
          font-size: 11px; 
          color: rgba(255, 255, 255, 0.9); 
          margin: 0; 
        }
        
        /* Modern Buttons */
        .btn-primary { 
          background: white; 
          color: #475569; 
          border: none; 
          padding: 6px 14px; 
          border-radius: 6px; 
          font-size: 12px; 
          font-weight: 600;
          cursor: pointer; 
          transition: all 0.2s ease;
          box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }
        .btn-primary:hover { 
          background: #f8f9fa;
          transform: translateY(-1px);
          box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
        }
        .btn-outline { 
          background: rgba(255, 255, 255, 0.2); 
          color: white; 
          border: 1px solid rgba(255, 255, 255, 0.3); 
          padding: 6px 14px; 
          border-radius: 6px; 
          font-size: 12px; 
          font-weight: 600;
          cursor: pointer; 
          transition: all 0.2s ease;
        }
        .btn-outline:hover { 
          background: rgba(255, 255, 255, 0.3);
          border-color: rgba(255, 255, 255, 0.5);
        }
        .btn-outline.active {
          background: #ffffff;
          color: #0f172a;
          border-color: #ffffff;
          box-shadow: 0 4px 10px rgba(15, 23, 42, 0.2);
        }

        /* Button style for light panels (dark text on light background) */
        .btn-surface {
          background: #f8fafc;
          color: #0f172a;
          border: 1px solid #cbd5e1;
          padding: 8px 12px;
          border-radius: 10px;
          font-size: 12px;
          font-weight: 700;
          cursor: pointer;
          transition: all 0.15s ease;
        }
        .btn-surface:hover:not(:disabled) {
          background: #f1f5f9;
          border-color: #94a3b8;
        }
        .btn-surface:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }
        .btn-surface.danger {
          background: #fff1f2;
          color: #b91c1c;
          border-color: #fecaca;
        }
        .btn-surface.danger:hover:not(:disabled) {
          background: #ffe4e6;
          color: #991b1b;
          border-color: #fca5a5;
        }

        .external-checklist-media {
          border: 1px solid #e2e8f0;
          border-radius: 10px;
          background: #ffffff;
          padding: 10px;
          margin-bottom: 12px;
        }
        .external-checklist-media-title {
          font-size: 12px;
          font-weight: 700;
          color: #0f172a;
          margin-bottom: 8px;
        }
        .external-checklist-media img {
          width: 100%;
          height: auto;
          border-radius: 8px;
          border: 1px solid #e2e8f0;
          display: block;
          background: #f8fafc;
        }
        .external-checklist-media-hint {
          font-size: 12px;
          color: #64748b;
          margin-top: 8px;
          line-height: 1.4;
        }

        .no-print { display: inline-flex; }
        .print-scale-hint {
          font-size: 11px;
          color: #475569;
          font-weight: 600;
          white-space: nowrap;
        }
        .hide-in-print { display: none !important; }
        .hide-when-all-days { display: none !important; }
        .swimlane-print-title { display: none; }
        .single-day-print-table { display: none; }
        .one-h-print-checklists,
        .one-h-marker-legend { display: none; }
        .print-header,
        .print-footer {
          display: none;
        }
        @media print {
          @page {
            margin: 0.45in 0.35in 0.51in 0.35in;
            size: landscape;
          }
          .no-print { display: none !important; }
          .hide-in-print { display: none !important; }
          .swimlane-delete,
          .swimlane-review-btn { display: none !important; }
          .week-table-delete { display: none !important; }
          aside, header, .command-palette, .top-header, .common-toolbar, .meeting-panel, .modal {
            display: none !important;
          }
          *, *::before, *::after { 
            box-sizing: border-box;
          }
          body, html { 
            background: white;
            margin: 0;
            padding: 0;
            width: 100%;
            overflow: visible;
          }
          main { 
            padding: 0 !important;
            margin: 0 !important;
          }
          .view-container { 
            padding: 0 !important;
            margin: 0 !important;
            background: white;
            overflow: visible !important;
          }
          .print-page {
            position: relative;
            padding-top: 0;
            padding-bottom: 0.35in;
            margin: 0;
            width: 100%;
            max-width: 100%;
            overflow: visible;
            page-break-before: auto;
          }
          .week-table-view { 
            display: block !important; 
            padding-top: 0;
            padding-bottom: 0.35in;
            margin: 0;
            width: 100%;
            max-width: 100%;
            overflow: visible;
            page-break-before: auto;
            page-break-inside: auto !important;
          }
          .print-header {
            display: grid;
            grid-template-columns: 1fr auto 1fr;
            align-items: center;
            margin-bottom: 8px;
            margin-top: 0;
            padding-top: 0;
            position: static !important;
            transform: none !important;
            page-break-after: avoid;
          }
          .week-table {
            page-break-inside: auto;
            margin-top: 0;
            border: 3px solid #111827 !important;
          }
          .print-title {
            font-size: 16px;
            font-weight: 700;
            text-transform: uppercase;
            text-align: center;
            color: #0f172a;
          }
          .print-datetime {
            text-align: right;
            font-size: 10px;
            color: #334155;
          }
          .print-footer {
            position: fixed;
            left: 0;
            right: 0;
            bottom: 0.2in;
            display: grid;
            grid-template-columns: 1fr auto 1fr;
            padding-left: 0.1in;
            padding-right: 0.1in;
            font-size: 8px;
            line-height: 1;
            color: #334155;
          }
          .print-page-count {
            grid-column: 2;
            text-align: center;
          }
          .print-initials {
            grid-column: 3;
            text-align: right;
          }
          .week-table-onepage {
            --week-table-print-scale: 1;
            position: relative;
            padding-bottom: 28px;
            overflow: visible;
            page-break-inside: auto;
          }
          .week-table-onepage-content {
            width: 100%;
            zoom: var(--week-table-print-scale);
          }
          .week-table-onepage .print-footer {
            position: fixed;
            left: 0;
            right: 0;
            bottom: 0.2in;
            padding-left: 0.1in;
            padding-right: 0.1in;
          }
          .single-day-print .swimlane-board {
            display: none !important;
          }
          .single-day-print {
            --single-day-print-scale: 1;
            padding-bottom: 28px;
          }
          .single-day-print-content {
            width: 100%;
            zoom: var(--single-day-print-scale);
          }
          .one-h-print-checklists {
            display: grid !important;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 12px;
            margin: 0 0 12px;
            page-break-inside: avoid;
          }
          .one-h-marker-legend {
            display: flex !important;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
            margin: 0 0 8px;
            padding: 5px 7px;
            border: 1px solid #93c5fd !important;
            border-radius: 5px;
            background: #eff6ff !important;
            color: #0f2a5f !important;
            font-size: 8px;
            font-weight: 700;
            page-break-inside: avoid;
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
          }
          .one-h-marker-legend b {
            color: #dc2626 !important;
            font-size: 13px;
            font-weight: 900;
          }
          .one-h-marker-legend b.compact-marker {
            font-size: 8px;
          }
          .one-h-marker-legend i {
            color: #0f2a5f !important;
            font-size: 19px;
            font-style: normal;
            font-weight: 900;
            line-height: 1;
          }
          .one-h-print-checklist-title {
            background: #eef2ff !important;
            border-left: 5px solid #2563eb !important;
            padding: 5px 7px;
            color: #0f172a !important;
            font-size: 9px;
            font-weight: 700;
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
          }
          .one-h-print-checklist-items {
            border: 1px solid #64748b !important;
            padding: 4px 6px;
            color: #000 !important;
            font-size: 7px;
            line-height: 1.3;
          }
          .one-h-print-checklist-day-label {
            grid-column: 1 / -1;
            margin: 0 0 3px;
            font-weight: 800;
          }
          .one-h-print-checklist-separator {
            font-size: 12px;
            font-weight: 900;
            line-height: 7px;
          }
          .one-h-print-checklist-description {
            color: #475569 !important;
          }
          .single-day-print-table tbody tr.print-slot-start > th,
          .single-day-print-table tbody tr.print-slot-start > td {
            border-top: 2px solid #111827 !important;
          }
          .single-day-print-table tbody tr.print-slot-continuation > td {
            border-top: 1px solid #cbd5e1 !important;
          }
          .single-day-print-table .print-slot-number,
          .single-day-print-table .print-slot-type {
            font-weight: 700 !important;
          }
          html,
          body,
          main,
          .common-view-page-root,
          .common-view-page-root .view-container,
          .single-day-print,
          .print-page.single-day-print,
          .single-day-print-table,
          .single-day-print-table tbody,
          .single-day-print-table tr,
          .single-day-print-table th,
          .single-day-print-table td {
            background-color: transparent !important;
            background-image: none !important;
            -webkit-print-color-adjust: economy !important;
            print-color-adjust: economy !important;
          }
          .single-day-print-table {
            display: table !important;
            width: 100% !important;
            border-collapse: collapse !important;
            table-layout: fixed;
            color: #000;
            font-size: 9px;
            line-height: 1.2;
          }
          .single-day-print-number-column {
            width: 20px;
          }
          .single-day-print-label-column {
            width: 78px;
          }
          .single-day-print-meetings-table {
            margin-top: 12px;
          }
          .single-day-print-table th,
          .single-day-print-table td {
            border: 1px solid #000 !important;
            padding: 4px 5px;
            vertical-align: top;
            text-align: left;
            font-weight: 400 !important;
            overflow-wrap: anywhere;
          }
          .single-day-print-table thead th:first-child,
          .single-day-print-table tbody th:first-child {
            width: 20px;
            min-width: 20px;
            padding-left: 3px;
            padding-right: 3px;
            white-space: nowrap;
          }
          .single-day-print-table tbody th:nth-child(2) {
            padding-left: 2px;
            padding-right: 2px;
          }
          .single-day-print-table thead th {
            font-weight: 700 !important;
            text-align: center;
            vertical-align: middle;
          }
          .single-day-print-table td.single-day-print-cell-personal-ga {
            background-color: #d8b4fe !important;
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
          }
          .single-day-print-task-content {
            min-height: 42px;
          }
          .single-day-print-table td.single-day-print-task-cell {
            position: relative;
            padding-top: 8px;
            padding-bottom: 27px;
          }
          .single-day-print-meetings-table td.single-day-print-task-cell {
            padding-top: 8px;
            font-size: 13px;
            line-height: 1.3;
          }
          .single-day-print-task-dates {
            position: absolute;
            left: 5px;
            right: 5px;
            bottom: 4px;
            display: flex;
            align-items: flex-end;
            justify-content: space-between;
            gap: 4px;
            white-space: nowrap;
          }
          .single-day-print-task-dates span {
            display: inline-flex;
            box-sizing: border-box;
            height: 18px;
            align-items: center;
            border: 1px solid #93c5fd !important;
            border-radius: 3px;
            background: #eff6ff !important;
            color: #1d4ed8 !important;
            padding: 1px 4px;
            font-weight: 800;
            line-height: 1;
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
          }
          .single-day-print-task-dates span.due {
            border: 3px solid #b91c1c !important;
            padding: 0 2px;
          }
          .single-day-print-task-dates span.due.today {
            height: 26px;
            border: 1px solid #991b1b !important;
            border-radius: 4px;
            background: #dc2626 !important;
            color: #ffffff !important;
            padding: 3px 9px;
            font-size: 14px;
            font-weight: 900;
            box-shadow: 0 1px 3px rgba(127, 29, 29, 0.45);
          }
          /* A one-day Common View printout is the compact fast-task report. */
          .single-day-print .swimlane-row:not(
            .swimlane-row-waitingClient,
            .swimlane-row-blocked,
            .swimlane-row-oneH10,
            .swimlane-row-oneH11,
            .swimlane-row-oneH1150,
            .swimlane-row-oneH1420,
            .swimlane-row-oneH1550,
            .swimlane-row-oneHNoSlot,
            .swimlane-row-r1,
            .swimlane-row-personalGA,
            .swimlane-row-personalKA,
            .swimlane-row-personalGENT,
            .swimlane-row-personalPX
          ) {
            display: none !important;
          }
          .single-day-print .swimlane-board,
          .single-day-print .swimlane-row,
          .single-day-print .swimlane-header,
          .single-day-print .swimlane-cell,
          .single-day-print .swimlane-cell::before,
          .single-day-print .swimlane-cell::after {
            background: #fff !important;
            background-image: none !important;
            color: #000 !important;
            box-shadow: none !important;
          }
          .single-day-print .swimlane-board {
            border: 1px solid #000 !important;
          }
          .single-day-print .swimlane-row {
            border: 0 !important;
          }
          .single-day-print .swimlane-row + .swimlane-row {
            border-top: 0 !important;
          }
          .single-day-print .swimlane-index-col,
          .single-day-print .swimlane-header {
            border-right: 1px solid #000 !important;
            border-bottom: 1px solid #000 !important;
          }
          .single-day-print .swimlane-cell {
            border: 0 !important;
            border-right: 1px solid #000 !important;
            border-bottom: 1px solid #000 !important;
          }
          .single-day-print .swimlane-cell:nth-child(3n) {
            border-right: 1px solid #000 !important;
          }
          .single-day-print .swimlane-cell.swimlane-cell-user-break::before {
            display: none !important;
          }
          .single-day-print .swimlane-index-col,
          .single-day-print .swimlane-badges,
          .single-day-print .swimlane-info-wrap,
          .single-day-print .swimlane-title-row-toggle,
          .single-day-print .swimlane-assignees,
          .single-day-print .swimlane-note-toggle,
          .single-day-print .swimlane-meta,
          .single-day-print .fast-task-order-badge,
          .single-day-print .period-indicator,
          .single-day-print .deadline-indicator,
          .single-day-print .time-indicator {
            display: none !important;
          }
          .single-day-print .swimlane-header,
          .single-day-print .swimlane-cell {
            padding: 6px 8px !important;
          }
          .single-day-print .swimlane-content {
            grid-template-columns: repeat(6, minmax(0, 1fr)) !important;
            grid-auto-columns: auto !important;
          }
          .single-day-print .swimlane-cell.empty {
            display: flex !important;
          }
          .single-day-print .swimlane-cell {
            min-height: 0 !important;
            height: auto !important;
          }
          .single-day-print .swimlane-title-row,
          .single-day-print .swimlane-title-main,
          .single-day-print .swimlane-title {
            display: block !important;
            width: 100% !important;
          }
          .single-day-print .swimlane-title-row {
            flex: 0 0 auto !important;
          }
          .single-day-print .swimlane-title-text {
            display: none !important;
          }
          .single-day-print .swimlane-print-title {
            display: block !important;
            color: #000 !important;
            font-weight: 400 !important;
            white-space: normal !important;
            overflow: visible !important;
          }
          .single-day-print .swimlane-header,
          .single-day-print .swimlane-label {
            font-weight: 400 !important;
          }
          .swimlane-board { gap: 12px; }
          .swimlane-row { break-inside: avoid; page-break-inside: avoid; }
          .swimlane-row-nav { display: none !important; }
          .swimlane-content-scroll { overflow: visible !important; padding-right: 0; }
          .swimlane-content {
            grid-auto-flow: row !important;
            grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
            grid-auto-columns: auto !important;
            min-width: 0 !important;
            width: 100% !important;
          }
          .swimlane-board {
            border: 1px solid #111827 !important;
            border-radius: 0 !important;
            box-shadow: none !important;
          }
          .swimlane-row + .swimlane-row {
            border-top: 2px solid #111827 !important;
          }
          .swimlane-row {
            margin-top: 6px;
          }
            .swimlane-header,
            .swimlane-cell {
              padding-top: 18px;
              padding-bottom: 18px;
            }
            .swimlane-cell {
              background: #ffffff !important;
              color: #111827 !important;
              position: relative !important;
              padding-right: 60px !important;
              overflow: visible !important;
              min-width: 0 !important;
            }
          .swimlane-header,
          .swimlane-badge,
          .swimlane-index {
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
          }
          .common-view-title {
            display: none !important;
          }
          .swimlane-header.delay { background: var(--delay-bg) !important; color: #c2410c !important; }
          .swimlane-header.absence { background: var(--absence-bg) !important; color: #b91c1c !important; }
          .swimlane-header.leave { background: var(--leave-bg) !important; color: #15803d !important; }
          .swimlane-header.externalHoliday { background: var(--externalHoliday-bg) !important; color: #be185d !important; }
          .swimlane-header.blocked { background: var(--blocked-bg) !important; color: #9f1239 !important; }
          .swimlane-header.waiting-client { background: #e2c15b !important; color: #4f3a00 !important; }
          .swimlane-header.oneh { background: var(--oneh-bg) !important; color: #0369a1 !important; }
          .swimlane-header.personal { background: var(--personal-bg) !important; color: #7e22ce !important; }
          .swimlane-header.external { background: var(--external-bg) !important; color: #0369a1 !important; }
          .swimlane-header.internal { background: var(--internal-bg) !important; color: #334155 !important; }
          .swimlane-header.bz { background: var(--bz-bg) !important; color: #0f766e !important; }
          .swimlane-header.r1 { background: var(--r1-bg) !important; color: #15803d !important; }
          .swimlane-header.problem { background: var(--problem-bg) !important; color: #0e7490 !important; }
          .swimlane-header.feedback { background: var(--feedback-bg) !important; color: #475569 !important; }
          .swimlane-header.priority { background: var(--priority-bg) !important; color: #b45309 !important; }
          .swimlane-header.diamond { background: var(--diamond-bg) !important; color: #0e7490 !important; }
          .swimlane-badge.delay { border-color: var(--delay-accent) !important; color: #c2410c !important; }
          .swimlane-badge.absence { border-color: var(--absence-accent) !important; color: #b91c1c !important; }
          .swimlane-badge.leave { border-color: var(--leave-accent) !important; color: #15803d !important; }
          .swimlane-badge.externalHoliday { border-color: var(--externalHoliday-accent) !important; color: #be185d !important; }
          .swimlane-badge.blocked { border-color: var(--blocked-accent) !important; color: #9f1239 !important; }
          .swimlane-badge.waiting-client { border-color: #b8860b !important; color: #4f3a00 !important; }
          .swimlane-badge.oneh { border-color: var(--oneh-accent) !important; color: #0369a1 !important; }
          .swimlane-badge.personal { border-color: var(--personal-accent) !important; color: #7e22ce !important; }
          .swimlane-badge.external { border-color: var(--external-accent) !important; color: #0369a1 !important; }
          .swimlane-badge.internal { border-color: var(--internal-accent) !important; color: #334155 !important; }
          .swimlane-badge.bz { border-color: var(--bz-accent) !important; color: #0f766e !important; }
          .swimlane-badge.r1 { border-color: var(--r1-accent) !important; color: #15803d !important; }
          .swimlane-badge.problem { border-color: var(--problem-accent) !important; color: #0e7490 !important; }
          .swimlane-badge.feedback { border-color: var(--feedback-accent) !important; color: #475569 !important; }
          .swimlane-badge.priority { border-color: var(--priority-accent) !important; color: #b45309 !important; }
          .swimlane-badge.diamond { border-color: var(--diamond-accent) !important; color: #0e7490 !important; }
          .swimlane-header,
          .swimlane-cell {
            border-color: #111827 !important;
          }
            .swimlane-title-row {
              display: flex !important;
              flex-direction: column !important;
              align-items: flex-start !important;
              gap: 6px !important;
              width: 100% !important;
              padding-right: 0 !important;
            }
            .swimlane-title {
              flex: 1 1 auto !important;
              min-width: 0 !important;
              width: 100% !important;
            }
            .swimlane-date {
              font-size: 12px !important;
              color: var(--swim-muted) !important;
              line-height: 1.2 !important;
            }
            .swimlane-assignees {
              display: flex !important;
              gap: 6px !important;
              flex-wrap: wrap !important;
              align-items: center !important;
              justify-content: flex-start !important;
              margin-left: 0 !important;
              flex-shrink: 0 !important;
              z-index: 2 !important;
            }
            .swimlane-avatar {
              display: inline-flex !important;
              align-items: center !important;
              justify-content: center !important;
              min-width: 24px !important;
              height: 20px !important;
              padding: 0 5px !important;
              font-size: 9px !important;
              line-height: 1 !important;
              white-space: nowrap !important;
              word-break: keep-all !important;
              overflow-wrap: normal !important;
              flex-shrink: 0 !important;
            }
          }
        
        /* View Container */
        .view-container { 
          padding: 16px 24px; 
          overflow: visible; 
          flex-grow: 1; 
          min-height: 0;
          position: relative;
          background: linear-gradient(to bottom, #f8f9fa 0%, #ffffff 100%);
        }
        .common-view-loading {
          position: absolute;
          inset: 54px 24px 16px;
          z-index: 40;
          min-height: 320px;
          display: flex;
          align-items: flex-start;
          justify-content: center;
          gap: 10px;
          padding-top: 72px;
          color: #475569;
          font-size: 14px;
          font-weight: 700;
          background: rgba(248, 250, 252, 0.98);
        }
        .common-view-loading-spinner {
          width: 18px;
          height: 18px;
          border: 2px solid #bfdbfe;
          border-top-color: #2563eb;
          border-radius: 999px;
          animation: common-view-loading-spin 0.7s linear infinite;
        }
        @keyframes common-view-loading-spin {
          to { transform: rotate(360deg); }
        }
        .common-view-title {
          text-align: center;
          font-weight: 800;
          font-size: 16px;
          letter-spacing: 0.6px;
          padding: 10px 0;
          color: #0f172a;
          text-transform: uppercase;
          position: sticky;
          top: var(--common-sticky-offset, 0px);
          z-index: 15;
          background: #ffffff;
          border-bottom: 1px solid #e2e8f0;
          box-shadow: 0 2px 6px rgba(15, 23, 42, 0.06);
        }
        .meeting-panel {
          margin: 16px 24px 0;
          background: #ffffff;
          border: 1px solid #e2e8f0;
          border-radius: 16px;
          padding: 16px 18px;
          box-shadow: 0 10px 20px rgba(15, 23, 42, 0.06);
        }
        .external-meetings-panel {
          margin-top: 12px;
        }
        .meeting-panel-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
        }
        .meeting-title {
          font-size: 14px;
          font-weight: 700;
          color: #0f172a;
        }
        .meeting-subtitle {
          font-size: 12px;
          color: #64748b;
          margin-top: 2px;
        }
        .meeting-tabs {
          display: flex;
          flex-wrap: wrap;
          gap: 12px;
          margin-top: 12px;
        }
        .meeting-create-card {
          margin-top: 12px;
          border: 1px dashed #cbd5e1;
          border-radius: 12px;
          padding: 12px;
          background: #f8fafc;
        }
        .meeting-create-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
        }
        .meeting-create-title {
          font-size: 13px;
          font-weight: 700;
          color: #0f172a;
        }
        .meeting-create-subtitle {
          font-size: 12px;
          color: #64748b;
          margin-top: 2px;
        }
        .meeting-create-grid {
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 10px;
          margin-top: 10px;
        }
        .meeting-create-field {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .meeting-create-field label {
          font-size: 12px;
          font-weight: 700;
          color: #475569;
        }
        .meeting-create-field select {
          border: 1px solid #e2e8f0;
          border-radius: 10px;
          padding: 8px 10px;
          background: #ffffff;
          color: #0f172a;
          font-size: 12px;
          font-weight: 600;
        }
        .meeting-create-note {
          grid-column: 1 / -1;
        }
        .meeting-create-error {
          margin-top: 8px;
          font-size: 12px;
          color: #b91c1c;
          font-weight: 600;
        }
        .meeting-dropdown {
          display: flex;
          flex-direction: column;
          gap: 6px;
          min-width: 220px;
        }
        .meeting-dropdown label {
          font-size: 12px;
          font-weight: 700;
          color: #475569;
        }
        .meeting-dropdown select {
          border: 1px solid #e2e8f0;
          border-radius: 10px;
          padding: 8px 10px;
          background: #ffffff;
          color: #0f172a;
          font-size: 12px;
          font-weight: 600;
        }
        .meeting-chip {
          background: #f1f5f9;
          border: 1px solid #e2e8f0;
          color: #334155;
          padding: 6px 10px;
          border-radius: 999px;
          font-size: 12px;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s ease;
        }
        .meeting-chip.active {
          background: #2563eb;
          border-color: #2563eb;
          color: #ffffff;
        }
        .meeting-table-card {
          margin-top: 14px;
          border: 1px solid #e2e8f0;
          border-radius: 12px;
          overflow: hidden;
          background: #ffffff;
        }
        .meeting-table-header {
          padding: 10px 12px;
          background: #f8fafc;
          border-bottom: 1px solid #e2e8f0;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
        }
        .meeting-table-title {
          font-size: 13px;
          font-weight: 700;
          color: #0f172a;
        }
        .meeting-table-meta {
          font-size: 12px;
          color: #64748b;
        }
        .meeting-note {
          padding: 8px 10px;
          background: #fff1f2;
          color: #b91c1c;
          font-size: 12px;
          font-weight: 700;
          border-bottom: 1px solid #fecdd3;
        }
        .meeting-table-wrap {
          overflow-x: auto;
        }
        .meeting-table {
          width: 100%;
          table-layout: fixed;
          border-collapse: collapse;
          font-size: 12px;
        }
        .external-meetings-grid {
          display: grid;
          grid-template-columns: minmax(360px, 640px) minmax(0, 1fr);
          gap: 18px;
          margin-top: 14px;
        }
        .external-meeting-form {
          align-self: start;
          padding: 14px;
          border: 1px solid #e2e8f0;
          border-radius: 12px;
          background: #f8fafc;
        }
        .external-meeting-form-title {
          font-size: 13px;
          font-weight: 700;
          color: #0f172a;
          margin-bottom: 12px;
        }
        .external-meeting-list-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          margin-bottom: 8px;
        }
        .external-meeting-list-header .external-meeting-form-title {
          margin-bottom: 0;
        }
        .external-meeting-filter {
          display: inline-flex;
          align-items: center;
          gap: 2px;
          border: 1px solid #dbe4f0;
          border-radius: 8px;
          background: #f8fafc;
          padding: 2px;
        }
        .external-meeting-filter button {
          border: 0;
          border-radius: 6px;
          background: transparent;
          color: #475569;
          cursor: pointer;
          font-size: 12px;
          font-weight: 700;
          line-height: 1;
          padding: 7px 10px;
        }
        .external-meeting-filter button.active {
          background: #2563eb;
          color: #ffffff;
          box-shadow: 0 3px 8px rgba(37, 99, 235, 0.22);
        }
        .external-meeting-fields {
          display: grid;
          gap: 10px;
        }
        .external-meeting-row {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 10px;
          align-items: start;
        }
        .external-meeting-field-stack {
          min-width: 0;
          display: grid;
          gap: 5px;
        }
        .external-create-internal-option {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 9px 11px;
          border: 1px solid #dbe4f0;
          border-radius: 9px;
          background: #ffffff;
          color: #334155;
          cursor: pointer;
        }
        .external-create-internal-option input {
          width: 16px;
          height: 16px;
          margin: 0;
          accent-color: #2563eb;
        }
        .external-create-internal-copy {
          min-width: 0;
          display: grid;
          gap: 1px;
          flex: 1;
        }
        .external-create-internal-copy strong {
          color: #0f172a;
          font-size: 12px;
        }
        .external-create-internal-copy small {
          color: #64748b;
          font-size: 11px;
        }
        .external-create-internal-status {
          flex: 0 0 auto;
          padding: 3px 8px;
          border-radius: 999px;
          background: #e0ecff;
          color: #1d4ed8;
          font-size: 11px;
          font-weight: 700;
        }
        .external-create-internal-status.off {
          background: #f1f5f9;
          color: #64748b;
        }
        .external-meeting-hint {
          font-size: 12px;
          color: #64748b;
        }
        .external-person-picker {
          position: relative;
        }
        .external-person-picker.compact {
          width: min(100%, 320px);
        }
        .external-person-picker-trigger {
          width: 100%;
          min-height: 36px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          padding: 7px 11px;
          border: 1px solid #cbd5e1;
          border-radius: 8px;
          background: #ffffff;
          color: #0f172a;
          cursor: pointer;
          font-size: 12px;
          font-weight: 600;
        }
        .external-person-picker-trigger:hover,
        .external-person-picker-trigger.active {
          border-color: #3b82f6;
          box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1);
        }
        .external-person-picker-count {
          min-width: 22px;
          height: 20px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          border-radius: 999px;
          background: #eff6ff;
          color: #2563eb;
          font-size: 11px;
          font-weight: 700;
        }
        .external-person-picker-menu {
          position: absolute;
          top: calc(100% + 6px);
          left: 0;
          right: 0;
          z-index: 250;
          padding: 10px;
          border: 1px solid #cbd5e1;
          border-radius: 10px;
          background: #ffffff;
          box-shadow: 0 14px 32px rgba(15, 23, 42, 0.18);
        }
        .external-person-picker-search {
          width: 100%;
          height: 34px;
          padding: 7px 10px;
          border: 1px solid #dbe4f0;
          border-radius: 7px;
          background: #f8fafc;
          color: #0f172a;
          font-size: 12px;
          outline: none;
        }
        .external-person-picker-search:focus {
          border-color: #3b82f6;
          background: #ffffff;
          box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1);
        }
        .external-person-picker-list {
          max-height: 180px;
          overflow-y: auto;
          margin-top: 7px;
          padding-right: 3px;
        }
        .external-person-picker-option {
          display: flex;
          align-items: center;
          gap: 9px;
          padding: 7px 8px;
          border-radius: 7px;
          color: #334155;
          cursor: pointer;
          font-size: 12px;
        }
        .external-person-picker-option:hover {
          background: #f1f5f9;
        }
        .external-person-picker-option input {
          width: 15px;
          height: 15px;
          margin: 0;
          accent-color: #2563eb;
        }
        .external-person-picker-empty {
          padding: 16px 8px;
          color: #94a3b8;
          text-align: center;
          font-size: 12px;
        }
        .external-person-picker-footer {
          display: flex;
          justify-content: flex-end;
          margin-top: 8px;
          padding-top: 8px;
          border-top: 1px solid #e2e8f0;
        }
        .external-person-picker-done {
          border: 0;
          border-radius: 7px;
          background: #2563eb;
          color: #ffffff;
          cursor: pointer;
          padding: 7px 14px;
          font-size: 12px;
          font-weight: 700;
        }
        .external-person-chips {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          margin-top: 7px;
        }
        .external-person-chip {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          max-width: 100%;
          padding: 3px 8px;
          border: 1px solid #dbe4f0;
          border-radius: 999px;
          background: #ffffff;
          color: #334155;
          font-size: 11px;
          font-weight: 600;
        }
        button.external-person-chip {
          cursor: pointer;
        }
        button.external-person-chip:hover {
          border-color: #bfdbfe;
          background: #eff6ff;
        }
        .external-person-chip-remove {
          color: #64748b;
          font-size: 13px;
          line-height: 1;
        }
        .external-meeting-person-summary {
          min-width: 0;
          display: flex;
          align-items: center;
          gap: 7px;
          margin-top: 6px;
          color: #64748b;
          font-size: 11px;
        }
        .external-meeting-person-count {
          flex: 0 0 auto;
          padding: 2px 7px;
          border-radius: 999px;
          background: #f1f5f9;
          color: #475569;
          font-weight: 700;
        }
        .external-meeting-person-names {
          min-width: 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .external-meeting-cards {
          display: grid;
          gap: 10px;
        }
        .external-meeting-card {
          border: 1px solid #e2e8f0;
          border-radius: 12px;
          padding: 10px 12px;
          background: #ffffff;
          box-shadow: 0 6px 14px rgba(15, 23, 42, 0.04);
        }
        .outlook-manual { background: #fff4cc !important; border-color: #d6b44c !important; }
        .outlook-violet { background: #e5e7fb !important; border-color: #7167d9 !important; }
        .outlook-blue { background: #dcecff !important; border-color: #5b9fe8 !important; }
        .outlook-teal { background: #cceff1 !important; border-color: #35abb4 !important; }
        .outlook-yellow { background: #ffe38f !important; border-color: #e6ad00 !important; }
        .outlook-brown { background: #c9a98a !important; border-color: #8b623d !important; }
        .outlook-orange { background: #ffd7ad !important; border-color: #e87922 !important; }
        .outlook-red { background: #ffd5dc !important; border-color: #e55361 !important; }
        .external-meeting-title {
          font-size: 13px;
          font-weight: 700;
          color: #0f172a;
        }
        .external-meeting-meta {
          display: flex;
          flex-wrap: wrap;
          gap: 8px 12px;
          font-size: 12px;
          color: #64748b;
          margin-top: 4px;
        }
        .external-meeting-empty {
          border: 1px dashed #cbd5e1;
          border-radius: 12px;
          padding: 12px;
          font-size: 12px;
          color: #94a3b8;
        }
        @media (max-width: 900px) {
          .external-meetings-grid {
            grid-template-columns: 1fr;
          }
          .meeting-create-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }
        }
        @media (max-width: 720px) {
          .external-meeting-row {
            grid-template-columns: 1fr;
          }
          .meeting-create-grid {
            grid-template-columns: 1fr;
          }
        }
        .meeting-table th {
          background: #e2e8f0;
          text-align: left;
          padding: 8px 10px;
          font-weight: 700;
          color: #1f2937;
          border-bottom: 1px solid #cbd5e1;
          white-space: nowrap;
        }
        .meeting-table td {
          border-top: 1px solid #e2e8f0;
          padding: 8px 10px;
          vertical-align: top;
          color: #0f172a;
          white-space: nowrap;
        }
        .meeting-table td.meeting-topic-cell {
          width: 860px;
          min-width: 860px;
          max-width: 860px;
          white-space: normal !important;
          overflow-wrap: anywhere;
          word-break: normal;
          line-height: 1.45;
        }
        .meeting-topic-text {
          display: block;
          width: 100%;
          max-width: 100%;
          white-space: normal;
          overflow-wrap: anywhere;
          word-break: break-word;
          line-height: 1.45;
        }
        .meeting-topic-header {
          width: 860px;
          min-width: 860px;
          max-width: 860px;
        }
        .meeting-topic-header-edit {
          border: 0;
          background: transparent;
          color: inherit;
          cursor: pointer;
          display: block;
          font: inherit;
          font-weight: inherit;
          padding: 0;
          text-align: left;
          width: 100%;
        }
        .meeting-topic-header-edit:hover {
          color: #1d4ed8;
        }
        .meeting-topic-header-input {
          width: 100%;
          border: 1px solid #93c5fd;
          border-radius: 6px;
          background: #ffffff;
          color: #0f172a;
          font: inherit;
          font-weight: 700;
          padding: 6px 8px;
          outline: none;
        }
        .meeting-topic-header-input:focus {
          border-color: #2563eb;
          box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.18);
        }
        .meeting-topic-cell .input {
          white-space: normal;
        }
        .meeting-check-cell {
          text-align: center;
          vertical-align: middle;
        }
        .meeting-check-select {
          width: 42px;
          height: 30px;
          border: 1px solid #cbd5e1;
          border-radius: 8px;
          background: #ffffff;
          color: #334155;
          font-size: 14px;
          font-weight: 800;
          text-align: center;
          cursor: pointer;
        }
        .meeting-check-select.status-check {
          border-color: #86efac;
          background: #f0fdf4;
          color: #15803d;
        }
        .meeting-check-select.status-x {
          border-color: #fecaca;
          background: #fef2f2;
          color: #b91c1c;
        }
        .meeting-check-select.status-o {
          border-color: #bfdbfe;
          background: #eff6ff;
          color: #1d4ed8;
        }
        .btn-icon {
          width: 28px;
          height: 28px;
          border-radius: 8px;
          border: 1px solid #e2e8f0;
          background: #ffffff;
          color: #475569;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
        }
        .btn-icon:hover {
          background: #f1f5f9;
          color: #334155;
        }
        .btn-icon:disabled {
          cursor: not-allowed;
          opacity: 0.45;
          transform: none;
        }
        .btn-icon:disabled:hover {
          background: #ffffff;
          color: #475569;
        }
        .btn-icon.danger {
          color: #b91c1c;
          border-color: #fecaca;
          background: #fff1f2;
        }
        .btn-icon.danger:hover {
          background: #ffe4e6;
          color: #991b1b;
        }
        .meeting-row-actions {
          display: flex;
          flex-wrap: nowrap;
          gap: 6px;
          align-items: center;
        }
        .meeting-owner-cell {
          text-align: center;
          font-weight: 600;
          color: #1f2937;
        }
        .meeting-empty {
          margin-top: 12px;
          font-size: 12px;
          color: #94a3b8;
        }

        .swimlane-board {
          border: 1px solid var(--swim-border);
          border-radius: 12px;
          overflow: hidden;
          background: #ffffff;
          box-shadow: 0 6px 16px rgba(15, 23, 42, 0.08);
          width: 100%;
        }
        .swimlane-row {
          display: flex;
        }
        .swimlane-row-subtext .swimlane-index-col {
          align-items: flex-start;
          padding-top: 10px;
        }
        .swimlane-row-subtext .swimlane-header-with-subtext {
          display: grid;
          grid-template-rows: 1fr auto;
          justify-content: stretch;
          align-items: stretch;
        }
        .swimlane-row-subtext .swimlane-header-row {
          align-self: start;
        }
        .swimlane-row + .swimlane-row {
          border-top: 1px solid var(--swim-border);
        }
        .swimlane-index-col {
          width: 44px;
          flex-shrink: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          background: #f8fafc;
          border-right: 1px solid var(--swim-border);
        }
        .swimlane-header {
          position: relative;
          width: 150px;
          padding: 10px 10px;
          display: grid;
          grid-template-columns: 1fr auto;
          align-items: center;
          column-gap: 8px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.2px;
          border-right: 1px solid var(--swim-border);
          color: var(--swim-text);
          line-height: 1.1;
          font-size: 12px;
          word-break: break-word;
          background: #f8f9fa;
          z-index: 5;
        }
        .swimlane-header-stacked {
          grid-template-columns: 1fr auto;
          grid-template-areas:
            "label badges";
          grid-auto-rows: auto;
          row-gap: 0;
          align-items: start;
          justify-items: start;
        }
        .swimlane-header-stacked .swimlane-badges {
          grid-area: badges;
          justify-self: end;
          align-self: start;
        }
        .swimlane-header-stacked .swimlane-label {
          grid-area: label;
        }
        .swimlane-header-with-subtext {
          display: flex;
          flex-direction: column;
          align-items: stretch;
          gap: 4px;
        }
        .swimlane-header-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 1px;
          width: 100%;
          flex: 1 1 auto;
        }
        .swimlane-header-main {
          display: flex;
          min-height: 0;
          flex-direction: column;
          align-items: stretch;
        }
        .swimlane-header-main .swimlane-header-row {
          flex: 0 0 auto;
        }
        .oneh-missing-users {
          display: flex;
          flex: 0 0 auto;
          flex-direction: row;
          flex-wrap: wrap;
          align-content: flex-start;
          align-items: flex-start;
          justify-content: flex-start;
          gap: 4px 8px;
          width: 100%;
          padding: 9px 2px 4px;
          color: #dc2626;
          font-size: 12px;
          font-weight: 800;
          line-height: 1.15;
          letter-spacing: 0.3px;
        }
        .oneh-missing-users .oneh-missing-user {
          display: inline-block;
          color: #dc2626;
          text-align: center;
          white-space: nowrap;
        }
        .oneh-missing-users.oneh-missing-users-covered {
          padding-top: 0;
          color: #15803d;
        }
        .oneh-missing-users-covered .oneh-missing-user {
          color: #15803d;
        }
        .oneh-missing-users .oneh-missing-user:not(:last-child)::after {
          content: "•";
          display: inline-block;
          margin-left: 8px;
          color: inherit;
          font-size: 9px;
          vertical-align: middle;
        }
        .swimlane-index {
          width: 24px;
          height: 24px;
          border-radius: 999px;
          background: rgba(15, 23, 42, 0.08);
          color: #111827;
          font-weight: 700;
          font-size: 12px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
        }
        .swimlane-label {
          min-width: 0;
          white-space: pre-line;
        }
        .swimlane-label-wrap {
          position: relative;
          display: inline-flex;
          flex-direction: column;
          align-items: flex-start;
          gap: 4px;
          min-width: 0;
        }
        .swimlane-label-sub {
          display: block;
          width: 100%;
          grid-column: 1 / -1;
          font-size: 9px;
          font-weight: 400;
          color: #475569;
          white-space: pre-line;
          line-height: 1.25;
          margin-top: auto;
        }
        .swimlane-badges {
          position: relative;
          display: inline-flex;
          align-items: flex-start;
          gap: 6px;
        }
        .swimlane-badge-stack {
          display: inline-flex;
          flex-direction: column;
          align-items: flex-end;
          gap: 3px;
        }
        .swimlane-badge {
          min-width: 24px;
          height: 24px;
          padding: 0 6px;
          border-radius: 999px;
          font-size: 12px;
          font-weight: 700;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          background: #ffffff;
          border: 1px solid rgba(15, 23, 42, 0.12);
        }
        .swimlane-badge-sub {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          font-size: 10px;
          font-weight: 700;
          line-height: 1.1;
          color: #475569;
          white-space: nowrap;
          padding: 1px 6px;
          border-radius: 999px;
          border: 1px solid transparent;
        }
        .swimlane-badge-sub-time {
          color: #ffffff;
          background: #dc2626;
          border-color: #dc2626;
        }
        .swimlane-badge-sub-deadline {
          color: #ffffff;
          background: #dc2626;
          border-color: #dc2626;
        }
        .swimlane-info-btn {
          border: none;
          background: transparent;
          color: #64748b;
          font-weight: 800;
          font-size: 11px;
          line-height: 1;
          padding: 0 2px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          transition: color 0.15s ease;
        }
        .swimlane-info-btn:hover {
          color: #0f172a;
        }
        .swimlane-info-wrap {
          position: relative;
          display: inline-flex;
          z-index: 60;
        }
        .swimlane-info-btn-under-label {
          width: 18px;
          height: 18px;
          border: 1px solid rgba(15, 23, 42, 0.16);
          border-radius: 999px;
          background: rgba(255, 255, 255, 0.72);
          color: #475569;
          font-size: 10px;
          padding: 0;
        }
        .swimlane-title-row-toggle {
          width: 20px;
          height: 20px;
          border: 1px solid #cbd5e1;
          border-radius: 6px;
          background: #ffffff;
          color: #334155;
          font-size: 10px;
          font-weight: 800;
          line-height: 1;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          padding: 0;
          box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
        }
        .swimlane-title-row-toggle:hover {
          background: #f8fafc;
          border-color: #94a3b8;
          color: #0f172a;
        }
        .swimlane-title-row-toggle[aria-expanded="true"] {
          background: #2563eb;
          border-color: #2563eb;
          color: #ffffff;
        }
        .swimlane-info-popover {
          position: absolute;
          top: 50%;
          left: calc(100% + 8px);
          transform: translateY(-50%);
          background: #ffffff;
          border: 1px solid #cbd5e1;
          border-radius: 6px;
          padding: 8px 10px;
          font-size: 11px;
          font-weight: 700;
          color: #0f172a;
          white-space: normal;
          min-width: 180px;
          max-width: 260px;
          word-break: break-word;
          line-height: 1.35;
          z-index: 50;
          box-shadow: 0 4px 10px rgba(15, 23, 42, 0.12);
        }
        .swimlane-content-shell {
          position: relative;
          flex: 1;
          min-width: 0;
        }
        .swimlane-row-nav {
          position: absolute;
          top: 8px;
          right: 8px;
          display: flex;
          gap: 4px;
          z-index: 10;
        }
        .swimlane-row-nav button {
          background: #f8fafc;
          border: 1px solid #e2e8f0;
          color: #64748b;
          border-radius: 8px;
          width: 24px;
          height: 24px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          box-shadow: none;
          font-size: 12px;
          opacity: 0.75;
          transition: all 0.2s ease;
        }
        .swimlane-row-nav button:hover {
          color: #334155;
          background: #e2e8f0;
          opacity: 1;
        }
        .swimlane-content-scroll {
          overflow-x: auto;
          padding-bottom: 6px;
          scroll-behavior: smooth;
          scrollbar-gutter: stable;
          padding-right: 70px;
          scrollbar-width: none;
          -ms-overflow-style: none;
          position: relative;
          z-index: 1;
        }
        .swimlane-content-scroll::-webkit-scrollbar {
          display: none;
        }
        .swimlane-content {
          flex: 1;
          display: grid;
          grid-template-columns: repeat(3, var(--swim-col-width));
          grid-auto-flow: column;
          grid-auto-columns: var(--swim-col-width);
          min-width: calc(var(--swim-col-width) * 3);
          width: max-content;
        }
        .swimlane-delete {
          position: absolute;
          top: 8px;
          right: 8px;
          width: 22px;
          height: 22px;
          border-radius: 8px;
          background: #ffffff;
          color: #dc2626;
          border: 1px solid #e2e8f0;
          font-weight: 900;
          line-height: 1;
          cursor: pointer;
          box-shadow: none;
          transition: transform 0.1s ease, box-shadow 0.2s ease, background 0.2s ease;
        }
        .swimlane-delete:hover {
          transform: translateY(-1px);
          background: #fee2e2;
          border-color: #fecaca;
        }
        .swimlane-delete:active {
          transform: translateY(0);
          box-shadow: none;
        }
        .swimlane-cell {
          padding: 12px 44px 12px 14px;
          border-right: 1px solid #94a3b8;
          border-bottom: 1px solid var(--swim-border);
          min-height: 68px;
          display: flex;
          flex-direction: column;
          justify-content: flex-start;
          gap: 4px;
          color: var(--swim-text);
          background: linear-gradient(180deg, var(--cell-bg) 0%, var(--cell-tint) 100%);
          position: relative;
        }
        .swimlane-cell.swimlane-cell-user-break::before {
          content: "";
          position: absolute;
          top: 0;
          bottom: -1px;
          left: -1px;
          width: 4px;
          background: #111827;
          pointer-events: none;
          z-index: 1;
        }
        .swimlane-cell:nth-child(3n) {
          border-right: 0;
        }
        .swimlane-cell.empty {
          background: #ffffff;
        }
        .swimlane-cell.placeholder {
          color: var(--swim-muted);
          font-style: italic;
        }
        .swimlane-cell.done,
        .swimlane-cell.task-state-done {
          background: #d4ffe1;
          border-left-color: #ffffff;
        }
        .swimlane-cell.task-state-waiting {
          background: #ffedd5;
          border-left-color: #ffffff;
        }
        .swimlane-cell.task-state-waiting-client {
          background: #e2c15b;
          border-left-color: #ffffff;
        }
        .swimlane-cell.task-state-in-progress {
          background:rgb(255, 253, 195);
          border-left-color: #ffffff;
        }
        .swimlane-cell.task-state-todo {
          background:rgb(255, 222, 241);
          border-left-color: #ffffff;
        }
        .swimlane-cell.starts-selected-day {
          background: linear-gradient(180deg, #eff6ff 0%, #dbeafe 100%);
          border: 2px solid #2563eb;
          box-shadow: inset 0 0 0 1px rgba(37, 99, 235, 0.14);
        }
        .swimlane-cell.new-task-emphasis {
          padding-top: 36px;
        }
        .swimlane-cell.new-task-emphasis::after,
        .week-table-entry.new-task-emphasis::after {
          content: "E RE";
          position: absolute;
          top: 7px;
          right: 7px;
          padding: 2px 6px;
          border: 1px solid #93c5fd;
          border-radius: 999px;
          background: #dbeafe;
          color: #1e3a8a;
          font-size: 9px;
          font-weight: 800;
          line-height: 1.2;
          letter-spacing: 0.04em;
          white-space: nowrap;
          z-index: 2;
        }
        .swimlane-cell.created-day-before::after,
        .week-table-entry.created-day-before::after {
          content: "DJE";
          border-color: #93c5fd;
          background: #dbeafe;
          color: #1e3a8a;
        }
        .swimlane-cell.created-this-week::after,
        .week-table-entry.created-this-week::after {
          content: "KËTË JAVË";
          border-color: #2563eb;
          background: #3b82f6;
          color: #ffffff;
        }
        .swimlane-cell.created-last-week::after,
        .week-table-entry.created-last-week::after {
          content: "JAVA E KALUAR";
          border-color: #172554;
          background: #1e3a8a;
          color: #ffffff;
        }
        .swimlane-cell.eight-am-task {
          border: 2px solid #dc2626;
        }
        .swimlane-cell.done,
        .swimlane-cell.starts-selected-day.done,
        .swimlane-cell.task-state-done,
        .swimlane-cell.starts-selected-day.task-state-done {
          background: #d4ffe1;
        }
        .swimlane-cell.one-time-meeting {
          border-color: #dc2626;
        }
        .swimlane-title-row {
          display: flex;
          flex-direction: column;
          align-items: flex-start;
          gap: 6px;
          width: 100%;
          padding-right: 0;
          flex: 1 1 auto;
        }
        .swimlane-title-main {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          gap: 6px;
          width: 100%;
        }
        .swimlane-title-main.priority {
          flex-direction: column;
          align-items: flex-start;
          flex-wrap: nowrap;
        }
        .swimlane-title-main.fast-task-layout .swimlane-title {
          flex: 0 0 100%;
          width: 100%;
        }
        .swimlane-title-main.meeting-layout {
          flex-direction: column;
          align-items: flex-start;
          flex-wrap: nowrap;
        }
        .swimlane-title-main.meeting-layout .swimlane-title {
          flex: 0 0 auto;
          width: 100%;
        }
        .swimlane-title-main.priority .swimlane-assignees,
        .swimlane-title-main.priority .swimlane-title {
          width: 100%;
        }
        .swimlane-title {
          flex: 1 1 auto;
          min-width: 0;
          font-weight: 700;
          font-size: 14px;
          display: flex;
          flex-direction: column;
          align-items: flex-start;
          white-space: pre-wrap;
          line-height: 1.35;
        }
        .swimlane-title-text.collapsed {
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
          overflow: hidden;
          white-space: normal;
          word-break: break-word;
        }
        .swimlane-title-text.expanded {
          display: inline;
          white-space: pre-wrap;
        }
        .swimlane-title-toggle {
          position: absolute;
          top: 8px;
          right: 34px;
          width: 24px;
          height: 24px;
          border: 1px solid #cbd5e1;
          border-radius: 6px;
          background: #ffffff;
          color: #334155;
          font-size: 11px;
          font-weight: 800;
          line-height: 1;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          padding: 0;
          box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
          z-index: 3;
        }
        .swimlane-title-toggle:hover {
          background: #f8fafc;
          border-color: #94a3b8;
          color: #0f172a;
        }
        .swimlane-title-toggle[aria-expanded="true"] {
          background: #334155;
          border-color: #334155;
          color: #ffffff;
        }
        .swimlane-note-toggle {
          position: absolute;
          top: 8px;
          right: 62px;
          width: 24px;
          height: 24px;
          border: 1px solid #bfdbfe;
          border-radius: 6px;
          background: #eff6ff;
          color: #1d4ed8;
          font-size: 14px;
          font-weight: 800;
          line-height: 1;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          padding: 0;
          box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
          z-index: 3;
        }
        .swimlane-note-toggle:hover {
          background: #dbeafe;
          border-color: #93c5fd;
          color: #1e40af;
        }
        .swimlane-note-toggle[aria-expanded="true"] {
          background: #1d4ed8;
          border-color: #1d4ed8;
          color: #ffffff;
        }
        .swimlane-review-btn {
          flex: 0 0 auto;
          width: 24px;
          height: 24px;
          border: 1px solid #a5f3fc;
          border-radius: 999px;
          background: #ffffff;
          color: #0891b2;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          padding: 0;
          box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
        }
        .swimlane-review-btn svg {
          width: 16px;
          height: 16px;
        }
        .swimlane-review-btn:hover {
          background: #ecfeff;
          border-color: #67e8f9;
          transform: translateY(-1px);
        }
        .swimlane-review-btn.reviewed {
          background: #cffafe;
          border-color: #0891b2;
        }
        .swimlane-date {
          font-size: 12px;
          color: #334155;
          font-weight: 700;
          line-height: 1.2;
          align-self: flex-start;
        }
        .swimlane-date.today {
          display: inline-flex;
          align-items: center;
          width: fit-content;
          border: 1px solid #60a5fa;
          border-radius: 4px;
          background: #dbeafe;
          color: #1d4ed8;
          font-weight: 800;
          padding: 2px 6px;
          box-shadow: 0 1px 2px rgba(37, 99, 235, 0.18);
        }
        .swimlane-task-dates {
          display: flex;
          flex-wrap: nowrap;
          align-items: flex-end;
          justify-content: space-between;
          gap: 5px;
          align-self: flex-start;
          width: 100%;
          white-space: nowrap;
        }
        .swimlane-task-date {
          display: inline-flex;
          box-sizing: border-box;
          height: 22px;
          align-items: center;
          gap: 4px;
          width: fit-content;
          border: 1px solid #93c5fd;
          border-radius: 4px;
          background: #eff6ff;
          color: #1d4ed8;
          font-size: 12px;
          font-weight: 800;
          line-height: 1;
          padding: 2px 6px;
          box-shadow: 0 1px 2px rgba(37, 99, 235, 0.12);
        }
        .swimlane-task-date.due {
          border: 3px solid #b91c1c;
          padding: 0 4px;
        }
        .swimlane-task-date.due.today {
          height: 26px;
          border: 1px solid #991b1b;
          background: #dc2626;
          color: #ffffff;
          padding: 3px 9px;
          font-size: 14px;
          font-weight: 900;
          box-shadow: 0 1px 3px rgba(153, 27, 27, 0.3);
        }
        .swimlane-start-today {
          display: inline-flex;
          align-items: center;
          border: 1px solid #60a5fa;
          border-radius: 999px;
          background: #dbeafe;
          color: #1d4ed8;
          padding: 2px 6px;
          font-size: 10px;
          font-weight: 800;
          line-height: 1;
        }
        .swimlane-task-start {
          display: inline-flex;
          flex-direction: column;
          align-items: flex-start;
          gap: 3px;
        }
        .swimlane-subtitle {
          font-size: 12px;
          color: var(--swim-muted);
        }
        .swimlane-note {
          width: 100%;
          border: 1px solid #cbd5e1;
          border-radius: 6px;
          background: #ffffff;
          color: #334155;
          font-size: 12px;
          line-height: 1.35;
          padding: 6px 8px;
          white-space: pre-wrap;
          word-break: break-word;
        }
        .swimlane-meta {
          margin-top: auto;
          display: flex;
          flex-direction: column;
          gap: 4px;
          width: 100%;
        }
        .swimlane-delete {
          position: absolute;
          top: 6px;
          right: 6px;
          border: 1px solid #e2e8f0;
          background: #ffffff;
          color: #dc2626;
          width: 22px;
          height: 22px;
          border-radius: 6px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          font-size: 14px;
          line-height: 1;
          opacity: 0.9;
          transition: all 0.2s ease;
        }
        .swimlane-delete:hover {
          background: #fee2e2;
          border-color: #fecaca;
          opacity: 1;
        }
        .swimlane-assignees {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          align-items: center;
          justify-content: flex-start;
          margin-left: 0;
          z-index: 2;
        }
        .swimlane-avatar {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-width: 24px;
          height: 24px;
          padding: 0 6px;
          border-radius: 999px;
          background: #e2e8f0;
          color: #0f172a;
          font-weight: 700;
          font-size: 10px;
          letter-spacing: 0.02em;
          border: 1px solid #cbd5e1;
          line-height: 1;
          white-space: nowrap;
          word-break: keep-all;
          overflow-wrap: normal;
          position: relative;
          z-index: 1;
        }
        
        /* Week Table View - Shows when all days are selected */
        .week-table-view {
          display: block;
          width: 100%;
          margin-bottom: 20px;
        }
        .week-table {
          width: 100%;
          border-collapse: collapse;
          border: 3px solid #111827;
          font-size: 11px;
          direction: ltr;
        }
        .week-table th {
          border: 1px solid #111827;
          background: #dbeafe;
          padding: 8px 6px;
          text-align: left;
          font-weight: 700;
          vertical-align: bottom;
          position: sticky;
          top: 0;
          z-index: 2;
        }
        .week-table thead tr:first-child th {
          border-top-width: 2px;
        }
        .week-table thead tr:last-child th {
          border-bottom-width: 2px;
        }
        .week-table thead th:first-child {
          border-left-width: 2px;
        }
        .week-table thead th:last-child {
          border-right-width: 2px;
        }
        .week-table thead tr:nth-child(2) th {
          top: 30px;
          z-index: 1;
        }
        .week-table-date-header {
          background: #bfdbfe !important;
          font-size: 10px;
        }
        .week-table-subheader {
          background: #dbeafe !important;
          font-size: 9px;
          font-weight: 600;
        }
        .week-table td {
          border: 1px solid #dee2e6;
          padding: 6px 8px;
          vertical-align: bottom;
          font-size: 10px;
          text-align: left;
        }
        .week-table-number {
          text-align: center;
          font-weight: 700;
          background: #f8f9fa;
        }
        .week-table-label {
          font-weight: 700;
          background: #f8f9fa;
        }
        .week-table-row.delay .week-table-label {
          background: var(--delay-bg);
        }
        .week-table-row.absence .week-table-label {
          background: var(--absence-bg);
        }
        .week-table-row.leave .week-table-label {
          background: var(--leave-bg);
        }
        .week-table-row.externalHoliday .week-table-label {
          background: var(--externalHoliday-bg);
        }
        .week-table-row.blocked .week-table-label {
          background: var(--blocked-bg);
        }
        .week-table-row.waiting-client .week-table-label {
          background: #e2c15b;
          color: #4f3a00;
        }
        .week-table-row.oneh .week-table-label {
          background: var(--oneh-bg);
        }
        .week-table-row.personal .week-table-label {
          background: var(--personal-bg);
        }
        .week-table-row.external .week-table-label {
          background: var(--external-bg);
        }
        .week-table-row.internal .week-table-label {
          background: var(--internal-bg);
        }
        .week-table-row.bz .week-table-label {
          background: var(--bz-bg);
        }
        .week-table-row.r1 .week-table-label {
          background: var(--r1-bg);
        }
        .week-table-row.problem .week-table-label {
          background: var(--problem-bg);
        }
        .week-table-row.feedback .week-table-label {
          background: var(--feedback-bg);
        }
        .week-table-row.priority .week-table-label {
          background: var(--priority-bg);
        }
        .week-table-row.diamond .week-table-label {
          background: var(--diamond-bg);
          color: #0e7490;
        }
        .diamond-mark {
          display: inline-flex;
          align-items: center;
          vertical-align: middle;
          flex: 0 0 auto;
          color: var(--diamond-accent);
          font-size: 11px;
          line-height: 1;
          margin-right: 4px;
        }
        .diamond-mark > span {
          display: inline-flex;
        }
        .week-table-cell {
          min-height: 30px;
        }
        .week-table-entries {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .week-table-entry {
          font-size: 10px;
          line-height: 1.4;
          display: flex;
          align-items: center;
          gap: 6px;
          border: 1px solid #cbd5e1;
          border-radius: 4px;
          padding: 4px 6px;
          background: #ffffff;
          margin-bottom: 2px;
        }
        .week-table-entry.task-state-done {
          background: #d4ffe1;
        }
        .week-table-entry.task-state-in-progress {
          background: #fef3c7;
        }
        .week-table-entry.task-state-waiting {
          background: #ffedd5;
        }
        .week-table-entry.task-state-waiting-client {
          background: #e2c15b;
        }
        .week-table-entry.task-state-todo {
          background: #fbcfe8;
        }
        .week-table-entry.one-time-meeting {
          border-color: #dc2626;
        }
        .week-table-entry.manual-internal-meeting .week-table-meeting-title {
          font-weight: 900;
        }
        .week-table-entry.manual-internal-meeting {
          box-shadow: inset 0 0 0 2px #d6b44c;
        }
        .week-table-entry.one-time-meeting .week-table-avatar {
          border-color: #fca5a5;
        }
        .week-table-view.neutral-all-days .week-table-entry,
        .week-table-view.neutral-all-days .week-table-entry.task-state-done,
        .week-table-view.neutral-all-days .week-table-entry.task-state-in-progress,
        .week-table-view.neutral-all-days .week-table-entry.task-state-waiting,
        .week-table-view.neutral-all-days .week-table-entry.task-state-todo {
          background: #ffffff;
        }
        .week-table-view.neutral-all-days .week-table-entry.one-time-meeting {
          border-color: #dc2626;
        }
        .week-table-entry-main {
          flex: 1;
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          gap: 6px;
          min-width: 0;
        }
        .week-table-prjk-divider {
          border-top: 1px solid #64748b;
          margin: 1px 0;
        }
        .week-table-entry > span,
        .week-table-entry-main > span:first-child {
          flex: 1;
          min-width: 0;
          max-width: 100%;
          white-space: pre-wrap;
          overflow-wrap: anywhere;
          word-break: break-word;
          line-height: 1.35;
        }
        .week-table-line-number {
          display: inline;
          font-weight: 800;
          margin-right: 2px;
        }
        .week-table-merged-cell {
          background: #ffffff;
        }
        .week-table-feedback-summary {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 3px;
        }
        .feedback-print-summary-line {
          flex: 1 1 auto;
          min-width: 0;
        }
        .feedback-print-date {
          color: #64748b;
          font-weight: 700;
        }
        .week-table-feedback-summary .week-table-delete {
          display: none !important;
        }
        .week-table-delete {
          border: 1px solid #cbd5e1;
          background: #ffffff;
          color: #dc2626;
          width: 18px;
          height: 18px;
          border-radius: 4px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          font-size: 12px;
          line-height: 1;
          padding: 0;
        }
        .week-table-delete:hover {
          background: #fee2e2;
          border-color: #fecaca;
        }
        .fast-task-order-badge {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-width: 20px;
          height: 20px;
          padding: 0 6px;
          border-radius: 999px;
          background: #eff6ff;
          border: 1px solid #bfdbfe;
          color: #1d4ed8;
          font-weight: 700;
          font-size: 10px;
          line-height: 1;
          flex: 0 0 auto;
        }
        .deadline-indicator {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-width: 0;
          height: 20px;
          padding: 0 7px;
          border-radius: 999px;
          background: #fef2f2;
          border: 1px solid #fecaca;
          color: #b91c1c;
          font-weight: 700;
          font-size: 10px;
          line-height: 1;
          flex: 0 0 auto;
          white-space: nowrap;
        }
        .meeting-status-select {
          height: 22px;
          max-width: 92px;
          border: 1px solid #cbd5e1;
          border-radius: 6px;
          background: #ffffff;
          color: #334155;
          font-size: 11px;
          font-weight: 700;
          padding: 1px 4px;
        }
        .meeting-time-chip {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-width: 0;
          height: 22px;
          padding: 0 8px;
          border: 1px solid #93c5fd;
          border-radius: 999px;
          background: #eff6ff;
          color: #1d4ed8;
          font-size: 10px;
          font-weight: 800;
          line-height: 1;
          white-space: nowrap;
          flex: 0 0 auto;
        }
        .manual-meeting-badge {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-height: 20px;
          padding: 0 7px;
          border: 1px solid #1e3a8a;
          border-radius: 999px;
          background: #1d4ed8;
          color: #ffffff;
          font-size: 9px;
          font-weight: 900;
          line-height: 1;
          letter-spacing: 0.06em;
          white-space: nowrap;
        }
        .calendar-meeting-badge {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-height: 20px;
          padding: 0 7px;
          border: 1px solid #0f766e;
          border-radius: 999px;
          background: #0d9488;
          color: #ffffff;
          font-size: 9px;
          font-weight: 900;
          line-height: 1;
          letter-spacing: 0.06em;
          white-space: nowrap;
        }
        .meeting-relation-badge {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-height: 20px;
          padding: 0 7px;
          border: 1px solid #475569;
          border-radius: 999px;
          background: #f8fafc;
          color: #0f172a;
          font-size: 9px;
          font-weight: 900;
          line-height: 1;
          white-space: nowrap;
          flex: 0 0 auto;
          margin-right: 5px;
        }
        .meeting-origin-row {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          flex-wrap: nowrap;
          white-space: nowrap;
        }
        .week-table-meeting-main {
          display: flex;
          flex: 1;
          min-width: 0;
          flex-direction: column;
          align-items: flex-start;
          gap: 3px;
        }
        .week-table-meeting-title {
          min-width: 0;
          white-space: pre-wrap;
          line-height: 1.35;
        }
        .time-indicator {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-width: 0;
          height: 20px;
          padding: 0 7px;
          border-radius: 999px;
          background: #dc2626;
          border: 1px solid #b91c1c;
          color: #ffffff;
          font-weight: 700;
          font-size: 10px;
          line-height: 1;
          flex: 0 0 auto;
          white-space: nowrap;
        }
        .period-indicator {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-width: 0;
          height: 20px;
          padding: 0 7px;
          border-radius: 999px;
          background: #e0f2fe;
          border: 1px solid #bae6fd;
          color: #0369a1;
          font-weight: 700;
          font-size: 10px;
          line-height: 1;
          flex: 0 0 auto;
          white-space: nowrap;
        }
        .wfc-indicator {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-width: 0;
          height: 20px;
          padding: 0 7px;
          border-radius: 999px;
          background: #ffedd5;
          border: 1px solid #fb923c;
          color: #c2410c;
          font-weight: 800;
          font-size: 10px;
          line-height: 1;
          flex: 0 0 auto;
          white-space: nowrap;
        }
        .oneh-marker-select {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-width: 50px;
          max-width: 54px;
          height: 22px;
          padding: 0 2px;
          border-radius: 999px;
          background: #eff6ff;
          border: 1px solid #93c5fd;
          color: #dc2626;
          font-weight: 900;
          font-size: 16px;
          text-shadow: 0 0 0 currentColor;
          line-height: 1;
          flex: 0 0 auto;
          cursor: pointer;
        }
        .oneh-marker-select:disabled {
          cursor: wait;
          opacity: 0.65;
        }
        .oneh-marker-select option {
          color: #dc2626;
          font-weight: 900;
          font-size: 16px;
        }
        .oneh-slot-indicator {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-width: 0;
          height: 20px;
          padding: 0 7px;
          border-radius: 999px;
          background: #fef3c7;
          border: 1px solid #fbbf24;
          color: #92400e;
          font-weight: 800;
          font-size: 10px;
          line-height: 1;
          flex: 0 0 auto;
          white-space: nowrap;
        }
        .fast-task-order-controls {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          flex: 0 0 auto;
        }
        .fast-task-order-btn {
          border: 1px solid #cbd5e1;
          background: #ffffff;
          color: #334155;
          width: 20px;
          height: 20px;
          border-radius: 4px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          font-size: 11px;
          line-height: 1;
          transition: background 0.15s ease, border-color 0.15s ease;
        }
        .fast-task-order-btn:hover:not(:disabled) {
          background: #eff6ff;
          border-color: #93c5fd;
        }
        .fast-task-order-btn:disabled {
          opacity: 0.45;
          cursor: not-allowed;
        }
        .week-table-avatars {
          display: flex;
          flex-wrap: wrap;
          gap: 5px;
          margin-top: 2px;
        }
        .week-table-avatar {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 24px;
          height: 24px;
          border-radius: 999px;
          background: #e2e8f0;
          color: #0f172a;
          font-weight: 600;
          font-size: 11px;
          line-height: 1;
          border: 1px solid #cbd5e1;
        }
        @media screen {
          .week-table-entry:has(> .week-table-avatars > .week-table-avatar:nth-child(6)) {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            align-items: start;
          }
          .week-table-entry:has(> .week-table-avatars > .week-table-avatar:nth-child(6)) > span,
          .week-table-entry:has(> .week-table-avatars > .week-table-avatar:nth-child(6)) > .week-table-entry-main {
            grid-column: 1 / -1;
            width: 100%;
          }
          .week-table-entry:has(> .week-table-avatars > .week-table-avatar:nth-child(6)) > .week-table-avatars {
            grid-column: 1;
            min-width: 0;
            max-width: 100%;
          }
          .week-table-entry:has(> .week-table-avatars > .week-table-avatar:nth-child(6)) > .week-table-delete {
            grid-column: 2;
            grid-row: 2;
          }
        }
        .week-table-empty {
          color: #adb5bd;
          font-style: italic;
        }
        .week-table-entry.starts-selected-day:not(.task-state-done),
        .week-table-view.neutral-all-days .week-table-entry.starts-selected-day:not(.task-state-done),
        .week-table-view.neutral-all-days .week-table-entry.starts-selected-day.task-state-in-progress,
        .week-table-view.neutral-all-days .week-table-entry.starts-selected-day.task-state-waiting,
        .week-table-view.neutral-all-days .week-table-entry.starts-selected-day.task-state-waiting-client,
        .week-table-view.neutral-all-days .week-table-entry.starts-selected-day.task-state-todo {
          background: linear-gradient(90deg, rgba(239, 246, 255, 0.98), rgba(255, 255, 255, 0.98)) !important;
          border: 2px solid #2563eb;
        }
        @media screen {
          .week-table-entry.new-task-emphasis,
          .week-table-view.neutral-all-days .week-table-entry.new-task-emphasis {
            position: relative;
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto auto;
            align-items: center;
            column-gap: 5px;
            padding: 4px 6px;
          }
          .week-table-entry.new-task-emphasis > .week-table-entry-main,
          .week-table-entry.new-task-emphasis > span:first-child {
            grid-column: 1;
            min-width: 0;
          }
          .week-table-entry.new-task-emphasis > .week-table-avatars {
            grid-column: 2;
            margin-top: 0;
          }
          .week-table-entry.new-task-emphasis::after {
            position: static;
            grid-column: 3;
            grid-row: 1;
            justify-self: end;
            transform: none;
            padding: 2px 5px;
            font-size: 8px;
          }
        }
        .week-table-entry.eight-am-task {
          border: 2px solid #dc2626;
        }
        .week-table-entry.deadline-important:not(.task-state-done),
        .week-table-view.neutral-all-days .week-table-entry.deadline-important:not(.task-state-done),
        .week-table-view.neutral-all-days .week-table-entry.deadline-important.task-state-in-progress,
        .week-table-view.neutral-all-days .week-table-entry.deadline-important.task-state-waiting,
        .week-table-view.neutral-all-days .week-table-entry.deadline-important.task-state-waiting-client,
        .week-table-view.neutral-all-days .week-table-entry.deadline-important.task-state-todo {
          background: linear-gradient(90deg, rgba(254, 242, 242, 0.98), rgba(255, 255, 255, 0.98)) !important;
          border: 2px solid #dc2626;
        }
        .week-table-entry.task-state-done,
        .week-table-entry.starts-selected-day.task-state-done,
        .week-table-entry.deadline-important.task-state-done,
        .week-table-view.neutral-all-days .week-table-entry.task-state-done,
        .week-table-view.neutral-all-days .week-table-entry.starts-selected-day.task-state-done,
        .week-table-view.neutral-all-days .week-table-entry.deadline-important.task-state-done {
          background: #d4ffe1 !important;
        }
        .week-table-entry.repeat-task-muted,
        .week-table-view.neutral-all-days .week-table-entry.repeat-task-muted,
        .week-table-view.neutral-all-days .week-table-entry.repeat-task-muted.task-state-done,
        .week-table-view.neutral-all-days .week-table-entry.repeat-task-muted.task-state-in-progress,
        .week-table-view.neutral-all-days .week-table-entry.repeat-task-muted.task-state-waiting,
        .week-table-view.neutral-all-days .week-table-entry.repeat-task-muted.task-state-waiting-client,
        .week-table-view.neutral-all-days .week-table-entry.repeat-task-muted.task-state-todo {
          color: #9ca3af;
        }
        .week-table-entry.repeat-task-muted.deadline-important,
        .week-table-entry.repeat-task-muted.starts-selected-day {
          color: #9ca3af;
        }
        .week-table-entry.repeat-task-muted .week-table-avatar,
        .week-table-entry.repeat-task-muted .fast-task-order-badge,
        .week-table-entry.repeat-task-muted .deadline-indicator,
        .week-table-entry.repeat-task-muted .period-indicator,
        .week-table-entry.repeat-task-muted .oneh-slot-indicator {
          color: #9ca3af;
        }
        .week-table-entry.repeat-task-muted .time-indicator {
          background: #f3f4f6;
          border-color: #d1d5db;
          color: #9ca3af;
        }
        .common-task-status-indicator {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          box-sizing: border-box;
          width: fit-content;
          flex-shrink: 0;
          vertical-align: middle;
          margin: 1px 3px 1px 0;
          padding: 1px 3px;
          border: 1px solid currentColor;
          border-radius: 5px;
          font-size: 9px;
          font-weight: 700;
          line-height: 1.2;
          white-space: nowrap;
          background: #fff !important;
          color: #475569 !important;
        }
        .common-task-status-indicator.status-todo {
          background: #fbcfe8 !important;
          color: #831843 !important;
        }
        .common-task-status-indicator.status-in-progress {
          background: #fef08a !important;
          color: #854d0e !important;
        }
        .common-task-status-indicator.status-done {
          background: #bbf7d0 !important;
          color: #166534 !important;
        }
        .common-task-status-indicator.status-waiting { color: #9a3412 !important; }
        .common-task-status-indicator.status-waiting-client { color: #854d0e !important; }
        .week-table-entry.calendar-internal-muted .week-table-meeting-title,
        .swimlane-cell.calendar-internal-muted .swimlane-title {
          color: #64748b;
          font-weight: 400;
        }
        .form-error {
          color: #b91c1c;
          font-size: 12px;
          font-weight: 600;
        }
        @media print {
          .week-table-view {
            display: block !important;
            page-break-inside: auto;
            page-break-after: auto;
          }
          .week-table-view .print-header {
            page-break-after: avoid;
            margin-bottom: 6px;
          }
          .week-table {
            page-break-inside: auto;
            table-layout: fixed;
            width: 100%;
            border: 3px solid #111827 !important;
            font-size: 10px;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
            margin-top: 0;
          }
          .week-table thead {
            display: table-header-group;
          }
          .week-table tr {
            break-inside: avoid-page;
            page-break-inside: avoid;
          }
          .week-table th,
          .week-table td {
            border: 1px solid #111827 !important;
            position: static !important;
            top: auto !important;
            z-index: auto !important;
            padding: 2px 3px;
            white-space: normal;
            overflow-wrap: anywhere;
            word-break: break-word;
          }
          .week-table thead tr:nth-child(2) th {
            top: auto !important;
          }
          .week-table-number {
            width: 30px !important;
          }
          .week-table-label {
            width: 72px !important;
          }
          .week-table-label-subtext {
            display: block;
            margin-top: 2px;
            font-size: 5.2px;
            font-weight: 400;
            line-height: 1.05;
            white-space: pre;
            overflow-wrap: normal !important;
            word-break: normal !important;
          }
          .week-table-cell,
          .week-table-entry > span:not(.week-table-avatar) {
            white-space: normal;
          }
          .week-table-entry > span:not(.week-table-avatar) {
            flex: 1 1 auto;
            display: block;
            margin: 0;
            padding: 2px 0 0;
            line-height: 1.15;
            align-self: center;
          }
          .week-table-row.feedback .feedback-print-clamp {
            display: -webkit-box !important;
            -webkit-box-orient: vertical;
            -webkit-line-clamp: 2;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: normal !important;
            line-height: 1.15;
          }
          .week-table-feedback-summary {
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 1px 3px;
          }
          .week-table-merged-cell {
            padding: 1px 3px !important;
          }
          .feedback-print-summary-line {
            display: block;
            white-space: nowrap !important;
            overflow: hidden;
            text-overflow: ellipsis;
            line-height: 1;
          }
          .feedback-print-date {
            color: #475569 !important;
          }
          .week-table-entry {
            border: 1px solid #94a3b8 !important;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
            page-break-inside: avoid;
            margin-bottom: 0px;
            font-size: 10px;
            line-height: 1;
            gap: 2px;
            padding: 2px 2px 1px;
            display: flex;
            align-items: center;
          }
          .week-table-entry.one-time-meeting {
            border-color: #dc2626 !important;
          }
          .week-table-entries {
            gap: 1px;
          }
          .week-table-avatars {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 2px;
            margin-top: 0;
            line-height: 1;
          }
          .week-table-avatar {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            flex: 0 0 auto !important;
            min-width: 0;
            min-height: 16px;
            height: 16px;
            padding: 0 4px;
            border-radius: 4px;
            font-size: 10px;
            line-height: 16px;
            font-weight: 600;
            white-space: nowrap;
            border-width: 1px;
            align-self: center;
            vertical-align: middle;
          }
        }
          align-items: center;
          justify-content: center;
          width: 24px;
          height: 24px;
          border-radius: 999px;
          border: 1px solid var(--swim-border);
          background: #ffffff;
          color: #475569;
          font-size: 10px;
          font-weight: 700;
          box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
        }
        .swimlane-header.delay { background: var(--delay-bg); color: #c2410c; }
        .swimlane-header.absence { background: var(--absence-bg); color: #b91c1c; }
        .swimlane-header.leave { background: var(--leave-bg); color: #15803d; }
        .swimlane-header.externalHoliday { background: var(--externalHoliday-bg); color: #be185d; }
        .swimlane-header.blocked { background: var(--blocked-bg); color: #9f1239; }
        .swimlane-header.waiting-client { background: #e2c15b; color: #4f3a00; }
        .swimlane-header.oneh { background: var(--oneh-bg); color: #0369a1; }
        .swimlane-header.personal { background: var(--personal-bg); color: #7e22ce; }
        .swimlane-header.external { background: var(--external-bg); color: #0369a1; }
        .swimlane-header.internal { background: var(--internal-bg); color: #334155; }
        .swimlane-header.bz { background: var(--bz-bg); color: #0f766e; }
        .swimlane-header.r1 { background: var(--r1-bg); color: #15803d; }
        .swimlane-header.problem { background: var(--problem-bg); color: #0e7490; }
        .swimlane-header.feedback { background: var(--feedback-bg); color: #475569; }
        .swimlane-header.priority { background: var(--priority-bg); color: #b45309; }
        .swimlane-header.diamond { background: var(--diamond-bg); color: #0e7490; }
        .swimlane-badge.delay { border-color: var(--delay-accent); color: #c2410c; }
        .swimlane-badge.absence { border-color: var(--absence-accent); color: #b91c1c; }
        .swimlane-badge.leave { border-color: var(--leave-accent); color: #15803d; }
        .swimlane-badge.externalHoliday { border-color: var(--externalHoliday-accent); color: #be185d; }
        .swimlane-badge.blocked { border-color: var(--blocked-accent); color: #9f1239; }
        .swimlane-badge.waiting-client { border-color: #b8860b; color: #4f3a00; }
        .swimlane-badge.oneh { border-color: var(--oneh-accent); color: #0369a1; }
        .swimlane-badge.personal { border-color: var(--personal-accent); color: #7e22ce; }
        .swimlane-badge.external { border-color: var(--external-accent); color: #0369a1; }
        .swimlane-badge.internal { border-color: var(--internal-accent); color: #334155; }
        .swimlane-badge.bz { border-color: var(--bz-accent); color: #0f766e; }
        .swimlane-badge.r1 { border-color: var(--r1-accent); color: #15803d; }
        .swimlane-badge.problem { border-color: var(--problem-accent); color: #0e7490; }
        .swimlane-badge.feedback { border-color: var(--feedback-accent); color: #475569; }
        .swimlane-badge.priority { border-color: var(--priority-accent); color: #b45309; }
        .swimlane-badge.diamond { border-color: var(--diamond-accent); color: #0e7490; }
        .swimlane-accent.delay { border-left: 4px solid var(--delay-accent); }
        .swimlane-accent.absence { border-left: 4px solid var(--absence-accent); }
        .swimlane-accent.leave { border-left: 4px solid var(--leave-accent); }
        .swimlane-accent.externalHoliday { border-left: 4px solid var(--externalHoliday-accent); }
        .swimlane-accent.blocked { border-left: 0; }
        .swimlane-accent.waiting-client { border-left: 0; }
        .swimlane-accent.oneh { border-left: 0; }
        .swimlane-accent.personal { border-left: 0; }
        .swimlane-accent.external { border-left: 4px solid var(--external-accent); }
        .swimlane-accent.internal { border-left: 4px solid var(--internal-accent); }
        .swimlane-cell.manual-internal-meeting .swimlane-title {
          font-weight: 900;
        }
        .swimlane-cell.manual-internal-meeting {
          box-shadow: inset 0 0 0 2px #d6b44c;
        }
        .swimlane-accent.bz { border-left: 4px solid var(--bz-accent); }
        .swimlane-accent.r1 { border-left: 0; }
        .swimlane-accent.problem { border-left: 4px solid var(--problem-accent); }
        .swimlane-accent.feedback { border-left: 4px solid var(--feedback-accent); }
        .swimlane-accent.priority { border-left: 4px solid var(--priority-accent); }
        .swimlane-accent.diamond { border-left: 4px solid var(--diamond-accent); }
        .swimlane-cell.one-time-meeting {
          border-color: #dc2626;
        }
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) {
          background: #dc2626;
          border-color: #b91c1c;
          box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.12);
          color: #ffffff;
        }
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .swimlane-title,
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .swimlane-date,
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .swimlane-subtitle,
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .swimlane-note,
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .swimlane-note * {
          color: #ffffff;
        }
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .swimlane-note {
          background: rgba(127, 29, 29, 0.35);
          border-color: rgba(255, 255, 255, 0.32);
        }
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .swimlane-task-date {
          background: rgba(255, 255, 255, 0.12);
          border-color: rgba(255, 255, 255, 0.45);
          color: #ffffff;
          box-shadow: none;
        }
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .swimlane-task-date.due.today {
          background: #dc2626;
          border-color: #991b1b;
          color: #ffffff;
          box-shadow: 0 1px 3px rgba(127, 29, 29, 0.45);
        }
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .swimlane-avatar,
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .fast-task-order-badge,
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .deadline-indicator,
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .time-indicator,
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .period-indicator,
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .oneh-slot-indicator {
          background: rgba(255, 255, 255, 0.12);
          border-color: rgba(255, 255, 255, 0.38);
          color: #ffffff;
        }
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .swimlane-note-toggle,
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .swimlane-title-toggle,
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .swimlane-delete,
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .fast-task-order-btn {
          background: rgba(255, 255, 255, 0.12);
          border-color: rgba(255, 255, 255, 0.38);
          color: #ffffff;
        }
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .swimlane-note-toggle:hover,
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .swimlane-title-toggle:hover,
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .swimlane-delete:hover,
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .fast-task-order-btn:hover {
          background: rgba(255, 255, 255, 0.2);
          border-color: rgba(255, 255, 255, 0.5);
          color: #ffffff;
        }
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .swimlane-title-toggle[aria-expanded="true"] {
          background: #ffffff;
          border-color: #ffffff;
          color: #b91c1c;
        }
        .swimlane-cell.deadline-important:not(.done):not(.task-state-done) .swimlane-note-toggle[aria-expanded="true"] {
          background: #ffffff;
          border-color: #ffffff;
          color: #b91c1c;
        }
        .task-title-wfc {
          color: #dc2626 !important;
          font-weight: 800;
        }
        .swimlane-cell.deadline-important:not(.personal-ga-task) .task-title-wfc,
        .week-table-entry.deadline-important:not(.personal-ga-task) .task-title-wfc {
          background: #ffffff;
          border-radius: 2px;
          padding: 0 2px;
        }
        .swimlane-cell.personal-ga-task,
        .week-table-entry.personal-ga-task,
        .week-table-view.neutral-all-days .week-table-entry.personal-ga-task {
          background: #d8b4fe !important;
          color: #111827 !important;
          -webkit-print-color-adjust: exact;
          print-color-adjust: exact;
        }
        .week-table-entry.personal-ga-task.repeat-task-muted,
        .week-table-view.neutral-all-days .week-table-entry.personal-ga-task.repeat-task-muted {
          color: #9ca3af !important;
        }

        /* Modern Toolbar */
        .common-toolbar { 
          background: white; 
          padding: 8px 24px; 
          border-bottom: 1px solid #e5e7eb; 
          display: flex; 
          flex-wrap: wrap; 
          gap: 8px; 
          align-items: center; 
          flex-shrink: 0;
          box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
        }
        .toolbar-group {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .task-focus-filter-group {
          align-items: flex-start;
        }
        .new-task-filter-stack {
          display: inline-flex;
          flex-direction: column;
          align-items: stretch;
          gap: 4px;
        }
        .new-task-category-row {
          justify-content: center;
          padding: 3px;
          margin-right: 0;
          background: #eff6ff;
          border: 1px solid #dbeafe;
        }
        .new-task-category-row .chip {
          padding: 3px 7px;
          font-size: 10px;
        }
        .user-filter-control {
          position: relative;
          display: inline-flex;
          align-items: center;
          gap: 6px;
          color: #475569;
          font-size: 11px;
          font-weight: 700;
          white-space: nowrap;
        }
        .user-filter-button {
          width: 180px;
          height: 32px;
          border: 1px solid #cbd5e1;
          border-radius: 8px;
          background: #fff;
          color: #0f172a;
          display: inline-flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          padding: 4px 8px;
          font-size: 12px;
          font-weight: 600;
          cursor: pointer;
        }
        .user-filter-button.active,
        .user-filter-button:hover {
          border-color: #3b82f6;
          box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.12);
        }
        .user-filter-button span:first-child {
          min-width: 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .user-filter-chevron {
          color: #64748b;
          font-size: 10px;
          flex: 0 0 auto;
        }
        .user-filter-menu {
          position: absolute;
          top: calc(100% + 6px);
          right: 0;
          z-index: 200;
          width: 220px;
          max-height: 260px;
          overflow-y: auto;
          border: 1px solid #cbd5e1;
          border-radius: 8px;
          background: #fff;
          box-shadow: 0 12px 28px rgba(15, 23, 42, 0.18);
          padding: 4px;
        }
        .user-filter-option {
          width: 100%;
          border: 0;
          border-radius: 6px;
          background: transparent;
          color: #0f172a;
          cursor: pointer;
          display: block;
          padding: 7px 8px;
          text-align: left;
          font-size: 12px;
          font-weight: 600;
        }
        .user-filter-option:hover {
          background: #eff6ff;
          color: #1d4ed8;
        }
        .user-filter-option.active {
          background: #2563eb;
          color: #fff;
        }
        .marker-filter-button {
          width: 150px;
          color: #0f2a5f;
          font-weight: 800;
        }
        .marker-filter-menu {
          left: auto;
          right: 0;
          width: 190px;
          max-height: 390px;
          overflow-y: auto;
        }
        .marker-filter-option {
          display: flex;
          align-items: center;
          gap: 8px;
          border-radius: 6px;
          padding: 7px 8px;
          color: #0f172a;
          font-size: 12px;
          font-weight: 700;
          cursor: pointer;
        }
        .marker-filter-option:hover {
          background: #eff6ff;
          color: #1d4ed8;
        }
        .marker-filter-option input {
          width: 14px;
          height: 14px;
          margin: 0;
          accent-color: #2563eb;
        }
        .marker-filter-footer {
          position: sticky;
          bottom: -4px;
          display: flex;
          justify-content: flex-end;
          border-top: 1px solid #e2e8f0;
          background: #fff;
          padding: 6px 4px 2px;
        }
        .marker-filter-footer button {
          border: 0;
          border-radius: 6px;
          background: #2563eb;
          color: #fff;
          padding: 5px 10px;
          font-size: 11px;
          font-weight: 800;
          cursor: pointer;
        }
        .toolbar-group .chip-row {
          margin-right: 0;
        }
        
        /* Elegant Chips */
        .chip-row { 
          display: inline-flex; 
          gap: 4px; 
          padding: 4px; 
          background: #f1f5f9; 
          border-radius: 8px; 
          margin-right: 8px; 
        }
        .chip { 
          border: none; 
          padding: 4px 10px; 
          font-size: 11px; 
          border-radius: 6px; 
          cursor: pointer; 
          background: transparent; 
          color: #64748b; 
          font-weight: 600; 
          display: inline-flex; 
          align-items: center; 
          gap: 4px;
          transition: all 0.2s ease;
        }
        .chip:hover { 
          background: #e2e8f0; 
          color: #475569;
        }
        .chip.active { 
          background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
          color: white; 
          box-shadow: 0 2px 8px rgba(59, 130, 246, 0.3);
        }
        .day-chip.active {
          background: #2563eb;
          box-shadow: none;
        }
        .chip.color-chip {
          border: 1px solid transparent;
        }
        .chip.color-chip.active {
          background: #0f172a;
          border-color: #0f172a;
          color: #ffffff;
        }
        .color-swatch {
          width: 12px;
          height: 12px;
          border-radius: 999px;
          border: 1px solid rgba(15, 23, 42, 0.22);
          flex: 0 0 auto;
        }
        .chip.color-chip.active .color-swatch {
          border-color: rgba(255, 255, 255, 0.85);
        }
        
        /* Week Navigation Buttons - Different style from day chips */
        .week-nav-buttons {
          display: inline-flex;
          gap: 6px;
          margin-right: 12px;
          align-items: center;
        }
        .week-nav-btn {
          border: 2px solid #cbd5e1;
          padding: 6px 14px;
          font-size: 12px;
          font-weight: 700;
          border-radius: 8px;
          cursor: pointer;
          background: white;
          color: #475569;
          transition: all 0.2s ease;
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .week-nav-btn:hover {
          background: #f1f5f9;
          border-color: #94a3b8;
          color: #334155;
        }
        .week-nav-btn.active {
          background: #3b82f6;
          border-color: #3b82f6;
          color: white;
          box-shadow: 0 2px 6px rgba(59, 130, 246, 0.4);
        }
        
        /* Input & Switch */
        .input { 
          border: 2px solid #e2e8f0; 
          border-radius: 8px; 
          padding: 10px 14px; 
          font-size: 14px; 
          width: 100%;
          transition: all 0.2s ease;
        }
        .input:focus {
          outline: none;
          border-color: #64748b;
          box-shadow: 0 0 0 3px rgba(100, 116, 139, 0.1);
        }
        .switch { 
          display: inline-flex; 
          align-items: center; 
          gap: 8px; 
          font-size: 13px; 
          color: #475569; 
          cursor: pointer;
          font-weight: 500;
        }
        .switch input { 
          width: 18px; 
          height: 18px; 
          accent-color: #64748b; 
        }
        
        /* Modern Badges */
        .badge { 
          padding: 4px 12px; 
          border-radius: 6px; 
          font-size: 11px; 
          font-weight: 700; 
          border: none;
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .bg-gray { background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%); color: #475569; }
        .bg-blue { background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%); color: #1e40af; }
        .bg-red-light { background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%); color: #991b1b; }
        .bg-purple { background: linear-gradient(135deg, #e0f2fe 0%, #bae6fd 100%); color: #0369a1; }
        .bg-orange { background: linear-gradient(135deg, #fed7aa 0%, #fdba74 100%); color: #9a3412; }
        .bg-green { background: linear-gradient(135deg, #bbf7d0 0%, #86efac 100%); color: #166534; }
        
        /* Elegant Grid */
        .common-grid { 
          display: grid; 
          grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); 
          gap: 12px; 
          align-content: start; 
        }
        
        /* Beautiful Cards */
        .common-card { 
          background: white; 
          border: none;
          border-radius: 12px; 
          overflow: hidden; 
          display: flex; 
          flex-direction: column; 
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
          transition: all 0.3s ease;
        }
        .common-card:hover {
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        }
        .common-card-header { 
          display: flex; 
          align-items: center; 
          justify-content: space-between; 
          gap: 8px; 
          padding: 10px 14px; 
          background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
          border-bottom: 1px solid #e2e8f0; 
          cursor: pointer; 
          flex-shrink: 0;
          border-radius: 12px 12px 0 0;
          transition: all 0.2s ease;
        }
        .common-card-header:hover { 
          background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%);
        }
        .common-card-title { 
          font-size: 11px; 
          font-weight: 800; 
          color: #1e293b; 
          text-transform: uppercase; 
          letter-spacing: 0.3px; 
          display: inline-flex; 
          align-items: center; 
          gap: 6px; 
        }
        .common-card-count { 
          padding: 2px 8px; 
          border-radius: 12px; 
          font-size: 10px; 
          font-weight: 800; 
          background: white;
          color: #475569;
          box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
        }
        .common-card-body { 
          padding: 12px 14px; 
          overflow: visible;
          flex: 1;
          min-height: 0;
        }
        .common-card[data-common-type="ga"] .common-card-body {
          max-height: 320px;
          overflow-y: auto;
        }
        
        /* Elegant List Items */
        .common-list { 
          list-style: none; 
          margin: 0; 
          padding: 0; 
          display: grid; 
          gap: 6px; 
        }
        .common-item { 
          border: 1px solid #e2e8f0; 
          border-radius: 8px; 
          padding: 8px 10px; 
          background: linear-gradient(to bottom, #ffffff 0%, #f8fafc 100%);
          transition: all 0.2s ease;
        }
        .common-item:hover {
          border-color: #cbd5e1;
          box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
        }
        .common-item-title { 
          font-weight: 700; 
          color: #0f172a; 
          font-size: 12px;
          margin-bottom: 4px;
          line-height: 1.3;
        }
        .common-item-meta { 
          margin-top: 4px; 
          font-size: 10px; 
          color: #64748b; 
          display: flex; 
          flex-wrap: wrap; 
          gap: 6px; 
          align-items: center; 
        }
        .common-item-meta b { 
          color: #1e293b; 
          font-weight: 700;
        }
        .common-empty { 
          color: #94a3b8; 
          font-size: 11px; 
          padding: 16px 12px; 
          border: 1px dashed #cbd5e1; 
          border-radius: 8px; 
          background: #f8fafc; 
          text-align: center;
          font-style: italic;
        }
        
        /* Priority Section */
        .common-priority { 
          grid-column: 1 / -1; 
        }
        .common-person-grid { 
          display: grid; 
          grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); 
          gap: 12px; 
        }
        .common-person { 
          background: white; 
          border: 1px solid #e2e8f0; 
          border-radius: 12px; 
          overflow: hidden;
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
          transition: all 0.3s ease;
          display: flex;
          flex-direction: column;
          max-height: 100%;
        }
        .common-person:hover {
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        }
        .common-person-header { 
          padding: 10px 14px; 
          border-bottom: 1px solid #e2e8f0; 
          background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
          display: flex; 
          align-items: center; 
          justify-content: space-between; 
          gap: 8px;
          flex-shrink: 0;
        }
        .common-person-name { 
          font-weight: 800; 
          color: #0f172a; 
          font-size: 12px; 
        }
        .common-person-body { 
          padding: 12px 14px;
          overflow-y: auto;
          flex: 1;
          min-height: 0;
        }
        .common-person-body ul { 
          margin: 0; 
          padding-left: 16px; 
          color: #1e293b; 
          font-size: 11px; 
        }
        .common-person-body li { 
          margin-bottom: 6px;
          line-height: 1.4;
        }
        .common-person-body li:last-child { 
          margin-bottom: 0; 
        }
        .common-person-body small { 
          color: #64748b; 
          font-weight: 600; 
          font-size: 10px; 
        }
        
        /* Modern Modal */
        .modal { 
          position: fixed; 
          inset: 0; 
          display: flex; 
          align-items: center; 
          justify-content: center; 
          z-index: 9999; 
        }
        .modal.hidden { 
          display: none; 
        }
        .modal-backdrop { 
          position: absolute; 
          inset: 0; 
          background: rgba(15, 23, 42, 0.6);
          backdrop-filter: blur(4px);
        }
        .modal-card { 
          position: relative; 
          width: min(720px, calc(100vw - 32px)); 
          background: white; 
          border-radius: 20px; 
          border: none;
          box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25); 
          overflow: hidden; 
        }
        .modal-header { 
          display: flex; 
          justify-content: space-between; 
          align-items: center; 
          padding: 24px 28px; 
          border-bottom: 2px solid #e2e8f0; 
          background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
        }
        .modal-header h4 { 
          font-size: 18px; 
          color: #0f172a; 
          margin: 0;
          font-weight: 700;
        }
        .modal-header .btn-outline {
          background: #ffffff;
          color: #0f172a;
          border-color: #cbd5e1;
          box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
        }
        .modal-header .btn-outline:hover:not(:disabled) {
          background: #f8fafc;
          border-color: #94a3b8;
        }
        .modal-header .btn-outline:disabled {
          color: #94a3b8;
          background: #f8fafc;
          border-color: #e2e8f0;
          opacity: 1;
        }
        .modal-body { 
          padding: 28px; 
        }
        .modal-footer { 
          display: flex; 
          justify-content: flex-end; 
          gap: 16px; 
          padding: 24px 28px; 
          border-top: 2px solid #e2e8f0; 
          background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
        }
        .modal-footer .btn-primary {
            background: #2563eb;
            color: white;
            border: none;
            padding: 10px 20px;
            font-size: 14px;
            font-weight: 700;
            border-radius: 8px;
            box-shadow: 0 3px 10px rgba(37, 99, 235, 0.25);
            min-width: 108px;
            transition: all 0.2s ease;
          }
        .modal-footer .btn-primary:hover:not(:disabled) {
          background: #1d4ed8;
          box-shadow: 0 6px 16px rgba(37, 99, 235, 0.4);
          transform: translateY(-1px);
        }
        .modal-footer .btn-primary:active:not(:disabled) {
          transform: translateY(0);
          box-shadow: 0 2px 8px rgba(37, 99, 235, 0.3);
        }
        .modal-footer .btn-outline {
            background: white;
            color: #475569;
            border: 1.5px solid #cbd5e1;
            padding: 10px 20px;
            font-size: 14px;
            font-weight: 700;
            border-radius: 8px;
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
            min-width: 108px;
            transition: all 0.2s ease;
          }
        .modal-footer .btn-outline:hover:not(:disabled) {
          background: #f8fafc;
          border-color: #94a3b8;
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
          transform: translateY(-1px);
        }
        .modal-footer .btn-outline:active:not(:disabled) {
          transform: translateY(0);
          box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        }
        .btn-primary:disabled,
        .btn-outline:disabled {
          opacity: 0.5;
          cursor: not-allowed;
          transform: none;
          box-shadow: none;
        }
        .form-grid { 
            display: grid; 
            grid-template-columns: 1fr 1fr; 
            gap: 16px; 
          }
        .form-row { 
          display: flex; 
          flex-direction: column; 
          gap: 8px; 
        }
        .form-row label { 
          font-size: 13px; 
          color: #475569; 
          font-weight: 700; 
        }
        .form-row textarea { 
          min-height: 100px; 
          resize: vertical; 
        }
          .span-2 { 
            grid-column: 1 / -1; 
          }
          .leave-inline {
            display: flex;
            align-items: flex-end;
            gap: 16px;
          }
          .leave-inline .leave-checkbox {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            margin: 0;
            min-width: 180px;
            font-weight: 600;
          }
          .leave-inline .leave-times {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 12px;
            width: 100%;
          }
          .leave-inline .mini-row {
            display: flex;
            flex-direction: column;
            gap: 6px;
          }
          .leave-inline .mini-row label {
            font-size: 13px;
            color: #475569;
            font-weight: 700;
          }
      `}</style>

      <div className="common-sticky" ref={stickyRef}>
        <header className="top-header">
          <div className="page-title">
            <h1>Common View</h1>
            <p>Daily/weekly view for key statuses and team priorities.</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              className="btn-outline no-print"
              type="button"
              onClick={handleExportExcel}
              disabled={exportingExcel}
            >
              {exportingExcel ? "Exporting..." : "Export Excel"}
            </button>
            <button className="btn-primary no-print" type="button" onClick={() => void handlePrint()} disabled={printingToday}>
              {printingToday ? "Preparing print..." : "Print"}
            </button>
            <button
              className="btn-outline no-print"
              type="button"
              onClick={handlePrintTomorrow}
              disabled={printingTomorrow}
              title="Print tasks and meetings for the next working day without changing Common View"
            >
              {printingTomorrow ? "Preparing tomorrow..." : "Print Tomorrow"}
            </button>
            {allDaysSelected ? (
              <span
                className="no-print print-scale-hint"
                title={
                  printOrientationHint === "landscape"
                    ? "For best fit, keep browser print scale at 100%"
                    : "Portrait mode prints as multi-page for readability"
                }
              >
                {printOrientationHint === "landscape"
                  ? ""
                  : ""}
              </span>
            ) : null}
            <button
              className={`btn-outline no-print ${meetingPanelOpen ? "active" : ""}`}
              type="button"
              aria-pressed={meetingPanelOpen}
              onClick={() => setMeetingPanelOpen((prev) => !prev)}
            >
              Meeting
            </button>
            <button
              className={`btn-outline no-print ${externalMeetingsOpen ? "active" : ""}`}
              type="button"
              aria-pressed={externalMeetingsOpen}
              onClick={() => setExternalMeetingsOpen((prev) => !prev)}
            >
              External Meetings
            </button>
            <button
              className={`btn-outline no-print ${internalMeetingsOpen ? "active" : ""}`}
              type="button"
              aria-pressed={internalMeetingsOpen}
              onClick={() => setInternalMeetingsOpen((prev) => !prev)}
            >
              Internal Meetings
            </button>
            <button className="btn-outline no-print" type="button" onClick={() => openModal()}>
              + Add
            </button>
          </div>
        </header>

        <div className="common-toolbar no-print">
          <div className="toolbar-group">
            <div className="chip-row">
            {weekISOs.map((iso) => {
              const d = fromISODate(iso)
              const label = `${alWeekdayShort(d)} ${formatDateHuman(iso)}`
              const isActive = selectedDates.has(iso)
              return (
                <button
                  key={iso}
                  className={`chip day-chip ${isActive ? "active" : ""}`}
                  type="button"
                  onClick={() => toggleDay(iso)}
                >
                  {label}
                </button>
              )
            })}
            </div>
            <div className="week-nav-buttons">
              <button
                className={`week-nav-btn ${selectedDates.size === 1 && selectedDates.has(todayIso) && toISODate(weekStart) === thisWeekMondayIso ? "active" : ""}`}
                type="button"
                onClick={selectToday}
              >
                Today
              </button>
              <button
                className={`week-nav-btn ${toISODate(weekStart) === thisWeekMondayIso && allDaysSelected ? "active" : ""}`}
                type="button"
                onClick={() => {
                  selectWeek(thisWeekMonday)
                }}
              >
                This Week
              </button>
              <button
                className={`week-nav-btn ${toISODate(weekStart) === toISODate(addDays(thisWeekMonday, 7)) && allDaysSelected ? "active" : ""}`}
                type="button"
                onClick={() => {
                  const nextWeekMonday = addDays(thisWeekMonday, 7)
                  selectWeek(nextWeekMonday)
                }}
              >
                Next Week
              </button>
            </div>
            <label className="switch" title="When OFF: select only one. When ON: select multiple.">
              <input type="checkbox" checked={multiMode} onChange={(e) => setMultiMode(e.target.checked)} />
              Multi-select (Days)
            </label>
            <label className="switch" title="Show the selected date's saved 1H slots in Common View and print.">
              <input
                type="checkbox"
                checked={freezeOneHSlots}
                onChange={(e) => setFreezeOneHSlots(e.target.checked)}
              />
              Freeze 1H slots
            </label>
            <div className="user-filter-control" ref={commonUserFilterRef}>
              <span>User</span>
              <button
                className={`user-filter-button ${commonUserMenuOpen ? "active" : ""}`}
                type="button"
                aria-haspopup="listbox"
                aria-expanded={commonUserMenuOpen}
                onClick={() => setCommonUserMenuOpen((open) => !open)}
              >
                <span>{selectedCommonUserLabel}</span>
                <span className="user-filter-chevron" aria-hidden="true">v</span>
              </button>
              {commonUserMenuOpen ? (
                <div className="user-filter-menu" role="listbox">
                  <button
                    type="button"
                    role="option"
                    aria-selected={selectedCommonUserId === "__all__"}
                    className={`user-filter-option ${selectedCommonUserId === "__all__" ? "active" : ""}`}
                    onClick={() => {
                      setSelectedCommonUserId("__all__")
                      setCommonUserMenuOpen(false)
                    }}
                  >
                    All users
                  </button>
                  {commonUserFilterOptions.map((option) => (
                    <button
                      key={option.id}
                      type="button"
                      role="option"
                      aria-selected={selectedCommonUserId === option.id}
                      className={`user-filter-option ${selectedCommonUserId === option.id ? "active" : ""}`}
                      onClick={() => {
                        setSelectedCommonUserId(option.id)
                        setCommonUserMenuOpen(false)
                      }}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
          <div className="toolbar-group">
            <div className="chip-row">
            <button
              className={`chip ${typeFilters.size === 0 ? "active" : ""}`}
              type="button"
              onClick={() => setTypeFilter("all")}
            >
              All
            </button>
            <button
              className={`chip ${typeFilters.has("blocked") ? "active" : ""}`}
              type="button"
              onClick={() => setTypeFilter("blocked")}
            >
              BLL
            </button>
            <button
              className={`chip ${typeFilters.has("oneH") ? "active" : ""}`}
              type="button"
              onClick={() => setTypeFilter("oneH")}
            >
              1H
            </button>
            <button
              className={`chip ${typeFilters.has("r1") ? "active" : ""}`}
              type="button"
              onClick={() => setTypeFilter("r1")}
            >
              R1
            </button>
            <button
              className={`chip ${typeFilters.has("personal") ? "active" : ""}`}
              type="button"
              onClick={() => setTypeFilter("personal")}
            >
              P:
            </button>
            <button
              className={`chip ${typeFilters.has("external") ? "active" : ""}`}
              type="button"
              onClick={() => setTypeFilter("external")}
            >
              TAK EXT
            </button>
            <button
              className={`chip ${typeFilters.has("internal") ? "active" : ""}`}
              type="button"
              onClick={() => setTypeFilter("internal")}
            >
              TAK INT
            </button>
            <button
              className={`chip ${typeFilters.has("bz") ? "active" : ""}`}
              type="button"
              onClick={() => setTypeFilter("bz")}
            >
              BZ
            </button>
            <button
              className={`chip ${typeFilters.has("priority") ? "active" : ""}`}
              type="button"
              onClick={() => setTypeFilter("priority")}
            >
              PRJK
            </button>
            <button
              className={`chip ${typeFilters.has("problem") ? "active" : ""}`}
              type="button"
              onClick={() => setTypeFilter("problem")}
            >
              PRBL
            </button>
            <button
              className={`chip ${typeFilters.has("feedback") ? "active" : ""}`}
              type="button"
              onClick={() => setTypeFilter("feedback")}
            >
              ANK/KRK/PRZ
            </button>
            <button
              className={`chip ${typeFilters.has("late") ? "active" : ""}`}
              type="button"
              onClick={() => setTypeFilter("late")}
            >
              VONS
            </button>
            <button
              className={`chip ${typeFilters.has("absent") ? "active" : ""}`}
              type="button"
              onClick={() => setTypeFilter("absent")}
            >
              MUNG
            </button>
            <button
              className={`chip ${typeFilters.has("leave") ? "active" : ""}`}
              type="button"
              onClick={() => setTypeFilter("leave")}
            >
              PV/FEST
            </button>
            </div>
            <label className="switch" title="When OFF: select only one. When ON: select multiple.">
              <input type="checkbox" checked={typeMultiMode} onChange={(e) => setTypeMultiMode(e.target.checked)} />
              Multi-select (Types)
            </label>
          </div>
          <div className="toolbar-group task-focus-filter-group">
            <div className="new-task-filter-stack">
              <div className="chip-row" aria-label="Task filters">
                {([
                  ["new", "Detyrat e reja"],
                  ["eightAm", "08:00"],
                  ["deadline", "Me deadline"],
                ] as const).map(([value, label]) => (
                  <button
                    key={value}
                    className={`chip ${taskFocusFilter === value ? "active" : ""}`}
                    type="button"
                    aria-pressed={taskFocusFilter === value}
                    onClick={() => setTaskFocusFilter((current) => current === value ? "all" : value)}
                    title={taskFocusFilter === value ? "Kliko përsëri për ta hequr filtrin" : undefined}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="chip-row new-task-category-row" aria-label="Llojet e detyrave të reja">
                {COMMON_TASK_NEW_CATEGORY_OPTIONS.map((option) => (
                  <button
                    key={option.value}
                    className={`chip ${taskFocusFilter === "new" && newTaskCategoryFilters.has(option.value) ? "active" : ""}`}
                    type="button"
                    aria-pressed={taskFocusFilter === "new" && newTaskCategoryFilters.has(option.value)}
                    onClick={() => toggleNewTaskCategoryFilter(option.value)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <div className="toolbar-group">
            <div className="chip-row" aria-label="Filter by color">
              <button
                className={`chip color-chip ${colorFilter === "all" ? "active" : ""}`}
                type="button"
                onClick={() => setColorFilter("all")}
              >
                All colors
              </button>
              {COMMON_COLOR_FILTER_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  className={`chip color-chip ${colorFilter === option.value ? "active" : ""}`}
                  type="button"
                  onClick={() => setColorFilter(option.value)}
                  title={`Show ${option.label.toLowerCase()} rows only`}
                >
                  <span
                    className="color-swatch"
                    style={{ backgroundColor: option.swatch }}
                    aria-hidden="true"
                  />
                  {option.label}
                </button>
              ))}
            </div>
          </div>
          <div className="toolbar-group">
            <div className="user-filter-control marker-filter-control" ref={oneHMarkerFilterRef}>
              <span>Symbol</span>
              <button
                className={`user-filter-button marker-filter-button ${oneHMarkerMenuOpen ? "active" : ""}`}
                type="button"
                aria-haspopup="listbox"
                aria-expanded={oneHMarkerMenuOpen}
                onClick={() => setOneHMarkerMenuOpen((open) => !open)}
              >
                <span
                  className={ONE_H_MARKER_OPTIONS.some((option) => option.label === oneHMarkerFilterLabel) ? "text-red-600" : undefined}
                >
                  {oneHMarkerFilterLabel}
                </span>
                <span className="user-filter-chevron" aria-hidden="true">v</span>
              </button>
              {oneHMarkerMenuOpen ? (
                <div className="user-filter-menu marker-filter-menu" role="listbox" aria-multiselectable="true">
                  <button
                    type="button"
                    role="option"
                    aria-selected={oneHMarkerFilters.size === 0}
                    className={`user-filter-option ${oneHMarkerFilters.size === 0 ? "active" : ""}`}
                    onClick={() => setOneHMarkerFilters(new Set())}
                  >
                    All
                  </button>
                  <label className="marker-filter-option">
                    <input
                      type="checkbox"
                      checked={ONE_H_MARKER_VALUES.every((marker) => oneHMarkerFilters.has(marker))}
                      onChange={toggleAllOneHMarkerFilters}
                    />
                    <span>All with symbols</span>
                  </label>
                  <label className="marker-filter-option">
                    <input
                      type="checkbox"
                      checked={oneHMarkerFilters.has("none")}
                      onChange={() => toggleOneHMarkerFilter("none")}
                    />
                    <span>No symbol</span>
                  </label>
                  {ONE_H_MARKER_OPTIONS.map((option) => (
                    <label key={option.value} className="marker-filter-option">
                      <input
                        type="checkbox"
                        checked={oneHMarkerFilters.has(option.value)}
                        onChange={() => toggleOneHMarkerFilter(option.value)}
                      />
                      <span className="font-black text-red-600">{option.label}</span>
                    </label>
                  ))}
                  <div className="marker-filter-footer">
                    <button type="button" onClick={() => setOneHMarkerMenuOpen(false)}>Done</button>
                  </div>
                </div>
              ) : null}
            </div>
          </div>
          <div style={{ position: "relative", display: "inline-flex", alignItems: "center", width: "auto" }}>
            <input
              className="input"
              type="text"
              placeholder="DD/MM/YYYY"
              value={toDDMMYYYY(calendarDateIso)}
              onChange={(e) => {
                const value = e.target.value
                const isoDate = fromDDMMYYYY(value)
                if (isoDate) {
                  setWeek(isoDate)
                }
              }}
              pattern="\d{2}/\d{2}/\d{4}"
              style={{ width: "140px", paddingRight: "35px" }}
            />
            <input
              type="date"
              value={calendarDateIso}
              onChange={(e) => setWeek(e.target.value)}
              style={{
                position: "absolute",
                right: "8px",
                opacity: 0,
                width: "24px",
                height: "24px",
                cursor: "pointer",
                zIndex: 1
              }}
              title="Open calendar"
            />
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{
                position: "absolute",
                right: "10px",
                pointerEvents: "none",
                color: "#666"
              }}
            >
              <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
              <line x1="16" y1="2" x2="16" y2="6"></line>
              <line x1="8" y1="2" x2="8" y2="6"></line>
              <line x1="3" y1="10" x2="21" y2="10"></line>
            </svg>
          </div>
          <div className="toolbar-group">
            <div className="chip-row">
              <button
                className={`chip ${kaGentFilterActive ? "active" : ""}`}
                type="button"
                aria-pressed={kaGentFilterActive}
                onClick={() => setKaGentFilterActive((active) => !active)}
                title="Show personal, symbol and WFC tasks for both KA and GENT"
              >
                KA/GENT
              </button>
              <button
                className={`chip ${taskFocusFilter === "startToday" ? "active" : ""}`}
                type="button"
                aria-pressed={taskFocusFilter === "startToday"}
                onClick={() => setTaskFocusFilter((current) => current === "startToday" ? "all" : "startToday")}
                title="Detyrat e krijuara sot me start date dhe due date sot"
              >
                START SOT
              </button>
            </div>
          </div>
          <button className="btn-outline" type="button" onClick={selectAll}>
            All days
          </button>
          <button className="btn-outline" type="button" onClick={selectToday}>
            Today
          </button>
        </div>
      </div>

      {meetingPanelOpen ? (
        <section className="meeting-panel">
          <div className="meeting-panel-header">
            <div>
              <div className="meeting-title">Meetings</div>
              <div className="meeting-subtitle">Select a meeting to view the checklist table.</div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              {canEditMeetingTemplates ? (
                <button
                  className="btn-surface"
                  type="button"
                  onClick={() => {
                    setMeetingTemplateError("")
                    setShowMeetingTemplateForm((prev) => !prev)
                  }}
                >
                  {showMeetingTemplateForm ? "Hide form" : "New checklist"}
                </button>
              ) : null}
              {canEditMeetingTemplates ? (
                <button
                  className="btn-surface danger"
                  type="button"
                  onClick={() => void deleteMeetingTemplate()}
                  disabled={!activeMeeting || deletingMeetingTemplate}
                >
                  {deletingMeetingTemplate ? "Deleting..." : "Delete checklist"}
                </button>
              ) : null}
              <button
                className="btn-surface"
                type="button"
                onClick={handleExportMeetingExcel}
                disabled={!activeMeeting || exportingMeetingExcel}
              >
                {exportingMeetingExcel ? "Exporting..." : "Export Excel"}
              </button>
              <button
                className="btn-surface"
                type="button"
                onClick={handleExportAllMeetingTemplatesExcel}
                disabled={!meetingTemplates.length || exportingAllMeetingTemplatesExcel}
              >
                {exportingAllMeetingTemplatesExcel ? "Exporting..." : "Export All Excel"}
              </button>
              <button className="btn-surface" type="button" onClick={() => setMeetingPanelOpen(false)}>
                Close
              </button>
            </div>
          </div>
          <div className="meeting-tabs">
            <div className="meeting-dropdown">
              <label htmlFor="meeting-board-ga">BORD/GA</label>
              <select
                id="meeting-board-ga"
                value={boardMeetingIds.includes(activeMeetingId) ? activeMeetingId : ""}
                onChange={(e) => {
                  setMeetingAutoSelectEnabled(true)
                  setActiveMeetingId(e.target.value)
                }}
              >
                <option value="" disabled>
                  Select meeting
                </option>
                {meetingTemplates.filter((t) => boardMeetingIds.includes(t.id)).map((template) => (
                  <option key={template.id} value={template.id}>
                    {template.title}
                  </option>
                ))}
              </select>
            </div>
            <div className="meeting-dropdown">
              <label htmlFor="meeting-staff-ga">STAFF/GA</label>
              <select
                id="meeting-staff-ga"
                value={staffMeetingIds.includes(activeMeetingId) ? activeMeetingId : ""}
                onChange={(e) => {
                  setMeetingAutoSelectEnabled(true)
                  setActiveMeetingId(e.target.value)
                }}
              >
                <option value="" disabled>
                  Select meeting
                </option>
                {meetingTemplates.filter((t) => staffMeetingIds.includes(t.id)).map((template) => (
                  <option key={template.id} value={template.id}>
                    {template.title}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {canEditMeetingTemplates ? (
            <>
              {showMeetingTemplateForm ? (
                <div className="meeting-create-card">
                  <div className="meeting-create-header">
                    <div>
                      <div className="meeting-create-title">Create checklist</div>
                      <div className="meeting-create-subtitle">Create a new Board/Staff meeting template.</div>
                    </div>
                    <div style={{ display: "flex", gap: "8px" }}>
                      <button
                        className="btn-outline"
                        type="button"
                        onClick={() => {
                          setShowMeetingTemplateForm(false)
                          setMeetingTemplateError("")
                          setMeetingTemplateTopicLabel("")
                          setMeetingTemplateTopicHeader("M1 PIKAT")
                        }}
                      >
                        Cancel
                      </button>
                      <button
                        className="btn-primary"
                        type="button"
                        onClick={() => void createMeetingTemplate()}
                        disabled={!canCreateMeetingTemplate || creatingMeetingTemplate}
                      >
                        {creatingMeetingTemplate ? "Creating..." : "Create checklist"}
                      </button>
                    </div>
                  </div>
                  <div className="meeting-create-grid">
                    <div className="meeting-create-field">
                      <label htmlFor="meeting-create-group">Group</label>
                      <select
                        id="meeting-create-group"
                        value={meetingTemplateGroup}
                        onChange={(e) => setMeetingTemplateGroup(e.target.value as "board" | "staff")}
                      >
                        <option value="board">BORD/GA</option>
                        <option value="staff">STAFF/GA</option>
                      </select>
                    </div>
                    <div className="meeting-create-field">
                      <label htmlFor="meeting-create-title">Title</label>
                      <input
                        id="meeting-create-title"
                        className="input"
                        type="text"
                        placeholder="Checklist title"
                        value={meetingTemplateTitle}
                        onChange={(e) => setMeetingTemplateTitle(e.target.value)}
                      />
                    </div>
                    <div className="meeting-create-field">
                      <label htmlFor="meeting-create-topic-header">M1 PIKAT</label>
                      <input
                        id="meeting-create-topic-header"
                        className="input"
                        type="text"
                        placeholder="M1 PIKAT"
                        value={meetingTemplateTopicHeader}
                        onChange={(e) => setMeetingTemplateTopicHeader(e.target.value)}
                      />
                    </div>
                    <div className="meeting-create-field">
                      <label htmlFor="meeting-create-owner">Default owner</label>
                      <input
                        id="meeting-create-owner"
                        className="input"
                        type="text"
                        placeholder="Optional"
                        value={meetingTemplateDefaultOwner}
                        onChange={(e) => setMeetingTemplateDefaultOwner(e.target.value)}
                      />
                    </div>
                    <div className="meeting-create-field">
                      <label htmlFor="meeting-create-time">Default time</label>
                      <input
                        id="meeting-create-time"
                        className="input"
                        type="text"
                        placeholder="Optional"
                        value={meetingTemplateDefaultTime}
                        onChange={(e) => setMeetingTemplateDefaultTime(e.target.value)}
                      />
                    </div>
                    <div className="meeting-create-field">
                      <label htmlFor="meeting-create-topic-label">Topic column</label>
                      <input
                        id="meeting-create-topic-label"
                        className="input"
                        type="text"
                        placeholder={
                          activeMeeting?.columns.find((col) => col.key === "topic")?.label || "M1 PIKAT"
                        }
                        value={meetingTemplateTopicLabel}
                        onChange={(e) => setMeetingTemplateTopicLabel(e.target.value)}
                      />
                    </div>
                    <div className="meeting-create-field meeting-create-note">
                      <label htmlFor="meeting-create-note">Note</label>
                      <input
                        id="meeting-create-note"
                        className="input"
                        type="text"
                        placeholder="Optional"
                        value={meetingTemplateNote}
                        onChange={(e) => setMeetingTemplateNote(e.target.value)}
                      />
                    </div>
                  </div>
                  {meetingTemplateError ? (
                    <div className="meeting-create-error">{meetingTemplateError}</div>
                  ) : null}
                </div>
              ) : null}
            </>
          ) : null}
          {activeMeeting ? (
            <div className="meeting-table-card">
              <div className="meeting-table-header">
                {editingMeetingTitle ? (
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", flex: 1 }}>
                    <input
                      type="text"
                      value={meetingTitleDraft}
                      onChange={(e) => setMeetingTitleDraft(e.target.value)}
                      className="input"
                      style={{ flex: 1, fontSize: "inherit", fontWeight: "inherit" }}
                      autoFocus
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          void saveMeetingTitle()
                        } else if (e.key === "Escape") {
                          cancelEditMeetingTitle()
                        }
                      }}
                    />
                    <button
                      className="btn-primary"
                      type="button"
                      onClick={() => void saveMeetingTitle()}
                      disabled={savingMeetingTitle || !meetingTitleDraft.trim()}
                    >
                      {savingMeetingTitle ? "Saving..." : "Save"}
                    </button>
                    <button className="btn-outline" type="button" onClick={cancelEditMeetingTitle}>
                      Cancel
                    </button>
                  </div>
                ) : (
                  <div
                    className="meeting-table-title"
                    style={canEditMeetingTemplates ? { cursor: "pointer", userSelect: "none" } : undefined}
                    onClick={canEditMeetingTemplates ? startEditMeetingTitle : undefined}
                    title={canEditMeetingTemplates ? "Click to edit" : undefined}
                  >
                    {activeMeeting.title}
                  </div>
                )}
                {activeMeeting.defaultOwner || activeMeeting.defaultTime ? (
                  <div className="meeting-table-meta">
                    {activeMeeting.defaultOwner ? `WHO: ${activeMeeting.defaultOwner}` : null}
                    {activeMeeting.defaultOwner && activeMeeting.defaultTime ? " | " : null}
                    {activeMeeting.defaultTime ? `WHEN: ${activeMeeting.defaultTime}` : null}
                  </div>
                ) : null}
              </div>
              {activeMeeting.note ? <div className="meeting-note">{activeMeeting.note}</div> : null}
              <div className="meeting-table-wrap">
                <table className="meeting-table">
                  <thead>
                    <tr>
                      {activeMeeting.columns.map((col) => (
                        <th
                          key={col.key}
                          className={col.key === "topic" ? "meeting-topic-header" : undefined}
                          style={col.width ? { width: col.width } : undefined}
                        >
                          {col.key === "topic" && canEditMeetingTemplates ? (
                            editingMeetingTopicHeader ? (
                              <input
                                type="text"
                                className="meeting-topic-header-input"
                                value={meetingTopicHeaderDraft}
                                onChange={(e) => setMeetingTopicHeaderDraft(e.target.value)}
                                autoFocus
                                disabled={savingMeetingTopicHeader}
                                onBlur={() => {
                                  if (skipMeetingTopicHeaderBlurRef.current) {
                                    skipMeetingTopicHeaderBlurRef.current = false
                                    return
                                  }
                                  if (meetingTopicHeaderDraft.trim()) void saveMeetingTopicHeader()
                                }}
                                onKeyDown={(e) => {
                                  if (e.key === "Enter") {
                                    e.preventDefault()
                                    void saveMeetingTopicHeader()
                                  } else if (e.key === "Escape") {
                                    cancelEditMeetingTopicHeader()
                                  }
                                }}
                              />
                            ) : (
                              <button
                                type="button"
                                className="meeting-topic-header-edit"
                                onClick={startEditMeetingTopicHeader}
                                title="Click to edit"
                              >
                                {col.label}
                              </button>
                            )
                          ) : (
                            col.label
                          )}
                        </th>
                      ))}
                      {canEditMeetingTemplates ? <th style={{ width: "160px" }}>Actions</th> : null}
                    </tr>
                  </thead>
                  <tbody>
                    {activeMeeting.rows
                      .slice()
                      .sort((a, b) => a.nr - b.nr || a.id.localeCompare(b.id))
                      .map((row, rowIndex) => (
                      <tr key={row.id}>
                        {activeMeeting.columns.map((col) => {
                          let value = ""
                          if (col.key === "nr") value = String(row.nr)
                          if (col.key === "day") value = row.day || ""
                          if (col.key === "topic") value = row.topic
                          if (col.key === "owner") {
                            value = row.owner || (rowIndex === 0 ? activeMeeting.defaultOwner || "" : "")
                          }
                          if (col.key === "time") {
                            value = row.time || (rowIndex === 0 ? activeMeeting.defaultTime || "" : "")
                          }
                          const isEditing = canEditMeetingTemplates && editingRowId === row.id

                          if (col.key === "owner" && mergeOwnerColumn) {
                            if (rowIndex !== 0) return null
                            return (
                              <td
                                key={`${activeMeeting.id}-${row.nr}-${col.key}`}
                                rowSpan={activeMeeting.rows.length}
                                className="meeting-owner-cell"
                                style={col.width ? { width: col.width } : undefined}
                              >
                                {value}
                              </td>
                            )
                          }

                          if (col.key === "check") {
                            const checkStatus = row.checkStatus ?? (row.isChecked ? "check" : "none")
                            return (
                              <td key={`${activeMeeting.id}-${row.nr}-${col.key}`} className="meeting-check-cell">
                                <select
                                  className={`meeting-check-select status-${checkStatus}`}
                                  aria-label={`Set status for ${row.topic}`}
                                  value={checkStatus}
                                  onChange={(e) =>
                                    void changeMeetingCheckStatus(
                                      activeMeeting.id,
                                      row.id,
                                      e.target.value as MeetingCheckStatus
                                    )
                                  }
                                >
                                  <option value="none"></option>
                                  <option value="check">{"\u2713"}</option>
                                  <option value="x">X</option>
                                  <option value="o">O</option>
                                </select>
                              </td>
                            )
                          }

                          if (col.key === "nr") {
                            return (
                              <td key={`${activeMeeting.id}-${row.nr}-${col.key}`} style={col.width ? { width: col.width } : undefined}>
                                {isEditing ? (
                                  <input
                                    className="input"
                                    type="text"
                                    inputMode="numeric"
                                    pattern="[0-9]*"
                                    value={editDraft.nr}
                                    onChange={(e) =>
                                      setEditDraft((prev) => ({
                                        ...prev,
                                        nr: e.target.value.replace(/\D/g, ""),
                                      }))
                                    }
                                    style={{ minWidth: "52px", textAlign: "center" }}
                                  />
                                ) : (
                                  value
                                )}
                              </td>
                            )
                          }

                          if (col.key === "topic") {
                            return (
                              <td
                                key={`${activeMeeting.id}-${row.nr}-${col.key}`}
                                className="meeting-topic-cell"
                                style={col.width ? { width: col.width } : undefined}
                              >
                                {isEditing ? (
                                  <input
                                    className="input"
                                    type="text"
                                    value={editDraft.topic}
                                    onChange={(e) => setEditDraft((prev) => ({ ...prev, topic: e.target.value }))}
                                    style={{ textTransform: "uppercase" }}
                                  />
                                ) : (
                                  <span className="meeting-topic-text">{value}</span>
                                )}
                              </td>
                            )
                          }

                          if (col.key === "day") {
                            return (
                              <td key={`${activeMeeting.id}-${row.nr}-${col.key}`} style={col.width ? { width: col.width } : undefined}>
                                {isEditing ? (
                                  <input
                                    className="input"
                                    type="text"
                                    value={editDraft.day}
                                    onChange={(e) => setEditDraft((prev) => ({ ...prev, day: e.target.value }))}
                                  />
                                ) : (
                                  value
                                )}
                              </td>
                            )
                          }

                          if (col.key === "owner") {
                            return (
                              <td key={`${activeMeeting.id}-${row.nr}-${col.key}`} style={col.width ? { width: col.width } : undefined}>
                                {isEditing ? (
                                  <input
                                    className="input"
                                    type="text"
                                    value={editDraft.owner}
                                    onChange={(e) => setEditDraft((prev) => ({ ...prev, owner: e.target.value }))}
                                  />
                                ) : (
                                  value
                                )}
                              </td>
                            )
                          }

                          if (col.key === "time") {
                            return (
                              <td key={`${activeMeeting.id}-${row.nr}-${col.key}`} style={col.width ? { width: col.width } : undefined}>
                                {isEditing ? (
                                  <input
                                    className="input"
                                    type="text"
                                    value={editDraft.time}
                                    onChange={(e) => setEditDraft((prev) => ({ ...prev, time: e.target.value }))}
                                  />
                                ) : (
                                  value
                                )}
                              </td>
                            )
                          }

                          return (
                            <td key={`${activeMeeting.id}-${row.nr}-${col.key}`} style={col.width ? { width: col.width } : undefined}>
                              {value}
                            </td>
                          )
                        })}
                        {canEditMeetingTemplates ? (
                          <td>
                            {editingRowId === row.id ? (
                              <div style={{ display: "flex", gap: "6px" }}>
                                <button className="btn-primary" type="button" onClick={() => saveMeetingRow(activeMeeting.id, row.id)}>
                                  Save
                                </button>
                                <button className="btn-outline" type="button" onClick={cancelEditMeetingRow}>
                                  Cancel
                                </button>
                              </div>
                            ) : (
                              <div className="meeting-row-actions">
                                <button className="btn-icon" type="button" onClick={() => startEditMeetingRow(row)} aria-label="Edit row">
                                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                                    <path
                                      d="M4 20h4l10.5-10.5a2.121 2.121 0 0 0-3-3L5 17v3z"
                                      stroke="currentColor"
                                      strokeWidth="1.6"
                                      strokeLinecap="round"
                                      strokeLinejoin="round"
                                    />
                                  </svg>
                                </button>
                                <button
                                  className="btn-icon danger"
                                  type="button"
                                  onClick={() => deleteMeetingRow(activeMeeting.id, row.id)}
                                  aria-label="Delete row"
                                >
                                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                                    <path
                                      d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"
                                      stroke="currentColor"
                                      strokeWidth="1.6"
                                      strokeLinecap="round"
                                      strokeLinejoin="round"
                                    />
                                  </svg>
                                </button>
                              </div>
                            )}
                          </td>
                        ) : null}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {canEditMeetingTemplates ? (
                <div style={{ padding: "12px", borderTop: "1px solid #e2e8f0" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr)) auto", gap: "8px" }}>
                    <input
                      className="input"
                      type="text"
                      inputMode="numeric"
                      pattern="[0-9]*"
                      placeholder="Nr"
                      value={addDraft.nr}
                      onChange={(e) =>
                        setAddDraft((prev) => ({
                          ...prev,
                          nr: e.target.value.replace(/\D/g, ""),
                        }))
                      }
                    />
                    {activeMeeting.columns.some((col) => col.key === "day") ? (
                      <input
                        className="input"
                        type="text"
                        placeholder="Day"
                        value={addDraft.day}
                        onChange={(e) => setAddDraft((prev) => ({ ...prev, day: e.target.value }))}
                      />
                    ) : (
                      <span />
                    )}
                    <input
                      className="input"
                      type="text"
                      placeholder="Topic"
                      value={addDraft.topic}
                      onChange={(e) => setAddDraft((prev) => ({ ...prev, topic: e.target.value }))}
                      style={{ textTransform: "uppercase" }}
                    />
                    <button className="btn-primary" type="button" onClick={() => addMeetingRow(activeMeeting.id)}>
                      Add meeting point
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          ) : (
            <div className="meeting-empty">No meeting selected.</div>
          )}
        </section>
      ) : null}

      {externalMeetingsOpen ? (
        <section className="meeting-panel external-meetings-panel">
          <div className="meeting-panel-header">
            <div>
              <div className="meeting-title">External Meetings</div>
              <div className="meeting-subtitle">Calendar events from info@primexeu.com are shown here as TAK EXT; PV events are excluded.</div>
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              <button
                className="btn-surface"
                type="button"
                disabled={syncingExternalCalendar}
                onClick={() => void syncAndReloadExternalMeetings(true)}
              >
                {syncingExternalCalendar ? "Syncing..." : "Sync Calendar"}
              </button>
              <button className="btn-surface" type="button" onClick={() => setExternalMeetingsOpen(false)}>
                Close
              </button>
            </div>
          </div>
          <div className="external-meetings-grid" style={{ gridTemplateColumns: "minmax(0, 1fr)" }}>
            <div className="external-meeting-form" style={{ display: "none" }} aria-hidden="true">
              <div className="external-meeting-form-title">
                {externalMeetingCreateInternal ? "Add TAK EXT + TAK INT" : "Add TAK EXT"}
              </div>
              <div className="external-meeting-fields">
                <input
                  className="input"
                  type="text"
                  placeholder="Meeting title"
                  value={externalMeetingTitle}
                  onChange={(e) => setExternalMeetingTitle(e.target.value)}
                />
                <div className="external-meeting-row">
                  <input
                    className="input"
                    type="text"
                    placeholder="Platform (Zoom, Meet, Office...)"
                    value={externalMeetingPlatform}
                    onChange={(e) => setExternalMeetingPlatform(e.target.value)}
                  />
                  <select
                    className="input"
                    value={externalMeetingRecurrenceType}
                    onChange={(e) => setExternalMeetingRecurrenceType(e.target.value as "none" | "weekly" | "monthly" | "yearly")}
                  >
                    <option value="none">One time</option>
                    <option value="weekly">Every week</option>
                    <option value="monthly">Every month</option>
                    <option value="yearly">Every year</option>
                  </select>
                </div>
                <label className="external-create-internal-option">
                  <input
                    type="checkbox"
                    checked={externalMeetingCreateInternal}
                    onChange={(event) => setExternalMeetingCreateInternal(event.target.checked)}
                  />
                  <span className="external-create-internal-copy">
                    <strong>Create TAK INT</strong>
                    <small>Create a linked internal meeting with this TAK EXT.</small>
                  </span>
                  <span className={`external-create-internal-status ${externalMeetingCreateInternal ? "" : "off"}`}>
                    {externalMeetingCreateInternal ? "Yes" : "No"}
                  </span>
                </label>
                <div
                  className="external-meeting-row"
                  style={{ gridTemplateColumns: externalMeetingCreateInternal ? "repeat(2, minmax(0, 1fr))" : "1fr" }}
                >
                  {externalMeetingRecurrenceType === "none" ? (
                    <>
                      <label style={{ flex: 1, display: "grid", gap: "6px", fontSize: "12px", color: "#475569" }}>
                        TAK EXT date and time
                        <input
                          className="input"
                          type="datetime-local"
                          value={externalMeetingStartsAt}
                          onChange={(e) => {
                            const nextValue = e.target.value
                            setExternalMeetingStartsAt(nextValue)
                            const defaultInternalStart = getMeetingStartOneHourLater(nextValue)
                            if (!externalMeetingInternalStartsAtEditedRef.current) {
                              setExternalMeetingInternalStartsAt(defaultInternalStart?.date || "")
                            }
                            if (!externalMeetingInternalStartTimeEditedRef.current) {
                              setExternalMeetingInternalStartTime(defaultInternalStart?.time || "")
                            }
                          }}
                        />
                      </label>
                      {externalMeetingCreateInternal ? (
                        <label style={{ flex: 1, display: "grid", gap: "6px", fontSize: "12px", color: "#475569" }}>
                          TAK INT date and time
                          <span
                            className="input"
                            style={{
                              display: "flex",
                              alignItems: "center",
                              gap: "4px",
                              overflow: "hidden",
                              padding: "0 8px",
                            }}
                          >
                            <input
                              type="date"
                              value={externalMeetingInternalStartsAt}
                              onChange={(e) => {
                                externalMeetingInternalStartsAtEditedRef.current = true
                                setExternalMeetingInternalStartsAt(e.target.value)
                              }}
                              style={{
                                minWidth: 0,
                                flex: 1,
                                border: 0,
                                outline: 0,
                                background: "transparent",
                              }}
                            />
                            <span aria-hidden="true" style={{ height: "22px", width: "1px", backgroundColor: "#e2e8f0" }} />
                            <input
                              type="time"
                              value={externalMeetingInternalStartTime}
                              onChange={(e) => {
                                externalMeetingInternalStartTimeEditedRef.current = true
                                setExternalMeetingInternalStartTime(e.target.value)
                              }}
                              style={{
                                width: "105px",
                                border: 0,
                                outline: 0,
                                background: "transparent",
                              }}
                            />
                          </span>
                        </label>
                      ) : null}
                    </>
                  ) : (
                    <>
                      <label style={{ flex: 1, display: "grid", gap: "6px", fontSize: "12px", color: "#475569" }}>
                        TAK EXT time
                        <input
                          className="input"
                          type="time"
                          value={externalMeetingStartTime}
                          onChange={(e) => {
                            const nextValue = e.target.value
                            setExternalMeetingStartTime(nextValue)
                            if (!externalMeetingInternalStartTimeEditedRef.current) {
                              setExternalMeetingInternalStartTime(getMeetingTimeOneHourLater(nextValue))
                            }
                          }}
                        />
                      </label>
                      {externalMeetingCreateInternal ? (
                        <label style={{ flex: 1, display: "grid", gap: "6px", fontSize: "12px", color: "#475569" }}>
                          TAK INT time
                          <input
                            className="input"
                            type="time"
                            value={externalMeetingInternalStartTime}
                            onChange={(e) => {
                              externalMeetingInternalStartTimeEditedRef.current = true
                              setExternalMeetingInternalStartTime(e.target.value)
                            }}
                          />
                        </label>
                      ) : null}
                    </>
                  )}
                </div>
                {externalMeetingRecurrenceType === "weekly" ? (
                  <>
                    <div className="external-meeting-row" style={{ justifyContent: "flex-start" }}>
                      <button
                        className="btn-surface"
                        type="button"
                        onClick={() => setShowWeekendDays((prev) => !prev)}
                        style={{
                          padding: "4px 10px",
                          fontSize: "12px",
                          fontWeight: 600,
                          backgroundColor: showWeekendDays ? "#1d4ed8" : "#eef2ff",
                          borderColor: "#3b82f6",
                          color: showWeekendDays ? "#ffffff" : "#1d4ed8",
                        }}
                      >
                        {showWeekendDays ? "Hide weekend days" : "Show weekend days"}
                      </button>
                    </div>
                    <div className="external-meeting-row" style={{ flexWrap: "wrap", gap: "8px", alignItems: "center" }}>
                      {["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                        .map((day, idx) => ({ day, idx }))
                        .filter(({ idx }) => showWeekendDays || idx < 5)
                        .map(({ day, idx }) => (
                          <label key={day} style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px" }}>
                            <input
                              type="checkbox"
                              checked={externalMeetingRecurrenceDaysOfWeek.includes(idx)}
                              onChange={(e) => {
                                if (e.target.checked) {
                                  setExternalMeetingRecurrenceDaysOfWeek((prev) => [...prev, idx])
                                } else {
                                  setExternalMeetingRecurrenceDaysOfWeek((prev) => prev.filter((d) => d !== idx))
                                }
                              }}
                            />
                            {day}
                          </label>
                        ))}
                    </div>
                  </>
                ) : null}
                {externalMeetingRecurrenceType === "monthly" ? (
                  <div
                    className="external-meeting-row"
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(7, minmax(0, 1fr))",
                      gap: "6px",
                    }}
                  >
                    {Array.from({ length: 31 }, (_, i) => i + 1).map((day) => (
                      <label
                        key={day}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: "6px",
                          fontSize: "12px",
                          padding: "4px 6px",
                          border: "1px solid #e2e8f0",
                          borderRadius: "8px",
                          backgroundColor: externalMeetingRecurrenceDaysOfMonth.includes(day) ? "#eef2ff" : "#ffffff",
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={externalMeetingRecurrenceDaysOfMonth.includes(day)}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setExternalMeetingRecurrenceDaysOfMonth((prev) => [...prev, day])
                            } else {
                              setExternalMeetingRecurrenceDaysOfMonth((prev) => prev.filter((d) => d !== day))
                            }
                          }}
                        />
                        <span style={{ fontVariantNumeric: "tabular-nums" }}>{day}</span>
                      </label>
                    ))}
                  </div>
                ) : null}
                {externalMeetingRecurrenceType === "yearly" ? (
                  <div className="external-meeting-row" style={{ gap: "8px" }}>
                    <select
                      className="input"
                      value={externalMeetingRecurrenceMonth}
                      onChange={(e) => setExternalMeetingRecurrenceMonth(e.target.value)}
                    >
                      {[
                        "January",
                        "February",
                        "March",
                        "April",
                        "May",
                        "June",
                        "July",
                        "August",
                        "September",
                        "October",
                        "November",
                        "December",
                      ].map((label, idx) => (
                        <option key={label} value={String(idx + 1)}>
                          {label}
                        </option>
                      ))}
                    </select>
                    <select
                      className="input"
                      value={externalMeetingRecurrenceDay}
                      onChange={(e) => setExternalMeetingRecurrenceDay(e.target.value)}
                    >
                      {Array.from({ length: 31 }, (_, i) => i + 1).map((day) => (
                        <option key={day} value={String(day)}>
                          {day}
                        </option>
                      ))}
                    </select>
                  </div>
                ) : null}
                <div className="external-meeting-row">
                  <div className="external-meeting-field-stack">
                    <select
                      className="input"
                      value={externalMeetingDepartmentId}
                      onChange={(e) => setExternalMeetingDepartmentId(e.target.value)}
                      disabled={!canSelectExternalDepartment}
                    >
                      <option value="">
                        {canSelectExternalDepartment ? "Select department" : "Department"}
                      </option>
                      {departments.map((dep) => (
                        <option key={dep.id} value={dep.id}>
                          {dep.name === "Project Content Manager" ? "Product Content" : dep.name}
                        </option>
                      ))}
                    </select>
                    {!canSelectExternalDepartment && externalMeetingDepartment ? (
                      <div className="external-meeting-hint">
                        {externalMeetingDepartment.name === "Project Content Manager" ? "Product Content" : externalMeetingDepartment.name}
                      </div>
                    ) : null}
                  </div>
                  <div className="external-person-picker" ref={externalMeetingPersonsRef}>
                    <button
                      className={`external-person-picker-trigger ${externalMeetingPersonsOpen ? "active" : ""}`}
                      type="button"
                      onClick={() => {
                        setExternalMeetingPersonsOpen((current) => {
                          if (current) setExternalMeetingPersonSearch("")
                          return !current
                        })
                      }}
                      aria-haspopup="dialog"
                      aria-expanded={externalMeetingPersonsOpen}
                    >
                      <span>{externalMeetingParticipantIds.length ? "Persons selected" : "Add persons (required)"}</span>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}>
                        {externalMeetingParticipantIds.length ? (
                          <span className="external-person-picker-count">{externalMeetingParticipantIds.length}</span>
                        ) : null}
                        <span aria-hidden="true">{externalMeetingPersonsOpen ? "^" : "v"}</span>
                      </span>
                    </button>
                    {externalMeetingPersonsOpen ? (
                      <div
                        className="external-person-picker-menu"
                        role="dialog"
                        aria-label="External meeting persons"
                      >
                        <input
                          className="external-person-picker-search"
                          type="search"
                          value={externalMeetingPersonSearch}
                          onChange={(event) => setExternalMeetingPersonSearch(event.target.value)}
                          placeholder="Search persons..."
                          aria-label="Search external meeting persons"
                          autoFocus
                        />
                        <div className="external-person-picker-list" role="group">
                          {commonUserFilterOptions
                            .filter(
                              (option) =>
                                option.isActive
                                && option.label.toLowerCase().includes(externalMeetingPersonSearch.trim().toLowerCase())
                            )
                            .map((option) => (
                              <label key={option.id} className="external-person-picker-option">
                                <input
                                  type="checkbox"
                                  checked={externalMeetingParticipantIds.includes(option.id)}
                                  onChange={(event) => {
                                    setExternalMeetingParticipantIds((current) =>
                                      event.target.checked
                                        ? [...current, option.id]
                                        : current.filter((id) => id !== option.id)
                                    )
                                  }}
                                />
                                <span>{option.label}</span>
                              </label>
                            ))}
                          {!commonUserFilterOptions.some(
                            (option) =>
                              option.isActive
                              && option.label.toLowerCase().includes(externalMeetingPersonSearch.trim().toLowerCase())
                          ) ? (
                            <div className="external-person-picker-empty">No persons found</div>
                          ) : null}
                        </div>
                        <div className="external-person-picker-footer">
                          <button
                            className="external-person-picker-done"
                            type="button"
                            onClick={() => {
                              setExternalMeetingPersonsOpen(false)
                              setExternalMeetingPersonSearch("")
                            }}
                          >
                            Done
                          </button>
                        </div>
                      </div>
                    ) : null}
                    {externalMeetingParticipantIds.length ? (
                      <div className="external-person-chips" aria-label="Selected persons">
                        {externalMeetingParticipantIds.slice(0, 3).map((id) => {
                          const person = commonUserFilterOptions.find((option) => option.id === id)
                          if (!person) return null
                          return (
                            <button
                              key={person.id}
                              className="external-person-chip"
                              type="button"
                              title={`Remove ${person.label}`}
                              onClick={() => setExternalMeetingParticipantIds((current) => current.filter((itemId) => itemId !== person.id))}
                            >
                              <span>{person.label}</span>
                              <span className="external-person-chip-remove" aria-hidden="true">&times;</span>
                            </button>
                          )
                        })}
                        {externalMeetingParticipantIds.length > 3 ? (
                          <span className="external-person-chip">+{externalMeetingParticipantIds.length - 3}</span>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                </div>
                <div style={{ marginTop: "2px" }}>
                  <button
                    className="btn-surface"
                    type="button"
                    onClick={() => setExternalMeetingChecklistOpen((prev) => !prev)}
                    disabled={externalMeetingChecklistLoading}
                    style={{ width: "100%", marginBottom: externalMeetingChecklistOpen ? "12px" : "0" }}
                  >
                    {externalMeetingChecklistLoading
                      ? "Loading Checklist..."
                      : externalMeetingChecklistOpen
                        ? "Hide Checklist"
                        : "Show Checklist"}
                    {/* Checklist is optional for creating meetings; no blocking warning here. */}
                  </button>
                  {externalMeetingChecklistOpen && !externalMeetingChecklistLoading && (
                    <>
                      {externalMeetingChecklist && externalMeetingChecklist.items && externalMeetingChecklist.items.length > 0 ? (
                        <div style={{ padding: "16px", border: "1px solid #e2e8f0", borderRadius: "8px", backgroundColor: "#f8fafc" }}>
                          <div style={{ marginBottom: "12px", fontWeight: "600", fontSize: "14px", color: "#1e293b" }}>
                            {externalMeetingChecklist.title || "Checklist"}
                          </div>
                          <div className="external-checklist-media">
                            <div className="external-checklist-media-title">Meeting options (reference)</div>
                            {!externalChecklistImageError ? (
                              <a href="/external-meeting-options.png" target="_blank" rel="noreferrer">
                                <img
                                  src="/external-meeting-options.png"
                                  alt="Teams meeting options reference"
                                  onError={() => setExternalChecklistImageError(true)}
                                />
                              </a>
                            ) : (
                              <div className="external-checklist-media-hint">
                                Add the image file to: <code>frontend/public/external-meeting-options.png</code>
                                <br />
                                Then refresh the page.
                              </div>
                            )}
                          </div>
                          <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                            {(() => {
                              const sorted = externalMeetingChecklist.items
                                .slice()
                                .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
                              let mainCounter = 0
                              return sorted.map((item, idx) => {
                                const isChecked = externalMeetingChecklistItems.get(item.id) ?? false
                                const rawTitle = item.title || ""
                                const match = rawTitle.match(/^(\d+(?:\.\d+)*)\.\s*(.*)$/)
                                const prefix = match?.[1] || ""
                                const titleOnly = (match?.[2] ?? rawTitle).trim()
                                const isSubpoint = /^\d+\.\d+/.test(prefix)
                                if (!isSubpoint) mainCounter += 1
                                // Always anchor numbering to the current mainCounter:
                                // - main items: 1,2,3...
                                // - subpoints: <current-main>.<sub> (so 9.1 becomes 10.1 if a new main item was inserted)
                                const displayNr = isSubpoint
                                  ? `${mainCounter}${prefix.replace(/^\d+/, "")}`
                                  : String(mainCounter)
                                const displayTitle = titleOnly
                                return (
                                  <div
                                    key={item.id}
                                    style={{
                                      display: "flex",
                                      alignItems: "flex-start",
                                      gap: "8px",
                                      padding: "8px",
                                      borderRadius: "4px",
                                      backgroundColor: isChecked ? "#f0fdf4" : "transparent",
                                      transition: "background-color 0.2s",
                                    }}
                                  >
                                    <span
                                      style={{
                                        width: "22px",
                                        flexShrink: 0,
                                        fontSize: "12px",
                                        fontWeight: 700,
                                        color: "#475569",
                                        textAlign: "right",
                                        marginTop: "2px",
                                      }}
                                    >
                                      {displayNr}.
                                    </span>
                                    <input
                                      type="checkbox"
                                      checked={isChecked}
                                      onChange={() => void toggleChecklistItem(item.id)}
                                      style={{ marginTop: "2px", cursor: "pointer" }}
                                    />
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                      {isAdmin && externalChecklistEditingId === item.id ? (
                                        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                                          <input
                                            className="input"
                                            type="text"
                                            value={externalChecklistEditTitle}
                                            onChange={(e) => setExternalChecklistEditTitle(e.target.value)}
                                            style={{ flex: 1 }}
                                          />
                                          <button
                                            className="btn-surface"
                                            type="button"
                                            onClick={() => void saveExternalChecklistItemTitle(item.id)}
                                            disabled={externalChecklistSavingId === item.id || !externalChecklistEditTitle.trim()}
                                          >
                                            Save
                                          </button>
                                          <button
                                            className="btn-surface"
                                            type="button"
                                            onClick={() => cancelEditExternalChecklistItem()}
                                            disabled={externalChecklistSavingId === item.id}
                                          >
                                            Cancel
                                          </button>
                                        </div>
                                      ) : (
                                        <span style={{ fontSize: "13px", lineHeight: "1.5", color: "#334155" }}>
                                          {displayTitle}
                                        </span>
                                      )}
                                    </div>
                                    {isAdmin ? (
                                      <div style={{ display: "flex", gap: "6px", marginLeft: "8px" }}>
                                        <button
                                          className="btn-surface"
                                          type="button"
                                          onClick={() => startEditExternalChecklistItem(item.id, `${displayNr}. ${displayTitle}`)}
                                          disabled={externalChecklistDeletingId === item.id || externalChecklistSavingId === item.id}
                                        >
                                          Edit
                                        </button>
                                        <button
                                          className="btn-surface"
                                          type="button"
                                          onClick={() => void deleteExternalChecklistItem(item.id)}
                                          disabled={externalChecklistDeletingId === item.id || externalChecklistSavingId === item.id}
                                        >
                                          {externalChecklistDeletingId === item.id ? "Deleting..." : "Delete"}
                                        </button>
                                      </div>
                                    ) : null}
                                  </div>
                                )
                              })
                            })()}
                          </div>
                          {isAdmin ? (
                            <div style={{ marginTop: "12px", paddingTop: "12px", borderTop: "1px solid #e2e8f0" }}>
                              <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                                <input
                                  className="input"
                                  type="number"
                                  min={1}
                                  placeholder="Order #"
                                  value={externalChecklistAddOrder}
                                  onChange={(e) => setExternalChecklistAddOrder(e.target.value)}
                                  style={{ width: "110px" }}
                                />
                                <input
                                  className="input"
                                  type="text"
                                  placeholder="Add new checklist item..."
                                  value={externalChecklistAddTitle}
                                  onChange={(e) => setExternalChecklistAddTitle(e.target.value)}
                                  style={{ flex: 1 }}
                                />
                                <button
                                  className="btn-surface"
                                  type="button"
                                  onClick={() => void addExternalChecklistItem()}
                                  disabled={
                                    externalChecklistAdding ||
                                    !externalChecklistAddTitle.trim() ||
                                    !externalMeetingChecklist?.id ||
                                    (externalChecklistAddOrder.trim() !== "" &&
                                      (!Number.isFinite(Number(externalChecklistAddOrder)) || Number(externalChecklistAddOrder) <= 0))
                                  }
                                >
                                  {externalChecklistAdding ? "Adding..." : "Add"}
                                </button>
                              </div>
                            </div>
                          ) : null}
                        </div>
                      ) : (
                        <div style={{ padding: "12px", textAlign: "center", color: "#dc2626", fontSize: "13px", border: "1px solid #fecaca", borderRadius: "4px", backgroundColor: "#fef2f2" }}>
                          Checklist not found. Please run the database migration to create the external meetings checklist.
                        </div>
                      )}
                    </>
                  )}
                </div>
                <button
                  className="btn-surface"
                  type="button"
                  disabled={!canSelectExternalMeetingAgentTestTask || creatingExternalMeeting}
                  onClick={() => setExternalMeetingCreateAgentTestTask((prev) => !prev)}
                  title={
                    canSelectExternalMeetingAgentTestTask
                      ? "Toggle Testimi i agentave task creation for this meeting"
                      : "Available only for one-time meetings with a start date"
                  }
                  style={{
                    width: "100%",
                    marginTop: "16px",
                    fontWeight: 600,
                    fontSize: "13px",
                    padding: "8px 12px",
                    backgroundColor: externalMeetingCreateAgentTestTask ? "#dcfce7" : "#ffffff",
                    borderColor: externalMeetingCreateAgentTestTask ? "#16a34a" : "#cbd5e1",
                    color: externalMeetingCreateAgentTestTask ? "#166534" : "#334155",
                  }}
                >
                  {externalMeetingCreateAgentTestTask ? "Test task will be created" : "A duhet te krijohet detyra 'Testimi i agentave'?"}
                </button>
                <button
                  className="btn-surface"
                  type="button"
                  disabled={!canSelectExternalMeetingAgentTestTask || creatingExternalMeeting}
                  onClick={() => setExternalMeetingCreatePimImageTestTask((prev) => !prev)}
                  title={
                    canSelectExternalMeetingAgentTestTask
                      ? "Toggle Testimi i PIM image task creation for Graphic Design"
                      : "Available only for one-time meetings with a start date"
                  }
                  style={{
                    width: "100%",
                    marginTop: "8px",
                    fontWeight: 600,
                    fontSize: "13px",
                    padding: "8px 12px",
                    backgroundColor: externalMeetingCreatePimImageTestTask ? "#dcfce7" : "#ffffff",
                    borderColor: externalMeetingCreatePimImageTestTask ? "#16a34a" : "#cbd5e1",
                    color: externalMeetingCreatePimImageTestTask ? "#166534" : "#334155",
                  }}
                >
                  {externalMeetingCreatePimImageTestTask
                    ? "PIM image test task will be created"
                    : "A duhet te krijohet detyra 'Testimi i PIM image'?"}
                </button>
                <div className="external-meeting-row" style={{ marginTop: "16px" }}>
                  <button
                    className="btn-primary"
                    type="button"
                    disabled={!canCreateExternalMeeting || creatingExternalMeeting}
                    onClick={() => void submitExternalMeeting()}
                    style={{
                      width: "100%",
                      fontWeight: 600,
                      fontSize: "13px",
                      padding: "8px 12px",
                      backgroundColor: "#2563eb",
                      borderColor: "#1d4ed8",
                      boxShadow: "0 6px 14px rgba(37, 99, 235, 0.25)",
                      color: "#ffffff",
                    }}
                  >
                    {creatingExternalMeeting ? "Saving..." : "Add"}
                  </button>
                </div>
              </div>
            </div>
            <div className="external-meeting-list">
              <div className="external-meeting-list-header">
                <div className="external-meeting-form-title">
                  {selectedDates.size
                    ? `External meetings for ${Array.from(selectedDates).sort().map(formatDateHuman).join(", ")}`
                    : "All external meetings"}
                </div>
                {!selectedDates.size ? (
                  <div className="external-meeting-filter" aria-label="External meetings filter">
                    {([
                      ["next", "Next"],
                      ["past", "Past"],
                      ["all", "All"],
                    ] as const).map(([value, label]) => (
                      <button
                        key={value}
                        type="button"
                        className={externalMeetingListFilter === value ? "active" : ""}
                        onClick={() => setExternalMeetingListFilter(value)}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
              {externalMeetingsVisible.length ? (
                <div className="external-meeting-cards">
                  {externalMeetingsVisible.map((meeting) => {
                    const department = departments.find((d) => d.id === meeting.department_id) || null
                    const owner = meeting.created_by ? userById.get(meeting.created_by) : null
                    const ownerName = owner?.full_name || owner?.username || "Unknown"
                    const participantNames = (meeting.participant_ids || [])
                      .map((participantId) => {
                        const participant = userById.get(participantId)
                        return participant?.full_name || participant?.username || participant?.email || ""
                      })
                      .filter(Boolean)
                    const isEditing = editingExternalMeetingId === meeting.id
                    const linkedInternalMeeting = internalMeetings.find(
                      (internalMeeting) => internalMeeting.paired_external_meeting_id === meeting.id
                    )
                    return (
                      <div
                        key={meeting.id}
                        className={`external-meeting-card ${meetingLegendTone({
                          categories: meeting.calendar_categories,
                          recurrenceType: meeting.recurrence_type,
                          meetingType: "external",
                          calendarImported: Boolean(meeting.calendar_imported || meeting.microsoft_event_id),
                        })}`}
                      >
                        {isEditing ? (
                          <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                            <input
                              className="input"
                              type="text"
                              placeholder="Meeting title"
                              value={editingExternalMeetingTitle}
                              onChange={(e) => setEditingExternalMeetingTitle(e.target.value)}
                            />
                            <div className="external-meeting-row">
                              <input
                                className="input"
                                type="text"
                                placeholder="Platform (Zoom, Meet, Office...)"
                                value={editingExternalMeetingPlatform}
                                onChange={(e) => setEditingExternalMeetingPlatform(e.target.value)}
                              />
                              {editingExternalMeetingRecurrenceType === "none" ? (
                                <input
                                  className="input"
                                  type="datetime-local"
                                  value={editingExternalMeetingStartsAt}
                                  onChange={(e) => setEditingExternalMeetingStartsAt(e.target.value)}
                                />
                              ) : (
                                <input
                                  className="input"
                                  type="time"
                                  value={editingExternalMeetingStartTime}
                                  onChange={(e) => setEditingExternalMeetingStartTime(e.target.value)}
                                />
                              )}
                            </div>
                            <div className="external-meeting-row">
                              <select
                                className="input"
                                value={editingExternalMeetingRecurrenceType}
                                onChange={(e) => setEditingExternalMeetingRecurrenceType(e.target.value as "none" | "weekly" | "monthly" | "yearly")}
                              >
                                <option value="none">One time</option>
                                <option value="weekly">Every week</option>
                                <option value="monthly">Every month</option>
                                <option value="yearly">Every year</option>
                              </select>
                            </div>
                            {editingExternalMeetingRecurrenceType === "weekly" ? (
                              <>
                                <div className="external-meeting-row" style={{ justifyContent: "flex-start" }}>
                                  <button
                                    className="btn-surface"
                                    type="button"
                                    onClick={() => setShowEditWeekendDays((prev) => !prev)}
                                    style={{
                                      padding: "4px 10px",
                                      fontSize: "12px",
                                      fontWeight: 600,
                                      backgroundColor: showEditWeekendDays ? "#1d4ed8" : "#eef2ff",
                                      borderColor: "#3b82f6",
                                      color: showEditWeekendDays ? "#ffffff" : "#1d4ed8",
                                    }}
                                  >
                                    {showEditWeekendDays ? "Hide weekend days" : "Show weekend days"}
                                  </button>
                                </div>
                                <div className="external-meeting-row" style={{ flexWrap: "wrap", gap: "8px", alignItems: "center" }}>
                                  {["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                                    .map((day, idx) => ({ day, idx }))
                                    .filter(({ idx }) => showEditWeekendDays || idx < 5)
                                    .map(({ day, idx }) => (
                                      <label key={day} style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px" }}>
                                        <input
                                          type="checkbox"
                                          checked={editingExternalMeetingRecurrenceDaysOfWeek.includes(idx)}
                                          onChange={(e) => {
                                            if (e.target.checked) {
                                              setEditingExternalMeetingRecurrenceDaysOfWeek((prev) => [...prev, idx])
                                            } else {
                                              setEditingExternalMeetingRecurrenceDaysOfWeek((prev) => prev.filter((d) => d !== idx))
                                            }
                                          }}
                                        />
                                        {day}
                                      </label>
                                    ))}
                                </div>
                              </>
                            ) : null}
                            {editingExternalMeetingRecurrenceType === "monthly" ? (
                              <div
                                className="external-meeting-row"
                                style={{
                                  display: "grid",
                                  gridTemplateColumns: "repeat(7, minmax(0, 1fr))",
                                  gap: "6px",
                                }}
                              >
                                {Array.from({ length: 31 }, (_, i) => i + 1).map((day) => (
                                  <label
                                    key={day}
                                    style={{
                                      display: "flex",
                                      alignItems: "center",
                                      gap: "6px",
                                      fontSize: "12px",
                                      padding: "4px 6px",
                                      border: "1px solid #e2e8f0",
                                      borderRadius: "8px",
                                      backgroundColor: editingExternalMeetingRecurrenceDaysOfMonth.includes(day) ? "#eef2ff" : "#ffffff",
                                    }}
                                  >
                                    <input
                                      type="checkbox"
                                      checked={editingExternalMeetingRecurrenceDaysOfMonth.includes(day)}
                                      onChange={(e) => {
                                        if (e.target.checked) {
                                          setEditingExternalMeetingRecurrenceDaysOfMonth((prev) => [...prev, day])
                                        } else {
                                          setEditingExternalMeetingRecurrenceDaysOfMonth((prev) => prev.filter((d) => d !== day))
                                        }
                                      }}
                                    />
                                    <span style={{ fontVariantNumeric: "tabular-nums" }}>{day}</span>
                                  </label>
                                ))}
                              </div>
                            ) : null}
                            {editingExternalMeetingRecurrenceType === "yearly" ? (
                              <div className="external-meeting-row" style={{ gap: "8px" }}>
                                <select
                                  className="input"
                                  value={editingExternalMeetingRecurrenceMonth}
                                  onChange={(e) => setEditingExternalMeetingRecurrenceMonth(e.target.value)}
                                >
                                  {[
                                    "January",
                                    "February",
                                    "March",
                                    "April",
                                    "May",
                                    "June",
                                    "July",
                                    "August",
                                    "September",
                                    "October",
                                    "November",
                                    "December",
                                  ].map((label, idx) => (
                                    <option key={label} value={String(idx + 1)}>
                                      {label}
                                    </option>
                                  ))}
                                </select>
                                <select
                                  className="input"
                                  value={editingExternalMeetingRecurrenceDay}
                                  onChange={(e) => setEditingExternalMeetingRecurrenceDay(e.target.value)}
                                >
                                  {Array.from({ length: 31 }, (_, i) => i + 1).map((day) => (
                                    <option key={day} value={String(day)}>
                                      {day}
                                    </option>
                                  ))}
                                </select>
                              </div>
                            ) : null}
                            <div className="external-meeting-row">
                              <select
                                className="input"
                                value={editingExternalMeetingDepartmentId}
                                onChange={(e) => setEditingExternalMeetingDepartmentId(e.target.value)}
                              >
                                <option value="">Select department</option>
                                {departments.map((dep) => (
                                  <option key={dep.id} value={dep.id}>
                                    {dep.name}
                                  </option>
                                ))}
                              </select>
                            </div>
                            <div className="external-person-picker compact" ref={editingExternalMeetingPersonsRef}>
                              <button
                                className={`external-person-picker-trigger ${editingExternalMeetingPersonsOpen ? "active" : ""}`}
                                type="button"
                                onClick={() => {
                                  setEditingExternalMeetingPersonsOpen((current) => {
                                    if (current) setEditingExternalMeetingPersonSearch("")
                                    return !current
                                  })
                                }}
                                aria-haspopup="dialog"
                                aria-expanded={editingExternalMeetingPersonsOpen}
                              >
                                <span>
                                  {editingExternalMeetingParticipantIds.length
                                    ? "Assigned PrimeFlow users"
                                    : "Assign PrimeFlow users"}
                                </span>
                                <span style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}>
                                  {editingExternalMeetingParticipantIds.length ? (
                                    <span className="external-person-picker-count">
                                      {editingExternalMeetingParticipantIds.length}
                                    </span>
                                  ) : null}
                                  <span aria-hidden="true">{editingExternalMeetingPersonsOpen ? "^" : "v"}</span>
                                </span>
                              </button>
                              {editingExternalMeetingPersonsOpen ? (
                                <div
                                  className="external-person-picker-menu"
                                  role="dialog"
                                  aria-label="Assign PrimeFlow users to external meeting"
                                >
                                  <input
                                    className="external-person-picker-search"
                                    type="search"
                                    value={editingExternalMeetingPersonSearch}
                                    onChange={(event) => setEditingExternalMeetingPersonSearch(event.target.value)}
                                    placeholder="Search users..."
                                    aria-label="Search PrimeFlow users"
                                    autoFocus
                                  />
                                  <div className="external-person-picker-list" role="group">
                                    {commonUserFilterOptions
                                      .filter(
                                        (option) =>
                                          option.isActive
                                          && option.label.toLowerCase().includes(
                                            editingExternalMeetingPersonSearch.trim().toLowerCase()
                                          )
                                      )
                                      .map((option) => (
                                        <label key={option.id} className="external-person-picker-option">
                                          <input
                                            type="checkbox"
                                            checked={editingExternalMeetingParticipantIds.includes(option.id)}
                                            onChange={(event) => {
                                              setEditingExternalMeetingParticipantIds((current) =>
                                                event.target.checked
                                                  ? Array.from(new Set([...current, option.id]))
                                                  : current.filter((id) => id !== option.id)
                                              )
                                            }}
                                          />
                                          <span>{option.label}</span>
                                        </label>
                                      ))}
                                    {!commonUserFilterOptions.some(
                                      (option) =>
                                        option.isActive
                                        && option.label.toLowerCase().includes(
                                          editingExternalMeetingPersonSearch.trim().toLowerCase()
                                        )
                                    ) ? (
                                      <div className="external-person-picker-empty">No users found</div>
                                    ) : null}
                                  </div>
                                  <div className="external-person-picker-footer">
                                    <button
                                      className="external-person-picker-done"
                                      type="button"
                                      onClick={() => {
                                        setEditingExternalMeetingPersonsOpen(false)
                                        setEditingExternalMeetingPersonSearch("")
                                      }}
                                    >
                                      Done
                                    </button>
                                  </div>
                                </div>
                              ) : null}
                              {editingExternalMeetingParticipantIds.length ? (
                                <div className="external-person-chips" aria-label="Assigned PrimeFlow users">
                                  {editingExternalMeetingParticipantIds.slice(0, 3).map((id) => {
                                    const person = commonUserFilterOptions.find((option) => option.id === id)
                                    if (!person) return null
                                    return (
                                      <button
                                        key={person.id}
                                        className="external-person-chip"
                                        type="button"
                                        title={`Remove ${person.label}`}
                                        onClick={() =>
                                          setEditingExternalMeetingParticipantIds((current) =>
                                            current.filter((itemId) => itemId !== person.id)
                                          )
                                        }
                                      >
                                        <span>{person.label}</span>
                                        <span className="external-person-chip-remove" aria-hidden="true">&times;</span>
                                      </button>
                                    )
                                  })}
                                  {editingExternalMeetingParticipantIds.length > 3 ? (
                                    <span className="external-person-chip">
                                      +{editingExternalMeetingParticipantIds.length - 3}
                                    </span>
                                  ) : null}
                                </div>
                              ) : null}
                            </div>
                            <div style={{ display: "flex", gap: "8px" }}>
                              <button
                                className="btn-surface"
                                type="button"
                                onClick={() => void saveExternalMeeting()}
                                disabled={updatingExternalMeeting || !editingExternalMeetingTitle.trim()}
                                style={{ flex: 1 }}
                              >
                                {updatingExternalMeeting ? "Saving..." : "Save"}
                              </button>
                              <button
                                className="btn-surface"
                                type="button"
                                onClick={cancelEditExternalMeeting}
                                disabled={updatingExternalMeeting}
                              >
                                Cancel
                              </button>
                            </div>
                          </div>
                        ) : (
                          <>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                              <div style={{ flex: 1 }}>
                                <div className="external-meeting-title">{meeting.title || "External meeting"}</div>
                                {meeting.calendar_imported ? (
                                  <div className="external-meeting-meta">
                                    <span>{meeting.calendar_sync_status === "cancelled" ? "Cancelled in Outlook" : "Microsoft Calendar"}</span>
                                  </div>
                                ) : null}
                                <div className="external-meeting-meta">
                                  <span>{formatExternalMeetingWhen(meeting)}</span>
                                  <span>{meeting.platform || "Platform TBD"}</span>
                                </div>
                                <div className="external-meeting-meta">
                                  <span>{department?.name || "Department TBD"}</span>
                                  <span>Owner: {ownerName}</span>
                                </div>
                                {participantNames.length ? (
                                  <div className="external-meeting-person-summary" aria-label="Meeting persons">
                                    <span className="external-meeting-person-count">
                                      {participantNames.length} {participantNames.length === 1 ? "person" : "persons"}
                                    </span>
                                    <span className="external-meeting-person-names" title={participantNames.join(", ")}>
                                      {participantNames.join(", ")}
                                    </span>
                                  </div>
                                ) : null}
                                <div className="external-meeting-meta" style={{ marginTop: "8px" }}>
                                  <span>Status: {renderMeetingStatusControl(meeting)}</span>
                                </div>
                                <div style={{ marginTop: "8px" }}>
                                  {linkedInternalMeeting ? (
                                    <span className="external-meeting-person-count">TAK INT linked</span>
                                  ) : meeting.calendar_sync_status !== "cancelled" ? (
                                    <button
                                      className="btn-surface"
                                      type="button"
                                      onClick={() => startLinkedInternalMeeting(meeting)}
                                      style={{ fontSize: "12px", padding: "4px 8px" }}
                                    >
                                      Create linked TAK INT
                                    </button>
                                  ) : null}
                                </div>
                              </div>
                              <div style={{ display: "flex", gap: "6px", marginLeft: "12px", flexWrap: "wrap", justifyContent: "flex-end" }}>
                                  <button
                                    className="btn-surface"
                                    type="button"
                                    onClick={() => openMeetingDetails(meeting)}
                                    title="View meeting details and assign PrimeFlow participants"
                                    style={{ borderColor: "#93c5fd", color: "#1d4ed8" }}
                                  >
                                    Participants &amp; reminder
                                  </button>
                                  {(isAdmin || isManager) && canCreateAgentTestTaskForMeeting(meeting) ? (
                                    <button
                                      className="btn-surface"
                                      type="button"
                                      onClick={() => void createAgentTestTaskForExternalMeeting(meeting.id)}
                                      disabled={
                                        creatingAgentTestTaskMeetingId === meeting.id
                                        || deletingExternalMeetingId === meeting.id
                                        || updatingExternalMeeting
                                      }
                                      title="Create Testimi i agentave task for this meeting"
                                      style={{
                                        fontSize: "12px",
                                        padding: "4px 8px",
                                        backgroundColor: "#ffffff",
                                        borderColor: "#cbd5e1",
                                        color: "#334155",
                                      }}
                                    >
                                      {creatingAgentTestTaskMeetingId === meeting.id
                                        ? "Creating..."
                                        : "Krijo detyrën 'Testimi i agentave'"}
                                    </button>
                                  ) : null}
                                  {(isAdmin || isManager) && canCreatePimImageTestTaskForMeeting(meeting) ? (
                                    <button
                                      className="btn-surface"
                                      type="button"
                                      onClick={() => void createPimImageTestTaskForExternalMeeting(meeting.id)}
                                      disabled={
                                        creatingPimImageTestTaskMeetingId === meeting.id
                                        || deletingExternalMeetingId === meeting.id
                                        || updatingExternalMeeting
                                      }
                                      title="Create Testimi i PIM image task for Graphic Design"
                                      style={{
                                        fontSize: "12px",
                                        padding: "4px 8px",
                                        backgroundColor: "#ffffff",
                                        borderColor: "#cbd5e1",
                                        color: "#334155",
                                      }}
                                    >
                                      {creatingPimImageTestTaskMeetingId === meeting.id
                                        ? "Creating..."
                                        : "Krijo detyrën 'Testimi i PIM image'"}
                                    </button>
                                  ) : null}
                                  {canEditExternalMeeting(meeting) ? (
                                    <>
                                      <button
                                        className="btn-surface"
                                        type="button"
                                        onClick={() => startEditExternalMeeting(meeting)}
                                        disabled={deletingExternalMeetingId === meeting.id || updatingExternalMeeting}
                                        title="Edit meeting"
                                      >
                                        Edit
                                      </button>
                                      {isAdmin ? (
                                        <button
                                          className="btn-surface"
                                          type="button"
                                          onClick={() => void deleteExternalMeeting(meeting.id)}
                                          disabled={deletingExternalMeetingId === meeting.id || updatingExternalMeeting}
                                          title="Delete meeting"
                                          style={{ color: "#dc2626", borderColor: "#fecaca" }}
                                        >
                                          {deletingExternalMeetingId === meeting.id ? "Deleting..." : "Delete"}
                                        </button>
                                      ) : null}
                                    </>
                                  ) : null}
                                </div>
                            </div>
                          </>
                        )}
                      </div>
                    )
                  })}
                </div>
              ) : (
                <div className="external-meeting-empty">
                  {selectedDates.size
                    ? "No external meetings for the selected date."
                    : externalMeetingListFilter === "past"
                    ? "No past external meetings."
                    : externalMeetingListFilter === "next"
                      ? "No upcoming external meetings."
                      : "No external meetings yet."}
                </div>
              )}
            </div>
          </div>
        </section>
      ) : null}

      <MeetingDetailsDialog
        meeting={activeMeetingDetails}
        users={users}
        canEdit={activeMeetingDetails ? canManageMeetingParticipants(activeMeetingDetails) : false}
        saving={savingMeetingDetails}
        formatWhen={formatExternalMeetingWhen}
        onClose={closeMeetingDetails}
        onSave={saveMeetingDetails}
      />

      {internalMeetingsOpen ? (
        <section className="meeting-panel internal-meetings-panel">
          <div className="meeting-panel-header">
            <div>
              <div className="meeting-title">Internal Meetings</div>
              <div className="meeting-subtitle">Show all internal meetings and add new ones.</div>
            </div>
            <button className="btn-surface" type="button" onClick={() => setInternalMeetingsOpen(false)}>
              Close
            </button>
          </div>
          <div className="external-meetings-grid">
            <div className="external-meeting-form">
              <div className="external-meeting-form-title">
                {internalMeetingPairExternalId ? "Add linked TAK INT" : "Add meeting"}
              </div>
              {internalMeetingPairExternalId ? (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: "8px",
                    marginBottom: "10px",
                    padding: "8px 10px",
                    border: "1px solid #bfdbfe",
                    borderRadius: "8px",
                    background: "#eff6ff",
                    fontSize: "12px",
                  }}
                >
                  <span>Linked with TAK EXT: {internalMeetingPairExternalTitle}</span>
                  <button
                    className="btn-surface"
                    type="button"
                    onClick={() => {
                      setInternalMeetingPairExternalId(null)
                      setInternalMeetingPairExternalTitle("")
                    }}
                    style={{ padding: "3px 7px", fontSize: "11px" }}
                  >
                    Remove link
                  </button>
                </div>
              ) : null}
              <div className="external-meeting-fields">
                <input
                  className="input"
                  type="text"
                  placeholder="Meeting title"
                  value={internalMeetingTitle}
                  onChange={(e) => setInternalMeetingTitle(e.target.value)}
                />
                <div className="external-meeting-row">
                  <input
                    className="input"
                    type="text"
                    placeholder="Platform (Zoom, Meet, Office...)"
                    value={internalMeetingPlatform}
                    onChange={(e) => setInternalMeetingPlatform(e.target.value)}
                  />
                  <select
                    className="input"
                    value={internalMeetingRecurrenceType}
                    onChange={(e) => setInternalMeetingRecurrenceType(e.target.value as "none" | "weekly" | "monthly" | "yearly")}
                  >
                    <option value="none">One time</option>
                    <option value="weekly">Every week</option>
                    <option value="monthly">Every month</option>
                    <option value="yearly">Every year</option>
                  </select>
                </div>
                <label className="external-meeting-field-stack" style={{ fontSize: "12px", color: "#475569" }}>
                  {internalMeetingRecurrenceType === "none" ? "Date and time" : "Time"}
                  {internalMeetingRecurrenceType === "none" ? (
                    <input
                      className={`input ${internalOneHConflicts.length ? "border-red-500 bg-red-50 text-red-800" : ""}`}
                      type="datetime-local"
                      value={internalMeetingStartsAt}
                      onChange={(e) => setInternalMeetingStartsAt(e.target.value)}
                    />
                  ) : (
                    <input
                      className={`input ${internalOneHConflicts.length ? "border-red-500 bg-red-50 text-red-800" : ""}`}
                      type="time"
                      value={internalMeetingStartTime}
                      onChange={(e) => setInternalMeetingStartTime(e.target.value)}
                    />
                  )}
                </label>
                {checkingInternalMeetingAvailability ? (
                  <div style={{ fontSize: "12px", color: "#64748b" }}>Duke kontrolluar orarin…</div>
                ) : internalOneHConflicts.length ? (
                  <div style={{ border: "1px solid #fecaca", borderRadius: "8px", background: "#fef2f2", color: "#991b1b", padding: "10px", fontSize: "12px" }}>
                    <strong style={{ display: "block" }}>Ky orar përputhet me 1H.</strong>
                    {internalMeetingAvailability?.suggested_slot ? (
                      <button className="btn-surface" type="button" onClick={applyInternalSuggestedSlot} style={{ marginTop: "8px" }}>
                        Përdor orarin e lirë {toLocalTimeInput(internalMeetingAvailability.suggested_slot.starts_at)}
                      </button>
                    ) : null}
                  </div>
                ) : null}
                {internalMeetingRecurrenceType === "weekly" ? (
                  <>
                    <div className="external-meeting-row" style={{ justifyContent: "flex-start" }}>
                      <button
                        className="btn-surface"
                        type="button"
                        onClick={() => setShowInternalWeekendDays((prev) => !prev)}
                        style={{
                          padding: "4px 10px",
                          fontSize: "12px",
                          fontWeight: 600,
                          backgroundColor: showInternalWeekendDays ? "#1d4ed8" : "#eef2ff",
                          borderColor: "#3b82f6",
                          color: showInternalWeekendDays ? "#ffffff" : "#1d4ed8",
                        }}
                      >
                        {showInternalWeekendDays ? "Hide weekend days" : "Show weekend days"}
                      </button>
                    </div>
                    <div className="external-meeting-row" style={{ flexWrap: "wrap", gap: "8px", alignItems: "center" }}>
                      {["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                        .map((day, idx) => ({ day, idx }))
                        .filter(({ idx }) => showInternalWeekendDays || idx < 5)
                        .map(({ day, idx }) => (
                          <label key={day} style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px" }}>
                            <input
                              type="checkbox"
                              checked={internalMeetingRecurrenceDaysOfWeek.includes(idx)}
                              onChange={(e) => {
                                if (e.target.checked) {
                                  setInternalMeetingRecurrenceDaysOfWeek((prev) => [...prev, idx])
                                } else {
                                  setInternalMeetingRecurrenceDaysOfWeek((prev) => prev.filter((d) => d !== idx))
                                }
                              }}
                            />
                            {day}
                          </label>
                        ))}
                    </div>
                  </>
                ) : null}
                {internalMeetingRecurrenceType === "monthly" ? (
                  <div
                    className="external-meeting-row"
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(7, minmax(0, 1fr))",
                      gap: "6px",
                    }}
                  >
                    {Array.from({ length: 31 }, (_, i) => i + 1).map((day) => (
                      <label
                        key={day}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: "6px",
                          fontSize: "12px",
                          padding: "4px 6px",
                          border: "1px solid #e2e8f0",
                          borderRadius: "8px",
                          backgroundColor: internalMeetingRecurrenceDaysOfMonth.includes(day) ? "#eef2ff" : "#ffffff",
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={internalMeetingRecurrenceDaysOfMonth.includes(day)}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setInternalMeetingRecurrenceDaysOfMonth((prev) => [...prev, day])
                            } else {
                              setInternalMeetingRecurrenceDaysOfMonth((prev) => prev.filter((d) => d !== day))
                            }
                          }}
                        />
                        <span style={{ fontVariantNumeric: "tabular-nums" }}>{day}</span>
                      </label>
                    ))}
                  </div>
                ) : null}
                {internalMeetingRecurrenceType === "yearly" ? (
                  <div className="external-meeting-row" style={{ gap: "8px" }}>
                    <select
                      className="input"
                      value={internalMeetingRecurrenceMonth}
                      onChange={(e) => setInternalMeetingRecurrenceMonth(e.target.value)}
                    >
                      {[
                        "January",
                        "February",
                        "March",
                        "April",
                        "May",
                        "June",
                        "July",
                        "August",
                        "September",
                        "October",
                        "November",
                        "December",
                      ].map((label, idx) => (
                        <option key={label} value={String(idx + 1)}>
                          {label}
                        </option>
                      ))}
                    </select>
                    <select
                      className="input"
                      value={internalMeetingRecurrenceDay}
                      onChange={(e) => setInternalMeetingRecurrenceDay(e.target.value)}
                    >
                      {Array.from({ length: 31 }, (_, i) => i + 1).map((day) => (
                        <option key={day} value={String(day)}>
                          {day}
                        </option>
                      ))}
                    </select>
                  </div>
                ) : null}
                <div className="external-meeting-row">
                  <div className="external-meeting-field-stack">
                    <select
                      className="input"
                      value={internalMeetingDepartmentId}
                      onChange={(e) => setInternalMeetingDepartmentId(e.target.value)}
                      disabled={!canSelectExternalDepartment}
                    >
                      {canSelectExternalDepartment ? (
                        <option value="">Select department</option>
                      ) : (
                        <option value="">Department</option>
                      )}
                      {departments.map((dep) => (
                        <option key={dep.id} value={dep.id}>
                          {dep.name === "Project Content Manager" ? "Product Content" : dep.name}
                        </option>
                      ))}
                    </select>
                    {!canSelectExternalDepartment && internalMeetingDepartment ? (
                      <div className="external-meeting-hint">
                        {internalMeetingDepartment.name === "Project Content Manager" ? "Product Content" : internalMeetingDepartment.name}
                      </div>
                    ) : null}
                  </div>
                  <div className="external-person-picker" ref={internalMeetingPersonsRef}>
                    <button
                      className={`external-person-picker-trigger ${internalMeetingPersonsOpen ? "active" : ""}`}
                      type="button"
                      onClick={() => {
                        setInternalMeetingPersonsOpen((current) => {
                          if (current) setInternalMeetingPersonSearch("")
                          return !current
                        })
                      }}
                      aria-haspopup="dialog"
                      aria-expanded={internalMeetingPersonsOpen}
                    >
                      <span>{internalMeetingParticipantIds.length ? "Persons selected" : "Add persons (required)"}</span>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}>
                        {internalMeetingParticipantIds.length ? (
                          <span className="external-person-picker-count">{internalMeetingParticipantIds.length}</span>
                        ) : null}
                        <span aria-hidden="true">{internalMeetingPersonsOpen ? "^" : "v"}</span>
                      </span>
                    </button>
                    {internalMeetingPersonsOpen ? (
                      <div
                        className="external-person-picker-menu"
                        role="dialog"
                        aria-label="Internal meeting persons"
                      >
                        <input
                          className="external-person-picker-search"
                          type="search"
                          value={internalMeetingPersonSearch}
                          onChange={(event) => setInternalMeetingPersonSearch(event.target.value)}
                          placeholder="Search persons..."
                          aria-label="Search internal meeting persons"
                          autoFocus
                        />
                        <div className="external-person-picker-list" role="group">
                          {commonUserFilterOptions
                            .filter(
                              (option) =>
                                option.isActive
                                && option.label.toLowerCase().includes(internalMeetingPersonSearch.trim().toLowerCase())
                            )
                            .map((option) => (
                              <label key={option.id} className="external-person-picker-option">
                                <input
                                  type="checkbox"
                                  checked={internalMeetingParticipantIds.includes(option.id)}
                                  onChange={(event) => {
                                    setInternalMeetingParticipantIds((current) =>
                                      event.target.checked
                                        ? [...current, option.id]
                                        : current.filter((id) => id !== option.id)
                                    )
                                  }}
                                />
                                <span>{option.label}</span>
                              </label>
                            ))}
                          {!commonUserFilterOptions.some(
                            (option) =>
                              option.isActive
                              && option.label.toLowerCase().includes(internalMeetingPersonSearch.trim().toLowerCase())
                          ) ? (
                            <div className="external-person-picker-empty">No persons found</div>
                          ) : null}
                        </div>
                        <div className="external-person-picker-footer">
                          <button
                            className="external-person-picker-done"
                            type="button"
                            onClick={() => {
                              setInternalMeetingPersonsOpen(false)
                              setInternalMeetingPersonSearch("")
                            }}
                          >
                            Done
                          </button>
                        </div>
                      </div>
                    ) : null}
                    {internalMeetingParticipantIds.length ? (
                      <div className="external-person-chips" aria-label="Selected internal meeting persons">
                        {internalMeetingParticipantIds.slice(0, 3).map((id) => {
                          const person = commonUserFilterOptions.find((option) => option.id === id)
                          if (!person) return null
                          return (
                            <button
                              key={person.id}
                              className="external-person-chip"
                              type="button"
                              title={`Remove ${person.label}`}
                              onClick={() => setInternalMeetingParticipantIds((current) => current.filter((itemId) => itemId !== person.id))}
                            >
                              <span>{person.label}</span>
                              <span className="external-person-chip-remove" aria-hidden="true">&times;</span>
                            </button>
                          )
                        })}
                        {internalMeetingParticipantIds.length > 3 ? (
                          <span className="external-person-chip">+{internalMeetingParticipantIds.length - 3}</span>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                </div>
                <div style={{ marginTop: "2px" }}>
                  <button
                    className="btn-primary"
                    type="button"
                    disabled={!canCreateInternalMeeting || creatingInternalMeeting}
                    onClick={() => void submitInternalMeeting()}
                    style={{
                      width: "100%",
                      fontWeight: 600,
                      fontSize: "13px",
                      padding: "8px 12px",
                      backgroundColor: "#2563eb",
                      borderColor: "#1d4ed8",
                      boxShadow: "0 6px 14px rgba(37, 99, 235, 0.25)",
                      color: "#ffffff",
                    }}
                  >
                    {creatingInternalMeeting ? "Saving..." : "Add"}
                  </button>
                </div>
              </div>
            </div>
            <div className="external-meeting-list">
              <div className="external-meeting-list-header">
                <div className="external-meeting-form-title">All internal meetings</div>
                <div className="external-meeting-filter" aria-label="Internal meetings filter">
                  {([
                    ["next", "Next"],
                    ["past", "Past"],
                    ["all", "All"],
                  ] as const).map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      className={internalMeetingListFilter === value ? "active" : ""}
                      onClick={() => setInternalMeetingListFilter(value)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              {internalMeetingsVisible.length ? (
                <div className="external-meeting-cards">
                  {internalMeetingsVisible.map((meeting) => {
                    const department = departments.find((d) => d.id === meeting.department_id) || null
                    const owner = meeting.created_by ? userById.get(meeting.created_by) : null
                    const ownerName = owner?.full_name || owner?.username || "Unknown"
                    const participantNames = (meeting.participant_ids || [])
                      .map((participantId) => {
                        const participant = userById.get(participantId)
                        return participant?.full_name || participant?.username || participant?.email || ""
                      })
                      .filter(Boolean)
                    const isEditing = editingInternalMeetingId === meeting.id
                    return (
                      <div key={meeting.id} className="external-meeting-card">
                        {isEditing ? (
                          <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                            <input
                              className="input"
                              type="text"
                              placeholder="Meeting title"
                              value={editingInternalMeetingTitle}
                              onChange={(e) => setEditingInternalMeetingTitle(e.target.value)}
                            />
                            <div className="external-meeting-row">
                              <input
                                className="input"
                                type="text"
                                placeholder="Platform (Zoom, Meet, Office...)"
                                value={editingInternalMeetingPlatform}
                                onChange={(e) => setEditingInternalMeetingPlatform(e.target.value)}
                              />
                              {editingInternalMeetingRecurrenceType === "none" ? (
                                <input
                                  className="input"
                                  type="datetime-local"
                                  value={editingInternalMeetingStartsAt}
                                  onChange={(e) => setEditingInternalMeetingStartsAt(e.target.value)}
                                />
                              ) : (
                                <input
                                  className="input"
                                  type="time"
                                  value={editingInternalMeetingStartTime}
                                  onChange={(e) => setEditingInternalMeetingStartTime(e.target.value)}
                                />
                              )}
                            </div>
                            <div className="external-meeting-row">
                              <select
                                className="input"
                                value={editingInternalMeetingRecurrenceType}
                                onChange={(e) => setEditingInternalMeetingRecurrenceType(e.target.value as "none" | "weekly" | "monthly" | "yearly")}
                              >
                                <option value="none">One time</option>
                                <option value="weekly">Every week</option>
                                <option value="monthly">Every month</option>
                                <option value="yearly">Every year</option>
                              </select>
                            </div>
                            {editingInternalMeetingRecurrenceType === "weekly" ? (
                              <>
                                <div className="external-meeting-row" style={{ justifyContent: "flex-start" }}>
                                  <button
                                    className="btn-surface"
                                    type="button"
                                    onClick={() => setShowInternalEditWeekendDays((prev) => !prev)}
                                    style={{
                                      padding: "4px 10px",
                                      fontSize: "12px",
                                      fontWeight: 600,
                                      backgroundColor: showInternalEditWeekendDays ? "#1d4ed8" : "#eef2ff",
                                      borderColor: "#3b82f6",
                                      color: showInternalEditWeekendDays ? "#ffffff" : "#1d4ed8",
                                    }}
                                  >
                                    {showInternalEditWeekendDays ? "Hide weekend days" : "Show weekend days"}
                                  </button>
                                </div>
                                <div className="external-meeting-row" style={{ flexWrap: "wrap", gap: "8px", alignItems: "center" }}>
                                  {["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                                    .map((day, idx) => ({ day, idx }))
                                    .filter(({ idx }) => showInternalEditWeekendDays || idx < 5)
                                    .map(({ day, idx }) => (
                                      <label key={day} style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px" }}>
                                        <input
                                          type="checkbox"
                                          checked={editingInternalMeetingRecurrenceDaysOfWeek.includes(idx)}
                                          onChange={(e) => {
                                            if (e.target.checked) {
                                              setEditingInternalMeetingRecurrenceDaysOfWeek((prev) => [...prev, idx])
                                            } else {
                                              setEditingInternalMeetingRecurrenceDaysOfWeek((prev) => prev.filter((d) => d !== idx))
                                            }
                                          }}
                                        />
                                        {day}
                                      </label>
                                    ))}
                                </div>
                              </>
                            ) : null}
                            {editingInternalMeetingRecurrenceType === "monthly" ? (
                              <div
                                className="external-meeting-row"
                                style={{
                                  display: "grid",
                                  gridTemplateColumns: "repeat(7, minmax(0, 1fr))",
                                  gap: "6px",
                                }}
                              >
                                {Array.from({ length: 31 }, (_, i) => i + 1).map((day) => (
                                  <label
                                    key={day}
                                    style={{
                                      display: "flex",
                                      alignItems: "center",
                                      gap: "6px",
                                      fontSize: "12px",
                                      padding: "4px 6px",
                                      border: "1px solid #e2e8f0",
                                      borderRadius: "8px",
                                      backgroundColor: editingInternalMeetingRecurrenceDaysOfMonth.includes(day) ? "#eef2ff" : "#ffffff",
                                    }}
                                  >
                                    <input
                                      type="checkbox"
                                      checked={editingInternalMeetingRecurrenceDaysOfMonth.includes(day)}
                                      onChange={(e) => {
                                        if (e.target.checked) {
                                          setEditingInternalMeetingRecurrenceDaysOfMonth((prev) => [...prev, day])
                                        } else {
                                          setEditingInternalMeetingRecurrenceDaysOfMonth((prev) => prev.filter((d) => d !== day))
                                        }
                                      }}
                                    />
                                    <span style={{ fontVariantNumeric: "tabular-nums" }}>{day}</span>
                                  </label>
                                ))}
                              </div>
                            ) : null}
                            {editingInternalMeetingRecurrenceType === "yearly" ? (
                              <div className="external-meeting-row" style={{ gap: "8px" }}>
                                <select
                                  className="input"
                                  value={editingInternalMeetingRecurrenceMonth}
                                  onChange={(e) => setEditingInternalMeetingRecurrenceMonth(e.target.value)}
                                >
                                  {[
                                    "January",
                                    "February",
                                    "March",
                                    "April",
                                    "May",
                                    "June",
                                    "July",
                                    "August",
                                    "September",
                                    "October",
                                    "November",
                                    "December",
                                  ].map((label, idx) => (
                                    <option key={label} value={String(idx + 1)}>
                                      {label}
                                    </option>
                                  ))}
                                </select>
                                <select
                                  className="input"
                                  value={editingInternalMeetingRecurrenceDay}
                                  onChange={(e) => setEditingInternalMeetingRecurrenceDay(e.target.value)}
                                >
                                  {Array.from({ length: 31 }, (_, i) => i + 1).map((day) => (
                                    <option key={day} value={String(day)}>
                                      {day}
                                    </option>
                                  ))}
                                </select>
                              </div>
                            ) : null}
                            <div className="external-meeting-row">
                              <select
                                className="input"
                                value={editingInternalMeetingDepartmentId}
                                onChange={(e) => setEditingInternalMeetingDepartmentId(e.target.value)}
                              >
                                <option value="">Select department</option>
                                {departments.map((dep) => (
                                  <option key={dep.id} value={dep.id}>
                                    {dep.name}
                                  </option>
                                ))}
                              </select>
                            </div>
                            <div style={{ display: "flex", gap: "8px" }}>
                              <button
                                className="btn-surface"
                                type="button"
                                onClick={() => void saveInternalMeeting()}
                                disabled={updatingInternalMeeting || !editingInternalMeetingTitle.trim()}
                                style={{ flex: 1 }}
                              >
                                {updatingInternalMeeting ? "Saving..." : "Save"}
                              </button>
                              <button
                                className="btn-surface"
                                type="button"
                                onClick={cancelEditInternalMeeting}
                                disabled={updatingInternalMeeting}
                              >
                                Cancel
                              </button>
                            </div>
                          </div>
                        ) : (
                          <>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                              <div style={{ flex: 1 }}>
                                <div className="external-meeting-title">{meeting.title || "Internal meeting"}</div>
                                <div className="external-meeting-meta">
                                  <span>{formatExternalMeetingWhen(meeting)}</span>
                                  <span>{meeting.platform || "-"}</span>
                                </div>
                                <div className="external-meeting-meta">
                                  <span>{department?.name || "Department TBD"}</span>
                                  <span>Owner: {ownerName}</span>
                                </div>
                                {participantNames.length ? (
                                  <div className="external-meeting-person-summary" aria-label="Meeting persons">
                                    <span className="external-meeting-person-count">
                                      {participantNames.length} {participantNames.length === 1 ? "person" : "persons"}
                                    </span>
                                    <span className="external-meeting-person-names" title={participantNames.join(", ")}>
                                      {participantNames.join(", ")}
                                    </span>
                                  </div>
                                ) : null}
                                <div className="external-meeting-meta" style={{ marginTop: "8px" }}>
                                  <span>Status: {renderMeetingStatusControl(meeting)}</span>
                                </div>
                              </div>
                              <div style={{ display: "flex", gap: "6px", marginLeft: "12px", flexWrap: "wrap", justifyContent: "flex-end" }}>
                                  <button
                                    className="btn-surface"
                                    type="button"
                                    onClick={() => openMeetingDetails(meeting)}
                                    title="View meeting details and assign PrimeFlow participants"
                                    style={{ borderColor: "#93c5fd", color: "#1d4ed8" }}
                                  >
                                    Participants &amp; reminder
                                  </button>
                                {canEditInternalMeeting(meeting) ? (
                                  <>
                                  <button
                                    className="btn-surface"
                                    type="button"
                                    onClick={() => startEditInternalMeeting(meeting)}
                                    disabled={deletingInternalMeetingId === meeting.id || updatingInternalMeeting}
                                    title="Edit meeting"
                                  >
                                    Edit
                                  </button>
                                  {isAdmin ? (
                                    <button
                                      className="btn-surface"
                                      type="button"
                                      onClick={() => void deleteInternalMeeting(meeting.id)}
                                      disabled={deletingInternalMeetingId === meeting.id || updatingInternalMeeting}
                                      title="Delete meeting"
                                      style={{ color: "#dc2626", borderColor: "#fecaca" }}
                                    >
                                      {deletingInternalMeetingId === meeting.id ? "Deleting..." : "Delete"}
                                    </button>
                                  ) : null}
                                  </>
                                ) : null}
                              </div>
                            </div>
                          </>
                        )}
                      </div>
                    )
                  })}
                </div>
              ) : (
                <div className="external-meeting-empty">
                  {internalMeetingListFilter === "past"
                    ? "No past internal meetings."
                    : internalMeetingListFilter === "next"
                      ? "No upcoming internal meetings."
                      : "No internal meetings yet."}
                </div>
              )}
            </div>
          </div>
        </section>
      ) : null}

      <div className="view-container" aria-busy={!dataLoaded}>
        <div className="common-view-title">PERMBLEDHJA - COMMON VIEW</div>
        {!dataLoaded ? (
          <div className="common-view-loading no-print" role="status" aria-live="polite">
            <span className="common-view-loading-spinner" aria-hidden="true" />
            <span>Loading tasks...</span>
          </div>
        ) : null}
        {allDaysSelected ? (
          <div className="week-table-view week-table-onepage neutral-all-days" ref={weekTablePrintRef}>
            <div className="week-table-onepage-content" ref={weekTablePrintContentRef}>
            <div className="print-header">
              <div />
              <div className="print-title">COMMON VIEW - WEEK PLAN</div>
              <div className="print-datetime">
                {formatDateTimeDMY(printedAt)}
              </div>
            </div>
            <table className="week-table">
              <thead>
                <tr>
                  <th rowSpan={2} style={{ width: "40px" }}>NR</th>
                  <th rowSpan={2} style={{ width: "86px" }}>LLOJI</th>
                  {weekISOs.map((iso) => {
                    const d = fromISODate(iso)
                    const dayCode = getDayCode(d)
                    return (
                      <th key={iso} colSpan={1} className="week-table-date-header">
                        <div>{dayCode} = {formatDateHuman(iso)}</div>
                      </th>
                    )
                  })}
                </tr>
                <tr>
                  {weekISOs.map((iso) => (
                    <th key={`sub-${iso}`} className="week-table-subheader">
                      KUSH/BZ ME/DET/SI/KUR/KUJT
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {orderCommonRowsForPrint(swimlaneRows.filter((row) => showCard(row.id, row.items.length)))
                  .map((row, rowIndex) => {
                    const includeOneH = typeFilters.size === 0 || typeFilters.has("oneH")
                    const includeR1 = typeFilters.size === 0 || typeFilters.has("r1")
                    const dayEntries: Record<string, CommonWeekTableEntry[]> = {}
                    weekISOs.forEach((iso) => {
                      const dayData = tableDataByDay?.[iso]
                      if (row.id === "late") dayEntries[iso] = dayData?.late || []
                      else if (row.id === "absent") dayEntries[iso] = dayData?.absent || []
                      else if (row.id === "leave") dayEntries[iso] = dayData?.leave || []
                      else if (row.id === "externalHoliday") dayEntries[iso] = dayData?.externalHoliday || []
                      else if (row.id === "waitingClient") dayEntries[iso] = mergePrintTaskEntries(row.id, dayData?.waitingClient || [])
                      else if (row.id === "blocked") dayEntries[iso] = mergePrintTaskEntries(row.id, dayData?.blocked || [])
                      else if (isOneHSlotRowId(row.id)) {
                        const oneHEntries = includeOneH ? dayData?.oneH || [] : []
                        const slot = getOneHSlotRowSlot(row.id)
                        const slotEntries = slot === undefined
                          ? oneHEntries
                          : oneHEntries.filter((entry) =>
                              slot === null
                                ? !normalizeOneHReportSlot((entry as OneHItem).oneHReportSlot)
                                : normalizeOneHReportSlot((entry as OneHItem).oneHReportSlot) === slot
                            )
                        dayEntries[iso] = mergePrintTaskEntries(row.id, slotEntries)
                      }
                      else if (row.id === "r1") dayEntries[iso] = includeR1 ? mergePrintTaskEntries(row.id, dayData?.r1 || []) : []
                      else if (isPersonalRowId(row.id)) {
                        dayEntries[iso] = mergePrintTaskEntries(
                          row.id,
                          personalTasksForRow(dayData?.personal || [], row.id)
                        )
                      }
                      else if (row.id === "external") dayEntries[iso] = dayData?.external || []
                      else if (row.id === "internal") dayEntries[iso] = dayData?.internal || []
                      else if (row.id === "bz") dayEntries[iso] = dayData?.bz || []
                      else if (row.id === "problem") dayEntries[iso] = dayData?.problems || []
                      else if (row.id === "feedback") dayEntries[iso] = dayData?.feedback || []
                      else if (row.id === "priority") dayEntries[iso] = dayData?.priority || []
                      else if (row.id === "diamond") dayEntries[iso] = dayData?.diamond || []
                    })
                    const repeatedTaskFirstDateById = buildRepeatedTaskFirstDateMap(
                      weekISOs,
                      (dateIso) =>
                        (dayEntries[dateIso] || []) as { taskId?: string | null; task_id?: string | null }[]
                    )
                    const repeatedTaskClassName = (entry: { taskId?: string | null; task_id?: string | null }, dateIso: string) =>
                      isRepeatedTaskInstance(entry, dateIso, repeatedTaskFirstDateById) ? "repeat-task-muted" : ""

                    const getWeekRowClass = (rowId: string) => {
                      if (rowId === "late") return "delay"
                      if (rowId === "absent") return "absence"
                      if (rowId === "leave") return "leave"
                      if (rowId === "externalHoliday") return "externalHoliday"
                      if (rowId === "waitingClient") return "waiting-client"
                      if (rowId === "blocked") return "blocked"
                      if (isOneHSlotRowId(rowId as CommonType)) return "oneh"
                      if (isPersonalRowId(rowId as CommonType)) return "personal"
                      if (rowId === "external") return "external"
                      if (rowId === "internal") return "internal"
                      if (rowId === "bz") return "bz"
                      if (rowId === "r1") return "r1"
                      if (rowId === "problem") return "problem"
                      if (rowId === "feedback") return "feedback"
                      if (rowId === "priority") return "priority"
                      if (rowId === "diamond") return "diamond"
                      return ""
                    }
                    const weekRowClass = getWeekRowClass(row.id)

                    const getCellContent = (iso: string) => {
                      const entries = dayEntries[iso] || []
                      if (entries.length === 0) return null
                      
                      if (row.id === "late") {
        return (entries as LateItem[]).map((e, idx: number) => (
          <div key={idx} className="week-table-entry">
            <span>{idx + 1}. {e.start || "08:00"}-{e.until}</span>
            <div className="week-table-avatars">
              {entryAssignees(e).map((name: string) => (
                <span key={`${e.start}-${name}`} className="week-table-avatar" title={name}>
                  {initials(name)}
                </span>
              ))}
            </div>
            {canDeleteCommon && e.entryId ? (
              <button
                type="button"
                className="week-table-delete week-table-delete-red"
                onClick={() => deleteCommonEntry(e.entryId!)}
                aria-label="Delete entry"
                title="Delete"
              >
                ×
              </button>
            ) : null}
          </div>
        ))
                      } else if (row.id === "absent") {
                        return (entries as AbsentItem[]).map((e, idx: number) => (
                          <div key={idx} className="week-table-entry">
                            <span>{idx + 1}. {e.from} - {e.to}</span>
                            <div className="week-table-avatars">
                              {entryAssignees(e).map((name: string) => (
                                <span key={`${e.from}-${name}`} className="week-table-avatar" title={name}>
                                  {initials(name)}
                                </span>
                              ))}
                            </div>
                            {canDeleteCommon && e.entryId ? (
                              <button
                                type="button"
                                className="week-table-delete week-table-delete-red"
                                onClick={() => deleteCommonEntry(e.entryId!)}
                                aria-label="Delete entry"
                                title="Delete"
                              >
                                ×
                              </button>
                            ) : null}
                          </div>
                        ))
                      } else if (row.id === "leave") {
                        return (entries as LeaveItem[]).map((e, idx: number) => {
                          const range = "" // hide date in table view
                          const isAllUsers = Boolean(e.isAllUsers || e.person === ALL_USERS_INITIALS)
                          const timeLabel = e.fullDay ? "08:00-16:30" : `${e.from}-${e.to}`
                          const noteLabel = e.note ? ` - ${e.note}` : ""
                          return (
                            <div key={idx} className="week-table-entry">
                              <span>
                                {idx + 1}. {isAllUsers ? `${timeLabel} ALL` : timeLabel}
                                {range ? ` ${range}` : ""}
                                {noteLabel}
                              </span>
                              {!isAllUsers ? (
                                <div className="week-table-avatars">
                                  {entryAssignees(e).map((name: string) => (
                                    <span key={`${e.from}-${name}`} className="week-table-avatar" title={name}>
                                      {initials(name)}
                                    </span>
                                  ))}
                                </div>
                              ) : null}
                              {canDeleteCommon && e.entryId ? (
                                <button
                                  type="button"
                                  className="week-table-delete week-table-delete-red"
                                  onClick={() => deleteCommonEntry(e.entryId!)}
                                  aria-label="Delete entry"
                                  title="Delete"
                                >
                                  ×
                                </button>
                              ) : null}
                              {isAdmin && e.isAllUsers ? (
                                <button
                                  type="button"
                                  className="week-table-delete week-table-delete-red"
                                  onClick={() => deleteAllUsersLeaveForDay(e.startDate)}
                                  aria-label="Delete all-users entries"
                                  title="Delete all users"
                                >
                                  ×
                                </button>
                              ) : null}
                            </div>
                          )
                        })
                      } else if (row.id === "externalHoliday") {
                        return (entries as ExternalHolidayItem[]).map((e, idx: number) => (
                          <div key={idx} className="week-table-entry">
                            <span>{idx + 1}. {e.title}{e.note ? ` - ${e.note}` : ""}</span>
                            {canDeleteCommon && e.entryId ? (
                              <button
                                type="button"
                                className="week-table-delete week-table-delete-red"
                                onClick={() => deleteCommonEntry(e.entryId!)}
                                aria-label="Delete entry"
                                title="Delete"
                              >
                                ×
                              </button>
                            ) : null}
                          </div>
                        ))
                      } else if (row.id === "blocked") {
                        return (entries as BlockedItem[]).map((e, idx: number) => (
                          <div
                            key={idx}
                            className={[
                              "week-table-entry",
                              commonTaskStateClassName(e.status, e.isDone),
                              commonTaskHighlightClassName(e),
                              hasEightAmIndicator(e.title, e.isSystemTask) ? "eight-am-task" : "",
                              repeatedTaskClassName(e, iso),
                            ].filter(Boolean).join(" ")}
                          >
                            <div className="week-table-entry-main">
                                  <span>
                                  <span className="week-table-line-number">{idx + 1}.</span>
                                  {isOneHSlotRowId(row.id) || row.id === "r1" ? (
                                    <span className="oneh-slot-indicator">{getOneHReportSlotLabel((e as OneHItem | R1Item).oneHReportSlot)}</span>
                                  ) : null}
                                  <span className="period-indicator">{getCommonTaskPeriodLabel(e.finishPeriod)}</span>
                                  {renderWfcIndicator(e)}
                                  {renderOneHMarkerControl(e)}
                                  {hasEightAmIndicator(e.title, e.isSystemTask) ? (
                                    <span className="time-indicator">08:00</span>
                                  ) : null}
                                  {renderCommonTaskStatusIndicator(e)}
                                  <span className="inline-flex min-w-0 flex-col align-middle"><TaskMarkerComment comment={e.oneHMarkerComment} taskId={e.taskId} />{renderWfcText(commonPrintTaskTitle(e))}</span>
                                </span>
                              </div>
                            <div className="week-table-avatars">
                              {entryAssignees(e).map((name: string) => (
                                <span key={`${e.title}-${name}`} className="week-table-avatar" title={name}>
                                  {initials(name)}
                                </span>
                              ))}
                            </div>
                          </div>
                        ))
                      } else if (row.id === "problem" || row.id === "feedback") {
                        return (entries as (ProblemItem | FeedbackItem)[]).map((e, idx: number) => (
                          <div key={idx} className="week-table-entry">
                            <span className={row.id === "feedback" ? "feedback-print-clamp" : undefined}>
                              {idx + 1}. {e.title}
                              {` - ${e.createdDate ? formatDateHuman(e.createdDate) : formatDateHuman(e.date)}`}
                              {e.note ? ` - ${e.note}` : ""}
                            </span>
                            <div className="week-table-avatars">
                              {entryAssignees(e).map((name: string) => (
                                <span key={`${e.title}-${name}`} className="week-table-avatar" title={name}>
                                  {initials(name)}
                                </span>
                              ))}
                            </div>
                            {canDeleteCommon && e.entryId ? (
                              <button
                                type="button"
                                className="week-table-delete week-table-delete-red"
                                onClick={() => deleteCommonEntry(e.entryId!)}
                                aria-label="Delete entry"
                                title="Delete"
                              >
                                ×
                              </button>
                            ) : null}
                          </div>
                        ))
                      } else if (isOneHSlotRowId(row.id) || row.id === "r1" || row.id === "waitingClient") {
                        return (entries as FastTaskEntry[]).map((e, idx: number) => (
                          <div
                            key={idx}
                            className={[
                              "week-table-entry",
                              commonTaskStateClassName(e.status, e.isDone),
                              commonTaskHighlightClassName(e),
                              hasEightAmIndicator(e.title, e.isSystemTask) ? "eight-am-task" : "",
                              repeatedTaskClassName(e, iso),
                            ].filter(Boolean).join(" ")}
                          >
                            <div className="week-table-entry-main">
                                  <span>
                                  <span className="week-table-line-number">{idx + 1}.</span>
                                  {(row.id !== "waitingClient" || e.oneHReportSlot) ? (
                                    <span className="oneh-slot-indicator">{getOneHReportSlotLabel(e.oneHReportSlot)}</span>
                                  ) : null}
                                  <span className="period-indicator">{getCommonTaskPeriodLabel(e.finishPeriod)}</span>
                                  {renderWfcIndicator(e)}
                                  {isShtypiTaskRowId(row.id) ? renderOneHMarkerControl(e) : null}
                                  {hasEightAmIndicator(e.title, e.isSystemTask) ? (
                                    <span className="time-indicator">08:00</span>
                                  ) : null}
                                  {renderCommonTaskStatusIndicator(e)}
                                  <span className="inline-flex min-w-0 flex-col align-middle"><TaskMarkerComment comment={e.oneHMarkerComment} taskId={e.taskId} />{renderWfcText(commonPrintTitleLine(e.title))}</span>
                                </span>
                              </div>
                            <div className="week-table-avatars">
                              {entryAssignees(e).map((name: string) => (
                                <span key={`${e.title}-${name}`} className="week-table-avatar" title={name}>
                                  {initials(name)}
                                </span>
                              ))}
                            </div>
                          </div>
                        ))
                      } else if (isPersonalRowId(row.id)) {
                        return (entries as PersonalItem[]).map((e, idx: number) => (
                          <div
                            key={idx}
                            className={[
                              "week-table-entry",
                              commonTaskStateClassName(e.status, e.isDone),
                              commonTaskHighlightClassName(e),
                              hasEightAmIndicator(e.title, e.isSystemTask) ? "eight-am-task" : "",
                              repeatedTaskClassName(e, iso),
                              row.id === "personalGA" ? "personal-ga-task" : "",
                            ].filter(Boolean).join(" ")}
                          >
                            <div className="week-table-entry-main">
                                  <span>
                                  <span className="week-table-line-number">{idx + 1}.</span>
                                  <span className="period-indicator">{getCommonTaskPeriodLabel(e.finishPeriod)}</span>
                                  {renderWfcIndicator(e)}
                                  {renderOneHMarkerControl(e)}
                                  {hasEightAmIndicator(e.title, e.isSystemTask) ? (
                                    <span className="time-indicator">08:00</span>
                                  ) : null}
                                  {renderCommonTaskStatusIndicator(e, true)}
                                  <span className="inline-flex min-w-0 flex-col align-middle"><TaskMarkerComment comment={e.oneHMarkerComment} taskId={e.taskId} />{renderWfcText(commonPrintPersonalTaskTitle(e))}</span>
                                </span>
                              </div>
                            <div className="week-table-avatars">
                              {entryAssignees(e).map((name: string) => (
                                <span key={`${e.title}-${name}`} className="week-table-avatar" title={name}>
                                  {initials(name)}
                                </span>
                              ))}
                            </div>
                          </div>
                        ))
                      } else if (row.id === "external") {
                        return (entries as ExternalItem[]).map((e, idx: number) => (
                          <div
                            key={idx}
                            className={[
                              "week-table-entry",
                              meetingLegendTone({
                                categories: e.calendarCategories,
                                recurrenceType: e.recurrenceType ?? e.recurrence_type,
                                meetingType: "external",
                                calendarImported: e.calendarImported,
                              }),
                              isOneTimeMeeting(e.recurrenceType ?? e.recurrence_type) ? "one-time-meeting" : "",
                            ]
                              .filter(Boolean)
                              .join(" ")}
                          >
                            <div className="week-table-meeting-main">
                              <span className="meeting-origin-row">
                                {formatTimeLabel(e.time) ? (
                                  <span className="meeting-time-chip">{formatTimeLabel(e.time)}</span>
                                ) : null}
                                {e.calendarImported ? (
                                  <span className="calendar-meeting-badge">CAL</span>
                                ) : null}
                              </span>
                              <span className="week-table-meeting-title">
                                <span className="week-table-line-number">{idx + 1}.</span>{" "}
                                {commonPrintTitleLine(e.title)}
                              </span>
                            </div>
                            {!e.calendarImported ? (
                              <div className="week-table-avatars">
                                {entryAssignees(e).map((name: string) => (
                                  <span key={`${e.title}-${name}`} className="week-table-avatar" title={name}>
                                    {initials(name)}
                                  </span>
                                ))}
                              </div>
                            ) : null}
                          </div>
                        ))
                      } else if (row.id === "internal") {
                        return (entries as InternalItem[]).map((e, idx: number) => (
                          <div
                            key={idx}
                            className={[
                              "week-table-entry",
                              internalMeetingLegendTone(e),
                              isCalendarLinkedInternalMeeting(e) ? "calendar-internal-muted" : "",
                              isManualInternalMeeting(e) ? "manual-internal-meeting" : "",
                              isOneTimeMeeting(e.recurrenceType ?? e.recurrence_type) ? "one-time-meeting" : "",
                            ]
                              .filter(Boolean)
                              .join(" ")}
                          >
                            <div className="week-table-meeting-main">
                              <span className="meeting-origin-row">
                                {formatTimeLabel(e.time) ? (
                                  <span className="meeting-time-chip">{formatTimeLabel(e.time)}</span>
                                ) : null}
                                {isManualInternalMeeting(e) ? (
                                  <span className="manual-meeting-badge">MANUAL</span>
                                ) : null}
                                {isCalendarLinkedInternalMeeting(e) ? (
                                  <span className="calendar-meeting-badge">CAL</span>
                                ) : null}
                              </span>
                              <span className="week-table-meeting-title">
                                <span className="week-table-line-number">{idx + 1}.</span>{" "}
                                {internalMeetingRelation(e) ? (
                                  <span className="meeting-relation-badge" title={`${internalMeetingRelation(e) === "PARA" ? "Para" : "Pas"} takimit extern`}>
                                    {internalMeetingRelation(e)}
                                  </span>
                                ) : null}
                                {commonPrintTitleLine(e.title)}
                              </span>
                            </div>
                            {!isCalendarLinkedInternalMeeting(e) ? (
                              <div className="week-table-avatars">
                                {entryAssignees(e).map((name: string) => (
                                  <span key={`${e.title}-${name}`} className="week-table-avatar" title={name}>
                                    {initials(name)}
                                  </span>
                                ))}
                              </div>
                            ) : null}
                          </div>
                        ))
                      } else if (row.id === "bz") {
                        return (entries as BzItem[]).map((e, idx: number) => (
                          <div
                            key={idx}
                            className={[
                              "week-table-entry",
                              repeatedTaskClassName(e, iso),
                            ].filter(Boolean).join(" ")}
                          >
                            <span>
                              {idx + 1}. {commonPrintTitleLine(`${formatTimeLabel(e.time)} ${e.title}`.trim())}
                              {e.bzWithLabel ? ` - BZ: ${e.bzWithLabel}` : ""}
                            </span>
                            {e.assignees && e.assignees.length ? (
                              <div className="week-table-avatars">
                                {e.assignees.map((name: string) => (
                                  <span key={`${e.title}-${name}`} className="week-table-avatar" title={name}>
                                    {initials(name)}
                                  </span>
                                ))}
                              </div>
                            ) : null}
                          </div>
                        ))
                      } else if (row.id === "priority") {
                        const groupMap = new Map<string, PriorityItem[]>()
                        for (const item of entries as PriorityItem[]) {
                          const departmentName = item.department_name || "Other"
                          const existing = groupMap.get(departmentName) || []
                          existing.push(item)
                          groupMap.set(departmentName, existing)
                        }
                        const preferredOrder = ["DEVELOPMENT", "GRAPHIC DESIGN", "PRODUCT CONTENT"]
                        const orderIndex = new Map(preferredOrder.map((name, idx) => [name, idx]))
                        const normalizeDept = (value: string) => value.trim().toUpperCase()
                        const isOther = (value: string) => normalizeDept(value) === "OTHER"
                        const groupKeys = Array.from(groupMap.keys()).sort((a, b) => {
                          const aKey = normalizeDept(a)
                          const bKey = normalizeDept(b)
                          const aIdx = orderIndex.get(aKey)
                          const bIdx = orderIndex.get(bKey)
                          if (aIdx != null && bIdx != null) return aIdx - bIdx
                          if (aIdx != null) return -1
                          if (bIdx != null) return 1
                          if (isOther(a) && !isOther(b)) return 1
                          if (!isOther(a) && isOther(b)) return -1
                          return a.localeCompare(b)
                        })
                        let entryIndex = 0
                        return groupKeys.map((departmentName, groupIdx) => (
                          <React.Fragment key={departmentName}>
                            {(groupMap.get(departmentName) || []).map((e, idx) => (
                              <div key={`${departmentName}-${idx}`} className="week-table-entry">
                                <span>{++entryIndex}. {e.project}</span>
                                <div className="week-table-avatars">
                                  {e.assignees.map((name) => (
                                    <span key={`${e.project}-${name}`} className="week-table-avatar" title={name}>
                                      {initials(name)}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            ))}
                            {groupIdx < groupKeys.length - 1 ? (
                              <div className="week-table-prjk-divider" />
                            ) : null}
                          </React.Fragment>
                        ))
                      } else if (row.id === "diamond") {
                        return (entries as DiamondItem[]).map((entry, idx) => (
                          <div key={entry.reviewId} className="week-table-entry diamond-entry">
                            <div className="week-table-entry-main">
                              <span>
                                <span className="week-table-line-number">{idx + 1}.</span>
                                <span className="diamond-mark">
                                  <DiamondAward compact />
                                </span>
                                <strong>{entry.person}</strong> — {entry.taskTitle}
                              </span>
                            </div>
                          </div>
                        ))
                      }
                      return null
                    }

                    const getFeedbackWeekSummary = () => {
                      const seen = new Set<string>()
                      const items: Array<{ entry: FeedbackItem; iso: string }> = []
                      weekISOs.forEach((iso) => {
                        const feedbackEntries = (dayEntries[iso] || []) as FeedbackItem[]
                        feedbackEntries.forEach((entry) => {
                          const key = entry.everyday
                            ? entry.entryId || `${normalizeTitle(entry.title)}|${normalizeTitle(entry.note || "")}|${entry.person}`
                            : `${iso}|${entry.entryId || normalizeTitle(entry.title)}|${normalizeTitle(entry.note || "")}|${entry.person}`
                          if (seen.has(key)) return
                          seen.add(key)
                          items.push({ entry, iso })
                        })
                      })
                      return items
                    }

                    const rowLabel = row.label.toUpperCase()
                    const rowSubtext = getCommonPrintRowSubtext(row.id)
                    if (row.id === "feedback") {
                      const feedbackSummary = getFeedbackWeekSummary()
                      return (
                        <tr key={row.id} className={`week-table-row ${weekRowClass} week-table-row-merged`}>
                          <td className="week-table-number">{rowIndex + 1}</td>
                          <td className="week-table-label">
                            <span>{rowLabel}</span>
                            {rowSubtext ? <span className="week-table-label-subtext">{rowSubtext}</span> : null}
                          </td>
                          <td colSpan={weekISOs.length} className="week-table-cell week-table-merged-cell">
                            {feedbackSummary.length ? (
                              <div className="week-table-entries week-table-feedback-summary">
                                {feedbackSummary.map(({ entry, iso }, idx) => {
                                  const dateLabel = entry.everyday
                                    ? "All week"
                                    : `${getDayCode(fromISODate(iso))} ${formatDateHuman(iso)}`
                                  return (
                                    <div key={`${entry.entryId || entry.title}-${iso}-${idx}`} className="week-table-entry">
                                      <span className="feedback-print-summary-line">
                                        {idx + 1}. {commonPrintTitleLine(entry.title)}
                                        <span className="feedback-print-date"> - {dateLabel}</span>
                                        {entry.note ? ` - ${commonPrintTitleLine(entry.note)}` : ""}
                                      </span>
                                      <div className="week-table-avatars">
                                        {entryAssignees(entry).map((name: string) => (
                                          <span key={`${entry.title}-${name}`} className="week-table-avatar" title={name}>
                                            {initials(name)}
                                          </span>
                                        ))}
                                      </div>
                                      {canDeleteCommon && entry.entryId ? (
                                        <button
                                          type="button"
                                          className="week-table-delete week-table-delete-red"
                                          onClick={() => deleteCommonEntry(entry.entryId!)}
                                          aria-label="Delete entry"
                                          title="Delete"
                                        >
                                          Ã—
                                        </button>
                                      ) : null}
                                    </div>
                                  )
                                })}
                              </div>
                            ) : (
                              <span className="week-table-empty">â€”</span>
                            )}
                          </td>
                        </tr>
                      )
                    }
                    
                    return (
                      <tr key={row.id} className={`week-table-row ${weekRowClass}`}>
                        <td className="week-table-number">{rowIndex + 1}</td>
                        <td className="week-table-label">
                          <span>{rowLabel}</span>
                          {rowSubtext ? <span className="week-table-label-subtext">{rowSubtext}</span> : null}
                        </td>
                        {weekISOs.map((iso) => {
                          const content = getCellContent(iso)
                          return (
                            <td key={iso} className="week-table-cell">
                              {content ? (
                                <div className="week-table-entries">
                                  {content}
                                </div>
                              ) : (
                                <span className="week-table-empty">—</span>
                              )}
                            </td>
                          )
                        })}
                      </tr>
                    )
                  })}
              </tbody>
            </table>
            </div>
            <div className="print-footer">
              <span />
              <div className="print-page-count">1/{printTotalPages}</div>
              <div className="print-initials">PUNOI: {printInitials}</div>
            </div>
          </div>
        ) : null}
        <div
          ref={singleDayPrintRef}
          className={`print-page single-day-print ${allDaysSelected ? "hide-when-all-days" : ""}`}
        >
          <div ref={singleDayPrintContentRef} className="single-day-print-content">
            <div className="print-header">
              <div />
              <div className="print-title">1H SHTYPI</div>
              <div className="print-datetime">
                {formatDateTimeDMY(printedAt)}
              </div>
            </div>
            <OneHPrintChecklists reportDay={new Date(`${calendarDateIso}T12:00:00`)} />
            <OneHMarkerLegend />
            <table className="single-day-print-table">
              <colgroup>
                <col className="single-day-print-number-column" />
                <col className="single-day-print-label-column" />
                <col span={6} />
              </colgroup>
              <thead>
                <tr>
                  <th scope="col">NR</th>
                  <th scope="col">LLoji dhe sloti</th>
                  <th scope="col" colSpan={6}>Tasks</th>
                </tr>
              </thead>
              <tbody>
                {renderSingleDayPrintRows(COMMON_FAST_PRINT_ROW_IDS)}
              </tbody>
            </table>
            <table className="single-day-print-table single-day-print-meetings-table">
              <colgroup>
                <col className="single-day-print-number-column" />
                <col className="single-day-print-label-column" />
                <col span={6} />
              </colgroup>
              <thead>
                <tr>
                  <th scope="col">NR</th>
                  <th scope="col">LLoji</th>
                  <th scope="col" colSpan={6}>Meeting</th>
                </tr>
              </thead>
              <tbody>{renderSingleDayPrintRows(COMMON_MEETING_PRINT_ROW_IDS)}</tbody>
            </table>
          </div>
          <div className={`swimlane-board ${allDaysSelected ? "hide-when-all-days" : ""}`}>
            {swimlaneRows
              .filter((row) => showCard(row.id, row.items.length))
              .map((row, rowIndex) => {
                const cells = buildSwimlaneCells(row.items, swimlaneColumnCount)
                const hasSubtext = Boolean(swimlaneHeaderSubtext[row.id])
                return (
                  <div
                    key={row.id}
                    className={[
                      "swimlane-row",
                      `swimlane-row-${row.id}`,
                      hasSubtext ? "swimlane-row-subtext" : "",
                    ].filter(Boolean).join(" ")}
                  >
                    <div className="swimlane-index-col">
                      <span className="swimlane-index">{rowIndex + 1}</span>
                    </div>
                    <div
                      className={[
                        row.headerClass,
                        hasSubtext ? "swimlane-header-with-subtext" : "",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                    >
                      {(() => {
                        const headerSubtext = swimlaneHeaderSubtext[row.id]
                        const hasTitleToggle = TITLE_EXPANDABLE_SWIMLANE_ROWS.includes(row.id)
                        const isTitleRowOpen = openSwimlaneTitleRows.has(row.id)
                        const infoButton = (
                          <span className="swimlane-info-wrap">
                            <button
                              type="button"
                              className="swimlane-info-btn swimlane-info-btn-under-label"
                              onClick={() => toggleInfo(row.id)}
                              aria-label="Info"
                              title="Info"
                            >
                              i
                            </button>
                            {openInfoId === row.id ? (
                              <div className="swimlane-info-popover" ref={infoPopoverRef}>
                                {swimlaneInfoText[row.id] || "Info Not Set"}
                              </div>
                            ) : null}
                          </span>
                        )
                        const badges = (
                          <span className="swimlane-badges">
                            {row.headerBreakdown?.length ? (
                              <span className="swimlane-badge-stack">
                                <span className={row.badgeClass}>{row.countLabel ?? row.count}</span>
                                {row.headerBreakdown.map((item, idx) => (
                                  <span
                                    key={`${row.id}-breakdown-${idx}`}
                                    className={item.className ?? "swimlane-badge-sub"}
                                    title={item.label}
                                  >
                                    <span>{`${item.value}/${item.label}`}</span>
                                  </span>
                                ))}
                              </span>
                            ) : row.badges?.length ? (
                              row.badges.map((badge, idx) => (
                                <span key={`${row.id}-badge-${idx}`} className={badge.className} title={badge.label}>
                                  {badge.value}
                                </span>
                              ))
                            ) : (
                              <span className={row.badgeClass}>{row.countLabel ?? row.count}</span>
                            )}
                            {hasTitleToggle ? (
                              <button
                                type="button"
                                className="swimlane-title-row-toggle"
                                onClick={() => toggleSwimlaneTitleRow(row.id)}
                                aria-expanded={isTitleRowOpen}
                                aria-label={isTitleRowOpen ? `Hide ${row.label} full titles` : `Show ${row.label} full titles`}
                                title={isTitleRowOpen ? `Hide ${row.label} full titles` : `Show ${row.label} full titles`}
                              >
                                +
                              </button>
                            ) : null}
                          </span>
                        )

                        if (headerSubtext) {
                          return (
                            <>
                              <div className="swimlane-header-main">
                                <div className="swimlane-header-row">
                                  <span className="swimlane-label-wrap">
                                    <span className="swimlane-label">{row.label}</span>
                                    {infoButton}
                                  </span>
                                  {badges}
                                </div>
                                {row.missingOneHUsers?.some((entry) => !entry.hasBlockedTask) ? (
                                  <div
                                    className="oneh-missing-users"
                                    aria-label={`Pa slot ${headerSubtext}: ${row.missingOneHUsers.filter((entry) => !entry.hasBlockedTask).map((entry) => entry.label).join(", ")}`}
                                  >
                                    {row.missingOneHUsers.filter((entry) => !entry.hasBlockedTask).map((entry) => (
                                      <span key={entry.id} className="oneh-missing-user" title={entry.label}>
                                        {entry.initials}
                                      </span>
                                    ))}
                                  </div>
                                ) : null}
                                {row.missingOneHUsers?.some((entry) => entry.hasBlockedTask) ? (
                                  <div
                                    className="oneh-missing-users oneh-missing-users-covered"
                                    aria-label={`Pa 1H 16:00, me BLL: ${row.missingOneHUsers.filter((entry) => entry.hasBlockedTask).map((entry) => entry.label).join(", ")}`}
                                  >
                                    {row.missingOneHUsers.filter((entry) => entry.hasBlockedTask).map((entry) => (
                                      <span key={entry.id} className="oneh-missing-user" title={entry.label}>
                                        {entry.initials}
                                      </span>
                                    ))}
                                  </div>
                                ) : null}
                                {row.missingBlockedUsers?.some((entry) => !entry.hasOneHAt16) ? (
                                  <div
                                    className="oneh-missing-users"
                                    aria-label={`Pa BLL dhe pa 1H 16:00: ${row.missingBlockedUsers.filter((entry) => !entry.hasOneHAt16).map((entry) => entry.label).join(", ")}`}
                                  >
                                    {row.missingBlockedUsers.filter((entry) => !entry.hasOneHAt16).map((entry) => (
                                      <span key={entry.id} className="oneh-missing-user" title={entry.label}>
                                        {entry.initials}
                                      </span>
                                    ))}
                                  </div>
                                ) : null}
                                {row.missingBlockedUsers?.some((entry) => entry.hasOneHAt16) ? (
                                  <div
                                    className="oneh-missing-users oneh-missing-users-covered"
                                    aria-label={`Pa BLL, me 1H 16:00: ${row.missingBlockedUsers.filter((entry) => entry.hasOneHAt16).map((entry) => entry.label).join(", ")}`}
                                  >
                                    {row.missingBlockedUsers.filter((entry) => entry.hasOneHAt16).map((entry) => (
                                      <span key={entry.id} className="oneh-missing-user" title={entry.label}>
                                        {entry.initials}
                                      </span>
                                    ))}
                                  </div>
                                ) : null}
                              </div>
                              <span className="swimlane-label-sub">{headerSubtext}</span>
                            </>
                          )
                        }

                        return (
                          <>
                            <span className="swimlane-label-wrap">
                              <span className="swimlane-label">{row.label}</span>
                              {infoButton}
                            </span>
                            {badges}
                          </>
                        )
                      })()}
                    </div>
                    <div className="swimlane-content-shell">
                      <div className="swimlane-row-nav">
                        <button type="button" onClick={() => scrollSwimlaneRow(row.id, "left")}>{"<"}</button>
                        <button type="button" onClick={() => scrollSwimlaneRow(row.id, "right")}>{">"}</button>
                      </div>
                      <div
                        className="swimlane-content-scroll"
                        ref={(node) => {
                          swimlaneRowRefs.current[row.id] = node
                        }}
                      >
                        <div className="swimlane-content">
                          {cells.map((cell, index) => {
                            if (!cell) {
                              return <div key={`${row.id}-empty-${index}`} className="swimlane-cell empty" />
                            }
                            const noteKey = cell.entryId || `${row.id}-${index}`
                            const isNoteOpen = openSwimlaneNoteId === noteKey
                            const isTitleRowOpen = openSwimlaneTitleRows.has(row.id)
                            const isTitleExpandable = TITLE_EXPANDABLE_SWIMLANE_ROWS.includes(row.id)
                            const taskStatusIndicator = !cell.placeholder && isFastTaskRowId(row.id)
                              ? renderCommonTaskStatusIndicator(cell, isPersonalRowId(row.id))
                              : null
                            const existingReview = cell.taskId && cell.userId
                              ? diamondReviewByTaskUser.get(`${cell.taskId}:${cell.userId}`)
                              : null
                            const canReviewCell =
                              !cell.placeholder &&
                              Boolean(cell.taskId && cell.userId && cell.isDone) &&
                              cell.userId !== userId &&
                              isFastTaskRowId(row.id) &&
                              (!existingReview || canManageTaskReviews)
                            const reviewButton = canReviewCell ? (
                              <button
                                type="button"
                                className={[
                                  "swimlane-review-btn",
                                  existingReview ? "reviewed" : "",
                                ].filter(Boolean).join(" ")}
                                onClick={() => openCommonTaskReview(cell)}
                                aria-label={existingReview ? "Edit diamond review" : "Add diamond review"}
                                title={existingReview ? "Edit diamond review" : "Add diamond review"}
                              >
                                <DiamondAward compact />
                              </button>
                            ) : null
                            return (
                              <div
                                key={`${row.id}-${index}`}
                                className={[
                                  "swimlane-cell",
                                  cell.accentClass || "",
                                  row.id === "internal" && cell.isCalendarMeeting ? "calendar-internal-muted" : "",
                                  getSwimlaneDividerClass(row.id, cells, index),
                                  cell.placeholder ? "placeholder" : "",
                                  commonTaskHighlightClassName(cell),
                                  isFastTaskRowId(row.id) && hasEightAmIndicator(cell.title, cell.isSystemTask) ? "eight-am-task" : "",
                                  cell.isDone ? "done" : "",
                                  commonTaskStateClassName(cell.status, cell.isDone),
                                  row.id === "personalGA" && !cell.placeholder ? "personal-ga-task" : "",
                                ]
                                  .filter(Boolean)
                                  .join(" ")}
                                role={cell.meetingId ? "button" : undefined}
                                tabIndex={cell.meetingId ? 0 : undefined}
                                title={cell.meetingId ? "Open meeting participants and reminder settings" : undefined}
                                onClick={(event) => {
                                  if (!cell.meetingId) return
                                  if ((event.target as HTMLElement).closest("button, select, input, textarea, a")) return
                                  openMeetingDetailsById(cell.meetingId)
                                }}
                                onKeyDown={(event) => {
                                  if (!cell.meetingId || (event.key !== "Enter" && event.key !== " ")) return
                                  event.preventDefault()
                                  openMeetingDetailsById(cell.meetingId)
                                }}
                                style={cell.meetingId ? { cursor: "pointer" } : undefined}
                              >
                                {!cell.placeholder && canDeleteCommon && cell.entryId ? (
                                  <button
                                    type="button"
                                    className="swimlane-delete"
                                    onClick={() => deleteCommonEntry(cell.entryId!)}
                                    aria-label="Delete entry"
                                    title="Delete"
                                  >
                                    ×
                                  </button>
                                ) : null}
                                {!cell.placeholder &&
                                row.id === "leave" &&
                                cell.title === ALL_USERS_INITIALS &&
                                cell.entryDate &&
                                isAdmin ? (
                                  <button
                                    type="button"
                                    className="swimlane-delete"
                                    onClick={() => deleteAllUsersLeaveForDay(cell.entryDate!)}
                                    aria-label="Delete all-users entries"
                                    title="Delete all users"
                                  >
                                    ×
                                  </button>
                                ) : null}
                                <div className="swimlane-title-row">
                                  <div
                                    className={[
                                      "swimlane-title-main",
                                      row.id === "priority" ? "priority" : "",
                                      isFastTaskRowId(row.id) ? "fast-task-layout" : "",
                                      row.id === "external" || row.id === "internal" ? "meeting-layout" : "",
                                    ].filter(Boolean).join(" ")}
                                  >
                                    {!cell.placeholder && cell.assignees?.length ? (
                                      <div className="swimlane-assignees">
                                        {cell.assignees.map((name) => (
                                          <span key={`${cell.title}-${name}`} className="swimlane-avatar" title={name}>
                                            {initials(name)}
                                          </span>
                                        ))}
                                        {isFastTaskRowId(row.id) && typeof cell.number === "number" ? (
                                          <span className="fast-task-order-badge">{cell.number}</span>
                                        ) : null}
                                        {isOneHSlotRowId(row.id) || row.id === "r1" ? renderOneHReportSlotControl(cell) : null}
                                        {isFastTaskRowId(row.id) ? (
                                          <span className="period-indicator" title={`${getCommonTaskPeriodLabel(cell.finishPeriod)} task`}>
                                            {getCommonTaskPeriodLabel(cell.finishPeriod)}
                                          </span>
                                        ) : null}
                                        {isFastTaskRowId(row.id) ? renderWfcIndicator(cell) : null}
                                        {isShtypiTaskRowId(row.id) ? renderOneHMarkerControl(cell) : null}
                                        {taskStatusIndicator}
                                        {isFastTaskRowId(row.id) && hasEightAmIndicator(cell.title, cell.isSystemTask) ? (
                                          <span className="time-indicator" title="08:00 task">
                                            08:00
                                          </span>
                                        ) : null}
                                        {(row.id === "external" || row.id === "internal") ? renderSwimlaneMeetingStatusControl(cell) : null}
                                        {(row.id === "external" || row.id === "internal") &&
                                        (cell.meetingTimeLabel || cell.isManualInternalMeeting || cell.isCalendarMeeting || cell.meetingRelation) ? (
                                          <span className="meeting-origin-row">
                                            {cell.meetingTimeLabel ? <span className="meeting-time-chip">{cell.meetingTimeLabel}</span> : null}
                                            {row.id === "internal" && cell.isManualInternalMeeting ? (
                                              <span className="manual-meeting-badge">MANUAL</span>
                                            ) : null}
                                            {cell.isCalendarMeeting ? <span className="calendar-meeting-badge">CAL</span> : null}
                                          </span>
                                        ) : null}
                                        {isFastTaskRowId(row.id) && row.id !== "waitingClient"
                                          ? renderFastTaskReorderControls(row.items, cell)
                                          : null}
                                        {reviewButton}
                                      </div>
                                    ) : !cell.placeholder && cell.assigneeLabels?.length ? (
                                      <div className="swimlane-assignees">
                                        {cell.assigneeLabels.map((label) => (
                                          <span key={`${cell.title}-${label}`} className="swimlane-avatar" title={label}>
                                            {label}
                                          </span>
                                        ))}
                                        {isFastTaskRowId(row.id) && typeof cell.number === "number" ? (
                                          <span className="fast-task-order-badge">{cell.number}</span>
                                        ) : null}
                                        {isOneHSlotRowId(row.id) || row.id === "r1" ? renderOneHReportSlotControl(cell) : null}
                                        {isFastTaskRowId(row.id) ? (
                                          <span className="period-indicator" title={`${getCommonTaskPeriodLabel(cell.finishPeriod)} task`}>
                                            {getCommonTaskPeriodLabel(cell.finishPeriod)}
                                          </span>
                                        ) : null}
                                        {isFastTaskRowId(row.id) ? renderWfcIndicator(cell) : null}
                                        {isShtypiTaskRowId(row.id) ? renderOneHMarkerControl(cell) : null}
                                        {taskStatusIndicator}
                                        {isFastTaskRowId(row.id) && hasEightAmIndicator(cell.title, cell.isSystemTask) ? (
                                          <span className="time-indicator" title="08:00 task">
                                            08:00
                                          </span>
                                        ) : null}
                                        {(row.id === "external" || row.id === "internal") ? renderSwimlaneMeetingStatusControl(cell) : null}
                                        {(row.id === "external" || row.id === "internal") &&
                                        (cell.meetingTimeLabel || cell.isManualInternalMeeting || cell.isCalendarMeeting || cell.meetingRelation) ? (
                                          <span className="meeting-origin-row">
                                            {cell.meetingTimeLabel ? <span className="meeting-time-chip">{cell.meetingTimeLabel}</span> : null}
                                            {row.id === "internal" && cell.isManualInternalMeeting ? (
                                              <span className="manual-meeting-badge">MANUAL</span>
                                            ) : null}
                                            {cell.isCalendarMeeting ? <span className="calendar-meeting-badge">CAL</span> : null}
                                          </span>
                                        ) : null}
                                        {isFastTaskRowId(row.id) && row.id !== "waitingClient"
                                          ? renderFastTaskReorderControls(row.items, cell)
                                          : null}
                                        {reviewButton}
                                      </div>
                                    ) : reviewButton ? (
                                      <div className="swimlane-assignees">
                                        {reviewButton}
                                      </div>
                                    ) : (row.id === "external" || row.id === "internal") ? (
                                      <div className="swimlane-assignees">
                                        {renderSwimlaneMeetingStatusControl(cell)}
                                        {cell.meetingTimeLabel || cell.isManualInternalMeeting || cell.isCalendarMeeting || cell.meetingRelation ? (
                                          <span className="meeting-origin-row">
                                            {cell.meetingTimeLabel ? <span className="meeting-time-chip">{cell.meetingTimeLabel}</span> : null}
                                            {row.id === "internal" && cell.isManualInternalMeeting ? (
                                              <span className="manual-meeting-badge">MANUAL</span>
                                            ) : null}
                                            {cell.isCalendarMeeting ? <span className="calendar-meeting-badge">CAL</span> : null}
                                          </span>
                                        ) : null}
                                      </div>
                                    ) : null}
                                    {row.id === "diamond" ? (
                                      <span className="diamond-mark">
                                        <DiamondAward compact />
                                      </span>
                                    ) : null}
                                    <div className="swimlane-title">
                                      {!cell.assignees?.length && !cell.assigneeLabels?.length ? taskStatusIndicator : null}
                                      {isFastTaskRowId(row.id) ? <TaskMarkerComment comment={cell.oneHMarkerComment} taskId={cell.taskId} /> : null}
                                      <span className="swimlane-print-title">
                                        {cell.meetingRelation ? <span className="meeting-relation-badge" title={`${cell.meetingRelation === "PARA" ? "Para" : "Pas"} takimit extern`}>{cell.meetingRelation}</span> : null}
                                        {commonPrintTitleLine(
                                          `${cell.title}${cell.meetingTimeLabel ? ` ${cell.meetingTimeLabel}` : ""}`,
                                        )}
                                      </span>
                                      <span
                                        className={[
                                          "swimlane-title-text",
                                          isTitleExpandable && !isTitleRowOpen ? "collapsed" : "",
                                          isTitleRowOpen ? "expanded" : "",
                                        ].filter(Boolean).join(" ")}
                                      >
                                        {cell.meetingRelation ? <span className="meeting-relation-badge" title={`${cell.meetingRelation === "PARA" ? "Para" : "Pas"} takimit extern`}>{cell.meetingRelation}</span> : null}
                                        {isTitleRowOpen
                                          ? highlightWfcReactNode(renderMarkedNoteContent(stripInitialsPrefix(cell.title), cell.title))
                                          : renderCommonMarkedTitleLine(cell.title)}
                                      </span>
                                    </div>
                                  </div>
                                  {cell.note ? (
                                    <button
                                      type="button"
                                      className="swimlane-note-toggle"
                                      onClick={() => setOpenSwimlaneNoteId((prev) => (prev === noteKey ? null : noteKey))}
                                      aria-expanded={isNoteOpen}
                                      aria-label={isNoteOpen ? "Hide note" : "Show note"}
                                      title={isNoteOpen ? "Hide note" : "Show note"}
                                    >
                                      {isNoteOpen ? "-" : "+"}
                                    </button>
                                  ) : null}
                                  {(() => {
                                    const showSubtitle =
                                      (row.id === "external" ||
                                        row.id === "internal" ||
                                        row.id === "bz" ||
                                        row.id === "late" ||
                                        row.id === "absent" ||
                                        row.id === "leave") &&
                                      Boolean(cell.subtitle)
                                    const showDate =
                                      Boolean(cell.dateLabel) &&
                                      !["late", "absent", "leave"].includes(row.id)
                                    const showSeparateTaskDates = isFastTaskRowId(row.id)
                                    const taskStartDate = showSeparateTaskDates
                                      ? formatFastTaskCardDate(cell.startDate || cell.entryDate)
                                      : null
                                    const taskDueDate = showSeparateTaskDates
                                      ? formatFastTaskCardDate(cell.dueDate, cell.entryDate)
                                      : null
                                    const taskDueDateIsToday = showSeparateTaskDates &&
                                      isFastTaskDateOnTarget(cell.dueDate, cell.entryDate)
                                    if (!showSubtitle && !showDate && !isNoteOpen) return null
                                    return (
                                      <div className="swimlane-meta">
                                        {showSubtitle ? (
                                          <div className="swimlane-subtitle">
                                            {renderMarkedNoteContent(cell.subtitle, cell.subtitle)}
                                          </div>
                                        ) : null}
                                        {showDate && showSeparateTaskDates ? (
                                          <div className="swimlane-task-dates">
                                            {taskStartDate ? (
                                              <span className="swimlane-task-start">
                                                {isCommonTaskStartToday(cell, cell.entryDate) ? (
                                                  <span className="swimlane-start-today" title="Created, started and due today">START SOT</span>
                                                ) : null}
                                                <span className="swimlane-task-date start" title="Start date">
                                                  {taskStartDate}
                                                </span>
                                              </span>
                                            ) : null}
                                            {taskDueDate ? (
                                              <span
                                                className={`swimlane-task-date due${taskDueDateIsToday ? " today" : ""}`}
                                                title="Due date"
                                              >
                                                {taskDueDate}
                                              </span>
                                            ) : null}
                                          </div>
                                        ) : showDate ? (
                                          <div className={["swimlane-date", cell.dateIsToday ? "today" : ""].filter(Boolean).join(" ")}>
                                            {cell.dateLabel}
                                          </div>
                                        ) : null}
                                        {isNoteOpen && cell.note ? (
                                          <div className="swimlane-note">
                                            {renderMarkedNoteContent(cell.note, cell.note)}
                                          </div>
                                        ) : null}
                                      </div>
                                    )
                                  })()}
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })}
          </div>
          <div className="print-footer">
            <span />
            <div className="print-page-count">1/{printTotalPages}</div>
            <div className="print-initials">PUNOI: {printInitials}</div>
          </div>
        </div>
      </div>

      {/* Modal */}
      {modalOpen && (
        <div className="modal">
          <div className="modal-backdrop" onClick={closeModal} />
          <div className="modal-card">
            <div className="modal-header">
            <h4>Add to Common View</h4>
              <button className="btn-outline" type="button" onClick={closeModal}>
                Close
              </button>
            </div>
            <div className="modal-body">
              <form onSubmit={submitForm}>
                <div className="form-grid">
            <div className="form-row">
              <label htmlFor="cv-type">Type</label>
              <select
                id="cv-type"
                className="input"
                value={formType}
                onChange={(e) => {
                  const nextType = e.target.value as any
                  setFormType(nextType)
                  setFormError("")
                  if (nextType !== "leave" && formPerson === ALL_USERS_VALUE) {
                    setFormPerson("")
                  }
                }}
                required
                >
                  <option value="late">Vonese</option>
                  <option value="absent">Mungese</option>
                  <option value="leave">Pushim Vjetor</option>
                  <option value="externalHoliday">Feste Externe</option>
                  <option value="problem">Problem</option>
                  <option value="feedback">Ankese/Kerkese/Propozim</option>
            </select>
          </div>
                  {formType !== "externalHoliday" && (
                  <div className="form-row">
                    <label htmlFor="cv-person">Person</label>
                    <select
                      id="cv-person"
                      className="input"
                      value={formPerson}
                      onChange={(e) => {
                        setFormPerson(e.target.value)
                        setFormError("")
                      }}
                      required
                    >
                      <option value="">--</option>
                      {formType === "leave" ? (
                        <option value={ALL_USERS_VALUE}>{ALL_USERS_LABEL}</option>
                      ) : null}
                      {users.map((u) => (
                        <option key={u.id} value={u.full_name || u.username || u.email}>
                          {u.full_name || u.username || u.email}
                        </option>
                      ))}
                    </select>
                  </div>
                  )}

                  {(formType === "feedback" || formType === "problem" || formType === "externalHoliday") && (
                    <div className="form-row span-2">
                      <label htmlFor="cv-title">{formType === "externalHoliday" ? "Holiday name" : "Title"}</label>
                      <input
                        id="cv-title"
                        className="input"
                        type="text"
                        placeholder={formType === "externalHoliday" ? "e.g. Christmas, New Year" : "e.g. Issue: server access"}
                        value={formTitle}
                        onChange={(e) => setFormTitle(e.target.value)}
                        required
                      />
                    </div>
                  )}

                  {formType !== "feedback" && formType !== "problem" && (
                    <div className="form-row">
                      <label htmlFor="cv-date">Date (DD/MM/YYYY)</label>
                    <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
                      <input
                        id="cv-date"
                        className="input"
                        type="text"
                        placeholder="DD/MM/YYYY"
                        value={formDateDisplay}
                        onChange={(e) => {
                          const value = e.target.value
                          setFormDateDisplay(value)
                          setFormError("")
                          const isoDate = fromDDMMYYYY(value)
                          if (isoDate) {
                            setFormDate(isoDate)
                          }
                        }}
                        pattern="\d{2}/\d{2}/\d{4}"
                        required
                        style={{ flex: 1 }}
                      />
                      <input
                        type="date"
                        value={formDate}
                        onChange={(e) => {
                          const value = e.target.value
                          if (value) {
                            setFormDate(value)
                            setFormDateDisplay(toDDMMYYYY(value))
                            setFormError("")
                          }
                        }}
                        style={{
                          position: "absolute",
                          right: "8px",
                          opacity: 0,
                          width: "24px",
                          height: "24px",
                          cursor: "pointer",
                          zIndex: 1
                        }}
                        title="Open calendar"
                      />
                      <svg
                        width="20"
                        height="20"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        style={{
                          position: "absolute",
                          right: "10px",
                          pointerEvents: "none",
                          color: "#666"
                        }}
                      >
                        <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
                        <line x1="16" y1="2" x2="16" y2="6"></line>
                        <line x1="8" y1="2" x2="8" y2="6"></line>
                        <line x1="3" y1="10" x2="21" y2="10"></line>
                      </svg>
                    </div>
                  </div>
                  )}

                  {formType === "late" && (
                    <>
                      <div className="form-row">
                        <label htmlFor="cv-start">Start time (delay)</label>
                        <input
                          id="cv-start"
                          className="input"
                          type="time"
                          value={formDelayStart}
                          onChange={(e) => setFormDelayStart(e.target.value)}
                        />
                      </div>
                      <div className="form-row">
                        <label htmlFor="cv-until">End time (delay)</label>
                        <input
                          id="cv-until"
                          className="input"
                          type="time"
                          value={formUntil}
                          onChange={(e) => setFormUntil(e.target.value)}
                        />
                      </div>
                    </>
                  )}

                  {formType === "absent" && (
                    <>
                      <div className="form-row">
                        <label htmlFor="cv-from">From </label>
                        <input
                          id="cv-from"
                          className="input"
                          type="time"
                          value={formFrom}
                          onChange={(e) => setFormFrom(e.target.value)}
                        />
                      </div>
                      <div className="form-row">
                        <label htmlFor="cv-to">Until (</label>
                        <input
                          id="cv-to"
                          className="input"
                          type="time"
                          value={formTo}
                          onChange={(e) => setFormTo(e.target.value)}
                        />
                      </div>
                    </>
                  )}

                  {formType === "leave" && (
                    <>
                      <div className="form-row">
                        <label htmlFor="cv-enddate">Until (optional) (DD/MM/YYYY)</label>
                        <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
                          <input
                            id="cv-enddate"
                            className="input"
                            type="text"
                            placeholder="DD/MM/YYYY"
                            value={formEndDateDisplay}
                            onChange={(e) => {
                              const value = e.target.value
                              setFormEndDateDisplay(value)
                              const isoDate = fromDDMMYYYY(value)
                              if (isoDate) {
                                setFormEndDate(isoDate)
                              } else if (!value) {
                                setFormEndDate("")
                              }
                            }}
                            pattern="\d{2}/\d{2}/\d{4}"
                            style={{ flex: 1 }}
                          />
                          <input
                            type="date"
                            value={formEndDate || ""}
                            onChange={(e) => {
                              const value = e.target.value
                              if (value) {
                                setFormEndDate(value)
                                setFormEndDateDisplay(toDDMMYYYY(value))
                              } else {
                                setFormEndDate("")
                                setFormEndDateDisplay("")
                              }
                            }}
                            style={{
                              position: "absolute",
                              right: "8px",
                              opacity: 0,
                              width: "24px",
                              height: "24px",
                              cursor: "pointer",
                              zIndex: 1
                            }}
                            title="Open calendar"
                          />
                          <svg
                            width="20"
                            height="20"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            style={{
                              position: "absolute",
                              right: "10px",
                              pointerEvents: "none",
                              color: "#666"
                            }}
                          >
                            <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
                            <line x1="16" y1="2" x2="16" y2="6"></line>
                            <line x1="8" y1="2" x2="8" y2="6"></line>
                            <line x1="3" y1="10" x2="21" y2="10"></line>
                          </svg>
                        </div>
                      </div>
                      <div className="form-row span-2 leave-inline">
                        <label className="checkbox leave-checkbox">
                          <input
                            type="checkbox"
                            checked={formFullDay}
                            onChange={(e) => setFormFullDay(e.target.checked)}
                          />
                          All day
                        </label>
                        {!formFullDay && (
                          <div className="leave-times">
                            <div className="mini-row">
                              <label htmlFor="cv-leave-from">From time</label>
                              <input
                                id="cv-leave-from"
                                className="input"
                                type="time"
                                value={formFrom}
                                onChange={(e) => setFormFrom(e.target.value)}
                                required={!formFullDay}
                              />
                            </div>
                            <div className="mini-row">
                              <label htmlFor="cv-leave-to">Until time</label>
                              <input
                                id="cv-leave-to"
                                className="input"
                                type="time"
                                value={formTo}
                                onChange={(e) => setFormTo(e.target.value)}
                                required={!formFullDay}
                              />
                            </div>
                          </div>
                        )}
                      </div>
                    </>
                  )}

                  <div className="form-row span-2">
                    <label htmlFor="cv-note">Note</label>
                    <textarea
                      id="cv-note"
                      className="input"
                      placeholder="Optional..."
                      value={formNote}
                      onChange={(e) => setFormNote(e.target.value)}
                    />
                  </div>
                </div>
                {formError ? <div className="form-error">{formError}</div> : null}
                <div className="modal-footer">
                  <button className="btn-outline" type="button" onClick={closeModal} disabled={isSavingEntry}>
                    Cancel
                  </button>
                  <button className="btn-primary" type="submit" disabled={isSavingEntry}>
                    {isSavingEntry ? (loadingPvTaskShift ? "Checking tasks..." : "Saving...") : "Save"}
                  </button>
                </div>
              </form>
              </div>
          </div>
        </div>
      )}
      {pendingPvTaskShift ? (
        <div className="modal">
          <div className="modal-backdrop" />
          <div className="modal-card">
            <div className="modal-header">
              <h4>Move tasks for PV/FESTE</h4>
              <button
                className="btn-outline"
                type="button"
                disabled={isSavingEntry}
                onClick={() => setPendingPvTaskShift(null)}
              >
                Close
              </button>
            </div>
            <div className="modal-body">
              <div className="space-y-3">
                <p className="text-sm text-slate-700">
                  {pendingPvTaskShift.person} has full-day PV/FESTE from{" "}
                  <strong>{formatDateHuman(pendingPvTaskShift.startDate)}</strong> to{" "}
                  <strong>{formatDateHuman(pendingPvTaskShift.endDate)}</strong>. These open tasks have start or due dates in that range.
                </p>
                <div className="form-row">
                  <label htmlFor="pv-move-date">Move to weekday</label>
                  <select
                    id="pv-move-date"
                    className="input"
                    value={pendingPvTaskShift.moveToDate}
                    onChange={(event) =>
                      setPendingPvTaskShift((current) =>
                        current ? { ...current, moveToDate: event.target.value } : current
                      )
                    }
                    disabled={isSavingEntry}
                  >
                    {nextWeekdayOptionsAfter(pendingPvTaskShift.endDate).map((iso) => (
                      <option key={iso} value={iso}>
                        {formatDateHuman(iso)}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="max-h-[320px] overflow-auto rounded-md border">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-slate-100 text-left">
                        <th className="px-3 py-2">Task</th>
                        <th className="px-3 py-2">Start</th>
                        <th className="px-3 py-2">Due</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pendingPvTaskShift.tasks.map(({ task, startDateInLeave, dueDateInLeave }) => (
                        <tr key={task.id} className="border-t">
                          <td className="px-3 py-2">
                            <div className="font-medium">{task.title}</div>
                            {task.assignees?.length ? (
                              <div className="text-xs text-slate-500">
                                {task.assignees.map((assignee) => assignee.full_name || assignee.username || assignee.email || "Unknown").join(", ")}
                              </div>
                            ) : null}
                          </td>
                          <td className={["px-3 py-2", startDateInLeave ? "font-semibold text-red-700" : ""].filter(Boolean).join(" ")}>
                            {task.start_date ? formatDateHuman(toISODate(parseDateOnly(task.start_date) || new Date(task.start_date))) : "-"}
                          </td>
                          <td className={["px-3 py-2", dueDateInLeave ? "font-semibold text-red-700" : ""].filter(Boolean).join(" ")}>
                            {task.due_date ? formatDateHuman(toISODate(parseDateOnly(task.due_date) || new Date(task.due_date))) : "-"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="modal-footer">
                  <button
                    className="btn-outline"
                    type="button"
                    disabled={isSavingEntry}
                    onClick={() => {
                      setPendingPvTaskShift(null)
                      void submitForm(undefined, { skipPvTaskPrompt: true })
                    }}
                  >
                    Save PV only
                  </button>
                  <button
                    className="btn-primary"
                    type="button"
                    disabled={isSavingEntry}
                    onClick={() => void submitForm(undefined, { skipPvTaskPrompt: true, movePvTasks: true })}
                  >
                    {isSavingEntry ? "Saving..." : "Yes, move tasks"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}
      <TaskReviewDialog
        row={commonReviewRow}
        open={commonReviewOpen}
        onOpenChange={setCommonReviewOpen}
        onSaved={handleCommonReviewSaved}
      />
    </div>
  )
}

