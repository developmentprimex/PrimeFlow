"use client"

import { DailyProjectCoverageNotices } from "@/components/daily-project-coverage-notices"
import * as React from "react"
import { useBrowserTabTitle } from "@/components/browser-tab-title"
import { TaskOneHMarkerEditor } from "@/components/task-one-h-marker-editor"
import { TaskMarkerComment } from "@/components/task-marker-comment"
import { TaskOneHMarkerLegend } from "@/components/task-one-h-marker-legend"
import { useVisibleRefresh } from "@/lib/use-visible-refresh"
import Link from "next/link"
import { usePathname, useSearchParams } from "next/navigation"

import { toast } from "sonner"
import { Check, GripVertical, Pencil, Printer, RotateCcw, Trash2 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useConfirm } from "@/components/providers/confirm-dialog-provider"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { BoldOnlyEditor } from "@/components/bold-only-editor"
import { DailyRlzCommentField, DailyRlzReasonCell, DailyRlzSaveButton, dailyRlzStateByTask } from "@/components/daily-rlz-panel"
import { DailyReportMeetingsTable } from "@/components/daily-report-meetings-table"
import { MeetingCanceledBadge } from "@/components/meeting-canceled-badge"
import { useCanceledMeetings } from "@/lib/use-canceled-meetings"
import { PxJavPlanningBriefView } from "@/components/px-jav-planning-brief-view"
import { useAuth } from "@/lib/auth"
import { formatDateDMY, formatDateTimeDMY, normalizeDueDateInput, toDateInputValue } from "@/lib/dates"
import { getDepartmentBootstrapCache, setDepartmentBootstrapCache } from "@/lib/department-bootstrap-cache"
import { readPersistentPageCache, writePersistentPageCache } from "@/lib/persistent-page-cache"
import { departmentTableTag, formatDepartmentName } from "@/lib/department-name"
import { loadGaNoteTaskAssigneeIds, replaceGaNoteTaskAssignees } from "@/lib/ga-note-task-membership"
import { buildMarkedAppendOnlyText, getPlainMarkedText, renderMarkedNoteContent } from "@/lib/note-markup"
import { getConfirmerCandidates, isWaitingConfirmation, validateWaitingConfirmation } from "@/lib/task-confirmation"
import { weeklyPlanStatusBgClass } from "@/lib/weekly-plan-status"
import { cn } from "@/lib/utils"
import { fetchProjectTitlesById } from "@/lib/project-title-lookup"
import { resolveProjectTitle } from "@/lib/project-display-title"
import type {
  ChecklistItem,
  DailyReportGaEntry,
  DailyReportGaTableResponse,
  DailyReportResponse,
  Department,
  InternalNote,
  Meeting,
  Project,
  SystemTaskTemplate,
  Task, TaskAssignee,
  TaskFinishPeriod,
  TaskPriority,
  UserLookup,
} from "@/lib/types"

const TABS = [
  { id: "all", label: "All", tone: "neutral" },
  { id: "projects", label: "Projects", tone: "neutral" },
  { id: "system", label: "System Tasks", tone: "blue" },
  { id: "no-project", label: "Fast Tasks", tone: "blue" },
  { id: "internal-notes", label: "Internal Notes", tone: "neutral" },
  { id: "meetings", label: "Meetings", tone: "neutral" },
] as const

type TabId = (typeof TABS)[number]["id"]
type AllRange = "today" | "tomorrow" | "past-7-days" | "this-week" | "next-week" | "all" | "date"

type MicrosoftEvent = {
  id: string
  subject: string | null
  starts_at: string | null
  ends_at: string | null
  location?: string | null
  is_all_day: boolean
  organizer?: string | null
  body_preview?: string | null
}

type TaskChecklist = {
  id: string
  title?: string | null
  task_id?: string | null
  items: ChecklistItem[]
}

const PHASES = ["MEETINGS", "PLANNING", "DEVELOPMENT", "TESTING", "DOCUMENTATION"] as const

const PHASE_LABELS: Record<string, string> = {
  MEETINGS: "Meetings",
  PLANNING: "Planning",
  DEVELOPMENT: "Development",
  TESTING: "Testing",
  DOCUMENTATION: "Documentation",
  CLOSED: "Closed",
}

function taskRequiresRlzCompletionComment(task?: Task | null) {
  if (!task) return false
  if (task.system_template_origin_id) return true
  if (task.ga_note_origin_id || task.plan_note_origin_id) return false
  return !Boolean(task.is_bllok || task.is_1h_report || task.is_r1 || task.is_personal)
}

function taskUpdateErrorMessage(payload: unknown, fallback: string) {
  if (!payload || typeof payload !== "object") return fallback
  const detail = (payload as { detail?: unknown }).detail
  if (typeof detail === "string" && detail.trim()) return detail
  if (detail && typeof detail === "object") {
    const message = (detail as { message?: unknown }).message
    if (typeof message === "string" && message.trim()) return message
  }
  return fallback
}

const WEEKDAYS_SQ = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
]

const FREQUENCY_LABELS: Record<SystemTaskTemplate["frequency"], string> = {
  DAILY: "Daily",
  WEEKLY: "Weekly",
  MONTHLY: "Monthly",
  YEARLY: "Yearly",
  "3_MONTHS": "3/6 months",
  "6_MONTHS": "3/6 months",
}

const PRIORITY_LABELS: Record<TaskPriority, string> = {
  NORMAL: "Normal",
  HIGH: "High",
  BLLOK: "Bllok",
}

const PRIORITY_BADGE_STYLES: Record<TaskPriority, string> = {
  NORMAL: "border-amber-200 bg-amber-50 text-amber-700",
  HIGH: "border-red-200 bg-red-50 text-red-700",
  BLLOK: "border-[#A78BFA] bg-[#EDE9FE] text-[#6D28D9]",
}

const PRIORITY_BORDER_STYLES: Record<TaskPriority, string> = {
  NORMAL: "border-l-amber-500",
  HIGH: "border-l-red-600",
  BLLOK: "border-l-[#8B5CF6]",
}

const TODAY_TASK_ROW_CLASS = "align-top"
const STARTS_ON_SELECTED_DAY_TASK_ROW_CLASS = "task-row-starts-selected-day"
const DUE_ON_SELECTED_DAY_TASK_ROW_CLASS = "task-row-due-selected-day"
const STARTS_ON_SELECTED_DAY_TASK_CARD_CLASS = "task-card-starts-selected-day"
const DUE_ON_SELECTED_DAY_TASK_CARD_CLASS = "task-card-due-selected-day"
const TODAY_TASK_CELL_CLASS = "py-3 align-top"
const TODAY_TASK_TEXT_CLAMP_CLASS = "leading-4 whitespace-pre-line break-words"

// Grid layout for system tasks table - matches system-tasks page
const GRID_CLASS = "grid grid-cols-[32px_minmax(200px,1fr)_120px_120px_90px_96px_96px_56px_80px_88px] xl:grid-cols-[36px_1fr_150px_150px_120px_120px_120px_64px_100px_100px] gap-2 xl:gap-4 items-center px-4"

const PRIORITY_OPTIONS: TaskPriority[] = ["NORMAL", "HIGH"]
const FINISH_PERIOD_OPTIONS: TaskFinishPeriod[] = ["AM", "PM"]
const FINISH_PERIOD_NONE_VALUE = "__none__"
const FINISH_PERIOD_NONE_LABEL = "None (all day)"
const ONE_H_REPORT_SLOT_OPTIONS = ["10:00", "11:00", "11:50", "14:20", "16:00"] as const
type OneHReportSlot = typeof ONE_H_REPORT_SLOT_OPTIONS[number]
const ONE_H_REPORT_SLOT_SET = new Set<string>(ONE_H_REPORT_SLOT_OPTIONS)
const ONE_H_REPORT_SLOT_NONE_VALUE = "__none__"

const normalizeOneHReportSlot = (value?: string | null): OneHReportSlot | null => {
  const normalized = (value || "").trim()
  return ONE_H_REPORT_SLOT_SET.has(normalized) ? (normalized as OneHReportSlot) : null
}
const getOneHReportSlotLabel = (value?: string | null) => normalizeOneHReportSlot(value) || "No slot"
const getReportRowOneHReportSlot = (row: unknown) => {
  if (!row || typeof row !== "object" || !("oneHReportSlot" in row)) return null
  return normalizeOneHReportSlot((row as { oneHReportSlot?: string | null }).oneHReportSlot)
}
const getDailyReportSlotDisplay = (row: { typeLabel?: string | null; subtype?: string | null }) => {
  if (row.typeLabel === "SYS") return "SYS"
  const subtype = (row.subtype || "").trim().toUpperCase().replace(/:$/, "")
  if (subtype === "BLL") return "BLL"
  if (subtype === "P") return "P"
  return "-"
}
const isWfeDailyReportRow = (row: { status?: string | null }) =>
  normalizeDailyReportStatusKey(row.status) === "WAITING_CLIENT"
const getDailyReportOneHSlotDisplay = (row: {
  typeLabel?: string | null
  subtype?: string | null
  status?: string | null
  oneHReportSlot?: string | null
}) => {
  if (row.subtype === "1H") {
    return isWfeDailyReportRow(row) ? "WFE" : getOneHReportSlotLabel(row.oneHReportSlot)
  }
  return getDailyReportSlotDisplay(row)
}
const isOneHReportRow = (row: unknown) =>
  Boolean(row && typeof row === "object" && "isOneHReportTask" in row && row.isOneHReportTask)
const oneHReportSlotRank = (row: unknown) => {
  const slot = getReportRowOneHReportSlot(row)
  return slot ? ONE_H_REPORT_SLOT_OPTIONS.indexOf(slot) : ONE_H_REPORT_SLOT_OPTIONS.length
}
const orderOneHReportRowsBySlot = <T,>(rows: T[]) => {
  const orderedOneHRows = rows
    .map((row, index) => ({ row, index }))
    .filter((entry) => isOneHReportRow(entry.row))
    .sort((a, b) => oneHReportSlotRank(a.row) - oneHReportSlotRank(b.row) || a.index - b.index)
    .map((entry) => entry.row)
  let oneHIndex = 0
  return rows.map((row) => (isOneHReportRow(row) ? orderedOneHRows[oneHIndex++]! : row))
}
const orderDoneReportRowsLast = <T extends { statusKey?: string | null; status?: string | null }>(rows: T[]) => [
  ...rows.filter((row) => row.statusKey !== "DONE" && row.status?.toUpperCase() !== "DONE"),
  ...rows.filter((row) => row.statusKey === "DONE" || row.status?.toUpperCase() === "DONE"),
]
const buildDailyReportOneHSlotMap = (report: DailyReportResponse | null) => {
  const map: Record<string, OneHReportSlot | null> = {}
  const items = [...(report?.tasks_today || []), ...(report?.tasks_overdue || [])]
  for (const item of items) {
    const task = item.task
    if (task?.id && (task.is_1h_report || task.is_r1)) {
      map[task.id] = normalizeOneHReportSlot(task.one_h_report_slot)
    }
  }
  return map
}

const STATUS_LABELS: Record<string, string> = {
  OPEN: "Open",
  INACTIVE: "Inactive",
}

const STATUS_OPTIONS = ["OPEN", "INACTIVE"] as const
const ALL_TODAY_TASK_STATUS_OPTIONS = ["TODO", "IN_PROGRESS", "WAITING_CLIENT", "WAITING_CONFIRMATION", "DONE"] as const

const NO_PROJECT_TYPES = [
  { id: "normal", label: "Normal", description: "General tasks without a project." },
  { id: "personal", label: "Personal", description: "Personal tasks tracked only in this view." },
  { id: "blocked", label: "BLLOK", description: "Blocked all day by a single task." },
  { id: "hourly", label: "1H", description: "Hourly meeting/reporting task." },
  { id: "r1", label: "R1", description: "First case must be discussed with the manager." },
] as const
const PROJECT_ALL_TODAY_TYPES = [
  { id: "normal", label: "Normal", description: "Standard project task." },
  { id: "high", label: "High", description: "High priority project task." },
  { id: "hourly", label: "1H", description: "Hourly meeting/reporting task." },
  { id: "r1", label: "R1", description: "First case must be discussed with the manager." },
  { id: "personal", label: "Personal", description: "Personal task inside the project." },
  { id: "blocked", label: "BLLOK", description: "Blocked project task." },
] as const
type AllTodayEditTypeId = (typeof PROJECT_ALL_TODAY_TYPES)[number]["id"]

function hasProjectId(projectId?: Task["project_id"]) {
  if (projectId == null) return false
  if (typeof projectId !== "string") return true
  return projectId.trim().length > 0
}

function isNoProjectTask(task: Task) {
  return (
    !hasProjectId(task.project_id) &&
    !hasProjectId(task.dependency_task_id) &&
    task.system_template_origin_id == null
  )
}

function isFastNormalTask(task: Task) {
  return (
    isNoProjectTask(task) &&
    !task.is_bllok &&
    !task.is_1h_report &&
    !task.is_r1 &&
    !task.is_personal &&
    task.priority === "NORMAL" &&
    task.department_id !== null &&
    task.department_id !== undefined
  )
}

const INTERNAL_MEETING = {
  title: "Pikat e diskutimit (Zhvillim M1, M2, M3)",
  team: ["Elsa Ferati", "Rinesa Ahmedi", "Laurent Hoxha", "Endi Hyseni"],
  slots: {
    M1: {
      tabLabel: "M1",
      label: "M1 PER ZHVILLIM (BLIC 08:05 - 08:15 MAX)",
      items: [
        "A ka mungesa, a ndryshon plani per sot?",
        "A ka shenime GA/KA ne grupe/Trello?",
        "Detyrat e secilit per sot (secili hap RD/Trello side-by-side dhe diskuton detyrat).",
        "A ka e-mails te reja ne IT?",
        "Shenimet ne grup te zhvillimit vendosen copy/paste ne Trello tek shenimet GA/KA.",
      ],
    },
    M2: {
      tabLabel: "M2",
      label: "M2 PER ZHVILLIM (11:45-12:00 MAX)",
      items: [
        "A ka shenime GA/KA ne grupe/Trello?",
        "Detyrat e secilit diskutohen, cka kemi punu deri 12:00?",
        "Cka mbetet per PM?",
      ],
    },
    M3: {
      tabLabel: "M3",
      label: "M3 (ME TRELLO) PER ZHVILLIM (15:45-16:00 MAX)",
      items: [
        "A ka shenime GA/KA ne grupe/Trello?",
        "Diskuto detyrat e te gjithve, cka kemi punu deri tash?",
        "Cka kemi me punu neser?",
      ],
    },
    TESTIMI_I_AGENT: {
      tabLabel: "Testimi i Agent",
      label: "TESTIMI I AGENT",
      items: [],
    },
  },
} as const

const INTERNAL_MEETING_GROUP_KEY = "development_internal_meetings"
const INTERNAL_MEETING_ARCHIVED_CHECKLIST_TITLES = new Set(["testimi i agent-ave"])
const INTERNAL_MEETING_ARCHIVED_MEETING_TITLES = new Set([
  "testimi i agent-ave (m1)",
  "testimi i agent-ave (m2)",
  "testimi i agent-ave (m3)",
])

function resolveInternalMeetingSlot(
  value: ChecklistItem["day"] | undefined | null
): keyof typeof INTERNAL_MEETING.slots {
  const fallback: keyof typeof INTERNAL_MEETING.slots = "M1"
  if (!value) return fallback
  const keys = Object.keys(INTERNAL_MEETING.slots) as Array<keyof typeof INTERNAL_MEETING.slots>
  return (keys as string[]).includes(value) ? (value as keyof typeof INTERNAL_MEETING.slots) : fallback
}

function initials(src: string) {
  return src
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("")
}

function assigneeLabel(user?: UserLookup | null) {
  return user?.full_name || user?.username || "-"
}

function formatToday() {
  const now = new Date()
  const date = formatDateDMY(now)
  const day = now.toLocaleDateString("en-US", { weekday: "short" })
  return `${day} - ${date}`
}

function isSameDay(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

function toDate(value?: string | null) {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return date
}

function formatDateInput(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, "0")
  const day = String(date.getDate()).padStart(2, "0")
  return `${year}-${month}-${day}`
}

function dateInputToDate(value?: string | null) {
  if (!value) return null
  const [year, month, day] = value.split("-").map(Number)
  if (!year || !month || !day) return null
  const date = new Date(year, month - 1, day)
  if (
    Number.isNaN(date.getTime()) ||
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== day
  ) {
    return null
  }
  return date
}

function formatDate(value?: string | null) {
  if (!value) return "-"
  const date = new Date(value)
  const day = date.getDate().toString().padStart(2, "0")
  const month = (date.getMonth() + 1).toString().padStart(2, "0")
  let hours = date.getHours()
  const minutes = date.getMinutes().toString().padStart(2, "0")
  const ampm = hours >= 12 ? "PM" : "AM"
  hours = hours % 12
  hours = hours ? hours : 12 // the hour '0' should be '12'
  const hoursStr = hours.toString().padStart(2, "0")
  return `${day}.${month}, ${hoursStr}:${minutes} ${ampm}`
}

function formatDateOnly(value?: string | null) {
  return formatDateDMY(value)
}

function systemTaskStartDate(task: SystemTaskTemplate): string | null {
  return task.start_date || task.occurrence_date || null
}

function systemTaskDisplayDate(task: SystemTaskTemplate): string | null {
  return task.due_date || task.effective_occurrence_date || task.occurrence_date || task.next_occurrence_date || null
}

function todayInputValue() {
  return dateInputValueWithOffset(0)
}

function tomorrowInputValue() {
  return dateInputValueWithOffset(1)
}

function dateInputValueWithOffset(offsetDays: number) {
  const now = new Date()
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60 * 1000)
  local.setDate(local.getDate() + offsetDays)
  return local.toISOString().slice(0, 10)
}

function getInitials(label: string) {
  const trimmed = label.trim()
  if (!trimmed) return "?"
  const parts = trimmed.split(/\s+/)
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase()
}

function abbreviateDepartmentName(name: string): string {
  const lowerName = name.toLowerCase()
  if (lowerName.includes("development")) return "DEV"
  if (lowerName.includes("graphic") && lowerName.includes("design")) return "GDS"
  if (lowerName.includes("product") && lowerName.includes("content")) return "PCM"
  if (lowerName.includes("project content")) return "PCM"
  // Return first 3 letters as fallback
  return name.slice(0, 3).toUpperCase()
}

function systemTaskDepartmentLabel(
  template: SystemTaskTemplate,
  departmentMap: Map<string, Department>,
  userMap: Map<string, UserLookup>
): string {
  const assigneeDeptCodes = template.assignees
    ? Array.from(
        new Set(
          template.assignees
            .map((assignee) => {
              const userDeptId = assignee.department_id || userMap.get(assignee.id || "")?.department_id
              return userDeptId ? departmentMap.get(userDeptId)?.code : null
            })
            .filter(Boolean) as string[]
        )
      )
    : []

  if (assigneeDeptCodes.length) return assigneeDeptCodes.join(" / ")
  if (template.scope === "GA") return "GA"
  if (template.scope === "ALL") return "ALL"
  return "-"
}

function MeetingDepartmentTag({
  meeting,
  departmentMap,
}: {
  meeting: Meeting
  departmentMap: Map<string, Department>
}) {
  const meetingDepartment = departmentMap.get(meeting.department_id)
  const tag = meetingDepartment ? departmentTableTag(meetingDepartment).toUpperCase() : "-"
  return (
    <span
      className={cn(
        "inline-flex min-w-[42px] items-center justify-center rounded-full border px-2 py-0.5 text-[10px] font-bold tracking-wide",
        tag === "DEV"
          ? "border-blue-700 bg-blue-600 text-white shadow-sm"
          : "border-slate-300 bg-slate-100 text-slate-700"
      )}
    >
      {tag}
    </span>
  )
}

const PRIORITY_BADGE: Record<"NORMAL" | "HIGH", string> = {
  NORMAL: "bg-emerald-100 text-emerald-800 border-emerald-200",
  HIGH: "bg-rose-100 text-rose-800 border-rose-200",
}
const GA_BADGE_CLASSES = "bg-rose-100 text-rose-800 border-rose-200"
const ONE_H_BADGE_CLASSES = "bg-amber-100 text-amber-800 border-amber-200"
const R1_BADGE_CLASSES = "bg-sky-100 text-sky-800 border-sky-200"
const PERSONAL_BADGE_CLASSES = "bg-emerald-100 text-emerald-800 border-emerald-200"
const BLLOK_BADGE_CLASSES = "bg-slate-200 text-slate-800 border-slate-300"

function formatDayLabel(date: Date) {
  const today = new Date()
  const todayKey = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime()
  const targetKey = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
  const delta = Math.round((targetKey - todayKey) / (24 * 60 * 60 * 1000))
  const prefix = delta === 0 ? "Today" : delta === -1 ? "Yesterday" : delta === 1 ? "Tomorrow" : ""
  const weekday = WEEKDAYS_SQ[date.getDay() === 0 ? 6 : date.getDay() - 1]
  return prefix ? `${prefix} - ${weekday}` : weekday
}

function getLastDayOfMonth(year: number, monthIndex: number) {
  return new Date(year, monthIndex + 1, 0).getDate()
}

function getFirstWorkingDay(year: number, monthIndex: number) {
  const firstDay = new Date(year, monthIndex, 1)
  const day = firstDay.getDay()
  if (day === 6) return 3
  if (day === 0) return 2
  return 1
}

function getYearEndDate(year: number) {
  const date = new Date(year, 11, 31)
  const weekday = date.getDay()
  if (weekday === 6) date.setDate(date.getDate() - 1)
  if (weekday === 0) date.setDate(date.getDate() - 2)
  return date
}

function getScheduledDateForMonth(t: SystemTaskTemplate, year: number, monthIndex: number) {
  const lastDay = getLastDayOfMonth(year, monthIndex)
  let day =
    t.day_of_month == null ? 1 : t.day_of_month === 0 ? lastDay : t.day_of_month === -1 ? getFirstWorkingDay(year, monthIndex) : t.day_of_month
  if (day < 1 || day > lastDay) return null
  const scheduled = new Date(year, monthIndex, day)
  if (t.day_of_month !== -1) {
    const weekday = scheduled.getDay()
    if (weekday === 6) scheduled.setDate(scheduled.getDate() - 1)
    if (weekday === 0) scheduled.setDate(scheduled.getDate() - 2)
  }
  return scheduled
}

function shouldShowTemplate(t: SystemTaskTemplate, date: Date) {
  if (t.frequency === "DAILY") return true
  if (t.frequency === "WEEKLY") {
    const dayIdx = date.getDay() === 0 ? 6 : date.getDay() - 1
    const days =
      t.days_of_week && t.days_of_week.length
        ? t.days_of_week
        : t.day_of_week != null
          ? [t.day_of_week]
          : null
    return days ? days.includes(dayIdx) : dayIdx === 0
  }
  if (t.frequency === "MONTHLY") {
    const current = getScheduledDateForMonth(t, date.getFullYear(), date.getMonth())
    const next = getScheduledDateForMonth(t, date.getFullYear(), date.getMonth() + 1)
    return (current && isSameDay(current, date)) || (next && isSameDay(next, date))
  }
  if (t.frequency === "YEARLY") {
    if (t.day_of_month === 0) {
      const current = getYearEndDate(date.getFullYear())
      const next = getYearEndDate(date.getFullYear() + 1)
      return (current && isSameDay(current, date)) || (next && isSameDay(next, date))
    }
    if (t.month_of_year == null) {
      const current = getScheduledDateForMonth(t, date.getFullYear(), date.getMonth())
      const next = getScheduledDateForMonth(t, date.getFullYear(), date.getMonth() + 1)
      return (current && isSameDay(current, date)) || (next && isSameDay(next, date))
    }
    const targetMonth = t.month_of_year - 1
    const current = getScheduledDateForMonth(t, date.getFullYear(), targetMonth)
    const next = getScheduledDateForMonth(t, date.getFullYear() + 1, targetMonth)
    return (current && isSameDay(current, date)) || (next && isSameDay(next, date))
  }
  if (t.frequency === "3_MONTHS" || t.frequency === "6_MONTHS") {
    const interval = t.frequency === "3_MONTHS" ? 3 : 6
    const monthValue = date.getMonth() + 1
    const nextDate = new Date(date.getFullYear(), date.getMonth() + 1, 1)
    const nextMonthValue = nextDate.getMonth() + 1
    const targetMonth = t.month_of_year != null ? t.month_of_year : null
    if (targetMonth != null && targetMonth !== monthValue && targetMonth !== nextMonthValue) return false
    const current =
      monthValue % interval === 0 ? getScheduledDateForMonth(t, date.getFullYear(), date.getMonth()) : null
    const next =
      nextMonthValue % interval === 0 ? getScheduledDateForMonth(t, nextDate.getFullYear(), nextDate.getMonth()) : null
    return (current && isSameDay(current, date)) || (next && isSameDay(next, date))
  }
  return false
}

function findPreviousOccurrenceDate(t: SystemTaskTemplate, fromDate: Date) {
  const candidate = new Date(fromDate)
  for (let i = 0; i < 370; i += 1) {
    if (shouldShowTemplate(t, candidate)) return candidate
    candidate.setDate(candidate.getDate() - 1)
  }
  return fromDate
}

function getNextOccurrenceDate(t: SystemTaskTemplate, fromDate: Date = new Date()): Date {
  const today = new Date(fromDate)
  today.setHours(0, 0, 0, 0)

  if (t.frequency === "DAILY") {
    return today
  }

  if (t.frequency === "WEEKLY") {
    const days = t.days_of_week && t.days_of_week.length
      ? t.days_of_week
      : t.day_of_week != null
        ? [t.day_of_week]
        : [0] // Monday by default

    const currentDayIdx = today.getDay() === 0 ? 6 : today.getDay() - 1
    const sortedDays = [...days].sort((a, b) => a - b)

    // Find next day in this week
    for (const dayIdx of sortedDays) {
      if (dayIdx >= currentDayIdx) {
        const nextDate = new Date(today)
        nextDate.setDate(today.getDate() + (dayIdx - currentDayIdx))
        return nextDate
      }
    }

    // If no day found this week, use first day of next week
    const nextDate = new Date(today)
    const daysUntilNextWeek = 7 - currentDayIdx + sortedDays[0]
    nextDate.setDate(today.getDate() + daysUntilNextWeek)
    return nextDate
  }

  if (t.frequency === "MONTHLY") {
    const current = getScheduledDateForMonth(t, today.getFullYear(), today.getMonth())
    if (current && current >= today) {
      return current
    }
    const next = getScheduledDateForMonth(t, today.getFullYear(), today.getMonth() + 1)
    return next || today
  }

  if (t.frequency === "YEARLY") {
    if (t.day_of_month === 0) {
      const current = getYearEndDate(today.getFullYear())
      if (current && current >= today) {
        return current
      }
      return getYearEndDate(today.getFullYear() + 1)
    }
    if (t.month_of_year == null) {
      const current = getScheduledDateForMonth(t, today.getFullYear(), today.getMonth())
      if (current && current >= today) {
        return current
      }
      const next = getScheduledDateForMonth(t, today.getFullYear(), today.getMonth() + 1)
      if (next) return next
      return getScheduledDateForMonth(t, today.getFullYear() + 1, 0) || today
    }
    const targetMonth = t.month_of_year - 1
    const current = getScheduledDateForMonth(t, today.getFullYear(), targetMonth)
    if (current && current >= today) {
      return current
    }
    return getScheduledDateForMonth(t, today.getFullYear() + 1, targetMonth) || today
  }

  if (t.frequency === "3_MONTHS" || t.frequency === "6_MONTHS") {
    const interval = t.frequency === "3_MONTHS" ? 3 : 6
    let checkMonth = today.getMonth()
    let checkYear = today.getFullYear()

    // Check up to 2 years ahead
    for (let i = 0; i < 24; i++) {
      const monthValue = checkMonth + 1
      if (monthValue % interval === 0) {
        const candidate = getScheduledDateForMonth(t, checkYear, checkMonth)
        if (candidate && candidate >= today) {
          return candidate
        }
      }
      checkMonth++
      if (checkMonth >= 12) {
        checkMonth = 0
        checkYear++
      }
    }
  }

  return today
}

function formatSchedule(t: SystemTaskTemplate, date: Date) {
  const dayLabel = formatDayLabel(date)
  const dateLabel = formatDateDMY(date)
  return `${dayLabel}\n${dateLabel}`
}

function formatMeetingLabel(meeting: Meeting) {
  const platformLabel = meeting.platform ? ` (${meeting.platform})` : ""
  const date = resolveMeetingDisplayDate(meeting)
  if (!date) return `${meeting.title}${platformLabel}`
  if (Number.isNaN(date.getTime())) return `${meeting.title}${platformLabel}`
  const today = new Date()
  const sameDay =
    date.getFullYear() === today.getFullYear() &&
    date.getMonth() === today.getMonth() &&
    date.getDate() === today.getDate()
  const timeLabel = date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })
  const weekdayLabel = date.toLocaleDateString("en-US", { weekday: "long" })
  const prefix = sameDay ? timeLabel : weekdayLabel
  return `${prefix} - ${meeting.title}${platformLabel}`
}

function formatMeetingDateTime(meeting: Meeting): string {
  const dateLabel = formatMeetingDate(meeting)
  const timeLabel = formatMeetingTime(meeting)
  return dateLabel === "-" || timeLabel === "-" ? "-" : `${dateLabel} ${timeLabel}`
}

function formatMeetingDate(meeting: Meeting): string {
  const date = resolveMeetingDisplayDate(meeting)
  if (!date) return "-"
  if (Number.isNaN(date.getTime())) return "-"
  const today = new Date()
  const sameDay =
    date.getFullYear() === today.getFullYear() &&
    date.getMonth() === today.getMonth() &&
    date.getDate() === today.getDate()
  const dateLabel = sameDay
    ? "Today"
    : date.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })
  return dateLabel
}

function formatMeetingTime(meeting: Meeting): string {
  const date = resolveMeetingDisplayDate(meeting)
  if (!date || Number.isNaN(date.getTime())) return "-"
  return date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })
}

function formatMsEventWindow(event: MicrosoftEvent) {
  if (!event.starts_at) return "Time not set"
  const start = new Date(event.starts_at)
  if (Number.isNaN(start.getTime())) return "Time not set"
  const end = event.ends_at ? new Date(event.ends_at) : null
  const dateLabel = start.toLocaleDateString("en-US", { month: "short", day: "2-digit" })
  if (event.is_all_day) return `${dateLabel} - All day`
  const startTime = start.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })
  const endTime =
    end && !Number.isNaN(end.getTime())
      ? end.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })
      : null
  return endTime ? `${dateLabel} ${startTime} - ${endTime}` : `${dateLabel} ${startTime}`
}

function toMeetingInputValue(value?: string | null) {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""
  const pad2 = (n: number) => String(n).padStart(2, "0")
  const y = date.getFullYear()
  const m = pad2(date.getMonth() + 1)
  const d = pad2(date.getDate())
  const h = pad2(date.getHours())
  const min = pad2(date.getMinutes())
  return `${y}-${m}-${d}T${h}:${min}`
}

function toMeetingTimeInputValue(value?: string | null) {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""
  const pad2 = (n: number) => String(n).padStart(2, "0")
  return `${pad2(date.getHours())}:${pad2(date.getMinutes())}`
}

function parseTimeValue(value: string) {
  const match = /^(\d{2}):(\d{2})$/.exec(value)
  if (!match) return null
  const hours = Number(match[1])
  const minutes = Number(match[2])
  if (Number.isNaN(hours) || Number.isNaN(minutes)) return null
  if (hours < 0 || hours > 23 || minutes < 0 || minutes > 59) return null
  return { hours, minutes }
}

function computeNextOccurrenceDate(params: {
  recurrenceType: "weekly" | "monthly"
  daysOfWeek: number[]
  daysOfMonth: number[]
  timeValue: string
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

  return null
}

function resolveMeetingDisplayDate(meeting: Meeting) {
  const recurrenceType = meeting.recurrence_type
  if (recurrenceType && recurrenceType !== "none" && meeting.starts_at) {
    const timeValue = toMeetingTimeInputValue(meeting.starts_at)
    if (timeValue) {
      const next = computeNextOccurrenceDate({
        recurrenceType: recurrenceType as "weekly" | "monthly",
        daysOfWeek: meeting.recurrence_days_of_week || [],
        daysOfMonth: meeting.recurrence_days_of_month || [],
        timeValue,
      })
      if (next) return next
    }
    return null
  }
  if (!meeting.starts_at) return null
  return new Date(meeting.starts_at)
}

function normalizePriority(value?: TaskPriority | string | null): TaskPriority {
  const normalized = typeof value === "string" ? value.toUpperCase() : null
  if (normalized === "URGENT") return "HIGH"
  if (normalized === "LOW" || normalized === "MEDIUM") return "NORMAL"
  if (normalized === "NORMAL" || normalized === "HIGH") return normalized
  return "NORMAL"
}

function startOfWeekMonday(date: Date) {
  const day = date.getDay()
  const diff = (day + 6) % 7
  const start = new Date(date)
  start.setDate(date.getDate() - diff)
  start.setHours(0, 0, 0, 0)
  return start
}

function formatPrintDay(date: Date) {
  const weekday = date.toLocaleDateString("en-US", { weekday: "short" })
  const day = date.toLocaleDateString("en-GB", { day: "2-digit", month: "2-digit" })
  return `${weekday} ${day}`
}

function noProjectTypeLabel(task: Task) {
  if (task.is_bllok) return "BLLOK"
  if (task.is_1h_report) return "1H"
  if (task.is_r1) return "R1"
  if (task.is_personal) return "Personal"
  return "Normal"
}

function getAllTodayTaskType(task: Task): AllTodayEditTypeId {
  if (task.is_bllok) return "blocked"
  if (task.is_1h_report) return "hourly"
  if (task.is_r1) return "r1"
  if (task.is_personal) return "personal"
  if (hasProjectId(task.project_id) && task.priority === "HIGH") return "high"
  return "normal"
}

function fastSubtypeLabel(task: Task) {
  const base = noProjectTypeLabel(task)
  if (base === "BLLOK") return "BLL"
  if (base === "Personal") return "P"
  return base
}

function systemFrequencyLabel(freq?: string | null) {
  if (!freq) return "-"
  switch (freq) {
    case "DAILY":
      return "Daily"
    case "WEEKLY":
      return "Weekly"
    case "MONTHLY":
      return "Monthly"
    case "3_MONTHS":
      return "Every 3 months"
    case "6_MONTHS":
      return "Every 6 months"
    case "YEARLY":
      return "Yearly"
    default:
      return freq
  }
}

function systemFrequencyShortLabel(freq?: SystemTaskTemplate["frequency"] | string | null) {
  if (!freq) return "-"
  switch (freq) {
    case "DAILY":
      return "D"
    case "WEEKLY":
      return "W"
    case "MONTHLY":
      return "M"
    case "YEARLY":
      return "Y"
    case "3_MONTHS":
      return "3M"
    case "6_MONTHS":
      return "6M"
    default:
      return String(freq)
  }
}

function reportStatusLabel(status?: Task["status"] | null) {
  if (!status) return "-"
  if (status === "IN_PROGRESS") return "In Progress"
  if (status === "WAITING_CLIENT") return "WFE"
  if (status === "WAITING_CONFIRMATION") return "Waiting Confirmation"
  if (status === "TODO") return "TO DO"
  if (status === "DONE") return "Done"
  return status
}

function normalizeDailyReportStatusKey(status?: string | null) {
  const normalized = (status || "")
    .trim()
    .toUpperCase()
    .replace(/[\s-]+/g, "_")
  if (!normalized) return ""
  if (normalized === "OPEN") return "TODO"
  if (normalized === "TODO" || normalized === "TO_DO") return "TODO"
  if (normalized === "IN_PROGRESS" || normalized === "INPROGRESS") return "IN_PROGRESS"
  if (normalized === "WFE" || normalized === "WAITING_CLIENT" || normalized === "WAITING_FOR_CLIENT") return "WAITING_CLIENT"
  if (normalized === "WAITING_CONFIRMATION") return "WAITING_CONFIRMATION"
  if (normalized === "DONE") return "DONE"
  return normalized
}

function dailyReportStatusChipLabel(key: string) {
  if (key === "TODO") return "TO DO"
  if (key === "IN_PROGRESS") return "IN PROGRESS"
  if (key === "WAITING_CLIENT") return "WFE"
  if (key === "WAITING_CONFIRMATION") return "WAITING CONFIRMATION"
  if (key === "DONE") return "DONE"
  return key.replace(/_/g, " ")
}

function dailyReportStatusDisplay(status?: string | null) {
  const key = normalizeDailyReportStatusKey(status)
  if (!key) return "-"
  return dailyReportStatusChipLabel(key)
}

function dailyReportTypeLabel(typeLabel?: string | null) {
  if (typeLabel === "FT") return "FAST TASK"
  if (typeLabel === "SYS") return "SYSTEM TASK"
  if (typeLabel === "PRJK" || typeLabel === "PRJ") return "PROJEKT"
  return typeLabel || "-"
}

function getDailyReportRowId(
  row: {
    taskId?: string
    systemTemplateId?: string
    systemOccurrenceDate?: string
    typeLabel?: string
    title?: string
  },
  fallbackIndex: number
) {
  if (row.taskId) return `task:${row.taskId}`
  if (row.systemTemplateId) return `system:${row.systemTemplateId}:${row.systemOccurrenceDate || "na"}`
  return `misc:${row.typeLabel || "na"}:${row.title || "untitled"}:${fallbackIndex}`
}

function getDailyReportTitlePreview(title?: string | null) {
  const raw = title || "-"
  return raw.split(/\r?\n/).map((line) => line.trim()).find(Boolean) || raw
}

function getCompleteTaskTitle(task: Task, sourceContent?: string | null) {
  const title = (task.title || "").trim()
  const sourceTitle = (sourceContent || "").trim()
  if (sourceTitle) return sourceTitle
  const description = (task.description || "").trim()
  if (!(task.ga_note_origin_id || task.plan_note_origin_id) || !description) return title || "-"

  const normalizedTitle = title.replace(/[ \t\f\v]+/g, " ")
  const descriptionFirstLine = description
    .split(/\r?\n/)
    .map((line) => line.replace(/[ \t\f\v]+/g, " ").trim())
    .find(Boolean) || ""
  const descriptionContinuesTitle =
    Boolean(normalizedTitle) &&
    (descriptionFirstLine === normalizedTitle || descriptionFirstLine.startsWith(normalizedTitle))

  return descriptionContinuesTitle ? description : title || description || "-"
}

function taskStatusValue(task: Task): Task["status"] {
  if (task.status === "DONE" || task.completed_at) return "DONE"
  if (task.status === "WAITING_CLIENT") return "WAITING_CLIENT"
  if (task.status === "WAITING_CONFIRMATION") return "WAITING_CONFIRMATION"
  if (task.status === "IN_PROGRESS") return "IN_PROGRESS"
  return "TODO"
}

function controlKoUserId(task: Task): string | null {
  if (String(task.phase || "").toUpperCase().trim() !== "CONTROL") return null
  const match = task.internal_notes?.match(/ko_user_id[:=]\s*([a-f0-9-]+)/i)
  return match ? match[1] : null
}

function statusBadgeClasses(status: Task["status"]) {
  if (status === "DONE") return "bg-green-100 text-green-700 border-green-200"
  if (status === "WAITING_CLIENT") return "bg-[#E2C15B] text-[#4F3A00] border-[#B8860B]"
  if (status === "WAITING_CONFIRMATION") return "bg-blue-100 text-blue-700 border-blue-200"
  if (status === "IN_PROGRESS") return "bg-amber-100 text-amber-800 border-amber-200"
  return "bg-slate-100 text-slate-700 border-slate-200"
}

const MS_PER_DAY = 24 * 60 * 60 * 1000

function dayKey(date: Date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
}

function businessDayDelta(startDate: Date, endDate: Date) {
  const start = new Date(startDate.getFullYear(), startDate.getMonth(), startDate.getDate())
  const end = new Date(endDate.getFullYear(), endDate.getMonth(), endDate.getDate())
  if (end <= start) return 0
  const totalDays = Math.floor((end.getTime() - start.getTime()) / MS_PER_DAY)
  const fullWeeks = Math.floor(totalDays / 7)
  const remainder = totalDays % 7
  let weekdays = fullWeeks * 5
  const startWeekday = start.getDay() // Sunday=0 ... Saturday=6
  for (let offset = 1; offset <= remainder; offset += 1) {
    const dayIdx = (startWeekday + offset) % 7
    if (dayIdx !== 0 && dayIdx !== 6) weekdays += 1
  }
  return weekdays
}

function systemFrequencyReportLabel(freq?: SystemTaskTemplate["frequency"] | string | null) {
  if (!freq) return "-"
  switch (freq) {
    case "DAILY":
      return "Daily"
    case "WEEKLY":
      return "Weekly"
    case "MONTHLY":
      return "Monthly"
    case "YEARLY":
      return "Yearly"
    case "3_MONTHS":
      return "3 months"
    case "6_MONTHS":
      return "6 months"
    default:
      return String(freq)
  }
}

function formatSystemOccurrenceStatus(status?: string | null) {
  if (!status) return "-"
  if (status === "TODO") return "TO DO"
  if (status === "IN_PROGRESS") return "IN PROGRESS"
  if (status === "WAITING_CLIENT") return "WFE"
  if (status === "WAITING_CONFIRMATION") return "Waiting Confirmation"
  if (status === "NOT_DONE") return "Not Done"
  if (status === "DONE") return "Done"
  if (status === "OPEN") return "TO DO"
  if (status === "SKIPPED") return "Skipped"
  return status
}

function formatAlignmentTime(value?: string | null) {
  if (!value) return "-"
  const match = String(value).match(/^(\d{2}:\d{2})/)
  return match ? match[1] : String(value)
}

function formatAlignmentUsers(userIds: string[] | null | undefined, userMap: Map<string, UserLookup>) {
  if (!userIds || userIds.length === 0) return "-"
  return userIds
    .map((id) => {
      const user = userMap.get(id)
      return user?.full_name || user?.username || id
    })
    .join(", ")
}

function formatAlignmentInitials(userIds: string[] | null | undefined, userMap: Map<string, UserLookup>) {
  if (!userIds || userIds.length === 0) return "-"
  const values = userIds
    .map((id) => {
      const user = userMap.get(id)
      const label = user?.full_name || user?.username || id
      return initials(label)
    })
    .filter(Boolean)
  if (!values.length) return "-"
  return values.join("/")
}

function getTyoLabel(baseDate: Date | null, completedAt: string | null | undefined, today: Date) {
  const completedDate = completedAt ? toDate(completedAt) : null
  if (completedDate && isSameDay(completedDate, today)) return "T"
  if (!baseDate) return "-"
  if (isSameDay(baseDate, today)) return "T"
  const delta = businessDayDelta(baseDate, today)
  if (delta === 1) return "Y"
  if (delta > 1) return String(delta)
  return "-"
}

type DailyReportTyoMode = "range" | "dueOnly"

function getDailyReportTyo({
  reportDate,
  startDate,
  dueDate,
  mode,
}: {
  reportDate: Date
  startDate?: Date | null
  dueDate?: Date | null
  mode: DailyReportTyoMode
}) {
  if (!dueDate) return "-"
  const reportKey = dayKey(reportDate)
  const dueKey = dayKey(dueDate)

  if (mode === "range") {
    if (startDate) {
      const startKey = dayKey(startDate)
      if (reportKey < startKey) return "-"
      if (reportKey <= dueKey) return "T"
    } else if (reportKey <= dueKey) {
      return reportKey === dueKey ? "T" : "-"
    }
  } else {
    if (reportKey < dueKey) return "-"
    if (reportKey === dueKey) return "T"
  }

  const lateDays = businessDayDelta(dueDate, reportDate)
  if (lateDays === 1) return "Y"
  if (lateDays >= 2) return String(lateDays)
  return "-"
}

function formatTyoDisplay(value: string, dateValue?: string | null, showDate = true) {
  if (!showDate) return value
  const dateLabel = formatDateDMY(dateValue)
  if (!dateLabel || dateLabel === "-") return value
  if (value === "-") return dateLabel
  return `${value} - ${dateLabel}`
}

function titleHasEightAmIndicator(title?: string | null) {
  // Email tasks (EM) belong to the 08:00 group even when the user omitted the
  // time marker from the title. Treat them exactly like explicitly marked
  // 08:00/8:00 tasks so the badge is visible in screen and print reports.
  return typeof title === "string" && (/\b0?8:00\b/.test(title) || /\bEM\b/i.test(title))
}

function fastReportSubtype(task: Task) {
  const base = noProjectTypeLabel(task)
  if (base === "BLLOK") return "BLL"
  if (base === "Personal") return "P"
  if (base === "Normal") return "NORMAL"
  return base
}

function fastReportSubtypeShort(task: Task) {
  const base = noProjectTypeLabel(task)
  if (base === "BLLOK") return "BLL"
  if (base === "Personal") return "P:"
  if (base === "Normal") return "N"
  return base
}

function projectReportSubtypeShort(task: Task) {
  const base = noProjectTypeLabel(task)
  if (base === "BLLOK") return "BLL"
  if (base === "Personal") return "P"
  if (base === "Normal") return "-"
  return base
}

function taskStatusLabel(task: Task) {
  if (task.status) return reportStatusLabel(task.status)
  if (task.completed_at) return "Done"
  return "-"
}

function reportPriorityLabel(priority?: TaskPriority | string | null) {
  if (!priority) return "-"
  return PRIORITY_LABELS[normalizePriority(priority)]
}

function systemTaskAssignedToUser(task: SystemTaskTemplate, userId: string) {
  if (task.default_assignee_id === userId) return true
  if (task.assignees?.some((assignee) => assignee.id === userId)) return true
  if (task.alignment_user_ids?.includes(userId)) return true
  return false
}

function mergeSystemTaskRows(base: SystemTaskTemplate[], extra: SystemTaskTemplate[]) {
  const rows = new Map<string, SystemTaskTemplate>()
  for (const task of base) rows.set(task.id, task)
  for (const task of extra) rows.set(task.id, task)
  return Array.from(rows.values())
}

function formatMeetingPrintLabel(meeting: Meeting) {
  const date = resolveMeetingDisplayDate(meeting)
  if (!date) return meeting.title || "Meeting"
  if (Number.isNaN(date.getTime())) return meeting.title || "Meeting"
  const timeLabel = date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })
  return `${timeLabel} ${meeting.title || "Meeting"}`
}

function periodFromDate(value?: string | null) {
  if (!value) return "AM"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "AM"
  return date.getHours() >= 12 ? "PM" : "AM"
}

function resolvePeriod(finishPeriod?: TaskFinishPeriod | null, dateValue?: string | null) {
  if (finishPeriod === "PM") return "PM"
  if (finishPeriod === "AM") return "AM"
  return "AM/PM"
}

export default function DepartmentKanban() {
  const departmentName = "Development"
  const departmentSlug = "development"
  const { apiFetch, user } = useAuth()
  const confirm = useConfirm()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const tabParam = searchParams.get("tab")
  const msParam = searchParams.get("ms")
  const normalizedTab = tabParam === "tasks" ? "no-project" : tabParam
  const isTabId = Boolean(normalizedTab && TABS.some((tab) => tab.id === normalizedTab))
  const returnToTasks = `${pathname}?tab=no-project`
  const printedAt = React.useMemo(() => new Date(), [])
  const printInitials = React.useMemo(
    () => initials(user?.full_name || user?.username || ""),
    [user?.full_name, user?.username]
  )
  const [department, setDepartment] = React.useState<Department | null>(null)
  const [departments, setDepartments] = React.useState<Department[]>([])
  const [projects, setProjects] = React.useState<Project[]>([])
  const [projectTitleLookup, setProjectTitleLookup] = React.useState<Map<string, string>>(new Map())
  const [projectMetaLookup, setProjectMetaLookup] = React.useState<
    Map<string, { title: string; department_id?: string | null }>
  >(new Map())
  const [projectMembers, setProjectMembers] = React.useState<Record<string, UserLookup[]>>({})
  const projectMembersRef = React.useRef<Record<string, UserLookup[]>>({})
  const bootstrapSystemTasksKeyRef = React.useRef<string | null>(null)
  const bootstrapInternalNoteDeptIdRef = React.useRef<string | null>(null)
  const bootstrapInternalNoteProjectsRef = React.useRef<Project[] | null>(null)
  const printContainerRef = React.useRef<HTMLDivElement | null>(null)
  const printMeasureRef = React.useRef<HTMLDivElement | null>(null)
  const [printPageMarkers, setPrintPageMarkers] = React.useState<Array<{ page: number; total: number; top: number }>>([])
  const [printPageMinHeight, setPrintPageMinHeight] = React.useState<number | null>(null)
  const [printTotalPages, setPrintTotalPages] = React.useState<number>(1)
  const [pendingPrint, setPendingPrint] = React.useState(false)
  const [systemTasks, setSystemTasks] = React.useState<SystemTaskTemplate[]>([])
  const [overviewSystemTasks, setOverviewSystemTasks] = React.useState<SystemTaskTemplate[]>([])
  const [closeTaskDialogOpen, setCloseTaskDialogOpen] = React.useState(false)
  const [taskToCloseId, setTaskToCloseId] = React.useState<string | null>(null)
  const [taskToCloseTemplate, setTaskToCloseTemplate] = React.useState<SystemTaskTemplate | null>(null)
  const [closeTaskComment, setCloseTaskComment] = React.useState("")
  const [closingTask, setClosingTask] = React.useState(false)
  const [departmentTasks, setDepartmentTasks] = React.useState<Task[]>([])
  const [noProjectTasks, setNoProjectTasks] = React.useState<Task[]>([])
  const [systemCreatedTasks, setSystemCreatedTasks] = React.useState<Task[]>([])
  const [crossDepartmentAssignedTasks, setCrossDepartmentAssignedTasks] = React.useState<Task[]>([])
  const [crossDepartmentConfirmTasks, setCrossDepartmentConfirmTasks] = React.useState<Task[]>([])
  const [users, setUsers] = React.useState<UserLookup[]>([])
  const [internalNotes, setInternalNotes] = React.useState<InternalNote[]>([])
  const [meetings, setMeetings] = React.useState<Meeting[]>([])
  const [myMeetings, setMyMeetings] = React.useState<Meeting[]>([])
  const [allDepartmentMeetings, setAllDepartmentMeetings] = React.useState<Meeting[]>([])
  const [msConnected, setMsConnected] = React.useState(false)
  const [msCanManage, setMsCanManage] = React.useState(false)
  const [msEvents, setMsEvents] = React.useState<MicrosoftEvent[]>([])
  const [loadingMsEvents, setLoadingMsEvents] = React.useState(false)
  const [checkingMsStatus, setCheckingMsStatus] = React.useState(false)
  const [loading, setLoading] = React.useState(true)
  const [loadingExtras, setLoadingExtras] = React.useState(false)
  const [viewMode, setViewMode] = React.useState<"department" | "mine">("department")
  useBrowserTabTitle(viewMode === "mine" ? "My View · Development" : "Development")
  React.useEffect(() => {
    if (searchParams.get("view") !== "mine") return
    const timer = window.setTimeout(() => setViewMode("mine"), 0)
    return () => window.clearTimeout(timer)
  }, [searchParams])
  const [activeTab, setActiveTab] = React.useState<TabId>(
    isTabId ? (normalizedTab as TabId) : "all"
  )
  const [allRange, setAllRange] = React.useState<AllRange>("today")
  const [allDateInput, setAllDateInput] = React.useState(() => todayInputValue())
  const [showAllDoneTasks, setShowAllDoneTasks] = React.useState(false)
  const [selectedUserId, setSelectedUserId] = React.useState<string>("__all__")
  const [fastTaskDateInput, setFastTaskDateInput] = React.useState(() => todayInputValue())
  const [showAllFastTasks, setShowAllFastTasks] = React.useState(false)
  const [dailyReport, setDailyReport] = React.useState<DailyReportResponse | null>(null)
  const [dailyReportOneHSlots, setDailyReportOneHSlots] = React.useState<Record<string, OneHReportSlot | null>>({})
  const [loadingDailyReport, setLoadingDailyReport] = React.useState(false)
  const [dailyReportCommentEdits, setDailyReportCommentEdits] = React.useState<Record<string, string>>({})
  const [savingDailyReportComments, setSavingDailyReportComments] = React.useState<Record<string, boolean>>({})
  const [exportingDailyReport, setExportingDailyReport] = React.useState(false)
  const [exportingInternalMeetings, setExportingInternalMeetings] = React.useState(false)
  const [taskChecklists, setTaskChecklists] = React.useState<Record<string, TaskChecklist | null>>({})
  const [taskChecklistLoading, setTaskChecklistLoading] = React.useState<Record<string, boolean>>({})
  const [taskChecklistOpen, setTaskChecklistOpen] = React.useState<Record<string, boolean>>({})
  const [gaTableEntry, setGaTableEntry] = React.useState<DailyReportGaEntry | null>(null)
  const [gaTableInput, setGaTableInput] = React.useState("")
  const [savingGaTable, setSavingGaTable] = React.useState(false)
  const [allUsersDailyReports, setAllUsersDailyReports] = React.useState<Map<string, DailyReportResponse>>(new Map())
  const [loadingAllUsersDailyReports, setLoadingAllUsersDailyReports] = React.useState(false)
  const dailyReportScrollRef = React.useRef<HTMLDivElement | null>(null)
  const dailyReportDragRef = React.useRef({ isDragging: false, startX: 0, startScrollLeft: 0 })
  const [isDraggingDailyReport, setIsDraggingDailyReport] = React.useState(false)
  const [showAllSystem, setShowAllSystem] = React.useState(false)
  const [systemDate, setSystemDate] = React.useState(() => new Date())
  const [showDailyUserReport, setShowDailyUserReport] = React.useState(false)
  const [dailyReportManualOrder, setDailyReportManualOrder] = React.useState<string[]>([])
  const [expandedDailyReportTitleIds, setExpandedDailyReportTitleIds] = React.useState<Record<string, boolean>>({})
  const [noteTitleByOriginId, setNoteTitleByOriginId] = React.useState<Record<string, string>>({})
  const [showFullDailyReportTable, setShowFullDailyReportTable] = React.useState(false)
  React.useEffect(() => {
    if (searchParams.get("daily") !== "full") return
    const timer = window.setTimeout(() => {
      setShowDailyUserReport(true)
      setShowFullDailyReportTable(true)
    }, 0)
    return () => window.clearTimeout(timer)
  }, [searchParams])
  const [dailyReportPeriodFilter, setDailyReportPeriodFilter] = React.useState<"all" | "am_side" | "pm_side">("all")
  const [dailyReportStatusFilter, setDailyReportStatusFilter] = React.useState<string[]>([])
  const [dragDailyReportRowId, setDragDailyReportRowId] = React.useState<string | null>(null)
  const [overDailyReportRowId, setOverDailyReportRowId] = React.useState<string | null>(null)
  const [savingOneHReportSlotTaskId, setSavingOneHReportSlotTaskId] = React.useState<string | null>(null)
  const [multiSelect, setMultiSelect] = React.useState(false)
  const [systemDepartmentId, setSystemDepartmentId] = React.useState("")
  const [systemFrequency, setSystemFrequency] = React.useState<SystemTaskTemplate["frequency"]>("DAILY")
  const [createProjectOpen, setCreateProjectOpen] = React.useState(false)
  const [creatingProject, setCreatingProject] = React.useState(false)
  const [projectTitle, setProjectTitle] = React.useState("")
  const [projectDescription, setProjectDescription] = React.useState("")
  const departmentCode = React.useMemo(
    () => (department?.code || department?.name || departmentName || "DEV").toUpperCase(),
    [department?.code, department?.name, departmentName]
  )
  const systemDateKey = React.useMemo(() => formatDateInput(systemDate), [systemDate])
  const cacheKey = React.useMemo(() => {
    const userId = user?.id || "anon"
    return `department:${departmentSlug}|user:${userId}|systemDate:${systemDateKey}|showTemplates:false`
  }, [departmentSlug, systemDateKey, user?.id])
  type DepartmentBootstrapPayload = {
    departments: Department[]
    department: Department | null
    users: UserLookup[]
    projects: Project[]
    systemTasks: SystemTaskTemplate[]
    overviewSystemTasks: SystemTaskTemplate[]
    departmentTasks: Task[]
    noProjectTasks: Task[]
    systemCreatedTasks: Task[]
    internalNotes: InternalNote[]
    meetings: Meeting[]
    allDepartmentMeetings?: Meeting[]
    systemDepartmentId: string
    systemTasksKey: string
    internalNoteDepartmentId: string | null
    internalNoteProjects: Project[]
  }
  const applyBootstrap = React.useCallback((payload: DepartmentBootstrapPayload) => {
    setDepartments(payload.departments)
    setDepartment(payload.department)
    setUsers(payload.users)
    setProjects(payload.projects)
    setSystemTasks(payload.systemTasks)
    setOverviewSystemTasks(payload.overviewSystemTasks)
    setDepartmentTasks(payload.departmentTasks)
    setNoProjectTasks(payload.noProjectTasks)
    setSystemCreatedTasks(payload.systemCreatedTasks)
    setInternalNotes(payload.internalNotes)
    setMeetings(payload.meetings)
    setAllDepartmentMeetings(payload.allDepartmentMeetings || [])
    setSystemDepartmentId(payload.systemDepartmentId)
    setInternalNoteProjects(payload.internalNoteProjects)
    bootstrapSystemTasksKeyRef.current = payload.systemTasksKey
    bootstrapInternalNoteDeptIdRef.current = payload.internalNoteDepartmentId
    bootstrapInternalNoteProjectsRef.current = payload.internalNoteProjects
  }, [])
  const [projectManagerId, setProjectManagerId] = React.useState("__unassigned__")
  const [projectMemberIds, setProjectMemberIds] = React.useState<string[]>([])
  const [selectMembersOpen, setSelectMembersOpen] = React.useState(false)
  const [projectStatus, setProjectStatus] = React.useState("TODO")
  const [projectDueDate, setProjectDueDate] = React.useState("")
  const [deletingProjectId, setDeletingProjectId] = React.useState<string | null>(null)
  const [deletingNoProjectTaskId, setDeletingNoProjectTaskId] = React.useState<string | null>(null)
  const [deletingAllTodayTaskId, setDeletingAllTodayTaskId] = React.useState<string | null>(null)
  const [editingTaskId, setEditingTaskId] = React.useState<string | null>(null)
  const [editTaskTitle, setEditTaskTitle] = React.useState("")
  const [editTaskDescription, setEditTaskDescription] = React.useState("")
  const [editTaskType, setEditTaskType] = React.useState<(typeof NO_PROJECT_TYPES)[number]["id"]>("normal")
  const [editTaskStatus, setEditTaskStatus] = React.useState<string>("TODO")
  const [editTaskConfirmationAssigneeId, setEditTaskConfirmationAssigneeId] = React.useState("")
  const [editTaskStartDate, setEditTaskStartDate] = React.useState("")
  const [editTaskDueDate, setEditTaskDueDate] = React.useState("")
  const [editTaskFinishPeriod, setEditTaskFinishPeriod] = React.useState<TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE>(FINISH_PERIOD_NONE_VALUE)
  const [editTaskDeadlineImportant, setEditTaskDeadlineImportant] = React.useState(false)
  const [editTaskAssignees, setEditTaskAssignees] = React.useState<string[]>([])
  const [editTaskInitialAssignees, setEditTaskInitialAssignees] = React.useState<string[]>([])
  const [selectEditTaskAssigneesOpen, setSelectEditTaskAssigneesOpen] = React.useState(false)
  const [updatingTask, setUpdatingTask] = React.useState(false)
  const [allTodayEditingTaskId, setAllTodayEditingTaskId] = React.useState<string | null>(null)
  const [allTodayPlanningDetail, setAllTodayPlanningDetail] = React.useState<{
    taskId: string
    brief: Task["planning_brief"]
    loading: boolean
  } | null>(null)
  const [allTodayEditTitle, setAllTodayEditTitle] = React.useState("")
  const [allTodayEditDescription, setAllTodayEditDescription] = React.useState("")
  const [allTodayEditType, setAllTodayEditType] = React.useState<AllTodayEditTypeId>("normal")
  const [allTodayEditStatus, setAllTodayEditStatus] = React.useState<string>("TODO")
  const [allTodayEditConfirmationAssigneeId, setAllTodayEditConfirmationAssigneeId] = React.useState("")
  const [allTodayEditStartDate, setAllTodayEditStartDate] = React.useState("")
  const [allTodayEditDueDate, setAllTodayEditDueDate] = React.useState("")
  const [allTodayEditFinishPeriod, setAllTodayEditFinishPeriod] = React.useState<TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE>(FINISH_PERIOD_NONE_VALUE)
  const [allTodayEditDeadlineImportant, setAllTodayEditDeadlineImportant] = React.useState(false)
  const [allTodayEditCompletionNote, setAllTodayEditCompletionNote] = React.useState("")
  const [allTodayUpdating, setAllTodayUpdating] = React.useState(false)
  const [markingWaitingTaskId, setMarkingWaitingTaskId] = React.useState<string | null>(null)
  const confirmerCandidates = React.useMemo(() => getConfirmerCandidates(users), [users])
  const [editingSystemTaskId, setEditingSystemTaskId] = React.useState<string | null>(null)
  const [editingSystemDateSource, setEditingSystemDateSource] = React.useState("")
  const [editingSystemDateTarget, setEditingSystemDateTarget] = React.useState("")
  const [editingSystemDateTitle, setEditingSystemDateTitle] = React.useState("")
  const [savingSystemDateOverride, setSavingSystemDateOverride] = React.useState(false)
  const [showTitleWarning, setShowTitleWarning] = React.useState(false)
  const [pendingProjectTitle, setPendingProjectTitle] = React.useState("")
  const [meetingTitle, setMeetingTitle] = React.useState("")
  const [meetingTimeFilter, setMeetingTimeFilter] = React.useState<"today" | "tomorrow" | "this_week" | "next_week" | "future">("today")
  const [meetingPlatform, setMeetingPlatform] = React.useState("")
  const [meetingStartsAt, setMeetingStartsAt] = React.useState("")
  const [meetingStartTime, setMeetingStartTime] = React.useState("")
  const [meetingUrl, setMeetingUrl] = React.useState("")
  const [meetingRecurrenceType, setMeetingRecurrenceType] = React.useState<"none" | "weekly" | "monthly">("none")
  const [meetingRecurrenceDaysOfWeek, setMeetingRecurrenceDaysOfWeek] = React.useState<number[]>([])
  const [meetingRecurrenceDaysOfMonth, setMeetingRecurrenceDaysOfMonth] = React.useState<number[]>([])
  const [meetingParticipantIds, setMeetingParticipantIds] = React.useState<string[]>([])
  const [meetingProjectId, setMeetingProjectId] = React.useState("__none__")
  const [creatingMeeting, setCreatingMeeting] = React.useState(false)
  const [showAddMeetingForm, setShowAddMeetingForm] = React.useState(false)
  const [internalMeetingTaskDialogOpen, setInternalMeetingTaskDialogOpen] = React.useState(false)
  const [internalMeetingTaskTitle, setInternalMeetingTaskTitle] = React.useState("")
  const [internalMeetingTaskPlatform, setInternalMeetingTaskPlatform] = React.useState("")
  const [internalMeetingTaskStartsAt, setInternalMeetingTaskStartsAt] = React.useState("")
  const [creatingInternalMeetingFromTask, setCreatingInternalMeetingFromTask] = React.useState(false)
  const [editingMeetingId, setEditingMeetingId] = React.useState<string | null>(null)
  const [editMeetingTitle, setEditMeetingTitle] = React.useState("")
  const [editMeetingPlatform, setEditMeetingPlatform] = React.useState("")
  const [editMeetingStartsAt, setEditMeetingStartsAt] = React.useState("")
  const [editMeetingStartTime, setEditMeetingStartTime] = React.useState("")
  const [editMeetingUrl, setEditMeetingUrl] = React.useState("")
  const [editMeetingRecurrenceType, setEditMeetingRecurrenceType] = React.useState<"none" | "weekly" | "monthly">("none")
  const [editMeetingRecurrenceDaysOfWeek, setEditMeetingRecurrenceDaysOfWeek] = React.useState<number[]>([])
  const [editMeetingRecurrenceDaysOfMonth, setEditMeetingRecurrenceDaysOfMonth] = React.useState<number[]>([])
  const [editMeetingParticipantIds, setEditMeetingParticipantIds] = React.useState<string[]>([])
  const [editMeetingProjectId, setEditMeetingProjectId] = React.useState("__none__")
  const [savingMeeting, setSavingMeeting] = React.useState(false)
  const [showParticipantDialog, setShowParticipantDialog] = React.useState(false)
  const [showEditParticipantDialog, setShowEditParticipantDialog] = React.useState(false)
  const [internalSlot, setInternalSlot] = React.useState<keyof typeof INTERNAL_MEETING.slots>("M1")
  const [internalMeetingChecklistId, setInternalMeetingChecklistId] = React.useState<string | null>(null)
  const [internalMeetingItems, setInternalMeetingItems] = React.useState<ChecklistItem[]>([])
  const [newInternalMeetingItem, setNewInternalMeetingItem] = React.useState("")
  const [addingInternalMeetingItem, setAddingInternalMeetingItem] = React.useState(false)
  const [editingInternalMeetingItemId, setEditingInternalMeetingItemId] = React.useState<string | null>(null)
  const [editingInternalMeetingItem, setEditingInternalMeetingItem] = React.useState("")
  const [editingInternalMeetingItemPosition, setEditingInternalMeetingItemPosition] = React.useState("1")
  const [savingInternalMeetingItem, setSavingInternalMeetingItem] = React.useState(false)
  const [noProjectOpen, setNoProjectOpen] = React.useState(false)
  const [noProjectTitle, setNoProjectTitle] = React.useState("")
  const [noProjectDescription, setNoProjectDescription] = React.useState("")
  const [noProjectType, setNoProjectType] = React.useState<(typeof NO_PROJECT_TYPES)[number]["id"]>("normal")
  const [noProjectAssignees, setNoProjectAssignees] = React.useState<string[]>([])
  const [selectNoProjectAssigneesOpen, setSelectNoProjectAssigneesOpen] = React.useState(false)
  const [noProjectStartDate, setNoProjectStartDate] = React.useState("")
  const [noProjectDueDate, setNoProjectDueDate] = React.useState("")
  const [noProjectDeadlineImportant, setNoProjectDeadlineImportant] = React.useState(false)
  const [noProjectFinishPeriod, setNoProjectFinishPeriod] = React.useState<TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE>(
    FINISH_PERIOD_NONE_VALUE
  )
  const [creatingNoProject, setCreatingNoProject] = React.useState(false)
  const [internalNoteOpen, setInternalNoteOpen] = React.useState(false)
  const [addingInternalNote, setAddingInternalNote] = React.useState(false)
  const [internalNoteTitle, setInternalNoteTitle] = React.useState("")
  const [internalNoteDescription, setInternalNoteDescription] = React.useState("")
  const [internalNoteDepartmentId, setInternalNoteDepartmentId] = React.useState("")
  const [internalNoteProjectId, setInternalNoteProjectId] = React.useState("")
  const [internalNoteProjects, setInternalNoteProjects] = React.useState<Project[]>([])
  const [loadingInternalNoteProjects, setLoadingInternalNoteProjects] = React.useState(false)
  const [internalNoteToUserIds, setInternalNoteToUserIds] = React.useState<string[]>([])
  const [editInternalNoteOpen, setEditInternalNoteOpen] = React.useState(false)
  const [editingInternalNoteIds, setEditingInternalNoteIds] = React.useState<string[]>([])
  const [savingInternalNoteEdit, setSavingInternalNoteEdit] = React.useState(false)
  const [editInternalNoteTitle, setEditInternalNoteTitle] = React.useState("")
  const [editInternalNoteDescription, setEditInternalNoteDescription] = React.useState("")
  const [editInternalNoteDepartmentId, setEditInternalNoteDepartmentId] = React.useState("")
  const [editInternalNoteProjectId, setEditInternalNoteProjectId] = React.useState("")
  const [editInternalNoteProjects, setEditInternalNoteProjects] = React.useState<Project[]>([])
  const [loadingEditInternalNoteProjects, setLoadingEditInternalNoteProjects] = React.useState(false)
  const [editInternalNoteToUserIds, setEditInternalNoteToUserIds] = React.useState<string[]>([])
  const [internalNotesFilter, setInternalNotesFilter] = React.useState<"all" | "done" | "undone">("all")
  const [updatingInternalNoteIds, setUpdatingInternalNoteIds] = React.useState<string[]>([])
  const [printRange, setPrintRange] = React.useState<"today" | "week">("week")

  const loadBootstrapData = React.useCallback(
    async (options: { silent: boolean }) => {
      const { silent } = options
      if (!silent) setLoading(true)
      try {
        const [depRes, usersRes] = await Promise.all([
          apiFetch("/departments"),
          apiFetch("/users/lookup"),
        ])
        if (!depRes.ok) {
          console.error("Failed to load departments:", depRes.status)
          return
        }
        const deps = (await depRes.json()) as Department[]
        const dep = deps.find((d) => d.name === departmentName) || null
        if (!dep) return

        let allUsers: UserLookup[] = []
        if (usersRes.ok) {
          allUsers = (await usersRes.json()) as UserLookup[]
        }

        // Publish the department as soon as it is known so the daily report
        // and other per-department requests start alongside the heavy
        // bootstrap below instead of waiting for it to finish.
        bootstrapSystemTasksKeyRef.current = `${dep.id}|${systemDateKey}`
        setDepartments(deps)
        setDepartment(dep)
        setUsers(allUsers)

        if (!silent) setLoadingExtras(true)
        // Show the page now; lists fill in when the bootstrap below arrives.
        if (!silent) setLoading(false)
        const [projRes, sysRes, allSysRes, tasksRes, internalRes, meetingsRes, allDepartmentMeetingsRes] = await Promise.all([
          apiFetch(`/projects?department_id=${dep.id}`),
          apiFetch(`/system-tasks?department_id=${dep.id}&occurrence_date=${systemDateKey}&include_overdue=true`),
          apiFetch(`/system-tasks?department_id=${dep.id}`),
          apiFetch(`/tasks?include_done=true&department_id=${dep.id}`),
          apiFetch(`/internal-notes?department_id=${dep.id}`),
          apiFetch(`/meetings?department_id=${dep.id}`),
          apiFetch("/meetings?include_all_departments=true"),
        ])
        const projects = projRes.ok ? ((await projRes.json()) as Project[]) : []
        const systemTasks = sysRes.ok ? ((await sysRes.json()) as SystemTaskTemplate[]) : []
        const allSystemTasks = allSysRes.ok ? ((await allSysRes.json()) as SystemTaskTemplate[]) : []
        const taskRows = tasksRes.ok ? ((await tasksRes.json()) as Task[]) : []
        const internalNotes = internalRes.ok ? ((await internalRes.json()) as InternalNote[]) : []
        const meetings = meetingsRes.ok ? ((await meetingsRes.json()) as Meeting[]) : []
        const allDepartmentMeetings = allDepartmentMeetingsRes.ok
          ? ((await allDepartmentMeetingsRes.json()) as Meeting[])
          : meetings
        const nonSystemTasks = taskRows.filter((t) => !t.system_template_origin_id)
        const systemTaskRows = taskRows.filter((t) => Boolean(t.system_template_origin_id))
        setDepartments(deps)
        setDepartment(dep)
        setUsers(allUsers)
        setProjects(projects)
        setSystemTasks(systemTasks)
        setOverviewSystemTasks(allSystemTasks)
        setDepartmentTasks(nonSystemTasks)
        setNoProjectTasks(nonSystemTasks.filter(isNoProjectTask))
        setSystemCreatedTasks(systemTaskRows)
        setSystemDepartmentId(dep.id)
        setInternalNoteProjects(projects)
        bootstrapSystemTasksKeyRef.current = `${dep.id}|${systemDateKey}`
        bootstrapInternalNoteDeptIdRef.current = dep.id
        bootstrapInternalNoteProjectsRef.current = projects
        if (!silent) setLoading(false)
        setInternalNotes(internalNotes)
        setMeetings(meetings)
        setAllDepartmentMeetings(allDepartmentMeetings)
        const payload: DepartmentBootstrapPayload = {
          departments: deps,
          department: dep,
          users: allUsers,
          projects,
          systemTasks,
          overviewSystemTasks: allSystemTasks,
          departmentTasks: nonSystemTasks,
          noProjectTasks: nonSystemTasks.filter(isNoProjectTask),
          systemCreatedTasks: systemTaskRows,
          internalNotes,
          meetings,
          allDepartmentMeetings,
          systemDepartmentId: dep.id,
          systemTasksKey: `${dep.id}|${systemDateKey}`,
          internalNoteDepartmentId: dep.id,
          internalNoteProjects: projects,
        }
        setDepartmentBootstrapCache(cacheKey, payload)
        void writePersistentPageCache(cacheKey, payload)
      } catch (error) {
        console.error("Error loading department data:", error)
        toast.error("Failed to load department data. Please check if the backend server is running.")
      } finally {
        if (!silent) setLoading(false)
        if (!silent) setLoadingExtras(false)
      }
    },
    [apiFetch, cacheKey, departmentName, systemDateKey]
  )

  React.useEffect(() => {
    const cached = getDepartmentBootstrapCache<DepartmentBootstrapPayload>(cacheKey)
    if (cached) {
      applyBootstrap(cached)
      setLoading(false)
      // Cached task data is only a fast first paint. Always revalidate so a
      // task created/assigned in GA Notes cannot stay missing for five minutes.
      void loadBootstrapData({ silent: true })
      return
    }
    let cancelled = false
    // Not in memory (reload or new tab): paint from the copy saved on this
    // device, if any, and revalidate silently behind it like the path above.
    void readPersistentPageCache<DepartmentBootstrapPayload>(cacheKey).then((persisted) => {
      if (cancelled) return
      if (persisted) {
        applyBootstrap(persisted)
        setLoading(false)
        void loadBootstrapData({ silent: true })
        return
      }
      void loadBootstrapData({ silent: false })
    })
    return () => {
      cancelled = true
    }
  }, [applyBootstrap, cacheKey, loadBootstrapData])

  React.useEffect(() => {
    if (!department?.id) return
    const systemTasksKey = `${department.id}|${formatDateInput(systemDate)}`
    if (bootstrapSystemTasksKeyRef.current === systemTasksKey) return
    const loadSystemTasks = async () => {
      const [res, allRes] = await Promise.all([
        apiFetch(`/system-tasks?department_id=${department.id}&occurrence_date=${formatDateInput(systemDate)}&include_overdue=true`),
        apiFetch(`/system-tasks?department_id=${department.id}`),
      ])
      if (res.ok) {
        setSystemTasks((await res.json()) as SystemTaskTemplate[])
      }
      if (allRes.ok) {
        setOverviewSystemTasks((await allRes.json()) as SystemTaskTemplate[])
      }
    }
    void loadSystemTasks()
  }, [apiFetch, department?.id, systemDate])

  React.useEffect(() => {
    if (viewMode !== "mine" || !user?.id) return
    const loadAssignedSystemTasks = async () => {
      const params = new URLSearchParams({
        assigned_to: user.id,
        occurrence_date: formatDateInput(systemDate),
        include_overdue: "true",
      })
      const res = await apiFetch(`/system-tasks?${params.toString()}`)
      if (res.ok) {
        const assignedRows = (await res.json()) as SystemTaskTemplate[]
        setSystemTasks((prev) => mergeSystemTaskRows(prev, assignedRows))
      }
    }
    void loadAssignedSystemTasks()
  }, [apiFetch, systemDate, user?.id, viewMode])

  React.useEffect(() => {
    if (!internalNoteDepartmentId && department?.id) {
      setInternalNoteDepartmentId(department.id)
    }
  }, [department?.id, internalNoteDepartmentId])

  React.useEffect(() => {
    const loadProjects = async () => {
      if (!internalNoteDepartmentId) {
        setInternalNoteProjects([])
        return
      }
      const bootstrapProjects = bootstrapInternalNoteProjectsRef.current
      if (bootstrapInternalNoteDeptIdRef.current === internalNoteDepartmentId && bootstrapProjects) {
        setInternalNoteProjects(bootstrapProjects)
        return
      }
      setLoadingInternalNoteProjects(true)
      try {
        const res = await apiFetch(`/projects?department_id=${internalNoteDepartmentId}`)
        if (!res.ok) {
          if (res.status !== 401 && res.status !== 403) {
            console.error("Failed to load department projects:", res.status)
          }
          setInternalNoteProjects([])
          return
        }
        setInternalNoteProjects((await res.json()) as Project[])
      } catch (error) {
        console.error("Error loading department projects:", error)
        setInternalNoteProjects([])
      } finally {
        setLoadingInternalNoteProjects(false)
      }
    }
    void loadProjects()
  }, [apiFetch, internalNoteDepartmentId])

  React.useEffect(() => {
    const loadProjects = async () => {
      if (!editInternalNoteDepartmentId) {
        setEditInternalNoteProjects([])
        return
      }
      if (editInternalNoteDepartmentId === internalNoteDepartmentId) {
        setEditInternalNoteProjects(internalNoteProjects)
        return
      }
      setLoadingEditInternalNoteProjects(true)
      try {
        const res = await apiFetch(`/projects?department_id=${editInternalNoteDepartmentId}`)
        if (!res.ok) {
          if (res.status !== 401 && res.status !== 403) {
            console.error("Failed to load department projects:", res.status)
          }
          setEditInternalNoteProjects([])
          return
        }
        setEditInternalNoteProjects((await res.json()) as Project[])
      } catch (error) {
        console.error("Error loading department projects:", error)
        setEditInternalNoteProjects([])
      } finally {
        setLoadingEditInternalNoteProjects(false)
      }
    }
    void loadProjects()
  }, [apiFetch, editInternalNoteDepartmentId, internalNoteDepartmentId, internalNoteProjects])

  React.useEffect(() => {
    projectMembersRef.current = projectMembers
  }, [projectMembers])

  React.useEffect(() => {
    const handleBeforePrint = () => {
      const container = printContainerRef.current
      if (!container) return
      const dpi = 96
      const measuredHeight = printMeasureRef.current?.offsetHeight
      const pageHeightPx = measuredHeight ?? (8.5 * dpi - (0.25 + 0.35) * dpi)
      const footerOffsetPx = 0.2 * dpi
      const totalPages = Math.max(1, Math.ceil(container.scrollHeight / pageHeightPx))
      const markers = Array.from({ length: totalPages }, (_, index) => ({
        page: index + 1,
        total: totalPages,
        top: pageHeightPx * (index + 1) - footerOffsetPx,
      }))
      setPrintPageMarkers(markers)
      setPrintPageMinHeight(totalPages * pageHeightPx)
      setPrintTotalPages(totalPages)
    }
    const handleAfterPrint = () => {
      setPrintPageMarkers([])
      setPrintPageMinHeight(null)
      setPrintTotalPages(1)
    }
    window.addEventListener("beforeprint", handleBeforePrint)
    window.addEventListener("afterprint", handleAfterPrint)
    const mediaQuery = window.matchMedia("print")
    const handleMediaChange = (event: MediaQueryListEvent) => {
      if (event.matches) {
        handleBeforePrint()
      } else {
        handleAfterPrint()
      }
    }
    if (typeof mediaQuery.addEventListener === "function") {
      mediaQuery.addEventListener("change", handleMediaChange)
    } else {
      mediaQuery.addListener(handleMediaChange)
    }
    return () => {
      window.removeEventListener("beforeprint", handleBeforePrint)
      window.removeEventListener("afterprint", handleAfterPrint)
      if (typeof mediaQuery.removeEventListener === "function") {
        mediaQuery.removeEventListener("change", handleMediaChange)
      } else {
        mediaQuery.removeListener(handleMediaChange)
      }
    }
  }, [])

  React.useEffect(() => {
    if (activeTab !== "all" && activeTab !== "projects") return
    if (!projects.length) return
    let cancelled = false
    const loadMembers = async () => {
      const missing = projects.filter((project) => !projectMembersRef.current[project.id])
      if (!missing.length) return
      const params = new URLSearchParams()
      for (const project of missing) params.append("project_ids", project.id)
      const res = await apiFetch(`/project-members/batch?${params.toString()}`)
      if (!res.ok) return
      const results = (await res.json()) as Array<{ project_id: string; members: UserLookup[] }>
      if (cancelled) return
      setProjectMembers((prev) => {
        const next = { ...prev }
        for (const result of results) {
          next[result.project_id] = result.members
        }
        return next
      })
    }
    void loadMembers()
    return () => {
      cancelled = true
    }
  }, [activeTab, projects, apiFetch])

  React.useEffect(() => {
    if (!department) return
    let cancelled = false
    const loadInternalMeetingChecklist = async () => {
      try {
        const res = await apiFetch(
          `/checklists?group_key=${INTERNAL_MEETING_GROUP_KEY}&include_items=true`
        )
        if (!res.ok) return
        const checklist = (await res.json()) as {
          id: string
          items?: ChecklistItem[]
        }[]
        let selected = checklist[0]
        let createdChecklist = false
        if (!selected) {
          const createRes = await apiFetch("/checklists", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              title: INTERNAL_MEETING.title,
              note: INTERNAL_MEETING.title,
              group_key: INTERNAL_MEETING_GROUP_KEY,
            }),
          })
          if (!createRes.ok) return
          selected = (await createRes.json()) as { id: string }
          createdChecklist = true
        }
        if (cancelled) return
        setInternalMeetingChecklistId(selected.id)
        let items = selected.items || []

        try {
          await apiFetch("/internal-meeting-sessions/ensure", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ checklist_id: selected.id }),
          })
          const refreshedRes = await apiFetch(`/checklist-items?checklist_id=${selected.id}`)
          if (refreshedRes.ok) {
            items = (await refreshedRes.json()) as ChecklistItem[]
          }
        } catch (error) {
          console.error("Failed to ensure internal meeting session", error)
        }

        // Remove obsolete seeded checklist items that should no longer appear.
        const itemsToDelete = ["dssdgsdg"]
        const deletePromises: Promise<Response>[] = []
        for (const item of items) {
          const itemTitle = (item.title || "").trim()
          const normalizedTitle = itemTitle.toLowerCase()
          if (
            itemsToDelete.some((toDelete) => normalizedTitle === toDelete.toLowerCase()) ||
            INTERNAL_MEETING_ARCHIVED_CHECKLIST_TITLES.has(normalizedTitle)
          ) {
            deletePromises.push(apiFetch(`/checklist-items/${item.id}`, { method: "DELETE" }))
          }
        }
        if (deletePromises.length > 0) {
          await Promise.all(deletePromises)
          // Reload items after deletion
          const reloadRes = await apiFetch(`/checklist-items?checklist_id=${selected.id}`)
          if (reloadRes.ok) {
            items = (await reloadRes.json()) as ChecklistItem[]
          }
        }

        // IMPORTANT: Only seed defaults when the checklist is first created (or truly empty).
        // Otherwise, deleting a default item would cause it to be re-created on the next reload.
        const shouldSeedDefaults = createdChecklist || items.length === 0
        if (!shouldSeedDefaults) {
          if (cancelled) return
          setInternalMeetingItems(items)
          return
        }

        const missingDefaultItems: Array<{
          day: keyof typeof INTERNAL_MEETING.slots
          title: string
          position: number
        }> = []

        for (const slot of Object.keys(INTERNAL_MEETING.slots) as Array<keyof typeof INTERNAL_MEETING.slots>) {
          const slotItems = items.filter((item) => resolveInternalMeetingSlot(item.day) === slot)
          const existingTitles = new Set(
            slotItems
              .map((item) => (item.title || "").trim().toLowerCase())
              .filter(Boolean)
          )
          let nextPosition =
            slotItems.reduce((max, item) => Math.max(max, item.position ?? 0), -1) + 1

          for (const defaultTitle of INTERNAL_MEETING.slots[slot].items) {
            const normalizedTitle = defaultTitle.trim().toLowerCase()
            if (existingTitles.has(normalizedTitle)) continue
            missingDefaultItems.push({
              day: slot,
              title: defaultTitle,
              position: nextPosition,
            })
            existingTitles.add(normalizedTitle)
            nextPosition += 1
          }
        }

        if (missingDefaultItems.length > 0) {
          await Promise.all(
            missingDefaultItems.map((item) =>
              apiFetch("/checklist-items", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  checklist_id: selected.id,
                  item_type: "CHECKBOX",
                  path: "INTERNAL_MEETINGS",
                  day: item.day,
                  title: item.title,
                  is_checked: false,
                  position: item.position,
                }),
              })
            )
          )

          const reloadRes = await apiFetch(`/checklist-items?checklist_id=${selected.id}`)
          if (reloadRes.ok) {
            items = (await reloadRes.json()) as ChecklistItem[]
          }
        }

        if (cancelled) return
        setInternalMeetingItems(items)
      } catch (error) {
        console.error("Failed to load internal meetings checklist", error)
      }
    }
    void loadInternalMeetingChecklist()
    return () => {
      cancelled = true
    }
  }, [apiFetch, department])

  React.useEffect(() => {
    const archivedMeetings = meetings.filter((meeting) =>
      INTERNAL_MEETING_ARCHIVED_MEETING_TITLES.has((meeting.title || "").trim().toLowerCase())
    )
    if (!archivedMeetings.length) return

    let cancelled = false

    const removeArchivedMeetings = async () => {
      setMeetings((prev) =>
        prev.filter((meeting) => !INTERNAL_MEETING_ARCHIVED_MEETING_TITLES.has((meeting.title || "").trim().toLowerCase()))
      )

      for (const meeting of archivedMeetings) {
        const res = await apiFetch(`/meetings/${meeting.id}`, { method: "DELETE" })
        if (!res.ok && !cancelled) {
          console.error("Failed to delete archived internal meeting", meeting.id)
        }
      }
    }

    void removeArchivedMeetings()

    return () => {
      cancelled = true
    }
  }, [apiFetch, meetings])

  React.useEffect(() => {
    if (isTabId) {
      setActiveTab(normalizedTab as TabId)
    }
  }, [isTabId, normalizedTab])

  const departmentMap = React.useMemo(() => new Map(departments.map((dep) => [dep.id, dep])), [departments])
  const userMap = React.useMemo(() => new Map(users.map((u) => [u.id, u])), [users])
  const isGaTask = React.useCallback(
    (task: Task | SystemTaskTemplate) => {
      if ("ga_note_origin_id" in task && task.ga_note_origin_id) return true
      const createdById = task.created_by
      if (!createdById) return false
      const creator = userMap.get(createdById)
      if (!creator) return false
      const label = creator.full_name || creator.username || ""
      if (!label) return false
      return getInitials(label) === "GA"
    },
    [userMap]
  )
  const taskAssigneeLabels = React.useCallback(
    (task: Task) => {
      const ids = new Set<string>()
      if (task.assigned_to) ids.add(task.assigned_to)
      if (task.assignees) {
        for (const assignee of task.assignees) {
          if (assignee.id) ids.add(assignee.id)
        }
      }
      if (!ids.size) return ["Unassigned"]
      return Array.from(ids).map((userId) => {
        const userFromMap = userMap.get(userId)
        if (userFromMap) return assigneeLabel(userFromMap)
        const assigneeFromArray = task.assignees?.find((a) => a.id === userId)
      return assigneeFromArray?.full_name || assigneeFromArray?.username || "Unknown"
    })
    },
    [userMap]
  )
  const taskAssigneeInitials = React.useCallback(
    (task: Task) => {
      const koUserId = controlKoUserId(task)
      if (koUserId) {
        const koUser = userMap.get(koUserId)
        const koAssignee = task.assignees?.find((assignee) => assignee.id === koUserId)
        const label = koUser
          ? assigneeLabel(koUser)
          : (koAssignee?.full_name || koAssignee?.username || "-")
        const value = initials(label)
        return value && value !== "-" ? [{ id: koUserId, label, value }] : []
      }

      const ids = new Set<string>()
      if (task.assigned_to) ids.add(task.assigned_to)
      if (task.assignees) {
        for (const assignee of task.assignees) {
          if (assignee.id) ids.add(assignee.id)
        }
      }
      return Array.from(ids)
        .map((userId) => {
          const userFromMap = userMap.get(userId)
          const assigneeFromArray = task.assignees?.find((a) => a.id === userId)
          const label = userFromMap
            ? assigneeLabel(userFromMap)
            : (assigneeFromArray?.full_name || assigneeFromArray?.username || "-")
          const value = initials(label)
          return { id: userId, label, value }
        })
        .filter((item) => item.value && item.value !== "-")
    },
    [userMap]
  )
  const systemAssigneeInitials = React.useCallback(
    (template: SystemTaskTemplate) => {
      const ids = new Set<string>()
      if (template.assignees?.length) {
        for (const assignee of template.assignees) {
          if (assignee.id) ids.add(assignee.id)
        }
      } else if (template.default_assignee_id) {
        ids.add(template.default_assignee_id)
      }
      return Array.from(ids)
        .map((userId) => {
          const userFromMap = userMap.get(userId)
          const assigneeFromArray = template.assignees?.find((a) => a.id === userId)
          const label = userFromMap
            ? assigneeLabel(userFromMap)
            : (assigneeFromArray?.full_name || assigneeFromArray?.username || "-")
          const value = initials(label)
          return { id: userId, label, value }
        })
        .filter((item) => item.value && item.value !== "-")
    },
    [userMap]
  )
  const departmentUsers = React.useMemo(
    () => (department ? users.filter((u) => u.department_id === department.id) : []),
    [department, users]
  )
  const weeklyNotesColumns = Math.max(1, departmentUsers.length)
  const noProjectAssigneeLabel = React.useMemo(() => {
    if (noProjectAssignees.length === 0) return "Unassigned"
    if (users.length && noProjectAssignees.length === users.length) return "All users"
    if (noProjectAssignees.length === 1) {
      const selected = users.find((u) => u.id === noProjectAssignees[0])
      return selected?.full_name || selected?.username || "1 selected"
    }
    return `${noProjectAssignees.length} selected`
  }, [users, noProjectAssignees])
  const editTaskAssigneeLabel = React.useMemo(() => {
    if (editTaskAssignees.length === 0) return "Unassigned"
    if (users.length && editTaskAssignees.length === users.length) return "All users"
    if (editTaskAssignees.length === 1) {
      const selected = users.find((u) => u.id === editTaskAssignees[0])
      return selected?.full_name || selected?.username || "1 selected"
    }
    return `${editTaskAssignees.length} selected`
  }, [users, editTaskAssignees])
  const editingGaTask = Boolean(
    editingTaskId && noProjectTasks.some(
      (task) => task.id === editingTaskId && (task.ga_note_origin_id || task.plan_note_origin_id)
    )
  )
  const editingPlanTask = Boolean(
    editingTaskId && noProjectTasks.some((task) => task.id === editingTaskId && task.plan_note_origin_id)
  )
  const todayDate = React.useMemo(() => new Date(), [])
  const canceledTodayMeetings = useCanceledMeetings(toDateInputValue(todayDate))
  const todayIso = React.useMemo(() => todayDate.toISOString().slice(0, 10), [todayDate])
  const tomorrowDate = React.useMemo(
    () => new Date(todayDate.getFullYear(), todayDate.getMonth(), todayDate.getDate() + 1),
    [todayDate]
  )
  const selectedAllDate = React.useMemo(
    () => dateInputToDate(allDateInput) ?? todayDate,
    [allDateInput, todayDate]
  )
  const selectedFastTaskDate = React.useMemo(
    () => dateInputToDate(fastTaskDateInput) ?? todayDate,
    [fastTaskDateInput, todayDate]
  )
  const weekStart = React.useMemo(() => startOfWeekMonday(todayDate), [todayDate])
  const weekEnd = React.useMemo(
    () => new Date(weekStart.getFullYear(), weekStart.getMonth(), weekStart.getDate() + 4),
    [weekStart]
  )
  const weekDates = React.useMemo(() => {
    const start = startOfWeekMonday(todayDate)
    return Array.from({ length: 5 }, (_, index) => {
      return new Date(start.getFullYear(), start.getMonth(), start.getDate() + index)
    })
  }, [todayDate])
  const pastSevenDaysStart = React.useMemo(
    () => new Date(todayDate.getFullYear(), todayDate.getMonth(), todayDate.getDate() - 6),
    [todayDate]
  )
  const nextWeekStart = React.useMemo(
    () => new Date(weekStart.getFullYear(), weekStart.getMonth(), weekStart.getDate() + 7),
    [weekStart]
  )
  const nextWeekEnd = React.useMemo(
    () => new Date(nextWeekStart.getFullYear(), nextWeekStart.getMonth(), nextWeekStart.getDate() + 4),
    [nextWeekStart]
  )
  const nextWeekDates = React.useMemo(() => {
    return Array.from({ length: 5 }, (_, index) => {
      return new Date(nextWeekStart.getFullYear(), nextWeekStart.getMonth(), nextWeekStart.getDate() + index)
    })
  }, [nextWeekStart])
  const selectedAllHighlightDate = React.useMemo(() => {
    if (allRange === "today") return todayDate
    if (allRange === "tomorrow") return tomorrowDate
    if (allRange === "date") return selectedAllDate
    return null
  }, [allRange, selectedAllDate, todayDate, tomorrowDate])
  const selectedAllReportDate = React.useMemo(() => {
    if (allRange === "tomorrow") return tomorrowDate
    if (allRange === "date") return selectedAllDate
    return todayDate
  }, [allRange, selectedAllDate, todayDate, tomorrowDate])
  const selectedAllReportIso = React.useMemo(
    () => formatDateInput(selectedAllReportDate),
    [selectedAllReportDate]
  )
  const selectedAllReportLabel = React.useMemo(() => {
    if (allRange === "tomorrow") return "Tomorrow"
    if (allRange === "date") return formatDateDMY(selectedAllDate)
    return null
  }, [allRange, selectedAllDate])
  const dailyReportHeading = selectedAllReportLabel ? `Daily Report - ${selectedAllReportLabel}` : "Daily Report"
  const isTaskStartingOnSelectedAllDate = React.useCallback(
    (task: Task) => {
      if (!task.start_date) return false
      const startDate = toDate(task.start_date)
      return Boolean(startDate && selectedAllHighlightDate && isSameDay(startDate, selectedAllHighlightDate))
    },
    [selectedAllHighlightDate]
  )
  const isTaskDueOnSelectedAllDate = React.useCallback(
    (task: Task) => {
      if (!task.is_deadline_important) return false
      if (!task.due_date) return false
      const dueDate = toDate(task.due_date)
      return Boolean(dueDate && selectedAllHighlightDate && isSameDay(dueDate, selectedAllHighlightDate))
    },
    [selectedAllHighlightDate]
  )
  const isDateStartingOnSelectedAllDate = React.useCallback(
    (value?: string | null) => {
      if (!value || !selectedAllHighlightDate) return false
      const date = toDate(value)
      return date ? isSameDay(date, selectedAllHighlightDate) : false
    },
    [selectedAllHighlightDate]
  )
  const selectedDayTaskRowClass = React.useCallback(
    (task: Task) =>
      [
        isTaskStartingOnSelectedAllDate(task) ? STARTS_ON_SELECTED_DAY_TASK_ROW_CLASS : "",
        isTaskDueOnSelectedAllDate(task) ? DUE_ON_SELECTED_DAY_TASK_ROW_CLASS : "",
      ].join(" "),
    [isTaskDueOnSelectedAllDate, isTaskStartingOnSelectedAllDate]
  )
  const selectedDayDateRowClass = React.useCallback(
    (startDate?: string | null, dueDate?: string | null, isDeadlineImportant = false) =>
      [
        isDateStartingOnSelectedAllDate(startDate) ? STARTS_ON_SELECTED_DAY_TASK_ROW_CLASS : "",
        isDeadlineImportant && isDateStartingOnSelectedAllDate(dueDate) ? DUE_ON_SELECTED_DAY_TASK_ROW_CLASS : "",
      ].join(" "),
    [isDateStartingOnSelectedAllDate]
  )
  const completeTaskTitle = React.useCallback(
    (task: Task) => {
      const originId = task.ga_note_origin_id || task.plan_note_origin_id
      // Knowledge PX prompt tasks show their own "PROMPT: …" title, not the note text.
      if ((task.title || "").startsWith("PROMPT:")) return task.title
      return getCompleteTaskTitle(task, originId ? noteTitleByOriginId[originId] : null)
    },
    [noteTitleByOriginId]
  )
  const renderAllTodayTaskTitle = React.useCallback(
    (task: Task) => {
      const completeTitle = completeTaskTitle(task)
      const title = !completeTitle.includes("[[") ? completeTitle
        : task.ga_note_origin_id || isTaskStartingOnSelectedAllDate(task)
          ? renderMarkedNoteContent(completeTitle, completeTitle)
          : getPlainMarkedText(completeTitle)
      return <><TaskMarkerComment comment={task.one_h_marker ? task.one_h_marker_comment : null} taskId={task.id} />{title}</>
    },
    [completeTaskTitle, isTaskStartingOnSelectedAllDate]
  )
  const isMineView = viewMode === "mine" && Boolean(user?.id)
  const isTaskAssignedToUser = React.useCallback(
    (task: Task, userId?: string | null) => {
      if (!userId) return false
      if (task.assigned_to === userId) return true
      return Boolean(task.assignees?.some((assignee) => assignee.id === userId))
    },
    []
  )
  const waitingConfirmationStatusLabel = React.useCallback(
    (task: Task) => {
      const statusValue = (task.status ? String(task.status) : "").toUpperCase()
      if (statusValue !== "WAITING_CONFIRMATION") return reportStatusLabel(task.status)
      if (task.confirmation_assignee_id && task.confirmation_assignee_id === user?.id) {
        return "Waiting to Confirm"
      }
      if (isTaskAssignedToUser(task, user?.id)) {
        return "Waiting for Confirm"
      }
      return "Waiting Confirmation"
    },
    [isTaskAssignedToUser, user?.id]
  )
  const canMarkWaitingConfirmation = React.useCallback(
    (task?: Task | null) => {
      if (!task || !user?.id) return false
      if (user.role === "ADMIN" || user.role === "MANAGER") return true
      if (task.confirmation_assignee_id === user.id) return true
      return isTaskAssignedToUser(task, user.id)
    },
    [isTaskAssignedToUser, user?.id, user?.role]
  )
  const isTaskOwnedByViewUser = React.useCallback(
    (task: Task, userId?: string | null) => {
      if (!userId) return false
      const koUserId = controlKoUserId(task)
      if (koUserId) return koUserId === userId
      if (isTaskAssignedToUser(task, userId)) return true
      return task.confirmation_assignee_id === userId
    },
    [isTaskAssignedToUser]
  )
  const isTaskActiveForDate = React.useCallback((task: Task, targetDate: Date) => {
    const targetKey = dayKey(targetDate)
    const start = toDate(task.start_date || task.created_at || task.due_date)
    const due = toDate(task.due_date || task.start_date || task.created_at)
    const startKey = start ? dayKey(start) : null
    const dueKey = due ? dayKey(due) : startKey

    if (startKey != null && targetKey < startKey) return false
    if (dueKey != null && targetKey > dueKey) return false
    return true
  }, [])
  const isTaskOverlappingRange = React.useCallback(
    (task: Task, rangeStart: Date, rangeEnd: Date) => {
      const start = task.start_date ? toDate(task.start_date) : null
      const due = task.due_date ? toDate(task.due_date) : null
      if (!start && !due) return false
      const taskRangeStart = start ?? due
      const taskRangeEnd = due ?? start
      if (!taskRangeStart || !taskRangeEnd) return false
      return dayKey(taskRangeStart) <= dayKey(rangeEnd) && dayKey(taskRangeEnd) >= dayKey(rangeStart)
    },
    []
  )
  const isTaskOverlappingWeek = React.useCallback(
    (task: Task) => isTaskOverlappingRange(task, weekStart, weekEnd),
    [isTaskOverlappingRange, weekEnd, weekStart]
  )
  const isTaskOverlappingNextWeek = React.useCallback(
    (task: Task) => isTaskOverlappingRange(task, nextWeekStart, nextWeekEnd),
    [isTaskOverlappingRange, nextWeekEnd, nextWeekStart]
  )
  const isTaskCompletedOnDate = React.useCallback((task: Task, targetDate: Date) => {
    const completedDate = task.completed_at ? toDate(task.completed_at) : null
    return completedDate ? isSameDay(completedDate, targetDate) : false
  }, [])
  const isTaskCompletedInRange = React.useCallback((task: Task, rangeStart: Date, rangeEnd: Date) => {
    const completedDate = task.completed_at ? toDate(task.completed_at) : null
    if (!completedDate) return false
    const completedKey = dayKey(completedDate)
    return completedKey >= dayKey(rangeStart) && completedKey <= dayKey(rangeEnd)
  }, [])
  const isTaskCompletedToday = React.useCallback(
    (task: Task) => isTaskCompletedOnDate(task, todayDate),
    [isTaskCompletedOnDate, todayDate]
  )
  const isTaskOverdueForDate = React.useCallback(
    (task: Task, targetDate: Date) => {
      if (taskStatusValue(task) === "DONE") return false
      const dueDate = task.due_date ? toDate(task.due_date) : null
      if (!dueDate) return false
      return dayKey(dueDate) < dayKey(targetDate)
    },
    [taskStatusValue]
  )
  const isTaskOverdue = React.useCallback(
    (task: Task) => isTaskOverdueForDate(task, todayDate),
    [isTaskOverdueForDate, todayDate]
  )
  const activeAllRangeLabel = React.useMemo(() => {
    switch (allRange) {
      case "past-7-days":
        return "Last 7 Days"
      case "this-week":
        return "This Week"
      case "next-week":
        return "Next Week"
      case "tomorrow":
        return "Tomorrow"
      case "all":
        return "All Open"
      case "date":
        return formatDateDMY(selectedAllDate)
      default:
        return "Today"
    }
  }, [allRange, selectedAllDate])
  const activeAllRangeTaskLabel = React.useMemo(() => {
    switch (allRange) {
      case "past-7-days":
        return "Last 7 Days"
      case "this-week":
        return "this week"
      case "next-week":
        return "next week"
      case "tomorrow":
        return "tomorrow"
      case "all":
        return "all open dates"
      case "date":
        return formatDateDMY(selectedAllDate)
      default:
        return "today"
    }
  }, [allRange, selectedAllDate])
  const allRangeDoneToggleApplies = allRange === "next-week" || allRange === "all"
  const matchesTaskAllRange = React.useCallback(
    (task: Task) => {
      switch (allRange) {
        case "past-7-days":
          return isTaskOverlappingRange(task, pastSevenDaysStart, todayDate)
        case "this-week":
          return isTaskOverlappingWeek(task)
        case "next-week":
          return isTaskOverlappingNextWeek(task)
        case "tomorrow":
          return isTaskActiveForDate(task, tomorrowDate)
        case "all":
          return showAllDoneTasks || taskStatusValue(task) !== "DONE"
        case "date":
          return isTaskActiveForDate(task, selectedAllDate)
        default:
          return isTaskActiveForDate(task, todayDate)
      }
    },
    [
      allRange,
      isTaskActiveForDate,
      isTaskOverlappingNextWeek,
      isTaskOverlappingRange,
      isTaskOverlappingWeek,
      pastSevenDaysStart,
      selectedAllDate,
      showAllDoneTasks,
      todayDate,
      tomorrowDate,
    ]
  )
  const isTaskCompletedInAllRange = React.useCallback(
    (task: Task) => {
      switch (allRange) {
        case "past-7-days":
          return isTaskCompletedInRange(task, pastSevenDaysStart, todayDate)
        case "this-week":
          return isTaskCompletedInRange(task, weekStart, weekEnd)
        case "next-week":
          return isTaskCompletedInRange(task, nextWeekStart, nextWeekEnd)
        case "tomorrow":
          return isTaskCompletedOnDate(task, tomorrowDate)
        case "date":
          return isTaskCompletedOnDate(task, selectedAllDate)
        default:
          return isTaskCompletedToday(task)
      }
    },
    [
      allRange,
      isTaskCompletedInRange,
      isTaskCompletedOnDate,
      isTaskCompletedToday,
      nextWeekEnd,
      nextWeekStart,
      pastSevenDaysStart,
      selectedAllDate,
      todayDate,
      tomorrowDate,
      weekEnd,
      weekStart,
    ]
  )
  const shouldIncludeOverdueInSelectedAllRange = React.useMemo(
    () => activeTab === "all" && allRange === "today" && viewMode === "mine",
    [activeTab, allRange, viewMode]
  )
  const sortDoneLast = React.useCallback(<T,>(items: T[], isDone: (item: T) => boolean) => {
    const withIndex = items.map((item, index) => ({ item, index }))
    withIndex.sort((a, b) => {
      const aDone = isDone(a.item)
      const bDone = isDone(b.item)
      if (aDone === bDone) return a.index - b.index
      return aDone ? 1 : -1
    })
    return withIndex.map((entry) => entry.item)
  }, [])
  const filteredProjects = React.useMemo(() => {
    let filtered = projects
    if (viewMode === "mine" && user?.id) {
      filtered = projects.filter((p) => {
        const members = projectMembers[p.id] || []
        return members.some((m) => m.id === user.id)
      })
    }
    // Sort: closed projects at the end, active projects first
    return [...filtered].sort((a, b) => {
      const aIsClosed = (a.current_phase || "").toUpperCase() === "CLOSED"
      const bIsClosed = (b.current_phase || "").toUpperCase() === "CLOSED"
      if (aIsClosed && !bIsClosed) return 1
      if (!aIsClosed && bIsClosed) return -1
      return 0
    })
  }, [projects, projectMembers, user?.id, viewMode])

  const crossDepartmentTaskUserId = React.useMemo(() => {
    if (isMineView && user?.id) return user.id
    if (selectedUserId !== "__all__") return selectedUserId
    return null
  }, [isMineView, selectedUserId, user?.id])
  const localProjectIds = React.useMemo(() => new Set(projects.map((project) => project.id)), [projects])
  const isCrossDepartmentTask = React.useCallback(
    (task: Task) => {
      if (!department?.id) return false
      if (task.project_id) return !localProjectIds.has(task.project_id)
      return Boolean(task.department_id && task.department_id !== department.id)
    },
    [department?.id, localProjectIds]
  )
  const visibleDepartmentTasks = React.useMemo(() => departmentTasks, [departmentTasks])
  const visibleNoProjectTasks = React.useMemo(() => {
    const filtered = [
      ...noProjectTasks.filter(isNoProjectTask),
      ...crossDepartmentAssignedTasks.filter(isNoProjectTask),
    ]

    // Deduplicate only exact duplicates by ID.
    // Fast tasks can intentionally exist as per-user copies (same title, different IDs),
    // so we must NOT merge by title/properties. Otherwise users can end up opening/editing
    // someone else's copy from "My view" / "All users" lists.
    const taskMapById = new Map<string, Task>()

    for (const t of filtered) {
      const existingById = taskMapById.get(t.id)
      if (existingById) {
        // Merge assignees if task already exists with same ID
        const assigneeMap = new Map<string, TaskAssignee>()

        // Add existing assignees
        if (existingById.assigned_to && userMap.has(existingById.assigned_to)) {
          const user = userMap.get(existingById.assigned_to)!
          assigneeMap.set(existingById.assigned_to, {
            id: existingById.assigned_to,
            full_name: user.full_name || null,
            username: user.username || null,
            email: user.email || null,
            department_id: user.department_id || null,
          })
        }
        existingById.assignees?.forEach(a => {
          if (a.id) assigneeMap.set(a.id, a)
        })

        // Add new task's assignees
        if (t.assigned_to && userMap.has(t.assigned_to)) {
          const user = userMap.get(t.assigned_to)!
          assigneeMap.set(t.assigned_to, {
            id: t.assigned_to,
            full_name: user.full_name || null,
            username: user.username || null,
            email: user.email || null,
            department_id: user.department_id || null,
          })
        }
        t.assignees?.forEach(a => {
          if (a.id) assigneeMap.set(a.id, a)
        })

        // Update existing task with merged assignees
        existingById.assignees = Array.from(assigneeMap.values())
        if (!existingById.assigned_to && t.assigned_to) {
          existingById.assigned_to = t.assigned_to
        }
        continue
      }

      const taskCopy = { ...t }
      taskMapById.set(t.id, taskCopy)
    }

    let deduped = Array.from(taskMapById.values())
    if (isMineView && user?.id) {
      deduped = deduped.filter((task) => isTaskOwnedByViewUser(task, user.id))
    }
    return deduped
  }, [crossDepartmentAssignedTasks, noProjectTasks, userMap, isMineView, user?.id, isTaskOwnedByViewUser])
  const visibleInternalNotes = React.useMemo(() => {
    const base = isMineView && user?.id ? internalNotes.filter((n) => n.to_user_id === user.id) : internalNotes
    const filteredByUser =
      !isMineView && selectedUserId !== "__all__"
        ? base.filter((n) => n.to_user_id === selectedUserId)
        : base
    if (internalNotesFilter === "done") return filteredByUser.filter((n) => n.is_done)
    if (internalNotesFilter === "undone") return filteredByUser.filter((n) => !n.is_done)
    return filteredByUser
  }, [internalNotes, internalNotesFilter, isMineView, selectedUserId, user?.id])
  const viewUserId = React.useMemo(() => {
    if (viewMode === "mine" && user?.id) return user.id
    if (selectedUserId !== "__all__") return selectedUserId
    const isAdminOrManager = user?.role === "ADMIN" || user?.role === "MANAGER"
    if (!isAdminOrManager && user?.id) return user.id
    return null
  }, [selectedUserId, user?.id, user?.role, viewMode])
  const getInternalNoteStatusNotes = React.useCallback(
    (notes: InternalNote[]) => {
      if (!viewUserId) return notes
      const filtered = notes.filter((n) => n.to_user_id === viewUserId)
      return filtered.length ? filtered : notes
    },
    [viewUserId]
  )
  const groupedInternalNotes = React.useMemo(() => {
    const normalizeTime = (value?: string | null) => {
      if (!value) return ""
      const date = new Date(value)
      if (Number.isNaN(date.getTime())) return value
      return date.toISOString().slice(0, 16)
    }
    const groups = new Map<
      string,
      { note: InternalNote; toUserIds: string[]; notes: InternalNote[] }
    >()
    for (const note of internalNotes) {
      const key = [
        note.title?.trim() || "",
        (note.description || "").trim(),
        note.from_user_id,
        note.department_id || note.to_department_id || "",
        note.project_id || "",
        normalizeTime(note.created_at),
      ].join("|")
      const existing = groups.get(key)
      if (existing) {
        if (!existing.toUserIds.includes(note.to_user_id)) {
          existing.toUserIds.push(note.to_user_id)
        }
        existing.notes.push(note)
      } else {
        groups.set(key, { note, toUserIds: [note.to_user_id], notes: [note] })
      }
    }
    let grouped = Array.from(groups.values())
    if (isMineView && user?.id) {
      grouped = grouped.filter((group) => group.toUserIds.includes(user.id))
    }
    if (!isMineView && selectedUserId !== "__all__") {
      grouped = grouped.filter((group) => group.toUserIds.includes(selectedUserId))
    }
    grouped = grouped.filter((group) => {
      if (internalNotesFilter === "all") return true
      const statusNotes = getInternalNoteStatusNotes(group.notes)
      if (internalNotesFilter === "done") {
        return statusNotes.length > 0 && statusNotes.every((n) => n.is_done)
      }
      return statusNotes.some((n) => !n.is_done)
    })
    return grouped.sort((a, b) => {
      const aTime = a.note.created_at ? new Date(a.note.created_at).getTime() : 0
      const bTime = b.note.created_at ? new Date(b.note.created_at).getTime() : 0
      return bTime - aTime
    })
  }, [getInternalNoteStatusNotes, internalNotes, internalNotesFilter, isMineView, selectedUserId, user?.id])
  React.useEffect(() => {
    if (!isMineView || !user?.id) {
      setMyMeetings([])
      return
    }
    let cancelled = false
    void apiFetch(`/meetings?participant_user_id=${encodeURIComponent(user.id)}`).then(async (response) => {
      if (!response.ok || cancelled) {
        if (!cancelled) setMyMeetings([])
        return
      }
      const participantMeetings = (await response.json()) as Meeting[]
      if (!cancelled) setMyMeetings(participantMeetings)
    }).catch(() => {
      if (!cancelled) setMyMeetings([])
    })
    return () => {
      cancelled = true
    }
  }, [apiFetch, isMineView, user?.id])

  const visibleMeetings = React.useMemo(() => {
    if (isMineView && user?.id) {
      return myMeetings.filter((meeting) => meeting.participant_ids?.includes(user.id))
    }
    if (department?.id) {
      return meetings.filter((meeting) => meeting.department_id === department.id)
    }
    return meetings
  }, [department?.id, isMineView, meetings, myMeetings, user?.id])
  const meetingTabMeetings = React.useMemo(() => {
    const meetingById = new Map<string, Meeting>()
    for (const meeting of visibleMeetings) meetingById.set(meeting.id, meeting)
    for (const meeting of allDepartmentMeetings) meetingById.set(meeting.id, meeting)
    return Array.from(meetingById.values())
  }, [allDepartmentMeetings, visibleMeetings])
  const visibleExternalMeetings = React.useMemo(
    () => visibleMeetings.filter((m) => (m.meeting_type || "external") === "external"),
    [visibleMeetings]
  )
  const visibleInternalMeetings = React.useMemo(
    () => visibleMeetings.filter((m) => m.meeting_type === "internal"),
    [visibleMeetings]
  )
  const visibleSystemTemplates = React.useMemo(
    () => {
      if (isMineView && user?.id) {
        return systemTasks.filter((t) => systemTaskAssignedToUser(t, user.id))
      }
      const depTasks = department
        ? systemTasks.filter((t) => {
          if (t.department_id === department.id) return true
          if (t.department_ids?.includes(department.id)) return true
          return false
        })
        : []
      return depTasks
    },
    [systemTasks, isMineView, user?.id, department]
  )
  const projectTasks = React.useMemo(() => {
    const taskMap = new Map<string, Task>()
    for (const task of visibleDepartmentTasks.filter((t) => t.project_id)) {
      taskMap.set(task.id, task)
    }
    for (const task of crossDepartmentAssignedTasks.filter((t) => t.project_id)) {
      if (!taskMap.has(task.id)) taskMap.set(task.id, task)
    }
    const tasks = Array.from(taskMap.values())
    if (isMineView && user?.id) {
      return tasks.filter((task) => isTaskOwnedByViewUser(task, user.id))
    }
    return tasks
  }, [crossDepartmentAssignedTasks, visibleDepartmentTasks, isMineView, user?.id, isTaskOwnedByViewUser])
  const crossDepartmentVisibleTasks = React.useMemo(() => {
    const taskMap = new Map<string, Task>()
    for (const task of crossDepartmentAssignedTasks) taskMap.set(task.id, task)
    for (const task of crossDepartmentConfirmTasks) {
      if (!taskMap.has(task.id)) taskMap.set(task.id, task)
    }
    return Array.from(taskMap.values())
  }, [crossDepartmentAssignedTasks, crossDepartmentConfirmTasks])
  React.useEffect(() => {
    let cancelled = false
    const run = async () => {
      if (!crossDepartmentTaskUserId) {
        setCrossDepartmentAssignedTasks([])
        return
      }
      try {
        const qs = new URLSearchParams({
          include_done: "true",
          assigned_to: crossDepartmentTaskUserId,
        })
        const res = await apiFetch(`/tasks?${qs.toString()}`)
        if (!res.ok) {
          console.warn("Failed to load cross-department assigned tasks", res.status)
          if (!cancelled) setCrossDepartmentAssignedTasks([])
          return
        }
        const payload = (await res.json()) as Task[]
        if (cancelled) return
        const localTaskIds = new Set([...departmentTasks, ...noProjectTasks].map((task) => task.id))
        const filtered = payload.filter(
          (task) =>
            !task.system_template_origin_id &&
            !localTaskIds.has(task.id) &&
            isCrossDepartmentTask(task) &&
            isTaskOwnedByViewUser(task, crossDepartmentTaskUserId)
        )
        const taskMap = new Map<string, Task>()
        for (const task of filtered) {
          if (!taskMap.has(task.id)) taskMap.set(task.id, task)
        }
        setCrossDepartmentAssignedTasks(Array.from(taskMap.values()))
      } catch (error) {
        console.warn("Failed to load cross-department assigned tasks", error)
        if (!cancelled) setCrossDepartmentAssignedTasks([])
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [
    apiFetch,
    crossDepartmentTaskUserId,
    departmentTasks,
    isCrossDepartmentTask,
    isTaskOwnedByViewUser,
    noProjectTasks,
  ])
  const visibleSystemCreatedTasks = React.useMemo(() => {
    if (isMineView && user?.id) {
      return systemCreatedTasks.filter((task) => isTaskOwnedByViewUser(task, user.id))
    }
    return systemCreatedTasks
  }, [isMineView, isTaskOwnedByViewUser, systemCreatedTasks, user?.id])
  React.useEffect(() => {
    let cancelled = false
    const run = async () => {
      if (viewMode !== "mine" || !user?.id) {
        setCrossDepartmentConfirmTasks([])
        return
      }
      try {
        const qs = new URLSearchParams({
          include_done: "true",
          status: "WAITING_CONFIRMATION",
          confirmation_assignee_id: user.id,
        })
        const res = await apiFetch(`/tasks?${qs.toString()}`)
        if (!res.ok) {
          console.warn("Failed to load cross-department waiting confirmation tasks", res.status)
          if (!cancelled) setCrossDepartmentConfirmTasks([])
          return
        }
        const payload = (await res.json()) as Task[]
        if (cancelled) return
        const localTaskIds = new Set([...departmentTasks, ...noProjectTasks].map((task) => task.id))
        const filtered = payload.filter(
          (task) => task.confirmation_assignee_id === user.id && !localTaskIds.has(task.id)
        )
        setCrossDepartmentConfirmTasks(filtered)
      } catch (error) {
        console.warn("Failed to load cross-department waiting confirmation tasks", error)
        if (!cancelled) setCrossDepartmentConfirmTasks([])
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [apiFetch, departmentTasks, noProjectTasks, user?.id, viewMode])
  const isSystemTaskOverdueForDate = React.useCallback(
    (task: SystemTaskTemplate, targetDate: Date) => {
      const status = String(task.status || "").toUpperCase()
      if (status === "DONE") return false
      const taskDate = toDate(task.due_date || task.start_date || task.occurrence_date || task.effective_occurrence_date || null)
      if (!taskDate) return false
      return dayKey(taskDate) < dayKey(targetDate)
    },
    []
  )
  const overdueTaskIds = React.useMemo(() => {
    const ids = new Set<string>()
    if (!shouldIncludeOverdueInSelectedAllRange) return ids
    for (const item of dailyReport?.tasks_overdue || []) {
      if (item?.task?.id) ids.add(item.task.id)
    }
    return ids
  }, [dailyReport?.tasks_overdue, shouldIncludeOverdueInSelectedAllRange])
  const todaySystemTasks = React.useMemo(() => {
    return visibleSystemCreatedTasks.filter((task) => {
      const matchesRange = matchesTaskAllRange(task)
      const completedInRange = isTaskCompletedInAllRange(task)
      const isDone = taskStatusValue(task) === "DONE"
      if (!matchesRange && !completedInRange) return false
      if (allRangeDoneToggleApplies && isDone && !showAllDoneTasks) return false
      if (selectedUserId !== "__all__") {
        return isTaskOwnedByViewUser(task, selectedUserId)
      }
      return true
    })
  }, [
    allRange,
    isTaskCompletedInAllRange,
    isTaskOwnedByViewUser,
    allRangeDoneToggleApplies,
    matchesTaskAllRange,
    selectedUserId,
    showAllDoneTasks,
    visibleSystemCreatedTasks,
  ])
  const todayProjectTasks = React.useMemo(() => {
    return projectTasks.filter((task) => {
      const matchesRange = matchesTaskAllRange(task)
      const completedToday = isTaskCompletedInAllRange(task)
      const isOverdue = overdueTaskIds.has(task.id)
      const isDone = taskStatusValue(task) === "DONE"
      if (!matchesRange && !completedToday && !isOverdue) return false
      if (allRangeDoneToggleApplies && isDone && !showAllDoneTasks) return false
      if (selectedUserId !== "__all__") {
        return isTaskOwnedByViewUser(task, selectedUserId)
      }
      return true
    })
  }, [
    allRange,
    isTaskCompletedInAllRange,
    projectTasks,
    matchesTaskAllRange,
    selectedUserId,
    isTaskOwnedByViewUser,
    allRangeDoneToggleApplies,
    overdueTaskIds,
    showAllDoneTasks,
  ])
  const waitingProjectTasksForMeta = React.useMemo(() => {
    if (!isMineView || !user?.id) return []
    return crossDepartmentVisibleTasks
      .filter(
        (task) =>
          task.project_id &&
          task.confirmation_assignee_id === user.id &&
          taskStatusValue(task) === "WAITING_CONFIRMATION"
      )
      .filter((task) => {
        const matchesRange = matchesTaskAllRange(task)
        const completedToday = isTaskCompletedInAllRange(task)
        const overdue = isTaskOverdue(task)
        if (allRange === "all" && taskStatusValue(task) === "DONE") return false
        return matchesRange || completedToday || overdue
      })
  }, [
    allRange,
    crossDepartmentVisibleTasks,
    isMineView,
    isTaskCompletedInAllRange,
    isTaskOverdue,
    matchesTaskAllRange,
    user?.id,
  ])
  React.useEffect(() => {
    let cancelled = false
    const run = async () => {
      const missingIds = new Set<string>()
      for (const task of [...todayProjectTasks, ...waitingProjectTasksForMeta]) {
        if (!task.project_id) continue
        const projectId = String(task.project_id)
        if (projects.some((p) => p.id === projectId)) continue
        if (projectMetaLookup.has(projectId)) continue
        missingIds.add(projectId)
      }
      if (!missingIds.size) return

      const results = await Promise.all(
        Array.from(missingIds).map(async (id) => {
          const res = await apiFetch(`/projects/${encodeURIComponent(id)}`)
          if (!res.ok) return null
          const data = (await res.json()) as { id?: string; title?: string | null; name?: string | null; department_id?: string | null }
          const title = data.title || data.name
          if (!data.id || !title) return null
          return { id: data.id, title, department_id: data.department_id ?? null }
        })
      )
      if (cancelled) return
      setProjectMetaLookup((prev) => {
        const next = new Map(prev)
        for (const item of results) {
          if (!item) continue
          next.set(item.id, { title: item.title, department_id: item.department_id })
        }
        return next
      })
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [apiFetch, projectMetaLookup, projects, todayProjectTasks, waitingProjectTasksForMeta])
  const todayNoProjectTasks = React.useMemo(() => {
    return visibleNoProjectTasks.filter((task) => {
      const matchesRange = matchesTaskAllRange(task)
      const completedToday = isTaskCompletedInAllRange(task)
      const isOverdue = overdueTaskIds.has(task.id)
      const isDone = taskStatusValue(task) === "DONE"
      if (!matchesRange && !completedToday && !isOverdue) return false
      if (allRangeDoneToggleApplies && isDone && !showAllDoneTasks) return false
      if (selectedUserId !== "__all__") {
        return isTaskOwnedByViewUser(task, selectedUserId)
      }
      return true
    })
  }, [
    allRange,
    isTaskCompletedInAllRange,
    matchesTaskAllRange,
    visibleNoProjectTasks,
    selectedUserId,
    isTaskOwnedByViewUser,
    allRangeDoneToggleApplies,
    overdueTaskIds,
    showAllDoneTasks,
  ])
  const selectedDateNoProjectTasks = React.useMemo(() => {
    if (showAllFastTasks) {
      return visibleNoProjectTasks.filter((task) => {
        if (selectedUserId !== "__all__") {
          return isTaskOwnedByViewUser(task, selectedUserId)
        }
        return true
      })
    }
    return visibleNoProjectTasks.filter((task) => {
      const matchesSelectedDate = isTaskActiveForDate(task, selectedFastTaskDate)
      const completedOnSelectedDate = isTaskCompletedOnDate(task, selectedFastTaskDate)
      if (!matchesSelectedDate && !completedOnSelectedDate) return false
      if (selectedUserId !== "__all__") {
        return isTaskOwnedByViewUser(task, selectedUserId)
      }
      return true
    })
  }, [
    visibleNoProjectTasks,
    isTaskActiveForDate,
    selectedFastTaskDate,
    isTaskCompletedOnDate,
    selectedUserId,
    showAllFastTasks,
    isTaskOwnedByViewUser,
  ])
  const todayInternalNotes = React.useMemo(() => {
    return visibleInternalNotes.filter((note) => {
      const date = toDate(note.created_at)
      return date ? isSameDay(date, todayDate) : false
    })
  }, [todayDate, visibleInternalNotes])
  const todayGroupedInternalNotes = React.useMemo(() => {
    return groupedInternalNotes.filter((group) => {
      const date = toDate(group.note.created_at)
      return date ? isSameDay(date, todayDate) : false
    })
  }, [groupedInternalNotes, todayDate])
  const todayMeetings = React.useMemo(
    () =>
      visibleMeetings.filter((m) => {
        if (!m.starts_at) return false
        const start = new Date(m.starts_at)
        if (Number.isNaN(start.getTime())) return false
        return isSameDay(start, todayDate)
      }),
    [visibleMeetings, todayDate]
  )
  const todayExternalMeetings = React.useMemo(
    () => visibleExternalMeetings.filter((m) => todayMeetings.some((meeting) => meeting.id === m.id)),
    [todayMeetings, visibleExternalMeetings]
  )
  const todayInternalMeetings = React.useMemo(
    () => visibleInternalMeetings.filter((m) => todayMeetings.some((meeting) => meeting.id === m.id)),
    [todayMeetings, visibleInternalMeetings]
  )
  const filteredMeetings = React.useMemo(() => {
    const startOfToday = new Date(todayDate)
    startOfToday.setHours(0, 0, 0, 0)
    const startOfTomorrow = new Date(startOfToday)
    startOfTomorrow.setDate(startOfTomorrow.getDate() + 1)
    const startOfThisWeek = startOfWeekMonday(startOfToday)
    const startOfNextWeek = new Date(startOfThisWeek)
    startOfNextWeek.setDate(startOfNextWeek.getDate() + 7)
    const startOfFuture = new Date(startOfNextWeek)
    startOfFuture.setDate(startOfFuture.getDate() + 7)

    return meetingTabMeetings
      .filter((meeting) => {
        const meetingDate = resolveMeetingDisplayDate(meeting)
        if (!meetingDate || Number.isNaN(meetingDate.getTime())) return false
        if (meetingTimeFilter === "today") {
          return meetingDate >= startOfToday && meetingDate < startOfTomorrow
        }
        if (meetingTimeFilter === "tomorrow") {
          const startOfDayAfterTomorrow = new Date(startOfTomorrow)
          startOfDayAfterTomorrow.setDate(startOfDayAfterTomorrow.getDate() + 1)
          return meetingDate >= startOfTomorrow && meetingDate < startOfDayAfterTomorrow
        }
        if (meetingTimeFilter === "this_week") {
          return meetingDate >= startOfThisWeek && meetingDate < startOfNextWeek
        }
        if (meetingTimeFilter === "next_week") {
          return meetingDate >= startOfNextWeek && meetingDate < startOfFuture
        }
        return meetingDate >= startOfFuture
      })
      .sort((a, b) => {
        const aTime = resolveMeetingDisplayDate(a)?.getTime() ?? 0
        const bTime = resolveMeetingDisplayDate(b)?.getTime() ?? 0
        return aTime - bTime
      })
  }, [meetingTabMeetings, meetingTimeFilter, todayDate])
  const filteredExternalMeetings = React.useMemo(
    () => filteredMeetings.filter((meeting) => (meeting.meeting_type || "external") === "external"),
    [filteredMeetings]
  )
  const filteredInternalMeetings = React.useMemo(
    () => filteredMeetings.filter((meeting) => meeting.meeting_type === "internal"),
    [filteredMeetings]
  )
  const dailyReportFastTasks = React.useMemo(() => {
    const reportDayKey = dayKey(selectedAllReportDate)
    const targetUserId =
      viewMode === "department"
        ? selectedUserId !== "__all__"
          ? selectedUserId
          : user?.id
        : user?.id

    return visibleNoProjectTasks.filter((task) => {
      if (!task.due_date) return false
      if (targetUserId && !isTaskOwnedByViewUser(task, targetUserId)) {
        return false
      }

      const completedDate = task.completed_at ? toDate(task.completed_at) : null
      const completedOnReportDay = completedDate ? isSameDay(completedDate, selectedAllReportDate) : false
      if (completedOnReportDay) return true
      const isDone = Boolean(completedDate) || task.status === "DONE"
      if (isDone) {
        return isTaskActiveForDate(task, selectedAllReportDate)
      }

      const startDate = task.start_date ? toDate(task.start_date) : null
      const dueDate = task.due_date ? toDate(task.due_date) : null
      if (startDate && dueDate) {
        return reportDayKey >= dayKey(startDate)
      }

      const baseDate = toDate(task.due_date || task.start_date || task.planned_for || task.created_at)
      if (!baseDate) return false
      return dayKey(baseDate) <= reportDayKey
    })
  }, [
    selectedAllReportDate,
    visibleNoProjectTasks,
    viewMode,
    selectedUserId,
    user?.id,
    isTaskOwnedByViewUser,
    isTaskActiveForDate,
  ])
  const dailyReportProjectTasks = React.useMemo(() => {
    const reportDayKey = dayKey(selectedAllReportDate)
    const targetUserId =
      viewMode === "department"
        ? selectedUserId !== "__all__"
          ? selectedUserId
          : user?.id
        : user?.id

    return projectTasks.filter((task) => {
      if (!task.due_date) return false
      if (targetUserId && !isTaskOwnedByViewUser(task, targetUserId)) {
        return false
      }

      const completedDate = task.completed_at ? toDate(task.completed_at) : null
      const completedOnReportDay = completedDate ? isSameDay(completedDate, selectedAllReportDate) : false

      // Show completed tasks if completed on the selected report day
      if (completedOnReportDay) return true
      const isDone = Boolean(completedDate) || task.status === "DONE"
      if (isDone) {
        return isTaskActiveForDate(task, selectedAllReportDate)
      }

      // Show project tasks from start_date through due_date (and after for late)
      const startDate = task.start_date ? toDate(task.start_date) : null
      const dueDate = task.due_date ? toDate(task.due_date) : null
      const createdDate = task.created_at ? toDate(task.created_at) : null

      // If we have both start and due dates, show if today is on/after start
      if (startDate && dueDate) {
        const startKey = dayKey(startDate)
        return reportDayKey >= startKey
      }

      // If only due date, show if due today or before
      if (dueDate) {
        const dueKey = dayKey(dueDate)
        return reportDayKey >= dueKey
      }

      // If only start date, show if started today or before
      if (startDate) {
        const startKey = dayKey(startDate)
        return reportDayKey >= startKey
      }

      // Fallback to created_at if no dates
      if (!createdDate) return false
      const createdKey = dayKey(createdDate)
      return createdKey <= reportDayKey
    })
  }, [projectTasks, selectedAllReportDate, viewMode, selectedUserId, user?.id, isTaskOwnedByViewUser, isTaskActiveForDate])
  React.useEffect(() => {
    const origins = new Map<string, "ga" | "plan">()
    for (const task of [...dailyReportFastTasks, ...dailyReportProjectTasks]) {
      if (task.ga_note_origin_id) origins.set(task.ga_note_origin_id, "ga")
      if (task.plan_note_origin_id) origins.set(task.plan_note_origin_id, "plan")
    }
    const missing = Array.from(origins.entries()).filter(([originId]) => !noteTitleByOriginId[originId])
    if (!missing.length) return

    let cancelled = false
    void Promise.all(
      missing.map(async ([originId, source]) => {
        try {
          const response = await apiFetch(`/${source === "ga" ? "ga-notes" : "plan-notes"}/${originId}`)
          if (!response.ok) return null
          const note = (await response.json()) as { content?: string | null }
          const content = (note.content || "").trim()
          return content ? ([originId, content] as const) : null
        } catch {
          return null
        }
      })
    ).then((results) => {
      if (cancelled) return
      setNoteTitleByOriginId((previous) => {
        const next = { ...previous }
        for (const result of results) {
          if (result) next[result[0]] = result[1]
        }
        return next
      })
    })
    return () => {
      cancelled = true
    }
  }, [apiFetch, dailyReportFastTasks, dailyReportProjectTasks, noteTitleByOriginId])
  const deadlineImportantTaskIds = React.useMemo(() => {
    const ids = new Set<string>()
    for (const task of dailyReportFastTasks) {
      if (task.is_deadline_important) ids.add(task.id)
    }
    for (const task of dailyReportProjectTasks) {
      if (task.is_deadline_important) ids.add(task.id)
    }
    for (const task of todaySystemTasks) {
      if (task.is_deadline_important) ids.add(task.id)
    }
    return ids
  }, [dailyReportFastTasks, dailyReportProjectTasks, todaySystemTasks])
  const dailyReportTyoDateByTaskId = React.useMemo(() => {
    const map = new Map<string, string>()
    for (const task of dailyReportFastTasks) {
      const dateValue = task.due_date || task.start_date || task.created_at
      if (dateValue) map.set(task.id, dateValue)
    }
    for (const task of dailyReportProjectTasks) {
      const dateValue = task.due_date || task.start_date || task.created_at
      if (dateValue) map.set(task.id, dateValue)
    }
    for (const task of todaySystemTasks) {
      const dateValue = task.due_date || task.start_date || task.origin_run_at || task.created_at
      if (dateValue) map.set(task.id, dateValue)
    }
    return map
  }, [dailyReportFastTasks, dailyReportProjectTasks, todaySystemTasks])
  const dailyReportStartDateByTaskId = React.useMemo(() => {
    const map = new Map<string, string>()
    for (const task of dailyReportFastTasks) {
      if (task.start_date) map.set(task.id, task.start_date)
    }
    for (const task of dailyReportProjectTasks) {
      if (task.start_date) map.set(task.id, task.start_date)
    }
    for (const task of todaySystemTasks) {
      if (task.start_date) map.set(task.id, task.start_date)
    }
    return map
  }, [dailyReportFastTasks, dailyReportProjectTasks, todaySystemTasks])
  const dailyReportDueDateByTaskId = React.useMemo(() => {
    const map = new Map<string, string>()
    for (const task of dailyReportFastTasks) {
      if (task.due_date) map.set(task.id, task.due_date)
    }
    for (const task of dailyReportProjectTasks) {
      if (task.due_date) map.set(task.id, task.due_date)
    }
    for (const task of todaySystemTasks) {
      if (task.due_date) map.set(task.id, task.due_date)
    }
    return map
  }, [dailyReportFastTasks, dailyReportProjectTasks, todaySystemTasks])

  React.useEffect(() => {
    const existingTitles = new Map<string, string>()
    for (const p of projects) {
      const title = resolveProjectTitle(p)
      if (title) {
        existingTitles.set(p.id, title)
      }
    }
    const missingIds = Array.from(
      new Set(
        dailyReportProjectTasks
          .map((task) => task.project_id)
          .filter((pid): pid is string => typeof pid === "string" && pid.trim().length > 0)
      )
    ).filter((pid) => !existingTitles.has(pid) && !projectTitleLookup.has(pid))

    if (!missingIds.length) return

    void (async () => {
      const data = await fetchProjectTitlesById(apiFetch, missingIds)
      if (!data.length) return
      setProjectTitleLookup((prev) => {
        const next = new Map(prev)
        for (const item of data) {
          if (item?.id) next.set(item.id, resolveProjectTitle(item))
        }
        return next
      })
    })()
  }, [apiFetch, dailyReportProjectTasks, projectTitleLookup, projects])
  const systemTemplateById = React.useMemo(() => {
    const map = new Map<string, SystemTaskTemplate>()
    for (const tmpl of visibleSystemTemplates) {
      map.set(tmpl.id, tmpl)
      if (tmpl.template_id) {
        map.set(tmpl.template_id, tmpl)
      }
    }
    return map
  }, [visibleSystemTemplates])

  const getChecklistItemsForTask = React.useCallback(
    (taskId?: string) => {
      if (!taskId) return []
      const checklist = taskChecklists[taskId]
      if (!checklist?.items?.length) return []
      return checklist.items
        .filter((item) => item.item_type === "CHECKBOX")
        .slice()
        .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
    },
    [taskChecklists]
  )

  const getChecklistCountsForTask = React.useCallback(
    (taskId?: string) => {
      const items = getChecklistItemsForTask(taskId)
      const total = items.length
      const done = items.filter((item) => item.is_checked).length
      return { total, done }
    },
    [getChecklistItemsForTask]
  )

  const dailyUserReportRows = React.useMemo(() => {
    const rows: Array<{
      typeLabel: string
      subtype: string
      period: string
      department: string
      title: string
      projectTitle?: string | null
      description: string
      status: string
      statusKey?: "TODO" | "IN_PROGRESS" | "WAITING_CLIENT" | "WAITING_CONFIRMATION" | "DONE"
      bz: string
      kohaBz: string
      tyo: string
      comment?: string | null
      userInitials?: string
      taskId?: string
      systemTemplateId?: string
      systemOccurrenceDate?: string
      systemStatus?: string
      sortDate?: string | null
      startDate?: string | null
      dueDate?: string | null
      oneHReportSlot?: OneHReportSlot | null
      isOneHReportTask?: boolean
      oneHMarker?: Task["one_h_marker"]
      oneHMarkerByGa?: boolean
    }> = []
    const systemAmRows: typeof rows = []
    const systemPmRows: typeof rows = []
    const fastRows: Array<{ order: number; index: number; row: (typeof rows)[number] }> = []
    const projectRows: typeof rows = []
    let fastIndex = 0
    const statusOrder = {
      TODO: 0,
      IN_PROGRESS: 1,
      WAITING_CLIENT: 2,
      WAITING_CONFIRMATION: 3,
      DONE: 4,
    } as const
    type StatusKey = keyof typeof statusOrder
    const normalizeTaskStatusKey = (task: Task): StatusKey => {
      const raw = task.status?.toUpperCase() || ""
      if (raw === "TODO" || raw === "IN_PROGRESS" || raw === "WAITING_CLIENT" || raw === "WAITING_CONFIRMATION" || raw === "DONE") {
        return raw
      }
      if (task.completed_at) return "DONE"
      return "TODO"
    }
    const isRowDone = (row: (typeof rows)[number]) => {
      return row.statusKey === "DONE" || row.status?.toUpperCase() === "DONE"
    }
    const doneLast = (items: Array<(typeof rows)[number]>) => {
      const open: Array<(typeof rows)[number]> = []
      const done: Array<(typeof rows)[number]> = []
      for (const item of items) {
        if (isRowDone(item)) {
          done.push(item)
        } else {
          open.push(item)
        }
      }
      return [...open, ...done]
    }
    const projectTitleByTaskId = new Map<string, string>()
    for (const item of [...(dailyReport?.tasks_today || []), ...(dailyReport?.tasks_overdue || [])]) {
      if (item.project_title) {
        projectTitleByTaskId.set(item.task.id, item.project_title)
      }
    }

    const pushSystemRow = (row: (typeof rows)[number]) => {
      if (row.period === "PM") {
        systemPmRows.push(row)
        return
      }
      systemAmRows.push(row)
    }

    const fastTypeOrder = (task: Task) => {
      const label = noProjectTypeLabel(task)
      if (label === "BLLOK") return 0
      if (label === "1H") return 1
      if (label === "Personal") return 2
      if (label === "R1") return 3
      if (label === "Normal") return 4
      return 5
    }

    const todayTemplateIds = new Set(
      (dailyReport?.system_today || [])
        .map((item) => item.task?.system_template_origin_id)
        .filter((value): value is string => Boolean(value))
    )
    const systemTodayByTemplate = new Map<string, DailyReportResponse["system_today"][number]>()
    if (dailyReport?.system_today?.length) {
      for (const item of dailyReport.system_today) {
        const templateId = item.task?.system_template_origin_id
        if (templateId) systemTodayByTemplate.set(templateId, item)
      }
    }
    const overdueByTemplate = new Map<string, DailyReportResponse["system_overdue"][number]>()
    if (dailyReport?.system_overdue?.length) {
      for (const item of dailyReport.system_overdue) {
        const templateId = item.task?.system_template_origin_id
        if (!templateId || todayTemplateIds.has(templateId)) {
          continue
        }
        const existing = overdueByTemplate.get(templateId)
        if (!existing) {
          overdueByTemplate.set(templateId, item)
          continue
        }
        const existingDate = toDate(existing.task?.start_date || existing.task?.origin_run_at || existing.task?.due_date || existing.task?.created_at)
        const nextDate = toDate(item.task?.start_date || item.task?.origin_run_at || item.task?.due_date || item.task?.created_at)
        if (!existingDate || (nextDate && dayKey(nextDate) > dayKey(existingDate))) {
          overdueByTemplate.set(templateId, item)
        }
      }
    }

    for (const item of overdueByTemplate.values()) {
      const task = item.task
      if (!task) continue
      const templateId = task.system_template_origin_id
      const tmpl = templateId ? (systemTemplateById.get(templateId) || null) : null
      const baseDate = toDate(task.start_date || task.origin_run_at || task.due_date || task.created_at)
      const alignmentEnabled = Boolean(
        tmpl?.requires_alignment ||
        tmpl?.alignment_time ||
        (tmpl?.alignment_user_ids && tmpl.alignment_user_ids.length) ||
        (tmpl?.alignment_roles && tmpl.alignment_roles.length)
      )
      const bzUsers = formatAlignmentUsers(tmpl?.alignment_user_ids, userMap)
      pushSystemRow({
        typeLabel: "SYS",
        subtype: tmpl ? systemFrequencyShortLabel(tmpl.frequency) : "SYS",
        period: resolvePeriod(task.finish_period ?? tmpl?.finish_period ?? null, task.due_date || task.start_date || task.created_at),
        department: departmentCode,
        title: task.title || "-",
        description: task.description || tmpl?.description || "-",
        status: taskStatusLabel(task),
        statusKey: normalizeTaskStatusKey(task),
        bz: alignmentEnabled
          ? bzUsers !== "-"
            ? formatAlignmentInitials(tmpl?.alignment_user_ids, userMap)
            : tmpl?.alignment_roles?.length
              ? tmpl.alignment_roles.join(", ")
              : "-"
          : "-",
        kohaBz: alignmentEnabled ? formatAlignmentTime(tmpl?.alignment_time) : "-",
        tyo: getTyoLabel(baseDate, task.completed_at, selectedAllReportDate),
        comment: task.user_comment ?? null,
        userInitials: printInitials,
        taskId: task.id,
        oneHMarker: task.one_h_marker,
        oneHMarkerByGa: task.one_h_marker_by_ga,
        sortDate: task.due_date || task.start_date || task.origin_run_at || task.created_at,
        startDate: task.start_date || null,
        dueDate: task.due_date || null,
      })
    }

    for (const item of systemTodayByTemplate.values()) {
      const task = item.task
      if (!task) continue
      const templateId = task.system_template_origin_id
      const tmpl = templateId ? (systemTemplateById.get(templateId) || null) : null
      const alignmentEnabled = Boolean(
        tmpl?.requires_alignment ||
        tmpl?.alignment_time ||
        (tmpl?.alignment_user_ids && tmpl.alignment_user_ids.length) ||
        (tmpl?.alignment_roles && tmpl.alignment_roles.length)
      )
      const bzUsers = formatAlignmentUsers(tmpl?.alignment_user_ids, userMap)
      pushSystemRow({
        typeLabel: "SYS",
        subtype: tmpl ? systemFrequencyShortLabel(tmpl.frequency) : "SYS",
        period: resolvePeriod(task.finish_period ?? tmpl?.finish_period ?? null, task.due_date || task.start_date || task.created_at),
        department: departmentCode,
        title: task.title || "-",
        description: task.description || tmpl?.description || "-",
        status: taskStatusLabel(task),
        statusKey: normalizeTaskStatusKey(task),
        bz: alignmentEnabled
          ? bzUsers !== "-"
            ? formatAlignmentInitials(tmpl?.alignment_user_ids, userMap)
            : tmpl?.alignment_roles?.length
              ? tmpl.alignment_roles.join(", ")
              : "-"
          : "-",
        kohaBz: alignmentEnabled ? formatAlignmentTime(tmpl?.alignment_time) : "-",
        tyo: "T",
        comment: task.user_comment ?? null,
        userInitials: printInitials,
        taskId: task.id,
        oneHMarker: task.one_h_marker,
        oneHMarkerByGa: task.one_h_marker_by_ga,
        sortDate: task.due_date || task.start_date || task.origin_run_at || task.created_at,
        startDate: task.start_date || null,
        dueDate: task.due_date || null,
      })
    }

    for (const task of dailyReportFastTasks) {
      const startDate = task.start_date ? toDate(task.start_date) : null
      const dueDate = task.due_date ? toDate(task.due_date) : null
      fastRows.push({
        order: fastTypeOrder(task),
        index: fastIndex,
        row: {
          typeLabel: "FT",
          subtype: fastReportSubtypeShort(task),
          period: resolvePeriod(task.finish_period, task.due_date || task.start_date || task.planned_for || task.created_at),
          department: departmentCode,
          title: completeTaskTitle(task),
          description: task.description || "-",
          status: taskStatusLabel(task),
          statusKey: normalizeTaskStatusKey(task),
          bz: "-",
          kohaBz: "-",
          tyo: getDailyReportTyo({
            reportDate: selectedAllReportDate,
            startDate,
            dueDate,
            mode: startDate && dueDate ? "range" : "dueOnly",
          }),
          comment: task.user_comment ?? null,
          userInitials: printInitials,
          taskId: task.id,
          oneHMarker: task.one_h_marker,
          oneHMarkerByGa: task.one_h_marker_by_ga,
          sortDate: task.due_date || task.start_date || task.planned_for || task.created_at,
          startDate: task.start_date || null,
          dueDate: task.due_date || null,
          oneHReportSlot: task.is_1h_report || task.is_r1
            ? dailyReportOneHSlots[task.id] ?? null
            : null,
          isOneHReportTask: Boolean(task.is_1h_report),
        },
      })
      fastIndex += 1
    }

    for (const task of dailyReportProjectTasks) {
      const startDate = task.start_date ? toDate(task.start_date) : null
      const dueDate = task.due_date ? toDate(task.due_date) : null
      const project = task.project_id ? projects.find((p) => p.id === task.project_id) || null : null
      const projectLabel =
        project?.title ||
        project?.name ||
        (task.project_id ? projectTitleLookup.get(task.project_id) : null) ||
        projectTitleByTaskId.get(task.id) ||
        null
      projectRows.push({
        typeLabel: "PRJK",
        subtype: projectReportSubtypeShort(task),
        period: resolvePeriod(task.finish_period, task.due_date || task.start_date || task.created_at),
        department: departmentCode,
        title: completeTaskTitle(task),
        projectTitle: projectLabel,
        description: task.description || "-",
        status: taskStatusLabel(task),
        statusKey: normalizeTaskStatusKey(task),
        bz: "-",
        kohaBz: "-",
        tyo: getDailyReportTyo({
          reportDate: selectedAllReportDate,
          startDate,
          dueDate,
          mode: startDate && dueDate ? "range" : "dueOnly",
        }),
        comment: task.user_comment ?? null,
        userInitials: printInitials,
        taskId: task.id,
        oneHMarker: task.one_h_marker,
        oneHMarkerByGa: task.one_h_marker_by_ga,
        sortDate: task.due_date || task.start_date || task.created_at,
        startDate: task.start_date || null,
        dueDate: task.due_date || null,
        oneHReportSlot: task.is_1h_report || task.is_r1
          ? dailyReportOneHSlots[task.id] ?? null
          : null,
        isOneHReportTask: Boolean(task.is_1h_report),
      })
    }

    const tyoRank = (value: string) => {
      const trimmed = value.trim()
      if (!trimmed || trimmed === "-") return 3
      if (trimmed === "Y") return 1
      if (trimmed === "T") return 2
      if (/^\d+$/.test(trimmed)) return 0
      return 3
    }
    const tyoNumber = (value: string) => {
      const trimmed = value.trim()
      return /^\d+$/.test(trimmed) ? Number(trimmed) : -1
    }
    const sortByTyo = (a: (typeof rows)[number], b: (typeof rows)[number]) => {
      const rankA = tyoRank(a.tyo)
      const rankB = tyoRank(b.tyo)
      if (rankA !== rankB) return rankA - rankB
      if (rankA === 0) return tyoNumber(b.tyo) - tyoNumber(a.tyo)
      return 0
    }
    const importantDeadlineRank = (row: (typeof rows)[number]) => {
      const rowDate = row.sortDate ? toDate(row.sortDate) : null
      if (rowDate && dayKey(rowDate) === dayKey(selectedAllReportDate)) {
        if (titleHasEightAmIndicator(row.title)) return 0
        if (row.period === "PM") return 2
        return 1
      }
      return 3
    }
    const importantDeadlineSort = (a: (typeof rows)[number], b: (typeof rows)[number]) => {
      const rankA = importantDeadlineRank(a)
      const rankB = importantDeadlineRank(b)
      if (rankA !== rankB) return rankA - rankB
      const dateA = a.sortDate ? toDate(a.sortDate) : null
      const dateB = b.sortDate ? toDate(b.sortDate) : null
      const dateDiff = (dateA ? dayKey(dateA) : Number.MAX_SAFE_INTEGER) - (dateB ? dayKey(dateB) : Number.MAX_SAFE_INTEGER)
      if (dateDiff !== 0) return dateDiff
      const eightAmDiff = Number(titleHasEightAmIndicator(b.title)) - Number(titleHasEightAmIndicator(a.title))
      if (eightAmDiff !== 0) return eightAmDiff
      const periodDiff = (a.period === "PM" ? 1 : 0) - (b.period === "PM" ? 1 : 0)
      return periodDiff
    }
    const periodRank = (row: (typeof rows)[number]) => (row.period === "PM" ? 1 : 0)
    const typeRank = (row: (typeof rows)[number]) => (row.typeLabel === "SYS" ? 0 : 1)

    const sortedFastRows = fastRows
      .sort(
        (a, b) =>
          a.order - b.order ||
          Number(titleHasEightAmIndicator(b.row.title)) - Number(titleHasEightAmIndicator(a.row.title)) ||
          periodRank(a.row) - periodRank(b.row) ||
          a.index - b.index
      )
      .map((entry) => entry.row)
    rows.push(...doneLast(sortedFastRows))
    rows.push(...doneLast(systemAmRows))
    rows.push(...doneLast(projectRows.sort(sortByTyo)))
    rows.push(...doneLast(systemPmRows))

    return orderDoneReportRowsLast(orderOneHReportRowsBySlot(
      rows
        .map((row, index) => ({ row, index }))
        .sort((a, b) => {
        const doneDiff = Number(isRowDone(a.row)) - Number(isRowDone(b.row))
        if (doneDiff !== 0) return doneDiff
        const periodDiff = periodRank(a.row) - periodRank(b.row)
        if (periodDiff !== 0) return periodDiff
        const typeDiff = typeRank(a.row) - typeRank(b.row)
        if (typeDiff !== 0) return typeDiff
        const aImportant = deadlineImportantTaskIds.has(a.row.taskId || "")
        const bImportant = deadlineImportantTaskIds.has(b.row.taskId || "")
        const importantDiff = Number(bImportant) - Number(aImportant)
        if (importantDiff !== 0) return importantDiff
        if (aImportant && bImportant) {
          const deadlineDiff = importantDeadlineSort(a.row, b.row)
          if (deadlineDiff !== 0) return deadlineDiff
        }
        const eightAmDiff =
          Number(titleHasEightAmIndicator(b.row.title)) - Number(titleHasEightAmIndicator(a.row.title))
        if (eightAmDiff !== 0) return eightAmDiff
        const statusDiff =
          statusOrder[a.row.statusKey ?? "TODO"] - statusOrder[b.row.statusKey ?? "TODO"]
        if (statusDiff !== 0) return statusDiff
        return a.index - b.index
      })
        .map((entry) => entry.row)
    ))
  }, [
    dailyReport,
    dailyReportFastTasks,
    dailyReportProjectTasks,
    dailyReportOneHSlots,
    projects,
    projectTitleLookup,
    systemTemplateById,
    selectedAllReportDate,
    todaySystemTasks,
    deadlineImportantTaskIds,
    userMap,
    departmentCode,
    printInitials,
    completeTaskTitle,
  ])

  const dailyUserReportDisplayRows = React.useMemo(() => {
    if (!dailyReportManualOrder.length) return dailyUserReportRows

    const entries = dailyUserReportRows.map((row, index) => ({
      id: getDailyReportRowId(row, index),
      row,
    }))
    const entryMap = new Map(entries.map((entry) => [entry.id, entry.row]))
    const ordered: (typeof dailyUserReportRows)[number][] = []
    const used = new Set<string>()

    for (const id of dailyReportManualOrder) {
      const match = entryMap.get(id)
      if (!match) continue
      ordered.push(match)
      used.add(id)
    }

    for (const entry of entries) {
      if (used.has(entry.id)) continue
      ordered.push(entry.row)
    }
    return orderDoneReportRowsLast(orderOneHReportRowsBySlot([
      ...ordered.filter((row) => row.statusKey !== "DONE" && row.status?.toUpperCase() !== "DONE"),
      ...ordered.filter((row) => row.statusKey === "DONE" || row.status?.toUpperCase() === "DONE"),
    ]))
  }, [dailyReportManualOrder, dailyUserReportRows])

  const dailyReportAvailableStatuses = React.useMemo(() => {
    const seen = new Set<string>()
    const list: Array<{ key: string; label: string }> = []
    const statusOrder: Record<string, number> = {
      TODO: 0,
      IN_PROGRESS: 1,
      WAITING_CLIENT: 2,
      WAITING_CONFIRMATION: 3,
      DONE: 4,
    }
    for (const row of dailyUserReportDisplayRows) {
      const key = normalizeDailyReportStatusKey(row.status)
      if (!key || seen.has(key)) continue
      seen.add(key)
      list.push({ key, label: dailyReportStatusChipLabel(key) })
    }
    list.sort((a, b) => {
      const orderDiff = (statusOrder[a.key] ?? Number.MAX_SAFE_INTEGER) - (statusOrder[b.key] ?? Number.MAX_SAFE_INTEGER)
      if (orderDiff !== 0) return orderDiff
      return a.label.localeCompare(b.label)
    })
    return list
  }, [dailyUserReportDisplayRows])

  const dailyUserReportFilteredEntries = React.useMemo(() => {
    const selectedStatuses = new Set(dailyReportStatusFilter)
    return dailyUserReportDisplayRows
      .map((row, index) => ({
        id: getDailyReportRowId(row, index),
        row,
      }))
      .filter(({ row }) => {
        const rowPeriod = row.period?.toUpperCase().trim()
        const periodMatch =
          dailyReportPeriodFilter === "all" ||
          (dailyReportPeriodFilter === "am_side" && (rowPeriod === "AM" || rowPeriod === "AM/PM")) ||
          (dailyReportPeriodFilter === "pm_side" && (rowPeriod === "PM" || rowPeriod === "AM/PM"))
        if (!periodMatch) return false

        if (selectedStatuses.size === 0) return true
        const rowStatus = normalizeDailyReportStatusKey(row.status)
        return Boolean(rowStatus && selectedStatuses.has(rowStatus))
      })
  }, [dailyReportPeriodFilter, dailyReportStatusFilter, dailyUserReportDisplayRows])

  const toggleDailyReportStatusFilter = React.useCallback((statusKey: string) => {
    setDailyReportStatusFilter((prev) =>
      prev.includes(statusKey) ? prev.filter((entry) => entry !== statusKey) : [...prev, statusKey]
    )
  }, [])

  const dailyUserReportDisplayIds = React.useMemo(
    () => dailyUserReportDisplayRows.map((row, index) => getDailyReportRowId(row, index)),
    [dailyUserReportDisplayRows]
  )

  const handleDailyReportRowDrop = React.useCallback(
    (targetRowId: string) => {
      if (!dragDailyReportRowId) return
      if (dragDailyReportRowId === targetRowId) return

      setDailyReportManualOrder((prev) => {
        const base = prev.length ? [...prev] : [...dailyUserReportDisplayIds]
        const dragIndex = base.indexOf(dragDailyReportRowId)
        const targetIndex = base.indexOf(targetRowId)
        if (dragIndex < 0 || targetIndex < 0) return base
        const next = [...base]
        const [moved] = next.splice(dragIndex, 1)
        next.splice(targetIndex, 0, moved)
        return next
      })
      setOverDailyReportRowId(null)
      setDragDailyReportRowId(null)
    },
    [dailyUserReportDisplayIds, dragDailyReportRowId]
  )

  // Helper function to convert DailyReportResponse to rows for print view
  const convertDailyReportToRows = React.useCallback(
    (report: DailyReportResponse, userId: string): Array<{
      typeLabel: string
      subtype: string
      period: string
      department: string
      title: string
      projectTitle?: string | null
      description: string
      status: string
      statusKey?: "TODO" | "IN_PROGRESS" | "WAITING_CLIENT" | "WAITING_CONFIRMATION" | "DONE"
      bz: string
      kohaBz: string
      tyo: string
      comment?: string | null
      userInitials: string
      taskId?: string
      systemTemplateId?: string
      systemOccurrenceDate?: string
      systemStatus?: string
      sortDate?: string | null
      startDate?: string | null
      dueDate?: string | null
      oneHReportSlot?: OneHReportSlot | null
      isOneHReportTask?: boolean
      oneHMarker?: Task["one_h_marker"]
      oneHMarkerByGa?: boolean
    }> => {
      const rows: ReturnType<typeof convertDailyReportToRows> = []
      const systemAmRows: typeof rows = []
      const systemPmRows: typeof rows = []
      const fastRows: Array<{ order: number; index: number; row: (typeof rows)[number] }> = []
      const projectRows: typeof rows = []
      let fastIndex = 0
      const statusOrder = {
        TODO: 0,
        IN_PROGRESS: 1,
        WAITING_CLIENT: 2,
        WAITING_CONFIRMATION: 3,
        DONE: 4,
      } as const
      type StatusKey = keyof typeof statusOrder
      const normalizeTaskStatusKey = (task: Task): StatusKey => {
        const raw = task.status?.toUpperCase() || ""
        if (raw === "TODO" || raw === "IN_PROGRESS" || raw === "WAITING_CLIENT" || raw === "WAITING_CONFIRMATION" || raw === "DONE") {
          return raw
        }
        if (task.completed_at) return "DONE"
        return "TODO"
      }
      const isRowDone = (row: (typeof rows)[number]) => {
        return row.statusKey === "DONE" || row.status?.toUpperCase() === "DONE"
      }
      const doneLast = (items: Array<(typeof rows)[number]>) => {
        const open: Array<(typeof rows)[number]> = []
        const done: Array<(typeof rows)[number]> = []
        for (const item of items) {
          if (isRowDone(item)) {
            done.push(item)
          } else {
            open.push(item)
          }
        }
        return [...open, ...done]
      }
      const reportUser = userMap.get(userId)
      const rowUserInitials = initials(reportUser?.full_name || reportUser?.username || "")

      const pushSystemRow = (row: (typeof rows)[number]) => {
        if (row.period === "PM") {
          systemPmRows.push(row)
          return
        }
        systemAmRows.push(row)
      }

      const fastTypeOrder = (task: Task) => {
        const label = noProjectTypeLabel(task)
        if (label === "BLLOK") return 0
        if (label === "1H") return 1
        if (label === "Personal") return 2
        if (label === "R1") return 3
        if (label === "Normal") return 4
        return 5
      }

      // Process system tasks
      const allSystemTaskItems = [
        ...(report.system_today || []),
        ...(report.system_overdue || []),
      ]
      const systemTodayByTemplate = new Map<string, DailyReportResponse["system_today"][number]>()
      for (const item of report.system_today || []) {
        const templateId = item.task?.system_template_origin_id
        if (templateId) systemTodayByTemplate.set(templateId, item)
      }

      for (const item of allSystemTaskItems) {
        const task = item.task
        if (!task) continue
        const templateId = task.system_template_origin_id
        if (!templateId) continue
        const tmpl = systemTemplateById.get(templateId) || null
        const baseDate = toDate(task.start_date || task.origin_run_at || task.due_date || task.created_at)
        if (baseDate && dayKey(baseDate) > dayKey(selectedAllReportDate)) {
          continue
        }
        const alignmentEnabled = Boolean(
          tmpl?.requires_alignment ||
          tmpl?.alignment_time ||
          (tmpl?.alignment_user_ids && tmpl.alignment_user_ids.length) ||
          (tmpl?.alignment_roles && tmpl.alignment_roles.length)
        )
        const bzUsers = formatAlignmentUsers(tmpl?.alignment_user_ids, userMap)
        pushSystemRow({
          typeLabel: "SYS",
          subtype: tmpl ? systemFrequencyShortLabel(tmpl.frequency) : "SYS",
          period: resolvePeriod(task.finish_period ?? tmpl?.finish_period ?? null, task.due_date || task.start_date || task.created_at),
          department: departmentCode,
          title: task.title || "-",
          description: task.description || tmpl?.description || "-",
          status: taskStatusLabel(task),
          statusKey: normalizeTaskStatusKey(task),
          bz: alignmentEnabled
            ? bzUsers !== "-"
              ? formatAlignmentInitials(tmpl?.alignment_user_ids, userMap)
              : tmpl?.alignment_roles?.length
                ? tmpl.alignment_roles.join(", ")
                : "-"
            : "-",
          kohaBz: alignmentEnabled ? formatAlignmentTime(tmpl?.alignment_time) : "-",
          tyo: getTyoLabel(baseDate, task.completed_at, selectedAllReportDate),
          comment: task.user_comment ?? null,
          userInitials: rowUserInitials,
          taskId: task.id,
          oneHMarker: task.one_h_marker,
          oneHMarkerByGa: task.one_h_marker_by_ga,
          sortDate: task.due_date || task.start_date || task.origin_run_at || task.created_at,
          startDate: task.start_date || null,
          dueDate: task.due_date || null,
        })
      }

      // Process tasks from API response
      const allTaskItems = [
        ...(report.tasks_today || []),
        ...(report.tasks_overdue || []),
      ]

      for (const item of allTaskItems) {
        const task = item.task
        const startDate = task.start_date ? toDate(task.start_date) : null
        const dueDate = task.due_date ? toDate(task.due_date) : null
        const isProject = Boolean(task.project_id)
        const project = task.project_id ? projects.find((p) => p.id === task.project_id) || null : null
        const projectLabel = resolveProjectTitle(project) || item.project_title || null

        if (isProject) {
          projectRows.push({
            typeLabel: "PRJK",
            subtype: projectReportSubtypeShort(task),
            period: resolvePeriod(task.finish_period, task.due_date || task.start_date || task.created_at),
            department: departmentCode,
            title: task.title || "-",
            projectTitle: projectLabel,
            description: task.description || "-",
            status: taskStatusLabel(task),
            statusKey: normalizeTaskStatusKey(task),
            bz: "-",
            kohaBz: "-",
            tyo: getDailyReportTyo({
              reportDate: selectedAllReportDate,
              startDate,
              dueDate,
              mode: startDate && dueDate ? "range" : "dueOnly",
            }),
            comment: task.user_comment ?? null,
            userInitials: rowUserInitials,
            taskId: task.id,
            oneHMarker: task.one_h_marker,
            oneHMarkerByGa: task.one_h_marker_by_ga,
            sortDate: task.due_date || task.start_date || task.created_at,
            startDate: task.start_date || null,
            dueDate: task.due_date || null,
            oneHReportSlot: task.is_1h_report || task.is_r1
              ? dailyReportOneHSlots[task.id] ?? normalizeOneHReportSlot(task.one_h_report_slot)
              : null,
            isOneHReportTask: Boolean(task.is_1h_report),
          })
        } else {
          fastRows.push({
            order: fastTypeOrder(task),
            index: fastIndex,
            row: {
              typeLabel: "FT",
              subtype: fastReportSubtypeShort(task),
              period: resolvePeriod(task.finish_period, task.due_date || task.start_date || task.created_at),
              department: departmentCode,
              title: task.title || "-",
              description: task.description || "-",
              status: taskStatusLabel(task),
              statusKey: normalizeTaskStatusKey(task),
              bz: "-",
              kohaBz: "-",
              tyo: getDailyReportTyo({
                reportDate: selectedAllReportDate,
                startDate,
                dueDate,
                mode: startDate && dueDate ? "range" : "dueOnly",
              }),
              comment: task.user_comment ?? null,
              userInitials: rowUserInitials,
              taskId: task.id,
              oneHMarker: task.one_h_marker,
              oneHMarkerByGa: task.one_h_marker_by_ga,
              sortDate: task.due_date || task.start_date || task.created_at,
              startDate: task.start_date || null,
              dueDate: task.due_date || null,
              oneHReportSlot: task.is_1h_report || task.is_r1
                ? dailyReportOneHSlots[task.id] ?? normalizeOneHReportSlot(task.one_h_report_slot)
                : null,
              isOneHReportTask: Boolean(task.is_1h_report),
            },
          })
          fastIndex += 1
        }
      }

      const tyoRank = (value: string) => {
        const trimmed = value.trim()
        if (!trimmed || trimmed === "-") return 3
        if (trimmed === "Y") return 1
        if (trimmed === "T") return 2
        if (/^\d+$/.test(trimmed)) return 0
        return 3
      }
      const tyoNumber = (value: string) => {
        const trimmed = value.trim()
        return /^\d+$/.test(trimmed) ? Number(trimmed) : -1
      }
      const sortByTyo = (a: (typeof rows)[number], b: (typeof rows)[number]) => {
        const rankA = tyoRank(a.tyo)
        const rankB = tyoRank(b.tyo)
        if (rankA !== rankB) return rankA - rankB
        if (rankA === 0) return tyoNumber(b.tyo) - tyoNumber(a.tyo)
        return 0
      }
      const importantDeadlineRank = (row: (typeof rows)[number]) => {
        const rowDate = row.sortDate ? toDate(row.sortDate) : null
        if (rowDate && dayKey(rowDate) === dayKey(selectedAllReportDate)) {
          if (titleHasEightAmIndicator(row.title)) return 0
          if (row.period === "PM") return 2
          return 1
        }
        return 3
      }
      const importantDeadlineSort = (a: (typeof rows)[number], b: (typeof rows)[number]) => {
        const rankA = importantDeadlineRank(a)
        const rankB = importantDeadlineRank(b)
        if (rankA !== rankB) return rankA - rankB
        const dateA = a.sortDate ? toDate(a.sortDate) : null
        const dateB = b.sortDate ? toDate(b.sortDate) : null
        const dateDiff = (dateA ? dayKey(dateA) : Number.MAX_SAFE_INTEGER) - (dateB ? dayKey(dateB) : Number.MAX_SAFE_INTEGER)
        if (dateDiff !== 0) return dateDiff
        const eightAmDiff = Number(titleHasEightAmIndicator(b.title)) - Number(titleHasEightAmIndicator(a.title))
        if (eightAmDiff !== 0) return eightAmDiff
        return (a.period === "PM" ? 1 : 0) - (b.period === "PM" ? 1 : 0)
      }
      const periodRank = (row: (typeof rows)[number]) => (row.period === "PM" ? 1 : 0)
      const typeRank = (row: (typeof rows)[number]) => (row.typeLabel === "SYS" ? 0 : 1)

      const sortedFastRows = fastRows
        .sort(
          (a, b) =>
            a.order - b.order ||
            Number(titleHasEightAmIndicator(b.row.title)) - Number(titleHasEightAmIndicator(a.row.title)) ||
            periodRank(a.row) - periodRank(b.row) ||
            sortByTyo(a.row, b.row) ||
            a.index - b.index
        )
        .map((entry) => entry.row)
      rows.push(...doneLast(sortedFastRows))
      rows.push(...doneLast(systemAmRows.sort(sortByTyo)))
      rows.push(...doneLast(projectRows.sort(sortByTyo)))
      rows.push(...doneLast(systemPmRows.sort(sortByTyo)))

      return rows
          .map((row, index) => ({ row, index }))
          .sort((a, b) => {
          const doneDiff = Number(isRowDone(a.row)) - Number(isRowDone(b.row))
          if (doneDiff !== 0) return doneDiff
          const periodDiff = periodRank(a.row) - periodRank(b.row)
          if (periodDiff !== 0) return periodDiff
          const typeDiff = typeRank(a.row) - typeRank(b.row)
          if (typeDiff !== 0) return typeDiff
          const aImportant = deadlineImportantTaskIds.has(a.row.taskId || "")
          const bImportant = deadlineImportantTaskIds.has(b.row.taskId || "")
          const importantDiff = Number(bImportant) - Number(aImportant)
          if (importantDiff !== 0) return importantDiff
          if (aImportant && bImportant) {
            const deadlineDiff = importantDeadlineSort(a.row, b.row)
            if (deadlineDiff !== 0) return deadlineDiff
          }
          const eightAmDiff =
            Number(titleHasEightAmIndicator(b.row.title)) - Number(titleHasEightAmIndicator(a.row.title))
          if (eightAmDiff !== 0) return eightAmDiff
          const statusDiff =
            statusOrder[a.row.statusKey ?? "TODO"] - statusOrder[b.row.statusKey ?? "TODO"]
          if (statusDiff !== 0) return statusDiff
          if (isOneHReportRow(a.row) && isOneHReportRow(b.row)) {
            const slotDiff = oneHReportSlotRank(a.row) - oneHReportSlotRank(b.row)
            if (slotDiff !== 0) return slotDiff
          }
          return a.index - b.index
        })
          .map((entry) => entry.row)
    },
    [dailyReportOneHSlots, deadlineImportantTaskIds, departmentCode, projects, selectedAllReportDate, systemTemplateById, userMap]
  )

  const weekProjectTasks = React.useMemo(() => {
    return weekDates.map((date) => {
      return projectTasks
        .filter((task) => {
          const taskDate = toDate(task.due_date || task.start_date || task.created_at)
          return taskDate ? isSameDay(taskDate, date) : false
        })
        .map((task) => {
          const project = projects.find((p) => p.id === task.project_id) || null
          const projectLabel = resolveProjectTitle(project) || "Project"
          return `${projectLabel}: ${task.title}`
        })
        .sort((a, b) => a.localeCompare(b))
    })
  }, [projectTasks, projects, weekDates])
  const weekNoProjectTasks = React.useMemo(() => {
    const fallbackDate =
      weekDates.find((date) => isSameDay(date, todayDate)) || weekDates[0]
    return weekDates.map((date) => {
      return visibleNoProjectTasks
        .filter((task) => {
          const taskDate = toDate(task.due_date || task.start_date || task.planned_for)
          const resolvedDate = taskDate || fallbackDate
          return resolvedDate ? isSameDay(resolvedDate, date) : false
        })
        .map((task) => `${noProjectTypeLabel(task)}: ${task.title}`)
        .sort((a, b) => a.localeCompare(b))
    })
  }, [visibleNoProjectTasks, weekDates])
  const weekSystemTasks = React.useMemo(() => {
    return weekDates.map((date) => {
      return visibleSystemTemplates
        .filter((task) => shouldShowTemplate(task, date))
        .map((task) => task.title || "System task")
        .sort((a, b) => a.localeCompare(b))
    })
  }, [visibleSystemTemplates, weekDates])
  const weekMeetings = React.useMemo(() => {
    return weekDates.map((date) => {
      return visibleMeetings
        .filter((meeting) => {
          if (!meeting.starts_at) return false
          const start = new Date(meeting.starts_at)
          if (Number.isNaN(start.getTime())) return false
          return isSameDay(start, date)
        })
        .map(formatMeetingPrintLabel)
        .sort((a, b) => a.localeCompare(b))
    })
  }, [visibleMeetings, weekDates])
  const printRows = React.useMemo(
    () => [
      { id: "project", label: "Project tasks", itemsByDay: weekProjectTasks },
      { id: "no-project", label: "Fast tasks", itemsByDay: weekNoProjectTasks },
      { id: "system", label: "System tasks", itemsByDay: weekSystemTasks },
      { id: "meetings", label: "Meetings", itemsByDay: weekMeetings },
    ],
    [weekMeetings, weekNoProjectTasks, weekProjectTasks, weekSystemTasks]
  )
  const weekRangeLabel = React.useMemo(() => {
    const start = weekDates[0]
    const end = weekDates[weekDates.length - 1]
    if (!start || !end) return ""
    const startLabel = formatDateDMY(start)
    const endLabel = formatDateDMY(end)
    return `${startLabel} - ${endLabel}`
  }, [weekDates])
  const todayProjectPrint = React.useMemo(() => {
    return todayProjectTasks
      .map((task) => {
        const project = task.project_id ? projects.find((p) => p.id === task.project_id) || null : null
        const projectLabel = resolveProjectTitle(project) || "Project"
        return `${projectLabel}: ${task.title}`
      })
      .sort((a, b) => a.localeCompare(b))
  }, [projects, todayProjectTasks])
  const todayNoProjectPrint = React.useMemo(() => {
    return todayNoProjectTasks
      .map((task) => `${noProjectTypeLabel(task)}: ${task.title}`)
      .sort((a, b) => a.localeCompare(b))
  }, [todayNoProjectTasks])
  const todaySystemPrint = React.useMemo(() => {
    return todaySystemTasks.map((task) => task.title || "System task").sort((a, b) => a.localeCompare(b))
  }, [todaySystemTasks])
  const todayMeetingsPrint = React.useMemo(() => {
    return todayMeetings.map(formatMeetingPrintLabel).sort((a, b) => a.localeCompare(b))
  }, [todayMeetings])
  const printDates = React.useMemo(() => {
    return printRange === "today" ? [todayDate] : weekDates
  }, [printRange, todayDate, weekDates])
  const printRowsByRange = React.useMemo(() => {
    if (printRange === "today") {
      return [
        { id: "project", label: "Project tasks", itemsByDay: [todayProjectPrint] },
        { id: "no-project", label: "Fast tasks", itemsByDay: [todayNoProjectPrint] },
        { id: "system", label: "System tasks", itemsByDay: [todaySystemPrint] },
        { id: "meetings", label: "Meetings", itemsByDay: [todayMeetingsPrint] },
      ]
    }
    return printRows
  }, [
    printRange,
    printRows,
    todayMeetingsPrint,
    todayNoProjectPrint,
    todayProjectPrint,
    todaySystemPrint,
  ])
  const weeklyTaskReportRows = React.useMemo(() => {
    const start = printRange === "today" ? todayDate : weekDates[0]
    const end = printRange === "today" ? todayDate : weekDates[weekDates.length - 1]
    if (!start || !end) return []

    const startKey = new Date(start.getFullYear(), start.getMonth(), start.getDate()).getTime()
    const endKey = new Date(end.getFullYear(), end.getMonth(), end.getDate()).getTime()
    const isInRange = (date: Date | null) => {
      if (!date) return false
      const key = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
      return key >= startKey && key <= endKey
    }

    const rows: {
      typeLabel: string
      subtype: string
      priority: string
      period: string
      title: string
      projectTitle?: string | null
      description: string
      status: string
    }[] = []

    for (const task of projectTasks) {
      const taskDate = toDate(task.due_date || task.start_date || task.created_at)
      if (!isInRange(taskDate)) continue
      const project = task.project_id ? projects.find((p) => p.id === task.project_id) || null : null
      const subtype = resolveProjectTitle(project) || "-"
      rows.push({
        typeLabel: "PRJK",
        subtype,
        projectTitle: resolveProjectTitle(project) || null,
        priority: reportPriorityLabel(task.priority),
        period: resolvePeriod(task.finish_period, task.due_date || task.start_date || task.created_at),
        title: task.title || "-",
        description: task.description || "-",
        status: reportStatusLabel(task.status),
      })
    }

    for (const task of visibleNoProjectTasks) {
      const taskDate = toDate(task.due_date || task.start_date || task.planned_for || task.created_at)
      if (!isInRange(taskDate)) continue
      rows.push({
        typeLabel: "FAST",
        subtype: fastSubtypeLabel(task),
        priority: reportPriorityLabel(task.priority),
        period: resolvePeriod(task.finish_period, task.due_date || task.start_date || task.created_at),
        title: task.title || "-",
        description: task.description || "-",
        status: reportStatusLabel(task.status),
      })
    }

    for (const tmpl of visibleSystemTemplates) {
      const occursInRange =
        printRange === "today"
          ? shouldShowTemplate(tmpl, todayDate)
          : weekDates.some((date) => shouldShowTemplate(tmpl, date))
      if (!occursInRange) continue
      rows.push({
        typeLabel: "SYSTEM",
        subtype: systemFrequencyLabel(String(tmpl.frequency || "")),
        priority: reportPriorityLabel(tmpl.priority),
        period: resolvePeriod(tmpl.finish_period, null),
        title: tmpl.title || "-",
        description: tmpl.description || "-",
        status: "-",
      })
    }

    return rows
  }, [
    printRange,
    projectTasks,
    projects,
    todayDate,
    visibleNoProjectTasks,
    visibleSystemTemplates,
    weekDates,
  ])
  const printRangeLabel = React.useMemo(() => {
    if (printRange === "today") {
      const dateLabel = formatDateDMY(todayDate)
      return `Today - ${dateLabel}`
    }
    return weekRangeLabel
  }, [printRange, todayDate, weekRangeLabel])

  const allTodayPrintBaseUsers = React.useMemo(() => {
    if (viewMode === "department") {
      if (selectedUserId !== "__all__") {
        const selected = departmentUsers.find((member) => member.id === selectedUserId)
        return selected ? [selected] : []
      }
      return departmentUsers.filter((member) => {
        const username = member.username?.toLowerCase()
        const fullName = member.full_name?.toLowerCase()
        return username !== "admin" && fullName !== "admin"
      })
    }
    if (user) {
      return [
        {
          id: user.id,
          full_name: user.full_name,
          username: user.username,
        },
      ]
    }
    return []
  }, [departmentUsers, selectedUserId, user, viewMode])

  const allTodayPrintItems = React.useMemo(() => {
    const items: Array<{
      userId: string
      period: "AM" | "PM" | "AM/PM"
      label: string
      category: "PRJK" | "FT" | "SYS" | "EXM" | "GA" | "IN"
      fastType?: string
    }> = []
    for (const task of todayProjectTasks) {
      const project = task.project_id ? projects.find((p) => p.id === task.project_id) || null : null
      const projectLabel = resolveProjectTitle(project) || "Project"
      const period = resolvePeriod(task.finish_period, task.due_date || task.start_date || task.created_at)
      const userId = task.assigned_to || task.assigned_to_user_id || task.created_by || "__unassigned__"
      items.push({
        userId,
        period,
        label: `${projectLabel}: ${task.title}`,
        category: "PRJK",
      })
    }
    for (const task of todayNoProjectTasks) {
      const period = resolvePeriod(task.finish_period, task.due_date || task.start_date || task.created_at)
      const userId = task.assigned_to || task.assigned_to_user_id || task.created_by || "__unassigned__"
      const fastType = noProjectTypeLabel(task)
      items.push({
        userId,
        period,
        label: task.title,
        category: "FT",
        fastType,
      })
    }
    for (const task of todaySystemTasks) {
      const period = resolvePeriod(task.finish_period, task.created_at)
      const userId = task.assigned_to || task.assigned_to_user_id || task.created_by || "__unassigned__"
      items.push({
        userId,
        period,
        label: `${task.title || "System task"}`,
        category: "SYS",
      })
    }
    for (const note of todayInternalNotes) {
      const period = periodFromDate(note.created_at)
      const userId = note.to_user_id || "__unassigned__"
      items.push({
        userId,
        period,
        label: `IN: ${note.title || "Internal note"}`,
        category: "IN",
      })
    }
    for (const meeting of todayMeetings) {
      const period = periodFromDate(meeting.starts_at)
      const userId = meeting.created_by || "__unassigned__"
      items.push({
        userId,
        period,
        label: `${formatMeetingPrintLabel(meeting)}`,
        category: "EXM",
      })
    }
    return items
  }, [
    projects,
    todayInternalNotes,
    todayMeetings,
    todayNoProjectTasks,
    todayProjectTasks,
    todaySystemTasks,
  ])

  const allTodayPrintHasUnassigned = React.useMemo(
    () => allTodayPrintItems.some((item) => item.userId === "__unassigned__"),
    [allTodayPrintItems]
  )

  const allTodayPrintColumns = React.useMemo(() => {
    const baseIds = new Set(allTodayPrintBaseUsers.map((member) => member.id))
    const extraIds = Array.from(
      new Set(
        allTodayPrintItems
          .map((item) => item.userId)
          .filter((userId) => userId !== "__unassigned__" && !baseIds.has(userId))
      )
    )
    const extraColumns = extraIds
      .map((userId) => {
        const user = userMap.get(userId)
        return {
          id: userId,
          label: user?.full_name || user?.username || "Unknown",
        }
      })
      .filter((column) => {
        if (column.label === "Unknown") return false
        const label = column.label.toLowerCase()
        return label !== "admin"
      })
    const columns = allTodayPrintBaseUsers.map((member) => ({
      id: member.id,
      label: member.full_name || member.username || "-",
    }))
      .concat(extraColumns)
    if (allTodayPrintHasUnassigned) {
      columns.push({ id: "__unassigned__", label: "Unassigned" })
    }
    return columns
  }, [allTodayPrintBaseUsers, allTodayPrintHasUnassigned, allTodayPrintItems, userMap])

  const allTodayPrintByUser = React.useMemo(() => {
    const categories = ["PRJK", "FT", "SYS", "EXM", "GA", "IN"] as const
    const map = new Map<
      string,
      Record<string, Array<{ period: "AM" | "PM" | "AM/PM"; label: string; fastType?: string }>>
    >()
    const ensure = (userId: string) => {
      if (!map.has(userId)) {
        const emptyBuckets = categories.reduce<
          Record<string, Array<{ period: "AM" | "PM" | "AM/PM"; label: string; fastType?: string }>>
        >(
          (acc, category) => {
            acc[category] = []
            return acc
          },
          {}
        )
        map.set(userId, { ...emptyBuckets })
      }
      return map.get(userId)!
    }
    for (const column of allTodayPrintColumns) {
      ensure(column.id)
    }
    for (const item of allTodayPrintItems) {
      const bucket = ensure(item.userId)
      bucket[item.category].push({ period: item.period, label: item.label, fastType: item.fastType })
    }
    for (const bucket of map.values()) {
      for (const category of categories) {
        bucket[category].sort((a, b) => a.label.localeCompare(b.label))
      }
    }
    return map
  }, [allTodayPrintColumns, allTodayPrintItems])

  const projectTaskGroups = React.useMemo(() => {
    const map = new Map<string, Task[]>()
    for (const task of projectTasks) {
      if (!task.project_id) continue
      const list = map.get(task.project_id) || []
      list.push(task)
      map.set(task.project_id, list)
    }
    return Array.from(map.entries()).map(([projectId, tasks]) => {
      const project = projects.find((p) => p.id === projectId) || null
      return {
        id: projectId,
        name: resolveProjectTitle(project) || "Project",
        tasks,
      }
    })
  }, [projectTasks, projects])

  const counts = React.useMemo(
    () => ({
      all:
        todayProjectTasks.length +
        todayNoProjectTasks.length +
        todaySystemTasks.length +
        todayMeetings.length,
      projects: filteredProjects.length,
      system: visibleSystemTemplates.length,
      "no-project": selectedDateNoProjectTasks.length,
      "internal-notes": groupedInternalNotes.length,
      meetings: meetingTabMeetings.length,
    }),
    [
      filteredProjects.length,
      visibleSystemTemplates.length,
      selectedDateNoProjectTasks.length,
      visibleInternalNotes.length,
      meetingTabMeetings,
      projectTasks.length,
      todayProjectTasks.length,
      todayNoProjectTasks.length,
      todayMeetings.length,
      todaySystemTasks.length,
    ]
  )
  const todayProjectTasksSorted = React.useMemo(
    () => sortDoneLast(todayProjectTasks, (task) => taskStatusValue(task) === "DONE"),
    [sortDoneLast, todayProjectTasks]
  )
  const todayNoProjectTasksSorted = React.useMemo(
    () => sortDoneLast(todayNoProjectTasks, (task) => taskStatusValue(task) === "DONE"),
    [sortDoneLast, todayNoProjectTasks]
  )
  const todayWaitingProjectTasks = React.useMemo(
    () => todayProjectTasksSorted.filter((task) => taskStatusValue(task) === "WAITING_CONFIRMATION"),
    [todayProjectTasksSorted]
  )
  const todayWaitingNoProjectTasks = React.useMemo(
    () => todayNoProjectTasksSorted.filter((task) => taskStatusValue(task) === "WAITING_CONFIRMATION"),
    [todayNoProjectTasksSorted]
  )
  const crossDepartmentWaitingTasks = React.useMemo(() => {
    if (!isMineView || !user?.id) return []
    return crossDepartmentVisibleTasks
      .filter(
        (task) =>
          task.confirmation_assignee_id === user.id && taskStatusValue(task) === "WAITING_CONFIRMATION"
      )
      .filter((task) => {
        const matchesRange = matchesTaskAllRange(task)
        const completedToday = isTaskCompletedInAllRange(task)
        const overdue = isTaskOverdue(task)
        if (allRange === "all" && taskStatusValue(task) === "DONE") return false
        return matchesRange || completedToday || overdue
      })
  }, [
    allRange,
    crossDepartmentVisibleTasks,
    isMineView,
    isTaskCompletedInAllRange,
    isTaskOverdue,
    matchesTaskAllRange,
    user?.id,
  ])
  const todayWaitingTasks = React.useMemo(
    () => {
      const merged = [
        ...todayWaitingProjectTasks.map((task) => ({ task, type: "Project" as const })),
        ...todayWaitingNoProjectTasks.map((task) => ({ task, type: "Fast" as const })),
        ...crossDepartmentWaitingTasks.map((task) => ({
          task,
          type: task.project_id ? ("Project" as const) : ("Fast" as const),
        })),
      ]
      const byId = new Map<string, { task: Task; type: "Project" | "Fast" }>()
      for (const item of merged) {
        if (!byId.has(item.task.id)) byId.set(item.task.id, item)
      }
      return Array.from(byId.values())
    },
    [crossDepartmentWaitingTasks, todayWaitingNoProjectTasks, todayWaitingProjectTasks]
  )
  const allTodayTaskLookup = React.useMemo(() => {
    const map = new Map<string, Task>()
    for (const task of departmentTasks) map.set(task.id, task)
    for (const task of noProjectTasks) map.set(task.id, task)
    for (const task of systemCreatedTasks) map.set(task.id, task)
    for (const task of crossDepartmentVisibleTasks) map.set(task.id, task)
    return map
  }, [crossDepartmentVisibleTasks, departmentTasks, noProjectTasks, systemCreatedTasks])
  const allTodayEditingTask = React.useMemo(
    () => (allTodayEditingTaskId ? allTodayTaskLookup.get(allTodayEditingTaskId) ?? null : null),
    [allTodayEditingTaskId, allTodayTaskLookup]
  )
  const allTodayCompletingRlzTask = Boolean(
    allTodayEditingTask &&
    allTodayEditStatus === "DONE" &&
    taskStatusValue(allTodayEditingTask) !== "DONE" &&
    taskRequiresRlzCompletionComment(allTodayEditingTask)
  )
  const allTodayActorIsAssignee = Boolean(
    allTodayEditingTask && user?.id && isTaskAssignedToUser(allTodayEditingTask, user.id)
  )
  const allTodayUsesCompletionOverride = Boolean(
    allTodayCompletingRlzTask &&
    !allTodayActorIsAssignee &&
    (user?.role === "ADMIN" || user?.role === "MANAGER")
  )
  const todaySystemTasksSorted = React.useMemo(
    () => sortDoneLast(todaySystemTasks, (task) => taskStatusValue(task) === "DONE"),
    [sortDoneLast, todaySystemTasks]
  )
  const showAllTodayPrint = activeTab === "all" && viewMode === "department"
  const gaTableDirty = gaTableInput !== (gaTableEntry?.content ?? "")

  // Daily Report is only available in My View.
  React.useEffect(() => {
    let cancelled = false
    const run = async () => {
      const shouldFetchDailyReport =
        viewMode === "mine" && (activeTab === "all" || activeTab === "system")
      if (!shouldFetchDailyReport) {
        setDailyReport(null)
        setDailyReportOneHSlots({})
        setLoadingDailyReport(false)
        return
      }
      const targetUserId = user?.id
      if (!department?.id || !targetUserId) {
        setDailyReport(null)
        setDailyReportOneHSlots({})
        setLoadingDailyReport(false)
        return
      }
      // Show the last copy of this report at once; the request below refreshes it.
      const dailyReportCacheKey = `daily-report|${department.id}|${targetUserId}|${selectedAllReportIso}`
      const cachedDailyReport = await readPersistentPageCache<DailyReportResponse>(dailyReportCacheKey)
      if (cancelled) return
      if (cachedDailyReport) {
        setDailyReport(cachedDailyReport)
        setDailyReportOneHSlots(buildDailyReportOneHSlotMap(cachedDailyReport))
      } else {
        setLoadingDailyReport(true)
      }
      try {
        const qs = new URLSearchParams({
          day: selectedAllReportIso,
          department_id: department.id,
          user_id: targetUserId,
        })
        const res = await apiFetch(`/reports/daily?${qs.toString()}`)
        if (!res.ok) {
          setDailyReport(null)
          setDailyReportOneHSlots({})
          return
        }
        const payload = (await res.json()) as DailyReportResponse
        if (!cancelled) {
          setDailyReport(payload)
          setDailyReportOneHSlots(buildDailyReportOneHSlotMap(payload))
          void writePersistentPageCache(dailyReportCacheKey, payload)
        }
      } catch {
        if (!cancelled) {
          setDailyReport(null)
          setDailyReportOneHSlots({})
        }
      } finally {
        if (!cancelled) setLoadingDailyReport(false)
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [activeTab, apiFetch, department?.id, selectedAllReportIso, user?.id, viewMode])

  const refreshDailyReport = React.useCallback(async () => {
    const shouldFetchDailyReport =
      viewMode === "mine" && (activeTab === "all" || activeTab === "system")
    if (!shouldFetchDailyReport) return
    const targetUserId = user?.id
    if (!department?.id || !targetUserId) return
    try {
      const qs = new URLSearchParams({
        day: selectedAllReportIso,
        department_id: department.id,
        user_id: targetUserId,
      })
      const res = await apiFetch(`/reports/daily?${qs.toString()}`)
      if (!res.ok) return
      const payload = (await res.json()) as DailyReportResponse
      setDailyReport(payload)
      setDailyReportOneHSlots(buildDailyReportOneHSlotMap(payload))
    } catch {
      // ignore refresh failures
    }
  }, [activeTab, apiFetch, department?.id, selectedAllReportIso, user?.id, viewMode])

  const loadTaskChecklist = React.useCallback(async (taskId: string) => {
    if (!taskId || taskChecklists[taskId] !== undefined) return
    setTaskChecklistLoading((prev) => ({ ...prev, [taskId]: true }))
    try {
      const res = await apiFetch(`/checklists?task_id=${taskId}&include_items=true`)
      if (!res.ok) {
        let detail = "Failed to load checklist"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(typeof detail === "string" ? detail : "Failed to load checklist")
        setTaskChecklists((prev) => ({ ...prev, [taskId]: null }))
        return
      }
      const data = (await res.json()) as TaskChecklist[]
      const checklist = data.length ? data[0] : null
      setTaskChecklists((prev) => ({ ...prev, [taskId]: checklist }))
    } catch (error) {
      console.error("Failed to load task checklist", error)
      toast.error("Failed to load checklist")
      setTaskChecklists((prev) => ({ ...prev, [taskId]: null }))
    } finally {
      setTaskChecklistLoading((prev) => ({ ...prev, [taskId]: false }))
    }
  }, [apiFetch, taskChecklists])

  const toggleTaskChecklist = React.useCallback((taskId: string) => {
    if (!taskId) return
    setTaskChecklistOpen((prev) => ({ ...prev, [taskId]: !prev[taskId] }))
    if (taskChecklists[taskId] === undefined) {
      void loadTaskChecklist(taskId)
    }
  }, [loadTaskChecklist, taskChecklists])

  useVisibleRefresh(async () => {
    if (activeTab === "all" || activeTab === "system") await refreshDailyReport()
    else await loadBootstrapData({ silent: true })
  }, viewMode === "mine" && !editingTaskId)

  React.useEffect(() => {
    if (!dailyUserReportRows.length) return
    const taskIds = new Set<string>()
    for (const row of dailyUserReportRows) {
      if (row.typeLabel !== "PRJK") continue
      if (!row.taskId) continue
      taskIds.add(row.taskId)
    }
    for (const taskId of taskIds) {
      if (taskChecklists[taskId] === undefined) {
        void loadTaskChecklist(taskId)
      }
    }
  }, [dailyUserReportRows, loadTaskChecklist, taskChecklists])

  React.useEffect(() => {
    let cancelled = false
    const run = async () => {
      if (activeTab !== "all" || viewMode !== "mine") {
        setGaTableEntry(null)
        setGaTableInput("")
        return
      }
      if (!department?.id || !user?.id) {
        setGaTableEntry(null)
        setGaTableInput("")
        return
      }
      try {
        const qs = new URLSearchParams({
          day: selectedAllReportIso,
          department_id: department.id,
          user_id: user.id,
        })
        const res = await apiFetch(`/reports/daily-ga-table?${qs.toString()}`)
        if (!res.ok) {
          if (!cancelled) {
            setGaTableEntry(null)
            setGaTableInput("")
          }
          return
        }
        const payload = (await res.json()) as DailyReportGaTableResponse
        if (cancelled) return
        setGaTableEntry(payload.entry ?? null)
        setGaTableInput(payload.entry?.content ?? "")
      } catch {
        if (!cancelled) {
          setGaTableEntry(null)
          setGaTableInput("")
        }
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [activeTab, apiFetch, department?.id, selectedAllReportIso, user?.id, viewMode])

  const saveGaTableEntry = React.useCallback(
    async (nextValue: string) => {
      if (!department?.id || !user?.id) return
      setSavingGaTable(true)
      try {
        const res = await apiFetch("/reports/daily-ga-entry", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            day: selectedAllReportIso,
            department_id: department.id,
            content: nextValue,
          }),
        })
        if (!res.ok) return
        const payload = (await res.json()) as DailyReportGaEntry
        setGaTableEntry(payload)
        setGaTableInput(payload.content ?? "")
      } finally {
        setSavingGaTable(false)
      }
    },
    [apiFetch, department?.id, selectedAllReportIso, user?.id]
  )

  // Fetch daily reports for all users when showing All Today print view
  React.useEffect(() => {
    let cancelled = false
    const run = async () => {
      if (!showAllTodayPrint || !department?.id || allTodayPrintBaseUsers.length === 0) {
        setAllUsersDailyReports(new Map())
        setLoadingAllUsersDailyReports(false)
        return
      }
      setLoadingAllUsersDailyReports(true)
      try {
        const reportsMap = new Map<string, DailyReportResponse>()
        await Promise.all(
          allTodayPrintBaseUsers.map(async (member) => {
            try {
              const qs = new URLSearchParams({
                day: selectedAllReportIso,
                department_id: department.id,
                user_id: member.id,
              })
              const res = await apiFetch(`/reports/daily?${qs.toString()}`)
              if (res.ok && !cancelled) {
                const payload = (await res.json()) as DailyReportResponse
                reportsMap.set(member.id, payload)
              }
            } catch {
              // Ignore errors for individual users
            }
          })
        )
        if (!cancelled) {
          setAllUsersDailyReports(reportsMap)
        }
      } catch {
        if (!cancelled) {
          setAllUsersDailyReports(new Map())
        }
      } finally {
        if (!cancelled) {
          setLoadingAllUsersDailyReports(false)
        }
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [showAllTodayPrint, department?.id, allTodayPrintBaseUsers, selectedAllReportIso, apiFetch])

  const handlePrint = React.useCallback(() => {
    // In "My View" mode, automatically show daily report for printing
    if (viewMode === "mine" && !showDailyUserReport) {
      setShowDailyUserReport(true)
      setPrintRange("today")
      // Use setTimeout to ensure state updates before printing
      setTimeout(() => {
        window.print()
      }, 0)
      return
    }

    if (showAllTodayPrint && loadingAllUsersDailyReports) {
      setPendingPrint(true)
      return
    }
    window.print()
  }, [loadingAllUsersDailyReports, showAllTodayPrint, viewMode, showDailyUserReport])

  React.useEffect(() => {
    if (!pendingPrint) return
    if (loadingAllUsersDailyReports) return
    if (!showAllTodayPrint) {
      setPendingPrint(false)
      return
    }
    setPendingPrint(false)
    const timer = window.setTimeout(() => window.print(), 0)
    return () => window.clearTimeout(timer)
  }, [loadingAllUsersDailyReports, pendingPrint, showAllTodayPrint])

  const canCreate = user?.role === "ADMIN" || user?.role === "MANAGER" || user?.role === "STAFF"
  const isReadOnly = viewMode === "mine"
  const canCreateNoProjectTask = canCreate
  const canEditAllTodayTask = React.useCallback(
    (task?: Task | null) => {
      if (!task || !user?.id) return false
      if (viewMode === "mine") return true
      if (viewMode !== "department") return false
      if (user.role === "ADMIN" || user.role === "MANAGER") return true
      return isTaskOwnedByViewUser(task, user.id)
    },
    [isTaskOwnedByViewUser, user?.id, user?.role, viewMode]
  )
  const canManage = canCreate && !isReadOnly
  const canManageDepartmentSystemDateEdit = user?.role === "ADMIN" || user?.role === "MANAGER"
  const showSystemActions = viewMode === "mine"
  const canDeleteProjects = user?.role === "ADMIN" && !isReadOnly
  const canDeleteNoProject = user?.role === "ADMIN" && !isReadOnly
  const canDeleteAllTodayTask = user?.role === "ADMIN" && !isReadOnly
  const canEditNoProjectTask = React.useCallback(
    (task?: Task | null) => {
      if (!task || !user?.id) return false
      if (user.role === "ADMIN" || user.role === "MANAGER") return true
      return isTaskAssignedToUser(task, user.id)
    },
    [isTaskAssignedToUser, user?.id, user?.role]
  )
  const editingNoProjectTask = React.useMemo(
    () =>
      editingTaskId
        ? noProjectTasks.find((task) => task.id === editingTaskId) ??
          departmentTasks.find((task) => task.id === editingTaskId) ??
          null
        : null,
    [departmentTasks, editingTaskId, noProjectTasks]
  )
  const canOpenNoProjectEditDialog = !editingTaskId || canEditNoProjectTask(editingNoProjectTask)
  const allTodayPrintCategories = React.useMemo(
    () => [
      { id: "PRJK", label: "PRJK" },
      { id: "FT", label: "FT" },
      { id: "SYS", label: "SYS" },
      { id: "EXM", label: "EXM" },
      { id: "GA", label: "GA" },
      { id: "IN", label: "IN" },
    ],
    []
  )

  const visibleSystemTasks = React.useMemo(() => {
    if (showAllSystem) return visibleSystemTemplates
    return visibleSystemTemplates.filter((t) => {
      return shouldShowTemplate(t, systemDate) || isSystemTaskOverdueForDate(t, systemDate)
    })
  }, [isSystemTaskOverdueForDate, showAllSystem, systemDate, visibleSystemTemplates])

  const noProjectBuckets = React.useMemo(() => {
    const normal: Task[] = []
    const personal: Task[] = []
    const blocked: Task[] = []
    const oneHour: Task[] = []
    const r1: Task[] = []

    for (const t of selectedDateNoProjectTasks) {
      if (t.is_bllok) {
        blocked.push(t)
      } else if (t.is_r1) {
        r1.push(t)
      } else if (t.is_1h_report) {
        oneHour.push(t)
      } else if (t.is_personal) {
        personal.push(t)
      } else if (isFastNormalTask(t)) {
        normal.push(t)
      }
    }
    return {
      normal: sortDoneLast(normal, (task) => taskStatusValue(task) === "DONE"),
      personal: sortDoneLast(personal, (task) => taskStatusValue(task) === "DONE"),
      blocked: sortDoneLast(blocked, (task) => taskStatusValue(task) === "DONE"),
      oneHour: sortDoneLast(oneHour, (task) => taskStatusValue(task) === "DONE"),
      r1: sortDoneLast(r1, (task) => taskStatusValue(task) === "DONE"),
    }
  }, [selectedDateNoProjectTasks, sortDoneLast, taskStatusValue])

  const statusRows = [
    {
      id: "blocked",
      title: "BLLOK",
      count: noProjectBuckets.blocked.length,
      items: noProjectBuckets.blocked,
      headerBg: "bg-white",
      headerText: "text-slate-700",
      badgeClass: "bg-white text-red-600 border border-red-200",
      borderClass: "border-red-500",
      itemBadge: "BLLOK",
      itemBadgeClass: "bg-white text-red-600 border-red-200",
    },
    {
      id: "one-hour",
      title: "1H TASKS",
      count: noProjectBuckets.oneHour.length,
      items: noProjectBuckets.oneHour,
      headerBg: "bg-white",
      headerText: "text-slate-700",
      badgeClass: "bg-white text-indigo-600 border border-indigo-200",
      borderClass: "border-indigo-500",
      itemBadge: "1H",
      itemBadgeClass: "bg-white text-indigo-600 border-indigo-200",
    },
    {
      id: "r1",
      title: "R1",
      count: noProjectBuckets.r1.length,
      items: noProjectBuckets.r1,
      headerBg: "bg-white",
      headerText: "text-slate-700",
      badgeClass: "bg-white text-emerald-600 border border-emerald-200",
      borderClass: "border-emerald-500",
      itemBadge: "R1",
      itemBadgeClass: "bg-white text-emerald-600 border-emerald-200",
    },
    {
      id: "personal",
      title: "PERSONAL",
      count: noProjectBuckets.personal.length,
      items: noProjectBuckets.personal,
      headerBg: "bg-white",
      headerText: "text-slate-700",
      badgeClass: "bg-white text-purple-600 border border-purple-200",
      borderClass: "border-purple-500",
      itemBadge: "Personal",
      itemBadgeClass: "bg-white text-purple-600 border-purple-200",
    },
    {
      id: "normal",
      title: "NORMAL",
      count: noProjectBuckets.normal.length,
      items: noProjectBuckets.normal,
      headerBg: "bg-white",
      headerText: "text-slate-700",
      badgeClass: "bg-white text-blue-600 border border-slate-200",
      borderClass: "border-blue-500",
      itemBadge: "Normal",
      itemBadgeClass: "bg-white text-blue-600 border-slate-200",
    },
  ] as const

  const systemGroups = React.useMemo(() => {
    const groups = new Map<string, SystemTaskTemplate[]>()
    for (const t of visibleSystemTasks) {
      const key = FREQUENCY_LABELS[t.frequency] || "Daily"
      const list = groups.get(key) || []
      list.push(t)
      groups.set(key, list)
    }
    return Array.from(groups.entries()).map(([label, items]) => ({
      label,
      items: items.sort((a, b) => {
        const rank = (value?: string | null) => {
          if (value === "HIGH") return 3
          if (value === "NORMAL") return 2
          return 0
        }
        const byPriority = rank(b.priority) - rank(a.priority)
        if (byPriority !== 0) return byPriority
        return a.title.localeCompare(b.title)
      }),
    }))
  }, [visibleSystemTasks])

  // Helper function for assignee summary
  const assigneeSummary = (list?: SystemTaskTemplate["assignees"]) => {
    if (!list || list.length === 0) return "-"
    if (list.length <= 2) {
      return list
        .map((person) => person.full_name || person.username || ("email" in person ? person.email : ""))
        .join(", ")
    }
    return `${list.length} people`
  }

  // Flattened and sorted list of all system tasks for table view
  const sortedSystemTasks = React.useMemo(() => {
    const frequencyOrder: Record<SystemTaskTemplate["frequency"], number> = {
      DAILY: 0,
      WEEKLY: 1,
      MONTHLY: 2,
      "3_MONTHS": 3,
      "6_MONTHS": 4,
      YEARLY: 5,
    }
    const priorityOrder: Record<TaskPriority, number> = {
      HIGH: 0,
      NORMAL: 1,
      BLLOK: 2,
    }
    return [...visibleSystemTasks].sort((a, b) => {
      const aInactive = !a.is_active
      const bInactive = !b.is_active
      if (aInactive !== bInactive) return aInactive ? 1 : -1
      const aFrequency = frequencyOrder[a.frequency] ?? 999
      const bFrequency = frequencyOrder[b.frequency] ?? 999
      if (aFrequency !== bFrequency) return aFrequency - bFrequency
      const aPriority = priorityOrder[normalizePriority(a.priority)]
      const bPriority = priorityOrder[normalizePriority(b.priority)]
      if (aPriority !== bPriority) return aPriority - bPriority
      const aCreated = a.created_at ? new Date(a.created_at).getTime() : 0
      const bCreated = b.created_at ? new Date(b.created_at).getTime() : 0
      if (aCreated !== bCreated) return bCreated - aCreated
      return a.title.localeCompare(b.title)
    })
  }, [visibleSystemTasks])

  const handleCloseTaskClick = (task: SystemTaskTemplate) => {
    setTaskToCloseId(task.id)
    setTaskToCloseTemplate(task)
    setCloseTaskComment("")
    setCloseTaskDialogOpen(true)
  }

  const confirmCloseTask = async () => {
    if (!taskToCloseId) return

    if (!closeTaskComment.trim()) {
      toast.error("Comment is required to close this task")
      return
    }

    setClosingTask(true)
    const closeComment = closeTaskComment.trim()
    const templateId = taskToCloseTemplate?.template_id ?? taskToCloseTemplate?.id ?? taskToCloseId
    const hasRealTaskRow = Boolean(taskToCloseTemplate?.template_id && taskToCloseTemplate.id !== taskToCloseTemplate.template_id)

    try {
      if (hasRealTaskRow) {
        const commentRes = await apiFetch(`/tasks/${taskToCloseId}/comment`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ comment: closeComment }),
        })
        if (!commentRes.ok) {
          toast.error("Failed to save the required result comment")
          return
        }
        const updateRes = await apiFetch(`/tasks/${taskToCloseId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: "DONE" }),
        })
        if (!updateRes.ok) {
          toast.error("Para mbylljes, shto komentin për rezultatin e kësaj detyre.")
          return
        }
      } else {
        const occurrenceBaseDate = taskToCloseTemplate
          ? findPreviousOccurrenceDate(taskToCloseTemplate, systemDate)
          : systemDate
        const occurrenceDate = formatDateInput(occurrenceBaseDate)
        const res = await apiFetch("/system-tasks/occurrences", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            template_id: templateId,
            occurrence_date: occurrenceDate,
            status: "DONE",
            comment: closeComment,
          }),
        })
        if (!res.ok) {
          toast.error("Failed to close system task")
          return
        }
      }

      setSystemTasks((prev) =>
        prev.map((task) => {
          const matchesTask = task.id === taskToCloseId
          const matchesTemplate = !hasRealTaskRow && (task.template_id ?? task.id) === templateId
          return matchesTask || matchesTemplate
            ? { ...task, status: "DONE", user_comment: closeComment }
            : task
        })
      )

      // Reload system tasks
      const sysRes = await apiFetch(
        `/system-tasks?department_id=${department?.id || ""}&occurrence_date=${formatDateInput(systemDate)}&include_overdue=true`
      )
      if (sysRes.ok) {
        setSystemTasks((await sysRes.json()) as SystemTaskTemplate[])
      }

      void refreshDailyReport()
      setCloseTaskDialogOpen(false)
      setTaskToCloseId(null)
      setTaskToCloseTemplate(null)
      setCloseTaskComment("")
      toast.success("Task closed successfully")
    } catch (err) {
      console.error("Failed to close task", err)
      toast.error("Failed to close task")
    } finally {
      setClosingTask(false)
    }
  }

  const canEditSystemDateRow = React.useCallback(
    (task: SystemTaskTemplate, occurrenceStatus?: string | null) => {
      if (!user?.id) return false
      const normalizedStatus = (occurrenceStatus || task.status || "").toUpperCase()
      if (normalizedStatus === "DONE") return false
      const isAssigned =
        task.default_assignee_id === user.id ||
        Boolean(task.assignees?.some((assignee) => assignee.id === user.id))
      if (viewMode === "mine") return isAssigned
      return canManageDepartmentSystemDateEdit
    },
    [canManageDepartmentSystemDateEdit, user?.id, viewMode]
  )

  const openSystemDateEditor = React.useCallback(
    (task: SystemTaskTemplate, occurrenceStatus?: string | null) => {
      const normalizedStatus = (occurrenceStatus || task.status || "").toUpperCase()
      if (normalizedStatus === "DONE") {
        toast.error("Done system tasks cannot be edited")
        return
      }
      const source = toDateInputValue(task.due_date || systemTaskDisplayDate(task)) || todayInputValue()
      setEditingSystemTaskId(task.id)
      setEditingSystemDateSource(source)
      setEditingSystemDateTarget(source)
      setEditingSystemDateTitle(task.title || "System task")
    },
    []
  )

  const closeSystemDateEditor = React.useCallback(() => {
    setEditingSystemTaskId(null)
    setEditingSystemDateSource("")
    setEditingSystemDateTarget("")
    setEditingSystemDateTitle("")
    setSavingSystemDateOverride(false)
  }, [])

  const saveSystemDateOverride = React.useCallback(async () => {
    if (!editingSystemTaskId || !editingSystemDateSource || !editingSystemDateTarget) return
    setSavingSystemDateOverride(true)
    try {
      const res = await apiFetch(`/tasks/${editingSystemTaskId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          due_date: new Date(`${editingSystemDateTarget}T12:00:00`).toISOString(),
        }),
      })
      if (!res.ok) {
        let detail = "Failed to update system task due date"
        try {
          const payload = (await res.json()) as { detail?: string }
          if (payload?.detail) detail = payload.detail
        } catch {
          // ignore parse failures
        }
        toast.error(detail)
        return
      }

      setSystemTasks((prev) =>
        prev.map((task) => {
          if (task.id !== editingSystemTaskId) return task
          return {
            ...task,
            due_date: new Date(`${editingSystemDateTarget}T12:00:00`).toISOString(),
          }
        })
      )

      const sysRes = await apiFetch(
        `/system-tasks?department_id=${department?.id || ""}&occurrence_date=${formatDateInput(systemDate)}&include_overdue=true`
      )
      if (sysRes.ok) {
        setSystemTasks((await sysRes.json()) as SystemTaskTemplate[])
      }

      void refreshDailyReport()
      closeSystemDateEditor()
      toast.success("System task due date updated")
    } catch {
      toast.error("Failed to update system task due date")
    } finally {
      setSavingSystemDateOverride(false)
    }
  }, [
    apiFetch,
    closeSystemDateEditor,
    department?.id,
    editingSystemDateSource,
    editingSystemDateTarget,
    editingSystemTaskId,
    refreshDailyReport,
    systemDate,
  ])

  const updateTaskCommentState = (taskId: string, comment: string | null) => {
    setDepartmentTasks((prev) =>
      prev.map((task) => (task.id === taskId ? { ...task, user_comment: comment } : task))
    )
    setNoProjectTasks((prev) =>
      prev.map((task) => (task.id === taskId ? { ...task, user_comment: comment } : task))
    )
  }

  const updateTaskOneHReportSlotState = React.useCallback((taskId: string, oneHReportSlot: OneHReportSlot | null) => {
    setDailyReportOneHSlots((prev) => ({ ...prev, [taskId]: oneHReportSlot }))
    setDailyReport((prev) => {
      if (!prev) return prev
      const applySlot = (task: Task) =>
        task.id === taskId ? { ...task, one_h_report_slot: oneHReportSlot } : task
      const applyItemSlot = <T extends { task: Task }>(items: T[]) =>
        items.map((item) => (item.task.id === taskId ? { ...item, task: applySlot(item.task) } : item))
      return {
        ...prev,
        tasks_today: applyItemSlot(prev.tasks_today),
        tasks_overdue: applyItemSlot(prev.tasks_overdue),
        system_today: applyItemSlot(prev.system_today),
        system_overdue: applyItemSlot(prev.system_overdue),
      }
    })
  }, [])

  const saveOneHReportSlot = React.useCallback(
    async (taskId: string, slotValue: string) => {
      const nextSlot = slotValue === ONE_H_REPORT_SLOT_NONE_VALUE ? null : normalizeOneHReportSlot(slotValue)
      setSavingOneHReportSlotTaskId(taskId)
      try {
        let res = await apiFetch(`/tasks/${taskId}/one-h-report-slot`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            report_date: selectedAllReportIso,
            one_h_report_slot: nextSlot,
          }),
        })
        if (res.status === 400 || res.status === 404 || res.status === 500) {
          res = await apiFetch(`/tasks/${taskId}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              one_h_report_slot: nextSlot,
            }),
          })
        }
        if (!res.ok) {
          const data = await res.json().catch(() => null)
          toast.error(data?.detail || "Failed to save 1H time")
          return
        }
        updateTaskOneHReportSlotState(taskId, nextSlot)
      } catch (error) {
        console.error("Failed to save 1H time", error)
        toast.error("Failed to save 1H time")
      } finally {
        setSavingOneHReportSlotTaskId((current) => (current === taskId ? null : current))
      }
    },
    [apiFetch, selectedAllReportIso, updateTaskOneHReportSlotState]
  )

  const setDailyReportCommentSaving = (commentKey: string, isSaving: boolean) => {
    setSavingDailyReportComments((prev) => ({ ...prev, [commentKey]: isSaving }))
  }

  const isDragTargetInteractive = (target: EventTarget | null) => {
    if (!(target instanceof HTMLElement)) return false
    const tag = target.tagName
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "BUTTON" || tag === "SELECT" || tag === "LABEL"
  }

  const handleDailyReportMouseDown = (event: React.MouseEvent<HTMLDivElement>) => {
    if (event.button !== 0) return
    if (isDragTargetInteractive(event.target)) return
    const container = dailyReportScrollRef.current
    if (!container) return
    dailyReportDragRef.current = {
      isDragging: true,
      startX: event.pageX - container.offsetLeft,
      startScrollLeft: container.scrollLeft,
    }
    setIsDraggingDailyReport(true)
  }

  const handleDailyReportMouseMove = (event: React.MouseEvent<HTMLDivElement>) => {
    const dragState = dailyReportDragRef.current
    if (!dragState.isDragging) return
    const container = dailyReportScrollRef.current
    if (!container) return
    const x = event.pageX - container.offsetLeft
    const walk = x - dragState.startX
    container.scrollLeft = dragState.startScrollLeft - walk
  }

  const handleDailyReportMouseEnd = () => {
    if (!dailyReportDragRef.current.isDragging) return
    dailyReportDragRef.current.isDragging = false
    setIsDraggingDailyReport(false)
  }

  const saveDailyReportTaskComment = async (
    taskId: string,
    nextValue: string,
    previousValue: string,
    commentKey: string
  ) => {
    const trimmed = nextValue.trim()
    const previousTrimmed = previousValue.trim()
    if (trimmed === previousTrimmed) return

    const payloadComment = trimmed.length ? trimmed : null
    setDailyReportCommentSaving(commentKey, true)
    try {
      const res = await apiFetch(`/tasks/${taskId}/comment`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ comment: payloadComment }),
      })
      if (!res.ok) {
        const data = await res.json()
        toast.error(data.detail || "Failed to save comment")
        setDailyReportCommentEdits((prev) => ({ ...prev, [commentKey]: previousValue }))
        return
      }
      updateTaskCommentState(taskId, payloadComment)
      setDailyReportCommentEdits((prev) => ({ ...prev, [commentKey]: trimmed }))
    } catch (error) {
      console.error("Failed to save comment", error)
      toast.error("Failed to save comment")
      setDailyReportCommentEdits((prev) => ({ ...prev, [commentKey]: previousValue }))
    } finally {
      setDailyReportCommentSaving(commentKey, false)
    }
  }

  const exportDailyReport = async () => {
    if (!department?.id || !user?.id) return
    setExportingDailyReport(true)
    try {
      const qs = new URLSearchParams({
        day: selectedAllReportIso,
        department_id: department.id,
        user_id: user.id,
      })
      const res = await apiFetch(`/exports/daily-report.xlsx?${qs.toString()}`)
      if (!res.ok) {
        toast.error("Failed to export report")
        return
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      const disposition = res.headers.get("Content-Disposition")
      const match = disposition?.match(/filename=\"?([^\";]+)\"?/i)
      if (match?.[1]) {
        link.download = match[1]
      }
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (error) {
      console.error("Failed to export report", error)
      toast.error("Failed to export report")
    } finally {
      setExportingDailyReport(false)
    }
  }

  const exportAllTodayReport = async () => {
    if (!department?.id) return
    setExportingDailyReport(true)
    try {
      const exportDay =
        allRange === "date"
          ? formatDateInput(selectedAllDate)
          : allRange === "tomorrow"
            ? formatDateInput(tomorrowDate)
            : todayIso
      const qs = new URLSearchParams({
        day: exportDay,
        department_id: department.id,
        all_today: "true",
      })
      if (allRange === "all") {
        qs.set("all_open", "true")
      }
      if (selectedUserId && selectedUserId !== "__all__") {
        qs.set("user_id", selectedUserId)
      } else {
        qs.set("all_users", "true")
      }
      const res = await apiFetch(`/exports/daily-report.xlsx?${qs.toString()}`)
      if (!res.ok) {
        toast.error("Failed to export report")
        return
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      const disposition = res.headers.get("Content-Disposition")
      const match = disposition?.match(/filename=\"?([^\";]+)\"?/i)
      if (match?.[1]) {
        link.download = match[1]
      }
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (error) {
      console.error("Failed to export report", error)
      toast.error("Failed to export report")
    } finally {
      setExportingDailyReport(false)
    }
  }

  const exportInternalMeetings = async () => {
    if (exportingInternalMeetings) return
    setExportingInternalMeetings(true)
    try {
      const qs = new URLSearchParams({
        group_key: INTERNAL_MEETING_GROUP_KEY,
        title: "Development Internal Meetings",
      })
      const res = await apiFetch(`/exports/department-internal-meetings.xlsx?${qs.toString()}`)
      if (!res.ok) {
        const detail = await res.text().catch(() => "")
        toast.error(detail || "Failed to export internal meetings")
        return
      }

      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      const disposition = res.headers.get("Content-Disposition")
      const match = disposition?.match(/filename=\"?([^\";]+)\"?/i)
      link.download = match?.[1] || "DEVELOPMENT_INTERNAL_MEETINGS.xlsx"
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (error) {
      console.error("Failed to export internal meetings", error)
      toast.error("Failed to export internal meetings")
    } finally {
      setExportingInternalMeetings(false)
    }
  }

  const looksLikeFullName = (title: string): boolean => {
    const trimmed = title.trim()
    if (!trimmed) return false
    const upper = trimmed.toUpperCase()

    // Check for common company suffixes
    const companyWords = [
      "COMPANY",
      "COMP",
      "INC",
      "INCORPORATED",
      "LLC",
      "LTD",
      "LIMITED",
      "CORP",
      "CORPORATION",
      "GROUP",
      "ENTERPRISES",
      "SOLUTIONS",
      "SYSTEMS",
      "SERVICES",
    ]
    const hasCompanyWord = companyWords.some((word) => upper.includes(word))

    // Check for multiple words or long titles (shortcuts should be short).
    const wordCount = trimmed.split(/\s+/).filter(Boolean).length
    const isTooLong = upper.length > 6

    return hasCompanyWord || wordCount > 1 || isTooLong
  }

  const handleProjectTitleChange = (value: string) => {
    const upperValue = value.toUpperCase()
    setProjectTitle(upperValue)
  }

  const attemptSubmitProject = () => {
    const trimmedTitle = projectTitle.trim()
    if (!trimmedTitle || !department) return

    setPendingProjectTitle(trimmedTitle)
    setShowTitleWarning(true)
  }

  const submitProject = async () => {
    if (!projectTitle.trim() || !department) return
    setCreatingProject(true)
    try {
      const normalizedDueDate = normalizeDueDateInput(projectDueDate.trim())
      const payload = {
        title: projectTitle.trim(),
        description: projectDescription.trim() || null,
        department_id: department.id,
        manager_id: projectMemberIds.length > 0 ? projectMemberIds[0] : (projectManagerId === "__unassigned__" ? null : projectManagerId),
        status: projectStatus,
        ...(normalizedDueDate ? { due_date: new Date(normalizedDueDate).toISOString() } : {}),
      }

      const res = await apiFetch("/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        let detail = "Failed to create project"
        try {
          const data = await res.json()
          if (Array.isArray(data)) {
            detail = data.map(e => `${e.loc.join('.')}: ${e.msg}`).join(', ')
          } else if (data?.detail) {
            detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
          }
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }
      const created = (await res.json()) as Project

      // Add project members if any were selected
      if (projectMemberIds.length > 0) {
        try {
          const memberRes = await apiFetch("/project-members", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              project_id: created.id,
              user_ids: projectMemberIds.filter((id) => id !== "__unassigned__"),
            }),
          })
          if (memberRes.ok) {
            // Reload members for the newly created project
            const members = (await memberRes.json()) as UserLookup[]
            setProjectMembers((prev) => ({ ...prev, [created.id]: members }))
          } else {
            console.error("Failed to add project members")
          }
        } catch (error) {
          console.error("Error adding project members:", error)
        }
      }

      setProjects((prev) => [created, ...prev])
      setCreateProjectOpen(false)
      setProjectTitle("")
      setProjectDescription("")
      setProjectManagerId("__unassigned__")
      setProjectMemberIds([])
      setProjectMemberIds([])
      setProjectStatus("TODO")
      setProjectDueDate("")
      toast.success("Project created")
    } finally {
      setCreatingProject(false)
    }
  }

  const deleteProject = async (projectId: string) => {
    const project = projects.find((p) => p.id === projectId)
    const projectLabel = resolveProjectTitle(project) || "this project"
    const confirmed = await confirm({
      title: "Delete project",
      description: `Delete "${projectLabel}"? This cannot be undone.`,
      confirmLabel: "Delete",
      variant: "destructive",
    })
    if (!confirmed) return

    setDeletingProjectId(projectId)
    try {
      const res = await apiFetch(`/projects/${projectId}`, { method: "DELETE" })
      if (!res.ok) {
        let detail = "Failed to delete project"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }
      setProjects((prev) => prev.filter((p) => p.id !== projectId))
      toast.success("Project deleted")
    } finally {
      setDeletingProjectId((prev) => (prev === projectId ? null : prev))
    }
  }

  const deleteNoProjectTask = async (taskId: string) => {
    const task = noProjectTasks.find((t) => t.id === taskId)
    const taskLabel = task?.title || "this task"
    const confirmed = await confirm({
      title: "Delete task",
      description: `Delete "${taskLabel}"? This cannot be undone.`,
      confirmLabel: "Delete",
      variant: "destructive",
    })
    if (!confirmed) return

    setDeletingNoProjectTaskId(taskId)
    try {
      const res = await apiFetch(`/tasks/${taskId}`, { method: "DELETE" })
      if (!res.ok) {
        let detail = "Failed to delete task"
        try {
          const data = (await res.json()) as { detail?: string }
          if (typeof data?.detail === "string") detail = data.detail
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }
      setDepartmentTasks((prev) => prev.filter((t) => t.id !== taskId))
      setNoProjectTasks((prev) => prev.filter((t) => t.id !== taskId))
      toast.success("Task deleted")
    } finally {
      setDeletingNoProjectTaskId((prev) => (prev === taskId ? null : prev))
    }
  }

  const deleteAllTodayTask = async (taskId: string) => {
    const task = allTodayTaskLookup.get(taskId) || null
    const taskLabel = task?.title || "this task"
    const confirmed = await confirm({
      title: "Delete task",
      description: `Delete "${taskLabel}"? This cannot be undone.`,
      confirmLabel: "Delete",
      variant: "destructive",
    })
    if (!confirmed) return

    setDeletingAllTodayTaskId(taskId)
    try {
      const res = await apiFetch(`/tasks/${taskId}`, { method: "DELETE" })
      if (!res.ok) {
        let detail = "Failed to delete task"
        try {
          const data = (await res.json()) as { detail?: string }
          if (typeof data?.detail === "string") detail = data.detail
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }
      setDepartmentTasks((prev) => prev.filter((t) => t.id !== taskId))
      setNoProjectTasks((prev) => prev.filter((t) => t.id !== taskId))
      setSystemCreatedTasks((prev) => prev.filter((t) => t.id !== taskId))
      setCrossDepartmentConfirmTasks((prev) => prev.filter((t) => t.id !== taskId))
      toast.success("Task deleted")
    } finally {
      setDeletingAllTodayTaskId((prev) => (prev === taskId ? null : prev))
    }
  }

  const startEditTask = (task: Task) => {
    if (!canEditNoProjectTask(task)) {
      toast.error("You do not have permission to edit this task")
      return
    }
    const plainTitle = getPlainMarkedText(task.title)
    setEditingTaskId(task.id)
    setEditTaskTitle(plainTitle)
    setEditTaskDescription(task.description || "")
    setEditTaskType(
      task.is_bllok
        ? "blocked"
        : task.is_1h_report
          ? "hourly"
          : task.is_r1
            ? "r1"
            : task.is_personal
              ? "personal"
              : "normal"
    )
    const statusValue = (task.status || "").toUpperCase()
    setEditTaskStatus(
      ALL_TODAY_TASK_STATUS_OPTIONS.includes(statusValue as (typeof ALL_TODAY_TASK_STATUS_OPTIONS)[number])
        ? statusValue
        : "TODO"
    )
    setEditTaskConfirmationAssigneeId(task.confirmation_assignee_id || "")
    setEditTaskStartDate(toDateInputValue(task.start_date))
    setEditTaskDueDate(toDateInputValue(task.due_date))
    setEditTaskFinishPeriod(task.finish_period || FINISH_PERIOD_NONE_VALUE)
    setEditTaskDeadlineImportant(Boolean(task.is_deadline_important))
    // Get assignees from assignees array, fallback to assigned_to for backward compatibility
    const assigneeIds = task.assignees && task.assignees.length > 0
      ? task.assignees.map(a => a.id).filter((id): id is string => Boolean(id))
      : (task.assigned_to ? [task.assigned_to] : [])
    setEditTaskAssignees(assigneeIds)
    setEditTaskInitialAssignees(assigneeIds)
    if (task.ga_note_origin_id) {
      void loadGaNoteTaskAssigneeIds(apiFetch, task.ga_note_origin_id)
        .then((gaAssigneeIds) => {
          setEditTaskAssignees(gaAssigneeIds)
          setEditTaskInitialAssignees(gaAssigneeIds)
        })
        .catch((error) => console.warn("Failed to load GA task membership", error))
    }
  }

  const cancelEditTask = () => {
    setEditingTaskId(null)
    setEditTaskTitle("")
    setEditTaskDescription("")
    setEditTaskType("normal")
    setEditTaskStatus("TODO")
    setEditTaskConfirmationAssigneeId("")
    setEditTaskStartDate("")
    setEditTaskDueDate("")
    setEditTaskFinishPeriod(FINISH_PERIOD_NONE_VALUE)
    setEditTaskDeadlineImportant(false)
    setEditTaskAssignees([])
    setEditTaskInitialAssignees([])
  }

  const sameIdSet = (a: string[], b: string[]) => {
    if (a.length !== b.length) return false
    const aSet = new Set(a)
    if (aSet.size !== b.length) return false
    for (const id of b) {
      if (!aSet.has(id)) return false
    }
    return true
  }

  const updateNoProjectTask = async () => {
    if (!editingTaskId || !editTaskTitle.trim() || !editTaskStartDate) return
    setUpdatingTask(true)
    try {
      const editingTask = noProjectTasks.find((candidate) => candidate.id === editingTaskId) || null
      const confirmationValidation = validateWaitingConfirmation(editTaskStatus, editTaskConfirmationAssigneeId)
      if (confirmationValidation) {
        toast.error(confirmationValidation)
        return
      }
      const startDateValue = editTaskStartDate ? new Date(editTaskStartDate).toISOString() : null
      const dueDateValue = editTaskDueDate ? new Date(editTaskDueDate).toISOString() : null
      const assigneesChanged = !sameIdSet(editTaskAssignees, editTaskInitialAssignees)
      let gaMembershipChanged = false
      let removedEditingCopy = false
      const payload: Record<string, unknown> = (editingTask?.ga_note_origin_id || editingTask?.plan_note_origin_id)
        ? {
            status: editTaskStatus,
            start_date: startDateValue,
            due_date: dueDateValue,
            finish_period: editTaskFinishPeriod === FINISH_PERIOD_NONE_VALUE ? null : editTaskFinishPeriod,
            is_deadline_important: editTaskDeadlineImportant,
            priority: "NORMAL",
            is_bllok: editTaskType === "blocked",
            is_1h_report: editTaskType === "hourly",
            is_r1: editTaskType === "r1",
            is_personal: editTaskType === "personal",
            ...(isWaitingConfirmation(editTaskStatus)
              ? { confirmation_assignee_id: editTaskConfirmationAssigneeId }
              : {}),
          }
        : {
            title: buildMarkedAppendOnlyText(editingTask?.title, editTaskTitle.trim()),
            description: editTaskDescription.trim() || null,
            is_bllok: editTaskType === "blocked",
            is_1h_report: editTaskType === "hourly",
            is_r1: editTaskType === "r1",
            is_personal: editTaskType === "personal",
            status: editTaskStatus,
            start_date: startDateValue,
            due_date: dueDateValue,
            finish_period: editTaskFinishPeriod === FINISH_PERIOD_NONE_VALUE ? null : editTaskFinishPeriod,
            is_deadline_important: editTaskDeadlineImportant,
            ...(isWaitingConfirmation(editTaskStatus)
              ? { confirmation_assignee_id: editTaskConfirmationAssigneeId }
              : {}),
          }
      if (assigneesChanged && editingTask?.ga_note_origin_id) {
        const membershipRes = await replaceGaNoteTaskAssignees(
          apiFetch,
          editingTask.ga_note_origin_id,
          editTaskAssignees
        )
        if (!membershipRes.ok) {
          let detail = "Failed to update GA task assignees"
          try {
            const data = (await membershipRes.json()) as { detail?: string }
            if (typeof data.detail === "string") detail = data.detail
          } catch {
            // Keep fallback.
          }
          toast.error(detail)
          return
        }
        gaMembershipChanged = true
        removedEditingCopy = Boolean(
          editingTask.assigned_to && !editTaskAssignees.includes(editingTask.assigned_to)
        )
      } else if (assigneesChanged && editingTask?.plan_note_origin_id) {
        toast.error("Change PX JAV task assignees from PX JAV")
        return
      } else if (assigneesChanged) {
        payload.assignees = editTaskAssignees
        payload.assigned_to = editTaskAssignees.length > 0 ? editTaskAssignees[0] : null
      }
      if (removedEditingCopy) {
        await loadBootstrapData({ silent: true })
        cancelEditTask()
        toast.success("Task assignees updated")
        return
      }
      const res = await apiFetch(`/tasks/${editingTaskId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        let detail = "Failed to update task"
        try {
          const data = (await res.json()) as { detail?: string }
          if (typeof data?.detail === "string") detail = data.detail
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }
      const updated = (await res.json()) as Task
      if (gaMembershipChanged) {
        await loadBootstrapData({ silent: true })
      } else {
        setDepartmentTasks((prev) => prev.map((t) => (t.id === editingTaskId ? updated : t)))
        setNoProjectTasks((prev) => prev.map((t) => (t.id === editingTaskId ? updated : t)))
      }
      cancelEditTask()
      toast.success("Task updated")
    } finally {
      setUpdatingTask(false)
    }
  }

  const startAllTodayTaskEdit = (task: Task) => {
    if (!canEditAllTodayTask(task)) {
      toast.error("You do not have permission to edit this task")
      return
    }
    const plainTitle = getPlainMarkedText(task.title)
    setAllTodayEditingTaskId(task.id)
    setAllTodayPlanningDetail({
      taskId: task.id,
      brief: task.planning_brief ?? null,
      loading: Boolean(task.plan_note_origin_id),
    })
    if (task.plan_note_origin_id) {
      void (async () => {
        try {
          const detailRes = await apiFetch(`/tasks/${task.id}`)
          if (!detailRes.ok) throw new Error("Failed to load PX JAV planning")
          const detail = (await detailRes.json()) as Task
          setAllTodayPlanningDetail((current) => (
            current?.taskId === task.id
              ? { taskId: task.id, brief: detail.planning_brief ?? null, loading: false }
              : current
          ))
        } catch {
          setAllTodayPlanningDetail((current) => (
            current?.taskId === task.id ? { ...current, loading: false } : current
          ))
          toast.error("Planifikimi PX JAV nuk u ngarkua")
        }
      })()
    }
    setAllTodayEditTitle(plainTitle)
    setAllTodayEditDescription(task.description || "")
    setAllTodayEditType(getAllTodayTaskType(task))
    const statusValue = (task.status || "").toUpperCase()
    setAllTodayEditStatus(
      ALL_TODAY_TASK_STATUS_OPTIONS.includes(statusValue as (typeof ALL_TODAY_TASK_STATUS_OPTIONS)[number])
        ? statusValue
        : "TODO"
    )
    setAllTodayEditConfirmationAssigneeId(task.confirmation_assignee_id || "")
    setAllTodayEditStartDate(toDateInputValue(task.start_date))
    setAllTodayEditDueDate(toDateInputValue(task.due_date))
    setAllTodayEditFinishPeriod(task.finish_period || FINISH_PERIOD_NONE_VALUE)
    setAllTodayEditDeadlineImportant(Boolean(task.is_deadline_important))
    setAllTodayEditCompletionNote(task.user_comment || "")
  }

  const cancelAllTodayTaskEdit = () => {
    setAllTodayEditingTaskId(null)
    setAllTodayPlanningDetail(null)
    setAllTodayEditStatus("TODO")
    setAllTodayEditTitle("")
    setAllTodayEditDescription("")
    setAllTodayEditType("normal")
    setAllTodayEditConfirmationAssigneeId("")
    setAllTodayEditStartDate("")
    setAllTodayEditDueDate("")
    setAllTodayEditFinishPeriod(FINISH_PERIOD_NONE_VALUE)
    setAllTodayEditDeadlineImportant(false)
    setAllTodayEditCompletionNote("")
  }

  const updateAllTodayTask = async () => {
    if (!allTodayEditingTaskId || !allTodayEditStatus) return
    const editingTask = allTodayTaskLookup.get(allTodayEditingTaskId) || null
    if (!canEditAllTodayTask(editingTask)) {
      toast.error("You do not have permission to edit this task")
      return
    }
    const isNoteOriginTask = Boolean(editingTask?.ga_note_origin_id || editingTask?.plan_note_origin_id)
    const isCompletingRlzTask = Boolean(
      editingTask &&
      allTodayEditStatus === "DONE" &&
      taskStatusValue(editingTask) !== "DONE" &&
      taskRequiresRlzCompletionComment(editingTask)
    )
    const actorIsAssignee = Boolean(editingTask && user?.id && isTaskAssignedToUser(editingTask, user.id))
    const usesCompletionOverride = Boolean(
      isCompletingRlzTask &&
      !actorIsAssignee &&
      (user?.role === "ADMIN" || user?.role === "MANAGER")
    )
    if (isCompletingRlzTask && !allTodayEditCompletionNote.trim()) {
      toast.error(
        usesCompletionOverride
          ? "Shkruaj arsyen pse po e mbyll këtë detyrë për përgjegjësin."
          : "Shkruaj komentin e rezultatit para se ta mbyllësh detyrën."
      )
      return
    }
    const confirmationValidation = validateWaitingConfirmation(allTodayEditStatus, allTodayEditConfirmationAssigneeId)
    if (confirmationValidation) {
      toast.error(confirmationValidation)
      return
    }
    setAllTodayUpdating(true)
    try {
      if (isCompletingRlzTask && actorIsAssignee) {
        const comment = allTodayEditCompletionNote.trim()
        if (comment !== (editingTask?.user_comment || "").trim()) {
          const commentRes = await apiFetch(`/tasks/${allTodayEditingTaskId}/comment`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ comment }),
          })
          if (!commentRes.ok) {
            const data = await commentRes.json().catch(() => null)
            toast.error(taskUpdateErrorMessage(data, "Failed to save result comment"))
            return
          }
        }
      }
      const isProjectLinked = hasProjectId(editingTask?.project_id)
      const startDateValue = allTodayEditStartDate ? new Date(allTodayEditStartDate).toISOString() : null
      const dueDateValue = allTodayEditDueDate ? new Date(allTodayEditDueDate).toISOString() : null
      const res = await apiFetch(`/tasks/${allTodayEditingTaskId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...(isNoteOriginTask
            ? {
                status: allTodayEditStatus,
                start_date: startDateValue,
                due_date: dueDateValue,
                finish_period: allTodayEditFinishPeriod === FINISH_PERIOD_NONE_VALUE ? null : allTodayEditFinishPeriod,
                is_deadline_important: allTodayEditDeadlineImportant,
                priority: allTodayEditType === "high" ? "HIGH" : "NORMAL",
                is_bllok: allTodayEditType === "blocked",
                is_1h_report: allTodayEditType === "hourly",
                is_r1: allTodayEditType === "r1",
                is_personal: allTodayEditType === "personal",
                ...(isWaitingConfirmation(allTodayEditStatus)
                  ? { confirmation_assignee_id: allTodayEditConfirmationAssigneeId }
                  : {}),
              }
            : {
                title: buildMarkedAppendOnlyText(editingTask?.title, allTodayEditTitle.trim()),
                description: allTodayEditDescription.trim() || null,
                ...(isProjectLinked
                  ? {
                      priority: allTodayEditType === "high" ? "HIGH" : "NORMAL",
                      is_bllok: allTodayEditType === "blocked",
                      is_1h_report: allTodayEditType === "hourly",
                      is_r1: allTodayEditType === "r1",
                      is_personal: allTodayEditType === "personal",
                    }
                  : {
                      is_bllok: allTodayEditType === "blocked",
                      is_1h_report: allTodayEditType === "hourly",
                      is_r1: allTodayEditType === "r1",
                      is_personal: allTodayEditType === "personal",
                    }),
                status: allTodayEditStatus,
                start_date: startDateValue,
                due_date: dueDateValue,
                finish_period: allTodayEditFinishPeriod === FINISH_PERIOD_NONE_VALUE ? null : allTodayEditFinishPeriod,
                is_deadline_important: allTodayEditDeadlineImportant,
                ...(isWaitingConfirmation(allTodayEditStatus)
                  ? { confirmation_assignee_id: allTodayEditConfirmationAssigneeId }
                  : {}),
              }),
          ...(usesCompletionOverride
            ? { completion_override_reason: allTodayEditCompletionNote.trim() }
            : {}),
        }
        ),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => null)
        toast.error(taskUpdateErrorMessage(data, "Failed to update task"))
        return
      }
      const updated = (await res.json()) as Task
      setDepartmentTasks((prev) => prev.map((t) => (t.id === allTodayEditingTaskId ? updated : t)))
      setNoProjectTasks((prev) => prev.map((t) => (t.id === allTodayEditingTaskId ? updated : t)))
      setSystemCreatedTasks((prev) => prev.map((t) => (t.id === allTodayEditingTaskId ? updated : t)))
      setCrossDepartmentConfirmTasks((prev) => {
        const exists = prev.some((t) => t.id === updated.id)
        if (!exists) return prev
        if (taskStatusValue(updated) !== "WAITING_CONFIRMATION") {
          return prev.filter((t) => t.id !== updated.id)
        }
        return prev.map((t) => (t.id === updated.id ? updated : t))
      })
      await refreshDailyReport()
      cancelAllTodayTaskEdit()
      toast.success("Task updated")
    } finally {
      setAllTodayUpdating(false)
    }
  }

  const markWaitingTaskDone = async (task: Task) => {
    if (!canMarkWaitingConfirmation(task)) {
      toast.error("You do not have permission to complete this task")
      return
    }
    setMarkingWaitingTaskId(task.id)
    try {
      const res = await apiFetch(`/tasks/${task.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "DONE" }),
      })
      if (!res.ok) {
        let detail = "Failed to mark task as done"
        try {
          const data = (await res.json()) as { detail?: string }
          if (typeof data?.detail === "string") detail = data.detail
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }
      const updated = (await res.json()) as Task
      setDepartmentTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)))
      setNoProjectTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)))
      setCrossDepartmentConfirmTasks((prev) => {
        const exists = prev.some((t) => t.id === updated.id)
        if (!exists) return prev
        if (taskStatusValue(updated) !== "WAITING_CONFIRMATION") {
          return prev.filter((t) => t.id !== updated.id)
        }
        return prev.map((t) => (t.id === updated.id ? updated : t))
      })
      void refreshDailyReport()
      toast.success("Task marked as done")
    } finally {
      setMarkingWaitingTaskId(null)
    }
  }

  const submitNoProjectTask = async () => {
    if (!noProjectTitle.trim() || !noProjectStartDate || !department) return
    setCreatingNoProject(true)
    try {
      const startDate = noProjectStartDate ? new Date(noProjectStartDate).toISOString() : null
      const dueDate = noProjectDueDate ? new Date(noProjectDueDate).toISOString() : null
      const payload = {
        title: noProjectTitle.trim(),
        description: noProjectDescription.trim() || null,
        project_id: null,
        department_id: department.id,
        status: "TODO",
        priority: "NORMAL",
        finish_period: noProjectFinishPeriod === FINISH_PERIOD_NONE_VALUE ? null : noProjectFinishPeriod,
        is_bllok: noProjectType === "blocked",
        is_1h_report: noProjectType === "hourly",
        is_r1: noProjectType === "r1",
        is_personal: noProjectType === "personal",
        ga_note_origin_id: null,
        start_date: startDate,
        due_date: dueDate,
        is_deadline_important: noProjectDeadlineImportant,
      }
      // Create one task with multiple assignees instead of multiple tasks
      const assigneeIds = noProjectAssignees.length > 0 ? noProjectAssignees : null
      const res = await apiFetch("/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...payload,
          assigned_to: assigneeIds && assigneeIds.length > 0 ? assigneeIds[0] : null,
          assignees: assigneeIds,
        }),
      })
      if (!res.ok) {
        let detail = "Failed to create task"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }
      const created = (await res.json()) as Task
      // Ensure boolean fields are explicitly set (backend might return undefined)
      // Explicitly set all boolean fields based on task type to ensure proper categorization
      created.is_bllok = noProjectType === "blocked" ? true : (created.is_bllok ?? false)
      created.is_1h_report = noProjectType === "hourly" ? true : (created.is_1h_report ?? false)
      created.is_r1 = noProjectType === "r1" ? true : (created.is_r1 ?? false)
      created.is_personal = noProjectType === "personal" ? true : (created.is_personal ?? false)
      if (noProjectType === "normal") {
        created.ga_note_origin_id = created.ga_note_origin_id || null
        created.priority = created.priority || "NORMAL"
      }
      // Add all non-project tasks to noProjectTasks (they'll be categorized into buckets)
      const nonProjectTasks = isNoProjectTask(created) ? [created] : []
      if (nonProjectTasks.length) {
        setNoProjectTasks((prev) => [...nonProjectTasks, ...prev])
      }
      setDepartmentTasks((prev) => [created, ...prev])
      setNoProjectOpen(false)
      setNoProjectTitle("")
      setNoProjectDescription("")
      setNoProjectType("normal")
      setNoProjectAssignees([])
      setNoProjectStartDate("")
      setNoProjectDueDate("")
      setNoProjectDeadlineImportant(false)
      setNoProjectFinishPeriod(FINISH_PERIOD_NONE_VALUE)
      toast.success("Task created")
    } finally {
      setCreatingNoProject(false)
    }
  }

  const submitMeeting = async () => {
    if (!meetingTitle.trim() || !department) return
    if (!meetingParticipantIds.length) {
      toast.error("Select at least one participant")
      return
    }
    setCreatingMeeting(true)
    try {
      let startsAt: string | null = null
      if (meetingRecurrenceType === "none") {
        startsAt = meetingStartsAt ? new Date(meetingStartsAt).toISOString() : null
      } else {
        if (!meetingStartTime) {
          toast.error("Time is required for recurring meetings")
          return
        }
        if (meetingRecurrenceType === "weekly" && meetingRecurrenceDaysOfWeek.length === 0) {
          toast.error("Select at least one day")
          return
        }
        if (meetingRecurrenceType === "monthly" && meetingRecurrenceDaysOfMonth.length === 0) {
          toast.error("Select at least one day")
          return
        }
        const next = computeNextOccurrenceDate({
          recurrenceType: meetingRecurrenceType,
          daysOfWeek: meetingRecurrenceDaysOfWeek,
          daysOfMonth: meetingRecurrenceDaysOfMonth,
          timeValue: meetingStartTime,
        })
        if (!next) {
          toast.error("Failed to compute next occurrence")
          return
        }
        startsAt = next.toISOString()
      }
      const payload = {
        title: meetingTitle.trim(),
        platform: meetingPlatform.trim() || null,
        starts_at: startsAt,
        meeting_url: meetingUrl.trim() || null,
        recurrence_type: meetingRecurrenceType === "none" ? null : meetingRecurrenceType,
        recurrence_days_of_week: meetingRecurrenceType === "weekly" && meetingRecurrenceDaysOfWeek.length > 0 ? meetingRecurrenceDaysOfWeek : null,
        recurrence_days_of_month: meetingRecurrenceType === "monthly" && meetingRecurrenceDaysOfMonth.length > 0 ? meetingRecurrenceDaysOfMonth : null,
        department_id: department.id,
        project_id: meetingProjectId === "__none__" ? null : meetingProjectId,
        participant_ids: meetingParticipantIds,
      }
      const res = await apiFetch("/meetings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        let detail = "Failed to create meeting"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }
      const created = (await res.json()) as Meeting
      setMeetings((prev) => [created, ...prev])
      setAllDepartmentMeetings((prev) => [created, ...prev.filter((meeting) => meeting.id !== created.id)])
      setMeetingTitle("")
      setMeetingPlatform("")
      setMeetingStartsAt("")
      setMeetingStartTime("")
      setMeetingUrl("")
      setMeetingRecurrenceType("none")
      setMeetingRecurrenceDaysOfWeek([])
      setMeetingRecurrenceDaysOfMonth([])
      setMeetingParticipantIds([])
      setMeetingProjectId("__none__")
      setShowAddMeetingForm(false)
      toast.success("Meeting created")
    } finally {
      setCreatingMeeting(false)
    }
  }

  const closeInternalMeetingTaskDialog = React.useCallback(() => {
    setInternalMeetingTaskDialogOpen(false)
    setInternalMeetingTaskTitle("")
    setInternalMeetingTaskPlatform("")
    setInternalMeetingTaskStartsAt("")
  }, [])

  const openInternalMeetingFromFastTask = React.useCallback((task: Task) => {
    setInternalMeetingTaskTitle(task.title || "")
    setInternalMeetingTaskPlatform("")
    setInternalMeetingTaskStartsAt("")
    setInternalMeetingTaskDialogOpen(true)
  }, [])

  const submitInternalMeetingFromTask = React.useCallback(async () => {
    const title = internalMeetingTaskTitle.trim()
    const departmentId = department?.id || user?.department_id
    if (!title) return
    if (!departmentId) {
      toast.error("Department is required to create an internal meeting.")
      return
    }
    setCreatingInternalMeetingFromTask(true)
    try {
      const startsAt = internalMeetingTaskStartsAt ? new Date(internalMeetingTaskStartsAt).toISOString() : null
      const payload = {
        title,
        platform: internalMeetingTaskPlatform.trim() || null,
        starts_at: startsAt,
        department_id: departmentId,
        project_id: null,
        meeting_type: "internal",
        participant_ids: user?.id ? [user.id] : [],
      }
      const res = await apiFetch("/meetings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        let detail = "Failed to create internal meeting"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }
      const created = (await res.json()) as Meeting
      setMeetings((prev) => [created, ...prev])
      closeInternalMeetingTaskDialog()
      toast.success("Internal meeting created")
    } finally {
      setCreatingInternalMeetingFromTask(false)
    }
  }, [
    apiFetch,
    closeInternalMeetingTaskDialog,
    department?.id,
    internalMeetingTaskPlatform,
    internalMeetingTaskStartsAt,
    internalMeetingTaskTitle,
    user?.department_id,
    user?.id,
  ])

  const startEditMeeting = (meeting: Meeting) => {
    setEditingMeetingId(meeting.id)
    setEditMeetingTitle(meeting.title)
    setEditMeetingPlatform(meeting.platform || "")
    setEditMeetingStartsAt(toMeetingInputValue(meeting.starts_at))
    setEditMeetingStartTime(toMeetingTimeInputValue(meeting.starts_at))
    setEditMeetingUrl(meeting.meeting_url || "")
    setEditMeetingRecurrenceType((meeting.recurrence_type as "none" | "weekly" | "monthly") || "none")
    setEditMeetingRecurrenceDaysOfWeek(meeting.recurrence_days_of_week || [])
    setEditMeetingRecurrenceDaysOfMonth(meeting.recurrence_days_of_month || [])
    setEditMeetingParticipantIds(meeting.participant_ids || [])
    setEditMeetingProjectId(meeting.project_id || "__none__")
  }

  const cancelEditMeeting = () => {
    setEditingMeetingId(null)
    setEditMeetingTitle("")
    setEditMeetingPlatform("")
    setEditMeetingStartsAt("")
    setEditMeetingStartTime("")
    setEditMeetingUrl("")
    setEditMeetingRecurrenceType("none")
    setEditMeetingRecurrenceDaysOfWeek([])
    setEditMeetingRecurrenceDaysOfMonth([])
    setEditMeetingParticipantIds([])
    setEditMeetingProjectId("__none__")
  }

  const saveMeeting = async (meetingId: string) => {
    if (!editMeetingTitle.trim()) {
      toast.error("Meeting title is required")
      return
    }
    if (!department) return
    setSavingMeeting(true)
    try {
      let startsAt: string | null = null
      if (editMeetingRecurrenceType === "none") {
        startsAt = editMeetingStartsAt ? new Date(editMeetingStartsAt).toISOString() : null
      } else {
        if (!editMeetingStartTime) {
          toast.error("Time is required for recurring meetings")
          return
        }
        if (editMeetingRecurrenceType === "weekly" && editMeetingRecurrenceDaysOfWeek.length === 0) {
          toast.error("Select at least one day")
          return
        }
        if (editMeetingRecurrenceType === "monthly" && editMeetingRecurrenceDaysOfMonth.length === 0) {
          toast.error("Select at least one day")
          return
        }
        const next = computeNextOccurrenceDate({
          recurrenceType: editMeetingRecurrenceType,
          daysOfWeek: editMeetingRecurrenceDaysOfWeek,
          daysOfMonth: editMeetingRecurrenceDaysOfMonth,
          timeValue: editMeetingStartTime,
        })
        if (!next) {
          toast.error("Failed to compute next occurrence")
          return
        }
        startsAt = next.toISOString()
      }
      const payload = {
        title: editMeetingTitle.trim(),
        platform: editMeetingPlatform.trim() || null,
        starts_at: startsAt,
        meeting_url: editMeetingUrl.trim() || null,
        recurrence_type: editMeetingRecurrenceType === "none" ? null : editMeetingRecurrenceType,
        recurrence_days_of_week: editMeetingRecurrenceType === "weekly" && editMeetingRecurrenceDaysOfWeek.length > 0 ? editMeetingRecurrenceDaysOfWeek : null,
        recurrence_days_of_month: editMeetingRecurrenceType === "monthly" && editMeetingRecurrenceDaysOfMonth.length > 0 ? editMeetingRecurrenceDaysOfMonth : null,
        project_id: editMeetingProjectId === "__none__" ? null : editMeetingProjectId,
        participant_ids: editMeetingParticipantIds,
      }
      const res = await apiFetch(`/meetings/${meetingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        let detail = "Failed to update meeting"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }
      const updated = (await res.json()) as Meeting
      setAllDepartmentMeetings((prev) => prev.map((meeting) => (meeting.id === updated.id ? updated : meeting)))
      console.log("Updated meeting from API:", updated)
      // Reload meetings to ensure we have the latest data including participants and recurrence
      const meetingsRes = await apiFetch(`/meetings?department_id=${department.id}`)
      if (meetingsRes.ok) {
        const refreshedMeetings = (await meetingsRes.json()) as Meeting[]
        console.log("Refreshed meetings:", refreshedMeetings)
        const updatedMeeting = refreshedMeetings.find(m => m.id === meetingId)
        console.log("Updated meeting in refreshed list:", updatedMeeting)
        setMeetings(refreshedMeetings)
      } else {
        console.warn("Failed to reload meetings, using updated meeting:", updated)
        // Fallback to updating just the one meeting if reload fails
        setMeetings((prev) => prev.map((m) => (m.id === updated.id ? updated : m)))
      }
      cancelEditMeeting()
      toast.success("Meeting updated successfully")
    } finally {
      setSavingMeeting(false)
    }
  }

  const deleteMeeting = async (meetingId: string) => {
    const res = await apiFetch(`/meetings/${meetingId}`, { method: "DELETE" })
    if (!res.ok) {
      let detail = "Failed to delete meeting"
      try {
        const data = (await res.json()) as { detail?: string }
        if (data?.detail) detail = data.detail
      } catch {
        // ignore
      }
      toast.error(detail)
      return
    }
    setMeetings((prev) => prev.filter((m) => m.id !== meetingId))
    setAllDepartmentMeetings((prev) => prev.filter((meeting) => meeting.id !== meetingId))
    toast.success("Meeting deleted")
  }

  const toggleInternalMeetingItem = async (itemId: string, next: boolean) => {
    const previous = internalMeetingItems.find((item) => item.id === itemId)?.is_checked ?? false
    setInternalMeetingItems((prev) =>
      prev.map((item) => (item.id === itemId ? { ...item, is_checked: next } : item))
    )
    const res = await apiFetch(`/checklist-items/${itemId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_checked: next }),
    })
    if (!res.ok) {
      setInternalMeetingItems((prev) =>
        prev.map((item) => (item.id === itemId ? { ...item, is_checked: previous } : item))
      )
      toast.error("Failed to update internal meeting item")
    }
  }

  const addInternalMeetingItem = async () => {
    if (!internalMeetingChecklistId) return
    const title = newInternalMeetingItem.trim()
    if (!title) return
    setAddingInternalMeetingItem(true)
    try {
      const nextPosition =
        internalMeetingItems.reduce((max, item) => Math.max(max, item.position ?? -1), -1) + 1
      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          checklist_id: internalMeetingChecklistId,
          item_type: "CHECKBOX",
          path: "INTERNAL_MEETINGS",
          day: internalSlot,
          title,
          is_checked: false,
          position: nextPosition,
        }),
      })
      if (!res.ok) {
        toast.error("Failed to add internal meeting item")
        return
      }
      const created = (await res.json()) as ChecklistItem
      setInternalMeetingItems((prev) => [...prev, created])
      setNewInternalMeetingItem("")
      toast.success("Internal meeting item added")
    } finally {
      setAddingInternalMeetingItem(false)
    }
  }

  const startEditInternalMeetingItem = (item: ChecklistItem, displayPosition: number) => {
    setEditingInternalMeetingItemId(item.id)
    setEditingInternalMeetingItem(item.title || "")
    setEditingInternalMeetingItemPosition(String(displayPosition))
  }

  const cancelEditInternalMeetingItem = () => {
    setEditingInternalMeetingItemId(null)
    setEditingInternalMeetingItem("")
    setEditingInternalMeetingItemPosition("1")
  }

  const saveInternalMeetingItem = async () => {
    if (!editingInternalMeetingItemId) return
    const title = editingInternalMeetingItem.trim()
    if (!title) {
      toast.error("Checklist item title is required")
      return
    }
    const requestedDisplayPosition = Number(editingInternalMeetingItemPosition)
    if (!Number.isInteger(requestedDisplayPosition) || requestedDisplayPosition < 1) {
      toast.error("Number must be 1 or greater")
      return
    }

    const orderedWithoutCurrent = [...internalMeetingItems]
      .filter((item) => item.id !== editingInternalMeetingItemId)
      .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
    const slotSiblings = orderedWithoutCurrent.filter(
      (item) => resolveInternalMeetingSlot(item.day) === internalSlot,
    )
    const targetIndex = Math.min(requestedDisplayPosition - 1, slotSiblings.length)
    let requestedStoredPosition = orderedWithoutCurrent.length + 1
    if (targetIndex < slotSiblings.length) {
      requestedStoredPosition = orderedWithoutCurrent.findIndex((item) => item.id === slotSiblings[targetIndex].id) + 1
    } else if (slotSiblings.length > 0) {
      requestedStoredPosition = orderedWithoutCurrent.findIndex(
        (item) => item.id === slotSiblings[slotSiblings.length - 1].id,
      ) + 2
    }

    setSavingInternalMeetingItem(true)
    try {
      const res = await apiFetch(`/checklist-items/${editingInternalMeetingItemId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, position: requestedStoredPosition }),
      })
      if (!res.ok) {
        toast.error("Failed to update internal meeting item")
        return
      }
      const updated = (await res.json()) as ChecklistItem
      const refreshedRes = internalMeetingChecklistId
        ? await apiFetch(`/checklist-items?checklist_id=${internalMeetingChecklistId}`)
        : null
      if (refreshedRes?.ok) {
        setInternalMeetingItems((await refreshedRes.json()) as ChecklistItem[])
      } else {
        setInternalMeetingItems((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
      }
      cancelEditInternalMeetingItem()
      toast.success("Checklist item updated")
    } finally {
      setSavingInternalMeetingItem(false)
    }
  }

  const deleteInternalMeetingItem = async (itemId: string) => {
    const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
    if (!res.ok) {
      toast.error("Failed to delete internal meeting item")
      return
    }
    setInternalMeetingItems((prev) => prev.filter((item) => item.id !== itemId))
    toast.success("Internal meeting item deleted")
  }

  const loadMicrosoftStatus = React.useCallback(async () => {
    setCheckingMsStatus(true)
    try {
      const res = await apiFetch("/microsoft/status")
      if (!res.ok) {
        setMsConnected(false)
        return
      }
      const data = (await res.json()) as { connected?: boolean; can_manage?: boolean }
      setMsConnected(Boolean(data.connected))
      setMsCanManage(Boolean(data.can_manage))
    } finally {
      setCheckingMsStatus(false)
    }
  }, [apiFetch])

  const connectMicrosoft = async () => {
    const redirectTo = `${window.location.origin}${pathname}?tab=meetings`
    const res = await apiFetch(`/microsoft/authorize-url?redirect_to=${encodeURIComponent(redirectTo)}`)
    if (!res.ok) {
      toast.error("Unable to start Microsoft auth")
      return
    }
    const data = (await res.json()) as { url?: string }
    if (data.url) {
      window.location.href = data.url
    } else {
      toast.error("Missing Microsoft auth URL")
    }
  }

  const disconnectMicrosoft = async () => {
    const res = await apiFetch("/microsoft/disconnect", { method: "DELETE" })
    if (!res.ok) {
      toast.error("Failed to disconnect Microsoft calendar")
      return
    }
    setMsConnected(false)
    setMsEvents([])
  }

  const loadMicrosoftEvents = React.useCallback(async () => {
    if (!msConnected) return
    setLoadingMsEvents(true)
    try {
      const start = new Date()
      const end = new Date(start)
      end.setDate(end.getDate() + 30)
      const res = await apiFetch(
        `/microsoft/events?start=${encodeURIComponent(start.toISOString())}&end=${encodeURIComponent(end.toISOString())}`
      )
      if (!res.ok) {
        toast.error("Failed to load Microsoft events")
        return
      }
      const data = (await res.json()) as MicrosoftEvent[]
      setMsEvents(data)
    } finally {
      setLoadingMsEvents(false)
    }
  }, [apiFetch, msConnected])

  React.useEffect(() => {
    if (activeTab !== "meetings") return
    void loadMicrosoftStatus()
  }, [activeTab, loadMicrosoftStatus])

  React.useEffect(() => {
    if (msParam === "connected") {
      toast.success("Microsoft calendar connected")
      void loadMicrosoftStatus()
    }
  }, [msParam, loadMicrosoftStatus])

  React.useEffect(() => {
    if (!msConnected || activeTab !== "meetings") return
    void loadMicrosoftEvents()
  }, [msConnected, activeTab, loadMicrosoftEvents])

  const submitInternalNote = async () => {
    const title = internalNoteTitle.trim()
    const description = internalNoteDescription.trim()
    if (!title || internalNoteToUserIds.length === 0) {
      return
    }
    setAddingInternalNote(true)
    try {
      const res = await apiFetch("/internal-notes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          description: description || null,
          departmentId: internalNoteDepartmentId || null,
          projectId: internalNoteProjectId || null,
          toUserIds: internalNoteToUserIds,
        }),
      })
      if (!res.ok) {
        let detail = "Failed to add internal note"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }
      const created = (await res.json()) as InternalNote[]
      const departmentId = department?.id
      const visibleCreated = departmentId
        ? created.filter((note) => (note.department_id || note.to_department_id) === departmentId)
        : created
      setInternalNotes((prev) => [...visibleCreated, ...prev])
      setInternalNoteTitle("")
      setInternalNoteDescription("")
      setInternalNoteProjectId("")
      setInternalNoteToUserIds([])
      setInternalNoteOpen(false)
      toast.success("Internal note added")
    } finally {
      setAddingInternalNote(false)
    }
  }

  const startEditInternalNote = (note: InternalNote, toUserIds: string[], noteIds: string[]) => {
    setEditingInternalNoteIds(noteIds)
    setEditInternalNoteTitle(note.title || "")
    setEditInternalNoteDescription(note.description || "")
    setEditInternalNoteDepartmentId((note.department_id || note.to_department_id || "") as string)
    setEditInternalNoteProjectId(note.project_id || "")
    setEditInternalNoteToUserIds(toUserIds)
    setEditInternalNoteOpen(true)
  }

  const submitInternalNoteEdit = async () => {
    if (!department?.id) return
    if (editingInternalNoteIds.length === 0) return

    const title = editInternalNoteTitle.trim()
    const description = editInternalNoteDescription.trim()
    if (!title || editInternalNoteToUserIds.length === 0 || !editInternalNoteDepartmentId) {
      return
    }

    setSavingInternalNoteEdit(true)
    try {
      const res = await apiFetch("/internal-notes/group", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          noteIds: editingInternalNoteIds,
          title,
          description: description || null,
          departmentId: editInternalNoteDepartmentId,
          projectId: editInternalNoteProjectId || null,
          toUserIds: editInternalNoteToUserIds,
        }),
      })
      if (!res.ok) {
        let detail = "Failed to update internal note"
        try {
          const data = (await res.json()) as { detail?: unknown }
          const rawDetail = data?.detail
          if (typeof rawDetail === "string") {
            detail = rawDetail
          } else if (Array.isArray(rawDetail)) {
            detail =
              rawDetail
                .map((item) => {
                  if (typeof item === "string") return item
                  if (item && typeof item === "object" && "msg" in item) return String((item as { msg?: unknown }).msg)
                  return "Invalid request"
                })
                .filter(Boolean)
                .join(", ") || detail
          }
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }

      const refresh = await apiFetch(`/internal-notes?department_id=${department.id}`)
      if (refresh.ok) {
        setInternalNotes((await refresh.json()) as InternalNote[])
      }
      setEditInternalNoteOpen(false)
      setEditingInternalNoteIds([])
      toast.success("Internal note updated")
    } finally {
      setSavingInternalNoteEdit(false)
    }
  }

  const deleteInternalNote = async (noteIds: string[] | string) => {
    const ids = Array.isArray(noteIds) ? noteIds : [noteIds]
    if (!ids.length) return
    const confirmed = await confirm({
      title: "Delete internal note",
      description: "Are you sure you want to delete this internal note?",
      confirmLabel: "Delete",
      variant: "destructive",
    })
    if (!confirmed) return
    let failed = false
    for (const noteId of ids) {
      const res = await apiFetch(`/internal-notes/${noteId}`, { method: "DELETE" })
      if (!res.ok) {
        failed = true
      }
    }
    if (failed) {
      toast.error("Failed to delete internal note")
      return
    }
    setInternalNotes((prev) => prev.filter((note) => !ids.includes(note.id)))
    toast.success("Internal note deleted")
  }

  const updateInternalNoteDone = async (noteIds: string[] | string, isDone: boolean) => {
    const ids = Array.isArray(noteIds) ? noteIds : [noteIds]
    if (!ids.length) return
    const previous = internalNotes
    setUpdatingInternalNoteIds((prev) => [...new Set([...prev, ...ids])])
    const nowIso = new Date().toISOString()
    setInternalNotes((prev) =>
      prev.map((note) =>
        ids.includes(note.id)
          ? {
            ...note,
            is_done: isDone,
            done_at: isDone ? nowIso : null,
            done_by_user_id: isDone ? (user?.id || null) : null,
          }
          : note
      )
    )
    let failed = false
    for (const noteId of ids) {
      const res = await apiFetch(`/internal-notes/${noteId}/done`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ isDone }),
      })
      if (!res.ok) {
        failed = true
      }
    }
    if (failed) {
      setInternalNotes(previous)
      toast.error("Failed to update internal note status")
    } else {
      toast.success(isDone ? "Internal note marked as done" : "Internal note reopened")
    }
    setUpdatingInternalNoteIds((prev) => prev.filter((id) => !ids.includes(id)))
  }

  if (loading)
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-center">
          <div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-slate-400 border-r-transparent"></div>
          <div className="mt-4 text-sm text-slate-600">Loading department...</div>
        </div>
      </div>
    )
  if (!department)
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-sm text-slate-600">Department not found.</div>
      </div>
    )

  return (
    <div className="min-h-screen">
      <style jsx>{`
        .common-sticky {
          position: sticky;
          top: 0;
          z-index: 20;
          background: #ffffff;
        }
        .top-header { 
          background: linear-gradient(135deg, #93c5fd 0%, #60a5fa 100%);
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
        .common-toolbar {
          background: #ffffff;
          border-bottom: 1px solid #e2e8f0;
          padding: 12px 24px;
          display: flex;
          flex-wrap: wrap;
          gap: 16px;
          align-items: center;
        }
        .toolbar-group {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .chip-row {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }
        .all-range-chip-row {
          flex-wrap: nowrap;
          overflow-x: auto;
          padding-bottom: 2px;
        }
        .all-range-chip-row-dev {
          background: #eef4ff;
          border: 1px solid #bfdbfe;
          border-radius: 12px;
          padding: 6px;
          gap: 6px;
        }
        .chip-all-range {
          background: #ffffff;
          color: #1e3a8a;
          border-color: #93c5fd;
        }
        .chip-all-range:hover {
          background: #dbeafe;
          border-color: #60a5fa;
        }
        .chip-all-range.active {
          background: #2563eb;
          color: #ffffff;
          border-color: #2563eb;
          box-shadow: 0 4px 10px rgba(37, 99, 235, 0.28);
        }
        .all-range-chip-row .chip {
          white-space: nowrap;
          flex-shrink: 0;
        }
        .all-range-chip-row input {
          flex-shrink: 0;
        }
        .chip {
          background: #f1f5f9;
          color: #475569;
          border: 1px solid #cbd5e1;
          padding: 6px 12px;
          border-radius: 6px;
          font-size: 12px;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s ease;
        }
        .chip:hover {
          background: #e2e8f0;
          border-color: #94a3b8;
        }
        .chip.active {
          background: #475569;
          color: white;
          border-color: #475569;
        }
        .switch {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 12px;
          color: #64748b;
          cursor: pointer;
        }
        .switch input[type="checkbox"] {
          cursor: pointer;
        }
      `}</style>
      <div className="common-sticky print:hidden">
        <header className="top-header">
          <div className="page-title">
            <h1>{departmentName}</h1>
            <p>Manage projects and daily tasks.</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              className="btn-outline no-print"
              type="button"
              onClick={() => setViewMode("department")}
            >
              Department
            </button>
            <button
              className={`btn-outline no-print ${viewMode === "mine" ? "active" : ""}`}
              type="button"
              onClick={() => setViewMode("mine")}
            >
              My View
            </button>
          </div>
        </header>

        <div className="common-toolbar no-print">
          <div className="toolbar-group">
            <div className="chip-row">
              {TABS.map((tab) => {
                const isActive = tab.id === activeTab
                return (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setActiveTab(tab.id)}
                    className={`chip ${isActive ? "active" : ""}`}
                  >
                    {tab.label} ({counts[tab.id]})
                  </button>
                )
              })}
            </div>
            {activeTab === "all" ? (
              <div className="chip-row all-range-chip-row all-range-chip-row-dev">

                <button
                  type="button"
                  onClick={() => setAllRange("past-7-days")}
                  className={`chip chip-all-range ${allRange === "past-7-days" ? "active" : ""}`}
                >
                  Last 7 Days
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setAllDateInput(todayInputValue())
                    setAllRange("today")
                  }}
                  className={`chip chip-all-range ${allRange === "today" ? "active" : ""}`}
                >
                  Today
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setAllDateInput(tomorrowInputValue())
                    setAllRange("tomorrow")
                  }}
                  className={`chip chip-all-range ${allRange === "tomorrow" ? "active" : ""}`}
                >
                  Tomorrow
                </button>
                <button
                  type="button"
                  onClick={() => setAllRange("this-week")}
                  className={`chip chip-all-range ${allRange === "this-week" ? "active" : ""}`}
                >
                  This Week
                </button>
                <button
                  type="button"
                  onClick={() => setAllRange("next-week")}
                  className={`chip chip-all-range ${allRange === "next-week" ? "active" : ""}`}
                >
                  Next Week
                </button>
                <button
                  type="button"
                  onClick={() => setAllRange("all")}
                  className={`chip chip-all-range ${allRange === "all" ? "active" : ""}`}
                >
                  All
                </button>
                <Input
                  type="date"
                  value={allDateInput}
                  onChange={(e) => {
                    const nextValue = e.target.value || todayInputValue()
                    setAllDateInput(nextValue)
                    setAllRange("date")
                  }}
                  className={`h-9 w-[160px] rounded-xl border-blue-300 bg-white text-xs text-blue-900 sm:text-sm ${allRange === "date" ? "ring-2 ring-blue-300" : ""}`}
                />
              </div>
            ) : null}
          </div>
        </div>
      </div>
      <div className="px-4 sm:px-6 pb-4 sm:pb-6 print:hidden">
        {activeTab === "projects" ? (
          <div className="mb-4 sm:mb-6">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
              <div className="text-lg sm:text-xl font-semibold text-slate-800">Active Projects</div>
              {canManage ? (
                <Dialog open={createProjectOpen} onOpenChange={setCreateProjectOpen}>
                  <DialogTrigger asChild>
                    <Button className="bg-slate-900 hover:bg-slate-800 text-white border-0 shadow-sm rounded-xl px-4 sm:px-6 w-full sm:w-auto">
                      + New Project
                    </Button>
                  </DialogTrigger>
                  <DialogContent className="sm:max-w-2xl bg-white border-slate-200 rounded-2xl">
                    <DialogHeader>
                      <DialogTitle className="text-slate-800">Add Project</DialogTitle>
                    </DialogHeader>
                    <div className="grid gap-4 md:grid-cols-2">
                      <div className="space-y-2 md:col-span-2">
                        <Label className="text-slate-700">Title</Label>
                        <Input
                          value={projectTitle}
                          onChange={(e) => handleProjectTitleChange(e.target.value)}
                          className="border-slate-200 focus:border-slate-400 rounded-xl uppercase placeholder:normal-case"
                          placeholder="Enter project shortcut (e.g., ABC, XYZ)"
                          style={{ textTransform: 'uppercase' }}
                        />
                        <div className="text-xs text-slate-600 flex items-center gap-1.5">
                          <span className="text-slate-500">i</span>
                          <span>Use a shortcut/abbreviation, not the full client name (e.g., "ABC" instead of "ABC Company")</span>
                        </div>
                      </div>
                      <div className="space-y-2 md:col-span-2">
                        <Label className="text-slate-700">Description</Label>
                        <Textarea
                          value={projectDescription}
                          onChange={(e) => setProjectDescription(e.target.value)}
                          placeholder="Enter the project description..."
                          className="border-slate-200 focus:border-slate-400 rounded-xl"
                        />
                      </div>
                      <div className="space-y-2">
                        <Label className="text-slate-700">Members</Label>
                        <Dialog open={selectMembersOpen} onOpenChange={setSelectMembersOpen}>
                          <DialogTrigger asChild>
                            <Button
                              type="button"
                              variant="outline"
                              disabled={editingPlanTask}
                              className="w-full justify-start border-slate-200 focus:border-slate-400 rounded-xl"
                            >
                              {projectMemberIds.length === 0
                                ? "Select members..."
                                : `${projectMemberIds.length} member${projectMemberIds.length === 1 ? "" : "s"} selected`}
                            </Button>
                          </DialogTrigger>
                          <DialogContent className="sm:max-w-md">
                            <DialogHeader>
                              <DialogTitle>Select Project Members</DialogTitle>
                            </DialogHeader>
                            <div className="mt-4 max-h-[400px] overflow-y-auto space-y-2">
                              {departmentUsers.map((u) => {
                                const isSelected = projectMemberIds.includes(u.id)
                                return (
                                  <div
                                    key={u.id}
                                    className="flex items-center space-x-2 p-2 rounded-lg hover:bg-slate-50 cursor-pointer"
                                    onClick={() => {
                                      if (isSelected) {
                                        setProjectMemberIds((prev) => prev.filter((id) => id !== u.id))
                                      } else {
                                        setProjectMemberIds((prev) => [...prev, u.id])
                                      }
                                    }}
                                  >
                                    <Checkbox checked={isSelected} />
                                    <Label className="cursor-pointer flex-1">
                                      {u.full_name || u.username || "-"}
                                    </Label>
                                  </div>
                                )
                              })}
                            </div>
                            <div className="mt-4 flex justify-end gap-2">
                              <Button
                                variant="outline"
                                onClick={() => {
                                  setProjectMemberIds([])
                                  setSelectMembersOpen(false)
                                }}
                              >
                                Clear
                              </Button>
                              <Button onClick={() => setSelectMembersOpen(false)}>
                                Done
                              </Button>
                            </div>
                          </DialogContent>
                        </Dialog>
                        {projectMemberIds.length > 0 && (
                          <div className="text-xs text-slate-600">
                            {projectMemberIds.length} member{projectMemberIds.length === 1 ? "" : "s"} selected
                          </div>
                        )}
                      </div>
                      <div className="space-y-2">
                        <Label className="text-slate-700">Due Date</Label>
                        <Input
                          type="date"
                          value={projectDueDate}
                          onChange={(e) => setProjectDueDate(e.target.value)}
                          placeholder="Select due date"
                          className="border-slate-200 focus:border-slate-400 rounded-xl"
                        />
                      </div>
                      <div className="flex justify-end gap-2 md:col-span-2">
                        <Button variant="outline" onClick={() => setCreateProjectOpen(false)} className="rounded-xl border-slate-200">
                          Cancel
                        </Button>
                        <Button disabled={!projectTitle.trim() || creatingProject} onClick={attemptSubmitProject} className="bg-slate-900 hover:bg-slate-800 text-white border-0 shadow-sm rounded-xl">
                          {creatingProject ? "Saving..." : "Save"}
                        </Button>
                      </div>
                    </div>
                  </DialogContent>
                </Dialog>
              ) : null}
            </div>
          </div>
        ) : null}

        {activeTab === "projects" ? (
          <div className="space-y-4 sm:space-y-6">
            <div className="grid gap-4 grid-cols-1 md:grid-cols-2 lg:grid-cols-4">
              {filteredProjects.map((project) => {
                const manager = project.manager_id ? userMap.get(project.manager_id) : null
                const creator = project.created_by ? userMap.get(project.created_by) : null
                const badgeUser = creator || manager
                const badgeTitle = creator
                  ? `Creator: ${creator.full_name || creator.username || "-"}`
                  : manager
                    ? `Manager: ${manager.full_name || manager.username || "-"}`
                    : "No creator"
                const membersForProject = projectMembers[project.id] || []
                const combinedMembers = manager ? [...membersForProject, manager] : membersForProject
                const uniqueMembers = Array.from(new Map(combinedMembers.map((m) => [m.id, m])).values())
                const visibleMembers = uniqueMembers.slice(0, 4)
                const remainingMembers = uniqueMembers.length - visibleMembers.length
                const phase = project.current_phase || "MEETINGS"
                const isClosed = phase.toUpperCase() === "CLOSED"

                // Count tasks for this project
                const taskCount = departmentTasks.filter(t => t.project_id === project.id).length

                // Format deadline
                const formatDeadline = (dateStr?: string | null) => {
                  if (!dateStr) return "-"
                  const date = new Date(dateStr)
                  if (Number.isNaN(date.getTime())) return "-"
                  return formatDateDMY(date)
                }

                return (
                  <Link key={project.id} href={`/projects/${project.id}`} className="group block">
                    <Card className={`bg-white border rounded-lg p-2.5 transition-all ${isClosed ? "border-slate-300 opacity-60 hover:opacity-80" : "border-slate-200 shadow-sm hover:shadow-md hover:-translate-y-1"}`}>
                      {/* Header: Title and Delete button */}
                      <div className="flex items-start justify-between gap-2 mb-2">
                        <div className="flex-1 min-w-0">
                          <div className={`text-sm font-semibold truncate ${isClosed ? "text-slate-500" : "text-slate-900 dark:text-slate-100"}`}>
                            {resolveProjectTitle(project)}
                            {isClosed && <span className="ml-1.5 text-xs font-normal text-slate-400">(Closed)</span>}
                          </div>
                        </div>
                        <div className="flex items-center gap-1.5 flex-shrink-0">
                          {badgeUser ? (
                            <div
                              className="h-6 w-6 rounded-full bg-amber-100 text-[10px] font-semibold text-amber-800 flex items-center justify-center shadow-sm"
                              title={badgeTitle}
                            >
                              {initials(badgeUser.full_name || badgeUser.username || "-")}
                            </div>
                          ) : (
                            <div className="h-6 w-6 rounded-full bg-slate-100 text-[10px] font-semibold text-slate-500 flex items-center justify-center">
                              -
                            </div>
                          )}
                          {canDeleteProjects ? (
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={deletingProjectId === project.id}
                              onClick={(event) => {
                                event.preventDefault()
                                event.stopPropagation()
                                void deleteProject(project.id)
                              }}
                              className="h-5 w-5 rounded-full border-red-200 p-0 text-xs text-red-600 hover:bg-red-50 flex-shrink-0 flex items-center justify-center"
                            >
                              {deletingProjectId === project.id ? "..." : "×"}
                            </Button>
                          ) : null}
                        </div>
                      </div>

                      {/* Current Phase */}
                      <div className="mb-2">
                        <Badge className={`text-xs whitespace-nowrap px-2 py-0.5 ${isClosed ? "bg-slate-200 text-slate-500 border border-slate-300" : "bg-blue-100 text-blue-700 border border-blue-200"}`}>
                          {PHASE_LABELS[phase] || "Meetings"}
                        </Badge>
                      </div>

                      {/* Stats Grid: Tasks, Deadline */}
                      <div className="grid grid-cols-2 gap-1.5 mb-2">
                        <div className="text-center p-1.5 bg-slate-50 dark:bg-slate-800 rounded-md">
                          <div className="text-[10px] text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-0.5">Tasks</div>
                          <div className="text-base font-semibold text-slate-900 dark:text-slate-100">{taskCount}</div>
                        </div>
                        <div className="text-center p-1.5 bg-slate-50 dark:bg-slate-800 rounded-md">
                          <div className="text-[10px] text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-0.5">Deadline</div>
                          <div className="text-xs font-semibold text-slate-900 dark:text-slate-100 leading-tight">{formatDeadline(project.due_date)}</div>
                        </div>
                      </div>

                      {/* Members */}
                      <div className="mb-2 pt-2 border-t border-slate-100 dark:border-slate-700">
                        <div className="text-[10px] text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1.5">Members</div>
                        <div className="flex items-center gap-1.5">
                          {visibleMembers.length > 0 ? (
                            <div className="flex -space-x-1.5">
                              {visibleMembers.map((member) => (
                                <div
                                  key={member.id}
                                  title={member.full_name || member.username || "-"}
                                  className="h-6 w-6 rounded-full border-2 border-white bg-slate-100 text-xs font-semibold text-slate-600 flex items-center justify-center shadow-sm dark:border-slate-800 dark:bg-slate-700 dark:text-slate-300"
                                >
                                  {initials(member.full_name || member.username || "-")}
                                </div>
                              ))}
                              {remainingMembers > 0 && (
                                <div className="h-6 w-6 rounded-full border-2 border-white bg-slate-100 text-[10px] font-semibold text-slate-600 flex items-center justify-center shadow-sm dark:border-slate-800 dark:bg-slate-700 dark:text-slate-300">
                                  +{remainingMembers}
                                </div>
                              )}
                            </div>
                          ) : (
                            <div className="text-xs text-slate-400 dark:text-slate-500">No members</div>
                          )}
                        </div>
                      </div>

                      {/* View Details Link */}
                      <div className="pt-2 border-t border-slate-100 dark:border-slate-700">
                        <span className="text-xs font-semibold text-blue-600 dark:text-blue-400 transition-colors group-hover:text-blue-700 dark:group-hover:text-blue-300 group-hover:underline">
                          View details →
                        </span>
                      </div>
                    </Card>
                  </Link>
                )
              })}
            </div>
          </div>
        ) : null}

        {activeTab === "all" ? (
          <div className="space-y-4 sm:space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
              <div>
                <div className="text-xl sm:text-2xl font-bold tracking-tight text-slate-800">
                  {viewMode === "department"
                    ? `All (${activeAllRangeLabel}) - Department`
                    : `All (${activeAllRangeLabel})`}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {allRangeDoneToggleApplies ? (
                  <Button
                    variant={showAllDoneTasks ? "default" : "outline"}
                    className="h-8 sm:h-9 rounded-xl border-slate-300 px-2 sm:px-3 text-xs sm:text-sm shadow-sm flex-1 sm:flex-none"
                    onClick={() => setShowAllDoneTasks((prev) => !prev)}
                  >
                    {showAllDoneTasks ? "Hide done" : "See done"}
                  </Button>
                ) : null}
                {viewMode === "department" ? (
                  <>
                    <Select value={selectedUserId} onValueChange={setSelectedUserId}>
                      <SelectTrigger className="h-8 sm:h-9 w-full sm:w-48 border-slate-200 focus:border-slate-400 rounded-xl text-xs sm:text-sm">
                        <SelectValue placeholder="All users" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__all__">All users</SelectItem>
                        {departmentUsers.map((u) => (
                          <SelectItem key={u.id} value={u.id}>
                            {u.full_name || u.username || "-"}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button
                      variant="outline"
                      className="h-8 sm:h-9 rounded-xl border-slate-300 bg-white px-2 sm:px-3 text-xs sm:text-sm text-slate-900 shadow-sm hover:bg-slate-50 flex-1 sm:flex-none"
                      onClick={handlePrint}
                    >
                      <Printer className="mr-1 sm:mr-2 h-3 w-3 sm:h-4 sm:w-4" />
                      Print
                    </Button>
                    <Button
                      variant="outline"
                      className="h-8 sm:h-9 rounded-xl border-slate-300 bg-white px-2 sm:px-3 text-xs sm:text-sm text-slate-900 shadow-sm hover:bg-slate-50 flex-1 sm:flex-none"
                      onClick={exportAllTodayReport}
                      disabled={exportingDailyReport}
                    >
                      {exportingDailyReport ? "Exporting..." : "Export Excel"}
                    </Button>
                  </>
                ) : null}
                {viewMode === "mine" ? (
                  <div className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-2 py-1 shadow-sm">
                    <Button
                      variant="outline"
                      className="h-8 rounded-lg border-slate-300 bg-white px-3 text-sm text-slate-900 shadow-sm hover:bg-slate-50"
                      onClick={() =>
                        setShowDailyUserReport((prev) => {
                          const next = !prev
                          if (next) setPrintRange("today")
                          return next
                        })
                      }
                    >
                      {showDailyUserReport ? "Hide Daily Report" : "Daily Report"}
                    </Button>
                    <Button
                      variant="outline"
                      className="h-8 rounded-lg border-slate-300 bg-white px-3 text-sm text-slate-900 shadow-sm hover:bg-slate-50"
                      onClick={handlePrint}
                    >
                      <Printer className="mr-2 h-4 w-4" />
                      Print
                    </Button>
                  </div>
                ) : null}
              </div>
            </div>
            {viewMode === "mine" && showDailyUserReport ? (
              <Card className="bg-white border border-slate-200 shadow-sm rounded-2xl p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-slate-800">{dailyReportHeading}</div>
                    <div className="text-xs text-slate-500 mt-1">
                      {selectedAllReportLabel
                        ? `System, fast, and project tasks for ${selectedAllReportLabel}.`
                        : "System, fast, and project tasks for today."}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {loadingDailyReport ? <div className="text-xs text-slate-500">Loading...</div> : null}
                    <Button
                      variant="outline"
                      className="h-8 rounded-lg border-slate-300 bg-white px-3 text-xs text-slate-900 shadow-sm hover:bg-slate-50"
                      onClick={() => setShowFullDailyReportTable((prev) => !prev)}
                    >
                      {showFullDailyReportTable ? "Compact table" : "Show full table"}
                    </Button>
                    <Button
                      variant="outline"
                      className="h-8 rounded-lg border-slate-300 bg-white px-3 text-xs text-slate-900 shadow-sm hover:bg-slate-50"
                      disabled={exportingDailyReport}
                      onClick={() => void exportDailyReport()}
                    >
                      {exportingDailyReport ? "Exporting..." : "Export Excel"}
                    </Button>
                  </div>
                </div>
                <TaskOneHMarkerLegend className="mt-3" />
                {!loadingDailyReport && dailyReport?.day === selectedAllReportIso ? (
                  <DailyProjectCoverageNotices rows={dailyUserReportRows} department="DEV" slotDisplay={getDailyReportOneHSlotDisplay} />
                ) : null}
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                  <span className="font-medium text-slate-600">Period:</span>
                  <button
                    type="button"
                    className={`rounded-md border px-2 py-1 ${dailyReportPeriodFilter === "all"
                      ? "border-blue-500 bg-blue-50 text-blue-700"
                      : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                      }`}
                    onClick={() => setDailyReportPeriodFilter("all")}
                  >
                    All
                  </button>
                  <button
                    type="button"
                    className={`rounded-md border px-2 py-1 ${dailyReportPeriodFilter === "am_side"
                      ? "border-blue-500 bg-blue-50 text-blue-700"
                      : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                      }`}
                    onClick={() => setDailyReportPeriodFilter("am_side")}
                  >
                    AM + AM/PM
                  </button>
                  <button
                    type="button"
                    className={`rounded-md border px-2 py-1 ${dailyReportPeriodFilter === "pm_side"
                      ? "border-blue-500 bg-blue-50 text-blue-700"
                      : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                      }`}
                    onClick={() => setDailyReportPeriodFilter("pm_side")}
                  >
                    PM + AM/PM
                  </button>
                  <span className="ml-2 font-medium text-slate-600">Status:</span>
                  <button
                    type="button"
                    className={`rounded-md border px-2 py-1 uppercase ${dailyReportStatusFilter.length === 0
                      ? "border-blue-500 bg-blue-50 text-blue-700"
                      : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                      }`}
                    onClick={() => setDailyReportStatusFilter([])}
                  >
                    All
                  </button>
                  {dailyReportAvailableStatuses.map((statusOption) => {
                    const isActive = dailyReportStatusFilter.includes(statusOption.key)
                    return (
                      <button
                        key={statusOption.key}
                        type="button"
                        className={`rounded-md border px-2 py-1 uppercase ${isActive
                          ? "border-blue-500 bg-blue-50 text-blue-700"
                          : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                          }`}
                        onClick={() => toggleDailyReportStatusFilter(statusOption.key)}
                      >
                        {statusOption.label}
                      </button>
                    )
                  })}
                  <DailyRlzSaveButton day={selectedAllReportIso} report={dailyReport} onSaved={refreshDailyReport} />
                </div>
                <DailyReportMeetingsTable
                  meetings={visibleMeetings}
                  users={users}
                  reportDateIso={selectedAllReportIso}
                />
                <div
                  ref={dailyReportScrollRef}
                  className={`mt-3 ${showFullDailyReportTable ? "max-h-none overflow-x-auto overflow-y-visible" : "max-h-[320px] overflow-x-auto overflow-y-auto"} ${isDraggingDailyReport ? "cursor-grabbing" : "cursor-grab"
                    }`}
                  onMouseDown={handleDailyReportMouseDown}
                  onMouseMove={handleDailyReportMouseMove}
                  onMouseUp={handleDailyReportMouseEnd}
                  onMouseLeave={handleDailyReportMouseEnd}
                >
                  <table className="min-w-[1350px] w-full table-fixed border border-slate-200 text-[11px] daily-report-table">
                    <colgroup>
                      <col className="w-[24px]" />
                      <col className="w-[32px]" />
                      <col className="w-[76px]" />
                      <col className="w-[44px]" />
                      <col className="w-[52px]" />
                      <col />
                      <col className="w-[100px]" />
                      <col className="w-[92px]" />
                      <col className="w-[86px]" />
                      <col className="w-[64px]" />
                      <col className="w-[88px]" />
                      <col className="w-[72px]" />
                      <col className="w-[170px]" />
                      <col className="w-[140px]" />
                    </colgroup>
                    <thead className="sticky top-0 z-10 bg-slate-50">
                      <tr>
                        <th className="border border-slate-200 bg-slate-50 px-1 py-2 text-center text-xs uppercase" aria-label="Move row" />
                        <th className="border border-slate-200 bg-slate-50 px-2 py-2 text-left text-xs uppercase whitespace-normal">
                          Nr
                        </th>
                        <th className="border border-slate-200 px-2 py-2 text-left text-xs uppercase">LLOJI</th>
                        <th className="border border-slate-200 px-2 py-2 text-left text-xs uppercase">NLL</th>
                        <th className="border border-slate-200 px-2 py-2 text-left text-xs uppercase whitespace-nowrap">AM/PM</th>
                        <th className="border border-slate-200 px-2 py-2 text-left text-xs uppercase">Titulli</th>
                        <th className="border border-slate-200 px-2 py-2 text-center text-xs uppercase">SIMBOLI</th>
                        <th className="border border-slate-200 px-2 py-2 text-left text-xs uppercase">STATUSI</th>
                        <th className="border border-slate-200 px-2 py-2 text-left text-xs uppercase whitespace-normal">1H SLOT</th>
                        <th className="border border-slate-200 px-2 py-2 text-left text-xs uppercase">BZ</th>
                        <th className="border border-slate-200 px-2 py-2 text-left text-xs uppercase whitespace-normal">KOHA BARAZIMIT</th>
                        <th className="border border-slate-200 px-2 py-2 text-left text-xs uppercase whitespace-nowrap">T/Y/O</th>
                        <th className="border border-slate-200 px-2 py-2 text-left text-xs uppercase">Arsyeja</th>
                        <th className="border border-slate-200 px-2 py-2 text-left text-xs uppercase">Koment</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dailyUserReportFilteredEntries.length ? (
                        dailyUserReportFilteredEntries.map(({ id: rowId, row }, index) => {
                          const commentKey = row.taskId ? `task:${row.taskId}` : ""
                          const previousValue = row.comment ?? ""
                          const isDeadlineImportant = row.taskId ? deadlineImportantTaskIds.has(row.taskId) : false
                          const hasEightAmIndicator = titleHasEightAmIndicator(row.title)
                          const isTitleExpanded = Boolean(expandedDailyReportTitleIds[rowId])
                          const canExpandTitle = Boolean((row.title || "").trim())
                          const visibleTitle = isTitleExpanded ? row.title : getDailyReportTitlePreview(row.title)
                          const selectedDayClass = row.taskId
                            ? selectedDayDateRowClass(
                              dailyReportStartDateByTaskId.get(row.taskId),
                              dailyReportDueDateByTaskId.get(row.taskId),
                              isDeadlineImportant,
                            )
                            : ""
                          return (
                            <tr
                              key={rowId}
                              className={[
                                dragDailyReportRowId === rowId ? "ring-2 ring-blue-300" : "",
                                overDailyReportRowId === rowId ? "bg-blue-50/60" : "",
                                selectedDayClass,
                              ].join(" ")}
                              onClick={() => {
                                if (dragDailyReportRowId && dragDailyReportRowId !== rowId) {
                                  handleDailyReportRowDrop(rowId)
                                }
                              }}
                              onDragOver={(event) => {
                                event.preventDefault()
                                if (dragDailyReportRowId && dragDailyReportRowId !== rowId) {
                                  setOverDailyReportRowId(rowId)
                                }
                              }}
                              onDrop={(event) => {
                                event.preventDefault()
                                handleDailyReportRowDrop(rowId)
                              }}
                            >
                              <td className="border border-slate-200 bg-white px-1 py-2 align-top">
                                <button
                                  type="button"
                                  draggable
                                  className="inline-flex h-5 w-5 shrink-0 cursor-grab items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-600 active:cursor-grabbing"
                                  aria-label="Move row"
                                  title="Tap to select, then tap another row to move"
                                  onMouseDown={(event) => event.stopPropagation()}
                                  onClick={(event) => {
                                    event.stopPropagation()
                                    setDragDailyReportRowId((prev) => (prev === rowId ? null : rowId))
                                    setOverDailyReportRowId(null)
                                  }}
                                  onDragStart={(event) => {
                                    setDragDailyReportRowId(rowId)
                                    event.dataTransfer.effectAllowed = "move"
                                    event.dataTransfer.setData("text/plain", rowId)
                                  }}
                                  onDragEnd={() => {
                                    setDragDailyReportRowId(null)
                                    setOverDailyReportRowId(null)
                                  }}
                                >
                                  <GripVertical className="h-3.5 w-3.5" aria-hidden="true" />
                                </button>
                              </td>
                              <td className="border border-slate-200 bg-white px-2 py-2 align-top font-semibold">
                                {index + 1}
                              </td>
                              <td className="border border-slate-200 px-2 py-2 align-top font-semibold">{dailyReportTypeLabel(row.typeLabel)}</td>
                              <td className="border border-slate-200 px-2 py-2 align-top">{row.subtype}</td>
                              <td className="border border-slate-200 px-2 py-2 align-top">{row.period}</td>
                              <td
                                className={[
                                  "border border-slate-200 px-2 py-2 align-top uppercase font-semibold",
                                  isDeadlineImportant ? "text-red-800" : "",
                                ].join(" ")}
                              >
                                <div className="flex flex-wrap items-start gap-2">
                                  {hasEightAmIndicator ? (
                                    <span className="inline-flex rounded-full border border-red-300 bg-red-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-red-700">
                                      08:00
                                    </span>
                                  ) : null}
                                  <span className="min-w-0 flex-1 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
                                    <TaskMarkerComment taskId={row.taskId} />
                                    {(() => {
                                      const hasMarks = typeof visibleTitle === "string" && visibleTitle.includes("[[")
                                      const renderedTitle = hasMarks ? renderMarkedNoteContent(visibleTitle, visibleTitle) : visibleTitle
                                      if (row.typeLabel === "PRJK" && row.projectTitle) {
                                        return (
                                          <>
                                            <span>{row.projectTitle}</span>
                                            <span> : {renderedTitle}</span>
                                          </>
                                        )
                                      }
                                      return renderedTitle
                                    })()}
                                  </span>
                                  {canExpandTitle ? (
                                    <button
                                      type="button"
                                      className="ml-auto inline-flex rounded border border-slate-300 bg-white px-2 py-0.5 text-[10px] font-semibold uppercase text-slate-600 hover:bg-slate-50"
                                      onClick={(event) => {
                                        event.stopPropagation()
                                        setExpandedDailyReportTitleIds((prev) => ({ ...prev, [rowId]: !prev[rowId] }))
                                      }}
                                    >
                                      {isTitleExpanded ? "-" : "+"}
                                    </button>
                                  ) : null}
                                </div>
                                {row.typeLabel === "PRJK" && row.taskId ? (
                                  (() => {
                                    const counts = getChecklistCountsForTask(row.taskId)
                                    if (counts.total === 0) return null
                                    const isOpen = Boolean(taskChecklistOpen[row.taskId])
                                    const label = `Subtasks ${counts.done}/${counts.total}`
                                    return (
                                      <div className="mt-1">
                                        <button
                                          type="button"
                                          className="text-[10px] uppercase text-slate-500 hover:text-slate-700"
                                          onClick={() => toggleTaskChecklist(row.taskId!)}
                                        >
                                          {`${label} ${isOpen ? "▲" : "▼"}`}
                                        </button>
                                        {isOpen ? (
                                          <div className="mt-1 space-y-1">
                                            {taskChecklistLoading[row.taskId] ? (
                                              <div className="text-[10px] text-slate-500">Loading subtasks...</div>
                                            ) : (
                                              getChecklistItemsForTask(row.taskId).map((item) => {
                                                const isChecked = Boolean(item.is_checked)
                                                const label = item.title || item.comment || item.description || "Untitled subtask"
                                                return (
                                                  <div key={item.id} className="flex items-start gap-1.5 normal-case">
                                                    <Checkbox checked={isChecked} disabled />
                                                    <span className={["text-[10px]", isChecked ? "line-through text-slate-400" : "text-slate-700"].join(" ")}>
                                                      {label}
                                                    </span>
                                                  </div>
                                                )
                                              })
                                            )}
                                          </div>
                                        ) : null}
                                      </div>
                                    )
                                  })()
                                ) : null}
                              </td>
                              <td className="border border-slate-200 w-[100px] min-w-[100px] px-2 py-2 text-center align-middle">
                                {row.typeLabel === "SYS" ? (
                                  <span className="text-xs font-semibold text-slate-600">SYS</span>
                                ) : (
                                  <TaskOneHMarkerEditor taskId={row.taskId} marker={row.oneHMarker} markerByGa={row.oneHMarkerByGa} className="mx-auto shrink-0" />
                                )}
                              </td>
                              <td
                                className={`border border-slate-200 px-2 py-2 align-top uppercase ${weeklyPlanStatusBgClass(normalizeDailyReportStatusKey(row.status))}`}
                              >
                                {dailyReportStatusDisplay(row.status)}
                              </td>
                              <td className="border border-slate-200 px-2 py-2 align-top">
                                {(row.subtype === "1H" || row.subtype === "R1") && row.taskId && !isWfeDailyReportRow(row) ? (
                                  <select
                                    className="h-7 w-full rounded-md border border-amber-300 bg-amber-50 px-2 text-[11px] font-semibold text-amber-900 shadow-sm outline-none focus:border-amber-500"
                                    value={normalizeOneHReportSlot(row.oneHReportSlot) || ONE_H_REPORT_SLOT_NONE_VALUE}
                                    disabled={savingOneHReportSlotTaskId === row.taskId}
                                    aria-label="1H report time"
                                    onClick={(event) => event.stopPropagation()}
                                    onChange={(event) => {
                                      event.stopPropagation()
                                      void saveOneHReportSlot(row.taskId!, event.target.value)
                                    }}
                                  >
                                    <option value={ONE_H_REPORT_SLOT_NONE_VALUE}>No slot</option>
                                    {ONE_H_REPORT_SLOT_OPTIONS.filter((slot) =>
                                      row.period === "AM"
                                        ? ["10:00", "11:00", "11:50"].includes(slot)
                                        : row.period === "PM"
                                          ? ["14:20", "16:00"].includes(slot)
                                          : true,
                                    ).map((slot) => (
                                      <option key={slot} value={slot}>
                                        {slot}
                                      </option>
                                    ))}
                                  </select>
                                ) : (
                                  getDailyReportOneHSlotDisplay(row)
                                )}
                              </td>
                              <td className="border border-slate-200 px-2 py-2 align-top">{row.bz}</td>
                              <td className="border border-slate-200 px-2 py-2 align-top">{row.kohaBz}</td>
                              <td className="border border-slate-200 px-2 py-2 align-top">
                                {formatTyoDisplay(
                                  row.tyo,
                                  row.taskId ? dailyReportTyoDateByTaskId.get(row.taskId) : null,
                                  row.taskId ? deadlineImportantTaskIds.has(row.taskId) : false,
                                )}
                              </td>
                              <td className="border border-slate-200 px-2 py-2 align-top">
                                <DailyRlzReasonCell
                                  taskId={row.taskId}
                                  day={selectedAllReportIso}
                                  state={row.taskId ? dailyRlzStateByTask(dailyReport).get(row.taskId) : null}
                                  onSaved={refreshDailyReport}
                                />
                              </td>
                              <td className="border border-slate-200 px-2 py-2 align-top">
                                <DailyRlzCommentField
                                  taskId={row.taskId}
                                  day={selectedAllReportIso}
                                  state={row.taskId ? dailyRlzStateByTask(dailyReport).get(row.taskId) : null}
                                  onSaved={refreshDailyReport}
                                />
                              </td>
                            </tr>
                          )
                        })
                      ) : (
                        <tr>
                          <td className="border border-slate-200 px-2 py-4 text-center italic text-slate-500" colSpan={14}>
                            No data available.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
                <div className="mt-4">
                  <table className="min-w-[900px] w-full border border-slate-200 text-[11px]">
                    <colgroup>
                      <col className="w-[180px]" />
                      <col />
                    </colgroup>
                    <tbody>
                      <tr>
                        <td className="border border-slate-200 px-2 py-2 text-xs font-semibold uppercase align-top">
                          GA/KUR/SI/KUJT/PRBL
                        </td>
                        <td className="border border-slate-200 px-2 py-2">
                          <div className="flex items-start gap-2">
                            <Textarea
                              value={gaTableInput}
                              onChange={(e) => setGaTableInput(e.target.value)}
                              onBlur={(e) => {
                                const nextValue = e.target.value
                                if (nextValue === (gaTableEntry?.content ?? "")) return
                                void saveGaTableEntry(nextValue)
                              }}
                              placeholder="Add GA/KUR/SI/KUJT/PRBL..."
                              className="min-h-[60px] text-xs"
                            />
                            <Button
                              type="button"
                              variant="outline"
                              className="h-8 rounded-lg border-slate-300 bg-white px-3 text-[11px] text-slate-900 shadow-sm hover:bg-slate-50"
                              disabled={savingGaTable || !gaTableDirty}
                              onClick={() => void saveGaTableEntry(gaTableInput)}
                            >
                              {savingGaTable ? "Saving..." : "Save"}
                            </Button>
                          </div>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </Card>
            ) : null}

            <div className="space-y-2">
              <Card className="bg-white border border-slate-200 shadow-sm rounded-2xl gap-2 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-slate-800">Meetings</div>
                  </div>
                  <div className="text-xs font-semibold text-slate-600">
                    {todayExternalMeetings.length + todayInternalMeetings.length}
                  </div>
                </div>
                {todayExternalMeetings.length || todayInternalMeetings.length ? (
                  <Table
                    containerClassName="mt-2 rounded-lg border border-slate-200 bg-white"
                    className="min-w-[520px] text-[11px]"
                  >
                    <TableHeader>
                      <TableRow className="bg-slate-50">
                        {["MEETING TITLE", "MEETING DATE"].map((label) => (
                          <TableHead
                            key={label}
                            className="text-[10px] font-semibold uppercase tracking-wide text-slate-500"
                          >
                            {label}
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {todayExternalMeetings.length ? (
                        <TableRow className="bg-slate-100/80">
                          <TableCell colSpan={2} className="px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-600">
                            External Meetings
                          </TableCell>
                        </TableRow>
                      ) : null}
                      {todayExternalMeetings.map((meeting) => (
                        <TableRow key={meeting.id} className={TODAY_TASK_ROW_CLASS}>
                          <TableCell className={`${TODAY_TASK_CELL_CLASS} whitespace-normal break-words font-medium text-slate-800`}>
                            <div className={TODAY_TASK_TEXT_CLAMP_CLASS}>{meeting.title || "Meeting"}</div>
                            {canceledTodayMeetings.has(meeting.id) ? <MeetingCanceledBadge /> : null}
                          </TableCell>
                          <TableCell className={TODAY_TASK_CELL_CLASS}>{formatMeetingDateTime(meeting)}</TableCell>
                        </TableRow>
                      ))}
                      {todayInternalMeetings.length ? (
                        <TableRow className="bg-slate-100/80">
                          <TableCell
                            colSpan={2}
                            className={`px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-600 ${todayExternalMeetings.length ? "border-t-4 border-white" : ""}`}
                          >
                            Internal Meetings
                          </TableCell>
                        </TableRow>
                      ) : null}
                      {todayInternalMeetings.map((meeting) => (
                        <TableRow key={meeting.id} className={TODAY_TASK_ROW_CLASS}>
                          <TableCell className={`${TODAY_TASK_CELL_CLASS} whitespace-normal break-words font-medium text-slate-800`}>
                            <div className={TODAY_TASK_TEXT_CLAMP_CLASS}>{meeting.title || "Meeting"}</div>
                            {canceledTodayMeetings.has(meeting.id) ? <MeetingCanceledBadge /> : null}
                          </TableCell>
                          <TableCell className={TODAY_TASK_CELL_CLASS}>{formatMeetingDateTime(meeting)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <div className="mt-1 text-sm text-slate-500">
                    {loadingExtras ? "Loading meetings..." : "No meetings today."}
                  </div>
                )}
              </Card>

              <Card className="bg-white border border-slate-200 shadow-sm rounded-2xl gap-2 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-slate-800">Waiting Confirmation</div>
                  </div>
                  <div className="text-xs font-semibold text-slate-600">{todayWaitingTasks.length}</div>
                </div>
                {todayWaitingTasks.length ? (
                  <Table
                    containerClassName="mt-2 rounded-lg border border-slate-200 bg-white"
                    className="min-w-[1100px] text-[11px]"
                  >
                    <TableHeader>
                      <TableRow className="bg-slate-50">
                        {["NR", "TYPE", "DEPARTMENT", "PROJECT", "ASSIGNED", "TASK TITLE", "CONFIRMER", "SYMBOL", "STATUS", "START", "DUE", "ACTIONS"].map((label) => (
                          <TableHead
                            key={label}
                            className="text-[10px] font-semibold uppercase tracking-wide text-slate-500"
                          >
                            {label}
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {todayWaitingTasks.map(({ task, type }, index) => {
                        const project = task.project_id ? projects.find((p) => p.id === task.project_id) || null : null
                        const meta = task.project_id ? projectMetaLookup.get(task.project_id) || null : null
                        const projectDepartmentId = project?.department_id || meta?.department_id || null
                        const taskDepartmentId = task.department_id || projectDepartmentId
                        const projectTitle = type === "Project" ? (resolveProjectTitle(project) || meta?.title || "-") : "-"
                        const departmentLabel = taskDepartmentId
                          ? formatDepartmentName(departmentMap.get(taskDepartmentId)?.name || "")
                          : "-"
                        const assignees = taskAssigneeInitials(task)
                        const confirmer = task.confirmation_assignee_id ? userMap.get(task.confirmation_assignee_id) : null
                        const confirmerLabel = confirmer?.full_name || confirmer?.username || confirmer?.email || "-"
                        return (
                          <TableRow
                            key={`waiting-${type}-${task.id}`}
                            className={`${TODAY_TASK_ROW_CLASS} ${selectedDayTaskRowClass(task)}`}
                          >
                            <TableCell className={`${TODAY_TASK_CELL_CLASS} font-semibold text-slate-700`}>{index + 1}</TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>{type}</TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>{departmentLabel || "-"}</TableCell>
                            <TableCell className={`${TODAY_TASK_CELL_CLASS} whitespace-normal break-words`}>
                              <div className={TODAY_TASK_TEXT_CLAMP_CLASS}>{projectTitle}</div>
                            </TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>
                              {assignees.length ? (
                                <div className="flex items-center gap-1">
                                  {assignees.map((item) => (
                                    <div
                                      key={item.id}
                                      className="h-6 w-6 rounded-full bg-slate-100 text-[9px] font-semibold text-slate-600 flex items-center justify-center"
                                      title={item.label}
                                    >
                                      {item.value}
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                <span className="text-slate-500">-</span>
                              )}
                            </TableCell>
                            <TableCell className={`${TODAY_TASK_CELL_CLASS} whitespace-normal break-words font-medium text-slate-800`}>
                              <div className={`flex flex-wrap items-start gap-2 ${TODAY_TASK_TEXT_CLAMP_CLASS}`}>
                                <span>{renderAllTodayTaskTitle(task)}</span>
                              </div>
                            </TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>{confirmerLabel}</TableCell>
                            <TableCell className="w-[100px] min-w-[100px] px-2 py-2 text-center align-middle">
                              <TaskOneHMarkerEditor taskId={task.id} marker={task.one_h_marker} markerByGa={task.one_h_marker_by_ga} markerComment={task.one_h_marker_comment} className="mx-auto shrink-0" />
                            </TableCell>
                            <TableCell className={`${TODAY_TASK_CELL_CLASS} ${weeklyPlanStatusBgClass(taskStatusValue(task))}`}>
                              {waitingConfirmationStatusLabel(task)}
                            </TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>{formatDateOnly(task.start_date)}</TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>{formatDateOnly(task.due_date)}</TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>
                              <div className="flex items-center gap-2">
                                {canMarkWaitingConfirmation(task) ? (
                                  <Button
                                    variant="outline"
                                    size="icon"
                                    className="h-6 w-6 border-emerald-200 text-emerald-600 hover:border-emerald-300 hover:text-emerald-700"
                                    title="Mark done"
                                    aria-label={`Mark ${task.title} as done`}
                                    onClick={() => void markWaitingTaskDone(task)}
                                    disabled={markingWaitingTaskId === task.id}
                                  >
                                    <Check className="h-3 w-3" />
                                  </Button>
                                ) : null}
                                <Button
                                  variant="outline"
                                  size="icon"
                                  className="h-6 w-6 border-slate-200 text-slate-500 hover:border-blue-200 hover:text-blue-600"
                                  title="Edit"
                                  aria-label={`Edit ${task.title}`}
                                  onClick={() => startAllTodayTaskEdit(task)}
                                  disabled={!canEditAllTodayTask(task)}
                                >
                                  <Pencil className="h-3 w-3" />
                                </Button>
                                {canDeleteAllTodayTask ? (
                                  <Button
                                    variant="outline"
                                    size="icon"
                                    className="h-6 w-6 border-slate-200 text-slate-500 hover:border-rose-200 hover:text-rose-600"
                                    title="Delete"
                                    aria-label={`Delete ${task.title}`}
                                    onClick={() => void deleteAllTodayTask(task.id)}
                                    disabled={deletingAllTodayTaskId === task.id}
                                  >
                                    <Trash2 className="h-3 w-3" />
                                  </Button>
                                ) : null}
                              </div>
                            </TableCell>
                          </TableRow>
                        )
                      })}
                    </TableBody>
                  </Table>
                ) : (
                  <div className="mt-1 text-sm text-slate-500">No waiting confirmation tasks.</div>
                )}
              </Card>

              <Card className="bg-white border border-slate-200 shadow-sm rounded-2xl p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-slate-800">Project Tasks</div>
                  </div>
                  <div className="text-xs font-semibold text-slate-600">{todayProjectTasks.length}</div>
                </div>
                {todayProjectTasks.length ? (
                  <Table
                    containerClassName="mt-3 rounded-lg border border-slate-200 bg-white"
                    className="min-w-[1200px] text-[11px]"
                  >
                    <colgroup>
                      <col />
                      <col className="w-[82px]" />
                      <col className="w-[64px]" />
                      <col />
                      <col />
                      <col className="w-[100px]" />
                      <col />
                      <col />
                      <col />
                      <col />
                      <col />
                    </colgroup>
                    <TableHeader>
                      <TableRow className="bg-slate-50">
                        {["NR", "PROJECT TITLE", "PHASE", "ASSIGNED", "TASK TITLE", "SYMBOL", "STATUS", "CREATED", "START", "DUE", "ACTIONS"].map((label) => (
                          <TableHead
                            key={label}
                            className="text-[10px] font-semibold uppercase tracking-wide text-slate-500"
                          >
                            {label}
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {todayProjectTasksSorted.map((task, index) => {
                        const project = task.project_id ? projects.find((p) => p.id === task.project_id) || null : null
                        const meta = task.project_id ? projectMetaLookup.get(task.project_id) || null : null
                        const projectTitle = resolveProjectTitle(project) || meta?.title || "-"
                        const phaseLabel = PHASE_LABELS[task.phase || "MEETINGS"] || task.phase || "-"
                        const assignees = taskAssigneeInitials(task)
                        return (
                          <TableRow
                            key={task.id}
                            className={`${TODAY_TASK_ROW_CLASS} ${selectedDayTaskRowClass(task)}`}
                          >
                            <TableCell className={`${TODAY_TASK_CELL_CLASS} font-semibold text-slate-700`}>
                              {index + 1}
                            </TableCell>
                            <TableCell className={`${TODAY_TASK_CELL_CLASS} w-[82px] whitespace-normal break-words`}>
                              <div className={TODAY_TASK_TEXT_CLAMP_CLASS}>{projectTitle}</div>
                            </TableCell>
                            <TableCell className={`${TODAY_TASK_CELL_CLASS} w-[64px] whitespace-normal break-words`}>
                              {phaseLabel}
                            </TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>
                              {assignees.length ? (
                                <div className="flex items-center gap-1">
                                  {assignees.map((item) => (
                                    <div
                                      key={item.id}
                                      className="h-6 w-6 rounded-full bg-slate-100 text-[9px] font-semibold text-slate-600 flex items-center justify-center"
                                      title={item.label}
                                    >
                                      {item.value}
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                <span className="text-slate-500">-</span>
                              )}
                            </TableCell>
                            <TableCell className={`${TODAY_TASK_CELL_CLASS} whitespace-normal break-words font-medium text-slate-800`}>
                              <div className={`flex flex-wrap items-start gap-2 ${TODAY_TASK_TEXT_CLAMP_CLASS}`}>
                                <span>
                                  {renderAllTodayTaskTitle(task)}
                                </span>
                                {task.plan_note_origin_id ? (
                                  <Badge className={`text-[10px] px-1.5 py-0 ${GA_BADGE_CLASSES}`}>PX JAV</Badge>
                                ) : isGaTask(task) ? (
                                  <Badge className={`text-[10px] px-1.5 py-0 ${GA_BADGE_CLASSES}`}>GA</Badge>
                                ) : null}
                                {task.is_1h_report ? (
                                  <Badge className={`text-[10px] px-1.5 py-0 ${ONE_H_BADGE_CLASSES}`}>1H</Badge>
                                ) : null}
                                {task.is_r1 ? (
                                  <Badge className={`text-[10px] px-1.5 py-0 ${R1_BADGE_CLASSES}`}>R1</Badge>
                                ) : null}
                                {task.is_personal ? (
                                  <Badge className={`text-[10px] px-1.5 py-0 ${PERSONAL_BADGE_CLASSES}`}>P</Badge>
                                ) : null}
                                {task.is_bllok ? (
                                  <Badge className={`text-[10px] px-1.5 py-0 ${BLLOK_BADGE_CLASSES}`}>BLLOK</Badge>
                                ) : null}
                              </div>
                            </TableCell>
                            <TableCell className="w-[100px] min-w-[100px] px-2 py-2 text-center align-middle">
                              <TaskOneHMarkerEditor taskId={task.id} marker={task.one_h_marker} markerByGa={task.one_h_marker_by_ga} markerComment={task.one_h_marker_comment} className="mx-auto shrink-0" />
                            </TableCell>
                            <TableCell className={`${TODAY_TASK_CELL_CLASS} ${weeklyPlanStatusBgClass(taskStatusValue(task))}`}>
                              {reportStatusLabel(taskStatusValue(task))}
                            </TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>{formatDateOnly(task.created_at)}</TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>{formatDateOnly(task.start_date)}</TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>{formatDateOnly(task.due_date)}</TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>
                              <div className="flex items-center gap-2">
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="h-6 rounded-md border-slate-200 px-2 text-[10px] font-semibold text-slate-600 hover:border-emerald-200 hover:text-emerald-700"
                                  title="Create internal meeting"
                                  aria-label={`Create internal meeting from ${task.title}`}
                                  onClick={() => openInternalMeetingFromFastTask(task)}
                                >
                                  INT
                                </Button>
                                <Button
                                  variant="outline"
                                  size="icon"
                                  className="h-6 w-6 border-slate-200 text-slate-500 hover:border-blue-200 hover:text-blue-600"
                                  title="Edit"
                                  aria-label={`Edit ${task.title}`}
                                  onClick={() => startAllTodayTaskEdit(task)}
                                  disabled={!canEditAllTodayTask(task)}
                                >
                                  <Pencil className="h-3 w-3" />
                                </Button>
                                {canDeleteAllTodayTask ? (
                                  <Button
                                    variant="outline"
                                    size="icon"
                                    className="h-6 w-6 border-slate-200 text-slate-500 hover:border-rose-200 hover:text-rose-600"
                                    title="Delete"
                                    aria-label={`Delete ${task.title}`}
                                    onClick={() => void deleteAllTodayTask(task.id)}
                                    disabled={deletingAllTodayTaskId === task.id}
                                  >
                                    <Trash2 className="h-3 w-3" />
                                  </Button>
                                ) : null}
                              </div>
                            </TableCell>
                          </TableRow>
                        )
                      })}
                    </TableBody>
                  </Table>
                ) : (
                  <div className="mt-3 text-sm text-slate-500">No project tasks for {activeAllRangeTaskLabel}.</div>
                )}
              </Card>

              <Card className="bg-white border border-slate-200 shadow-sm rounded-2xl p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-slate-800">Fast Tasks</div>
                  </div>
                  <div className="text-xs font-semibold text-slate-600">{todayNoProjectTasks.length}</div>
                </div>
                {todayNoProjectTasks.length ? (
                  <Table
                    containerClassName="mt-3 rounded-lg border border-slate-200 bg-white"
                    className="min-w-[900px] text-[11px]"
                  >
                    <TableHeader>
                      <TableRow className="bg-slate-50">
                        {["NR", "TYPE", "ASSIGNED", "TASK TITLE", "SYMBOL", "STATUS", "CREATED", "START", "DUE", "ACTIONS"].map((label) => (
                          <TableHead
                            key={label}
                            className="text-[10px] font-semibold uppercase tracking-wide text-slate-500"
                          >
                            {label}
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {todayNoProjectTasksSorted.map((task, index) => {
                        const assignees = taskAssigneeInitials(task)
                        return (
                          <TableRow
                            key={task.id}
                            className={`${TODAY_TASK_ROW_CLASS} ${selectedDayTaskRowClass(task)}`}
                          >
                            <TableCell className={`${TODAY_TASK_CELL_CLASS} font-semibold text-slate-700`}>
                              {index + 1}
                            </TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>{noProjectTypeLabel(task)}</TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>
                              {assignees.length ? (
                                <div className="flex items-center gap-1">
                                  {assignees.map((item) => (
                                    <div
                                      key={item.id}
                                      className="h-6 w-6 rounded-full bg-slate-100 text-[9px] font-semibold text-slate-600 flex items-center justify-center"
                                      title={item.label}
                                    >
                                      {item.value}
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                <span className="text-slate-500">-</span>
                              )}
                            </TableCell>
                            <TableCell className={`${TODAY_TASK_CELL_CLASS} whitespace-normal break-words font-medium text-slate-800`}>
                              <div className={`flex flex-wrap items-start gap-2 ${TODAY_TASK_TEXT_CLAMP_CLASS}`}>
                                <span>
                                  {renderAllTodayTaskTitle(task)}
                                </span>
                                {task.plan_note_origin_id ? (
                                  <Badge className={`text-[10px] px-1.5 py-0 ${GA_BADGE_CLASSES}`}>PX JAV</Badge>
                                ) : isGaTask(task) ? (
                                  <Badge className={`text-[10px] px-1.5 py-0 ${GA_BADGE_CLASSES}`}>GA</Badge>
                                ) : null}
                              </div>
                            </TableCell>
                            <TableCell className="w-[100px] min-w-[100px] px-2 py-2 text-center align-middle">
                              <TaskOneHMarkerEditor taskId={task.id} marker={task.one_h_marker} markerByGa={task.one_h_marker_by_ga} markerComment={task.one_h_marker_comment} className="mx-auto shrink-0" />
                            </TableCell>
                            <TableCell className={`${TODAY_TASK_CELL_CLASS} ${weeklyPlanStatusBgClass(taskStatusValue(task))}`}>
                              {reportStatusLabel(taskStatusValue(task))}
                            </TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>{formatDateOnly(task.created_at)}</TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>{formatDateOnly(task.start_date)}</TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>{formatDateOnly(task.due_date)}</TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>
                              <div className="flex items-center gap-2">
                                <Button
                                  variant="outline"
                                  size="icon"
                                  className="h-6 w-6 border-slate-200 text-slate-500 hover:border-blue-200 hover:text-blue-600"
                                  title="Edit"
                                  aria-label={`Edit ${task.title}`}
                                  onClick={() => startAllTodayTaskEdit(task)}
                                  disabled={!canEditAllTodayTask(task)}
                                >
                                  <Pencil className="h-3 w-3" />
                                </Button>
                                {canDeleteAllTodayTask ? (
                                  <Button
                                    variant="outline"
                                    size="icon"
                                    className="h-6 w-6 border-slate-200 text-slate-500 hover:border-rose-200 hover:text-rose-600"
                                    title="Delete"
                                    aria-label={`Delete ${task.title}`}
                                    onClick={() => void deleteAllTodayTask(task.id)}
                                    disabled={deletingAllTodayTaskId === task.id}
                                  >
                                    <Trash2 className="h-3 w-3" />
                                  </Button>
                                ) : null}
                              </div>
                            </TableCell>
                          </TableRow>
                        )
                      })}
                    </TableBody>
                  </Table>
                ) : (
                  <div className="mt-3 text-sm text-slate-500">No fast tasks for {activeAllRangeTaskLabel}.</div>
                )}
              </Card>

              <Card className="bg-white border border-slate-200 shadow-sm rounded-2xl p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-slate-800">System Tasks</div>
                  </div>
                  <div className="text-xs font-semibold text-slate-600">{todaySystemTasks.length}</div>
                </div>
                {todaySystemTasks.length ? (
                  <Table
                    containerClassName="mt-3 rounded-lg border border-slate-200 bg-white"
                    className="min-w-[900px] text-[11px]"
                  >
                    <TableHeader>
                      <TableRow className="bg-slate-50">
                        {["NR", "ASSIGNED", "TASK TITLE", "SYMBOL", "STATUS", "PRIORITY", "CREATED", "START", "DUE", "ACTIONS"].map((label) => (
                          <TableHead
                            key={label}
                            className="text-[10px] font-semibold uppercase tracking-wide text-slate-500"
                          >
                            {label}
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {todaySystemTasksSorted.map((task, index) => {
                        const assignees = taskAssigneeInitials(task)
                        return (
                          <TableRow
                            key={task.id}
                            className={`${TODAY_TASK_ROW_CLASS} ${selectedDayTaskRowClass(task)}`}
                          >
                            <TableCell className={`${TODAY_TASK_CELL_CLASS} font-semibold text-slate-700`}>
                              {index + 1}
                            </TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>
                              {assignees.length ? (
                                <div className="flex items-center gap-1">
                                  {assignees.map((item) => (
                                    <div
                                      key={item.id}
                                      className="h-6 w-6 rounded-full bg-slate-100 text-[9px] font-semibold text-slate-600 flex items-center justify-center"
                                      title={item.label}
                                    >
                                      {item.value}
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                <span className="text-slate-500">-</span>
                              )}
                            </TableCell>
                            <TableCell className={`${TODAY_TASK_CELL_CLASS} whitespace-normal break-words font-medium text-slate-800`}>
                              <div className={`flex flex-wrap items-start gap-2 ${TODAY_TASK_TEXT_CLAMP_CLASS}`}>
                                <span>{task.title || "-"}</span>
                                <Badge className="text-[10px] px-1.5 py-0 border-slate-200 bg-slate-50 text-slate-700">SYS</Badge>
                              </div>
                            </TableCell>
                            <TableCell className="w-[100px] min-w-[100px] px-2 py-2 text-center align-middle">
                              <span className="text-xs font-semibold text-slate-600">SYS</span>
                            </TableCell>
                            <TableCell className={`${TODAY_TASK_CELL_CLASS} ${weeklyPlanStatusBgClass(taskStatusValue(task))}`}>
                              {reportStatusLabel(taskStatusValue(task))}
                            </TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>{reportPriorityLabel(task.priority)}</TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>{formatDateOnly(task.created_at)}</TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>{formatDateOnly(task.start_date)}</TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>{formatDateOnly(task.due_date)}</TableCell>
                            <TableCell className={TODAY_TASK_CELL_CLASS}>
                              <div className="flex items-center gap-2">
                                <Button
                                  variant="outline"
                                  size="icon"
                                  className="h-6 w-6 border-slate-200 text-slate-500 hover:border-blue-200 hover:text-blue-600"
                                  title="Edit"
                                  aria-label={`Edit ${task.title || "system task"}`}
                                  onClick={() => startAllTodayTaskEdit(task)}
                                  disabled={!canEditAllTodayTask(task)}
                                >
                                  <Pencil className="h-3 w-3" />
                                </Button>
                                {canDeleteAllTodayTask ? (
                                  <Button
                                    variant="outline"
                                    size="icon"
                                    className="h-6 w-6 border-slate-200 text-slate-500 hover:border-rose-200 hover:text-rose-600"
                                    title="Delete"
                                    aria-label={`Delete ${task.title || "system task"}`}
                                    onClick={() => void deleteAllTodayTask(task.id)}
                                    disabled={deletingAllTodayTaskId === task.id}
                                  >
                                    <Trash2 className="h-3 w-3" />
                                  </Button>
                                ) : null}
                              </div>
                            </TableCell>
                          </TableRow>
                        )
                      })}
                    </TableBody>
                  </Table>
                ) : (
                  <div className="mt-3 text-sm text-slate-500">No system tasks for {activeAllRangeTaskLabel}.</div>
                )}
              </Card>

              <Dialog open={Boolean(allTodayEditingTaskId)} onOpenChange={(open) => { if (!open) cancelAllTodayTaskEdit() }}>
                <DialogContent className="flex flex-col overflow-hidden sm:max-w-lg bg-white border-slate-200 rounded-2xl">
                  <DialogHeader className="shrink-0">
                    <DialogTitle className="text-slate-800">Edit Task</DialogTitle>
                  </DialogHeader>
                  <div className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain pr-2">
                    {allTodayEditingTask?.ga_note_origin_id || allTodayEditingTask?.plan_note_origin_id ? (
                      <div className="rounded-xl border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-800">
                        This is your independent note task copy. Edit its status and scheduling here; shared details are managed in {allTodayEditingTask?.plan_note_origin_id ? "PX JAV" : "GA Notes"}.
                      </div>
                    ) : null}
                    {allTodayEditingTask?.plan_note_origin_id ? (
                      <PxJavPlanningBriefView
                        brief={allTodayPlanningDetail?.taskId === allTodayEditingTask.id ? allTodayPlanningDetail.brief : null}
                        loading={allTodayPlanningDetail?.taskId === allTodayEditingTask.id && allTodayPlanningDetail.loading}
                      />
                    ) : null}
                    <div className="space-y-2">
                      <Label className="text-slate-700">Symbol</Label>
                      <TaskOneHMarkerEditor taskId={allTodayEditingTask?.id} marker={allTodayEditingTask?.one_h_marker} markerByGa={allTodayEditingTask?.one_h_marker_by_ga} markerComment={allTodayEditingTask?.one_h_marker_comment} className="w-full max-w-none rounded-xl" />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-slate-700">Title</Label>
                      <Textarea
                        value={allTodayEditTitle}
                        disabled={Boolean(allTodayEditingTask?.ga_note_origin_id || allTodayEditingTask?.plan_note_origin_id)}
                        onChange={(e) => setAllTodayEditTitle(e.target.value)}
                        rows={3}
                        className="h-24 min-h-24 max-h-24 resize-none overflow-y-auto whitespace-pre-wrap [overflow-wrap:anywhere] border-slate-200 focus:border-slate-400 rounded-xl"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-slate-700">Description</Label>
                      {allTodayEditingTask?.ga_note_origin_id || allTodayEditingTask?.plan_note_origin_id ? (
                        <div className="h-32 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
                          {allTodayEditDescription || "—"}
                        </div>
                      ) : (
                        <BoldOnlyEditor
                          value={allTodayEditDescription}
                          onChange={setAllTodayEditDescription}
                          editorClassName="h-32 min-h-32 max-h-32 overflow-y-auto"
                        />
                      )}
                    </div>
                    <div className={isWaitingConfirmation(allTodayEditStatus) ? "grid gap-3 sm:grid-cols-[minmax(0,0.6fr)_minmax(0,1.4fr)_minmax(0,1fr)]" : "grid gap-4 md:grid-cols-2"}>
                      <div className="space-y-2">
                        <Label className="text-slate-700">Type</Label>
                        <Select value={allTodayEditType} onValueChange={(value) => setAllTodayEditType(value as AllTodayEditTypeId)}>
                          <SelectTrigger className="w-full min-w-0 border-slate-200 focus:border-slate-400 rounded-xl [&_[data-slot=select-value]]:min-w-0 [&_[data-slot=select-value]]:truncate">
                            <SelectValue placeholder="Select type" />
                          </SelectTrigger>
                          <SelectContent>
                            {(hasProjectId(allTodayEditingTask?.project_id) ? PROJECT_ALL_TODAY_TYPES : NO_PROJECT_TYPES).map((option) => (
                              <SelectItem key={option.id} value={option.id}>
                                {option.label}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <div className="text-xs text-slate-500">
                          {(hasProjectId(allTodayEditingTask?.project_id) ? PROJECT_ALL_TODAY_TYPES : NO_PROJECT_TYPES).find((option) => option.id === allTodayEditType)?.description}
                        </div>
                      </div>
                      <div className="space-y-2">
                        <Label className="text-slate-700">Status</Label>
                        <Select value={allTodayEditStatus} onValueChange={setAllTodayEditStatus}>
                          <SelectTrigger className="w-full min-w-0 border-slate-200 focus:border-slate-400 rounded-xl [&_[data-slot=select-value]]:min-w-0 [&_[data-slot=select-value]]:truncate">
                            <SelectValue placeholder="Select status" />
                          </SelectTrigger>
                          <SelectContent>
                            {ALL_TODAY_TASK_STATUS_OPTIONS.map((value) => (
                              <SelectItem key={value} value={value}>
                                {reportStatusLabel(value)}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>

                      {isWaitingConfirmation(allTodayEditStatus) ? (
                        <div className="space-y-2">
                          <Label className="text-slate-700" title="Manager/Admin/GA">Confirm by</Label>
                          <Select
                            value={allTodayEditConfirmationAssigneeId || "__none__"}
                            onValueChange={(value) =>
                              setAllTodayEditConfirmationAssigneeId(value === "__none__" ? "" : value)
                            }
                          >
                            <SelectTrigger className="w-full min-w-0 border-slate-200 focus:border-slate-400 rounded-xl [&_[data-slot=select-value]]:min-w-0 [&_[data-slot=select-value]]:truncate">
                              <SelectValue placeholder="Select confirmer" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="__none__">Select confirmer</SelectItem>
                              {confirmerCandidates.map((candidate) => (
                                <SelectItem key={candidate.id} value={candidate.id}>
                                  {candidate.full_name || candidate.username || "-"}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                      ) : null}
                    </div>
                    <div
                      className={cn(
                        "space-y-2 rounded-xl border p-3",
                        allTodayCompletingRlzTask
                          ? allTodayUsesCompletionOverride
                            ? "border-amber-300 bg-amber-50"
                            : "border-blue-300 bg-blue-50"
                          : "border-slate-200 bg-slate-50"
                      )}
                    >
                      <Label className="text-slate-800">
                        {allTodayUsesCompletionOverride ? "Reason for closing this task" : "Result comment"}
                        {allTodayCompletingRlzTask ? <span className="ml-1 text-rose-600">*</span> : null}
                      </Label>
                      <Textarea
                        value={allTodayEditCompletionNote}
                        onChange={(event) => setAllTodayEditCompletionNote(event.target.value)}
                        rows={3}
                        placeholder={
                          allTodayUsesCompletionOverride
                            ? "Explain why you are closing it for the assignee..."
                            : "Briefly write what was completed..."
                        }
                        className="min-h-20 resize-y border-slate-200 bg-white"
                      />
                      <p className="text-xs text-slate-600">
                        {allTodayUsesCompletionOverride
                          ? "Required when closing another user's task; saved in the audit log."
                          : allTodayCompletingRlzTask
                            ? "Required for Done. The comment is saved before the task is closed."
                            : "Optional now; it becomes required when Status is Done."}
                      </p>
                    </div>
                    <div className="grid gap-4 md:grid-cols-2">
                      <div className="space-y-2">
                        <Label className="text-slate-700">Finish by (optional)</Label>
                        <Select
                          value={allTodayEditFinishPeriod}
                          onValueChange={(value) =>
                            setAllTodayEditFinishPeriod(value as TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE)
                          }
                        >
                          <SelectTrigger className="border-slate-200 focus:border-slate-400 rounded-xl">
                            <SelectValue placeholder="Select period" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value={FINISH_PERIOD_NONE_VALUE}>{FINISH_PERIOD_NONE_LABEL}</SelectItem>
                            {FINISH_PERIOD_OPTIONS.map((value) => (
                              <SelectItem key={value} value={value}>
                                {value}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-2">
                        <Label className="text-slate-700">Start date</Label>
                        <Input
                          type="date"
                          value={allTodayEditStartDate}
                          onChange={(e) => setAllTodayEditStartDate(normalizeDueDateInput(e.target.value))}
                          className="border-slate-200 focus:border-slate-400 rounded-xl w-full"
                        />
                      </div>
                      <div className="space-y-2">
                        <Label className="text-slate-700">Due date (optional)</Label>
                        <Input
                          type="date"
                          value={allTodayEditDueDate}
                          onChange={(e) => setAllTodayEditDueDate(normalizeDueDateInput(e.target.value))}
                          className="border-slate-200 focus:border-slate-400 rounded-xl w-full"
                        />
                      </div>
                    </div>
                    <label className="flex items-center gap-3 rounded-xl border border-slate-200 px-3 py-2">
                      <Checkbox
                        checked={allTodayEditDeadlineImportant}
                        onCheckedChange={(checked) => setAllTodayEditDeadlineImportant(checked === true)}
                      />
                      <span className="text-sm font-medium text-slate-700">Deadline important</span>
                    </label>
                  </div>
                    <div className="flex shrink-0 justify-end gap-2 border-t pt-4">
                      <Button variant="outline" onClick={cancelAllTodayTaskEdit} className="rounded-xl border-slate-200">
                        Cancel
                      </Button>
                      <Button
                        disabled={
                          (!(allTodayEditingTask?.ga_note_origin_id || allTodayEditingTask?.plan_note_origin_id) && !allTodayEditTitle.trim()) ||
                          !allTodayEditStatus ||
                          allTodayUpdating ||
                          (allTodayCompletingRlzTask && !allTodayEditCompletionNote.trim()) ||
                          (!(allTodayEditingTask?.ga_note_origin_id || allTodayEditingTask?.plan_note_origin_id) && isWaitingConfirmation(allTodayEditStatus) && !allTodayEditConfirmationAssigneeId) ||
                          !canEditAllTodayTask(allTodayEditingTask)
                        }
                        onClick={() => void updateAllTodayTask()}
                        className="bg-blue-500 hover:bg-blue-600 text-white border-0 shadow-sm rounded-xl"
                      >
                        {allTodayUpdating ? "Updating..." : "Update"}
                      </Button>
                    </div>

                </DialogContent>
              </Dialog>

            </div>
          </div>
        ) : null}

        {activeTab === "system" ? (
          <div className="space-y-4 sm:space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
              <div>
                <div className="text-lg sm:text-xl font-semibold text-slate-900 pt-4">System Tasks</div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <div className="inline-flex rounded-full border border-slate-200 bg-white p-1 shadow-sm">
                {[
                  { label: "Today", offset: 0 },
                  { label: "Yesterday", offset: -1 },
                  { label: "Tomorrow", offset: 1 },
                ].map((opt) => {
                  const target = new Date()
                  target.setDate(target.getDate() + opt.offset)
                  const active =
                    target.toDateString() === systemDate.toDateString()
                  return (
                    <button
                      key={opt.label}
                      type="button"
                      onClick={() => setSystemDate(target)}
                      className={[
                        "rounded-full px-4 py-2 text-sm font-medium transition-colors",
                        active
                          ? "bg-foreground text-background shadow-sm"
                          : "text-muted-foreground hover:text-foreground",
                      ].join(" ")}
                    >
                      {opt.label}
                    </button>
                  )
                })}
              </div>
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Checkbox checked={multiSelect} onCheckedChange={(v) => setMultiSelect(Boolean(v))} />
                <span>Multi-select</span>
              </div>
              <div className="flex items-center gap-2 rounded-xl border border-border bg-background px-3 py-1.5">
                <Input
                  type="date"
                  className="h-9 w-40 border-0 bg-transparent p-0 shadow-none focus-visible:ring-0"
                  value={formatDateInput(systemDate)}
                  onChange={(e) => setSystemDate(new Date(e.target.value))}
                />
                <div className="h-5 w-px bg-border" />
                <Button variant="outline" size="sm" onClick={() => setShowAllSystem((prev) => !prev)}>
                  {showAllSystem ? "Only date" : "Show all"}
                </Button>
              </div>
            </div>

            <div className="relative w-full rounded-lg border bg-white shadow-sm">
              <div className="overflow-x-auto">
                <div className="min-w-[1000px] xl:min-w-0">
                  <div className="sticky top-0 z-30">
                    <div className="border-b bg-slate-50/95 backdrop-blur py-3 px-4">
                      <div className={GRID_CLASS + " text-[11px] font-bold uppercase tracking-wider text-slate-500"}>
                        <div>No.</div>
                        <div>Task Title</div>
                        <div>Department</div>
                        <div>Owner</div>
                        <div>Frequency</div>
                        <div>Start Date</div>
                        <div>Due Date</div>
                        <div>Finish by</div>
                        <div>Priority</div>
                        <div className="text-right">Actions</div>
                      </div>
                    </div>
                  </div>

                  <div className="p-4 space-y-2 bg-slate-50">
                    {sortedSystemTasks.length ? (
                      (() => {
                        let globalIndex = 0
                        return sortedSystemTasks.map((template) => {
                          const taskNumber = globalIndex + 1
                          globalIndex++
                          const priorityValue = normalizePriority(template.priority)
                          const departmentLabel = systemTaskDepartmentLabel(template, departmentMap, userMap)
                          const ownerLabel = assigneeSummary(template.assignees) ||
                            (template.default_assignee_id ? users.find((u) => u.id === template.default_assignee_id)?.full_name || users.find((u) => u.id === template.default_assignee_id)?.username || "-" : "-")
                          const frequencyLabel = FREQUENCY_LABELS[template.frequency] || template.frequency
                          const statusValue = template.status || "TODO"
                          const isClosed = statusValue === "DONE"
                          const isOverdue = isSystemTaskOverdueForDate(template, systemDate)
                          const isAssigned =
                            Boolean(user?.id) &&
                            (template.default_assignee_id === user?.id ||
                              template.assignees?.some((assignee) => assignee.id === user?.id))
                          const canEditSystemDate = canEditSystemDateRow(template, statusValue)
                          const isInactive = template.is_active === false

                          return (
                            <div
                              key={template.id}
                              className={[
                                GRID_CLASS,
                                "py-3 bg-white border border-slate-200 border-l-4 transition-colors hover:bg-slate-50",
                                PRIORITY_BORDER_STYLES[priorityValue],
                                isInactive && "opacity-60 grayscale"
                              ].join(" ")}
                            >
                              <div className="text-sm font-semibold text-slate-600">
                                {taskNumber}
                              </div>
                              <div className="min-w-0 pr-4">
                                <div className="flex flex-wrap items-center gap-2">
                                  <div className="text-[15px] font-semibold leading-tight text-slate-900 break-words" title={template.title}>
                                    {template.title}
                                  </div>
                                  {isOverdue ? (
                                    <Badge variant="outline" className="h-5 text-[10px] uppercase bg-rose-100 text-rose-700 border-rose-200">
                                      Late
                                    </Badge>
                                  ) : null}
                                  <Badge variant="secondary" className="h-5 text-[10px] uppercase">
                                    {statusValue}
                                  </Badge>
                                </div>
                              </div>
                              <div className="truncate text-sm text-slate-700 font-normal" title={departmentLabel}>
                                {departmentLabel}
                              </div>
                              <div className="truncate text-sm text-slate-700 font-normal" title={ownerLabel !== "-" ? ownerLabel : ""}>
                                {ownerLabel === "-" ? <span className="text-slate-400">-</span> : ownerLabel}
                              </div>
                              <div>
                                <span className="text-sm text-slate-700 font-normal">
                                  {frequencyLabel}
                                </span>
                              </div>
                              <div className="text-sm text-slate-700 font-normal">
                                {formatDateOnly(systemTaskStartDate(template))}
                              </div>
                              <div className="text-sm text-slate-700 font-normal">
                                {formatDateOnly(systemTaskDisplayDate(template))}
                              </div>
                              <div className="text-sm text-slate-700 font-normal">
                                {template.finish_period || "-"}
                              </div>
                              <div>
                                <Badge
                                  variant="outline"
                                  className={["px-2 py-0.5 text-[13px] border", PRIORITY_BADGE_STYLES[priorityValue]].join(" ")}
                                >
                                  {PRIORITY_LABELS[priorityValue]}
                                </Badge>
                              </div>
                              <div className="text-right">
                                <div className="flex flex-col items-end gap-2">
                                  {canEditSystemDate ? (
                                    <Button
                                      variant="outline"
                                      size="sm"
                                      disabled={savingSystemDateOverride}
                                      onClick={() => openSystemDateEditor(template, statusValue)}
                                      className="h-7 text-xs"
                                    >
                                      Edit date
                                    </Button>
                                  ) : null}
                                  {showSystemActions && isAssigned && !isClosed && (
                                    <Button
                                      variant="outline"
                                      size="sm"
                                      disabled={closingTask}
                                      onClick={() => handleCloseTaskClick(template)}
                                      className="h-7 text-xs"
                                    >
                                      {closingTask ? "Updating..." : "Mark done"}
                                    </Button>
                                  )}
                                  {isClosed && (
                                    <span className="text-xs text-emerald-700">Done</span>
                                  )}
                                </div>
                              </div>
                            </div>
                          )
                        })
                      })()
                    ) : (
                      <div className="py-12 text-center text-sm text-muted-foreground">
                        No system tasks yet.
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : null}

        <Dialog open={Boolean(editingSystemTaskId)} onOpenChange={(open) => { if (!open) closeSystemDateEditor() }}>
          <DialogContent className="sm:max-w-lg bg-white border-slate-200 rounded-2xl">
            <DialogHeader>
              <DialogTitle className="text-slate-800">Edit System Task Date</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              <div className="text-sm text-slate-600">{editingSystemDateTitle}</div>
              <div className="space-y-2">
                <Label className="text-slate-700">Current due date</Label>
                <Input type="date" value={editingSystemDateSource} disabled className="border-slate-200 rounded-xl w-full bg-slate-50" />
              </div>
              <div className="space-y-2">
                <Label className="text-slate-700">New due date</Label>
                <Input
                  type="date"
                  value={editingSystemDateTarget}
                  onChange={(e) => setEditingSystemDateTarget(normalizeDueDateInput(e.target.value))}
                  className="border-slate-200 focus:border-slate-400 rounded-xl w-full"
                />
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={closeSystemDateEditor} className="rounded-xl border-slate-200">
                  Cancel
                </Button>
                <Button
                  disabled={!editingSystemDateTarget || savingSystemDateOverride}
                  onClick={() => void saveSystemDateOverride()}
                  className="bg-blue-500 hover:bg-blue-600 text-white border-0 shadow-sm rounded-xl"
                >
                  {savingSystemDateOverride ? "Saving..." : "Save"}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>

        {/* Dialog for closing task with optional comment */}
        <Dialog open={closeTaskDialogOpen} onOpenChange={setCloseTaskDialogOpen}>
          <DialogContent className="flex flex-col overflow-hidden sm:max-w-lg">
            <DialogHeader className="shrink-0">
              <DialogTitle>Close System Task</DialogTitle>
            </DialogHeader>
            <div className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain pr-2">
              <div className="space-y-2">
                <Label htmlFor="close-task-comment">
                  Employee Comment
                </Label>
                <Textarea
                  id="close-task-comment"
                  value={closeTaskComment}
                  onChange={(e) => setCloseTaskComment(e.target.value)}
                  placeholder="Describe what was done in this task..."
                  className="h-32 min-h-32 max-h-32 resize-none overflow-y-auto"
                />
              </div>
            </div>
              <div className="flex shrink-0 justify-end gap-2 border-t pt-4">
                <Button
                  variant="outline"
                  onClick={() => {
                    setCloseTaskDialogOpen(false)
                    setTaskToCloseId(null)
                    setCloseTaskComment("")
                  }}
                  disabled={closingTask}
                >
                  Cancel
                </Button>
                <Button
                  onClick={() => void confirmCloseTask()}
                  disabled={closingTask || !closeTaskComment.trim()}
                  className="bg-emerald-600 hover:bg-emerald-700"
                >
                  {closingTask ? "Closing..." : "Close Task"}
                </Button>
              </div>

          </DialogContent>
        </Dialog>

        {activeTab === "no-project" ? (
          <div className="space-y-4 sm:space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
              <div>
                <div className="text-lg sm:text-xl font-semibold text-slate-900 pt-4">Fast Tasks</div>
              </div>
              <div className="flex w-full flex-col gap-3 sm:w-auto sm:flex-row sm:items-end">
                <div className="w-full sm:w-[180px]">
                  <Label htmlFor="fast-task-date" className="mb-2 block text-xs font-medium uppercase tracking-wide text-slate-500">
                    Date
                  </Label>
                  <Input
                    id="fast-task-date"
                    type="date"
                    value={fastTaskDateInput}
                    onChange={(e) => {
                      setShowAllFastTasks(false)
                      setFastTaskDateInput(e.target.value || todayInputValue())
                    }}
                    className="border-slate-200 focus:border-slate-400 rounded-xl w-full"
                  />
                </div>
                <div className="flex gap-2 sm:pb-0.5">
                  <Button
                    type="button"
                    variant={showAllFastTasks ? "outline" : "default"}
                    onClick={() => {
                      setShowAllFastTasks(false)
                      setFastTaskDateInput(todayInputValue())
                    }}
                    className="rounded-xl"
                  >
                    Today
                  </Button>
                  <Button
                    type="button"
                    variant={showAllFastTasks ? "default" : "outline"}
                    onClick={() => setShowAllFastTasks(true)}
                    className="rounded-xl"
                  >
                    All
                  </Button>
                </div>
                {canCreateNoProjectTask ? (
                  <Dialog open={noProjectOpen} onOpenChange={setNoProjectOpen}>
                    <DialogTrigger asChild>
                      <Button className="bg-blue-500 hover:bg-blue-600 text-white border-0 shadow-sm rounded-xl px-4 sm:px-6 w-full sm:w-auto">
                        + Add Task
                      </Button>
                    </DialogTrigger>
                    <DialogContent className="flex flex-col overflow-hidden sm:max-w-lg bg-white border-slate-200 rounded-2xl">
                      <DialogHeader className="shrink-0">
                        <DialogTitle className="text-slate-800">New Task</DialogTitle>
                      </DialogHeader>
                      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain pr-2">
                        <div className="space-y-2">
                          <Label className="text-slate-700">Type</Label>
                          <Select value={noProjectType} onValueChange={(v) => setNoProjectType(v as typeof noProjectType)}>
                            <SelectTrigger className="border-slate-200 focus:border-slate-400 rounded-xl">
                              <SelectValue placeholder="Select type" />
                            </SelectTrigger>
                            <SelectContent>
                              {NO_PROJECT_TYPES.map((opt) => (
                                <SelectItem key={opt.id} value={opt.id}>
                                  {opt.label}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <div className="text-xs text-slate-500">
                            {NO_PROJECT_TYPES.find((opt) => opt.id === noProjectType)?.description}
                          </div>
                        </div>
                        <div className="space-y-2">
                          <Label className="text-slate-700">Title</Label>
                          <Input value={noProjectTitle} onChange={(e) => setNoProjectTitle(e.target.value)} className="border-slate-200 focus:border-slate-400 rounded-xl" />
                        </div>
                        <div className="space-y-2">
                          <Label className="text-slate-700">Description</Label>
                          <BoldOnlyEditor value={noProjectDescription} onChange={setNoProjectDescription} editorClassName="h-32 min-h-32 max-h-32 overflow-y-auto [overflow-wrap:anywhere]" />
                        </div>
                        <div className="grid gap-4 md:grid-cols-2">
                          <div className="space-y-2">
                            <Label className="text-slate-700">Assign to</Label>
                            <Dialog open={selectNoProjectAssigneesOpen} onOpenChange={setSelectNoProjectAssigneesOpen}>
                              <DialogTrigger asChild>
                                <Button
                                  type="button"
                                  variant="outline"
                                  className="w-full justify-start border-slate-200 focus:border-slate-400 rounded-xl"
                                >
                                  {noProjectAssigneeLabel}
                                </Button>
                              </DialogTrigger>
                              <DialogContent className="sm:max-w-md z-[110]">
                                <DialogHeader>
                                  <DialogTitle>Select Assignees</DialogTitle>
                                </DialogHeader>
                                <div className="mt-4 max-h-[400px] overflow-y-auto space-y-2">
                                  {users.length ? (
                                    users.map((u) => {
                                      const isSelected = noProjectAssignees.includes(u.id)
                                      return (
                                        <div
                                          key={u.id}
                                          className="flex items-center space-x-2 p-2 rounded-lg hover:bg-slate-50 cursor-pointer"
                                          onClick={() => {
                                            if (isSelected) {
                                              setNoProjectAssignees((prev) => prev.filter((id) => id !== u.id))
                                            } else {
                                              setNoProjectAssignees((prev) => [...prev, u.id])
                                            }
                                          }}
                                        >
                                          <Checkbox checked={isSelected} />
                                          <Label className="cursor-pointer flex-1">
                                            {u.full_name || u.username || "-"}
                                          </Label>
                                        </div>
                                      )
                                    })
                                  ) : (
                                    <div className="text-sm text-slate-600">No users available.</div>
                                  )}
                                </div>
                                <div className="mt-4 flex justify-end gap-2">
                                  <Button variant="outline" onClick={() => setNoProjectAssignees([])}>
                                    Clear
                                  </Button>
                                  <Button
                                    variant="outline"
                                    onClick={() => setNoProjectAssignees(users.map((u) => u.id))}
                                    disabled={!users.length}
                                  >
                                    All users
                                  </Button>
                                  <Button onClick={() => setSelectNoProjectAssigneesOpen(false)}>
                                    Done
                                  </Button>
                                </div>
                              </DialogContent>
                            </Dialog>
                          </div>
                          <div className="space-y-2">
                            <Label className="text-slate-700">Finish by (optional)</Label>
                            <Select
                              value={noProjectFinishPeriod}
                              onValueChange={(value) =>
                                setNoProjectFinishPeriod(value as TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE)
                              }
                            >
                              <SelectTrigger className="border-slate-200 focus:border-slate-400 rounded-xl">
                                <SelectValue placeholder="Select period" />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value={FINISH_PERIOD_NONE_VALUE}>{FINISH_PERIOD_NONE_LABEL}</SelectItem>
                                {FINISH_PERIOD_OPTIONS.map((value) => (
                                  <SelectItem key={value} value={value}>
                                    {value}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                          <div className="space-y-2">
                            <Label className="text-slate-700">Start date</Label>
                            <Input
                              type="date"
                              required
                              value={noProjectStartDate}
                              onChange={(e) => setNoProjectStartDate(normalizeDueDateInput(e.target.value))}
                              className="border-slate-200 focus:border-slate-400 rounded-xl w-full"
                            />
                          </div>
                          <div className="space-y-2">
                            <Label className="text-slate-700">Due date (optional)</Label>
                            <Input
                              type="date"
                              value={noProjectDueDate}
                              onChange={(e) => setNoProjectDueDate(normalizeDueDateInput(e.target.value))}
                              className="border-slate-200 focus:border-slate-400 rounded-xl w-full"
                            />
                          </div>
                        </div>
                        <label className="flex items-center gap-3 rounded-xl border border-slate-200 px-3 py-2">
                          <Checkbox
                            checked={noProjectDeadlineImportant}
                            onCheckedChange={(checked) => setNoProjectDeadlineImportant(checked === true)}
                          />
                          <span className="text-sm font-medium text-slate-700">Deadline important</span>
                        </label>
                      </div>
                        <div className="flex shrink-0 justify-end gap-2 border-t pt-4">
                          <Button variant="outline" onClick={() => setNoProjectOpen(false)} className="rounded-xl border-slate-200">
                            Cancel
                          </Button>
                          <Button
                            disabled={!noProjectTitle.trim() || !noProjectStartDate || creatingNoProject}
                            onClick={() => void submitNoProjectTask()}
                            className="bg-blue-500 hover:bg-blue-600 text-white border-0 shadow-sm rounded-xl"
                          >
                            {creatingNoProject ? "Creating..." : "Create"}
                          </Button>
                        </div>

                    </DialogContent>
                  </Dialog>
                ) : null}
              </div>
              {canOpenNoProjectEditDialog ? (
                <Dialog open={Boolean(editingTaskId)} onOpenChange={(open) => { if (!open) cancelEditTask() }}>
                  <DialogContent className="flex flex-col overflow-hidden sm:max-w-lg bg-white border-slate-200 rounded-2xl">
                    <DialogHeader className="shrink-0">
                      <DialogTitle className="text-slate-800">Edit Task</DialogTitle>
                    </DialogHeader>
                    <div className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain pr-2">
                      {editingGaTask ? (
                        <div className="rounded-xl border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-800">
                          This is an independent note task copy. Edit its status and scheduling here; shared details are managed in {editingPlanTask ? "PX JAV" : "GA Notes"}.
                        </div>
                        ) : null}
                        <div className="space-y-2">
                          <Label className="text-slate-700">Symbol</Label>
                          <TaskOneHMarkerEditor taskId={editingNoProjectTask?.id} marker={editingNoProjectTask?.one_h_marker} markerByGa={editingNoProjectTask?.one_h_marker_by_ga} markerComment={editingNoProjectTask?.one_h_marker_comment} className="w-full max-w-none rounded-xl" />
                        </div>
                        <div className="space-y-2">
                        <Label className="text-slate-700">Title</Label>
                        <Textarea
                          value={editTaskTitle}
                          disabled={editingGaTask}
                          onChange={(e) => setEditTaskTitle(e.target.value)}
                          rows={3}
                          className="h-24 min-h-24 max-h-24 overflow-y-auto resize-none whitespace-pre-wrap [overflow-wrap:anywhere] border-slate-200 focus:border-slate-400 rounded-xl"
                        />
                      </div>
                      <div className="space-y-2">
                        <Label className="text-slate-700">Description</Label>
                        {editingGaTask ? (
                          <div className="h-32 overflow-y-auto whitespace-pre-wrap [overflow-wrap:anywhere] rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
                            {editTaskDescription || "—"}
                          </div>
                        ) : (
                          <BoldOnlyEditor value={editTaskDescription} onChange={setEditTaskDescription} editorClassName="h-32 min-h-32 max-h-32 overflow-y-auto [overflow-wrap:anywhere]" />
                        )}
                      </div>
                      <div className={isWaitingConfirmation(editTaskStatus) ? "grid gap-3 sm:grid-cols-[minmax(0,0.6fr)_minmax(0,1.4fr)_minmax(0,1fr)]" : "grid gap-4 md:grid-cols-2"}>
                        <div className="space-y-2">
                          <Label className="text-slate-700">Type</Label>
                          <Select value={editTaskType} onValueChange={(value) => setEditTaskType(value as typeof editTaskType)}>
                            <SelectTrigger className="w-full min-w-0 border-slate-200 focus:border-slate-400 rounded-xl [&_[data-slot=select-value]]:min-w-0 [&_[data-slot=select-value]]:truncate">
                              <SelectValue placeholder="Select type" />
                            </SelectTrigger>
                            <SelectContent>
                              {NO_PROJECT_TYPES.map((opt) => (
                                <SelectItem key={opt.id} value={opt.id}>
                                  {opt.label}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <div className="text-xs text-slate-500">
                            {NO_PROJECT_TYPES.find((opt) => opt.id === editTaskType)?.description}
                          </div>
                        </div>
                        <div className="space-y-2">
                          <Label className="text-slate-700">Status</Label>
                          <Select value={editTaskStatus} onValueChange={setEditTaskStatus}>
                            <SelectTrigger className="w-full min-w-0 border-slate-200 focus:border-slate-400 rounded-xl [&_[data-slot=select-value]]:min-w-0 [&_[data-slot=select-value]]:truncate">
                              <SelectValue placeholder="Select status" />
                            </SelectTrigger>
                            <SelectContent>
                              {ALL_TODAY_TASK_STATUS_OPTIONS.map((value) => (
                                <SelectItem key={value} value={value}>
                                  {reportStatusLabel(value)}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>

                        {isWaitingConfirmation(editTaskStatus) ? (
                          <div className="space-y-2">
                            <Label className="text-slate-700" title="Manager/Admin/GA">Confirm by</Label>
                            <Select
                              value={editTaskConfirmationAssigneeId || "__none__"}
                              onValueChange={(value) => setEditTaskConfirmationAssigneeId(value === "__none__" ? "" : value)}
                            >
                              <SelectTrigger className="w-full min-w-0 border-slate-200 focus:border-slate-400 rounded-xl [&_[data-slot=select-value]]:min-w-0 [&_[data-slot=select-value]]:truncate">
                                <SelectValue placeholder="Select confirmer" />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="__none__">Select confirmer</SelectItem>
                                {confirmerCandidates.map((candidate) => (
                                  <SelectItem key={candidate.id} value={candidate.id}>
                                    {candidate.full_name || candidate.username || "-"}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                        ) : null}
                      </div>
                      <div className="grid gap-4 md:grid-cols-2">
                        <div className="space-y-2">
                          <Label className="text-slate-700">Finish by (optional)</Label>
                          <Select
                            value={editTaskFinishPeriod}
                            onValueChange={(value) =>
                              setEditTaskFinishPeriod(value as TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE)
                            }
                          >
                            <SelectTrigger className="border-slate-200 focus:border-slate-400 rounded-xl">
                              <SelectValue placeholder="Select period" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value={FINISH_PERIOD_NONE_VALUE}>{FINISH_PERIOD_NONE_LABEL}</SelectItem>
                              {FINISH_PERIOD_OPTIONS.map((value) => (
                                <SelectItem key={value} value={value}>
                                  {value}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                        <div className="space-y-2">
                          <Label className="text-slate-700">Start date</Label>
                          <Input
                            type="date"
                            required
                            value={editTaskStartDate}
                            onChange={(e) => setEditTaskStartDate(normalizeDueDateInput(e.target.value))}
                            className="border-slate-200 focus:border-slate-400 rounded-xl w-full"
                          />
                        </div>
                        <div className="space-y-2">
                          <Label className="text-slate-700">Due date (optional)</Label>
                          <Input
                            type="date"
                            value={editTaskDueDate}
                            onChange={(e) => setEditTaskDueDate(normalizeDueDateInput(e.target.value))}
                            className="border-slate-200 focus:border-slate-400 rounded-xl w-full"
                          />
                        </div>
                      </div>
                      <label className="flex items-center gap-3 rounded-xl border border-slate-200 px-3 py-2">
                        <Checkbox
                          checked={editTaskDeadlineImportant}
                          onCheckedChange={(checked) => setEditTaskDeadlineImportant(checked === true)}
                        />
                        <span className="text-sm font-medium text-slate-700">Deadline important</span>
                      </label>
                      <div className="space-y-2">
                        <Label className="text-slate-700">Assign to</Label>
                        <Dialog open={selectEditTaskAssigneesOpen} onOpenChange={setSelectEditTaskAssigneesOpen}>
                          <DialogTrigger asChild>
                            <Button
                              type="button"
                              variant="outline"
                              className="w-full justify-start border-slate-200 focus:border-slate-400 rounded-xl"
                            >
                              {editTaskAssigneeLabel}
                            </Button>
                          </DialogTrigger>
                          <DialogContent className="sm:max-w-md z-[110]">
                            <DialogHeader>
                              <DialogTitle>Select Assignees</DialogTitle>
                            </DialogHeader>
                            <div className="mt-4 max-h-[400px] overflow-y-auto space-y-2">
                              {users.length ? (
                                users.map((u) => {
                                  const isSelected = editTaskAssignees.includes(u.id)
                                  return (
                                    <div
                                      key={u.id}
                                      className="flex items-center space-x-2 p-2 rounded-lg hover:bg-slate-50 cursor-pointer"
                                      onClick={() => {
                                        if (isSelected) {
                                          setEditTaskAssignees((prev) => prev.filter((id) => id !== u.id))
                                        } else {
                                          setEditTaskAssignees((prev) => [...prev, u.id])
                                        }
                                      }}
                                    >
                                      <Checkbox checked={isSelected} />
                                      <Label className="cursor-pointer flex-1">
                                        {u.full_name || u.username || "-"}
                                      </Label>
                                    </div>
                                  )
                                })
                              ) : (
                                <div className="text-sm text-slate-600">No users available.</div>
                              )}
                            </div>
                            <div className="mt-4 flex justify-end gap-2">
                              <Button variant="outline" onClick={() => setEditTaskAssignees([])}>
                                Clear
                              </Button>
                              <Button
                                variant="outline"
                                onClick={() => setEditTaskAssignees(users.map((u) => u.id))}
                                disabled={!users.length}
                              >
                                All users
                              </Button>
                              <Button onClick={() => setSelectEditTaskAssigneesOpen(false)}>
                                Done
                              </Button>
                            </div>
                          </DialogContent>
                        </Dialog>
                      </div>
                    </div>
                      <div className="flex shrink-0 justify-end gap-2 border-t pt-4">
                        <Button variant="outline" onClick={cancelEditTask} className="rounded-xl border-slate-200">
                          Cancel
                        </Button>
                        <Button
                          disabled={!editTaskTitle.trim() || !editTaskStartDate || updatingTask}
                          onClick={() => void updateNoProjectTask()}
                          className="bg-blue-500 hover:bg-blue-600 text-white border-0 shadow-sm rounded-xl"
                        >
                          {updatingTask ? "Updating..." : "Update"}
                        </Button>
                      </div>

                  </DialogContent>
                </Dialog>
              ) : null}
              <Dialog
                open={internalMeetingTaskDialogOpen}
                onOpenChange={(open) => {
                  if (!open) closeInternalMeetingTaskDialog()
                }}
              >
                <DialogContent className="sm:max-w-md bg-white border-slate-200 rounded-2xl">
                  <DialogHeader>
                    <DialogTitle className="text-slate-800">Create Internal Meeting</DialogTitle>
                  </DialogHeader>
                  <div className="space-y-4">
                    <div className="space-y-2">
                      <Label className="text-slate-700">Meeting title</Label>
                      <Input
                        value={internalMeetingTaskTitle}
                        onChange={(e) => setInternalMeetingTaskTitle(e.target.value)}
                        className="border-slate-200 focus:border-slate-400 rounded-xl"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-slate-700">Platform</Label>
                      <Input
                        value={internalMeetingTaskPlatform}
                        onChange={(e) => setInternalMeetingTaskPlatform(e.target.value)}
                        placeholder="Zoom, Meet, Office..."
                        className="border-slate-200 focus:border-slate-400 rounded-xl"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-slate-700">Date and time</Label>
                      <Input
                        type="datetime-local"
                        value={internalMeetingTaskStartsAt}
                        onChange={(e) => setInternalMeetingTaskStartsAt(e.target.value)}
                        className="border-slate-200 focus:border-slate-400 rounded-xl"
                      />
                    </div>
                    <div className="flex justify-end gap-2">
                      <Button variant="outline" onClick={closeInternalMeetingTaskDialog} className="rounded-xl border-slate-200">
                        Cancel
                      </Button>
                      <Button
                        disabled={!internalMeetingTaskTitle.trim() || creatingInternalMeetingFromTask}
                        onClick={() => void submitInternalMeetingFromTask()}
                        className="bg-blue-500 hover:bg-blue-600 text-white border-0 shadow-sm rounded-xl"
                      >
                        {creatingInternalMeetingFromTask ? "Creating..." : "Create"}
                      </Button>
                    </div>
                  </div>
                </DialogContent>
              </Dialog>
            </div>
            <div className="space-y-4">
              {statusRows.map((row) => (
                <div
                  key={row.id}
                  className="rounded-2xl border border-slate-200 bg-white p-2"
                >
                  <div className="flex items-center justify-between gap-2 px-1">
                    <div className="flex items-center gap-2">
                      <div className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${row.itemBadgeClass}`}>
                        {row.title}
                      </div>
                      <span className="text-[11px] text-slate-500">
                        {row.items.length ? "Active items" : "No items"}
                      </span>
                    </div>
                    <span className={`rounded-full px-1.5 py-0 text-[11px] font-semibold ${row.badgeClass}`}>
                      {row.count}
                    </span>
                  </div>
                  <div className="mt-2 flex flex-col max-h-[300px] overflow-y-auto">
                    {row.items.length ? (
                      <div className="flex flex-col gap-2">
                        <div className="hidden sm:grid sm:gap-0 sm:divide-x sm:divide-slate-200 sm:grid-cols-[36px_minmax(0,3.2fr)_minmax(0,0.45fr)_100px_minmax(0,0.75fr)_minmax(0,0.55fr)_minmax(0,0.45fr)_minmax(0,0.65fr)_minmax(0,0.65fr)_minmax(0,0.55fr)] px-2 py-1 border border-slate-200 rounded-md bg-slate-50 text-[10px] uppercase tracking-wide text-slate-400 font-semibold">
                          <div className="sm:px-2 text-center">Nr</div>
                          <div className="sm:px-3">Title</div>
                          <div className="sm:px-3">GA</div>
                          <div className="sm:px-3 text-center">Symbol</div>
                          <div className="sm:px-3">Status</div>
                          <div className="sm:px-3">Type</div>
                          <div className="sm:px-3">Assignees</div>
                          <div className="sm:px-3">Start</div>
                          <div className="sm:px-3">Due</div>
                          <div className="sm:px-3 text-right">Actions</div>
                        </div>
                        {row.items.map((t, index) => {
                          const statusValue = taskStatusValue(t)
                          const isCompleted = statusValue === "DONE"
                          const startsOnSelectedDay = isTaskStartingOnSelectedAllDate(t)
                          const dueOnSelectedDay = isTaskDueOnSelectedAllDate(t)
                          return (
                            <Link
                              key={t.id}
                              id={`task-${t.id}`}
                              href={`/tasks/${t.id}?returnTo=${encodeURIComponent(`${returnToTasks}#task-${t.id}`)}`}
                              className={`block rounded-lg border border-slate-200 border-l-4 px-2 py-2 text-sm transition hover:bg-slate-50 ${dueOnSelectedDay
                                ? DUE_ON_SELECTED_DAY_TASK_CARD_CLASS
                                : startsOnSelectedDay
                                ? STARTS_ON_SELECTED_DAY_TASK_CARD_CLASS
                                : isCompleted
                                ? "border-green-500 bg-green-50/30 opacity-75"
                                : `${row.borderClass} bg-white`
                                }`}
                            >
                                  <div className={`grid gap-2 sm:gap-0 sm:grid-cols-[36px_minmax(0,3.2fr)_minmax(0,0.45fr)_100px_minmax(0,0.75fr)_minmax(0,0.55fr)_minmax(0,0.45fr)_minmax(0,0.65fr)_minmax(0,0.65fr)_minmax(0,0.55fr)] sm:divide-x ${dueOnSelectedDay ? "sm:divide-red-600" : startsOnSelectedDay ? "sm:divide-blue-600" : "sm:divide-slate-200"}`}>
                                <div className="sm:px-2 text-center text-[11px] font-semibold text-slate-500">
                                  {index + 1}
                                </div>
                                <div className="sm:px-3">
                                  <div className="flex items-center gap-2 flex-wrap min-w-0">
                                      <div className={`min-w-0 whitespace-pre-line break-words text-[12px] font-medium leading-4.5 ${isCompleted ? "text-slate-500" : "text-slate-800"}`}>
                                          <TaskMarkerComment comment={t.one_h_marker_comment} taskId={t.id} />
                                          {typeof t.title === "string" && t.title.includes("[[")
                                            ? renderMarkedNoteContent(t.title, t.title)
                                            : t.title}
                                      </div>
                                    </div>
                                  </div>
                                <div className="sm:px-3 flex items-start">
                                  {t.plan_note_origin_id ? (
                                    <Badge className="bg-indigo-500 text-white border-0 text-[9px] px-1.5 py-0.5 font-semibold">
                                      PX JAV
                                    </Badge>
                                  ) : t.ga_note_origin_id ? (
                                    <Badge className="bg-red-500 text-white border-0 text-[9px] px-1.5 py-0.5 font-semibold">
                                      GA
                                    </Badge>
                                  ) : (
                                    <span className="text-[11px] text-slate-400">-</span>
                                  )}
                                </div>
                                <div className="sm:px-3 flex items-center justify-center">
                                  <TaskOneHMarkerEditor taskId={t.id} marker={t.one_h_marker} markerByGa={t.one_h_marker_by_ga} markerComment={t.one_h_marker_comment} className="mx-auto shrink-0" />
                                </div>
                                <div className="sm:px-3 flex items-start">
                                  <Badge className={`border text-[10px] ${statusBadgeClasses(statusValue)}`}>
                                    {reportStatusLabel(statusValue)}
                                  </Badge>
                                </div>
                                <div className="sm:px-3 flex items-start">
                                  <Badge className={`border text-[11px] ${row.itemBadgeClass}`}>
                                    {row.itemBadge}
                                  </Badge>
                                </div>
                                <div className="sm:px-3 flex items-start gap-1 flex-wrap">
                                  {(() => {
                                    // Collect all assignees: from assigned_to and assignees array
                                    const assigneeIds = new Set<string>()
                                    if (t.assigned_to) {
                                      assigneeIds.add(t.assigned_to)
                                    }
                                    if (t.assignees) {
                                      for (const assignee of t.assignees) {
                                        if (assignee.id) {
                                          assigneeIds.add(assignee.id)
                                        }
                                      }
                                    }

                                    // Render all assignee initials
                                    const assigneeChips = Array.from(assigneeIds).map((userId) => {
                                      // Try to get user from userMap first, then from assignees array
                                      const userFromMap = userMap.get(userId)
                                      const assigneeFromArray = t.assignees?.find(a => a.id === userId)
                                      // Get label from userMap or assignees array
                                      const label = userFromMap
                                        ? assigneeLabel(userFromMap)
                                        : (assigneeFromArray?.full_name || assigneeFromArray?.username || "-")
                                      return (
                                        <div
                                          key={userId}
                                          className="h-5 w-5 rounded-full bg-slate-100 text-[9px] font-semibold text-slate-600 flex items-center justify-center"
                                          title={label}
                                        >
                                          {initials(label)}
                                        </div>
                                      )
                                    })

                                    return assigneeChips.length > 0 ? assigneeChips : (
                                      <span className="text-[11px] text-slate-400">-</span>
                                    )
                                  })()}
                                </div>
                                <div className="sm:px-3 flex items-start text-[11px] text-slate-600">
                                  {formatDateOnly(t.start_date)}
                                </div>
                                <div className="sm:px-3 flex items-start text-[11px] text-slate-600">
                                  {formatDateOnly(t.due_date)}
                                </div>
                                <div className="sm:px-3 flex items-start justify-end gap-2">
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    className="h-5 rounded-md border-slate-200 px-1.5 text-[9px] font-semibold text-slate-600 hover:border-emerald-200 hover:text-emerald-700"
                                    title="Create internal meeting"
                                    aria-label={`Create internal meeting from ${t.title}`}
                                    onClick={(event) => {
                                      event.preventDefault()
                                      event.stopPropagation()
                                      openInternalMeetingFromFastTask(t)
                                    }}
                                  >
                                    INT
                                  </Button>
                                  {canEditNoProjectTask(t) ? (
                                    <Button
                                      variant="outline"
                                      size="icon"
                                      className="h-5 w-5 border-slate-200 text-slate-500 hover:border-blue-200 hover:text-blue-600"
                                      title="Edit"
                                      aria-label={`Edit ${t.title}`}
                                      onClick={(event) => {
                                        event.preventDefault()
                                        event.stopPropagation()
                                        startEditTask(t)
                                      }}
                                    >
                                      <Pencil className="h-3 w-3" />
                                    </Button>
                                  ) : null}
                                  {canDeleteNoProject ? (
                                    <Button
                                      variant="outline"
                                      size="icon"
                                      disabled={deletingNoProjectTaskId === t.id}
                                      className="h-5 w-5 border-slate-200 text-slate-500 hover:border-red-200 hover:text-red-600"
                                      title="Delete"
                                      aria-label={`Delete ${t.title}`}
                                      onClick={(event) => {
                                        event.preventDefault()
                                        event.stopPropagation()
                                        void deleteNoProjectTask(t.id)
                                      }}
                                    >
                                      <Trash2 className="h-3 w-3" />
                                    </Button>
                                  ) : null}
                                </div>
                              </div>
                            </Link>
                          )
                        })}
                      </div>
                    ) : (
                      <div className="text-sm text-slate-500">No tasks in this category.</div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {activeTab === "internal-notes" ? (
          <div className="space-y-3 sm:space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
              <div className="text-base sm:text-lg font-semibold">Internal Notes</div>
              <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
                <Select value={internalNotesFilter} onValueChange={(value) => setInternalNotesFilter(value as "all" | "done" | "undone")}>
                  <SelectTrigger className="h-8 sm:h-9 w-full sm:w-48 border-slate-200 focus:border-slate-400 rounded-xl text-xs sm:text-sm">
                    <SelectValue placeholder="All notes" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All</SelectItem>
                    <SelectItem value="done">Done</SelectItem>
                    <SelectItem value="undone">Undone</SelectItem>
                  </SelectContent>
                </Select>
                {viewMode === "department" ? (
                  <Select value={selectedUserId} onValueChange={setSelectedUserId}>
                    <SelectTrigger className="h-8 sm:h-9 w-full sm:w-48 border-slate-200 focus:border-slate-400 rounded-xl text-xs sm:text-sm">
                      <SelectValue placeholder="All users" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__all__">All users</SelectItem>
                      {departmentUsers.map((u) => (
                        <SelectItem key={u.id} value={u.id}>
                          {u.full_name || u.username || "-"}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : null}
                <Dialog open={internalNoteOpen} onOpenChange={setInternalNoteOpen}>
                  <DialogTrigger asChild>
                    <Button variant="outline" className="w-full sm:w-auto">Create Internal Note</Button>
                  </DialogTrigger>
                  <DialogContent className="sm:max-w-lg">
                    <DialogHeader>
                      <DialogTitle>Create Internal Note</DialogTitle>
                    </DialogHeader>
                    <div className="space-y-3">
                      <div className="space-y-2">
                        <Label>Title</Label>
                        <Input
                          value={internalNoteTitle}
                          onChange={(e) => setInternalNoteTitle(e.target.value)}
                          placeholder="Enter title"
                        />
                      </div>
                      <div className="space-y-2">
                        <Label>Description</Label>
                        <Textarea
                          value={internalNoteDescription}
                          onChange={(e) => setInternalNoteDescription(e.target.value)}
                          placeholder="Enter description"
                          rows={4}
                        />
                      </div>
                      <div className="space-y-2">
                        <Label>Department</Label>
                        <Select
                          value={internalNoteDepartmentId}
                          onValueChange={(value) => {
                            setInternalNoteDepartmentId(value)
                            setInternalNoteProjectId("")
                          }}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="Select department" />
                          </SelectTrigger>
                          <SelectContent>
                            {departments.map((dep) => (
                              <SelectItem key={dep.id} value={dep.id}>
                                {dep.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-2">
                        <Label>Project</Label>
                        <Select
                          value={internalNoteProjectId}
                          onValueChange={setInternalNoteProjectId}
                          disabled={!internalNoteDepartmentId || loadingInternalNoteProjects}
                        >
                          <SelectTrigger>
                            <SelectValue
                              placeholder={
                                !internalNoteDepartmentId
                                  ? "Select a department first"
                                  : loadingInternalNoteProjects
                                    ? "Loading projects..."
                                    : "Select project"
                              }
                            />
                          </SelectTrigger>
                          <SelectContent>
                            {internalNoteProjects.map((project) => (
                              <SelectItem key={project.id} value={project.id}>
                                {resolveProjectTitle(project) || "Untitled project"}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-2">
                        <Label>User (To)</Label>
                        <div className="rounded-md border border-slate-200 p-2 max-h-56 overflow-y-auto space-y-2">
                          <label className="flex items-center gap-2 text-sm font-medium cursor-pointer">
                            <Checkbox
                              checked={users.length > 0 && users.every((u) => internalNoteToUserIds.includes(u.id))}
                              onCheckedChange={(value) => {
                                const next = Boolean(value)
                                setInternalNoteToUserIds(next ? users.map((u) => u.id) : [])
                              }}
                            />
                            <span>Select all users</span>
                          </label>
                          {users.map((member) => {
                            const label = member.full_name || member.username || "-"
                            const checked = internalNoteToUserIds.includes(member.id)
                            return (
                              <label key={member.id} className="flex items-center gap-2 text-sm cursor-pointer">
                                <Checkbox
                                  checked={checked}
                                  onCheckedChange={(value) => {
                                    const next = Boolean(value)
                                    setInternalNoteToUserIds((prev) =>
                                      next ? [...prev, member.id] : prev.filter((id) => id !== member.id)
                                    )
                                  }}
                                />
                                <span>{label}</span>
                              </label>
                            )
                          })}
                        </div>
                      </div>
                      <div className="flex justify-end gap-2">
                        <Button variant="outline" onClick={() => setInternalNoteOpen(false)}>
                          Cancel
                        </Button>
                        <Button
                          disabled={
                            !internalNoteTitle.trim() ||
                            internalNoteToUserIds.length === 0 ||
                            addingInternalNote
                          }
                          onClick={() => void submitInternalNote()}
                        >
                          {addingInternalNote ? "Saving..." : "Save"}
                        </Button>
                      </div>
                    </div>
                  </DialogContent>
                </Dialog>

                <Dialog
                  open={editInternalNoteOpen}
                  onOpenChange={(open) => {
                    setEditInternalNoteOpen(open)
                    if (!open) {
                      setEditingInternalNoteIds([])
                      setEditInternalNoteTitle("")
                      setEditInternalNoteDescription("")
                      setEditInternalNoteDepartmentId("")
                      setEditInternalNoteProjectId("")
                      setEditInternalNoteToUserIds([])
                    }
                  }}
                >
                  <DialogContent className="sm:max-w-lg">
                    <DialogHeader>
                      <DialogTitle>Edit Internal Note</DialogTitle>
                    </DialogHeader>
                    <div className="space-y-3">
                      <div className="space-y-2">
                        <Label>Title</Label>
                        <Input
                          value={editInternalNoteTitle}
                          onChange={(e) => setEditInternalNoteTitle(e.target.value)}
                          placeholder="Enter title"
                        />
                      </div>
                      <div className="space-y-2">
                        <Label>Description</Label>
                        <Textarea
                          value={editInternalNoteDescription}
                          onChange={(e) => setEditInternalNoteDescription(e.target.value)}
                          placeholder="Enter description"
                          rows={4}
                        />
                      </div>
                      <div className="space-y-2">
                        <Label>Department</Label>
                        <Select
                          value={editInternalNoteDepartmentId}
                          onValueChange={(value) => {
                            setEditInternalNoteDepartmentId(value)
                            setEditInternalNoteProjectId("")
                            setEditInternalNoteToUserIds([])
                          }}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="Select department" />
                          </SelectTrigger>
                          <SelectContent>
                            {departments.map((dep) => (
                              <SelectItem key={dep.id} value={dep.id}>
                                {dep.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-2">
                        <Label>Project</Label>
                        <Select
                          value={editInternalNoteProjectId}
                          onValueChange={setEditInternalNoteProjectId}
                          disabled={!editInternalNoteDepartmentId || loadingEditInternalNoteProjects}
                        >
                          <SelectTrigger>
                            <SelectValue
                              placeholder={
                                !editInternalNoteDepartmentId
                                  ? "Select a department first"
                                  : loadingEditInternalNoteProjects
                                    ? "Loading projects..."
                                    : "Select project"
                              }
                            />
                          </SelectTrigger>
                          <SelectContent>
                            {editInternalNoteProjects.map((project) => (
                              <SelectItem key={project.id} value={project.id}>
                                {resolveProjectTitle(project) || "Untitled project"}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-2">
                        <Label>User (To)</Label>
                        <div className="rounded-md border border-slate-200 p-2 max-h-56 overflow-y-auto space-y-2">
                          {(() => {
                            const eligibleUsers = editInternalNoteDepartmentId
                              ? users.filter((u) => u.department_id === editInternalNoteDepartmentId)
                              : users
                            return (
                              <>
                                <label className="flex items-center gap-2 text-sm font-medium cursor-pointer">
                                  <Checkbox
                                    checked={
                                      eligibleUsers.length > 0 &&
                                      eligibleUsers.every((u) => editInternalNoteToUserIds.includes(u.id))
                                    }
                                    onCheckedChange={(value) => {
                                      const next = Boolean(value)
                                      setEditInternalNoteToUserIds(next ? eligibleUsers.map((u) => u.id) : [])
                                    }}
                                  />
                                  <span>Select all users</span>
                                </label>
                                {eligibleUsers.map((member) => {
                                  const label = member.full_name || member.username || "-"
                                  const checked = editInternalNoteToUserIds.includes(member.id)
                                  return (
                                    <label key={member.id} className="flex items-center gap-2 text-sm cursor-pointer">
                                      <Checkbox
                                        checked={checked}
                                        onCheckedChange={(value) => {
                                          const next = Boolean(value)
                                          setEditInternalNoteToUserIds((prev) =>
                                            next ? [...prev, member.id] : prev.filter((id) => id !== member.id)
                                          )
                                        }}
                                      />
                                      <span>{label}</span>
                                    </label>
                                  )
                                })}
                              </>
                            )
                          })()}
                        </div>
                      </div>
                      <div className="flex justify-end gap-2">
                        <Button variant="outline" onClick={() => setEditInternalNoteOpen(false)}>
                          Cancel
                        </Button>
                        <Button
                          disabled={
                            !editInternalNoteTitle.trim() ||
                            editInternalNoteToUserIds.length === 0 ||
                            !editInternalNoteDepartmentId ||
                            savingInternalNoteEdit
                          }
                          onClick={() => void submitInternalNoteEdit()}
                        >
                          {savingInternalNoteEdit ? "Saving..." : "Save"}
                        </Button>
                      </div>
                    </div>
                  </DialogContent>
                </Dialog>
              </div>
            </div>

            <div className="rounded-md border-2 border-slate-700 max-h-[75vh] overflow-x-auto overflow-y-auto relative bg-white w-full">
              <div className="w-full min-w-[900px]">
                <table className="w-full caption-bottom text-sm min-w-[900px]">
                  <thead className="sticky top-0 z-50 bg-white shadow-md" style={{ position: "sticky", top: 0, zIndex: 50 }}>
                    <tr className="bg-white" style={{ borderBottom: "1px solid rgb(51 65 85)" }}>
                      <th className="w-[40px] border border-slate-600 border-l-2 border-l-slate-800 bg-white text-foreground h-10 px-2 text-left align-middle font-medium" style={{ verticalAlign: "bottom", borderBottom: "1px solid rgb(51 65 85)", whiteSpace: "normal" }}>NUMRI</th>
                      <th className="w-[300px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: "bottom", borderBottom: "1px solid rgb(51 65 85)" }}>NOTE</th>
                      <th className="w-[360px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: "bottom", borderBottom: "1px solid rgb(51 65 85)" }}>DESCRIPTION</th>
                      <th className="w-[180px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: "bottom", borderBottom: "1px solid rgb(51 65 85)" }}>DEPARTMENT</th>
                      <th className="w-[200px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: "bottom", borderBottom: "1px solid rgb(51 65 85)" }}>PROJECT</th>
                      <th className="w-[140px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: "bottom", borderBottom: "1px solid rgb(51 65 85)" }}>DATE, TIME</th>
                      <th className="w-[80px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: "bottom", borderBottom: "1px solid rgb(51 65 85)" }}>FROM</th>
                      <th className="w-[160px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: "bottom", borderBottom: "1px solid rgb(51 65 85)" }}>TO</th>
                      <th className="w-[160px] border border-slate-600 border-r-2 border-r-slate-800 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: "bottom", borderBottom: "1px solid rgb(51 65 85)" }}>ACTIONS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {groupedInternalNotes.length ? (
                      groupedInternalNotes.map((group, idx) => {
                        const note = group.note
                        const fromUser = users.find((u) => u.id === note.from_user_id) || null
                        const fromLabel = fromUser?.full_name || fromUser?.username || "Unknown user"
                        const toInitials = group.toUserIds
                          .map((id) => {
                            const toUser = userMap.get(id)
                            const toLabel = toUser?.full_name || toUser?.username || "Unknown user"
                            return initials(toLabel)
                          })
                          .join(", ")
                        const departmentLabel =
                          departments.find((d) => d.id === (note.department_id || note.to_department_id))?.name || "-"
                        const projectLabel =
                          projects.find((p) => p.id === note.project_id)?.title ||
                          projects.find((p) => p.id === note.project_id)?.name ||
                          "-"
                        const isAdminOrManager = user?.role === "ADMIN" || user?.role === "MANAGER"
                        const canDeleteNote =
                          isAdminOrManager ||
                          (user?.id ? group.toUserIds.includes(user.id) : false)
                        const canEditNote = isAdminOrManager || (user?.id ? note.from_user_id === user.id : false)
                        const statusNotes = getInternalNoteStatusNotes(group.notes)
                        const groupIsDone = statusNotes.length > 0 && statusNotes.every((n) => n.is_done)
                        const noteIdsForAction = (() => {
                          if (isAdminOrManager) return group.notes.map((n) => n.id)
                          return user?.id ? group.notes.filter((n) => n.to_user_id === user.id).map((n) => n.id) : []
                        })()
                        const noteIdsForEdit = canEditNote ? group.notes.map((n) => n.id) : []
                        const canUpdateDone = noteIdsForAction.length > 0

                        return (
                          <tr
                            key={note.id}
                            className={`hover:bg-muted/50 border-b transition-colors ${groupIsDone ? "bg-slate-50/70 opacity-70" : ""}`}
                          >
                            <td className="font-bold text-muted-foreground border border-slate-600 border-l-2 border-l-slate-800 p-2 align-middle whitespace-nowrap" style={{ verticalAlign: "bottom" }}>{idx + 1}</td>
                            <td className="whitespace-pre-wrap break-words w-[300px] border border-slate-600 p-2 align-middle" style={{ verticalAlign: "bottom" }}>
                              <div className="flex flex-col gap-1">
                                <span className={`text-sm font-semibold ${groupIsDone ? "line-through text-slate-500" : ""}`}>{note.title}</span>
                              </div>
                            </td>
                            <td className="whitespace-pre-wrap break-words w-[360px] border border-slate-600 p-2 align-middle" style={{ verticalAlign: "bottom" }}>
                              <span className="text-sm">{note.description || "-"}</span>
                            </td>
                            <td className="border border-slate-600 p-2 align-middle whitespace-nowrap" style={{ verticalAlign: "bottom" }}>{departmentLabel}</td>
                            <td className="border border-slate-600 p-2 align-middle whitespace-nowrap" style={{ verticalAlign: "bottom" }}>{projectLabel}</td>
                            <td className="border border-slate-600 p-2 align-middle whitespace-nowrap" style={{ verticalAlign: "bottom" }}>{formatDate(note.created_at)}</td>
                            <td className="border border-slate-600 p-2 align-middle whitespace-nowrap" style={{ verticalAlign: "bottom" }}>{initials(fromLabel)}</td>
                            <td className="border border-slate-600 p-2 align-middle whitespace-nowrap" style={{ verticalAlign: "bottom" }}>{toInitials}</td>
                            <td className="border border-slate-600 border-r-2 border-r-slate-800 p-2 align-middle whitespace-nowrap" style={{ verticalAlign: "bottom" }}>
                              <div className="flex items-center justify-center gap-2">
                                {canEditNote ? (
                                  <Button
                                    variant="outline"
                                    size="icon"
                                    className="h-7 w-7 border-slate-200 text-slate-500 hover:border-sky-200 hover:text-sky-700"
                                    title="Edit"
                                    aria-label={`Edit ${note.title}`}
                                    onClick={() => startEditInternalNote(note, group.toUserIds, noteIdsForEdit)}
                                  >
                                    <Pencil className="h-3.5 w-3.5" />
                                  </Button>
                                ) : null}
                                {!groupIsDone ? (
                                  canUpdateDone ? (
                                    <Button
                                      variant="outline"
                                      size="sm"
                                      className="h-7 text-xs border-emerald-200 text-emerald-700 hover:bg-emerald-50"
                                      disabled={noteIdsForAction.some((id) => updatingInternalNoteIds.includes(id))}
                                      onClick={() => void updateInternalNoteDone(noteIdsForAction, true)}
                                    >
                                      <Check className="h-3.5 w-3.5 mr-1" />
                                      Mark as done
                                    </Button>
                                  ) : null
                                ) : (
                                  <div className="flex items-center gap-1">
                                    <span className="text-xs text-emerald-700">Done</span>
                                    <Check className="h-3.5 w-3.5 text-emerald-600" />
                                    {canUpdateDone ? (
                                      <Button
                                        variant="outline"
                                        size="icon"
                                        className="h-7 w-7 border-slate-200 text-slate-500 hover:border-amber-200 hover:text-amber-600"
                                        title="Undo"
                                        aria-label={`Undo done for ${note.title}`}
                                        disabled={noteIdsForAction.some((id) => updatingInternalNoteIds.includes(id))}
                                        onClick={() => void updateInternalNoteDone(noteIdsForAction, false)}
                                      >
                                        <RotateCcw className="h-3.5 w-3.5" />
                                      </Button>
                                    ) : null}
                                  </div>
                                )}
                                {canDeleteNote ? (
                                  <Button
                                    variant="outline"
                                    size="icon"
                                    className="h-7 w-7 border-slate-200 text-slate-500 hover:border-red-200 hover:text-red-600"
                                    title="Delete"
                                    aria-label={`Delete ${note.title}`}
                                    onClick={() => void deleteInternalNote(noteIdsForAction)}
                                  >
                                    <Trash2 className="h-3.5 w-3.5" />
                                  </Button>
                                ) : null}
                              </div>
                            </td>
                          </tr>
                        )
                      })
                    ) : (
                      <tr>
                        <td colSpan={9} className="border border-slate-600 p-4 text-center text-sm text-muted-foreground">
                          {loadingExtras ? "Loading internal notes..." : "No internal notes yet."}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        ) : null}

        {activeTab === "meetings" ? (
          <div className="space-y-4 sm:space-y-6">
            <div className="text-lg sm:text-xl font-semibold">Meetings</div>
            <div className="grid gap-4 grid-cols-1 lg:grid-cols-2">
              <Card className="rounded-2xl border-slate-200 bg-white p-5 shadow-sm space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="text-sm font-semibold">External Meetings</div>
                  <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-1">
                    {([
                      ["today", "Sot"],
                      ["tomorrow", "Nesër"],
                      ["this_week", "This Week"],
                      ["next_week", "Next Week"],
                      ["future", "Future"],
                    ] as const).map(([value, label]) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => setMeetingTimeFilter(value)}
                        className={[
                          "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                          meetingTimeFilter === value
                            ? "bg-white text-slate-900 shadow-sm"
                            : "text-slate-500 hover:text-slate-900",
                        ].join(" ")}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
                {filteredExternalMeetings.length ? (
                  <div className="rounded-md border border-slate-200">
                    <Table className="table-fixed">
                      <TableHeader>
                        <TableRow className="bg-slate-100 hover:bg-slate-100">
                          <TableHead className="w-[320px] uppercase">Title</TableHead>
                          <TableHead className="w-[80px] uppercase">DEP</TableHead>
                          <TableHead className="w-[105px] uppercase">Date</TableHead>
                          <TableHead className="w-[85px] uppercase">Time</TableHead>
                          {!isReadOnly ? <TableHead className="w-[90px] text-right uppercase">Actions</TableHead> : null}
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {filteredExternalMeetings.map((meeting) => {
                          const isEditing = !isReadOnly && editingMeetingId === meeting.id
                          return (
                            <TableRow key={meeting.id}>
                              {isEditing ? (
                                <>
                                  <TableCell colSpan={!isReadOnly ? 5 : 4}>
                                    <div className="space-y-3">
                                      <Input
                                        value={editMeetingTitle}
                                        onChange={(e) => setEditMeetingTitle(e.target.value)}
                                        placeholder="Meeting title"
                                      />
                                      <div className="grid gap-3 md:grid-cols-2">
                                        <Input
                                          value={editMeetingPlatform}
                                          onChange={(e) => setEditMeetingPlatform(e.target.value)}
                                          placeholder="Platform"
                                        />
                                        {editMeetingRecurrenceType === "none" ? (
                                          <Input
                                            type="datetime-local"
                                            value={editMeetingStartsAt}
                                            onChange={(e) => setEditMeetingStartsAt(e.target.value)}
                                          />
                                        ) : (
                                          <Input
                                            type="time"
                                            value={editMeetingStartTime}
                                            onChange={(e) => setEditMeetingStartTime(e.target.value)}
                                            placeholder="Time (HH:MM)"
                                          />
                                        )}
                                      </div>
                                      <Input
                                        type="url"
                                        placeholder="Meeting URL (optional)"
                                        value={editMeetingUrl}
                                        onChange={(e) => setEditMeetingUrl(e.target.value)}
                                      />
                                      <div className="grid gap-3">
                                        <Label>Recurrence</Label>
                                        <Select value={editMeetingRecurrenceType} onValueChange={(v) => setEditMeetingRecurrenceType(v as "none" | "weekly" | "monthly")}>
                                          <SelectTrigger>
                                            <SelectValue />
                                          </SelectTrigger>
                                          <SelectContent>
                                            <SelectItem value="none">One time</SelectItem>
                                            <SelectItem value="weekly">Every week</SelectItem>
                                            <SelectItem value="monthly">Every month</SelectItem>
                                          </SelectContent>
                                        </Select>
                                        {editMeetingRecurrenceType === "weekly" && (
                                          <div className="space-y-2">
                                            <Label>Days of week</Label>
                                            <div className="flex flex-wrap gap-2">
                                              {["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map((day, idx) => (
                                                <div key={idx} className="flex items-center space-x-2">
                                                  <Checkbox
                                                    checked={editMeetingRecurrenceDaysOfWeek.includes(idx)}
                                                    onCheckedChange={(checked) => {
                                                      if (checked) {
                                                        setEditMeetingRecurrenceDaysOfWeek([...editMeetingRecurrenceDaysOfWeek, idx])
                                                      } else {
                                                        setEditMeetingRecurrenceDaysOfWeek(editMeetingRecurrenceDaysOfWeek.filter(d => d !== idx))
                                                      }
                                                    }}
                                                  />
                                                  <Label className="text-sm">{day}</Label>
                                                </div>
                                              ))}
                                            </div>
                                          </div>
                                        )}
                                        {editMeetingRecurrenceType === "monthly" && (
                                          <div className="space-y-2">
                                            <Label>Days of month (1-31)</Label>
                                            <div className="flex flex-wrap gap-2 max-h-32 overflow-y-auto">
                                              {Array.from({ length: 31 }, (_, i) => i + 1).map((day) => (
                                                <div key={day} className="flex items-center space-x-2">
                                                  <Checkbox
                                                    checked={editMeetingRecurrenceDaysOfMonth.includes(day)}
                                                    onCheckedChange={(checked) => {
                                                      if (checked) {
                                                        setEditMeetingRecurrenceDaysOfMonth([...editMeetingRecurrenceDaysOfMonth, day])
                                                      } else {
                                                        setEditMeetingRecurrenceDaysOfMonth(editMeetingRecurrenceDaysOfMonth.filter(d => d !== day))
                                                      }
                                                    }}
                                                  />
                                                  <Label className="text-sm">{day}</Label>
                                                </div>
                                              ))}
                                            </div>
                                          </div>
                                        )}
                                      </div>
                                      <div className="space-y-2">
                                        <Label>Participants</Label>
                                        <Dialog open={showEditParticipantDialog} onOpenChange={setShowEditParticipantDialog}>
                                          <DialogTrigger asChild>
                                            <Button variant="outline" className="w-full justify-between">
                                              {editMeetingParticipantIds.length > 0
                                                ? `${editMeetingParticipantIds.length} participant${editMeetingParticipantIds.length > 1 ? 's' : ''} selected`
                                                : "Select participants"}
                                            </Button>
                                          </DialogTrigger>
                                          <DialogContent className="sm:max-w-md">
                                            <DialogHeader>
                                              <DialogTitle>Select Participants</DialogTitle>
                                            </DialogHeader>
                                            <div className="mt-4 max-h-[400px] overflow-y-auto space-y-2">
                                              {users.map((u) => {
                                                const isSelected = editMeetingParticipantIds.includes(u.id)
                                                return (
                                                  <div
                                                    key={u.id}
                                                    className="flex items-center space-x-2 p-2 rounded-lg hover:bg-slate-50 cursor-pointer"
                                                    onClick={() => {
                                                      if (isSelected) {
                                                        setEditMeetingParticipantIds((prev) => prev.filter((id) => id !== u.id))
                                                      } else {
                                                        setEditMeetingParticipantIds((prev) => [...prev, u.id])
                                                      }
                                                    }}
                                                  >
                                                    <Checkbox checked={isSelected} />
                                                    <Label className="cursor-pointer flex-1">
                                                      {u.full_name || u.username || "-"}
                                                    </Label>
                                                  </div>
                                                )
                                              })}
                                            </div>
                                          </DialogContent>
                                        </Dialog>
                                      </div>
                                      <div className="grid gap-3 md:grid-cols-2">
                                        <Select value={editMeetingProjectId} onValueChange={setEditMeetingProjectId}>
                                          <SelectTrigger>
                                            <SelectValue placeholder="Project (optional)" />
                                          </SelectTrigger>
                                          <SelectContent>
                                            <SelectItem value="__none__">No project</SelectItem>
                                            {filteredProjects.map((p) => (
                                              <SelectItem key={p.id} value={p.id}>
                                                {p.title || p.name}
                                              </SelectItem>
                                            ))}
                                          </SelectContent>
                                        </Select>
                                        <div className="flex gap-2">
                                          <Button
                                            variant="outline"
                                            onClick={cancelEditMeeting}
                                            className="flex-1"
                                            type="button"
                                            disabled={savingMeeting}
                                          >
                                            Cancel
                                          </Button>
                                          <Button
                                            onClick={() => void saveMeeting(meeting.id)}
                                            className="flex-1"
                                            type="button"
                                            disabled={!editMeetingTitle.trim() || savingMeeting}
                                          >
                                            {savingMeeting ? "Saving..." : "Save"}
                                          </Button>
                                        </div>
                                      </div>
                                    </div>
                                  </TableCell>
                                </>
                              ) : (
                                <>
                                  <TableCell className="w-[320px] max-w-[320px] font-medium">
                                    <span className="block whitespace-normal break-words">{meeting.title}</span>
                                  </TableCell>
                                  <TableCell>
                                    <MeetingDepartmentTag meeting={meeting} departmentMap={departmentMap} />
                                  </TableCell>
                                  <TableCell>{formatMeetingDate(meeting)}</TableCell>
                                  <TableCell>{formatMeetingTime(meeting)}</TableCell>
                                  {!isReadOnly ? (
                                    <TableCell className="text-right">
                                      <div className="flex items-center justify-end gap-1">
                                        <Button
                                          variant="outline"
                                          size="icon"
                                          onClick={() => startEditMeeting(meeting)}
                                          aria-label="Edit meeting"
                                          title="Edit"
                                          className="h-7 w-7"
                                        >
                                          <Pencil className="h-3.5 w-3.5" />
                                        </Button>
                                        <Button
                                          variant="outline"
                                          size="icon"
                                          onClick={() => void deleteMeeting(meeting.id)}
                                          aria-label="Delete meeting"
                                          title="Delete"
                                          className="h-7 w-7 text-red-600 border-red-200 hover:bg-red-50"
                                        >
                                          <Trash2 className="h-3.5 w-3.5" />
                                        </Button>
                                      </div>
                                    </TableCell>
                                  ) : null}
                                </>
                              )}
                            </TableRow>
                          )
                        })}
                      </TableBody>
                    </Table>
                  </div>
                ) : (
                  <div className="text-sm text-muted-foreground">
                    {loadingExtras ? "Loading meetings..." : "No external meetings for this filter."}
                  </div>
                )}
                <div className="space-y-3 border-t border-slate-200 pt-4">
                  <div className="text-sm font-semibold">Internal Meetings</div>
                  {filteredInternalMeetings.length ? (
                    <div className="rounded-md border border-slate-200">
                      <Table className="table-fixed">
                        <TableHeader>
                          <TableRow className="bg-slate-100 hover:bg-slate-100">
                            <TableHead className="w-[320px] uppercase">Title</TableHead>
                            <TableHead className="w-[80px] uppercase">DEP</TableHead>
                            <TableHead className="w-[105px] uppercase">Date</TableHead>
                            <TableHead className="w-[85px] uppercase">Time</TableHead>
                            {!isReadOnly ? <TableHead className="w-[90px] text-right uppercase">Actions</TableHead> : null}
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {filteredInternalMeetings.map((meeting) => {
                            const isEditing = !isReadOnly && editingMeetingId === meeting.id
                            return (
                              <TableRow key={meeting.id}>
                                {isEditing ? (
                                  <TableCell colSpan={!isReadOnly ? 5 : 4}>
                                    <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_220px_auto]">
                                      <Input
                                        value={editMeetingTitle}
                                        onChange={(e) => setEditMeetingTitle(e.target.value)}
                                        placeholder="Meeting title"
                                      />
                                      {editMeetingRecurrenceType === "none" ? (
                                        <Input
                                          type="datetime-local"
                                          value={editMeetingStartsAt}
                                          onChange={(e) => setEditMeetingStartsAt(e.target.value)}
                                        />
                                      ) : (
                                        <Input
                                          type="time"
                                          value={editMeetingStartTime}
                                          onChange={(e) => setEditMeetingStartTime(e.target.value)}
                                        />
                                      )}
                                      <div className="flex gap-2">
                                        <Button
                                          type="button"
                                          variant="outline"
                                          onClick={cancelEditMeeting}
                                          disabled={savingMeeting}
                                        >
                                          Cancel
                                        </Button>
                                        <Button
                                          type="button"
                                          onClick={() => void saveMeeting(meeting.id)}
                                          disabled={!editMeetingTitle.trim() || savingMeeting}
                                        >
                                          {savingMeeting ? "Saving..." : "Save"}
                                        </Button>
                                      </div>
                                    </div>
                                  </TableCell>
                                ) : (
                                  <>
                                    <TableCell className="w-[320px] max-w-[320px] font-medium">
                                      <span className="block whitespace-normal break-words">
                                        {meeting.title || "Internal meeting"}
                                      </span>
                                    </TableCell>
                                    <TableCell>
                                      <MeetingDepartmentTag meeting={meeting} departmentMap={departmentMap} />
                                    </TableCell>
                                    <TableCell>{formatMeetingDate(meeting)}</TableCell>
                                    <TableCell>{formatMeetingTime(meeting)}</TableCell>
                                    {!isReadOnly ? (
                                      <TableCell className="text-right">
                                        <div className="flex items-center justify-end gap-1">
                                          <Button
                                            variant="outline"
                                            size="icon"
                                            onClick={() => startEditMeeting(meeting)}
                                            aria-label="Edit internal meeting"
                                            title="Edit"
                                            className="h-7 w-7"
                                          >
                                            <Pencil className="h-3.5 w-3.5" />
                                          </Button>
                                          <Button
                                            variant="outline"
                                            size="icon"
                                            onClick={() => void deleteMeeting(meeting.id)}
                                            aria-label="Delete internal meeting"
                                            title="Delete"
                                            className="h-7 w-7 border-red-200 text-red-600 hover:bg-red-50"
                                          >
                                            <Trash2 className="h-3.5 w-3.5" />
                                          </Button>
                                        </div>
                                      </TableCell>
                                    ) : null}
                                  </>
                                )}
                              </TableRow>
                            )
                          })}
                        </TableBody>
                      </Table>
                    </div>
                  ) : (
                    <div className="text-sm text-muted-foreground">
                      {loadingExtras ? "Loading meetings..." : "No internal meetings for this filter."}
                    </div>
                  )}
                </div>
                {!isReadOnly ? (
                  <div className="border-t border-slate-200 pt-4">
                    {!showAddMeetingForm ? (
                      <Button onClick={() => setShowAddMeetingForm(true)} variant="outline">
                        Add
                      </Button>
                    ) : (
                      <div className="space-y-3">
                        <div className="text-sm font-semibold">Add</div>
                        <div className="grid gap-3">
                          <Input
                            placeholder="Meeting title"
                            value={meetingTitle}
                            onChange={(e) => setMeetingTitle(e.target.value)}
                          />
                          <div className="grid gap-3 md:grid-cols-2">
                            <Input
                              placeholder="Platform (Zoom, Meet, Office...)"
                              value={meetingPlatform}
                              onChange={(e) => setMeetingPlatform(e.target.value)}
                            />
                            {meetingRecurrenceType === "none" ? (
                              <Input
                                type="datetime-local"
                                value={meetingStartsAt}
                                onChange={(e) => setMeetingStartsAt(e.target.value)}
                              />
                            ) : (
                              <Input
                                type="time"
                                value={meetingStartTime}
                                onChange={(e) => setMeetingStartTime(e.target.value)}
                                placeholder="Time (HH:MM)"
                              />
                            )}
                          </div>
                          <Input
                            type="url"
                            placeholder="Meeting URL (optional)"
                            value={meetingUrl}
                            onChange={(e) => setMeetingUrl(e.target.value)}
                          />
                          <div className="grid gap-3">
                            <Label>Recurrence</Label>
                            <Select value={meetingRecurrenceType} onValueChange={(v) => setMeetingRecurrenceType(v as "none" | "weekly" | "monthly")}>
                              <SelectTrigger>
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="none">One time</SelectItem>
                                <SelectItem value="weekly">Every week</SelectItem>
                                <SelectItem value="monthly">Every month</SelectItem>
                              </SelectContent>
                            </Select>
                            {meetingRecurrenceType === "weekly" && (
                              <div className="space-y-2">
                                <Label>Days of week</Label>
                                <div className="flex flex-wrap gap-2">
                                  {["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map((day, idx) => (
                                    <div key={idx} className="flex items-center space-x-2">
                                      <Checkbox
                                        checked={meetingRecurrenceDaysOfWeek.includes(idx)}
                                        onCheckedChange={(checked) => {
                                          if (checked) {
                                            setMeetingRecurrenceDaysOfWeek([...meetingRecurrenceDaysOfWeek, idx])
                                          } else {
                                            setMeetingRecurrenceDaysOfWeek(meetingRecurrenceDaysOfWeek.filter(d => d !== idx))
                                          }
                                        }}
                                      />
                                      <Label className="text-sm">{day}</Label>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                            {meetingRecurrenceType === "monthly" && (
                              <div className="space-y-2">
                                <Label>Days of month (1-31)</Label>
                                <div className="flex flex-wrap gap-2">
                                  {Array.from({ length: 31 }, (_, i) => i + 1).map((day) => (
                                    <div key={day} className="flex items-center space-x-2">
                                      <Checkbox
                                        checked={meetingRecurrenceDaysOfMonth.includes(day)}
                                        onCheckedChange={(checked) => {
                                          if (checked) {
                                            setMeetingRecurrenceDaysOfMonth([...meetingRecurrenceDaysOfMonth, day])
                                          } else {
                                            setMeetingRecurrenceDaysOfMonth(meetingRecurrenceDaysOfMonth.filter(d => d !== day))
                                          }
                                        }}
                                      />
                                      <Label className="text-sm">{day}</Label>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                          <div className="space-y-2">
                            <Label>Participants</Label>
                            <Dialog open={showParticipantDialog} onOpenChange={setShowParticipantDialog}>
                              <DialogTrigger asChild>
                                <Button variant="outline" className="w-full justify-between">
                                  {meetingParticipantIds.length > 0
                                    ? `${meetingParticipantIds.length} participant${meetingParticipantIds.length > 1 ? 's' : ''} selected`
                                    : "Select participants"}
                                </Button>
                              </DialogTrigger>
                              <DialogContent className="sm:max-w-md">
                                <DialogHeader>
                                  <DialogTitle>Select Participants</DialogTitle>
                                </DialogHeader>
                                <div className="mt-4 max-h-[400px] overflow-y-auto space-y-2">
                                  {users.map((u) => {
                                    const isSelected = meetingParticipantIds.includes(u.id)
                                    return (
                                      <div
                                        key={u.id}
                                        className="flex items-center space-x-2 p-2 rounded-lg hover:bg-slate-50 cursor-pointer"
                                        onClick={() => {
                                          if (isSelected) {
                                            setMeetingParticipantIds((prev) => prev.filter((id) => id !== u.id))
                                          } else {
                                            setMeetingParticipantIds((prev) => [...prev, u.id])
                                          }
                                        }}
                                      >
                                        <Checkbox checked={isSelected} />
                                        <Label className="cursor-pointer flex-1">
                                          {u.full_name || u.username || "-"}
                                        </Label>
                                      </div>
                                    )
                                  })}
                                </div>
                              </DialogContent>
                            </Dialog>
                          </div>
                          <div className="grid gap-3 md:grid-cols-2">
                            <Select value={meetingProjectId} onValueChange={setMeetingProjectId}>
                              <SelectTrigger>
                                <SelectValue placeholder="Project (optional)" />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="__none__">No project</SelectItem>
                                {filteredProjects.map((project) => (
                                  <SelectItem key={project.id} value={project.id}>
                                    {resolveProjectTitle(project)}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                            <div className="flex gap-2">
                              <Button
                                disabled={!meetingTitle.trim() || !meetingParticipantIds.length || creatingMeeting}
                                onClick={() => void submitMeeting()}
                                className="flex-1"
                                type="button"
                              >
                                {creatingMeeting ? "Saving..." : "Add"}
                              </Button>
                              <Button
                                variant="outline"
                                onClick={() => {
                                  setShowAddMeetingForm(false)
                                  setMeetingTitle("")
                                  setMeetingPlatform("")
                                  setMeetingStartsAt("")
                                  setMeetingStartTime("")
                                  setMeetingUrl("")
                                  setMeetingRecurrenceType("none")
                                  setMeetingRecurrenceDaysOfWeek([])
                                  setMeetingRecurrenceDaysOfMonth([])
                                  setMeetingParticipantIds([])
                                  setMeetingProjectId("__none__")
                                }}
                                type="button"
                                disabled={creatingMeeting}
                              >
                                Cancel
                              </Button>
                            </div>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                ) : null}
                <div className="rounded-xl border border-slate-200 bg-white p-3 space-y-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-sm font-semibold text-slate-800">Microsoft Calendar</div>
                    <div className="flex items-center gap-2">
                      {msConnected ? (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => void loadMicrosoftEvents()}
                          disabled={loadingMsEvents}
                          className="rounded-full border-slate-200"
                        >
                          {loadingMsEvents ? "Syncing..." : "Sync"}
                        </Button>
                      ) : msCanManage ? (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => void connectMicrosoft()}
                          disabled={checkingMsStatus}
                          className="rounded-full border-slate-200"
                        >
                          {checkingMsStatus ? "Checking..." : "Connect"}
                        </Button>
                      ) : (
                        <span className="text-xs text-amber-700">info@primexeu.com not connected</span>
                      )}
                      {msConnected && msCanManage ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => void disconnectMicrosoft()}
                          className="rounded-full text-slate-500"
                        >
                          Disconnect
                        </Button>
                      ) : null}
                    </div>
                  </div>
                  {msConnected ? (
                    loadingMsEvents ? (
                      <div className="text-xs text-muted-foreground">Loading events...</div>
                    ) : msEvents.length ? (
                      <div className="space-y-2">
                        {msEvents.map((event) => (
                          <div key={event.id} className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                            <div className="text-sm font-semibold text-slate-800">
                              {event.subject || "Untitled event"}
                            </div>
                            <div className="text-xs text-slate-600">{formatMsEventWindow(event)}</div>
                            {event.location ? (
                              <div className="text-xs text-slate-500">Location: {event.location}</div>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-xs text-muted-foreground">No upcoming events.</div>
                    )
                  ) : (
                    <div className="text-xs text-muted-foreground">
                      Connect your Microsoft account to read calendar events.
                    </div>
                  )}
                </div>
              </Card>

              <Card className="rounded-2xl border-slate-200 bg-white p-5 shadow-sm space-y-4">
                <div className="flex flex-wrap items-center justify-end gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => void exportInternalMeetings()}
                    disabled={exportingInternalMeetings || !internalMeetingItems.length}
                  >
                    {exportingInternalMeetings ? "Exporting..." : "Export Excel"}
                  </Button>
                </div>
                {todayInternalMeetings.length ? (
                  <div className="rounded-md border border-slate-200">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="uppercase">Title</TableHead>
                          <TableHead className="uppercase">Date & Time</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {todayInternalMeetings.map((meeting) => (
                          <TableRow key={meeting.id}>
                            <TableCell className="font-medium">{meeting.title || "Internal meeting"}</TableCell>
                            <TableCell>{formatMeetingDateTime(meeting)}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                ) : null}
                <div>
                  <div className="text-base font-semibold">{INTERNAL_MEETING.title}</div>
                  <div className="mt-1 text-sm text-muted-foreground">
                    {INTERNAL_MEETING.team.join(", ")}
                  </div>
                </div>
                <div className="inline-flex rounded-full border border-slate-200 bg-white p-1 shadow-sm">
                  {(Object.keys(INTERNAL_MEETING.slots) as Array<keyof typeof INTERNAL_MEETING.slots>).map((slot) => (
                    <button
                      key={slot}
                      type="button"
                      onClick={() => setInternalSlot(slot)}
                      className={[
                        "rounded-full px-4 py-2 text-sm font-medium transition-colors",
                        internalSlot === slot
                          ? "bg-foreground text-background shadow-sm"
                          : "text-muted-foreground hover:text-foreground",
                      ].join(" ")}
                    >
                      {INTERNAL_MEETING.slots[slot].tabLabel}
                    </button>
                  ))}
                </div>
                <div className="space-y-3">
                  <div className="text-sm font-semibold">{INTERNAL_MEETING.slots[internalSlot].label}</div>
                  {!isReadOnly ? (
                    <div className="flex flex-wrap items-center gap-2">
                      <Input
                        value={newInternalMeetingItem}
                        onChange={(e) => setNewInternalMeetingItem(e.target.value)}
                        placeholder="Add checklist item..."
                        className="min-w-[220px] flex-1"
                      />
                      <Button
                        variant="outline"
                        disabled={!newInternalMeetingItem.trim() || addingInternalMeetingItem}
                        onClick={() => void addInternalMeetingItem()}
                        type="button"
                      >
                        {addingInternalMeetingItem ? "Adding..." : "Add"}
                      </Button>
                    </div>
                  ) : null}
                  <div className="space-y-2">
                    {internalMeetingItems
                      .filter((item) => resolveInternalMeetingSlot(item.day) === internalSlot)
                      .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
                      .map((item, idx) => {
                        const isEditing = editingInternalMeetingItemId === item.id
                        const displayTitle = (internalSlot === "M2" || internalSlot === "M3")
                          ? (item.title || "").toUpperCase()
                          : (item.title || "")
                        return (
                          <div key={item.id} className="flex flex-wrap items-start gap-3 rounded-xl border border-slate-200 bg-white px-3 py-2">
                            <Checkbox
                              checked={Boolean(item.is_checked)}
                              onCheckedChange={(checked) => toggleInternalMeetingItem(item.id, Boolean(checked))}
                            />
                            <div className="flex-1">
                              {isEditing ? (
                                <div className="flex items-center gap-2">
                                  <Input
                                    type="number"
                                    min={1}
                                    max={internalMeetingItems.filter(
                                      (candidate) => resolveInternalMeetingSlot(candidate.day) === internalSlot,
                                    ).length}
                                    value={editingInternalMeetingItemPosition}
                                    onChange={(e) => setEditingInternalMeetingItemPosition(e.target.value)}
                                    aria-label="Checklist item number"
                                    title="Order number"
                                    className="w-20 shrink-0"
                                  />
                                  <Input
                                    value={editingInternalMeetingItem}
                                    onChange={(e) => setEditingInternalMeetingItem(e.target.value)}
                                    placeholder="Checklist item"
                                  />
                                </div>
                              ) : (
                                <div className="text-sm text-muted-foreground">
                                  {idx + 1}. {displayTitle}
                                </div>
                              )}
                            </div>
                            {!isReadOnly ? (
                              <div className="flex items-center gap-2">
                                {isEditing ? (
                                  <>
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      onClick={() => void saveInternalMeetingItem()}
                                      type="button"
                                      disabled={!editingInternalMeetingItem.trim() || savingInternalMeetingItem}
                                    >
                                      {savingInternalMeetingItem ? "Saving..." : "Save"}
                                    </Button>
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      onClick={cancelEditInternalMeetingItem}
                                      type="button"
                                      disabled={savingInternalMeetingItem}
                                    >
                                      Cancel
                                    </Button>
                                  </>
                                ) : (
                                  <>
                                    <Button
                                      size="icon"
                                      variant="outline"
                                      onClick={() => startEditInternalMeetingItem(item, idx + 1)}
                                      aria-label="Edit internal meeting item"
                                      title="Edit"
                                    >
                                      <Pencil className="h-4 w-4" />
                                    </Button>
                                    <Button
                                      size="icon"
                                      variant="outline"
                                      className="text-red-600 border-red-200 hover:bg-red-50"
                                      onClick={() => void deleteInternalMeetingItem(item.id)}
                                      aria-label="Delete internal meeting item"
                                      title="Delete"
                                    >
                                      <Trash2 className="h-4 w-4" />
                                    </Button>
                                  </>
                                )}
                              </div>
                            ) : null}
                          </div>
                        )
                      })}
                    {!internalMeetingItems.some((item) => resolveInternalMeetingSlot(item.day) === internalSlot) ? (
                      <div className="text-sm text-muted-foreground">No checklist items yet.</div>
                    ) : null}
                  </div>
                </div>
              </Card>
            </div>
          </div>
        ) : null}

        {/* Title Warning Confirmation Dialog */}
        <Dialog open={showTitleWarning} onOpenChange={setShowTitleWarning}>
          <DialogContent className="sm:max-w-md border-red-200 bg-white shadow-xl rounded-2xl">
            <DialogHeader>
              <DialogTitle className="text-slate-900 flex items-center gap-3">
                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-red-600 text-white text-lg shadow-sm">
                  !
                </span>
                <span>Confirm Project Title</span>
              </DialogTitle>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div className="text-sm text-slate-700">
                Please confirm the title "<span className="font-semibold text-red-900">{pendingProjectTitle}</span>" is the correct shortcut to use.
              </div>
              {looksLikeFullName(pendingProjectTitle) ? (
                <div className="text-sm text-red-700 font-semibold">
                  This looks longer than a typical shortcut. Consider shortening it.
                </div>
              ) : null}
              <div className="rounded-xl border border-red-200 bg-red-50/60 p-4">
                <div className="text-xs font-semibold uppercase tracking-wide text-red-700 mb-2">Remember</div>
                <div className="text-xs text-red-800 space-y-1">
                  <div>• Use shortcuts/abbreviations (e.g., "ABC" instead of "ABC Company")</div>
                  <div>• Keep it short and simple (typically 2-6 characters)</div>
                  <div>• Avoid company suffixes like "Company", "Inc", "LLC", etc.</div>
                </div>
              </div>
              <div className="text-sm text-slate-700">
                Are you sure you want to use this as the project title?
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => {
                  setShowTitleWarning(false)
                  setPendingProjectTitle("")
                }}
                className="rounded-xl border-slate-200 hover:bg-slate-100"
              >
                Go Back & Edit
              </Button>
              <Button
                onClick={() => {
                  setShowTitleWarning(false)
                  setPendingProjectTitle("")
                  void submitProject()
                }}
                className="bg-red-600 hover:bg-red-700 text-white border-0 shadow-sm rounded-xl"
              >
                Yes, Use This Title
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>
      <div className="hidden print:block">
        <div
          ref={printContainerRef}
          className="print-page px-6 pb-6"
          style={printPageMinHeight ? { minHeight: `${printPageMinHeight}px` } : undefined}
        >
          <div ref={printMeasureRef} className="print-page-measure" />
          <div className="print-header">
            <div />
            <div className="print-title">
              {showAllTodayPrint
                ? "ALL TODAY REPORT"
                : printRange === "today" && showDailyUserReport
                  ? "DAILY TASK REPORT"
                  : "PLANIFIKIMI JAVOR - PRMBL PLANIFIKIMI JAVOR"}
            </div>
            <div className="print-datetime">
              {formatDateTimeDMY(printedAt)}
            </div>
          </div>
          <div className="print-meta">
            <div>Department: {departmentName}</div>
            {showAllTodayPrint ? (
              <div>
                Users: {selectedUserId === "__all__"
                  ? "All users"
                  : allTodayPrintColumns[0]?.label || "Selected user"}
              </div>
            ) : (
              <div>User: {user?.full_name || user?.username || "-"}</div>
            )}
            {null}
          </div>
          {showAllTodayPrint ? (
            <>
              {loadingAllUsersDailyReports ? (
                <div className="text-sm text-slate-600 py-4">Loading daily reports...</div>
              ) : (() => {
                // Collect all rows from all users into a single array
                const allRows: Array<{
                  typeLabel: string
                  subtype: string
                  period: string
                  department: string
                  title: string
                  projectTitle?: string | null
                  description: string
                  status: string
                  statusKey?: string
                  bz: string
                  kohaBz: string
                  tyo: string
                  comment?: string | null
                  taskId?: string
                  systemTemplateId?: string
                  systemOccurrenceDate?: string
                  systemStatus?: string
                  sortDate?: string | null
                  startDate?: string | null
                  dueDate?: string | null
                  oneHMarker?: Task["one_h_marker"]
                  oneHMarkerByGa?: boolean
                  userName: string
                  userInitials: string
                }> = []

                for (const member of allTodayPrintBaseUsers) {
                  const userReport = allUsersDailyReports.get(member.id)
                  if (!userReport) continue
                  const userRows = convertDailyReportToRows(userReport, member.id)
                  const userName = member.full_name || member.username || "-"
                  const userInitials = initials(userName)
                  // Add userName to each row and add to allRows
                  for (const row of userRows) {
                    allRows.push({ ...row, userName, userInitials })
                  }
                }
                const tyoRank = (value: string) => {
                  const trimmed = value.trim()
                  if (!trimmed || trimmed === "-") return 3
                  if (trimmed === "Y") return 1
                  if (trimmed === "T") return 2
                  if (/^\d+$/.test(trimmed)) return 0
                  return 3
                }
                const tyoNumber = (value: string) => {
                  const trimmed = value.trim()
                  return /^\d+$/.test(trimmed) ? Number(trimmed) : -1
                }
                const sortByTyo = (a: (typeof allRows)[number], b: (typeof allRows)[number]) => {
                  const rankA = tyoRank(a.tyo)
                  const rankB = tyoRank(b.tyo)
                  if (rankA !== rankB) return rankA - rankB
                  if (rankA === 0) return tyoNumber(b.tyo) - tyoNumber(a.tyo)
                  return 0
                }
                const fastSubtypeOrder = (subtype: string) => {
                  const normalized = subtype.trim().toUpperCase()
                  if (normalized === "BLL") return 0
                  if (normalized === "1H") return 1
                  if (normalized === "P:" || normalized === "P") return 2
                  if (normalized === "R1") return 3
                  if (normalized === "N" || normalized === "NORMAL") return 4
                  return 5
                }
                const typeOrder = (row: (typeof allRows)[number]) => {
                  if (row.typeLabel === "FT") return 0
                  if (row.typeLabel === "SYS") return row.period === "PM" ? 3 : 1
                  if (row.typeLabel === "PRJK") return 2
                  return 4
                }
                const importantDeadlineRank = (row: (typeof allRows)[number]) => {
                  const rowDate = row.sortDate ? toDate(row.sortDate) : null
                  if (rowDate && dayKey(rowDate) === dayKey(selectedAllReportDate)) {
                    if (titleHasEightAmIndicator(row.title)) return 0
                    if (row.period === "PM") return 2
                    return 1
                  }
                  return 3
                }
                const importantDeadlineSort = (a: (typeof allRows)[number], b: (typeof allRows)[number]) => {
                  const rankA = importantDeadlineRank(a)
                  const rankB = importantDeadlineRank(b)
                  if (rankA !== rankB) return rankA - rankB
                  const dateA = a.sortDate ? toDate(a.sortDate) : null
                  const dateB = b.sortDate ? toDate(b.sortDate) : null
                  const dateDiff = (dateA ? dayKey(dateA) : Number.MAX_SAFE_INTEGER) - (dateB ? dayKey(dateB) : Number.MAX_SAFE_INTEGER)
                  if (dateDiff !== 0) return dateDiff
                  const eightAmDiff = Number(titleHasEightAmIndicator(b.title)) - Number(titleHasEightAmIndicator(a.title))
                  if (eightAmDiff !== 0) return eightAmDiff
                  return (a.period === "PM" ? 1 : 0) - (b.period === "PM" ? 1 : 0)
                }
                const sortedRows = [...allRows].sort((a, b) => {
                  const doneDiff =
                    Number(a.statusKey === "DONE" || a.status?.toUpperCase() === "DONE") -
                    Number(b.statusKey === "DONE" || b.status?.toUpperCase() === "DONE")
                  if (doneDiff !== 0) return doneDiff
                  const periodDiff = (a.period === "PM" ? 1 : 0) - (b.period === "PM" ? 1 : 0)
                  if (periodDiff !== 0) return periodDiff
                  const typeDiff = (a.typeLabel === "SYS" ? 0 : 1) - (b.typeLabel === "SYS" ? 0 : 1)
                  if (typeDiff !== 0) return typeDiff
                  const aImportant = deadlineImportantTaskIds.has(a.taskId || "")
                  const bImportant = deadlineImportantTaskIds.has(b.taskId || "")
                  const importantDiff = Number(bImportant) - Number(aImportant)
                  if (importantDiff !== 0) return importantDiff
                  if (aImportant && bImportant) {
                    const deadlineDiff = importantDeadlineSort(a, b)
                    if (deadlineDiff !== 0) return deadlineDiff
                  }
                  const typeOrderDiff = typeOrder(a) - typeOrder(b)
                  if (typeOrderDiff !== 0) return typeOrderDiff
                  if (a.typeLabel === "FT" && b.typeLabel === "FT") {
                    const subtypeDiff = fastSubtypeOrder(a.subtype) - fastSubtypeOrder(b.subtype)
                    if (subtypeDiff !== 0) return subtypeDiff
                    const eightAmDiff = Number(titleHasEightAmIndicator(b.title)) - Number(titleHasEightAmIndicator(a.title))
                    if (eightAmDiff !== 0) return eightAmDiff
                    const tyoDiff = sortByTyo(a, b)
                    if (tyoDiff !== 0) return tyoDiff
                    return a.title.localeCompare(b.title) || a.userInitials.localeCompare(b.userInitials)
                  }
                  const tyoDiff = sortByTyo(a, b)
                  if (tyoDiff !== 0) return tyoDiff
                  return a.title.localeCompare(b.title) || a.userInitials.localeCompare(b.userInitials)
                })

                return (
                  <table className="w-full border border-slate-900 text-[11px] daily-report-table print:table-fixed">
                    <colgroup>
                      <col className="w-[32px]" />
                      <col className="w-[40px]" />
                      <col className="w-[28px]" />
                      <col className="w-[32px]" />
                      <col className="w-[170px]" />
                      <col className="w-[100px]" />
                      <col className="w-[60px]" />
                      <col className="w-[44px]" />
                      <col className="w-[36px]" />
                      <col className="w-[50px]" />
                      <col className="w-[36px]" />
                      <col className="w-[90px]" />
                      <col className="w-[40px]" />
                    </colgroup>
                    <thead>
                      <tr className="bg-slate-100">
                        <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase whitespace-normal print-nr-cell">
                          Nr
                        </th>
                        <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase">LLOJI</th>
                        <th className="border border-slate-900 px-2 py-2 pr-3 text-left text-xs uppercase whitespace-normal">
                          NLL
                        </th>
                        <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase whitespace-normal">
                          <span className="block">AM/</span>
                          <span className="block">PM</span>
                        </th>
                        <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase">Titulli</th>
                        <th className="border border-slate-900 px-2 py-2 text-center text-xs uppercase">SIMBOLI</th>
                        <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase">STATUSI</th>
                        <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase whitespace-normal">1H SLOT</th>
                        <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase">BZ</th>
                        <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase whitespace-normal">KOHA BARAZIMIT</th>
                        <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase whitespace-normal break-words">
                          T/Y/O
                        </th>
                        <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase">Koment</th>
                        <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase">User</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortedRows.length ? (
                        sortedRows.map((row, index) => (
                          <tr
                            key={`${row.userName}-${row.typeLabel}-${row.title}-${index}`}
                            className={[
                              selectedDayDateRowClass(
                                row.startDate,
                                row.dueDate,
                                Boolean(row.taskId && deadlineImportantTaskIds.has(row.taskId)),
                              ),
                            ].join(" ")}
                          >
                            <td className="border border-slate-900 px-2 py-2 align-top print-nr-cell">{index + 1}</td>
                            <td className="border border-slate-900 px-2 py-2 align-top font-semibold">{dailyReportTypeLabel(row.typeLabel)}</td>
                            <td className="border border-slate-900 px-2 py-2 align-top whitespace-normal break-words">
                              {row.subtype}
                            </td>
                            <td className="border border-slate-900 px-2 py-2 align-top whitespace-normal break-words">
                              {row.period}
                            </td>
                            <td className="border border-slate-900 px-2 py-2 align-top uppercase">
                              <div className="flex flex-wrap items-start gap-2">
                                {titleHasEightAmIndicator(row.title) ? (
                                  <span className="inline-flex rounded-full border border-red-300 bg-red-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-red-700">
                                    08:00
                                  </span>
                                ) : null}
                                <span className="whitespace-pre-wrap break-words">
                                  <TaskMarkerComment taskId={row.taskId} />
                                  {row.typeLabel === "PRJK" && row.projectTitle ? (
                                    <>
                                      <span className="font-semibold">{row.projectTitle}</span>
                                      <span> : {row.title}</span>
                                    </>
                                  ) : (
                                    row.title
                                  )}
                                </span>
                              </div>
                            </td>
                            <td className="border border-slate-900 w-[100px] min-w-[100px] px-2 py-2 text-center align-middle">
                              {row.typeLabel === "SYS" ? (
                                <span className="text-xs font-semibold text-slate-600">SYS</span>
                              ) : (
                                <TaskOneHMarkerEditor taskId={row.taskId} marker={row.oneHMarker} markerByGa={row.oneHMarkerByGa} className="mx-auto shrink-0" />
                              )}
                            </td>
                            <td
                              className={`border border-slate-900 px-2 py-2 align-top uppercase ${weeklyPlanStatusBgClass(normalizeDailyReportStatusKey(row.status))}`}
                            >
                              {dailyReportStatusDisplay(row.status)}
                            </td>
                            <td className="border border-slate-900 px-2 py-2 align-top">
                              {getDailyReportOneHSlotDisplay(row)}
                            </td>
                            <td className="border border-slate-900 px-2 py-2 align-top">{row.bz}</td>
                            <td className="border border-slate-900 px-2 py-2 align-top">{row.kohaBz}</td>
                            <td className="border border-slate-900 px-2 py-2 align-top whitespace-normal break-words">
                              {formatTyoDisplay(
                                row.tyo,
                                row.taskId ? dailyReportTyoDateByTaskId.get(row.taskId) : null,
                                row.taskId ? deadlineImportantTaskIds.has(row.taskId) : false,
                              )}
                            </td>
                            <td className="border border-slate-900 px-2 py-2 align-top">
                              <div className="h-4 w-full border-b border-slate-400" />
                            </td>
                            <td className="border border-slate-900 px-2 py-2 align-top uppercase">
                              {row.userInitials}
                            </td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td className="border border-slate-900 px-2 py-4 text-center italic text-slate-600" colSpan={13}>
                            No data available.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                )
              })()}
            </>
          ) : printRange === "today" && showDailyUserReport ? (
            <>
              <DailyReportMeetingsTable
                meetings={visibleMeetings}
                users={users}
                reportDateIso={selectedAllReportIso}
              />
              <div className="h-3" />
              <table className="w-full border border-slate-900 text-[11px] daily-report-table print:table-fixed">
                <colgroup>
                  <col className="w-[36px]" />
                  <col className="w-[44px]" />
                  <col className="w-[30px]" />
                  <col className="w-[36px]" />
                  <col className="w-[200px]" />
                  <col className="w-[100px]" />
                  <col className="w-[60px]" />
                  <col className="w-[44px]" />
                  <col className="w-[40px]" />
                  <col className="w-[52px]" />
                  <col className="w-[40px]" />
                  <col className="w-[140px]" />
                </colgroup>
                <thead>
                  <tr className="bg-slate-100">
                    <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase whitespace-normal print-nr-cell">
                      Nr
                    </th>
                    <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase">LLOJI</th>
                    <th className="border border-slate-900 px-2 py-2 pr-3 text-left text-xs uppercase whitespace-normal">
                      NLL
                    </th>
                    <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase whitespace-normal">
                      <span className="block">AM/</span>
                      <span className="block">PM</span>
                    </th>
                    <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase">Titulli</th>
                    <th className="border border-slate-900 px-2 py-2 text-center text-xs uppercase">SIMBOLI</th>
                    <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase">STATUSI</th>
                    <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase whitespace-normal">1H SLOT</th>
                    <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase">BZ</th>
                    <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase whitespace-normal">KOHA BARAZIMIT</th>
                    <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase whitespace-normal break-words">T/Y/O</th>
                    <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase">Koment</th>
                  </tr>
                </thead>
                <tbody>
                  {dailyUserReportRows.length ? (
                    dailyUserReportRows.map((row, index) => (
                        <tr
                          key={`${row.typeLabel}-${row.title}-${index}`}
                          className={[
                            row.taskId
                              ? selectedDayDateRowClass(
                                dailyReportStartDateByTaskId.get(row.taskId),
                                dailyReportDueDateByTaskId.get(row.taskId),
                                deadlineImportantTaskIds.has(row.taskId),
                              )
                              : "",
                          ].join(" ")}
                        >
                        <td className="border border-slate-900 px-2 py-2 align-top print-nr-cell">{index + 1}</td>
                        <td className="border border-slate-900 px-2 py-2 align-top font-semibold">{dailyReportTypeLabel(row.typeLabel)}</td>
                        <td className="border border-slate-900 px-2 py-2 align-top whitespace-normal break-words">
                          {row.subtype}
                        </td>
                        <td className="border border-slate-900 px-2 py-2 align-top whitespace-normal break-words">{row.period}</td>
                        <td className="border border-slate-900 px-2 py-2 align-top uppercase">
                          <div className="flex flex-wrap items-start gap-2">
                            {titleHasEightAmIndicator(row.title) ? (
                              <span className="inline-flex rounded-full border border-red-300 bg-red-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-red-700">
                                08:00
                              </span>
                            ) : null}
                            <span className="whitespace-pre-wrap break-words">
                              <TaskMarkerComment taskId={row.taskId} />
                              {row.typeLabel === "PRJK" && row.projectTitle ? (
                                <>
                                  <span className="font-semibold">{row.projectTitle}</span>
                                  <span> : {row.title}</span>
                                </>
                              ) : (
                                row.title
                              )}
                            </span>
                          </div>
                        </td>
                        <td className="border border-slate-900 w-[100px] min-w-[100px] px-2 py-2 text-center align-middle">
                          {row.typeLabel === "SYS" ? (
                            <span className="text-xs font-semibold text-slate-600">SYS</span>
                          ) : (
                            <TaskOneHMarkerEditor taskId={row.taskId} marker={row.oneHMarker} markerByGa={row.oneHMarkerByGa} className="mx-auto shrink-0" />
                          )}
                        </td>
                        <td
                          className={`border border-slate-900 px-2 py-2 align-top uppercase ${weeklyPlanStatusBgClass(normalizeDailyReportStatusKey(row.status))}`}
                        >
                          {dailyReportStatusDisplay(row.status)}
                        </td>
                        <td className="border border-slate-900 px-2 py-2 align-top">
                          {getDailyReportOneHSlotDisplay(row)}
                        </td>
                        <td className="border border-slate-900 px-2 py-2 align-top">{row.bz}</td>
                        <td className="border border-slate-900 px-2 py-2 align-top">{row.kohaBz}</td>
                        <td className="border border-slate-900 px-2 py-2 align-top whitespace-normal break-words">
                          {formatTyoDisplay(
                            row.tyo,
                            row.taskId ? dailyReportTyoDateByTaskId.get(row.taskId) : null,
                            row.taskId ? deadlineImportantTaskIds.has(row.taskId) : false,
                          )}
                        </td>
                        <td className="border border-slate-900 px-2 py-2 align-top">
                          <div className="h-4 w-full border-b border-slate-400" />
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td className="border border-slate-900 px-2 py-4 text-center italic text-slate-600" colSpan={12}>
                        No data available.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
              <div className="mt-4">
                <table className="w-full border border-slate-900 text-[11px] print:table-fixed">
                  <colgroup>
                    <col className="w-[180px]" />
                    <col />
                  </colgroup>
                  <tbody>
                    <tr>
                      <td className="border border-slate-900 px-2 py-2 text-xs font-semibold uppercase align-top">
                        GA/KUR/SI/KUJT/PRBL
                      </td>
                      <td className="border border-slate-900 px-2 py-2">
                        {gaTableInput || "-"}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <>
              <table className="w-full border border-slate-900 text-[11px] weekly-report-table">
                <colgroup>
                  <col className="w-[36px]" />
                  <col className="w-[44px]" />
                  <col className="w-[56px]" />
                  <col className="w-[56px]" />
                  <col className="w-[150px]" />
                  <col className="w-[110px]" />
                  <col className="w-[60px]" />
                  <col className="w-[40px]" />
                  <col className="w-[52px]" />
                  <col className="w-[52px]" />
                  <col className="w-[48px]" />
                  <col className="w-[140px]" />
                </colgroup>
                <thead>
                  <tr className="bg-slate-100">
                    <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase whitespace-normal print-nr-cell">
                      Nr
                    </th>
                    <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase">LLOJI</th>
                    <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase">NLL</th>
                    <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase">Prioriteti</th>
                    <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase">AM/PM</th>
                    <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase">Titulli</th>
                    <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase">Pershkrimi</th>
                    <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase">STATUSI</th>
                    <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase whitespace-normal">1H SLOT</th>
                    <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase">BZ</th>
                    <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase whitespace-normal">KOHA BARAZIMIT</th>
                    <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase">T/Y/O</th>
                    <th className="border border-slate-900 px-2 py-2 text-left text-xs uppercase">Koment</th>
                  </tr>
                </thead>
                <tbody>
                  {weeklyTaskReportRows.length ? (
                    weeklyTaskReportRows.map((row, index) => (
                      <tr key={`${row.typeLabel}-${row.title}-${index}`}>
                        <td className="border border-slate-900 px-2 py-2 align-top print-nr-cell">{index + 1}</td>
                        <td className="border border-slate-900 px-2 py-2 align-top font-semibold">{dailyReportTypeLabel(row.typeLabel)}</td>
                        <td className="border border-slate-900 px-2 py-2 align-top">
                          {row.subtype}
                        </td>
                        <td className="border border-slate-900 px-2 py-2 align-top">{row.priority}</td>
                        <td className="border border-slate-900 px-2 py-2 align-top">{row.period}</td>
                        <td className="border border-slate-900 px-2 py-2 align-top uppercase">
                          {row.typeLabel === "PRJK" && row.projectTitle ? (
                            <>
                              <span className="font-semibold">{row.projectTitle}</span>
                              <span> : {row.title}</span>
                            </>
                          ) : (
                            row.title
                          )}
                        </td>
                        <td className="border border-slate-900 px-2 py-2 align-top">{row.description}</td>
                        <td
                          className={`border border-slate-900 px-2 py-2 align-top uppercase ${weeklyPlanStatusBgClass(normalizeDailyReportStatusKey(row.status))}`}
                        >
                          {dailyReportStatusDisplay(row.status)}
                        </td>
                        <td className="border border-slate-900 px-2 py-2 align-top">
                          {getDailyReportOneHSlotDisplay(row)}
                        </td>
                        <td className="border border-slate-900 px-2 py-2 align-top">-</td>
                        <td className="border border-slate-900 px-2 py-2 align-top">-</td>
                        <td className="border border-slate-900 px-2 py-2 align-top">-</td>
                        <td className="border border-slate-900 px-2 py-2 align-top">
                          <input
                            type="text"
                            aria-label="Koment"
                            className="h-4 w-full border-b border-slate-400 bg-transparent"
                          />
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td className="border border-slate-900 px-2 py-4 text-center italic text-slate-600" colSpan={13}>
                        No data available.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
              <div className="mt-4">
                <table className="w-full border border-slate-900 text-[11px] weekly-notes-table">
                  <colgroup>
                    <col className="w-[180px]" />
                    <col />
                  </colgroup>
                  <tbody>
                    <tr>
                      <td className="border border-slate-900 px-2 py-2 text-xs font-semibold uppercase align-top weekly-notes-label">
                        KOMENT
                      </td>
                      <td className="border border-slate-900 px-2 py-2">
                        <div
                          className="weekly-notes-columns"
                          style={{ gridTemplateColumns: `repeat(${weeklyNotesColumns}, minmax(0, 1fr))` }}
                        >
                          {Array.from({ length: weeklyNotesColumns }).map((_, idx) => (
                            <div key={`weekly-notes-comment-${idx}`} className="weekly-notes-column">
                              <div className="weekly-notes-line" />
                              <div className="weekly-notes-line" />
                              <div className="weekly-notes-line" />
                            </div>
                          ))}
                        </div>
                      </td>
                    </tr>
                    <tr>
                      <td className="border border-slate-900 px-2 py-2 text-xs font-semibold uppercase align-top weekly-notes-label">
                        ANKESA / KERKESA / PROPOZIME
                      </td>
                      <td className="border border-slate-900 px-2 py-2">
                        <div
                          className="weekly-notes-columns"
                          style={{ gridTemplateColumns: `repeat(${weeklyNotesColumns}, minmax(0, 1fr))` }}
                        >
                          {Array.from({ length: weeklyNotesColumns }).map((_, idx) => (
                            <div key={`weekly-notes-requests-${idx}`} className="weekly-notes-column">
                              <div className="weekly-notes-line" />
                              <div className="weekly-notes-line" />
                              <div className="weekly-notes-line" />
                            </div>
                          ))}
                        </div>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </>
          )}
          {printPageMarkers.map((marker) => (
            <div
              key={`print-page-${marker.page}`}
              className="print-page-marker"
              style={{ top: `${marker.top}px` }}
            >
              Page {marker.page} / {marker.total}
            </div>
          ))}
          <div className="print-footer">
            <span />
            <div className="print-page-count">1/{printTotalPages}</div>
            <div className="print-initials">
              PUNOI: {printInitials || "-"}
            </div>
          </div>
        </div>
      </div>
      <style jsx global>{`
        .task-row-starts-selected-day {
          background-color: rgb(239 246 255 / 0.86) !important;
        }
        .task-row-starts-selected-day:hover {
          background-color: rgb(219 234 254 / 0.9) !important;
        }
        .task-row-starts-selected-day > td {
          border-top: 3px solid #2563eb !important;
          border-bottom: 3px solid #2563eb !important;
        }
        .task-row-starts-selected-day > td:first-child {
          border-left: 3px solid #2563eb !important;
        }
        .task-row-starts-selected-day > td:last-child {
          border-right: 3px solid #2563eb !important;
        }
        .task-card-starts-selected-day {
          border: 3px solid #2563eb !important;
          background-color: rgb(239 246 255 / 0.88) !important;
          box-shadow: 0 0 0 1px rgb(37 99 235 / 0.22);
        }
        .task-card-starts-selected-day:hover {
          background-color: rgb(219 234 254 / 0.92) !important;
        }
        .task-row-due-selected-day {
          background-color: rgb(254 242 242 / 0.92) !important;
        }
        .task-row-due-selected-day:hover {
          background-color: rgb(254 226 226 / 0.95) !important;
        }
        .task-row-due-selected-day > td {
          border-top: 3px solid #dc2626 !important;
          border-bottom: 3px solid #dc2626 !important;
        }
        .task-row-due-selected-day > td:first-child {
          border-left: 3px solid #dc2626 !important;
        }
        .task-row-due-selected-day > td:last-child {
          border-right: 3px solid #dc2626 !important;
        }
        .task-card-due-selected-day {
          border: 3px solid #dc2626 !important;
          background-color: rgb(254 242 242 / 0.94) !important;
          box-shadow: 0 0 0 1px rgb(220 38 38 / 0.24);
        }
        .task-card-due-selected-day:hover {
          background-color: rgb(254 226 226 / 0.96) !important;
        }
        .daily-report-table th,
        .daily-report-table td {
          vertical-align: bottom;
          padding-bottom: 0;
          padding-top: 15px;
          direction: ltr;
          text-align: left;
        }
        .daily-report-table {
          border: 3px solid #0f172a !important;
          border-collapse: collapse;
        }
        .weekly-report-table th,
        .weekly-report-table td {
          vertical-align: bottom;
          padding-bottom: 0;
          padding-top: 15px;
          padding-left: 4px;
          padding-right: 4px;
          direction: ltr;
          text-align: left;
        }
        .weekly-notes-table td {
          vertical-align: top;
          padding: 6px;
          direction: ltr;
          text-align: left;
        }
        .weekly-notes-label {
          letter-spacing: 0.02em;
        }
        .weekly-notes-columns {
          display: grid;
          width: 100%;
        }
        .weekly-notes-column {
          padding: 0 6px;
        }
        .weekly-notes-column + .weekly-notes-column {
          border-left: 1px solid #94a3b8;
        }
        .weekly-notes-line {
          height: 12px;
          border-bottom: 1px solid #94a3b8;
        }
        .weekly-notes-line:last-child {
          border-bottom: 0;
        }
        .daily-report-table th:nth-child(3),
        .daily-report-table td:nth-child(3) {
          padding-left: 2px;
          padding-right: 2px;
        }
        .daily-report-table thead th {
          border-width: 2px;
          border-color: #cbd5e1;
        }
        .weekly-report-table thead th {
          border-width: 2px;
          border-color: #0f172a;
        }
        .daily-report-table thead tr {
          border-top: 2px solid #e2e8f0;
          border-bottom: 2px solid #e2e8f0;
        }
        @media print {
          * {
            box-sizing: border-box;
          }
          html, body {
            height: auto !important;
            min-height: 0 !important;
            overflow: visible !important;
            background: white;
          }
          aside, header, nav {
            display: none !important;
          }
          @page {
            margin: 0.25in 0.1in 0.35in 0.1in;
            size: landscape;
          }
          .print-page {
            position: relative;
            padding: 0.1in !important;
            margin: 0 !important;
            min-height: 0 !important;
            max-height: none !important;
            height: auto !important;
            overflow: visible !important;
            padding-bottom: 0.6in;
          }
          .print-page-measure {
            position: absolute;
            top: 0;
            left: 0;
            height: calc(8.5in - 0.25in - 0.35in);
            width: 1px;
            visibility: hidden;
            pointer-events: none;
          }
          .print-header {
            display: grid;
            grid-template-columns: 1fr auto 1fr;
            align-items: center;
            margin-top: 0.15in;
            margin-bottom: 0.2in;
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
          .print-meta {
            font-size: 11px;
            color: #334155;
            margin-bottom: 16px;
            display: grid;
            gap: 2px;
          }
          .print-footer {
            position: fixed;
            bottom: 0.1in;
            left: 0;
            right: 0;
            display: grid;
            grid-template-columns: 1fr auto 1fr;
            padding-left: 0.2in;
            padding-right: 0.2in;
            font-size: 10px;
            color: #334155;
          }
          .print-page-count {
            text-align: center;
          }
          .print-initials {
            text-align: right;
          }
          .print-page-marker {
            position: absolute;
            left: 0.1in;
            right: 0.1in;
            text-align: center;
            font-size: 10px;
            color: #334155;
            z-index: 5;
            display: none;
          }
          .weekly-report-table thead {
            display: table-header-group;
          }
          .weekly-report-table th,
          .weekly-report-table td,
          .daily-report-table th,
          .daily-report-table td {
            vertical-align: bottom !important;
            direction: ltr;
            text-align: left;
          }
          .weekly-report-table th,
          .weekly-report-table td {
            padding-bottom: 0;
            padding-top: 15px;
            padding-left: 4px;
            padding-right: 4px;
          }
          .daily-report-table th:nth-child(3),
          .daily-report-table td:nth-child(3) {
            padding-left: 2px;
            padding-right: 2px;
          }
          .weekly-report-table,
          .daily-report-table {
            table-layout: fixed;
            margin-bottom: 0.6in;
            page-break-inside: auto;
          }
          .daily-report-table tr {
            page-break-inside: avoid;
            page-break-after: auto;
          }
          .daily-report-table thead {
            display: table-header-group;
          }
          .daily-report-table tfoot {
            display: table-footer-group;
          }
          .weekly-report-table thead th {
            border-width: 2px;
          }
          .daily-report-table thead th {
            border: 2px solid #0f172a !important;
            background-color: #f1f5f9 !important;
            box-shadow: none !important;
            position: static !important;
            border-left: 2px solid #0f172a !important;
            border-right: 2px solid #0f172a !important;
          }
          .daily-report-table thead tr {
            border-top: 3px solid #0f172a !important;
            border-bottom: 3px solid #0f172a !important;
          }
          .daily-report-table th,
          .daily-report-table td {
            border: 1px solid #0f172a !important;
          }
          .daily-report-table .task-row-starts-selected-day > td {
            border-top: 3px solid #2563eb !important;
            border-bottom: 3px solid #2563eb !important;
          }
          .daily-report-table .task-row-starts-selected-day > td:first-child {
            border-left: 3px solid #2563eb !important;
          }
          .daily-report-table .task-row-starts-selected-day > td:last-child {
            border-right: 3px solid #2563eb !important;
          }
          .daily-report-table .task-row-due-selected-day > td {
            border-top: 3px solid #dc2626 !important;
            border-bottom: 3px solid #dc2626 !important;
          }
          .daily-report-table .task-row-due-selected-day > td:first-child {
            border-left: 3px solid #dc2626 !important;
          }
          .daily-report-table .task-row-due-selected-day > td:last-child {
            border-right: 3px solid #dc2626 !important;
          }
          .daily-report-table {
            border: 3px solid #0f172a !important;
            border-collapse: collapse !important;
            border-spacing: 0 !important;
          }
          .weekly-report-table {
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
          }
          .print-nr-cell {
            font-weight: 700;
          }
        }
      `}</style>
    </div>
  )
}


