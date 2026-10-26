
"use client"

import * as React from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { BoldOnlyEditor } from "@/components/bold-only-editor"
import { useConfirm } from "@/components/providers/confirm-dialog-provider"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import { useAuth } from "@/lib/auth"
import { formatDateTimeDMY } from "@/lib/dates"
import { formatDepartmentName } from "@/lib/department-name"
import { fetchUsersLookupCached } from "@/lib/users-cache"
import { toast } from "sonner"
import type {
  Department,
  SystemTaskFrequency,
  SystemTaskScope,
  SystemTaskTemplateDefinition,
  TaskFinishPeriod,
  TaskPriority,
  User,
  UserLookup,
} from "@/lib/types"

// --- Constants & Types ---

const EMPTY_VALUE = "__none__"
const ALL_DEPARTMENTS_VALUE = "__all_departments__"
const GA_DEPARTMENTS_VALUE = "__ga__"
const FIRST_WORKING_DAY_VALUE = "__first_working_day__"
const END_OF_MONTH_VALUE = "__end_of_month__"

const FREQUENCY_OPTIONS = [
  { value: "DAILY", label: "Daily" },
  { value: "WEEKLY", label: "Weekly" },
  { value: "MONTHLY", label: "Monthly" },
  { value: "3_MONTHS", label: "Every 3 months" },
  { value: "6_MONTHS", label: "Every 6 months" },
  { value: "YEARLY", label: "Yearly" },
] as const

const FREQUENCY_VALUES = FREQUENCY_OPTIONS.map((option) => option.value)
const COMBINED_FREQUENCIES: SystemTaskFrequency[] = ["3_MONTHS", "6_MONTHS"]

const FREQUENCY_CHIPS = [
  { id: "all", label: "All" },
  { id: "DAILY", label: "Daily" },
  { id: "WEEKLY", label: "Weekly" },
  { id: "MONTHLY", label: "Monthly" },
  { id: "3_6_MONTHS", label: "Every 3/6 months" },
  { id: "YEARLY", label: "Yearly" },
]

const PRIORITY_OPTIONS: TaskPriority[] = ["NORMAL", "HIGH"]

const PRIORITY_LABELS: Record<TaskPriority, string> = {
  NORMAL: "Normal",
  HIGH: "High",
  BLLOK: "Bllok",
}

const PRIORITY_BADGE_STYLES: Record<TaskPriority, string> = {
  NORMAL: "border-[#FDBA74] bg-[#FFEDD5] text-[#9A3412]",
  HIGH: "border-[#FCA5A5] bg-[#FEE2E2] text-[#B91C1C]",
  BLLOK: "border-[#A78BFA] bg-[#EDE9FE] text-[#6D28D9]",
}

// Restored specific left-border colors
const PRIORITY_BORDER_STYLES: Record<TaskPriority, string> = {
  NORMAL: "border-l-[#F97316]", // Specific Orange
  HIGH: "border-l-[#EF4444]",   // Specific Red
  BLLOK: "border-l-[#8B5CF6]",  // Specific Purple
}

const PRIORITY_SORT_ORDER: Record<TaskPriority, number> = {
  HIGH: 0,
  NORMAL: 1,
  BLLOK: 2,
}

const FINISH_PERIOD_OPTIONS: TaskFinishPeriod[] = ["AM", "PM"]
const FINISH_PERIOD_NONE_VALUE = EMPTY_VALUE
const FINISH_PERIOD_NONE_LABEL = "None (all day)"

const FINISH_PERIOD_LABELS: Record<TaskFinishPeriod, string> = {
  AM: "AM",
  PM: "PM",
}

const GA_EMAIL = "ga@primexeu.com"
const MAX_ASSIGNEES_REQUIRING_REPLACEMENTS = 9

function replacementsRequired(assigneeIds: string[]) {
  return assigneeIds.length > 0 && assigneeIds.length <= MAX_ASSIGNEES_REQUIRING_REPLACEMENTS
}

function replacementSelectionError(zv1UserId: string, zv2UserId: string, assigneeIds: string[]) {
  if (!zv1UserId && !zv2UserId && !replacementsRequired(assigneeIds)) return null
  if (!zv1UserId && replacementsRequired(assigneeIds)) {
    return "ZV1 is required for specifically assigned tasks."
  }
  if (zv1UserId && zv2UserId && zv1UserId === zv2UserId) {
    return "ZV1 and ZV2 must be different users."
  }
  if (assigneeIds.includes(zv1UserId) || assigneeIds.includes(zv2UserId)) {
    return "ZV1 and ZV2 cannot also be assignees."
  }
  return null
}

function timeInputValue(value?: string | null) {
  if (!value) return ""
  const match = String(value).match(/^(\d{2}:\d{2})/)
  if (match) return match[1]
  return String(value).slice(0, 5)
}

function userDisplayLabel(
  user?: {
    full_name?: string | null
    username?: string | null
    email?: string | null
  } | null
) {
  if (!user) return ""
  return user.full_name || user.username || user.email || ""
}

function userInitials(label: string) {
  const trimmed = label.trim()
  if (!trimmed) return "--"
  const base = trimmed.includes("@") ? trimmed.split("@")[0] : trimmed
  const tokens = base.match(/[A-Za-z0-9]+/g) || []
  if (tokens.length === 0) return base.slice(0, 2).toUpperCase()
  if (tokens.length === 1) return tokens[0].slice(0, 2).toUpperCase()
  const first = tokens[0]?.[0] ?? ""
  const last = tokens[tokens.length - 1]?.[0] ?? ""
  return `${first}${last}`.toUpperCase()
}

const MAX_ASSIGNEE_INITIALS = 10

const INTERNAL_NOTE_FIELDS = [
  { key: "REGJ", label: "REGJ", placeholder: "0" },
  { key: "PATH", label: "PATH", placeholder: "S:\\03_HOMEFACE\\04_PLAN PRODUTION\\2023" },
  { key: "CHECK", label: "CHECKLISTA", placeholder: "S:\\03_HOMEFACE\\01_CHECKLISTA\\01_CHECKLISTA" },
  { key: "TRAINING", label: "TRAINING", placeholder: "Z:\\03_HOMEFACE\\04_PLAN PRODUCTION" },
  { key: "BZ GROUP", label: "BZ GROUP", placeholder: "! BO PLAN PRODUCTION (PR 15:00 - H 10:00)" },
]

const INTERNAL_QA_FIELDS = [
  { key: "QA", label: "Question/Answer", placeholder: "" },
]

const WEEK_DAYS = [
  { value: "0", label: "Monday" },
  { value: "1", label: "Tuesday" },
  { value: "2", label: "Wednesday" },
  { value: "3", label: "Thursday" },
  { value: "4", label: "Friday" },
  { value: "5", label: "Saturday" },
  { value: "6", label: "Sunday" },
]
const WEEKDAY_OPTIONS = WEEK_DAYS.slice(0, 5)
const WEEKEND_OPTIONS = WEEK_DAYS.slice(5)

const MONTH_OPTIONS = Array.from({ length: 12 }, (_, index) => ({
  value: String(index + 1).padStart(2, "0"),
  label: new Date(0, index).toLocaleString("en-US", { month: "long" }),
}))

const DAY_OF_MONTH_OPTIONS = Array.from({ length: 31 }, (_, index) => ({
  value: String(index + 1),
  label: String(index + 1),
}))

// Define the grid layout once so header and body always match.
// Base columns: Order, Title (Flex), Department, Owner, Frequency, Finish, Priority, Actions
// Optional column: BZ Time (between Owner and Frequency)
// Responsive breakpoints:
// - sm (640px+): Compact layout with essential columns
// - md (768px+): Add more columns
// - lg (1024px+): More columns visible
// - xl (1280px+): Full columns
const BASE_GRID_CLASS = "grid grid-cols-[28px_minmax(130px,1fr)_70px_70px_70px_58px_40px_60px_60px] sm:grid-cols-[32px_minmax(160px,1fr)_88px_88px_88px_72px_50px_70px_70px] md:grid-cols-[32px_minmax(180px,1fr)_98px_98px_98px_82px_56px_75px_70px] lg:grid-cols-[32px_minmax(190px,1fr)_108px_108px_108px_90px_56px_80px_70px] xl:grid-cols-[36px_1fr_130px_130px_130px_110px_64px_100px_80px] gap-1.5 sm:gap-2 md:gap-2.5 lg:gap-3 xl:gap-4 items-center px-2 sm:px-3 md:px-4"
const GRID_WITH_BZ_TIME_CLASS = "grid grid-cols-[28px_minmax(120px,1fr)_64px_64px_68px_54px_62px_40px_58px_58px] sm:grid-cols-[32px_minmax(150px,1fr)_80px_80px_84px_60px_72px_48px_68px_68px] md:grid-cols-[32px_minmax(170px,1fr)_90px_90px_94px_66px_82px_54px_72px_68px] lg:grid-cols-[32px_minmax(180px,1fr)_100px_100px_104px_72px_90px_56px_78px_70px] xl:grid-cols-[36px_1fr_120px_120px_125px_80px_110px_64px_95px_80px] gap-1.5 sm:gap-2 md:gap-2.5 lg:gap-3 xl:gap-4 items-center px-2 sm:px-3 md:px-4"

type Section = {
  id: string
  label: string
  date: Date
  templates: SystemTaskTemplateDefinition[]
}

type ApprovalView = "approved" | "pending" | "rejected"

// --- Helpers ---

function resolveScope(value: string): SystemTaskScope {
  if (value === GA_DEPARTMENTS_VALUE) return "GA"
  if (value === ALL_DEPARTMENTS_VALUE) return "ALL"
  return "DEPARTMENT"
}

function resolveDepartmentId(value: string): string | null {
  return resolveScope(value) === "DEPARTMENT" ? value : null
}

function isCycleFrequency(value: SystemTaskFrequency | null | undefined) {
  return value === "3_MONTHS" || value === "6_MONTHS"
}

function isYearlyFrequency(value: SystemTaskFrequency | null | undefined) {
  return value === "YEARLY"
}

function resolveDayOfMonth(value: string): number | null {
  if (!value) return null
  if (value === END_OF_MONTH_VALUE) return 0
  if (value === FIRST_WORKING_DAY_VALUE) return -1
  return Number(value)
}

function resolveMonthOfYear(value: string): number | null {
  return value && value !== EMPTY_VALUE ? Number(value) : null
}

function isGlobalScopeValue(value: string) {
  return value === ALL_DEPARTMENTS_VALUE || value === GA_DEPARTMENTS_VALUE
}

function parseCSV(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ""
  let inQuotes = false

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i]
    if (inQuotes) {
      if (char === "\"") {
        const next = text[i + 1]
        if (next === "\"") {
          field += "\""
          i += 1
        } else {
          inQuotes = false
        }
      } else {
        field += char
      }
    } else if (char === "\"") {
      inQuotes = true
    } else if (char === ",") {
      row.push(field)
      field = ""
    } else if (char === "\n") {
      row.push(field)
      if (row.some((cell) => cell.trim().length)) rows.push(row)
      row = []
      field = ""
    } else if (char !== "\r") {
      field += char
    }
  }

  row.push(field)
  if (row.some((cell) => cell.trim().length)) rows.push(row)
  return rows
}

function csvEscape(value: unknown): string {
  const str = String(value ?? "")
  return /[",\n]/.test(str) ? `"${str.replace(/"/g, "\"\"")}"` : str
}

function normalizePriority(value?: TaskPriority | string | null): TaskPriority {
  const normalized = typeof value === "string" ? value.toUpperCase() : null
  if (normalized === "URGENT") return "HIGH"
  if (normalized === "LOW" || normalized === "MEDIUM") return "NORMAL"
  if (normalized === "NORMAL" || normalized === "HIGH") return normalized
  return "NORMAL"
}

function getMondayBasedDay(date: Date) {
  return (date.getDay() + 6) % 7
}

function getFirstWorkingDayOfMonth(year: number, monthIndex: number) {
  for (let day = 1; day <= 7; day += 1) {
    const date = new Date(year, monthIndex, day)
    const dayOfWeek = getMondayBasedDay(date)
    if (dayOfWeek <= 4) return day
  }
  return 1
}

function matchesTemplateDayOfWeek(template: SystemTaskTemplateDefinition, targetDay: number) {
  const configuredDays =
    template.days_of_week && template.days_of_week.length
      ? template.days_of_week
      : template.day_of_week != null
        ? [template.day_of_week]
        : []
  const effectiveDays = configuredDays.map((day) => (day > 4 ? 4 : day))
  return effectiveDays.includes(targetDay)
}

function scheduledDateForMonth(
  template: SystemTaskTemplateDefinition,
  year: number,
  monthIndex: number
) {
  const firstOfMonth = new Date(year, monthIndex, 1)
  const resolvedYear = firstOfMonth.getFullYear()
  const resolvedMonth = firstOfMonth.getMonth()
  const lastDay = new Date(resolvedYear, resolvedMonth + 1, 0).getDate()
  const templateDay = template.day_of_month
  if (templateDay == null) return null

  const resolvedDay =
    templateDay === 0
      ? lastDay
      : templateDay === -1
        ? getFirstWorkingDayOfMonth(resolvedYear, resolvedMonth)
        : Math.min(templateDay, lastDay)
  const scheduled = new Date(resolvedYear, resolvedMonth, resolvedDay)
  const weekday = scheduled.getDay()
  if (weekday === 6) scheduled.setDate(scheduled.getDate() - 1)
  if (weekday === 0) scheduled.setDate(scheduled.getDate() - 2)
  return scheduled
}

function sameLocalDate(left: Date | null, right: Date) {
  return Boolean(
    left &&
      left.getFullYear() === right.getFullYear() &&
      left.getMonth() === right.getMonth() &&
      left.getDate() === right.getDate()
  )
}

function matchesMonthCycle(template: SystemTaskTemplateDefinition, nominalMonth: number) {
  if (template.month_of_year == null) return true
  if (template.frequency === "3_MONTHS") {
    return (nominalMonth - template.month_of_year + 12) % 3 === 0
  }
  if (template.frequency === "6_MONTHS") {
    return (nominalMonth - template.month_of_year + 12) % 6 === 0
  }
  return true
}

function templateIntervalMatches(
  template: SystemTaskTemplateDefinition,
  target: Date,
  nominalYear = target.getFullYear(),
  nominalMonthIndex = target.getMonth()
) {
  const interval = Math.max(template.interval || 1, 1)
  if (interval === 1) return true
  const anchorValue = template.apply_from || template.created_at
  if (!anchorValue) return true
  const anchor = new Date(anchorValue)
  if (Number.isNaN(anchor.getTime())) return true

  if (template.frequency === "DAILY") {
    const anchorDay = new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate())
    const targetDay = new Date(target.getFullYear(), target.getMonth(), target.getDate())
    const days = Math.round((targetDay.getTime() - anchorDay.getTime()) / 86_400_000)
    return days >= 0 && days % interval === 0
  }
  if (template.frequency === "WEEKLY") {
    const anchorDay = new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate())
    const targetDay = new Date(target.getFullYear(), target.getMonth(), target.getDate())
    const days = Math.round((targetDay.getTime() - anchorDay.getTime()) / 86_400_000)
    return days >= 0 && Math.floor(days / 7) % interval === 0
  }
  if (template.frequency === "MONTHLY") {
    const months = (nominalYear - anchor.getFullYear()) * 12 + nominalMonthIndex - anchor.getMonth()
    return months >= 0 && months % interval === 0
  }
  if (template.frequency === "YEARLY") {
    const years = nominalYear - anchor.getFullYear()
    return years >= 0 && years % interval === 0
  }
  return true
}

function matchesTemplateDate(template: SystemTaskTemplateDefinition, date: Date) {
  const dayOfWeek = getMondayBasedDay(date)
  const monthIndex = date.getMonth()
  const year = date.getFullYear()

  if (template.frequency === "DAILY") {
    return dayOfWeek <= 4 && templateIntervalMatches(template, date)
  }
  if (template.frequency === "WEEKLY") {
    return (
      matchesTemplateDayOfWeek(template, dayOfWeek) &&
      templateIntervalMatches(template, date)
    )
  }

  if (template.frequency === "MONTHLY" || template.frequency === "3_MONTHS" || template.frequency === "6_MONTHS") {
    const currentMonthDate = scheduledDateForMonth(template, year, monthIndex)
    if (
      sameLocalDate(currentMonthDate, date) &&
      matchesMonthCycle(template, monthIndex + 1) &&
      templateIntervalMatches(template, date, year, monthIndex)
    ) {
      return true
    }
    const nextMonthDate = scheduledDateForMonth(template, year, monthIndex + 1)
    const nextNominalDate = new Date(year, monthIndex + 1, 1)
    return (
      sameLocalDate(nextMonthDate, date) &&
      matchesMonthCycle(template, nextNominalDate.getMonth() + 1) &&
      templateIntervalMatches(
        template,
        date,
        nextNominalDate.getFullYear(),
        nextNominalDate.getMonth()
      )
    )
  }

  if (template.frequency === "YEARLY") {
    if (template.month_of_year == null) return false
    const nominalMonthIndex = template.month_of_year - 1
    return (
      (sameLocalDate(scheduledDateForMonth(template, year, nominalMonthIndex), date) &&
        templateIntervalMatches(template, date, year, nominalMonthIndex)) ||
      (sameLocalDate(scheduledDateForMonth(template, year + 1, nominalMonthIndex), date) &&
        templateIntervalMatches(template, date, year + 1, nominalMonthIndex))
    )
  }

  return true
}

function parseInternalNotes(value?: string | null): Record<string, string> {
  const result: Record<string, string> = {}
  if (!value) return result
  
  // Create a mapping from label to key for all internal note fields
  const labelToKeyMap: Record<string, string> = {}
  for (const field of INTERNAL_NOTE_FIELDS) {
    // Map exact label (uppercase)
    labelToKeyMap[field.label.toUpperCase()] = field.key
    // Map normalized version (lowercase, no spaces)
    const normalizedLabel = field.label.toLowerCase().replace(/\s+/g, "")
    labelToKeyMap[normalizedLabel] = field.key
    // Also map the key itself (for backward compatibility)
    labelToKeyMap[field.key.toUpperCase()] = field.key
    labelToKeyMap[field.key.toLowerCase()] = field.key
  }
  
  const lines = value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
  for (const line of lines) {
    const idx = line.indexOf(":")
    if (idx === -1) continue
    const key = line.slice(0, idx).trim()
    const rest = line.slice(idx + 1).trim()
    if (!key) continue
    const normalizedKey = key.toLowerCase().replace(/\s+/g, "")
    
    // Handle QA fields
    if (normalizedKey === "qa" || normalizedKey === "question/answer" || normalizedKey === "questionanswer") {
      result.QA = rest
      continue
    }
    if (normalizedKey === "q1" || normalizedKey === "q2" || normalizedKey === "q3" || normalizedKey === "q4" || normalizedKey === "q5") {
      const existing = result.QA ? `${result.QA}\n${rest}` : rest
      result.QA = existing
      continue
    }
    
    // Map the label back to the key (e.g., "CHECKLISTA" -> "CHECK")
    // Try uppercase first, then normalized, then use original key
    const mappedKey = labelToKeyMap[key.toUpperCase()] || labelToKeyMap[normalizedKey] || key
    result[mappedKey] = rest
  }
  return result
}

function resolveTemplateScope(template: SystemTaskTemplateDefinition): SystemTaskScope {
  if (template.scope) return template.scope
  return template.department_id ? "DEPARTMENT" : "ALL"
}

function templateApprovalStatus(template: SystemTaskTemplateDefinition) {
  return template.approval_status ?? "approved"
}

type SystemTasksViewProps = {
  scopeFilter?: SystemTaskScope
  headingTitle?: string
  headingDescription?: string
  showSystemActions?: boolean
  showFilters?: boolean
  allowMarkAsDone?: boolean
  forceLoadAll?: boolean
  externalPriorityFilter?: TaskPriority | "all"
  externalDayFilter?: string | "all"
  externalDateFilter?: string | null
  alignmentUsernameFilter?: string | null
  showBzTimeColumn?: boolean
}

export function SystemTasksView({
  scopeFilter,
  headingTitle,
  headingDescription,
  showSystemActions = true,
  showFilters = true,
  allowMarkAsDone = false,
  forceLoadAll = false,
  externalPriorityFilter = "all",
  externalDayFilter = "all",
  externalDateFilter = null,
  alignmentUsernameFilter = null,
  showBzTimeColumn = false,
}: SystemTasksViewProps) {
  const { apiFetch, user } = useAuth()
  const confirm = useConfirm()
  type AssigneeUser = User | UserLookup
  const [templates, setTemplates] = React.useState<SystemTaskTemplateDefinition[]>([])
  const [departments, setDepartments] = React.useState<Department[]>([])
  const [users, setUsers] = React.useState<AssigneeUser[]>([])
  const [loading, setLoading] = React.useState(true)
  const [createOpen, setCreateOpen] = React.useState(false)
  const [editOpen, setEditOpen] = React.useState(false)
  const [saving, setSaving] = React.useState(false)
  const [editSaving, setEditSaving] = React.useState(false)
  const [deletingTemplateId, setDeletingTemplateId] = React.useState<string | null>(null)
  const [approvingTemplateId, setApprovingTemplateId] = React.useState<string | null>(null)
  const [rejectingTemplateId, setRejectingTemplateId] = React.useState<string | null>(null)
  const [rejectTemplate, setRejectTemplate] = React.useState<SystemTaskTemplateDefinition | null>(null)
  const [rejectReason, setRejectReason] = React.useState("")
  const [approvalView, setApprovalView] = React.useState<ApprovalView>("approved")
  const [frequencyFilters, setFrequencyFilters] = React.useState<SystemTaskFrequency[]>([])
  const [frequencyMultiSelect, setFrequencyMultiSelect] = React.useState(false)
  const [priorityFilters, setPriorityFilters] = React.useState<TaskPriority[]>([])
  const fileInputRef = React.useRef<HTMLInputElement | null>(null)
  const searchInputRef = React.useRef<HTMLInputElement | null>(null)
  const [searchQuery, setSearchQuery] = React.useState("")
  const [printing, setPrinting] = React.useState(false)
  const [exportingExcel, setExportingExcel] = React.useState(false)

  const [title, setTitle] = React.useState("")
  const [description, setDescription] = React.useState("")
  const [departmentId, setDepartmentId] = React.useState(
    scopeFilter === "GA" ? GA_DEPARTMENTS_VALUE : ""
  )
  const [assigneeIds, setAssigneeIds] = React.useState<string[]>([])
  const [zv1UserId, setZv1UserId] = React.useState("")
  const [zv2UserId, setZv2UserId] = React.useState("")
  const [assigneeQuery, setAssigneeQuery] = React.useState("")
  const [assigneeError, setAssigneeError] = React.useState<string | null>(null)
  const [assigneeOpen, setAssigneeOpen] = React.useState(false)
  const [frequency, setFrequency] = React.useState<SystemTaskFrequency>("DAILY")
  const [priority, setPriority] = React.useState<TaskPriority>("NORMAL")
  const [finishPeriod, setFinishPeriod] = React.useState<TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE>(
    FINISH_PERIOD_NONE_VALUE
  )
  const [internalNotes, setInternalNotes] = React.useState<Record<string, string>>({})
  const createDetailsRef = React.useRef<HTMLDetailsElement>(null)
  const [daysOfWeek, setDaysOfWeek] = React.useState<string[]>([])
  const [dayOfMonth, setDayOfMonth] = React.useState("")
  const [monthOfYear, setMonthOfYear] = React.useState(EMPTY_VALUE)
  const [isActive, setIsActive] = React.useState(true)
  const [showInWeeklyPlanner, setShowInWeeklyPlanner] = React.useState(false)
  const [isRepetitive, setIsRepetitive] = React.useState(false)
  const [requiresAlignment, setRequiresAlignment] = React.useState(false)
  const [alignmentTime, setAlignmentTime] = React.useState("")
  const [alignmentManagerIds, setAlignmentManagerIds] = React.useState<string[]>([])
  const [showWeekendDays, setShowWeekendDays] = React.useState(false)
  const [editTemplate, setEditTemplate] = React.useState<SystemTaskTemplateDefinition | null>(null)
  const [editTitle, setEditTitle] = React.useState("")
  const [editDescription, setEditDescription] = React.useState("")
  const [editDepartmentId, setEditDepartmentId] = React.useState("")
  const [editAssigneeIds, setEditAssigneeIds] = React.useState<string[]>([])
  const [editZv1UserId, setEditZv1UserId] = React.useState("")
  const [editZv2UserId, setEditZv2UserId] = React.useState("")
  const [editAssigneeQuery, setEditAssigneeQuery] = React.useState("")
  const [editAssigneeError, setEditAssigneeError] = React.useState<string | null>(null)
  const [editAssigneeOpen, setEditAssigneeOpen] = React.useState(false)
  const [editFrequency, setEditFrequency] = React.useState<SystemTaskFrequency>("DAILY")
  const [editPriority, setEditPriority] = React.useState<TaskPriority>("NORMAL")
  const [editFinishPeriod, setEditFinishPeriod] = React.useState<TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE>(
    FINISH_PERIOD_NONE_VALUE
  )
  const [editInternalNotes, setEditInternalNotes] = React.useState<Record<string, string>>({})
  const [editDaysOfWeek, setEditDaysOfWeek] = React.useState<string[]>([])
  const [editDayOfMonth, setEditDayOfMonth] = React.useState("")
  const [editMonthOfYear, setEditMonthOfYear] = React.useState(EMPTY_VALUE)
  const [editIsActive, setEditIsActive] = React.useState(true)
  const [editShowInWeeklyPlanner, setEditShowInWeeklyPlanner] = React.useState(false)
  const [editIsRepetitive, setEditIsRepetitive] = React.useState(false)
  const [editRequiresAlignment, setEditRequiresAlignment] = React.useState(false)
  const [editAlignmentTime, setEditAlignmentTime] = React.useState("")
  const [editAlignmentManagerIds, setEditAlignmentManagerIds] = React.useState<string[]>([])
  const [editShowWeekendDays, setEditShowWeekendDays] = React.useState(false)

  const isAdmin = user?.role === "ADMIN"
  const isManagerOrAdmin = isAdmin || user?.role === "MANAGER"
  const canCreate = showSystemActions

  // Email is the authoritative identity for Gane in the System Tasks workflow.
  const ganeUser = React.useMemo(
    () => users.find((u) => u.email?.trim().toLowerCase() === GA_EMAIL) ?? null,
    [users]
  )
  const ganeUserId = React.useMemo(() => ganeUser?.id ?? null, [ganeUser])
  const alignmentFilterUserId = React.useMemo(() => {
    if (!alignmentUsernameFilter) return null
    const normalized = alignmentUsernameFilter.toLowerCase()
    return users.find((u) => u.username?.toLowerCase() === normalized)?.id ?? null
  }, [alignmentUsernameFilter, users])

  const load = React.useCallback(async () => {
    setLoading(true)
    try {
      const [templatesRes, departmentsRes] = await Promise.all([
        apiFetch("/system-tasks/templates"),
        apiFetch("/departments"),
      ])
      if (templatesRes.ok) {
        const rows = (await templatesRes.json()) as SystemTaskTemplateDefinition[]
        const groupedByTemplate = new Map<
          string,
          typeof rows[0] & { assignees: typeof rows[0]["assignees"]; department_ids?: string[] }
        >()
        for (const row of rows) {
          const key = String(row.id)
          if (groupedByTemplate.has(key)) {
            const existing = groupedByTemplate.get(key)!
            const existingAssigneeIds = new Set(existing.assignees?.map((a) => a.id) || [])
            const newAssignees = (row.assignees || []).filter((a) => !existingAssigneeIds.has(a.id))
            if (newAssignees.length > 0) {
              existing.assignees = [...(existing.assignees || []), ...newAssignees]
            }
            const existingDeptIds = new Set(existing.department_ids || [])
            if (row.department_id && !existingDeptIds.has(row.department_id)) {
              existing.department_ids = [...(existing.department_ids || []), row.department_id]
            }
            if ((row as { department_ids?: string[] }).department_ids) {
              for (const deptId of (row as { department_ids?: string[] }).department_ids || []) {
                if (!existingDeptIds.has(deptId)) {
                  existing.department_ids = [...(existing.department_ids || []), deptId]
                }
              }
            }
            if (row.status === "DONE" && existing.status !== "DONE") {
              existing.status = row.status
            }
            if (!existing.id) {
              existing.id = row.id
            }
          } else {
            const deptIds: string[] = []
            if (row.department_id) {
              deptIds.push(row.department_id)
            }
            if ((row as { department_ids?: string[] }).department_ids) {
              for (const deptId of (row as { department_ids?: string[] }).department_ids || []) {
                if (!deptIds.includes(deptId)) {
                  deptIds.push(deptId)
                }
              }
            }
            groupedByTemplate.set(key, {
              ...row,
              assignees: row.assignees || [],
              department_ids: deptIds.length > 0 ? deptIds : undefined,
            })
          }
        }
        setTemplates(Array.from(groupedByTemplate.values()))
      } else {
        console.error("Failed to load system tasks", templatesRes.status)
      }
      if (departmentsRes.ok) {
        setDepartments((await departmentsRes.json()) as Department[])
      } else {
        console.error("Failed to load departments", departmentsRes.status)
      }
      if (isManagerOrAdmin) {
        const usersRes = await apiFetch("/users")
        if (usersRes.ok) {
          setUsers((await usersRes.json()) as AssigneeUser[])
        } else {
          console.error("Failed to load users", usersRes.status)
        }
      } else {
        const usersList = await fetchUsersLookupCached(apiFetch)
        if (usersList) setUsers(usersList as AssigneeUser[])
        else console.error("Failed to load users")
      }
    } finally {
      setLoading(false)
    }
  }, [apiFetch, isManagerOrAdmin])

  React.useEffect(() => {
    void load()
  }, [load])

  const gridClass = React.useMemo(
    () => (showBzTimeColumn ? GRID_WITH_BZ_TIME_CLASS : BASE_GRID_CLASS),
    [showBzTimeColumn]
  )

  React.useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault()
        searchInputRef.current?.focus()
      }
    }
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [])

  React.useEffect(() => {
    if (departments.length === 0) return
    if (!departmentId) {
      setDepartmentId(scopeFilter === "GA" ? GA_DEPARTMENTS_VALUE : ALL_DEPARTMENTS_VALUE)
    }
  }, [departments, departmentId, scopeFilter, user?.department_id])


  React.useEffect(() => {
    if (!editTemplate) return
    setEditTitle(editTemplate.title || "")
    setEditDescription(editTemplate.description || "")
    const editDeptValue =
      editTemplate.scope === "GA"
        ? GA_DEPARTMENTS_VALUE
        : editTemplate.scope === "ALL"
          ? ALL_DEPARTMENTS_VALUE
          : editTemplate.department_id ?? ALL_DEPARTMENTS_VALUE
    setEditDepartmentId(editDeptValue)
    const listedAssigneeIds = editTemplate.assignees?.map((assignee) => assignee.id) ?? []
    const activeSlotAssigneeIds = (editTemplate.assignee_slots ?? [])
      .filter((slot) => slot.is_active)
      .map((slot) => slot.primary_user_id)
    const editIds = listedAssigneeIds.length
      ? listedAssigneeIds
      : editTemplate.default_assignee_id
        ? [editTemplate.default_assignee_id]
        : activeSlotAssigneeIds
    setEditAssigneeIds(editIds)
    setEditZv1UserId(editTemplate.zv1_user_id || "")
    setEditZv2UserId(editTemplate.zv2_user_id || "")
    setEditFrequency(editTemplate.frequency)
    setEditPriority(normalizePriority(editTemplate.priority))
    setEditFinishPeriod(editTemplate.finish_period ?? FINISH_PERIOD_NONE_VALUE)
    setEditInternalNotes(parseInternalNotes(editTemplate.internal_notes))
    const editDays =
      editTemplate.days_of_week && editTemplate.days_of_week.length
        ? editTemplate.days_of_week
        : editTemplate.day_of_week != null
          ? [editTemplate.day_of_week]
          : []
    setEditDaysOfWeek(editDays.map((value) => String(value)))
    setEditDayOfMonth(
      editTemplate.day_of_month === 0
        ? END_OF_MONTH_VALUE
        : editTemplate.day_of_month === -1
          ? FIRST_WORKING_DAY_VALUE
          : editTemplate.day_of_month != null
            ? String(editTemplate.day_of_month)
            : ""
    )
    setEditMonthOfYear(
      editTemplate.month_of_year != null
        ? String(editTemplate.month_of_year).padStart(2, "0")
        : EMPTY_VALUE
    )
    setEditIsActive(editTemplate.is_active)
    setEditShowInWeeklyPlanner(Boolean(editTemplate.show_in_weekly_planner))
    setEditIsRepetitive(Boolean(editTemplate.is_repetitive))
    setEditRequiresAlignment(Boolean(editTemplate.requires_alignment))
    setEditAlignmentTime(timeInputValue(editTemplate.alignment_time))
    setEditAlignmentManagerIds(editTemplate.alignment_user_ids ?? [])
    setEditAssigneeQuery("")
    setEditAssigneeError(null)
  }, [editTemplate])

  const departmentMap = React.useMemo(() => {
    return new Map(departments.map((dept) => [dept.id, dept]))
  }, [departments])

  const userMap = React.useMemo(() => {
    return new Map(users.map((u) => [u.id, u]))
  }, [users])

  const departmentNamesForOwnerIds = React.useCallback(
    (ownerIds: string[]) => {
      const ids = new Set<string>()
      for (const ownerId of ownerIds) {
        const deptId = userMap.get(ownerId)?.department_id
        if (deptId) ids.add(deptId)
      }
      return Array.from(ids)
        .map((id) => departmentMap.get(id)?.name)
        .filter((name): name is string => Boolean(name))
    },
    [departmentMap, userMap]
  )

  const departmentNamesForAssignees = React.useCallback(
    (assignees?: SystemTaskTemplateDefinition["assignees"]) => {
      if (!assignees || assignees.length === 0) return []
      return departmentNamesForOwnerIds(assignees.map((assignee) => assignee.id))
    },
    [departmentNamesForOwnerIds]
  )

  const templateDepartmentLabel = React.useCallback(
    (template: SystemTaskTemplateDefinition) => {
      const scope = resolveTemplateScope(template)
      const assigneeDeptCodes = template.assignees
        ? Array.from(
            new Set(
              template.assignees
                .map((a) => {
                  const userDeptId = a.department_id || userMap.get(a.id || "")?.department_id
                  return userDeptId ? departmentMap.get(userDeptId)?.code : null
                })
                .filter(Boolean) as string[]
            )
          )
        : []

      if (assigneeDeptCodes.length) return assigneeDeptCodes.join(" / ")
      if (scope === "GA") return "GA"
      if (scope === "ALL") return "ALL"
      return "-"
    },
    [departmentMap, userMap]
  )

  const formatDepartmentNames = React.useCallback((names: string[]) => {
    if (!names.length) return "All departments"
    const formatted = names.map((name) => formatDepartmentName(name))
    if (formatted.length === 1) return formatted[0]
    if (formatted.length === 2) return `${formatted[0]}, ${formatted[1]}`
    return `${formatted[0]}, ${formatted[1]} +${formatted.length - 2}`
  }, [])

  const ownerDepartmentId = React.useCallback(
    (ownerId: string) => userMap.get(ownerId)?.department_id ?? null,
    [userMap]
  )

  const isAssigneeAllowedForDepartment = React.useCallback(
    (deptId: string, ownerId: string) => {
      if (!deptId || isGlobalScopeValue(deptId)) return true
      const ownerDept = ownerDepartmentId(ownerId)
      if (!ownerDept) return true
      return ownerDept === deptId
    },
    [ownerDepartmentId]
  )

  const validateOwners = React.useCallback(
    (deptId: string, ownerIds: string[]) => {
      // Allow users from different departments - no validation needed
      return { ok: true }
    },
    []
  )

  const handleDepartmentChange = (nextDeptId: string) => {
    setDepartmentId(nextDeptId)
    // Allow users from any department - no filtering needed
    setAssigneeError(null)
  }

  const handleEditDepartmentChange = (nextDeptId: string) => {
    setEditDepartmentId(nextDeptId)
    // Allow users from any department - no filtering needed
    setEditAssigneeError(null)
  }

  const handleAssigneesChange = (nextOwnerIds: string[]) => {
    if (!nextOwnerIds.length) {
      setAssigneeIds([])
      setAssigneeError(null)
      return
    }
    
    // Allow assignees across departments; adjust department selection to ALL if mixed.
    const assigneeDepartments = new Set<string>()
    for (const id of nextOwnerIds) {
      const deptId = ownerDepartmentId(id)
      if (deptId) assigneeDepartments.add(deptId)
    }
    if (assigneeDepartments.size > 1 && !isGlobalScopeValue(departmentId)) {
      setDepartmentId(ALL_DEPARTMENTS_VALUE)
    } else if (assigneeDepartments.size === 1 && !isGlobalScopeValue(departmentId)) {
      const [singleDept] = Array.from(assigneeDepartments)
      if (singleDept) setDepartmentId(singleDept)
    }
    
    setAssigneeIds(nextOwnerIds)
    setAssigneeError(null)
  }

  const handleEditAssigneesChange = (nextOwnerIds: string[]) => {
    if (!nextOwnerIds.length) {
      setEditAssigneeIds([])
      setEditAssigneeError(null)
      return
    }
    
    // Allow assignees across departments; adjust department selection to ALL if mixed.
    const assigneeDepartments = new Set<string>()
    for (const id of nextOwnerIds) {
      const deptId = ownerDepartmentId(id)
      if (deptId) assigneeDepartments.add(deptId)
    }
    if (assigneeDepartments.size > 1 && !isGlobalScopeValue(editDepartmentId)) {
      setEditDepartmentId(ALL_DEPARTMENTS_VALUE)
    } else if (assigneeDepartments.size === 1 && !isGlobalScopeValue(editDepartmentId)) {
      const [singleDept] = Array.from(assigneeDepartments)
      if (singleDept) setEditDepartmentId(singleDept)
    }
    
    setEditAssigneeIds(nextOwnerIds)
    setEditAssigneeError(null)
  }

  const removeAssignee = (id: string) => {
    handleAssigneesChange(assigneeIds.filter((item) => item !== id))
  }

  const removeEditAssignee = (id: string) => {
    handleEditAssigneesChange(editAssigneeIds.filter((item) => item !== id))
  }

  // Find GA department by code
  const gaDepartmentId = React.useMemo(() => {
    const gaDept = departments.find((dept) => dept.code?.toUpperCase() === "GA")
    return gaDept?.id ?? null
  }, [departments])

  const scopeTemplates = React.useMemo(() => {
    if (!scopeFilter) return templates

    // GA view: show any template where Gane is an assignee OR the template is scoped to GA department.
    if (scopeFilter === "GA") {
      const isAssignedToGane = (template: SystemTaskTemplateDefinition) =>
        (ganeUserId &&
          (template.default_assignee_id === ganeUserId ||
            template.assignees?.some((assignee) => assignee.id === ganeUserId))) ||
        template.assignees?.some((assignee) => assignee.email?.trim().toLowerCase() === GA_EMAIL)

      const isGaDepartment = (template: SystemTaskTemplateDefinition) =>
        template.scope === "GA" || (gaDepartmentId ? template.department_id === gaDepartmentId : false)

      return templates.filter((template) => isAssignedToGane(template) || isGaDepartment(template))
    }

    return templates.filter((template) => resolveTemplateScope(template) === scopeFilter)
  }, [scopeFilter, templates, ganeUserId, gaDepartmentId])

  const filteredByAlignmentUser = React.useMemo(() => {
    if (!alignmentUsernameFilter) return scopeTemplates
    if (!alignmentFilterUserId) return []
    return scopeTemplates.filter((template) =>
      template.alignment_user_ids?.includes(alignmentFilterUserId)
    )
  }, [alignmentFilterUserId, alignmentUsernameFilter, scopeTemplates])

  const frequencyCounts = React.useMemo(() => {
    const counts = new Map<SystemTaskFrequency, number>()
    for (const value of FREQUENCY_VALUES) {
      counts.set(value as SystemTaskFrequency, 0)
    }
    for (const template of filteredByAlignmentUser) {
      counts.set(template.frequency, (counts.get(template.frequency) || 0) + 1)
    }
    return counts
  }, [filteredByAlignmentUser])

  const priorityCounts = React.useMemo(() => {
    const counts = new Map<TaskPriority, number>()
    for (const value of PRIORITY_OPTIONS) {
      counts.set(value, 0)
    }
    for (const template of filteredByAlignmentUser) {
      const normalized = normalizePriority(template.priority)
      counts.set(normalized, (counts.get(normalized) || 0) + 1)
    }
    return counts
  }, [filteredByAlignmentUser])

  const filteredTemplates = React.useMemo(() => {
    let filtered = filteredByAlignmentUser
    const query = searchQuery.trim().toLowerCase()
    const dayFilterValue =
      externalDayFilter === "all" ? null : Number.isNaN(Number(externalDayFilter)) ? null : Number(externalDayFilter)
    const dateValue = externalDateFilter ? new Date(`${externalDateFilter}T00:00:00`) : null
    const hasValidDate = Boolean(dateValue && !Number.isNaN(dateValue.getTime()))

    if (externalPriorityFilter !== "all") {
      filtered = filtered.filter((template) => normalizePriority(template.priority) === externalPriorityFilter)
    }
    if (hasValidDate && dateValue) {
      filtered = filtered.filter((template) => matchesTemplateDate(template, dateValue))
    }
    if (dayFilterValue != null) {
      filtered = filtered.filter((template) => {
        if (template.frequency === "DAILY") return true
        if (matchesTemplateDayOfWeek(template, dayFilterValue)) return true
        return false
      })
    }
    if (query) {
      filtered = filtered.filter((template) => {
        const title = template.title?.toLowerCase() || ""
        const description = template.description?.toLowerCase() || ""
        return title.includes(query) || description.includes(query)
      })
    }
    if (frequencyFilters.length) {
      const allowed = new Set(frequencyFilters)
      filtered = filtered.filter((template) => allowed.has(template.frequency))
    }
    if (priorityFilters.length) {
      const allowed = new Set(priorityFilters)
      filtered = filtered.filter((template) => allowed.has(normalizePriority(template.priority)))
    }
    return filtered
  }, [
    externalDateFilter,
    externalDayFilter,
    externalPriorityFilter,
    frequencyFilters,
    priorityFilters,
    filteredByAlignmentUser,
    searchQuery,
  ])

  const pendingTemplates = React.useMemo(
    () => filteredTemplates.filter((template) => templateApprovalStatus(template) === "pending"),
    [filteredTemplates]
  )

  const rejectedTemplates = React.useMemo(
    () => filteredTemplates.filter((template) => templateApprovalStatus(template) === "rejected"),
    [filteredTemplates]
  )

  const approvedTemplates = React.useMemo(
    () => filteredTemplates.filter((template) => templateApprovalStatus(template) === "approved"),
    [filteredTemplates]
  )

  React.useEffect(() => {
    const combinedSelected =
      COMBINED_FREQUENCIES.every((value) => frequencyFilters.includes(value)) &&
      frequencyFilters.length >= COMBINED_FREQUENCIES.length
    if (!frequencyMultiSelect && frequencyFilters.length > 1 && !combinedSelected) {
      setFrequencyFilters([frequencyFilters[0]])
    }
  }, [frequencyFilters, frequencyMultiSelect])

  const sections = React.useMemo<Section[]>(() => {
    const frequencyOrder: Record<SystemTaskFrequency, number> = {
      DAILY: 0,
      WEEKLY: 1,
      MONTHLY: 2,
      "3_MONTHS": 3,
      "6_MONTHS": 4,
      YEARLY: 5,
    }
    const sorted = [...approvedTemplates].sort((a, b) => {
      const aInactive = !a.is_active
      const bInactive = !b.is_active
      if (aInactive !== bInactive) return aInactive ? 1 : -1
      const aFrequency = frequencyOrder[a.frequency]
      const bFrequency = frequencyOrder[b.frequency]
      if (aFrequency !== bFrequency) return aFrequency - bFrequency
      const aPriority = PRIORITY_SORT_ORDER[normalizePriority(a.priority)]
      const bPriority = PRIORITY_SORT_ORDER[normalizePriority(b.priority)]
      if (aPriority !== bPriority) return aPriority - bPriority
      const aCreated = a.created_at ? new Date(a.created_at).getTime() : 0
      const bCreated = b.created_at ? new Date(b.created_at).getTime() : 0
      if (aCreated !== bCreated) return bCreated - aCreated
      return a.title.localeCompare(b.title)
    })
    return [
      {
        id: "all-templates",
        label: "All System Tasks",
        date: new Date(),
        templates: sorted,
      },
    ]
  }, [approvedTemplates])

  const resetFilters = () => {
    setFrequencyFilters([])
    setFrequencyMultiSelect(false)
    setPriorityFilters([])
  }

  const toggleFrequencyFilter = (value: SystemTaskFrequency | "all" | "3_6_MONTHS") => {
    if (value === "all") {
      setFrequencyFilters([])
      return
    }
    if (value === "3_6_MONTHS") {
      setFrequencyFilters((prev) => {
        const hasCombined = COMBINED_FREQUENCIES.every((item) => prev.includes(item))
        const remaining = prev.filter((item) => !COMBINED_FREQUENCIES.includes(item))
        if (hasCombined) {
          return remaining
        }
        if (frequencyMultiSelect) {
          return [...remaining, ...COMBINED_FREQUENCIES]
        }
        return [...COMBINED_FREQUENCIES]
      })
      return
    }
    setFrequencyFilters((prev) => {
      if (prev.includes(value)) {
        return prev.filter((item) => item !== value)
      }
      if (frequencyMultiSelect) {
        return [...prev, value]
      }
      return [value]
    })
  }

  const submit = async () => {
    if (!departmentId) return
    const missingDetail = INTERNAL_NOTE_FIELDS.find(
      (field) => !internalNotes[field.key]?.trim()
    )
    if (missingDetail) {
      toast.error(`${missingDetail.label} is required.`)
      const details = createDetailsRef.current
      if (details) {
        details.open = true
        details.querySelector<HTMLInputElement | HTMLTextAreaElement>(
          `[name="${missingDetail.key}"]`
        )?.focus()
      }
      return
    }
    // Check if assignees are from different departments - if so, use ALL scope
    const assigneeDepartments = new Set<string>()
    for (const id of assigneeIds) {
      const deptId = ownerDepartmentId(id)
      if (deptId) {
        assigneeDepartments.add(deptId)
      }
    }
    // If assignees are from multiple departments, use ALL scope
    let finalDeptId = departmentId
    if (assigneeDepartments.size > 1 && !isGlobalScopeValue(departmentId)) {
      finalDeptId = ALL_DEPARTMENTS_VALUE
    }
    const scope = resolveScope(finalDeptId)
    const weeklyDays = frequency === "WEEKLY" ? normalizeDayValues(daysOfWeek) : []
    const resolvedDayOfMonth = resolveDayOfMonth(dayOfMonth)
    const resolvedMonthOfYear = resolveMonthOfYear(monthOfYear)
    if (isCycleFrequency(frequency) && (resolvedDayOfMonth == null || resolvedMonthOfYear == null)) {
      toast.error("Day of month and start month are required for 3/6-month tasks.")
      return
    }
    if (isYearlyFrequency(frequency) && resolvedMonthOfYear == null) {
      toast.error("Start month is required for yearly tasks.")
      return
    }
    if (requiresAlignment && !alignmentTime) {
      toast.error("BZ time is required when BZ is enabled.")
      return
    }
    const replacementError = replacementSelectionError(zv1UserId, zv2UserId, assigneeIds)
    if (replacementError) {
      toast.error(replacementError)
      return
    }
    setSaving(true)
    try {
      const payload = {
        title: title.trim(),
        description: description.trim() || null,
        scope,
        department_id: resolveDepartmentId(finalDeptId),
        assignee_ids: assigneeIds,
        zv1_user_id: zv1UserId || null,
        zv2_user_id: zv2UserId || null,
        frequency,
        priority,
        finish_period: finishPeriod === FINISH_PERIOD_NONE_VALUE ? null : finishPeriod,
        internal_notes: buildInternalNotes(internalNotes),
        requires_alignment: requiresAlignment,
        show_in_weekly_planner: showInWeeklyPlanner,
        is_repetitive: isRepetitive,
        alignment_time: requiresAlignment ? alignmentTime : null,
        alignment_roles: requiresAlignment ? ["MANAGER"] : [],
        alignment_user_ids: requiresAlignment ? alignmentManagerIds : [],
        day_of_week: weeklyDays.length ? weeklyDays[0] : null,
        days_of_week: weeklyDays.length ? weeklyDays : null,
        day_of_month:
          resolvedDayOfMonth,
        month_of_year:
          resolvedMonthOfYear,
        is_active: isActive,
      }
      const res = await apiFetch("/system-tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        let detail = "Failed to create system task"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(typeof detail === "string" ? detail : "An error occurred")
        return
      }
      setCreateOpen(false)
      setTitle("")
      setDescription("")
      setAssigneeIds([])
      setZv1UserId("")
      setZv2UserId("")
      setAssigneeQuery("")
      setAssigneeError(null)
      setDaysOfWeek([])
      setDayOfMonth("")
      setMonthOfYear(EMPTY_VALUE)
      setFrequency("DAILY")
      setPriority("NORMAL")
      setFinishPeriod(FINISH_PERIOD_NONE_VALUE)
      setInternalNotes({})
      setIsActive(true)
      setShowInWeeklyPlanner(false)
      setIsRepetitive(false)
      setRequiresAlignment(false)
      setAlignmentTime("")
      setAlignmentManagerIds([])
      await load()
      toast.success("System task submitted for approval")
    } finally {
      setSaving(false)
    }
  }

  const togglePriorityFilter = (value: TaskPriority | "all") => {
    if (value === "all") {
      setPriorityFilters([])
      return
    }
    setPriorityFilters([value])
  }

  const canEditTemplate = React.useCallback(
    (template?: SystemTaskTemplateDefinition | null) => {
      if (!template) return false
      if (!showSystemActions || !user) return false
      if (isManagerOrAdmin) return true
      const assigneeIds = new Set<string>()
      if (template.default_assignee_id) assigneeIds.add(template.default_assignee_id)
      if (template.assignees && template.assignees.length) {
        for (const person of template.assignees) {
          assigneeIds.add(person.id)
        }
      }
      return assigneeIds.has(user.id)
    },
    [isManagerOrAdmin, showSystemActions, user]
  )

  const startEdit = (template: SystemTaskTemplateDefinition) => {
    if (!canEditTemplate(template)) return
    setEditTemplate(template)
    setEditOpen(true)
  }

  const submitEdit = async () => {
    if (!editTemplate || !editTitle.trim()) return
    // Check if assignees are from different departments - if so, use ALL scope
    const assigneeDepartments = new Set<string>()
    for (const id of editAssigneeIds) {
      const deptId = ownerDepartmentId(id)
      if (deptId) {
        assigneeDepartments.add(deptId)
      }
    }
    // If assignees are from multiple departments, use ALL scope
    let finalDeptId = editDepartmentId
    if (assigneeDepartments.size > 1 && !isGlobalScopeValue(editDepartmentId)) {
      finalDeptId = ALL_DEPARTMENTS_VALUE
    }
    const scope = resolveScope(finalDeptId)
    const weeklyDays = editFrequency === "WEEKLY" ? normalizeDayValues(editDaysOfWeek) : []
    const resolvedEditDayOfMonth = resolveDayOfMonth(editDayOfMonth)
    const resolvedEditMonthOfYear = resolveMonthOfYear(editMonthOfYear)
    const originalDay = editTemplate.day_of_month ?? null
    const originalMonth = editTemplate.month_of_year ?? null
    const scheduleChanged =
      editFrequency !== editTemplate.frequency ||
      resolvedEditDayOfMonth !== originalDay ||
      resolvedEditMonthOfYear !== originalMonth
    if (
      isCycleFrequency(editFrequency) &&
      scheduleChanged &&
      (resolvedEditDayOfMonth == null || resolvedEditMonthOfYear == null)
    ) {
      toast.error("Day of month and start month are required for 3/6-month tasks.")
      return
    }
    if (isYearlyFrequency(editFrequency) && scheduleChanged && resolvedEditMonthOfYear == null) {
      toast.error("Start month is required for yearly tasks.")
      return
    }
    if (editRequiresAlignment && !editAlignmentTime) {
      toast.error("BZ time is required when BZ is enabled.")
      return
    }
    const replacementError = replacementSelectionError(editZv1UserId, editZv2UserId, editAssigneeIds)
    if (replacementError) {
      toast.error(replacementError)
      return
    }
    setEditSaving(true)
    try {
      const payload = {
        title: editTitle.trim(),
        description: editDescription.trim() || null,
        scope,
        department_id: resolveDepartmentId(finalDeptId),
        assignee_ids: editAssigneeIds,
        zv1_user_id: editZv1UserId || null,
        zv2_user_id: editZv2UserId || null,
        frequency: editFrequency,
        priority: editPriority,
        finish_period: editFinishPeriod === FINISH_PERIOD_NONE_VALUE ? null : editFinishPeriod,
        internal_notes: buildInternalNotes(editInternalNotes),
        requires_alignment: editRequiresAlignment,
        show_in_weekly_planner: editShowInWeeklyPlanner,
        is_repetitive: editIsRepetitive,
        alignment_time: editRequiresAlignment ? editAlignmentTime : null,
        alignment_roles: editRequiresAlignment ? ["MANAGER"] : [],
        alignment_user_ids: editRequiresAlignment ? editAlignmentManagerIds : [],
        day_of_week: weeklyDays.length ? weeklyDays[0] : null,
        days_of_week: weeklyDays.length ? weeklyDays : null,
        day_of_month:
          resolvedEditDayOfMonth,
        month_of_year:
          resolvedEditMonthOfYear,
        is_active: editIsActive,
      }
      const templateId = editTemplate.id
      const res = await apiFetch(`/system-tasks/${templateId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        let detail = "Failed to update system task"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(typeof detail === "string" ? detail : "An error occurred")
        return
      }
      const updated = (await res.json()) as SystemTaskTemplateDefinition
      setTemplates((prev) =>
        prev.map((item) => (item.id === updated.id ? updated : item))
      )
      setEditOpen(false)
      setEditTemplate(null)
      setEditAssigneeError(null)
      // Reload to refresh the list, but the updated template should already be in the list
      await load()
    } finally {
      setEditSaving(false)
    }
  }

  const deleteTemplate = async (template: SystemTaskTemplateDefinition) => {
    const templateId = template.id
    const templateTitle = template.title || "this system task"

    const confirmed = await confirm({
      title: "Delete system task",
      description: `Are you sure you want to delete the system task "${templateTitle}"? This action cannot be undone and will also delete all associated tasks.`,
      confirmLabel: "Delete",
      variant: "destructive",
    })

    if (!confirmed) return

    setDeletingTemplateId(templateId)
    try {
      const res = await apiFetch(`/system-tasks/${templateId}`, {
        method: "DELETE",
      })
      if (!res.ok) {
        let detail = "Failed to delete system task"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(typeof detail === "string" ? detail : "An error occurred")
        return
      }
      // Remove from templates list
      setTemplates((prev) => prev.filter((item) => item.id !== templateId))
      toast.success("System task deleted")
      await load()
    } catch {
      toast.error("Failed to delete system task")
    } finally {
      setDeletingTemplateId(null)
    }
  }

  const approveTemplate = async (template: SystemTaskTemplateDefinition) => {
    const confirmed = await confirm({
      title: "Approve system task",
      description: `Approve "${template.title}" and allow it to generate scheduled task instances?`,
      confirmLabel: "Approve",
    })
    if (!confirmed) return

    setApprovingTemplateId(template.id)
    try {
      const res = await apiFetch(`/system-tasks/${template.id}/approve`, {
        method: "POST",
      })
      if (!res.ok) {
        let detail = "Failed to approve system task"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(typeof detail === "string" ? detail : "An error occurred")
        return
      }
      toast.success("System task approved")
      await load()
    } finally {
      setApprovingTemplateId(null)
    }
  }

  const openRejectDialog = (template: SystemTaskTemplateDefinition) => {
    setRejectTemplate(template)
    setRejectReason("")
  }

  const submitReject = async () => {
    if (!rejectTemplate) return
    const reason = rejectReason.trim()
    if (reason.length < 2) {
      toast.error("Please enter a rejection reason.")
      return
    }

    setRejectingTemplateId(rejectTemplate.id)
    try {
      const res = await apiFetch(`/system-tasks/${rejectTemplate.id}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      })
      if (!res.ok) {
        let detail = "Failed to reject system task"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(typeof detail === "string" ? detail : "An error occurred")
        return
      }
      toast.success("System task rejected")
      setRejectTemplate(null)
      setRejectReason("")
      await load()
    } finally {
      setRejectingTemplateId(null)
    }
  }

  const availableAssignees = React.useMemo(() => {
    if (!departmentId || isGlobalScopeValue(departmentId)) return users
    return users.filter((u) => u.department_id === departmentId || !u.department_id)
  }, [departmentId, users])
  const editAvailableAssignees = React.useMemo(() => {
    if (!editDepartmentId || isGlobalScopeValue(editDepartmentId)) return users
    return users.filter((u) => u.department_id === editDepartmentId || !u.department_id)
  }, [editDepartmentId, users])
  const filteredAssignees = React.useMemo(() => {
    const query = assigneeQuery.trim().toLowerCase()
    if (!query) return availableAssignees
    return availableAssignees.filter((person) => {
      const email = "email" in person ? person.email || "" : ""
      const name = `${person.full_name || ""} ${person.username || ""} ${email}`.toLowerCase()
      return name.includes(query)
    })
  }, [assigneeQuery, availableAssignees])
  const filteredEditAssignees = React.useMemo(() => {
    const query = editAssigneeQuery.trim().toLowerCase()
    const base = !query
      ? editAvailableAssignees
      : editAvailableAssignees.filter((person) => {
        const email = "email" in person ? person.email || "" : ""
        const name = `${person.full_name || ""} ${person.username || ""} ${email}`.toLowerCase()
        return name.includes(query)
      })
    return [...base].sort((a, b) => {
      const aSelected = editAssigneeIds.includes(a.id)
      const bSelected = editAssigneeIds.includes(b.id)
      if (aSelected !== bSelected) return aSelected ? -1 : 1
      const aEmail = "email" in a ? a.email || "" : ""
      const bEmail = "email" in b ? b.email || "" : ""
      const aName = (a.full_name || a.username || aEmail).toLowerCase()
      const bName = (b.full_name || b.username || bEmail).toLowerCase()
      return aName.localeCompare(bName)
    })
  }, [editAssigneeQuery, editAvailableAssignees, editAssigneeIds])
  const combinedSelected =
    COMBINED_FREQUENCIES.every((value) => frequencyFilters.includes(value)) &&
    frequencyFilters.length >= COMBINED_FREQUENCIES.length
  const allFrequenciesSelected = frequencyFilters.length === 0
  const allPrioritiesSelected = priorityFilters.length === 0
  const frequencyFilterActive = !allFrequenciesSelected
  const priorityFilterActive = !allPrioritiesSelected
  const filterTriggerClass =
    "h-8 rounded-full border border-slate-200 bg-slate-100 px-3 text-sm font-medium text-slate-700 hover:bg-slate-200"
  const filterTriggerActiveClass = "border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100"
  const frequencyLabel = React.useMemo(() => {
    if (allFrequenciesSelected) return "All frequencies"
    const labels: string[] = []
    const remaining = frequencyFilters.filter((value) => !COMBINED_FREQUENCIES.includes(value))
    if (combinedSelected) labels.push("3/6 months")
    for (const value of remaining) {
      const option = FREQUENCY_OPTIONS.find((item) => item.value === value)
      if (option) labels.push(option.label)
    }
    if (labels.length > 2) return `${labels.length} selected`
    return labels.join(", ") || "Selected"
  }, [allFrequenciesSelected, combinedSelected, frequencyFilters])
  const priorityLabel = allPrioritiesSelected
    ? "All priorities"
    : PRIORITY_LABELS[priorityFilters[0] as TaskPriority] || "Priority"
  const assigneeDeptNames = departmentNamesForOwnerIds(assigneeIds)
  const editAssigneeDeptNames = departmentNamesForOwnerIds(editAssigneeIds)
  const weekendShiftHint =
    "If the selected day falls on Saturday/Sunday, the task runs on Friday."

  const assigneeSummary = React.useCallback((list?: SystemTaskTemplateDefinition["assignees"]) => {
    const labels = (list ?? [])
      .map((person) => person.full_name || person.username || person.email || "")
      .filter(Boolean)
    if (!labels.length) return "-"
    if (labels.length > MAX_ASSIGNEE_INITIALS) return "All"
    return labels.map((label) => userInitials(label)).join(", ")
  }, [])

  const assigneeSummaryTitle = React.useCallback((list?: SystemTaskTemplateDefinition["assignees"]) => {
    return (list ?? [])
      .map((person) => person.full_name || person.username || person.email || "")
      .filter(Boolean)
      .join(", ")
  }, [])

  const resolveAssigneeNameById = React.useCallback(
    (userId?: string | null) => {
      if (!userId) return "-"
      const person = userMap.get(userId)
      const email = person && "email" in person ? person.email || "" : ""
      return person?.full_name || person?.username || email || userId
    },
    [userMap]
  )

  const renderAssigneeSummaryText = React.useCallback(
    (labels: string[], inactive = false) => {
      const cleaned = labels.map((label) => label.trim()).filter(Boolean)
      if (cleaned.length === 0) return <span className="text-slate-400">-</span>
      if (cleaned.length > MAX_ASSIGNEE_INITIALS) {
        return (
          <span
            title={cleaned.join(", ")}
            className={cn("block text-xs sm:text-sm text-slate-700 font-normal", inactive && "opacity-55")}
          >
            All
          </span>
        )
      }
      return (
        <div className={cn("flex flex-wrap gap-1.5", inactive && "opacity-55")} title={cleaned.join(", ")}>
          {cleaned.map((label) => (
            <span
              key={label}
              className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] text-slate-700"
              title={label}
            >
              {userInitials(label)}
            </span>
          ))}
        </div>
      )
    },
    []
  )

  const renderManagementAssignees = React.useCallback(
    (template: SystemTaskTemplateDefinition) => {
      const slots = (template.assignee_slots ?? []).filter((slot) => slot.is_active)
      if (slots.length > 0) {
        return renderAssigneeSummaryText(
          slots.map((slot) => resolveAssigneeNameById(slot.primary_user_id))
        )
      }

      if (template.assignees?.length) {
        return renderAssigneeSummaryText(
          template.assignees
            .map((person) => person.full_name || person.username || person.email || "")
            .filter(Boolean)
        )
      }
      if (template.default_assignee_id) {
        return renderAssigneeSummaryText([resolveAssigneeNameById(template.default_assignee_id)])
      }
      return <span className="text-slate-400">-</span>
    },
    [renderAssigneeSummaryText, resolveAssigneeNameById]
  )

  const renderReplacements = React.useCallback(
    (template: SystemTaskTemplateDefinition) => {
      const replacements = [
        ["ZV1", template.zv1_user_id],
        ["ZV2", template.zv2_user_id],
      ] as const
      if (!template.zv1_user_id && !template.zv2_user_id) {
        return <span className="text-slate-400">-</span>
      }
      return (
        <div className="space-y-1 text-[11px] text-slate-700">
          {replacements.map(([label, userId]) => (
            <div key={label} className="truncate" title={resolveAssigneeNameById(userId)}>
              <span className="font-semibold">{label}:</span>{" "}
              {userId ? userInitials(resolveAssigneeNameById(userId)) : "-"}
            </div>
          ))}
        </div>
      )
    },
    [resolveAssigneeNameById]
  )

  const renderApprovalSection = React.useCallback(
    (
      title: string,
      description: string,
      items: SystemTaskTemplateDefinition[],
      status: "pending" | "rejected"
    ) => {
      if (!showSystemActions || items.length === 0) return null

      return (
        <div className="rounded-lg border bg-white shadow-sm">
          <div className="border-b bg-slate-50 px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-sm font-semibold text-slate-900">{title}</div>
                <div className="text-xs text-slate-500">{description}</div>
              </div>
              <Badge variant="outline" className="bg-white text-slate-700">
                {items.length}
              </Badge>
            </div>
          </div>
          <div className="divide-y">
            {items.map((template) => {
              const priorityValue = normalizePriority(template.priority)
              const rejectedAt = template.rejected_at ? formatDateTimeDMY(template.rejected_at) : null
              return (
                <div key={template.id} className="grid gap-3 px-4 py-3 md:grid-cols-[1fr_120px_160px_140px_220px] md:items-center">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="font-medium text-slate-900">{template.title}</div>
                      {template.is_repetitive && <Badge variant="outline">Detyrë e përsëritur</Badge>}
                      <Badge
                        variant="outline"
                        className={cn("border text-[11px]", PRIORITY_BADGE_STYLES[priorityValue])}
                      >
                        {PRIORITY_LABELS[priorityValue]}
                      </Badge>
                    </div>
                    <div className="mt-1 text-xs text-slate-500">
                      {templateDepartmentLabel(template)} · {FREQUENCY_OPTIONS.find((option) => option.value === template.frequency)?.label ?? template.frequency}
                    </div>
                    {status === "rejected" ? (
                      <div className="mt-2 rounded border border-red-100 bg-red-50 px-2 py-1.5 text-xs text-red-700">
                        {template.rejection_reason || "Rejected"}
                        {rejectedAt ? <span className="ml-1 text-red-500">({rejectedAt})</span> : null}
                      </div>
                    ) : null}
                  </div>
                  <div className="text-xs text-slate-600 md:text-sm">
                    {template.finish_period || "-"}
                  </div>
                  <div>{renderManagementAssignees(template)}</div>
                  <div>{renderReplacements(template)}</div>
                  <div className="flex flex-wrap justify-start gap-2 md:justify-end">
                    {canEditTemplate(template) ? (
                      <Button variant="outline" size="sm" onClick={() => startEdit(template)}>
                        Edit
                      </Button>
                    ) : null}
                    {isAdmin ? (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={deletingTemplateId === template.id}
                        className="border-red-200 text-red-600 hover:bg-red-50 hover:text-red-700"
                        onClick={() => void deleteTemplate(template)}
                      >
                        {deletingTemplateId === template.id ? "Deleting..." : "Delete"}
                      </Button>
                    ) : null}
                    {status === "pending" && isManagerOrAdmin ? (
                      <>
                        <Button
                          size="sm"
                          disabled={approvingTemplateId === template.id}
                          onClick={() => void approveTemplate(template)}
                        >
                          {approvingTemplateId === template.id ? "Approving..." : "Approve"}
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={rejectingTemplateId === template.id}
                          className="border-red-200 text-red-600 hover:bg-red-50 hover:text-red-700"
                          onClick={() => openRejectDialog(template)}
                        >
                          Reject
                        </Button>
                      </>
                    ) : null}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )
    },
    [
      approveTemplate,
      approvingTemplateId,
      canEditTemplate,
      deleteTemplate,
      deletingTemplateId,
      isAdmin,
      isManagerOrAdmin,
      openRejectDialog,
      rejectingTemplateId,
      renderManagementAssignees,
      renderReplacements,
      showSystemActions,
      startEdit,
      templateDepartmentLabel,
    ]
  )

  const setInternalNoteValue = (
    key: string,
    value: string,
    setter: React.Dispatch<React.SetStateAction<Record<string, string>>>
  ) => {
    setter((prev) => ({ ...prev, [key]: value }))
  }

  const buildInternalNotes = (values: Record<string, string>) => {
    const lines = [...INTERNAL_NOTE_FIELDS, ...INTERNAL_QA_FIELDS]
      .map(({ key, label }) => {
        const raw = values[key]?.trim()
        return raw ? `${label}: ${raw}` : ""
      })
      .filter(Boolean)
    return lines.length ? lines.join("\n") : null
  }

  const normalizeDayValues = (values: string[]) => {
    const cleaned = values
      .map((value) => Number(value))
      .filter((value) => Number.isFinite(value))
    return Array.from(new Set(cleaned)).sort((a, b) => a - b)
  }

  const toggleDayValue = (
    value: string,
    current: string[],
    setter: React.Dispatch<React.SetStateAction<string[]>>
  ) => {
    const next = current.includes(value)
      ? current.filter((item) => item !== value)
      : [...current, value]
    next.sort((a, b) => Number(a) - Number(b))
    setter(next)
  }

  const exportTemplatesCSV = (mode: "all" | "active" | "inactive") => {
    const rows = templates.filter((template) => {
      if (mode === "active") return template.is_active
      if (mode === "inactive") return !template.is_active
      return true
    })
    const header = [
      "Title",
      "Description",
      "Department",
      "DepartmentCode",
      "Frequency",
      "Priority",
      "FinishPeriod",
      "DayOfWeek",
      "DayOfMonth",
      "MonthOfYear",
      "DefaultAssignee",
      "ZV1",
      "ZV2",
      "Active",
    ]
    const dayOfMonthLabel = (value?: number | null) => {
      if (value == null) return ""
      if (value === 0) return "end_of_month"
      if (value === -1) return "first_working_day"
      return String(value)
    }
    const dayOfWeekLabel = (template: SystemTaskTemplateDefinition) => {
      const days =
        template.days_of_week && template.days_of_week.length
          ? template.days_of_week
          : template.day_of_week != null
            ? [template.day_of_week]
            : []
      return days.join("|")
    }

    const body = rows.map((template) => {
      const assignee = template.default_assignee_id ? userMap.get(template.default_assignee_id) : null
      const zv1 = template.zv1_user_id ? userMap.get(template.zv1_user_id) : null
      const zv2 = template.zv2_user_id ? userMap.get(template.zv2_user_id) : null
      const departmentLabel = templateDepartmentLabel(template)
      const departmentCode = departmentLabel === "-" ? "" : departmentLabel
      return [
        template.title,
        template.description || "",
        departmentLabel,
        departmentCode,
        template.frequency,
        normalizePriority(template.priority),
        template.finish_period || "",
        dayOfWeekLabel(template),
        dayOfMonthLabel(template.day_of_month),
        template.month_of_year ?? "",
        assignee ? assignee.username || assignee.email || assignee.full_name || "" : "",
        zv1 ? zv1.username || zv1.email || zv1.full_name || "" : "",
        zv2 ? zv2.username || zv2.email || zv2.full_name || "" : "",
        template.is_active ? "true" : "false",
      ]
        .map(csvEscape)
        .join(",")
    })
    const blob = new Blob([header.join(",") + "\n" + body.join("\n")], { type: "text/csv" })
    const link = document.createElement("a")
    link.href = URL.createObjectURL(blob)
    link.download = `system_task_templates_${mode}.csv`
    link.click()
  }

  const exportTemplatesExcel = async () => {
    if (exportingExcel) return
    setExportingExcel(true)
    try {
      const res = await apiFetch("/exports/system-task-templates.xlsx?mode=all")
      if (!res?.ok) {
        const detail = await res.text()
        toast.error(detail || "Failed to export Excel.")
        return
      }
      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = "system_task_templates_all.xlsx"
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (err) {
      console.error("Failed to export system tasks Excel", err)
      toast.error("Failed to export Excel.")
    } finally {
      setExportingExcel(false)
    }
  }

  const handlePrint = React.useCallback(() => {
    const escapeHtml = (value: unknown) => {
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;")
    }
    const stripHtml = (value: string | null | undefined) => String(value ?? "").replace(/<[^>]+>/g, "").trim()
    const buildDetails = (template: SystemTaskTemplateDefinition) => {
      const notes = parseInternalNotes(template.internal_notes)
      const parts: string[] = []
      const reg = notes.REGJ ? `REGJ: ${notes.REGJ}` : ""
      const path = notes.PATH ? `PATH: ${notes.PATH}` : ""
      const check = (notes.CHECK || notes.CHECKLISTA) ? `CHECKLISTA: ${notes.CHECK || notes.CHECKLISTA}` : ""
      const training = notes.TRAINING ? `TRAINING: ${notes.TRAINING}` : ""
      if (reg) parts.push(reg)
      if (path) parts.push(path)
      if (check) parts.push(check)
      if (training) parts.push(training)
      return parts.join(" | ")
    }
    const buildBzGroup = (template: SystemTaskTemplateDefinition) => {
      const notes = parseInternalNotes(template.internal_notes)
      return notes["BZ GROUP"] || ""
    }
    const buildBzMe = (template: SystemTaskTemplateDefinition) => {
      const managerIds = template.alignment_user_ids ?? []
      if (managerIds.length === 0) return ""
      const labels = managerIds
        .map((id) => {
          const person = userMap.get(id)
          if (!person) return ""
          return userDisplayLabel(person)
        })
        .filter(Boolean)
        .map((label) => userInitials(label))
        .filter(Boolean)
      return labels.join(", ")
    }
    const buildBzKur = (template: SystemTaskTemplateDefinition) => {
      if (!template.requires_alignment) return ""
      return timeInputValue(template.alignment_time)
    }
    const buildDetailsWithBzGroup = (template: SystemTaskTemplateDefinition) => {
      const notes = parseInternalNotes(template.internal_notes)
      const normalize = (value?: string | null) => {
        const trimmed = String(value ?? "").trim()
        return trimmed === "-" ? "" : trimmed
      }
      const reg = normalize(notes.REGJ)
      const path = normalize(notes.PATH)
      const training = normalize(notes.TRAINING)
      const checklistaValue = normalize(notes.CHECK || notes.CHECKLISTA)
      const bzGroup = normalize(buildBzGroup(template))
      const hasAny = reg || path || training || checklistaValue || bzGroup
      if (!hasAny) return ""
      const parts = [
        `<strong>1.REGJ:</strong> ${escapeHtml(reg || "-")}`,
        `<strong>2.PATH:</strong> ${escapeHtml(path || "-")}`,
        `<strong>3.CHECKLISTA:</strong> ${escapeHtml(checklistaValue || "-")}`,
        `<strong>4.TRAINING:</strong> ${escapeHtml(training || "-")}`,
        `<strong>5.BZ GROUP:</strong> ${escapeHtml(bzGroup || "-")}`,
      ]
      return parts.join("\n")
    }
    const assigneeInitials = (list?: SystemTaskTemplateDefinition["assignees"]) => {
      if (!list || list.length === 0) return "-"
      return list
        .map((person) => userDisplayLabel(person))
        .filter(Boolean)
        .map((label) => userInitials(label))
        .join(", ")
    }
    const replacementInitials = (template: SystemTaskTemplateDefinition) => {
      const labelFor = (userId?: string | null) => {
        if (!userId) return "-"
        const person = userMap.get(userId)
        return person ? userInitials(userDisplayLabel(person)) : "-"
      }
      return `ZV1: ${labelFor(template.zv1_user_id)} / ZV2: ${labelFor(template.zv2_user_id)}`
    }

    const rows = sections[0]?.templates ?? []
    if (rows.length === 0) {
      toast("No system task templates to print for the current filters.")
      return
    }

    const printWindow = window.open("", "_blank")
    if (!printWindow) return

    const effectiveTitle = headingTitle ?? (scopeFilter === "GA" ? "Admin System Tasks" : "System Tasks")
    const now = new Date()
    const printedAt = formatDateTimeDMY(now)

    const activeFilters: string[] = []
    if (searchQuery.trim()) activeFilters.push(`Search: "${searchQuery.trim()}"`)
    if (!allFrequenciesSelected) activeFilters.push(`Frequency: ${frequencyLabel}`)
    if (!allPrioritiesSelected) activeFilters.push(`Priority: ${priorityLabel}`)
    const filterLine = activeFilters.length ? activeFilters.join(" | ") : "All"

    const frequencyOrder: SystemTaskFrequency[] = ["DAILY", "WEEKLY", "MONTHLY", "3_MONTHS", "6_MONTHS", "YEARLY"]
    const grouped = new Map<SystemTaskFrequency, SystemTaskTemplateDefinition[]>()
    for (const f of frequencyOrder) grouped.set(f, [])
    const inactive: SystemTaskTemplateDefinition[] = []
    for (const template of rows) {
      if (template.is_active === false) {
        inactive.push(template)
        continue
      }
      grouped.get(template.frequency)?.push(template)
    }

    const frequencyShortLabel = (value: SystemTaskFrequency) => {
      switch (value) {
        case "DAILY":
          return "D"
        case "WEEKLY":
          return "W"
        case "MONTHLY":
          return "M"
        case "3_MONTHS":
          return "3M"
        case "6_MONTHS":
          return "6M"
        case "YEARLY":
          return "Y"
        default:
          return value
      }
    }

    const departmentShortLabel = (template: SystemTaskTemplateDefinition) => {
      return templateDepartmentLabel(template)
    }

    const renderTemplateRow = (template: SystemTaskTemplateDefinition, rowNumber: number) => {
      const priorityValue = normalizePriority(template.priority)
                        const departmentLabel = templateDepartmentLabel(template)
      const ownerLabel = assigneeInitials(template.assignees)
      const frequencyLabelResolved =
        FREQUENCY_OPTIONS.find((option) => option.value === template.frequency)?.label ?? template.frequency
      const frequencyShort = frequencyShortLabel(template.frequency)
      const departmentShort = departmentShortLabel(template)
      const priorityShort = priorityValue === "HIGH" ? "H" : "N"

      return `
        <tr>
          <td class="num tight">${rowNumber}</td>
          <td class="center tight">${escapeHtml(priorityShort)}</td>
          <td class="center no-wrap tight">${escapeHtml(frequencyShort)}</td>
          <td class="no-wrap tight">${escapeHtml(departmentShort)}</td>
          <td class="ampm tight">${escapeHtml(template.finish_period || "-")}</td>
          <td class="title">${escapeHtml(template.title)}</td>
          <td>${escapeHtml(ownerLabel)}</td>
          <td>${escapeHtml(replacementInitials(template))}</td>
          <td class="details-bz">${buildDetailsWithBzGroup(template)}</td>
          <td class="bz-me">${escapeHtml(buildBzMe(template) || "-")}</td>
          <td class="bz-kur">${escapeHtml(buildBzKur(template) || "-")}</td>
          <td class="comment">-</td>
        </tr>
      `
    }

    let tableBody = ""
    let counter = 0
    for (const frequency of frequencyOrder) {
      const list = grouped.get(frequency) ?? []
      if (!list.length) continue
      // Print view: no DAILY/WEEKLY/... separator rows; keep ordering only.
      for (const template of list) {
        counter += 1
        tableBody += renderTemplateRow(template, counter)
      }
    }

    // Keep inactive tasks at the end, but without a separate "Inactive Tasks" separator row.
    if (inactive.length) {
      for (const template of inactive) {
        counter += 1
        tableBody += renderTemplateRow(template, counter)
      }
    }

    const html = `
      <!DOCTYPE html>
      <html>
        <head>
          <meta charset="utf-8" />
          <title>${escapeHtml(effectiveTitle)}</title>
          <style>
            @page { margin: 8mm; }
            html, body {
              direction: ltr;
              margin: 0;
              padding: 0;
            }

            body {
              font-family: Arial, sans-serif;
              font-size: 10pt;
              color: #0f172a;
            }

            .header {
              text-align: left;
              margin: 0 0 8px 0;
              padding: 0;
              border-bottom: 0;
            }

            .header h1 {
              margin: 0;
              font-size: 16pt;
              letter-spacing: 0.2px;
              text-align: center;
            }

            .meta {
              margin-top: 6px;
              font-size: 9pt;
              color: #475569;
              display: flex;
              justify-content: space-between;
              gap: 12px;
              flex-wrap: wrap;
            }

            .meta .filters {
              flex: 1;
              text-align: left;
              word-break: break-word;
            }

            .meta .printedAt {
              white-space: nowrap;
              text-align: right;
            }

            table {
              width: 100%;
              border-collapse: collapse;
              table-layout: auto;
              direction: ltr;
              margin-top: 0;
              border: 2px solid #0f172a;
            }

            col.col-num { width: auto; }
            col.col-prio { width: auto; }
            col.col-lloji { width: auto; }
            col.col-dept { width: auto; }
            col.col-ampm { width: auto; }
            col.col-title { width: 20%; }
            col.col-person { width: auto; }
            col.col-zv { width: auto; }
            col.col-details { width: 24%; }
            col.col-bzme { width: auto; }
            col.col-bzkur { width: auto; }
            col.col-comment { width: 12%; }

            thead th {
              background: #f1f5f9;
              border: 2px solid #0f172a;
              padding: 3px;
              font-size: 9pt;
              text-align: left;
              text-transform: uppercase;
              white-space: normal;
              word-break: break-word;
              hyphens: auto;
              vertical-align: bottom;
              line-height: 1.1;
            }

            tbody td {
              border: 1px solid #0f172a;
              padding: 3px;
              vertical-align: bottom;
              font-size: 9pt;
              word-break: break-word;
              white-space: normal;
            }
            /* Match left/right spacing for narrow columns */
            thead th:nth-child(-n + 5),
            tbody td:nth-child(-n + 5),
            thead th:nth-child(7),
            tbody td:nth-child(7),
            thead th:nth-child(8),
            tbody td:nth-child(8),
            thead th:nth-child(10),
            tbody td:nth-child(10),
            thead th:nth-child(11),
            tbody td:nth-child(11) {
              padding-left: 4px;
              padding-right: 4px;
            }
            .details-bz {
              white-space: pre-line;
            }
 /* Force tight columns (first 5 + Personi + ZV + BZ ME + KOHA BZ) */
            thead th:nth-child(-n + 5),
            tbody td:nth-child(-n + 5),
            thead th:nth-child(7),
            tbody td:nth-child(7),
            thead th:nth-child(8),
            tbody td:nth-child(8),
            thead th:nth-child(10),
            tbody td:nth-child(10),
            thead th:nth-child(11),
            tbody td:nth-child(11) {
              padding-left: 4px;
              padding-right: 4px;
              white-space: nowrap;
            }

            tr { page-break-inside: avoid; }

            .num { text-align: left; font-weight: bold; }
            .tight { padding-left: 0; padding-right: 0; }
            .ampm { text-align: center; }
            .ampm-head { text-align: center; line-height: 1.05; }
            .ampm-head span { display: inline-block; }
            .title { font-weight: 400; }
            .description { }
            .details { }
            .bz-group { }
            .center { text-align: left; }

            .pill {
              display: inline-block;
              padding: 2px 8px;
              border-radius: 999px;
              border: 1px solid #cbd5e1;
              font-size: 8pt;
              font-weight: 700;
            }

            .pill-normal { background: #ffedd5; border-color: #fdba74; color: #9a3412; }
            .pill-high { background: #fee2e2; border-color: #fca5a5; color: #b91c1c; }

            .print-footer {
              display: none;
            }

            @media print {
              .print-footer {
                display: grid;
                position: fixed;
                bottom: 0;
                left: 0;
                right: 0;
                padding: 0;
                font-size: 9pt;
                color: #475569;
                grid-template-columns: 1fr auto 1fr;
                align-items: center;
              }
              .print-footer .page-count {
                grid-column: 2;
                text-align: center;
              }
              .print-footer .punoi {
                grid-column: 3;
                text-align: right;
              }
            }

            @media screen {
              .print-footer {
                display: grid;
                position: fixed;
                bottom: 0;
                left: 0;
                right: 0;
                padding: 0;
                font-size: 9pt;
                color: #475569;
                background: white;
                grid-template-columns: 1fr auto 1fr;
                align-items: center;
              }
              .print-footer .page-count {
                grid-column: 2;
                text-align: center;
              }
              .print-footer .punoi {
                grid-column: 3;
                text-align: right;
              }
            }
          </style>
        </head>
        <body>
          <div class="header">
            <h1>${escapeHtml(effectiveTitle)}</h1>
            <div class="meta">
              <div class="filters"><strong>FILTERS:</strong> ${escapeHtml(filterLine).toUpperCase()}</div>
              <div class="printedAt">${escapeHtml(printedAt)}</div>
            </div>
          </div>

          <table>
            <colgroup>
              <col class="col-num" />
              <col class="col-prio" />
              <col class="col-lloji" />
              <col class="col-dept" />
              <col class="col-ampm" />
              <col class="col-title" />
              <col class="col-person" />
              <col class="col-zv" />
              <col class="col-details" />
              <col class="col-bzme" />
              <col class="col-bzkur" />
              <col class="col-comment" />
            </colgroup>
            <thead>
              <tr>
                <th class="tight">NR</th>
                <th class="tight">PRIO</th>
                <th class="tight">LL</th>
                <th class="tight">DEP</th>
                <th class="ampm-head tight"><span>AM/<br />PM</span></th>
                <th>Titulli</th>
                <th>USER</th>
                <th>ZV1 / ZV2</th>
                <th>REGJ/PATH/CHECKLISTA/TRAINING / BZ GROUP</th>
                <th>BZ ME</th>
                <th>KOHA BZ</th>
                <th>KOMENT</th>
              </tr>
            </thead>
            <tbody>
              ${tableBody}
            </tbody>
          </table>
          <div class="print-footer">
            <span></span>
            <span class="page-count" id="page-count">1/1</span>
            <span class="punoi">PUNOI ___</span>
          </div>
          <script>
            (function () {
              // Calculate approximate page count based on content height
              var A4_HEIGHT_PX = 11.69 * 96; // ~1122px
              var MARGIN_PX = 0;
              var printableHeight = A4_HEIGHT_PX - MARGIN_PX * 2;
              
              function updatePageCount() {
                var bodyHeight = Math.max(
                  document.body.scrollHeight,
                  document.body.offsetHeight,
                  document.documentElement.scrollHeight
                );
                var totalPages = Math.max(1, Math.ceil(bodyHeight / printableHeight));
                var pageCountEl = document.getElementById("page-count");
                if (pageCountEl) {
                  pageCountEl.textContent = "1/" + totalPages;
                }
              }
              
              // Update on load
              if (document.readyState === "complete") {
                updatePageCount();
              } else {
                window.addEventListener("load", updatePageCount);
              }
            })();
          </script>
        </body>
      </html>
    `

    printWindow.document.open()
    printWindow.document.write(html)
    printWindow.document.close()
    printWindow.focus()

    const triggerPrint = () => {
      printWindow.focus()
      printWindow.print()
    }

    // Prefer onload so the footer/counters are ready for the preview.
    printWindow.onload = () => {
      setTimeout(triggerPrint, 100)
    }
    printWindow.onafterprint = () => {
      printWindow.close()
    }
    // Fallback in case onload doesn't fire (rare for about:blank).
    setTimeout(() => {
      try {
        triggerPrint()
      } catch {}
    }, 600)
  }, [
    allFrequenciesSelected,
    allPrioritiesSelected,
    departmentMap,
    frequencyLabel,
    headingTitle,
    priorityLabel,
    scopeFilter,
    searchQuery,
    sections,
  ])

  const importTemplatesFromFile = async (file: File) => {
    if (!canCreate) return
    const text = await file.text()
    const rows = parseCSV(text)
    if (!rows.length) return

    const header = rows[0].map((cell) => cell.trim().toLowerCase())
    const hasHeader = header.includes("title") || header.includes("frequency")
    if (!hasHeader) {
      toast.error("CSV import requires a header row with ZV1 and ZV2 columns.")
      return
    }
    const dataRows = hasHeader ? rows.slice(1) : rows
    const noHeaderHasPriority = !hasHeader && (dataRows[0]?.length ?? 0) >= 11
    const noHeaderHasFinishPeriod = !hasHeader && (dataRows[0]?.length ?? 0) >= 12

    const getIndex = (name: string, aliases: string[] = []) => {
      const target = [name, ...aliases]
      return header.findIndex((cell) => target.includes(cell.replace(/\s+/g, "")))
    }

    const idxTitle = hasHeader ? getIndex("title") : 0
    const idxDescription = hasHeader ? getIndex("description") : 1
    const idxDepartment = hasHeader ? getIndex("department", ["departmentcode", "department_code"]) : 2
    const idxFrequency = hasHeader ? getIndex("frequency") : 3
    const idxPriority = hasHeader ? getIndex("priority") : noHeaderHasPriority ? 4 : -1
    const idxFinishPeriod = hasHeader
      ? getIndex("finishperiod", ["finish_period", "finish"])
      : noHeaderHasFinishPeriod
        ? 5
        : -1
    const idxDayOfWeek = hasHeader
      ? getIndex("dayofweek", ["day_of_week"])
      : noHeaderHasFinishPeriod
        ? 6
        : noHeaderHasPriority
          ? 5
          : 4
    const idxDayOfMonth = hasHeader
      ? getIndex("dayofmonth", ["day_of_month"])
      : noHeaderHasFinishPeriod
        ? 7
        : noHeaderHasPriority
          ? 6
          : 5
    const idxMonthOfYear = hasHeader
      ? getIndex("monthofyear", ["month_of_year"])
      : noHeaderHasFinishPeriod
        ? 8
        : noHeaderHasPriority
          ? 7
          : 6
    const idxAssignee = hasHeader
      ? getIndex("defaultassignee", ["assignee"])
      : noHeaderHasFinishPeriod
        ? 9
        : noHeaderHasPriority
          ? 8
          : 7
    const idxZv1 = getIndex("zv1", ["zv1userid", "zv1_user_id"])
    const idxZv2 = getIndex("zv2", ["zv2userid", "zv2_user_id"])
    if (idxZv1 < 0 || idxZv2 < 0) {
      toast.error("CSV import requires ZV1 and ZV2 columns.")
      return
    }
    const idxActive = hasHeader
      ? getIndex("active")
      : noHeaderHasFinishPeriod
        ? 10
        : noHeaderHasPriority
          ? 9
          : 8

    const normalize = (value: string) => value.trim().toLowerCase()
    const frequencyForValue = (value: string): SystemTaskFrequency | null => {
      const raw = normalize(value)
      const upper = value.trim().toUpperCase()
      if ((FREQUENCY_VALUES as string[]).includes(upper)) {
        return upper as SystemTaskFrequency
      }
      if (raw.includes("daily") || raw.includes("every day") || raw.includes("ditore")) return "DAILY"
      if (raw.includes("weekly") || raw.includes("every week") || raw.includes("javore")) return "WEEKLY"
      if (raw.includes("yearly") || raw.includes("annual") || raw.includes("vjetore")) return "YEARLY"
      if (raw.includes("3") && raw.includes("month")) return "3_MONTHS"
      if (raw.includes("6") && raw.includes("month")) return "6_MONTHS"
      if (raw.includes("3") && raw.includes("mujore")) return "3_MONTHS"
      if (raw.includes("6") && raw.includes("mujore")) return "6_MONTHS"
      if (raw.includes("monthly") || raw.includes("mujore")) return "MONTHLY"
      return null
    }

    const priorityForValue = (value: string): TaskPriority | null => {
      const raw = normalize(value)
      if (!raw) return null
      const upper = value.trim().toUpperCase()
      if ((PRIORITY_OPTIONS as string[]).includes(upper)) {
        return upper as TaskPriority
      }
      if (raw.includes("urgent") || raw.includes("critical")) return "HIGH"
      if (raw.includes("high")) return "HIGH"
      if (raw.includes("medium") || raw.includes("low") || raw.includes("normal")) return "NORMAL"
      return null
    }

    const finishPeriodForValue = (value: string): TaskFinishPeriod | null => {
      const raw = normalize(value)
      if (!raw) return null
      if (raw.includes("none") || raw.includes("all day") || raw.includes("allday")) return null
      const upper = value.trim().toUpperCase()
      if ((FINISH_PERIOD_OPTIONS as string[]).includes(upper)) {
        return upper as TaskFinishPeriod
      }
      if (raw.includes("am")) return "AM"
      if (raw.includes("pm")) return "PM"
      return null
    }

    const dayOfWeekForValue = (value: string): number[] | null => {
      const raw = normalize(value)
      if (!raw) return null
      const map: Record<string, number> = {
        monday: 0,
        tuesday: 1,
        wednesday: 2,
        thursday: 3,
        friday: 4,
        saturday: 5,
        sunday: 6,
        "e hene": 0,
        "e marte": 1,
        "e merkure": 2,
        "e enjte": 3,
        "e premte": 4,
        "e shtune": 5,
        "e diel": 6,
      }
      const parseToken = (token: string) => {
        const cleaned = token.trim().toLowerCase()
        if (!cleaned) return null
        const numeric = Number(cleaned)
        if (!Number.isNaN(numeric)) return numeric
        return map[cleaned] ?? null
      }
      const segments = raw.split(/[|;,\s]+/).filter(Boolean)
      const parsed = segments.map(parseToken).filter((day): day is number => day != null)
      if (parsed.length) return Array.from(new Set(parsed)).sort((a, b) => a - b)
      const single = parseToken(raw)
      return single != null ? [single] : null
    }

    const scopeForValue = (value: string): { scope: SystemTaskScope; departmentId: string | null } => {
      const raw = normalize(value)
      if (!raw || raw === "all" || raw === "all departments") {
        return { scope: "ALL", departmentId: null }
      }
      if (raw === "ga") {
        return { scope: "GA", departmentId: null }
      }
      const byCode = departments.find((dept) => dept.code.toLowerCase() === raw)
      if (byCode) return { scope: "DEPARTMENT", departmentId: byCode.id }
      const byName = departments.find((dept) => dept.name.toLowerCase() === raw)
      return { scope: "DEPARTMENT", departmentId: byName?.id ?? null }
    }

    const assigneeIdForValue = (value: string) => {
      const raw = normalize(value)
      if (!raw) return null
      const byUsername = users.find((u) => (u.username || "").toLowerCase() === raw)
      if (byUsername) return byUsername.id
      const byEmail = users.find((u) => (u.email || "").toLowerCase() === raw)
      if (byEmail) return byEmail.id
      const byName = users.find((u) => (u.full_name || "").toLowerCase() === raw)
      return byName?.id ?? null
    }

    const activeForValue = (value: string) => {
      const raw = normalize(value)
      if (!raw) return true
      if (["true", "yes", "1", "active", "open"].includes(raw)) return true
      if (["false", "no", "0", "inactive", "closed"].includes(raw)) return false
      return true
    }

    const dayOfMonthForValue = (value: string) => {
      const raw = normalize(value)
      if (!raw) return null
      if (raw.includes("first") && raw.includes("work")) return -1
      if (raw.includes("end") && raw.includes("month")) return 0
      const numeric = Number(raw)
      return Number.isNaN(numeric) ? null : numeric
    }

    for (const row of dataRows) {
      const title = row[idxTitle]?.trim()
      if (!title) continue
      const frequencyValue = frequencyForValue(row[idxFrequency] || "")
      if (!frequencyValue) continue
      const priorityValue =
        idxPriority >= 0 ? priorityForValue(row[idxPriority] || "") : null
      const finishPeriodValue =
        idxFinishPeriod >= 0 ? finishPeriodForValue(row[idxFinishPeriod] || "") : null

      const scopeEntry = scopeForValue(row[idxDepartment] || "")
      const dayOfWeekValue = dayOfWeekForValue(row[idxDayOfWeek] || "")
      const assigneeId = assigneeIdForValue(row[idxAssignee] || "")
      const zv1UserId = assigneeIdForValue(row[idxZv1] || "")
      const zv2UserId = assigneeIdForValue(row[idxZv2] || "")
      if (replacementSelectionError(zv1UserId || "", zv2UserId || "", assigneeId ? [assigneeId] : [])) {
        toast.error(`Skipped "${title}": invalid ZV1/ZV2.`)
        continue
      }
      const payload = {
        title,
        description: row[idxDescription]?.trim() || null,
        scope: scopeEntry.scope,
        department_id: scopeEntry.departmentId,
        default_assignee_id: assigneeId,
        zv1_user_id: zv1UserId || null,
        zv2_user_id: zv2UserId || null,
        frequency: frequencyValue,
        priority: priorityValue,
        finish_period: finishPeriodValue,
        day_of_week: dayOfWeekValue ? dayOfWeekValue[0] : null,
        days_of_week: dayOfWeekValue,
        day_of_month: dayOfMonthForValue(row[idxDayOfMonth] || ""),
        month_of_year: row[idxMonthOfYear] ? Number(row[idxMonthOfYear]) : null,
        is_active: activeForValue(row[idxActive] || ""),
      }

      await apiFetch("/system-tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
    }

    await load()
  }

  const effectiveHeadingTitle =
    headingTitle ?? (scopeFilter === "GA" ? "Admin System Tasks" : "System Tasks")
  const effectiveHeadingDescription =
    headingDescription ??
    (scopeFilter === "GA"
      ? "System tasks scoped for Kosove and Gane admins."
      : "Department tasks organized by frequency and date.")

  const stickyHeaderRef = React.useRef<HTMLDivElement | null>(null)
  const [stickyOffset, setStickyOffset] = React.useState(0)

  React.useLayoutEffect(() => {
    const element = stickyHeaderRef.current
    if (!element || typeof ResizeObserver === "undefined") return

    const updateOffset = () => {
      setStickyOffset(element.offsetHeight)
    }

    updateOffset()
    const observer = new ResizeObserver(updateOffset)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  return (
    <div
      className="space-y-4 pb-12"
      style={{ "--system-tasks-sticky-offset": `${stickyOffset}px` } as React.CSSProperties}
    >
      {/* Header Area */}
      <div
        ref={stickyHeaderRef}
        className="sticky top-0 z-50 rounded-lg border border-border/60 bg-white/95 p-4 shadow-sm backdrop-blur"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-xl font-semibold leading-tight text-slate-900">{effectiveHeadingTitle}</h3>
            <p className="text-sm font-normal leading-snug text-slate-500">
              {effectiveHeadingDescription}
            </p>
          </div>
          {showSystemActions ? (
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex h-9 overflow-hidden rounded-md border border-slate-200 bg-slate-50">
                {[
                  { id: "approved", label: "System Tasks", count: approvedTemplates.length },
                  { id: "pending", label: "New", count: pendingTemplates.length },
                  { id: "rejected", label: "Rejected", count: rejectedTemplates.length },
                ].map((item) => {
                  const active = approvalView === item.id
                  return (
                    <button
                      key={item.id}
                      type="button"
                      className={cn(
                        "border-r border-slate-200 px-3 text-sm font-medium last:border-r-0",
                        active
                          ? "bg-blue-600 text-white"
                          : "bg-white text-slate-700 hover:bg-slate-100"
                      )}
                      onClick={() => setApprovalView(item.id as ApprovalView)}
                    >
                      {item.label}
                      {item.count > 0 ? <span className="ml-1 text-xs opacity-80">({item.count})</span> : null}
                    </button>
                  )
                })}
              </div>
              {approvalView === "approved" ? (
                <>
                  <Button
                    variant="outline"
                    onClick={handlePrint}
                    size="sm"
                    className="h-9 border-slate-200 px-3 text-sm text-slate-700 hover:bg-slate-50"
                  >
                    Print
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => void exportTemplatesExcel()}
                    disabled={exportingExcel}
                    size="sm"
                    className="h-9 border-blue-200 px-3 text-sm text-blue-700 hover:bg-blue-50 hover:text-blue-800"
                  >
                    {exportingExcel ? "Exporting..." : "Export Excel"}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => exportTemplatesCSV("all")}
                    size="sm"
                    className="h-9 border-slate-200 px-3 text-sm text-slate-700 hover:bg-slate-50"
                  >
                    Export CSV
                  </Button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".csv,text/csv"
                    className="hidden"
                    onChange={(event) => {
                      const file = event.target.files?.[0]
                      if (file) void importTemplatesFromFile(file)
                      event.target.value = ""
                    }}
                  />
                  <Button
                    variant="outline"
                    onClick={() => fileInputRef.current?.click()}
                    size="sm"
                    className="h-9 border-slate-200 px-3 text-sm text-slate-700 hover:bg-slate-50"
                  >
                    Import CSV
                  </Button>
                </>
              ) : null}
              <Dialog open={createOpen} onOpenChange={setCreateOpen}>
                <DialogTrigger asChild>
                  <Button
                    disabled={!canCreate}
                    size="sm"
                    className="h-9 bg-blue-600 px-3 text-sm text-white hover:bg-blue-700"
                  >
                    + Add Task
                  </Button>
                </DialogTrigger>
                {/* CREATE DIALOG CONTENT (Omitted for brevity, assumed same as original) */}
                <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-3xl">
                  <DialogHeader>
                    <DialogTitle>Add system task</DialogTitle>
                  </DialogHeader>
                  <div className="space-y-5">
                    <div className="grid gap-4 md:grid-cols-2">
                      <div className="space-y-2">
                        <Label>Department</Label>
                        <Select value={departmentId} onValueChange={handleDepartmentChange}>
                          <SelectTrigger>
                            <SelectValue placeholder="Select department" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value={ALL_DEPARTMENTS_VALUE}>All departments</SelectItem>
                            {departments.map((dept) => (
                              <SelectItem key={dept.id} value={dept.id}>
                                {formatDepartmentName(dept.name)} ({dept.code})
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-2">
                        <Label>Title</Label>
                        <Input
                          value={title}
                          onChange={(event) => {
                            const input = event.target
                            const cursorPosition = input.selectionStart || 0
                            const newValue = event.target.value.toUpperCase()
                            setTitle(newValue)
                            // Restore cursor position after React updates
                            setTimeout(() => {
                              input.setSelectionRange(cursorPosition, cursorPosition)
                            }, 0)
                          }}
                        />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label>Description</Label>
                      <BoldOnlyEditor value={description} onChange={setDescription} />
                    </div>
                    <div className="grid gap-3 md:grid-cols-3">
                      <div className="space-y-2">
                        <Label>Repeat</Label>
                        <Select value={frequency} onValueChange={(value) => setFrequency(value as SystemTaskFrequency)}>
                          <SelectTrigger>
                            <SelectValue placeholder="Select repeat" />
                          </SelectTrigger>
                          <SelectContent>
                            {FREQUENCY_OPTIONS.map((option) => (
                              <SelectItem key={option.value} value={option.value}>
                                {option.label}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-2">
                        <Label>Finish by (optional)</Label>
                        <Select
                          value={finishPeriod}
                          onValueChange={(value) =>
                            setFinishPeriod(value as TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE)
                          }
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="Select period" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value={FINISH_PERIOD_NONE_VALUE}>{FINISH_PERIOD_NONE_LABEL}</SelectItem>
                            {FINISH_PERIOD_OPTIONS.map((value) => (
                              <SelectItem key={value} value={value}>
                                {FINISH_PERIOD_LABELS[value]}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-2">
                        <Label>Priority</Label>
                        <Select value={priority} onValueChange={(value) => setPriority(value as TaskPriority)}>
                          <SelectTrigger>
                            <SelectValue placeholder="Select priority" />
                          </SelectTrigger>
                          <SelectContent>
                            {PRIORITY_OPTIONS.map((value) => (
                              <SelectItem key={value} value={value}>
                                {PRIORITY_LABELS[value]}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                    <div className="rounded-lg border border-slate-200 bg-white p-4">
                      <div className="flex items-start gap-3">
                        <Checkbox
                          checked={requiresAlignment}
                          onCheckedChange={(value) => setRequiresAlignment(Boolean(value))}
                        />
                        <div className="flex-1">
                          <div className="text-sm font-semibold text-slate-900">Requires BZ</div>
                          {requiresAlignment ? (
                            <div className="mt-4 grid gap-3 md:grid-cols-2">
                              <div className="space-y-2">
                                <Label>BZ time</Label>
                                <Input
                                  type="time"
                                  value={alignmentTime}
                                  onChange={(event) => setAlignmentTime(event.target.value)}
                                />
                                <div className="text-[12px] text-slate-500">Required.</div>
                              </div>
                              <div className="space-y-2">
                                <Label>BZ with (managers)</Label>
                                <div className="rounded-md border border-slate-200 bg-white p-2">
                                  <div className="flex flex-wrap gap-2">
                                    {alignmentManagerIds.map((id) => {
                                      const manager = users.find((u) => u.id === id)
                                      const label = userDisplayLabel(manager) || id
                                      const initials = userInitials(label)
                                      return (
                                        <span
                                          key={id}
                                          className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-700"
                                          title={label}
                                        >
                                          {initials}
                                          <button
                                            type="button"
                                            className="text-slate-500 hover:text-slate-900"
                                            onClick={() => setAlignmentManagerIds((prev) => prev.filter((x) => x !== id))}
                                            aria-label={`Remove ${label}`}
                                          >
                                            ×
                                          </button>
                                        </span>
                                      )
                                    })}
                                    <Select
                                      value={EMPTY_VALUE}
                                      onValueChange={(value) => {
                                        if (value === EMPTY_VALUE) return
                                        setAlignmentManagerIds((prev) => (prev.includes(value) ? prev : [...prev, value]))
                                      }}
                                    >
                                      <SelectTrigger className="h-8 w-48">
                                        <SelectValue placeholder="Add manager" />
                                      </SelectTrigger>
                                      <SelectContent>
                                        <SelectItem value={EMPTY_VALUE}>Select…</SelectItem>
                                        {users
                                          .filter((u) => u.role === "MANAGER")
                                          .map((manager) => (
                                            <SelectItem key={manager.id} value={manager.id}>
                                              {manager.full_name || manager.username || ("email" in manager ? manager.email : "")}
                                            </SelectItem>
                                          ))}
                                      </SelectContent>
                                    </Select>
                                  </div>
                                </div>
                              </div>
                            </div>
                          ) : null}
                        </div>
                      </div>
                    </div>
                    {frequency === "WEEKLY" ? (
                      <div className="space-y-2">
                        <Label>Days of week</Label>
                        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                          {WEEKDAY_OPTIONS.map((day) => {
                            const checked = daysOfWeek.includes(day.value)
                            return (
                              <label key={day.value} className="flex items-center gap-2 text-sm text-slate-700">
                                <Checkbox
                                  checked={checked}
                                  onCheckedChange={() => toggleDayValue(day.value, daysOfWeek, setDaysOfWeek)}
                                />
                                <span>{day.label}</span>
                              </label>
                            )
                          })}
                          <label className="flex items-center gap-2 text-sm text-slate-600 sm:col-start-2 lg:col-start-3">
                            <Checkbox
                              checked={showWeekendDays}
                              onCheckedChange={(value) => setShowWeekendDays(Boolean(value))}
                            />
                            <span>Show weekend days</span>
                          </label>
                        </div>
                        {showWeekendDays ? (
                          <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                            {WEEKEND_OPTIONS.map((day) => {
                              const checked = daysOfWeek.includes(day.value)
                              return (
                                <label key={day.value} className="flex items-center gap-2 text-sm text-slate-700">
                                  <Checkbox
                                    checked={checked}
                                    onCheckedChange={() => toggleDayValue(day.value, daysOfWeek, setDaysOfWeek)}
                                  />
                                  <span>{day.label}</span>
                                </label>
                              )
                            })}
                          </div>
                        ) : null}
                        <p className="text-[12px] text-muted-foreground">Select one or more days.</p>
                      </div>
                    ) : null}
                    {(frequency === "MONTHLY" ||
                      frequency === "YEARLY" ||
                      frequency === "3_MONTHS" ||
                      frequency === "6_MONTHS") && (
                        <div className="grid gap-3 md:grid-cols-2">
                          <div className="space-y-2">
                            <Label>Day of month</Label>
                            <Select value={dayOfMonth} onValueChange={setDayOfMonth}>
                              <SelectTrigger>
                                <SelectValue placeholder="Select day" />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value={FIRST_WORKING_DAY_VALUE}>First working day</SelectItem>
                                <SelectItem value={END_OF_MONTH_VALUE}>End of month/year</SelectItem>
                                {DAY_OF_MONTH_OPTIONS.map((option) => (
                                  <SelectItem key={option.value} value={option.value}>
                                    {option.label}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                          </Select>
                          <div className="text-[13px] text-muted-foreground">{weekendShiftHint}</div>
                        </div>
                        <div className="space-y-2">
                          <Label>
                            {isCycleFrequency(frequency)
                              ? "Start month"
                              : isYearlyFrequency(frequency)
                                ? "Month (required)"
                                : "Month (optional)"}
                          </Label>
                          <Select value={monthOfYear} onValueChange={setMonthOfYear}>
                            <SelectTrigger>
                              <SelectValue placeholder="Select month" />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value={EMPTY_VALUE}>None</SelectItem>
                                {MONTH_OPTIONS.map((option) => (
                                  <SelectItem key={option.value} value={option.value}>
                                    {option.label}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                          </Select>
                        </div>
                      </div>
                    )}
                    <details ref={createDetailsRef} open className="rounded-lg border border-border/60 bg-muted/20 p-3">
                      <summary className="cursor-pointer text-sm font-medium text-slate-700">
                        More details (required)
                      </summary>
                      <div className="mt-3 space-y-4">
                        <div className="grid gap-3 md:grid-cols-2">
                          {INTERNAL_NOTE_FIELDS.map((field) => (
                            <div key={field.key} className="space-y-1">
                              <Label htmlFor={`create-note-${field.key}`} className="text-sm">{field.label} *</Label>
                              <Input
                                id={`create-note-${field.key}`}
                                name={field.key}
                                required
                                value={internalNotes[field.key] || ""}
                                onChange={(event) =>
                                  setInternalNoteValue(field.key, event.target.value, setInternalNotes)
                                }
                                placeholder={field.placeholder}
                                className="placeholder:text-muted-foreground/60"
                              />
                            </div>
                          ))}
                        </div>
                        <div className="space-y-2">
                          <Label htmlFor="create-note-QA" className="text-sm text-muted-foreground">
                            <span className="uppercase">Question/Answer</span> (optional)
                          </Label>
                          <Textarea
                            id="create-note-QA"
                            name="QA"
                            value={internalNotes.QA || ""}
                            onChange={(event) => setInternalNoteValue("QA", event.target.value, setInternalNotes)}
                            placeholder="Type any questions/answers..."
                            className="placeholder:text-muted-foreground/60"
                          />
                        </div>
                      </div>
                    </details>
                    <div className="space-y-2">
                      <Label>Assignees (optional)</Label>
                      {isGlobalScopeValue(departmentId) ? (
                        assigneeDeptNames.length ? (
                          <p className="text-[13px] text-muted-foreground">
                            Departments: {formatDepartmentNames(assigneeDeptNames)}
                          </p>
                        ) : (
                          <p className="text-[13px] text-muted-foreground">
                            When you select an owner, the department will appear here.
                          </p>
                        )
                      ) : null}
                      <div className="rounded-lg border border-border/60 bg-white p-2">
                        <div className="flex flex-wrap items-center gap-2">
                          {assigneeIds.map((id) => {
                            const person = userMap.get(id)
                            const email = person && "email" in person ? person.email || "" : ""
                            const label = person?.full_name || person?.username || email || id
                            return (
                              <span key={id} className="flex items-center gap-1 rounded-full bg-muted px-2 py-1 text-xs">
                                <span>{label}</span>
                                <button
                                  type="button"
                                  className="text-muted-foreground hover:text-foreground"
                                  onClick={() => removeAssignee(id)}
                                  aria-label={`Remove ${label}`}
                                >
                                  ×
                                </button>
                              </span>
                            )
                          })}
                          <Input
                            value={assigneeQuery}
                            onChange={(event) => setAssigneeQuery(event.target.value)}
                            onFocus={() => setAssigneeOpen(true)}
                            onBlur={() => setTimeout(() => setAssigneeOpen(false), 120)}
                            placeholder="Search users..."
                            className="h-8 min-w-[180px] border-0 px-0 focus-visible:ring-0"
                          />
                        </div>
                        {assigneeOpen ? (
                          <div className="mt-2 max-h-44 overflow-y-auto rounded-md border border-border/60 bg-white shadow-sm">
                            {filteredAssignees.length ? (
                              filteredAssignees.map((person) => {
                                const isSelected = assigneeIds.includes(person.id)
                                const isReplacement = person.id === zv1UserId || person.id === zv2UserId
                                const nextIds = isSelected
                                  ? assigneeIds.filter((item) => item !== person.id)
                                  : [...assigneeIds, person.id]
                                return (
                                  <button
                                    key={person.id}
                                    type="button"
                                    disabled={isReplacement && !isSelected}
                                    className="flex w-full items-center justify-between px-2 py-2 text-left text-sm hover:bg-muted/60 disabled:cursor-not-allowed disabled:opacity-50"
                                    onMouseDown={(event) => event.preventDefault()}
                                    onClick={() => handleAssigneesChange(nextIds)}
                                  >
                                    <span>{person.full_name || person.username || ("email" in person ? person.email : "")}</span>
                                    {isSelected ? <span className="text-xs text-muted-foreground">Selected</span> : null}
                                  </button>
                                )
                              })
                            ) : (
                              <div className="px-2 py-2 text-sm text-muted-foreground">No users found.</div>
                            )}
                          </div>
                        ) : null}
                      </div>
                      {assigneeError ? (
                        <div className="text-[13px] font-medium text-red-600">{assigneeError}</div>
                      ) : null}
                    </div>
                    <div className="grid gap-4 md:grid-cols-2">
                      <div className="space-y-2">
                        <Label>
                          ZV1 {replacementsRequired(assigneeIds) ? "*" : "(optional for All/10+)"}
                        </Label>
                        <Select value={zv1UserId} onValueChange={setZv1UserId}>
                          <SelectTrigger>
                            <SelectValue placeholder="Select first replacement" />
                          </SelectTrigger>
                          <SelectContent>
                            {users.map((person) => (
                              <SelectItem
                                key={person.id}
                                value={person.id}
                                disabled={assigneeIds.includes(person.id) || person.id === zv2UserId}
                              >
                                {userDisplayLabel(person)}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-2">
                        <Label>
                          ZV2 (optional)
                        </Label>
                        <Select
                          value={zv2UserId || EMPTY_VALUE}
                          onValueChange={(value) => setZv2UserId(value === EMPTY_VALUE ? "" : value)}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="Select second replacement" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value={EMPTY_VALUE}>None</SelectItem>
                            {users.map((person) => (
                              <SelectItem
                                key={person.id}
                                value={person.id}
                                disabled={assigneeIds.includes(person.id) || person.id === zv1UserId}
                              >
                                {userDisplayLabel(person)}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <Checkbox checked={isActive} onCheckedChange={(value) => setIsActive(Boolean(value))} />
                      <span className="text-base">Active</span>
                    </div>
                    <div className="space-y-2">
                      <Button
                        type="button"
                        variant={isRepetitive ? "default" : "outline"}
                        aria-pressed={isRepetitive}
                        onClick={() => setIsRepetitive((value) => !value)}
                      >
                        Detyrë e përsëritur: {isRepetitive ? "Po" : "Jo"}
                      </Button>
                      <p className="text-xs text-slate-500">Vetëm si informacion.</p>
                    </div>
                    <div className="flex items-start gap-3 rounded-lg border border-slate-200 bg-white p-4">
                      <Checkbox
                        checked={showInWeeklyPlanner}
                        onCheckedChange={(value) => setShowInWeeklyPlanner(Boolean(value))}
                      />
                      <div>
                        <div className="text-sm font-semibold text-slate-900">Show in Weekly Planner</div>
                        <div className="text-xs text-slate-500">
                          Display generated occurrences in the assigned user&apos;s SYS row.
                        </div>
                      </div>
                    </div>
                    <div className="sticky bottom-0 z-10 -mx-6 mt-6 flex items-center justify-end gap-2 border-t border-border/60 bg-white/90 px-6 py-3 backdrop-blur">
                      <Button variant="outline" onClick={() => setCreateOpen(false)}>
                        Cancel
                      </Button>
                      <Button
                        disabled={
                          saving ||
                          !title.trim() ||
                          !departmentId ||
                          (replacementsRequired(assigneeIds) && !zv1UserId)
                        }
                        onClick={() => void submit()}
                      >
                        {saving ? "Saving..." : "Save task"}
                      </Button>
                    </div>
                  </div>
                </DialogContent>
              </Dialog>

              {/* EDIT DIALOG */}
              <Dialog
                open={editOpen}
                onOpenChange={(open) => {
                  setEditOpen(open)
                  if (!open) setEditTemplate(null)
                }}
              >
                {/* EDIT DIALOG CONTENT (Same structure as create) */}
                <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-3xl">
                  <DialogHeader>
                    <DialogTitle>Edit system task</DialogTitle>
                  </DialogHeader>
                  <div className="space-y-5">
                    <div className="grid gap-4 md:grid-cols-2">
                      <div className="space-y-2">
                        <Label>Department</Label>
                        <Select value={editDepartmentId} onValueChange={handleEditDepartmentChange}>
                          <SelectTrigger>
                            <SelectValue placeholder="Select department" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value={ALL_DEPARTMENTS_VALUE}>All departments</SelectItem>
                            {departments.map((dept) => (
                              <SelectItem key={dept.id} value={dept.id}>
                                {formatDepartmentName(dept.name)} ({dept.code})
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-2">
                        <Label>Title</Label>
                        <Input
                          value={editTitle}
                          onChange={(event) => {
                            const input = event.target
                            const cursorPosition = input.selectionStart || 0
                            const newValue = event.target.value.toUpperCase()
                            setEditTitle(newValue)
                            // Restore cursor position after React updates
                            setTimeout(() => {
                              input.setSelectionRange(cursorPosition, cursorPosition)
                            }, 0)
                          }}
                        />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label>Description</Label>
                      <BoldOnlyEditor value={editDescription} onChange={setEditDescription} />
                    </div>
                    <div className="grid gap-3 md:grid-cols-3">
                      <div className="space-y-2">
                        <Label>Repeat</Label>
                        <Select
                          value={editFrequency}
                          onValueChange={(value) => setEditFrequency(value as SystemTaskFrequency)}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="Select repeat" />
                          </SelectTrigger>
                          <SelectContent>
                            {FREQUENCY_OPTIONS.map((option) => (
                              <SelectItem key={option.value} value={option.value}>
                                {option.label}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-2">
                        <Label>Finish by (optional)</Label>
                        <Select
                          value={editFinishPeriod}
                          onValueChange={(value) =>
                            setEditFinishPeriod(value as TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE)
                          }
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="Select period" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value={FINISH_PERIOD_NONE_VALUE}>{FINISH_PERIOD_NONE_LABEL}</SelectItem>
                            {FINISH_PERIOD_OPTIONS.map((value) => (
                              <SelectItem key={value} value={value}>
                                {FINISH_PERIOD_LABELS[value]}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-2">
                        <Label>Priority</Label>
                        <Select value={editPriority} onValueChange={(value) => setEditPriority(value as TaskPriority)}>
                          <SelectTrigger>
                            <SelectValue placeholder="Select priority" />
                          </SelectTrigger>
                          <SelectContent>
                            {PRIORITY_OPTIONS.map((value) => (
                              <SelectItem key={value} value={value}>
                                {PRIORITY_LABELS[value]}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                    <div className="rounded-lg border border-slate-200 bg-white p-4">
                      <div className="flex items-start gap-3">
                        <Checkbox
                          checked={editRequiresAlignment}
                          onCheckedChange={(value) => setEditRequiresAlignment(Boolean(value))}
                        />
                        <div className="flex-1">
                          <div className="text-sm font-semibold text-slate-900">Requires BZ</div>
                          <div className="text-xs text-slate-500 mt-1">
                            If enabled, the task should be BZ with managers at the specified time.
                          </div>
                          {editRequiresAlignment ? (
                            <div className="mt-4 grid gap-3 md:grid-cols-2">
                              <div className="space-y-2">
                                <Label>BZ time</Label>
                                <Input
                                  type="time"
                                  value={editAlignmentTime}
                                  onChange={(event) => setEditAlignmentTime(event.target.value)}
                                />
                                <div className="text-[12px] text-slate-500">Required.</div>
                              </div>
                              <div className="space-y-2">
                                <Label>BZ with (managers)</Label>
                                <div className="rounded-md border border-slate-200 bg-white p-2">
                                  <div className="flex flex-wrap gap-2">
                                    {editAlignmentManagerIds.map((id) => {
                                      const manager = users.find((u) => u.id === id)
                                      const label = userDisplayLabel(manager) || id
                                      const initials = userInitials(label)
                                      return (
                                        <span
                                          key={id}
                                          className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-700"
                                          title={label}
                                        >
                                          {initials}
                                          <button
                                            type="button"
                                            className="text-slate-500 hover:text-slate-900"
                                            onClick={() => setEditAlignmentManagerIds((prev) => prev.filter((x) => x !== id))}
                                            aria-label={`Remove ${label}`}
                                          >
                                            ×
                                          </button>
                                        </span>
                                      )
                                    })}
                                    <Select
                                      value={EMPTY_VALUE}
                                      onValueChange={(value) => {
                                        if (value === EMPTY_VALUE) return
                                        setEditAlignmentManagerIds((prev) => (prev.includes(value) ? prev : [...prev, value]))
                                      }}
                                    >
                                      <SelectTrigger className="h-8 w-48">
                                        <SelectValue placeholder="Add manager" />
                                      </SelectTrigger>
                                      <SelectContent>
                                        <SelectItem value={EMPTY_VALUE}>Select…</SelectItem>
                                        {users
                                          .filter((u) => u.role === "MANAGER")
                                          .map((manager) => (
                                            <SelectItem key={manager.id} value={manager.id}>
                                              {manager.full_name || manager.username || ("email" in manager ? manager.email : "")}
                                            </SelectItem>
                                          ))}
                                      </SelectContent>
                                    </Select>
                                  </div>
                                </div>
                              </div>
                            </div>
                          ) : null}
                        </div>
                      </div>
                    </div>
                    {editFrequency === "WEEKLY" ? (
                      <div className="space-y-2">
                        <Label>Days of week</Label>
                        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                          {WEEKDAY_OPTIONS.map((day) => {
                            const checked = editDaysOfWeek.includes(day.value)
                            return (
                              <label key={day.value} className="flex items-center gap-2 text-sm text-slate-700">
                                <Checkbox
                                  checked={checked}
                                  onCheckedChange={() =>
                                    toggleDayValue(day.value, editDaysOfWeek, setEditDaysOfWeek)
                                  }
                                />
                                <span>{day.label}</span>
                              </label>
                            )
                          })}
                          <label className="flex items-center gap-2 text-sm text-slate-600 sm:col-start-2 lg:col-start-3">
                            <Checkbox
                              checked={editShowWeekendDays}
                              onCheckedChange={(value) => setEditShowWeekendDays(Boolean(value))}
                            />
                            <span>Show weekend days</span>
                          </label>
                        </div>
                        {editShowWeekendDays ? (
                          <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                            {WEEKEND_OPTIONS.map((day) => {
                              const checked = editDaysOfWeek.includes(day.value)
                              return (
                                <label key={day.value} className="flex items-center gap-2 text-sm text-slate-700">
                                  <Checkbox
                                    checked={checked}
                                    onCheckedChange={() =>
                                      toggleDayValue(day.value, editDaysOfWeek, setEditDaysOfWeek)
                                    }
                                  />
                                  <span>{day.label}</span>
                                </label>
                              )
                            })}
                          </div>
                        ) : null}
                        <p className="text-[12px] text-muted-foreground">Select one or more days.</p>
                      </div>
                    ) : null}
                    {(editFrequency === "MONTHLY" ||
                      editFrequency === "YEARLY" ||
                      editFrequency === "3_MONTHS" ||
                      editFrequency === "6_MONTHS") && (
                        <div className="grid gap-3 md:grid-cols-2">
                          <div className="space-y-2">
                            <Label>Day of month</Label>
                            <Select value={editDayOfMonth} onValueChange={setEditDayOfMonth}>
                              <SelectTrigger>
                                <SelectValue placeholder="Select day" />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value={FIRST_WORKING_DAY_VALUE}>First working day</SelectItem>
                                <SelectItem value={END_OF_MONTH_VALUE}>End of month/year</SelectItem>
                                {DAY_OF_MONTH_OPTIONS.map((option) => (
                                  <SelectItem key={option.value} value={option.value}>
                                    {option.label}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                          </Select>
                          <div className="text-[13px] text-muted-foreground">{weekendShiftHint}</div>
                        </div>
                        <div className="space-y-2">
                          <Label>
                            {isCycleFrequency(editFrequency)
                              ? "Start month"
                              : isYearlyFrequency(editFrequency)
                                ? "Month (required)"
                                : "Month (optional)"}
                          </Label>
                          <Select value={editMonthOfYear} onValueChange={setEditMonthOfYear}>
                            <SelectTrigger>
                              <SelectValue placeholder="Select month" />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value={EMPTY_VALUE}>None</SelectItem>
                                {MONTH_OPTIONS.map((option) => (
                                  <SelectItem key={option.value} value={option.value}>
                                    {option.label}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                        </div>
                      )}
                    <details className="rounded-lg border border-border/60 bg-muted/20 p-3">
                      <summary className="cursor-pointer text-sm font-medium text-slate-700">
                        More details
                      </summary>
                      <div className="mt-3 space-y-4">
                        <div className="grid gap-3 md:grid-cols-2">
                          {INTERNAL_NOTE_FIELDS.map((field) => (
                            <div key={field.key} className="space-y-1">
                              <Label className="text-sm">{field.label}</Label>
                              <Input
                                value={editInternalNotes[field.key] || ""}
                                onChange={(event) => {
                                  const newValue = event.target.value
                                  setEditInternalNotes((prev) => ({
                                    ...prev,
                                    [field.key]: newValue,
                                  }))
                                }}
                                placeholder={field.placeholder}
                                className="placeholder:text-muted-foreground/60"
                              />
                            </div>
                          ))}
                        </div>
                        <div className="space-y-2">
                          <Label className="text-sm text-muted-foreground ">
                            <span className="uppercase">Question/Answer</span> (optional)
                          </Label>
                          <Textarea
                            value={editInternalNotes.QA || ""}
                            onChange={(event) => setInternalNoteValue("QA", event.target.value, setEditInternalNotes)}
                            placeholder="Type any questions/answers..."
                            className="placeholder:text-muted-foreground/60"
                          />
                        </div>
                      </div>
                    </details>
                    <div className="space-y-2">
                      <Label>Assignees (optional)</Label>
                      {isGlobalScopeValue(editDepartmentId) ? (
                        editAssigneeDeptNames.length ? (
                          <p className="text-[13px] text-muted-foreground">
                            Departments: {formatDepartmentNames(editAssigneeDeptNames)}
                          </p>
                        ) : (
                          <p className="text-[13px] text-muted-foreground">
                            When you select an owner, the department will appear here.
                          </p>
                        )
                      ) : null}
                      <div className="rounded-lg border border-border/60 bg-white p-2">
                        <div className="flex flex-wrap items-center gap-2">
                          {editAssigneeIds.map((id) => {
                            const person = userMap.get(id)
                            const email = person && "email" in person ? person.email || "" : ""
                            const label = person?.full_name || person?.username || email || id
                            return (
                              <span key={id} className="flex items-center gap-1 rounded-full bg-muted px-2 py-1 text-xs">
                                <span>{label}</span>
                                <button
                                  type="button"
                                  className="text-muted-foreground hover:text-foreground"
                                  onClick={() => removeEditAssignee(id)}
                                  aria-label={`Remove ${label}`}
                                >
                                  ×
                                </button>
                              </span>
                            )
                          })}
                          <Input
                            value={editAssigneeQuery}
                            onChange={(event) => setEditAssigneeQuery(event.target.value)}
                            onFocus={() => setEditAssigneeOpen(true)}
                            onBlur={() => setTimeout(() => setEditAssigneeOpen(false), 120)}
                            placeholder="Search users..."
                            className="h-8 min-w-[180px] border-0 px-0 focus-visible:ring-0"
                          />
                        </div>
                        {editAssigneeOpen ? (
                          <div className="mt-2 max-h-44 overflow-y-auto rounded-md border border-border/60 bg-white shadow-sm">
                            {filteredEditAssignees.length ? (
                              filteredEditAssignees.map((person) => {
                                const isSelected = editAssigneeIds.includes(person.id)
                                const isReplacement =
                                  person.id === editZv1UserId || person.id === editZv2UserId
                                const nextIds = isSelected
                                  ? editAssigneeIds.filter((item) => item !== person.id)
                                  : [...editAssigneeIds, person.id]
                                return (
                                  <button
                                    key={person.id}
                                    type="button"
                                    disabled={isReplacement && !isSelected}
                                    className="flex w-full items-center justify-between px-2 py-2 text-left text-sm hover:bg-muted/60 disabled:cursor-not-allowed disabled:opacity-50"
                                    onMouseDown={(event) => event.preventDefault()}
                                    onClick={() => handleEditAssigneesChange(nextIds)}
                                  >
                                    <span>{person.full_name || person.username || ("email" in person ? person.email : "")}</span>
                                    {isSelected ? <span className="text-xs text-muted-foreground">Selected</span> : null}
                                  </button>
                                )
                              })
                            ) : (
                              <div className="px-2 py-2 text-sm text-muted-foreground">No users found.</div>
                            )}
                          </div>
                        ) : null}
                      </div>
                      {editAssigneeError ? (
                        <div className="text-[13px] font-medium text-red-600">{editAssigneeError}</div>
                      ) : null}
                    </div>
                    <div className="grid gap-4 md:grid-cols-2">
                      <div className="space-y-2">
                        <Label>
                          ZV1 {replacementsRequired(editAssigneeIds) ? "*" : "(optional for All/10+)"}
                        </Label>
                        <Select value={editZv1UserId} onValueChange={setEditZv1UserId}>
                          <SelectTrigger>
                            <SelectValue placeholder="Select first replacement" />
                          </SelectTrigger>
                          <SelectContent>
                            {users.map((person) => (
                              <SelectItem
                                key={person.id}
                                value={person.id}
                                disabled={editAssigneeIds.includes(person.id) || person.id === editZv2UserId}
                              >
                                {userDisplayLabel(person)}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-2">
                        <Label>
                          ZV2 (optional)
                        </Label>
                        <Select
                          value={editZv2UserId || EMPTY_VALUE}
                          onValueChange={(value) => setEditZv2UserId(value === EMPTY_VALUE ? "" : value)}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="Select second replacement" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value={EMPTY_VALUE}>None</SelectItem>
                            {users.map((person) => (
                              <SelectItem
                                key={person.id}
                                value={person.id}
                                disabled={editAssigneeIds.includes(person.id) || person.id === editZv1UserId}
                              >
                                {userDisplayLabel(person)}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <Checkbox checked={editIsActive} onCheckedChange={(value) => setEditIsActive(Boolean(value))} />
                      <span className="text-base">Active</span>
                    </div>
                    <div className="space-y-2">
                      <Button
                        type="button"
                        variant={editIsRepetitive ? "default" : "outline"}
                        aria-pressed={editIsRepetitive}
                        onClick={() => setEditIsRepetitive((value) => !value)}
                      >
                        Detyrë e përsëritur: {editIsRepetitive ? "Po" : "Jo"}
                      </Button>
                      <p className="text-xs text-slate-500">Vetëm si informacion.</p>
                    </div>
                    <div className="flex items-start gap-3 rounded-lg border border-slate-200 bg-white p-4">
                      <Checkbox
                        checked={editShowInWeeklyPlanner}
                        onCheckedChange={(value) => setEditShowInWeeklyPlanner(Boolean(value))}
                      />
                      <div>
                        <div className="text-sm font-semibold text-slate-900">Show in Weekly Planner</div>
                        <div className="text-xs text-slate-500">
                          Display generated occurrences in the assigned user&apos;s SYS row.
                        </div>
                      </div>
                    </div>
                    <div className="sticky bottom-0 z-10 -mx-6 mt-6 flex items-center justify-end gap-2 border-t border-border/60 bg-white/90 px-6 py-3 backdrop-blur">
                      <Button variant="outline" onClick={() => setEditOpen(false)}>
                        Cancel
                      </Button>
                      <Button
                        disabled={
                          editSaving ||
                          !editTitle.trim() ||
                          !editDepartmentId ||
                          (replacementsRequired(editAssigneeIds) && !editZv1UserId)
                        }
                        onClick={() => void submitEdit()}
                      >
                        {editSaving ? "Saving..." : "Save changes"}
                      </Button>
                    </div>
                  </div>
                </DialogContent>
              </Dialog>

              <Dialog
                open={Boolean(rejectTemplate)}
                onOpenChange={(open) => {
                  if (!open) {
                    setRejectTemplate(null)
                    setRejectReason("")
                  }
                }}
              >
                <DialogContent className="max-w-md">
                  <DialogHeader>
                    <DialogTitle>Reject system task</DialogTitle>
                  </DialogHeader>
                  <div className="space-y-3">
                    <div className="text-sm text-slate-600">
                      {rejectTemplate ? `Reject "${rejectTemplate.title}" and keep it in rejected system tasks.` : ""}
                    </div>
                    <div className="space-y-2">
                      <Label>Reason</Label>
                      <Textarea
                        value={rejectReason}
                        onChange={(event) => setRejectReason(event.target.value)}
                        placeholder="Enter the reason for rejection..."
                        rows={4}
                      />
                    </div>
                    <div className="flex justify-end gap-2">
                      <Button
                        variant="outline"
                        onClick={() => {
                          setRejectTemplate(null)
                          setRejectReason("")
                        }}
                      >
                        Cancel
                      </Button>
                      <Button
                        variant="destructive"
                        disabled={!rejectReason.trim() || Boolean(rejectTemplate && rejectingTemplateId === rejectTemplate.id)}
                        onClick={() => void submitReject()}
                      >
                        {rejectTemplate && rejectingTemplateId === rejectTemplate.id ? "Rejecting..." : "Reject"}
                      </Button>
                    </div>
                  </div>
                </DialogContent>
              </Dialog>

              {!canCreate ? (
                <span className="text-base text-muted-foreground">Only managers or admins can add tasks.</span>
              ) : null}
            </div>
          ) : null}
        </div>

        {showFilters ? (
          <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-slate-100 pt-3">
            <div className="relative flex min-w-[220px] flex-1 items-center">
              <span className="pointer-events-none absolute left-3 text-slate-400">
                <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" className="h-4 w-4">
                  <path
                    d="M14.5 14.5L18 18"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                  />
                  <circle cx="8.75" cy="8.75" r="5.75" stroke="currentColor" strokeWidth="1.5" />
                </svg>
              </span>
              <Input
                ref={searchInputRef}
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Search by task name..."
                className="h-9 border-slate-200 bg-slate-50 pl-9 pr-16 text-sm focus:bg-white transition-colors"
              />
              <span className="pointer-events-none absolute right-2 rounded border border-slate-200 bg-white px-1.5 py-0.5 text-[11px] text-slate-500">
                Ctrl K
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    className={cn(filterTriggerClass, frequencyFilterActive && filterTriggerActiveClass)}
                  >
                    Frequency: {frequencyLabel}
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent className="w-64">
                  <DropdownMenuLabel>Frequency</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  {FREQUENCY_CHIPS.map((chip) => {
                    const isAll = chip.id === "all"
                    const isCombined = chip.id === "3_6_MONTHS"
                    const active = isAll
                      ? allFrequenciesSelected
                      : isCombined
                        ? combinedSelected
                        : frequencyFilters.includes(chip.id as SystemTaskFrequency)
                    const count = isAll
                      ? scopeTemplates.length
                      : isCombined
                        ? (frequencyCounts.get("3_MONTHS") ?? 0) + (frequencyCounts.get("6_MONTHS") ?? 0)
                        : frequencyCounts.get(chip.id as SystemTaskFrequency) ?? 0
                    return (
                      <DropdownMenuCheckboxItem
                        key={chip.id}
                        checked={active}
                        onCheckedChange={() =>
                          toggleFrequencyFilter(chip.id as SystemTaskFrequency | "all" | "3_6_MONTHS")
                        }
                      >
                        <span className="flex flex-1 items-center justify-between">
                          <span>{chip.label}</span>
                          <span className="text-base text-muted-foreground">({count})</span>
                        </span>
                      </DropdownMenuCheckboxItem>
                    )
                  })}
                  <DropdownMenuSeparator />
                  <DropdownMenuCheckboxItem
                    checked={frequencyMultiSelect}
                    onCheckedChange={(value) => setFrequencyMultiSelect(Boolean(value))}
                  >
                    Multi-select frequencies
                  </DropdownMenuCheckboxItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    className={cn(filterTriggerClass, priorityFilterActive && filterTriggerActiveClass)}
                  >
                    Priority: {priorityLabel}
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent className="w-56">
                  <DropdownMenuLabel>Priority</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuRadioGroup
                    value={allPrioritiesSelected ? "all" : (priorityFilters[0] as TaskPriority)}
                    onValueChange={(value) => togglePriorityFilter(value as TaskPriority | "all")}
                  >
                    <DropdownMenuRadioItem value="all">
                      <span className="flex flex-1 items-center justify-between">
                        <span>All</span>
                        <span className="text-base text-muted-foreground">({scopeTemplates.length})</span>
                      </span>
                    </DropdownMenuRadioItem>
                    {PRIORITY_OPTIONS.map((value) => (
                      <DropdownMenuRadioItem key={value} value={value}>
                        <span className="flex flex-1 items-center justify-between">
                          <span>{PRIORITY_LABELS[value]}</span>
                          <span className="text-base text-muted-foreground">({priorityCounts.get(value) ?? 0})</span>
                        </span>
                      </DropdownMenuRadioItem>
                    ))}
                  </DropdownMenuRadioGroup>
                </DropdownMenuContent>
              </DropdownMenu>
              <Button
                variant="ghost"
                onClick={resetFilters}
                size="sm"
                className="h-8 px-3 text-sm text-red-600 hover:bg-red-50 hover:text-red-700"
              >
                Clear filters
              </Button>
            </div>
          </div>
        ) : null}
      </div>

      {loading ? (
        <div className="py-8 text-center text-sm text-muted-foreground">Loading tasks...</div>
      ) : approvalView === "pending" ? (
        pendingTemplates.length ? (
          renderApprovalSection(
            "New System Tasks",
            "Submitted system tasks waiting for manager/admin approval.",
            pendingTemplates,
            "pending"
          )
        ) : (
          <div className="rounded-lg border bg-white py-12 text-center text-sm text-muted-foreground">
            No new system tasks waiting for approval.
          </div>
        )
      ) : approvalView === "rejected" ? (
        rejectedTemplates.length ? (
          renderApprovalSection(
            "Rejected System Tasks",
            "Rejected submissions kept for review and editing.",
            rejectedTemplates,
            "rejected"
          )
        ) : (
          <div className="rounded-lg border bg-white py-12 text-center text-sm text-muted-foreground">
            No rejected system tasks.
          </div>
        )
      ) : sections.length ? (
        <div
          id="system-task-table"
          className={cn(
            "relative w-full rounded-lg border bg-white shadow-sm print:rounded-none print:border-slate-900 print:shadow-none",
            printing && "print:border-0 print:shadow-none"
          )}
        >
          {/* SCROLL WRAPPER for responsive table */}
          <div className="overflow-x-auto lg:overflow-visible print:overflow-visible">
            {/* STICKY HEADER ROW */}
            <div className="w-full print:min-w-0">
              <div className="sticky top-[var(--system-tasks-sticky-offset)] z-30 print:static">
                <div className="border-b bg-slate-50/95 backdrop-blur py-2 sm:py-2.5 md:py-3 px-2 sm:px-3 md:px-4 print:bg-white print:backdrop-blur-0 print:px-2 print:py-2 print:border-slate-900">
                  <div
                    className={cn(
                      gridClass,
                      "text-[10px] sm:text-[10.5px] md:text-[11px] font-bold uppercase tracking-wider text-slate-500 print:border print:border-slate-900 print:px-2 print:gap-0 print:divide-x print:divide-slate-900 print:text-slate-900 print:[&>*]:px-2 print:[&>*]:py-2"
                    )}
                  >
                    <div>No.</div>
                    <div>Task Title</div>
                    <div>Department</div>
                    <div>{showSystemActions ? "Assignees" : "Owner"}</div>
                    <div>ZV1 / ZV2</div>
                    {showBzTimeColumn ? <div>BZ Time</div> : null}
                    <div className="hidden sm:block">Frequency</div>
                    <div className="hidden md:block">Finish by</div>
                    <div>Priority</div>
                    <div className="text-right">Actions</div>
                  </div>
                </div>
              </div>

              {/* TABLE BODY */}
              <div className="p-2 sm:p-3 md:p-4 space-y-2 bg-slate-50 print:bg-white print:p-0 print:space-y-0">
                {(() => {
                  let globalIndex = 0
                  return sections.map((section) => (
                    <React.Fragment key={section.id}>
                      {section.templates.length ? (
                        section.templates.map((template, index) => {
                          const taskNumber = globalIndex + 1
                          globalIndex++
                        const priorityValue = normalizePriority(template.priority)
                        const departmentLabel = templateDepartmentLabel(template)
                        const ownerLabel = assigneeSummary(template.assignees)
                        const ownerTitle = assigneeSummaryTitle(template.assignees)
                        const isUnassignedAll = !template.department_id && !template.default_assignee_id
                        const frequencyLabel =
                          FREQUENCY_OPTIONS.find((option) => option.value === template.frequency)?.label ??
                          template.frequency
                        const bzTimeValue = timeInputValue(template.alignment_time)
                        const bzTimeLabel =
                          template.requires_alignment && bzTimeValue ? bzTimeValue : "-"

                        const isInactive = template.is_active === false
                        const showInactiveDivider =
                          isInactive && (index === 0 || section.templates[index - 1]?.is_active !== false)

                        // Grouping Logic
                        const prev = index > 0 ? section.templates[index - 1] : null
                        const prevPriority = prev ? normalizePriority(prev.priority) : null
                        const showFrequencyDivider =
                          !isInactive &&
                          (index === 0 || (prev && prev.frequency !== template.frequency))

                        const showPriorityDivider =
                          !isInactive &&
                          !showFrequencyDivider &&
                          prevPriority !== null &&
                          prevPriority !== priorityValue &&
                          priorityValue === "HIGH"

                        const templateKey = template.id
                        return (
                          <React.Fragment key={templateKey}>
                            {/* Dividers */}
                            {showInactiveDivider && (
                              <div className="col-span-full border-b border-dashed bg-slate-50 px-2 py-2 text-xs font-semibold uppercase text-slate-400 print:border print:border-slate-900 print:bg-slate-100 print:text-slate-700 print:rounded-none">
                                Inactive Tasks
                              </div>
                            )}
                            {showPriorityDivider && (
                              <div className="col-span-full rounded border-l-4 border-l-transparent bg-red-50 px-2 py-1.5 text-[10px] font-bold uppercase tracking-widest text-red-400 print:border print:border-slate-900 print:bg-slate-100 print:text-slate-700 print:rounded-none">
                                High Priority
                              </div>
                            )}
                            {showFrequencyDivider && (
                              <div className="col-span-full rounded border-l-4 border-l-transparent bg-slate-100 px-2 py-1.5 text-[10px] font-bold uppercase tracking-widest text-slate-400 print:border print:border-slate-900 print:bg-slate-100 print:text-slate-700 print:rounded-none">
                                {frequencyLabel}
                              </div>
                            )}

                            {/* Task Row (Card Style) */}
                            <div
                              className={cn(
                                gridClass,
                                "py-3 bg-white border border-slate-200 border-l-4 transition-colors hover:bg-slate-50 print:gap-0 print:divide-x print:divide-slate-900 print:border-slate-900 print:border-l-slate-900 print:rounded-none print:shadow-none print:px-2 print:[&>*]:px-2 print:[&>*]:py-2",
                                PRIORITY_BORDER_STYLES[priorityValue],
                                isInactive && "opacity-60 grayscale"
                              )}
                            >
                              <div className="text-xs sm:text-sm font-semibold text-slate-600">
                                {taskNumber}
                              </div>
                              {/* Title Only (Description removed from list view) */}
                              <div className="min-w-0 pr-2 sm:pr-4">
                                <div className="text-[13px] sm:text-[14px] md:text-[15px] font-semibold leading-tight text-slate-900 break-words" title={template.title}>
                                  {template.title}
                                </div>
                                {template.is_repetitive && (
                                  <Badge variant="outline" className="mt-1 text-[11px]">Detyrë e përsëritur</Badge>
                                )}
                              </div>

                              <div className="truncate text-xs sm:text-sm text-slate-700 font-normal" title={departmentLabel}>
                                {departmentLabel}
                              </div>

                              <div
                                className={cn(
                                  "text-xs sm:text-sm text-slate-700 font-normal",
                                  showSystemActions ? "space-y-1" : "truncate"
                                )}
                                title={!showSystemActions && ownerLabel !== "-" ? ownerTitle : ""}
                              >
                                {showSystemActions
                                  ? renderManagementAssignees(template)
                                  : ownerLabel === "-" && isUnassignedAll
                                    ? <span className="text-slate-400">-</span>
                                    : ownerLabel}
                              </div>

                              <div>{renderReplacements(template)}</div>

                              {showBzTimeColumn ? (
                                <div className="text-xs sm:text-sm text-slate-700 font-normal">
                                  {bzTimeLabel}
                                </div>
                              ) : null}

                              <div className="hidden sm:block">
                                <span className="text-xs sm:text-sm text-slate-700 font-normal">
                                  {frequencyLabel}
                                </span>
                              </div>

                              <div className="hidden md:block text-xs sm:text-sm text-slate-700 font-normal">
                                {template.finish_period || "-"}
                              </div>

                              <div>
                                <Badge
                                  variant="outline"
                                  className={cn("px-1.5 sm:px-2 py-0.5 text-[11px] sm:text-[12px] md:text-[13px] border", PRIORITY_BADGE_STYLES[priorityValue])}
                                >
                                  {PRIORITY_LABELS[priorityValue]}
                                </Badge>
                              </div>

                              <div className="text-right">
                                <div className="flex flex-col items-end gap-2">
                                  {canEditTemplate(template) && (
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      className="h-7 w-full border border-transparent text-xs text-slate-500 hover:border-slate-200 hover:bg-white hover:text-blue-600"
                                      onClick={() => startEdit(template)}
                                    >
                                      Edit
                                    </Button>
                                  )}
                                  {user?.role === "ADMIN" && (
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      disabled={deletingTemplateId === template.id}
                                      className="h-7 w-full border border-transparent text-xs text-red-600 hover:border-red-200 hover:bg-red-50 hover:text-red-700"
                                      onClick={() => void deleteTemplate(template)}
                                    >
                                      {deletingTemplateId === template.id ? "Deleting..." : "Delete"}
                                    </Button>
                                  )}
                                </div>
                              </div>
                            </div>
                          </React.Fragment>
                        )
                      })
                    ) : (
                      <div className="py-12 text-center text-sm text-muted-foreground">
                        No system task templates found.
                      </div>
                    )}
                  </React.Fragment>
                  ))
                })()}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-slate-300 p-8 text-center text-sm text-muted-foreground bg-slate-50">
          No system task templates match the current filters.
        </div>
      )}
    </div>
  )
}

export default function SystemTasksPage() {
  return <SystemTasksView />
}
