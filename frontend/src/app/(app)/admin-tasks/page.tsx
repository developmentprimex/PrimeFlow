"use client"

import * as React from "react"
import { createPortal } from "react-dom"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { API_HTTP_URL } from "@/lib/config"
import { useAuth } from "@/lib/auth"
import { TaskOneHMarker } from "@/components/task-one-h-marker"
import { useConfirm } from "@/components/providers/confirm-dialog-provider"
import { formatDateDMY, formatDateTimeDMY, toDateInputValue } from "@/lib/dates"
import { cn } from "@/lib/utils"
import { fetchUsersLookupCached } from "@/lib/users-cache"
import { getConfirmerCandidates, isWaitingConfirmation, validateWaitingConfirmation } from "@/lib/task-confirmation"
import { weeklyPlanStatusBgClass } from "@/lib/weekly-plan-status"
import { getPlainMarkedText, renderMarkedNoteContent } from "@/lib/note-markup"
import { buildRepeatedTaskFirstDateMap, isRepeatedTaskInstance } from "@/lib/repeated-task-visibility"
import { internalMeetingLegendTone, isManualInternalMeeting, meetingLegendTone } from "@/lib/meeting-tone"
import { Plus, Pencil, Trash2 } from "lucide-react"
import { EmbeddedPrintReportGenerator } from "../tomorrow-print-report/page"
import type {
  DailyReportResponse,
  DailyReportSystemOccurrence,
  Department,
  SystemTaskOut,
  SystemTaskScope,
  Task,
  TaskFinishPeriod,
  TaskPriority,
  User,
  UserLookup,
} from "@/lib/types"

const FINISH_PERIOD_NONE_VALUE = "__none__"
const PRIORITY_OPTIONS: TaskPriority[] = ["NORMAL", "HIGH", "BLLOK"]
const FINISH_PERIOD_OPTIONS: TaskFinishPeriod[] = ["AM", "PM"]
const FINISH_PERIOD_NONE_LABEL = "None (all day)"
const TASK_STATUS_OPTIONS = ["TODO", "IN_PROGRESS", "WAITING_CLIENT", "WAITING_CONFIRMATION", "DONE"] as const
const SYSTEM_STATUS_OPTIONS = ["OPEN", "DONE"] as const
type AdminTasksSectionId = "all-tasks" | "common" | "ga-time" | "one-h-print"

// Last loaded GA time table data, kept on the device so the table paints at
// once on the next visit while fresh data is fetched behind it.
const GA_VIEW_CACHE_PREFIX = "primeflow-ga-view:"
function readGaViewCache<T>(key: string): T | null {
  try {
    const raw = window.localStorage.getItem(GA_VIEW_CACHE_PREFIX + key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    return null
  }
}
function writeGaViewCache(key: string, value: unknown) {
  try {
    // One entry per kind: older weeks are dropped so storage cannot fill up.
    const kind = key.split("|")[0]
    for (let index = window.localStorage.length - 1; index >= 0; index -= 1) {
      const existing = window.localStorage.key(index)
      if (existing?.startsWith(`${GA_VIEW_CACHE_PREFIX}${kind}|`)) window.localStorage.removeItem(existing)
    }
    window.localStorage.setItem(GA_VIEW_CACHE_PREFIX + key, JSON.stringify(value))
  } catch {
    // Storage full or blocked: the table simply loads from the network.
  }
}

function findGaneUser<T extends { username?: string | null }>(users: T[]): T | null {
  return (
    users.find((person) => {
      const username = person.username?.toLowerCase()
      const email =
        "email" in person && typeof person.email === "string" ? person.email.toLowerCase() : null
      return username === "gane.arifaj" || email === "ga@primexeu.com"
    }) ?? null
  )
}
function findGaDepartmentId(departments: Department[]): string | null {
  const byCode = departments.find((dept) => dept.code?.toUpperCase() === "GA")
  if (byCode) return byCode.id
  const byName = departments.find((dept) => dept.name?.toUpperCase().includes("GA"))
  return byName?.id ?? null
}
// Ids of Gane and the GA department from the last visit, so the small GA task
// list can be requested at once instead of waiting for users/departments.
const GA_IDS_STORAGE_KEY = "primeflow-admin-tasks:ga-ids"
function readGaIds(): { userId: string; departmentId: string | null } | null {
  try {
    const raw = window.localStorage.getItem(GA_IDS_STORAGE_KEY)
    return raw ? (JSON.parse(raw) as { userId: string; departmentId: string | null }) : null
  } catch {
    return null
  }
}
function writeGaIds(value: { userId: string; departmentId: string | null }) {
  try {
    window.localStorage.setItem(GA_IDS_STORAGE_KEY, JSON.stringify(value))
  } catch {
    // Storage blocked: the ids are looked up again next time.
  }
}

// The main task lists are too large for localStorage, so the last loaded copy
// lives in IndexedDB. The page paints from it at once and refreshes behind it.
const ADMIN_TASKS_IDB_NAME = "primeflow-admin-tasks"
const ADMIN_TASKS_IDB_STORE = "cache"
function openAdminTasksDb(): Promise<IDBDatabase | null> {
  return new Promise((resolve) => {
    try {
      const request = window.indexedDB.open(ADMIN_TASKS_IDB_NAME, 1)
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains(ADMIN_TASKS_IDB_STORE)) {
          request.result.createObjectStore(ADMIN_TASKS_IDB_STORE)
        }
      }
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => resolve(null)
      request.onblocked = () => resolve(null)
    } catch {
      resolve(null)
    }
  })
}
async function readAdminTasksCache<T>(key: string): Promise<T | null> {
  const db = await openAdminTasksDb()
  if (!db) return null
  return new Promise((resolve) => {
    try {
      const request = db.transaction(ADMIN_TASKS_IDB_STORE, "readonly").objectStore(ADMIN_TASKS_IDB_STORE).get(key)
      request.onsuccess = () => resolve((request.result as T | undefined) ?? null)
      request.onerror = () => resolve(null)
    } catch {
      resolve(null)
    } finally {
      db.close()
    }
  })
}
async function writeAdminTasksCache(key: string, value: unknown) {
  const db = await openAdminTasksDb()
  if (!db) return
  try {
    const store = db.transaction(ADMIN_TASKS_IDB_STORE, "readwrite").objectStore(ADMIN_TASKS_IDB_STORE)
    // One entry per user: switching accounts on a device replaces the old copy.
    store.clear()
    store.put(value, key)
  } catch {
    // Storage full or blocked: the page simply loads from the network.
  } finally {
    db.close()
  }
}
const NO_PROJECT_TYPES = [
  { id: "normal", label: "Normal", description: "General tasks without a project." },
  { id: "personal", label: "Personal", description: "Personal tasks tracked only in this view." },
  { id: "blocked", label: "BLLOK", description: "Blocked all day by a single task." },
  { id: "hourly", label: "1H", description: "Hourly meeting/reporting task." },
  { id: "r1", label: "R1", description: "First case must be discussed with the manager." },
] as const

// Date utility functions
const pad2 = (n: number) => String(n).padStart(2, "0")
const toISODate = (d: Date) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
const toDDMMYYYY = (isoDate: string) => {
  if (!isoDate) return ""
  const [y, m, d] = isoDate.split("-").map(Number)
  return `${pad2(d)}/${pad2(m)}/${y}`
}
const fromDDMMYYYY = (ddmmyyyy: string) => {
  if (!ddmmyyyy) return ""
  const parts = ddmmyyyy.split("/")
  if (parts.length !== 3) return ""
  const [d, m, y] = parts.map(Number)
  if (isNaN(d) || isNaN(m) || isNaN(y)) return ""
  if (d < 1 || d > 31 || m < 1 || m > 12) return ""
  return `${y}-${pad2(m)}-${pad2(d)}`
}
const DAY_OPTIONS = [
  { value: "all", label: "All days" },
  { value: "0", label: "Monday" },
  { value: "1", label: "Tuesday" },
  { value: "2", label: "Wednesday" },
  { value: "3", label: "Thursday" },
  { value: "4", label: "Friday" },
  { value: "5", label: "Saturday" },
  { value: "6", label: "Sunday" },
]

// --- Bold-only editor (same behavior as System Tasks) ---
const BOLD_TAG_PATTERN = /<(strong|b|br|div|p)(\s|>|\/)/i

function escapeHtml(value: string) {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
}

function sanitizeBoldOnlyHtml(raw: string) {
  if (typeof document === "undefined") return raw
  const container = document.createElement("div")
  container.innerHTML = raw

  const unwrapBlockElements = (el: Element) => {
    const blocks = el.querySelectorAll("div, p")
    Array.from(blocks)
      .reverse()
      .forEach((block) => {
        const parent = block.parentNode
        if (!parent) return
        while (block.firstChild) {
          parent.insertBefore(block.firstChild, block)
        }
        parent.removeChild(block)
      })
  }
  unwrapBlockElements(container)

  const clean = document.createElement("div")

  const sanitizeNode = (node: Node): Node[] => {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = node.textContent ?? ""
      return text.length > 0 ? [document.createTextNode(text)] : []
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return []
    const el = node as HTMLElement
    const tag = el.tagName
    if (tag === "BR") return [document.createElement("br")]
    const children = Array.from(el.childNodes).flatMap(sanitizeNode)
    if (tag === "B" || tag === "STRONG") {
      const strong = document.createElement("strong")
      children.forEach((child) => strong.appendChild(child))
      return [strong]
    }
    if (tag === "SPAN") {
      const weight = el.style.fontWeight || el.getAttribute("data-weight") || ""
      const numericWeight = Number.parseInt(weight, 10)
      const isBold =
        weight.toLowerCase() === "bold" || (!Number.isNaN(numericWeight) && numericWeight >= 600)
      if (isBold) {
        const strong = document.createElement("strong")
        children.forEach((child) => strong.appendChild(child))
        return [strong]
      }
      return children
    }
    return children
  }

  Array.from(container.childNodes).forEach((node) => {
    sanitizeNode(node).forEach((child) => clean.appendChild(child))
  })

  clean.normalize()

  const text = clean.textContent?.replace(/\s+/g, "") ?? ""
  if (!text) return ""
  return clean.innerHTML
}

function normalizeBoldValue(value: string) {
  if (!value) return ""
  if (typeof document === "undefined") return value
  if (BOLD_TAG_PATTERN.test(value)) return sanitizeBoldOnlyHtml(value)
  const container = document.createElement("div")
  const lines = value.split(/\r?\n/)
  lines.forEach((line, index) => {
    container.appendChild(document.createTextNode(line))
    if (index < lines.length - 1) container.appendChild(document.createElement("br"))
  })
  return container.innerHTML
}

type BoldOnlyEditorProps = {
  value: string
  onChange: (value: string) => void
}

function BoldOnlyEditor({ value, onChange }: BoldOnlyEditorProps) {
  const editorRef = React.useRef<HTMLDivElement | null>(null)

  React.useEffect(() => {
    if (!editorRef.current) return
    const normalized = normalizeBoldValue(value)
    if (editorRef.current.innerHTML !== normalized) {
      editorRef.current.innerHTML = normalized
    }
  }, [value])

  const commitChange = React.useCallback(() => {
    if (!editorRef.current) return
    const sanitized = sanitizeBoldOnlyHtml(editorRef.current.innerHTML)
    if (sanitized !== editorRef.current.innerHTML) {
      editorRef.current.innerHTML = sanitized
    }
    onChange(sanitized)
  }, [onChange])

  const handleInput = React.useCallback(() => {
    if (!editorRef.current) return
    onChange(editorRef.current.innerHTML)
  }, [onChange])

  const [isBold, setIsBold] = React.useState(false)

  const checkBoldState = React.useCallback(() => {
    if (typeof document !== "undefined") {
      setIsBold(document.queryCommandState("bold"))
    }
  }, [])

  const applyBold = React.useCallback(() => {
    if (!editorRef.current) return
    editorRef.current.focus()
    document.execCommand("bold", false)
    checkBoldState()
    commitChange()
  }, [commitChange, checkBoldState])

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <button
          type="button"
          className={`inline-flex h-8 w-8 items-center justify-center rounded-md border text-sm font-semibold shadow-sm transition ${
            isBold
              ? "border-blue-500 bg-blue-100 text-blue-700"
              : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
          }`}
          onMouseDown={(event) => event.preventDefault()}
          onClick={applyBold}
          aria-label="Bold"
          aria-pressed={isBold}
        >
          B
        </button>
        <span className="text-xs text-muted-foreground">Bold only</span>
      </div>
      <div
        ref={editorRef}
        contentEditable
        role="textbox"
        aria-multiline="true"
        className="border-input focus-visible:border-ring focus-visible:ring-ring/50 min-h-20 w-full rounded-md border bg-transparent px-3 py-2 text-base shadow-xs outline-none transition-[color,box-shadow] focus-visible:ring-[3px] md:text-sm whitespace-pre-wrap"
        onInput={handleInput}
        onBlur={commitChange}
        onSelect={checkBoldState}
        onKeyUp={checkBoldState}
        onMouseUp={checkBoldState}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault()
            document.execCommand("insertLineBreak")
            handleInput()
            return
          }
          if (event.ctrlKey || event.metaKey) {
            const key = event.key.toLowerCase()
            if (key === "b") {
              event.preventDefault()
              applyBold()
              return
            }
            if (["i", "u"].includes(key)) {
              event.preventDefault()
            }
          }
        }}
        onPaste={(event) => {
          event.preventDefault()
          const text = event.clipboardData.getData("text/plain")
          if (!text) return
          const html = escapeHtml(text)
            .replace(/\r\n/g, "\n")
            .replace(/\r/g, "\n")
            .replace(/\n/g, "<br>")
          document.execCommand("insertHTML", false, html)
          commitChange()
        }}
        suppressContentEditableWarning
      />
    </div>
  )
}

function formatDateDayMonth(value?: string | null) {
  if (!value) return "-"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "-"
  return date.toLocaleDateString("en-GB", { month: "2-digit", day: "2-digit" })
}

function getMondayBasedDay(date: Date) {
  return (date.getDay() + 6) % 7
}

const MS_PER_DAY = 24 * 60 * 60 * 1000

function initials(src: string) {
  return src
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("")
}

type AllTasksAssigneeBadge = { id: string; userId: string; value: string; label: string }

function systemFrequencyTitle(frequency?: string | null) {
  const normalized = (frequency || "").toUpperCase()
  if (normalized === "DAILY") return "Daily"
  if (normalized === "WEEKLY") return "Weekly"
  if (normalized === "MONTHLY") return "Monthly"
  if (normalized === "YEARLY") return "Yearly"
  if (normalized === "3_MONTHS") return "Every 3 months"
  if (normalized === "6_MONTHS") return "Every 6 months"
  return normalized || ""
}

function systemFrequencyDisplayLabel(frequency?: string | null) {
  const normalized = (frequency || "").toUpperCase()
  if (normalized === "DAILY") return "Daily"
  if (normalized === "WEEKLY") return "Weekly"
  if (normalized === "MONTHLY") return "Monthly"
  if (normalized === "YEARLY") return "Yearly"
  if (normalized === "3_MONTHS") return "3M"
  if (normalized === "6_MONTHS") return "6M"
  return normalized || ""
}

const SYSTEM_FREQUENCY_SORT_ORDER: Record<string, number> = {
  DAILY: 0,
  WEEKLY: 1,
  MONTHLY: 2,
  "3_MONTHS": 3,
  "6_MONTHS": 4,
  YEARLY: 5,
}

function systemFrequencySortOrder(frequency?: string | null) {
  return SYSTEM_FREQUENCY_SORT_ORDER[(frequency || "").toUpperCase()] ?? 99
}

function compareSystemFrequency(first?: string | null, second?: string | null) {
  return systemFrequencySortOrder(first) - systemFrequencySortOrder(second)
}

function mergeAllTasksAssigneeBadges(a: AllTasksAssigneeBadge[], b: AllTasksAssigneeBadge[]): AllTasksAssigneeBadge[] {
  const map = new Map<string, AllTasksAssigneeBadge>()
  for (const item of [...a, ...b]) {
    if (!map.has(item.userId)) map.set(item.userId, item)
  }
  return Array.from(map.values()).sort((x, y) => x.label.localeCompare(y.label))
}

function dayKey(date: Date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
}

function toDate(value?: string | null) {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return date
}

function toDateOnlyIso(value?: string | null) {
  const date = toDate(value)
  if (!date) return ""
  return toISODate(new Date(date.getFullYear(), date.getMonth(), date.getDate()))
}

function systemTaskDisplayDate(task: SystemTaskOut): string | null {
  return task.effective_occurrence_date || task.next_occurrence_date || task.occurrence_date || null
}

function getTaskDateIso(task: Task): string {
  const isSystemTask = Boolean(task.system_template_origin_id || task.task_type === "system")
  const isDone = (task.status || "").toUpperCase() === "DONE" || Boolean(task.completed_at)
  if (isSystemTask && isDone) {
    return toDateOnlyIso(
      task.original_due_date || task.origin_run_at || task.start_date || task.due_date || null
    )
  }
  return toDateOnlyIso(task.due_date || task.start_date || null)
}

function formatTaskDateRangeDisplay(task: Pick<Task, "start_date" | "due_date">): string {
  const startIso = toDateOnlyIso(task.start_date || null)
  const dueIso = toDateOnlyIso(task.due_date || null)
  if (startIso && dueIso) {
    if (startIso === dueIso) return toDDMMYYYY(startIso)
    return `${toDDMMYYYY(startIso)} - ${toDDMMYYYY(dueIso)}`
  }
  if (dueIso) return toDDMMYYYY(dueIso)
  if (startIso) return toDDMMYYYY(startIso)
  return "-"
}

function isIsoWithinInclusiveRange(targetIso: string, startIso?: string | null, endIso?: string | null) {
  if (!targetIso) return false
  const normalizedStart = startIso || endIso || ""
  const normalizedEnd = endIso || startIso || ""
  if (!normalizedStart || !normalizedEnd) return false
  if (normalizedStart <= normalizedEnd) {
    return targetIso >= normalizedStart && targetIso <= normalizedEnd
  }
  return targetIso >= normalizedEnd && targetIso <= normalizedStart
}

function getSystemDateIso(task: SystemTaskOut): string {
  return toDateOnlyIso(systemTaskDisplayDate(task) || null)
}

function dayDiffInclusive(fromIso: string, toIso: string) {
  if (!fromIso || !toIso) return 0
  const fromDate = fromISODate(fromIso)
  const toDate = fromISODate(toIso)
  const msPerDay = 24 * 60 * 60 * 1000
  return Math.max(0, Math.round((toDate.getTime() - fromDate.getTime()) / msPerDay))
}

function parseInternalNotes(notes?: string | null) {
  if (!notes) return {}
  const values: Record<string, string> = {}
  for (const raw of notes.split("\n")) {
    if (!raw.includes(":")) continue
    const [key, ...rest] = raw.split(":")
    const value = rest.join(":").trim()
    const normalizedKey = (key || "").trim().toUpperCase()
    if (!normalizedKey || !value) continue
    values[normalizedKey] = value
  }
  return values
}

function formatInternalDetails(notes?: string | null) {
  const values = parseInternalNotes(notes)
  const regj = values["REGJ"] || "-"
  const path = values["PATH"] || "-"
  const check = values["CHECKLISTA"] || values["CHECK"] || "-"
  const training = values["TRAINING"] || "-"
  const bzGroup = values["BZ GROUP"] || "-"
  if ([regj, path, check, training, bzGroup].every((value) => value === "-")) {
    return ""
  }
  return [
    `1.REGJ: ${regj}`,
    `2.PATH: ${path}`,
    `3.CHECKLISTA: ${check}`,
    `4.TRAINING: ${training}`,
    `5.BZ GROUP: ${bzGroup}`,
  ].join("\n")
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

function getFinishPeriodIndicatorLabel(finishPeriod?: string | null) {
  const normalized = (finishPeriod || "").trim().toUpperCase()
  return normalized === "AM" || normalized === "PM" ? normalized : ""
}

function getCommonTaskPeriodLabel(finishPeriod?: string | null) {
  return getFinishPeriodIndicatorLabel(finishPeriod) || "AM/PM"
}

function noProjectTypeLabel(task: Task) {
  if (task.is_bllok) return "BLLOK"
  if (task.is_1h_report) return "1H"
  if (task.is_r1) return "R1"
  if (task.is_personal) return "Personal"
  if (task.ga_note_origin_id) return "GA"
  return "Normal"
}

function fastReportSubtypeShort(task: Task) {
  const base = noProjectTypeLabel(task)
  if (base === "BLLOK") return "BLL"
  if (base === "Personal") return "P:"
  if (base === "Normal") return "N"
  return base
}

function getDisplayPriority(task: Task): TaskPriority {
  if (task.is_bllok) return "BLLOK"
  return (task.priority || "NORMAL") as TaskPriority
}

function reportStatusLabel(status?: Task["status"] | null) {
  if (!status) return "-"
  if (status === "IN_PROGRESS") return "In Progress"
  if (status === "WAITING_CLIENT") return "WFE"
  if (status === "WAITING_CONFIRMATION") return "Waiting Confirmation"
  if (status === "TODO") return "To Do"
  if (status === "DONE") return "Done"
  return status
}

function taskStatusLabel(task: Task) {
  if (task.status) return reportStatusLabel(task.status)
  if (task.completed_at) return "Done"
  return "-"
}

function formatSystemOccurrenceStatus(status?: string | null) {
  if (!status) return "-"
  if (status === "TODO") return "To Do"
  if (status === "IN_PROGRESS") return "In Progress"
  if (status === "WAITING_CLIENT") return "WFE"
  if (status === "WAITING_CONFIRMATION") return "Waiting Confirmation"
  if (status === "NOT_DONE") return "Not Done"
  if (status === "DONE") return "Done"
  if (status === "OPEN") return "Open"
  if (status === "SKIPPED") return "Skipped"
  return status
}

function getTyoLabel(baseDate: Date | null, completedAt: string | null | undefined, today: Date) {
  const completedDate = completedAt ? toDate(completedAt) : null
  if (completedDate && isSameDay(completedDate, today)) return "T"
  if (!baseDate) return "-"
  if (isSameDay(baseDate, today)) return "T"
  const delta = Math.floor((dayKey(today) - dayKey(baseDate)) / MS_PER_DAY)
  if (delta === 1) return "Y"
  if (delta > 1) return String(delta)
  return "-"
}

function isSameDay(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

type CommonType =
  | "late"
  | "absent"
  | "leave"
  | "blocked"
  | "oneH"
  | "personal"
  | "external"
  | "internal"
  | "r1"
  | "problem"
  | "feedback"
  | "priority"
  | "bz"
  | "det_ga"

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
type BlockedItem = { title: string; person: string; date: string; note?: string; assignees?: string[]; userId?: string; taskId?: string; finishPeriod?: string | null }
type OneHItem = {
  title: string
  person: string
  date: string
  note?: string
  assignees?: string[]
  departmentId?: string
  isDone?: boolean
  userId?: string
  taskId?: string
  finishPeriod?: string | null
}
type PersonalItem = { title: string; person: string; date: string; note?: string; assignees?: string[]; userId?: string; taskId?: string; finishPeriod?: string | null }
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
  calendar_categories?: string[]
  calendarImported?: boolean
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
type R1Item = {
  title: string
  date: string
  owner: string
  note?: string
  assignees?: string[]
  departmentId?: string
  isDone?: boolean
  userId?: string
  taskId?: string
  finishPeriod?: string | null
}
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
  templateId?: string | null
  matchTitle?: string
}

type CommonGaTableEntry = {
  kind: "task" | "system"
  title: string
  assignees?: string[]
  time?: string
  bzWithLabel?: string
  taskId?: string
  templateId?: string | null
  matchTitle?: string
}

type GaTimeSlotEntry = {
  id: string
  user_id: string
  day_of_week: number
  start_time: string
  end_time: string
  content: string
  sort_order: number
  background_color: string
  text_color: string
  is_bold: boolean
  is_italic: boolean
  created_at: string
  updated_at: string
  occurrence_date?: string | null
  source_type?: "calendar" | "reminder" | null
  source_name?: string | null
}

type GaIcloudSyncConnection = {
  id: string
  device_name: string
  calendar_name: string
  reminder_list_name: string
  last_synced_at?: string | null
  last_imported_count: number
  created_at: string
}

type GaIcloudSyncPairing = GaIcloudSyncConnection & {
  import_url: string
  pairing_token: string
}

function taskRequiresRlzCompletionComment(task: Task) {
  if (task.system_template_origin_id) return true
  if (task.ga_note_origin_id || task.plan_note_origin_id) return false
  return !Boolean(task.is_bllok || task.is_1h_report || task.is_r1 || task.is_personal)
}

function apiErrorMessage(payload: unknown, fallback: string) {
  if (!payload || typeof payload !== "object") return fallback
  const detail = (payload as { detail?: unknown }).detail
  if (typeof detail === "string" && detail.trim()) return detail
  if (detail && typeof detail === "object") {
    const message = (detail as { message?: unknown }).message
    if (typeof message === "string" && message.trim()) return message
  }
  return fallback
}

function apiErrorCode(payload: unknown) {
  if (!payload || typeof payload !== "object") return null
  const detail = (payload as { detail?: unknown }).detail
  if (!detail || typeof detail !== "object") return null
  const code = (detail as { code?: unknown }).code
  return typeof code === "string" ? code : null
}

type GaTimeEntryFormat = Pick<
  GaTimeSlotEntry,
  "background_color" | "text_color" | "is_bold" | "is_italic"
>

const DEFAULT_GA_TIME_ENTRY_FORMAT: GaTimeEntryFormat = {
  background_color: "#FFFFFF",
  text_color: "#0F172A",
  is_bold: false,
  is_italic: false,
}

const GA_TIME_BACKGROUND_COLORS = [
  "#FFFFFF",
  "#FACC15",
  "#A855F7",
  "#EF4444",
  "#22C55E",
  "#3B82F6",
] as const

const GA_TIME_STRONG_BACKGROUND_COLORS: Record<string, string> = {
  "#FEF3C7": "#FACC15",
  "#FCE7F3": "#A855F7",
  "#F472B6": "#A855F7",
  "#FEE2E2": "#EF4444",
  "#DCFCE7": "#22C55E",
  "#DBEAFE": "#3B82F6",
}

const normalizeGaTimeBackgroundColor = (color: string) =>
  GA_TIME_STRONG_BACKGROUND_COLORS[color.toUpperCase()] || color

const gaTimeTextColorForBackground = (backgroundColor: string, textColor: string) => {
  const normalizedBackground = normalizeGaTimeBackgroundColor(backgroundColor).toUpperCase()
  // Red cells use white text by default for contrast, but an explicit text
  // colour chosen in the editor must still be respected (for example black).
  const normalizedText = textColor.trim().toUpperCase()
  return normalizedBackground === "#EF4444" && normalizedText === DEFAULT_GA_TIME_ENTRY_FORMAT.text_color
    ? "#FFFFFF"
    : textColor
}

const GA_TIME_TEXT_COLORS = [
  { label: "Black", value: "#000000" },
  { label: "White", value: "#FFFFFF" },
  { label: "Yellow", value: "#FACC15" },
  { label: "Purple", value: "#A855F7" },
  { label: "Red", value: "#EF4444" },
  { label: "Green", value: "#22C55E" },
  { label: "Blue", value: "#3B82F6" },
] as const

const GA_TIME_RICH_TEXT_TAG_PATTERN = /<(strong|b|em|i|br|span|font)(\s|>|\/)/i

function normalizeGaTimeInlineColor(value: string) {
  const normalized = value.trim().replace(/\s+/g, "").toUpperCase()
  const aliases: Record<string, string> = {
    BLACK: "#000000",
    "RGB(0,0,0)": "#000000",
    "#000000": "#000000",
    RED: "#FF0000",
    "RGB(255,0,0)": "#FF0000",
    "#FF0000": "#FF0000",
    WHITE: "#FFFFFF",
    "RGB(255,255,255)": "#FFFFFF",
    "#FFFFFF": "#FFFFFF",
    YELLOW: "#FACC15",
    "RGB(250,204,21)": "#FACC15",
    "#FACC15": "#FACC15",
    PURPLE: "#A855F7",
    "RGB(168,85,247)": "#A855F7",
    "#A855F7": "#A855F7",
    "RGB(239,68,68)": "#EF4444",
    "#EF4444": "#EF4444",
    GREEN: "#22C55E",
    "RGB(34,197,94)": "#22C55E",
    "#22C55E": "#22C55E",
    BLUE: "#3B82F6",
    "RGB(59,130,246)": "#3B82F6",
    "#3B82F6": "#3B82F6",
  }
  return aliases[normalized] || ""
}

function sanitizeGaTimeRichTextHtml(raw: string) {
  if (!raw || typeof document === "undefined") return ""

  const source = document.createElement("div")
  source.innerHTML = raw
  const clean = document.createElement("div")

  const sanitizeNode = (node: Node): Node[] => {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = node.textContent || ""
      return text ? [document.createTextNode(text)] : []
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return []

    const element = node as HTMLElement
    const tag = element.tagName.toUpperCase()
    if (tag === "BR") return [document.createElement("br")]

    const children = Array.from(element.childNodes).flatMap(sanitizeNode)
    if (tag === "STRONG" || tag === "B") {
      const strong = document.createElement("strong")
      children.forEach((child) => strong.appendChild(child))
      return [strong]
    }
    if (tag === "EM" || tag === "I") {
      const emphasis = document.createElement("em")
      children.forEach((child) => emphasis.appendChild(child))
      return [emphasis]
    }

    if (tag === "SPAN" || tag === "FONT") {
      const color = normalizeGaTimeInlineColor(
        element.getAttribute("data-ga-color") || element.getAttribute("color") || element.style.color || ""
      )
      const fontSize = element.style.fontSize.toLowerCase()
      const legacySize = Number.parseInt(element.getAttribute("size") || "", 10)
      const isLarge =
        element.getAttribute("data-ga-size") === "large" ||
        (!Number.isNaN(legacySize) && legacySize >= 4) ||
        fontSize === "large" ||
        fontSize === "larger" ||
        fontSize === "1.25em" ||
        Number.parseFloat(fontSize) >= 16

      if (color || isLarge) {
        const span = document.createElement("span")
        if (color) {
          span.setAttribute("data-ga-color", color)
          span.style.color = color
        }
        if (isLarge) {
          span.setAttribute("data-ga-size", "large")
          span.style.fontSize = "1.25em"
        }
        children.forEach((child) => span.appendChild(child))
        return [span]
      }
    }

    if (tag === "DIV" || tag === "P") {
      return [...children, document.createElement("br")]
    }
    return children
  }

  Array.from(source.childNodes).forEach((node) => {
    sanitizeNode(node).forEach((child) => clean.appendChild(child))
  })
  clean.normalize()

  while (clean.lastChild?.nodeName === "BR") clean.removeChild(clean.lastChild)
  return (clean.textContent || "").trim() ? clean.innerHTML : ""
}

function normalizeGaTimeRichTextValue(value: string) {
  if (!value) return ""
  if (typeof document === "undefined") return ""
  if (GA_TIME_RICH_TEXT_TAG_PATTERN.test(value)) return sanitizeGaTimeRichTextHtml(value)
  // contentEditable exposes plain text entities through innerHTML. Decode
  // those entities before escaping once, otherwise each autosave can turn
  // `&nbsp;` into visible `&amp;amp;nbsp;` text.
  const decoded = document.createElement("div")
  let plainValue = value
  for (let pass = 0; pass < 3 && /&(?:amp;)*(?:nbsp|amp|lt|gt|quot);/i.test(plainValue); pass += 1) {
    decoded.innerHTML = plainValue
    plainValue = decoded.textContent || ""
  }
  return escapeHtml(plainValue)
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .replace(/\n/g, "<br>")
}

function applyGaTimeAutomaticContrast(value: string, backgroundColor: string) {
  if (normalizeGaTimeBackgroundColor(backgroundColor).toUpperCase() !== "#EF4444") return value
  if (typeof document === "undefined" || !GA_TIME_RICH_TEXT_TAG_PATTERN.test(value)) return value
  const container = document.createElement("div")
  container.innerHTML = normalizeGaTimeRichTextValue(value)
  container.querySelectorAll("span[data-ga-color], span[style*='color'], font[color]").forEach((node) => {
    const element = node as HTMLElement
    const inlineColor = normalizeGaTimeInlineColor(
      element.getAttribute("data-ga-color") || element.getAttribute("color") || element.style.color || ""
    )
    if (inlineColor !== "#FF0000" && inlineColor !== "#EF4444") return
    element.setAttribute("data-ga-color", "#FFFFFF")
    element.style.color = "#FFFFFF"
    element.removeAttribute("color")
  })
  return container.innerHTML
}

function getPlainGaTimeRichText(value: string) {
  if (!value) return ""
  if (typeof document === "undefined") {
    return value.replace(/<br\s*\/?>/gi, "\n").replace(/<[^>]*>/g, "")
  }
  const container = document.createElement("div")
  container.innerHTML = normalizeGaTimeRichTextValue(value)
  return container.textContent || ""
}

function GaTimeRichTextContent({ value, backgroundColor }: { value: string; backgroundColor?: string }) {
  if (!value) return null
  if (typeof document === "undefined") return <>{getPlainGaTimeRichText(value)}</>
  const html = applyGaTimeAutomaticContrast(value, backgroundColor || DEFAULT_GA_TIME_ENTRY_FORMAT.background_color)
  return <span dangerouslySetInnerHTML={{ __html: normalizeGaTimeRichTextValue(html) }} />
}

const gaTimeEntryDisplayContent = (entry: GaTimeSlotEntry) =>
  entry.source_type === "reminder"
    ? entry.content.replace(/^\s*REMINDER\s*:?\s*/i, "R: ")
    : entry.content

function GaTimeEntryContent({ entry }: { entry: GaTimeSlotEntry }) {
  const content = gaTimeEntryDisplayContent(entry)
  const plainContent = getPlainGaTimeRichText(content)
  const isReminder = entry.source_type === "reminder" || /^\s*R\s*:/i.test(plainContent)
  return (
    <span className={isReminder ? "ga-time-reminder-preview" : undefined} title={isReminder ? plainContent : undefined}>
      <GaTimeRichTextContent value={content} backgroundColor={entry.background_color} />
    </span>
  )
}

function GaTimeRichTextEditor({
  value,
  onChange,
  placeholder,
  disabled,
  multiline = false,
  cellFormat,
  onEditorBlur,
}: {
  value: string
  onChange: (value: string) => void
  placeholder: string
  disabled: boolean
  multiline?: boolean
  cellFormat?: Partial<GaTimeEntryFormat>
  onEditorBlur?: () => void
}) {
  const editorRef = React.useRef<HTMLDivElement | null>(null)
  const lastEditorValueRef = React.useRef<string | null>(null)
  const selectionRef = React.useRef<Range | null>(null)

  const rememberSelection = React.useCallback(() => {
    const editor = editorRef.current
    const selection = window.getSelection()
    if (!editor || !selection?.rangeCount || !selection.anchorNode || !editor.contains(selection.anchorNode)) return
    const range = selection.getRangeAt(0)
    // A toolbar press can momentarily report a collapsed caret. Keep the
    // previously captured highlighted range in that case.
    if (range.collapsed) return
    selectionRef.current = range.cloneRange()
  }, [])

  React.useEffect(() => {
    const editor = editorRef.current
    if (!editor || value === lastEditorValueRef.current) return
    // Do not rewrite a focused contentEditable on every parent update: doing
    // so resets the caret/selection and makes typing jump or lose characters.
    if (document.activeElement === editor) {
      return
    }
    const normalized = normalizeGaTimeRichTextValue(value)
    if (editor.innerHTML !== normalized) editor.innerHTML = normalized
    lastEditorValueRef.current = normalized
  }, [value])

  React.useEffect(() => {
    const editor = editorRef.current
    if (!editor) return
    editor.focus()
    const selection = window.getSelection()
    if (!selection || !editor.textContent) return
    const range = document.createRange()
    range.selectNodeContents(editor)
    range.collapse(false)
    selection.removeAllRanges()
    selection.addRange(range)
  }, [])

  const emitCurrentValue = React.useCallback((sanitize = false) => {
    const editor = editorRef.current
    if (!editor) return
    const nextValue = sanitize ? sanitizeGaTimeRichTextHtml(editor.innerHTML) : editor.innerHTML
    if (sanitize && editor.innerHTML !== nextValue) editor.innerHTML = nextValue
    lastEditorValueRef.current = nextValue
    onChange(nextValue)
  }, [onChange])

  const applyCommand = React.useCallback((command: string, commandValue?: string) => {
    const editor = editorRef.current
    if (!editor || disabled) return
    editor.focus()
    if (selectionRef.current && editor.contains(selectionRef.current.commonAncestorContainer)) {
      const selection = window.getSelection()
      selection?.removeAllRanges()
      selection?.addRange(selectionRef.current)
    }
    const selection = window.getSelection()
    const range = selection?.rangeCount ? selection.getRangeAt(0) : null
    // execCommand('foreColor') is inconsistent across browsers and can lose
    // the selection when the toolbar is clicked. Wrap the selected contents
    // explicitly so the chosen colour is persisted in the editor HTML.
    if (command === "foreColor" && commandValue && range && !range.collapsed && editor.contains(range.commonAncestorContainer)) {
      const colored = document.createElement("span")
      colored.setAttribute("data-ga-color", commandValue.toUpperCase())
      colored.style.color = commandValue
      colored.appendChild(range.extractContents())
      // Remove older color wrappers before adding the new one. Repeatedly
      // wrapping an already-coloured selection can otherwise grow the HTML
      // until it exceeds the database content limit.
      colored.querySelectorAll("span[data-ga-color], span[style*='color'], font[color]").forEach((node) => {
        const nested = node as HTMLElement
        if (nested.getAttribute("data-ga-size") === "large") {
          nested.removeAttribute("data-ga-color")
          nested.style.removeProperty("color")
          nested.removeAttribute("color")
          return
        }
        const parent = nested.parentNode
        if (!parent) return
        while (nested.firstChild) parent.insertBefore(nested.firstChild, nested)
        parent.removeChild(nested)
      })
      range.insertNode(colored)
      const selected = document.createRange()
      selected.selectNodeContents(colored)
      selection?.removeAllRanges()
      selection?.addRange(selected)
      selectionRef.current = selected.cloneRange()
      emitCurrentValue(false)
      return
    }
    document.execCommand(command, false, commandValue)
    // Keep the browser's active range intact so the same selected text can
    // receive several formats (for example bold, red, and larger).
    emitCurrentValue(false)
  }, [disabled, emitCurrentValue])

  return (
    <div className="space-y-1.5">
      <div
        ref={editorRef}
        contentEditable={!disabled}
        role="textbox"
        aria-multiline={multiline}
        aria-label={placeholder}
        data-placeholder={placeholder}
        style={{
          backgroundColor: normalizeGaTimeBackgroundColor(
            cellFormat?.background_color || DEFAULT_GA_TIME_ENTRY_FORMAT.background_color
          ),
          color: gaTimeTextColorForBackground(
            cellFormat?.background_color || DEFAULT_GA_TIME_ENTRY_FORMAT.background_color,
            cellFormat?.text_color || DEFAULT_GA_TIME_ENTRY_FORMAT.text_color
          ),
          fontWeight: cellFormat?.is_bold ? 700 : 400,
          fontStyle: cellFormat?.is_italic ? "italic" : "normal",
        }}
        className={cn(
          "w-full rounded-md border border-slate-300 bg-white px-2 py-1 text-xs leading-5 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200 empty:before:pointer-events-none empty:before:text-slate-400 empty:before:content-[attr(data-placeholder)]",
          normalizeGaTimeBackgroundColor(
            cellFormat?.background_color || DEFAULT_GA_TIME_ENTRY_FORMAT.background_color
          ).toUpperCase() === "#EF4444" && "ga-time-editor-contrast",
          multiline ? "min-h-[72px] whitespace-pre-wrap" : "min-h-8"
        )}
        onInput={() => emitCurrentValue(false)}
        onSelect={rememberSelection}
        onMouseUp={rememberSelection}
        onKeyUp={rememberSelection}
        onBlur={() => {
          emitCurrentValue(true)
          onEditorBlur?.()
        }}
        onKeyDown={(event) => {
          if (!multiline && event.key === "Enter") {
            event.preventDefault()
            return
          }
          if ((event.ctrlKey || event.metaKey) && ["b", "i"].includes(event.key.toLowerCase())) {
            event.preventDefault()
            applyCommand(event.key.toLowerCase() === "b" ? "bold" : "italic")
          }
        }}
        onPaste={(event) => {
          event.preventDefault()
          const text = event.clipboardData.getData("text/plain")
          if (!text) return
          const html = escapeHtml(text)
            .replace(/\r\n/g, "\n")
            .replace(/\r/g, "\n")
            .replace(/\n/g, multiline ? "<br>" : " ")
          document.execCommand("insertHTML", false, html)
          emitCurrentValue(true)
        }}
        suppressContentEditableWarning
      />
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-[10px] font-medium text-slate-500">Selected text</span>
        {GA_TIME_TEXT_COLORS.map((color) => (
          <button
            key={color.value}
            type="button"
            className="h-4 w-4 rounded-full border border-slate-400"
            style={{ backgroundColor: color.value }}
            onMouseDown={(event) => {
              event.preventDefault()
              rememberSelection()
              applyCommand("foreColor", color.value)
            }}
            onClick={(event) => {
              // Keyboard activation has no preceding mouse-down event.
              if (event.detail === 0) applyCommand("foreColor", color.value)
            }}
            disabled={disabled}
            aria-label={`${color.label} text`}
            title={`${color.label} text`}
          />
        ))}
        <button
          type="button"
          className="h-7 min-w-7 rounded border border-slate-300 bg-white px-2 text-xs font-bold text-slate-700"
          onMouseDown={(event) => {
            rememberSelection()
            event.preventDefault()
          }}
          onClick={() => applyCommand("bold")}
          disabled={disabled}
          title="Bold selected text"
          aria-label="Bold selected text"
        >
          B
        </button>
        <button
          type="button"
          className="h-7 min-w-7 rounded border border-slate-300 bg-white px-2 text-xs italic text-slate-700"
          onMouseDown={(event) => {
            rememberSelection()
            event.preventDefault()
          }}
          onClick={() => applyCommand("italic")}
          disabled={disabled}
          title="Italic selected text"
          aria-label="Italic selected text"
        >
          I
        </button>
        <button
          type="button"
          className="h-7 min-w-8 rounded border border-slate-300 bg-white px-2 text-sm font-semibold text-slate-700"
          onMouseDown={(event) => {
            rememberSelection()
            event.preventDefault()
          }}
          onClick={() => applyCommand("fontSize", "4")}
          disabled={disabled}
          title="Make selected text bigger"
          aria-label="Make selected text bigger"
        >
          A+
        </button>
      </div>
    </div>
  )
}

type GaTimeSaveStatus = "idle" | "saving" | "saved" | "error"

const gaTimeSaveSignature = (content: string, format: GaTimeEntryFormat) => JSON.stringify([
  content,
  format.background_color,
  format.text_color,
  format.is_bold,
  format.is_italic,
])

function useGaTimeManualSave({
  initialContent,
  initialFormat,
  content,
  format,
  onSave,
}: {
  initialContent: string
  initialFormat: GaTimeEntryFormat
  content: string
  format: GaTimeEntryFormat
  onSave: (content: string, format: GaTimeEntryFormat) => Promise<boolean>
}) {
  const lastSavedSignatureRef = React.useRef(gaTimeSaveSignature(initialContent, initialFormat))
  const [status, setStatus] = React.useState<GaTimeSaveStatus>("idle")
  const savingRef = React.useRef(false)
  const currentSignature = gaTimeSaveSignature(content, format)
  const hasChanges = currentSignature !== lastSavedSignatureRef.current
  const save = React.useCallback(async () => {
    if (savingRef.current) return false
    if (!hasChanges) return true
    const sanitizedContent = sanitizeGaTimeRichTextHtml(normalizeGaTimeRichTextValue(content))
    if (!getPlainGaTimeRichText(sanitizedContent).trim()) {
      setStatus("idle")
      return false
    }
    savingRef.current = true
    setStatus("saving")
    try {
      const saved = await onSave(sanitizedContent, format)
      if (saved) {
        lastSavedSignatureRef.current = currentSignature
        setStatus("saved")
      } else {
        setStatus("error")
      }
      return saved
    } catch {
      setStatus("error")
      return false
    } finally {
      savingRef.current = false
    }
  }, [content, currentSignature, format, hasChanges, onSave])

  return { status, hasChanges, save }
}

const normalizeGaTimeEntryFormat = (
  entry?: Partial<GaTimeEntryFormat> | null
): GaTimeEntryFormat => ({
  background_color: normalizeGaTimeBackgroundColor(
    entry?.background_color || DEFAULT_GA_TIME_ENTRY_FORMAT.background_color
  ),
  text_color: entry?.text_color || DEFAULT_GA_TIME_ENTRY_FORMAT.text_color,
  is_bold: Boolean(entry?.is_bold),
  is_italic: Boolean(entry?.is_italic),
})

const gaTimeEntryStyle = (entry: Partial<GaTimeEntryFormat>): React.CSSProperties => ({
  backgroundColor: normalizeGaTimeBackgroundColor(
    entry.background_color || DEFAULT_GA_TIME_ENTRY_FORMAT.background_color
  ),
  color: gaTimeTextColorForBackground(
    entry.background_color || DEFAULT_GA_TIME_ENTRY_FORMAT.background_color,
    entry.text_color || DEFAULT_GA_TIME_ENTRY_FORMAT.text_color
  ),
  fontWeight: entry.is_bold ? 700 : 400,
  fontStyle: entry.is_italic ? "italic" : "normal",
})

// On a phone the table cell is far too narrow for the editor, and the keyboard
// covers whatever is below it. Touch devices therefore get the same editor in a
// full-width panel pinned to the top of the visible screen, with finger-sized
// controls; desktop keeps the inline editor inside the cell.
// Kept outside the page component: defining it inline gave it a new identity on
// every render, so React remounted each section (scroll jump, lost focus).
function AdminTasksSection({
  sectionId,
  title,
  description,
  actions,
  children,
  headerClassName,
  contentClassName,
  isCollapsed,
  onToggle,
}: {
  sectionId: AdminTasksSectionId
  title: string
  description?: string
  actions?: React.ReactNode
  children?: React.ReactNode
  headerClassName?: string
  contentClassName?: string
  isCollapsed: boolean
  onToggle: (sectionId: AdminTasksSectionId) => void
}) {
  return (
    <Card className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <CardHeader className={cn("flex flex-wrap items-center justify-center gap-3", "relative pl-14", headerClassName)}>
        <div>
          <CardTitle className="text-base font-semibold text-slate-900">{title}</CardTitle>
          {description ? <div className="mt-1 text-xs text-slate-500">{description}</div> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="absolute left-3 top-3 h-8 w-8 p-0 text-lg font-semibold leading-none print:hidden"
          aria-label={isCollapsed ? `Open ${title}` : `Close ${title}`}
          aria-expanded={!isCollapsed}
          onClick={() => onToggle(sectionId)}
        >
          {isCollapsed ? "+" : "-"}
        </Button>
      </CardHeader>
      {!isCollapsed && children ? <CardContent className={cn("px-2", contentClassName)}>{children}</CardContent> : null}
    </Card>
  )
}

function GaTimeEditorShell({ className, children }: { className: string; children: React.ReactNode }) {
  const [isTouch] = React.useState(
    () => typeof window !== "undefined" && window.matchMedia("(pointer: coarse)").matches
  )
  const [viewport, setViewport] = React.useState<{ top: number; height: number } | null>(null)

  React.useEffect(() => {
    if (!isTouch) return
    const visual = window.visualViewport
    // The visual viewport shrinks when the keyboard opens and shifts when iOS
    // scrolls the page under it; follow both so the panel stays in view.
    const sync = () =>
      setViewport({ top: visual?.offsetTop ?? 0, height: visual?.height ?? window.innerHeight })
    sync()
    visual?.addEventListener("resize", sync)
    visual?.addEventListener("scroll", sync)
    return () => {
      visual?.removeEventListener("resize", sync)
      visual?.removeEventListener("scroll", sync)
    }
  }, [isTouch])

  if (!isTouch) return <div className={className}>{children}</div>

  return createPortal(
    <div className="fixed inset-0 z-[300] bg-black/40 print:hidden">
      <div
        style={{ top: (viewport?.top ?? 0) + 8, maxHeight: Math.max((viewport?.height ?? 320) - 16, 160) }}
        className={[
          "absolute inset-x-2 flex flex-col gap-3 overflow-y-auto rounded-xl border border-blue-200 bg-white p-3 shadow-2xl",
          // 16px text stops iOS from zooming the page when the field is focused.
          "[&_[role=textbox]]:min-h-12 [&_[role=textbox]]:px-3 [&_[role=textbox]]:py-2 [&_[role=textbox]]:text-base",
          // Selecting text makes iOS show its copy/paste bubble right under the
          // field; the colour row sits below that bubble so it stays tappable.
          "[&_[role=textbox]+div]:mt-14",
          "[&_span]:text-xs [&_.flex]:gap-2.5",
          "[&_button.rounded-full]:h-8 [&_button.rounded-full]:w-8",
          "[&_button:not(.rounded-full)]:h-10 [&_button:not(.rounded-full)]:min-w-10 [&_button:not(.rounded-full)]:px-4 [&_button:not(.rounded-full)]:text-sm",
          // Cancel / Save stay reachable even when the panel has to scroll.
          "[&>div:last-child]:sticky [&>div:last-child]:bottom-0 [&>div:last-child]:bg-white [&>div:last-child]:pt-1",
        ].join(" ")}
      >
        {children}
      </div>
    </div>,
    document.body
  )
}

function GaTimeEntryEditor({
  initialContent = "",
  initialFormat,
  saving = false,
  onSave,
  onCancel,
}: {
  initialContent?: string
  initialFormat?: Partial<GaTimeEntryFormat>
  saving?: boolean
  onSave: (content: string, format: GaTimeEntryFormat) => Promise<boolean>
  onCancel: () => void
}) {
  const [content, setContent] = React.useState(initialContent)
  const [normalizedInitialFormat] = React.useState<GaTimeEntryFormat>(() => normalizeGaTimeEntryFormat(initialFormat))
  const [format, setFormat] = React.useState<GaTimeEntryFormat>(normalizedInitialFormat)
  const { status, hasChanges, save } = useGaTimeManualSave({
    initialContent,
    initialFormat: normalizedInitialFormat,
    content,
    format,
    onSave,
  })
  const isSaving = saving || status === "saving"

  const saveAndClose = React.useCallback(async () => {
    if (await save()) {
      onCancel()
      toast.success("U ruajt me sukses.")
    }
  }, [onCancel, save])

  return (
    <GaTimeEditorShell className="w-full space-y-2 rounded-md border border-blue-200 bg-white p-2">
      <GaTimeRichTextEditor
        value={content}
        onChange={setContent}
        placeholder="Write task..."
        disabled={isSaving}
        cellFormat={format}
      />
      <div className="space-y-1.5">
        <div className="flex items-center gap-1 whitespace-nowrap">
          <span className="mr-1 shrink-0 text-[10px] font-medium text-slate-500">Cell</span>
          {GA_TIME_BACKGROUND_COLORS.map((color) => (
            <button
              key={color}
              type="button"
              className={cn(
                "h-4 w-4 shrink-0 rounded-full border border-slate-300",
                format.background_color === color && "ring-2 ring-blue-500 ring-offset-1"
              )}
              style={{ backgroundColor: color }}
              disabled={isSaving}
              onClick={() => {
                setFormat((current) => ({ ...current, background_color: color }))
                if (color === "#EF4444") setContent((current) => applyGaTimeAutomaticContrast(current, color))
              }}
              aria-label={`Cell color ${color}`}
              title={`Cell color ${color}`}
            />
          ))}
        </div>
      </div>
      <div className="flex justify-end">
        <div className="flex items-center gap-1">
          <Button type="button" size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={onCancel} disabled={isSaving}>
            Cancel
          </Button>
          <Button type="button" size="sm" className="h-7 px-2 text-xs" onClick={() => void saveAndClose()} disabled={isSaving || !hasChanges || !getPlainGaTimeRichText(content).trim()}>
            {isSaving ? "Saving..." : "Save"}
          </Button>
        </div>
      </div>
    </GaTimeEditorShell>
  )
}

function GaTimeRowCommentEditor({
  initialComment,
  initialFormat,
  saving,
  onSave,
  onCancel,
}: {
  initialComment: string
  initialFormat?: Partial<GaTimeEntryFormat>
  saving: boolean
  onSave: (comment: string, format: GaTimeEntryFormat) => Promise<boolean>
  onCancel: () => void
}) {
  const [comment, setComment] = React.useState(initialComment)
  const [normalizedInitialFormat] = React.useState<GaTimeEntryFormat>(() => normalizeGaTimeEntryFormat(initialFormat))
  const [format, setFormat] = React.useState<GaTimeEntryFormat>(normalizedInitialFormat)
  const { status, hasChanges, save } = useGaTimeManualSave({
    initialContent: initialComment,
    initialFormat: normalizedInitialFormat,
    content: comment,
    format,
    onSave,
  })
  const isSaving = saving || status === "saving"

  const saveAndClose = React.useCallback(async () => {
    if (await save()) {
      onCancel()
      toast.success("U ruajt me sukses.")
    }
  }, [onCancel, save])

  return (
    <GaTimeEditorShell className="flex min-w-[158px] flex-col gap-2 rounded-md border border-blue-200 bg-white p-2">
      <GaTimeRichTextEditor
        value={comment}
        onChange={setComment}
        placeholder="Add comment..."
        disabled={isSaving}
        multiline
        cellFormat={format}
      />
      <div className="space-y-1.5">
        <div className="flex items-center gap-1 whitespace-nowrap">
          <span className="mr-1 shrink-0 text-[10px] font-medium text-slate-500">Cell</span>
          {GA_TIME_BACKGROUND_COLORS.map((color) => (
            <button
              key={color}
              type="button"
              className={cn(
                "h-4 w-4 shrink-0 rounded-full border border-slate-300",
                format.background_color === color && "ring-2 ring-blue-500 ring-offset-1"
              )}
              style={{ backgroundColor: color }}
              disabled={isSaving}
              onClick={() => {
                setFormat((current) => ({ ...current, background_color: color }))
                if (color === "#EF4444") setComment((current) => applyGaTimeAutomaticContrast(current, color))
              }}
              aria-label={`Comment cell color ${color}`}
              title={`Comment cell color ${color}`}
            />
          ))}
        </div>
      </div>
      <div className="flex justify-end">
        <div className="flex items-center gap-1">
          <Button type="button" size="sm" variant="ghost" className="h-8 px-3 text-xs" onClick={onCancel} disabled={isSaving}>
            Cancel
          </Button>
          <Button type="button" size="sm" className="h-8 px-3 text-xs" onClick={() => void saveAndClose()} disabled={isSaving || !hasChanges || !getPlainGaTimeRichText(comment).trim()}>
            {isSaving ? "Saving..." : "Save"}
          </Button>
        </div>
      </div>
    </GaTimeEditorShell>
  )
}

type GaTimeRowComment = {
  id: string
  content: string
  backgroundColor: string
  textColor: string
  isBold: boolean
  isItalic: boolean
}

type GaTimeCommentColumn = "start" | "end"

type GaTimeCommentDragSource = {
  commentId: string
  rowStart: string
  rowEnd: string
  column: GaTimeCommentColumn
}

type GaTimeRow = {
  id?: string | null
  start: string
  end: string
  label: string
  nrLabel: string
  isSpecial?: boolean
  sortOrder?: number
  comment: string
  commentBackgroundColor?: string
  commentTextColor?: string
  commentIsBold?: boolean
  commentIsItalic?: boolean
  comments?: GaTimeRowComment[]
  endComments?: GaTimeRowComment[]
}

type GaTimeTableRowCommentResponse = {
  id: string
  content: string
  comment_background_color?: string | null
  comment_text_color?: string | null
  comment_is_bold?: boolean
  comment_is_italic?: boolean
}

type GaTimeTableRowResponse = {
  id?: string | null
  sort_order: number
  nr_label: string
  label: string
  start_time: string
  end_time: string
  is_special?: boolean
  comment?: string | null
  comment_background_color?: string | null
  comment_text_color?: string | null
  comment_is_bold?: boolean
  comment_is_italic?: boolean
  comments?: GaTimeTableRowCommentResponse[]
  end_comments?: GaTimeTableRowCommentResponse[]
}

type GaTimeCrossCellMoveResponse = {
  rows: GaTimeTableRowResponse[]
  entries: GaTimeSlotEntry[]
}

type CommonBucket =
  | "late"
  | "absent"
  | "leave"
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

const ALL_USERS_INITIALS = "ALL"
const FEEDBACK_DAILY_MARKER = "[EVERYDAY]"

const DEFAULT_GA_TIME_ROWS: readonly GaTimeRow[] = [
  { start: "00:00", end: "00:01", label: "", nrLabel: "", isSpecial: true, comment: "" },
  { start: "00:01", end: "00:02", label: "", nrLabel: "", isSpecial: true, comment: "" },
  { start: "07:30", end: "08:00", label: "07:30 - 08:00", nrLabel: "1", comment: "" },
  { start: "08:00", end: "09:00", label: "08:00 - 09:00", nrLabel: "2", comment: "" },
  { start: "09:00", end: "10:00", label: "09:00 - 10:00", nrLabel: "3", comment: "" },
  { start: "10:00", end: "11:00", label: "10:00 - 11:00", nrLabel: "4", comment: "" },
  { start: "11:00", end: "12:00", label: "11:00 - 12:00", nrLabel: "5", comment: "" },
  { start: "12:00", end: "13:00", label: "12:00 - 13:00", nrLabel: "6", comment: "" },
  { start: "13:00", end: "13:30", label: "13:00 - 13:30", nrLabel: "7", comment: "" },
  { start: "13:30", end: "14:00", label: "13:30 - 14:00", nrLabel: "8", comment: "" },
  { start: "14:00", end: "14:30", label: "14:00 - 14:30", nrLabel: "9", comment: "" },
  { start: "14:30", end: "15:30", label: "14:30 - 15:30", nrLabel: "10", comment: "" },
  { start: "15:30", end: "16:00", label: "15:30 - 16:00", nrLabel: "11", comment: "" },
  { start: "16:00", end: "16:30", label: "16:00 - 16:30", nrLabel: "12", comment: "" },
  { start: "16:30", end: "17:00", label: "16:30 - 17:00", nrLabel: "13", comment: "" },
  { start: "17:00", end: "18:00", label: "17:00 - 18:00", nrLabel: "14", comment: "" },
  { start: "18:00", end: "19:00", label: "18:00 - 19:00", nrLabel: "15", comment: "" },
  { start: "19:00", end: "20:00", label: "19:00 - 20:00", nrLabel: "16", comment: "" },
  { start: "20:00", end: "21:00", label: "20:00 - 21:00", nrLabel: "17", comment: "" },
  { start: "21:00", end: "22:00", label: "21:00 - 22:00", nrLabel: "18", comment: "" },
] as const

const formatGaTimeRowLabel = (start: string, end: string) => `${start} - ${end}`

const normalizeGaTimeValue = (value: string) => (value ? value.slice(0, 5) : "")

const gaTimeCommentsForRow = (row: GaTimeRow, column: GaTimeCommentColumn = "start"): GaTimeRowComment[] => {
  if (column === "end") return row.endComments || []
  if (row.comments?.length) return row.comments
  if (!row.comment) return []
  return [{
    id: `legacy-${row.id || `${row.start}-${row.end}`}`,
    content: row.comment,
    backgroundColor: row.commentBackgroundColor || DEFAULT_GA_TIME_ENTRY_FORMAT.background_color,
    textColor: row.commentTextColor || DEFAULT_GA_TIME_ENTRY_FORMAT.text_color,
    isBold: Boolean(row.commentIsBold),
    isItalic: Boolean(row.commentIsItalic),
  }]
}

const gaTimeCommentEditorKey = (
  row: GaTimeRow,
  commentId: string,
  column: GaTimeCommentColumn = "start"
) => `${row.start}|${row.end}|${column}|${commentId}`

const normalizeGaTimeRows = (rows: GaTimeTableRowResponse[]): GaTimeRow[] =>
  rows
    .map((row) => {
      const start = normalizeGaTimeValue(row.start_time)
      const end = normalizeGaTimeValue(row.end_time)
      const isSpecial = Boolean(row.is_special)
      const comments = (row.comments || []).map((comment) => ({
        id: comment.id,
        content: comment.content,
        backgroundColor: comment.comment_background_color || DEFAULT_GA_TIME_ENTRY_FORMAT.background_color,
        textColor: comment.comment_text_color || DEFAULT_GA_TIME_ENTRY_FORMAT.text_color,
        isBold: Boolean(comment.comment_is_bold),
        isItalic: Boolean(comment.comment_is_italic),
      }))
      const endComments = (row.end_comments || []).map((comment) => ({
        id: comment.id,
        content: comment.content,
        backgroundColor: comment.comment_background_color || DEFAULT_GA_TIME_ENTRY_FORMAT.background_color,
        textColor: comment.comment_text_color || DEFAULT_GA_TIME_ENTRY_FORMAT.text_color,
        isBold: Boolean(comment.comment_is_bold),
        isItalic: Boolean(comment.comment_is_italic),
      }))
      return {
        id: row.id,
        sortOrder: row.sort_order,
        start,
        end,
        label: isSpecial ? "" : row.label || (start && end ? formatGaTimeRowLabel(start, end) : ""),
        nrLabel: row.nr_label || "",
        isSpecial,
        comment: row.comment || "",
        commentBackgroundColor: row.comment_background_color || DEFAULT_GA_TIME_ENTRY_FORMAT.background_color,
        commentTextColor: row.comment_text_color || DEFAULT_GA_TIME_ENTRY_FORMAT.text_color,
        commentIsBold: Boolean(row.comment_is_bold),
        commentIsItalic: Boolean(row.comment_is_italic),
        comments,
        endComments,
      }
    })
    .sort((a, b) => (a.sortOrder ?? 0) - (b.sortOrder ?? 0) || a.start.localeCompare(b.start))

const renumberGaTimeRows = (rows: GaTimeRow[]): GaTimeRow[] => {
  let nr = 1
  return rows.map((row, index) => {
    if (row.isSpecial) return { ...row, sortOrder: index, nrLabel: "", label: "" }
    const start = normalizeGaTimeValue(row.start)
    const end = normalizeGaTimeValue(row.end)
    const next = {
      ...row,
      start,
      end,
      sortOrder: index,
      nrLabel: String(nr),
      label: start && end ? formatGaTimeRowLabel(start, end) : "",
    }
    nr += 1
    return next
  })
}

const sortVisibleGaTimeRows = (rows: GaTimeRow[]) =>
  [...rows].sort((a, b) => a.start.localeCompare(b.start) || a.end.localeCompare(b.end))

const resolveGaTimeRowStart = (start: string, rows: readonly GaTimeRow[]) => {
  if (rows.some((row) => row.start === start)) return start
  return rows.find((row) => !row.isSpecial && row.start <= start && start < row.end)?.start ?? start
}

const parseFeedbackNote = (note: string | null | undefined) => {
  const raw = note || ""
  const everyday = raw.includes(FEEDBACK_DAILY_MARKER)
  const cleaned = raw.split(FEEDBACK_DAILY_MARKER).join("").trim()
  return { note: cleaned || undefined, everyday }
}

const commonViewInitials = (name: string) => {
  const cleaned = name.trim()
  if (!cleaned) return "?"
  const parts = cleaned.split(/\s+/)
  const first = parts[0]?.[0] || ""
  const last = parts.length > 1 ? parts[parts.length - 1]?.[0] || "" : ""
  return `${first}${last}`.toUpperCase()
}

const stripInitialsPrefix = (value: string) => value
const renderCommonMarkedTitle = (value: string) => renderMarkedNoteContent(stripInitialsPrefix(value), stripInitialsPrefix(value))
const plainCommonMarkedTitle = (value: string) => getPlainMarkedText(stripInitialsPrefix(value))
const commonPrintTitleLine = (value: string) =>
  plainCommonMarkedTitle(value)
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find(Boolean) || ""
const normalizeCommonGaTitle = (value?: string | null) =>
  plainCommonMarkedTitle(value || "")
    .trim()
    .replace(/\s+/g, " ")
    .toLowerCase()
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
const mergeTaskEntriesByVisibleTitle = <
  T extends { title: string; assignees?: string[]; person?: string; owner?: string }
>(
  entries: T[]
) => {
  const merged = new Map<string, T>()
  entries.forEach((entry) => {
    const visibleTitle = plainCommonMarkedTitle(entry.title).trim()
    const key = visibleTitle.toLowerCase()
    const existing = merged.get(key)
    if (!existing) {
      merged.set(key, { ...entry, assignees: [...entryAssignees(entry)] })
      return
    }
    const combinedAssignees = Array.from(new Set([...entryAssignees(existing), ...entryAssignees(entry)]))
    merged.set(key, { ...existing, assignees: combinedAssignees })
  })
  return Array.from(merged.values())
}
const getCommonGaEntryMatchKeys = (entry: {
  templateId?: string | null
  matchTitle?: string | null
  title?: string | null
}) => {
  const keys: string[] = []
  if (entry.templateId) keys.push(`template:${entry.templateId}`)
  const titleKey = normalizeCommonGaTitle(entry.matchTitle || entry.title || "")
  if (titleKey) keys.push(`title:${titleKey}`)
  return keys
}
const mergeLabelList = (left?: string, right?: string) => {
  const labels = [...(left ? left.split(",") : []), ...(right ? right.split(",") : [])]
    .map((value) => value.trim())
    .filter(Boolean)
  return Array.from(new Set(labels)).join(", ")
}
const formatBzTimeDisplay = (value?: string | null) => formatTimeLabel(value || "").trim() || "-"
const isNonDailyWeeklyRecurrence = (recurrenceType?: string | null) => {
  if (recurrenceType == null) return false
  const normalized = recurrenceType.trim().toLowerCase()
  return normalized !== "daily" && normalized !== "weekly"
}

const fromISODate = (s: string) => {
  const [y, m, d] = s.split("-").map(Number)
  return new Date(y, (m || 1) - 1, d || 1)
}
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
const parseTimeValue = (value: string) => {
  const match = /^(\d{2}):(\d{2})$/.exec(value)
  if (!match) return null
  const hours = Number(match[1])
  const minutes = Number(match[2])
  if (Number.isNaN(hours) || Number.isNaN(minutes)) return null
  if (hours < 0 || hours > 23 || minutes < 0 || minutes > 59) return null
  return { hours, minutes }
}
const minutesToTimeValue = (minutes: number) => {
  const bounded = Math.max(0, Math.min(minutes, 23 * 60 + 59))
  return `${pad2(Math.floor(bounded / 60))}:${pad2(bounded % 60)}`
}
const addMinutesToTimeValue = (value: string, minutes: number) => {
  const parsed = parseTimeValue(value)
  if (!parsed) return value
  return minutesToTimeValue(parsed.hours * 60 + parsed.minutes + minutes)
}
const parseTimeToMinutes = (value?: string | null) => {
  if (!value) return null
  let normalized = value.trim()
  if (!normalized) return null
  normalized = normalized.replace(/[()]/g, "").trim()
  const lower = normalized.toLowerCase()
  if (lower === "tbd" || lower === "n/a" || lower === "na") return null
  if (
    normalized.includes("–") ||
    normalized.includes("—") ||
    normalized.includes("â€“") ||
    normalized.includes("â€”") ||
    normalized.includes("-")
  ) {
    const separator = normalized.includes("–")
      ? "–"
      : normalized.includes("—")
        ? "—"
        : normalized.includes("â€“")
          ? "â€“"
          : normalized.includes("â€”")
            ? "â€”"
            : "-"
    const [firstPartRaw, secondPartRaw] = normalized.split(separator).map((part) => part.trim())
    const secondPart = secondPartRaw || ""
    const firstPart = firstPartRaw || ""
    const trailingMeridianMatch = /\b(am|pm)\b/i.exec(secondPart)
    const firstHasMeridian = /\b(am|pm)\b/i.test(firstPart)
    normalized =
      trailingMeridianMatch && firstPart && !firstHasMeridian
        ? `${firstPart} ${trailingMeridianMatch[1]}`
        : firstPart
  }
  const amPmMatch = /^(\d{1,2})(?::(\d{2}))?(?::\d{2})?\s*(am|pm)\b/i.exec(normalized)
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
  const timeMatch = /^(\d{1,2}):(\d{2})(?::\d{2})?$/.exec(normalized)
  if (!timeMatch) return null
  const hours = Number(timeMatch[1])
  const minutes = Number(timeMatch[2])
  if (Number.isNaN(hours) || Number.isNaN(minutes)) return null
  if (hours < 0 || hours > 23 || minutes < 0 || minutes > 59) return null
  return hours * 60 + minutes
}
const formatTimeLabel = (value?: string): string => {
  if (!value) return ""
  const normalized = value.trim()
  if (!normalized || normalized.toLowerCase() === "tbd") return normalized
  const amPmMatch = /^(\d{1,2}:\d{2})(?::\d{2})?\s*(am|pm)\b/i.exec(normalized)
  if (amPmMatch) {
    return `${amPmMatch[1]} ${amPmMatch[2].toUpperCase()}`
  }
  const secondsMatch = /^(\d{1,2}:\d{2}):\d{2}$/.exec(normalized)
  if (secondsMatch) {
    return secondsMatch[1]
  }
  if (/am|pm/i.test(normalized)) return normalized
  if (normalized.includes("-")) {
    const [startRaw, endRaw] = normalized.split("-").map((part) => part.trim())
    const startLabel = formatTimeLabel(startRaw)
    const endLabel = formatTimeLabel(endRaw)
    if (startLabel && endLabel) return `${startLabel} - ${endLabel}`
    return normalized
  }
  const parsed = parseTimeValue(normalized)
  if (!parsed) return normalized
  const temp = new Date()
  temp.setHours(parsed.hours, parsed.minutes, 0, 0)
  return formatTime(temp)
}
const getDayCode = (d: Date) => {
  const codes = ["H", "M", "MR", "E", "P", "S", "D"]
  return codes[d.getDay() === 0 ? 6 : d.getDay() - 1] || ""
}

export default function AdminTasksPage() {
  const { apiFetch, user } = useAuth()
  const confirm = useConfirm()
  type AssigneeUser = User | UserLookup
  const [tasks, setTasks] = React.useState<Task[]>([])
  const [systemTasks, setSystemTasks] = React.useState<SystemTaskOut[]>([])
  const [departments, setDepartments] = React.useState<Department[]>([])
  const [users, setUsers] = React.useState<AssigneeUser[]>([])
  const [loadingTasks, setLoadingTasks] = React.useState(true)
  const [createOpen, setCreateOpen] = React.useState(false)
  const [creating, setCreating] = React.useState(false)
  const [viewFilter, setViewFilter] = React.useState<"all" | "tasks" | "system">("all")
  const [priorityFilter, setPriorityFilter] = React.useState<"all" | TaskPriority>("all")
  const [dayFilter, setDayFilter] = React.useState<string>("all")
  const [dateFilter, setDateFilter] = React.useState("")

  const [title, setTitle] = React.useState("")
  const [description, setDescription] = React.useState("")
  const [startDate, setStartDate] = React.useState("")
  const [startDateDisplay, setStartDateDisplay] = React.useState("")
  const [dueDate, setDueDate] = React.useState("")
  const [dueDateDisplay, setDueDateDisplay] = React.useState("")
  const [taskPriority, setTaskPriority] = React.useState<TaskPriority>("NORMAL")
  const [finishPeriod, setFinishPeriod] = React.useState<TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE>(
    FINISH_PERIOD_NONE_VALUE
  )
  const [fastTaskOpen, setFastTaskOpen] = React.useState(false)
  const [creatingFastTask, setCreatingFastTask] = React.useState(false)
  const [fastTaskTitle, setFastTaskTitle] = React.useState("")
  const [fastTaskDescription, setFastTaskDescription] = React.useState("")
  const [fastTaskType, setFastTaskType] = React.useState<(typeof NO_PROJECT_TYPES)[number]["id"]>("normal")
  const [fastTaskAssignees, setFastTaskAssignees] = React.useState<string[]>([])
  const [selectFastTaskAssigneesOpen, setSelectFastTaskAssigneesOpen] = React.useState(false)
  const [fastTaskStartDate, setFastTaskStartDate] = React.useState("")
  const [fastTaskDueDate, setFastTaskDueDate] = React.useState("")
  const [fastTaskDeadlineImportant, setFastTaskDeadlineImportant] = React.useState(false)
  const [fastTaskFinishPeriod, setFastTaskFinishPeriod] = React.useState<
    TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE
  >(FINISH_PERIOD_NONE_VALUE)

  // Edit task state
  const [editOpen, setEditOpen] = React.useState(false)
  const [editingTaskId, setEditingTaskId] = React.useState<string | null>(null)
  const [editTitle, setEditTitle] = React.useState("")
  const [editStartDate, setEditStartDate] = React.useState("")
  const [editDueDate, setEditDueDate] = React.useState("")
  const [editingTaskIsFast, setEditingTaskIsFast] = React.useState(false)
  const [savingEdit, setSavingEdit] = React.useState(false)
  const [deletingTaskId, setDeletingTaskId] = React.useState<string | null>(null)

  const printedAt = React.useMemo(() => new Date(), [])
  const printInitials = initials(user?.full_name || user?.username || "")
  const todayDate = React.useMemo(() => new Date(), [])
  const todayIso = React.useMemo(() => todayDate.toISOString().slice(0, 10), [todayDate])
  const [allTasksDateFrom, setAllTasksDateFrom] = React.useState(() => todayIso)
  const [allTasksDateTo, setAllTasksDateTo] = React.useState(() => todayIso)
  const allTasksThisWeekFrom = toISODate(getMonday(todayDate))
  const allTasksThisWeekTo = toISODate(addDays(getMonday(todayDate), 4))
  const allTasksNextWeekFrom = toISODate(addDays(getMonday(todayDate), 7))
  const allTasksNextWeekTo = toISODate(addDays(getMonday(todayDate), 11))
  const [taskStatusUpdating, setTaskStatusUpdating] = React.useState<Record<string, boolean>>({})
  const [systemStatusOverrides, setSystemStatusOverrides] = React.useState<Record<string, string>>({})
  const [fastEditOpen, setFastEditOpen] = React.useState(false)
  const [fastEditTaskId, setFastEditTaskId] = React.useState<string | null>(null)
  const [fastEditTitle, setFastEditTitle] = React.useState("")
  const [fastEditStartDate, setFastEditStartDate] = React.useState("")
  const [fastEditDueDate, setFastEditDueDate] = React.useState("")
  const [fastEditPriority, setFastEditPriority] = React.useState<TaskPriority>("NORMAL")
  const [fastEditStatus, setFastEditStatus] = React.useState("TODO")
  const [fastEditConfirmationAssigneeId, setFastEditConfirmationAssigneeId] = React.useState("")
  const [fastEditOriginalIsBllok, setFastEditOriginalIsBllok] = React.useState(false)
  const [fastEditSaving, setFastEditSaving] = React.useState(false)
  const [pendingStatusTaskId, setPendingStatusTaskId] = React.useState<string | null>(null)
  const [pendingStatusValue, setPendingStatusValue] = React.useState("TODO")
  const [pendingConfirmationAssigneeId, setPendingConfirmationAssigneeId] = React.useState("")
  const [pendingCompletionOverrideTaskId, setPendingCompletionOverrideTaskId] = React.useState<string | null>(null)
  const [pendingCompletionOverrideReason, setPendingCompletionOverrideReason] = React.useState("")
  const [pendingCompletionCommentTaskId, setPendingCompletionCommentTaskId] = React.useState<string | null>(null)
  const [pendingCompletionComment, setPendingCompletionComment] = React.useState("")
  const [pendingCompletionCommentSaving, setPendingCompletionCommentSaving] = React.useState(false)

  const [printTarget, setPrintTarget] = React.useState<AdminTasksSectionId | null>(null)
  // True when the page was opened through /admin-tasks#ga-time-table.
  const [gaTimeTableFirst, setGaTimeTableFirst] = React.useState(false)
  const [printTotalPages, setPrintTotalPages] = React.useState(1)
  const [collapsedAdminSections, setCollapsedAdminSections] = React.useState<Record<AdminTasksSectionId, boolean>>({
    "all-tasks": false,
    common: false,
    "ga-time": false,
    "one-h-print": false,
  })

  const [dailyReport, setDailyReport] = React.useState<DailyReportResponse | null>(null)
  const [loadingDailyReport, setLoadingDailyReport] = React.useState(false)
  const [showDailyUserReport, setShowDailyUserReport] = React.useState(true)
  const [dailyReportCommentEdits, setDailyReportCommentEdits] = React.useState<Record<string, string>>({})
  const [savingDailyReportComments, setSavingDailyReportComments] = React.useState<Record<string, boolean>>({})
  const [allTasksReportCommentEdits, setAllTasksReportCommentEdits] = React.useState<Record<string, string>>({})
  const [savingAllTasksReportComments, setSavingAllTasksReportComments] = React.useState<Record<string, boolean>>({})
  // ALL TASKS shows one shared comment per task: the latest one, whoever wrote it.
  const [sharedTaskComments, setSharedTaskComments] = React.useState<Record<string, string | null>>({})
  const [exportingDailyReport, setExportingDailyReport] = React.useState(false)
  const [showAllTasksReport, setShowAllTasksReport] = React.useState(false)
  const [exportingAllTasks, setExportingAllTasks] = React.useState(false)
  const [exportingCommonView, setExportingCommonView] = React.useState(false)
  const [exportingGaTime, setExportingGaTime] = React.useState(false)
  const dailyReportScrollRef = React.useRef<HTMLDivElement | null>(null)
  const dailyReportDragRef = React.useRef({ isDragging: false, startX: 0, startScrollLeft: 0 })
  const [isDraggingDailyReport, setIsDraggingDailyReport] = React.useState(false)

  const [commonWeekStart, setCommonWeekStart] = React.useState<Date>(() => getMonday(new Date()))
  const commonWeekISOs = React.useMemo(() => getWeekdays(commonWeekStart).map(toISODate), [commonWeekStart])
  const thisCommonWeekIso = React.useMemo(() => toISODate(getMonday(new Date())), [])
  const nextCommonWeekIso = React.useMemo(() => toISODate(addDays(getMonday(new Date()), 7)), [])
  const setAllTasksQuickRange = (from: string, to: string) => {
    setAllTasksDateFrom(from)
    setAllTasksDateTo(to)

    if (
      (from === todayIso && to === todayIso) ||
      (from === allTasksThisWeekFrom && to === allTasksThisWeekTo)
    ) {
      setCommonWeekStart(getMonday(todayDate))
    } else if (from === allTasksNextWeekFrom && to === allTasksNextWeekTo) {
      setCommonWeekStart(addDays(getMonday(todayDate), 7))
    }
  }
  const [commonUsers, setCommonUsers] = React.useState<User[]>([])
  const [commonDepartments, setCommonDepartments] = React.useState<Department[]>([])
  const [commonData, setCommonData] = React.useState({
    late: [] as LateItem[],
    absent: [] as AbsentItem[],
    leave: [] as LeaveItem[],
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
  const [commonLoading, setCommonLoading] = React.useState(false)
  const [commonError, setCommonError] = React.useState<string | null>(null)
  const [gaSystemByDay, setGaSystemByDay] = React.useState<Record<string, DailyReportSystemOccurrence[]>>({})
  const [gaSystemLoading, setGaSystemLoading] = React.useState(false)
  const [gaSystemError, setGaSystemError] = React.useState<string | null>(null)
  const [gaTimeEntries, setGaTimeEntries] = React.useState<GaTimeSlotEntry[]>([])
  const [gaTimeRows, setGaTimeRows] = React.useState<GaTimeRow[]>(() => [...DEFAULT_GA_TIME_ROWS])
  const [gaTimeLoading, setGaTimeLoading] = React.useState(false)
  const [gaTimeError, setGaTimeError] = React.useState<string | null>(null)
  const [gaTimeSaving, setGaTimeSaving] = React.useState<Record<string, boolean>>({})
  const [gaTimeDeleting, setGaTimeDeleting] = React.useState<Record<string, boolean>>({})
  const [gaTimeEditingId, setGaTimeEditingId] = React.useState<string | null>(null)
  const [gaTimeAddingCell, setGaTimeAddingCell] = React.useState<string | null>(null)
  const [gaTimeDraggingId, setGaTimeDraggingId] = React.useState<string | null>(null)
  const [gaTimeDropTarget, setGaTimeDropTarget] = React.useState<{
    cellKey: string
    beforeEntryId: string | null
  } | null>(null)
  const gaTimeDraggingIdRef = React.useRef<string | null>(null)
  const gaTimeDropTargetRef = React.useRef<{
    dayOfWeek: number
    startTime: string
    endTime: string
    beforeEntryId: string | null
  } | null>(null)
  const gaTimeDropHandledRef = React.useRef(false)
  const [gaTimeCommentEditingKey, setGaTimeCommentEditingKey] = React.useState<string | null>(null)
  const [gaTimeCommentSavingKey, setGaTimeCommentSavingKey] = React.useState<string | null>(null)
  const [gaTimeCommentDragging, setGaTimeCommentDragging] = React.useState<GaTimeCommentDragSource | null>(null)
  const [gaTimeCommentDropTarget, setGaTimeCommentDropTarget] = React.useState<{
    cellKey: string
    beforeCommentId: string | null
  } | null>(null)
  const gaTimeCommentDraggingRef = React.useRef<GaTimeCommentDragSource | null>(null)
  const gaTimeCommentDropTargetRef = React.useRef<(
    | {
        kind: "comment"
        rowStart: string
        rowEnd: string
        column: GaTimeCommentColumn
        beforeCommentId: string | null
      }
    | {
        kind: "slot"
        dayOfWeek: number
        startTime: string
        endTime: string
        beforeEntryId: string | null
      }
  ) | null>(null)
  const gaTimeCommentDropHandledRef = React.useRef(false)
  const gaTimeCommentPointerDragRef = React.useRef<{
    source: GaTimeCommentDragSource
    pointerId: number
    startX: number
    startY: number
    active: boolean
  } | null>(null)
  const [gaTimeCommentPointerPosition, setGaTimeCommentPointerPosition] = React.useState<{
    x: number
    y: number
  } | null>(null)
  const gaTimeCommentSuppressClickRef = React.useRef(false)
  const gaTimeEntryCommentDropTargetRef = React.useRef<{
    rowStart: string
    rowEnd: string
    column: GaTimeCommentColumn
    beforeCommentId: string | null
  } | null>(null)
  const [gaTimeRowsDialogOpen, setGaTimeRowsDialogOpen] = React.useState(false)
  const [gaTimeRowsDraft, setGaTimeRowsDraft] = React.useState<GaTimeRow[]>([])
  const [gaTimeRowsDraftVersion, setGaTimeRowsDraftVersion] = React.useState(0)
  const [gaTimeRowsSaving, setGaTimeRowsSaving] = React.useState(false)
  const [gaTimeNewRowOpen, setGaTimeNewRowOpen] = React.useState(false)
  const [gaTimeNewRowSaving, setGaTimeNewRowSaving] = React.useState(false)
  const [gaIcloudDialogOpen, setGaIcloudDialogOpen] = React.useState(false)
  const [gaCalendarDialogOpen, setGaCalendarDialogOpen] = React.useState(false)
  const [gaCalendarFeedUrl, setGaCalendarFeedUrl] = React.useState<string | null>(null)
  const [gaCalendarAccount, setGaCalendarAccount] = React.useState<{
    server: string
    username: string
    password: string
    accountUrl: string
    profileUrl: string
  } | null>(null)
  const [gaIcloudConnection, setGaIcloudConnection] = React.useState<GaIcloudSyncConnection | null>(null)
  const [gaIcloudPairing, setGaIcloudPairing] = React.useState<GaIcloudSyncPairing | null>(null)
  const [gaIcloudLoading, setGaIcloudLoading] = React.useState(false)
  const [gaIcloudSaving, setGaIcloudSaving] = React.useState(false)
  const [gaIcloudCalendarName, setGaIcloudCalendarName] = React.useState("ganimete.ar@gmail.com")
  const [gaIcloudReminderList, setGaIcloudReminderList] = React.useState("REMINDER")
  const gaTimeRowsDialogRef = React.useRef<HTMLDivElement | null>(null)
  const gaTimeRowInputRefs = React.useRef<
    Record<number, { start: HTMLInputElement | null; end: HTMLInputElement | null }>
  >({})
  const gaTimeNewRowStartRef = React.useRef<HTMLInputElement | null>(null)
  const gaTimeNewRowEndRef = React.useRef<HTMLInputElement | null>(null)
  const [secondarySectionsReady, setSecondarySectionsReady] = React.useState(false)
  // The GA time table does not depend on the heavy task lists, so the direct
  // link loads it at once instead of queueing it behind them.
  const gaSectionsReady = secondarySectionsReady || gaTimeTableFirst
  const confirmerCandidates = React.useMemo(
    () => getConfirmerCandidates(users as UserLookup[]),
    [users]
  )

  const parseFilenameFromDisposition = React.useCallback((headerValue: string | null) => {
    if (!headerValue) return ""
    const match =
      /filename\*=(?:UTF-8'')?([^;]+)/i.exec(headerValue) || /filename=\"?([^\";]+)\"?/i.exec(headerValue)
    if (!match) return ""
    try {
      return decodeURIComponent(match[1].trim().replace(/^\"|\"$/g, ""))
    } catch {
      return match[1].trim().replace(/^\"|\"$/g, "")
    }
  }, [])

  const handleSectionPrint = React.useCallback((target: AdminTasksSectionId) => {
    setCollapsedAdminSections((current) => ({ ...current, [target]: false }))
    setPrintTarget(target)
    window.setTimeout(() => window.print(), 80)
  }, [])

  React.useEffect(() => {
    if (loadingTasks || secondarySectionsReady) return
    const timeoutId = window.setTimeout(() => {
      setSecondarySectionsReady(true)
    }, 0)
    return () => window.clearTimeout(timeoutId)
  }, [loadingTasks, secondarySectionsReady])

  const commonDepartmentsById = React.useMemo(
    () => new Map(commonDepartments.map((d) => [d.id, d])),
    [commonDepartments]
  )
  const getDepartmentMeta = React.useCallback(
    (departmentId?: string) => {
      const dept = departmentId ? commonDepartmentsById.get(departmentId) : undefined
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
    [commonDepartmentsById]
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
  const compareTaskOrder = React.useCallback(
    (
      a: { isDone?: boolean; departmentId?: string; title?: string; person?: string; owner?: string; assignees?: string[] },
      b: { isDone?: boolean; departmentId?: string; title?: string; person?: string; owner?: string; assignees?: string[] }
    ) => {
      const doneA = a.isDone ? 1 : 0
      const doneB = b.isDone ? 1 : 0
      if (doneA !== doneB) return doneA - doneB
      const metaA = getDepartmentMeta(a.departmentId)
      const metaB = getDepartmentMeta(b.departmentId)
      if (metaA.rank !== metaB.rank) return metaA.rank - metaB.rank
      if (metaA.rank === 3) {
        const nameCmp = metaA.name.localeCompare(metaB.name)
        if (nameCmp) return nameCmp
      }
      const personA = getPersonSortKey(a)
      const personB = getPersonSortKey(b)
      if (personA !== personB) return personA.localeCompare(personB)
      return (a.title || "").localeCompare(b.title || "")
    },
    [getDepartmentMeta, getPersonSortKey]
  )
  const sortTasksByOrder = React.useCallback(
    <T extends { date: string; isDone?: boolean; departmentId?: string; title?: string; person?: string; owner?: string; assignees?: string[] }>(
      items: T[]
    ) => {
      const sorted = [...items]
      sorted.sort((a, b) => compareTaskOrder(a, b))
      return sorted
    },
    [compareTaskOrder]
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
    []
  )

  React.useEffect(() => {
    if (!gaSectionsReady) return
    let mounted = true
    async function loadCommonWeek() {
      const weekStartIso = toISODate(commonWeekStart)
      const cacheKey = `common|${user?.id || ""}|${weekStartIso}`
      const cached = readGaViewCache<{ users: any; departments: any; data: any }>(cacheKey)
      if (cached?.data) {
        setCommonUsers(cached.users || [])
        setCommonDepartments(cached.departments || [])
        setCommonData(cached.data)
      } else {
        setCommonLoading(true)
      }
      setCommonError(null)
      try {
        const include = "users,departments,entries,meetings,system_tasks,tasks"
        const res = await apiFetch(
          `/common-view?week_start=${encodeURIComponent(weekStartIso)}&include=${encodeURIComponent(include)}&include_all_departments=true`
        )
        if (!res?.ok) {
          throw new Error(`common_view_failed_${res?.status}`)
        }
        const payload = (await res.json()) as CommonViewPayload
        const normalizedFeedback = payload.items.feedback.map((item) => {
          const parsed = parseFeedbackNote(item.note)
          return {
            ...item,
            note: parsed.note,
            everyday: parsed.everyday,
            date: parsed.everyday ? payload.week_start : item.date,
          }
        })
        const normalizedProblems = payload.items.problems.map((item) => {
          const parsed = parseFeedbackNote(item.note)
          return {
            ...item,
            note: parsed.note,
            everyday: parsed.everyday,
            date: parsed.everyday ? payload.week_start : item.date,
          }
        })
        const normalizedAbsent = payload.items.absent.map((item: any) => ({
          ...item,
          userId: item.userId || item.user_id || undefined,
        }))
        const normalizedBlocked = payload.items.blocked.map((item: any) => ({
          ...item,
          taskId: item.taskId || item.task_id || undefined,
          finishPeriod: item.finishPeriod || item.finish_period || null,
          userId: item.userId || item.user_id || undefined,
        }))
        const normalizedPersonal = payload.items.personal.map((item: any) => ({
          ...item,
          taskId: item.taskId || item.task_id || undefined,
          finishPeriod: item.finishPeriod || item.finish_period || null,
          userId: item.userId || item.user_id || undefined,
        }))
        const normalizedOneH = payload.items.oneH.map((item: any) => ({
          ...item,
          taskId: item.taskId || item.task_id || undefined,
          finishPeriod: item.finishPeriod || item.finish_period || null,
          departmentId: item.departmentId || item.department_id || undefined,
          isDone: Boolean(item.isDone),
          userId: item.userId || item.user_id || undefined,
        }))
        const normalizedR1 = payload.items.r1.map((item: any) => ({
          ...item,
          taskId: item.taskId || item.task_id || undefined,
          finishPeriod: item.finishPeriod || item.finish_period || null,
          departmentId: item.departmentId || item.department_id || undefined,
          isDone: Boolean(item.isDone),
          userId: item.userId || item.user_id || undefined,
        }))
        if (!mounted) return
        const nextCommonData = {
          late: payload.items.late,
          absent: normalizedAbsent,
          leave: payload.items.leave,
          blocked: normalizedBlocked,
          oneH: normalizedOneH,
          personal: normalizedPersonal,
          external: payload.items.external,
          internal: payload.items.internal,
          r1: normalizedR1,
          problems: normalizedProblems,
          feedback: normalizedFeedback,
          priority: payload.items.priority,
          bz: payload.items.bz,
        }
        setCommonUsers(payload.users || [])
        setCommonDepartments(payload.departments || [])
        setCommonData(nextCommonData)
        writeGaViewCache(cacheKey, {
          users: payload.users || [],
          departments: payload.departments || [],
          data: nextCommonData,
        })
      } catch (err) {
        console.error("Failed to load common view data", err)
        if (mounted && !cached?.data) setCommonError("Failed to load common week table.")
      } finally {
        if (mounted) setCommonLoading(false)
      }
    }
    void loadCommonWeek()
    return () => {
      mounted = false
    }
  }, [apiFetch, commonWeekStart, gaSectionsReady, user?.id])

  const isAdmin = String(user?.role || "").trim().toUpperCase() === "ADMIN"
  const ganeUser = React.useMemo(() => findGaneUser(users), [users])
  const ganeUserId = ganeUser?.id ?? null

  const mainCacheKey = `main|${user?.id || ""}|${user?.role || ""}`
  // Set once fresh data arrives so a slower cache read can never overwrite it.
  const mainNetworkLoadedRef = React.useRef(false)

  React.useEffect(() => {
    if (!user?.id) return
    let mounted = true
    void readAdminTasksCache<{
      tasks: Task[]
      departments: Department[]
      systemTasks: SystemTaskOut[]
      users: AssigneeUser[]
    }>(mainCacheKey).then((cached) => {
      if (!mounted || !cached || mainNetworkLoadedRef.current) return
      setTasks(cached.tasks)
      setDepartments(cached.departments)
      setSystemTasks(cached.systemTasks)
      setUsers(cached.users)
      setLoadingTasks(false)
    })
    return () => {
      mounted = false
    }
  }, [mainCacheKey, user?.id])

  const load = React.useCallback(async () => {
    setLoadingTasks(true)
    try {
      const loadUsers = async (): Promise<AssigneeUser[] | null> => {
        if (user?.role === "STAFF") {
          const usersList = await fetchUsersLookupCached(apiFetch)
          return usersList ? (usersList as AssigneeUser[]) : null
        }
        const usersRes = await apiFetch("/users")
        return usersRes.ok ? ((await usersRes.json()) as AssigneeUser[]) : null
      }
      const readJson = async <T,>(res: Response): Promise<T | null> => (res.ok ? ((await res.json()) as T) : null)
      // All four lookups are independent, so they run side by side.
      const tasksPromise = apiFetch("/tasks?include_done=true").then((res) => readJson<Task[]>(res))
      const departmentsPromise = apiFetch("/departments").then((res) => readJson<Department[]>(res))
      const systemTasksPromise = apiFetch("/system-tasks?only_active=false").then((res) =>
        readJson<SystemTaskOut[]>(res)
      )
      const usersPromise = loadUsers()

      // The full company task list is slow; the page only builds rows from
      // GA's tasks. Paint those first from a small request, then swap in the
      // full list once it arrives so everything else stays as before.
      let fullTasksApplied = false
      const loadGaTasksFirst = async () => {
        let ids = readGaIds()
        if (!ids) {
          const [usersList, departmentsList] = await Promise.all([usersPromise, departmentsPromise])
          const gane = findGaneUser(usersList || [])
          if (!gane) return
          ids = { userId: gane.id, departmentId: findGaDepartmentId(departmentsList || []) }
        }
        const qs = new URLSearchParams({ include_done: "true", related_user_id: ids.userId })
        if (ids.departmentId) qs.set("related_department_id", ids.departmentId)
        const [gaTasks, departmentsList, systemTasksList, usersList] = await Promise.all([
          apiFetch(`/tasks?${qs.toString()}`).then((res) => readJson<Task[]>(res)),
          departmentsPromise,
          systemTasksPromise,
          usersPromise,
        ])
        if (fullTasksApplied || !gaTasks) return
        mainNetworkLoadedRef.current = true
        setTasks(gaTasks)
        if (departmentsList) setDepartments(departmentsList)
        if (systemTasksList) setSystemTasks(systemTasksList)
        if (usersList) setUsers(usersList)
        setLoadingTasks(false)
      }
      void loadGaTasksFirst().catch((error) => console.error("Failed to load GA tasks first", error))

      const [nextTasks, nextDepartments, nextSystemTasks, nextUsers] = await Promise.all([
        tasksPromise,
        departmentsPromise,
        systemTasksPromise,
        usersPromise,
      ])
      fullTasksApplied = true
      mainNetworkLoadedRef.current = true
      const gane = findGaneUser(nextUsers || [])
      if (gane) writeGaIds({ userId: gane.id, departmentId: findGaDepartmentId(nextDepartments || []) })
      if (nextTasks) setTasks(nextTasks)
      if (nextDepartments) setDepartments(nextDepartments)
      if (nextSystemTasks) setSystemTasks(nextSystemTasks)
      if (nextUsers) setUsers(nextUsers)
      if (user?.id && nextTasks && nextDepartments && nextSystemTasks && nextUsers) {
        void writeAdminTasksCache(mainCacheKey, {
          tasks: nextTasks,
          departments: nextDepartments,
          systemTasks: nextSystemTasks,
          users: nextUsers,
        })
      }
    } finally {
      setLoadingTasks(false)
    }
  }, [apiFetch, mainCacheKey, user?.id, user?.role])

  const adminDepartmentId = React.useMemo(() => findGaDepartmentId(departments), [departments])

  const fastTaskAssigneeLabel = React.useMemo(() => {
    if (fastTaskAssignees.length === 0) return "Unassigned"
    if (users.length && fastTaskAssignees.length === users.length) return "All users"
    if (fastTaskAssignees.length === 1) {
      const selected = users.find((u) => u.id === fastTaskAssignees[0])
      return selected?.full_name || selected?.username || "1 selected"
    }
    return `${fastTaskAssignees.length} selected`
  }, [fastTaskAssignees, users])

  const loadGaIcloudConnection = React.useCallback(async () => {
    setGaIcloudLoading(true)
    try {
      const res = await apiFetch("/ga-time-slots/icloud-sync")
      if (!res.ok) {
        const data = await res.json().catch(() => null)
        throw new Error(apiErrorMessage(data, "Failed to load iPhone sync status."))
      }
      const data = (await res.json()) as GaIcloudSyncConnection | null
      setGaIcloudConnection(data)
      if (data) {
        setGaIcloudCalendarName(data.calendar_name)
        setGaIcloudReminderList(data.reminder_list_name)
      }
    } catch (error) {
      console.error("Failed to load iPhone sync status", error)
      toast.error(error instanceof Error ? error.message : "Failed to load iPhone sync status.")
    } finally {
      setGaIcloudLoading(false)
    }
  }, [apiFetch])

  const openGaIcloudDialog = React.useCallback(() => {
    setGaIcloudPairing(null)
    setGaIcloudDialogOpen(true)
    void loadGaIcloudConnection()
  }, [loadGaIcloudConnection])

  const openGaCalendarDialog = React.useCallback(async () => {
    setGaCalendarDialogOpen(true)
    if (gaCalendarFeedUrl && gaCalendarAccount) return
    try {
      const [feedRes, accountRes] = await Promise.all([
        apiFetch("/ga-time-slots/calendar-feed"),
        apiFetch("/ga-time-slots/calendar-account"),
      ])
      if (!feedRes.ok || !accountRes.ok) throw new Error("Failed to load the calendar details.")
      const feed = (await feedRes.json()) as { feed_path: string }
      const account = (await accountRes.json()) as {
        username: string
        password: string
        principal_path: string
        profile_path: string
      }
      // The calendar account lives on the API host itself, outside the /api prefix.
      const apiOrigin = new URL(API_HTTP_URL, window.location.origin).origin
      setGaCalendarFeedUrl(`${API_HTTP_URL}${feed.feed_path}`)
      setGaCalendarAccount({
        server: new URL(apiOrigin).host,
        username: account.username,
        password: account.password,
        accountUrl: `${apiOrigin}${account.principal_path}`,
        profileUrl: `${API_HTTP_URL}${account.profile_path}`,
      })
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to load the calendar details.")
    }
  }, [apiFetch, gaCalendarAccount, gaCalendarFeedUrl])

  const pairGaIcloudDevice = React.useCallback(async () => {
    const calendarName = gaIcloudCalendarName.trim()
    const reminderListName = gaIcloudReminderList.trim()
    if (!calendarName || !reminderListName) {
      toast.error("Calendar and reminder list names are required.")
      return
    }
    if (gaIcloudConnection) {
      const accepted = await confirm({
        title: "Replace iPhone connection?",
        description: "The existing token will stop working. The new token is shown only once.",
        confirmLabel: "Replace connection",
        variant: "destructive",
      })
      if (!accepted) return
    }
    setGaIcloudSaving(true)
    try {
      const res = await apiFetch("/ga-time-slots/icloud-sync/pair", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          device_name: "iPhone GA",
          calendar_name: calendarName,
          reminder_list_name: reminderListName,
        }),
      })
      const data = await res.json().catch(() => null)
      if (!res.ok) throw new Error(apiErrorMessage(data, "Failed to create iPhone connection."))
      const pairing = data as GaIcloudSyncPairing
      setGaIcloudPairing(pairing)
      setGaIcloudConnection(pairing)
      toast.success("iPhone pairing created. Save the token now; it is shown only once.")
    } catch (error) {
      console.error("Failed to pair iPhone sync", error)
      toast.error(error instanceof Error ? error.message : "Failed to create iPhone connection.")
    } finally {
      setGaIcloudSaving(false)
    }
  }, [apiFetch, confirm, gaIcloudCalendarName, gaIcloudConnection, gaIcloudReminderList])

  const revokeGaIcloudDevice = React.useCallback(async () => {
    if (!gaIcloudConnection) return
    const accepted = await confirm({
      title: "Disconnect iPhone sync?",
      description: "Imported Calendar and Reminder entries will be removed. The phone token will stop working.",
      confirmLabel: "Disconnect",
      variant: "destructive",
    })
    if (!accepted) return
    setGaIcloudSaving(true)
    try {
      const res = await apiFetch(`/ga-time-slots/icloud-sync/${gaIcloudConnection.id}`, { method: "DELETE" })
      if (!res.ok) {
        const data = await res.json().catch(() => null)
        throw new Error(apiErrorMessage(data, "Failed to disconnect iPhone sync."))
      }
      setGaIcloudConnection(null)
      setGaIcloudPairing(null)
      setGaTimeEntries((entries) => entries.filter((entry) => !entry.source_type))
      toast.success("iPhone sync disconnected.")
    } catch (error) {
      console.error("Failed to disconnect iPhone sync", error)
      toast.error(error instanceof Error ? error.message : "Failed to disconnect iPhone sync.")
    } finally {
      setGaIcloudSaving(false)
    }
  }, [apiFetch, confirm, gaIcloudConnection])

  const copyGaIcloudValue = React.useCallback(async (value: string, label: string) => {
    try {
      await navigator.clipboard.writeText(value)
      toast.success(`${label} copied.`)
    } catch {
      toast.error(`Could not copy ${label.toLowerCase()}.`)
    }
  }, [])

  React.useEffect(() => {
    if (!gaSectionsReady) return
    let mounted = true
    async function loadGaTimeSlots() {
      const weekStartIso = toISODate(commonWeekStart)
      const cacheKey = `slots|${user?.id || ""}|${weekStartIso}`
      const cached = readGaViewCache<{ rows: GaTimeRow[]; entries: GaTimeSlotEntry[] }>(cacheKey)
      if (cached?.rows && cached.entries) {
        setGaTimeRows(cached.rows)
        setGaTimeEntries(cached.entries)
      } else {
        setGaTimeLoading(true)
      }
      setGaTimeError(null)
      try {
        const [rowsRes, entriesRes] = await Promise.all([
          apiFetch("/ga-time-slots/rows"),
          apiFetch(`/ga-time-slots?week_start=${encodeURIComponent(weekStartIso)}`),
        ])
        if (!rowsRes.ok) {
          throw new Error(`ga_time_rows_failed_${rowsRes.status}`)
        }
        if (!entriesRes.ok) {
          throw new Error(`ga_time_slots_failed_${entriesRes.status}`)
        }
        const rows = normalizeGaTimeRows((await rowsRes.json()) as GaTimeTableRowResponse[])
        const data = (await entriesRes.json()) as GaTimeSlotEntry[]
        if (!mounted) return
        const nextRows = rows.length ? rows : [...DEFAULT_GA_TIME_ROWS]
        setGaTimeRows(nextRows)
        setGaTimeEntries(data)
        writeGaViewCache(cacheKey, { rows: nextRows, entries: data })
      } catch (err) {
        console.error("Failed to load GA time slots", err)
        if (mounted && !cached) setGaTimeError("Failed to load GA time slots.")
      } finally {
        if (mounted) setGaTimeLoading(false)
      }
    }
    void loadGaTimeSlots()
    return () => {
      mounted = false
    }
  }, [apiFetch, commonWeekStart, gaSectionsReady, user?.id])

  React.useEffect(() => {
    if (!secondarySectionsReady) return
    let mounted = true
    async function loadGaSystemByDay() {
      if (!ganeUserId) {
        setGaSystemByDay({})
        return
      }
      const cacheKey = `system|${user?.id || ""}|${ganeUserId}|${adminDepartmentId || ""}|${commonWeekISOs.join(",")}`
      const cached = readGaViewCache<Record<string, DailyReportSystemOccurrence[]>>(cacheKey)
      if (cached) {
        setGaSystemByDay(cached)
      } else {
        setGaSystemLoading(true)
      }
      setGaSystemError(null)
      try {
        const results = await Promise.all(
          commonWeekISOs.map(async (iso) => {
            const params: Record<string, string> = { day: iso, user_id: ganeUserId }
            if (adminDepartmentId) params.department_id = adminDepartmentId
            const qs = new URLSearchParams(params)
            const res = await apiFetch(`/reports/daily?${qs.toString()}`)
            if (!res.ok) throw new Error(`daily_report_failed_${res.status}`)
            const payload = (await res.json()) as DailyReportResponse
            const occurrences = [...(payload.system_today || []), ...(payload.system_overdue || [])].filter(
              (occ) => occ.occurrence_date === iso
            )
            return [iso, occurrences] as const
          })
        )
        if (!mounted) return
        const nextMap: Record<string, DailyReportSystemOccurrence[]> = {}
        for (const [iso, occurrences] of results) {
          nextMap[iso] = occurrences
        }
        setGaSystemByDay(nextMap)
        writeGaViewCache(cacheKey, nextMap)
      } catch (err) {
        console.error("Failed to load GA system occurrences", err)
        if (mounted && !cached) setGaSystemError("Failed to load DET GA system tasks.")
      } finally {
        if (mounted) setGaSystemLoading(false)
      }
    }
    void loadGaSystemByDay()
    return () => {
      mounted = false
    }
  }, [adminDepartmentId, apiFetch, commonWeekISOs, ganeUserId, secondarySectionsReady, user?.id])

  const loadDailyReport = React.useCallback(async () => {
    // This section always displays Gane's report for the GA department.
    // Wait until both async lookups are ready so we never briefly request
    // the logged-in admin's report with GA's department (which returns 403).
    if (!ganeUserId || !adminDepartmentId) return
    setLoadingDailyReport(true)
    try {
      const params: Record<string, string> = {
        day: todayIso,
        user_id: ganeUserId,
        department_id: adminDepartmentId,
      }
      const qs = new URLSearchParams(params)
      const res = await apiFetch(`/reports/daily?${qs.toString()}`)
      if (!res.ok) {
        toast.error("Failed to load daily report")
        return
      }
      setDailyReport((await res.json()) as DailyReportResponse)
    } catch (error) {
      console.error("Failed to load daily report", error)
      toast.error("Failed to load daily report")
    } finally {
      setLoadingDailyReport(false)
    }
  }, [adminDepartmentId, apiFetch, ganeUserId, todayIso])

  React.useEffect(() => {
    void load()
  }, [load])

  React.useEffect(() => {
    if (!showDailyUserReport) return
    void loadDailyReport()
  }, [loadDailyReport, showDailyUserReport])

  React.useEffect(() => {
    const handleBeforePrint = () => {
      if (printTarget === "ga-time" || printTarget === "common") {
        setPrintTotalPages(1)
        return
      }

      const printRoot = document.querySelector(`[data-print-target="${printTarget || ""}"]`) as HTMLElement | null
      const activeSection = printRoot?.querySelector(
        `.print-section[data-print-section="${printTarget}"]`
      ) as HTMLElement | null

      const dpi = 96
      const pageHeightPx = 11 * dpi - (0.36 + 0.51) * dpi
      const sectionHeight = activeSection?.scrollHeight || activeSection?.offsetHeight || 0
      const bodyHeight = Math.max(
        document.body.scrollHeight,
        document.documentElement.scrollHeight,
        document.body.offsetHeight
      )
      const measuredHeight = sectionHeight || bodyHeight
      const totalPages = Math.max(1, Math.ceil(measuredHeight / pageHeightPx))
      setPrintTotalPages(totalPages)
    }
    const handleAfterPrint = () => setPrintTarget(null)
    window.addEventListener("beforeprint", handleBeforePrint)
    window.addEventListener("afterprint", handleAfterPrint)
    return () => {
      window.removeEventListener("beforeprint", handleBeforePrint)
      window.removeEventListener("afterprint", handleAfterPrint)
    }
  }, [printTarget])


  const submitTask = async () => {
    if (!title.trim()) {
      toast.error("Task title is required")
      return
    }
    if (!ganeUserId) {
      toast.error("Gane Arifaj user not found. Cannot assign task.")
      return
    }
    setCreating(true)
    try {
      const startDateValue = startDate ? new Date(startDate).toISOString() : null
      const dueDateValue = dueDate ? new Date(dueDate).toISOString() : null
      const isBllok = taskPriority === "BLLOK"
      const actualPriority: "NORMAL" | "HIGH" = isBllok ? "NORMAL" : (taskPriority === "HIGH" ? "HIGH" : "NORMAL")
      const payload: Record<string, unknown> = {
        title: title.trim(),
        description: description.trim() || null,
        status: "TODO",
        priority: actualPriority,
        finish_period: finishPeriod === FINISH_PERIOD_NONE_VALUE ? null : finishPeriod,
        start_date: startDateValue,
        due_date: dueDateValue,
        is_deadline_important: false,
        assigned_to: ganeUserId,
        ...(isBllok && { is_bllok: true }),
      }
      const res = await apiFetch("/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        let detail = "Failed to create task"
        try {
          const data = (await res.json()) as { detail?: string | Array<{ msg?: string }> }
          if (data?.detail) {
            if (typeof data.detail === "string") {
              detail = data.detail
            } else if (Array.isArray(data.detail) && data.detail.length > 0) {
              detail = data.detail.map((e) => e.msg || "Validation error").join(", ")
            }
          }
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }
      const created = (await res.json()) as Task
      setTasks((prev) => [created, ...prev])
      setCreateOpen(false)
      setTitle("")
      setDescription("")
      setStartDate("")
      setStartDateDisplay("")
      setDueDate("")
      setDueDateDisplay("")
      setTaskPriority("NORMAL")
      setFinishPeriod(FINISH_PERIOD_NONE_VALUE)
      toast.success("Task created")
    } finally {
      setCreating(false)
    }
  }

  const departmentMap = React.useMemo(() => new Map(departments.map((dept) => [dept.id, dept])), [departments])
  const userMap = React.useMemo(() => new Map(users.map((person) => [person.id, person])), [users])
  const taskAssigneeInitials = React.useCallback(
    (task: Task) => {
      const ids = new Set<string>()
      if (task.assigned_to) ids.add(task.assigned_to)
      if (task.assignees) {
        for (const assignee of task.assignees) {
          if (assignee.id) ids.add(assignee.id)
        }
      }
      if (!ids.size) return ""
      const labels = Array.from(ids)
        .map((userId) => {
          const userFromMap = userMap.get(userId)
          if (userFromMap) return userFromMap.full_name || userFromMap.username || ""
          const assigneeFromArray = task.assignees?.find((a) => a.id === userId)
          return assigneeFromArray?.full_name || assigneeFromArray?.username || ""
        })
        .filter(Boolean)
      if (!labels.length) return ""
      return labels.map((label) => initials(label)).join(", ")
    },
    [userMap]
  )
  const systemAssigneeInitials = React.useCallback(
    (task: SystemTaskOut) => {
      const ids = new Set<string>()
      if (task.default_assignee_id) ids.add(task.default_assignee_id)
      if (task.assignees) {
        for (const assignee of task.assignees) {
          if (assignee.id) ids.add(assignee.id)
        }
      }
      if (!ids.size) return ""
      const labels = Array.from(ids)
        .map((userId) => {
          const userFromMap = userMap.get(userId)
          if (userFromMap) return userFromMap.full_name || userFromMap.username || ""
          const assigneeFromArray = task.assignees?.find((a) => a.id === userId)
          return assigneeFromArray?.full_name || assigneeFromArray?.username || ""
        })
        .filter(Boolean)
      if (!labels.length) return ""
      return labels.map((label) => initials(label)).join(", ")
    },
    [userMap]
  )
  const taskAssigneeDepartments = React.useCallback(
    (task: Task) => {
      const ids = new Set<string>()
      if (task.assigned_to) ids.add(task.assigned_to)
      if (task.assignees) {
        for (const assignee of task.assignees) {
          if (assignee.id) ids.add(assignee.id)
        }
      }
      if (!ids.size) return ""
      const labels = Array.from(ids)
        .map((userId) => {
          const userFromMap = userMap.get(userId)
          const deptId =
            userFromMap?.department_id || task.assignees?.find((assignee) => assignee.id === userId)?.department_id
          if (!deptId) return ""
          const dept = departmentMap.get(deptId)
          if (!dept) return ""
          const code = (dept.code || "").trim().toUpperCase()
          return code || (dept.name || "").trim()
        })
        .filter(Boolean)
      if (!labels.length) return ""
      return Array.from(new Set(labels)).sort().join(", ")
    },
    [departmentMap, userMap]
  )
  const systemAssigneeDepartments = React.useCallback(
    (task: SystemTaskOut) => {
      const ids = new Set<string>()
      if (task.default_assignee_id) ids.add(task.default_assignee_id)
      if (task.assignees) {
        for (const assignee of task.assignees) {
          if (assignee.id) ids.add(assignee.id)
        }
      }
      if (!ids.size) return ""
      const labels = Array.from(ids)
        .map((userId) => {
          const userFromMap = userMap.get(userId)
          const deptId =
            userFromMap?.department_id || task.assignees?.find((assignee) => assignee.id === userId)?.department_id
          if (!deptId) return ""
          const dept = departmentMap.get(deptId)
          if (!dept) return ""
          const code = (dept.code || "").trim().toUpperCase()
          return code || (dept.name || "").trim()
        })
        .filter(Boolean)
      if (!labels.length) return ""
      return Array.from(new Set(labels)).sort().join(", ")
    },
    [departmentMap, userMap]
  )
  const systemTaskByTemplateId = React.useMemo(() => {
    const map = new Map<string, SystemTaskOut>()
    for (const task of systemTasks) {
      map.set(task.template_id, task)
    }
    return map
  }, [systemTasks])

  const taskAssigneeBadges = React.useCallback(
    (task: Task): AllTasksAssigneeBadge[] => {
      const seen = new Set<string>()
      const orderedIds: string[] = []
      const pushId = (id: string | null | undefined) => {
        if (!id || seen.has(id)) return
        seen.add(id)
        orderedIds.push(id)
      }
      pushId(task.assigned_to)
      for (const assignee of task.assignees || []) {
        pushId(assignee.id)
      }

      // A generated system-task occurrence can contain only the copy assigned to GA.
      // Include the source template's complete assignee list so the other executors
      // still appear in ALL TASKS (for example, HS on a template assigned to HS + GA).
      const systemTemplate = task.system_template_origin_id
        ? systemTaskByTemplateId.get(task.system_template_origin_id)
        : undefined
      if (systemTemplate) {
        pushId(systemTemplate.default_assignee_id)
        for (const assignee of systemTemplate.assignees || []) {
          pushId(assignee.id)
        }
      }

      // ALL TASKS "BZ ME" column: show task executors only, never alignment / "BZ me" managers (e.g. GA).
      const alignmentExclude = new Set<string>()
      for (const id of task.alignment_user_ids || []) {
        if (id) alignmentExclude.add(id)
      }
      if (systemTemplate) {
        for (const id of systemTemplate.alignment_user_ids || []) {
          if (id) alignmentExclude.add(id)
        }
      }

      const filteredIds = orderedIds.filter((userId) => !alignmentExclude.has(userId))
      if (!filteredIds.length) return []

      return filteredIds
        .map((userId) => {
          const userFromMap = userMap.get(userId)
          const label =
            (userFromMap ? userFromMap.full_name || userFromMap.username : "") ||
            task.assignees?.find((a) => a.id === userId)?.full_name ||
            task.assignees?.find((a) => a.id === userId)?.username ||
            systemTemplate?.assignees?.find((a) => a.id === userId)?.full_name ||
            systemTemplate?.assignees?.find((a) => a.id === userId)?.username ||
            ""
          const trimmed = label.trim()
          if (!trimmed) return null
          return {
            id: `${task.id}-${userId}`,
            userId,
            value: initials(trimmed),
            label: trimmed,
          }
        })
        .filter((b): b is AllTasksAssigneeBadge => b !== null)
    },
    [userMap, systemTaskByTemplateId]
  )
  const systemAssigneeBadges = React.useCallback(
    (task: SystemTaskOut) => {
      const ids = new Set<string>()
      if (task.default_assignee_id) ids.add(task.default_assignee_id)
      if (task.assignees) {
        for (const assignee of task.assignees) {
          if (assignee.id) ids.add(assignee.id)
        }
      }
      if (!ids.size) return []
      const labels = Array.from(ids)
        .map((userId) => {
          const userFromMap = userMap.get(userId)
          if (userFromMap) return userFromMap.full_name || userFromMap.username || ""
          const assigneeFromArray = task.assignees?.find((a) => a.id === userId)
          return assigneeFromArray?.full_name || assigneeFromArray?.username || ""
        })
        .filter(Boolean)
      return labels.map((label, index) => ({
        id: `${task.id}-${index}`,
        value: initials(label),
        label,
      }))
    },
    [userMap]
  )

  const adminTaskRows = React.useMemo(() => {
    const rows: Task[] = []
    const hasGane = Boolean(ganeUserId)

    for (const task of tasks) {
      const isSystem = Boolean(task.system_template_origin_id || task.task_type === "system")
      if (isSystem) continue
      if (task.is_active === false) continue

      const assignedToGane =
        hasGane &&
        (task.assigned_to === ganeUserId ||
          task.assignees?.some((assignee) => assignee.id === ganeUserId) ||
          task.alignment_user_ids?.includes(ganeUserId as string))
      const inGaDepartment = Boolean(adminDepartmentId && task.department_id === adminDepartmentId)
      if (!assignedToGane && !inGaDepartment) continue

      rows.push(task)
    }

    return rows
  }, [adminDepartmentId, ganeUserId, tasks])

  const filteredTasks = React.useMemo(() => {
    if (viewFilter === "system") return []
    let filtered = adminTaskRows
    if (priorityFilter !== "all") {
      filtered = filtered.filter(
        (task) => getDisplayPriority(task).toUpperCase() === priorityFilter
      )
    }
    if (dateFilter) {
      filtered = filtered.filter((task) => {
        if (!task.due_date) return false
        const iso = new Date(task.due_date).toISOString().slice(0, 10)
        return iso === dateFilter
      })
    }
    if (dayFilter !== "all") {
      const targetDay = Number(dayFilter)
      if (!Number.isNaN(targetDay)) {
        filtered = filtered.filter((task) => {
          if (!task.due_date) return false
          const day = getMondayBasedDay(new Date(task.due_date))
          return day === targetDay
        })
      }
    }
    return filtered
  }, [adminTaskRows, dateFilter, dayFilter, priorityFilter, viewFilter])

  const sortedTasks = React.useMemo(
    () =>
      [...filteredTasks].sort((a, b) => {
        const aCreated = a.created_at ? new Date(a.created_at).getTime() : 0
        const bCreated = b.created_at ? new Date(b.created_at).getTime() : 0
        return bCreated - aCreated
      }),
    [filteredTasks]
  )

  const taskCommentMap = React.useMemo(() => {
    const map = new Map<string, string | null>()
    for (const task of tasks) {
      map.set(task.id, task.user_comment ?? null)
    }
    return map
  }, [tasks])

  const allTasksTableRows = React.useMemo(() => {
    const rows: Array<{
      id: string
      ll: "SYS" | "FT"
      nll: string
      assigned: AllTasksAssigneeBadge[]
      startDateIso: string
      startDateLabel: string
      dateIso: string
      dateLabel: string
      period: string
      title: string
      oneHMarker?: Task["one_h_marker"]
      systemFrequency: string
      systemFrequencyDisplayLabel: string
      bz: string
      kohaBz: string
      status: string
      priority: TaskPriority
      comment?: string | null
      taskId: string
      isFastTask?: boolean
      isTemplateAlignedSystem?: boolean
      needsGaneConfirmation?: boolean
      isLateSystemTask?: boolean
      lateDays?: number
      isGaneAssigned?: boolean
      isGaneRealAssignee?: boolean
      isBzOnly?: boolean
      systemTemplateOriginId?: string | null
    }> = []

    if (!ganeUserId) return rows

    for (const task of tasks) {
      if (task.is_active === false) continue

      const isSystemTask = Boolean(task.system_template_origin_id || task.task_type === "system")
      const systemTemplate = task.system_template_origin_id
        ? systemTaskByTemplateId.get(task.system_template_origin_id)
        : undefined
      const hasTaskAlignment = Boolean(ganeUserId && task.alignment_user_ids?.includes(ganeUserId))
      const hasTemplateAlignment = Boolean(
        isSystemTask && ganeUserId && systemTemplate?.alignment_user_ids?.includes(ganeUserId)
      )
      const isRealAssignee =
        task.assigned_to === ganeUserId ||
        Boolean(task.assignees?.some((assignee) => assignee.id === ganeUserId))
      const isAssigned = isRealAssignee || hasTaskAlignment
      const needsGaneConfirmation =
        task.status === "WAITING_CONFIRMATION" && task.confirmation_assignee_id === ganeUserId

      const startDateIso = toDateOnlyIso(task.start_date || null)
      const dueDateIso = getTaskDateIso(task)
      const dueDateDisplayIso = toDateOnlyIso(task.due_date || null)
      const dateIso = dueDateIso || startDateIso
      const statusValue = task.status || (task.completed_at ? "DONE" : "TODO")
      const systemFrequency = isSystemTask ? systemTemplate?.frequency || "" : ""
      const hasGaneBzToday = (hasTaskAlignment || hasTemplateAlignment) && dateIso === todayIso
      const completedDateIso = toDateOnlyIso(task.completed_at || null)
      const computedLateDays =
        statusValue === "DONE"
          ? dueDateIso && completedDateIso && dueDateIso < completedDateIso
            ? Math.max(task.late_days ?? 0, dayDiffInclusive(dueDateIso, completedDateIso))
            : 0
          : dueDateIso && dueDateIso < todayIso
            ? Math.max(task.late_days ?? 0, dayDiffInclusive(dueDateIso, todayIso))
            : 0
      const isLateSystemTask = Boolean(isSystemTask && (isAssigned || hasTemplateAlignment) && computedLateDays > 0)
      // Keep system tasks on the list when due on/before today if Gane is alignment-only — otherwise overdue
      // rows disappear after the due day (hasGaneBzToday only matched dateIso === today).
      const alignmentSystemStillOpen =
        isSystemTask &&
        statusValue !== "DONE" &&
        Boolean(dueDateIso && dueDateIso <= todayIso) &&
        (hasTemplateAlignment || hasTaskAlignment)
      if (!isAssigned && !needsGaneConfirmation && !hasGaneBzToday && !alignmentSystemStillOpen) continue

      rows.push({
        id: `task:${task.id}`,
        ll: isSystemTask ? "SYS" : "FT",
        nll: isSystemTask ? "SYS" : task.project_id ? "-" : fastReportSubtypeShort(task),
        assigned: taskAssigneeBadges(task),
        startDateIso,
        startDateLabel: startDateIso ? formatDateDayMonth(startDateIso) : "-",
        dateIso,
        dateLabel: dueDateDisplayIso ? formatDateDayMonth(dueDateDisplayIso) : "-",
        period: resolvePeriod(task.finish_period, task.due_date || task.start_date || task.created_at),
        title: task.title || "-",
        oneHMarker: task.one_h_marker,
        systemFrequency,
        systemFrequencyDisplayLabel: systemFrequencyDisplayLabel(systemFrequency),
        bz: hasTaskAlignment || hasTemplateAlignment ? "GA" : "-",
        kohaBz: hasTemplateAlignment ? formatTimeLabel(systemTemplate?.alignment_time || "") || "TPL" : "-",
        status: statusValue,
        priority: getDisplayPriority(task),
        comment: taskCommentMap.get(task.id) ?? null,
        taskId: task.id,
        isFastTask: !task.project_id && !isSystemTask,
        isTemplateAlignedSystem: hasTemplateAlignment,
        needsGaneConfirmation,
        isLateSystemTask,
        lateDays: computedLateDays,
        isGaneAssigned: isAssigned,
        isGaneRealAssignee: isRealAssignee,
        isBzOnly: !isAssigned && !needsGaneConfirmation && hasGaneBzToday,
        systemTemplateOriginId: task.system_template_origin_id ?? null,
      })
    }

    const dedupedRows = new Map<string, (typeof rows)[number]>()
    for (const row of rows) {
      const dedupeKey = [
        row.ll,
        row.nll,
        row.title.trim().toLowerCase(),
        row.startDateIso || "-",
        row.dateIso || "-",
        row.period || "-",
        row.kohaBz || "-",
      ].join("|")
      const existing = dedupedRows.get(dedupeKey)
      if (!existing) {
        dedupedRows.set(dedupeKey, row)
        continue
      }
      dedupedRows.set(dedupeKey, {
        ...existing,
        assigned: mergeAllTasksAssigneeBadges(existing.assigned, row.assigned),
        systemFrequency: existing.systemFrequency || row.systemFrequency,
        systemFrequencyDisplayLabel: existing.systemFrequencyDisplayLabel || row.systemFrequencyDisplayLabel,
        systemTemplateOriginId: existing.systemTemplateOriginId || row.systemTemplateOriginId,
        needsGaneConfirmation: Boolean(existing.needsGaneConfirmation || row.needsGaneConfirmation),
        isLateSystemTask: Boolean(existing.isLateSystemTask || row.isLateSystemTask),
        lateDays: Math.max(existing.lateDays ?? 0, row.lateDays ?? 0) || undefined,
        isGaneAssigned: Boolean(existing.isGaneAssigned || row.isGaneAssigned),
        isGaneRealAssignee: Boolean(existing.isGaneRealAssignee || row.isGaneRealAssignee),
        isBzOnly: Boolean(existing.isBzOnly && row.isBzOnly),
      })
    }

    const orderedRows = Array.from(dedupedRows.values())
    orderedRows.sort((a, b) => {
      const aFast = Boolean(a.isFastTask)
      const bFast = Boolean(b.isFastTask)
      if (aFast !== bFast) return aFast ? -1 : 1
      const frequencyComparison = compareSystemFrequency(a.systemFrequency, b.systemFrequency)
      if (frequencyComparison) return frequencyComparison
      const aMinutes = parseTimeToMinutes(a.kohaBz)
      const bMinutes = parseTimeToMinutes(b.kohaBz)
      if (aMinutes !== null && bMinutes !== null && aMinutes !== bMinutes) return aMinutes - bMinutes
      if (aMinutes !== null && bMinutes === null) return -1
      if (aMinutes === null && bMinutes !== null) return 1
      const aLate = a.isLateSystemTask ? 1 : 0
      const bLate = b.isLateSystemTask ? 1 : 0
      if (aLate !== bLate) return bLate - aLate
      if (a.dateIso !== b.dateIso) return b.dateIso.localeCompare(a.dateIso)
      return a.title.localeCompare(b.title)
    })

    // Match Common View BZ: merge assignees across all instances of the same system template on the same day.
    return orderedRows.map((row) => {
      if (row.ll !== "SYS" || !row.systemTemplateOriginId || !row.dateIso) return row
      const byUser = new Map<string, AllTasksAssigneeBadge>()
      for (const t of tasks) {
        if (t.is_active === false) continue
        if (t.system_template_origin_id !== row.systemTemplateOriginId) continue
        if (getTaskDateIso(t) !== row.dateIso) continue
        for (const b of taskAssigneeBadges(t)) {
          if (!byUser.has(b.userId)) byUser.set(b.userId, b)
        }
      }
      const merged = Array.from(byUser.values()).sort((a, b) => a.label.localeCompare(b.label))
      if (!merged.length) return row
      return { ...row, assigned: merged }
    })
  }, [
    tasks,
    ganeUserId,
    systemTaskByTemplateId,
    taskAssigneeBadges,
    taskCommentMap,
    todayIso,
  ])

  const filteredAllTasksRows = React.useMemo(() => {
    if (!allTasksDateFrom && !allTasksDateTo) return allTasksTableRows
    return allTasksTableRows.filter((row) => {
      // Keep open overdue tasks visible even when the date filter starts at today
      // (same behavior previously only applied to late system tasks).
      if (row.status !== "DONE" && row.dateIso && row.dateIso < todayIso) {
        return true
      }
      return isIsoWithinInclusiveRange(row.dateIso, allTasksDateFrom, allTasksDateTo)
    })
  }, [allTasksDateFrom, allTasksDateTo, allTasksTableRows, todayIso])

  const allTasksCommentIds = React.useMemo(
    () => Array.from(new Set(filteredAllTasksRows.map((row) => row.taskId).filter(Boolean))).sort().join(","),
    [filteredAllTasksRows]
  )

  React.useEffect(() => {
    if (!allTasksCommentIds) return
    let cancelled = false
    void (async () => {
      try {
        const res = await apiFetch("/tasks/shared-comments", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ task_ids: allTasksCommentIds.split(",") }),
        })
        if (!res.ok || cancelled) return
        const rows = (await res.json()) as Array<{ task_id: string; comment: string | null }>
        if (cancelled) return
        setSharedTaskComments((prev) => {
          const next = { ...prev }
          for (const row of rows) next[row.task_id] = row.comment
          return next
        })
      } catch (error) {
        console.error("Failed to load shared comments", error)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [apiFetch, allTasksCommentIds])

  const dailyUserReportRows = React.useMemo(() => {
    const rows: Array<{
      typeLabel: string
      subtype: string
      frequency: string
      period: string
      department: string
      title: string
      projectTitle?: string | null
      description: string
      status: string
      bz: string
      kohaBz: string
      tyo: string
      comment?: string | null
      userInitials?: string
      taskId?: string
      systemTemplateId?: string
      systemOccurrenceDate?: string
      systemStatus?: string
    }> = []

    if (!dailyReport) return rows

    const tasksToday = dailyReport.tasks_today || []
    const tasksOverdue = dailyReport.tasks_overdue || []
    const seenTaskIds = new Set<string>()

    const resolveDepartmentLabel = (
      departmentId?: string | null,
      scope?: SystemTaskScope | null,
      isGaNote?: boolean
    ) => {
      if (scope === "GA") return "GA"
      if (scope === "ALL") return "ALL"
      if (departmentId) {
        const dept = departments.find((d) => d.id === departmentId)
        return dept?.code || dept?.name || "-"
      }
      if (isGaNote) return "GA"
      return "-"
    }

    const pushTaskRow = (item: DailyReportResponse["tasks_today"][number]) => {
      const task = item.task
      if (ganeUserId) {
        const isAssigned =
          task.assigned_to === ganeUserId ||
          task.assignees?.some((assignee) => assignee.id === ganeUserId)
        if (!isAssigned) return
      }
      if (seenTaskIds.has(task.id)) return
      seenTaskIds.add(task.id)
      const baseDate = toDate(task.due_date || task.start_date || task.created_at)
      const isProject = Boolean(task.project_id)
      rows.push({
        typeLabel: isProject ? "PRJK" : "FT",
        subtype: isProject ? "-" : fastReportSubtypeShort(task),
        frequency: "",
        period: resolvePeriod(task.finish_period, task.due_date || task.start_date || task.created_at),
        department: resolveDepartmentLabel(task.department_id, null, Boolean(task.ga_note_origin_id)),
        title: task.title || "-",
        projectTitle: isProject ? (item.project_title ?? null) : null,
        description: task.description || "-",
        status: taskStatusLabel(task),
        bz: "-",
        kohaBz: "-",
        tyo: getTyoLabel(baseDate, task.completed_at, todayDate),
        comment: taskCommentMap.get(task.id) ?? null,
        userInitials: taskAssigneeInitials(task),
        taskId: task.id,
      })
    }

    tasksToday.forEach(pushTaskRow)
    tasksOverdue.forEach(pushTaskRow)

    // Include fast tasks (no project) across their start->due date window
    for (const task of tasks) {
      if (!ganeUserId) continue
      const isAssigned =
        task.assigned_to === ganeUserId ||
        task.assignees?.some((assignee) => assignee.id === ganeUserId)
      if (!isAssigned) continue
      if (task.is_active === false) continue
      if (task.system_template_origin_id) continue

      const isProject = Boolean(task.project_id)
      if (isProject) continue // show only fast tasks here

      if (!task.due_date) continue
      const due = toDate(task.due_date)
      const start = toDate(task.start_date || task.due_date)
      if (!due || !start) continue

      // Show on any day within start -> due (inclusive)
      if (todayDate < start || todayDate > due) continue

      if (seenTaskIds.has(task.id)) continue
      seenTaskIds.add(task.id)

      const baseDate = toDate(task.due_date || task.start_date || task.created_at)
      rows.push({
        typeLabel: "FT",
        subtype: fastReportSubtypeShort(task),
        frequency: "",
        period: resolvePeriod(task.finish_period, task.due_date || task.start_date || task.created_at),
        department: resolveDepartmentLabel(task.department_id, null, Boolean(task.ga_note_origin_id)),
        title: task.title || "-",
        description: task.description || "-",
        status: taskStatusLabel(task),
        bz: "-",
        kohaBz: "-",
        // Show as "T" for every day within start->due window
        tyo: "T",
        comment: taskCommentMap.get(task.id) ?? null,
        userInitials: taskAssigneeInitials(task),
        taskId: task.id,
      })
    }

    const systemToday = dailyReport.system_today || []
    const systemOverdue = dailyReport.system_overdue || []
    const seenSystemKeys = new Set<string>()
    const pushSystemRow = (occ: DailyReportResponse["system_today"][number]) => {
      const key = `${occ.template_id}:${occ.occurrence_date}`
      if (seenSystemKeys.has(key)) return
      seenSystemKeys.add(key)

      // Only include GA-scoped occurrences (scope GA or department GA)
      const isGaScope =
        occ.scope === "GA" ||
        (adminDepartmentId && occ.department_id === adminDepartmentId)
      if (!isGaScope) return

      const baseDate = toDate(occ.occurrence_date)
      const systemSubtype =
        occ.frequency === "DAILY"
          ? "D"
          : occ.frequency === "WEEKLY"
            ? "W"
            : occ.frequency === "MONTHLY"
              ? "M"
              : occ.frequency === "YEARLY"
                ? "Y"
                : occ.frequency === "3_MONTHS"
                  ? "3M"
                  : occ.frequency === "6_MONTHS"
                    ? "6M"
                    : "SYS"
      rows.push({
        typeLabel: "SYS",
        subtype: systemSubtype,
        frequency: systemSubtype,
        period: "AM",
        department: resolveDepartmentLabel(occ.department_id, occ.scope || null, false),
        title: occ.title || "-",
        description: "-",
        status: formatSystemOccurrenceStatus(occ.status),
        bz: "-",
        kohaBz: "-",
        tyo: getTyoLabel(baseDate, occ.acted_at, todayDate),
        comment: occ.comment ?? null,
        userInitials: ganeUser ? initials(ganeUser.full_name || ganeUser.username || "") : "",
        systemTemplateId: occ.template_id,
        systemOccurrenceDate: occ.occurrence_date,
        systemStatus: occ.status,
      })
    }
    systemToday.forEach(pushSystemRow)
    systemOverdue.forEach(pushSystemRow)

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
    const isDoneRow = (row: (typeof rows)[number]) => row.status.trim().toUpperCase() === "DONE"
    const typeRank = (row: (typeof rows)[number]) => (row.typeLabel === "SYS" ? 0 : 1)
    const periodRank = (row: (typeof rows)[number]) => (row.period === "PM" ? 1 : 0)
    const orderedRows = rows
      .map((row, index) => ({ row, index }))
      .sort((a, b) => {
        const doneDiff = Number(isDoneRow(a.row)) - Number(isDoneRow(b.row))
        if (doneDiff !== 0) return doneDiff
        const periodDiff = periodRank(a.row) - periodRank(b.row)
        if (periodDiff !== 0) return periodDiff
        const typeDiff = typeRank(a.row) - typeRank(b.row)
        if (typeDiff !== 0) return typeDiff
        const aIsProject = a.row.typeLabel === "PRJK"
        const bIsProject = b.row.typeLabel === "PRJK"
        if (aIsProject && bIsProject) {
          return sortByTyo(a.row, b.row)
        }
        return a.index - b.index
      })
      .map((entry) => entry.row)

    return orderedRows
  }, [dailyReport, departments, ganeUser, ganeUserId, taskAssigneeInitials, taskCommentMap, tasks, todayDate])

  const startEditTask = (task: Task) => {
    const isFastTask = !task.project_id && !task.system_template_origin_id && task.task_type !== "system"
    setEditingTaskId(task.id)
    setEditingTaskIsFast(isFastTask)
    setEditTitle(task.title || "")
    const taskStartDate = toDateInputValue(task.start_date)
    setEditStartDate(taskStartDate)
    const taskDueDate = toDateInputValue(task.due_date)
    setEditDueDate(taskDueDate)
    setEditOpen(true)
  }

  const saveEditTask = async () => {
    if (!editingTaskId) return
    setSavingEdit(true)
    try {
      const normalizedStartDate = editStartDate || ""
      const normalizedDueDate = editDueDate || ""
      if (normalizedStartDate && normalizedDueDate && normalizedStartDate > normalizedDueDate) {
        toast.error("Start date cannot be after due date")
        return
      }
      const startDateValue = normalizedStartDate ? new Date(normalizedStartDate).toISOString() : null
      const dueDateValue = normalizedDueDate ? new Date(normalizedDueDate).toISOString() : null
      // This dialog edits dates only. Do not resend title or other shared fields:
      // note-derived fast tasks must keep those fields synchronized with their source note.
      const payload: Record<string, unknown> = { start_date: startDateValue, due_date: dueDateValue }
      const res = await apiFetch(`/tasks/${editingTaskId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        let detail = "Failed to update task"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }
      const updated = (await res.json()) as Task
      if (editingTaskIsFast) {
        await load()
      } else {
        setTasks((prev) => prev.map((task) => (task.id === updated.id ? updated : task)))
      }
      setEditOpen(false)
      setEditingTaskId(null)
      setEditingTaskIsFast(false)
      toast.success("Task updated")
    } finally {
      setSavingEdit(false)
    }
  }

  const deleteTask = async (taskId: string) => {
    const confirmed = await confirm({
      title: "Delete task",
      description: "Are you sure you want to delete this task?",
      confirmLabel: "Delete",
      variant: "destructive",
    })
    if (!confirmed) return
    setDeletingTaskId(taskId)
    try {
      const res = await apiFetch(`/tasks/${taskId}`, { method: "DELETE" })
      if (!res?.ok) {
        if (res?.status === 405) {
          toast.error("Delete endpoint not active. Restart backend.")
        } else {
          toast.error("Failed to delete task")
        }
        return
      }
      setTasks((prev) => prev.filter((t) => t.id !== taskId))
      toast.success("Task deleted")
    } finally {
      setDeletingTaskId(null)
    }
  }

  const updateTaskStatus = async (
    taskId: string,
    status: string,
    completionOverrideReason?: string,
    personalCommentVerified = false
  ): Promise<boolean> => {
    const task = tasks.find((t) => t.id === taskId)
    if (!task) return false
    if (isWaitingConfirmation(status) && !task.confirmation_assignee_id) {
      setPendingStatusTaskId(taskId)
      setPendingStatusValue(status)
      setPendingConfirmationAssigneeId("")
      return false
    }
    const actorIsAssignee = Boolean(
      user?.id &&
      (task.assigned_to === user.id || task.assignees?.some((assignee) => assignee.id === user.id))
    )
    const needsPrivilegedOverride = Boolean(
      status === "DONE" &&
      taskRequiresRlzCompletionComment(task) &&
      (user?.role === "ADMIN" || user?.role === "MANAGER") &&
      !actorIsAssignee
    )
    const needsPersonalComment = Boolean(
      status === "DONE" &&
      taskRequiresRlzCompletionComment(task) &&
      actorIsAssignee &&
      !personalCommentVerified &&
      !task.user_comment?.trim()
    )
    if (needsPersonalComment) {
      setPendingCompletionCommentTaskId(taskId)
      setPendingCompletionComment(task.user_comment || "")
      return false
    }
    if (needsPrivilegedOverride && !completionOverrideReason?.trim()) {
      setPendingCompletionOverrideTaskId(taskId)
      setPendingCompletionOverrideReason("")
      return false
    }
    const key = `task:${taskId}`
    setTaskStatusUpdating((prev) => ({ ...prev, [key]: true }))
    try {
      const payload: Record<string, unknown> = { status }
      if (isWaitingConfirmation(status) && task.confirmation_assignee_id) {
        payload.confirmation_assignee_id = task.confirmation_assignee_id
      }
      if (completionOverrideReason?.trim()) {
        payload.completion_override_reason = completionOverrideReason.trim()
      }
      const res = await apiFetch(`/tasks/${taskId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => null)
        const code = apiErrorCode(data)
        if (code === "RLZ_COMPLETION_OVERRIDE_REASON_REQUIRED" && (user?.role === "ADMIN" || user?.role === "MANAGER")) {
          setPendingCompletionOverrideTaskId(taskId)
          setPendingCompletionOverrideReason("")
          return false
        }
        if (code === "RLZ_TASK_COMMENT_REQUIRED") {
          setPendingCompletionCommentTaskId(taskId)
          setPendingCompletionComment(task.user_comment || "")
          return false
        }
        toast.error(apiErrorMessage(data, "Failed to update task status"))
        return false
      }
      const updated = (await res.json()) as Task
      setTasks((prev) => prev.map((task) => (task.id === updated.id ? updated : task)))
      return true
    } catch (error) {
      console.error("Failed to update task status", error)
      toast.error("Failed to update task status")
      return false
    } finally {
      setTaskStatusUpdating((prev) => ({ ...prev, [key]: false }))
    }
  }

  const updateSystemOccurrenceStatus = async (
    templateId: string,
    occurrenceDate: string,
    status: string,
    comment?: string | null
  ) => {
    const key = `system:${templateId}:${occurrenceDate}`
    setTaskStatusUpdating((prev) => ({ ...prev, [key]: true }))
    try {
      const payload: { template_id: string; occurrence_date: string; status: string; comment?: string | null } = {
        template_id: templateId,
        occurrence_date: occurrenceDate,
        status,
      }
      if (typeof comment !== "undefined") {
        payload.comment = comment
      }
      const res = await apiFetch("/system-tasks/occurrences", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        toast.error("Failed to update system task status")
        return
      }
      const overrideKey = `${templateId}:${occurrenceDate}`
      setSystemStatusOverrides((prev) => ({ ...prev, [overrideKey]: status }))
      setSystemTasks((prev) =>
        prev.map((task) =>
          task.template_id === templateId ? { ...task, status } : task
        )
      )
    } catch (error) {
      console.error("Failed to update system task status", error)
      toast.error("Failed to update system task status")
    } finally {
      setTaskStatusUpdating((prev) => ({ ...prev, [key]: false }))
    }
  }

  const startFastTaskEdit = (taskId: string) => {
    const task = tasks.find((item) => item.id === taskId)
    if (!task) return
    setFastEditTaskId(task.id)
    setFastEditTitle(task.title || "")
    setFastEditStartDate(toDateInputValue(task.start_date))
    setFastEditDueDate(toDateInputValue(task.due_date))
    setFastEditPriority((task.is_bllok ? "BLLOK" : (task.priority || "NORMAL")) as TaskPriority)
    setFastEditStatus(task.status || "TODO")
    setFastEditConfirmationAssigneeId(task.confirmation_assignee_id || "")
    setFastEditOriginalIsBllok(Boolean(task.is_bllok))
    setFastEditOpen(true)
  }

  const saveFastTaskEdit = async () => {
    if (!fastEditTaskId || !fastEditTitle.trim()) return
    const confirmationValidation = validateWaitingConfirmation(fastEditStatus, fastEditConfirmationAssigneeId)
    if (confirmationValidation) {
      toast.error(confirmationValidation)
      return
    }
    setFastEditSaving(true)
    try {
      const startDateValue = fastEditStartDate ? new Date(fastEditStartDate).toISOString() : null
      const dueDateValue = fastEditDueDate ? new Date(fastEditDueDate).toISOString() : null
      const isBllok = fastEditPriority === "BLLOK"
      const actualPriority: "NORMAL" | "HIGH" = isBllok ? "NORMAL" : (fastEditPriority === "HIGH" ? "HIGH" : "NORMAL")
      const payload: Record<string, unknown> = {
        title: fastEditTitle.trim(),
        start_date: startDateValue,
        due_date: dueDateValue,
        priority: actualPriority,
        status: fastEditStatus,
      }
      if (isWaitingConfirmation(fastEditStatus)) {
        payload.confirmation_assignee_id = fastEditConfirmationAssigneeId
      }
      if (isBllok !== fastEditOriginalIsBllok) {
        payload.is_bllok = isBllok
      }
      const res = await apiFetch(`/tasks/${fastEditTaskId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        let detail = "Failed to update task"
        try {
          const data = (await res.json()) as { detail?: unknown }
          if (typeof data?.detail === "string" && data.detail.trim()) {
            detail = data.detail
          } else if (Array.isArray(data?.detail)) {
            detail = data.detail.map((e: any) => e.msg || String(e)).join(", ")
          }
        } catch {
          // ignore parse errors
        }
        toast.error(detail)
        return
      }
      const updated = (await res.json()) as Task
      setTasks((prev) => prev.map((task) => (task.id === updated.id ? updated : task)))
      setFastEditOpen(false)
      setFastEditTaskId(null)
      setFastEditConfirmationAssigneeId("")
    } catch (error) {
      console.error("Failed to update task", error)
      const message = error instanceof Error && error.message ? error.message : "Failed to update task"
      toast.error(message)
    } finally {
      setFastEditSaving(false)
    }
  }

  const updateTaskCommentState = (taskId: string, comment: string | null) => {
    setTasks((prev) => prev.map((task) => (task.id === taskId ? { ...task, user_comment: comment } : task)))
  }

  const setDailyReportCommentSaving = (commentKey: string, isSaving: boolean) => {
    setSavingDailyReportComments((prev) => ({ ...prev, [commentKey]: isSaving }))
  }

  const setAllTasksReportCommentSaving = (commentKey: string, isSaving: boolean) => {
    setSavingAllTasksReportComments((prev) => ({ ...prev, [commentKey]: isSaving }))
  }

  const saveAllTasksReportTaskComment = async (
    taskId: string,
    nextValue: string,
    previousValue: string,
    commentKey: string
  ) => {
    const trimmed = nextValue.trim()
    const previousTrimmed = previousValue.trim()
    if (trimmed === previousTrimmed) return true

    const payloadComment = trimmed.length ? trimmed : null
    setAllTasksReportCommentSaving(commentKey, true)
    try {
      const res = await apiFetch(`/tasks/${taskId}/comment`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ comment: payloadComment }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => null)
        toast.error(apiErrorMessage(data, "Failed to save comment"))
        setAllTasksReportCommentEdits((prev) => ({ ...prev, [commentKey]: previousValue }))
        return false
      }
      updateTaskCommentState(taskId, payloadComment)
      setSharedTaskComments((prev) => ({ ...prev, [taskId]: payloadComment }))
      setAllTasksReportCommentEdits((prev) => ({ ...prev, [commentKey]: trimmed }))
      return true
    } catch (error) {
      console.error("Failed to save comment", error)
      toast.error("Failed to save comment")
      setAllTasksReportCommentEdits((prev) => ({ ...prev, [commentKey]: previousValue }))
      return false
    } finally {
      setAllTasksReportCommentSaving(commentKey, false)
    }
  }

  const completeTaskFromAllTasksReport = async (
    task: Task,
    nextComment: string,
    previousComment: string,
    commentKey: string,
    isConfirmationAction: boolean
  ) => {
    const actorIsAssignee = Boolean(
      user?.id &&
      (task.assigned_to === user.id || task.assignees?.some((assignee) => assignee.id === user.id))
    )
    const requiresPersonalComment = Boolean(
      !isConfirmationAction && actorIsAssignee && taskRequiresRlzCompletionComment(task)
    )

    if (requiresPersonalComment && !nextComment.trim()) {
      setPendingCompletionCommentTaskId(task.id)
      setPendingCompletionComment(nextComment)
      return
    }
    if (requiresPersonalComment && nextComment.trim() !== previousComment.trim()) {
      const saved = await saveAllTasksReportTaskComment(
        task.id,
        nextComment,
        previousComment,
        commentKey
      )
      if (!saved) return
    }
    await updateTaskStatus(task.id, "DONE", undefined, requiresPersonalComment)
  }

  const submitCompletionComment = async () => {
    if (!pendingCompletionCommentTaskId) return
    const comment = pendingCompletionComment.trim()
    if (!comment) {
      toast.error("Para mbylljes, shto komentin për rezultatin e kësaj detyre.")
      return
    }
    const task = tasks.find((item) => item.id === pendingCompletionCommentTaskId)
    if (!task) return

    setPendingCompletionCommentSaving(true)
    try {
      const commentKey = `completion:${task.id}`
      const saved = await saveAllTasksReportTaskComment(
        task.id,
        comment,
        task.user_comment || "",
        commentKey
      )
      if (!saved) return
      const updated = await updateTaskStatus(task.id, "DONE", undefined, true)
      if (!updated) return
      setPendingCompletionCommentTaskId(null)
      setPendingCompletionComment("")
    } finally {
      setPendingCompletionCommentSaving(false)
    }
  }

  const submitCompletionOverride = async () => {
    if (!pendingCompletionOverrideTaskId) return
    const reason = pendingCompletionOverrideReason.trim()
    if (!reason) {
      toast.error("Shkruaj arsyen pse po e mbyll këtë detyrë në emër të assignee-t.")
      return
    }
    const updated = await updateTaskStatus(pendingCompletionOverrideTaskId, "DONE", reason)
    if (!updated) return
    setPendingCompletionOverrideTaskId(null)
    setPendingCompletionOverrideReason("")
  }

  const saveAllTasksReportSystemComment = async (
    templateId: string,
    occurrenceDate: string,
    status: string,
    nextValue: string,
    previousValue: string,
    commentKey: string
  ) => {
    const trimmed = nextValue.trim()
    const previousTrimmed = previousValue.trim()
    if (trimmed === previousTrimmed) return

    const payloadComment = trimmed.length ? trimmed : null
    setAllTasksReportCommentSaving(commentKey, true)
    try {
      const res = await apiFetch("/system-tasks/occurrences", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          template_id: templateId,
          occurrence_date: occurrenceDate || todayIso,
          status: status || "OPEN",
          comment: payloadComment,
        }),
      })
      if (!res.ok) {
        const data = await res.json()
        toast.error(data.detail || "Failed to save comment")
        setAllTasksReportCommentEdits((prev) => ({ ...prev, [commentKey]: previousValue }))
        return
      }
      setAllTasksReportCommentEdits((prev) => ({ ...prev, [commentKey]: trimmed }))
      // Update system tasks state
      setSystemTasks((prev) =>
        prev.map((st) =>
          st.template_id === templateId
            ? { ...st, user_comment: payloadComment }
            : st
        )
      )
    } catch (error) {
      console.error("Failed to save comment", error)
      toast.error("Failed to save comment")
      setAllTasksReportCommentEdits((prev) => ({ ...prev, [commentKey]: previousValue }))
    } finally {
      setAllTasksReportCommentSaving(commentKey, false)
    }
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

  const saveDailyReportSystemComment = async (
    templateId: string,
    occurrenceDate: string,
    status: string,
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
      const res = await apiFetch("/system-tasks/occurrences", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          template_id: templateId,
          occurrence_date: occurrenceDate,
          status: status || "OPEN",
          comment: payloadComment,
        }),
      })
      if (!res.ok) {
        const data = await res.json()
        toast.error(data.detail || "Failed to save comment")
        setDailyReportCommentEdits((prev) => ({ ...prev, [commentKey]: previousValue }))
        return
      }

      setDailyReport((prev) => {
        if (!prev) return prev
        const updateOccurrence = (occ: DailyReportResponse["system_today"][number]) =>
          occ.template_id === templateId && occ.occurrence_date === occurrenceDate
            ? { ...occ, comment: payloadComment }
            : occ
        return {
          ...prev,
          system_today: prev.system_today.map(updateOccurrence),
          system_overdue: prev.system_overdue.map(updateOccurrence),
        }
      })
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
    if (!user?.id) return
    if (!ganeUserId) {
      toast.error("Gane Arifaj user not found. Cannot export.")
      return
    }
    setExportingDailyReport(true)
    try {
      const qs = new URLSearchParams({
        day: todayIso,
        user_id: ganeUserId,
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
      link.download = `daily_report_${todayIso}_${printInitials || "user"}.xlsx`
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

  // Convert all tasks to daily report row format
  const allTasksReportRows = React.useMemo(() => {
    const rows: Array<{
      typeLabel: string
      subtype: string
      frequency: string
      period: string
      department: string
      title: string
      description: string
      details: string
      dateIso: string
      ditaLabel: string
      bzMe: string
      status: string
      bz: string
      kohaBz: string
      tyo: string
      comment?: string | null
      userInitials?: string
      taskId?: string
      startDateIso?: string
      isFastTask?: boolean
      isLateSystemTask?: boolean
      createdDate?: string
      systemTemplateId?: string
      systemOccurrenceDate?: string
      systemStatus?: string
    }> = []

    if (!ganeUserId) return rows

    const resolveDepartmentLabel = (
      departmentId?: string | null,
      scope?: string | null,
      isGaNote?: boolean
    ) => {
      if (scope === "GA") return "GA"
      if (scope === "ALL") return "ALL"
      if (departmentId) {
        const dept = departments.find((d) => d.id === departmentId)
        return dept?.code || dept?.name || "-"
      }
      if (isGaNote) return "GA"
      return "-"
    }

    // Process all tasks assigned to Gane
    for (const task of tasks) {
      const isAssigned =
        task.assigned_to === ganeUserId ||
        task.assignees?.some((assignee) => assignee.id === ganeUserId) ||
        task.alignment_user_ids?.includes(ganeUserId)
      if (!isAssigned) continue
      if (task.is_active === false) continue
      if (task.system_template_origin_id) continue // Skip system tasks (handled separately)

      const isProject = Boolean(task.project_id)
      const baseDate = toDate(task.due_date || task.start_date || task.created_at)
      const createdDate = task.created_at ? new Date(task.created_at).toISOString().slice(0, 10) : undefined
      const startDateIso = toDateOnlyIso(task.start_date || task.due_date || null)
      const dateIso = getTaskDateIso(task)
      const assigneeDepartments = taskAssigneeDepartments(task)
      rows.push({
        typeLabel: isProject ? "PRJK" : "FT",
        subtype: isProject ? "-" : fastReportSubtypeShort(task),
        frequency: "",
        period: resolvePeriod(task.finish_period, task.due_date || task.start_date || task.created_at),
        department: assigneeDepartments || resolveDepartmentLabel(task.department_id, null, Boolean(task.ga_note_origin_id)),
        title: task.title || "-",
        description: task.description || "",
        details: formatInternalDetails(task.internal_notes),
        dateIso,
        ditaLabel: dateIso ? formatDateDMY(dateIso) : "-",
        bzMe: (task.alignment_user_ids || [])
          .map((id) => {
            const userFromMap = userMap.get(id)
            return userFromMap ? initials(userFromMap.full_name || userFromMap.username || "") : ""
          })
          .filter(Boolean)
          .join(", "),
        status: taskStatusLabel(task),
        bz: "-",
        kohaBz: "-",
        tyo: baseDate ? getTyoLabel(baseDate, task.completed_at, todayDate) : "-",
        comment: taskCommentMap.get(task.id) ?? null,
        userInitials: taskAssigneeInitials(task),
        taskId: task.id,
        startDateIso,
        isFastTask: !isProject,
        createdDate,
      })
    }

    // Process all system tasks assigned to Gane or scoped to GA
    for (const systemTask of systemTasks) {
      const isAssignedToGane =
        systemTask.default_assignee_id === ganeUserId ||
        systemTask.assignees?.some((assignee) => assignee.id === ganeUserId)
      if (systemTask.is_active === false) continue

      const isGaScope =
        systemTask.scope === "GA" ||
        (adminDepartmentId && systemTask.department_id === adminDepartmentId)
      if (!isAssignedToGane && !isGaScope) continue

      const systemSubtype =
        systemTask.frequency === "DAILY"
          ? "D"
          : systemTask.frequency === "WEEKLY"
            ? "W"
            : systemTask.frequency === "MONTHLY"
              ? "M"
              : systemTask.frequency === "YEARLY"
                ? "Y"
                : systemTask.frequency === "3_MONTHS"
                  ? "3M"
                  : systemTask.frequency === "6_MONTHS"
                    ? "6M"
                    : "SYS"
      
      const createdDate = systemTask.created_at ? new Date(systemTask.created_at).toISOString().slice(0, 10) : undefined
      const baseDate = createdDate ? toDate(createdDate) : null

      const dateIso = getSystemDateIso(systemTask)
      const assigneeDepartments = systemAssigneeDepartments(systemTask)
      rows.push({
        typeLabel: "SYS",
        subtype: systemSubtype,
        frequency: systemSubtype,
        period: systemTask.finish_period || "AM",
        department:
          assigneeDepartments || resolveDepartmentLabel(systemTask.department_id, systemTask.scope || null, false),
        title: systemTask.title || "-",
        description: systemTask.description || "",
        details: formatInternalDetails(systemTask.internal_notes),
        dateIso,
        ditaLabel: dateIso ? formatDateDMY(dateIso) : "-",
        bzMe: (systemTask.alignment_user_ids || [])
          .map((id) => {
            const userFromMap = userMap.get(id)
            return userFromMap ? initials(userFromMap.full_name || userFromMap.username || "") : ""
          })
          .filter(Boolean)
          .join(", "),
        status: formatSystemOccurrenceStatus(systemTask.status),
        bz: "-",
        kohaBz: "-",
        tyo: baseDate ? getTyoLabel(baseDate, null, todayDate) : "-",
        comment: systemTask.user_comment ?? null,
        userInitials: systemAssigneeInitials(systemTask),
        systemTemplateId: systemTask.template_id,
        isFastTask: false,
        createdDate,
      })
    }

    // Sort by created date (newest first)
    rows.sort((a, b) => {
      if (!a.createdDate && !b.createdDate) return 0
      if (!a.createdDate) return 1
      if (!b.createdDate) return -1
      return b.createdDate.localeCompare(a.createdDate)
    })

    return rows
  }, [
    tasks,
    systemTasks,
    ganeUserId,
    departments,
    taskAssigneeInitials,
    systemAssigneeInitials,
    taskAssigneeDepartments,
    systemAssigneeDepartments,
    taskCommentMap,
    todayDate,
    adminDepartmentId,
    userMap,
  ])

  const filteredAllTasksReportRows = React.useMemo(() => {
    if (!allTasksDateFrom && !allTasksDateTo) return allTasksReportRows
    return allTasksReportRows.filter((row) => {
      if (row.isLateSystemTask && isIsoWithinInclusiveRange(todayIso, allTasksDateFrom, allTasksDateTo)) {
        return true
      }
      // Open overdue FT/PRJK rows (status label is "Done" when completed).
      if (
        row.status !== "Done" &&
        row.dateIso &&
        row.dateIso < todayIso &&
        isIsoWithinInclusiveRange(todayIso, allTasksDateFrom, allTasksDateTo)
      ) {
        return true
      }
      return isIsoWithinInclusiveRange(row.dateIso, allTasksDateFrom, allTasksDateTo)
    })
  }, [allTasksDateFrom, allTasksDateTo, allTasksReportRows, todayIso])

  const exportAllTasks = async () => {
    if (!user?.id) return
    if (!ganeUserId) {
      toast.error("Gane Arifaj user not found. Cannot export.")
      return
    }
    setExportingAllTasks(true)
    try {
      const rowsPayload = filteredAllTasksReportRows.map((row) => {
        return {
          typeLabel: row.typeLabel,
          subtype: row.subtype,
          frequency: row.frequency || "",
          dateLabel: row.ditaLabel,
          bzMe: row.bzMe,
          kohaBz: row.kohaBz,
          department: row.department,
          period: row.period,
          title: row.title,
          description: row.description,
          details: row.details,
          status: row.status,
          userInitials: row.userInitials || "",
        }
      })

      const res = await apiFetch(`/exports/all-tasks-report.xlsx`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: "ALL ADMIN TASK REPORT",
          usersInitials: (() => {
            const unique = Array.from(
              new Set(
                rowsPayload
                  .map((r) => (r.userInitials || "").trim().toUpperCase())
                  .filter(Boolean)
              )
            ).sort()
            return unique.join("_")
          })(),
          rows: rowsPayload,
        }),
      })
      if (!res.ok) {
        toast.error("Failed to export all tasks")
        return
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      const filename = parseFilenameFromDisposition(res.headers.get("content-disposition"))
      link.download = filename || "ALL_ADMIN_TASK_REPORT.xlsx"
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (error) {
      console.error("Failed to export all tasks", error)
      toast.error("Failed to export all tasks")
    } finally {
      setExportingAllTasks(false)
    }
  }

  const submitPendingStatusUpdate = async () => {
    if (!pendingStatusTaskId) return
    const validation = validateWaitingConfirmation(pendingStatusValue, pendingConfirmationAssigneeId)
    if (validation) {
      toast.error(validation)
      return
    }
    const key = `task:${pendingStatusTaskId}`
    setTaskStatusUpdating((prev) => ({ ...prev, [key]: true }))
    try {
      const res = await apiFetch(`/tasks/${pendingStatusTaskId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          status: pendingStatusValue,
          confirmation_assignee_id: pendingConfirmationAssigneeId,
        }),
      })
      if (!res.ok) {
        let detail = "Failed to update task status"
        try {
          const data = (await res.json()) as { detail?: string }
          if (typeof data?.detail === "string" && data.detail.trim()) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }
      const updated = (await res.json()) as Task
      setTasks((prev) => prev.map((task) => (task.id === updated.id ? updated : task)))
      setPendingStatusTaskId(null)
      setPendingStatusValue("TODO")
      setPendingConfirmationAssigneeId("")
    } catch (error) {
      console.error("Failed to update task status", error)
      toast.error("Failed to update task status")
    } finally {
      setTaskStatusUpdating((prev) => ({ ...prev, [key]: false }))
    }
  }

  const resetFastTaskForm = React.useCallback(() => {
    setFastTaskTitle("")
    setFastTaskDescription("")
    setFastTaskType("normal")
    setFastTaskAssignees([])
    setFastTaskStartDate("")
    setFastTaskDueDate("")
    setFastTaskDeadlineImportant(false)
    setFastTaskFinishPeriod(FINISH_PERIOD_NONE_VALUE)
  }, [])

  const submitFastTask = async () => {
    if (!fastTaskTitle.trim()) {
      toast.error("Task title is required")
      return
    }
    if (!fastTaskStartDate) {
      toast.error("Start date is required")
      return
    }
    if (!adminDepartmentId) {
      toast.error("Department is required")
      return
    }
    setCreatingFastTask(true)
    try {
      const startDate = fastTaskStartDate ? new Date(fastTaskStartDate).toISOString() : null
      const dueDate = fastTaskDueDate ? new Date(fastTaskDueDate).toISOString() : null
      const payload = {
        title: fastTaskTitle.trim(),
        description: fastTaskDescription.trim() || null,
        project_id: null,
        department_id: adminDepartmentId,
        status: "TODO",
        priority: "NORMAL",
        finish_period: fastTaskFinishPeriod === FINISH_PERIOD_NONE_VALUE ? null : fastTaskFinishPeriod,
        is_deadline_important: fastTaskDeadlineImportant,
        is_bllok: fastTaskType === "blocked",
        is_1h_report: fastTaskType === "hourly",
        is_r1: fastTaskType === "r1",
        is_personal: fastTaskType === "personal",
        ga_note_origin_id: null,
        start_date: startDate,
        due_date: dueDate,
      }
      const assigneeIds = fastTaskAssignees.length > 0 ? fastTaskAssignees : null
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
      created.is_bllok = fastTaskType === "blocked" ? true : (created.is_bllok ?? false)
      created.is_1h_report = fastTaskType === "hourly" ? true : (created.is_1h_report ?? false)
      created.is_r1 = fastTaskType === "r1" ? true : (created.is_r1 ?? false)
      created.is_personal = fastTaskType === "personal" ? true : (created.is_personal ?? false)
      if (fastTaskType === "normal") {
        created.ga_note_origin_id = created.ga_note_origin_id || null
        created.priority = created.priority || "NORMAL"
      }
      setTasks((prev) => [created, ...prev])
      setFastTaskOpen(false)
      resetFastTaskForm()
      toast.success("Task created")
    } finally {
      setCreatingFastTask(false)
    }
  }

  const exportCommonView = async (payload: { title: string; columns: string[]; rows: string[][] }) => {
    if (exportingCommonView) return
    setExportingCommonView(true)
    try {
      const res = await apiFetch(`/exports/common-view.xlsx`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res?.ok) {
        const detail = await res.text()
        toast.error(detail || "Failed to export common view.")
        return
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      const filename = parseFilenameFromDisposition(res.headers.get("content-disposition"))
      link.download = filename || "COMMON_VIEW.xlsx"
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (error) {
      console.error("Failed to export common view", error)
      toast.error("Failed to export common view")
    } finally {
      setExportingCommonView(false)
    }
  }

  const exportGaTime = async () => {
    if (exportingGaTime) return
    setExportingGaTime(true)
    try {
      const weekStartIso = toISODate(commonWeekStart)
      const res = await apiFetch(`/exports/ga-time.xlsx?week_start=${encodeURIComponent(weekStartIso)}`)
      if (!res?.ok) {
        const detail = await res.text()
        toast.error(detail || "Failed to export GA time.")
        return
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      const filename = parseFilenameFromDisposition(res.headers.get("content-disposition"))
      link.download = filename || "GA_TIME_TABLE.xlsx"
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (error) {
      console.error("Failed to export GA time", error)
      toast.error("Failed to export GA time")
    } finally {
      setExportingGaTime(false)
    }
  }

  // Direct link for phones: /admin-tasks#ga-time-table opens the page at the GA
  // time table. The sections above it load late and push it down, so the
  // scroll is repeated while the page settles.
  React.useEffect(() => {
    // Phones and tablets always get this view, link or not: the address loses
    // its "#ga-time-table" after a login redirect or when opened from the menu.
    const isTouchDevice = window.matchMedia("(pointer: coarse)").matches
    if (window.location.hash !== "#ga-time-table" && !isTouchDevice) return
    // Only the GA time table starts open; the others stay one tap away on "+".
    setCollapsedAdminSections({ "all-tasks": true, common: true, "one-h-print": true, "ga-time": false })
    setGaTimeTableFirst(true)
    const startedAt = Date.now()
    let timer = 0
    const stop = () => {
      window.clearInterval(timer)
      userEvents.forEach((name) => window.removeEventListener(name, stop))
    }
    // Hand control back the moment the user scrolls or taps.
    const userEvents = ["touchstart", "wheel", "keydown", "mousedown"] as const
    userEvents.forEach((name) => window.addEventListener(name, stop, { passive: true }))
    timer = window.setInterval(() => {
      if (Date.now() - startedAt > 15000) return stop()
      const table = document.getElementById("ga-time-table")
      if (table && Math.abs(table.getBoundingClientRect().top) > 24) {
        table.scrollIntoView({ block: "start" })
      }
    }, 250)
    return stop
  }, [])

  const toggleAdminSection = React.useCallback((sectionId: AdminTasksSectionId) => {
    setCollapsedAdminSections((current) => ({
      ...current,
      [sectionId]: !current[sectionId],
    }))
  }, [])

  const commonFiltered = React.useMemo(() => {
    const datesToUse = commonWeekISOs
    const activeUserIds = commonUsers.filter((u) => u.is_active).map((u) => u.id)
    const fullyCoveredDates = new Set<string>()
    if (activeUserIds.length) {
      for (const dateStr of datesToUse) {
        const coveredUsers = new Set(
          commonData.leave
            .filter((x) => x.userId && dateStr >= x.startDate && dateStr <= x.endDate)
            .map((x) => x.userId as string)
        )
        if (coveredUsers.size >= activeUserIds.length) {
          fullyCoveredDates.add(dateStr)
        }
      }
    }

    // Match 1H SHTYPI: explicit full-day leave or a PV/MUNG range covering
    // 08:00-16:00 hides the user's work for that date.
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
      const start = parseTimeToMinutes(lv.from)
      const end = parseTimeToMinutes(lv.to)
      if (!lv.userId || (!lv.fullDay && !(start !== null && end !== null && start <= 8 * 60 && end >= 16 * 60))) continue
      for (const d of datesToUse) {
        if (d >= lv.startDate && d <= lv.endDate) {
          addHidden(d, lv.userId)
        }
      }
    }
    for (const ab of commonData.absent) {
      if (!ab.userId) continue
      const start = parseTimeToMinutes(ab.from)
      const end = parseTimeToMinutes(ab.to)
      if (start !== null && end !== null && start <= 8 * 60 && end >= 16 * 60) {
        addHidden(ab.date, ab.userId)
      }
    }

    // Resolve user display names (full_name / username / email) to user IDs so
    // we can hide items that only carry a person name (problems, feedback, and
    // the assignee/owner lists on priority/meetings/bz).
    const nameToUserId = new Map<string, string>()
    for (const u of commonUsers) {
      if (!u.id) continue
      if (u.full_name) nameToUserId.set(u.full_name.trim().toLowerCase(), u.id)
      if (u.username) nameToUserId.set(u.username.trim().toLowerCase(), u.id)
      if (u.email) nameToUserId.set(u.email.trim().toLowerCase(), u.id)
    }
    const resolveUserId = (name: string | undefined | null): string | null => {
      if (!name) return null
      return nameToUserId.get(name.trim().toLowerCase()) || null
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

    const inSelectedDates = (dateStr: string) => datesToUse.includes(dateStr)
    const late = commonData.late.filter((x) => inSelectedDates(x.date) && !fullyCoveredDates.has(x.date))
    const absent = commonData.absent.filter((x) => inSelectedDates(x.date) && !fullyCoveredDates.has(x.date))
    const leave = commonData.leave.filter((x) => {
      const visibleDates = datesToUse.filter((d) => d >= x.startDate && d <= x.endDate)
      if (!visibleDates.length) return false
      return visibleDates.some((d) => !fullyCoveredDates.has(d))
    })
    const blocked = commonData.blocked
      .filter((x) => inSelectedDates(x.date) && !fullyCoveredDates.has(x.date))
      .filter((x) => !isUserHiddenOn(x.date, x.userId))
    const oneH = commonData.oneH
      .filter((x) => inSelectedDates(x.date) && !fullyCoveredDates.has(x.date))
      .filter((x) => !isUserHiddenOn(x.date, x.userId))
    const personal = commonData.personal
      .filter((x) => inSelectedDates(x.date) && !fullyCoveredDates.has(x.date))
      .filter((x) => !isUserHiddenOn(x.date, x.userId))
    const r1 = commonData.r1
      .filter((x) => inSelectedDates(x.date) && !fullyCoveredDates.has(x.date))
      .filter((x) => !isUserHiddenOn(x.date, x.userId))
    const external = commonData.external
      .filter((x) => inSelectedDates(x.date) && !fullyCoveredDates.has(x.date))
      .flatMap((x) => {
        const hiddenSet = hiddenUsersByDate.get(x.date)
        if (!hiddenSet || hiddenSet.size === 0) return [x]
        const ownerHidden = isNameHiddenOn(x.date, x.owner)
        const filteredAssignees = (x.assignees || []).filter((n) => !isNameHiddenOn(x.date, n))
        if (ownerHidden && filteredAssignees.length === 0) return []
        if (filteredAssignees.length === (x.assignees?.length || 0)) return [x]
        return [{ ...x, assignees: filteredAssignees }]
      })
    const internal = commonData.internal
      .filter((x) => inSelectedDates(x.date) && !fullyCoveredDates.has(x.date))
      .flatMap((x) => {
        const hiddenSet = hiddenUsersByDate.get(x.date)
        if (!hiddenSet || hiddenSet.size === 0) return [x]
        const ownerHidden = isNameHiddenOn(x.date, x.owner)
        const filteredAssignees = (x.assignees || []).filter((n) => !isNameHiddenOn(x.date, n))
        if (ownerHidden && filteredAssignees.length === 0) return []
        if (filteredAssignees.length === (x.assignees?.length || 0)) return [x]
        return [{ ...x, assignees: filteredAssignees }]
      })
    const problems = commonData.problems
      .filter((x) => x.everyday || (inSelectedDates(x.date) && !fullyCoveredDates.has(x.date)))
      .filter((x) => x.everyday || !isNameHiddenOn(x.date, x.person))
    const feedback = commonData.feedback
      .filter((x) => x.everyday || (inSelectedDates(x.date) && !fullyCoveredDates.has(x.date)))
      .filter((x) => x.everyday || !isNameHiddenOn(x.date, x.person))
    const bz = commonData.bz
      .filter((x) => inSelectedDates(x.date) && !fullyCoveredDates.has(x.date))
      .flatMap((x) => {
        const hiddenSet = hiddenUsersByDate.get(x.date)
        if (!hiddenSet || hiddenSet.size === 0) return [x]
        const filteredAssignees = (x.assignees || []).filter((n) => !isNameHiddenOn(x.date, n))
        if (filteredAssignees.length === 0) return []
        if (filteredAssignees.length === (x.assignees?.length || 0)) return [x]
        return [{ ...x, assignees: filteredAssignees }]
      })
    const priority = commonData.priority.filter((p) => inSelectedDates(p.date))

    const filteredPriority = priority
      .filter((p) => !fullyCoveredDates.has(p.date))
      .flatMap((p) => {
        const hiddenSet = hiddenUsersByDate.get(p.date)
        if (!hiddenSet || hiddenSet.size === 0) return [p]
        const filteredAssignees = (p.assignees || []).filter((n) => !isNameHiddenOn(p.date, n))
        if (filteredAssignees.length === 0) return []
        if (filteredAssignees.length === (p.assignees?.length || 0)) return [p]
        return [{ ...p, assignees: filteredAssignees }]
      })

    return {
      late,
      absent,
      leave,
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
  }, [commonData, commonUsers, commonWeekISOs])

  const allUsersLeaveByDate = React.useMemo(() => {
    const byDate = new Map<string, LeaveItem>()
    for (const iso of commonWeekISOs) {
      const matching = commonData.leave.find((x) => x.isAllUsers && iso >= x.startDate && iso <= x.endDate)
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
  }, [commonData.leave, commonWeekISOs])

  const bzSystemTasksByDay = React.useMemo(() => {
    const byDay: Record<string, BzItem[]> = {}
    for (const iso of commonWeekISOs) {
      byDay[iso] = []
    }
    if (!ganeUserId) return byDay

    const assigneeLabelsForTask = (task: Task) => {
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
          if (userFromMap) return userFromMap.full_name || userFromMap.username || ""
          const assigneeFromArray = task.assignees?.find((a) => a.id === userId)
          return assigneeFromArray?.full_name || assigneeFromArray?.username || ""
        })
        .filter(Boolean)
    }

    for (const task of tasks) {
      if (task.is_active === false) continue
      if (!task.system_template_origin_id) continue
      const template = systemTaskByTemplateId.get(task.system_template_origin_id)
      if (!template?.alignment_user_ids?.includes(ganeUserId)) continue

      const occurrenceDate = toDate(task.start_date || task.due_date || task.created_at)
      if (!occurrenceDate) continue
      const occurrenceIso = toISODate(occurrenceDate)
      if (!commonWeekISOs.includes(occurrenceIso)) continue

      const assigneeLabels = assigneeLabelsForTask(task)
      byDay[occurrenceIso].push({
        title: task.title || "-",
        date: occurrenceIso,
        time: template.alignment_time || "",
        assignees: assigneeLabels,
        bzWithLabel: "GA",
        taskId: task.id,
        templateId: task.system_template_origin_id,
        matchTitle: task.title || "-",
      })
    }

    for (const iso of commonWeekISOs) {
      byDay[iso] = sortByTime(byDay[iso], (item) => item.time, (item) => item.title)
    }

    return byDay
  }, [commonWeekISOs, ganeUserId, sortByTime, systemTaskByTemplateId, tasks, userMap])

  const tableDataByDay = React.useMemo(() => {
    const dataByDay: Record<
      string,
      {
        late: LateItem[]
        absent: AbsentItem[]
        leave: LeaveItem[]
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
    const dailyFeedback = commonFiltered.feedback.filter((x) => x.everyday)
    const dailyProblems = commonFiltered.problems.filter((x) => x.everyday)

    commonWeekISOs.forEach((iso) => {
      if (commonFiltered.fullyCoveredDates.has(iso)) {
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
        late: commonFiltered.late.filter((x) => x.date === iso),
        absent: commonFiltered.absent.filter((x) => x.date === iso),
        leave: commonFiltered.leave.filter((x) => iso >= x.startDate && iso <= x.endDate),
        blocked: commonFiltered.blocked.filter((x) => x.date === iso),
        oneH: sortTasksByOrder(commonFiltered.oneH.filter((x) => x.date === iso)),
        personal: commonFiltered.personal.filter((x) => x.date === iso),
        external: sortByTime(commonFiltered.external.filter((x) => x.date === iso), (x) => x.time, (x) => x.title),
        internal: sortByTime(commonFiltered.internal.filter((x) => x.date === iso), (x) => x.time, (x) => x.title),
        bz: bzSystemTasksByDay[iso] || [],
        r1: sortTasksByOrder(commonFiltered.r1.filter((x) => x.date === iso)),
        problems: [
          ...commonFiltered.problems.filter((x) => !x.everyday && x.date === iso),
          ...dailyProblems,
        ],
        feedback: [
          ...commonFiltered.feedback.filter((x) => !x.everyday && x.date === iso),
          ...dailyFeedback,
        ],
        priority: commonFiltered.priority.filter((x) => x.date === iso),
      }
    })

    return dataByDay
  }, [bzSystemTasksByDay, commonFiltered, commonWeekISOs, sortByTime, sortTasksByOrder])

  const weekTableRows = React.useMemo(
    () => [
      { id: "leave", label: "PV/FESTE" },
      { id: "blocked", label: "BLL" },
      { id: "external", label: "TAK EXT" },
      { id: "internal", label: "TAK INT" },
      { id: "bz", label: "BZ GA" },
      { id: "oneH", label: "1H" },
      { id: "r1", label: "R1=1H" },
      { id: "personal", label: "P:" },
      { id: "priority", label: "PRJK" },
    ],
    []
  )

  const gaTasksByDay = React.useMemo(() => {
    const byDay: Record<string, Task[]> = {}
    commonWeekISOs.forEach((iso) => {
      byDay[iso] = []
    })
    if (!ganeUserId) return byDay
    for (const task of tasks) {
      const isSystem = Boolean(task.system_template_origin_id || task.task_type === "system")
      if (isSystem) continue
      const assignedToGane =
        task.assigned_to === ganeUserId ||
        task.assignees?.some((assignee) => assignee.id === ganeUserId) ||
        task.alignment_user_ids?.includes(ganeUserId)
      if (!assignedToGane) continue

      const startDate = toDate(task.start_date || task.due_date || task.created_at)
      const endDate = toDate(task.due_date || task.start_date || task.created_at)
      if (!startDate || !endDate) continue
      const startIso = toISODate(startDate)
      const endIso = toISODate(endDate)
      for (const iso of commonWeekISOs) {
        if (iso >= startIso && iso <= endIso) {
          byDay[iso].push(task)
        }
      }

      // Overdue open FT tasks fall off the week grid after due date — pin them to today
      // (or Monday of the viewed week) so they stay findable like M3 LATE.
      const statusValue = (task.status || "").toUpperCase()
      const isOpen = statusValue !== "DONE" && !task.completed_at
      if (isOpen && endIso < todayIso) {
        const pinIso = commonWeekISOs.includes(todayIso) ? todayIso : commonWeekISOs[0]
        if (pinIso && !byDay[pinIso].some((existing) => existing.id === task.id)) {
          byDay[pinIso].push(task)
        }
      }
    }
    return byDay
  }, [commonWeekISOs, ganeUserId, tasks, todayIso])

  const commonGaRowsByDay = React.useMemo(() => {
    const byDay: Record<string, { bz: BzItem[]; detGa: CommonGaTableEntry[] }> = {}

    const appendBzEntry = (entries: BzItem[], candidate: BzItem) => {
      const candidateKeys = getCommonGaEntryMatchKeys(candidate)
      const existingIndex = entries.findIndex((entry) => {
        const existingKeys = getCommonGaEntryMatchKeys(entry)
        return candidateKeys.some((key) => existingKeys.includes(key))
      })
      if (existingIndex === -1) {
        entries.push({
          ...candidate,
          assignees: Array.from(new Set(candidate.assignees || [])),
          matchTitle: candidate.matchTitle || candidate.title,
        })
        return
      }

      const existing = entries[existingIndex]
      entries[existingIndex] = {
        ...existing,
        assignees: Array.from(new Set([...(existing.assignees || []), ...(candidate.assignees || [])])),
        time: existing.time || candidate.time || "",
        bzWithLabel: mergeLabelList(existing.bzWithLabel, candidate.bzWithLabel) || undefined,
        taskId: existing.taskId || candidate.taskId,
        templateId: existing.templateId || candidate.templateId,
        matchTitle: existing.matchTitle || candidate.matchTitle || existing.title,
      }
    }
    const appendDetGaEntry = (entries: CommonGaTableEntry[], candidate: CommonGaTableEntry) => {
      const candidateKeys = getCommonGaEntryMatchKeys(candidate)
      const existingIndex = entries.findIndex((entry) => {
        const existingKeys = getCommonGaEntryMatchKeys(entry)
        return candidateKeys.some((key) => existingKeys.includes(key))
      })
      if (existingIndex === -1) {
        entries.push(candidate)
        return
      }

      const existing = entries[existingIndex]
      entries[existingIndex] = {
        ...existing,
        assignees: Array.from(new Set([...(existing.assignees || []), ...(candidate.assignees || [])])),
        taskId: existing.taskId || candidate.taskId,
        templateId: existing.templateId || candidate.templateId,
        matchTitle: existing.matchTitle || candidate.matchTitle || existing.title,
      }
    }

    for (const iso of commonWeekISOs) {
      const bzEntries: BzItem[] = []

      for (const taskEntry of bzSystemTasksByDay[iso] || []) {
        appendBzEntry(bzEntries, taskEntry)
      }

      const bzMatchKeys = new Set(bzEntries.flatMap((entry) => getCommonGaEntryMatchKeys(entry)))
      const detGaEntries: CommonGaTableEntry[] = []

      for (const occurrence of gaSystemByDay[iso] || []) {
        const entry: CommonGaTableEntry = {
          kind: "system",
          title: occurrence.title || "-",
          templateId: occurrence.template_id,
          matchTitle: occurrence.title || "-",
        }
        const shouldHide = getCommonGaEntryMatchKeys(entry).some((key) => bzMatchKeys.has(key))
        if (!shouldHide) {
          appendDetGaEntry(detGaEntries, entry)
        }
      }

      for (const task of gaTasksByDay[iso] || []) {
        const entry: CommonGaTableEntry = {
          kind: "task",
          title: task.title || "-",
          taskId: task.id,
          matchTitle: task.title || "-",
        }
        const shouldHide = getCommonGaEntryMatchKeys(entry).some((key) => bzMatchKeys.has(key))
        if (!shouldHide) {
          appendDetGaEntry(detGaEntries, entry)
        }
      }

      byDay[iso] = {
        bz: sortByTime(bzEntries, (entry) => entry.time || "", (entry) => entry.title),
        detGa: detGaEntries,
      }
    }

    return byDay
  }, [
    bzSystemTasksByDay,
    commonWeekISOs,
    gaSystemByDay,
    gaTasksByDay,
    sortByTime,
  ])

  const canEditGaTimeSlots =
    isAdmin || (user?.username ? user.username.toLowerCase() === "gane.arifaj" : false)

  const normalizeSlotTime = (value: string) => (value ? value.slice(0, 5) : "")
  const toDayOfWeek = (iso: string) => getMondayBasedDay(fromISODate(iso))

  const remountGaTimeRowInputs = React.useCallback(() => {
    gaTimeRowInputRefs.current = {}
    setGaTimeRowsDraftVersion((version) => version + 1)
  }, [])

  const setGaTimeRowInputRef = React.useCallback(
    (index: number, field: "start" | "end", node: HTMLInputElement | null) => {
      const refs = gaTimeRowInputRefs.current[index] ?? { start: null, end: null }
      refs[field] = node
      gaTimeRowInputRefs.current[index] = refs
    },
    []
  )

  const readGaTimeRowsDraft = React.useCallback(
    () => gaTimeRowsDraft.map((row, index) => {
      const inputRefs = gaTimeRowInputRefs.current[index]
      return {
        ...row,
        start: normalizeGaTimeValue(inputRefs?.start?.value ?? row.start),
        end: normalizeGaTimeValue(inputRefs?.end?.value ?? row.end),
      }
    }),
    [gaTimeRowsDraft]
  )

  const openGaTimeRowsDialog = React.useCallback(() => {
    setGaTimeRowsDraft(sortVisibleGaTimeRows(gaTimeRows.filter((row) => !row.isSpecial)))
    remountGaTimeRowInputs()
    setGaTimeNewRowOpen(false)
    setGaTimeRowsDialogOpen(true)
  }, [gaTimeRows, remountGaTimeRowInputs])

  const hasUnsavedGaTimeRowChanges = React.useCallback(() => {
    const persisted = sortVisibleGaTimeRows(gaTimeRows.filter((row) => !row.isSpecial))
    const draft = sortVisibleGaTimeRows(readGaTimeRowsDraft())
    if (persisted.length !== draft.length) return true
    return persisted.some((row, index) => (
      normalizeGaTimeValue(row.start) !== normalizeGaTimeValue(draft[index]?.start || "") ||
      normalizeGaTimeValue(row.end) !== normalizeGaTimeValue(draft[index]?.end || "")
    ))
  }, [gaTimeRows, readGaTimeRowsDraft])

  const openGaTimeNewRowForm = React.useCallback(() => {
    if (hasUnsavedGaTimeRowChanges()) {
      toast.error("Save or cancel the existing time changes before adding a new row.")
      return
    }
    setGaTimeNewRowOpen(true)
    window.requestAnimationFrame(() => gaTimeNewRowStartRef.current?.focus({ preventScroll: true }))
  }, [hasUnsavedGaTimeRowChanges])

  const cancelGaTimeNewRow = React.useCallback(() => {
    setGaTimeNewRowOpen(false)
  }, [])

  const saveGaTimeNewRow = React.useCallback(async () => {
    if (hasUnsavedGaTimeRowChanges()) {
      toast.error("Save or cancel the existing time changes before adding a new row.")
      return
    }
    const start = normalizeGaTimeValue(gaTimeNewRowStartRef.current?.value || "")
    const startValue = parseTimeValue(start)
    if (!startValue) {
      toast.error("Enter a valid start time.")
      gaTimeNewRowStartRef.current?.focus()
      return
    }
    const enteredEnd = normalizeGaTimeValue(gaTimeNewRowEndRef.current?.value || "")
    if (!enteredEnd && startValue.hours * 60 + startValue.minutes > 23 * 60 + 29) {
      toast.error("Enter an end time for starts after 23:29.")
      return
    }
    const end = enteredEnd || addMinutesToTimeValue(start, 30)
    const endValue = parseTimeValue(end)
    if (!endValue) {
      toast.error("Enter a valid end time.")
      return
    }
    const startMinutes = startValue.hours * 60 + startValue.minutes
    const endMinutes = endValue.hours * 60 + endValue.minutes
    if (startMinutes >= endMinutes) {
      toast.error("End time must be after start time.")
      return
    }
    const overlappingRows = gaTimeRows.filter((row) => {
      if (row.isSpecial) return false
      const existingStart = parseTimeToMinutes(row.start)
      const existingEnd = parseTimeToMinutes(row.end)
      return existingStart !== null && existingEnd !== null && existingStart < endMinutes && startMinutes < existingEnd
    })
    const containingRow = overlappingRows.length === 1 ? overlappingRows[0] : null
    const containingStart = containingRow ? parseTimeToMinutes(containingRow.start) : null
    const containingEnd = containingRow ? parseTimeToMinutes(containingRow.end) : null
    const canSplitContainingRow = Boolean(
      containingRow &&
      containingStart !== null &&
      containingEnd !== null &&
      containingStart <= startMinutes &&
      endMinutes <= containingEnd
    )
    if (
      canSplitContainingRow &&
      containingStart === startMinutes &&
      containingEnd === endMinutes
    ) {
      toast.error("This time row already exists.")
      return
    }
    if (overlappingRows.length && !canSplitContainingRow) {
      toast.error("This time partially overlaps another row. Choose a time fully inside one row to split it.")
      return
    }

    setGaTimeNewRowSaving(true)
    try {
      const res = await apiFetch("/ga-time-slots/rows", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start_time: start, end_time: end }),
      })
      if (!res.ok) {
        const detail = await res.json().catch(() => null) as { detail?: string } | null
        throw new Error(detail?.detail || `ga_time_row_create_failed_${res.status}`)
      }
      const rows = normalizeGaTimeRows((await res.json()) as GaTimeTableRowResponse[])
      setGaTimeRows(rows.length ? rows : renumberGaTimeRows([...DEFAULT_GA_TIME_ROWS]))
      setGaTimeRowsDraft(sortVisibleGaTimeRows(rows.filter((row) => !row.isSpecial)))
      remountGaTimeRowInputs()
      cancelGaTimeNewRow()
      if (canSplitContainingRow && containingRow) {
        const splitLabels = [
          containingStart !== null && containingStart < startMinutes
            ? formatGaTimeRowLabel(containingRow.start, start)
            : null,
          formatGaTimeRowLabel(start, end),
          containingEnd !== null && endMinutes < containingEnd
            ? formatGaTimeRowLabel(end, containingRow.end)
            : null,
        ].filter((label): label is string => Boolean(label))
        toast.success(`Time ${containingRow.label} split into ${splitLabels.join(", ")}.`)
      } else {
        toast.success(`Time ${formatGaTimeRowLabel(start, end)} added.`)
      }
    } catch (err) {
      console.error("Failed to add GA timetable row", err)
      toast.error(err instanceof Error ? err.message : "Failed to add time row.")
    } finally {
      setGaTimeNewRowSaving(false)
    }
  }, [apiFetch, cancelGaTimeNewRow, gaTimeRows, hasUnsavedGaTimeRowChanges, remountGaTimeRowInputs])

  const removeGaTimeRowDraft = React.useCallback((index: number) => {
    setGaTimeRowsDraft(readGaTimeRowsDraft().filter((_, rowIndex) => rowIndex !== index))
    remountGaTimeRowInputs()
  }, [readGaTimeRowsDraft, remountGaTimeRowInputs])

  const resetGaTimeRowsDraft = React.useCallback(() => {
    setGaTimeRowsDraft(sortVisibleGaTimeRows(DEFAULT_GA_TIME_ROWS.filter((row) => !row.isSpecial)))
    remountGaTimeRowInputs()
  }, [remountGaTimeRowInputs])

  const saveGaTimeRows = React.useCallback(async () => {
    const visibleRows = sortVisibleGaTimeRows(
      readGaTimeRowsDraft().map((row) => {
        const start = normalizeGaTimeValue(row.start)
        const enteredEnd = normalizeGaTimeValue(row.end)
        return {
          ...row,
          start,
          end: enteredEnd || (start ? addMinutesToTimeValue(start, 30) : ""),
        }
      })
    )
    if (!visibleRows.length) {
      toast.error("Add at least one time row.")
      return
    }
    for (let idx = 0; idx < visibleRows.length; idx += 1) {
      const row = visibleRows[idx]
      const start = parseTimeValue(row.start)
      const end = parseTimeValue(row.end)
      if (!start) {
        toast.error("Enter a start time for every row.")
        return
      }
      if (!end) {
        toast.error("Use a valid HH:MM end time.")
        return
      }
      const startMinutes = start.hours * 60 + start.minutes
      const endMinutes = end.hours * 60 + end.minutes
      if (startMinutes >= endMinutes) {
        toast.error("Each row end time must be after start time.")
        return
      }
      if (idx > 0) {
        const previousEnd = parseTimeToMinutes(visibleRows[idx - 1].end)
        if (previousEnd !== null && previousEnd > startMinutes) {
          toast.error("Time rows cannot overlap.")
          return
        }
      }
    }

    setGaTimeRowsSaving(true)
    try {
      const res = await apiFetch("/ga-time-slots/rows", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rows: visibleRows.map((row) => ({
            start_time: row.start,
            end_time: row.end,
            comment: row.comment,
            comment_background_color: row.commentBackgroundColor || DEFAULT_GA_TIME_ENTRY_FORMAT.background_color,
            comment_text_color: row.commentTextColor || DEFAULT_GA_TIME_ENTRY_FORMAT.text_color,
            comment_is_bold: Boolean(row.commentIsBold),
            comment_is_italic: Boolean(row.commentIsItalic),
          })),
        }),
      })
      if (!res.ok) throw new Error(`ga_time_rows_update_failed_${res.status}`)
      const rows = normalizeGaTimeRows((await res.json()) as GaTimeTableRowResponse[])
      setGaTimeRows(rows.length ? rows : renumberGaTimeRows([...DEFAULT_GA_TIME_ROWS]))
      setGaTimeRowsDialogOpen(false)
      toast.success("GA timetable rows updated.")
    } catch (err) {
      console.error("Failed to update GA timetable rows", err)
      toast.error("Failed to update GA timetable rows.")
    } finally {
      setGaTimeRowsSaving(false)
    }
  }, [apiFetch, readGaTimeRowsDraft])

  const saveGaTimeRowComment = React.useCallback(async (
    row: GaTimeRow,
    commentId: string | null,
    comment: string,
    format: GaTimeEntryFormat,
    column: GaTimeCommentColumn = "start"
  ) => {
    const key = `${row.start}|${row.end}`
    const trimmedComment = comment.trim()
    const currentComments = gaTimeCommentsForRow(row, column)
    const targetCommentId = commentId || crypto.randomUUID()
    const comments = commentId
      ? currentComments.flatMap((item) => (
          item.id !== commentId
            ? [item]
            : trimmedComment
              ? [{
                  ...item,
                  content: trimmedComment,
                  backgroundColor: format.background_color,
                  textColor: format.text_color,
                  isBold: format.is_bold,
                  isItalic: format.is_italic,
                }]
              : []
        ))
      : trimmedComment
        ? [
            ...currentComments,
            {
              id: targetCommentId,
              content: trimmedComment,
              backgroundColor: format.background_color,
              textColor: format.text_color,
              isBold: format.is_bold,
              isItalic: format.is_italic,
            },
          ]
        : currentComments
    setGaTimeCommentSavingKey(key)
    try {
      const res = await apiFetch("/ga-time-slots/rows/comments", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          start_time: row.start,
          end_time: row.end,
          column,
          comments: comments.map((item) => ({
            id: item.id,
            content: item.content,
            comment_background_color: item.backgroundColor,
            comment_text_color: item.textColor,
            comment_is_bold: item.isBold,
            comment_is_italic: item.isItalic,
          })),
        }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => null)
        throw new Error(apiErrorMessage(data, "Failed to save row comment"))
      }
      const updated = (await res.json()) as GaTimeTableRowResponse
      const normalized = normalizeGaTimeRows([updated])[0]
      setGaTimeRows((current) => current.map((item) => (
        item.start === row.start && item.end === row.end
          ? normalized
          : item
      )))
      if (!commentId && trimmedComment) {
        const newEditorKey = gaTimeCommentEditorKey(row, "new", column)
        setGaTimeCommentEditingKey((current) => (
          current === newEditorKey
            ? gaTimeCommentEditorKey(row, targetCommentId, column)
            : current
        ))
      }
      if (!trimmedComment) toast.success("Comment removed.")
      return true
    } catch (error) {
      console.error("Failed to save GA timetable row comment", error)
      toast.error(error instanceof Error ? error.message : "Failed to save row comment")
      return false
    } finally {
      setGaTimeCommentSavingKey(null)
    }
  }, [apiFetch])

  const moveGaTimeRowComment = React.useCallback(async (
    source: GaTimeCommentDragSource,
    targetRow: GaTimeRow,
    targetColumn: GaTimeCommentColumn,
    beforeCommentId: string | null
  ) => {
    if (gaTimeCommentSavingKey) return
    const sourceCellKey = `${source.rowStart}|${source.rowEnd}|${source.column}`
    const targetCellKey = `${targetRow.start}|${targetRow.end}|${targetColumn}`
    const sourceComments = gaTimeRows.find(
      (row) => row.start === source.rowStart && row.end === source.rowEnd
    )
    const sourceIndex = sourceComments
      ? gaTimeCommentsForRow(sourceComments, source.column).findIndex((comment) => comment.id === source.commentId)
      : -1
    if (sourceIndex < 0) return
    if (sourceCellKey === targetCellKey) {
      const targetComments = gaTimeCommentsForRow(targetRow, targetColumn)
      const currentBeforeId = targetComments[sourceIndex + 1]?.id ?? null
      if (beforeCommentId === source.commentId || beforeCommentId === currentBeforeId) return
    }

    const savingKey = `${source.rowStart}|${source.rowEnd}`
    setGaTimeCommentEditingKey(null)
    setGaTimeCommentSavingKey(savingKey)
    try {
      const res = await apiFetch("/ga-time-slots/rows/comments/move", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          comment_id: source.commentId,
          source_start_time: source.rowStart,
          source_end_time: source.rowEnd,
          source_column: source.column,
          target_start_time: targetRow.start,
          target_end_time: targetRow.end,
          target_column: targetColumn,
          before_comment_id: beforeCommentId,
        }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => null)
        throw new Error(apiErrorMessage(data, "Failed to move row comment"))
      }
      const updatedRows = normalizeGaTimeRows((await res.json()) as GaTimeTableRowResponse[])
      const updatedByKey = new Map(updatedRows.map((row) => [`${row.start}|${row.end}`, row]))
      setGaTimeRows((current) => current.map((row) => updatedByKey.get(`${row.start}|${row.end}`) || row))
    } catch (error) {
      console.error("Failed to move GA timetable row comment", error)
      toast.error(error instanceof Error ? error.message : "Failed to move row comment")
    } finally {
      setGaTimeCommentSavingKey(null)
      gaTimeCommentDraggingRef.current = null
      setGaTimeCommentDragging(null)
      setGaTimeCommentPointerPosition(null)
      setGaTimeCommentDropTarget(null)
    }
  }, [apiFetch, gaTimeCommentSavingKey, gaTimeRows])

  const moveGaTimeCommentToSlot = React.useCallback(async (
    source: GaTimeCommentDragSource,
    targetDayOfWeek: number,
    targetStartTime: string,
    targetEndTime: string,
    beforeEntryId: string | null
  ) => {
    if (gaTimeCommentSavingKey) return
    const savingKey = `${source.rowStart}|${source.rowEnd}`
    const targetCellKey = `${targetDayOfWeek}|${targetStartTime}`
    setGaTimeCommentEditingKey(null)
    setGaTimeCommentSavingKey(savingKey)
    try {
      const res = await apiFetch("/ga-time-slots/rows/comments/move-to-slot", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          comment_id: source.commentId,
          source_start_time: source.rowStart,
          source_end_time: source.rowEnd,
          source_column: source.column,
          target_day_of_week: targetDayOfWeek,
          target_start_time: targetStartTime,
          target_end_time: targetEndTime,
          before_entry_id: beforeEntryId,
        }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => null)
        throw new Error(apiErrorMessage(data, "Failed to move comment into timetable"))
      }
      const updated = (await res.json()) as GaTimeCrossCellMoveResponse
      const normalizedRows = normalizeGaTimeRows(updated.rows)
      const updatedRowsByKey = new Map(normalizedRows.map((row) => [`${row.start}|${row.end}`, row]))
      setGaTimeRows((current) => current.map((row) => updatedRowsByKey.get(`${row.start}|${row.end}`) || row))
      setGaTimeEntries((current) => [
        ...current.filter((entry) => {
          const rowStart = resolveGaTimeRowStart(normalizeSlotTime(entry.start_time), gaTimeRows)
          return `${entry.day_of_week}|${rowStart}` !== targetCellKey
        }),
        ...updated.entries,
      ])
    } catch (error) {
      console.error("Failed to move GA comment into timetable", error)
      toast.error(error instanceof Error ? error.message : "Failed to move comment")
    } finally {
      setGaTimeCommentSavingKey(null)
      gaTimeCommentDraggingRef.current = null
      gaTimeCommentDropTargetRef.current = null
      gaTimeCommentDropHandledRef.current = false
      setGaTimeCommentDragging(null)
      setGaTimeCommentDropTarget(null)
      setGaTimeDropTarget(null)
    }
  }, [apiFetch, gaTimeCommentSavingKey, gaTimeRows])

  const moveGaTimeEntryToComment = React.useCallback(async (
    entryId: string,
    targetRow: GaTimeRow,
    targetColumn: GaTimeCommentColumn,
    beforeCommentId: string | null
  ) => {
    const draggedEntry = gaTimeEntries.find((entry) => entry.id === entryId)
    if (!draggedEntry || draggedEntry.source_type || gaTimeSaving[entryId]) return
    const sourceRowStart = resolveGaTimeRowStart(normalizeSlotTime(draggedEntry.start_time), gaTimeRows)
    const sourceCellKey = `${draggedEntry.day_of_week}|${sourceRowStart}`
    setGaTimeEditingId(null)
    setGaTimeAddingCell(null)
    setGaTimeSaving((current) => ({ ...current, [entryId]: true }))
    try {
      const res = await apiFetch("/ga-time-slots/rows/comments/move-from-slot", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          entry_id: entryId,
          target_start_time: targetRow.start,
          target_end_time: targetRow.end,
          target_column: targetColumn,
          before_comment_id: beforeCommentId,
        }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => null)
        throw new Error(apiErrorMessage(data, "Failed to move timetable entry into comments"))
      }
      const updated = (await res.json()) as GaTimeCrossCellMoveResponse
      const normalizedRows = normalizeGaTimeRows(updated.rows)
      const updatedRowsByKey = new Map(normalizedRows.map((row) => [`${row.start}|${row.end}`, row]))
      setGaTimeRows((current) => current.map((row) => updatedRowsByKey.get(`${row.start}|${row.end}`) || row))
      setGaTimeEntries((current) => [
        ...current.filter((entry) => {
          const rowStart = resolveGaTimeRowStart(normalizeSlotTime(entry.start_time), gaTimeRows)
          return `${entry.day_of_week}|${rowStart}` !== sourceCellKey
        }),
        ...updated.entries,
      ])
    } catch (error) {
      console.error("Failed to move GA timetable entry into comments", error)
      toast.error(error instanceof Error ? error.message : "Failed to move timetable entry")
    } finally {
      setGaTimeSaving((current) => ({ ...current, [entryId]: false }))
      gaTimeDraggingIdRef.current = null
      gaTimeEntryCommentDropTargetRef.current = null
      setGaTimeDraggingId(null)
      setGaTimeDropTarget(null)
      setGaTimeCommentDropTarget(null)
    }
  }, [apiFetch, gaTimeEntries, gaTimeRows, gaTimeSaving])

  React.useEffect(() => {
    const clearPointerDrag = () => {
      gaTimeCommentPointerDragRef.current = null
      gaTimeCommentDraggingRef.current = null
      gaTimeCommentDropTargetRef.current = null
      setGaTimeCommentDragging(null)
      setGaTimeCommentDropTarget(null)
      setGaTimeDropTarget(null)
    }

    const updatePointerTarget = (clientX: number, clientY: number) => {
      const element = document.elementFromPoint(clientX, clientY) as HTMLElement | null
      if (!element) return

      const commentCell = element.closest<HTMLElement>("[data-ga-comment-cell]")
      if (commentCell) {
        const commentEntry = element.closest<HTMLElement>("[data-ga-comment-entry-id]")
        let beforeCommentId: string | null = null
        if (commentEntry) {
          const bounds = commentEntry.getBoundingClientRect()
          beforeCommentId = clientY < bounds.top + bounds.height / 2
            ? commentEntry.dataset.gaCommentEntryId || null
            : commentEntry.dataset.gaNextCommentId || null
        }
        const rowStart = commentCell.dataset.gaRowStart
        const rowEnd = commentCell.dataset.gaRowEnd
        const column = commentCell.dataset.gaCommentColumn as GaTimeCommentColumn | undefined
        if (!rowStart || !rowEnd || !column) return
        gaTimeCommentDropTargetRef.current = {
          kind: "comment",
          rowStart,
          rowEnd,
          column,
          beforeCommentId,
        }
        const cellKey = `${rowStart}|${rowEnd}|${column}`
        setGaTimeCommentDropTarget((current) => (
          current?.cellKey === cellKey && current.beforeCommentId === beforeCommentId
            ? current
            : { cellKey, beforeCommentId }
        ))
        setGaTimeDropTarget(null)
        return
      }

      const slotCell = element.closest<HTMLElement>("[data-ga-slot-cell]")
      if (slotCell) {
        const slotEntry = element.closest<HTMLElement>("[data-ga-slot-entry-id]")
        let beforeEntryId: string | null = null
        if (slotEntry) {
          const bounds = slotEntry.getBoundingClientRect()
          beforeEntryId = clientY < bounds.top + bounds.height / 2
            ? slotEntry.dataset.gaSlotEntryId || null
            : slotEntry.dataset.gaNextEntryId || null
        }
        const dayOfWeek = Number(slotCell.dataset.gaDayOfWeek)
        const startTime = slotCell.dataset.gaStartTime
        const endTime = slotCell.dataset.gaEndTime
        if (!Number.isInteger(dayOfWeek) || !startTime || !endTime) return
        gaTimeCommentDropTargetRef.current = {
          kind: "slot",
          dayOfWeek,
          startTime,
          endTime,
          beforeEntryId,
        }
        const cellKey = `${dayOfWeek}|${startTime}`
        setGaTimeDropTarget((current) => (
          current?.cellKey === cellKey && current.beforeEntryId === beforeEntryId
            ? current
            : { cellKey, beforeEntryId }
        ))
        setGaTimeCommentDropTarget(null)
      }
    }

    const handlePointerMove = (event: PointerEvent) => {
      const drag = gaTimeCommentPointerDragRef.current
      if (!drag || event.pointerId !== drag.pointerId) return
      if (!drag.active) {
        const distance = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY)
        if (distance < 5) return
        drag.active = true
        gaTimeCommentDraggingRef.current = drag.source
        gaTimeCommentDropTargetRef.current = null
        gaTimeCommentDropHandledRef.current = false
        setGaTimeCommentDragging(drag.source)
        setGaTimeCommentEditingKey(null)
        setGaTimeEditingId(null)
        setGaTimeAddingCell(null)
      }
      event.preventDefault()
      setGaTimeCommentPointerPosition({ x: event.clientX, y: event.clientY })
      updatePointerTarget(event.clientX, event.clientY)
    }

    const handlePointerEnd = (event: PointerEvent) => {
      const drag = gaTimeCommentPointerDragRef.current
      if (!drag || event.pointerId !== drag.pointerId) return
      const target = gaTimeCommentDropTargetRef.current
      const wasActive = drag.active
      const source = drag.source
      clearPointerDrag()
      if (!wasActive || !target) return
      event.preventDefault()
      gaTimeCommentSuppressClickRef.current = true
      window.setTimeout(() => {
        gaTimeCommentSuppressClickRef.current = false
      }, 0)
      if (target.kind === "comment") {
        const targetRow = gaTimeRows.find(
          (row) => row.start === target.rowStart && row.end === target.rowEnd
        )
        if (targetRow) {
          void moveGaTimeRowComment(source, targetRow, target.column, target.beforeCommentId)
        }
      } else {
        void moveGaTimeCommentToSlot(
          source,
          target.dayOfWeek,
          target.startTime,
          target.endTime,
          target.beforeEntryId
        )
      }
    }

    const handlePointerCancel = (event: PointerEvent) => {
      const drag = gaTimeCommentPointerDragRef.current
      if (!drag || event.pointerId !== drag.pointerId) return
      clearPointerDrag()
    }

    document.addEventListener("pointermove", handlePointerMove, { passive: false })
    document.addEventListener("pointerup", handlePointerEnd)
    document.addEventListener("pointercancel", handlePointerCancel)
    return () => {
      document.removeEventListener("pointermove", handlePointerMove)
      document.removeEventListener("pointerup", handlePointerEnd)
      document.removeEventListener("pointercancel", handlePointerCancel)
    }
  }, [gaTimeRows, moveGaTimeCommentToSlot, moveGaTimeRowComment])

  const gaTimeEntriesByCell = React.useMemo(() => {
    const map = new Map<string, GaTimeSlotEntry[]>()
    for (const entry of gaTimeEntries) {
      const day = entry.day_of_week
      const start = resolveGaTimeRowStart(normalizeSlotTime(entry.start_time), gaTimeRows)
      const key = `${day}|${start}`
      const list = map.get(key) || []
      list.push(entry)
      map.set(key, list)
    }
    for (const list of map.values()) {
      list.sort((a, b) => {
        const orderDifference = (a.sort_order ?? 0) - (b.sort_order ?? 0)
        if (orderDifference) return orderDifference
        return a.created_at.localeCompare(b.created_at)
      })
    }
    return map
  }, [gaTimeEntries, gaTimeRows])

  const gaMeetingsByCell = React.useMemo(() => {
    type TimeTableMeeting =
      | { kind: "internal"; meeting: InternalItem }
      | { kind: "external"; meeting: ExternalItem }
    const map = new Map<string, TimeTableMeeting[]>()
    const addMeeting = (item: TimeTableMeeting) => {
      const { meeting } = item
      if (!commonWeekISOs.includes(meeting.date)) return
      const startMinutes = parseTimeToMinutes(meeting.time)
      if (startMinutes === null) return
      const rowStart = resolveGaTimeRowStart(minutesToTimeValue(startMinutes), gaTimeRows)
      if (!gaTimeRows.some((row) => row.start === rowStart)) return
      const key = `${toDayOfWeek(meeting.date)}|${rowStart}`
      const list = map.get(key) || []
      list.push(item)
      map.set(key, list)
    }

    for (const meeting of commonFiltered.internal) {
      if (isManualInternalMeeting(meeting)) addMeeting({ kind: "internal", meeting })
    }
    for (const meeting of commonFiltered.external) addMeeting({ kind: "external", meeting })
    for (const meetings of map.values()) {
      meetings.sort((a, b) => {
        const timeDifference =
          (parseTimeToMinutes(a.meeting.time) ?? Number.MAX_SAFE_INTEGER) -
          (parseTimeToMinutes(b.meeting.time) ?? Number.MAX_SAFE_INTEGER)
        if (timeDifference) return timeDifference
        return a.meeting.title.localeCompare(b.meeting.title)
      })
    }
    return map
  }, [commonFiltered.external, commonFiltered.internal, commonWeekISOs, gaTimeRows])

  const createGaTimeEntry = React.useCallback(
    async (
      dayOfWeek: string,
      startTime: string,
      endTime: string,
      content: string,
      format: GaTimeEntryFormat
    ) => {
      const trimmed = content.trim()
      if (!trimmed) return null
      const key = `${dayOfWeek}|${startTime}`
      const sortOrder = gaTimeEntriesByCell.get(key)?.length ?? 0
      setGaTimeSaving((prev) => ({ ...prev, [key]: true }))
      try {
        const res = await apiFetch("/ga-time-slots", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            day_of_week: Number(dayOfWeek),
            start_time: startTime,
            end_time: endTime,
            content: trimmed,
            sort_order: sortOrder,
            ...format,
          }),
        })
        if (!res.ok) {
          throw new Error(`ga_time_slot_create_failed_${res.status}`)
        }
        const created = (await res.json()) as GaTimeSlotEntry
        setGaTimeEntries((prev) => [...prev, created])
        return created
      } catch (err) {
        console.error("Failed to create GA time slot entry", err)
        toast.error("Failed to save time slot entry.")
        return null
      } finally {
        setGaTimeSaving((prev) => ({ ...prev, [key]: false }))
      }
    },
    [apiFetch, gaTimeEntriesByCell]
  )

  const updateGaTimeEntry = React.useCallback(
    async (entryId: string, content: string, format: GaTimeEntryFormat) => {
      const trimmed = content.trim()
      if (!trimmed) return false
      setGaTimeSaving((prev) => ({ ...prev, [entryId]: true }))
      try {
        const res = await apiFetch(`/ga-time-slots/${entryId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: trimmed, ...format }),
        })
        if (!res.ok) {
          throw new Error(`ga_time_slot_update_failed_${res.status}`)
        }
        const updated = (await res.json()) as GaTimeSlotEntry
        setGaTimeEntries((prev) => prev.map((entry) => (entry.id === entryId ? updated : entry)))
        return true
      } catch (err) {
        console.error("Failed to update GA time slot entry", err)
        toast.error("Failed to update time slot entry.")
        return false
      } finally {
        setGaTimeSaving((prev) => ({ ...prev, [entryId]: false }))
      }
    },
    [apiFetch]
  )

  const moveGaTimeEntry = React.useCallback(
    async (
      entryId: string,
      targetDayOfWeek: number,
      targetStartTime: string,
      targetEndTime: string,
      beforeEntryId: string | null
    ) => {
      const draggedEntry = gaTimeEntries.find((entry) => entry.id === entryId)
      if (!draggedEntry || draggedEntry.source_type || gaTimeSaving[entryId]) return

      const cellKeyForEntry = (entry: GaTimeSlotEntry) => {
        const rowStart = resolveGaTimeRowStart(normalizeSlotTime(entry.start_time), gaTimeRows)
        return `${entry.day_of_week}|${rowStart}`
      }
      const sourceCellKey = cellKeyForEntry(draggedEntry)
      const targetCellKey = `${targetDayOfWeek}|${targetStartTime}`
      if (sourceCellKey === targetCellKey && beforeEntryId === entryId) {
        setGaTimeDraggingId(null)
        setGaTimeDropTarget(null)
        return
      }
      const originalTargetEntries = gaTimeEntries.filter(
        (entry) => !entry.source_type && cellKeyForEntry(entry) === targetCellKey
      )
      const targetEntries = originalTargetEntries.filter((entry) => entry.id !== entryId)
      const beforeEntryIndex = beforeEntryId
        ? targetEntries.findIndex((entry) => entry.id === beforeEntryId)
        : -1
      const insertionIndex = beforeEntryIndex >= 0 ? beforeEntryIndex : targetEntries.length
      targetEntries.splice(insertionIndex, 0, draggedEntry)

      if (
        sourceCellKey === targetCellKey &&
        originalTargetEntries.length === targetEntries.length &&
        originalTargetEntries.every((entry, index) => entry.id === targetEntries[index]?.id)
      ) {
        setGaTimeDraggingId(null)
        setGaTimeDropTarget(null)
        return
      }

      const sourceEntries = sourceCellKey === targetCellKey
        ? []
        : gaTimeEntries.filter(
            (entry) => !entry.source_type && entry.id !== entryId && cellKeyForEntry(entry) === sourceCellKey
          )
      const positionedEntries = [
        ...sourceEntries.map((entry, sortOrder) => ({ ...entry, sort_order: sortOrder })),
        ...targetEntries.map((entry, sortOrder) => ({
          ...entry,
          day_of_week: targetDayOfWeek,
          start_time: targetStartTime,
          end_time: targetEndTime,
          sort_order: sortOrder,
        })),
      ]
      const positionedById = new Map(positionedEntries.map((entry) => [entry.id, entry]))
      const previousEntries = gaTimeEntries

      setGaTimeEditingId(null)
      setGaTimeAddingCell(null)
      setGaTimeSaving((prev) => ({ ...prev, [entryId]: true }))
      setGaTimeEntries((prev) => prev.map((entry) => positionedById.get(entry.id) || entry))
      try {
        const res = await apiFetch("/ga-time-slots/reorder", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            entries: positionedEntries.map((entry) => ({
              id: entry.id,
              day_of_week: entry.day_of_week,
              start_time: normalizeSlotTime(entry.start_time),
              end_time: normalizeSlotTime(entry.end_time),
              sort_order: entry.sort_order,
            })),
          }),
        })
        if (!res.ok) throw new Error(`ga_time_slot_reorder_failed_${res.status}`)
        const savedEntries = (await res.json()) as GaTimeSlotEntry[]
        const savedById = new Map(savedEntries.map((entry) => [entry.id, entry]))
        setGaTimeEntries((prev) => prev.map((entry) => savedById.get(entry.id) || entry))
      } catch (error) {
        console.error("Failed to move GA timetable entry", error)
        setGaTimeEntries(previousEntries)
        toast.error("Failed to move timetable entry.")
      } finally {
        setGaTimeSaving((prev) => ({ ...prev, [entryId]: false }))
        setGaTimeDraggingId(null)
        setGaTimeDropTarget(null)
      }
    },
    [apiFetch, gaTimeEntries, gaTimeRows, gaTimeSaving]
  )

  const deleteGaTimeEntry = React.useCallback(
    async (entryId: string) => {
      if (gaTimeEntries.find((entry) => entry.id === entryId)?.source_type) return
      setGaTimeDeleting((prev) => ({ ...prev, [entryId]: true }))
      try {
        const res = await apiFetch(`/ga-time-slots/${entryId}`, { method: "DELETE" })
        if (!res.ok) {
          throw new Error(`ga_time_slot_delete_failed_${res.status}`)
        }
        setGaTimeEntries((prev) => prev.filter((entry) => entry.id !== entryId))
      } catch (err) {
        console.error("Failed to delete GA time slot entry", err)
        toast.error("Failed to delete time slot entry.")
      } finally {
        setGaTimeDeleting((prev) => ({ ...prev, [entryId]: false }))
      }
    },
    [apiFetch, gaTimeEntries]
  )

  const renderGaTimeCommentCell = (
    slot: GaTimeRow,
    column: GaTimeCommentColumn,
    isSpecialStartCell = false
  ) => {
    const comments = gaTimeCommentsForRow(slot, column)
    const cellKey = `${slot.start}|${slot.end}|${column}`
    const rowSavingKey = `${slot.start}|${slot.end}`
    const newEditorKey = gaTimeCommentEditorKey(slot, "new", column)

    const dropIntoComment = (beforeCommentId: string | null) => {
      const commentSource = gaTimeCommentDraggingRef.current
      const entryId = gaTimeDraggingIdRef.current
      setGaTimeCommentDropTarget(null)
      if (commentSource) {
        void moveGaTimeRowComment(commentSource, slot, column, beforeCommentId)
      } else if (entryId) {
        void moveGaTimeEntryToComment(entryId, slot, column, beforeCommentId)
      }
    }

    return (
      <td
        className={`ga-time-cell ga-time-comment${isSpecialStartCell ? " ga-time-special-comment" : ""}`}
        data-ga-comment-cell="true"
        data-ga-row-start={slot.start}
        data-ga-row-end={slot.end}
        data-ga-comment-column={column}
        onDragOver={(event) => {
          if (!canEditGaTimeSlots || (!gaTimeCommentDraggingRef.current && !gaTimeDraggingIdRef.current)) return
          event.preventDefault()
          event.dataTransfer.dropEffect = "move"
          if (gaTimeCommentDraggingRef.current) {
            gaTimeCommentDropTargetRef.current = {
              kind: "comment",
              rowStart: slot.start,
              rowEnd: slot.end,
              column,
              beforeCommentId: null,
            }
          } else {
            gaTimeEntryCommentDropTargetRef.current = {
              rowStart: slot.start,
              rowEnd: slot.end,
              column,
              beforeCommentId: null,
            }
          }
          setGaTimeCommentDropTarget((current) => (
            current?.cellKey === cellKey && current.beforeCommentId === null
              ? current
              : { cellKey, beforeCommentId: null }
          ))
        }}
        onDrop={(event) => {
          if (!canEditGaTimeSlots || (!gaTimeCommentDraggingRef.current && !gaTimeDraggingIdRef.current)) return
          event.preventDefault()
          if (gaTimeCommentDraggingRef.current) gaTimeCommentDropHandledRef.current = true
          if (gaTimeDraggingIdRef.current) gaTimeDropHandledRef.current = true
          dropIntoComment(null)
        }}
      >
        <div className={`ga-time-comment-list ${
          gaTimeCommentDropTarget?.cellKey === cellKey && gaTimeCommentDropTarget.beforeCommentId === null
            ? "ga-time-drop-cell"
            : ""
        }`}>
          {comments.map((comment, commentIndex) => {
            const editorKey = gaTimeCommentEditorKey(slot, comment.id, column)
            if (gaTimeCommentEditingKey === editorKey) {
              return (
                <GaTimeRowCommentEditor
                  key={comment.id}
                  initialComment={comment.content}
                  initialFormat={{
                    background_color: comment.backgroundColor,
                    text_color: comment.textColor,
                    is_bold: comment.isBold,
                    is_italic: comment.isItalic,
                  }}
                  saving={gaTimeCommentSavingKey === rowSavingKey}
                  onSave={(content, format) => saveGaTimeRowComment(slot, comment.id, content, format, column)}
                  onCancel={() => setGaTimeCommentEditingKey(null)}
                />
              )
            }
            return (
              <div
                key={comment.id}
                className={`ga-time-comment-entry ga-time-draggable select-none ${
                  gaTimeCommentDragging?.commentId === comment.id ? "ga-time-dragging" : ""
                } ${
                  gaTimeCommentDropTarget?.cellKey === cellKey &&
                  gaTimeCommentDropTarget.beforeCommentId === comment.id
                    ? "ga-time-drop-before"
                    : ""
                }`}
                style={gaTimeEntryStyle({
                  background_color: comment.backgroundColor,
                  text_color: comment.textColor,
                  is_bold: comment.isBold,
                  is_italic: comment.isItalic,
                })}
                draggable={false}
                data-ga-comment-entry-id={comment.id}
                data-ga-next-comment-id={comments[commentIndex + 1]?.id || ""}
                onPointerDown={(event) => {
                  if (!canEditGaTimeSlots || gaTimeCommentSavingKey || event.button !== 0) return
                  if ((event.target as HTMLElement).closest(".ga-time-delete")) return
                  gaTimeCommentPointerDragRef.current = {
                    source: {
                      commentId: comment.id,
                      rowStart: slot.start,
                      rowEnd: slot.end,
                      column,
                    },
                    pointerId: event.pointerId,
                    startX: event.clientX,
                    startY: event.clientY,
                    active: false,
                  }
                }}
                onDragOver={(event) => {
                  if (!canEditGaTimeSlots || (!gaTimeCommentDraggingRef.current && !gaTimeDraggingIdRef.current)) return
                  event.preventDefault()
                  event.stopPropagation()
                  event.dataTransfer.dropEffect = "move"
                  const bounds = event.currentTarget.getBoundingClientRect()
                  const isAfter = event.clientY >= bounds.top + bounds.height / 2
                  const beforeCommentId = isAfter
                    ? comments[commentIndex + 1]?.id ?? null
                    : comment.id
                  if (gaTimeCommentDraggingRef.current) {
                    gaTimeCommentDropTargetRef.current = {
                      kind: "comment",
                      rowStart: slot.start,
                      rowEnd: slot.end,
                      column,
                      beforeCommentId,
                    }
                  } else {
                    gaTimeEntryCommentDropTargetRef.current = {
                      rowStart: slot.start,
                      rowEnd: slot.end,
                      column,
                      beforeCommentId,
                    }
                  }
                  setGaTimeCommentDropTarget((current) => (
                    current?.cellKey === cellKey && current.beforeCommentId === beforeCommentId
                      ? current
                      : { cellKey, beforeCommentId }
                  ))
                }}
                onDrop={(event) => {
                  if (!canEditGaTimeSlots || (!gaTimeCommentDraggingRef.current && !gaTimeDraggingIdRef.current)) return
                  event.preventDefault()
                  event.stopPropagation()
                  const bounds = event.currentTarget.getBoundingClientRect()
                  const isAfter = event.clientY >= bounds.top + bounds.height / 2
                  const beforeCommentId = isAfter
                    ? comments[commentIndex + 1]?.id ?? null
                    : comment.id
                  if (gaTimeCommentDraggingRef.current) gaTimeCommentDropHandledRef.current = true
                  if (gaTimeDraggingIdRef.current) gaTimeDropHandledRef.current = true
                  dropIntoComment(beforeCommentId)
                }}
                title="Drag to move or click to edit"
              >
                <span
                  className="ga-time-comment-text"
                  role="button"
                  tabIndex={0}
                  draggable={false}
                  onClick={() => {
                    if (gaTimeCommentSuppressClickRef.current) return
                    if (!canEditGaTimeSlots) return
                    setGaTimeAddingCell(null)
                    setGaTimeEditingId(null)
                    setGaTimeCommentEditingKey(editorKey)
                  }}
                  onKeyDown={(event) => {
                    if (event.key !== "Enter" && event.key !== " ") return
                    event.preventDefault()
                    if (!canEditGaTimeSlots) return
                    setGaTimeAddingCell(null)
                    setGaTimeEditingId(null)
                    setGaTimeCommentEditingKey(editorKey)
                  }}
                >
                  <GaTimeRichTextContent value={comment.content} />
                </span>
                {canEditGaTimeSlots ? (
                  <button
                    type="button"
                    className="ga-time-delete"
                    disabled={gaTimeCommentSavingKey === rowSavingKey}
                    onClick={() => void saveGaTimeRowComment(slot, comment.id, "", {
                      background_color: comment.backgroundColor,
                      text_color: comment.textColor,
                      is_bold: comment.isBold,
                      is_italic: comment.isItalic,
                    }, column)}
                    title="Delete comment"
                    aria-label="Delete comment"
                  >
                    {gaTimeCommentSavingKey === rowSavingKey ? "..." : "\u00d7"}
                  </button>
                ) : null}
              </div>
            )
          })}
          {canEditGaTimeSlots ? (
            gaTimeCommentEditingKey === newEditorKey ? (
              <GaTimeRowCommentEditor
                initialComment=""
                saving={gaTimeCommentSavingKey === rowSavingKey}
                onSave={(content, format) => saveGaTimeRowComment(slot, null, content, format, column)}
                onCancel={() => setGaTimeCommentEditingKey(null)}
              />
            ) : (
              <button
                type="button"
                className="ga-time-add ga-time-comment-add"
                title="Add another comment"
                aria-label={`Add ${column === "end" ? "end " : ""}comment for ${slot.label || slot.start}`}
                onClick={() => {
                  setGaTimeAddingCell(null)
                  setGaTimeEditingId(null)
                  setGaTimeCommentEditingKey(newEditorKey)
                }}
              >
                +
              </button>
            )
          ) : null}
        </div>
      </td>
    )
  }

  const AdminCommonWeekTable = () => {
    const weekTitleRange =
      commonWeekISOs.length >= 2
        ? `${formatDateHuman(commonWeekISOs[0])} - ${formatDateHuman(commonWeekISOs[commonWeekISOs.length - 1])}`
        : ""
    const exportPayload = React.useMemo(() => {
      const columns = ["NR", "LLOJI", ...commonWeekISOs.map((iso) => `${getDayCode(fromISODate(iso))} = ${formatDateHuman(iso)}`)]

      const assigneesSuffix = (entry: any) => {
        const initialsList = entryAssignees(entry).map((name: string) => commonViewInitials(name)).filter(Boolean)
        return initialsList.length ? ` (${initialsList.join(", ")})` : ""
      }

      const renderBzLines = (iso: string) => {
        const bzEntries = commonGaRowsByDay[iso]?.bz || []
        return bzEntries.map((e: BzItem, idx: number) => {
          const bzLabel = e.bzWithLabel ? ` - ${e.bzWithLabel}` : ""
          return `${idx + 1}. ${commonPrintTitleLine(`${formatBzTimeDisplay(e.time)} ${e.title}`.trim())}${bzLabel}${assigneesSuffix(e)}`
        })
      }

      const renderCellLines = (rowId: CommonType, iso: string) => {
        const dayData = tableDataByDay?.[iso]
        if (!dayData) return []
        if (rowId === "det_ga") {
          const combined = commonGaRowsByDay[iso]?.detGa || []
          if (!combined.length) return []
          return combined.map((entry, idx) => `${idx + 1}. ${commonPrintTitleLine(entry.title)}`)
        }

        const entries =
          rowId === "late"
            ? dayData.late
            : rowId === "absent"
              ? dayData.absent
              : rowId === "leave"
                ? dayData.leave
                : rowId === "blocked"
                  ? dayData.blocked
                  : rowId === "oneH"
                    ? dayData.oneH
                    : rowId === "r1"
                      ? dayData.r1
                      : rowId === "personal"
                        ? dayData.personal
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

        if (rowId === "bz") {
          return renderBzLines(iso)
        }
        if (!entries.length) return []

        if (rowId === "late") {
          return dayData.late.map((e: LateItem, idx: number) =>
            `${idx + 1}. ${e.start || "08:00"}-${e.until}${assigneesSuffix(e)}`
          )
        }
        if (rowId === "absent") {
          return dayData.absent.map((e: AbsentItem, idx: number) => `${idx + 1}. ${e.from} - ${e.to}${assigneesSuffix(e)}`)
        }
        if (rowId === "leave") {
          return dayData.leave.map((e: LeaveItem, idx: number) => {
            const isAllUsers = Boolean(e.isAllUsers || e.person === ALL_USERS_INITIALS)
            const timeLabel = e.fullDay ? "08:00-16:30" : `${e.from}-${e.to}`
            const label = isAllUsers ? `${timeLabel} ALL` : timeLabel
            const noteLabel = e.note ? ` - ${e.note}` : ""
            return `${idx + 1}. ${label}${noteLabel}${isAllUsers ? "" : assigneesSuffix(e)}`
          })
        }
        if (rowId === "blocked") {
          return dayData.blocked.map((e: BlockedItem, idx: number) =>
            `${idx + 1}. ${commonPrintTitleLine(e.title)}${assigneesSuffix(e)}`
          )
        }
        if (rowId === "problem" || rowId === "feedback") {
          return (rowId === "problem" ? dayData.problems : dayData.feedback).map((e: ProblemItem | FeedbackItem, idx: number) => {
            const dateLabel = e.createdDate ? formatDateHuman(e.createdDate) : formatDateHuman(e.date)
            const noteLabel = e.note ? ` - ${e.note}` : ""
            return `${idx + 1}. ${e.title} - ${dateLabel}${noteLabel}${assigneesSuffix(e)}`
          })
        }
        if (rowId === "oneH" || rowId === "r1") {
          return mergeTaskEntriesByVisibleTitle(entries as (OneHItem | R1Item)[]).map((e: any, idx: number) =>
            `${idx + 1}. ${commonPrintTitleLine(e.title)}${assigneesSuffix(e)}`
          )
        }
        if (rowId === "personal") {
          return mergeTaskEntriesByVisibleTitle(entries as PersonalItem[]).map((e: PersonalItem, idx: number) =>
            `${idx + 1}. ${commonPrintTitleLine(e.title)}${assigneesSuffix(e)}`
          )
        }
        if (rowId === "external") {
          return dayData.external.map((e: ExternalItem, idx: number) =>
            `${idx + 1}. ${`${commonPrintTitleLine(e.title)} ${formatTimeLabel(e.time)}`.trim()}${assigneesSuffix(e)}`
          )
        }
        if (rowId === "internal") {
          return dayData.internal.map((e: InternalItem, idx: number) =>
            `${idx + 1}. ${`${commonPrintTitleLine(e.title)} ${formatTimeLabel(e.time)}`.trim()}${assigneesSuffix(e)}`
          )
        }
        if (rowId === "priority") {
          return dayData.priority.map((e: PriorityItem, idx: number) => `${idx + 1}. ${e.project}${assigneesSuffix(e)}`)
        }
        return []
      }

      const rows = weekTableRows.map((row, rowIndex) => {
        const cells = commonWeekISOs.map((iso) => renderCellLines(row.id as CommonType, iso).join("\n"))
        return [String(rowIndex + 1), row.label.toUpperCase(), ...cells]
      })

      return {
        title: `COMMON VIEW - GANE TASKS${weekTitleRange ? ` (${weekTitleRange})` : ""}`,
        columns,
        rows,
      }
    }, [commonGaRowsByDay, commonWeekISOs, tableDataByDay, weekTableRows, weekTitleRange])

    const repeatedTaskFirstDateByRow = React.useMemo(() => {
      const entriesForRepeatCheck = (rowId: CommonType, iso: string): Array<{ taskId?: string | null; task_id?: string | null }> => {
        if (rowId === "det_ga") return commonGaRowsByDay[iso]?.detGa || []
        if (rowId === "bz") return commonGaRowsByDay[iso]?.bz || []

        const dayData = tableDataByDay?.[iso]
        if (!dayData) return []
        if (rowId === "blocked") return dayData.blocked
        if (rowId === "oneH") return dayData.oneH
        if (rowId === "r1") return dayData.r1
        if (rowId === "personal") return dayData.personal
        return []
      }

      const firstDateByRow = new Map<CommonType, Map<string, string>>()
      for (const row of weekTableRows) {
        const rowId = row.id as CommonType
        firstDateByRow.set(
          rowId,
          buildRepeatedTaskFirstDateMap(commonWeekISOs, (iso) => entriesForRepeatCheck(rowId, iso))
        )
      }
      return firstDateByRow
    }, [commonGaRowsByDay, commonWeekISOs, tableDataByDay, weekTableRows])

    const repeatedTaskClassName = (
      rowId: CommonType,
      entry: { taskId?: string | null; task_id?: string | null },
      dateIso: string
    ) => {
      const firstDateByTaskId = repeatedTaskFirstDateByRow.get(rowId)
      return firstDateByTaskId && isRepeatedTaskInstance(entry, dateIso, firstDateByTaskId)
        ? "repeat-task-muted"
        : ""
    }

    const renderCellContent = (rowId: CommonType, iso: string) => {
      const dayData = tableDataByDay?.[iso]
      if (!dayData) return null
      if (rowId === "det_ga") {
        const combined = commonGaRowsByDay[iso]?.detGa || []
        if (!combined.length) return null
        return combined.map((entry, idx) => (
          <div
            key={`${entry.kind}-${entry.templateId || entry.taskId || idx}`}
            className={["week-table-entry", repeatedTaskClassName(rowId, entry, iso)].filter(Boolean).join(" ")}
          >
            <span>{idx + 1}. {commonPrintTitleLine(entry.title)}</span>
          </div>
        ))
      }
      const renderBzContent = () => {
        const bzEntries = commonGaRowsByDay[iso]?.bz || []
        if (!bzEntries.length) return null

        return bzEntries.map((e: BzItem, idx: number) => (
          <div
            key={`bz-${e.templateId || e.taskId || idx}`}
            className={["week-table-entry", repeatedTaskClassName("bz", e, iso)].filter(Boolean).join(" ")}
          >
            <span>
              {idx + 1}. {commonPrintTitleLine(`${formatBzTimeDisplay(e.time)} ${e.title}`.trim())}
              {e.bzWithLabel ? ` - BZ: ${e.bzWithLabel}` : ""}
            </span>
            {e.assignees && e.assignees.length ? (
              <div className="week-table-avatars">
                {e.assignees.map((name: string) => (
                  <span key={`${e.title}-${name}`} className="week-table-avatar" title={name}>
                    {commonViewInitials(name)}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        ))
      }
      const entries =
        rowId === "late"
          ? dayData.late
          : rowId === "absent"
            ? dayData.absent
            : rowId === "leave"
              ? dayData.leave
              : rowId === "blocked"
                ? dayData.blocked
                : rowId === "oneH"
                  ? dayData.oneH
                  : rowId === "r1"
                    ? dayData.r1
                    : rowId === "personal"
                      ? dayData.personal
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

      if (rowId === "bz") {
        return renderBzContent()
      }
      if (!entries.length) return null

      if (rowId === "late") {
        return dayData.late.map((e: LateItem, idx: number) => (
          <div key={idx} className="week-table-entry">
            <span>{idx + 1}. {e.start || "08:00"}-{e.until}</span>
            <div className="week-table-avatars">
              {entryAssignees(e).map((name: string) => (
                <span key={`${e.start}-${name}`} className="week-table-avatar" title={name}>
                  {commonViewInitials(name)}
                </span>
              ))}
            </div>
          </div>
        ))
      }
      if (rowId === "absent") {
        return dayData.absent.map((e: AbsentItem, idx: number) => (
          <div key={idx} className="week-table-entry">
            <span>{idx + 1}. {e.from} - {e.to}</span>
            <div className="week-table-avatars">
              {entryAssignees(e).map((name: string) => (
                <span key={`${e.from}-${name}`} className="week-table-avatar" title={name}>
                  {commonViewInitials(name)}
                </span>
              ))}
            </div>
          </div>
        ))
      }
      if (rowId === "leave") {
        return dayData.leave.map((e: LeaveItem, idx: number) => {
          const isAllUsers = Boolean(e.isAllUsers || e.person === ALL_USERS_INITIALS)
          const timeLabel = e.fullDay ? "08:00-16:30" : `${e.from}-${e.to}`
          const noteLabel = e.note ? ` - ${e.note}` : ""
          return (
            <div key={idx} className="week-table-entry">
              <span>
                {idx + 1}. {isAllUsers ? `${timeLabel} ALL` : timeLabel}
                {noteLabel}
              </span>
              {!isAllUsers ? (
                <div className="week-table-avatars">
                  {entryAssignees(e).map((name: string) => (
                    <span key={`${e.from}-${name}`} className="week-table-avatar" title={name}>
                      {commonViewInitials(name)}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          )
        })
      }
      if (rowId === "blocked") {
        return dayData.blocked.map((e: BlockedItem, idx: number) => (
          <div
            key={idx}
            className={["week-table-entry", repeatedTaskClassName(rowId, e, iso)].filter(Boolean).join(" ")}
          >
            <span>
              {idx + 1}. <span className="period-indicator">{getCommonTaskPeriodLabel(e.finishPeriod)}</span> {commonPrintTitleLine(e.title)}
            </span>
            <div className="week-table-avatars">
              {entryAssignees(e).map((name: string) => (
                <span key={`${e.title}-${name}`} className="week-table-avatar" title={name}>
                  {commonViewInitials(name)}
                </span>
              ))}
            </div>
          </div>
        ))
      }
      if (rowId === "problem" || rowId === "feedback") {
        return (rowId === "problem" ? dayData.problems : dayData.feedback).map((e: ProblemItem | FeedbackItem, idx: number) => (
          <div key={idx} className="week-table-entry">
            <span className={rowId === "feedback" ? "feedback-print-clamp" : undefined}>
              {idx + 1}. {e.title}
              {` - ${e.createdDate ? formatDateHuman(e.createdDate) : formatDateHuman(e.date)}`}
              {e.note ? ` - ${e.note}` : ""}
            </span>
            <div className="week-table-avatars">
              {entryAssignees(e).map((name: string) => (
                <span key={`${e.title}-${name}`} className="week-table-avatar" title={name}>
                  {commonViewInitials(name)}
                </span>
              ))}
            </div>
          </div>
        ))
      }
      if (rowId === "oneH" || rowId === "r1") {
        return mergeTaskEntriesByVisibleTitle(entries as (OneHItem | R1Item)[]).map((e: any, idx: number) => (
          <div
            key={idx}
            className={["week-table-entry", repeatedTaskClassName(rowId, e, iso)].filter(Boolean).join(" ")}
          >
            <span>
              {idx + 1}. <span className="period-indicator">{getCommonTaskPeriodLabel(e.finishPeriod)}</span> {commonPrintTitleLine(e.title)}
            </span>
            <div className="week-table-avatars">
              {entryAssignees(e).map((name: string) => (
                <span key={`${e.title}-${name}`} className="week-table-avatar" title={name}>
                  {commonViewInitials(name)}
                </span>
              ))}
            </div>
          </div>
        ))
      }
      if (rowId === "personal") {
        return mergeTaskEntriesByVisibleTitle(entries as PersonalItem[]).map((e: PersonalItem, idx: number) => (
          <div
            key={idx}
            className={["week-table-entry", repeatedTaskClassName(rowId, e, iso)].filter(Boolean).join(" ")}
          >
            <span>
              {idx + 1}. <span className="period-indicator">{getCommonTaskPeriodLabel(e.finishPeriod)}</span> {commonPrintTitleLine(e.title)}
            </span>
            <div className="week-table-avatars">
              {entryAssignees(e).map((name: string) => (
                <span key={`${e.title}-${name}`} className="week-table-avatar" title={name}>
                  {commonViewInitials(name)}
                </span>
              ))}
            </div>
          </div>
        ))
      }
      if (rowId === "external") {
        return (entries as ExternalItem[]).map((e, idx: number) => (
          <div
            key={idx}
            className={[
              "week-table-entry",
              isNonDailyWeeklyRecurrence(e.recurrenceType ?? e.recurrence_type) ? "external-non-daily-weekly" : "",
            ]
              .filter(Boolean)
              .join(" ")}
          >
            <span>{idx + 1}. {`${commonPrintTitleLine(e.title)} ${formatTimeLabel(e.time)}`.trim()}</span>
            <div className="week-table-avatars">
              {entryAssignees(e).map((name: string) => (
                <span key={`${e.title}-${name}`} className="week-table-avatar" title={name}>
                  {commonViewInitials(name)}
                </span>
              ))}
            </div>
          </div>
        ))
      }
      if (rowId === "internal") {
        return dayData.internal.map((e: InternalItem, idx: number) => (
          <div key={idx} className="week-table-entry">
            <span>{idx + 1}. {`${commonPrintTitleLine(e.title)} ${formatTimeLabel(e.time)}`.trim()}</span>
            <div className="week-table-avatars">
              {entryAssignees(e).map((name: string) => (
                <span key={`${e.title}-${name}`} className="week-table-avatar" title={name}>
                  {commonViewInitials(name)}
                </span>
              ))}
            </div>
          </div>
        ))
      }
      if (rowId === "priority") {
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
                      {commonViewInitials(name)}
                    </span>
                  ))}
                </div>
              </div>
            ))}
            {groupIdx < groupKeys.length - 1 ? <div className="week-table-prjk-divider" /> : null}
          </React.Fragment>
        ))
      }
      return null
    }

    const renderAssignedBadges = (badges: AllTasksAssigneeBadge[]) => {
      if (!badges.length) return <span className="text-slate-500">-</span>
      return (
        <div className="flex flex-wrap items-center gap-1">
          {badges.map((item) => (
            <div
              key={item.userId}
              className="h-6 w-6 rounded-full bg-slate-100 text-[9px] font-semibold text-slate-600 flex items-center justify-center"
              title={item.label}
            >
              {item.value}
            </div>
          ))}
        </div>
      )
    }

    const renderAllTasksTable = (
      rows: typeof filteredAllTasksRows,
      options?: { accent?: boolean; emptyLabel?: string }
    ) => {
      const headers = [
        "NR",
        "LL",
        "START DATE",
        "DUE DATE",
        "AM/PM",
        "TITLE",
        "FREQUENCY",
        "KOHA BZ",
        "BZ ME",
        "STATUS",
        "PRIORITY",
        "KOMENT",
        "ACTIONS",
      ]
      const sortByTimeThenUser = (groupRows: typeof rows) => {
        const userOrder = new Map<string, number>()
        let nextUserOrder = 0

        // Preserve the section's existing user order while bringing every task
        // for that user together. Multi-user tasks join the first matching group.
        for (const row of groupRows) {
          for (const assignee of row.assigned) {
            if (userOrder.has(assignee.userId)) continue
            userOrder.set(assignee.userId, nextUserOrder)
            nextUserOrder += 1
          }
        }

        return groupRows
          .map((row, originalIndex) => ({ row, originalIndex }))
          .sort((a, b) => {
            const aFast = Boolean(a.row.isFastTask)
            const bFast = Boolean(b.row.isFastTask)
            if (aFast !== bFast) return aFast ? -1 : 1

            const aDone = (a.row.status || "").toUpperCase() === "DONE" ? 1 : 0
            const bDone = (b.row.status || "").toUpperCase() === "DONE" ? 1 : 0
            if (aDone !== bDone) return aDone - bDone

            const aMinutes = parseTimeToMinutes(a.row.kohaBz) ?? Number.MAX_SAFE_INTEGER
            const bMinutes = parseTimeToMinutes(b.row.kohaBz) ?? Number.MAX_SAFE_INTEGER
            if (aMinutes !== bMinutes) return aMinutes - bMinutes

            const aUserOrder = a.row.assigned.reduce(
              (lowest, assignee) => Math.min(lowest, userOrder.get(assignee.userId) ?? Number.MAX_SAFE_INTEGER),
              Number.MAX_SAFE_INTEGER
            )
            const bUserOrder = b.row.assigned.reduce(
              (lowest, assignee) => Math.min(lowest, userOrder.get(assignee.userId) ?? Number.MAX_SAFE_INTEGER),
              Number.MAX_SAFE_INTEGER
            )
            if (aUserOrder !== bUserOrder) return aUserOrder - bUserOrder

            return a.originalIndex - b.originalIndex
          })
          .map(({ row }) => row)
      }
      let nextRowNumber = 1
      const rowGroups = [
        {
          key: "gane",
          label: "GA Tasks",
          rows: sortByTimeThenUser(
            rows.filter((row) => row.isGaneRealAssignee || row.needsGaneConfirmation)
          ),
        },
        {
          key: "bz-me",
          label: "BZ ME GA Tasks",
          rows: sortByTimeThenUser(
            rows.filter((row) => !row.isGaneRealAssignee && !row.needsGaneConfirmation)
          ),
        },
      ]
        .filter((group) => group.rows.length > 0)
        .map((group) => {
          const startNumber = nextRowNumber
          nextRowNumber += group.rows.length
          return { ...group, startNumber }
        })
      return (
          <Table
        containerClassName="all-tasks-table-scroll mt-3 rounded-lg bg-white"
        className="all-tasks-table min-w-[820px] text-[10px] sm:min-w-[1020px]"
      >
        <TableHeader>
          <TableRow className="bg-slate-50">
            {headers.map((label) => (
              <TableHead
                key={label}
                className={`h-8 border-r border-slate-200 px-1.5 text-[10px] font-bold uppercase tracking-wide text-slate-600 last:border-r-0 ${
                  label === "NR"
                    ? "w-[26px] px-1 text-center"
                    : label === "LL"
                      ? "w-[30px] px-1 text-center"
                    : label === "START DATE" || label === "DUE DATE"
                        ? "w-[42px] max-w-[42px] px-0.5 sm:w-[74px] sm:max-w-none sm:px-1"
                        : label === "AM/PM"
                          ? "w-[54px]"
                          : label === "TITLE"
                            ? "min-w-[160px] sm:min-w-[220px]"
                            : label === "FREQUENCY"
                              ? "w-[76px] px-1 text-center"
                              : label === "KOHA BZ"
                                ? "hidden w-[70px] sm:table-cell"
                                : label === "BZ ME"
                                  ? "min-w-[56px] max-w-[100px] px-1"
                                  : label === "STATUS"
                                    ? "w-[86px]"
                                    : label === "PRIORITY"
                                    ? "w-[70px]"
                                    : label === "KOMENT"
                                      ? "min-w-[120px]"
                                      : label === "ACTIONS"
                                        ? "w-[82px]"
                                        : ""
                }`}
              >
                {label}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length ? (
            rowGroups.map((group, groupIndex) => (
              <React.Fragment key={group.key}>
                <TableRow className={`bg-slate-100/80 hover:bg-slate-100 ${groupIndex > 0 ? "border-t-2 border-t-slate-300" : ""}`}>
                  <TableCell
                    colSpan={headers.length}
                    className="h-7 px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-slate-700"
                  >
                    <span>{group.label}</span>
                    <span className="ml-1.5 font-medium text-slate-500">({group.rows.length})</span>
                  </TableCell>
                </TableRow>
                {group.rows.map((row, index) => {
              const statusValue = TASK_STATUS_OPTIONS.includes(row.status as (typeof TASK_STATUS_OPTIONS)[number])
                ? row.status
                : "TODO"
              const statusLabel = reportStatusLabel(statusValue)
              const statusClass = weeklyPlanStatusBgClass(statusValue)
              const actionKey = `task:${row.taskId || "na"}`
              const isUpdating = Boolean(taskStatusUpdating[actionKey])
              const commentKey = `all-task:${row.taskId}`
              const previousValue =
                (row.taskId && row.taskId in sharedTaskComments ? sharedTaskComments[row.taskId] : row.comment) ?? ""
              const commentValue = commentKey ? (allTasksReportCommentEdits[commentKey] ?? previousValue) : ""
              const isSaving = commentKey ? Boolean(savingAllTasksReportComments[commentKey]) : false
              const isConfirmAction = Boolean(row.needsGaneConfirmation && statusValue === "WAITING_CONFIRMATION")
              const canMarkDone =
                statusValue !== "DONE" &&
                !row.isBzOnly &&
                (row.isGaneRealAssignee || isConfirmAction)
              const actionLabel = isConfirmAction ? "Confirm" : "Done"
              const rowTask = tasks.find((task) => task.id === row.taskId) || null
              return (
                <TableRow key={row.id}>
                  <TableCell className="w-[26px] border-r border-slate-200 px-1 py-1 text-center align-middle font-semibold text-slate-700 last:border-r-0">{group.startNumber + index}</TableCell>
                  <TableCell className="w-[30px] border-r border-slate-200 px-1 py-1 text-center align-middle font-semibold last:border-r-0">{row.ll}</TableCell>
                  <TableCell className="w-[42px] max-w-[42px] border-r border-slate-200 px-0.5 py-1 align-middle last:border-r-0 sm:w-[74px] sm:max-w-none sm:px-1">
                    {row.startDateLabel}
                  </TableCell>
                  <TableCell className="w-[42px] max-w-[42px] border-r border-slate-200 px-0.5 py-1 align-middle last:border-r-0 sm:w-[74px] sm:max-w-none sm:px-1">
                    <div className="flex flex-col items-start gap-0.5 leading-none">
                      <span>{row.dateLabel}</span>
                      {row.isLateSystemTask ? (
                        <Badge
                          variant="destructive"
                          className="w-fit rounded-sm px-1 py-0 text-[8px] uppercase leading-tight sm:px-1.5 sm:text-[10px]"
                        >
                          {row.lateDays ? `Late ${row.lateDays}` : "Late"}
                        </Badge>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell className="w-[54px] border-r border-slate-200 px-1.5 py-1 align-middle last:border-r-0">{row.period || "-"}</TableCell>
                  <TableCell
                    className="min-w-[160px] border-r border-slate-200 px-1.5 py-1 align-middle whitespace-normal break-words font-medium text-slate-800 last:border-r-0 sm:min-w-[220px]"
                    title={plainCommonMarkedTitle(row.title)}
                  >
                    <div className="flex items-start gap-1.5">
                      {row.kohaBz !== "-" ? (
                        <span className="inline-flex shrink-0 rounded-sm bg-slate-100 px-1 py-0.5 text-[9px] font-semibold text-slate-600 sm:hidden">
                          {row.kohaBz}
                        </span>
                      ) : null}
                      <TaskOneHMarker marker={row.oneHMarker} />
                      <span>{renderCommonMarkedTitle(row.title)}</span>
                    </div>
                  </TableCell>
                  <TableCell className="w-[76px] border-r border-slate-200 px-1 py-1 text-center align-middle last:border-r-0">
                    {row.systemFrequencyDisplayLabel ? (
                      <span
                        className="inline-flex h-5 items-center justify-center rounded-full border border-slate-200 px-2 text-[10px] font-semibold text-slate-600"
                        title={systemFrequencyTitle(row.systemFrequency)}
                      >
                        {row.systemFrequencyDisplayLabel}
                      </span>
                    ) : null}
                  </TableCell>
                  <TableCell className="hidden w-[70px] border-r border-slate-200 px-1.5 py-1 align-middle last:border-r-0 sm:table-cell">
                    {row.kohaBz}
                  </TableCell>
                  <TableCell className="min-w-[56px] max-w-[100px] border-r border-slate-200 px-1 py-1 align-middle last:border-r-0">
                    {renderAssignedBadges(row.assigned)}
                  </TableCell>
                  <TableCell className={`w-[86px] border-r border-slate-200 px-1.5 py-1 align-middle uppercase last:border-r-0 ${statusClass}`}>
                    {statusLabel}
                  </TableCell>
                  <TableCell className="w-[70px] border-r border-slate-200 px-1.5 py-1 align-middle uppercase last:border-r-0">{row.priority}</TableCell>
                  <TableCell className="min-w-[120px] border-r border-slate-200 px-1.5 py-1 align-middle last:border-r-0">
                    <div className="flex items-center gap-1">
                      <input
                        type="text"
                        aria-label="Koment"
                        className="h-4 w-full min-w-0 border-b border-slate-300 bg-transparent"
                        value={commentValue}
                        onChange={(e) => {
                          if (!commentKey) return
                          setAllTasksReportCommentEdits((prev) => ({ ...prev, [commentKey]: e.target.value }))
                        }}
                        onBlur={(e) => {
                          const nextValue = e.target.value
                          void saveAllTasksReportTaskComment(row.taskId, nextValue, previousValue, commentKey)
                        }}
                        disabled={!commentKey}
                      />
                      <span className="text-[10px] text-slate-400">{isSaving ? "Saving" : ""}</span>
                    </div>
                  </TableCell>
                  <TableCell className="w-[82px] px-1.5 py-1 align-middle">
                    <div className="flex items-center gap-1">
                      {canMarkDone ? (
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-6 px-2 text-[10px]"
                          disabled={isUpdating}
                          onMouseDown={(event) => event.preventDefault()}
                          onClick={() => {
                            if (!rowTask) return
                            void completeTaskFromAllTasksReport(
                              rowTask,
                              commentValue,
                              previousValue,
                              commentKey,
                              isConfirmAction
                            )
                          }}
                        >
                          {isUpdating ? "Updating..." : actionLabel}
                        </Button>
                      ) : statusValue === "DONE" ? (
                        <span className="text-xs text-emerald-700">Done</span>
                      ) : row.isBzOnly ? (
                        <span className="text-[10px] text-amber-700">You&apos;re not assigned</span>
                      ) : !row.isGaneRealAssignee ? (
                        <span className="text-[10px] text-slate-500">You&apos;re not assigned</span>
                      ) : null}
                      {rowTask ? (
                        <Button
                          variant="outline"
                          size="icon"
                          className="h-5 w-5 border-slate-200 text-slate-500 hover:border-blue-200 hover:text-blue-600"
                          title="Edit task dates"
                          aria-label={`Edit ${plainCommonMarkedTitle(row.title)}`}
                          onClick={() => startEditTask(rowTask)}
                        >
                          <Pencil className="h-3 w-3" />
                        </Button>
                      ) : null}
                    </div>
                  </TableCell>
                </TableRow>
              )
                })}
              </React.Fragment>
            ))
          ) : (
            <TableRow>
              <TableCell colSpan={headers.length} className="py-8 text-center text-sm text-muted-foreground">
                {options?.emptyLabel || "No tasks available."}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      )
    }

    return (
      <div className="admin-week-table flex flex-col">
        <div className="print-section order-1" data-print-section="all-tasks">
          <AdminTasksSection
            sectionId="all-tasks"
            isCollapsed={collapsedAdminSections["all-tasks"]}
            onToggle={toggleAdminSection}
            title="ALL TASKS"
            description=""
            headerClassName="px-3 sm:px-6"
            contentClassName="px-2"
            actions={
              <div className="flex items-center gap-2 print:hidden">
                <Button variant="outline" size="sm" onClick={() => setFastTaskOpen(true)}>
                  + Add Fast Task
                </Button>
                <Button variant="outline" size="sm" onClick={() => handleSectionPrint("all-tasks")}>
                  Print
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void exportAllTasks()}
                  disabled={exportingAllTasks}
                >
                  {exportingAllTasks ? "Exporting..." : "Export"}
                </Button>
              </div>
            }
          >
          <div className="flex flex-col gap-2 text-xs text-slate-500 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
            <div>Total: {filteredAllTasksRows.length}</div>
            <div className="grid w-full grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-2 sm:hidden">
              <div className="col-span-2 flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant={allTasksDateFrom === todayIso && allTasksDateTo === todayIso ? "default" : "outline"}
                  size="sm"
                  className="h-8 px-3"
                  onClick={() => setAllTasksQuickRange(todayIso, todayIso)}
                >
                  Sot
                </Button>
                <Button
                  type="button"
                  variant={allTasksDateFrom === allTasksThisWeekFrom && allTasksDateTo === allTasksThisWeekTo ? "default" : "outline"}
                  size="sm"
                  className="h-8 px-3"
                  onClick={() => setAllTasksQuickRange(allTasksThisWeekFrom, allTasksThisWeekTo)}
                >
                  This Week
                </Button>
                <Button
                  type="button"
                  variant={allTasksDateFrom === allTasksNextWeekFrom && allTasksDateTo === allTasksNextWeekTo ? "default" : "outline"}
                  size="sm"
                  className="h-8 px-3"
                  onClick={() => setAllTasksQuickRange(allTasksNextWeekFrom, allTasksNextWeekTo)}
                >
                  Next Week
                </Button>
                <Button
                  type="button"
                  variant={!allTasksDateFrom && !allTasksDateTo ? "default" : "outline"}
                  size="sm"
                  className="h-8 px-3"
                  onClick={() => setAllTasksQuickRange("", "")}
                >
                  All dates
                </Button>
              </div>
              <span>From</span>
              <Input
                type="date"
                className="h-8 w-full min-w-0 text-xs"
                value={allTasksDateFrom || ""}
                onChange={(event) => setAllTasksDateFrom(event.target.value)}
              />
              <span>To</span>
              <Input
                type="date"
                className="h-8 w-full min-w-0 text-xs"
                value={allTasksDateTo || ""}
                onChange={(event) => setAllTasksDateTo(event.target.value)}
              />
            </div>
            <div className="hidden sm:flex sm:items-center sm:gap-2">
              <span>Date</span>
              <Button
                type="button"
                variant={allTasksDateFrom === todayIso && allTasksDateTo === todayIso ? "default" : "outline"}
                size="sm"
                className="h-8 px-3"
                onClick={() => setAllTasksQuickRange(todayIso, todayIso)}
              >
                Sot
              </Button>
              <Button
                type="button"
                variant={allTasksDateFrom === allTasksThisWeekFrom && allTasksDateTo === allTasksThisWeekTo ? "default" : "outline"}
                size="sm"
                className="h-8 px-3"
                onClick={() => setAllTasksQuickRange(allTasksThisWeekFrom, allTasksThisWeekTo)}
              >
                This Week
              </Button>
              <Button
                type="button"
                variant={allTasksDateFrom === allTasksNextWeekFrom && allTasksDateTo === allTasksNextWeekTo ? "default" : "outline"}
                size="sm"
                className="h-8 px-3"
                onClick={() => setAllTasksQuickRange(allTasksNextWeekFrom, allTasksNextWeekTo)}
              >
                Next Week
              </Button>
              <Button
                type="button"
                variant={!allTasksDateFrom && !allTasksDateTo ? "default" : "outline"}
                size="sm"
                className="h-8 px-3"
                onClick={() => setAllTasksQuickRange("", "")}
              >
                All
              </Button>
              <span>From</span>
              <Input
                type="date"
                className="h-8 w-[160px] text-xs"
                value={allTasksDateFrom || ""}
                onChange={(event) => setAllTasksDateFrom(event.target.value)}
              />
              <span>To</span>
              <Input
                type="date"
                className="h-8 w-[160px] text-xs"
                value={allTasksDateTo || ""}
                onChange={(event) => setAllTasksDateTo(event.target.value)}
              />
            </div>
          </div>
          <div className="mt-4">
            {renderAllTasksTable(filteredAllTasksRows, {
              emptyLabel: "No tasks available.",
            })}
          </div>
          </AdminTasksSection>
        </div>
        <div className="order-3 print:hidden">
          <AdminTasksSection
            sectionId="one-h-print"
            isCollapsed={collapsedAdminSections["one-h-print"]}
            onToggle={toggleAdminSection}
            title="1H SHTYPI"
            description="Generate the same Today or Tomorrow report used by 1H SHTYPI."
          >
            <EmbeddedPrintReportGenerator />
          </AdminTasksSection>
        </div>
        <div className="print-section order-4" data-print-section="common">
          <div className="print-only week-table-view">
            <div className="print-page">
              <div className="print-header">
                <div />
                <div className="print-title">COMMON VIEW - WEEK PLAN</div>
                <div className="print-datetime">{formatDateTimeDMY(printedAt)}</div>
              </div>
              <table className="week-table">
                <thead>
                <tr>
                  <th style={{ width: "40px" }}>NR</th>
                  <th style={{ width: "110px" }}>LLOJI</th>
                  {commonWeekISOs.map((iso) => {
                    const d = fromISODate(iso)
                    const dayCode = getDayCode(d)
                    return (
                      <th key={iso} colSpan={1} className="week-table-date-header">
                        <div>{dayCode} = {formatDateHuman(iso)}</div>
                      </th>
                    )
                  })}
                </tr>
              </thead>
                <tbody>
                  {weekTableRows.map((row, rowIndex) => {
                    const rowLabel = row.label.toUpperCase()
                    const weekRowClass =
                      row.id === "late"
                        ? "delay"
                        : row.id === "absent"
                          ? "absence"
                          : row.id === "oneH"
                            ? "oneh"
                            : row.id
                    return (
                      <tr key={`print-${row.id}`} className={`week-table-row ${weekRowClass}`}>
                        <td className="week-table-number">{rowIndex + 1}</td>
                        <td className="week-table-label">{rowLabel}</td>
                        {commonWeekISOs.map((iso) => {
                          const content = renderCellContent(row.id as CommonType, iso)
                          return (
                            <td key={`print-${row.id}-${iso}`} className="week-table-cell">
                              {content ? (
                                <div className="week-table-entries">{content}</div>
                              ) : (
                                <span className="week-table-empty">-</span>
                              )}
                            </td>
                          )
                        })}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              <div className="print-footer">
                <span />
                <div className="print-page-count">1/{printTotalPages}</div>
                <div className="print-initials">PUNOI: {printInitials}</div>
              </div>
            </div>
          </div>
          <div className="print:hidden">
            <AdminTasksSection
              sectionId="common"
              isCollapsed={collapsedAdminSections["common"]}
              onToggle={toggleAdminSection}
              title={`COMMON VIEW - GANE TASKS${weekTitleRange ? ` (${weekTitleRange})` : ""}`}
              description=""
              actions={
                <div className="flex flex-wrap items-center gap-2 print:hidden">
                  <Button
                    variant={toISODate(commonWeekStart) === thisCommonWeekIso ? "default" : "outline"}
                    size="sm"
                    onClick={() => setAllTasksQuickRange(allTasksThisWeekFrom, allTasksThisWeekTo)}
                  >
                    This Week
                  </Button>
                  <Button
                    variant={toISODate(commonWeekStart) === nextCommonWeekIso ? "default" : "outline"}
                    size="sm"
                    onClick={() => setAllTasksQuickRange(allTasksNextWeekFrom, allTasksNextWeekTo)}
                  >
                    Next Week
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => handleSectionPrint("common")}>
                    Print
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void exportCommonView(exportPayload)}
                    disabled={exportingCommonView}
                  >
                    {exportingCommonView ? "Exporting..." : "Export"}
                  </Button>
                </div>
              }
            >
              <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500 print:hidden">
                {commonLoading ? <span>Loading...</span> : null}
                {commonError ? <span className="text-red-600">{commonError}</span> : null}
                {gaSystemLoading ? <span>Loading DET GA...</span> : null}
                {gaSystemError ? <span className="text-red-600">{gaSystemError}</span> : null}
              </div>
              <div className="mt-3 overflow-x-auto print:hidden">
                <table className="week-table">
                  <thead>
                  <tr>
                    <th style={{ width: "40px" }}>NR</th>
                    <th style={{ width: "110px" }}>LLOJI</th>
                    {commonWeekISOs.map((iso) => {
                      const d = fromISODate(iso)
                      const dayCode = getDayCode(d)
                      return (
                        <th key={iso} colSpan={1} className="week-table-date-header">
                          <div>{dayCode} = {formatDateHuman(iso)}</div>
                        </th>
                      )
                    })}
                  </tr>
                </thead>
                  <tbody>
                    {weekTableRows.map((row, rowIndex) => {
                      const rowLabel = row.label.toUpperCase()
                      const weekRowClass =
                        row.id === "late"
                          ? "delay"
                          : row.id === "absent"
                            ? "absence"
                            : row.id === "oneH"
                              ? "oneh"
                              : row.id
                      return (
                        <tr key={row.id} className={`week-table-row ${weekRowClass}`}>
                          <td className="week-table-number">{rowIndex + 1}</td>
                          <td className="week-table-label">{rowLabel}</td>
                          {commonWeekISOs.map((iso) => {
                            const content = renderCellContent(row.id as CommonType, iso)
                            return (
                              <td key={iso} className="week-table-cell">
                                {content ? (
                                  <div className="week-table-entries">{content}</div>
                                ) : (
                                  <span className="week-table-empty">-</span>
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
            </AdminTasksSection>
          </div>
        </div>
        <div className={cn("print-section", gaTimeTableFirst ? "order-first" : "order-2")} data-print-section="ga-time">
          <div className="print-only">
            <div className="print-page">
              <div className="print-header">
                <div />
                <div className="print-title">GA TIME TABLE{weekTitleRange ? ` (${weekTitleRange})` : ""}</div>
                <div className="print-datetime">{formatDateTimeDMY(printedAt)}</div>
              </div>
              <div className="ga-time-table">
                <table className="ga-time-table-table">
                  <colgroup>
                    <col className="ga-time-nr-column" />
                    <col className="ga-time-time-column" />
                    <col className="ga-time-comment-column" />
                    {commonWeekISOs.map((iso) => <col key={`ga-print-col-${iso}`} className="ga-time-day-column" />)}
                    <col className="ga-time-comment-column" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th className="ga-time-header ga-time-nr">NR</th>
                      <th className="ga-time-header ga-time-time">TIME</th>
                      <th className="ga-time-header ga-time-comment">KOMENT</th>
                      {commonWeekISOs.map((iso) => {
                        const d = fromISODate(iso)
                        const dayCode = getDayCode(d)
                        return (
                          <th key={`ga-print-${iso}`} className="ga-time-header">
                            <div>{dayCode} = {formatDateHuman(iso)}</div>
                          </th>
                        )
                      })}
                      <th className="ga-time-header ga-time-comment">KOMENT</th>
                    </tr>
                  </thead>
                  <tbody>
                    {gaTimeRows.map((slot) => (
                      <tr
                        key={`ga-print-${slot.start}`}
                        className={
                          slot.isSpecial
                            ? "ga-time-row ga-time-row-custom"
                            : slot.start === "08:00"
                            ? "ga-time-row ga-time-row-secondary"
                            : slot.start < "14:00"
                              ? "ga-time-row ga-time-row-primary"
                              : "ga-time-row ga-time-row-secondary"
                        }
                      >
                        <td className="ga-time-slot-label ga-time-nr">{slot.nrLabel}</td>
                        {!slot.isSpecial ? (
                          <td className="ga-time-slot-label ga-time-time">
                            {slot.label ? (
                              <span className="ga-time-range">
                                <span>{slot.start}</span>
                                <span>{slot.end}</span>
                              </span>
                            ) : "\u00A0"}
                          </td>
                        ) : null}
                        <td
                          className={`ga-time-cell ga-time-comment${slot.isSpecial ? " ga-time-special-comment" : ""}`}
                          colSpan={slot.isSpecial ? 2 : undefined}
                        >
                          <div className="ga-time-comment-list">
                            {gaTimeCommentsForRow(slot).map((comment) => (
                              <div
                                key={`ga-print-comment-${slot.start}-${comment.id}`}
                                className="ga-time-comment-text"
                                style={gaTimeEntryStyle({
                                  background_color: comment.backgroundColor,
                                  text_color: comment.textColor,
                                  is_bold: comment.isBold,
                                  is_italic: comment.isItalic,
                                })}
                              >
                                <GaTimeRichTextContent value={comment.content} />
                              </div>
                            ))}
                          </div>
                        </td>
                        {commonWeekISOs.map((iso) => {
                          const dayOfWeek = toDayOfWeek(iso)
                          const cellKey = `${dayOfWeek}|${slot.start}`
                          const entries = gaTimeEntriesByCell.get(cellKey) || []
                          const meetings = gaMeetingsByCell.get(cellKey) || []
                          return (
                            <td key={`ga-print-${cellKey}`} className="ga-time-cell">
                              <div className="ga-time-cell-content">
                                {meetings.map(({ kind, meeting }, index) => (
                                  <div
                                    key={`ga-print-meeting-${kind}-${meeting.id || `${meeting.date}-${meeting.time}-${index}`}`}
                                    className={`ga-time-entry ${
                                      kind === "internal"
                                        ? internalMeetingLegendTone(meeting)
                                        : meetingLegendTone({
                                            categories: meeting.calendarCategories ?? meeting.calendar_categories,
                                            recurrenceType: meeting.recurrenceType ?? meeting.recurrence_type,
                                            meetingType: "external",
                                            calendarImported: Boolean(
                                              meeting.calendarImported ??
                                                meeting.calendar_imported ??
                                                meeting.microsoft_event_id
                                            ),
                                          })
                                    }`}
                                  >
                                    <span className="ga-time-meeting-time">{formatTimeLabel(meeting.time)}</span>
                                    <span><strong>{kind === "internal" ? "TAK INT:" : "TAK EXT:"}</strong> {meeting.title}</span>
                                  </div>
                                ))}
                                {entries.map((entry) => (
                                    <div
                                      key={`ga-print-${entry.id}`}
                                      className="ga-time-entry"
                                      style={gaTimeEntryStyle(entry)}
                                    >
                                      <GaTimeEntryContent entry={entry} />
                                    </div>
                                  ))}
                                {!entries.length && !meetings.length && !slot.isSpecial ? (
                                  <span className="week-table-empty">-</span>
                                ) : null}
                              </div>
                            </td>
                          )
                        })}
                        <td className="ga-time-cell ga-time-comment">
                          <div className="ga-time-comment-list">
                            {gaTimeCommentsForRow(slot, "end").map((comment) => (
                              <div
                                key={`ga-print-end-comment-${slot.start}-${comment.id}`}
                                className="ga-time-comment-text"
                                style={gaTimeEntryStyle({
                                  background_color: comment.backgroundColor,
                                  text_color: comment.textColor,
                                  is_bold: comment.isBold,
                                  is_italic: comment.isItalic,
                                })}
                              >
                                <GaTimeRichTextContent value={comment.content} />
                              </div>
                            ))}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
          <div id="ga-time-table" className="scroll-mt-4 print:hidden">
          <AdminTasksSection
            sectionId="ga-time"
            isCollapsed={collapsedAdminSections["ga-time"]}
            onToggle={toggleAdminSection}
            title={`GA TIME TABLE${weekTitleRange ? ` (${weekTitleRange})` : ""}`}
            description=""
            actions={
              <div className="flex flex-wrap items-center gap-2 print:hidden">
                <Button
                  variant={toISODate(commonWeekStart) === thisCommonWeekIso ? "default" : "outline"}
                  size="sm"
                  onClick={() => setAllTasksQuickRange(allTasksThisWeekFrom, allTasksThisWeekTo)}
                >
                  This Week
                </Button>
                <Button
                  variant={toISODate(commonWeekStart) === nextCommonWeekIso ? "default" : "outline"}
                  size="sm"
                  onClick={() => setAllTasksQuickRange(allTasksNextWeekFrom, allTasksNextWeekTo)}
                >
                  Next Week
                </Button>
                {canEditGaTimeSlots ? (
                  <>
                    <Button variant="outline" size="sm" onClick={openGaIcloudDialog}>
                      iPhone Sync
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => void openGaCalendarDialog()}>
                      Apple Calendar
                    </Button>
                    <Button variant="outline" size="sm" onClick={openGaTimeRowsDialog}>
                      <Pencil className="mr-2 h-4 w-4" />
                      Times
                    </Button>
                  </>
                ) : null}
                <Button variant="outline" size="sm" onClick={() => handleSectionPrint("ga-time")}>
                  Print
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void exportGaTime()}
                  disabled={exportingGaTime}
                >
                  {exportingGaTime ? "Exporting..." : "Export"}
                </Button>
              </div>
            }
          >
          <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500">
            {gaTimeLoading ? <span>Loading GA time slots...</span> : null}
            {gaTimeError ? <span className="text-red-600">{gaTimeError}</span> : null}
          </div>
          {gaTimeCommentDragging && gaTimeCommentPointerPosition ? (() => {
            const sourceRow = gaTimeRows.find(
              (row) => row.start === gaTimeCommentDragging.rowStart && row.end === gaTimeCommentDragging.rowEnd
            )
            const sourceComment = sourceRow
              ? gaTimeCommentsForRow(sourceRow, gaTimeCommentDragging.column).find(
                  (comment) => comment.id === gaTimeCommentDragging.commentId
                )
              : null
            return sourceComment ? (
              <div
                className="pointer-events-none fixed z-[100] max-w-[260px] rounded-md border border-blue-400 px-3 py-2 text-xs shadow-xl"
                style={{
                  left: gaTimeCommentPointerPosition.x + 12,
                  top: gaTimeCommentPointerPosition.y + 12,
                  ...gaTimeEntryStyle({
                    background_color: sourceComment.backgroundColor,
                    text_color: sourceComment.textColor,
                    is_bold: sourceComment.isBold,
                    is_italic: sourceComment.isItalic,
                  }),
                }}
              >
                <GaTimeRichTextContent value={sourceComment.content} />
              </div>
            ) : null
          })() : null}
          <div className="mt-3 ga-time-table ga-time-table-scroll">
            <table className="ga-time-table-table ga-time-table-live">
              <colgroup>
                <col className="ga-time-nr-column" />
                <col className="ga-time-time-column" />
                <col className="ga-time-comment-column" />
                {commonWeekISOs.map((iso) => <col key={`ga-col-${iso}`} className="ga-time-day-column" />)}
                <col className="ga-time-comment-column" />
              </colgroup>
              <thead>
                <tr>
                  <th className="ga-time-header ga-time-nr">NR</th>
                  <th className="ga-time-header ga-time-time">TIME</th>
                  <th className="ga-time-header ga-time-comment">KOMENT</th>
                  {commonWeekISOs.map((iso) => {
                    const d = fromISODate(iso)
                    const dayCode = getDayCode(d)
                    return (
                      <th key={`ga-${iso}`} className="ga-time-header">
                        <div>{dayCode} = {formatDateHuman(iso)}</div>
                      </th>
                    )
                  })}
                  <th className="ga-time-header ga-time-comment">KOMENT</th>
                </tr>
              </thead>
              <tbody>
                {gaTimeRows.map((slot) => (
                  <tr key={slot.start} className={slot.isSpecial ? "ga-time-row-custom" : undefined}>
                    <td className="ga-time-slot-label ga-time-nr">{slot.nrLabel}</td>
                    <td className="ga-time-slot-label ga-time-time">
                      {!slot.isSpecial && slot.label ? (
                        <span className="ga-time-range">
                          <span>{slot.start}</span>
                          <span>{slot.end}</span>
                        </span>
                      ) : "\u00A0"}
                    </td>
                    {renderGaTimeCommentCell(slot, "start", Boolean(slot.isSpecial))}
                    {commonWeekISOs.map((iso) => {
                      const dayOfWeek = toDayOfWeek(iso)
                      const cellKey = `${dayOfWeek}|${slot.start}`
                      const entries = gaTimeEntriesByCell.get(cellKey) || []
                      const meetings = gaMeetingsByCell.get(cellKey) || []
                      return (
                        <td
                          key={`${cellKey}`}
                          className="ga-time-cell"
                          data-ga-slot-cell="true"
                          data-ga-day-of-week={dayOfWeek}
                          data-ga-start-time={slot.start}
                          data-ga-end-time={slot.end}
                          onDragOver={(event) => {
                            if (!canEditGaTimeSlots) return
                            event.preventDefault()
                            event.dataTransfer.dropEffect = "move"
                            if (gaTimeCommentDraggingRef.current) {
                              gaTimeCommentDropTargetRef.current = {
                                kind: "slot",
                                dayOfWeek,
                                startTime: slot.start,
                                endTime: slot.end,
                                beforeEntryId: null,
                              }
                              setGaTimeDropTarget((current) =>
                                current?.cellKey === cellKey && current.beforeEntryId === null
                                  ? current
                                  : { cellKey, beforeEntryId: null }
                              )
                              return
                            }
                            gaTimeDropTargetRef.current = {
                              dayOfWeek,
                              startTime: slot.start,
                              endTime: slot.end,
                              beforeEntryId: null,
                            }
                            setGaTimeDropTarget((current) =>
                              current?.cellKey === cellKey && current.beforeEntryId === null
                                ? current
                                : { cellKey, beforeEntryId: null }
                            )
                          }}
                          onDrop={(event) => {
                            if (!canEditGaTimeSlots) return
                            event.preventDefault()
                            const commentSource = gaTimeCommentDraggingRef.current
                            if (commentSource) {
                              gaTimeCommentDropHandledRef.current = true
                              void moveGaTimeCommentToSlot(
                                commentSource,
                                dayOfWeek,
                                slot.start,
                                slot.end,
                                null
                              )
                              return
                            }
                            const entryId =
                              event.dataTransfer.getData("application/x-ga-time-entry") ||
                              event.dataTransfer.getData("text/plain") ||
                              gaTimeDraggingIdRef.current ||
                              gaTimeDraggingId
                            if (!entryId) return
                            gaTimeDropHandledRef.current = true
                            void moveGaTimeEntry(entryId, dayOfWeek, slot.start, slot.end, null)
                          }}
                        >
                          <div
                            className={`ga-time-cell-content ${
                              gaTimeDropTarget?.cellKey === cellKey && gaTimeDropTarget.beforeEntryId === null
                                ? "ga-time-drop-cell"
                                : ""
                            }`}
                          >
                            {meetings.map(({ kind, meeting }, index) => (
                              <div
                                key={`ga-meeting-${kind}-${meeting.id || `${meeting.date}-${meeting.time}-${index}`}`}
                                className={`ga-time-entry ${
                                  kind === "internal"
                                    ? internalMeetingLegendTone(meeting)
                                    : meetingLegendTone({
                                        categories: meeting.calendarCategories ?? meeting.calendar_categories,
                                        recurrenceType: meeting.recurrenceType ?? meeting.recurrence_type,
                                        meetingType: "external",
                                        calendarImported: Boolean(
                                          meeting.calendarImported ??
                                            meeting.calendar_imported ??
                                            meeting.microsoft_event_id
                                        ),
                                      })
                                }`}
                                title={`${formatTimeLabel(meeting.time)} · ${meeting.title}`}
                              >
                                <span className="ga-time-meeting-time">{formatTimeLabel(meeting.time)}</span>
                                <span><strong>{kind === "internal" ? "TAK INT:" : "TAK EXT:"}</strong> {meeting.title}</span>
                              </div>
                            ))}
                            {entries.map((entry, entryIndex) => {
                              const isImported = Boolean(entry.source_type)
                              const isEditing = gaTimeEditingId === entry.id
                              if (isEditing) {
                                return (
                                  <GaTimeEntryEditor
                                    key={entry.id}
                                    initialContent={entry.content}
                                    initialFormat={entry}
                                    saving={Boolean(gaTimeSaving[entry.id])}
                                    onSave={(content, format) => updateGaTimeEntry(entry.id, content, format)}
                                    onCancel={() => setGaTimeEditingId(null)}
                                  />
                                )
                              }
                              return (
                                <div
                                  key={entry.id}
                                    className={`ga-time-entry select-none ${isImported ? "cursor-default ring-1 ring-inset ring-sky-300" : "ga-time-draggable cursor-grab active:cursor-grabbing"} ${
                                      normalizeGaTimeBackgroundColor(entry.background_color || "").toUpperCase() === "#EF4444"
                                        ? "ga-time-entry-contrast"
                                        : ""
                                    } ${
                                    gaTimeDraggingId === entry.id ? "ga-time-dragging" : ""
                                  } ${
                                    gaTimeDropTarget?.cellKey === cellKey &&
                                    gaTimeDropTarget.beforeEntryId === entry.id
                                      ? "ga-time-drop-before"
                                      : ""
                                  }`}
                                  style={gaTimeEntryStyle(entry)}
                                  draggable={canEditGaTimeSlots && !isImported && !gaTimeSaving[entry.id]}
                                  data-ga-slot-entry-id={entry.id}
                                  data-ga-next-entry-id={entries[entryIndex + 1]?.id || ""}
                                  onDragStart={(event) => {
                                    if (!canEditGaTimeSlots || isImported) return
                                    event.dataTransfer.effectAllowed = "move"
                                    event.dataTransfer.setData("application/x-ga-time-entry", entry.id)
                                    event.dataTransfer.setData("text/plain", entry.id)
                                    gaTimeDraggingIdRef.current = entry.id
                                    gaTimeDropTargetRef.current = null
                                    gaTimeEntryCommentDropTargetRef.current = null
                                    gaTimeDropHandledRef.current = false
                                    setGaTimeDraggingId(entry.id)
                                    setGaTimeEditingId(null)
                                    setGaTimeAddingCell(null)
                                  }}
                                  onDragOver={(event) => {
                                    if (!canEditGaTimeSlots || isImported) return
                                    event.preventDefault()
                                    event.stopPropagation()
                                    event.dataTransfer.dropEffect = "move"
                                    const bounds = event.currentTarget.getBoundingClientRect()
                                    const isAfter = event.clientY >= bounds.top + bounds.height / 2
                                    const beforeEntryId = isAfter
                                      ? entries[entryIndex + 1]?.id ?? null
                                      : entry.id
                                    if (gaTimeCommentDraggingRef.current) {
                                      gaTimeCommentDropTargetRef.current = {
                                        kind: "slot",
                                        dayOfWeek,
                                        startTime: slot.start,
                                        endTime: slot.end,
                                        beforeEntryId,
                                      }
                                      setGaTimeDropTarget((current) =>
                                        current?.cellKey === cellKey && current.beforeEntryId === beforeEntryId
                                          ? current
                                          : { cellKey, beforeEntryId }
                                      )
                                      return
                                    }
                                    gaTimeDropTargetRef.current = {
                                      dayOfWeek,
                                      startTime: slot.start,
                                      endTime: slot.end,
                                      beforeEntryId,
                                    }
                                    setGaTimeDropTarget((current) =>
                                      current?.cellKey === cellKey && current.beforeEntryId === beforeEntryId
                                        ? current
                                        : { cellKey, beforeEntryId }
                                    )
                                  }}
                                  onDrop={(event) => {
                                    if (!canEditGaTimeSlots || isImported) return
                                    event.preventDefault()
                                    event.stopPropagation()
                                    const bounds = event.currentTarget.getBoundingClientRect()
                                    const isAfter = event.clientY >= bounds.top + bounds.height / 2
                                    const beforeEntryId = isAfter
                                      ? entries[entryIndex + 1]?.id ?? null
                                      : entry.id
                                    const commentSource = gaTimeCommentDraggingRef.current
                                    if (commentSource) {
                                      gaTimeCommentDropHandledRef.current = true
                                      void moveGaTimeCommentToSlot(
                                        commentSource,
                                        dayOfWeek,
                                        slot.start,
                                        slot.end,
                                        beforeEntryId
                                      )
                                      return
                                    }
                                    const entryId =
                                      event.dataTransfer.getData("application/x-ga-time-entry") ||
                                      event.dataTransfer.getData("text/plain") ||
                                      gaTimeDraggingIdRef.current ||
                                      gaTimeDraggingId
                                    if (!entryId || entryId === entry.id) return
                                    gaTimeDropHandledRef.current = true
                                    void moveGaTimeEntry(entryId, dayOfWeek, slot.start, slot.end, beforeEntryId)
                                  }}
                                  onDragEnd={() => {
                                    const entryId = gaTimeDraggingIdRef.current
                                    const target = gaTimeDropTargetRef.current
                                    const commentTarget = gaTimeEntryCommentDropTargetRef.current
                                    const dropWasHandled = gaTimeDropHandledRef.current
                                    gaTimeDraggingIdRef.current = null
                                    gaTimeDropTargetRef.current = null
                                    gaTimeEntryCommentDropTargetRef.current = null
                                    gaTimeDropHandledRef.current = false
                                    setGaTimeDraggingId(null)
                                    setGaTimeDropTarget(null)
                                    if (!dropWasHandled && entryId && commentTarget) {
                                      const targetRow = gaTimeRows.find(
                                        (row) => row.start === commentTarget.rowStart && row.end === commentTarget.rowEnd
                                      )
                                      if (targetRow) {
                                        void moveGaTimeEntryToComment(
                                          entryId,
                                          targetRow,
                                          commentTarget.column,
                                          commentTarget.beforeCommentId
                                        )
                                      }
                                    } else if (!dropWasHandled && entryId && target) {
                                      void moveGaTimeEntry(
                                        entryId,
                                        target.dayOfWeek,
                                        target.startTime,
                                        target.endTime,
                                        target.beforeEntryId
                                      )
                                    }
                                  }}
                                  title={isImported
                                    ? `Imported from ${entry.source_type === "calendar" ? "Calendar" : "Reminders"}: ${entry.source_name || "iPhone"}`
                                    : "Drag to move or click to edit"}
                                >
                                  <span
                                    className="ga-time-entry-text"
                                    style={gaTimeEntryStyle(entry)}
                                    role="button"
                                    tabIndex={0}
                                    draggable={canEditGaTimeSlots && !isImported && !gaTimeSaving[entry.id]}
                                    onClick={() => {
                                      if (!canEditGaTimeSlots || isImported) return
                                      setGaTimeAddingCell(null)
                                      setGaTimeCommentEditingKey(null)
                                      setGaTimeEditingId(entry.id)
                                    }}
                                    onKeyDown={(event) => {
                                      if (event.key !== "Enter" && event.key !== " ") return
                                      event.preventDefault()
                                      if (!canEditGaTimeSlots || isImported) return
                                      setGaTimeAddingCell(null)
                                      setGaTimeCommentEditingKey(null)
                                      setGaTimeEditingId(entry.id)
                                    }}
                                  >
                                    <GaTimeEntryContent entry={entry} />
                                  </span>
                                  {canEditGaTimeSlots && !isImported ? (
                                    <button
                                      type="button"
                                      className="ga-time-delete"
                                      disabled={gaTimeDeleting[entry.id]}
                                      onClick={() => void deleteGaTimeEntry(entry.id)}
                                      title="Delete entry"
                                    >
                                      {gaTimeDeleting[entry.id] ? "..." : "×"}
                                    </button>
                                  ) : null}
                                </div>
                              )
                            })}
                            {canEditGaTimeSlots ? (
                              gaTimeAddingCell === cellKey ? (
                                <GaTimeEntryEditor
                                  saving={Boolean(gaTimeSaving[cellKey])}
                                  onSave={async (content, format) => {
                                    const created = await createGaTimeEntry(
                                      String(dayOfWeek),
                                      slot.start,
                                      slot.end,
                                      content,
                                      format
                                    )
                                    // The editor closes itself after a successful save.
                                    // Reopening it on the new entry left a box on
                                    // screen with a disabled Save button.
                                    return Boolean(created)
                                  }}
                                  onCancel={() => setGaTimeAddingCell(null)}
                                />
                              ) : (
                                <button
                                  type="button"
                                  className="ga-time-add"
                                  onClick={() => {
                                    setGaTimeEditingId(null)
                                    setGaTimeCommentEditingKey(null)
                                    setGaTimeAddingCell(cellKey)
                                  }}
                                >
                                  +
                                </button>
                              )
                            ) : null}
                          </div>
                        </td>
                      )
                    })}
                    {renderGaTimeCommentCell(slot, "end")}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </AdminTasksSection>
          </div>
          <Dialog open={gaCalendarDialogOpen} onOpenChange={setGaCalendarDialogOpen}>
            <DialogContent className="sm:max-w-xl">
              <DialogHeader>
                <DialogTitle>Apple Calendar &amp; Reminders</DialogTitle>
                <p className="text-xs text-slate-500">
                  Every GA Time Table entry shows in the iPhone Calendar every week, with a reminder at the row start time.
                </p>
              </DialogHeader>
              <div className="space-y-4 text-sm">
                <div className="space-y-3 rounded-md border border-slate-200 p-3">
                  <div>
                    <p className="font-semibold text-slate-900">In the time table colours (recommended)</p>
                    <p className="text-xs text-slate-500">
                      One calendar account, set up once. Each time table colour becomes its own calendar on the iPhone,
                      and new colours appear by themselves.
                    </p>
                  </div>
                  {gaCalendarAccount ? (
                    <Button asChild className="w-full">
                      <a href={gaCalendarAccount.profileUrl}>Install on iPhone</a>
                    </Button>
                  ) : null}
                  <ol className="list-decimal space-y-1 pl-5 text-slate-700">
                    <li>
                      On GA&apos;s iPhone, open this page in <b>Safari</b>, tap <b>Install on iPhone</b>, then <b>Allow</b>.
                    </li>
                    <li>
                      Open <b>Settings</b>, tap <b>Profile Downloaded</b> at the top, then <b>Install</b>. The
                      &quot;Not Signed&quot; notice is expected.
                    </li>
                    <li>
                      If the old calendar link is already subscribed, remove it in <b>Settings → Apps → Calendar →
                      Calendar Accounts → Subscribed Calendars</b>, otherwise every entry shows twice.
                    </li>
                    <li>
                      Set <b>Calendar Accounts → Fetch New Data</b> to every 15 minutes so changes arrive quickly.
                    </li>
                  </ol>
                  <details className="text-xs text-slate-600">
                    <summary className="cursor-pointer font-medium">Set up by hand instead</summary>
                    <p className="mt-2">
                      <b>Settings → Apps → Calendar → Calendar Accounts → Add Account → Other → Add CalDAV Account</b>,
                      then enter:
                    </p>
                    <div className="mt-2 space-y-2">
                      {(
                        [
                          ["Server", gaCalendarAccount?.server],
                          ["User Name", gaCalendarAccount?.username],
                          ["Password", gaCalendarAccount?.password],
                          ["Account URL (only if the server is not found)", gaCalendarAccount?.accountUrl],
                        ] as const
                      ).map(([label, value]) => (
                        <div key={label} className="space-y-1">
                          <Label>{label}</Label>
                          <div className="flex gap-2">
                            <Input readOnly value={value ?? "Loading…"} className="font-mono text-xs" />
                            <Button
                              variant="outline"
                              disabled={!value}
                              onClick={() => value && void copyGaIcloudValue(value, label)}
                            >
                              Copy
                            </Button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </details>
                </div>
                <p className="font-semibold text-slate-900">Single calendar link (one colour)</p>
                <div className="space-y-1.5">
                  <Label htmlFor="ga-calendar-feed-url">Calendar link (keep it private)</Label>
                  <div className="flex gap-2">
                    <Input id="ga-calendar-feed-url" readOnly value={gaCalendarFeedUrl ?? "Loading…"} className="font-mono text-xs" />
                    <Button
                      variant="outline"
                      disabled={!gaCalendarFeedUrl}
                      onClick={() => gaCalendarFeedUrl && void copyGaIcloudValue(gaCalendarFeedUrl, "Calendar link")}
                    >
                      Copy
                    </Button>
                  </div>
                </div>
                {gaCalendarFeedUrl ? (
                  <Button asChild className="w-full">
                    <a href={gaCalendarFeedUrl.replace(/^https?:\/\//, "webcal://")}>Open on iPhone</a>
                  </Button>
                ) : null}
                <ol className="list-decimal space-y-1 pl-5 text-slate-700">
                  <li>On GA&apos;s iPhone, open this page in Safari and tap <b>Open on iPhone</b>, then <b>Subscribe</b>.</li>
                  <li>
                    Or by hand: <b>Settings → Apps → Calendar → Calendar Accounts → Add Account → Other → Add Subscribed
                    Calendar</b> and paste the link.
                  </li>
                  <li>
                    Turn <b>Remove Alerts</b> OFF, otherwise the iPhone hides the reminders.
                  </li>
                  <li>
                    So new entries show up quickly, set <b>Settings → Apps → Calendar → Calendar Accounts → Fetch New Data</b> to
                    every 15 minutes.
                  </li>
                </ol>
                <p className="text-xs text-slate-500">
                  One-way: changes in PrimeFlow reach the phone, but changes on the phone do not come back.
                </p>
              </div>
            </DialogContent>
          </Dialog>
          <Dialog
            open={gaIcloudDialogOpen}
            onOpenChange={(open) => {
              setGaIcloudDialogOpen(open)
              if (!open) setGaIcloudPairing(null)
            }}
          >
            <DialogContent className="sm:max-w-2xl">
              <DialogHeader>
                <DialogTitle>iPhone Calendar &amp; Reminders Sync</DialogTitle>
                <p className="text-xs text-slate-500">
                  Read-only import into GA Time Table. PrimeFlow never changes Calendar or Reminders on the phone.
                </p>
              </DialogHeader>
              <div className="space-y-4">
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label htmlFor="ga-icloud-calendar">Calendar name</Label>
                    <Input
                      id="ga-icloud-calendar"
                      value={gaIcloudCalendarName}
                      onChange={(event) => setGaIcloudCalendarName(event.target.value)}
                      disabled={gaIcloudSaving}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="ga-icloud-reminders">Reminder list</Label>
                    <Input
                      id="ga-icloud-reminders"
                      value={gaIcloudReminderList}
                      onChange={(event) => setGaIcloudReminderList(event.target.value)}
                      disabled={gaIcloudSaving}
                    />
                  </div>
                </div>

                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
                  {gaIcloudLoading ? (
                    <span className="text-slate-500">Checking connection…</span>
                  ) : gaIcloudConnection ? (
                    <div className="space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="secondary">Connected</Badge>
                        <span className="font-medium">{gaIcloudConnection.device_name}</span>
                      </div>
                      <div className="text-xs text-slate-600">
                        Last sync: {gaIcloudConnection.last_synced_at
                          ? new Date(gaIcloudConnection.last_synced_at).toLocaleString()
                          : "not run yet"}
                        {` · ${gaIcloudConnection.last_imported_count} imported items`}
                      </div>
                    </div>
                  ) : (
                    <span className="text-slate-600">No iPhone is paired.</span>
                  )}
                </div>

                {gaIcloudPairing ? (
                  <div className="space-y-3 rounded-lg border border-amber-300 bg-amber-50 p-3">
                    <div>
                      <div className="font-semibold text-amber-950">Save these values now</div>
                      <div className="text-xs text-amber-800">
                        The pairing token is shown only once. Put it in the Shortcut header named X-PrimeFlow-Sync-Token.
                      </div>
                    </div>
                    <div className="space-y-1">
                      <Label>Import URL</Label>
                      <div className="flex gap-2">
                        <Input readOnly value={gaIcloudPairing.import_url} className="font-mono text-xs" />
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => void copyGaIcloudValue(gaIcloudPairing.import_url, "Import URL")}
                        >
                          Copy
                        </Button>
                      </div>
                    </div>
                    <div className="space-y-1">
                      <Label>Pairing token</Label>
                      <div className="flex gap-2">
                        <Input readOnly value={gaIcloudPairing.pairing_token} className="font-mono text-xs" />
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => void copyGaIcloudValue(gaIcloudPairing.pairing_token, "Pairing token")}
                        >
                          Copy
                        </Button>
                      </div>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => void copyGaIcloudValue(JSON.stringify({
                        import_url: gaIcloudPairing.import_url,
                        pairing_token: gaIcloudPairing.pairing_token,
                        calendar_name: gaIcloudPairing.calendar_name,
                        reminder_list_name: gaIcloudPairing.reminder_list_name,
                        timezone: "Europe/Berlin",
                      }, null, 2), "Shortcut configuration")}
                    >
                      Copy complete Shortcut configuration
                    </Button>
                  </div>
                ) : null}

                <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-xs text-blue-950">
                  Timed events and reminders go to their matching time row. All-day events and reminders without a time
                  go to the untimed row for that date. Completed reminders and all other lists/calendars are ignored.
                </div>

                <div className="flex flex-wrap justify-end gap-2">
                  <Button type="button" variant="outline" onClick={() => void loadGaIcloudConnection()} disabled={gaIcloudLoading || gaIcloudSaving}>
                    Refresh status
                  </Button>
                  {gaIcloudConnection ? (
                    <Button type="button" variant="destructive" onClick={() => void revokeGaIcloudDevice()} disabled={gaIcloudSaving}>
                      Disconnect
                    </Button>
                  ) : null}
                  <Button type="button" onClick={() => void pairGaIcloudDevice()} disabled={gaIcloudSaving || gaIcloudLoading}>
                    {gaIcloudSaving ? "Saving…" : gaIcloudConnection ? "Create new token" : "Create pairing"}
                  </Button>
                </div>
              </div>
            </DialogContent>
          </Dialog>
          <Dialog
            open={gaTimeRowsDialogOpen}
            onOpenChange={(open) => {
              setGaTimeRowsDialogOpen(open)
              if (!open) cancelGaTimeNewRow()
            }}
          >
            <DialogContent
              ref={gaTimeRowsDialogRef}
              className="sm:max-w-2xl"
              onOpenAutoFocus={(event) => {
                event.preventDefault()
                gaTimeRowsDialogRef.current?.focus({ preventScroll: true })
              }}
            >
              <DialogHeader>
                <DialogTitle>GA timetable times</DialogTitle>
                <p className="text-xs text-slate-500">
                  Edit the times, then click Save. Nothing is changed while you are typing.
                </p>
              </DialogHeader>
              <div className="space-y-3">
                <div
                  className={[
                    gaTimeNewRowOpen ? "max-h-[42vh]" : "max-h-[60vh]",
                    "overflow-y-auto rounded-md border",
                  ].join(" ")}
                >
                  <div className="grid grid-cols-[48px_minmax(0,1fr)_minmax(0,1fr)_48px] items-center gap-2 border-b bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-600">
                    <div>NR</div>
                    <div>Start</div>
                    <div>End</div>
                    <div />
                  </div>
                  <div key={gaTimeRowsDraftVersion} className="divide-y">
                    {gaTimeRowsDraft.map((row, index) => (
                      <div
                        key={row.id || `ga-time-row-${index}`}
                        className="grid grid-cols-[48px_minmax(0,1fr)_minmax(0,1fr)_48px] items-center gap-2 px-3 py-2"
                      >
                        <div className="text-sm font-medium text-slate-700">{index + 1}</div>
                        <Input
                          ref={(node) => setGaTimeRowInputRef(index, "start", node)}
                          type="time"
                          defaultValue={row.start}
                          disabled={gaTimeNewRowOpen}
                        />
                        <Input
                          ref={(node) => setGaTimeRowInputRef(index, "end", node)}
                          type="time"
                          defaultValue={row.end}
                          disabled={gaTimeNewRowOpen}
                        />
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => removeGaTimeRowDraft(index)}
                          disabled={gaTimeRowsDraft.length <= 1 || gaTimeNewRowOpen}
                          title="Delete row"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    ))}
                  </div>
                </div>
                {gaTimeNewRowOpen ? (
                  <form
                    className="rounded-md border border-blue-200 bg-blue-50/70 p-3"
                    onSubmit={(event) => {
                      event.preventDefault()
                      void saveGaTimeNewRow()
                    }}
                  >
                    <div className="mb-2 flex items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold text-slate-900">New time row</div>
                        <div className="text-xs text-slate-600">
                          Enter both times, or leave End empty to use 30 minutes. Times inside an existing row split it automatically.
                        </div>
                      </div>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div className="space-y-1">
                        <Label htmlFor="ga-new-row-start" className="text-xs">Start</Label>
                        <Input
                          ref={gaTimeNewRowStartRef}
                          id="ga-new-row-start"
                          type="time"
                          defaultValue=""
                          disabled={gaTimeNewRowSaving}
                        />
                      </div>
                      <div className="space-y-1">
                        <Label htmlFor="ga-new-row-end" className="text-xs">End (optional)</Label>
                        <Input
                          ref={gaTimeNewRowEndRef}
                          id="ga-new-row-end"
                          type="time"
                          defaultValue=""
                          disabled={gaTimeNewRowSaving}
                        />
                      </div>
                    </div>
                    <div className="mt-3 flex justify-end gap-2">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={cancelGaTimeNewRow}
                        disabled={gaTimeNewRowSaving}
                      >
                        Cancel new row
                      </Button>
                      <Button type="submit" size="sm" disabled={gaTimeNewRowSaving}>
                        {gaTimeNewRowSaving ? "Saving time..." : "Save time"}
                      </Button>
                    </div>
                  </form>
                ) : null}
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={openGaTimeNewRowForm}
                      disabled={gaTimeNewRowOpen}
                    >
                      <Plus className="mr-2 h-4 w-4" />
                      Add row
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={resetGaTimeRowsDraft}
                      disabled={gaTimeNewRowOpen}
                    >
                      Reset defaults
                    </Button>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setGaTimeRowsDialogOpen(false)}
                      disabled={gaTimeNewRowSaving}
                    >
                      Cancel
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      onClick={() => void saveGaTimeRows()}
                      disabled={gaTimeRowsSaving || gaTimeNewRowOpen}
                    >
                      {gaTimeRowsSaving ? "Saving..." : "Save"}
                    </Button>
                  </div>
                </div>
              </div>
            </DialogContent>
          </Dialog>
        </div>
      </div>
    )
  }

  return (
    <div className="mx-4 bg-slate-50/30" data-print-target={printTarget || ""}>
      <div className="-mx-4 w-[calc(100%+2rem)] max-w-none space-y-6 px-1 py-4 sm:mx-0 sm:w-full sm:px-0">
        <div className="space-y-8">
          {AdminCommonWeekTable()}
        </div>
      </div>
      <Dialog
        open={editOpen}
        onOpenChange={(open) => {
          setEditOpen(open)
          if (!open) {
            setEditingTaskId(null)
            setEditingTaskIsFast(false)
          }
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{editingTaskIsFast ? "Edit Fast Task Dates" : "Edit Task Dates"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Task</Label>
              <Input value={editTitle} readOnly className="bg-slate-50 text-slate-600" />
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="space-y-2">
                <Label>Start date</Label>
                <Input
                  type="date"
                  value={editStartDate}
                  onChange={(event) => {
                    setEditStartDate(event.target.value)
                  }}
                />
              </div>
              <div className="space-y-2">
                <Label>Due date</Label>
                <Input
                  type="date"
                  value={editDueDate}
                  onChange={(event) => {
                    setEditDueDate(event.target.value)
                  }}
                />
              </div>
            </div>
            <div className="text-xs text-slate-500">
              {editingTaskIsFast
                ? "This updates the fast task date range for the active generated task copies."
                : "This updates only this generated task row. The system task template stays unchanged."}
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setEditOpen(false)}>
                Cancel
              </Button>
              <Button
                disabled={savingEdit || !editingTaskId || (!editStartDate && !editDueDate)}
                onClick={() => void saveEditTask()}
              >
                {savingEdit ? "Saving..." : "Save"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog
        open={fastTaskOpen}
        onOpenChange={(open) => {
          setFastTaskOpen(open)
          if (!open) resetFastTaskForm()
        }}
      >
        <DialogContent className="sm:max-w-lg bg-white border-slate-200 rounded-2xl">
          <DialogHeader>
            <DialogTitle className="text-slate-800">New Fast Task</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label className="text-slate-700">Type</Label>
              <Select
                value={fastTaskType}
                onValueChange={(v) => setFastTaskType(v as (typeof NO_PROJECT_TYPES)[number]["id"])}
              >
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
                {NO_PROJECT_TYPES.find((opt) => opt.id === fastTaskType)?.description}
              </div>
            </div>
            <div className="space-y-2">
              <Label className="text-slate-700">Title</Label>
              <Input
                value={fastTaskTitle}
                onChange={(e) => setFastTaskTitle(e.target.value)}
                className="border-slate-200 focus:border-slate-400 rounded-xl"
              />
            </div>
            <div className="space-y-2">
              <Label className="text-slate-700">Description</Label>
              <BoldOnlyEditor value={fastTaskDescription} onChange={setFastTaskDescription} />
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label className="text-slate-700">Assign to</Label>
                <Dialog open={selectFastTaskAssigneesOpen} onOpenChange={setSelectFastTaskAssigneesOpen}>
                  <Button
                    type="button"
                    variant="outline"
                    className="w-full justify-start border-slate-200 focus:border-slate-400 rounded-xl"
                    onClick={() => setSelectFastTaskAssigneesOpen(true)}
                  >
                    {fastTaskAssigneeLabel}
                  </Button>
                  <DialogContent className="sm:max-w-md z-[110]">
                    <DialogHeader>
                      <DialogTitle>Select Assignees</DialogTitle>
                    </DialogHeader>
                    <div className="mt-4 max-h-[400px] overflow-y-auto space-y-2">
                      {users.length ? (
                        users.map((u) => {
                          const isSelected = fastTaskAssignees.includes(u.id)
                          return (
                            <div
                              key={u.id}
                              className="flex items-center space-x-2 p-2 rounded-lg hover:bg-slate-50 cursor-pointer"
                              onClick={() => {
                                if (isSelected) {
                                  setFastTaskAssignees((prev) => prev.filter((id) => id !== u.id))
                                } else {
                                  setFastTaskAssignees((prev) => [...prev, u.id])
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
                      <Button variant="outline" onClick={() => setFastTaskAssignees([])}>
                        Clear
                      </Button>
                      <Button
                        variant="outline"
                        onClick={() => setFastTaskAssignees(users.map((u) => u.id))}
                        disabled={!users.length}
                      >
                        All users
                      </Button>
                      <Button onClick={() => setSelectFastTaskAssigneesOpen(false)}>
                        Done
                      </Button>
                    </div>
                  </DialogContent>
                </Dialog>
              </div>
              <div className="space-y-2">
                <Label className="text-slate-700">Finish by (optional)</Label>
                <Select
                  value={fastTaskFinishPeriod}
                  onValueChange={(value) =>
                    setFastTaskFinishPeriod(value as TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE)
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
                  value={fastTaskStartDate}
                  onChange={(e) => setFastTaskStartDate(e.target.value)}
                  className="border-slate-200 focus:border-slate-400 rounded-xl w-full"
                />
              </div>
              <div className="space-y-2">
                <Label className="text-slate-700">Due date (optional)</Label>
                <Input
                  type="date"
                  value={fastTaskDueDate}
                  onChange={(e) => setFastTaskDueDate(e.target.value)}
                  className="border-slate-200 focus:border-slate-400 rounded-xl w-full"
                />
              </div>
            </div>
            <label className="flex items-center gap-3 rounded-xl border border-slate-200 px-3 py-2">
              <Checkbox
                checked={fastTaskDeadlineImportant}
                onCheckedChange={(checked) => setFastTaskDeadlineImportant(checked === true)}
              />
              <span className="text-sm font-medium text-slate-700">Deadline important</span>
            </label>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setFastTaskOpen(false)} className="rounded-xl border-slate-200">
                Cancel
              </Button>
              <Button
                disabled={!fastTaskTitle.trim() || !fastTaskStartDate || creatingFastTask}
                onClick={() => void submitFastTask()}
                className="bg-blue-500 hover:bg-blue-600 text-white border-0 shadow-sm rounded-xl"
              >
                {creatingFastTask ? "Creating..." : "Create"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog
        open={fastEditOpen}
        onOpenChange={(open) => {
          setFastEditOpen(open)
          if (!open) setFastEditTaskId(null)
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Edit Fast Task</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Title</Label>
              <Input value={fastEditTitle} onChange={(event) => setFastEditTitle(event.target.value)} />
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="space-y-2">
                <Label>Start date</Label>
                <Input
                  type="date"
                  value={fastEditStartDate}
                  onChange={(event) => setFastEditStartDate(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label>Due date</Label>
                <Input
                  type="date"
                  value={fastEditDueDate}
                  onChange={(event) => setFastEditDueDate(event.target.value)}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label>Priority</Label>
              <Select value={fastEditPriority} onValueChange={(value) => setFastEditPriority(value as TaskPriority)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PRIORITY_OPTIONS.map((value) => (
                    <SelectItem key={value} value={value}>
                      {value}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Status</Label>
              <Select value={fastEditStatus} onValueChange={setFastEditStatus}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TASK_STATUS_OPTIONS.map((value) => (
                    <SelectItem key={value} value={value}>
                      {reportStatusLabel(value)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {isWaitingConfirmation(fastEditStatus) ? (
              <div className="space-y-2">
                <Label>Confirm by (Manager/Admin)</Label>
                <Select
                  value={fastEditConfirmationAssigneeId || "__none__"}
                  onValueChange={(value) => setFastEditConfirmationAssigneeId(value === "__none__" ? "" : value)}
                >
                  <SelectTrigger>
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
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setFastEditOpen(false)}>
                Cancel
              </Button>
              <Button
                disabled={
                  fastEditSaving ||
                  !fastEditTitle.trim() ||
                  (isWaitingConfirmation(fastEditStatus) && !fastEditConfirmationAssigneeId)
                }
                onClick={() => void saveFastTaskEdit()}
              >
                {fastEditSaving ? "Saving..." : "Save"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog
        open={Boolean(pendingCompletionCommentTaskId)}
        onOpenChange={(open) => {
          if (!open && !pendingCompletionCommentSaving) {
            setPendingCompletionCommentTaskId(null)
            setPendingCompletionComment("")
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Complete task</DialogTitle>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault()
              void submitCompletionComment()
            }}
          >
            <div className="rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">
              Add a short result comment before closing this task.
              {pendingCompletionCommentTaskId ? (
                <div className="mt-1 font-semibold text-slate-900">
                  {tasks.find((task) => task.id === pendingCompletionCommentTaskId)?.title || "Task"}
                </div>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="completion-result-comment">Result comment</Label>
              <Input
                id="completion-result-comment"
                value={pendingCompletionComment}
                onChange={(event) => setPendingCompletionComment(event.target.value)}
                placeholder="What was completed?"
                autoFocus
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={pendingCompletionCommentSaving}
                onClick={() => {
                  setPendingCompletionCommentTaskId(null)
                  setPendingCompletionComment("")
                }}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={!pendingCompletionComment.trim() || pendingCompletionCommentSaving}
              >
                {pendingCompletionCommentSaving ? "Closing..." : "Save comment & close"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog
        open={Boolean(pendingCompletionOverrideTaskId)}
        onOpenChange={(open) => {
          if (!open) {
            setPendingCompletionOverrideTaskId(null)
            setPendingCompletionOverrideReason("")
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Close task with override</DialogTitle>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault()
              void submitCompletionOverride()
            }}
          >
            <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              You are closing a task assigned to another user. This reason will be saved in the audit log.
              {pendingCompletionOverrideTaskId ? (
                <div className="mt-1 font-semibold text-slate-900">
                  {tasks.find((task) => task.id === pendingCompletionOverrideTaskId)?.title || "Task"}
                </div>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="completion-override-reason">Reason</Label>
              <Input
                id="completion-override-reason"
                value={pendingCompletionOverrideReason}
                onChange={(event) => setPendingCompletionOverrideReason(event.target.value)}
                placeholder="Why is this task being closed by Admin/Manager?"
                autoFocus
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setPendingCompletionOverrideTaskId(null)
                  setPendingCompletionOverrideReason("")
                }}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={
                  !pendingCompletionOverrideReason.trim() ||
                  Boolean(
                    pendingCompletionOverrideTaskId &&
                    taskStatusUpdating[`task:${pendingCompletionOverrideTaskId}`]
                  )
                }
              >
                {pendingCompletionOverrideTaskId && taskStatusUpdating[`task:${pendingCompletionOverrideTaskId}`]
                  ? "Closing..."
                  : "Close task"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog
        open={Boolean(pendingStatusTaskId)}
        onOpenChange={(open) => {
          if (!open) {
            setPendingStatusTaskId(null)
            setPendingStatusValue("TODO")
            setPendingConfirmationAssigneeId("")
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Select Confirmer</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="text-sm text-slate-600">
              This task is moving to Waiting Confirmation. Select the manager/admin who will confirm it.
            </div>
            <div className="space-y-2">
              <Label>Confirm by (Manager/Admin)</Label>
              <Select
                value={pendingConfirmationAssigneeId || "__none__"}
                onValueChange={(value) => setPendingConfirmationAssigneeId(value === "__none__" ? "" : value)}
              >
                <SelectTrigger>
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
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => {
                  setPendingStatusTaskId(null)
                  setPendingStatusValue("TODO")
                  setPendingConfirmationAssigneeId("")
                }}
              >
                Cancel
              </Button>
              <Button
                disabled={!pendingConfirmationAssigneeId}
                onClick={() => void submitPendingStatusUpdate()}
              >
                Confirm
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
      <style jsx global>{`
        .daily-report-table th,
        .daily-report-table td {
          vertical-align: bottom;
          padding-bottom: 0;
          padding-top: 15px;
        }
        .daily-report-table {
          border-collapse: collapse !important;
          border-spacing: 0 !important;
        }
        .daily-report-table thead {
          position: sticky;
          top: 0;
          z-index: 10;
        }
        .daily-report-table thead th {
          border-width: 2px !important;
          border-color: #475569 !important;
          background-color: #f8fafc !important;
          box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
        }
        .daily-report-table thead th:first-child {
          border-left: 3px solid #475569 !important;
          position: sticky;
          left: 0;
          z-index: 30;
          box-shadow: 2px 0 4px rgba(0, 0, 0, 0.1);
        }
        .daily-report-table thead th:last-child {
          border-right: 3px solid #475569 !important;
        }
        .daily-report-table thead tr {
          border-top: 3px solid #475569 !important;
          border-bottom: 3px solid #475569 !important;
          border-left: 2px solid #475569 !important;
          border-right: 2px solid #475569 !important;
        }
        .admin-week-table {
          --delay-bg: #fff4e6;
          --absence-bg: #ffe9e9;
          --leave-bg: #e9f9ef;
          --blocked-bg: #ffe7ea;
          --oneh-bg: #e0f2fe;
          --personal-bg: #f3e8ff;
          --external-bg: #ffc7ce;
          --internal-bg: #ffe699;
          --bz-bg: #e6fffb;
          --r1-bg: #dcfce7;
          --problem-bg: #ecfeff;
          --feedback-bg: #e2e8f0;
          --priority-bg: #fef3c7;
        }
        .admin-week-table .all-tasks-table-scroll {
          overflow: visible;
        }
        .admin-week-table .all-tasks-table {
          width: 100%;
          border: 2px solid #020617;
          border-collapse: collapse;
        }
        .admin-week-table .all-tasks-table th,
        .admin-week-table .all-tasks-table td {
          border: 1px solid #111827 !important;
        }
        .admin-week-table .all-tasks-table thead th {
          position: sticky;
          top: 0;
          z-index: 20;
          border-top: 2px solid #020617 !important;
          border-bottom: 0 !important;
          background: #f8fafc;
          text-transform: uppercase;
          box-shadow:
            inset 0 -2px 0 #020617,
            0 2px 3px rgba(15, 23, 42, 0.2);
        }
        .admin-week-table .all-tasks-table thead th:first-child {
          border-left: 2px solid #020617 !important;
          border-right: 2px solid #020617 !important;
        }
        .admin-week-table .all-tasks-table thead th:last-child {
          border-right: 2px solid #020617 !important;
        }
        .admin-week-table .all-tasks-table tbody td:first-child:not([colspan]) {
          border-left: 2px solid #020617 !important;
          border-right: 2px solid #020617 !important;
        }
        .admin-week-table .all-tasks-table tbody td[colspan] {
          border-left: 2px solid #020617 !important;
          border-right: 2px solid #020617 !important;
        }
        .admin-week-table .all-tasks-table tbody td:last-child {
          border-right: 2px solid #020617 !important;
        }
        .admin-week-table .all-tasks-table tbody tr:last-child td {
          border-bottom: 2px solid #020617 !important;
        }
        @media (max-width: 1023px) {
          .admin-week-table .all-tasks-table-scroll {
            width: 100%;
            max-width: 100%;
            max-height: calc(100vh - 16px);
            overflow: auto;
            overscroll-behavior: contain;
            -webkit-overflow-scrolling: touch;
          }
        }
        .admin-week-table .week-table {
          width: 100%;
          border-collapse: collapse;
          border: 2px solid #111827;
          font-size: 11px;
          direction: ltr;
          table-layout: fixed;
        }
        .admin-week-table .week-table th {
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
        .admin-week-table .week-table thead tr:first-child th {
          border-top-width: 2px;
        }
        .admin-week-table .week-table thead tr:last-child th {
          border-bottom-width: 2px;
        }
        .admin-week-table .week-table thead th:first-child {
          border-left-width: 2px;
        }
        .admin-week-table .week-table thead th:last-child {
          border-right-width: 2px;
        }
        .admin-week-table .week-table thead tr:nth-child(2) th {
          top: 30px;
          z-index: 1;
        }
        .admin-week-table .week-table-date-header {
          background: #bfdbfe !important;
          font-size: 10px;
        }
        .admin-week-table .week-table-subheader {
          background: #dbeafe !important;
          font-size: 9px;
          font-weight: 600;
        }
        .admin-week-table .week-table td {
          border: 1px solid #dee2e6;
          padding: 6px 8px;
          vertical-align: bottom;
          font-size: 10px;
          text-align: left;
        }
        .admin-week-table .week-table-number {
          width: 40px;
          text-align: center;
          font-weight: 700;
          background: #f8f9fa;
        }
        .admin-week-table .week-table-label {
          width: 110px;
          font-weight: 700;
          background: #f8f9fa;
        }
        .admin-week-table .week-table-row.delay .week-table-label {
          background: var(--delay-bg);
        }
        .admin-week-table .week-table-row.absence .week-table-label {
          background: var(--absence-bg);
        }
        .admin-week-table .week-table-row.leave .week-table-label {
          background: var(--leave-bg);
        }
        .admin-week-table .week-table-row.blocked .week-table-label {
          background: var(--blocked-bg);
        }
        .admin-week-table .week-table-row.oneh .week-table-label {
          background: var(--oneh-bg);
        }
        .admin-week-table .week-table-row.personal .week-table-label {
          background: var(--personal-bg);
        }
        .admin-week-table .week-table-row.external .week-table-label {
          background: var(--external-bg);
          color: #c00000;
        }
        .admin-week-table .week-table-row.internal .week-table-label {
          background: var(--internal-bg);
          color: #806000;
        }
        .admin-week-table .week-table-row.bz .week-table-label {
          background: var(--bz-bg);
        }
        .admin-week-table .week-table-row.r1 .week-table-label {
          background: var(--r1-bg);
        }
        .admin-week-table .week-table-row.problem .week-table-label {
          background: var(--problem-bg);
        }
        .admin-week-table .week-table-row.feedback .week-table-label {
          background: var(--feedback-bg);
        }
        .admin-week-table .week-table-row.priority .week-table-label {
          background: var(--priority-bg);
        }
        .admin-week-table .week-table-cell {
          min-height: 30px;
        }
        .admin-week-table .week-table-entries {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .admin-week-table .week-table-entry {
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
        .admin-week-table .week-table-entry.external-non-daily-weekly {
          background: #fef2f2;
          border-color: #ef4444;
          color: #991b1b;
        }
        .admin-week-table .week-table-entry.external-non-daily-weekly .week-table-avatar {
          border-color: #fecaca;
          background: #fee2e2;
          color: #991b1b;
        }
        .admin-week-table .week-table-prjk-divider {
          border-top: 1px solid #64748b;
          margin: 1px 0;
        }
        .admin-week-table .week-table-entry span {
          flex: 1;
        }
        .admin-week-table .week-table-avatars {
          display: flex;
          flex-wrap: wrap;
          gap: 4px;
          margin-top: 2px;
        }
        .admin-week-table .week-table-avatar {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 20px;
          height: 20px;
          border-radius: 999px;
          background: #e2e8f0;
          color: #0f172a;
          font-weight: 700;
          font-size: 9px;
          border: 1px solid #cbd5e1;
        }
        .admin-week-table .period-indicator {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          height: 18px;
          padding: 0 6px;
          border-radius: 999px;
          background: #e0f2fe;
          border: 1px solid #bae6fd;
          color: #0369a1;
          font-weight: 700;
          font-size: 9px;
          line-height: 1;
          white-space: nowrap;
        }
        .admin-week-table .week-table-entry.repeat-task-muted {
          color: #9ca3af;
        }
        .admin-week-table .week-table-entry.repeat-task-muted .week-table-avatar {
          color: #9ca3af;
        }
        .admin-week-table .week-table-entry.repeat-task-muted .time-indicator {
          background: #f3f4f6;
          border-color: #d1d5db;
          color: #9ca3af;
        }
        .admin-week-table .week-table-empty {
          color: #adb5bd;
          font-style: italic;
        }
        .admin-week-table .ga-time-table-table {
          width: 100%;
          table-layout: fixed;
          border-collapse: collapse;
          border: 2px solid #020617;
          font-size: 11px;
        }
        .admin-week-table .ga-time-table-live {
          border-collapse: separate;
          border-spacing: 0;
        }
        .admin-week-table .ga-time-table-scroll {
          overflow: visible;
        }
        @media (max-width: 1023px) {
          .admin-week-table .ga-time-table-scroll {
            width: 100%;
            max-width: 100%;
            max-height: calc(100vh - 16px);
            overflow: auto;
            overscroll-behavior: contain;
            -webkit-overflow-scrolling: touch;
          }
          .admin-week-table .ga-time-table-live {
            width: 1080px;
            min-width: 1080px;
          }
        }
        .admin-week-table .ga-time-nr-column {
          width: 30px;
        }
        .admin-week-table .ga-time-time-column {
          width: 46px;
        }
        .admin-week-table .ga-time-comment-column {
          width: 150px;
        }
        .admin-week-table .ga-time-day-column {
          width: calc((100% - 376px) / 5);
        }
        .admin-week-table .ga-time-header {
          border: 1px solid #111827;
          border-top: 2px solid #020617;
          border-bottom: 0;
          background: #f8fafc;
          padding: 8px 6px;
          text-align: left;
          text-transform: uppercase;
          font-weight: 700;
          font-size: 10px;
          vertical-align: bottom;
          position: sticky;
          top: 0;
          z-index: 20;
          box-shadow:
            inset 0 -2px 0 #020617,
            0 2px 3px rgba(15, 23, 42, 0.2);
        }
        .admin-week-table .ga-time-table-live .ga-time-nr,
        .admin-week-table .ga-time-table-live .ga-time-time {
          position: sticky;
          background: #f1f5f9;
          z-index: 10;
        }
        .admin-week-table .ga-time-table-live .ga-time-nr {
          left: 0;
        }
        .admin-week-table .ga-time-table-live .ga-time-time {
          left: 30px;
          box-shadow: inset -1px 0 #111827, 2px 0 3px rgba(15, 23, 42, 0.16);
        }
        .admin-week-table .ga-time-table-live thead .ga-time-nr,
        .admin-week-table .ga-time-table-live thead .ga-time-time {
          background: #f8fafc;
          z-index: 30;
        }
        .admin-week-table .ga-time-table-live thead .ga-time-time {
          box-shadow: inset -1px 0 #111827, inset 0 -2px 0 #020617, 2px 0 3px rgba(15, 23, 42, 0.16);
        }
        .admin-week-table .ga-time-table-live .ga-time-row-custom .ga-time-nr {
          background: #f8fafc;
        }
        .admin-week-table .ga-time-table-table thead th:first-child {
          border-left: 2px solid #020617;
          border-right: 2px solid #020617;
        }
        .admin-week-table .ga-time-table-table thead th:last-child {
          border-right: 2px solid #020617;
        }
        .admin-week-table .ga-time-table-table tbody td:first-child {
          border-left: 2px solid #020617;
          border-right: 2px solid #020617;
        }
        .admin-week-table .ga-time-table-table tbody td:last-child {
          border-right: 2px solid #020617;
        }
        .admin-week-table .ga-time-table-table tbody tr:last-child td {
          border-bottom: 2px solid #020617;
        }
        .admin-week-table .ga-time-table-live th,
        .admin-week-table .ga-time-table-live td {
          border-right: 0;
          border-bottom: 0;
        }
        .admin-week-table .ga-time-table-live thead th:first-child,
        .admin-week-table .ga-time-table-live tbody td:first-child {
          border-right: 0;
        }
        .admin-week-table .ga-time-nr {
          width: 30px;
          text-align: center;
        }
        .admin-week-table .ga-time-time {
          width: 46px;
        }
        .admin-week-table .ga-time-range {
          display: flex;
          flex-direction: column;
          gap: 2px;
          line-height: 1.15;
        }
        .admin-week-table .ga-time-comment {
          min-width: 150px;
          width: 150px;
        }
        .admin-week-table .ga-time-special-comment {
          min-width: 0;
          width: auto;
        }
        .admin-week-table .ga-time-comment-list {
          display: flex;
          min-height: 100%;
          flex-direction: column;
          justify-content: flex-start;
          gap: 6px;
        }
        .admin-week-table .ga-time-comment-entry {
          display: flex;
          width: 100%;
          min-height: 36px;
          align-items: center;
          gap: 6px;
          border: 1px solid #e2e8f0;
          border-radius: 6px;
          background: #ffffff;
          padding: 4px 6px;
          color: #0f172a;
          font-size: 13px;
          line-height: 18px;
        }
        .admin-week-table .ga-time-comment-text {
          width: 100%;
          min-height: 36px;
          border: 1px solid #e2e8f0;
          border-radius: 6px;
          background: #ffffff;
          padding: 7px 8px;
          color: #0f172a;
          font-size: 13px;
          line-height: 18px;
          text-align: left;
          white-space: pre-wrap;
          overflow-wrap: anywhere;
          cursor: pointer;
        }
        .admin-week-table .ga-time-comment-entry .ga-time-comment-text {
          min-width: 0;
          min-height: 0;
          flex: 1;
          border: 0;
          border-radius: 0;
          background: transparent;
          padding: 3px 2px;
          color: inherit;
          font-weight: inherit;
          font-style: inherit;
        }
        .admin-week-table .ga-time-comment-entry.ga-time-draggable .ga-time-comment-text {
          cursor: grab;
        }
        .admin-week-table .ga-time-comment-entry.ga-time-draggable .ga-time-comment-text:active {
          cursor: grabbing;
        }
        .admin-week-table .ga-time-comment-add {
          width: 26px;
          height: 26px;
          padding: 0;
          align-items: center;
          justify-content: center;
        }
        .admin-week-table .ga-time-slot-label {
          border: 1px solid #111827;
          background: #f1f5f9;
          font-weight: 700;
          font-size: 10px;
          text-align: left;
          padding: 6px;
          white-space: nowrap;
          direction: ltr;
          vertical-align: top;
        }
        .admin-week-table .ga-time-row-custom .ga-time-slot-label {
          background: #f8fafc;
        }
        .admin-week-table .ga-time-cell {
          border: 1px solid #111827;
          padding: 6px;
          vertical-align: top;
          min-width: 0;
        }
        .admin-week-table .ga-time-cell-content {
          display: flex;
          flex-direction: column;
          justify-content: flex-start;
          gap: 6px;
          min-height: 100%;
        }
        .admin-week-table .ga-time-entry {
          display: flex;
          align-items: center;
          gap: 6px;
          background: #ffffff;
          border: 1px solid #e2e8f0;
          border-radius: 6px;
          padding: 4px 6px;
          font-size: 11px;
        }
        .admin-week-table .ga-time-entry-contrast,
        .admin-week-table .ga-time-editor-contrast {
          color: #ffffff;
        }
        .admin-week-table .ga-time-entry > span {
          min-width: 0;
          overflow-wrap: anywhere;
        }
        .admin-week-table .ga-time-meeting-time {
          flex: 0 0 auto;
          align-self: flex-start;
          margin-top: 2px;
          font-size: 8px;
          font-weight: 700;
          line-height: 1;
          white-space: nowrap;
          opacity: 0.72;
        }
        .admin-week-table .ga-time-draggable {
          cursor: grab;
          transition: opacity 120ms ease, transform 120ms ease, box-shadow 120ms ease;
        }
        .admin-week-table .ga-time-draggable:active {
          cursor: grabbing;
        }
        .admin-week-table .ga-time-dragging {
          opacity: 1;
        }
        .admin-week-table .ga-time-drop-before {
          box-shadow: 0 0 0 1px #cbd5e1;
          transform: none;
        }
        .admin-week-table .ga-time-drop-cell {
          border-radius: 6px;
          outline: 1px dashed #cbd5e1;
          outline-offset: -1px;
          background: transparent;
        }
        .admin-week-table .ga-time-entry.outlook-manual { background: #fff4cc; border-color: #d6b44c; }
        .admin-week-table .ga-time-entry.outlook-violet { background: #e5e7fb; border-color: #7167d9; }
        .admin-week-table .ga-time-entry.outlook-blue { background: #dcecff; border-color: #5b9fe8; }
        .admin-week-table .ga-time-entry.outlook-teal { background: #cceff1; border-color: #35abb4; }
        .admin-week-table .ga-time-entry.outlook-yellow { background: #ffe38f; border-color: #e6ad00; }
        .admin-week-table .ga-time-entry.outlook-brown { background: #c9a98a; border-color: #8b623d; }
        .admin-week-table .ga-time-entry.outlook-orange { background: #ffd7ad; border-color: #e87922; }
        .admin-week-table .ga-time-entry.outlook-red { background: #ffd5dc; border-color: #e55361; }
        .admin-week-table .ga-time-entry[class*="outlook-"] {
          color: #0f172a;
          line-height: 1.35;
        }
        .admin-week-table .ga-time-entry-text {
          background: transparent;
          border: none;
          text-align: left;
          padding: 0;
          font-size: 11px;
          color: #0f172a;
          flex: 1;
          cursor: inherit;
        }
        .admin-week-table .ga-time-entry-text:disabled {
          cursor: default;
        }
        .admin-week-table .ga-time-reminder-preview {
          display: -webkit-box;
          -webkit-box-orient: vertical;
          -webkit-line-clamp: 3;
          overflow: hidden;
          text-overflow: ellipsis;
          overflow-wrap: anywhere;
          white-space: normal;
          width: 100%;
          min-width: 0;
        }
        .admin-week-table .ga-time-input {
          width: 100%;
          border: 1px solid #cbd5e1;
          border-radius: 6px;
          padding: 4px 6px;
          font-size: 11px;
          color: #0f172a;
          background: #ffffff;
        }
        .admin-week-table .ga-time-delete {
          border: 1px solid #fecaca;
          background: #fff1f2;
          color: #b91c1c;
          width: 20px;
          height: 20px;
          border-radius: 6px;
          font-weight: 700;
          line-height: 1;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
        }
        .admin-week-table .ga-time-add {
          align-self: flex-start;
          border: 1px dashed #cbd5e1;
          background: #f8fafc;
          color: #475569;
          font-size: 10px;
          font-weight: 600;
          padding: 4px 8px;
          border-radius: 6px;
          cursor: pointer;
        }
        .admin-week-table .ga-time-table-live .ga-time-cell:has(.ga-time-add) {
          position: relative;
          padding-bottom: 38px;
        }
        .admin-week-table .ga-time-table-live .ga-time-cell .ga-time-add {
          position: absolute;
          bottom: 6px;
          left: 6px;
          z-index: 1;
        }
        .print-header,
        .print-footer {
          display: none;
        }
        .print-only {
          display: none;
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
            margin: 0;
            padding: 0;
          }
          aside, header, nav {
            display: none !important;
          }
          @page {
            margin: 4mm;
            size: landscape;
          }
          [data-print-target="ga-time"],
          [data-print-target="ga-time"] > div,
          [data-print-target="ga-time"] .admin-week-table,
          [data-print-target="ga-time"] .print-section[data-print-section="ga-time"],
          [data-print-target="ga-time"] .print-only,
          [data-print-target="ga-time"] .print-page,
          [data-print-target="ga-time"] .ga-time-table {
            width: 100% !important;
            min-width: 0 !important;
            max-width: 100% !important;
            margin-left: 0 !important;
            margin-right: 0 !important;
          }
          [data-print-target="ga-time"] > div {
            padding-left: 0 !important;
            padding-right: 0 !important;
          }
          .admin-week-table .all-tasks-table-scroll {
            max-height: none !important;
            overflow: visible !important;
          }
          .admin-week-table .all-tasks-table thead th {
            position: static !important;
            border-bottom: 2px solid #111827 !important;
            box-shadow: none !important;
          }
          .print-only {
            display: block !important;
          }
          .print-page {
            position: relative;
            padding: 0.12in 0.12in 0.14in 0.12in;
            margin: 0;
            width: 100%;
            max-width: 100%;
            overflow: visible;
            page-break-before: auto;
          }
          .print-section[data-print-section="ga-time"] .print-page {
            display: flex;
            flex-direction: column;
            height: calc(210mm - 8mm);
            min-height: calc(210mm - 8mm);
            max-height: none;
            overflow: visible;
            padding: 0.04in 0.02in;
          }
          .print-section[data-print-section="ga-time"] .print-header {
            margin-bottom: 4px;
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
          .admin-week-table .week-table-view {
            display: block !important;
            page-break-inside: avoid;
            page-break-after: auto;
            padding-top: 0;
            padding-bottom: 0.35in;
            padding-left: 0;
            padding-right: 0;
            margin: 0;
            width: 100%;
            max-width: 100%;
            overflow: visible;
            page-break-before: auto;
          }
          .admin-week-table .week-table {
            page-break-inside: avoid;
            margin-top: 0;
            table-layout: fixed;
            width: 100%;
            font-size: 9px;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
          }
          .admin-week-table .week-table thead {
            display: table-header-group;
          }
          .admin-week-table .week-table th,
          .admin-week-table .week-table td {
            border: 1px solid #111827 !important;
            position: static !important;
            top: auto !important;
            z-index: auto !important;
            padding: 4px 5px;
            white-space: normal;
            overflow-wrap: anywhere;
            word-break: break-word;
          }
          .admin-week-table .week-table thead tr:nth-child(2) th {
            top: auto !important;
          }
          .admin-week-table .week-table-number {
            width: 36px !important;
          }
          .admin-week-table .week-table-label {
            width: 100px !important;
          }
          .admin-week-table .week-table-cell,
          .admin-week-table .week-table-entry span {
            white-space: normal;
          }
          .admin-week-table .week-table-row.feedback .feedback-print-clamp {
            display: -webkit-box !important;
            -webkit-box-orient: vertical;
            -webkit-line-clamp: 2;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: normal !important;
            line-height: 1.15;
          }
          .admin-week-table .week-table-date-header,
          .admin-week-table .week-table-subheader {
            background: #e5e7eb !important;
            color: #111827 !important;
          }
          .admin-week-table .week-table thead th {
            background: #e5e7eb !important;
          }
          .admin-week-table .week-table-entry {
            border: 1px solid #111827 !important;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
            page-break-inside: avoid;
            margin-bottom: 3px;
            font-size: 9px;
            padding: 2px 4px;
          }
          .admin-week-table .week-table-entry.external-non-daily-weekly {
            background: #fef2f2 !important;
            border-color: #ef4444 !important;
            color: #991b1b !important;
          }
          .admin-week-table .week-table-entries {
            gap: 2px;
          }
          .admin-week-table .ga-time-table-table {
            table-layout: fixed;
            width: 100%;
            height: 100%;
            font-size: 9px;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
            border: 1px solid #111827 !important;
          }
          .print-section[data-print-section="ga-time"] .ga-time-table {
            flex: 1;
            display: flex;
            min-height: 0;
            overflow: visible;
          }
          .print-section[data-print-section="ga-time"] .ga-time-table-table tbody .ga-time-row-primary,
          .print-section[data-print-section="ga-time"] .ga-time-table-table tbody .ga-time-row-secondary {
            height: auto;
          }
          .print-section[data-print-section="ga-time"] .ga-time-table-table tbody .ga-time-row-custom {
            height: 3mm;
          }
          .admin-week-table .ga-time-table-table th,
          .admin-week-table .ga-time-table-table td {
            border: 1px solid #111827 !important;
            position: static !important;
            top: auto !important;
            z-index: auto !important;
            padding: 2px 3px;
            white-space: normal;
            overflow-wrap: anywhere;
            word-break: break-word;
          }
          .admin-week-table .ga-time-table-table thead .ga-time-header {
            border-top: 2px solid #111827 !important;
            border-bottom: 2px solid #111827 !important;
          }
          .admin-week-table .ga-time-table-table thead th:first-child,
          .admin-week-table .ga-time-table-table tbody td:first-child {
            border-left: 2px solid #111827 !important;
            border-right: 2px solid #111827 !important;
          }
          .admin-week-table .ga-time-table-table thead th:last-child,
          .admin-week-table .ga-time-table-table tbody td:last-child {
            border-right: 2px solid #111827 !important;
          }
          .admin-week-table .ga-time-table-table tbody tr:last-child td {
            border-bottom: 2px solid #111827 !important;
          }
          .admin-week-table .ga-time-header {
            background: #e5e7eb !important;
            color: #111827 !important;
            box-shadow: none !important;
          }
          .admin-week-table .ga-time-nr {
            width: 2.5% !important;
          }
          .admin-week-table .ga-time-nr-column {
            width: 2.5% !important;
          }
          .admin-week-table .ga-time-time-column {
            width: 4% !important;
          }
          .admin-week-table .ga-time-comment-column {
            width: 14% !important;
          }
          .admin-week-table .ga-time-day-column {
            width: 13.1% !important;
          }
          .admin-week-table .ga-time-comment {
            min-width: 0 !important;
            width: 14% !important;
          }
          .admin-week-table .ga-time-special-comment {
            min-width: 0 !important;
            width: auto !important;
          }
          .admin-week-table .ga-time-time {
            width: 4% !important;
          }
          .admin-week-table .ga-time-slot-label {
            background: #f3f4f6 !important;
            text-align: left !important;
            direction: ltr;
            vertical-align: top !important;
            font-size: 8px;
            line-height: 1.1;
          }
          .print-section[data-print-section="ga-time"] .ga-time-slot-label,
          .print-section[data-print-section="ga-time"] .ga-time-cell {
            height: inherit;
            vertical-align: top;
          }
          .print-section[data-print-section="ga-time"] .ga-time-cell-content {
            min-height: 100%;
            justify-content: flex-start;
            gap: 2px;
          }
          .print-section[data-print-section="ga-time"] .ga-time-table-table tbody {
            height: 100%;
          }
          .admin-week-table .ga-time-entry {
            border: 1px solid #111827 !important;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
            page-break-inside: avoid;
            margin-bottom: 1px;
            font-size: 8px;
            line-height: 1.15;
            padding: 1px 2px;
          }
          .print-section[data-print-section="ga-time"] .ga-time-comment-list {
            gap: 2px;
          }
          .print-section[data-print-section="ga-time"] .ga-time-comment-text {
            min-height: 0;
            padding: 2px 3px;
            font-size: 8px;
            line-height: 1.15;
          }
          .print-title {
            font-size: 13px;
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
            bottom: 0.08in;
            left: 0.12in;
            right: 0.12in;
            display: grid;
            grid-template-columns: 1fr auto 1fr;
            padding-left: 0;
            padding-right: 0;
            font-size: 10px;
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
          [data-print-target]:not([data-print-target=""]) .print-section {
            display: none !important;
          }
          [data-print-target="common"] .print-section[data-print-section="common"],
          [data-print-target="ga-time"] .print-section[data-print-section="ga-time"],
          [data-print-target="all-tasks"] .print-section[data-print-section="all-tasks"] {
            display: block !important;
          }
          .daily-report-table thead {
            display: table-header-group;
          }
          .daily-report-table th,
          .daily-report-table td {
            vertical-align: bottom !important;
            border: 1px solid #0f172a !important;
          }
          .daily-report-table {
            table-layout: fixed;
            border-width: 2px;
            border-color: #0f172a;
            border-collapse: collapse !important;
            border-spacing: 0 !important;
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
          .print-nr-cell {
            font-weight: 700;
          }
        }
      `}</style>
    </div>
  )
}
