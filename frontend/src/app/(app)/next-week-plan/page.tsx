"use client"

import * as React from "react"
import Link from "next/link"
import { useSearchParams } from "next/navigation"
import { Bold, Calendar as CalendarIcon, Check, Clock, FileDown, FileSpreadsheet, FileText, Image as ImageIcon, List, ListOrdered, ListTodo, Paperclip, Pencil, Printer, Trash2, Upload } from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { TaskTitleLimitHint } from "@/components/task-title-limit-hint"
import { Checkbox } from "@/components/ui/checkbox"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { BoldOnlyEditor } from "@/components/bold-only-editor"
import { useConfirm } from "@/components/providers/confirm-dialog-provider"
import { useAuth } from "@/lib/auth"
import { formatDepartmentName } from "@/lib/department-name"
import { fetchUsersLookupCached } from "@/lib/users-cache"
import type { Department, PlanNote, PlanNoteAttachment, Project, PxJavPlanningBrief, Task, TaskAssignee, TaskFinishPeriod, TaskPriority, UserLookup } from "@/lib/types"

type NoteType = "GA" | "KA"
type NotePriority = "NORMAL" | "HIGH" | "NONE"

type OneHMarker = "EXCLAMATION" | "QUESTION" | "KA" | "GENT" | "FLAG" | "F" | "BZ1N1" | "M2" | "M3" | "M2_M3" | "MONITOR" | "CLOSE" | "CLIENT_URGENT" | "SHARE"
const ONE_H_MARKER_NONE = "__none__"
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
const oneHMarkerLabel = (value?: OneHMarker | null, byGa = false) => {
  const label = ONE_H_MARKER_OPTIONS.find((option) => option.value === value)?.label || ""
  return label && byGa ? `(${label})` : label
}

const TYPE_BADGE: Record<NoteType, string> = {
  GA: "bg-amber-100 text-amber-800 border-amber-200",
  KA: "bg-cyan-100 text-cyan-800 border-cyan-200",
}

const PRIORITY_BADGE: Record<Exclude<NotePriority, "NONE">, string> = {
  NORMAL: "bg-emerald-100 text-emerald-800 border-emerald-200",
  HIGH: "bg-rose-100 text-rose-800 border-rose-200",
}

const NOTE_TO_TASK_PRIORITY: Record<NotePriority, TaskPriority> = {
  NONE: "NORMAL",
  NORMAL: "NORMAL",
  HIGH: "HIGH",
}

const PRIORITY_OPTIONS: TaskPriority[] = ["NORMAL", "HIGH"]
const TASK_TYPE_OPTIONS_NO_PROJECT = ["NORMAL", "R1", "1H", "PERSONAL", "BLLOK"] as const
const TASK_TYPE_OPTIONS_WITH_PROJECT = ["NORMAL", "HIGH", "1H", "R1", "PERSONAL", "BLLOK"] as const
type TaskTypeOption = typeof TASK_TYPE_OPTIONS_NO_PROJECT[number] | TaskPriority
const FINISH_PERIOD_OPTIONS: TaskFinishPeriod[] = ["AM", "PM"]
const FINISH_PERIOD_NONE_VALUE = "__none__"
const ONE_H_REPORT_SLOT_OPTIONS = ["10:00", "11:00", "11:50", "14:20", "16:00"] as const
type OneHReportSlot = typeof ONE_H_REPORT_SLOT_OPTIONS[number]
const ONE_H_REPORT_SLOT_NONE_VALUE = "__none__"
const ONE_H_REPORT_SLOTS_BY_PERIOD: Record<TaskFinishPeriod, readonly OneHReportSlot[]> = {
  AM: ["10:00", "11:00", "11:50"],
  PM: ["14:20", "16:00"],
}
const TASK_PRIORITY_STYLES: Record<string, string> = {
  HIGH: "bg-rose-50 text-rose-700",
  NORMAL: "bg-blue-50 text-blue-700",
}
const TASK_STATUS_STYLES: Record<string, { label: string; dot: string; pill: string }> = {
  TODO: { label: "TODO", dot: "bg-slate-500", pill: "bg-slate-100 text-slate-700" },
  IN_PROGRESS: { label: "In progress", dot: "bg-amber-500", pill: "bg-amber-50 text-amber-700" },
  WAITING_CLIENT: { label: "WFE", dot: "bg-[#B8860B]", pill: "bg-[#E2C15B] text-[#4F3A00]" },
  WAITING_CONFIRMATION: { label: "Waiting Confirmation", dot: "bg-blue-600", pill: "bg-blue-50 text-blue-700" },
  DONE: { label: "Done", dot: "bg-emerald-500", pill: "bg-emerald-50 text-emerald-700" },
}
const MAX_ATTACHMENT_FILES = 20
const MAX_ATTACHMENT_MB = 25
const MAX_ATTACHMENT_BYTES = MAX_ATTACHMENT_MB * 1024 * 1024
const INITIAL_NOTES_RENDER_LIMIT = 80
const NOTES_RENDER_BATCH_SIZE = 80
const PLAN_NOTES_PAGE_SIZE = 200
const EMAIL_MARKER_RE = /(^|\s)em:/i
const DONE_MARK_START = "[[done]]"
const DONE_MARK_END = "[[/done]]"
const ADDED_MARK_START = "[[added]]"
const ADDED_MARK_END = "[[/added]]"
const NOTE_MARK_TOKEN_RE = /\[\[(done|added)\]\]|\[\[\/(done|added)\]\]/g

type NormalizedTaskStatus = "TODO" | "IN_PROGRESS" | "WAITING_CLIENT" | "WAITING_CONFIRMATION" | "DONE" | "UNKNOWN"
type TaskStatusFilter = "all" | "notes" | "tasks" | "open" | "closed" | NormalizedTaskStatus
type ContentFilter = "all" | "emails"
type NextWeekFilter = "all" | "checked" | "unchecked"
type TextMarkRange = { start: number; end: number }
type DoneMarkRange = TextMarkRange
type PlanningTextField = "dl" | "dg_kush" | "kush" | "sq"
function planningBriefProgress(brief?: PxJavPlanningBrief | null) {
  if (!brief) return 0
  return [
    Boolean(brief.dl?.trim()),
    Boolean(brief.lloji_det),
    typeof brief.dg === "boolean" && (!brief.dg || Boolean(brief.dg_kush?.trim())),
    Boolean(brief.hapat?.trim()),
    Boolean(brief.kush?.trim()),
    Boolean(brief.sq?.trim()),
  ].filter(Boolean).length
}

function planningBriefDraft(brief?: PxJavPlanningBrief | null): PxJavPlanningBrief {
  return {
    dl: brief?.dl || "",
    lloji_det: brief?.lloji_det || null,
    dg: typeof brief?.dg === "boolean" ? brief.dg : null,
    dg_kush: brief?.dg_kush || "",
    dg_kush_user_ids: brief?.dg_kush_user_ids || [],
    hapat: brief?.hapat || "",
    kush: brief?.kush || "",
    kush_user_ids: brief?.kush_user_ids || [],
    sq: brief?.sq || "",
  }
}
type NoteTaskInfo = {
  assignees: TaskAssignee[]
  description: string | null
  taskId: string | null
  taskDepartmentId: string | null
  taskProjectId: string | null
  taskStatus: string | null
  taskStatuses: string[]
  taskTypeLabels: string[]
  dueDate?: string | null
  startDate?: string | null
  finishPeriod?: TaskFinishPeriod | null
  isDeadlineImportant?: boolean | null
  isRepetitive?: boolean | "indeterminate"
}

type CommonLeaveItem = {
  entryId?: string
  person: string
  startDate: string
  endDate: string
  fullDay: boolean
  isAllUsers?: boolean
  userId?: string | null
}
type CommonViewLeavePayload = {
  items?: {
    leave?: CommonLeaveItem[]
  }
}

const pad2 = (value: number) => String(value).padStart(2, "0")
const toISODate = (value: Date) => `${value.getFullYear()}-${pad2(value.getMonth() + 1)}-${pad2(value.getDate())}`

const getMonday = (value: Date) => {
  const date = new Date(value.getFullYear(), value.getMonth(), value.getDate())
  const day = date.getDay()
  date.setDate(date.getDate() - (day === 0 ? 6 : day - 1))
  return date
}

const addDays = (isoDate: string, days: number) => {
  const date = new Date(`${isoDate}T12:00:00`)
  date.setDate(date.getDate() + days)
  return toISODate(date)
}

const dateRangeKey = (startIso: string, endIso: string) => {
  const dates: string[] = []
  for (let date = startIso; date <= endIso; date = addDays(date, 1)) {
    dates.push(date)
  }
  return dates.join("|")
}

const formatISODateDMY = (value?: string | null) => {
  if (!value) return ""
  const iso = value.slice(0, 10)
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  if (!match) return value
  return `${match[3]}/${match[2]}/${match[1]}`
}

function oneHReportSlotsForPeriod(period?: TaskFinishPeriod | null) {
  return period ? ONE_H_REPORT_SLOTS_BY_PERIOD[period] : ONE_H_REPORT_SLOT_OPTIONS
}

function finishPeriodForOneHReportSlot(slot: OneHReportSlot): TaskFinishPeriod {
  return ONE_H_REPORT_SLOTS_BY_PERIOD.AM.includes(slot) ? "AM" : "PM"
}

function mondayISO(today = new Date()) {
  const d = new Date(today)
  const day = (d.getDay() + 6) % 7
  d.setDate(d.getDate() - day)
  return toISODate(d)
}

function shiftIsoDateByDays(iso: string, days: number) {
  const [year, month, day] = iso.split("-").map(Number)
  const date = new Date(year, month - 1, day)
  date.setDate(date.getDate() + days)
  return toISODate(date)
}

function taskDateKey(value?: string | null) {
  if (!value) return null
  if (/^\d{4}-\d{2}-\d{2}/.test(value)) return value.slice(0, 10)
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return toISODate(date)
}

const PLANNED_HORIZON_NONE = "__none__" as const

type PlannedHorizonOption =
  | typeof PLANNED_HORIZON_NONE
  | "next_week"
  | "next_2_weeks"
  | "next_3_weeks"
  | "next_4_weeks"
  | "next_month"
  | "next_2_months"

function plannedHorizonToIso(option: PlannedHorizonOption, today = new Date()): string | null {
  if (option === PLANNED_HORIZON_NONE) return null
  if (option === "next_month") {
    const d = new Date(today.getFullYear(), today.getMonth() + 1, 15)
    return toISODate(d)
  }
  if (option === "next_2_months") {
    const d = new Date(today.getFullYear(), today.getMonth() + 2, 15)
    return toISODate(d)
  }
  const thisMon = mondayISO(today)
  const weekIndex =
    option === "next_week"
      ? 1
      : option === "next_2_weeks"
        ? 2
        : option === "next_3_weeks"
          ? 3
          : 4
  return shiftIsoDateByDays(thisMon, 7 * weekIndex + 2)
}

function matchStoredDateToPlannedHorizon(iso: string | null | undefined, today = new Date()): PlannedHorizonOption {
  if (!iso) return PLANNED_HORIZON_NONE
  const key = taskDateKey(iso)
  if (!key) return PLANNED_HORIZON_NONE
  const [y, m, d] = key.split("-").map(Number)
  const t = new Date(y, m - 1, d)
  const startNextMonth = new Date(today.getFullYear(), today.getMonth() + 1, 1)
  const endNextMonth = new Date(today.getFullYear(), today.getMonth() + 2, 0)
  if (t >= startNextMonth && t <= endNextMonth) {
    return "next_month"
  }
  const startTwoMonthsAhead = new Date(today.getFullYear(), today.getMonth() + 2, 1)
  const endTwoMonthsAhead = new Date(today.getFullYear(), today.getMonth() + 3, 0)
  if (t >= startTwoMonthsAhead && t <= endTwoMonthsAhead) {
    return "next_2_months"
  }
  const thisMon = mondayISO(today)
  for (let n = 1; n <= 4; n++) {
    const wStart = shiftIsoDateByDays(thisMon, 7 * n)
    const wEnd = shiftIsoDateByDays(wStart, 4)
    if (key >= wStart && key <= wEnd) {
      return n === 1 ? "next_week" : n === 2 ? "next_2_weeks" : n === 3 ? "next_3_weeks" : "next_4_weeks"
    }
  }
  return PLANNED_HORIZON_NONE
}

function parseMarkedNoteContent(content?: string | null): {
  text: string
  doneRanges: TextMarkRange[]
  addedRanges: TextMarkRange[]
} {
  if (!content) return { text: "", doneRanges: [], addedRanges: [] }
  const doneRanges: DoneMarkRange[] = []
  const addedRanges: TextMarkRange[] = []
  const openMarks: Record<"done" | "added", number[]> = { done: [], added: [] }
  let text = ""
  let lastIndex = 0
  let match: RegExpExecArray | null

  NOTE_MARK_TOKEN_RE.lastIndex = 0
  while ((match = NOTE_MARK_TOKEN_RE.exec(content)) !== null) {
    text += content.slice(lastIndex, match.index)

    const openingMark = match[1] as "done" | "added" | undefined
    const closingMark = match[2] as "done" | "added" | undefined
    if (openingMark) {
      openMarks[openingMark].push(text.length)
    } else if (closingMark) {
      const start = openMarks[closingMark].pop()
      if (start !== undefined && text.length > start) {
        const targetRanges = closingMark === "done" ? doneRanges : addedRanges
        targetRanges.push({ start, end: text.length })
      }
    }

    lastIndex = match.index + match[0].length
  }
  text += content.slice(lastIndex)

  return {
    text,
    doneRanges: normalizeTextRanges(doneRanges),
    addedRanges: normalizeAddedRanges(text, addedRanges),
  }
}

function normalizeTextRanges(ranges: TextMarkRange[]) {
  const sorted = ranges
    .filter((range) => range.end > range.start)
    .sort((a, b) => a.start - b.start || a.end - b.end)
  const normalized: TextMarkRange[] = []

  for (const range of sorted) {
    const previous = normalized[normalized.length - 1]
    if (previous && range.start <= previous.end) {
      previous.end = Math.max(previous.end, range.end)
    } else {
      normalized.push({ ...range })
    }
  }

  return normalized
}

function normalizeAddedRanges(text: string, ranges: TextMarkRange[]) {
  const normalized = normalizeTextRanges(ranges)
  const merged: TextMarkRange[] = []

  for (const range of normalized) {
    const previous = merged[merged.length - 1]
    const gap = previous ? text.slice(previous.end, range.start) : ""
    if (previous && /^[ \t]*$/.test(gap)) {
      previous.end = range.end
    } else {
      merged.push({ ...range })
    }
  }

  return merged
}

function normalizeDoneRanges(ranges: DoneMarkRange[]) {
  return normalizeTextRanges(ranges)
}

function toggleDoneRange(ranges: DoneMarkRange[], selectedRange: DoneMarkRange) {
  const normalized = normalizeDoneRanges(ranges)
  const overlapsExisting = normalized.some(
    (range) => selectedRange.start < range.end && selectedRange.end > range.start
  )

  if (!overlapsExisting) {
    return normalizeDoneRanges([...normalized, selectedRange])
  }

  const nextRanges: DoneMarkRange[] = []
  for (const range of normalized) {
    if (selectedRange.end <= range.start || selectedRange.start >= range.end) {
      nextRanges.push(range)
      continue
    }
    if (range.start < selectedRange.start) {
      nextRanges.push({ start: range.start, end: selectedRange.start })
    }
    if (selectedRange.end < range.end) {
      nextRanges.push({ start: selectedRange.end, end: range.end })
    }
  }

  return normalizeDoneRanges(nextRanges)
}

function serializeMarkedNoteContent(text: string, doneRanges: TextMarkRange[], addedRanges: TextMarkRange[] = []) {
  const normalizedDoneRanges = normalizeTextRanges(doneRanges)
  const normalizedAddedRanges = normalizeAddedRanges(text, addedRanges)
  const boundaries = new Set([0, text.length])

  normalizedDoneRanges.forEach((range) => {
    boundaries.add(range.start)
    boundaries.add(range.end)
  })
  normalizedAddedRanges.forEach((range) => {
    boundaries.add(range.start)
    boundaries.add(range.end)
  })

  const orderedBoundaries = Array.from(boundaries)
    .filter((boundary) => boundary >= 0 && boundary <= text.length)
    .sort((a, b) => a - b)
  let result = ""

  for (let idx = 0; idx < orderedBoundaries.length - 1; idx += 1) {
    const start = orderedBoundaries[idx]
    const end = orderedBoundaries[idx + 1]
    const segment = text.slice(start, end)
    if (!segment) continue

    const isDone = normalizedDoneRanges.some((range) => range.start <= start && range.end >= end)
    const isAdded = normalizedAddedRanges.some((range) => range.start <= start && range.end >= end)
    let markedSegment = segment

    if (isAdded) markedSegment = `${ADDED_MARK_START}${markedSegment}${ADDED_MARK_END}`
    if (isDone) markedSegment = `${DONE_MARK_START}${markedSegment}${DONE_MARK_END}`

    result += markedSegment
  }

  return result
}

function getTextChangeBounds(previousText: string, nextText: string) {
  let prefixLength = 0
  while (
    prefixLength < previousText.length &&
    prefixLength < nextText.length &&
    previousText[prefixLength] === nextText[prefixLength]
  ) {
    prefixLength += 1
  }

  let suffixLength = 0
  while (
    suffixLength < previousText.length - prefixLength &&
    suffixLength < nextText.length - prefixLength &&
    previousText[previousText.length - 1 - suffixLength] === nextText[nextText.length - 1 - suffixLength]
  ) {
    suffixLength += 1
  }

  const previousChangeEnd = previousText.length - suffixLength
  const nextChangeEnd = nextText.length - suffixLength

  return { prefixLength, previousChangeEnd, nextChangeEnd }
}

function adjustTextRangesForTextChange(previousText: string, nextText: string, ranges: TextMarkRange[]) {
  if (previousText === nextText) return ranges

  const { prefixLength, previousChangeEnd, nextChangeEnd } = getTextChangeBounds(previousText, nextText)
  const delta = nextChangeEnd - previousChangeEnd

  return normalizeTextRanges(
    ranges
      .map((range) => {
        if (range.end <= prefixLength) return range
        if (range.start >= previousChangeEnd) {
          return { start: range.start + delta, end: range.end + delta }
        }

        const start = range.start <= prefixLength ? range.start : prefixLength
        const end = range.end >= previousChangeEnd ? range.end + delta : prefixLength
        return { start, end }
      })
      .filter((range) => range.end > range.start)
  )
}

function addInsertedTextRange(previousText: string, nextText: string, ranges: TextMarkRange[]) {
  if (previousText === nextText) return normalizeAddedRanges(nextText, ranges)

  const { prefixLength, nextChangeEnd } = getTextChangeBounds(previousText, nextText)
  const adjustedRanges = adjustTextRangesForTextChange(previousText, nextText, ranges)
  if (nextChangeEnd <= prefixLength) return normalizeAddedRanges(nextText, adjustedRanges)

  const insertedText = nextText.slice(prefixLength, nextChangeEnd)
  if (!insertedText.trim()) return normalizeAddedRanges(nextText, adjustedRanges)

  return normalizeAddedRanges(nextText, [...adjustedRanges, { start: prefixLength, end: nextChangeEnd }])
}

function getNoteMarkClass(isDone: boolean, isAdded: boolean) {
  if (isDone && isAdded) {
    return "rounded bg-blue-100 px-1 text-emerald-900 ring-1 ring-blue-300 line-through decoration-emerald-700 decoration-2"
  }
  if (isAdded) return "rounded bg-blue-200 px-1 text-blue-950 ring-1 ring-blue-300"
  if (isDone) {
    return "rounded bg-emerald-100 px-1 text-emerald-800 line-through decoration-emerald-700 decoration-2"
  }
  return ""
}

function renderMarkedNoteContent(content?: string | null) {
  if (!content) return "-"
  const parsed = parseMarkedNoteContent(content)
  return renderNoteContentWithRanges(parsed.text, parsed.doneRanges, parsed.addedRanges)
}

type MarkedSegment = {
  text: string
  isDone: boolean
  isAdded: boolean
}

function buildMarkedSegments(content: string, doneRanges: TextMarkRange[], addedRanges: TextMarkRange[] = []) {
  const normalizedDoneRanges = normalizeTextRanges(doneRanges)
  const normalizedAddedRanges = normalizeAddedRanges(content, addedRanges)
  const boundaries = new Set([0, content.length])

  normalizedDoneRanges.forEach((range) => {
    boundaries.add(range.start)
    boundaries.add(range.end)
  })
  normalizedAddedRanges.forEach((range) => {
    boundaries.add(range.start)
    boundaries.add(range.end)
  })

  const orderedBoundaries = Array.from(boundaries)
    .filter((boundary) => boundary >= 0 && boundary <= content.length)
    .sort((a, b) => a - b)

  const segments: MarkedSegment[] = []
  for (let idx = 0; idx < orderedBoundaries.length - 1; idx += 1) {
    const start = orderedBoundaries[idx]
    const end = orderedBoundaries[idx + 1]
    const text = content.slice(start, end)
    if (!text) continue

    segments.push({
      text,
      isDone: normalizedDoneRanges.some((range) => range.start <= start && range.end >= end),
      isAdded: normalizedAddedRanges.some((range) => range.start <= start && range.end >= end),
    })
  }

  return segments
}

function splitSegmentsByNewline(segments: MarkedSegment[]) {
  const lines: MarkedSegment[][] = [[]]

  for (const segment of segments) {
    const parts = segment.text.split("\n")
    parts.forEach((part, index) => {
      if (part) {
        lines[lines.length - 1].push({
          text: part,
          isDone: segment.isDone,
          isAdded: segment.isAdded,
        })
      }
      if (index < parts.length - 1) {
        lines.push([])
      }
    })
  }

  return lines
}

function trimLinePrefix(segments: MarkedSegment[], charsToTrim: number) {
  if (charsToTrim <= 0) return segments

  let remaining = charsToTrim
  const trimmed: MarkedSegment[] = []

  for (const segment of segments) {
    if (remaining >= segment.text.length) {
      remaining -= segment.text.length
      continue
    }
    if (remaining > 0) {
      trimmed.push({
        ...segment,
        text: segment.text.slice(remaining),
      })
      remaining = 0
      continue
    }
    trimmed.push(segment)
  }

  return trimmed.filter((segment) => segment.text.length > 0)
}

function renderInlineMarkedSegments(segments: MarkedSegment[], keyPrefix: string) {
  if (segments.length === 0) return null

  const chars = segments.flatMap((segment) =>
    Array.from(segment.text).map((char) => ({
      char,
      isDone: segment.isDone,
      isAdded: segment.isAdded,
    }))
  )

  const runs: Array<{ text: string; isDone: boolean; isAdded: boolean; isBold: boolean }> = []
  let buffer = ""
  let currentBold = false
  let currentDone: boolean | null = null
  let currentAdded: boolean | null = null

  const flushBuffer = () => {
    if (!buffer) return
    runs.push({
      text: buffer,
      isDone: Boolean(currentDone),
      isAdded: Boolean(currentAdded),
      isBold: currentBold,
    })
    buffer = ""
  }

  for (let index = 0; index < chars.length; index += 1) {
    const current = chars[index]
    const next = chars[index + 1]

    if (current.char === "*" && next?.char === "*") {
      flushBuffer()
      currentBold = !currentBold
      currentDone = null
      currentAdded = null
      index += 1
      continue
    }

    if (
      buffer &&
      (currentDone !== current.isDone || currentAdded !== current.isAdded)
    ) {
      flushBuffer()
    }

    currentDone = current.isDone
    currentAdded = current.isAdded
    buffer += current.char
  }

  flushBuffer()

  return runs.map((run, index) => {
    const className = getNoteMarkClass(run.isDone, run.isAdded)
    const contentNode = run.isBold ? <strong>{run.text}</strong> : run.text

    if (!className) {
      return <React.Fragment key={`${keyPrefix}-run-${index}`}>{contentNode}</React.Fragment>
    }

    return (
      <span key={`${keyPrefix}-run-${index}`} className={className}>
        {contentNode}
      </span>
    )
  })
}

function renderNoteContentWithRanges(content: string, doneRanges: TextMarkRange[], addedRanges: TextMarkRange[] = []) {
  if (!content) return "-"
  const lines = splitSegmentsByNewline(buildMarkedSegments(content, doneRanges, addedRanges))
  const blocks: React.ReactNode[] = []
  let index = 0

  while (index < lines.length) {
    const lineSegments = lines[index]
    const lineText = lineSegments.map((segment) => segment.text).join("")
    const bulletMatch = lineText.match(/^\s*[•\-*]\s+/)
    const orderedMatch = lineText.match(/^\s*\d+\.\s+/)

    if (bulletMatch) {
      const items: React.ReactNode[] = []
      while (index < lines.length) {
        const itemSegments = lines[index]
        const itemText = itemSegments.map((segment) => segment.text).join("")
        const match = itemText.match(/^\s*[•\-*]\s+/)
        if (!match) break
        items.push(
          <li key={`note-bullet-${index}`}>
            {renderInlineMarkedSegments(trimLinePrefix(itemSegments, match[0].length), `note-bullet-${index}`)}
          </li>
        )
        index += 1
      }
      blocks.push(
        <ul key={`note-ul-${index}`} className="list-disc pl-5 space-y-1">
          {items}
        </ul>
      )
      continue
    }

    if (orderedMatch) {
      const items: React.ReactNode[] = []
      while (index < lines.length) {
        const itemSegments = lines[index]
        const itemText = itemSegments.map((segment) => segment.text).join("")
        const match = itemText.match(/^\s*\d+\.\s+/)
        if (!match) break
        items.push(
          <li key={`note-ordered-${index}`}>
            {renderInlineMarkedSegments(trimLinePrefix(itemSegments, match[0].length), `note-ordered-${index}`)}
          </li>
        )
        index += 1
      }
      blocks.push(
        <ol key={`note-ol-${index}`} className="list-decimal pl-5 space-y-1">
          {items}
        </ol>
      )
      continue
    }

    blocks.push(
      <div key={`note-line-${index}`} className={lineText ? "" : "min-h-[1.25rem]"}>
        {lineText ? renderInlineMarkedSegments(lineSegments, `note-line-${index}`) : "\u00A0"}
      </div>
    )
    index += 1
  }

  return blocks.length > 0 ? blocks : content
}

type TextSelectionTransformResult = {
  nextValue: string
  selectionStart: number
  selectionEnd: number
}

function applyTextSelectionTransform(
  value: string,
  selectionStart: number,
  selectionEnd: number,
  transform: (value: string, selectionStart: number, selectionEnd: number) => TextSelectionTransformResult
) {
  return transform(value, selectionStart, selectionEnd)
}

function wrapSelectedText(value: string, selectionStart: number, selectionEnd: number, wrapper: string): TextSelectionTransformResult {
  const selected = value.slice(selectionStart, selectionEnd)
  const nextValue = `${value.slice(0, selectionStart)}${wrapper}${selected}${wrapper}${value.slice(selectionEnd)}`
  return {
    nextValue,
    selectionStart: selectionStart + wrapper.length,
    selectionEnd: selectionEnd + wrapper.length,
  }
}

function prefixSelectedLines(
  value: string,
  selectionStart: number,
  selectionEnd: number,
  prefixBuilder: (lineIndex: number) => string
): TextSelectionTransformResult {
  const lineStart = value.lastIndexOf("\n", Math.max(0, selectionStart - 1)) + 1
  const lineEndIndex = value.indexOf("\n", selectionEnd)
  const blockEnd = lineEndIndex === -1 ? value.length : lineEndIndex
  const block = value.slice(lineStart, blockEnd)
  const lines = block.split("\n")

  let nextBlock = ""
  let addedBeforeSelectionStart = 0
  let addedBeforeSelectionEnd = 0
  let consumed = 0

  lines.forEach((line, index) => {
    const prefix = prefixBuilder(index)
    if (index > 0) {
      nextBlock += "\n"
      consumed += 1
    }
    if (consumed <= selectionStart - lineStart) addedBeforeSelectionStart += prefix.length
    if (consumed <= selectionEnd - lineStart) addedBeforeSelectionEnd += prefix.length
    nextBlock += `${prefix}${line}`
    consumed += line.length
  })

  return {
    nextValue: `${value.slice(0, lineStart)}${nextBlock}${value.slice(blockEnd)}`,
    selectionStart: selectionStart + addedBeforeSelectionStart,
    selectionEnd: selectionEnd + addedBeforeSelectionEnd,
  }
}

function normalizeTaskStatus(value?: string | null): NormalizedTaskStatus {
  if (!value) return "UNKNOWN"
  const normalized = value.trim().toLowerCase().replace(/\s+/g, "_")
  if (["todo", "to_do", "to-do", "to do"].includes(normalized)) return "TODO"
  if (["in_progress", "in-progress", "in progress"].includes(normalized)) return "IN_PROGRESS"
  if (["waiting_client", "waiting-client", "waiting for client", "wfe"].includes(normalized)) return "WAITING_CLIENT"
  if (["waiting_confirmation", "waiting-confirmation", "waiting confirmation"].includes(normalized)) return "WAITING_CONFIRMATION"
  if (["done"].includes(normalized)) return "DONE"
  return "UNKNOWN"
}

function aggregateTaskStatus(statuses: Array<string | null | undefined>): NormalizedTaskStatus {
  const normalized = statuses.map((status) => {
    const value = normalizeTaskStatus(status)
    return value === "UNKNOWN" ? "TODO" : value
  })
  if (normalized.length === 0) return "UNKNOWN"
  const allDone = normalized.every((status) => status === "DONE")
  if (allDone) return "DONE"
  const allWaiting = normalized.every((status) => status === "WAITING_CONFIRMATION")
  if (allWaiting) return "WAITING_CONFIRMATION"
  const allWaitingClient = normalized.every((status) => status === "WAITING_CLIENT")
  if (allWaitingClient) return "WAITING_CLIENT"
  const anyInProgress = normalized.some((status) => status === "IN_PROGRESS")
  if (anyInProgress) return "IN_PROGRESS"
  const anyWaiting = normalized.some((status) => status === "WAITING_CONFIRMATION" || status === "WAITING_CLIENT")
  const anyTodo = normalized.some((status) => status === "TODO")
  if (anyWaiting && anyTodo) return "IN_PROGRESS"
  if (anyWaiting) return "WAITING_CONFIRMATION"
  const anyDone = normalized.some((status) => status === "DONE")
  if (anyDone) return "IN_PROGRESS"
  return "TODO"
}

function formatDateParts(value?: string | null) {
  if (!value) return { date: "-", time: "" }
  const date = new Date(value)
  const day = date.getDate().toString().padStart(2, "0")
  const month = (date.getMonth() + 1).toString().padStart(2, "0")
  let hours = date.getHours()
  const minutes = date.getMinutes().toString().padStart(2, "0")
  const ampm = hours >= 12 ? "PM" : "AM"
  hours = hours % 12
  hours = hours ? hours : 12 // the hour '0' should be '12'
  const hoursStr = hours.toString().padStart(2, "0")
  return { date: `${day}.${month}`, time: `${hoursStr}:${minutes} ${ampm}` }
}

/** e.g. 12.03.2026 — calendar day in Europe-style dots */
function formatCalendarDateDots(value?: string | null) {
  if (!value) return "—"
  const key = taskDateKey(value)
  if (!key) return "—"
  const [y, mo, d] = key.split("-").map(Number)
  return `${pad2(d)}.${pad2(mo)}.${y}`
}

function formatFileSize(bytes: number) {
  if (!Number.isFinite(bytes)) return "-"
  if (bytes < 1024) return `${bytes} B`
  const kb = bytes / 1024
  if (kb < 1024) return `${kb.toFixed(1)} KB`
  const mb = kb / 1024
  if (mb < 1024) return `${mb.toFixed(1)} MB`
  const gb = mb / 1024
  return `${gb.toFixed(2)} GB`
}

function getTaskTypeLabels(task: Task) {
  const labels: string[] = []
  if (task.is_1h_report) labels.push("1H")
  if (task.is_bllok) labels.push("BLL")
  if (task.is_r1) labels.push("R1")
  if (task.is_personal) labels.push("P")
  if (labels.length === 0 && task.priority) labels.push(task.priority === "NORMAL" ? "N" : task.priority)
  return labels
}

function mergeTaskTypeLabels(base: string[] = [], incoming: string[] = []) {
  return Array.from(new Set([...base, ...incoming].filter(Boolean)))
}

function getInitials(label: string) {
  const trimmed = label.trim()
  if (!trimmed) return "?"
  const parts = trimmed.split(/\s+/)
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase()
}

function noteToTaskTitle(content: string) {
  const cleaned = content
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .split("\n")
    .map((line) => line.trim().replace(/[ \t\f\v]+/g, " "))
    .filter(Boolean)
    .join("\n")
  if (!cleaned) return "Plan note task"
  return cleaned
}

function getDueTone(value?: string | null) {
  if (!value) return "text-slate-500"
  const due = new Date(value)
  const now = new Date()
  if (Number.isNaN(due.getTime())) return "text-slate-500"
  if (due.getTime() < now.getTime()) return "text-rose-600"
  const hoursLeft = (due.getTime() - now.getTime()) / 3_600_000
  return hoursLeft <= 24 ? "text-amber-600" : "text-slate-600"
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

function isDevelopmentDepartment(dept?: Department | null) {
  if (!dept) return false
  const name = (dept.name || "").trim().toUpperCase()
  const code = (dept.code || "").trim().toUpperCase()
  return name === "DEVELOPMENT" || code === "DEV"
}

export default function NextWeekPlanPage() {
  const { user, apiFetch } = useAuth()
  const confirm = useConfirm()
  const searchParams = useSearchParams()
  const [notes, setNotes] = React.useState<PlanNote[]>([])
  const notesRef = React.useRef<PlanNote[]>([])
  notesRef.current = notes
  const notesFetchVersionRef = React.useRef(0)
  const noteTaskRequestVersionRef = React.useRef(0)
  const loadedNoteTaskIdsRef = React.useRef<Set<string>>(new Set())
  const noteOriginsKey = React.useMemo(
    () => notes.map((note) => note.id).join("|"),
    [notes]
  )
  const [departments, setDepartments] = React.useState<Department[]>([])
  const [projects, setProjects] = React.useState<Project[]>([])
  const [users, setUsers] = React.useState<UserLookup[]>([])
  const usersRef = React.useRef<UserLookup[]>([])
  usersRef.current = users

  // Initialize from URL parameters if present
  const urlDepartmentId = searchParams.get("department_id")
  const urlProjectId = searchParams.get("project_id")
  const [departmentId, setDepartmentId] = React.useState(urlDepartmentId || "ALL")
  const [projectId, setProjectId] = React.useState(urlProjectId || "NONE")
  const [noteOneHMarker, setNoteOneHMarker] = React.useState<OneHMarker | typeof ONE_H_MARKER_NONE>(ONE_H_MARKER_NONE)
  const [noteOneHMarkerComment, setNoteOneHMarkerComment] = React.useState("")
  const [editOneHMarker, setEditOneHMarker] = React.useState<OneHMarker | typeof ONE_H_MARKER_NONE>(ONE_H_MARKER_NONE)
  const [editOneHMarkerComment, setEditOneHMarkerComment] = React.useState("")
  const [taskOneHMarker, setTaskOneHMarker] = React.useState<OneHMarker | typeof ONE_H_MARKER_NONE>(ONE_H_MARKER_NONE)
  const [taskOneHMarkerComment, setTaskOneHMarkerComment] = React.useState("")
  const [taskOneHReportSlot, setTaskOneHReportSlot] = React.useState<OneHReportSlot | typeof ONE_H_REPORT_SLOT_NONE_VALUE>(ONE_H_REPORT_SLOT_NONE_VALUE)
  const [taskDateLeaveItems, setTaskDateLeaveItems] = React.useState<CommonLeaveItem[]>([])
  const [content, setContent] = React.useState("")
  const [plannedHorizonNewNote, setPlannedHorizonNewNote] = React.useState<PlannedHorizonOption>(PLANNED_HORIZON_NONE)
  const [noteType] = React.useState<NoteType>("GA")
  const [priority] = React.useState<NotePriority>("NONE")
  const [loading, setLoading] = React.useState(false)
  const [posting, setPosting] = React.useState(false)
  const [selectedFiles, setSelectedFiles] = React.useState<File[]>([])
  const fileInputRef = React.useRef<HTMLInputElement | null>(null)
  const [attachmentUploadFiles, setAttachmentUploadFiles] = React.useState<File[]>([])
  const attachmentUploadInputRef = React.useRef<HTMLInputElement | null>(null)
  const [uploadingAttachments, setUploadingAttachments] = React.useState(false)
  const [deletingAttachmentIds, setDeletingAttachmentIds] = React.useState<string[]>([])
  const [taskDialogNoteId, setTaskDialogNoteId] = React.useState<string | null>(null)
  const [creatingTask, setCreatingTask] = React.useState(false)
  const [taskStatusFilter, setTaskStatusFilter] = React.useState<TaskStatusFilter>("all")
  const [contentFilter, setContentFilter] = React.useState<ContentFilter>("all")
  const [nextWeekFilter, setNextWeekFilter] = React.useState<NextWeekFilter>("all")
  const [searchQuery, setSearchQuery] = React.useState("")
  const deferredSearchQuery = React.useDeferredValue(searchQuery)
  const [notesRenderLimit, setNotesRenderLimit] = React.useState(INITIAL_NOTES_RENDER_LIMIT)
  const [showLegend, setShowLegend] = React.useState(false)
  const [taskTitle, setTaskTitle] = React.useState("")
  const [taskDescription, setTaskDescription] = React.useState("")
  const [taskPriority, setTaskPriority] = React.useState<TaskTypeOption>("NORMAL")
  const [taskFinishPeriod, setTaskFinishPeriod] = React.useState<TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE>(
    FINISH_PERIOD_NONE_VALUE
  )
  const [taskDueDate, setTaskDueDate] = React.useState("")
  const [taskStartDate, setTaskStartDate] = React.useState("")
  const [taskDeadlineImportant, setTaskDeadlineImportant] = React.useState(false)
  const [taskIsRepetitive, setTaskIsRepetitive] = React.useState(false)
  const [taskAssigneeIds, setTaskAssigneeIds] = React.useState<string[]>([])
  const [taskDepartmentIds, setTaskDepartmentIds] = React.useState<string[]>([])
  const [taskProjectId, setTaskProjectId] = React.useState("NONE")
  const [noteTaskInfo, setNoteTaskInfo] = React.useState<Map<string, NoteTaskInfo>>(new Map())
  const [savingCommentIds, setSavingCommentIds] = React.useState<Record<string, boolean>>({})
  const [savingNextWeekIds, setSavingNextWeekIds] = React.useState<Record<string, boolean>>({})
  const [savingPlanningIds, setSavingPlanningIds] = React.useState<Record<string, boolean>>({})
  const planningSaveVersionsRef = React.useRef<Map<string, number>>(new Map())
  const [editNoteId, setEditNoteId] = React.useState<string | null>(null)
  const [editContent, setEditContent] = React.useState("")
  const [editDoneRanges, setEditDoneRanges] = React.useState<DoneMarkRange[]>([])
  const [editAddedRanges, setEditAddedRanges] = React.useState<TextMarkRange[]>([])
  const [editDescription, setEditDescription] = React.useState("")
  const [editTaskDeadline, setEditTaskDeadline] = React.useState("")
  const [editTaskDeadlineImportant, setEditTaskDeadlineImportant] = React.useState(false)
  const [editTaskInitialDeadline, setEditTaskInitialDeadline] = React.useState("")
  const [editTaskInitialDeadlineImportant, setEditTaskInitialDeadlineImportant] = React.useState(false)
  const [editTaskIsRepetitive, setEditTaskIsRepetitive] = React.useState<boolean | "indeterminate">(false)
  const [editPlannedHorizon, setEditPlannedHorizon] = React.useState<PlannedHorizonOption>(PLANNED_HORIZON_NONE)
  const [savingEdit, setSavingEdit] = React.useState(false)
  const [markingDoneNoteId, setMarkingDoneNoteId] = React.useState<string | null>(null)
  const [markingSelectedNoteId, setMarkingSelectedNoteId] = React.useState<string | null>(null)
  const contentTextareaRef = React.useRef<HTMLTextAreaElement | null>(null)
  const editTextareaRef = React.useRef<HTMLTextAreaElement | null>(null)
  const [attachmentsDialogOpen, setAttachmentsDialogOpen] = React.useState(false)
  const [attachmentsDialogNoteId, setAttachmentsDialogNoteId] = React.useState<string | null>(null)
  const [loadingAttachmentsNoteId, setLoadingAttachmentsNoteId] = React.useState<string | null>(null)
  const [previewUrl, setPreviewUrl] = React.useState<string | null>(null)
  const [previewTitle, setPreviewTitle] = React.useState<string | null>(null)

  const [internalMeetingTaskDialogOpen, setInternalMeetingTaskDialogOpen] = React.useState(false)
  const [internalMeetingTaskTitle, setInternalMeetingTaskTitle] = React.useState("")
  const [internalMeetingTaskPlatform, setInternalMeetingTaskPlatform] = React.useState("")
  const [internalMeetingTaskStartsAt, setInternalMeetingTaskStartsAt] = React.useState("")
  const [creatingInternalMeetingFromTask, setCreatingInternalMeetingFromTask] = React.useState(false)
  const internalMeetingDepartmentIdRef = React.useRef<string | null>(null)

  const savePlanningBrief = React.useCallback(async (
    noteId: string,
    brief: PxJavPlanningBrief,
    previousBrief: PxJavPlanningBrief | null,
  ) => {
    const version = (planningSaveVersionsRef.current.get(noteId) || 0) + 1
    planningSaveVersionsRef.current.set(noteId, version)
    setSavingPlanningIds((current) => ({ ...current, [noteId]: true }))
    try {
      const hasAnswer = Boolean(
        brief.dl?.trim() ||
        brief.lloji_det ||
        typeof brief.dg === "boolean" ||
        brief.hapat?.trim() ||
        brief.kush?.trim() ||
        brief.sq?.trim()
      )
      const res = await apiFetch(`/plan-notes/${noteId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          planning_brief: hasAnswer
            ? {
                dl: brief.dl?.trim() || null,
                lloji_det: brief.lloji_det || null,
                dg: typeof brief.dg === "boolean" ? brief.dg : null,
                dg_kush: brief.dg === true ? brief.dg_kush?.trim() || null : null,
                dg_kush_user_ids: brief.dg === true ? brief.dg_kush_user_ids || [] : [],
                hapat: brief.hapat?.trim() || null,
                kush: brief.kush?.trim() || null,
                kush_user_ids: brief.kush_user_ids || [],
                sq: brief.sq?.trim() || null,
              }
            : null,
        }),
      })
      if (!res?.ok) {
        let message = "Planifikimi nuk u ruajt"
        try {
          const payload = (await res?.json()) as { detail?: string }
          if (payload?.detail) message = payload.detail
        } catch {
          // Keep fallback message.
        }
        throw new Error(message)
      }

      const updated = (await res.json()) as PlanNote
      if (planningSaveVersionsRef.current.get(noteId) === version) {
        setNotes((current) => current.map((note) => (note.id === updated.id ? updated : note)))
      }
    } catch (error) {
      if (planningSaveVersionsRef.current.get(noteId) === version) {
        setNotes((current) => current.map((note) => (
          note.id === noteId ? { ...note, planning_brief: previousBrief } : note
        )))
      }
      toast.error(error instanceof Error ? error.message : "Planifikimi nuk u ruajt")
    } finally {
      if (planningSaveVersionsRef.current.get(noteId) === version) {
        setSavingPlanningIds((current) => {
          const next = { ...current }
          delete next[noteId]
          return next
        })
      }
    }
  }, [apiFetch])

  const updatePlanningBriefDraft = React.useCallback((
    noteId: string,
    patch: Partial<PxJavPlanningBrief>,
  ) => {
    setNotes((current) => current.map((item) => (
      item.id === noteId
        ? { ...item, planning_brief: { ...planningBriefDraft(item.planning_brief), ...patch } }
        : item
    )))
  }, [])

  const savePlanningInput = React.useCallback((
    note: PlanNote,
    field: PlanningTextField,
    value: string,
    previousBriefJson: string,
  ) => {
    let previousBrief: PxJavPlanningBrief | null = null
    try {
      previousBrief = JSON.parse(previousBriefJson) as PxJavPlanningBrief | null
    } catch {
      previousBrief = note.planning_brief ?? null
    }

    const previousValue = planningBriefDraft(previousBrief)[field] || ""
    if (value.trim() === previousValue.trim()) return

    const nextBrief = {
      ...planningBriefDraft(note.planning_brief),
      [field]: value,
      ...(field === "dg_kush" ? { dg_kush_user_ids: [] } : {}),
      ...(field === "kush" ? { kush_user_ids: [] } : {}),
    }
    void savePlanningBrief(note.id, nextBrief, previousBrief)
  }, [savePlanningBrief])

  const loadDepartments = React.useCallback(async () => {
    const res = await apiFetch("/departments")
    if (res?.ok) {
      setDepartments((await res.json()) as Department[])
    }
  }, [apiFetch])

  const loadUsers = React.useCallback(async () => {
    if (user?.role === "STAFF") {
      const usersList = await fetchUsersLookupCached(apiFetch)
      if (usersList) setUsers(usersList as UserLookup[])
    } else {
      const res = await apiFetch("/users")
      if (res?.ok) setUsers((await res.json()) as UserLookup[])
    }
  }, [apiFetch, user?.role])

  const loadProjects = React.useCallback(
    async (deptId?: string) => {
      const query = deptId ? `?department_id=${deptId}` : ""
      const res = await apiFetch(`/projects${query}`)
      if (res?.ok) {
        setProjects((await res.json()) as Project[])
      }
    },
    [apiFetch]
  )



  const fetchNotes = React.useCallback(async () => {
    if (!user) return
    const fetchVersion = ++notesFetchVersionRef.current
    noteTaskRequestVersionRef.current += 1
    loadedNoteTaskIdsRef.current.clear()
    setNoteTaskInfo(new Map())
    setNotes([])
    setLoading(true)
    try {
      const baseParams = new URLSearchParams()
      if (projectId !== "NONE") {
        baseParams.set("project_id", projectId)
      } else if (departmentId !== "ALL") {
        baseParams.set("department_id", departmentId)
      }
      baseParams.set("limit", String(PLAN_NOTES_PAGE_SIZE))
      baseParams.set("include_attachments", "false")

      let offset = 0
      let accumulatedNotes: PlanNote[] = []
      while (true) {
        const params = new URLSearchParams(baseParams)
        params.set("offset", String(offset))
        const res = await apiFetch(`/plan-notes?${params.toString()}`)
        if (!res?.ok) {
          if (notesFetchVersionRef.current === fetchVersion) toast.error("Could not load plan notes")
          return
        }
        const page = (await res.json()) as PlanNote[]
        if (notesFetchVersionRef.current !== fetchVersion) return
        accumulatedNotes = [...accumulatedNotes, ...page]
        setNotes(accumulatedNotes)
        if (offset === 0) setLoading(false)
        if (page.length < PLAN_NOTES_PAGE_SIZE) break
        offset += PLAN_NOTES_PAGE_SIZE
      }
    } finally {
      if (notesFetchVersionRef.current === fetchVersion) setLoading(false)
    }
  }, [apiFetch, departmentId, projectId, user])

  // Sync state with URL parameters when they change
  React.useEffect(() => {
    const urlDeptId = searchParams.get("department_id")
    const urlProjId = searchParams.get("project_id")
    if (urlDeptId) {
      setDepartmentId(urlDeptId)
    }
    if (urlProjId) {
      setProjectId(urlProjId)
    }
  }, [searchParams])

  React.useEffect(() => {
    void loadDepartments()
  }, [loadDepartments])

  React.useEffect(() => {
    void loadUsers()
  }, [loadUsers])

  React.useEffect(() => {
    void loadProjects()
  }, [loadProjects])

  React.useEffect(() => {
    void fetchNotes()
  }, [fetchNotes])

  const loadNoteTasks = React.useCallback(async (noteIdsOverride?: string[]) => {
    const noteIds = noteIdsOverride ?? notesRef.current.map((note) => note.id).filter(Boolean)
    if (!noteIds.length) {
      if (!noteIdsOverride) {
        setNoteTaskInfo(new Map())
      }
      return
    }
    const requestVersion = noteTaskRequestVersionRef.current
    const res = await apiFetch("/tasks/by-ga-notes/summary", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ga_note_origin_ids: [],
        plan_note_origin_ids: noteIds,
        include_done: true,
        include_all_done: false,
      }),
    })
    if (!res?.ok || noteTaskRequestVersionRef.current !== requestVersion) return false
    const data = (await res.json()) as Task[]
    if (noteTaskRequestVersionRef.current !== requestVersion) return false
    const userMapById = new Map(usersRef.current.map((u) => [u.id, u]))

    const map = new Map<string, NoteTaskInfo>()
    const mergeAssignees = (base: TaskAssignee[], incoming: TaskAssignee[]) => {
      const result: TaskAssignee[] = []
      const seen = new Set<string>()
      const add = (assignee: TaskAssignee) => {
        const key =
          assignee.id ||
          assignee.username ||
          assignee.full_name ||
          assignee.email ||
          Math.random().toString()
        if (seen.has(key)) return
        seen.add(key)
        result.push(assignee)
      }
      base.forEach(add)
      incoming.forEach(add)
      return result
    }
    for (const t of data) {
      if (!t.plan_note_origin_id) continue
      let assignees: TaskAssignee[] = []
      if (t.assignees && t.assignees.length > 0) {
        // Use TaskAssignee directly from API - it has all the info we need for display
        assignees = t.assignees
      }
      if (assignees.length === 0 && t.assigned_to) {
        // Fallback to assigned_to if no assignees in TaskAssignee table
        const fallback = userMapById.get(t.assigned_to)
        if (fallback) {
          // Convert UserLookup to TaskAssignee format for consistency
          assignees = [{
            id: fallback.id,
            email: null,
            username: fallback.username || null,
            full_name: fallback.full_name || null,
            department_id: fallback.department_id || null,
          }]
        }
      }
      const existing = map.get(t.plan_note_origin_id)
      map.set(t.plan_note_origin_id, {
        assignees: mergeAssignees(existing?.assignees ?? [], assignees),
        description: existing?.description ?? t.description ?? null,
        taskId: existing?.taskId ?? t.id,
        taskDepartmentId: existing?.taskDepartmentId ?? t.department_id ?? null,
        taskProjectId: existing?.taskProjectId ?? t.project_id ?? null,
        taskStatus: existing?.taskStatus ?? t.status ?? null,
        taskStatuses: [...(existing?.taskStatuses ?? []), t.status ?? ""],
        taskTypeLabels: mergeTaskTypeLabels(existing?.taskTypeLabels, getTaskTypeLabels(t)),
        dueDate: existing?.dueDate ?? t.due_date ?? null,
        startDate: existing?.startDate ?? t.start_date ?? null,
        finishPeriod: existing?.finishPeriod ?? t.finish_period ?? null,
        isDeadlineImportant:
          existing?.isDeadlineImportant ?? (t.is_deadline_important ?? null),
        isRepetitive: existing?.isRepetitive === undefined
          ? Boolean(t.is_repetitive)
          : existing.isRepetitive === Boolean(t.is_repetitive) ? existing.isRepetitive : "indeterminate",
      })
    }
    if (noteIdsOverride) {
      setNoteTaskInfo((current) => {
        const next = new Map(current)
        noteIds.forEach((noteId) => next.delete(noteId))
        map.forEach((value, noteId) => next.set(noteId, value))
        return next
      })
    } else {
      setNoteTaskInfo(map)
    }
    return true
  }, [apiFetch])

  // Load tasks linked to notes to show assignees/descriptions
  React.useEffect(() => {
    const missingNoteIds = notesRef.current
      .map((note) => note.id)
      .filter((noteId) => !loadedNoteTaskIdsRef.current.has(noteId))
    if (!missingNoteIds.length) return
    missingNoteIds.forEach((noteId) => loadedNoteTaskIdsRef.current.add(noteId))
    void loadNoteTasks(missingNoteIds).then((loaded) => {
      if (loaded) return
      missingNoteIds.forEach((noteId) => loadedNoteTaskIdsRef.current.delete(noteId))
    })
  }, [loadNoteTasks, noteOriginsKey])

  const updateNoteCommentDraft = React.useCallback((noteId: string, comment: string) => {
    setNotes((prev) => prev.map((note) => (note.id === noteId ? { ...note, comment } : note)))
  }, [])

  const saveNoteComment = React.useCallback(
    async (noteId: string, comment: string, previousComment = "") => {
      const trimmed = comment.trim()

      setSavingCommentIds((prev) => ({ ...prev, [noteId]: true }))
      try {
        const res = await apiFetch(`/plan-notes/${noteId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ comment: trimmed || null }),
        })
        if (!res?.ok) {
          let message = "Failed to save comment"
          try {
            const payload = (await res.json()) as { detail?: string }
            if (payload?.detail) message = payload.detail
          } catch {
            // Keep fallback message.
          }
          throw new Error(message)
        }

        const updated = (await res.json()) as PlanNote
        setNotes((prev) => prev.map((note) => (note.id === updated.id ? updated : note)))
      } catch (error) {
        updateNoteCommentDraft(noteId, previousComment)
        toast.error(error instanceof Error ? error.message : "Failed to save comment")
      } finally {
        setSavingCommentIds((prev) => {
          const next = { ...prev }
          delete next[noteId]
          return next
        })
      }
    },
    [apiFetch, updateNoteCommentDraft]
  )

  const toggleNoteNextWeek = React.useCallback(
    async (noteId: string, checked: boolean) => {
      const previousValue = Boolean(notes.find((note) => note.id === noteId)?.next_week)
      setNotes((prev) => prev.map((note) => (note.id === noteId ? { ...note, next_week: checked } : note)))
      setSavingNextWeekIds((prev) => ({ ...prev, [noteId]: true }))
      try {
        const res = await apiFetch(`/plan-notes/${noteId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ next_week: checked }),
        })
        if (!res?.ok) {
          let message = "Failed to save next week"
          try {
            const payload = (await res.json()) as { detail?: string }
            if (payload?.detail) message = payload.detail
          } catch {
            // Keep fallback message.
          }
          throw new Error(message)
        }

        const updated = (await res.json()) as PlanNote
        setNotes((prev) => prev.map((note) => (note.id === updated.id ? updated : note)))
      } catch (error) {
        setNotes((prev) =>
          prev.map((note) => (note.id === noteId ? { ...note, next_week: previousValue } : note))
        )
        toast.error(error instanceof Error ? error.message : "Failed to save next week")
      } finally {
        setSavingNextWeekIds((prev) => {
          const next = { ...prev }
          delete next[noteId]
          return next
        })
      }
    },
    [apiFetch, notes]
  )



  const validateAttachmentSelection = (existingFiles: File[], incomingFiles: File[]) => {
    if (incomingFiles.length === 0) return existingFiles

    const combined = [...existingFiles, ...incomingFiles]
    if (combined.length > MAX_ATTACHMENT_FILES) {
      toast.error(`You can upload up to ${MAX_ATTACHMENT_FILES} files.`)
    }

    const limited = combined.slice(0, MAX_ATTACHMENT_FILES)
    return limited.filter((file) => {
      if (file.size > MAX_ATTACHMENT_BYTES) {
        toast.error(`"${file.name}" exceeds ${MAX_ATTACHMENT_MB}MB.`)
        return false
      }
      return true
    })
  }

  const handleFileSelection = (event: React.ChangeEvent<HTMLInputElement>) => {
    const incoming = Array.from(event.target.files || [])
    setSelectedFiles((prev) => validateAttachmentSelection(prev, incoming))
    if (fileInputRef.current) {
      fileInputRef.current.value = ""
    }
  }

  const removeSelectedFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, idx) => idx !== index))
  }

  const handleAttachmentUploadSelection = (event: React.ChangeEvent<HTMLInputElement>) => {
    const incoming = Array.from(event.target.files || [])
    setAttachmentUploadFiles((prev) => validateAttachmentSelection(prev, incoming))
    if (attachmentUploadInputRef.current) {
      attachmentUploadInputRef.current.value = ""
    }
  }

  const removeAttachmentUploadFile = (index: number) => {
    setAttachmentUploadFiles((prev) => prev.filter((_, idx) => idx !== index))
  }

  const closeInternalMeetingTaskDialog = React.useCallback(() => {
    setInternalMeetingTaskDialogOpen(false)
    setInternalMeetingTaskTitle("")
    setInternalMeetingTaskPlatform("")
    setInternalMeetingTaskStartsAt("")
    internalMeetingDepartmentIdRef.current = null
  }, [])

  const openInternalMeetingFromNoteTask = React.useCallback(
    (note: PlanNote, taskInfo?: NoteTaskInfo | null) => {
      const parsed = parseMarkedNoteContent(note.content)
      const cleanTitle = (parsed.text || "").trim().replace(/\s+/g, " ")
      const title = cleanTitle.length > 255 ? `${cleanTitle.slice(0, 252)}...` : cleanTitle

      setInternalMeetingTaskTitle(title || "Internal meeting")
      setInternalMeetingTaskPlatform("")
      setInternalMeetingTaskStartsAt("")
      internalMeetingDepartmentIdRef.current =
        taskInfo?.taskDepartmentId || note.department_id || user?.department_id || null
      setInternalMeetingTaskDialogOpen(true)
    },
    [user?.department_id]
  )

  const submitInternalMeetingFromNoteTask = React.useCallback(async () => {
    const title = internalMeetingTaskTitle.trim()
    const departmentId = internalMeetingDepartmentIdRef.current
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
      closeInternalMeetingTaskDialog()
      toast.success("Internal meeting created")
    } finally {
      setCreatingInternalMeetingFromTask(false)
    }
  }, [
    apiFetch,
    closeInternalMeetingTaskDialog,
    internalMeetingTaskPlatform,
    internalMeetingTaskStartsAt,
    internalMeetingTaskTitle,
    user?.id,
  ])

  const uploadNoteAttachments = async (noteId: string, files: File[]) => {
    const buildFormData = (includeNoteId: boolean) => {
      const formData = new FormData()
      if (includeNoteId) {
        formData.append("note_id", noteId)
      }
      files.forEach((file) => formData.append("files", file))
      return formData
    }

    const encodedNoteId = encodeURIComponent(noteId)
    let res = await apiFetch(`/plan-notes/${encodedNoteId}/attachments`, {
      method: "POST",
      body: buildFormData(false),
    })

    if (res?.status === 404) {
      res = await apiFetch("/plan-notes/attachments", {
        method: "POST",
        body: buildFormData(true),
      })
    }

    if (!res?.ok) {
      const errorText = await res.text()
      throw new Error(errorText || "upload_failed")
    }
    return (await res.json()) as PlanNoteAttachment[]
  }

  const mergeNoteAttachments = React.useCallback((noteId: string, attachments: PlanNoteAttachment[]) => {
    if (attachments.length === 0) return
    setNotes((prev) =>
      prev.map((note) => {
        if (note.id !== noteId) return note
        const existing = note.attachments ?? []
        const existingIds = new Set(existing.map((attachment) => attachment.id))
        const merged = [...existing]
        attachments.forEach((attachment) => {
          if (!existingIds.has(attachment.id)) {
            merged.push(attachment)
          }
        })
        return { ...note, attachments: merged, attachment_count: merged.length }
      })
    )
  }, [])

  const removeNoteAttachment = React.useCallback((noteId: string, attachmentId: string) => {
    setNotes((prev) =>
      prev.map((note) =>
        note.id === noteId
          ? (() => {
              const attachments = (note.attachments ?? []).filter((attachment) => attachment.id !== attachmentId)
              return { ...note, attachments, attachment_count: attachments.length }
            })()
          : note
      )
    )
  }, [])

  const resetManageAttachmentsState = React.useCallback(() => {
    setAttachmentUploadFiles([])
    setDeletingAttachmentIds([])
    if (attachmentUploadInputRef.current) {
      attachmentUploadInputRef.current.value = ""
    }
  }, [])

  const downloadAttachment = async (attachment: PlanNoteAttachment) => {
    try {
      const res = await apiFetch(`/plan-notes/attachments/${attachment.id}`)
      if (!res?.ok) {
        toast.error("Failed to download file")
        return
      }
      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = attachment.original_filename || "download"
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch {
      toast.error("Failed to download file")
    }
  }

  const openAttachmentPreview = async (attachment: PlanNoteAttachment) => {
    try {
      const res = await apiFetch(`/plan-notes/attachments/${attachment.id}`)
      if (!res?.ok) {
        toast.error("Failed to open file")
        return
      }
      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      setPreviewTitle(attachment.original_filename || "Attachment preview")
      setPreviewUrl((prev) => {
        if (prev) window.URL.revokeObjectURL(prev)
        return url
      })
    } catch {
      toast.error("Failed to open file")
    }
  }

  const deleteAttachmentFromDialog = async (noteId: string, attachment: PlanNoteAttachment) => {
    const confirmed = await confirm({
      title: "Delete attachment",
      description: `Delete "${attachment.original_filename}"?`,
      confirmLabel: "Delete",
      variant: "destructive",
    })
    if (!confirmed) return

    setDeletingAttachmentIds((prev) => (prev.includes(attachment.id) ? prev : [...prev, attachment.id]))
    try {
      const res = await apiFetch(`/plan-notes/attachments/${attachment.id}`, {
        method: "DELETE",
      })
      if (!res?.ok) {
        toast.error("Failed to delete file")
        return
      }
      removeNoteAttachment(noteId, attachment.id)
      toast.success("Attachment deleted")
    } catch {
      toast.error("Failed to delete file")
    } finally {
      setDeletingAttachmentIds((prev) => prev.filter((id) => id !== attachment.id))
    }
  }

  React.useEffect(() => {
    return () => {
      if (previewUrl) {
        window.URL.revokeObjectURL(previewUrl)
      }
    }
  }, [previewUrl])

  React.useEffect(() => {
    if (!attachmentsDialogOpen) {
      resetManageAttachmentsState()
      setAttachmentsDialogNoteId(null)
    }
  }, [attachmentsDialogOpen, resetManageAttachmentsState])

  const createNote = async () => {
    if (!content.trim()) {
      toast.error("Content is required")
      return
    }
    // Use URL parameters if present, otherwise determine based on user role
    const departmentForNote = searchParams.get("department_id") || null
    const projectForNote = searchParams.get("project_id") || null
    
    // Determine department_id to send to backend
    let finalDepartmentId = departmentForNote
    const finalProjectId = projectForNote
    
    // If no URL params, send user's department_id for STAFF users (for backend validation)
    // but we'll hide it in the display if it matches the user's auto-assigned department
    if (!departmentForNote && !projectForNote) {
      const isAdminOrManager = user?.role === "ADMIN" || user?.role === "MANAGER"
      if (!isAdminOrManager && user?.department_id) {
        finalDepartmentId = user.department_id
      }
    }
    
    setPosting(true)
    try {
      const res = await apiFetch("/plan-notes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: content.trim(),
          one_h_marker: noteOneHMarker === ONE_H_MARKER_NONE ? null : noteOneHMarker,
          one_h_marker_comment: noteOneHMarker === ONE_H_MARKER_NONE ? null : noteOneHMarkerComment.trim() || null,
          note_type: noteType,
          priority: priority === "NONE" ? null : priority,
          department_id: finalDepartmentId,
          project_id: finalProjectId,
          planned_for_date: plannedHorizonToIso(plannedHorizonNewNote),
        }),
      })
      if (!res?.ok) {
        let errorMessage = "Failed to create note"
        try {
          const errorData = (await res.json()) as { detail?: string }
          if (errorData?.detail) {
            errorMessage = errorData.detail
          }
        } catch {
          // ignore
        }
        toast.error(errorMessage)
        return
      }
      const created = (await res.json()) as PlanNote
      setNotes((prev) => [created, ...prev])
      setContent("")
      setNoteOneHMarker(ONE_H_MARKER_NONE)
      setNoteOneHMarkerComment("")
      setPlannedHorizonNewNote(PLANNED_HORIZON_NONE)
      if (selectedFiles.length > 0) {
        try {
          const attachments = await uploadNoteAttachments(created.id, selectedFiles)
          mergeNoteAttachments(created.id, attachments)
          setSelectedFiles([])
        } catch (error) {
          console.error("Attachment upload failed:", error)
          toast.error("Note saved, attachments failed")
        }
      }
    } finally {
      setPosting(false)
    }
  }

  const openEditNote = (note: PlanNote) => {
    const parsedContent = parseMarkedNoteContent(note.content)
    setEditOneHMarker(note.one_h_marker ?? ONE_H_MARKER_NONE)
    setEditOneHMarkerComment(note.one_h_marker_comment ?? "")
    setEditNoteId(note.id)
    setEditContent(parsedContent.text)
    setEditDoneRanges(parsedContent.doneRanges)
    setEditAddedRanges(parsedContent.addedRanges)
    const taskInfo = noteTaskInfo.get(note.id)
    setEditDescription(taskInfo?.description || "")
    setEditTaskIsRepetitive(taskInfo?.isRepetitive ?? false)
    const isoDeadline = taskDateKey(taskInfo?.dueDate ?? null) || ""
    const importantInitial = Boolean(taskInfo?.isDeadlineImportant)
    setEditTaskDeadline(isoDeadline)
    setEditTaskInitialDeadline(isoDeadline)
    setEditTaskDeadlineImportant(importantInitial)
    setEditTaskInitialDeadlineImportant(importantInitial)
    setEditPlannedHorizon(matchStoredDateToPlannedHorizon(note.planned_for_date ? String(note.planned_for_date) : null))
  }

  const handleEditContentChange = (nextContent: string) => {
    setEditDoneRanges((current) => adjustTextRangesForTextChange(editContent, nextContent, current))
    setEditAddedRanges((current) => addInsertedTextRange(editContent, nextContent, current))
    setEditContent(nextContent)
  }

  const applyTextEditToTextarea = React.useCallback(
    (
      textarea: HTMLTextAreaElement | null,
      currentValue: string,
      onChange: (nextValue: string) => void,
      transform: (value: string, selectionStart: number, selectionEnd: number) => TextSelectionTransformResult
    ) => {
      if (!textarea) return
      const result = applyTextSelectionTransform(
        currentValue,
        textarea.selectionStart,
        textarea.selectionEnd,
        transform
      )
      onChange(result.nextValue)
      window.setTimeout(() => {
        textarea.focus()
        textarea.setSelectionRange(result.selectionStart, result.selectionEnd)
      }, 0)
    },
    []
  )

  const applyNewNoteBold = React.useCallback(() => {
    applyTextEditToTextarea(contentTextareaRef.current, content, setContent, (value, selectionStart, selectionEnd) =>
      wrapSelectedText(value, selectionStart, selectionEnd, "**")
    )
  }, [applyTextEditToTextarea, content])

  const applyNewNoteBullets = React.useCallback(() => {
    applyTextEditToTextarea(contentTextareaRef.current, content, setContent, (value, selectionStart, selectionEnd) =>
      prefixSelectedLines(value, selectionStart, selectionEnd, () => "• ")
    )
  }, [applyTextEditToTextarea, content])

  const applyNewNoteNumbers = React.useCallback(() => {
    applyTextEditToTextarea(contentTextareaRef.current, content, setContent, (value, selectionStart, selectionEnd) =>
      prefixSelectedLines(value, selectionStart, selectionEnd, (lineIndex) => `${lineIndex + 1}. `)
    )
  }, [applyTextEditToTextarea, content])

  const applyEditNoteBold = React.useCallback(() => {
    applyTextEditToTextarea(editTextareaRef.current, editContent, handleEditContentChange, (value, selectionStart, selectionEnd) =>
      wrapSelectedText(value, selectionStart, selectionEnd, "**")
    )
  }, [applyTextEditToTextarea, editContent])

  const applyEditNoteBullets = React.useCallback(() => {
    applyTextEditToTextarea(editTextareaRef.current, editContent, handleEditContentChange, (value, selectionStart, selectionEnd) =>
      prefixSelectedLines(value, selectionStart, selectionEnd, () => "• ")
    )
  }, [applyTextEditToTextarea, editContent])

  const applyEditNoteNumbers = React.useCallback(() => {
    applyTextEditToTextarea(editTextareaRef.current, editContent, handleEditContentChange, (value, selectionStart, selectionEnd) =>
      prefixSelectedLines(value, selectionStart, selectionEnd, (lineIndex) => `${lineIndex + 1}. `)
    )
  }, [applyTextEditToTextarea, editContent])

  const markSelectedEditTextDone = () => {
    const textarea = editTextareaRef.current
    if (!textarea) return
    const start = textarea.selectionStart
    const end = textarea.selectionEnd
    if (!editContent.slice(start, end).trim()) {
      toast.error("Select text inside the note to strike or undo")
      return
    }
    const scrollTop = textarea.scrollTop
    const scrollLeft = textarea.scrollLeft
    const direction = textarea.selectionDirection
    setEditDoneRanges((current) => toggleDoneRange(current, { start, end }))
    window.setTimeout(() => {
      textarea.focus({ preventScroll: true })
      textarea.setSelectionRange(start, end, direction)
      textarea.scrollTop = scrollTop
      textarea.scrollLeft = scrollLeft
    }, 0)
  }

  const getNoteSelectionRange = (noteId: string) => {
    const container = document.getElementById(`ga-note-content-${noteId}`)
    const selection = window.getSelection()
    if (!container || !selection || selection.rangeCount === 0 || selection.isCollapsed) return null

    const range = selection.getRangeAt(0)
    const containsNode = (node: Node) => node === container || container.contains(node)
    if (!containsNode(range.startContainer) || !containsNode(range.endContainer)) return null

    const beforeSelection = range.cloneRange()
    beforeSelection.selectNodeContents(container)
    beforeSelection.setEnd(range.startContainer, range.startOffset)

    const start = beforeSelection.toString().length
    const end = start + range.toString().length
    return end > start ? { start, end } : null
  }

  const markSelectedNoteTextDone = async (note: PlanNote) => {
    const parsedContent = parseMarkedNoteContent(note.content)
    const selectionRange = getNoteSelectionRange(note.id)
    if (!selectionRange) {
      toast.error("Select text inside the note to mark done")
      return
    }

    const selected = parsedContent.text.slice(selectionRange.start, selectionRange.end)
    if (!selected.trim()) {
      toast.error("Select text inside the note to mark done")
      return
    }

    const nextRanges = toggleDoneRange(parsedContent.doneRanges, selectionRange)

    setMarkingSelectedNoteId(note.id)
    try {
      const res = await apiFetch(`/plan-notes/${note.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: serializeMarkedNoteContent(parsedContent.text, nextRanges, parsedContent.addedRanges).trim(),
        }),
      })
      if (!res?.ok) {
        toast.error("Failed to mark selected text done")
        return
      }
      const updated = (await res.json()) as PlanNote
      setNotes((prev) => prev.map((n) => (n.id === updated.id ? updated : n)))
    } catch (error) {
      console.error("Failed to mark selected note text done:", error)
      toast.error("Failed to mark selected text done")
    } finally {
      setMarkingSelectedNoteId(null)
    }
  }

  const saveEditNote = async () => {
    if (!editNoteId) return
    const trimmed = editContent.trim()
    if (!trimmed) {
      toast.error("Note text cannot be empty")
      return
    }
    setSavingEdit(true)
    try {
      // Update the note
      const res = await apiFetch(`/plan-notes/${editNoteId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: serializeMarkedNoteContent(editContent, editDoneRanges, editAddedRanges).trim(),
          planned_for_date: plannedHorizonToIso(editPlannedHorizon),
          one_h_marker: editOneHMarker === ONE_H_MARKER_NONE ? null : editOneHMarker,
          one_h_marker_comment: editOneHMarker === ONE_H_MARKER_NONE ? null : editOneHMarkerComment.trim() || null,
        }),
      })
      if (res?.ok) {
        const updated = (await res.json()) as PlanNote
        setNotes((prev) => prev.map((n) => (n.id === updated.id ? updated : n)))
        
        // Update the task description if a task exists
        const taskInfo = noteTaskInfo.get(editNoteId)
        if (taskInfo?.taskId) {
          if (editTaskIsRepetitive !== "indeterminate" && editTaskIsRepetitive !== (taskInfo.isRepetitive ?? false)) {
            const repetitiveRes = await apiFetch(`/plan-notes/${editNoteId}/task-bundle`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ is_repetitive: editTaskIsRepetitive, expected_updated_at: updated.updated_at }),
            })
            if (!repetitiveRes.ok) {
              toast.error("Note updated, but repetitive task setting could not be saved")
              return
            }
            const bundle = await repetitiveRes.json() as { note: PlanNote }
            setNotes((prev) => prev.map((note) => note.id === bundle.note.id ? bundle.note : note))
          }
          const taskRes = await apiFetch(`/tasks/${taskInfo.taskId}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ description: editDescription.trim() || null }),
          })
          if (taskRes?.ok) {
            // Reload note task info to reflect the updated description
            const notesRes = await apiFetch("/tasks?include_done=true&include_all_departments=true")
            if (notesRes?.ok) {
              const tasksData = (await notesRes.json()) as Task[]
              const userMapById = new Map(users.map((u) => [u.id, u]))
              const map = new Map<string, NoteTaskInfo>()
              const mergeAssignees = (base: TaskAssignee[], incoming: TaskAssignee[]) => {
                const result: TaskAssignee[] = []
                const seen = new Set<string>()
                const add = (assignee: TaskAssignee) => {
                  const key =
                    assignee.id ||
                    assignee.username ||
                    assignee.full_name ||
                    assignee.email ||
                    Math.random().toString()
                  if (seen.has(key)) return
                  seen.add(key)
                  result.push(assignee)
                }
                base.forEach(add)
                incoming.forEach(add)
                return result
              }
              for (const t of tasksData) {
                if (!t.plan_note_origin_id) continue
                let assignees: TaskAssignee[] = t.assignees ?? []
                if (assignees.length === 0 && t.assigned_to) {
                  const fallback = userMapById.get(t.assigned_to)
                  if (fallback) {
                    assignees = [{
                      id: fallback.id,
                      email: null,
                      username: fallback.username || null,
                      full_name: fallback.full_name || null,
                      department_id: fallback.department_id || null,
                    }]
                  }
                }
                const existing = map.get(t.plan_note_origin_id)
                map.set(t.plan_note_origin_id, {
                  assignees: mergeAssignees(existing?.assignees ?? [], assignees),
                  description: existing?.description ?? t.description ?? null,
                  taskId: existing?.taskId ?? t.id,
                  taskDepartmentId: existing?.taskDepartmentId ?? t.department_id ?? null,
                  taskProjectId: existing?.taskProjectId ?? t.project_id ?? null,
                  taskStatus: existing?.taskStatus ?? t.status ?? null,
                  taskStatuses: [...(existing?.taskStatuses ?? []), t.status ?? ""],
                  taskTypeLabels: mergeTaskTypeLabels(existing?.taskTypeLabels, getTaskTypeLabels(t)),
                  isRepetitive: existing?.isRepetitive === undefined
                    ? Boolean(t.is_repetitive)
                    : existing.isRepetitive === Boolean(t.is_repetitive) ? existing.isRepetitive : "indeterminate",
                })
              }
              setNoteTaskInfo(map)
            }
          } else {
            let errorMessage = "Note updated, but linked task description could not be updated"
            try {
              const errorData = (await taskRes.json()) as { detail?: string }
              if (errorData?.detail) {
                errorMessage = `Note updated, but linked task description could not be updated: ${errorData.detail}`
              }
            } catch {
              // Keep the generic fallback message.
            }
            toast.error(errorMessage)
          }

          const deadlineChanged =
            editTaskDeadline !== editTaskInitialDeadline ||
            editTaskDeadlineImportant !== editTaskInitialDeadlineImportant
          if (deadlineChanged) {
            const nextIsoDeadline = editTaskDeadline
              ? new Date(editTaskDeadline).toISOString()
              : null
            const deadlineRes = await apiFetch(`/plan-notes/${editNoteId}/task-deadline`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                due_date: nextIsoDeadline,
                is_deadline_important: editTaskDeadlineImportant,
                clear: nextIsoDeadline === null,
              }),
            })
            if (deadlineRes?.ok) {
              applyDeadlineUpdateToInfo(editNoteId, nextIsoDeadline, editTaskDeadlineImportant)
              void loadNoteTasks()
            } else {
              let errorMessage = "Note updated, but task deadline could not be updated"
              try {
                const errorData = (await deadlineRes.json()) as { detail?: string }
                if (errorData?.detail) {
                  errorMessage = `Note updated, but task deadline could not be updated: ${errorData.detail}`
                }
              } catch {
                // Keep the generic fallback message.
              }
              toast.error(errorMessage)
            }
          }
        }
        
        toast.success("Note updated")
        setEditNoteId(null)
        setEditDoneRanges([])
        setEditAddedRanges([])
        setEditTaskDeadline("")
        setEditTaskInitialDeadline("")
        setEditTaskDeadlineImportant(false)
        setEditTaskInitialDeadlineImportant(false)
      } else {
        let errorMessage = "Failed to update note"
        try {
          const errorData = (await res.json()) as { detail?: string }
          if (errorData?.detail) {
            errorMessage = errorData.detail
          }
        } catch {
          // Keep the generic fallback message.
        }
        toast.error(errorMessage)
      }
    } finally {
      setSavingEdit(false)
    }
  }

  const openTaskDialog = (note: PlanNote) => {
    const hasProject = Boolean(note.project_id)
    const noteDepartment = note.department_id ? departments.find((d) => d.id === note.department_id) || null : null
    const noteProject = note.project_id ? projects.find((p) => p.id === note.project_id) || null : null
    const projectDepartment = noteProject?.department_id
      ? departments.find((d) => d.id === noteProject.department_id) || null
      : null
    const isDevLinked = isDevelopmentDepartment(noteDepartment) || isDevelopmentDepartment(projectDepartment)

    if (hasProject && !isDevLinked) {
      toast.error("Tasks for non-development project notes must be created manually")
      return
    }
    const defaultTitle = noteToTaskTitle(note.content || "")
    setTaskOneHReportSlot(ONE_H_REPORT_SLOT_NONE_VALUE)
    setTaskOneHMarker(note.one_h_marker ?? ONE_H_MARKER_NONE)
    setTaskOneHMarkerComment(note.one_h_marker_comment ?? "")
    setTaskDialogNoteId(note.id)
    setTaskTitle(defaultTitle)
    setTaskDescription("") // start empty so creator can add detailed description
    setTaskPriority(note.priority === "HIGH" ? "HIGH" : "NORMAL")
    setTaskFinishPeriod(FINISH_PERIOD_NONE_VALUE)
    setTaskDueDate("")
    setTaskStartDate("")
    setTaskDeadlineImportant(false)
    setTaskIsRepetitive(false)
    setTaskAssigneeIds([])
    setTaskDepartmentIds([])
    setTaskProjectId(note.project_id ?? "NONE")
  }

  // Get available priority/type options based on whether a project is selected
  const availablePriorityOptions = React.useMemo<readonly TaskTypeOption[]>(() => {
    if (taskProjectId !== "NONE") {
      return TASK_TYPE_OPTIONS_WITH_PROJECT
    }
    return TASK_TYPE_OPTIONS_NO_PROJECT
  }, [taskProjectId])

  const createTaskFromNote = async (note: PlanNote) => {
    if (note.is_converted_to_task) return
    const hasProject = Boolean(note.project_id)
    const noteDepartment = note.department_id ? departments.find((d) => d.id === note.department_id) || null : null
    const noteProject = note.project_id ? projects.find((p) => p.id === note.project_id) || null : null
    const projectDepartment = noteProject?.department_id
      ? departments.find((d) => d.id === noteProject.department_id) || null
      : null
    const isDevLinked = isDevelopmentDepartment(noteDepartment) || isDevelopmentDepartment(projectDepartment)
    if (hasProject && !isDevLinked) {
      toast.error("Tasks for non-development project notes must be created manually")
      return
    }
    if (!taskTitle.trim()) {
      toast.error("Task title is required")
      return
    }
    if (taskAssigneeIds.length === 0) {
      toast.error("Select at least one assignee before creating a task")
      return
    }
    const effectiveDepartments =
      taskDepartmentIds.length > 0
        ? taskDepartmentIds
        : note.department_id
          ? [note.department_id]
          : []
    if (effectiveDepartments.length === 0) {
      toast.error("Select at least one department before creating a task")
      return
    }
    const pvAssignees = taskAssigneeIds.flatMap((id) => {
      const leave = taskPvByAssigneeId.get(id)
      return leave ? [`${taskAssigneeLabel(users.find((person) => person.id === id), id)} is in PV until ${formatISODateDMY(leave.endDate)}`] : []
    })
    if (pvAssignees.length) toast.warning("Selected assignee is in PV", { description: pvAssignees.join(" · ") })
    const primaryDepartmentId = effectiveDepartments[0]
    setCreatingTask(true)
    try {
      const dueDateValue = taskDueDate ? new Date(taskDueDate).toISOString() : null
      const startDateValue = taskStartDate ? new Date(taskStartDate).toISOString() : null
      
      // Map task type/priority to actual priority and boolean flags
      const isProjectTask = taskProjectId !== "NONE"
      let actualPriority: TaskPriority = "NORMAL"
      let isBllok = false
      let is1hReport = false
      let isR1 = false
      let isPersonal = false

      if (isProjectTask) {
        // For project tasks: allow HIGH, NORMAL, 1H, R1, Personal, or BLLOK
        if (taskPriority === "1H") {
          is1hReport = true
          actualPriority = "NORMAL"
        } else if (taskPriority === "R1") {
          isR1 = true
          actualPriority = "NORMAL"
        } else if (taskPriority === "PERSONAL") {
          isPersonal = true
          actualPriority = "NORMAL"
        } else if (taskPriority === "BLLOK") {
          isBllok = true
          actualPriority = "NORMAL"
        } else {
          actualPriority = taskPriority === "HIGH" ? "HIGH" : "NORMAL"
        }
      } else {
        // For non-project tasks: map to priority or boolean flags
        if (taskPriority === "BLLOK") {
          isBllok = true
          actualPriority = "NORMAL"
        } else if (taskPriority === "1H") {
          is1hReport = true
          actualPriority = "NORMAL"
        } else if (taskPriority === "R1") {
          isR1 = true
          actualPriority = "NORMAL"
        } else if (taskPriority === "PERSONAL") {
          isPersonal = true
          actualPriority = "NORMAL"
        } else {
          actualPriority = taskPriority === "HIGH" ? "HIGH" : "NORMAL"
        }
      }

      const taskRes = await apiFetch("/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: taskTitle.trim() || noteToTaskTitle(note.content || ""),
          description: taskDescription.trim() || null,
          status: "TODO",
          priority: actualPriority,
          finish_period: taskFinishPeriod === FINISH_PERIOD_NONE_VALUE ? null : taskFinishPeriod,
          due_date: dueDateValue,
          start_date: startDateValue,
          is_deadline_important: taskDeadlineImportant,
          is_repetitive: taskIsRepetitive,
          assigned_to: taskAssigneeIds[0] ?? null,
          assignees: taskAssigneeIds,
          plan_note_origin_id: note.id,
          department_id: primaryDepartmentId,
          project_id: taskProjectId !== "NONE" ? taskProjectId : null,
          is_bllok: isBllok,
          is_1h_report: is1hReport,
          one_h_report_slot: is1hReport && taskOneHReportSlot !== ONE_H_REPORT_SLOT_NONE_VALUE ? taskOneHReportSlot : null,
          one_h_marker: taskOneHMarker === ONE_H_MARKER_NONE ? null : taskOneHMarker,
          one_h_marker_comment: taskOneHMarker === ONE_H_MARKER_NONE ? null : taskOneHMarkerComment.trim() || null,
          is_r1: isR1,
          is_personal: isPersonal,
        }),
      })
      if (!taskRes.ok) {
        toast.error("Failed to create task")
        return
      }
      const createdTask = (await taskRes.json()) as Task
      const patchRes = await apiFetch(`/plan-notes/${note.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_converted_to_task: true }),
      })
      if (patchRes.ok) {
        const updated = (await patchRes.json()) as PlanNote
        setNotes((prev) => prev.map((n) => (n.id === note.id ? updated : n)))
      } else {
        setNotes((prev) =>
          prev.map((n) => (n.id === note.id ? { ...n, is_converted_to_task: true } : n))
        )
      }
      setNoteTaskInfo((prev) => {
        const next = new Map(prev)
        const userMapById = new Map(users.map((u) => [u.id, u]))
        let assignees: TaskAssignee[] = []
        if (taskAssigneeIds.length > 0) {
          assignees = taskAssigneeIds.map((id) => {
            const user = userMapById.get(id)
            return {
              id,
              email: null,
              username: user?.username || null,
              full_name: user?.full_name || null,
              department_id: user?.department_id || null,
            }
          })
        } else if (createdTask.assignees && createdTask.assignees.length > 0) {
          assignees = createdTask.assignees
        } else if (createdTask.assigned_to) {
          const fallback = userMapById.get(createdTask.assigned_to)
          if (fallback) {
            assignees = [{
              id: fallback.id,
              email: null,
              username: fallback.username || null,
              full_name: fallback.full_name || null,
              department_id: fallback.department_id || null,
            }]
          }
        }
        const cleanedDescription = taskDescription.trim()
        next.set(note.id, {
          assignees,
          description: (cleanedDescription || createdTask.description) ?? null,
          taskId: createdTask.id,
          taskDepartmentId: createdTask.department_id ?? null,
          taskProjectId: createdTask.project_id ?? null,
          taskStatus: createdTask.status ?? null,
          taskStatuses: [createdTask.status ?? ""],
          taskTypeLabels: getTaskTypeLabels(createdTask),
          dueDate: createdTask.due_date ?? null,
          startDate: createdTask.start_date ?? null,
          finishPeriod: createdTask.finish_period ?? null,
          isDeadlineImportant: createdTask.is_deadline_important ?? null,
          isRepetitive: Boolean(createdTask.is_repetitive),
        })
        return next
      })
      setTaskDialogNoteId(null)
      toast.success("Task created from note")
    } finally {
      setCreatingTask(false)
    }
  }

  const formatPlannedHorizonDisplay = React.useCallback((note: PlanNote, taskInfo?: NoteTaskInfo | null) => {
    const primaryIso = taskInfo?.dueDate ?? note.planned_for_date ?? null
    if (!primaryIso) return "—"
    const key = taskDateKey(primaryIso)
    if (!key) return "—"
    const matched = matchStoredDateToPlannedHorizon(primaryIso)
    const horizonByOption: Record<Exclude<PlannedHorizonOption, typeof PLANNED_HORIZON_NONE>, string> = {
      next_week: "Next week",
      next_2_weeks: "Next 2 weeks",
      next_3_weeks: "Next 3 weeks",
      next_4_weeks: "Next 4 weeks",
      next_month: "Next month",
      next_2_months: "Next 2 months",
    }
    if (matched !== PLANNED_HORIZON_NONE) {
      return horizonByOption[matched]
    }
    const thisMon = mondayISO()
    const nextWkEnd = shiftIsoDateByDays(shiftIsoDateByDays(thisMon, 7), 4)
    if (key > nextWkEnd) {
      return "Later"
    }
    return "—"
  }, [])

  const applyDeadlineUpdateToInfo = React.useCallback(
    (noteId: string, isoDateValue: string | null, important: boolean) => {
      setNoteTaskInfo((prev) => {
        const next = new Map(prev)
        const existing = next.get(noteId)
        if (existing) {
          next.set(noteId, {
            ...existing,
            dueDate: isoDateValue,
            isDeadlineImportant: important,
          })
        }
        return next
      })
    },
    []
  )

  const closeNote = async (id: string) => {
    const res = await apiFetch(`/plan-notes/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "CLOSED" }),
    })
    if (res?.ok) {
      const updated = (await res.json()) as PlanNote
      setNotes((prev) => prev.map((n) => (n.id === id ? updated : n)))
    } else {
      toast.error("Failed to update note")
    }
  }

  const toggleNoteDiscussed = async (id: string, isDiscussed: boolean) => {
    const res = await apiFetch(`/plan-notes/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_discussed: isDiscussed }),
    })
    if (res?.ok) {
      const updated = (await res.json()) as PlanNote
      setNotes((prev) => prev.map((n) => (n.id === id ? updated : n)))
    } else {
      toast.error("Failed to update discussion status")
    }
  }

  const markWaitingTasksDone = async (noteId: string) => {
    setMarkingDoneNoteId(noteId)
    try {
      const res = await apiFetch(`/plan-notes/${noteId}/mark-waiting-done`, {
        method: "POST",
      })
      if (!res?.ok) {
        toast.error("Failed to update tasks")
        return
      }
      const result = (await res.json()) as { updated_count?: number; skipped_count?: number }
      if ((result.updated_count ?? 0) === 0) {
        toast.info("No tasks to update")
      } else {
        toast.success("Tasks marked as done")
      }
    } catch (error) {
      console.error("Failed to mark tasks done:", error)
      toast.error("Failed to update tasks")
    } finally {
      await loadNoteTasks([noteId])
      setMarkingDoneNoteId(null)
    }
  }

  const downloadPxJavReport = async (format: "xlsx" | "docx" | "pdf") => {
    try {
      const res = await apiFetch(`/reports/px-jav-weekly/download?format=${format}`)
      if (!res?.ok) {
        let message = `Could not export PX JAV as ${format.toUpperCase()}`
        try {
          const payload = (await res.json()) as { detail?: string }
          if (payload.detail) message = payload.detail
        } catch {
          // Keep the fallback message.
        }
        throw new Error(message)
      }
      const blob = await res.blob()
      const disposition = res.headers.get("content-disposition") || ""
      const match = disposition.match(/filename="?([^";]+)"?/i)
      const filename = match?.[1] || `Raporti_PX_JAV.${format}`
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      toast.success(`PX JAV ${format.toUpperCase()} exported.`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "PX JAV export failed")
    }
  }

  const exportDailyReport = async () => downloadPxJavReport("xlsx")

  // Project list is used only in the task creation dialog (filtered separately).
  const taskDialogNote = taskDialogNoteId ? notes.find((n) => n.id === taskDialogNoteId) || null : null
  const taskDepartmentLocked = false
  const effectiveTaskDepartmentIds = React.useMemo(() => {
    if (taskDepartmentIds.length > 0) return taskDepartmentIds
    if (taskDialogNote?.department_id) return [taskDialogNote.department_id]
    return []
  }, [taskDepartmentIds, taskDialogNote?.department_id])
  const taskAssigneeOptions = users
  const taskSelectedDateRange = React.useMemo(() => {
    const dates = [taskStartDate, taskDueDate].filter(Boolean).sort()
    if (dates.length === 0) return null
    return {
      start: dates[0],
      end: dates[dates.length - 1],
      key: dateRangeKey(dates[0], dates[dates.length - 1]),
    }
  }, [taskDueDate, taskStartDate])
  const taskSelectedWeekStartISOs = React.useMemo(() => {
    if (!taskSelectedDateRange) return null
    const weekStarts = new Set<string>()
    for (const iso of taskSelectedDateRange.key.split("|").filter(Boolean)) {
      weekStarts.add(toISODate(getMonday(new Date(`${iso}T12:00:00`))))
    }
    return Array.from(weekStarts)
  }, [taskSelectedDateRange])
  const taskPvAssigneeIds = React.useMemo(() => {
    if (!taskSelectedDateRange) return new Set<string>()
    const result = new Set<string>()
    const selectedDates = taskSelectedDateRange.key.split("|").filter(Boolean)
    const allUsersOnLeave = taskDateLeaveItems.some((item) =>
      item.fullDay &&
      item.isAllUsers &&
      selectedDates.some((iso) => iso >= item.startDate && iso <= item.endDate)
    )
    if (allUsersOnLeave) {
      taskAssigneeOptions.forEach((person) => {
        if (person.id) result.add(person.id)
      })
    }
    for (const item of taskDateLeaveItems) {
      if (!item.fullDay || !item.userId) continue
      if (selectedDates.some((iso) => iso >= item.startDate && iso <= item.endDate)) {
        result.add(item.userId)
      }
    }
    return result
  }, [taskAssigneeOptions, taskDateLeaveItems, taskSelectedDateRange])
  const taskPvByAssigneeId = React.useMemo(() => {
    if (!taskSelectedDateRange) return new Map<string, CommonLeaveItem>()
    const selectedDates = taskSelectedDateRange.key.split("|").filter(Boolean)
    const result = new Map<string, CommonLeaveItem>()
    const allUsersLeave = taskDateLeaveItems
      .filter((item) =>
        item.fullDay &&
        item.isAllUsers &&
        selectedDates.some((iso) => iso >= item.startDate && iso <= item.endDate)
      )
      .sort((a, b) => b.endDate.localeCompare(a.endDate))[0]
    if (allUsersLeave) {
      taskAssigneeOptions.forEach((person) => {
        if (person.id) result.set(person.id, allUsersLeave)
      })
    }
    for (const item of taskDateLeaveItems) {
      if (!item.fullDay || !item.userId) continue
      if (!selectedDates.some((iso) => iso >= item.startDate && iso <= item.endDate)) continue
      const existing = result.get(item.userId)
      if (!existing || item.endDate > existing.endDate) {
        result.set(item.userId, item)
      }
    }
    return result
  }, [taskAssigneeOptions, taskDateLeaveItems, taskSelectedDateRange])
  const taskAssigneeLabel = React.useCallback(
    (person?: Pick<UserLookup, "id" | "full_name" | "username"> | null, fallbackId?: string) => {
      const id = person?.id || fallbackId || ""
      return person?.full_name || person?.username || fallbackId || id
    },
    []
  )
  const taskAssigneePvBadge = React.useCallback(
    (userId?: string | null) =>
      userId && taskPvAssigneeIds.has(userId) ? (
        <span
          className="ml-1 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-red-600 text-[9px] font-bold leading-none text-white"
          title={`PV until ${formatISODateDMY(taskPvByAssigneeId.get(userId)?.endDate)}`}
        >
          PV
        </span>
      ) : null,
    [taskPvAssigneeIds, taskPvByAssigneeId]
  )

  React.useEffect(() => {
    if (!taskDialogNoteId || !taskSelectedWeekStartISOs?.length) {
      setTaskDateLeaveItems([])
      return
    }

    let cancelled = false
    const loadTaskDateLeave = async () => {
      const responses = await Promise.all(
        taskSelectedWeekStartISOs.map((weekStartIso) => {
          const params = new URLSearchParams({
            week_start: weekStartIso,
            include: "entries",
            include_all_departments: "true",
          })
          return apiFetch(`/common-view?${params.toString()}`)
        })
      )
      if (responses.some((res) => !res?.ok)) {
        if (!cancelled) setTaskDateLeaveItems([])
        return
      }
      const payloads = await Promise.all(responses.map(async (res) => (await res.json()) as CommonViewLeavePayload))
      const leaveItems = payloads.flatMap((payload) => payload.items?.leave ?? [])
      if (!cancelled) setTaskDateLeaveItems(leaveItems)
    }

    void loadTaskDateLeave().catch((error) => {
      if (!cancelled) { setTaskDateLeaveItems([]); toast.error("Unable to check assignee PV") }
      console.error("Failed to load task date leave:", error)
    })
    return () => {
      cancelled = true
    }
  }, [apiFetch, taskDialogNoteId, taskSelectedWeekStartISOs])



  // Projects filtered by the department chosen in the task dialog
  const primaryDepartmentId = effectiveTaskDepartmentIds[0] || null
  const taskProjectOptions = React.useMemo(() => {
    if (primaryDepartmentId) {
      return projects.filter((p) => p.department_id === primaryDepartmentId)
    }
    return projects
  }, [primaryDepartmentId, projects])

  // Keep projects in sync when opening dialog or changing department
  React.useEffect(() => {
    if (!taskDialogNoteId) return
    const dep =
      effectiveTaskDepartmentIds.length === 1 ? effectiveTaskDepartmentIds[0] : undefined
    void loadProjects(dep)
  }, [effectiveTaskDepartmentIds, loadProjects, taskDialogNoteId])

  // Reset priority when switching between project/non-project modes
  React.useEffect(() => {
    if (!taskDialogNoteId) return
    const currentIsValid = availablePriorityOptions.includes(taskPriority)
     
    if (!currentIsValid) {
      setTaskPriority("NORMAL")
    }
  }, [availablePriorityOptions, taskDialogNoteId, taskPriority])
  const visibleNotes = React.useMemo(() => {
    const now = Date.now()
    const closedCutoff = now - 30 * 24 * 60 * 60 * 1000
    const normalizedSearchQuery = deferredSearchQuery.trim().toLowerCase()

    const withinRange = (note: PlanNote) => {
      const isClosed = note.status === "CLOSED"
      if (isClosed) {
        if (!note.completed_at) return true
        const completed = new Date(note.completed_at).getTime()
        if (Number.isNaN(completed)) return true
        return completed >= closedCutoff
      }
      return true
    }
    const matchesTaskStatusFilter = (note: PlanNote) => {
      if (taskStatusFilter === "all") return true
      if (taskStatusFilter === "open") return note.status !== "CLOSED"
      if (taskStatusFilter === "closed") return note.status === "CLOSED"
      const hasTask = note.is_converted_to_task === true || noteTaskInfo.has(note.id)
      if (taskStatusFilter === "notes") return !hasTask && note.status !== "CLOSED"
      if (taskStatusFilter === "tasks") return hasTask
      const taskInfo = noteTaskInfo.get(note.id)
      if (!taskInfo) return false
      const aggregatedStatus =
        taskInfo.taskStatuses?.length > 1
          ? aggregateTaskStatus(taskInfo.taskStatuses)
          : normalizeTaskStatus(taskInfo.taskStatus)
      if (aggregatedStatus === "UNKNOWN") return false
      return aggregatedStatus === taskStatusFilter
    }
    const matchesContentFilter = (note: PlanNote) => {
      if (contentFilter === "all") return true
      return EMAIL_MARKER_RE.test(note.content || "")
    }
    const matchesNextWeekFilter = (note: PlanNote) => {
      if (nextWeekFilter === "all") return true
      const checked = Boolean(note.next_week)
      return nextWeekFilter === "checked" ? checked : !checked
    }
    const matchesSearchQuery = (note: PlanNote) => {
      if (!normalizedSearchQuery) return true

      const taskInfo = noteTaskInfo.get(note.id)
      const creator = note.created_by ? users.find((person) => person.id === note.created_by) : null
      const noteDepartment = note.department_id ? departments.find((dept) => dept.id === note.department_id) : null
      const taskDepartment = taskInfo?.taskDepartmentId
        ? departments.find((dept) => dept.id === taskInfo.taskDepartmentId)
        : null
      const noteProject = note.project_id ? projects.find((project) => project.id === note.project_id) : null
      const taskProject = taskInfo?.taskProjectId
        ? projects.find((project) => project.id === taskInfo.taskProjectId)
        : null

      const searchHaystack = [
        parseMarkedNoteContent(note.content).text,
        note.comment,
        taskInfo?.description,
        note.note_type,
        note.status,
        creator?.full_name,
        creator?.username,
        noteDepartment?.name,
        taskDepartment?.name,
        noteProject?.title,
        noteProject?.name,
        taskProject?.title,
        taskProject?.name,
        ...(taskInfo?.taskTypeLabels ?? []),
        ...(taskInfo?.assignees ?? []).flatMap((assignee) => [assignee.full_name, assignee.username]),
        ...(note.attachments ?? []).map((attachment) => attachment.original_filename),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()

      return searchHaystack.includes(normalizedSearchQuery)
    }
    const taskDoneBucket = (note: PlanNote) => {
      const taskInfo = noteTaskInfo.get(note.id)
      if (!taskInfo) return 0
      const aggregatedStatus =
        taskInfo.taskStatuses?.length > 1
          ? aggregateTaskStatus(taskInfo.taskStatuses)
          : normalizeTaskStatus(taskInfo.taskStatus)
      return aggregatedStatus === "DONE" ? 1 : 0
    }
    const sorted = [...notes]
      .filter(withinRange)
      .filter(matchesTaskStatusFilter)
      .filter(matchesContentFilter)
      .filter(matchesNextWeekFilter)
      .filter(matchesSearchQuery)
      .sort((a, b) => {
        const aIsClosed = a.status === "CLOSED"
        const bIsClosed = b.status === "CLOSED"
        if (aIsClosed !== bIsClosed) {
          return aIsClosed ? 1 : -1
        }
        const aDoneBucket = taskDoneBucket(a)
        const bDoneBucket = taskDoneBucket(b)
        if (aDoneBucket !== bDoneBucket) {
          return aDoneBucket - bDoneBucket
        }
        const aCreated = a.created_at ? new Date(a.created_at).getTime() : 0
        const bCreated = b.created_at ? new Date(b.created_at).getTime() : 0
        return bCreated - aCreated
      })
    return sorted
  }, [notes, taskStatusFilter, contentFilter, nextWeekFilter, deferredSearchQuery, noteTaskInfo, users, departments, projects])

  React.useEffect(() => {
    setNotesRenderLimit(INITIAL_NOTES_RENDER_LIMIT)
  }, [contentFilter, deferredSearchQuery, departmentId, nextWeekFilter, projectId, taskStatusFilter])

  const renderedNotes = React.useMemo(
    () => visibleNotes.slice(0, notesRenderLimit),
    [notesRenderLimit, visibleNotes]
  )

  const attachmentDialogItems = React.useMemo(() => {
    if (!attachmentsDialogNoteId) return []
    const note = visibleNotes.find((item) => item.id === attachmentsDialogNoteId)
    if (!note) return []
    return (note.attachments ?? []).map((attachment) => ({
      noteId: note.id,
      noteContent: note.content,
      noteCreatedAt: note.created_at,
      attachment,
    }))
  }, [attachmentsDialogNoteId, visibleNotes])

  const attachmentsDialogNote = React.useMemo(() => {
    if (!attachmentsDialogNoteId) return null
    return notes.find((item) => item.id === attachmentsDialogNoteId) ?? null
  }, [attachmentsDialogNoteId, notes])

  const attachmentsDialogCanAddFiles = React.useMemo(() => {
    if (!attachmentsDialogNote) return false
    const taskInfo = noteTaskInfo.get(attachmentsDialogNote.id)
    const isClosed =
      attachmentsDialogNote.status === "CLOSED" ||
      (attachmentsDialogNote as { isClosed?: boolean }).isClosed === true ||
      (attachmentsDialogNote as { closed?: boolean }).closed === true
    const aggregatedStatus =
      taskInfo && (taskInfo.taskStatuses?.length ?? 0) > 1
        ? aggregateTaskStatus(taskInfo.taskStatuses)
        : normalizeTaskStatus(taskInfo?.taskStatus)

    return !isClosed && aggregatedStatus !== "DONE"
  }, [attachmentsDialogNote, noteTaskInfo])

  const openAttachmentsForNote = async (noteId: string) => {
    resetManageAttachmentsState()
    setAttachmentsDialogNoteId(noteId)
    setAttachmentsDialogOpen(true)
    setLoadingAttachmentsNoteId(noteId)
    try {
      const res = await apiFetch(`/plan-notes/${encodeURIComponent(noteId)}`)
      if (!res?.ok) {
        toast.error("Failed to load attachments")
        return
      }
      const loadedNote = (await res.json()) as PlanNote
      setNotes((current) => current.map((note) => (
        note.id === noteId
          ? {
              ...note,
              attachments: loadedNote.attachments ?? [],
              attachment_count: loadedNote.attachment_count ?? loadedNote.attachments?.length ?? 0,
            }
          : note
      )))
    } catch {
      toast.error("Failed to load attachments")
    } finally {
      setLoadingAttachmentsNoteId((current) => (current === noteId ? null : current))
    }
  }

  const uploadAttachmentsFromDialog = async () => {
    if (!attachmentsDialogNoteId || attachmentUploadFiles.length === 0) return
    setUploadingAttachments(true)
    try {
      const attachments = await uploadNoteAttachments(attachmentsDialogNoteId, attachmentUploadFiles)
      mergeNoteAttachments(attachmentsDialogNoteId, attachments)
      resetManageAttachmentsState()
      toast.success("Attachments uploaded")
    } catch (error) {
      console.error("Attachment upload failed:", error)
      toast.error("Failed to upload attachments")
    } finally {
      setUploadingAttachments(false)
    }
  }

  const departmentMap = React.useMemo(() => new Map(departments.map((dept) => [dept.id, dept])), [departments])
  const projectMap = React.useMemo(() => new Map(projects.map((project) => [project.id, project])), [projects])
  const userMap = React.useMemo(() => new Map(users.map((person) => [person.id, person])), [users])

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border bg-gradient-to-r from-amber-50 via-indigo-50 to-cyan-50 p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-xs font-semibold tracking-[0.18em] text-primary/80 uppercase">Weekly planning</div>
            <div className="text-2xl font-semibold leading-tight mt-1 text-slate-900">PX JAV</div>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Badge variant="secondary" className="px-3 py-1 rounded-full shadow-sm bg-emerald-100 text-emerald-800">
              Open {notes.filter((n) => n.status !== "CLOSED").length}
            </Badge>
            <Badge variant="outline" className="px-3 py-1 rounded-full border-indigo-200 text-indigo-800">
              Total: {notes.length}
            </Badge>
          </div>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">New Note</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Button type="button" variant="outline" size="sm" className="h-8 gap-2" onClick={applyNewNoteBold}>
                <Bold className="h-4 w-4" />
                Bold
              </Button>
              <Button type="button" variant="outline" size="sm" className="h-8 gap-2" onClick={applyNewNoteBullets}>
                <List className="h-4 w-4" />
                Bullets
              </Button>
              <Button type="button" variant="outline" size="sm" className="h-8 gap-2" onClick={applyNewNoteNumbers}>
                <ListOrdered className="h-4 w-4" />
                Numbers
              </Button>
              <span className="text-xs text-muted-foreground">Select text for bold, or lines for bullets/numbers.</span>
              <Button className="ml-auto h-8 sm:hidden" onClick={() => void createNote()} disabled={posting}>
                {posting ? "Saving..." : "Save note"}
              </Button>
            </div>
            <Textarea
              ref={contentTextareaRef}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={4}
              className="min-h-[110px] md:min-h-[120px] resize-none text-base md:text-lg bg-primary/5 border-primary/40 shadow-[0_0_0_1px_rgba(0,0,0,0.04)] focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:border-primary"
              autoFocus
            />
            <div className="flex flex-wrap items-center gap-2">
              <Label className="text-xs whitespace-nowrap">Planned for</Label>
              <Select
                value={plannedHorizonNewNote}
                onValueChange={(value) => setPlannedHorizonNewNote(value as PlannedHorizonOption)}
              >
                <SelectTrigger className="h-9 w-[min(100%,240px)] max-w-[260px]">
                  <SelectValue placeholder="Optional" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={PLANNED_HORIZON_NONE}>No date</SelectItem>
                  <SelectItem value="next_week">Next week</SelectItem>
                  <SelectItem value="next_2_weeks">Next 2 weeks</SelectItem>
                  <SelectItem value="next_3_weeks">Next 3 weeks</SelectItem>
                  <SelectItem value="next_4_weeks">Next 4 weeks</SelectItem>
                  <SelectItem value="next_month">Next month</SelectItem>
                  <SelectItem value="next_2_months">Next 2 months</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="max-w-[220px] space-y-2">
            <Label>Symbol (optional)</Label>
            <Select value={noteOneHMarker} onValueChange={(rawValue) => {
              const value = rawValue as OneHMarker | typeof ONE_H_MARKER_NONE
              if (value === ONE_H_MARKER_NONE) { setNoteOneHMarker(value); setNoteOneHMarkerComment(""); return }
              const nextComment = window.prompt("Optional symbol comment:", value === noteOneHMarker ? noteOneHMarkerComment : "")
              if (nextComment !== null) { setNoteOneHMarker(value); setNoteOneHMarkerComment(nextComment) }
            }}>
              <SelectTrigger className={`border-blue-300 bg-blue-50 font-black ${noteOneHMarker === ONE_H_MARKER_NONE ? "text-[#0F2A5F]" : "text-red-600"}`}><SelectValue /></SelectTrigger>
              <SelectContent className="font-black text-[#0F2A5F]">
                <SelectItem value={ONE_H_MARKER_NONE}>No symbol</SelectItem>
                {ONE_H_MARKER_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value} className="font-black text-red-600 focus:text-red-700">{option.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Attachments</Label>
            <Input
              ref={fileInputRef}
              type="file"
              multiple
              onChange={handleFileSelection}
            />
            {selectedFiles.length === 0 ? (
              <div className="text-xs text-muted-foreground">
                No files selected. Max {MAX_ATTACHMENT_FILES} files, {MAX_ATTACHMENT_MB}MB each.
              </div>
            ) : (
              <div className="rounded-md border bg-slate-50 p-2 space-y-2">
                {selectedFiles.map((file, idx) => (
                  <div key={`${file.name}-${idx}`} className="flex items-center justify-between gap-2 text-xs">
                    <div className="flex flex-col">
                      <span className="font-medium text-slate-700">{file.name}</span>
                      <span className="text-slate-500">{formatFileSize(file.size)}</span>
                    </div>
                    <Button variant="ghost" size="sm" onClick={() => removeSelectedFile(idx)}>
                      Remove
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="hidden justify-start sm:flex">
            <Button onClick={() => void createNote()} disabled={posting}>
              {posting ? "Saving..." : "Save note"}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-2">
            <CardTitle className="text-sm">Notes</CardTitle>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              onClick={() => setShowLegend((prev) => !prev)}
            >
              {showLegend ? "Hide legend" : "Show legend"}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {showLegend ? (
            <div className="rounded-md border bg-white">
              <div className="px-4 pt-4">
              <div className="text-xs font-semibold tracking-[0.18em] text-slate-500 uppercase">Legjenda</div>
              </div>
              <div className="p-4 pt-3 overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-16 text-sm">Color</TableHead>
                      <TableHead className="w-36 text-sm">Label</TableHead>
                      <TableHead className="text-sm">Meaning</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    <TableRow className="h-8">
                      <TableCell className="p-1">
                        <div className="w-4 h-4 rounded-sm border border-slate-300 bg-sky-200" />
                      </TableCell>
                      <TableCell className="text-sm font-semibold">Shenim pa task</TableCell>
                      <TableCell className="text-sm text-slate-600">Ngjyra e rreshtit (SHENIMI)</TableCell>
                    </TableRow>
                    <TableRow className="h-8">
                      <TableCell className="p-1">
                        <div className="w-4 h-4 rounded-sm border border-slate-300 bg-pink-200" />
                      </TableCell>
                      <TableCell className="text-sm font-semibold">Me task të krijuar</TableCell>
                      <TableCell className="text-sm text-slate-600">Ngjyra e rreshtit (SHENIMI)</TableCell>
                    </TableRow>
                    <TableRow className="h-8">
                      <TableCell className="p-1">
                        <div className="w-4 h-4 rounded-sm border border-slate-300 bg-yellow-200" />
                      </TableCell>
                      <TableCell className="text-sm font-semibold">Task: In progress</TableCell>
                      <TableCell className="text-sm text-slate-600">Ngjyra e rreshtit (SHENIMI)</TableCell>
                    </TableRow>
                    <TableRow className="h-8">
                      <TableCell className="p-1">
                        <div className="w-4 h-4 rounded-sm border border-slate-300 bg-amber-50" />
                      </TableCell>
                      <TableCell className="text-sm font-semibold">Task: Waiting confirmation</TableCell>
                      <TableCell className="text-sm text-slate-600">Ngjyra e rreshtit (SHENIMI)</TableCell>
                    </TableRow>
                    <TableRow className="h-8">
                      <TableCell className="p-1">
                        <div className="w-4 h-4 rounded-sm border border-emerald-200 bg-emerald-200" />
                      </TableCell>
                      <TableCell className="text-sm font-semibold">Task: Done</TableCell>
                      <TableCell className="text-sm text-slate-600">Ngjyra e rreshtit (SHENIMI)</TableCell>
                    </TableRow>
                    <TableRow className="h-8">
                      <TableCell className="p-1">
                        <div className="w-4 h-4 rounded-sm border border-slate-400 bg-slate-300 opacity-70" />
                      </TableCell>
                      <TableCell className="text-sm font-semibold">Mbyllur</TableCell>
                      <TableCell className="text-sm text-slate-600">Ngjyra e rreshtit (SHENIMI)</TableCell>
                    </TableRow>
                    <TableRow className="h-8">
                      <TableCell className="p-1">
                        <span className="rounded bg-blue-200 px-1 text-xs text-blue-950 ring-1 ring-blue-300">
                          New
                        </span>
                      </TableCell>
                      <TableCell className="text-sm font-semibold">Shtuar ne edit</TableCell>
                      <TableCell className="text-sm text-slate-600">Pjese e shtuar pas krijimit</TableCell>
                    </TableRow>
                    <TableRow className="h-8">
                      <TableCell className="p-1">
                        <div className="w-4 h-4 rounded-sm border border-rose-200 bg-rose-100" />
                      </TableCell>
                      <TableCell className="text-sm font-semibold">GA</TableCell>
                      <TableCell className="text-sm text-slate-600">Inicialet (NGA / PER)</TableCell>
                    </TableRow>
                    <TableRow className="h-8">
                      <TableCell className="p-1">
                        <div className="w-4 h-4 rounded-sm border border-blue-200 bg-blue-100" />
                      </TableCell>
                      <TableCell className="text-sm font-semibold">KA</TableCell>
                      <TableCell className="text-sm text-slate-600">Inicialet (NGA / PER)</TableCell>
                    </TableRow>
                    <TableRow className="h-8">
                      <TableCell className="p-1">
                        <div className="w-4 h-4 rounded-sm border border-slate-300 bg-slate-200" />
                      </TableCell>
                      <TableCell className="text-sm font-semibold">Tjere</TableCell>
                      <TableCell className="text-sm text-slate-600">Inicialet (NGA / PER)</TableCell>
                    </TableRow>
                    <TableRow className="h-8">
                      <TableCell className="p-1">
                        <div className={`w-4 h-4 rounded-sm border ${PRIORITY_BADGE.NORMAL}`} />
                      </TableCell>
                      <TableCell className="text-sm font-semibold">NORMAL</TableCell>
                      <TableCell className="text-sm text-slate-600">Prioriteti i shenimit</TableCell>
                    </TableRow>
                    <TableRow className="h-8">
                      <TableCell className="p-1">
                        <div className={`w-4 h-4 rounded-sm border ${PRIORITY_BADGE.HIGH}`} />
                      </TableCell>
                      <TableCell className="text-sm font-semibold">HIGH</TableCell>
                      <TableCell className="text-sm text-slate-600">Prioriteti i shenimit</TableCell>
                    </TableRow>
                  </TableBody>
                </Table>
              </div>
            </div>
          ) : null}
          <div className="flex flex-wrap items-center gap-3">
            <div className="space-y-1">
              <Select
                value={taskStatusFilter}
                onValueChange={(v) => setTaskStatusFilter(v as TaskStatusFilter)}
              >
                <SelectTrigger className="h-9 w-[180px]">
                  <SelectValue placeholder="Tasks/Status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Tasks/Notes</SelectItem>
                  <SelectItem value="open">Open</SelectItem>
                  <SelectItem
                    value="notes"
                    className="bg-sky-100 text-sky-900 focus:bg-sky-200 focus:text-sky-900"
                  >
                    Notes
                  </SelectItem>
                  <SelectItem
                    value="tasks"
                    className="bg-pink-100 text-pink-900 focus:bg-pink-200 focus:text-pink-900"
                  >
                    Tasks
                  </SelectItem>
                  <SelectItem
                    value="closed"
                    className="bg-slate-200 text-slate-800 focus:bg-slate-300 focus:text-slate-900"
                  >
                    Closed
                  </SelectItem>
                  <SelectItem
                    value="TODO"
                    className="bg-pink-100 text-pink-900 focus:bg-pink-200 focus:text-pink-900"
                  >
                    To do
                  </SelectItem>
                  <SelectItem
                    value="IN_PROGRESS"
                    className="bg-yellow-100 text-amber-900 focus:bg-amber-200 focus:text-amber-900"
                  >
                    In progress
                  </SelectItem>
                  <SelectItem
                    value="WAITING_CLIENT"
                    className="bg-[#F5E6B3] text-[#7A5A00] focus:bg-[#EBD58D] focus:text-[#7A5A00]"
                  >
                    WFE
                  </SelectItem>
                  <SelectItem
                    value="WAITING_CONFIRMATION"
                    className="bg-amber-50 text-blue-900 focus:bg-blue-200 focus:text-blue-900"
                  >
                    Waiting Confirmation
                  </SelectItem>
                  <SelectItem
                    value="DONE"
                    className="bg-emerald-100 text-emerald-900 focus:bg-emerald-200 focus:text-emerald-900"
                  >
                    Done
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Select
                value={contentFilter}
                onValueChange={(v) => setContentFilter(v as ContentFilter)}
              >
                <SelectTrigger className="h-9 w-[140px]">
                  <SelectValue placeholder="Content" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All</SelectItem>
                  <SelectItem value="emails">Emails</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Select
                value={nextWeekFilter}
                onValueChange={(v) => setNextWeekFilter(v as NextWeekFilter)}
              >
                <SelectTrigger className="h-9 w-[140px]">
                  <SelectValue placeholder="This Week" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">This Week</SelectItem>
                  <SelectItem value="checked">Checked</SelectItem>
                  <SelectItem value="unchecked">Blank</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Input
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Search notes..."
                className="h-9 w-[220px]"
                aria-label="Search notes"
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              className="h-8 rounded-lg border-slate-300 bg-white px-3 text-sm text-slate-900 shadow-sm hover:bg-slate-50"
              onClick={() => {
                const printWindow = window.open('', '_blank')
                if (!printWindow) return
                
                const tableContainer = document.querySelector('.notes-table-container')
                if (!tableContainer) return
                
                const table = tableContainer.querySelector('table')
                if (!table) return
                
                // Get user initials
                const userInitials = user ? getInitials(user.full_name || user.username || "") : "USER"
                
                // Get current date and time
                const now = new Date()
                const day = now.getDate().toString().padStart(2, "0")
                const month = (now.getMonth() + 1).toString().padStart(2, "0")
                const year = now.getFullYear()
                let hours = now.getHours()
                const minutes = now.getMinutes().toString().padStart(2, "0")
                const ampm = hours >= 12 ? "PM" : "AM"
                hours = hours % 12
                hours = hours ? hours : 12
                const hoursStr = hours.toString().padStart(2, "0")
                const dateTimeStr = `${day}.${month}.${year}, ${hoursStr}:${minutes} ${ampm}`
                
                // Clone the table and clean up React-specific attributes
                const clonedTable = table.cloneNode(true) as HTMLElement
                clonedTable.querySelectorAll('[data-planning-editor="true"]').forEach((row) => row.remove())
                const allElements = clonedTable.querySelectorAll('*')
                allElements.forEach((el) => {
                  // Remove React event handlers and other attributes
                  Array.from(el.attributes).forEach((attr) => {
                    if (attr.name.startsWith('data-') || attr.name.startsWith('on') || attr.name === 'class') {
                      // Keep class for styling
                      return
                    }
                    if (['style', 'colspan', 'rowspan'].includes(attr.name)) {
                      return
                    }
                    el.removeAttribute(attr.name)
                  })
                })

                clonedTable.querySelectorAll('input, textarea').forEach((el) => {
                  const field = el as HTMLInputElement | HTMLTextAreaElement
                  const span = document.createElement('span')
                  span.textContent = field.value
                  field.parentNode?.replaceChild(span, field)
                })

                clonedTable.querySelectorAll('[role="checkbox"]').forEach((el) => {
                  const checked = el.getAttribute('aria-checked') === 'true' || el.getAttribute('data-state') === 'checked'
                  const span = document.createElement('span')
                  span.textContent = checked ? 'YES' : 'NO'
                  el.parentNode?.replaceChild(span, el)
                })
                
                // Extract text content from badges and buttons, replace with plain text
                clonedTable.querySelectorAll('[class*="Badge"], button').forEach((el) => {
                  const text = el.textContent?.trim() || ''
                  const span = document.createElement('span')
                  span.textContent = text
                  el.parentNode?.replaceChild(span, el)
                })
                
                // Make all header text uppercase
                clonedTable.querySelectorAll('thead th').forEach((th) => {
                  th.textContent = th.textContent?.toUpperCase() || ''
                })
                
                // Ensure NR column is bold and wraps
                clonedTable.querySelectorAll('tbody td:first-child').forEach((td) => {
                  const cell = td as HTMLElement
                  cell.style.fontWeight = 'bold'
                  cell.style.whiteSpace = 'normal'
                })
                
                // Remove fixed widths from table and cells to allow auto-sizing, except SHENIMI column
                clonedTable.style.width = 'auto'
                clonedTable.style.minWidth = 'auto'
                clonedTable.querySelectorAll('th, td').forEach((item) => {
                  const cell = item as HTMLTableCellElement
                  // Keep SHENIMI column (2nd column) with fixed width
                  const isShenimiColumn = cell.cellIndex === 1 // 0-indexed, so 1 is 2nd column
                  if (!isShenimiColumn) {
                    cell.style.width = 'auto'
                    cell.style.minWidth = 'auto'
                  } else {
                    cell.style.width = '300px'
                    cell.style.maxWidth = '300px'
                    cell.style.whiteSpace = 'normal'
                    cell.style.wordWrap = 'break-word'
                  }
                })
                clonedTable.querySelectorAll('colgroup').forEach((col) => col.remove())
                
                printWindow.document.write(`
                  <!DOCTYPE html>
                  <html>
                    <head>
                      <title>GA/KA Notes</title>
                      <style>
                        * { margin: 0; padding: 0; box-sizing: border-box; }
                        @page {
                          margin-top: 0.36in;
                          margin-bottom: 0.51in;
                          margin-left: 0.1in;
                          margin-right: 0.1in;
                          size: landscape;
                        }
                        body { 
                          margin: 0; 
                          padding: 0;
                          font-family: Arial, sans-serif; 
                          font-size: 12px;
                        }
                        .title {
                          font-size: 16px;
                          font-weight: bold;
                          margin-top: 0.3in;
                          margin-bottom: 0.2in;
                          text-align: center;
                        }
                        table { 
                          border-collapse: collapse; 
                          width: auto;
                          margin: 0 auto;
                          margin-top: 0.1in;
                        }
                        thead {
                          display: table-header-group;
                        }
                        tbody {
                          display: table-row-group;
                        }
                        th, td { 
                          border: 1px solid #475569; 
                          padding: 6px 8px; 
                          text-align: left; 
                          vertical-align: bottom;
                          white-space: nowrap;
                        }
                        /* SHENIMI column (2nd column) - set width and wrap */
                        th:nth-child(2), td:nth-child(2) {
                          width: 300px;
                          max-width: 300px;
                          white-space: normal;
                          word-wrap: break-word;
                        }
                        th { 
                          background-color: #D9D9D9; 
                          font-weight: bold; 
                          text-transform: uppercase;
                          /* Thick outside borders for header */
                          border-top: 2px solid #1e293b;
                          border-bottom: 2px solid #1e293b;
                        }
                        thead tr:first-child th:first-child {
                          border-left: 2px solid #1e293b;
                        }
                        thead tr:first-child th:last-child {
                          border-right: 2px solid #1e293b;
                        }
                        td:first-child { 
                          border-left: 2px solid #1e293b; 
                          font-weight: bold;
                          white-space: normal;
                        }
                        td:last-child { 
                          border-right: 2px solid #1e293b; 
                        }
                        /* Thick outside border for table - bottom */
                        tbody tr:last-child td { 
                          border-bottom: 2px solid #1e293b; 
                        }
                        .footer {
                          position: fixed;
                          bottom: 0;
                          width: 100%;
                          display: flex;
                          justify-content: space-between;
                          padding-bottom: 0.2in;
                          font-size: 10px;
                        }
                        .page-number {
                          position: absolute;
                          left: 50%;
                          transform: translateX(-50%);
                        }
                        .user-initials {
                          position: absolute;
                          right: 0.1in;
                        }
                          @media print {
                          .footer {
                            position: running(footer);
                          }
                          @page {
                            @top-right {
                              content: "${dateTimeStr}";
                              font-size: 10px;
                            }
                            @bottom-center {
                              content: "Page " counter(page) " / " counter(pages);
                              font-size: 10px;
                            }
                            @bottom-right {
                              content: "${userInitials}";
                              font-size: 10px;
                            }
                          }
                          body { 
                            margin: 0; 
                            padding: 0;
                          }
                          table { 
                            font-size: 10px;
                            width: auto;
                          }
                          th, td { 
                            padding: 4px 6px;
                          }
                        }
                      </style>
                    </head>
                    <body>
                      <div class="title">GA/KA NOTES</div>
                      ${clonedTable.outerHTML}
                      <div class="footer">
                        <div class="page-number"></div>
                      </div>
                    </body>
                  </html>
                `)
                printWindow.document.close()
                setTimeout(() => {
                  printWindow.print()
                  setTimeout(() => printWindow.close(), 100)
                }, 250)
              }}
            >
              <Printer className="mr-2 h-4 w-4" />
              Print
            </Button>
            <Button
              variant="outline"
              className="h-8 rounded-lg border-slate-300 bg-white px-3 text-sm text-slate-900 shadow-sm hover:bg-slate-50"
              onClick={() => void exportDailyReport()}
            >
              <FileSpreadsheet className="mr-2 h-4 w-4" />
              Export Excel
            </Button>
            <Button
              variant="outline"
              className="h-8 rounded-lg border-slate-300 bg-white px-3 text-sm text-slate-900 shadow-sm hover:bg-slate-50"
              onClick={() => void downloadPxJavReport("docx")}
            >
              <FileText className="mr-2 h-4 w-4" />
              Export Word
            </Button>
            <Button
              variant="outline"
              className="h-8 rounded-lg border-slate-300 bg-white px-3 text-sm text-slate-900 shadow-sm hover:bg-slate-50"
              onClick={() => void downloadPxJavReport("pdf")}
            >
              <FileDown className="mr-2 h-4 w-4" />
              Export PDF
            </Button>
          </div>
          {loading ? (
            <div className="text-sm text-muted-foreground">Loading notes...</div>
          ) : notes.length === 0 ? (
            <div className="text-sm text-muted-foreground">No notes yet.</div>
          ) : (
            <div
              className="notes-table-container rounded-md border-2 border-slate-700 max-h-[75vh] overflow-x-auto overflow-y-auto relative bg-white w-full"
              onScroll={(event) => {
                const container = event.currentTarget
                const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight
                if (distanceFromBottom > 800 || notesRenderLimit >= visibleNotes.length) return
                setNotesRenderLimit((current) => Math.min(current + NOTES_RENDER_BATCH_SIZE, visibleNotes.length))
              }}
            >
              <div className="w-full min-w-[1480px] sm:min-w-[1560px]">
                <table className="w-full table-fixed caption-bottom text-sm min-w-[1480px] sm:min-w-[1560px]">
                  <thead className="sticky top-0 z-50 bg-white shadow-md" style={{ position: 'sticky', top: 0, zIndex: 50 }}>
                    <tr className="bg-white" style={{ borderBottom: '1px solid rgb(51 65 85)' }}>
                      <th className="w-[40px] border border-slate-600 border-l-2 border-l-slate-800 bg-white text-foreground h-10 px-2 text-left align-middle font-medium" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)', whiteSpace: 'normal' }}>NR</th>
                      <th className="min-w-[300px] w-[300px] max-w-[300px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }}>SHENIMI</th>
                      <th className="min-w-[320px] w-[320px] max-w-[320px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }}>PLANIFIKIM</th>
                      <th className="min-w-[180px] w-[180px] max-w-[180px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }}>KOMENT</th>
                      <th className="min-w-[50px] w-[50px] max-w-[50px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }} title="Diskutuar YES/JO?">DISK</th>
                      <th className="min-w-[50px] w-[50px] max-w-[50px] border border-slate-600 bg-white text-foreground h-10 px-1 text-center align-middle font-medium whitespace-normal leading-tight text-xs" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }}>THIS<br />WEEK</th>
                      <th className="w-[96px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }}>DATA,ORA</th>
                      <th className="w-[44px] min-w-[44px] max-w-[44px] border border-slate-600 bg-white text-foreground h-10 px-1 text-center align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }}>NGA</th>
                      <th className="min-w-[70px] w-[70px] max-w-[70px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }}>PER</th>
                      <th className="min-w-[76px] w-[76px] border border-slate-600 bg-white text-foreground h-10 px-1.5 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }} title="Linked task start date">START</th>
                      <th className="w-[90px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }}>KRIJO DET</th>
                      <th className="w-[60px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }}>INT</th>
                      <th className="min-w-[80px] w-[80px] max-w-[80px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }}>MBYLL</th>
                      <th className="min-w-[70px] w-[70px] max-w-[70px] border border-slate-600 border-r-2 border-r-slate-800 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }}>EDIT</th>
                    </tr>
                  </thead>
                  <tbody>
                  {renderedNotes.map((note, idx) => {
                    const creator = note.created_by ? userMap.get(note.created_by) : null
                    const creatorLabel = creator?.full_name || creator?.username || "Unknown user"
                    const creatorInitials = getInitials(creatorLabel)
                    const creatorBadgeClasses =
                      creatorInitials === "GA"
                        ? "bg-rose-100 text-rose-800 border border-rose-200"
                        : creatorInitials === "KA"
                          ? "bg-blue-100 text-blue-800 border border-blue-200"
                          : "bg-slate-200 text-slate-700"
                    const noteDepartment = note.department_id ? departmentMap.get(note.department_id) : null
                    const taskInfo = noteTaskInfo.get(note.id)
                    const taskDepartment = taskInfo?.taskDepartmentId
                      ? departmentMap.get(taskInfo.taskDepartmentId)
                      : null
                    const displayDepartment = noteDepartment || taskDepartment
                    const projectId = note.project_id || taskInfo?.taskProjectId || null
                    const project = projectId ? projectMap.get(projectId) : null
                    const projectDepartment = project?.department_id
                      ? departmentMap.get(project.department_id)
                      : null
                    const isDevProject = isDevelopmentDepartment(projectDepartment)
                    const isDevNote = isDevelopmentDepartment(noteDepartment)
                    const isDevLinked = isDevProject || isDevNote
                    const hasProject = Boolean(projectId)
                    const assignees = taskInfo?.assignees ?? []
                    const attachments = note.attachments ?? []
                    const attachmentCount = note.attachment_count ?? attachments.length
                    const isClosed =
                      note.status === "CLOSED" ||
                      (note as { isClosed?: boolean }).isClosed === true ||
                      (note as { closed?: boolean }).closed === true
                    const createdAt = new Date(note.created_at).getTime()
                    const updatedAt = new Date(note.updated_at).getTime()
                    const isEdited =
                      Number.isFinite(createdAt) &&
                      Number.isFinite(updatedAt) &&
                      updatedAt > createdAt
                    const aggregatedStatus =
                      taskInfo && (taskInfo.taskStatuses?.length ?? 0) > 1
                        ? aggregateTaskStatus(taskInfo.taskStatuses)
                        : normalizeTaskStatus(taskInfo?.taskStatus)
                    const hasTask = Boolean(note.is_converted_to_task || taskInfo?.taskId)
                    const taskTypeLabels = taskInfo?.taskTypeLabels ?? []
                    const canAddAttachments = !isClosed && aggregatedStatus !== "DONE"
                    const editDisabled = isClosed
                    const editDisabledTitle = isClosed
                      ? "Edit disabled when note is closed"
                      : "Edit"
                    const canCreateTask = !isClosed && (!hasProject || isDevLinked)
                    const showManualOnly = hasProject && !isDevLinked
                    const shenimiCellClass = isClosed
                      ? "bg-slate-300 opacity-70"
                      : hasTask
                        ? aggregatedStatus === "TODO"
                          ? "bg-pink-200"
                          : aggregatedStatus === "IN_PROGRESS"
                            ? "bg-yellow-200"
                            : aggregatedStatus === "DONE"
                              ? "bg-emerald-200"
                              : aggregatedStatus === "WAITING_CONFIRMATION"
                                ? "bg-amber-50"
                                : "bg-slate-100"
                        : "bg-sky-200"

                    const mobileDeptAbbrev = displayDepartment ? abbreviateDepartmentName(displayDepartment.name) : null
                    const showMobileDeptBadge =
                      mobileDeptAbbrev === "DEV" || mobileDeptAbbrev === "GDS" || mobileDeptAbbrev === "PCM"
                    const commentValue = note.comment ?? ""
                    const isSavingComment = Boolean(savingCommentIds[note.id])
                    const isSavingNextWeek = Boolean(savingNextWeekIds[note.id])
                    const isSavingPlanning = Boolean(savingPlanningIds[note.id])
                    const planningNames = (ids?: string[], fallback?: string | null) => {
                      const names = (ids || []).map((id) => {
                        const person = users.find((item) => item.id === id)
                        return person?.full_name || person?.username || id
                      })
                      return names.length
                        ? names.join(", ")
                        : fallback !== undefined && fallback !== null
                          ? fallback
                          : "—"
                    }

                    return (
                      <React.Fragment key={note.id}>
                      <tr className="hover:bg-muted/50 border-b transition-colors">
                        <td className="font-bold text-muted-foreground border border-slate-600 border-l-2 border-l-slate-800 p-2 align-middle whitespace-nowrap" style={{ verticalAlign: 'bottom' }}>{idx + 1}</td>
                        <td className={`min-w-[300px] w-[300px] max-w-[300px] whitespace-pre-wrap break-words border border-slate-600 p-2 align-middle ${shenimiCellClass}`} style={{ verticalAlign: 'bottom' }}>
                          <div className="flex flex-col gap-1">
                            <div className="flex items-start justify-between gap-2">
                              <div className="min-w-0 flex-1 flex flex-col gap-1">
                                <div className="flex flex-wrap items-center gap-1">
                                  {showMobileDeptBadge || assignees.length > 0 ? (
                                    <span className="sm:hidden inline-flex items-center gap-1 mr-1">
                                      {showMobileDeptBadge ? (
                                        <Badge className="text-[9px] px-1 py-0 bg-amber-50 text-amber-700 border border-amber-200">
                                          {mobileDeptAbbrev}
                                        </Badge>
                                      ) : null}
                                      {assignees.length > 0 ? (
                                        <span className="inline-flex items-center gap-1">
                                          {assignees.map((assignee, assigneeIdx) => {
                                            const assigneeLabel = assignee.full_name || assignee.username || "Unknown"
                                            const assigneeInitials = getInitials(assigneeLabel)
                                            return (
                                              <span
                                                key={assigneeIdx}
                                                className="flex h-4 w-4 items-center justify-center rounded-full text-[9px] font-semibold bg-slate-200 text-slate-700"
                                                title={assigneeLabel}
                                              >
                                                {assigneeInitials}
                                              </span>
                                            )
                                          })}
                                        </span>
                                      ) : null}
                                    </span>
                                  ) : null}
                                {note.one_h_marker ? (
                                  <button
                                    type="button"
                                    className="inline-flex min-h-6 shrink-0 items-center rounded-md border border-blue-300 bg-blue-50 px-2 text-lg font-black text-red-600 [text-shadow:0_0_0_currentColor]"
                                    title={note.one_h_marker_comment || "Note symbol"}
                                    onClick={() => { if (note.one_h_marker_comment) window.prompt("Symbol comment (copy with Ctrl+C):", note.one_h_marker_comment) }}
                                  >
                                    {oneHMarkerLabel(note.one_h_marker, note.one_h_marker_by_ga)}
                                  </button>
                                ) : null}
                                  <span id={`ga-note-content-${note.id}`} className="min-w-0 text-sm break-words">
                                    {renderMarkedNoteContent(note.content)}
                                  </span>
                                </div>
                                {taskInfo?.description ? (
                                  <div className="border-t border-slate-200/80 pt-1 text-[11px] text-slate-600 line-clamp-4 whitespace-pre-wrap break-words">
                                    {taskInfo.description}
                                  </div>
                                ) : null}
                              </div>
                              <div className="flex items-center justify-end gap-2 flex-wrap">
                                {!editDisabled ? (
                                  <Button
                                    variant="outline"
                                    size="icon"
                                    disabled={markingSelectedNoteId === note.id}
                                    className="h-5 w-5 shrink-0 border-emerald-200 text-emerald-700 hover:bg-emerald-50 disabled:opacity-60"
                                    aria-label="Mark or undo selected note text done"
                                    title="Mark or undo selected text done"
                                    onMouseDown={(event) => event.preventDefault()}
                                    onClick={() => void markSelectedNoteTextDone(note)}
                                  >
                                    <Check className="h-3 w-3" />
                                  </Button>
                                ) : null}
                                {canAddAttachments || attachmentCount > 0 ? (
                                  <Button
                                    variant="outline"
                                    size="icon"
                                    className="h-7 w-7 shrink-0"
                                    title={
                                      canAddAttachments
                                        ? attachmentCount > 0
                                          ? "Manage attachments"
                                          : "Add attachments"
                                        : "View attachments"
                                    }
                                    aria-label={
                                      canAddAttachments
                                        ? attachmentCount > 0
                                          ? "Manage attachments"
                                          : "Add attachments"
                                        : "View attachments"
                                    }
                                    onClick={() => void openAttachmentsForNote(note.id)}
                                  >
                                    {attachmentCount > 0 ? <ImageIcon className="h-4 w-4" /> : <Paperclip className="h-4 w-4" />}
                                  </Button>
                                ) : null}
                                <Button
                                  variant="outline"
                                  size="icon"
                                  disabled={editDisabled}
                                  aria-disabled={editDisabled}
                                  className={`h-7 w-7 shrink-0 ${editDisabled ? "opacity-50 cursor-not-allowed" : ""}`}
                                  aria-label={editDisabledTitle}
                                  title={editDisabledTitle}
                                  onClick={() => !editDisabled && openEditNote(note)}
                                >
                                  <Pencil className="h-4 w-4" />
                                </Button>
                                {hasTask && aggregatedStatus === "WAITING_CONFIRMATION" && note.status !== "CLOSED" ? (
                                  <Button
                                    variant="outline"
                                    size="icon"
                                    disabled={markingDoneNoteId === note.id}
                                    className="h-7 w-7 shrink-0 border-emerald-200 text-emerald-700 hover:bg-emerald-50 disabled:opacity-60"
                                    aria-label="Mark done"
                                    title="Mark done"
                                    onClick={() => void markWaitingTasksDone(note.id)}
                                  >
                                    <Check className="h-4 w-4" />
                                  </Button>
                                ) : null}
                                {!hasTask && canCreateTask ? (
                                  <Button
                                    variant="outline"
                                    size="icon"
                                    className="h-7 w-7 shrink-0"
                                    title="Create task"
                                    aria-label="Create task"
                                    onClick={() => openTaskDialog(note)}
                                  >
                                    <ListTodo className="h-4 w-4" />
                                  </Button>
                                ) : null}
                              </div>
                            </div>
                            <div className="text-[11px] text-slate-600 sm:hidden">
                              {(() => {
                                const parts = formatDateParts(note.created_at)
                                return parts.time ? `${parts.date}, ${parts.time}` : parts.date
                              })()}
                            </div>
                            <div className="flex items-center gap-2">
                              {note.priority ? (
                                <Badge className={`text-[10px] px-1.5 py-0 ${PRIORITY_BADGE[note.priority as Exclude<NotePriority, "NONE">]}`}>
                                  {note.priority}
                                </Badge>
                              ) : null}
                              {hasTask
                                ? taskTypeLabels.map((label) => (
                                    <Badge
                                      key={label}
                                      variant="outline"
                                      className="text-[10px] px-1.5 py-0 bg-cyan-50 text-cyan-800 border-cyan-200 font-semibold"
                                      title="Created task type"
                                    >
                                      {label}
                                    </Badge>
                                  ))
                                : null}
                              {isEdited && !hasTask ? (
                                <Badge
                                  variant="outline"
                                  className="text-[10px] px-1.5 py-0 bg-slate-50 text-slate-600 border-slate-200"
                                  title={`Edited ${(() => {
                                    const parts = formatDateParts(note.updated_at)
                                    return parts.time ? `${parts.date}, ${parts.time}` : parts.date
                                  })()}`}
                                >
                                  Edited
                                </Badge>
                              ) : null}
                              {note.is_discussed ? (
                                <Badge
                                  variant="outline"
                                  className="text-[10px] px-1.5 py-0 bg-emerald-50 text-emerald-700 border-emerald-200"
                                >
                                  Discussed
                                </Badge>
                              ) : null}
                              {isClosed ? (
                                <Badge className="text-[10px] px-1.5 py-0 bg-slate-300 text-slate-700 border border-slate-400">
                                  Closed
                                </Badge>
                              ) : null}
                            </div>
                          </div>
                        </td>
                        <td className="relative min-w-[320px] w-[320px] max-w-[320px] border border-slate-600 p-0.5 align-top">
                          {savingPlanningIds[note.id] ? (
                            <span className="absolute right-1 top-0.5 z-10 text-[9px] font-medium text-violet-600">Duke ruajtur...</span>
                          ) : null}
                          <div className="divide-y overflow-hidden rounded border border-slate-200 bg-white">
                            <div className="grid min-h-6 grid-cols-[64px_minmax(0,1fr)]">
                              <label htmlFor={`planning-dl-${note.id}`} className="bg-slate-50 px-1 py-0.5 text-[10px] font-semibold">DL</label>
                              <Input
                                id={`planning-dl-${note.id}`}
                                value={note.planning_brief?.dl || ""}
                                onFocus={(event) => { event.currentTarget.dataset.previousBrief = JSON.stringify(note.planning_brief ?? null) }}
                                onChange={(event) => updatePlanningBriefDraft(note.id, { dl: event.target.value })}
                                onBlur={(event) => savePlanningInput(note, "dl", event.currentTarget.value, event.currentTarget.dataset.previousBrief ?? "null")}
                                onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur() }}
                                disabled={isClosed || isSavingPlanning}
                                className="h-6 rounded-none border-0 px-1.5 text-[11px] shadow-none focus-visible:ring-1"
                              />
                            </div>
                            <div className="grid min-h-6 grid-cols-[64px_minmax(0,1fr)]">
                              <label className="bg-slate-50 px-1 py-0.5 text-[10px] font-semibold">DG</label>
                              <div className="flex min-w-0 items-center gap-1 p-0.5">
                                <Select
                                  value={typeof note.planning_brief?.dg !== "boolean" ? "__unset__" : note.planning_brief.dg ? "yes" : "no"}
                                  onValueChange={(value) => {
                                    const previousBrief = note.planning_brief ? planningBriefDraft(note.planning_brief) : null
                                    const nextBrief = {
                                      ...planningBriefDraft(note.planning_brief),
                                      dg: value === "__unset__" ? null : value === "yes",
                                      dg_kush: value === "yes" ? note.planning_brief?.dg_kush || "" : "",
                                      dg_kush_user_ids: value === "yes" ? note.planning_brief?.dg_kush_user_ids || [] : [],
                                    }
                                    updatePlanningBriefDraft(note.id, nextBrief)
                                    void savePlanningBrief(note.id, nextBrief, previousBrief)
                                  }}
                                  disabled={isClosed || isSavingPlanning}
                                >
                                  <SelectTrigger className="h-6 w-[82px] shrink-0 px-2 text-[10px]"><SelectValue /></SelectTrigger>
                                  <SelectContent><SelectItem value="__unset__">—</SelectItem><SelectItem value="no">Jo</SelectItem><SelectItem value="yes">Po</SelectItem></SelectContent>
                                </Select>
                                {note.planning_brief?.dg === true ? (
                                  <div className="flex min-w-0 flex-1 items-center gap-1">
                                    <span className="shrink-0 text-[10px] font-semibold text-slate-600">KUSH:</span>
                                    <Input
                                      value={note.planning_brief.dg_kush || planningNames(note.planning_brief.dg_kush_user_ids, "")}
                                      onFocus={(event) => { event.currentTarget.dataset.previousBrief = JSON.stringify(note.planning_brief ?? null) }}
                                      onChange={(event) => updatePlanningBriefDraft(note.id, { dg_kush: event.target.value, dg_kush_user_ids: [] })}
                                      onBlur={(event) => savePlanningInput(note, "dg_kush", event.currentTarget.value, event.currentTarget.dataset.previousBrief ?? "null")}
                                      onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur() }}
                                      placeholder="Shkruaj kush"
                                      aria-label="DG - Nëse po, kush"
                                      disabled={isClosed || isSavingPlanning}
                                      className="h-6 min-w-0 rounded-sm px-2 text-xs"
                                    />
                                  </div>
                                ) : null}
                              </div>
                            </div>
                            <div className="grid min-h-6 grid-cols-[64px_minmax(0,1fr)]">
                              <label htmlFor={`planning-hapat-${note.id}`} className="bg-slate-50 px-1 py-0.5 text-[10px] font-semibold">HAPAT</label>
                              <div className="flex items-center p-0.5">
                                <Select
                                  value={note.planning_brief?.hapat === "Po" ? "yes" : note.planning_brief?.hapat === "Jo" ? "no" : "__unset__"}
                                  onValueChange={(value) => {
                                    const previousBrief = note.planning_brief ? planningBriefDraft(note.planning_brief) : null
                                    const nextBrief = {
                                      ...planningBriefDraft(note.planning_brief),
                                      hapat: value === "yes" ? "Po" : value === "no" ? "Jo" : "",
                                    }
                                    updatePlanningBriefDraft(note.id, nextBrief)
                                    void savePlanningBrief(note.id, nextBrief, previousBrief)
                                  }}
                                  disabled={isClosed || isSavingPlanning}
                                >
                                  <SelectTrigger id={`planning-hapat-${note.id}`} className="h-6 w-[82px] px-2 text-[10px]"><SelectValue /></SelectTrigger>
                                  <SelectContent><SelectItem value="__unset__">—</SelectItem><SelectItem value="no">Jo</SelectItem><SelectItem value="yes">Po</SelectItem></SelectContent>
                                </Select>
                              </div>
                            </div>
                            <div className="grid min-h-6 grid-cols-[64px_minmax(0,1fr)]">
                              <label htmlFor={`planning-kush-${note.id}`} className="bg-slate-50 px-1 py-0.5 text-[10px] font-semibold">KUSH</label>
                              <Input
                                id={`planning-kush-${note.id}`}
                                value={note.planning_brief?.kush || planningNames(note.planning_brief?.kush_user_ids, "")}
                                onFocus={(event) => { event.currentTarget.dataset.previousBrief = JSON.stringify(note.planning_brief ?? null) }}
                                onChange={(event) => updatePlanningBriefDraft(note.id, { kush: event.target.value, kush_user_ids: [] })}
                                onBlur={(event) => savePlanningInput(note, "kush", event.currentTarget.value, event.currentTarget.dataset.previousBrief ?? "null")}
                                onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur() }}
                                disabled={isClosed || isSavingPlanning}
                                className="h-6 rounded-none border-0 px-1.5 text-[11px] shadow-none focus-visible:ring-1"
                              />
                            </div>
                            <div className="grid min-h-6 grid-cols-[64px_minmax(0,1fr)]">
                              <label htmlFor={`planning-sq-${note.id}`} className="bg-slate-50 px-1 py-0.5 text-[10px] font-semibold">SQ</label>
                              <Input
                                id={`planning-sq-${note.id}`}
                                value={note.planning_brief?.sq || ""}
                                onFocus={(event) => { event.currentTarget.dataset.previousBrief = JSON.stringify(note.planning_brief ?? null) }}
                                onChange={(event) => updatePlanningBriefDraft(note.id, { sq: event.target.value })}
                                onBlur={(event) => savePlanningInput(note, "sq", event.currentTarget.value, event.currentTarget.dataset.previousBrief ?? "null")}
                                onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur() }}
                                disabled={isClosed || isSavingPlanning}
                                className="h-6 rounded-none border-0 px-1.5 text-[11px] shadow-none focus-visible:ring-1"
                              />
                            </div>
                            <div className="grid min-h-6 grid-cols-[64px_minmax(0,1fr)]">
                              <label htmlFor={`planning-lloji-det-${note.id}`} className="bg-slate-50 px-1 py-0.5 text-[10px] font-semibold">LLOJI DET</label>
                              <div className="flex items-center p-0.5">
                                <Select
                                  value={note.planning_brief?.lloji_det || "__unset__"}
                                  onValueChange={(value) => {
                                    const previousBrief = note.planning_brief ? planningBriefDraft(note.planning_brief) : null
                                    const nextBrief = {
                                      ...planningBriefDraft(note.planning_brief),
                                      lloji_det: value === "__unset__" ? null : value as "1H" | "P" | "BLLOK" | "R1",
                                    }
                                    updatePlanningBriefDraft(note.id, nextBrief)
                                    void savePlanningBrief(note.id, nextBrief, previousBrief)
                                  }}
                                  disabled={isClosed || isSavingPlanning}
                                >
                                  <SelectTrigger id={`planning-lloji-det-${note.id}`} className="h-6 w-[96px] px-2 text-[10px]"><SelectValue /></SelectTrigger>
                                  <SelectContent>
                                    <SelectItem value="__unset__">—</SelectItem>
                                    <SelectItem value="1H">1H</SelectItem>
                                    <SelectItem value="P">P</SelectItem>
                                    <SelectItem value="BLLOK">BLLOK</SelectItem>
                                    <SelectItem value="R1">R1</SelectItem>
                                  </SelectContent>
                                </Select>
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="border border-slate-600 p-1 align-middle min-w-[180px] w-[180px] max-w-[180px]" style={{ verticalAlign: 'bottom' }}>
                          <Textarea
                            value={commentValue}
                            placeholder="Koment"
                            aria-label="Koment"
                            rows={3}
                            className="min-h-[72px] w-full resize-none rounded-sm border-slate-300 bg-white px-2 py-1.5 text-xs leading-snug whitespace-pre-wrap"
                            disabled={isSavingComment}
                            onFocus={(event) => {
                              event.currentTarget.dataset.previousValue = commentValue
                            }}
                            onChange={(event) => updateNoteCommentDraft(note.id, event.target.value)}
                            onBlur={(event) => {
                              const previousValue = event.currentTarget.dataset.previousValue ?? ""
                              const nextValue = event.currentTarget.value
                              if (nextValue.trim() !== previousValue.trim()) {
                                void saveNoteComment(note.id, nextValue, previousValue)
                              }
                            }}
                            onKeyDown={(event) => {
                              if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                                event.currentTarget.blur()
                              }
                            }}
                          />
                        </td>
                        <td className="border border-slate-600 p-1 align-middle whitespace-nowrap min-w-[50px] w-[50px] max-w-[50px]" style={{ verticalAlign: 'bottom' }}>
                          <div className="flex justify-center">
                            <Button
                              variant="outline"
                              size="sm"
                              className={note.is_discussed
                                ? "h-6 px-2 text-[10px] bg-emerald-600 text-white border-emerald-700 font-semibold hover:bg-emerald-700 hover:text-white"
                                : "h-6 px-2 text-[11px] border-dashed border-slate-300 bg-white text-slate-500 hover:border-emerald-300 hover:bg-emerald-50 hover:text-emerald-700"}
                              aria-pressed={Boolean(note.is_discussed)}
                              title={note.is_discussed ? "Mark as not discussed" : "Mark as discussed"}
                              onClick={() => void toggleNoteDiscussed(note.id, !note.is_discussed)}
                            >
                              YES
                            </Button>
                          </div>
                        </td>
                        <td className="border border-slate-600 p-1 align-middle min-w-[50px] w-[50px] max-w-[50px]" style={{ verticalAlign: 'bottom' }}>
                          <div className="flex justify-center">
                            <Checkbox
                              checked={Boolean(note.next_week)}
                              disabled={isSavingNextWeek}
                              aria-label="Javen tjeter"
                              onCheckedChange={(value) => {
                                void toggleNoteNextWeek(note.id, value === true)
                              }}
                            />
                          </div>
                        </td>
                        <td className="border border-slate-600 p-2 align-middle whitespace-nowrap w-[96px]" style={{ verticalAlign: 'bottom' }}>
                          {(() => {
                            const parts = formatDateParts(note.created_at)
                            return (
                              <div className="leading-tight">
                                <div>{parts.date}</div>
                                {parts.time ? <div>{parts.time}</div> : null}
                              </div>
                            )
                          })()}
                        </td>
                        <td className="w-[44px] min-w-[44px] max-w-[44px] border border-slate-600 p-1 align-middle whitespace-nowrap text-center" style={{ verticalAlign: 'bottom' }}>
                          {creator ? (
                            <div
                              className={`mx-auto flex h-7 w-7 items-center justify-center rounded-full text-[11px] font-bold leading-none ${creatorBadgeClasses}`}
                              title={creatorLabel}
                            >
                              {creatorInitials}
                            </div>
                          ) : (
                            <span className="text-xs text-slate-500">-</span>
                          )}
                        </td>
                        <td className="border border-slate-600 p-2 align-middle whitespace-nowrap min-w-[70px] w-[70px] max-w-[70px]" style={{ verticalAlign: 'bottom' }}>
                          {!note.is_converted_to_task ? (
                            <span className="text-xs text-slate-500">-</span>
                          ) : assignees.length === 0 ? (
                            <span className="text-xs text-slate-500">-</span>
                          ) : (
                            <div className="flex items-center gap-1 flex-wrap">
                              {assignees.map((assignee, assigneeIdx) => {
                                const assigneeLabel = assignee.full_name || assignee.username || "Unknown"
                                const assigneeInitials = getInitials(assigneeLabel)
                                const assigneeBadgeClasses =
                                  assigneeInitials === "GA"
                                    ? "bg-rose-100 text-rose-800 border border-rose-200"
                                    : assigneeInitials === "KA"
                                      ? "bg-blue-100 text-blue-800 border border-blue-200"
                                      : "bg-slate-200 text-slate-700"
                                return (
                                  <div
                                    key={assigneeIdx}
                                    className={`flex h-7 w-7 items-center justify-center rounded-full text-[11px] font-bold leading-none ${assigneeBadgeClasses}`}
                                    title={assigneeLabel}
                                  >
                                    {assigneeInitials}
                                  </div>
                                )
                              })}
                            </div>
                          )}
                        </td>
                        <td className="border border-slate-600 p-1 align-middle w-[76px]" style={{ verticalAlign: 'bottom' }}>
                          {hasTask && taskInfo?.startDate ? (
                            <div className="flex items-center justify-center text-center">
                              <div className="text-[12px] font-bold leading-tight text-slate-900 tabular-nums">
                                {formatCalendarDateDots(taskInfo.startDate)}
                              </div>
                            </div>
                          ) : (
                            <span className="text-xs text-slate-400">—</span>
                          )}
                        </td>
                        <td className="border border-slate-600 p-2 align-middle whitespace-nowrap min-w-[70px] w-[70px] max-w-[70px]" style={{ verticalAlign: 'bottom' }}>
                          <div className="flex justify-center">
                            {hasTask ? (
                              <Badge variant="outline" className="text-xs font-semibold px-2 py-0.5 bg-purple-50 text-purple-800 border-purple-200 h-7 flex items-center text-center">
                                Task Created
                              </Badge>
                            ) : canCreateTask ? (
                              <Button
                                variant="outline"
                                size="sm"
                                className="h-7 text-xs border-indigo-200 text-indigo-700 hover:bg-indigo-50"
                                onClick={() => openTaskDialog(note)}
                              >
                                Create Task
                              </Button>
                            ) : showManualOnly ? (
                              <Badge variant="outline" className="text-[10px] px-1.5 py-0 bg-slate-50 text-slate-600 border-slate-200 h-7 flex items-center">
                                Manual only
                              </Badge>
                            ) : (
                              <Badge variant="outline" className="text-[10px] px-1.5 py-0 bg-slate-50 text-slate-600 border-slate-200 h-7 flex items-center">
                                Closed
                              </Badge>
                            )}
                          </div>
                        </td>
                        <td className="border border-slate-600 p-2 align-middle whitespace-nowrap w-[60px]" style={{ verticalAlign: 'bottom' }}>
                          <div className="flex justify-center">
                            {hasTask ? (
                              <Button
                                variant="outline"
                                size="sm"
                                className="h-7 px-2 text-[10px] border-slate-200 text-slate-700 hover:bg-slate-50"
                                title="Create internal meeting from task"
                                onClick={() => openInternalMeetingFromNoteTask(note, taskInfo)}
                              >
                                INT
                              </Button>
                            ) : (
                              <span className="text-xs text-slate-400">-</span>
                            )}
                          </div>
                        </td>
                        <td className="border border-slate-600 p-2 align-middle whitespace-nowrap min-w-[80px] w-[80px] max-w-[80px]" style={{ verticalAlign: 'bottom' }}>
                          <div className="flex justify-center">
                            {note.status !== "CLOSED" ? (
                              <Button
                                variant="outline"
                                size="sm"
                                disabled={hasTask}
                                aria-disabled={hasTask}
                                title={hasTask ? "Close disabled when task exists" : "Close"}
                                className={`h-7 text-xs border-emerald-200 text-emerald-700 hover:bg-emerald-50 ${hasTask ? "opacity-50 cursor-not-allowed" : ""}`}
                                onClick={() => void closeNote(note.id)}
                              >
                                Close
                              </Button>
                            ) : (
                              <Badge variant="outline" className="text-[10px] px-1.5 py-0 bg-emerald-50 text-emerald-700 border-emerald-200 h-7 flex items-center">
                                Closed
                              </Badge>
                            )}
                          </div>
                        </td>
                        <td className="border border-slate-600 border-r-2 border-r-slate-800 p-2 align-middle whitespace-nowrap" style={{ verticalAlign: 'bottom' }}>
                          <div className="flex justify-center">
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={editDisabled}
                              aria-disabled={editDisabled}
                              title={editDisabledTitle}
                              className={`h-7 text-xs border-slate-200 text-slate-700 hover:bg-slate-50 ${editDisabled ? "opacity-50 cursor-not-allowed" : ""}`}
                              onClick={() => !editDisabled && openEditNote(note)}
                            >
                              Edit
                            </Button>
                          </div>
                        </td>
                      </tr>
                      </React.Fragment>
                    )
                  })}
                </tbody>
              </table>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={attachmentsDialogOpen} onOpenChange={setAttachmentsDialogOpen}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>Manage Attachments</DialogTitle>
          </DialogHeader>
          {attachmentsDialogNote ? (
            <div className="space-y-4">
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Note</div>
                <div className="mt-1 whitespace-pre-wrap break-words text-sm text-slate-700">
                  {renderMarkedNoteContent(attachmentsDialogNote.content)}
                </div>
              </div>
              {attachmentsDialogCanAddFiles ? (
                <div className="space-y-2">
                  <Label>Add files</Label>
                  <Input
                    ref={attachmentUploadInputRef}
                    type="file"
                    multiple
                    onChange={handleAttachmentUploadSelection}
                    disabled={uploadingAttachments}
                  />
                  {attachmentUploadFiles.length === 0 ? (
                    <div className="text-xs text-muted-foreground">
                      No files selected. Max {MAX_ATTACHMENT_FILES} files, {MAX_ATTACHMENT_MB}MB each.
                    </div>
                  ) : (
                    <div className="space-y-2 rounded-md border bg-slate-50 p-2">
                      {attachmentUploadFiles.map((file, idx) => (
                        <div key={`${file.name}-${idx}`} className="flex items-center justify-between gap-2 text-xs">
                          <div className="flex flex-col">
                            <span className="font-medium text-slate-700">{file.name}</span>
                            <span className="text-slate-500">{formatFileSize(file.size)}</span>
                          </div>
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={uploadingAttachments}
                            onClick={() => removeAttachmentUploadFile(idx)}
                          >
                            Remove
                          </Button>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="flex justify-end">
                    <Button
                      type="button"
                      className="gap-2"
                      disabled={attachmentUploadFiles.length === 0 || uploadingAttachments}
                      onClick={() => void uploadAttachmentsFromDialog()}
                    >
                      <Upload className="h-4 w-4" />
                      {uploadingAttachments ? "Uploading..." : "Upload files"}
                    </Button>
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
          {loadingAttachmentsNoteId === attachmentsDialogNoteId ? (
            <div className="text-sm text-slate-500">Loading attachments...</div>
          ) : attachmentDialogItems.length === 0 ? (
            <div className="text-sm text-slate-500">No attachments yet.</div>
          ) : (
            <div className="max-h-[70vh] space-y-3 overflow-y-auto pr-1">
              {attachmentDialogItems.map((item) => {
                const isImage = (item.attachment.content_type || "").startsWith("image/")
                const isDeleting = deletingAttachmentIds.includes(item.attachment.id)
                return (
                  <div key={item.attachment.id} className="rounded-lg border border-slate-200 bg-white p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-slate-800 truncate">
                          {item.attachment.original_filename}
                        </div>
                        <div className="text-xs text-slate-500">
                          {formatFileSize(item.attachment.size_bytes)} • {(() => {
                            const parts = formatDateParts(item.noteCreatedAt)
                            return parts.time ? `${parts.date}, ${parts.time}` : parts.date
                          })()}
                        </div>
                        <div className="mt-2 text-xs text-slate-600 truncate">
                          {item.noteContent}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        {isImage ? (
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-7 text-xs"
                            onClick={() => void openAttachmentPreview(item.attachment)}
                          >
                            View
                          </Button>
                        ) : null}
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-7 text-xs"
                          disabled={isDeleting}
                          onClick={() => void downloadAttachment(item.attachment)}
                        >
                          Download
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-7 gap-1 text-xs text-rose-600 hover:text-rose-700"
                          disabled={isDeleting}
                          onClick={() => void deleteAttachmentFromDialog(item.noteId, item.attachment)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          {isDeleting ? "Deleting..." : "Delete"}
                        </Button>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </DialogContent>
      </Dialog>

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
                onClick={() => void submitInternalMeetingFromNoteTask()}
                className="bg-blue-500 hover:bg-blue-600 text-white border-0 shadow-sm rounded-xl"
              >
                {creatingInternalMeetingFromTask ? "Creating..." : "Create"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(previewUrl)}
        onOpenChange={(open) => {
          if (!open) {
            setPreviewUrl((prev) => {
              if (prev) window.URL.revokeObjectURL(prev)
              return null
            })
            setPreviewTitle(null)
          }
        }}
      >
        <DialogContent className="sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle>{previewTitle || "Attachment preview"}</DialogTitle>
          </DialogHeader>
          {previewUrl ? (
            <div className="flex max-h-[70vh] items-center justify-center overflow-hidden rounded border border-slate-200 bg-white p-2">
              <img src={previewUrl} alt={previewTitle || "Attachment preview"} className="max-h-[66vh] w-auto object-contain" />
            </div>
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(taskDialogNoteId)} onOpenChange={(open) => (!open ? setTaskDialogNoteId(null) : null)}>
        <DialogContent className="flex max-h-[calc(100dvh-2rem)] w-[95vw] flex-col overflow-hidden sm:max-w-3xl">
          <DialogHeader className="shrink-0">
            <DialogTitle>Create Task from Note</DialogTitle>
          </DialogHeader>
          {taskDialogNote ? (
            <>
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain pr-2">
              {taskDialogNote.planning_brief ? (
                <div className="flex items-center justify-between gap-3 rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-sm text-violet-900">
                  <div className="flex min-w-0 items-center gap-2">
                    <span>Ky task do ta marrë automatikisht planifikimin nga PX JAV.</span>
                    {taskDialogNote.planning_brief.lloji_det ? (
                      <Badge variant="outline" className="shrink-0 border-violet-300 bg-white text-violet-800">
                        LLOJI DET: {taskDialogNote.planning_brief.lloji_det}
                      </Badge>
                    ) : null}
                  </div>
                  <Badge variant="outline" className="shrink-0 border-violet-200 bg-white text-violet-700">
                    {planningBriefProgress(taskDialogNote.planning_brief)}/6
                  </Badge>
                </div>
              ) : null}
              <div className="space-y-2">
                <Label>Title</Label>
                <Textarea
                  value={taskTitle}
                  onChange={(e) => setTaskTitle(e.target.value)}
                  className="h-24 min-h-24 max-h-24 resize-none overflow-y-auto [overflow-wrap:anywhere]"
                />
                <TaskTitleLimitHint title={taskTitle} />
              </div>
              <div className="space-y-2">
                <Label>Description</Label>
                <BoldOnlyEditor
                  value={taskDescription}
                  onChange={setTaskDescription}
                  editorClassName="h-32 min-h-32 max-h-32 overflow-y-auto [overflow-wrap:anywhere] text-sm px-2 py-1"
                />
              </div>
              <div className="grid gap-2 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>Priority</Label>
                  <Select 
                    value={taskPriority} 
                    onValueChange={(v) => {
                      // Reset to NORMAL if switching between project/non-project modes and current value is invalid
                      const nextValue = v as TaskTypeOption
                      const isValid = availablePriorityOptions.includes(nextValue)
                      const nextPriority = isValid ? nextValue : "NORMAL"
                      setTaskPriority(nextPriority)
                      if (nextPriority !== "1H") setTaskOneHReportSlot(ONE_H_REPORT_SLOT_NONE_VALUE)
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {availablePriorityOptions.map((value) => (
                        <SelectItem key={value} value={value}>
                          {value}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                {taskPriority === "1H" ? (
                  <div className="space-y-2">
                    <Label>1H slot (optional)</Label>
                    <Select
                      value={taskOneHReportSlot}
                      onValueChange={(value) => {
                        const nextSlot = value as OneHReportSlot | typeof ONE_H_REPORT_SLOT_NONE_VALUE
                        setTaskOneHReportSlot(nextSlot)
                        if (nextSlot !== ONE_H_REPORT_SLOT_NONE_VALUE) {
                          setTaskFinishPeriod(finishPeriodForOneHReportSlot(nextSlot))
                        }
                      }}
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue placeholder="Select slot" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={ONE_H_REPORT_SLOT_NONE_VALUE}>Unassigned</SelectItem>
                        {oneHReportSlotsForPeriod(
                          taskFinishPeriod === FINISH_PERIOD_NONE_VALUE ? null : taskFinishPeriod
                        ).map((value) => (
                          <SelectItem key={value} value={value}>{value}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                ) : null}
                <div className="space-y-2">
                  <Label>Finish by (optional)</Label>
                  <Select
                    value={taskFinishPeriod}
                    onValueChange={(value) => {
                      const nextPeriod = value as TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE
                      setTaskFinishPeriod(nextPeriod)
                      if (nextPeriod !== FINISH_PERIOD_NONE_VALUE && taskOneHReportSlot !== ONE_H_REPORT_SLOT_NONE_VALUE && finishPeriodForOneHReportSlot(taskOneHReportSlot) !== nextPeriod) {
                        setTaskOneHReportSlot(ONE_H_REPORT_SLOT_NONE_VALUE)
                      }
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="None (all day)" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={FINISH_PERIOD_NONE_VALUE}>None (all day)</SelectItem>
                      {FINISH_PERIOD_OPTIONS.map((value) => (
                        <SelectItem key={value} value={value}>
                          {value}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Symbol (optional)</Label>
                  <Select value={taskOneHMarker} onValueChange={(rawValue) => {
                    const value = rawValue as OneHMarker | typeof ONE_H_MARKER_NONE
                    if (value === ONE_H_MARKER_NONE) { setTaskOneHMarker(value); setTaskOneHMarkerComment(""); return }
                    const nextComment = window.prompt("Optional symbol comment:", value === taskOneHMarker ? taskOneHMarkerComment : "")
                    if (nextComment !== null) { setTaskOneHMarker(value); setTaskOneHMarkerComment(nextComment) }
                  }}>
                    <SelectTrigger className={`w-full border-blue-300 bg-blue-50 font-black ${taskOneHMarker === ONE_H_MARKER_NONE ? "text-[#0F2A5F]" : "text-red-600"}`}><SelectValue /></SelectTrigger>
                    <SelectContent className="font-black text-[#0F2A5F]">
                      <SelectItem value={ONE_H_MARKER_NONE}>No symbol</SelectItem>
                      {ONE_H_MARKER_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value} className="font-black text-red-600 focus:text-red-700">{option.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="grid gap-2 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>Start date (optional)</Label>
                  <Input type="date" value={taskStartDate} onChange={(e) => setTaskStartDate(e.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label>Due date (optional)</Label>
                  <Input type="date" value={taskDueDate} onChange={(e) => setTaskDueDate(e.target.value)} />
                </div>
              </div>
              <label className="flex items-center gap-3 rounded-md border px-3 py-2">
                <Checkbox
                  checked={taskDeadlineImportant}
                  onCheckedChange={(checked) => setTaskDeadlineImportant(checked === true)}
                />
                <span className="text-sm font-medium">Deadline important</span>
              </label>
              <label className="flex items-center gap-3 rounded-md border px-3 py-2">
                <Checkbox
                  checked={taskIsRepetitive}
                  onCheckedChange={(checked) => setTaskIsRepetitive(checked === true)}
                  disabled={creatingTask}
                />
                <span className="text-sm font-medium">Detyrë e përsëritur</span>
              </label>
              <div className="grid gap-2 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>Departments</Label>
                  <div className="rounded-md border bg-white p-2">
                    <div className="flex flex-wrap gap-2 mb-2">
                      {taskDepartmentIds.length === 0 ? (
                        <span className="text-xs text-muted-foreground">No departments selected.</span>
                      ) : (
                        taskDepartmentIds.map((id) => {
                          const dept = departments.find((d) => d.id === id)
                          const label = formatDepartmentName(dept?.name) || id
                          return (
                            <button
                              key={id}
                              type="button"
                              className="flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs"
                              onClick={() =>
                                setTaskDepartmentIds((prev) => prev.filter((item) => item !== id))
                              }
                            >
                              {label}
                              <span className="text-slate-500">×</span>
                            </button>
                          )
                        })
                      )}
                    </div>
                    <Select
                      value="__dept_picker__"
                      onValueChange={(value) => {
                        if (value === "__dept_picker__") return
                        setTaskProjectId("NONE")
                        setTaskDepartmentIds((prev) => (prev.includes(value) ? prev : [...prev, value]))
                      }}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Add department" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__dept_picker__" disabled>
                          Add department
                        </SelectItem>
                        {departments
                          .filter((dept) => !taskDepartmentIds.includes(dept.id))
                          .map((dept) => (
                            <SelectItem key={dept.id} value={dept.id}>
                              {formatDepartmentName(dept.name)}
                            </SelectItem>
                          ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div className="space-y-2">
                  <Label>Project (optional)</Label>
                  <Select
                    value={taskProjectId}
                    onValueChange={(value) => setTaskProjectId(value)}
                    disabled={effectiveTaskDepartmentIds.length === 0 && taskProjectOptions.length === 0}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select project" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="NONE">No project</SelectItem>
                      {taskProjectOptions.map((p) => (
                        <SelectItem key={p.id} value={p.id}>
                          {p.title || p.name || "Untitled project"}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {effectiveTaskDepartmentIds.length === 0 ? (
                    <p className="text-xs text-muted-foreground">Choose a department to filter its projects.</p>
                  ) : null}
                </div>
              </div>
              <div className="space-y-2">
                <Label>Assign to</Label>
                <div className="rounded-md border bg-white p-2">
                  <div className="flex flex-wrap gap-2 mb-2">
                    {taskAssigneeIds.length === 0 ? (
                      <span className="text-xs text-muted-foreground">No assignees selected.</span>
                    ) : (
                      taskAssigneeIds.map((id) => {
                        const person = taskAssigneeOptions.find((p) => p.id === id)
                        const label = person?.full_name || person?.username || id
                        return (
                          <button
                            key={id}
                            type="button"
                            className="flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs"
                            onClick={() =>
                              setTaskAssigneeIds((prev) => prev.filter((item) => item !== id))
                            }
                          >
                            {label}
                            {taskAssigneePvBadge(id)}
                            <span className="text-slate-500">×</span>
                          </button>
                        )
                      })
                    )}
                  </div>
                  <Select
                    value="__picker__"
                    onValueChange={(value) => {
                      if (value === "__picker__") return
                      setTaskAssigneeIds((prev) => (prev.includes(value) ? prev : [...prev, value]))
                      const person = users.find((u) => u.id === value)
                      if (person?.department_id) {
                        setTaskDepartmentIds((prev) =>
                          prev.includes(person.department_id as string)
                            ? prev
                            : [...prev, person.department_id as string]
                        )
                      }
                    }}
                    disabled={taskAssigneeOptions.length === 0}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Add assignee" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__picker__" disabled>
                        Add assignee
                      </SelectItem>
                      {taskAssigneeOptions
                        .filter((person) => person.id && !taskAssigneeIds.includes(person.id))
                        .map((person) => (
                          <SelectItem key={person.id} value={person.id}>
                            <span className="inline-flex items-center">{taskAssigneeLabel(person)}{taskAssigneePvBadge(person.id)}</span>
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                </div>
                {taskDepartmentIds.length === 0 ? (
                  <p className="text-xs text-muted-foreground">Select one or more departments to guide projects (optional).</p>
                ) : null}
              </div>
            </div>
              <div className="flex shrink-0 justify-end gap-2 border-t bg-background pt-3">
                <Button variant="outline" onClick={() => setTaskDialogNoteId(null)}>
                  Cancel
                </Button>
                <Button disabled={creatingTask || taskAssigneeIds.length === 0} onClick={() => void createTaskFromNote(taskDialogNote)}>
                  {creatingTask ? "Creating..." : "Create task"}
                </Button>
              </div>
            </>
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(editNoteId)} onOpenChange={(open) => {
        if (!open) {
          setEditNoteId(null)
          setEditDoneRanges([])
          setEditAddedRanges([])
          setEditDescription("")
          setEditTaskDeadline("")
          setEditTaskInitialDeadline("")
          setEditTaskDeadlineImportant(false)
          setEditTaskInitialDeadlineImportant(false)
          setEditPlannedHorizon(PLANNED_HORIZON_NONE)
        }
      }}>
        <DialogContent className="flex max-h-[calc(100dvh-2rem)] flex-col overflow-hidden sm:max-w-3xl">
          <DialogHeader className="shrink-0">
            <DialogTitle>Edit Note</DialogTitle>
          </DialogHeader>
          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain pr-1">
            <div className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Label>Note text</Label>
                <div className="flex flex-wrap items-center gap-2">
                  <Button type="button" variant="outline" size="sm" className="h-8 gap-2" onClick={applyEditNoteBold}>
                    <Bold className="h-4 w-4" />
                    Bold
                  </Button>
                  <Button type="button" variant="outline" size="sm" className="h-8 gap-2" onClick={applyEditNoteBullets}>
                    <List className="h-4 w-4" />
                    Bullets
                  </Button>
                  <Button type="button" variant="outline" size="sm" className="h-8 gap-2" onClick={applyEditNoteNumbers}>
                    <ListOrdered className="h-4 w-4" />
                    Numbers
                  </Button>
                  <Button type="button" variant="outline" size="sm" className="h-8"
                    onMouseDown={(event) => event.preventDefault()} onClick={markSelectedEditTextDone}>
                    Strike / Undo
                  </Button>
                </div>
              </div>
              <Textarea
                ref={editTextareaRef}
                value={editContent}
                onChange={(e) => handleEditContentChange(e.target.value)}
                className="min-h-[180px] max-h-[42vh] resize-y overflow-y-auto text-sm leading-normal"
              />
              <div className="space-y-1">
                <Label className="text-xs text-muted-foreground">Preview</Label>
                <div className="min-h-[120px] max-h-[32vh] overflow-y-auto whitespace-pre-wrap break-words rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm leading-normal">
                  {renderNoteContentWithRanges(editContent, editDoneRanges, editAddedRanges)}
                </div>
              </div>
            </div>
          <div className="max-w-[220px] space-y-2">
            <Label>Symbol (optional)</Label>
            <Select value={editOneHMarker} onValueChange={(rawValue) => {
              const value = rawValue as OneHMarker | typeof ONE_H_MARKER_NONE
              if (value === ONE_H_MARKER_NONE) { setEditOneHMarker(value); setEditOneHMarkerComment(""); return }
              const nextComment = window.prompt("Optional symbol comment:", value === editOneHMarker ? editOneHMarkerComment : "")
              if (nextComment !== null) { setEditOneHMarker(value); setEditOneHMarkerComment(nextComment) }
            }}>
              <SelectTrigger className={`border-blue-300 bg-blue-50 font-black ${editOneHMarker === ONE_H_MARKER_NONE ? "text-[#0F2A5F]" : "text-red-600"}`}><SelectValue /></SelectTrigger>
              <SelectContent className="font-black text-[#0F2A5F]">
                <SelectItem value={ONE_H_MARKER_NONE}>No symbol</SelectItem>
                {ONE_H_MARKER_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value} className="font-black text-red-600 focus:text-red-700">{option.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
            <div className="space-y-2">
              <Label className="text-xs">Planned for (optional)</Label>
              <Select
                value={editPlannedHorizon}
                onValueChange={(value) => setEditPlannedHorizon(value as PlannedHorizonOption)}
                disabled={savingEdit}
              >
                <SelectTrigger className="max-w-[260px]">
                  <SelectValue placeholder="No date" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={PLANNED_HORIZON_NONE}>No date</SelectItem>
                  <SelectItem value="next_week">Next week</SelectItem>
                  <SelectItem value="next_2_weeks">Next 2 weeks</SelectItem>
                  <SelectItem value="next_3_weeks">Next 3 weeks</SelectItem>
                  <SelectItem value="next_4_weeks">Next 4 weeks</SelectItem>
                  <SelectItem value="next_month">Next month</SelectItem>
                  <SelectItem value="next_2_months">Next 2 months</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                Shown in the PLAN column until a linked task has a due date.
              </p>
            </div>
            {editNoteId && noteTaskInfo.get(editNoteId)?.taskId ? (
              <div className="space-y-2">
                <Label>Description</Label>
                <BoldOnlyEditor value={editDescription} onChange={setEditDescription} editorClassName="h-32 min-h-32 max-h-32 overflow-y-auto [overflow-wrap:anywhere]" />
              </div>
            ) : null}
            {editNoteId && noteTaskInfo.get(editNoteId)?.taskId ? (
              <div className="space-y-2 rounded-md border border-slate-200 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Label className="flex items-center gap-1">
                    <CalendarIcon className="h-4 w-4 text-emerald-600" />
                    Deadline
                  </Label>
                  <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    Applies to all assignees
                  </span>
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  <Input
                    type="date"
                    value={editTaskDeadline}
                    onChange={(e) => setEditTaskDeadline(e.target.value)}
                    disabled={savingEdit}
                  />
                  <label className="flex items-center gap-3 rounded-md border px-3 py-2">
                    <Checkbox
                      checked={editTaskDeadlineImportant}
                      onCheckedChange={(checked) =>
                        setEditTaskDeadlineImportant(checked === true)
                      }
                      disabled={savingEdit}
                    />
                    <span className="text-sm font-medium">Deadline important</span>
                  </label>
                </div>
                {editTaskDeadline ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 px-2 text-[11px] border-rose-200 text-rose-700 hover:bg-rose-50"
                    disabled={savingEdit}
                    onClick={() => {
                      setEditTaskDeadline("")
                      setEditTaskDeadlineImportant(false)
                    }}
                  >
                    Clear deadline
                  </Button>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    No deadline set. Pick a date above to add one for every assignee.
                  </p>
                )}
              </div>
            ) : null}
            {editNoteId && noteTaskInfo.get(editNoteId)?.taskId ? (
              <label className="flex items-center gap-3 rounded-md border px-3 py-2">
                <Checkbox
                  checked={editTaskIsRepetitive}
                  onCheckedChange={(checked) => setEditTaskIsRepetitive(checked === true)}
                  disabled={savingEdit}
                />
                <span className="text-sm font-medium">Detyrë e përsëritur</span>
              </label>
            ) : null}
          </div>
            <div className="flex shrink-0 justify-end gap-2 border-t bg-background pt-3">
              <Button variant="outline" onClick={() => {
                setEditNoteId(null)
                setEditDoneRanges([])
                setEditAddedRanges([])
                setEditDescription("")
                setEditTaskDeadline("")
                setEditTaskInitialDeadline("")
                setEditTaskDeadlineImportant(false)
                setEditTaskInitialDeadlineImportant(false)
              }}>
                Cancel
              </Button>
              <Button onClick={() => void saveEditNote()} disabled={savingEdit}>
                {savingEdit ? "Saving..." : "Save changes"}
              </Button>
            </div>

        </DialogContent>
      </Dialog>
    </div>
  )
}
