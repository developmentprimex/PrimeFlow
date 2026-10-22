"use client"

import * as React from "react"
import { flushSync } from "react-dom"
import { useVisibleRefresh } from "@/lib/use-visible-refresh"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { Bold, Calendar as CalendarIcon, Check, ChevronDown, ChevronUp, Clock, Cloud, Image as ImageIcon, List, ListOrdered, ListTodo, Paperclip, Pencil, Printer, Mic, Square, Trash2, Upload } from "lucide-react"
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
import { TaskSkillField } from "@/components/task-skill-field"
import { TaskMarkerComment } from "@/components/task-marker-comment"
import { TeamMarkerCommentsButton } from "@/components/team-marker-comments-button"
import { KNOWLEDGE_CONFIG, knowledgeText } from "@/components/knowledge/knowledge-config"
import { PromptLinkButton, promptHrefFromText } from "@/components/knowledge/prompt-link"
import { useConfirm } from "@/components/providers/confirm-dialog-provider"
import { useAuth } from "@/lib/auth"
import { formatDepartmentName } from "@/lib/department-name"
import { resolveProjectTitle } from "@/lib/project-display-title"
import { fetchUsersLookupCached } from "@/lib/users-cache"
import { getConfirmerCandidates, isWaitingConfirmation, validateWaitingConfirmation } from "@/lib/task-confirmation"
import { inferSkillCategory, SKILL_CATEGORIES } from "@/lib/skills"
import { useCloudDictation } from "@/lib/useCloudDictation"
import { useSpeechDictation } from "@/lib/useSpeechDictation"
import { useVoiceAssistant } from "@/lib/useVoiceAssistant"
import { createNotesVoiceController, reconcileSavedNoteDraft, type NotesVoiceAdapter, type NotesVoiceState } from "@/lib/px-notes-voice"
import { PxNotesMiraControls } from "@/components/px-notes-mira-controls"
import type { Department, GaNote, GaNoteAttachment, PlanNote, Project, SkillCategory, SkillCategoryInference, Task, TaskAssignee, TaskFinishPeriod, TaskPriority, UserLookup } from "@/lib/types"

function isKnowledgeNote(note: GaNote | null | undefined) {
  return Boolean(note?.knowledge_type && KNOWLEDGE_CONFIG[note.knowledge_type])
}

function noteKnowledgeText(note: GaNote | null | undefined, text: string) {
  return knowledgeText(note?.knowledge_type || "PROMPT", text)
}

type NoteType = "GA" | "KA"
type NotePriority = "NORMAL" | "HIGH" | "NONE"
type OneHMarker = "EXCLAMATION" | "QUESTION" | "KA" | "GENT" | "FLAG" | "F" | "BZ1N1" | "M2" | "M3" | "M2_M3" | "MONITOR" | "CLOSE" | "CLIENT_URGENT" | "SHARE"
type OneHMarkerFilter = "all" | "with" | "none" | OneHMarker
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
const EMAIL_MARKER_RE = /(^|\s)em:/i
const DONE_MARK_START = "[[done]]"
const DONE_MARK_END = "[[/done]]"
const ADDED_MARK_START = "[[added]]"
const ADDED_MARK_END = "[[/added]]"
const NOTE_MARK_TOKEN_RE = /\[\[(done|added)\]\]|\[\[\/(done|added)\]\]/g
const STRIKE_TIMESTAMP_RE = /^ \d{2}:\d{2} \d{2}\.\d{2}(?=$|\s)/

function shouldPreferCloudDictation(): boolean {
  if (typeof navigator === "undefined") return false

  const userAgent = navigator.userAgent
  const isIOSDevice =
    /iPad|iPhone|iPod/i.test(userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
  const isSafari =
    /Safari/i.test(userAgent) &&
    !/Chrome|Chromium|CriOS|FxiOS|EdgiOS|OPiOS|Android/i.test(userAgent)

  return isIOSDevice || isSafari
}

type NormalizedTaskStatus = "TODO" | "IN_PROGRESS" | "WAITING_CLIENT" | "WAITING_CONFIRMATION" | "DONE" | "UNKNOWN"
type TaskStatusFilter = "all" | "notes" | "tasks" | "open" | "closed" | NormalizedTaskStatus
type ContentFilter = "all" | "emails"
type TextMarkRange = { start: number; end: number }
type DoneMarkRange = TextMarkRange
type ParsedMarkedNoteContent = {
  text: string
  doneRanges: TextMarkRange[]
  addedRanges: TextMarkRange[]
}
type GaAssigneeTaskStatus = "TODO" | "IN_PROGRESS" | "WAITING_CLIENT" | "WAITING_CONFIRMATION" | "DONE"
type GaAssigneeTaskType = "NORMAL" | "HIGH" | "1H" | "R1" | "PERSONAL" | "BLLOK"
type GaNotesTableNote = GaNote & { source?: "GA_KA" | "PX_JAV" }
type GaAssigneeTaskState = {
  taskId: string | null
  type: GaAssigneeTaskType
  status: GaAssigneeTaskStatus
  confirmationAssigneeId: string
  startDate: string
  dueDate: string
  finishPeriod: TaskFinishPeriod | null
  oneHReportSlot: OneHReportSlot | null
  oneHMarker: OneHMarker | null
  isDeadlineImportant: boolean
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
  taskCreatedAt?: string | null
  taskUpdatedAt?: string | null
  assigneeStates: Record<string, GaAssigneeTaskState>
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

function taskDateKey(value?: string | null) {
  if (!value) return null
  if (/^\d{4}-\d{2}-\d{2}/.test(value)) return value.slice(0, 10)
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return toISODate(date)
}

function oneHReportSlotsForPeriod(period?: TaskFinishPeriod | null) {
  return period ? ONE_H_REPORT_SLOTS_BY_PERIOD[period] : ONE_H_REPORT_SLOT_OPTIONS
}

function finishPeriodForOneHReportSlot(slot: OneHReportSlot): TaskFinishPeriod {
  return ONE_H_REPORT_SLOTS_BY_PERIOD.AM.includes(slot) ? "AM" : "PM"
}

function createEmptyGaAssigneeTaskState(): GaAssigneeTaskState {
  return {
    taskId: null,
    type: "NORMAL",
    status: "TODO",
    confirmationAssigneeId: "",
    startDate: "",
    dueDate: "",
    finishPeriod: null,
    oneHReportSlot: null,
    oneHMarker: null,
    isDeadlineImportant: false,
  }
}

function sameStringSet(left: string[], right: string[]) {
  if (left.length !== right.length) return false
  const rightValues = new Set(right)
  return left.every((value) => rightValues.has(value))
}

function sameGaAssigneeTaskState(
  left: GaAssigneeTaskState,
  right: GaAssigneeTaskState
) {
  return (
    left.type === right.type &&
    left.status === right.status &&
    (isWaitingConfirmation(left.status) ? left.confirmationAssigneeId : "") ===
      (isWaitingConfirmation(right.status) ? right.confirmationAssigneeId : "") &&
    left.startDate === right.startDate &&
    left.dueDate === right.dueDate &&
    left.finishPeriod === right.finishPeriod &&
    left.oneHReportSlot === right.oneHReportSlot &&
    left.oneHMarker === right.oneHMarker &&
    left.isDeadlineImportant === right.isDeadlineImportant
  )
}

function serializeGaAssigneeTaskState(
  assigneeId: string,
  state: GaAssigneeTaskState
) {
  return {
    assignee_id: assigneeId,
    status: state.status,
    confirmation_assignee_id: isWaitingConfirmation(state.status) ? state.confirmationAssigneeId : null,
    priority: state.type === "HIGH" ? "HIGH" : "NORMAL",
    is_bllok: state.type === "BLLOK",
    is_1h_report: state.type === "1H",
    is_r1: state.type === "R1",
    is_personal: state.type === "PERSONAL",
    start_date: state.startDate ? new Date(state.startDate).toISOString() : null,
    due_date: state.dueDate ? new Date(state.dueDate).toISOString() : null,
    finish_period: state.finishPeriod,
    one_h_report_slot: state.oneHReportSlot,
    one_h_marker: state.oneHMarker,
    is_deadline_important: state.isDeadlineImportant,
  }
}

function gaAssigneeTaskType(task: Task): GaAssigneeTaskType {
  if (task.is_bllok) return "BLLOK"
  if (task.is_1h_report) return "1H"
  if (task.is_r1) return "R1"
  if (task.is_personal) return "PERSONAL"
  if (task.priority === "HIGH") return "HIGH"
  return "NORMAL"
}

function parseMarkedNoteContent(content?: string | null): ParsedMarkedNoteContent {
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
    // Older notes can have a closing marker on its own line:
    // `4. Item\n[[/done]]\n5. Item`. Removing the marker must not leave
    // an empty line, otherwise the browser restarts the ordered list at 1.
    if (closingMark && text.endsWith("\n") && content[lastIndex] === "\n") {
      lastIndex += 1
    }
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

function formatStrikeTimestamp(now = new Date()) {
  return `${pad2(now.getHours())}:${pad2(now.getMinutes())} ${pad2(now.getDate())}.${pad2(now.getMonth() + 1)}`
}

function toggleDoneRangeWithTimestamp(
  text: string,
  ranges: DoneMarkRange[],
  selectedRange: DoneMarkRange,
  timestamp = formatStrikeTimestamp()
) {
  const normalizedRanges = normalizeDoneRanges(ranges)
  const removesExistingStrike = normalizedRanges.some(
    (range) => selectedRange.start < range.end && selectedRange.end > range.start
  )
  let nextText = text
  let nextRanges = toggleDoneRange(normalizedRanges, selectedRange)

  if (!removesExistingStrike) {
    const stamp = ` ${timestamp}`
    nextText = `${text.slice(0, selectedRange.end)}${stamp}${text.slice(selectedRange.end)}`
    return {
      text: nextText,
      doneRanges: adjustTextRangesForTextChange(text, nextText, nextRanges),
    }
  }

  // A timestamp belongs to a fully un-struck range only. This keeps partial
  // un-strikes from removing the completion time for text that remains done.
  const completedRangesToClear = normalizedRanges
    .filter((range) => selectedRange.start <= range.start && selectedRange.end >= range.end)
    .sort((left, right) => right.end - left.end)

  for (const range of completedRangesToClear) {
    const stampMatch = nextText.slice(range.end).match(STRIKE_TIMESTAMP_RE)
    if (!stampMatch) continue
    const nextValue = `${nextText.slice(0, range.end)}${nextText.slice(range.end + stampMatch[0].length)}`
    nextRanges = adjustTextRangesForTextChange(nextText, nextValue, nextRanges)
    nextText = nextValue
  }

  return { text: nextText, doneRanges: nextRanges }
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

function getNumberedListProgress(text: string, doneRanges: TextMarkRange[]) {
  const normalizedDoneRanges = normalizeTextRanges(doneRanges)
  let completed = 0
  let total = 0
  let lineStart = 0

  for (const line of text.split("\n")) {
    const orderedMatch = line.match(/^\s*\d+\.\s+/)
    if (orderedMatch) {
      const itemStart = lineStart + orderedMatch[0].length
      const itemEnd = lineStart + line.length
      const meaningfulPositions: number[] = []

      for (let position = itemStart; position < itemEnd; position += 1) {
        const character = text[position]
        if (!/\s/.test(character) && character !== "*") {
          meaningfulPositions.push(position)
        }
      }

      if (meaningfulPositions.length > 0) {
        total += 1
        const isCompleted = meaningfulPositions.every((position) =>
          normalizedDoneRanges.some((range) => range.start <= position && range.end > position)
        )
        if (isCompleted) completed += 1
      }
    }

    lineStart += line.length + 1
  }

  return total > 0 ? { completed, total } : null
}

function synchronizeNumberedListProgress(parsed: ParsedMarkedNoteContent): ParsedMarkedNoteContent {
  const progress = getNumberedListProgress(parsed.text, parsed.doneRanges)
  if (!progress) return parsed

  const lines = parsed.text.split("\n")
  const titleLineIndex = lines.findIndex((line) => line.trim() && !/^\s*\d+\.\s+/.test(line))
  if (titleLineIndex === -1) return parsed

  const titleLine = lines[titleLineIndex]
  const titleMatch = titleLine.match(
    /^(\s*(?:[A-Za-zÀ-ž]{1,5}(?:\s*\/\s*[A-Za-zÀ-ž]{1,5})?\s*:\s*)+)(?:([A-Za-zÀ-ž0-9][A-Za-zÀ-ž0-9/_-]{0,11}\s*-\s*))?(?:(\d{1,3}(?:\s*\/\s*\d{1,3})?)(?=\s+|$|\/))?/
  )
  if (!titleMatch) return parsed

  const progressLabel = progress.completed > 0 ? `${progress.completed}/${progress.total}` : String(progress.total)
  const initialsPrefix = titleMatch[1]
  const codePrefix = titleMatch[2] || ""
  const progressStart = initialsPrefix.length + codePrefix.length
  let progressEnd = titleMatch[0].length
  const slashParts = titleLine.slice(progressStart).match(
    /^\d{1,3}(?:\s*\/\s*[A-Za-zÀ-ž0-9_-]+)+/
  )

  if (slashParts) {
    const separators = Array.from(slashParts[0].matchAll(/\s*\/\s*/g))
    const firstValue = Number.parseInt(slashParts[0], 10)
    const hasManualSuffix = separators.length >= 2 || firstValue === progress.total || progress.completed === 0

    if (hasManualSuffix) {
      // The last slash part is entered manually. Keep it intact while replacing
      // only the leading automatic progress: `68/20` stays `68/20`, then becomes
      // `1/68/20` after the first checklist point is struck. A plain automatic
      // progress such as `1/68` continues to be replaced as one complete value.
      const automaticPartCount = separators.length >= 2 ? 2 : 1
      progressEnd = progressStart + (
        automaticPartCount === 2 ? separators[1].index : separators[0].index
      )
    }
  }

  let titleSuffix = titleLine.slice(progressEnd).trimStart()
  let manualProgressSuffix = ""
  const manualSuffixMatch = titleSuffix.match(/^(\/\s*[A-Za-zÀ-ž0-9_-]+)(?:\s+|$)/)
  if (manualSuffixMatch) {
    manualProgressSuffix = manualSuffixMatch[1]
    titleSuffix = titleSuffix.slice(manualSuffixMatch[0].length).trimStart()
  }

  const remainingTitle = [codePrefix.trim(), titleSuffix].filter(Boolean).join(" ")
  const nextTitleLine = `${initialsPrefix}${progressLabel}${manualProgressSuffix}${remainingTitle ? ` ${remainingTitle}` : ""}`
  if (nextTitleLine === titleLine) return parsed

  lines[titleLineIndex] = nextTitleLine
  const nextText = lines.join("\n")

  return {
    text: nextText,
    doneRanges: adjustTextRangesForTextChange(parsed.text, nextText, parsed.doneRanges),
    addedRanges: adjustTextRangesForTextChange(parsed.text, nextText, parsed.addedRanges),
  }
}

function parseMarkedNoteContentWithProgress(content?: string | null) {
  return synchronizeNumberedListProgress(parseMarkedNoteContent(content))
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

function renderMarkedNoteContent(content?: string | null, showStrikeTimestamps = false) {
  if (!content) return "-"
  const parsed = parseMarkedNoteContentWithProgress(content)
  return renderNoteContentWithRanges(parsed.text, parsed.doneRanges, parsed.addedRanges, showStrikeTimestamps)
}

// Mira notes start with their date and title, then a blank line before the notes.
function miraNoteTitle(content?: string | null) {
  const text = content ? parseMarkedNoteContentWithProgress(content).text.trim() : ""
  return text.split(/\n\s*\n/)[0].trim() || "Shënim nga Mira"
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

function renderInlineMarkedSegments(
  segments: MarkedSegment[],
  keyPrefix: string,
  showStrikeTimestamps = false
) {
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
    const timestampMatch = !run.isDone && runs[index - 1]?.isDone
      ? run.text.match(STRIKE_TIMESTAMP_RE)
      : null
    if (timestampMatch) {
      return (
        <React.Fragment key={`${keyPrefix}-run-${index}`}>
          {showStrikeTimestamps ? <span className="text-slate-400">{timestampMatch[0]}</span> : null}
          {run.text.slice(timestampMatch[0].length)}
        </React.Fragment>
      )
    }
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

function renderNoteContentWithRanges(
  content: string,
  doneRanges: TextMarkRange[],
  addedRanges: TextMarkRange[] = [],
  showStrikeTimestamps = false
) {
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
          <li key={`note-bullet-${index}`} data-note-line-index={index}>
            {renderInlineMarkedSegments(
              trimLinePrefix(itemSegments, match[0].length),
              `note-bullet-${index}`,
              showStrikeTimestamps
            )}
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
          <li key={`note-ordered-${index}`} data-note-line-index={index}>
            {renderInlineMarkedSegments(
              trimLinePrefix(itemSegments, match[0].length),
              `note-ordered-${index}`,
              showStrikeTimestamps
            )}
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
      <div key={`note-line-${index}`} data-note-line-index={index} className={lineText ? "" : "min-h-[1.25rem]"}>
        {lineText ? renderInlineMarkedSegments(lineSegments, `note-line-${index}`, showStrikeTimestamps) : "\u00A0"}
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

function completeLineRange(value: string, selectionStart: number, selectionEnd: number): TextMarkRange | null {
  const start = value.lastIndexOf("\n", Math.max(0, selectionStart - 1)) + 1
  const lastSelectedCharacter = Math.max(selectionStart, selectionEnd - 1)
  const lastSelectedLineStart = value.lastIndexOf("\n", Math.max(0, lastSelectedCharacter - 1)) + 1
  if (lastSelectedLineStart !== start) return null
  const endOfSelectedLine = value.indexOf("\n", lastSelectedCharacter)
  const end = endOfSelectedLine === -1 ? value.length : endOfSelectedLine
  const selectedText = value.slice(start, end)
  return selectedText.trim() ? { start, end } : null
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
  if (Number.isNaN(date.getTime())) return { date: "-", time: "" }
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

function getEditedTimestamp(updatedAt?: string | null, createdAt?: string | null) {
  const updated = updatedAt ? new Date(updatedAt).getTime() : Number.NaN
  const created = createdAt ? new Date(createdAt).getTime() : Number.NaN

  if (!Number.isFinite(updated) || !Number.isFinite(created) || updated <= created) {
    return null
  }

  return updated
}

function getLastEditedValue(note: GaNote, taskInfo?: NoteTaskInfo | null) {
  const noteUpdated = getEditedTimestamp(note.updated_at, note.created_at)
  const taskUpdated = getEditedTimestamp(taskInfo?.taskUpdatedAt, taskInfo?.taskCreatedAt)

  if (taskUpdated !== null && (noteUpdated === null || taskUpdated > noteUpdated)) {
    return taskInfo?.taskUpdatedAt ?? null
  }

  return noteUpdated !== null ? note.updated_at : null
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

function formatApiDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === "string") return item
        if (item && typeof item === "object" && "msg" in item) {
          return String((item as { msg?: unknown }).msg || "")
        }
        return ""
      })
      .map((part) => part.trim())
      .filter(Boolean)
    if (parts.length) return parts.join("; ")
  }
  return fallback
}

function capitalizeNoteFirstLetter(text: string): string {
  return text.replace(/^([^\p{L}\r\n]*)(\p{L})/u, (_, prefix: string, letter: string) =>
    `${prefix}${letter.toUpperCase()}`
  )
}

function normalizeNoteTextareaInput(textarea: HTMLTextAreaElement): string {
  const previous = textarea.value
  const normalized = capitalizeNoteFirstLetter(previous)
  if (previous === normalized) return normalized

  const { prefixLength, previousChangeEnd, nextChangeEnd } = getTextChangeBounds(previous, normalized)
  const mapPosition = (position: number) => {
    if (position <= prefixLength) return position
    if (position >= previousChangeEnd) return position + nextChangeEnd - previousChangeEnd
    return nextChangeEnd
  }
  const start = mapPosition(textarea.selectionStart)
  const end = mapPosition(textarea.selectionEnd)
  const direction = textarea.selectionDirection
  const scrollTop = textarea.scrollTop
  const scrollLeft = textarea.scrollLeft

  // Keep the DOM value in sync before React updates the controlled field.
  // Replacing it during the render would move the caret to the end.
  textarea.value = normalized
  textarea.setSelectionRange(start, end, direction)
  textarea.scrollTop = scrollTop
  textarea.scrollLeft = scrollLeft
  return normalized
}

function noteToTaskTitle(content: string) {
  const cleaned = content
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .split("\n")
    .map((line) => line.trim().replace(/[ \t\f\v]+/g, " "))
    .filter(Boolean)
    .join("\n")
  if (!cleaned) return "GA/KA note task"
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

function isGraphicDesignDepartment(dept?: Department | null) {
  if (!dept) return false
  const name = (dept.name || "").trim().toUpperCase()
  const code = (dept.code || "").trim().toUpperCase()
  return name === "GRAPHIC DESIGN" || code === "GD" || code === "GDS"
}

const GA_NOTE_TEMPLATE_EMAIL = "ga@primexeu.com"
// Note text goes on line 1; the template starts on line 4.
const GA_NOTE_TEMPLATE = "\n\n\nDL:\nAM/PM:\nLL:\nSIMBOLI:"

export default function PxNotesWorkspace({ editorNote, onEditorClose, onEditorSaved, embeddedEditor = false }: {
  editorNote?: GaNote & { source?: "GA_KA" | "PX_JAV" }
  onEditorClose?: () => void
  onEditorSaved?: () => void
  embeddedEditor?: boolean
} = {}) {
  const { user, apiFetch } = useAuth()
  const canViewStrikeTimestamps = user?.role === "ADMIN"
  const confirm = useConfirm()
  const searchParams = useSearchParams()
  const router = useRouter()
  // Deep link from Knowledge PX > Prompts: open this page's task dialog for a note,
  // then return to the calling page once the task is created or the dialog is closed.
  const taskForNoteId = searchParams.get("taskFor")
  const taskReturnTo = React.useMemo(() => {
    const value = searchParams.get("returnTo")
    return value && value.startsWith("/") && !value.startsWith("//") ? value : null
  }, [searchParams])
  // Opened from the iPhone home screen icon: skip the banner so the note box is first.
  const quickMode = searchParams.get("quick") === "1"
  const deepLinkTaskStateRef = React.useRef<"idle" | "open" | "done">("idle")
  const [notes, setNotes] = React.useState<GaNotesTableNote[]>(() => editorNote ? [editorNote] : [])
  const notesRef = React.useRef<GaNotesTableNote[]>([])
  notesRef.current = notes
  const noteOriginsKey = React.useMemo(
    () => notes.map((note) => `${note.source || "GA_KA"}:${note.id}`).join("|"),
    [notes]
  )
  const [departments, setDepartments] = React.useState<Department[]>([])
  const [projects, setProjects] = React.useState<Project[]>([])
  const [users, setUsers] = React.useState<UserLookup[]>([])
  const usersRef = React.useRef<UserLookup[]>([])
  usersRef.current = users
  const confirmerCandidates = React.useMemo(() => getConfirmerCandidates(users), [users])

  // Initialize from URL parameters if present
  const urlDepartmentId = searchParams.get("department_id")
  const urlProjectId = searchParams.get("project_id")
  const [departmentId, setDepartmentId] = React.useState(urlDepartmentId || "ALL")
  const [projectId, setProjectId] = React.useState(urlProjectId || "NONE")
  const [content, setContentState] = React.useState("")
  const setContent = React.useCallback((value: React.SetStateAction<string>) => {
    setContentState((previous) => capitalizeNoteFirstLetter(
      typeof value === "function" ? value(previous) : value
    ))
  }, [])
  const isGaUser = user?.email?.trim().toLowerCase() === GA_NOTE_TEMPLATE_EMAIL
  const defaultNoteContent = isGaUser ? GA_NOTE_TEMPLATE : ""
  const [noteOneHMarker, setNoteOneHMarker] = React.useState<OneHMarker | typeof ONE_H_MARKER_NONE>(ONE_H_MARKER_NONE)
  const [noteOneHMarkerComment, setNoteOneHMarkerComment] = React.useState("")
  const [noteType] = React.useState<NoteType>("GA")
  const [priority] = React.useState<NotePriority>("NONE")
  const [loading, setLoading] = React.useState(false)
  const notesRequestIdRef = React.useRef(0)
  const notesRequestInFlightRef = React.useRef(false)
  const [posting, setPosting] = React.useState(false)
  const [selectedFiles, setSelectedFiles] = React.useState<File[]>([])
  const fileInputRef = React.useRef<HTMLInputElement | null>(null)
  const [attachmentUploadFiles, setAttachmentUploadFiles] = React.useState<File[]>([])
  const attachmentUploadInputRef = React.useRef<HTMLInputElement | null>(null)
  const [uploadingAttachments, setUploadingAttachments] = React.useState(false)
  const [deletingAttachmentIds, setDeletingAttachmentIds] = React.useState<string[]>([])
  const [taskDialogNoteId, setTaskDialogNoteId] = React.useState<string | null>(null)
  const [creatingTask, setCreatingTask] = React.useState(false)
  const creatingTaskRef = React.useRef(false)
  const [rangeFilter, setRangeFilter] = React.useState<"week" | "all">("all")
  const [taskStatusFilter, setTaskStatusFilter] = React.useState<TaskStatusFilter>("all")
  const [contentFilter, setContentFilter] = React.useState<ContentFilter>("all")
  const [oneHMarkerFilter, setOneHMarkerFilter] = React.useState<OneHMarkerFilter>("all")
  const [searchQuery, setSearchQuery] = React.useState("")
  const deferredSearchQuery = React.useDeferredValue(searchQuery)
  const [notesRenderLimit, setNotesRenderLimit] = React.useState(INITIAL_NOTES_RENDER_LIMIT)
  const [exportingDailyReport, setExportingDailyReport] = React.useState(false)
  const [showLegend, setShowLegend] = React.useState(false)
  const [taskTitle, setTaskTitle] = React.useState("")
  const [taskDescription, setTaskDescription] = React.useState("")
  const [taskPriority, setTaskPriority] = React.useState<TaskTypeOption>("NORMAL")
  const [taskFinishPeriod, setTaskFinishPeriod] = React.useState<TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE>(
    FINISH_PERIOD_NONE_VALUE
  )
  const [taskOneHReportSlot, setTaskOneHReportSlot] = React.useState<OneHReportSlot | typeof ONE_H_REPORT_SLOT_NONE_VALUE>(
    ONE_H_REPORT_SLOT_NONE_VALUE
  )
  const [taskOneHMarker, setTaskOneHMarker] = React.useState<OneHMarker | typeof ONE_H_MARKER_NONE>(ONE_H_MARKER_NONE)
  const [taskOneHMarkerComment, setTaskOneHMarkerComment] = React.useState("")
  const [taskDueDate, setTaskDueDate] = React.useState("")
  const [taskStartDate, setTaskStartDate] = React.useState("")
  const [taskDeadlineImportant, setTaskDeadlineImportant] = React.useState(false)
  const [taskAssigneeIds, setTaskAssigneeIds] = React.useState<string[]>([])
  // Knowledge PX prompt notes: who tests the prompt ("PROMPT: TESTO: ..." task).
  const [taskPromptTesterId, setTaskPromptTesterId] = React.useState("")
  const [taskDepartmentIds, setTaskDepartmentIds] = React.useState<string[]>([])
  const [taskProjectId, setTaskProjectId] = React.useState("NONE")
  const [taskSkillCategory, setTaskSkillCategory] = React.useState<SkillCategory | null>(null)
  const [taskSkillAutoSuggested, setTaskSkillAutoSuggested] = React.useState(false)
  const [taskSkillAiReason, setTaskSkillAiReason] = React.useState("")
  const [taskSkillAiLoading, setTaskSkillAiLoading] = React.useState(false)
  const skillInferenceRequestRef = React.useRef(0)
  const [taskDateLeaveItems, setTaskDateLeaveItems] = React.useState<CommonLeaveItem[]>([])
  const [noteTaskInfo, setNoteTaskInfo] = React.useState<Map<string, NoteTaskInfo>>(new Map())
  const [editNoteId, setEditNoteId] = React.useState<string | null>(null)
  const [loadingEditNote, setLoadingEditNote] = React.useState(false)
  const [editorLookupsReady, setEditorLookupsReady] = React.useState(false)
  const editorStartedRef = React.useRef(false)
  const editorOpenedRef = React.useRef(false)
  const [editContent, setEditContent] = React.useState("")
  const [editNoteOneHMarker, setEditNoteOneHMarker] = React.useState<OneHMarker | typeof ONE_H_MARKER_NONE>(ONE_H_MARKER_NONE)
  const [editNoteOneHMarkerComment, setEditNoteOneHMarkerComment] = React.useState("")
  const [editDoneRanges, setEditDoneRanges] = React.useState<DoneMarkRange[]>([])
  const [editAddedRanges, setEditAddedRanges] = React.useState<TextMarkRange[]>([])
  const [editDescription, setEditDescription] = React.useState("")
  const [editTaskProjectId, setEditTaskProjectId] = React.useState("NONE")
  const [editTaskAssigneeIds, setEditTaskAssigneeIds] = React.useState<string[]>([])
  const [editTaskAssigneeStates, setEditTaskAssigneeStates] = React.useState<Record<string, GaAssigneeTaskState>>({})
  const [savingEdit, setSavingEdit] = React.useState(false)
  const [markingDoneNoteId, setMarkingDoneNoteId] = React.useState<string | null>(null)
  const [markingSelectedNoteId, setMarkingSelectedNoteId] = React.useState<string | null>(null)
  const [expandedMiraNoteIds, setExpandedMiraNoteIds] = React.useState<Set<string>>(() => new Set())
  const toggleMiraNote = React.useCallback((noteId: string) => {
    setExpandedMiraNoteIds((current) => {
      const next = new Set(current)
      if (!next.delete(noteId)) next.add(noteId)
      return next
    })
  }, [])
  const contentTextareaRef = React.useRef<HTMLTextAreaElement | null>(null)
  const editTextareaRef = React.useRef<HTMLTextAreaElement | null>(null)

  React.useEffect(() => {
    if (!defaultNoteContent) return
    setContent((prev) => (prev ? prev : defaultNoteContent))
  }, [defaultNoteContent, setContent])

  React.useEffect(() => {
    if (!defaultNoteContent || content !== defaultNoteContent) return
    const textarea = contentTextareaRef.current
    if (textarea && document.activeElement === textarea) {
      textarea.setSelectionRange(0, 0)
    }
  }, [content, defaultNoteContent])
  const editNoteVersionRef = React.useRef<string | null>(null)
  const editContentLatestRef = React.useRef("")
  const editDictationSelectionRef = React.useRef({ start: 0, end: 0 })
  const bindEditTextarea = React.useCallback((textarea: HTMLTextAreaElement | null) => {
    editTextareaRef.current = textarea
    if (textarea) {
      const cursor = editDictationSelectionRef.current
      textarea.setSelectionRange(cursor.start, cursor.end)
    }
  }, [])
  const [attachmentsDialogOpen, setAttachmentsDialogOpen] = React.useState(false)
  const [attachmentsDialogNoteId, setAttachmentsDialogNoteId] = React.useState<string | null>(null)
  const [previewUrl, setPreviewUrl] = React.useState<string | null>(null)
  const [previewTitle, setPreviewTitle] = React.useState<string | null>(null)
  const [previewContentType, setPreviewContentType] = React.useState<string | null>(null)
  const [previewAttachment, setPreviewAttachment] = React.useState<GaNoteAttachment | null>(null)

  const [internalMeetingTaskDialogOpen, setInternalMeetingTaskDialogOpen] = React.useState(false)
  const [internalMeetingTaskTitle, setInternalMeetingTaskTitle] = React.useState("")
  const [internalMeetingTaskPlatform, setInternalMeetingTaskPlatform] = React.useState("")
  const [internalMeetingTaskStartsAt, setInternalMeetingTaskStartsAt] = React.useState("")
  const [creatingInternalMeetingFromTask, setCreatingInternalMeetingFromTask] = React.useState(false)
  const internalMeetingDepartmentIdRef = React.useRef<string | null>(null)
  const [voiceLanguage, setVoiceLanguage] = React.useState<"en" | "sq">("sq")
  const [preferCloudDictation, setPreferCloudDictation] = React.useState(false)
  const speechLang = voiceLanguage === "sq" ? "sq-AL" : "en-US"
  const cloudLang = voiceLanguage === "sq" ? "sq" : "en"

  React.useEffect(() => {
    setPreferCloudDictation(shouldPreferCloudDictation())
  }, [])

  const insertEditDictationAtCursor = React.useCallback((spokenText: string) => {
    const transcript = spokenText.trim()
    if (!transcript) return

    const current = editContentLatestRef.current
    const selection = editDictationSelectionRef.current
    const start = Math.max(0, Math.min(selection.start, current.length))
    const end = Math.max(start, Math.min(selection.end, current.length))
    const before = current.slice(0, start)
    const after = current.slice(end)
    const leadingSpace = before.length > 0 && !/\s$/.test(before) ? " " : ""
    const trailingSpace = after.length > 0 && !/^\s|^[,.;:!?]/.test(after) ? " " : ""
    const insertedText = `${leadingSpace}${transcript}${trailingSpace}`
    const insertedContent = `${before}${insertedText}${after}`
    const next = capitalizeNoteFirstLetter(insertedContent)
    const nextCursor = start + insertedText.length - trailingSpace.length + next.length - insertedContent.length

    setEditDoneRanges((ranges) => adjustTextRangesForTextChange(current, next, ranges))
    setEditAddedRanges((ranges) => addInsertedTextRange(current, next, ranges))
    editContentLatestRef.current = next
    editDictationSelectionRef.current = { start: nextCursor, end: nextCursor }
    setEditContent(next)

    window.setTimeout(() => {
      const textarea = editTextareaRef.current
      if (!textarea) return
      textarea.focus()
      textarea.setSelectionRange(nextCursor, nextCursor)
    }, 0)
  }, [])

  const {
    isSupported: isVoiceSupported,
    isListening: isVoiceListening,
    interimText: voiceInterimText,
    stop: stopVoice,
    toggle: toggleVoice,
  } = useSpeechDictation({
    lang: speechLang,
    onFinalText: (text) => {
      const finalText = text.trim()
      if (!finalText) return
      setContent((prev) => {
        const base = prev ?? ""
        const needsSeparator = base.length > 0 && !/\s$/.test(base)
        const separator = needsSeparator ? "\n" : ""
        return `${base}${separator}${finalText}`
      })
    },
  })

  const {
    isSupported: isCloudSupported,
    isRecording: isCloudRecording,
    isTranscribing: isCloudTranscribing,
    stop: stopCloud,
    toggle: toggleCloud,
  } = useCloudDictation({
    apiFetch,
    lang: cloudLang,
    onFinalText: (text) => {
      const finalText = text.trim()
      if (!finalText) return
      setContent((prev) => {
        const base = prev ?? ""
        const needsSeparator = base.length > 0 && !/\s$/.test(base)
        const separator = needsSeparator ? "\n" : ""
        return `${base}${separator}${finalText}`
      })
    },
  })

  const voiceMode =
    preferCloudDictation && isCloudSupported
      ? "cloud"
      : isVoiceSupported
        ? "browser"
        : isCloudSupported
          ? "cloud"
          : "none"

  const {
    isSupported: isEditVoiceSupported,
    isListening: isEditVoiceListening,
    interimText: editVoiceInterimText,
    stop: stopEditVoice,
    toggle: toggleEditVoice,
  } = useSpeechDictation({
    lang: speechLang,
    onFinalText: insertEditDictationAtCursor,
  })

  const {
    isSupported: isEditCloudSupported,
    isRecording: isEditCloudRecording,
    isTranscribing: isEditCloudTranscribing,
    stop: stopEditCloud,
    toggle: toggleEditCloud,
  } = useCloudDictation({
    apiFetch,
    lang: cloudLang,
    onFinalText: insertEditDictationAtCursor,
  })

  const editVoiceMode =
    preferCloudDictation && isEditCloudSupported
      ? "cloud"
      : isEditVoiceSupported
        ? "browser"
        : isEditCloudSupported
          ? "cloud"
          : "none"

  React.useEffect(() => {
    if (posting && isVoiceListening) stopVoice()
    if (posting && isCloudRecording) stopCloud()
  }, [isCloudRecording, isVoiceListening, posting, stopCloud, stopVoice])

  React.useEffect(() => {
    if (voiceMode === "browser" && isCloudRecording) stopCloud()
    if (voiceMode === "cloud" && isVoiceListening) stopVoice()
  }, [isCloudRecording, isVoiceListening, stopCloud, stopVoice, voiceMode])

  const handleVoiceToggle = () => {
    stopMira()
    if (voiceMode === "browser") {
      toggleVoice()
      return
    }
    if (voiceMode === "cloud") {
      toggleCloud()
      return
    }
    toast.error("Voice dictation not supported in this browser")
  }

  const handleEditVoiceToggle = () => {
    stopMira()
    const textarea = editTextareaRef.current
    if (textarea) {
      editDictationSelectionRef.current = {
        start: textarea.selectionStart ?? editContentLatestRef.current.length,
        end: textarea.selectionEnd ?? textarea.selectionStart ?? editContentLatestRef.current.length,
      }
    }
    if (isVoiceListening) stopVoice()
    if (isCloudRecording) stopCloud()
    if (editVoiceMode === "browser") {
      toggleEditVoice()
      return
    }
    if (editVoiceMode === "cloud") {
      toggleEditCloud()
      return
    }
    toast.error("Voice dictation not supported in this browser")
  }

  React.useEffect(() => {
    if (!editNoteId || savingEdit) {
      if (isEditVoiceListening) stopEditVoice()
      if (isEditCloudRecording) stopEditCloud()
    }
  }, [editNoteId, isEditCloudRecording, isEditVoiceListening, savingEdit, stopEditCloud, stopEditVoice])


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



  const fetchNotes = React.useCallback(async ({ silent = false }: { silent?: boolean } = {}) => {
    if (editorNote || !user?.id) return false
    // Polling/focus refreshes are best-effort. If another notes request is
    // already running, keep the current table and let that request finish.
    if (silent && notesRequestInFlightRef.current) return false

    const requestId = ++notesRequestIdRef.current
    notesRequestInFlightRef.current = true
    if (!silent) setLoading(true)
    try {
      let gaUrl = "/ga-notes"
      let planUrl = "/plan-notes"
      const params = new URLSearchParams()
      if (projectId !== "NONE") {
        params.set("project_id", projectId)
      } else if (departmentId !== "ALL") {
        params.set("department_id", departmentId)
      }
      const query = params.toString() ? `?${params}` : ""
      gaUrl += query
      planUrl += query
      const [gaRes, planRes] = await Promise.all([apiFetch(gaUrl), apiFetch(planUrl)])
      if (gaRes?.ok && planRes?.ok) {
        const gaNotes = (await gaRes.json()) as GaNote[]
        const planNotes = (await planRes.json()) as PlanNote[]
        const combined: GaNotesTableNote[] = [
          ...gaNotes.map((note) => ({ ...note, source: "GA_KA" as const })),
          ...planNotes
            .filter((note) => note.is_converted_to_task)
            .map((note) => ({
              ...note,
              source: "PX_JAV" as const,
              attachments: [],
            })),
        ]
        if (requestId === notesRequestIdRef.current) setNotes(combined)
        return true
      } else {
        if (!silent) toast.error("Could not load GA/KA and PX JAV notes")
        return false
      }
    } finally {
      if (requestId === notesRequestIdRef.current) {
        notesRequestInFlightRef.current = false
        if (!silent) setLoading(false)
      }
    }
  }, [apiFetch, departmentId, projectId, user?.id, editorNote])

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
    void loadUsers().catch(() => toast.error("Could not load users")).finally(() => setEditorLookupsReady(true))
  }, [loadUsers])

  React.useEffect(() => {
    void loadProjects()
  }, [loadProjects])

  React.useEffect(() => {
    void fetchNotes()
  }, [fetchNotes])

  const loadNoteTasks = React.useCallback(async (noteIdsOverride?: string[]) => {
    const currentNotes = notesRef.current
    const selectedNotes = noteIdsOverride
      ? currentNotes.filter((note) => noteIdsOverride.includes(note.id))
      : currentNotes
    const gaNoteIds = selectedNotes.filter((note) => note.source !== "PX_JAV").map((note) => note.id)
    const planNoteIds = selectedNotes.filter((note) => note.source === "PX_JAV").map((note) => note.id)
    const noteIds = [...gaNoteIds, ...planNoteIds]
    if (!noteIds.length) {
      if (!noteIdsOverride) {
        setNoteTaskInfo(new Map())
      }
      return
    }
    const taskRequests: Promise<Response>[] = []
    if (gaNoteIds.length) {
      taskRequests.push(
        apiFetch("/tasks/by-ga-notes/summary", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ga_note_origin_ids: gaNoteIds,
            include_done: true,
            include_all_done: true,
          }),
        })
      )
    }
    if (planNoteIds.length) {
      taskRequests.push(
        apiFetch("/tasks/by-ga-notes/summary", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ga_note_origin_ids: [],
            plan_note_origin_ids: planNoteIds,
            include_done: true,
            include_all_done: false,
          }),
        })
      )
    }
    const taskResponses = await Promise.all(taskRequests)
    if (taskResponses.some((response) => !response.ok)) return
    const data = (
      await Promise.all(taskResponses.map(async (response) => (await response.json()) as Task[]))
    ).flat()

    const map = new Map<string, NoteTaskInfo>()
    const userMapById = new Map(usersRef.current.map((person) => [person.id, person]))
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
      const sourceNoteId = t.ga_note_origin_id || t.plan_note_origin_id
      if (!sourceNoteId) continue
      let assignees: TaskAssignee[] = []
      if (t.assigned_to) {
        const explicitOwner = t.assignees?.find((assignee) => assignee.id === t.assigned_to)
        const owner = userMapById.get(t.assigned_to)
        assignees = explicitOwner
          ? [explicitOwner]
          : [{
              id: t.assigned_to,
              email: null,
              username: owner?.username ?? null,
              full_name: owner?.full_name ?? null,
              department_id: owner?.department_id ?? null,
            }]
      }
      const existing = map.get(sourceNoteId)
      const normalizedStatus = normalizeTaskStatus(t.status)
      const assigneeState: Record<string, GaAssigneeTaskState> = t.assigned_to
        ? {
            [t.assigned_to]: {
              taskId: t.id,
              type: gaAssigneeTaskType(t),
              status: normalizedStatus === "IN_PROGRESS" || normalizedStatus === "WAITING_CLIENT" || normalizedStatus === "WAITING_CONFIRMATION" || normalizedStatus === "DONE"
                ? normalizedStatus
                : "TODO",
              confirmationAssigneeId: t.confirmation_assignee_id || "",
              startDate: taskDateKey(t.start_date) || "",
              dueDate: taskDateKey(t.due_date) || "",
              finishPeriod: t.finish_period === "AM" || t.finish_period === "PM" ? t.finish_period : null,
              oneHReportSlot: ONE_H_REPORT_SLOT_OPTIONS.includes(t.one_h_report_slot as OneHReportSlot)
                ? t.one_h_report_slot as OneHReportSlot
                : null,
              oneHMarker: (t.one_h_marker as OneHMarker | null) || null,
              isDeadlineImportant: Boolean(t.is_deadline_important),
            },
          }
        : {}
      map.set(sourceNoteId, {
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
        taskCreatedAt: existing?.taskCreatedAt ?? t.created_at,
        taskUpdatedAt:
          existing?.taskUpdatedAt && new Date(existing.taskUpdatedAt).getTime() > new Date(t.updated_at).getTime()
            ? existing.taskUpdatedAt
            : t.updated_at,
        assigneeStates: {
          ...(existing?.assigneeStates ?? {}),
          ...assigneeState,
        },
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
    return map
  }, [apiFetch])

  useVisibleRefresh(async () => {
    await fetchNotes({ silent: true })
    await loadNoteTasks()
  }, !editorNote && !editNoteId && !savingEdit)

  // Load tasks linked to notes to show assignees/descriptions
  React.useEffect(() => {
    if (!editorNote) void loadNoteTasks()
  }, [loadNoteTasks, noteOriginsKey, editorNote])



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
    (note: GaNote, taskInfo?: NoteTaskInfo | null) => {
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
    let res = await apiFetch(`/ga-notes/${encodedNoteId}/attachments`, {
      method: "POST",
      body: buildFormData(false),
    })

    if (res?.status === 404) {
      res = await apiFetch("/ga-notes/attachments", {
        method: "POST",
        body: buildFormData(true),
      })
    }

    if (!res?.ok) {
      const errorText = await res.text()
      throw new Error(errorText || "upload_failed")
    }
    return (await res.json()) as GaNoteAttachment[]
  }

  const mergeNoteAttachments = React.useCallback((noteId: string, attachments: GaNoteAttachment[]) => {
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
        return { ...note, attachments: merged }
      })
    )
  }, [])

  const removeNoteAttachment = React.useCallback((noteId: string, attachmentId: string) => {
    setNotes((prev) =>
      prev.map((note) =>
        note.id === noteId
          ? { ...note, attachments: (note.attachments ?? []).filter((attachment) => attachment.id !== attachmentId) }
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

  const downloadAttachment = async (attachment: GaNoteAttachment) => {
    try {
      const res = await apiFetch(`/ga-notes/attachments/${attachment.id}`)
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

  const openAttachmentPreview = async (attachment: GaNoteAttachment) => {
    try {
      const res = await apiFetch(`/ga-notes/attachments/${attachment.id}/preview`)
      if (!res?.ok) {
        toast.error("Failed to open file")
        return
      }
      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      setPreviewTitle(attachment.original_filename || "Attachment preview")
      setPreviewContentType(blob.type || attachment.content_type || "application/octet-stream")
      setPreviewAttachment(attachment)
      setPreviewUrl((prev) => {
        if (prev) window.URL.revokeObjectURL(prev)
        return url
      })
    } catch {
      toast.error("Failed to open file")
    }
  }

  const deleteAttachmentFromDialog = async (noteId: string, attachment: GaNoteAttachment) => {
    const confirmed = await confirm({
      title: "Delete attachment",
      description: `Delete "${attachment.original_filename}"?`,
      confirmLabel: "Delete",
      variant: "destructive",
    })
    if (!confirmed) return

    setDeletingAttachmentIds((prev) => (prev.includes(attachment.id) ? prev : [...prev, attachment.id]))
    try {
      const res = await apiFetch(`/ga-notes/attachments/${attachment.id}`, {
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

  const handleVoiceLanguageChange = (value: string) => {
    if (value !== "en" && value !== "sq") return
    if (value === voiceLanguage) return
    if (isVoiceListening) stopVoice()
    if (isCloudRecording) stopCloud()
    if (isEditVoiceListening) stopEditVoice()
    if (isEditCloudRecording) stopEditCloud()
    setVoiceLanguage(value)
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
    if (!content.trim() || (defaultNoteContent && content.trim() === defaultNoteContent.trim())) {
      toast.error("Content is required")
      return
    }
    const contentWithProgress = synchronizeNumberedListProgress({
      text: capitalizeNoteFirstLetter(content.trim()),
      doneRanges: [],
      addedRanges: [],
    }).text
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
      const res = await apiFetch("/ga-notes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: contentWithProgress,
          note_type: noteType,
          priority: priority === "NONE" ? null : priority,
          department_id: finalDepartmentId,
          project_id: finalProjectId,
          one_h_marker: noteOneHMarker === ONE_H_MARKER_NONE ? null : noteOneHMarker,
          one_h_marker_comment: noteOneHMarker === ONE_H_MARKER_NONE ? null : noteOneHMarkerComment.trim() || null,
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
      const created = (await res.json()) as GaNote
      setNotes((prev) => [created, ...prev])
      flushSync(() => setContent((latest) => latest === content ? defaultNoteContent : latest))
      if (contentTextareaRef.current?.value === defaultNoteContent) {
        contentTextareaRef.current.setSelectionRange(0, 0)
      }
      setNoteOneHMarker(ONE_H_MARKER_NONE)
      setNoteOneHMarkerComment("")
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
      return created
    } finally {
      setPosting(false)
    }
  }

  const updateEditNoteMarker = (value: OneHMarker | typeof ONE_H_MARKER_NONE) => {
    if (value !== ONE_H_MARKER_NONE) {
      const nextComment = window.prompt("Optional symbol comment:", value === editNoteOneHMarker ? editNoteOneHMarkerComment : "")
      if (nextComment === null) return
      setEditNoteOneHMarkerComment(nextComment)
    } else {
      setEditNoteOneHMarkerComment("")
    }
    setEditNoteOneHMarker(value)
    const marker = value === ONE_H_MARKER_NONE ? null : value
    setEditTaskAssigneeStates((current) => Object.fromEntries(
      Object.entries(current).map(([id, state]) => [id, { ...state, oneHMarker: marker }])
    ))
  }

  const updateEditTaskAssigneeState = (
    assigneeId: string,
    patch: Partial<GaAssigneeTaskState>
  ) => {
    setEditTaskAssigneeStates((current) => ({
      ...current,
      [assigneeId]: {
        ...(current[assigneeId] ?? createEmptyGaAssigneeTaskState()),
        ...patch,
      },
    }))
  }

  const openEditNote = React.useCallback(async (note: GaNote) => {
    if (loadingEditNote) return
    setLoadingEditNote(true)
    try {
      const freshTaskInfo = await loadNoteTasks([note.id])
      if (!freshTaskInfo) {
        toast.error("Failed to load the latest task changes. Please try again.")
        return false
      }
      const parsedContent = parseMarkedNoteContentWithProgress(note.content)
      const normalizedText = capitalizeNoteFirstLetter(parsedContent.text)
      const doneRanges = adjustTextRangesForTextChange(parsedContent.text, normalizedText, parsedContent.doneRanges)
      const addedRanges = adjustTextRangesForTextChange(parsedContent.text, normalizedText, parsedContent.addedRanges)
      editNoteVersionRef.current = note.updated_at || null
      setEditNoteId(note.id)
      editContentLatestRef.current = normalizedText
      editDictationSelectionRef.current = {
        start: normalizedText.length,
        end: normalizedText.length,
      }
      setEditContent(normalizedText)
      setEditNoteOneHMarker(note.one_h_marker ?? ONE_H_MARKER_NONE)
      setEditNoteOneHMarkerComment(note.one_h_marker_comment || "")
      setEditDoneRanges(doneRanges)
      setEditAddedRanges(addedRanges)
      const taskInfo = freshTaskInfo.get(note.id)
      setEditDescription(taskInfo?.description || "")
      setEditTaskProjectId(taskInfo?.taskProjectId ?? note.project_id ?? "NONE")
      setEditTaskAssigneeStates(taskInfo?.assigneeStates ?? {})
      setEditTaskAssigneeIds(
        Array.from(new Set((taskInfo?.assignees ?? []).map((assignee) => assignee.id).filter(Boolean)))
      )
      return true
    } catch {
      toast.error("Failed to load the latest task changes. Please try again.")
      return false
    } finally {
      setLoadingEditNote(false)
    }
  }, [loadingEditNote, loadNoteTasks])

  React.useEffect(() => {
    if (!editorNote || !editorLookupsReady || editorStartedRef.current) return
    editorStartedRef.current = true
    void openEditNote(editorNote).then((opened) => { if (!opened) onEditorClose?.() })
  }, [editorNote, editorLookupsReady, openEditNote, onEditorClose])

  React.useEffect(() => {
    if (!editorNote) return
    if (editNoteId) editorOpenedRef.current = true
    else if (editorOpenedRef.current) onEditorClose?.()
  }, [editorNote, editNoteId, onEditorClose])

  React.useEffect(() => {
    if (embeddedEditor && editNoteId) editTextareaRef.current?.focus({ preventScroll: true })
  }, [embeddedEditor, editNoteId])

  const handleEditContentChange = (nextContent: string) => {
    const normalizedContent = capitalizeNoteFirstLetter(nextContent)
    setEditDoneRanges((current) => adjustTextRangesForTextChange(editContent, normalizedContent, current))
    setEditAddedRanges((current) => addInsertedTextRange(editContent, normalizedContent, current))
    editContentLatestRef.current = normalizedContent
    setEditContent(normalizedContent)
  }

  const rememberEditDictationCursor = React.useCallback((textarea: HTMLTextAreaElement) => {
    editDictationSelectionRef.current = {
      start: textarea.selectionStart ?? textarea.value.length,
      end: textarea.selectionEnd ?? textarea.selectionStart ?? textarea.value.length,
    }
  }, [])

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
  }, [applyTextEditToTextarea, content, setContent])

  const applyNewNoteBullets = React.useCallback(() => {
    applyTextEditToTextarea(contentTextareaRef.current, content, setContent, (value, selectionStart, selectionEnd) =>
      prefixSelectedLines(value, selectionStart, selectionEnd, () => "• ")
    )
  }, [applyTextEditToTextarea, content, setContent])

  const applyNewNoteNumbers = React.useCallback(() => {
    applyTextEditToTextarea(contentTextareaRef.current, content, setContent, (value, selectionStart, selectionEnd) =>
      prefixSelectedLines(value, selectionStart, selectionEnd, (lineIndex) => `${lineIndex + 1}. `)
    )
  }, [applyTextEditToTextarea, content, setContent])

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

    const value = textarea.value
    const textareaScrollTop = textarea.scrollTop
    const textareaScrollLeft = textarea.scrollLeft
    const dialogScroller = textarea.parentElement?.closest<HTMLElement>(".overflow-y-auto") ?? null
    const dialogScrollTop = dialogScroller?.scrollTop
    let start = textarea.selectionStart
    let end = textarea.selectionEnd
    const selectionDirection = textarea.selectionDirection

    const lineRange = completeLineRange(value, start, end)
    if (!lineRange) {
      toast.error("Select the text or place cursor on the line to mark done")
      return
    }
    start = lineRange.start
    end = lineRange.end

    const nextContent = toggleDoneRangeWithTimestamp(editContent, editDoneRanges, { start, end })
    editContentLatestRef.current = nextContent.text
    setEditContent(nextContent.text)
    setEditDoneRanges(nextContent.doneRanges)
    setEditAddedRanges((current) => adjustTextRangesForTextChange(editContent, nextContent.text, current))
    window.setTimeout(() => {
      textarea.focus({ preventScroll: true })
      textarea.setSelectionRange(start, end, selectionDirection)
      textarea.scrollTop = textareaScrollTop
      textarea.scrollLeft = textareaScrollLeft
      if (dialogScroller && dialogScrollTop !== undefined) {
        dialogScroller.scrollTop = dialogScrollTop
      }
    }, 0)
  }

  const getNoteSelectionRange = (noteId: string) => {
    const container = document.getElementById(`ga-note-content-${noteId}`)
    const selection = window.getSelection()
    if (!container || !selection || selection.rangeCount === 0 || selection.isCollapsed) return null

    const range = selection.getRangeAt(0)
    const containsNode = (node: Node) => node === container || container.contains(node)
    if (!containsNode(range.startContainer) || !containsNode(range.endContainer)) return null

    const lineElement = (node: Node) => {
      const element = node.nodeType === Node.ELEMENT_NODE ? node as Element : node.parentElement
      return element?.closest<HTMLElement>("[data-note-line-index]") ?? null
    }
    const startLine = lineElement(range.startContainer)
    const endLine = lineElement(range.endContainer)
    if (startLine && endLine && startLine.dataset.noteLineIndex === endLine.dataset.noteLineIndex) {
      const lineIndex = Number(startLine.dataset.noteLineIndex)
      if (Number.isInteger(lineIndex) && lineIndex >= 0) {
        const parsed = parseMarkedNoteContentWithProgress(notes.find((note) => note.id === noteId)?.content)
        const lines = parsed.text.split("\n")
        const start = lines.slice(0, lineIndex).reduce((total, line) => total + line.length + 1, 0)
        const end = start + (lines[lineIndex]?.length ?? 0)
        if (parsed.text.slice(start, end).trim()) return { start, end }
      }
    }

    const beforeSelection = range.cloneRange()
    beforeSelection.selectNodeContents(container)
    beforeSelection.setEnd(range.startContainer, range.startOffset)

    const start = beforeSelection.toString().length
    const end = start + range.toString().length
    return completeLineRange(
      parseMarkedNoteContentWithProgress(notes.find((note) => note.id === noteId)?.content).text,
      start,
      end
    )
  }

  const markSelectedNoteTextDone = async (note: GaNote) => {
    const parsedContent = parseMarkedNoteContentWithProgress(note.content)
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

    const toggledContent = toggleDoneRangeWithTimestamp(
      parsedContent.text,
      parsedContent.doneRanges,
      selectionRange
    )
    const nextContent = synchronizeNumberedListProgress({
      text: toggledContent.text,
      doneRanges: toggledContent.doneRanges,
      addedRanges: adjustTextRangesForTextChange(
        parsedContent.text,
        toggledContent.text,
        parsedContent.addedRanges
      ),
    })

    setMarkingSelectedNoteId(note.id)
    try {
      const source = notes.find((item) => item.id === note.id)?.source
      const res = await apiFetch(`/${source === "PX_JAV" ? "plan-notes" : "ga-notes"}/${note.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: serializeMarkedNoteContent(
            nextContent.text,
            nextContent.doneRanges,
            nextContent.addedRanges
          ).trim(),
        }),
      })
      if (!res?.ok) {
        toast.error("Failed to mark selected text done")
        return
      }
      const updated = (await res.json()) as GaNote
      setNotes((prev) =>
        prev.map((n) => (n.id === updated.id ? { ...updated, source: n.source } : n))
      )
    } catch (error) {
      console.error("Failed to mark selected note text done:", error)
      toast.error("Failed to mark selected text done")
    } finally {
      setMarkingSelectedNoteId(null)
    }
  }

  const saveEditNote = async (keepOpen = false) => {
    if (!editNoteId) return
    const trimmed = editContent.trim()
    if (!trimmed) {
      toast.error("Note text cannot be empty")
      return
    }
    for (const assigneeId of editTaskAssigneeIds) {
      const state = editTaskAssigneeStates[assigneeId]
      const confirmationValidation = validateWaitingConfirmation(state?.status, state?.confirmationAssigneeId)
      if (confirmationValidation) {
        const person = taskAssigneeOptions.find((item) => item.id === assigneeId)
        toast.error(`${person?.full_name || person?.username || assigneeId}: ${confirmationValidation}`)
        return
      }
      if (state?.startDate && state?.dueDate && state.startDate > state.dueDate) {
        const person = taskAssigneeOptions.find((item) => item.id === assigneeId)
        toast.error(`Start date cannot be after due date for ${person?.full_name || person?.username || assigneeId}`)
        return
      }
    }
    const submittedDraft = { text: editContent, doneRanges: editDoneRanges, addedRanges: editAddedRanges, cursor: { start: 0, end: 0 } }
    setSavingEdit(true)
    try {
      const editContentWithProgress = synchronizeNumberedListProgress({
        text: editContent,
        doneRanges: editDoneRanges,
        addedRanges: editAddedRanges,
      })
      const serializedContent = serializeMarkedNoteContent(
        editContentWithProgress.text,
        editContentWithProgress.doneRanges,
        editContentWithProgress.addedRanges
      ).trim()
      const taskInfo = noteTaskInfo.get(editNoteId)
      const currentNote = notes.find((note) => note.id === editNoteId) || null
      const selectedProjectId = editTaskProjectId === "NONE" ? null : editTaskProjectId
      if (taskInfo?.taskId && editTaskAssigneeIds.length === 0) {
        toast.error("A task must keep at least one assignee")
        return
      }
      const noteBasePath = currentNote?.source === "PX_JAV" ? "plan-notes" : "ga-notes"
      const endpoint = taskInfo?.taskId || keepOpen
        ? `/${noteBasePath}/${editNoteId}/task-bundle`
        : `/${noteBasePath}/${editNoteId}`
      const body: Record<string, unknown> = { content: serializedContent }
      body.one_h_marker = editNoteOneHMarker === ONE_H_MARKER_NONE ? null : editNoteOneHMarker
      body.one_h_marker_comment = editNoteOneHMarker === ONE_H_MARKER_NONE ? null : editNoteOneHMarkerComment.trim() || null
      if (taskInfo?.taskId) {
        const originalAssigneeIds = Array.from(
          new Set(taskInfo.assignees.map((assignee) => assignee.id).filter(Boolean))
        )
        const assigneesChanged = !sameStringSet(editTaskAssigneeIds, originalAssigneeIds)
        const changedStateIds = editTaskAssigneeIds.filter((assigneeId) => {
          const editedState = editTaskAssigneeStates[assigneeId] ?? createEmptyGaAssigneeTaskState()
          const originalState = taskInfo.assigneeStates[assigneeId]
          return !originalState || !sameGaAssigneeTaskState(editedState, originalState)
        })
        const editedDescription = editDescription.trim() || null
        const originalDescription = taskInfo.description?.trim() || null

        if (editedDescription !== originalDescription) {
          body.description = editedDescription
        }
        const originalProjectId = taskInfo.taskProjectId ?? currentNote?.project_id ?? null
        if (selectedProjectId !== originalProjectId) {
          body.project_id = selectedProjectId
        }
        if (assigneesChanged) {
          body.assignee_ids = editTaskAssigneeIds
        }
        if (assigneesChanged || changedStateIds.length > 0) {
          const stateIds = assigneesChanged ? editTaskAssigneeIds : changedStateIds
          body.assignee_states = stateIds.map((assigneeId) =>
            serializeGaAssigneeTaskState(
              assigneeId,
              editTaskAssigneeStates[assigneeId] ?? createEmptyGaAssigneeTaskState()
            )
          )
        }
        body.expected_updated_at = currentNote?.updated_at || null
      }

      if (keepOpen) {
        if (!editNoteVersionRef.current) throw new Error("Reopen the note before saving with Mira.")
        body.expected_updated_at = editNoteVersionRef.current
      }
      const res = await apiFetch(endpoint, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      if (res?.ok) {
        const payload = (await res.json()) as GaNote | { note: GaNote }
        const updated = "note" in payload ? payload.note : payload
        setNotes((prev) =>
          prev.map((n) => (n.id === updated.id ? { ...updated, source: n.source } : n))
        )
        if (taskInfo?.taskId) {
          await loadNoteTasks([editNoteId])
        }

        toast.success("Note updated")
        if (!keepOpen) {
          onEditorSaved?.()
          setEditNoteId(null)
          setEditDoneRanges([])
          setEditAddedRanges([])
          setEditTaskProjectId("NONE")
          setEditTaskAssigneeIds([])
          setEditTaskAssigneeStates({})
        } else {
          const fresh = parseMarkedNoteContentWithProgress(updated.content)
          const current = voiceAdapter.current?.read()
          if (current?.target === `${currentNote?.source || "GA_KA"}:${editNoteId}`) {
            editNoteVersionRef.current = updated.updated_at || null
            const reconciled = reconcileSavedNoteDraft(submittedDraft, current.draft, { ...fresh, cursor: current.draft.cursor })
            setEditContent(reconciled.text)
            editContentLatestRef.current = reconciled.text
            setEditDoneRanges(reconciled.doneRanges)
            setEditAddedRanges(reconciled.addedRanges)
          }
        }
        return updated
      } else {
        let errorMessage = "Failed to update note"
        if (res) {
          const responseText = await res.text()
          try {
            const errorData = JSON.parse(responseText) as { detail?: unknown }
            errorMessage = formatApiDetail(errorData?.detail, errorMessage)
          } catch {
            if (responseText.trim()) {
              errorMessage = responseText.trim().slice(0, 300)
            }
          }
          if (errorMessage === "Failed to update note") {
            errorMessage = `${errorMessage} (HTTP ${res.status})`
          }
        }
        toast.error(errorMessage)
      }
    } catch (error) {
      console.error("Failed to update GA note", error)
      toast.error("Failed to update note")
    } finally {
      setSavingEdit(false)
    }
  }

  const requestAiSkillCategory = React.useCallback(async (title: string, description: string) => {
    const requestId = ++skillInferenceRequestRef.current
    setTaskSkillAiLoading(true)
    try {
      const response = await apiFetch("/skills/infer-category", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, description }),
      })
      if (!response.ok || requestId !== skillInferenceRequestRef.current) return false
      const result = (await response.json()) as SkillCategoryInference
      setTaskSkillCategory(result.category)
      setTaskSkillAutoSuggested(true)
      setTaskSkillAiReason(result.reason)
      return true
    } catch {
      return false
    } finally {
      if (requestId === skillInferenceRequestRef.current) setTaskSkillAiLoading(false)
    }
  }, [apiFetch])

  const openTaskDialog = (note: GaNote) => {
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
    const noteTitle = noteToTaskTitle(note.content || "")
    // Knowledge PX: the prompt creator's task is "PROMPT: …" (renamed to the prompt title once it is saved).
    const defaultTitle = isKnowledgeNote(note) ? `${KNOWLEDGE_CONFIG[note.knowledge_type || "PROMPT"].prefix}: ${noteTitle}` : noteTitle
    setTaskDialogNoteId(note.id)
    setTaskTitle(defaultTitle)
    setTaskDescription("") // start empty so creator can add detailed description
    setTaskPriority(note.priority === "HIGH" ? "HIGH" : "NORMAL")
    setTaskFinishPeriod(FINISH_PERIOD_NONE_VALUE)
    setTaskOneHReportSlot(ONE_H_REPORT_SLOT_NONE_VALUE)
    setTaskOneHMarker(note.one_h_marker ?? ONE_H_MARKER_NONE)
    setTaskOneHMarkerComment(note.one_h_marker_comment || "")
    setTaskDueDate("")
    setTaskStartDate("")
    setTaskDeadlineImportant(false)
    setTaskAssigneeIds([])
    setTaskPromptTesterId(note.knowledge_tester_id ?? "")
    setTaskDepartmentIds([])
    setTaskProjectId(note.project_id ?? "NONE")
    const inferredCategory = inferSkillCategory(defaultTitle, note.content)
    setTaskSkillCategory(inferredCategory)
    setTaskSkillAutoSuggested(Boolean(inferredCategory))
    setTaskSkillAiReason("")
    void requestAiSkillCategory(defaultTitle, note.content || "")
  }

  const openTaskDialogRef = React.useRef(openTaskDialog)
  openTaskDialogRef.current = openTaskDialog

  React.useEffect(() => {
    if (!taskForNoteId || deepLinkTaskStateRef.current !== "idle" || loading) return
    const target = notes.find((n) => n.id === taskForNoteId && n.source !== "PX_JAV")
    if (!target) {
      if (notes.length === 0) return
      deepLinkTaskStateRef.current = "done"
      toast.error("Shënimi nuk u gjet te PX Notes")
      if (taskReturnTo) router.push(taskReturnTo)
      return
    }
    if (target.is_converted_to_task) {
      deepLinkTaskStateRef.current = "done"
      toast.info("Ky shënim e ka tashmë një detyrë")
      if (taskReturnTo) router.push(taskReturnTo)
      return
    }
    deepLinkTaskStateRef.current = "open"
    openTaskDialogRef.current(target)
  }, [loading, notes, router, taskForNoteId, taskReturnTo])

  React.useEffect(() => {
    if (deepLinkTaskStateRef.current !== "open" || taskDialogNoteId) return
    deepLinkTaskStateRef.current = "done"
    if (taskReturnTo) router.push(taskReturnTo)
  }, [router, taskDialogNoteId, taskReturnTo])

  // Get available priority/type options based on whether a project is selected
  const availablePriorityOptions = React.useMemo<readonly TaskTypeOption[]>(() => {
    if (taskProjectId !== "NONE") {
      return TASK_TYPE_OPTIONS_WITH_PROJECT
    }
    return TASK_TYPE_OPTIONS_NO_PROJECT
  }, [taskProjectId])

  const createTaskFromNote = async (note: GaNote) => {
    if (creatingTaskRef.current) return
    if (note.is_converted_to_task || noteTaskInfo.has(note.id)) {
      setNotes((prev) =>
        prev.map((n) => (n.id === note.id ? { ...n, is_converted_to_task: true } : n))
      )
      setTaskDialogNoteId(null)
      toast.info("Task already exists for this note")
      return
    }
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
      toast.error("Select at least one assignee before creating the task")
      return
    }
    const isPromptNote = isKnowledgeNote(note)
    if (isPromptNote && !taskPromptTesterId) {
      toast.error(noteKnowledgeText(note, "Zgjidh testuesin e promptit"))
      return
    }
    if (isPromptNote && taskAssigneeIds.includes(taskPromptTesterId)) {
      toast.error(noteKnowledgeText(note, "Testuesi duhet të jetë person tjetër nga ai që e bën promptin"))
      return
    }
    const selectedPvAssignees = taskAssigneeIds
      .map((assigneeId) => {
        const leave = taskPvByAssigneeId.get(assigneeId)
        if (!leave) return null
        const person = taskAssigneeOptions.find((item) => item.id === assigneeId)
        const label = taskAssigneeLabel(person, assigneeId)
        const until = formatISODateDMY(leave.endDate)
        return until ? `${label} is in PV until ${until}` : `${label} is in PV`
      })
      .filter((item): item is string => Boolean(item))
    if (selectedPvAssignees.length > 0) {
      toast.warning("Selected assignee is in PV", {
        description: selectedPvAssignees.join("; "),
        duration: 8000,
      })
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
    const primaryDepartmentId = effectiveDepartments[0]
    creatingTaskRef.current = true
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

      if (isPromptNote) {
        const testerRes = await apiFetch(`/knowledge/prompt-notes/${note.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tester_id: taskPromptTesterId }),
        })
        if (!testerRes.ok) {
          const data = await testerRes.json().catch(() => null)
          toast.error(typeof data?.detail === "string" ? data.detail : noteKnowledgeText(note, "Testuesi nuk u ruajt"))
          return
        }
        setNotes((prev) =>
          prev.map((item) => (item.id === note.id ? { ...item, knowledge_tester_id: taskPromptTesterId } : item))
        )
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
          assigned_to: taskAssigneeIds[0] ?? null,
          assignees: taskAssigneeIds,
          ga_note_origin_id: note.id,
          department_id: primaryDepartmentId,
          project_id: taskProjectId !== "NONE" ? taskProjectId : null,
          is_bllok: isBllok,
          is_1h_report: is1hReport,
          one_h_report_slot:
            is1hReport && taskOneHReportSlot !== ONE_H_REPORT_SLOT_NONE_VALUE
              ? taskOneHReportSlot
              : null,
          one_h_marker: taskOneHMarker === ONE_H_MARKER_NONE ? null : taskOneHMarker,
          one_h_marker_comment: taskOneHMarker === ONE_H_MARKER_NONE ? null : taskOneHMarkerComment.trim() || null,
          is_r1: isR1,
          is_personal: isPersonal,
          skill_category: taskSkillCategory,
        }),
      })
      if (!taskRes.ok) {
        toast.error("Failed to create task")
        return
      }
      // Task creation already marks the note converted in the same backend
      // transaction. Reload every independent assignee copy from the source of
      // truth instead of synthesizing a combined client-side task.
      setNotes((prev) =>
        prev.map((item) => (item.id === note.id ? { ...item, is_converted_to_task: true } : item))
      )
      await loadNoteTasks([note.id])
      setTaskDialogNoteId(null)
      toast.success("Task created from note")
    } finally {
      creatingTaskRef.current = false
      setCreatingTask(false)
    }
  }

  const closeNote = async (id: string) => {
    const res = await apiFetch(`/ga-notes/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "CLOSED" }),
    })
    if (res?.ok) {
      const updated = (await res.json()) as GaNote
      setNotes((prev) => prev.map((n) => (n.id === id ? updated : n)))
    } else {
      toast.error("Failed to update note")
    }
  }

  const toggleNoteDiscussed = async (id: string, isDiscussed: boolean) => {
    const source = notes.find((note) => note.id === id)?.source
    const res = await apiFetch(`/${source === "PX_JAV" ? "plan-notes" : "ga-notes"}/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_discussed: isDiscussed }),
    })
    if (res?.ok) {
      const updated = (await res.json()) as GaNote
      setNotes((prev) =>
        prev.map((n) => (n.id === id ? { ...updated, source: n.source } : n))
      )
    } else {
      toast.error("Failed to update discussion status")
    }
  }

  const markWaitingTasksDone = async (noteId: string) => {
    setMarkingDoneNoteId(noteId)
    try {
      const res = await apiFetch(`/ga-notes/${noteId}/mark-waiting-done`, {
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

  const exportDailyReport = async () => {
    if (!user?.id) return
    setExportingDailyReport(true)
    try {
      const qs = new URLSearchParams()
      if (departmentId !== "ALL") {
        qs.set("department_id", departmentId)
      }
      if (projectId !== "NONE") {
        qs.set("project_id", projectId)
      }
      // Note: You'll need to create a backend endpoint /exports/ga-notes.xlsx
      // For now, using a placeholder - adjust the endpoint as needed
      const res = await apiFetch(`/exports/ga-notes.xlsx?${qs.toString()}`)
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
      } else {
        const today = new Date().toISOString().split('T')[0]
        link.download = `ga_notes_export_${today}.xlsx`
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

  // Project list is used by task creation and task editing dialogs.
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

    void loadTaskDateLeave()
    return () => {
      cancelled = true
    }
  }, [apiFetch, taskDialogNoteId, taskSelectedWeekStartISOs])

  // Projects filtered by the department chosen in the task dialog
  const primaryDepartmentId = effectiveTaskDepartmentIds[0] || null
  const primaryDepartment = React.useMemo(
    () => (primaryDepartmentId ? departments.find((dept) => dept.id === primaryDepartmentId) || null : null),
    [departments, primaryDepartmentId]
  )
  const taskProjectOptions = React.useMemo(() => {
    const isGraphicDesign = isGraphicDesignDepartment(primaryDepartment)
    const filtered = projects.filter((project) => {
      if (primaryDepartmentId && project.department_id !== primaryDepartmentId) return false
      if (project.is_template) return false
      if ((project.current_phase || "").toUpperCase() === "CLOSED") return false
      if (isGraphicDesign && (project.project_type || "").toUpperCase() === "GENERAL") return false
      return true
    })

    return filtered.sort((a, b) => {
      const aLabel = resolveProjectTitle(a) || "Untitled project"
      const bLabel = resolveProjectTitle(b) || "Untitled project"
      return aLabel.localeCompare(bLabel)
    })
  }, [primaryDepartment, primaryDepartmentId, projects])

  const editTaskProjectOptions = React.useMemo(
    () => projects
      .filter((project) => !project.is_template && (project.current_phase || "").toUpperCase() !== "CLOSED")
      .sort((a, b) => (resolveProjectTitle(a) || "Untitled project").localeCompare(resolveProjectTitle(b) || "Untitled project")),
    [projects]
  )

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
    const weekAgo = now - 7 * 24 * 60 * 60 * 1000
    const closedCutoff = now - 30 * 24 * 60 * 60 * 1000
    const normalizedSearchQuery = deferredSearchQuery.trim().toLowerCase()

    const withinRange = (note: GaNote) => {
      const isClosed = note.status === "CLOSED"
      if (isClosed) {
        if (!note.completed_at) return true
        const completed = new Date(note.completed_at).getTime()
        if (Number.isNaN(completed)) return true
        return completed >= closedCutoff
      }
      if (rangeFilter === "all") return true
      const created = note.created_at ? new Date(note.created_at).getTime() : 0
      return created >= weekAgo
    }
    const matchesTaskStatusFilter = (note: GaNote) => {
      if (taskStatusFilter === "all") return true
      if (taskStatusFilter === "open") return note.status !== "CLOSED"
      if (taskStatusFilter === "closed") return note.status === "CLOSED"
      const hasTask = note.is_converted_to_task === true || noteTaskInfo.has(note.id)
      if (taskStatusFilter === "notes") return !hasTask && note.status !== "CLOSED"
      if (taskStatusFilter === "tasks") return hasTask
      const taskInfo = noteTaskInfo.get(note.id)
      if (!taskInfo) return false
      const aggregatedStatus =
        taskInfo && (taskInfo.taskStatuses?.length ?? 0) > 1
          ? aggregateTaskStatus(taskInfo.taskStatuses)
          : normalizeTaskStatus(taskInfo?.taskStatus)
      if (aggregatedStatus === "UNKNOWN") return false
      return aggregatedStatus === taskStatusFilter
    }
    const matchesContentFilter = (note: GaNote) => {
      if (contentFilter === "all") return true
      return EMAIL_MARKER_RE.test(note.content || "")
    }
    const matchesOneHMarkerFilter = (note: GaNote) => {
      const marker = note.one_h_marker || null
      if (oneHMarkerFilter === "all") return true
      if (oneHMarkerFilter === "with") return marker !== null
      if (oneHMarkerFilter === "none") return marker === null
      return marker === oneHMarkerFilter
    }
    const matchesSearchQuery = (note: GaNote) => {
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
    const taskDoneBucket = (note: GaNote) => {
      const taskInfo = noteTaskInfo.get(note.id)
      if (!taskInfo) return 0
      const aggregatedStatus =
        taskInfo && (taskInfo.taskStatuses?.length ?? 0) > 1
          ? aggregateTaskStatus(taskInfo.taskStatuses)
          : normalizeTaskStatus(taskInfo?.taskStatus)
      return aggregatedStatus === "DONE" ? 1 : 0
    }
    const sorted = [...notes]
      .filter(withinRange)
      .filter(matchesTaskStatusFilter)
      .filter(matchesContentFilter)
      .filter(matchesOneHMarkerFilter)
      .filter(matchesSearchQuery)
      .sort((a, b) => {
        // First, sort by status: open notes first, closed notes last
        const aIsClosed = a.status === "CLOSED"
        const bIsClosed = b.status === "CLOSED"
        if (aIsClosed !== bIsClosed) {
          return aIsClosed ? 1 : -1 // Closed notes go to the end
        }
        // Then, move DONE tasks after non-done tasks
        const aBucket = taskDoneBucket(a)
        const bBucket = taskDoneBucket(b)
        if (aBucket !== bBucket) {
          return aBucket - bBucket
        }
        // Keep newest-created notes first; edits should not change row order.
        const aCreated = a.created_at ? new Date(a.created_at).getTime() : 0
        const bCreated = b.created_at ? new Date(b.created_at).getTime() : 0
        return bCreated - aCreated
      })
    return sorted
  }, [notes, rangeFilter, taskStatusFilter, contentFilter, oneHMarkerFilter, deferredSearchQuery, noteTaskInfo, users, departments, projects])

  React.useEffect(() => {
    setNotesRenderLimit(INITIAL_NOTES_RENDER_LIMIT)
  }, [contentFilter, deferredSearchQuery, departmentId, oneHMarkerFilter, projectId, rangeFilter, taskStatusFilter])

  const renderedNotes = React.useMemo(
    () => visibleNotes.slice(0, notesRenderLimit),
    [notesRenderLimit, visibleNotes]
  )

  const voiceAdapter = React.useRef<NotesVoiceAdapter | null>(null)
  const [runNotesTool] = React.useState(() => createNotesVoiceController({
    read: () => voiceAdapter.current!.read(),
    write: draft => voiceAdapter.current!.write(draft),
    select: note => voiceAdapter.current!.select(note),
    newNote: () => voiceAdapter.current!.newNote(),
    save: () => voiceAdapter.current!.save(),
  }))
  const { phase: miraPhase, muted: miraMuted, error: miraError, audioBlocked: miraAudioBlocked,
    audioRef: miraAudio, start: startMira, stop: stopMira, toggleMute: muteMira, resumeAudio: resumeMira } = useVoiceAssistant({ mode: "px_notes", onToolCall: runNotesTool })

  // Realtime callbacks read the committed editor state, never the state from
  // when the microphone was first opened. Local edits stay in the same UI.
  React.useLayoutEffect(() => {
    const waitForTarget = async (target: string) => {
      for (let frame = 0; frame < 20; frame++) {
        await new Promise<void>(resolve => window.requestAnimationFrame(() => resolve()))
        const state = voiceAdapter.current!.read()
        if (state.target === target && !state.busy) return
      }
      throw new Error("Editori nuk u hap. Provo përsëri.")
    }
    voiceAdapter.current = {
      read: (): NotesVoiceState => {
        const note = notes.find(item => item.id === editNoteId)
        const editing = Boolean(editNoteId)
        const textarea = editing ? editTextareaRef.current : contentTextareaRef.current
        const text = editing ? editContent : content
        const parsed = note ? parseMarkedNoteContentWithProgress(note.content) : null
        const currentText = editing ? serializeMarkedNoteContent(editContent, editDoneRanges, editAddedRanges) : content
        const originalText = parsed ? serializeMarkedNoteContent(parsed.text, parsed.doneRanges, parsed.addedRanges) : defaultNoteContent
        const taskInfo = editNoteId ? noteTaskInfo.get(editNoteId) : null
        const metadataChanged = editing && (
          editDescription.trim() !== (taskInfo?.description || "").trim()
          || editTaskProjectId !== (taskInfo?.taskProjectId ?? note?.project_id ?? "NONE")
          || !sameStringSet(editTaskAssigneeIds, taskInfo?.assignees.map(assignee => assignee.id) || [])
          || editNoteOneHMarker !== (note?.one_h_marker ?? ONE_H_MARKER_NONE)
          || editNoteOneHMarkerComment !== (note?.one_h_marker_comment || "")
          || editTaskAssigneeIds.some(id => !sameGaAssigneeTaskState(editTaskAssigneeStates[id] ?? createEmptyGaAssigneeTaskState(), taskInfo?.assigneeStates[id] ?? createEmptyGaAssigneeTaskState()))
        )
        return {
          target: editing ? `${note?.source || "GA_KA"}:${editNoteId}` : "new",
          draft: { text, doneRanges: editing ? editDoneRanges : [], addedRanges: editing ? editAddedRanges : [],
            cursor: { start: textarea?.selectionStart ?? text.length, end: textarea?.selectionEnd ?? text.length } },
          notes: renderedNotes.map(item => ({ id: item.id, source: item.source || "GA_KA", content: item.content, closed: item.status === "CLOSED" })),
          dirty: currentText.trim() !== originalText.trim() || Boolean(metadataChanged),
          busy: posting || savingEdit || loadingEditNote,
        }
      },
      write: async draft => {
        flushSync(() => {
          if (editNoteId) {
            setEditContent(draft.text)
            editContentLatestRef.current = draft.text
            setEditDoneRanges(draft.doneRanges)
            setEditAddedRanges(draft.addedRanges)
            editDictationSelectionRef.current = draft.cursor
          } else setContent(draft.text)
        })
        const textarea = editNoteId ? editTextareaRef.current : contentTextareaRef.current
        textarea?.setSelectionRange(draft.cursor.start, draft.cursor.end)
      },
      select: async selected => {
        if (editorNote && selected.id !== editorNote.id) throw new Error("Hap këtë Note nga lista PX Notes.")
        const note = notes.find(item => item.id === selected.id && (item.source || "GA_KA") === selected.source)
        if (!note || !await openEditNote(note)) throw new Error("Note-i nuk u hap.")
        await waitForTarget(`${selected.source}:${selected.id}`)
      },
      newNote: async () => {
        if (editorNote) throw new Error("Hap PX Notes për një Note të ri.")
        if (content.trim() && content.trim() !== defaultNoteContent.trim()) throw new Error("Ruaje fillimisht draftin e ri.")
        flushSync(() => { setEditNoteId(null) })
        contentTextareaRef.current?.setSelectionRange(0, 0)
        await waitForTarget("new")
      },
      save: async () => {
        const saved = editNoteId ? await saveEditNote(true) : await createNote()
        return saved || null
      },
    }
  })

  const startNotesMira = () => {
    if (isVoiceListening) stopVoice()
    if (isCloudRecording) stopCloud()
    if (isEditVoiceListening) stopEditVoice()
    if (isEditCloudRecording) stopEditCloud()
    void startMira()
  }
  const miraControls = <PxNotesMiraControls phase={miraPhase} muted={miraMuted} error={miraError} audioBlocked={miraAudioBlocked}
    onStart={startNotesMira} onStop={stopMira} onMute={muteMira} onResume={() => void resumeMira()} />

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

  const openAttachmentsForNote = (noteId: string) => {
    resetManageAttachmentsState()
    setAttachmentsDialogNoteId(noteId)
    setAttachmentsDialogOpen(true)
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

  const editDialogContent = (
    <>
          <DialogHeader className="shrink-0">
            <DialogTitle>Edit Note</DialogTitle>
          </DialogHeader>
          {miraControls}
          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain pr-1">
            <div className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Label>Note text</Label>
                <div className="flex flex-wrap items-center gap-2">
                  <Select value={voiceLanguage} onValueChange={handleVoiceLanguageChange}>
                    <SelectTrigger className="h-8 w-[118px] text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="en">English</SelectItem>
                      <SelectItem value="sq">Albanian</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button
                    type="button"
                    variant={isEditVoiceListening || isEditCloudRecording ? "default" : "outline"}
                    size="sm"
                    className="h-8 gap-2"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={handleEditVoiceToggle}
                    disabled={editVoiceMode === "none" || isEditCloudTranscribing || savingEdit}
                    title={isEditVoiceListening || isEditCloudRecording ? "Stop voice dictation" : "Dictate at cursor"}
                  >
                    {isEditVoiceListening || isEditCloudRecording ? (
                      <Square className="h-4 w-4" />
                    ) : (
                      <Mic className="h-4 w-4" />
                    )}
                    {isEditVoiceListening || isEditCloudRecording
                      ? "Stop"
                      : isEditCloudTranscribing
                        ? "Transcribing"
                        : "Voice"}
                  </Button>
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
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={markSelectedEditTextDone}
                  >
                    Mark / undo selected done
                  </Button>
                </div>
              </div>
              <Textarea
                ref={bindEditTextarea}
                value={editContent}
                onChange={(event) => {
                  handleEditContentChange(normalizeNoteTextareaInput(event.currentTarget))
                  rememberEditDictationCursor(event.currentTarget)
                }}
                onFocus={(event) => rememberEditDictationCursor(event.currentTarget)}
                onSelect={(event) => rememberEditDictationCursor(event.currentTarget)}
                onClick={(event) => rememberEditDictationCursor(event.currentTarget)}
                onKeyUp={(event) => rememberEditDictationCursor(event.currentTarget)}
                className="min-h-[180px] max-h-[42vh] resize-y overflow-y-auto text-sm leading-normal"
              />
              <div className="flex justify-end sm:hidden">
                <Button type="button" onClick={() => void saveEditNote()} disabled={savingEdit}>
                  {savingEdit ? "Saving..." : "Save changes"}
                </Button>
              </div>
              {isEditVoiceListening || isEditCloudRecording || isEditCloudTranscribing || editVoiceInterimText ? (
                <div className="flex items-center gap-2 text-xs text-blue-700">
                  <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-red-500" />
                  {isEditCloudTranscribing
                    ? "Transcribing..."
                    : editVoiceInterimText
                      ? `Listening: ${editVoiceInterimText}`
                      : "Listening — words will be inserted at the cursor."}
                </div>
              ) : null}
              <p className="text-xs text-muted-foreground">
                Select text and click mark done to toggle it, or place the cursor on a line to toggle the whole line.
              </p>
              <div className="max-w-[220px] space-y-1">
                <Label>Note symbol</Label>
                <Select
                  value={editNoteOneHMarker}
                  onValueChange={(value) => updateEditNoteMarker(value as OneHMarker | typeof ONE_H_MARKER_NONE)}
                  disabled={savingEdit}
                >
                  <SelectTrigger className={`border-blue-300 bg-blue-50 font-black ${editNoteOneHMarker === ONE_H_MARKER_NONE ? "text-[#0F2A5F]" : "text-red-600"}`}><SelectValue /></SelectTrigger>
                  <SelectContent className="font-black text-[#0F2A5F]">
                    <SelectItem value={ONE_H_MARKER_NONE}>No symbol</SelectItem>
                    {ONE_H_MARKER_OPTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value} className="font-black text-red-600 focus:text-red-700">{option.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className={isGaUser ? "hidden space-y-1 sm:block" : "space-y-1"}>
                <Label className="text-xs text-muted-foreground">Preview</Label>
                <div className="min-h-[120px] max-h-[32vh] overflow-y-auto whitespace-pre-wrap break-words rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm leading-normal">
                  {(() => {
                    const previewContent = synchronizeNumberedListProgress({
                      text: editContent,
                      doneRanges: editDoneRanges,
                      addedRanges: editAddedRanges,
                    })
                    return renderNoteContentWithRanges(
                      previewContent.text,
                      previewContent.doneRanges,
                      previewContent.addedRanges,
                      canViewStrikeTimestamps
                    )
                  })()}
                </div>
              </div>
            </div>
            {editNoteId && noteTaskInfo.get(editNoteId)?.taskId ? (
              <div className="space-y-2">
                <Label>Description</Label>
                <BoldOnlyEditor value={editDescription} onChange={setEditDescription} editorClassName="h-32 min-h-32 max-h-32 overflow-y-auto [overflow-wrap:anywhere]" />
              </div>
            ) : null}
            {editNoteId && noteTaskInfo.get(editNoteId)?.taskId ? (
              <div className="space-y-2">
                <Label>PRJK</Label>
                <Select value={editTaskProjectId} onValueChange={setEditTaskProjectId} disabled={savingEdit}>
                  <SelectTrigger><SelectValue placeholder="Select project" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="NONE">No project</SelectItem>
                    {editTaskProjectOptions.map((project) => (
                      <SelectItem key={project.id} value={project.id}>
                        {resolveProjectTitle(project) || "Untitled project"}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : null}
            {editNoteId && noteTaskInfo.get(editNoteId)?.taskId ? (
              <div className="space-y-2">
                <Label>Assign to</Label>
                <div className="rounded-md border bg-white p-2">
                  <div className="mb-2 flex flex-wrap gap-2">
                    {editTaskAssigneeIds.length === 0 ? (
                      <span className="text-xs text-muted-foreground">No assignees selected.</span>
                    ) : (
                      editTaskAssigneeIds.map((id) => {
                        const person = taskAssigneeOptions.find((p) => p.id === id)
                        const label = person?.full_name || person?.username || id
                        return (
                          <button
                            key={id}
                            type="button"
                            className="flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs"
                            disabled={savingEdit}
                            onClick={() => setEditTaskAssigneeIds((prev) => prev.filter((item) => item !== id))}
                          >
                            {label}
                            <span className="text-slate-500">Ã—</span>
                          </button>
                        )
                      })
                    )}
                  </div>
                  <Select
                    value="__edit_assignee_picker__"
                    onValueChange={(value) => {
                      if (value === "__edit_assignee_picker__") return
                      setEditTaskAssigneeIds((prev) => (prev.includes(value) ? prev : [...prev, value]))
                      setEditTaskAssigneeStates((current) =>
                        current[value]
                          ? current
                          : { ...current, [value]: createEmptyGaAssigneeTaskState() }
                      )
                    }}
                    disabled={savingEdit || taskAssigneeOptions.length === 0}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Add assignee" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__edit_assignee_picker__" disabled>
                        Add assignee
                      </SelectItem>
                      {taskAssigneeOptions
                        .filter((person) => person.id && !editTaskAssigneeIds.includes(person.id))
                        .map((person) => (
                          <SelectItem key={person.id} value={person.id}>
                            {person.full_name || person.username || person.id}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
            ) : null}
            {editNoteId && noteTaskInfo.get(editNoteId)?.taskId ? (
              <div className="space-y-2 rounded-md border border-slate-200 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Label className="flex items-center gap-1">
                    <CalendarIcon className="h-4 w-4 text-emerald-600" />
                    Per-person execution
                  </Label>
                  <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    Independent status and scheduling
                  </span>
                </div>
                {editTaskAssigneeIds.length === 0 ? (
                  <p className="text-xs text-muted-foreground">Select at least one assignee.</p>
                ) : (
                  <div className="space-y-3">
                    {editTaskAssigneeIds.map((assigneeId) => {
                      const person = taskAssigneeOptions.find((item) => item.id === assigneeId)
                      const state = editTaskAssigneeStates[assigneeId] ?? createEmptyGaAssigneeTaskState()
                      return (
                        <div key={assigneeId} className="space-y-3 rounded-md border border-slate-200 bg-slate-50/60 p-3">
                          <div className="text-sm font-semibold text-slate-800">
                            {person?.full_name || person?.username || assigneeId}
                          </div>
                          <div className={`grid gap-2 sm:grid-cols-2 ${state.type === "1H" ? "lg:grid-cols-6" : "lg:grid-cols-5"}`}>
                            <div className="space-y-1">
                              <Label className="text-xs text-muted-foreground">Type</Label>
                              <Select
                                value={state.type}
                                onValueChange={(value) => {
                                  const nextType = value as GaAssigneeTaskType
                                  updateEditTaskAssigneeState(assigneeId, {
                                    type: nextType,
                                    ...(nextType === "1H" ? {} : { oneHReportSlot: null }),
                                  })
                                }}
                                disabled={savingEdit}
                              >
                                <SelectTrigger><SelectValue /></SelectTrigger>
                                  <SelectContent>
                                  <SelectItem value="NORMAL">Normal</SelectItem>
                                  <SelectItem value="HIGH">High</SelectItem>
                                  <SelectItem value="1H">1H</SelectItem>
                                  <SelectItem value="R1">R1</SelectItem>
                                  <SelectItem value="PERSONAL">Personal</SelectItem>
                                  <SelectItem value="BLLOK">BLLOK</SelectItem>
                                </SelectContent>
                              </Select>
                            </div>
                            {state.type === "1H" ? (
                              <div className="space-y-1">
                                <Label className="text-xs text-muted-foreground">1H slot</Label>
                                <Select
                                  value={state.oneHReportSlot ?? ONE_H_REPORT_SLOT_NONE_VALUE}
                                  onValueChange={(value) => {
                                    const nextSlot = value === ONE_H_REPORT_SLOT_NONE_VALUE
                                      ? null
                                      : value as OneHReportSlot
                                    updateEditTaskAssigneeState(assigneeId, {
                                      oneHReportSlot: nextSlot,
                                      ...(nextSlot ? { finishPeriod: finishPeriodForOneHReportSlot(nextSlot) } : {}),
                                    })
                                  }}
                                  disabled={savingEdit}
                                >
                                  <SelectTrigger><SelectValue placeholder="Select slot" /></SelectTrigger>
                                  <SelectContent>
                                    <SelectItem value={ONE_H_REPORT_SLOT_NONE_VALUE}>Unassigned</SelectItem>
                                    {oneHReportSlotsForPeriod(state.finishPeriod).map((value) => (
                                      <SelectItem key={value} value={value}>{value}</SelectItem>
                                    ))}
                                  </SelectContent>
                                </Select>
                              </div>
                            ) : null}
                            <div className="space-y-1">
                              <Label className="text-xs text-muted-foreground">Status</Label>
                              <Select
                                value={state.status}
                                onValueChange={(value) =>
                                  updateEditTaskAssigneeState(assigneeId, { status: value as GaAssigneeTaskStatus })
                                }
                                disabled={savingEdit}
                              >
                                <SelectTrigger><SelectValue /></SelectTrigger>
                                <SelectContent>
                                  <SelectItem value="TODO">To do</SelectItem>
                                  <SelectItem value="IN_PROGRESS">In progress</SelectItem>
                                  <SelectItem value="WAITING_CLIENT">WFE</SelectItem>
                                  <SelectItem value="WAITING_CONFIRMATION">Waiting Confirmation</SelectItem>
                                  <SelectItem value="DONE">Done</SelectItem>
                                </SelectContent>
                              </Select>
                            </div>
                            {isWaitingConfirmation(state.status) ? (
                              <div className="space-y-1">
                                <Label className="text-xs text-muted-foreground">Confirm by</Label>
                                <Select
                                  value={state.confirmationAssigneeId || "__none__"}
                                  onValueChange={(value) =>
                                    updateEditTaskAssigneeState(assigneeId, {
                                      confirmationAssigneeId: value === "__none__" ? "" : value,
                                    })
                                  }
                                  disabled={savingEdit}
                                >
                                  <SelectTrigger><SelectValue placeholder="Manager, Admin, or GA" /></SelectTrigger>
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
                            <div className="space-y-1">
                              <Label className="text-xs text-muted-foreground">Start date</Label>
                              <Input
                                type="date"
                                value={state.startDate}
                                onChange={(event) => updateEditTaskAssigneeState(assigneeId, { startDate: event.target.value })}
                                disabled={savingEdit}
                              />
                            </div>
                            <div className="space-y-1">
                              <Label className="text-xs text-muted-foreground">Due date</Label>
                              <Input
                                type="date"
                                value={state.dueDate}
                                onChange={(event) => updateEditTaskAssigneeState(assigneeId, { dueDate: event.target.value })}
                                disabled={savingEdit}
                              />
                            </div>
                            <div className="space-y-1">
                              <Label className="text-xs text-muted-foreground">Finish by</Label>
                              <Select
                                value={state.finishPeriod ?? FINISH_PERIOD_NONE_VALUE}
                                onValueChange={(value) => {
                                  const nextPeriod = value === FINISH_PERIOD_NONE_VALUE
                                    ? null
                                    : value as TaskFinishPeriod
                                  updateEditTaskAssigneeState(assigneeId, {
                                    finishPeriod: nextPeriod,
                                  })
                                }}
                                disabled={savingEdit}
                              >
                                <SelectTrigger><SelectValue /></SelectTrigger>
                                <SelectContent>
                                  <SelectItem value={FINISH_PERIOD_NONE_VALUE}>All day</SelectItem>
                                  {FINISH_PERIOD_OPTIONS.map((value) => (
                                    <SelectItem key={value} value={value}>{value}</SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            </div>
                            <div className="space-y-1">
                              <Label className="text-xs text-muted-foreground">Symbol</Label>
                              <Select
                                value={state.oneHMarker ?? ONE_H_MARKER_NONE}
                                onValueChange={(value) => updateEditNoteMarker(value as OneHMarker | typeof ONE_H_MARKER_NONE)}
                                disabled={savingEdit}
                              >
                                <SelectTrigger className={`border-blue-300 bg-blue-50 font-black ${state.oneHMarker ? "text-red-600" : "text-[#0F2A5F]"}`}><SelectValue /></SelectTrigger>
                                <SelectContent className="font-black text-[#0F2A5F]">
                                  <SelectItem value={ONE_H_MARKER_NONE}>No symbol</SelectItem>
                                  {ONE_H_MARKER_OPTIONS.map((option) => (
                                    <SelectItem key={option.value} value={option.value} className="font-black text-red-600 focus:text-red-700">{option.label}</SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            </div>
                          </div>
                          <label className="flex items-center gap-2 text-xs text-slate-700">
                            <Checkbox
                              checked={state.isDeadlineImportant}
                              onCheckedChange={(checked) =>
                                updateEditTaskAssigneeState(assigneeId, { isDeadlineImportant: checked === true })
                              }
                              disabled={savingEdit}
                            />
                            Deadline important
                          </label>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            ) : null}
          </div>
            <div className="flex shrink-0 justify-end gap-2 border-t bg-background pt-3">
              <Button variant="outline" onClick={() => {
                stopMira()
                setEditNoteId(null)
                setEditDoneRanges([])
                setEditAddedRanges([])
                setEditDescription("")
                setEditTaskProjectId("NONE")
                setEditTaskAssigneeIds([])
                setEditTaskAssigneeStates({})
              }}>
                Cancel
              </Button>
              <Button className="hidden sm:inline-flex" onClick={() => void saveEditNote()} disabled={savingEdit}>
                {savingEdit ? "Saving..." : "Save changes"}
              </Button>
            </div>

    </>
  )

  const editDialog = <Dialog open={Boolean(editNoteId)} onOpenChange={(open) => {
    if (!open) {
      stopMira()
      setEditNoteId(null)
      setEditDoneRanges([])
      setEditAddedRanges([])
      setEditDescription("")
      setEditTaskProjectId("NONE")
      setEditTaskAssigneeIds([])
      setEditTaskAssigneeStates({})
    }
  }}><DialogContent className="flex max-h-[calc(100dvh-2rem)] flex-col overflow-hidden sm:max-w-3xl">{editDialogContent}</DialogContent></Dialog>

  // The same editor and save path are used both here and from the comments inbox.
  if (editorNote) {
    const content = editNoteId ? editDialogContent : <><DialogHeader className="shrink-0"><DialogTitle>Edit Note</DialogTitle></DialogHeader><p role="status">Duke ngarkuar detyrën…</p></>
    return <><audio ref={miraAudio} autoPlay className="hidden" />{embeddedEditor ? content : <Dialog open onOpenChange={(open) => { if (!open) onEditorClose?.() }}>
      <DialogContent className="flex max-h-[calc(100dvh-2rem)] flex-col overflow-hidden sm:max-w-3xl">{content}</DialogContent>
    </Dialog>}</>
  }

  return (
    <div className="space-y-6">
      <audio ref={miraAudio} autoPlay className="hidden" />
      <div className={`rounded-2xl border bg-gradient-to-r from-amber-50 via-indigo-50 to-cyan-50 p-6 shadow-sm${quickMode ? " hidden" : ""}`}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-xs font-semibold tracking-[0.18em] text-primary/80 uppercase">Notes for all</div>
            <div className="text-2xl font-semibold leading-tight mt-1 text-slate-900">PX Notes</div>
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
          <CardAction>
            <div className="flex items-center gap-2">
              <Select value={voiceLanguage} onValueChange={handleVoiceLanguageChange}>
                <SelectTrigger className="h-8 w-[130px] text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="en">English</SelectItem>
                  <SelectItem value="sq">Albanian</SelectItem>
                </SelectContent>
              </Select>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-8 gap-2"
                onClick={handleVoiceToggle}
                disabled={voiceMode === "none" || (voiceMode === "cloud" && isCloudTranscribing)}
                title={
                  voiceMode === "browser"
                    ? isVoiceListening
                      ? "Stop voice dictation"
                      : "Start voice dictation"
                    : voiceMode === "cloud"
                      ? isCloudRecording
                        ? "Stop cloud dictation"
                        : "Start cloud dictation"
                      : "Voice dictation not supported"
                }
              >
                {voiceMode === "cloud" ? (
                  isCloudRecording ? <Square className="h-4 w-4" /> : <Mic className="h-4 w-4" />
                ) : isVoiceListening ? (
                  <Square className="h-4 w-4" />
                ) : (
                  <Mic className="h-4 w-4" />
                )}
                {voiceMode === "cloud"
                  ? isCloudRecording
                    ? "Stop"
                    : isCloudTranscribing
                      ? "Transcribing"
                      : "Voice"
                  : isVoiceListening
                    ? "Stop"
                    : "Voice"}
              </Button>
              {voiceMode === "cloud" ? (
                <span className="text-[11px] text-slate-500">Cloud fallback</span>
              ) : null}
            </div>
          </CardAction>
        </CardHeader>
        <CardContent className="space-y-3">
          {miraControls}
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
              onChange={(event) => setContent(normalizeNoteTextareaInput(event.currentTarget))}
              rows={4}
              className="min-h-[110px] md:min-h-[120px] resize-none text-base md:text-lg bg-primary/5 border-primary/40 shadow-[0_0_0_1px_rgba(0,0,0,0.04)] focus-visible:ring-2 focus-visible:ring-primary/60 focus-visible:border-primary"
              autoFocus
            />
            {isVoiceListening ? (
              <div className="text-xs text-muted-foreground">
                <span className="font-medium text-slate-700">Listening...</span>
                {voiceInterimText ? <span className="ml-2">{voiceInterimText}</span> : null}
              </div>
            ) : null}
            {isCloudRecording ? (
              <div className="text-xs text-muted-foreground">
                <span className="font-medium text-slate-700">Recording...</span>
              </div>
            ) : null}
            {isCloudTranscribing ? (
              <div className="text-xs text-muted-foreground">
                <span className="font-medium text-slate-700">Transcribing...</span>
              </div>
            ) : null}
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
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-sm">Notes</CardTitle>
            <div className="flex flex-wrap items-center gap-2">
            <TeamMarkerCommentsButton />
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 gap-2 text-xs"
              aria-expanded={showLegend}
              aria-controls="px-notes-symbol-legend px-notes-detail-legend"
              aria-label={showLegend ? "Fshih legjendën" : "Shfaq legjendën"}
              onClick={() => setShowLegend((prev) => !prev)}
            >
              Legjenda <span className="text-base leading-none" aria-hidden="true">{showLegend ? "−" : "+"}</span>
            </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {showLegend ? (
          <div id="px-notes-symbol-legend" className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-blue-300 bg-blue-50 px-3 py-2 text-xs text-[#0F2A5F]">
            <span className="font-bold uppercase">Legjenda:</span>
             <span><b className="text-base font-black text-red-600">?</b> - PYETJE/PAQARTESI</span>
            <span className="text-lg font-black text-[#0F2A5F]" aria-hidden="true">/</span>
             <span><b className="text-base font-black text-red-600">!</b> - DYSHIM/ NUK KUPTOHET DET</span>
             <span className="text-lg font-black text-[#0F2A5F]" aria-hidden="true">/</span>
             <span><b className="text-base font-black text-red-600">!!!</b> - KLIENT/URGJENT</span>
             <span className="text-lg font-black text-[#0F2A5F]" aria-hidden="true">/</span>
             <span><b className="text-xs font-black text-red-600">SHARE</b> - DET QE DUHET SCREENSHARE ME GA</span>
             <span className="text-lg font-black text-[#0F2A5F]" aria-hidden="true">/</span>
             <span><b className="text-base font-black text-red-600">👁</b> - KËRKON MONITORIM NGA DIKUSH TJETËR</span>
             <span className="text-lg font-black text-[#0F2A5F]" aria-hidden="true">/</span>
             <span><b className="text-base font-black text-red-600">X</b> - MBYLL DETYREN</span>
            <span className="text-lg font-black text-[#0F2A5F]" aria-hidden="true">/</span>
            <span><b className="text-xs font-black text-red-600">M2</b> - DOREZIM DERI NE PAUZE</span>
            <span className="text-lg font-black text-[#0F2A5F]" aria-hidden="true">/</span>
            <span><b className="text-xs font-black text-red-600">M3</b> - DOREZIM DERI NE FUND TE DITES</span>
            <span className="text-lg font-black text-[#0F2A5F]" aria-hidden="true">/</span>
            <span><b className="text-xs font-black text-red-600">M2/3</b> - DOREZIM EDHE NE M2 EDHE M3</span>
            <span className="text-lg font-black text-[#0F2A5F]" aria-hidden="true">/</span>
            <span><b className="text-xs font-black text-red-600">GENT</b> - PYETJE/SQARIM ME GENTIN</span>
            <span className="text-lg font-black text-[#0F2A5F]" aria-hidden="true">/</span>
            <span><b className="text-xs font-black text-red-600">KA</b> - PYETJE/SQARIM ME KA</span>
            <span className="text-lg font-black text-[#0F2A5F]" aria-hidden="true">/</span>
            <span><b className="text-xs font-black text-red-600">GA</b> - PYETJE/SQARIM ME GA</span>
            <span className="text-lg font-black text-[#0F2A5F]" aria-hidden="true">/</span>
            <span><b className="text-base font-black text-red-600">F</b> - DET FIZIKISHT</span>
            <span className="text-lg font-black text-[#0F2A5F]" aria-hidden="true">/</span>
            <span><b className="text-xs font-black text-red-600">BZ1N1</b></span>
          </div>
          ) : null}
          {showLegend ? (
            <div id="px-notes-detail-legend" className="rounded-md border bg-white">
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
                    {[
                      ["?", "PYETJE/PAQARTESI"],
                      ["!", "DYSHIM/ NUK KUPTOHET DET"],
                      ["!!!", "KLIENT/URGJENT"],
                      ["SHARE", "DET QE DUHET SCREENSHARE ME GA"],
                      ["👁", "KËRKON MONITORIM NGA DIKUSH TJETËR"],
                      ["X", "MBYLL DETYREN"],
                      ["M2", "DOREZIM DERI NE PAUZE"],
                      ["M3", "DOREZIM DERI NE FUND TE DITES"],
                      ["M2/3", "DOREZIM EDHE NE M2 EDHE M3"],
                      ["GENT", "PYETJE/SQARIM ME GENTIN"],
                      ["KA", "PYETJE/SQARIM ME KA"],
                      ["GA", "PYETJE/SQARIM ME GA"],
                      ["F", "DET FIZIKISHT"],
                      ["BZ1N1", ""],
                    ].map(([symbol, meaning]) => (
                      <TableRow key={symbol} className="h-8">
                        <TableCell className="p-1 text-center text-lg font-black text-red-600">{symbol}</TableCell>
                        <TableCell className="text-sm font-semibold">Symbol</TableCell>
                        <TableCell className="text-sm text-slate-600">{meaning || "—"}</TableCell>
                      </TableRow>
                    ))}
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
                      <TableCell className="text-sm font-semibold">Task: To do</TableCell>
                      <TableCell className="text-sm text-slate-600">Ngjyra e rreshtit (SHENIMI)</TableCell>
                    </TableRow>
                    <TableRow className="h-8">
                      <TableCell className="p-1">
                        <div className="w-4 h-4 rounded-sm border border-slate-300 bg-amber-200" />
                      </TableCell>
                      <TableCell className="text-sm font-semibold">Task: In progress</TableCell>
                      <TableCell className="text-sm text-slate-600">Ngjyra e rreshtit (SHENIMI)</TableCell>
                    </TableRow>
                    <TableRow className="h-8">
                      <TableCell className="p-1">
                        <div className="h-4 w-4 rounded-sm border border-[#B8860B] bg-[#E2C15B]" />
                      </TableCell>
                      <TableCell className="text-sm font-semibold">Task: WFE</TableCell>
                      <TableCell className="text-sm text-slate-600">Ngjyra e rreshtit (SHENIMI)</TableCell>
                    </TableRow>
                    <TableRow className="h-8">
                      <TableCell className="p-1">
                        <div className="w-4 h-4 rounded-sm border border-slate-300 bg-emerald-200" />
                      </TableCell>
                      <TableCell className="text-sm font-semibold">Task: Done</TableCell>
                      <TableCell className="text-sm text-slate-600">Ngjyra e rreshtit (SHENIMI)</TableCell>
                    </TableRow>
                    <TableRow className="h-8">
                      <TableCell className="p-1">
                        <div className="w-4 h-4 rounded-sm border border-slate-300 bg-slate-200" />
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
          <div className="grid grid-cols-2 items-center gap-2 sm:flex sm:flex-wrap sm:gap-3">
            <div className="min-w-0 space-y-1">
              <Select value={rangeFilter} onValueChange={(v) => setRangeFilter(v as "week" | "all")}>
                <SelectTrigger className="h-9 w-full min-w-0 gap-1 px-2 text-xs sm:w-[160px] sm:gap-2 sm:px-3 sm:text-sm [&_[data-slot=select-value]]:min-w-0">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="week">This week</SelectItem>
                  <SelectItem value="all">All (default)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="min-w-0 space-y-1">
              <Select
                value={taskStatusFilter}
                onValueChange={(v) => setTaskStatusFilter(v as TaskStatusFilter)}
              >
                <SelectTrigger className="h-9 w-full min-w-0 gap-1 px-2 text-xs sm:w-[180px] sm:gap-2 sm:px-3 sm:text-sm [&_[data-slot=select-value]]:min-w-0">
                  <SelectValue placeholder="Tasks/Status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Tasks/Notes</SelectItem>
                  <SelectItem value="tasks">Tasks</SelectItem>
                  <SelectItem
                    value="notes"
                    className="bg-sky-100 text-sky-900 focus:bg-sky-200 focus:text-sky-900"
                  >
                    Notes
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
                    className="bg-[#E2C15B] text-[#4F3A00] focus:bg-[#D6AF3D] focus:text-[#4F3A00]"
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
            <div className="min-w-0 space-y-1">
              <Select
                value={contentFilter}
                onValueChange={(v) => setContentFilter(v as ContentFilter)}
              >
                <SelectTrigger className="h-9 w-full min-w-0 gap-1 px-2 text-xs sm:w-[140px] sm:gap-2 sm:px-3 sm:text-sm [&_[data-slot=select-value]]:min-w-0">
                  <SelectValue placeholder="Content" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All</SelectItem>
                  <SelectItem value="emails">Emails</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="min-w-0 space-y-1">
              <Select
                value={oneHMarkerFilter}
                onValueChange={(value) => setOneHMarkerFilter(value as OneHMarkerFilter)}
              >
                <SelectTrigger className={`h-9 w-full min-w-0 gap-1 border-blue-300 bg-blue-50 px-2 text-xs font-black sm:w-[170px] sm:gap-2 sm:px-3 sm:text-sm [&_[data-slot=select-value]]:min-w-0 ${ONE_H_MARKER_OPTIONS.some((option) => option.value === oneHMarkerFilter) ? "text-red-600" : "text-[#0F2A5F]"}`}>
                  <SelectValue placeholder="Symbols" />
                </SelectTrigger>
                <SelectContent className="font-black text-[#0F2A5F]">
                  <SelectItem value="all">All symbols/default</SelectItem>
                  <SelectItem value="with">All with symbols</SelectItem>
                  <SelectItem value="none">No symbol</SelectItem>
                  {ONE_H_MARKER_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value} className="font-black text-red-600 focus:text-red-700">{option.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="col-span-2 min-w-0 space-y-1">
              <Input
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Search notes..."
                className="h-9 w-full sm:w-[220px]"
                aria-label="Search notes"
              />
            </div>
            <div className="col-span-2 flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              className="h-8 rounded-lg border-slate-300 bg-white px-3 text-sm text-slate-900 shadow-sm hover:bg-slate-50"
              onClick={async () => {
                const printWindow = window.open('', '_blank')
                if (!printWindow) return

                const previousNotesRenderLimit = notesRenderLimit
                if (notesRenderLimit < visibleNotes.length) {
                  setNotesRenderLimit(visibleNotes.length)
                  await new Promise<void>((resolve) => {
                    window.requestAnimationFrame(() => window.requestAnimationFrame(() => resolve()))
                  })
                }

                const tableContainer = document.querySelector('.notes-table-container')
                if (!tableContainer) {
                  setNotesRenderLimit(previousNotesRenderLimit)
                  printWindow.close()
                  return
                }

                const table = tableContainer.querySelector('table')
                if (!table) {
                  setNotesRenderLimit(previousNotesRenderLimit)
                  printWindow.close()
                  return
                }
                
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
                setNotesRenderLimit(previousNotesRenderLimit)
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
                    cell.style.width = '600px'
                    cell.style.maxWidth = '600px'
                    cell.style.whiteSpace = 'normal'
                    cell.style.wordWrap = 'break-word'
                  }
                })
                clonedTable.querySelectorAll('colgroup').forEach((col) => col.remove())
                
                printWindow.document.write(`
                  <!DOCTYPE html>
                  <html>
                    <head>
                      <title>Notes</title>
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
                          width: 350px;
                          max-width: 350px;
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
                      <div class="title">NOTES</div>
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
              disabled={exportingDailyReport}
              onClick={() => void exportDailyReport()}
            >
              {exportingDailyReport ? "Exporting..." : "Export Excel"}
            </Button>
            </div>
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
              <div className="w-full min-w-[1266px] sm:min-w-[1466px]">
                <table className="w-full table-fixed caption-bottom text-sm min-w-[1266px] sm:min-w-[1466px]">
                  <thead className="sticky top-0 z-50 bg-white shadow-md" style={{ position: 'sticky', top: 0, zIndex: 50 }}>
                    <tr className="bg-white" style={{ borderBottom: '1px solid rgb(51 65 85)' }}>
                      <th className="w-[40px] border border-slate-600 border-l-2 border-l-slate-800 bg-white text-foreground h-10 px-2 text-left align-middle font-medium" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)', whiteSpace: 'normal' }}>NR</th>
                      <th className="min-w-[280px] w-[280px] max-w-[280px] sm:min-w-[320px] sm:w-[320px] sm:max-w-[320px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }}>SHENIMI</th>
                      <th className="hidden sm:table-cell min-w-[170px] w-[170px] max-w-[170px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }}>PERSHKRIMI</th>
                      <th className="min-w-[50px] w-[50px] max-w-[50px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }} title="Diskutuar YES/JO?">DISK</th>
                      <th className="w-[96px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }}>DATA,ORA</th>
                      <th className="w-[106px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }}>EDITUAR</th>
                      <th className="w-[60px] border border-slate-600 bg-white text-foreground h-10 px-1.5 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }}>NGA</th>
                      <th className="min-w-[70px] w-[70px] max-w-[70px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }}>PER</th>
                      <th className="w-[60px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }}>DEP</th>
                      <th className="w-[90px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }}>PRJK</th>
                      <th className="w-[90px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }}>KRIJO DET</th>
                      <th className="w-[60px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }}>INT</th>
                      <th className="min-w-[80px] w-[80px] max-w-[80px] border border-slate-600 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }}>MBYLL</th>
                      <th className="min-w-[70px] w-[70px] max-w-[70px] border border-slate-600 border-r-2 border-r-slate-800 bg-white text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap" style={{ verticalAlign: 'bottom', borderBottom: '1px solid rgb(51 65 85)' }}>EDIT</th>
                    </tr>
                  </thead>
                  <tbody>
                  {renderedNotes.map((note, idx) => {
                    const isPxJavNote = note.source === "PX_JAV"
                    const creator = note.created_by ? userMap.get(note.created_by) : null
                    const creatorLabel =
                      creator?.full_name || creator?.username || "Unknown user"
                    const creatorInitials = getInitials(creatorLabel)
                    const creatorBadgeClasses =
                      creatorInitials === "GA"
                        ? "bg-rose-100 text-rose-800 border border-rose-200"
                        : creatorInitials === "KA"
                          ? "bg-blue-100 text-blue-800 border border-blue-200"
                          : "bg-slate-200 text-slate-700"
                    const noteDepartment = note.department_id ? departmentMap.get(note.department_id) : null
                    const noteProject = note.project_id ? projectMap.get(note.project_id) : null
                    const taskInfo = noteTaskInfo.get(note.id)
                    const taskDepartment = taskInfo?.taskDepartmentId
                      ? departmentMap.get(taskInfo.taskDepartmentId)
                      : null
                    const taskProject = taskInfo?.taskProjectId
                      ? projectMap.get(taskInfo.taskProjectId)
                      : null
                    const displayDepartment = noteDepartment || taskDepartment
                    const displayProject = noteProject || taskProject
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
                    const attachments = isPxJavNote ? [] : (note.attachments ?? [])
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
                    const lastEditedValue = getLastEditedValue(note, taskInfo)
                    const aggregatedStatus =
                      taskInfo && (taskInfo.taskStatuses?.length ?? 0) > 1
                        ? aggregateTaskStatus(taskInfo.taskStatuses)
                        : normalizeTaskStatus(taskInfo?.taskStatus)
                    const hasTask = Boolean(note.is_converted_to_task || taskInfo?.taskId)
                    const taskTypeLabels = taskInfo?.taskTypeLabels ?? []
                    const canAddAttachments = !isPxJavNote && !isClosed && aggregatedStatus !== "DONE"
                    const editDisabled = isClosed || loadingEditNote
                    const editDisabledTitle = isClosed
                      ? "Edit disabled when note is closed"
                      : "Edit"
                    const canCreateTask = !isPxJavNote && !isClosed && (!hasProject || isDevLinked)
                    const showManualOnly = hasProject && !isDevLinked
                    const shenimiCellClass = isClosed
                      ? "bg-slate-300 opacity-70"
                      : hasTask
                        ? aggregatedStatus === "TODO"
                          ? "bg-pink-200"
                          : aggregatedStatus === "IN_PROGRESS"
                            ? "bg-yellow-200"
                            : aggregatedStatus === "WAITING_CLIENT"
                              ? "bg-[#E2C15B] text-[#4F3A00]"
                              : aggregatedStatus === "DONE"
                                ? "bg-emerald-200"
                                : aggregatedStatus === "WAITING_CONFIRMATION"
                                  ? "bg-amber-50"
                                  : "bg-slate-100"
                        : note.from_mira
                          ? "bg-violet-100"
                          : "bg-sky-200"

                    // Only show department if:
                    // 1. Note has a project (always show projects)
                    // 2. We're currently filtering by department/project (on a specific page)
                    // 3. Note's department_id is different from user's department (explicitly set, not auto-assigned)
                    const miraCollapsed = Boolean(note.from_mira) && !expandedMiraNoteIds.has(note.id)
                    const isFilteredView = departmentId !== "ALL" || projectId !== "NONE"
                    const isExplicitDepartment = note.department_id && note.department_id !== user?.department_id
                    const shouldShowDepartment = displayDepartment && (displayProject || isFilteredView || isExplicitDepartment)
                    const mobileDeptAbbrev = displayDepartment ? abbreviateDepartmentName(displayDepartment.name) : null
                    const showMobileDeptBadge =
                      mobileDeptAbbrev === "DEV" || mobileDeptAbbrev === "GDS" || mobileDeptAbbrev === "PCM"

                    return (
                      <tr key={note.id} className="hover:bg-muted/50 border-b transition-colors">
                        <td className="font-bold text-muted-foreground border border-slate-600 border-l-2 border-l-slate-800 p-2 align-middle whitespace-nowrap" style={{ verticalAlign: 'bottom' }}>{idx + 1}</td>
                        <td className={`min-w-[280px] w-[280px] max-w-[280px] sm:min-w-[320px] sm:w-[320px] sm:max-w-[320px] whitespace-pre-wrap break-words border border-slate-600 p-2 align-middle ${shenimiCellClass}`} style={{ verticalAlign: 'bottom' }}>
                          <div className="flex flex-col gap-1">
                            <div className="flex items-start justify-between gap-2">
                              <div className="min-w-0 flex flex-wrap items-center gap-1">
                                {note.from_mira ? (
                                  <button
                                    type="button"
                                    className="flex min-w-0 items-center gap-2 rounded-md text-left hover:bg-violet-200/60"
                                    aria-expanded={!miraCollapsed}
                                    title={miraCollapsed ? "Hap shënimin e Mira-s" : "Mbyll shënimin e Mira-s"}
                                    onClick={() => toggleMiraNote(note.id)}
                                  >
                                    <img
                                      src="/mira-avatar.png"
                                      alt="Mira"
                                      className="h-10 w-10 shrink-0 rounded-full border-2 border-violet-300"
                                    />
                                    {miraCollapsed ? (
                                      <span className="min-w-0 text-sm font-semibold break-words">{miraNoteTitle(note.content)}</span>
                                    ) : null}
                                    {miraCollapsed ? (
                                      <ChevronDown className="h-4 w-4 shrink-0 text-violet-700" />
                                    ) : (
                                      <ChevronUp className="h-4 w-4 shrink-0 text-violet-700" />
                                    )}
                                  </button>
                                ) : null}
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
                                          const knownAssignee = assignee.id ? userMap.get(assignee.id) : null
                                          const assigneeLabel = assignee.full_name || assignee.username || knownAssignee?.full_name || knownAssignee?.username || "Unknown"
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
                                {isKnowledgeNote(note) ? (
                                  <Link
                                    href={`${KNOWLEDGE_CONFIG[note.knowledge_type || "PROMPT"].route}?view=notes`}
                                    className="inline-flex h-5 shrink-0 items-center rounded-md border border-violet-200 bg-violet-50 px-1.5 text-[10px] font-semibold uppercase tracking-wide text-violet-700 hover:bg-violet-100"
                                    title={noteKnowledgeText(note, "Kërkesë për prompt · Knowledge PX")}
                                  >
                                    {noteKnowledgeText(note, "Prompt")}
                                  </Link>
                                ) : null}
                                {miraCollapsed ? null : (
                                  <span id={`ga-note-content-${note.id}`} className="min-w-0 text-sm break-words">
                                    {note.one_h_marker ? <TaskMarkerComment comment={note.one_h_marker_comment} /> : null}
                                    {renderMarkedNoteContent(note.content, canViewStrikeTimestamps)}
                                  </span>
                                )}
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
                                <Button
                                  variant="outline"
                                  size="icon"
                                  disabled={editDisabled}
                                  aria-disabled={editDisabled}
                                  className={`h-7 w-7 shrink-0 ${editDisabled ? "opacity-50 cursor-not-allowed" : ""}`}
                                  aria-label={editDisabledTitle}
                                  title={editDisabledTitle}
                                  onClick={() => !editDisabled && void openEditNote(note)}
                                >
                                  <Pencil className="h-4 w-4" />
                                </Button>
                                {canAddAttachments || attachments.length > 0 ? (
                                  <Button
                                    variant="outline"
                                    size="icon"
                                    disabled={!canAddAttachments}
                                    aria-disabled={!canAddAttachments}
                                    className={`h-7 w-7 shrink-0 sm:hidden ${!canAddAttachments ? "opacity-50 cursor-not-allowed" : ""}`}
                                    title={
                                      canAddAttachments
                                        ? attachments.length > 0
                                          ? "Manage attachments"
                                          : "Add attachments"
                                        : "Attachments disabled for done tasks and closed notes"
                                    }
                                    aria-label={
                                      canAddAttachments
                                        ? attachments.length > 0
                                          ? "Manage attachments"
                                          : "Add attachments"
                                        : "Attachments disabled"
                                    }
                                    onClick={() => canAddAttachments && openAttachmentsForNote(note.id)}
                                  >
                                    {attachments.length > 0 ? <ImageIcon className="h-4 w-4" /> : <Paperclip className="h-4 w-4" />}
                                  </Button>
                                ) : null}
                                {hasTask && aggregatedStatus === "WAITING_CONFIRMATION" && note.status !== "CLOSED" ? (
                                  <Button
                                    variant="outline"
                                    size="icon"
                                    disabled={markingDoneNoteId === note.id}
                                    className="h-7 w-7 shrink-0 sm:hidden border-emerald-200 text-emerald-700 hover:bg-emerald-50 disabled:opacity-60"
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
                                    className="h-7 w-7 shrink-0 sm:hidden"
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
                              {lastEditedValue
                                ? (() => {
                                    const parts = formatDateParts(lastEditedValue)
                                    return parts.time ? `${parts.date}, ${parts.time}` : parts.date
                                  })()
                                : null}
                            </div>
                            <div className="flex items-center gap-2">
                              {note.priority ? (
                                <Badge className={`text-[10px] px-1.5 py-0 ${PRIORITY_BADGE[note.priority as Exclude<NotePriority, "NONE">]}`}>
                                  {note.priority}
                                </Badge>
                              ) : null}
                              {isPxJavNote ? (
                                <Badge
                                  variant="outline"
                                  className="text-[10px] px-1.5 py-0 bg-indigo-50 text-indigo-700 border-indigo-200 font-semibold"
                                  title="Task created from PX JAV"
                                >
                                  PX JAV
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
                        <td className="hidden sm:table-cell border border-slate-600 p-2 align-middle whitespace-pre-wrap text-xs text-slate-700 min-w-[170px] w-[170px] max-w-[170px]" style={{ verticalAlign: 'bottom' }}>
                          {taskInfo?.description || attachments.length > 0 ? (
                            <div className="space-y-2">
                              {canAddAttachments || attachments.length > 0 ? (
                                <div className="flex justify-end">
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    disabled={!canAddAttachments}
                                    aria-disabled={!canAddAttachments}
                                    className={`h-6 text-[10px] ${!canAddAttachments ? "opacity-50 cursor-not-allowed" : ""}`}
                                    title={canAddAttachments ? undefined : "Attachments disabled for done tasks and closed notes"}
                                    onClick={() => canAddAttachments && openAttachmentsForNote(note.id)}
                                  >
                                    {attachments.length > 0 ? "Manage files" : "Add files"}
                                  </Button>
                                </div>
                              ) : null}
                              {taskInfo?.description ? (
                                promptHrefFromText(taskInfo.description) ? (
                                  <PromptLinkButton text={taskInfo.description} compact />
                                ) : (
                                  <div className="break-words [overflow-wrap:anywhere]">{taskInfo.description}</div>
                                )
                              ) : null}
                              {attachments.length > 0 ? (
                                <div className="space-y-1">
                                  {attachments.map((attachment) => (
                                    <button
                                      key={attachment.id}
                                      type="button"
                                      className="flex w-full min-w-0 items-start gap-1.5 rounded border border-slate-200 bg-white px-2 py-1.5 text-left transition-colors hover:border-blue-300 hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                                      title={`Open ${attachment.original_filename}`}
                                      onClick={() => void openAttachmentPreview(attachment)}
                                    >
                                      <Paperclip className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-500" />
                                      <span className="min-w-0 flex-1">
                                        <span className="block truncate text-xs font-medium text-blue-700 underline underline-offset-2">
                                          {attachment.original_filename}
                                        </span>
                                        <span className="block text-[10px] text-slate-500">
                                          {formatFileSize(attachment.size_bytes)}
                                        </span>
                                      </span>
                                    </button>
                                  ))}
                                </div>
                              ) : null}
                            </div>
                          ) : (
                            <div className="flex justify-end">
                              <Button
                                variant="outline"
                                size="sm"
                                disabled={!canAddAttachments}
                                aria-disabled={!canAddAttachments}
                                className={`h-6 text-[10px] ${!canAddAttachments ? "opacity-50 cursor-not-allowed" : ""}`}
                                title={canAddAttachments ? undefined : "Attachments disabled for done tasks and closed notes"}
                                onClick={() => canAddAttachments && openAttachmentsForNote(note.id)}
                              >
                                Add files
                              </Button>
                            </div>
                          )}
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
                        <td className="border border-slate-600 p-2 align-middle whitespace-nowrap w-[96px]" style={{ verticalAlign: 'bottom' }}>
                          {(() => {
                            const parts = formatDateParts(note.created_at)
                            return (
                              <div className="leading-tight">
                                {parts.time ? <div>{parts.time}</div> : null}
                                <div>{parts.date}</div>
                              </div>
                            )
                          })()}
                        </td>
                        <td className="border border-slate-600 p-2 align-middle whitespace-nowrap w-[106px]" style={{ verticalAlign: 'bottom' }}>
                          {lastEditedValue ? (
                            (() => {
                              const parts = formatDateParts(lastEditedValue)
                              return (
                                <div className="leading-tight">
                                  {parts.time ? <div>{parts.time}</div> : null}
                                  <div>{parts.date}</div>
                                </div>
                              )
                            })()
                          ) : null}
                        </td>
                        <td className="w-[60px] border border-slate-600 p-1.5 align-middle whitespace-nowrap" style={{ verticalAlign: 'bottom' }}>
                          <div className="flex items-center gap-2 text-xs">
                            <div
                              className={`flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-semibold ${creatorBadgeClasses}`}
                              title={creatorLabel}
                            >
                              {creatorInitials}
                            </div>
                          </div>
                        </td>
                        <td className="border border-slate-600 p-2 align-middle whitespace-nowrap min-w-[70px] w-[70px] max-w-[70px]" style={{ verticalAlign: 'bottom' }}>
                          {!note.is_converted_to_task ? (
                            <span className="text-xs text-slate-500">-</span>
                          ) : assignees.length === 0 ? (
                            <span className="text-xs text-slate-500">-</span>
                          ) : (
                            <div className="flex items-center gap-1 flex-wrap">
                              {assignees.map((assignee, assigneeIdx) => {
                                const knownAssignee = assignee.id ? userMap.get(assignee.id) : null
                                const assigneeLabel = assignee.full_name || assignee.username || knownAssignee?.full_name || knownAssignee?.username || "Unknown"
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
                                    className={`flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-semibold ${assigneeBadgeClasses}`}
                                    title={assigneeLabel}
                                  >
                                    {assigneeInitials}
                                  </div>
                                )
                              })}
                            </div>
                          )}
                        </td>
                        <td className="border border-slate-600 p-2 align-middle whitespace-nowrap" style={{ verticalAlign: 'bottom' }}>
                          {shouldShowDepartment && displayDepartment ? (
                            <Badge variant="outline" className="text-[10px] bg-amber-50 text-amber-700 border-amber-200 whitespace-normal text-left">
                              {abbreviateDepartmentName(displayDepartment.name)}
                            </Badge>
                          ) : null}
                        </td>
                        <td className="border border-slate-600 p-2 align-middle whitespace-nowrap w-[90px]" style={{ verticalAlign: 'bottom' }}>
                          {displayProject ? (
                            <Badge variant="outline" className="text-[10px] bg-indigo-50 text-indigo-700 border-indigo-200 whitespace-normal text-left">
                              {displayProject.title || displayProject.name || "Project"}
                            </Badge>
                          ) : null}
                        </td>
                        <td className="border border-slate-600 p-2 align-middle whitespace-nowrap min-w-[70px] w-[70px] max-w-[70px]" style={{ verticalAlign: 'bottom' }}>
                          <div className="flex justify-center">
                            {hasTask ? (
                              <Badge variant="outline" className="text-[10px] px-1.5 py-0 bg-purple-50 text-purple-700 border-purple-200 h-7 flex items-center text-center">
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
                              size="icon"
                              disabled={editDisabled}
                              aria-disabled={editDisabled}
                              aria-label={editDisabledTitle}
                              title={editDisabledTitle}
                              className={`h-7 w-7 shrink-0 ${editDisabled ? "opacity-50 cursor-not-allowed" : ""}`}
                              onClick={() => !editDisabled && void openEditNote(note)}
                            >
                              <Pencil className="h-4 w-4" />
                            </Button>
                          </div>
                        </td>
                      </tr>
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
                  {renderMarkedNoteContent(attachmentsDialogNote.content, canViewStrikeTimestamps)}
                </div>
              </div>
              {attachmentsDialogCanAddFiles ? (
                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-3">
                    <Label>Add files</Label>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="gap-2"
                      disabled={uploadingAttachments}
                      onClick={() => attachmentUploadInputRef.current?.click()}
                    >
                      <Cloud className="h-4 w-4 text-blue-600" />
                      Choose from OneDrive / computer
                    </Button>
                  </div>
                  <Input
                    ref={attachmentUploadInputRef}
                    type="file"
                    multiple
                    className="sr-only"
                    onChange={handleAttachmentUploadSelection}
                    disabled={uploadingAttachments}
                  />
                  {attachmentUploadFiles.length === 0 ? (
                    <div className="text-xs text-muted-foreground">
                      Select files from your computer or from the locally synchronized OneDrive folder. Max {MAX_ATTACHMENT_FILES} files, {MAX_ATTACHMENT_MB}MB each.
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
          {attachmentDialogItems.length === 0 ? (
            <div className="text-sm text-slate-500">No attachments yet.</div>
          ) : (
            <div className="max-h-[70vh] space-y-3 overflow-y-auto pr-1">
              {attachmentDialogItems.map((item) => {
                const isDeleting = deletingAttachmentIds.includes(item.attachment.id)
                return (
                  <div key={item.attachment.id} className="rounded-lg border border-slate-200 bg-white p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <button
                          type="button"
                          className="block max-w-full truncate text-left text-sm font-medium text-blue-700 underline underline-offset-2 hover:text-blue-900"
                          title={`Open ${item.attachment.original_filename}`}
                          onClick={() => void openAttachmentPreview(item.attachment)}
                        >
                          {item.attachment.original_filename}
                        </button>
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
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-7 text-xs"
                          onClick={() => void openAttachmentPreview(item.attachment)}
                        >
                          Preview
                        </Button>
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
            setPreviewContentType(null)
            setPreviewAttachment(null)
          }
        }}
      >
        <DialogContent className="w-[96vw] sm:max-w-5xl">
          <DialogHeader>
            <div className="flex items-center justify-between gap-3 pr-6">
              <DialogTitle className="min-w-0 truncate" title={previewTitle || undefined}>
                {previewTitle || "Attachment preview"}
              </DialogTitle>
              {previewAttachment ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="shrink-0"
                  onClick={() => void downloadAttachment(previewAttachment)}
                >
                  Download
                </Button>
              ) : null}
            </div>
          </DialogHeader>
          {previewUrl ? (
            <div className="flex h-[72vh] items-center justify-center overflow-hidden rounded border border-slate-200 bg-white">
              {previewContentType?.startsWith("image/") ? (
                <img src={previewUrl} alt={previewTitle || "Attachment preview"} className="max-h-full max-w-full object-contain" />
              ) : previewContentType?.startsWith("audio/") ? (
                <audio src={previewUrl} controls className="w-[min(90%,640px)]" />
              ) : previewContentType?.startsWith("video/") ? (
                <video src={previewUrl} controls className="max-h-full max-w-full" />
              ) : (
                <iframe
                  src={previewUrl}
                  title={previewTitle || "Attachment preview"}
                  className="h-full w-full border-0 bg-white"
                />
              )}
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
              <div className={`grid gap-2 ${taskPriority === "1H" ? "md:grid-cols-3" : "md:grid-cols-2"}`}>
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
                      if (nextPriority !== "1H") {
                        setTaskOneHReportSlot(ONE_H_REPORT_SLOT_NONE_VALUE)
                      }
                    }}
                  >
                    <SelectTrigger className="w-full">
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
                    }}
                  >
                    <SelectTrigger className="w-full">
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
                          {resolveProjectTitle(p) || "Untitled project"}
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
                <Label>
                  {isKnowledgeNote(taskDialogNote) ? noteKnowledgeText(taskDialogNote, "Assign to · Krijuesi i promptit") : "Assign to"}
                </Label>
                <div className="rounded-md border bg-white p-2">
                  <div className="flex flex-wrap gap-2 mb-2">
                    {taskAssigneeIds.length === 0 ? (
                      <span className="text-xs text-muted-foreground">No assignees selected.</span>
                    ) : (
                      taskAssigneeIds.map((id) => {
                        const person = taskAssigneeOptions.find((p) => p.id === id)
                        const label = taskAssigneeLabel(person, id)
                        return (
                          <button
                            key={id}
                            type="button"
                            className="flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs"
                            onClick={() =>
                              setTaskAssigneeIds((prev) => prev.filter((item) => item !== id))
                            }
                          >
                            <span>{label}</span>
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
                            <span className="flex items-center gap-1">
                              <span>{taskAssigneeLabel(person, person.id)}</span>
                              {taskAssigneePvBadge(person.id)}
                            </span>
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                </div>
                {taskDepartmentIds.length === 0 ? (
                  <p className="text-xs text-muted-foreground">Select one or more departments to guide projects (optional).</p>
                ) : null}
              </div>
              {isKnowledgeNote(taskDialogNote) ? (
                <div className="space-y-2 rounded-md border border-violet-200 bg-violet-50/60 p-2">
                  <Label>{noteKnowledgeText(taskDialogNote, "Testuesi i promptit")}</Label>
                  <Select value={taskPromptTesterId || undefined} onValueChange={setTaskPromptTesterId}>
                    <SelectTrigger className="bg-white">
                      <SelectValue placeholder={noteKnowledgeText(taskDialogNote, "Zgjidh personin që do ta testojë promptin")} />
                    </SelectTrigger>
                    <SelectContent>
                      {taskAssigneeOptions
                        .filter((person) => person.id && person.is_active !== false && !taskAssigneeIds.includes(person.id))
                        .map((person) => (
                          <SelectItem key={person.id} value={person.id}>
                            {taskAssigneeLabel(person, person.id)}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">
                    {noteKnowledgeText(taskDialogNote, 'Kur shtohet prompti, testuesit i krijohet detyra "PROMPT: TESTO: Titulli". Kjo detyrë mbyllet vetëm pasi testuesi ta konfirmojë testimin; atëherë mbyllen automatikisht të dyja detyrat.')}
                  </p>
                </div>
              ) : null}
              <TaskSkillField
                value={taskSkillCategory}
                onChange={(category) => {
                  skillInferenceRequestRef.current += 1
                  setTaskSkillCategory(category)
                  setTaskSkillAutoSuggested(false)
                  setTaskSkillAiReason("")
                }}
                disabled={creatingTask}
                selectedAssigneeIds={taskAssigneeIds}
                onSelectCandidate={(candidateId) => {
                  setTaskAssigneeIds((previous) => previous.includes(candidateId) ? previous : [...previous, candidateId])
                  const person = users.find((item) => item.id === candidateId)
                  if (person?.department_id) {
                    setTaskDepartmentIds((previous) => previous.includes(person.department_id as string)
                      ? previous
                      : [...previous, person.department_id as string])
                  }
                }}
              />
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <span className="text-muted-foreground">
                  {taskSkillAutoSuggested && taskSkillCategory
                    ? `${taskSkillAiReason ? "Sugjeruar nga AI" : "Sugjeruar automatikisht"}: ${SKILL_CATEGORIES.find((item) => item.id === taskSkillCategory)?.label || taskSkillCategory}${taskSkillAiReason ? ` — ${taskSkillAiReason}` : ""}`
                    : "Mund ta rianalizosh pasi të ndryshosh titullin ose përshkrimin."}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  disabled={taskSkillAiLoading}
                  onClick={() => {
                    const inferred = inferSkillCategory(taskTitle, taskDescription, taskDialogNote.content)
                    setTaskSkillCategory(inferred)
                    setTaskSkillAutoSuggested(Boolean(inferred))
                    setTaskSkillAiReason("")
                    void requestAiSkillCategory(taskTitle, `${taskDescription}\n${taskDialogNote.content || ""}`).then((usedAi) => {
                      if (!usedAi && !inferred) toast.info("Nuk u identifikua një kategori e qartë; zgjidhe manualisht.")
                    })
                  }}
                >
                  {taskSkillAiLoading ? "Duke analizuar me AI…" : "Analizo me AI përsëri"}
                </Button>
              </div>
            </div>
              <div className="flex shrink-0 justify-end gap-2 border-t border-slate-200 bg-background pt-3">
                <Button variant="outline" onClick={() => setTaskDialogNoteId(null)}>
                  Cancel
                </Button>
                <Button disabled={creatingTask} onClick={() => void createTaskFromNote(taskDialogNote)}>
                  {creatingTask ? "Creating..." : "Create task"}
                </Button>
              </div>
            </>
          ) : null}
        </DialogContent>
      </Dialog>

      {editDialog}
    </div>
  )
}
