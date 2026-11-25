"use client"

import * as React from "react"
import { toast } from "sonner"

import { TaskEditDialog } from "@/components/task-edit-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useAuth } from "@/lib/auth"
import { formatDateDMY, toDateInputValue } from "@/lib/dates"
import { weeklyPlanStatusBgClass } from "@/lib/weekly-plan-status"
import type { SystemTaskTemplateDefinition, Task, User } from "@/lib/types"

const ALL_USERS_VALUE = "__all__"
const QUICK_FILTER_ALL = "all"
const QUICK_FILTER_TODAY = "today"
const QUICK_FILTER_OVERDUE = "overdue"
const QUICK_FILTER_TODAY_OVERDUE = "today_overdue"
const MAX_SAME_TASK_INITIALS = 10

type QuickFilterValue =
  | typeof QUICK_FILTER_ALL
  | typeof QUICK_FILTER_TODAY
  | typeof QUICK_FILTER_OVERDUE
  | typeof QUICK_FILTER_TODAY_OVERDUE

type AssigneeInitialEntry = { id: string; label: string; initials: string }

const FREQUENCY_LABELS: Record<string, string> = {
  DAILY: "Daily",
  WEEKLY: "Weekly",
  MONTHLY: "Monthly",
  YEARLY: "Yearly",
  "3_MONTHS": "Every 3 months",
  "6_MONTHS": "Every 6 months",
}

const TABLE_HEADERS = [
  "NR",
  "Title",
  "Assignee",
  "Other Assignees",
  "Start Date",
  "Due Date",
  "Late",
  "Moved",
  "Frequency",
  "AM/PM",
  "Barazime",
  "Koha e Bz",
  "Status",
  "Actions",
] as const

type RowView = {
  task: Task
  id: string
  templateId: string
  title: string
  assigneeIds: string[]
  assigneeLabel: string
  assigneeEntries: AssigneeInitialEntry[]
  relatedAssignees: AssigneeInitialEntry[]
  startDateIso: string
  dueDateIso: string
  movedFromDateIso: string
  lateDays: number | null
  movedDays: number | null
  frequencyLabel: string
  amPm: string
  barazime: string
  kohaBarazimeve: string
  status: string
  statusClassName: string
  canEdit: boolean
  canMarkDone: boolean
}

function userLabel(user?: User | null) {
  if (!user) return ""
  return user.full_name || user.username || user.email || ""
}

function initials(name: string) {
  const cleaned = name.trim()
  if (!cleaned) return "?"
  const parts = cleaned.split(/\s+/)
  const first = parts[0]?.[0] || ""
  const last = parts.length > 1 ? parts[parts.length - 1]?.[0] || "" : ""
  return `${first}${last}`.toUpperCase()
}

function formatAlignmentInitials(
  alignmentUserIds: string[] | null | undefined,
  alignmentRoles: string[] | null | undefined,
  usersById: Map<string, User>
) {
  const alignmentInitials = (alignmentUserIds || [])
    .map((id) => {
      const label = userLabel(usersById.get(id))
      return label ? initials(label) : ""
    })
    .filter(Boolean)

  if (alignmentInitials.length) return alignmentInitials.join(", ")
  if (alignmentRoles?.length) return alignmentRoles.join(", ")
  return "-"
}

function taskAssigneeInfo(task: Task, usersById: Map<string, User>) {
  const seen = new Set<string>()
  const labels: string[] = []
  const ids: string[] = []

  const pushUser = (id?: string | null, fallbackLabel?: string | null) => {
    if (!id || seen.has(id)) return
    seen.add(id)
    ids.push(id)
    const user = usersById.get(id)
    const label = userLabel(user) || fallbackLabel || id
    labels.push(label)
  }

  if (task.assignees?.length) {
    for (const assignee of task.assignees) {
      pushUser(assignee.id, assignee.full_name || assignee.username || assignee.email || null)
    }
  }

  pushUser(task.assigned_to)

  return {
    ids,
    label: labels.length ? labels.join(", ") : "Unassigned",
  }
}

function assigneeEntriesFromIds(assigneeIds: string[], usersById: Map<string, User>): AssigneeInitialEntry[] {
  return assigneeIds
    .map((id) => {
      const label = userLabel(usersById.get(id)) || id
      return {
        id,
        label,
        initials: initials(label),
      }
    })
    .sort((a, b) => a.label.localeCompare(b.label))
}

function initialsSummary(assignees: AssigneeInitialEntry[]) {
  if (assignees.length > MAX_SAME_TASK_INITIALS) return "All"
  return assignees.map((assignee) => assignee.initials).join(", ") || "-"
}

function formatTimeLabel(value?: string | null) {
  if (!value) return "-"
  const normalized = value.trim()
  if (!normalized) return "-"
  const [hoursRaw, minutesRaw] = normalized.slice(0, 5).split(":")
  const hours = Number(hoursRaw)
  const minutes = Number(minutesRaw)
  if (Number.isNaN(hours) || Number.isNaN(minutes)) return normalized
  const suffix = hours >= 12 ? "PM" : "AM"
  const displayHours = hours % 12 === 0 ? 12 : hours % 12
  return `${String(displayHours).padStart(2, "0")}:${String(minutes).padStart(2, "0")} ${suffix}`
}

function isoOrEmpty(value?: string | null) {
  return toDateInputValue(value || null)
}

function signedDaysLabel(value: number | null) {
  if (value == null) return "-"
  if (value > 0) return `+${value}`
  return String(value)
}

function parseFilenameFromDisposition(headerValue: string | null) {
  if (!headerValue) return null
  const filenameStarMatch = headerValue.match(/filename\*\s*=\s*UTF-8''([^;]+)/i)
  if (filenameStarMatch?.[1]) return decodeURIComponent(filenameStarMatch[1])
  const filenameMatch = headerValue.match(/filename\s*=\s*"?([^";]+)"?/i)
  return filenameMatch?.[1] ?? null
}

function isIsoWithinInclusiveRange(value: string, from: string, to: string) {
  if (!value) return false
  if (from && value < from) return false
  if (to && value > to) return false
  return true
}

function isOpenStatus(status: string) {
  return status === "TODO" || status === "IN_PROGRESS" || status === "PAUSED" || status === "WAITING_CONFIRMATION"
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

function rowPriorityRank(row: RowView) {
  const isLate = (row.lateDays ?? 0) > 0
  const isMoved = (row.movedDays ?? 0) !== 0
  const isOpen = isOpenStatus(row.status)

  if (isLate && isOpen) return 0
  if (isMoved && isOpen) return 1
  if (row.status === "TODO") return 2
  if (row.status === "IN_PROGRESS") return 3
  if (row.status === "WAITING_CONFIRMATION") return 4
  if (isOpen) return 5
  if (row.status === "DONE") return 7
  return 6
}

function rowGroupDate(row: RowView) {
  return row.startDateIso || row.movedFromDateIso || row.dueDateIso
}

function rowGroupKey(row: RowView) {
  return [row.templateId, row.title, row.startDateIso, row.dueDateIso, row.movedFromDateIso].join("|")
}

function rowMatchesToday(row: RowView, todayIso: string) {
  return [row.startDateIso, row.dueDateIso].filter(Boolean).includes(todayIso)
}

function rowAmPmRank(row: RowView) {
  if (row.amPm === "AM") return 0
  if (row.amPm === "PM") return 1
  return 2
}

function rowMatchesDateFilter(
  row: RowView,
  dateFrom: string,
  dateTo: string
) {
  const candidateDates = [row.startDateIso, row.dueDateIso, row.movedFromDateIso].filter(Boolean)
  if (!candidateDates.length) return false
  if (!dateFrom && !dateTo) return true
  if (dateFrom && !dateTo) return candidateDates.includes(dateFrom)
  if (!dateFrom && dateTo) return candidateDates.includes(dateTo)
  const start = dateFrom <= dateTo ? dateFrom : dateTo
  const end = dateFrom <= dateTo ? dateTo : dateFrom
  return candidateDates.some((dateValue) => isIsoWithinInclusiveRange(dateValue, start, end))
}

export default function SystemTaskInstancesPage() {
  const { apiFetch, user } = useAuth()
  const [tasks, setTasks] = React.useState<Task[]>([])
  const [templates, setTemplates] = React.useState<SystemTaskTemplateDefinition[]>([])
  const [users, setUsers] = React.useState<User[]>([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [selectedUserId, setSelectedUserId] = React.useState<string>(ALL_USERS_VALUE)
  const [quickFilters, setQuickFilters] = React.useState<QuickFilterValue[]>([QUICK_FILTER_ALL])
  const [dateFrom, setDateFrom] = React.useState("")
  const [dateTo, setDateTo] = React.useState("")
  const [showDone, setShowDone] = React.useState(false)
  const [updatingTaskIds, setUpdatingTaskIds] = React.useState<Record<string, boolean>>({})
  const [exportingExcel, setExportingExcel] = React.useState(false)
  const [editingTask, setEditingTask] = React.useState<Task | null>(null)
  const [stickyHeaderVisible, setStickyHeaderVisible] = React.useState(false)
  const [stickyHeaderLeft, setStickyHeaderLeft] = React.useState(0)
  const [stickyHeaderWidth, setStickyHeaderWidth] = React.useState(0)
  const [stickyTableWidth, setStickyTableWidth] = React.useState(0)
  const [tableScrollLeft, setTableScrollLeft] = React.useState(0)
  const [headerColumnWidths, setHeaderColumnWidths] = React.useState<number[]>([])
  const tableContainerRef = React.useRef<HTMLDivElement | null>(null)
  const todayIso = React.useMemo(() => toDateInputValue(new Date()), [])
  const activeQuickFilter = React.useMemo(
    () => quickFilters[0] || QUICK_FILTER_ALL,
    [quickFilters]
  )

  const loadData = React.useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [tasksRes, templatesRes, usersRes] = await Promise.all([
        apiFetch("/tasks?system_only=true&include_done=true&include_all_done=true"),
        apiFetch("/system-tasks/templates"),
        apiFetch("/users"),
      ])

      if (!tasksRes.ok || !templatesRes.ok || !usersRes.ok) {
        throw new Error("Unable to load generated system tasks.")
      }

      setTasks((await tasksRes.json()) as Task[])
      setTemplates((await templatesRes.json()) as SystemTaskTemplateDefinition[])
      setUsers((await usersRes.json()) as User[])
    } catch (loadError) {
      const message = loadError instanceof Error ? loadError.message : "Unable to load generated system tasks."
      setError(message)
    } finally {
      setLoading(false)
    }
  }, [apiFetch])

  React.useEffect(() => {
    void loadData()
  }, [loadData])

  const usersById = React.useMemo(() => {
    const map = new Map<string, User>()
    for (const user of users) {
      map.set(user.id, user)
    }
    return map
  }, [users])

  const templatesById = React.useMemo(() => {
    const map = new Map<string, SystemTaskTemplateDefinition>()
    for (const template of templates) {
      map.set(template.id, template)
    }
    return map
  }, [templates])

  const rows = React.useMemo<RowView[]>(() => {
    const nextRows = tasks
      .filter((task) => Boolean(task.system_template_origin_id))
      .map((task) => {
        const template = task.system_template_origin_id
          ? templatesById.get(task.system_template_origin_id)
          : undefined
        const assigneeInfo = taskAssigneeInfo(task, usersById)
        const hasAlignment = Boolean(
          template?.requires_alignment ||
            template?.alignment_time ||
            template?.alignment_roles?.length ||
            template?.alignment_user_ids?.length
        )
        const statusValue = task.status || "TODO"
        const isManagerView = user?.role === "ADMIN" || user?.role === "MANAGER"
        const isAssignedToCurrentUser = Boolean(user?.id && assigneeInfo.ids.includes(user.id))
        const canEdit = Boolean((isManagerView || isAssignedToCurrentUser) && statusValue !== "DONE")

        return {
          task,
          id: task.id,
          templateId: task.system_template_origin_id || "",
          title: task.title || "-",
          assigneeIds: assigneeInfo.ids,
          assigneeLabel: assigneeInfo.label,
          assigneeEntries: assigneeEntriesFromIds(assigneeInfo.ids, usersById),
          relatedAssignees: assigneeEntriesFromIds(assigneeInfo.ids, usersById),
          startDateIso: isoOrEmpty(task.start_date),
          dueDateIso: isoOrEmpty(task.due_date),
          movedFromDateIso: isoOrEmpty(task.planned_date || task.original_due_date),
          lateDays: task.late_days ?? null,
          movedDays: task.moved_days ?? null,
          frequencyLabel: template?.frequency ? (FREQUENCY_LABELS[template.frequency] || template.frequency) : "-",
          amPm: task.finish_period || template?.finish_period || "-",
          barazime: hasAlignment
            ? formatAlignmentInitials(template?.alignment_user_ids, template?.alignment_roles, usersById)
            : "-",
          kohaBarazimeve: hasAlignment ? formatTimeLabel(template?.alignment_time) : "-",
          status: statusValue,
          statusClassName: weeklyPlanStatusBgClass(statusValue),
          canEdit,
          canMarkDone: canEdit && statusValue !== "DONE",
        }
      })

    const groupedRows = new Map<string, RowView[]>()
    for (const row of nextRows) {
      const key = rowGroupKey(row)
      const existing = groupedRows.get(key)
      if (existing) {
        existing.push(row)
      } else {
        groupedRows.set(key, [row])
      }
    }

    const sortedGroups = Array.from(groupedRows.values()).sort((a, b) => {
      const aTopRank = Math.min(...a.map(rowPriorityRank))
      const bTopRank = Math.min(...b.map(rowPriorityRank))
      if (aTopRank !== bTopRank) return aTopRank - bTopRank

      const aHasLate = a.some((row) => (row.lateDays ?? 0) > 0)
      const bHasLate = b.some((row) => (row.lateDays ?? 0) > 0)
      if (aHasLate !== bHasLate) return aHasLate ? -1 : 1

      const aHasMoved = a.some((row) => (row.movedDays ?? 0) !== 0)
      const bHasMoved = b.some((row) => (row.movedDays ?? 0) !== 0)
      if (aHasMoved !== bHasMoved) return aHasMoved ? -1 : 1

      const aDate = rowGroupDate(a[0]!)
      const bDate = rowGroupDate(b[0]!)
      if (aDate !== bDate) return bDate.localeCompare(aDate)

      const aTitle = a[0]?.title || ""
      const bTitle = b[0]?.title || ""
      if (aTitle !== bTitle) return aTitle.localeCompare(bTitle)

      const aTemplateId = a[0]?.templateId || ""
      const bTemplateId = b[0]?.templateId || ""
      return aTemplateId.localeCompare(bTemplateId)
    })

    return sortedGroups.flatMap((group) => {
      const sharedAssigneeMap = new Map<string, { id: string; label: string; initials: string }>()
      for (const row of group) {
        for (const assignee of row.relatedAssignees) {
          if (!sharedAssigneeMap.has(assignee.id)) {
            sharedAssigneeMap.set(assignee.id, assignee)
          }
        }
      }
      const sharedAssignees = Array.from(sharedAssigneeMap.values()).sort((a, b) =>
        a.label.localeCompare(b.label)
      )

      return [...group]
        .sort((a, b) => a.assigneeLabel.localeCompare(b.assigneeLabel))
        .map((row) => ({
          ...row,
          relatedAssignees: sharedAssignees,
        }))
    })
  }, [tasks, templatesById, user?.id, user?.role, usersById])

  const filteredRows = React.useMemo(() => {
    const visibleRows = rows.filter((row) => {
      if (selectedUserId !== ALL_USERS_VALUE && !row.assigneeIds.includes(selectedUserId)) {
        return false
      }

      return rowMatchesDateFilter(row, dateFrom, dateTo)
    })

    const allSelected = activeQuickFilter === QUICK_FILTER_ALL
    const includeToday =
      allSelected ||
      activeQuickFilter === QUICK_FILTER_TODAY ||
      activeQuickFilter === QUICK_FILTER_TODAY_OVERDUE
    const includeOverdue =
      allSelected ||
      activeQuickFilter === QUICK_FILTER_OVERDUE ||
      activeQuickFilter === QUICK_FILTER_TODAY_OVERDUE

    let prioritizedRows = visibleRows
    if (allSelected) {
      const overdueRows = visibleRows
        .filter((row) => row.status !== "DONE" && (row.lateDays ?? 0) > 0)
        .sort((a, b) => {
          const aLate = a.lateDays ?? 0
          const bLate = b.lateDays ?? 0
          if (aLate !== bLate) return bLate - aLate
          return rows.indexOf(a) - rows.indexOf(b)
        })

      const todayRows = visibleRows
        .filter(
          (row) =>
            row.status !== "DONE" &&
            (row.lateDays ?? 0) <= 0 &&
            rowMatchesToday(row, todayIso)
        )
        .sort((a, b) => {
          const aPeriod = rowAmPmRank(a)
          const bPeriod = rowAmPmRank(b)
          if (aPeriod !== bPeriod) return aPeriod - bPeriod
          return rows.indexOf(a) - rows.indexOf(b)
        })

      const pickedIds = new Set([...overdueRows, ...todayRows].map((row) => row.id))
      const otherRows = visibleRows.filter(
        (row) => row.status !== "DONE" && !pickedIds.has(row.id)
      )

      const doneRows = visibleRows.filter((row) => row.status === "DONE")
      prioritizedRows = [...overdueRows, ...todayRows, ...otherRows, ...doneRows]
    } else {
      prioritizedRows = visibleRows.filter((row) => {
        const matchesToday = includeToday && rowMatchesToday(row, todayIso)
        const matchesOverdue = includeOverdue && (row.lateDays ?? 0) > 0
        return matchesToday || matchesOverdue
      })

      if (includeToday && includeOverdue) {
        const overdueRows = prioritizedRows
          .filter((row) => (row.lateDays ?? 0) > 0)
          .sort((a, b) => {
            const aLate = a.lateDays ?? 0
            const bLate = b.lateDays ?? 0
            if (aLate !== bLate) return bLate - aLate
            return rows.indexOf(a) - rows.indexOf(b)
          })

        const todayRows = prioritizedRows
          .filter((row) => (row.lateDays ?? 0) <= 0 && rowMatchesToday(row, todayIso))
          .sort((a, b) => {
            const aPeriod = rowAmPmRank(a)
            const bPeriod = rowAmPmRank(b)
            if (aPeriod !== bPeriod) return aPeriod - bPeriod
            return rows.indexOf(a) - rows.indexOf(b)
          })

        prioritizedRows = [...overdueRows, ...todayRows]
      } else if (includeOverdue) {
        prioritizedRows = prioritizedRows.sort((a, b) => {
          const aLate = a.lateDays ?? 0
          const bLate = b.lateDays ?? 0
          if (aLate !== bLate) return bLate - aLate
          return rows.indexOf(a) - rows.indexOf(b)
        })
      } else if (includeToday) {
        prioritizedRows = prioritizedRows.sort((a, b) => {
          const aPeriod = rowAmPmRank(a)
          const bPeriod = rowAmPmRank(b)
          if (aPeriod !== bPeriod) return aPeriod - bPeriod
          return rows.indexOf(a) - rows.indexOf(b)
        })
      }
    }

    const nonDoneRows = prioritizedRows.filter((row) => row.status !== "DONE")
    if (!allSelected) return nonDoneRows
    if (!showDone) return nonDoneRows

    const doneRows = prioritizedRows.filter((row) => row.status === "DONE")
    return [...nonDoneRows, ...doneRows]
  }, [activeQuickFilter, dateFrom, dateTo, rows, selectedUserId, showDone, todayIso])

  const toggleQuickFilter = React.useCallback((value: QuickFilterValue, checked: boolean) => {
    setQuickFilters((prev) => {
      if (!checked) return prev
      return [value]
    })
  }, [])

  const quickFilterLabel = React.useMemo(() => {
    if (activeQuickFilter === QUICK_FILTER_TODAY) return "Today"
    if (activeQuickFilter === QUICK_FILTER_OVERDUE) return "Overdue"
    if (activeQuickFilter === QUICK_FILTER_TODAY_OVERDUE) return "Today + Overdue"
    return "All"
  }, [activeQuickFilter])

  const selectedUserLabel = React.useMemo(() => {
    if (selectedUserId === ALL_USERS_VALUE) return "All users"
    const selectedUser = users.find((entry) => entry.id === selectedUserId)
    return userLabel(selectedUser) || selectedUser?.email || "Selected user"
  }, [selectedUserId, users])

  const handleTaskUpdated = React.useCallback((updatedTask: Task) => {
    setTasks((prev) => prev.map((task) => (task.id === updatedTask.id ? updatedTask : task)))
  }, [])

  const exportPayload = React.useMemo(() => {
    const columns = [
      "NR",
      "Title",
      "Assignee",
      "Other Assigneees",
      "Start Date",
      "Due Date",
      "Late",
      "Moved",
      "Frequency",
      "AM/PM",
      "Barazime",
      "Koha e Bz",
      "Status",
    ]

    const dateRangeLabel =
      dateFrom || dateTo
        ? ` | Dates: ${formatDateDMY(dateFrom) || "-"} - ${formatDateDMY(dateTo) || "-"}`
        : ""
    const doneLabel = activeQuickFilter === QUICK_FILTER_ALL ? ` | ${showDone ? "Including done" : "Open only"}` : ""

    return {
      title: `System Tasks Report | ${selectedUserLabel} | ${quickFilterLabel}${dateRangeLabel}${doneLabel}`,
      filename_prefix: "SYSTEM_TASKS_REPORTS",
      freeze_panes: "B5",
      columns,
      column_widths: [5, 40, 10, 10, 11, 11, 6, 7, 12, 8, 10, 10, 14],
      rows: filteredRows.map((row, index) => [
        String(index + 1),
        row.title,
        initialsSummary(row.assigneeEntries),
        initialsSummary(row.relatedAssignees),
        formatDateDMY(row.startDateIso),
        formatDateDMY(row.dueDateIso),
        row.lateDays != null ? String(row.lateDays) : "-",
        signedDaysLabel(row.movedDays),
        row.frequencyLabel,
        row.amPm,
        row.barazime,
        row.kohaBarazimeve,
        row.status,
      ]),
    }
  }, [activeQuickFilter, dateFrom, dateTo, filteredRows, quickFilterLabel, selectedUserLabel, showDone])

  const handleMarkDone = React.useCallback(
    async (taskId: string) => {
      const task = tasks.find((candidate) => candidate.id === taskId)
      if (!task) {
        toast.error("Task not found. Refresh the report and try again.")
        return
      }

      const actorIsAssignee = Boolean(
        user?.id &&
          (task.assigned_to === user.id || task.assignees?.some((assignee) => assignee.id === user.id))
      )
      const usesPrivilegedOverride = Boolean(
        !actorIsAssignee && (user?.role === "ADMIN" || user?.role === "MANAGER")
      )
      const promptMessage = usesPrivilegedOverride
        ? "Enter the reason for closing this task on behalf of the assignee."
        : "Before closing, add a comment describing the result of this task."
      const completionNote = window.prompt(promptMessage)?.trim()
      if (!completionNote) {
        toast.error(promptMessage)
        return
      }
      setUpdatingTaskIds((prev) => ({ ...prev, [taskId]: true }))
      try {
        if (!usesPrivilegedOverride) {
          const commentRes = await apiFetch(`/tasks/${taskId}/comment`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ comment: completionNote }),
          })
          if (!commentRes.ok) {
            const payload = await commentRes.json().catch(() => null)
            throw new Error(apiErrorMessage(payload, "The result comment could not be saved."))
          }
        }

        const updatePayload: Record<string, string> = { status: "DONE" }
        if (usesPrivilegedOverride) {
          updatePayload.completion_override_reason = completionNote
        }
        const res = await apiFetch(`/tasks/${taskId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(updatePayload),
        })

        if (!res.ok) {
          const payload = await res.json().catch(() => null)
          throw new Error(apiErrorMessage(payload, "Failed to mark task as done."))
        }

        const updatedTask = (await res.json()) as Task
        setTasks((prev) => prev.map((task) => (task.id === taskId ? updatedTask : task)))
        toast.success("Task marked as done")
      } catch (error) {
        const message = error instanceof Error ? error.message : "Failed to mark task as done."
        toast.error(message)
      } finally {
        setUpdatingTaskIds((prev) => {
          const next = { ...prev }
          delete next[taskId]
          return next
        })
      }
    },
    [apiFetch, tasks, user]
  )

  const handleExportExcel = React.useCallback(async () => {
    if (exportingExcel) return
    if (!exportPayload.rows.length) {
      toast.error("No rows available to export.")
      return
    }

    setExportingExcel(true)
    try {
      const res = await apiFetch("/exports/common-view.xlsx", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(exportPayload),
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
      link.download =
        parseFilenameFromDisposition(res.headers.get("content-disposition")) ?? "system_task_rows.xlsx"
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (error) {
      console.error("Failed to export system task rows", error)
      toast.error("Failed to export Excel.")
    } finally {
      setExportingExcel(false)
    }
  }, [apiFetch, exportPayload, exportingExcel])

  React.useEffect(() => {
    const container = tableContainerRef.current
    if (!container || loading || error) return

    const updateStickyHeaderMetrics = () => {
      const rect = container.getBoundingClientRect()
      const headerHeight = 40
      const table = container.querySelector("table")
      const headerCells = Array.from(container.querySelectorAll("thead th"))

      setStickyHeaderVisible(rect.top <= 0 && rect.bottom > headerHeight)
      setStickyHeaderLeft(rect.left)
      setStickyHeaderWidth(rect.width)
      setTableScrollLeft(container.scrollLeft)
      setStickyTableWidth(table instanceof HTMLTableElement ? table.scrollWidth : 0)
      setHeaderColumnWidths(headerCells.map((cell) => cell.getBoundingClientRect().width))
    }

    const handleContainerScroll = () => {
      setTableScrollLeft(container.scrollLeft)
    }

    updateStickyHeaderMetrics()

    const resizeObserver = new ResizeObserver(() => {
      updateStickyHeaderMetrics()
    })

    resizeObserver.observe(container)
    window.addEventListener("scroll", updateStickyHeaderMetrics, { passive: true })
    window.addEventListener("resize", updateStickyHeaderMetrics)
    container.addEventListener("scroll", handleContainerScroll, { passive: true })

    return () => {
      resizeObserver.disconnect()
      window.removeEventListener("scroll", updateStickyHeaderMetrics)
      window.removeEventListener("resize", updateStickyHeaderMetrics)
      container.removeEventListener("scroll", handleContainerScroll)
    }
  }, [error, filteredRows.length, loading])

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div>
            <CardTitle>System Tasks Report</CardTitle>
          </div>
          <Button onClick={() => void loadData()} variant="outline">
            Refresh
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-4">
            <div className="space-y-2">
              <Label>People</Label>
              <Select value={selectedUserId} onValueChange={setSelectedUserId}>
                <SelectTrigger>
                  <SelectValue placeholder="All users" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_USERS_VALUE}>All users</SelectItem>
                  {users.map((user) => (
                    <SelectItem key={user.id} value={user.id}>
                      {userLabel(user) || user.email}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>View</Label>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button type="button" variant="outline" className="justify-start">
                    {quickFilterLabel}
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="w-48">
                  <DropdownMenuLabel>Quick filters</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuCheckboxItem
                    checked={quickFilters.includes(QUICK_FILTER_ALL)}
                    onCheckedChange={(checked) => toggleQuickFilter(QUICK_FILTER_ALL, Boolean(checked))}
                  >
                    All
                  </DropdownMenuCheckboxItem>
                  <DropdownMenuCheckboxItem
                    checked={quickFilters.includes(QUICK_FILTER_TODAY)}
                    onCheckedChange={(checked) => toggleQuickFilter(QUICK_FILTER_TODAY, Boolean(checked))}
                  >
                    Today
                  </DropdownMenuCheckboxItem>
                  <DropdownMenuCheckboxItem
                    checked={quickFilters.includes(QUICK_FILTER_OVERDUE)}
                    onCheckedChange={(checked) => toggleQuickFilter(QUICK_FILTER_OVERDUE, Boolean(checked))}
                  >
                    Overdue
                  </DropdownMenuCheckboxItem>
                  <DropdownMenuCheckboxItem
                    checked={quickFilters.includes(QUICK_FILTER_TODAY_OVERDUE)}
                    onCheckedChange={(checked) =>
                      toggleQuickFilter(QUICK_FILTER_TODAY_OVERDUE, Boolean(checked))
                    }
                  >
                    Today + Overdue
                  </DropdownMenuCheckboxItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
            <div className="space-y-2">
              <Label>Date from</Label>
              <Input
                type="date"
                value={dateFrom}
                onChange={(event) => setDateFrom(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label>Date to</Label>
              <Input
                type="date"
                value={dateTo}
                onChange={(event) => setDateTo(event.target.value)}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <CardTitle>System Task Rows</CardTitle>
          <div className="flex items-center gap-3">
            <div className="text-sm text-slate-500">{filteredRows.length} rows</div>
            <Button
              type="button"
              variant="outline"
              onClick={() => void handleExportExcel()}
              disabled={loading || Boolean(error) || !filteredRows.length || exportingExcel}
            >
              {exportingExcel ? "Exporting..." : "Export Excel"}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="text-sm text-slate-500">Loading generated system tasks...</div>
          ) : error ? (
            <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          ) : (
            <div className="space-y-4">
              {stickyHeaderVisible ? (
                <div
                  aria-hidden="true"
                  className="fixed top-0 z-30 overflow-hidden border border-slate-200 bg-slate-50 shadow-sm"
                  style={{ left: stickyHeaderLeft, width: stickyHeaderWidth }}
                >
                  <table
                    className="caption-bottom text-sm"
                    style={{
                      width: stickyTableWidth || undefined,
                      transform: `translateX(-${tableScrollLeft}px)`,
                    }}
                  >
                    <thead>
                      <tr className="border-b bg-slate-50">
                        {TABLE_HEADERS.map((header, index) => (
                          <th
                            key={header}
                            className="text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap"
                            style={{
                              width: headerColumnWidths[index],
                              minWidth: headerColumnWidths[index],
                              maxWidth: headerColumnWidths[index],
                            }}
                          >
                            {header}
                          </th>
                        ))}
                      </tr>
                    </thead>
                  </table>
                </div>
              ) : null}

              <Table
                containerClassName="rounded-lg border border-slate-200 bg-white"
                containerProps={{ ref: tableContainerRef }}
                className="min-w-[1660px] text-sm"
              >
                <TableHeader className="sticky top-0 z-20 bg-slate-50 [&_th]:sticky [&_th]:top-0 [&_th]:z-20 [&_th]:bg-slate-50 [&_th]:shadow-[inset_0_-1px_0_0_rgb(226_232_240)]">
                  <TableRow className="bg-slate-50">
                    {TABLE_HEADERS.map((header) => (
                      <TableHead key={header}>{header}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredRows.length ? (
                    filteredRows.map((row, index) => (
                      <TableRow key={row.id}>
                        <TableCell className="font-semibold text-slate-700">{index + 1}</TableCell>
                        <TableCell className="min-w-[320px] whitespace-normal font-medium text-slate-800">
                          {row.title}
                        </TableCell>
                        <TableCell>
                          {row.assigneeEntries.length > MAX_SAME_TASK_INITIALS ? (
                            <span className="text-sm font-medium text-slate-700" title={row.assigneeLabel}>
                              All
                            </span>
                          ) : row.assigneeEntries.length ? (
                            <div className="flex min-w-[84px] flex-wrap gap-1" title={row.assigneeLabel}>
                              {row.assigneeEntries.map((assignee) => (
                                <span
                                  key={assignee.id}
                                  className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[11px] text-slate-700"
                                  title={assignee.label}
                                >
                                  {assignee.initials}
                                </span>
                              ))}
                            </div>
                          ) : (
                            "-"
                          )}
                        </TableCell>
                        <TableCell>
                          {row.relatedAssignees.length > MAX_SAME_TASK_INITIALS ? (
                            <span className="text-sm font-medium text-slate-700">All</span>
                          ) : row.relatedAssignees.length ? (
                            <div className="flex min-w-[84px] flex-wrap gap-1">
                              {row.relatedAssignees.map((assignee) => (
                                <span
                                  key={assignee.id}
                                  className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[11px] text-slate-700"
                                  title={assignee.label}
                                >
                                  {assignee.initials}
                                </span>
                              ))}
                            </div>
                          ) : (
                            "-"
                          )}
                        </TableCell>
                        <TableCell>{formatDateDMY(row.startDateIso)}</TableCell>
                        <TableCell>{formatDateDMY(row.dueDateIso)}</TableCell>
                        <TableCell>
                          {row.lateDays != null ? (
                            <Badge variant="destructive">{row.lateDays}</Badge>
                          ) : (
                            "-"
                          )}
                        </TableCell>
                        <TableCell>{signedDaysLabel(row.movedDays)}</TableCell>
                        <TableCell>{row.frequencyLabel}</TableCell>
                        <TableCell>{row.amPm}</TableCell>
                        <TableCell>{row.barazime}</TableCell>
                        <TableCell>{row.kohaBarazimeve}</TableCell>
                        <TableCell>
                          <span className={`inline-flex rounded px-2 py-1 text-xs font-medium uppercase ${row.statusClassName}`}>
                            {row.status === "PAUSED" ? "Stopped" : row.status === "WAITING_CONFIRMATION" ? "WFC INT" : row.status}
                          </span>
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-2">
                            {row.canEdit ? (
                              <Button size="sm" variant="outline" onClick={() => setEditingTask(row.task)}>
                                Edit
                              </Button>
                            ) : (
                              <span className="text-xs text-slate-400">No access</span>
                            )}
                            {row.canMarkDone ? (
                              <Button
                                size="sm"
                                className="bg-emerald-500 text-white hover:bg-emerald-600"
                                onClick={() => void handleMarkDone(row.id)}
                                disabled={Boolean(updatingTaskIds[row.id])}
                              >
                                {updatingTaskIds[row.id] ? "Saving..." : "Done"}
                              </Button>
                            ) : null}
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell colSpan={14} className="py-8 text-center text-sm text-slate-500">
                        No generated system tasks match the selected filters.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>

              {activeQuickFilter === QUICK_FILTER_ALL ? (
                <div className="flex justify-center border-t pt-3">
                  <Button type="button" variant="ghost" size="sm" onClick={() => setShowDone((prev) => !prev)}>
                    {showDone ? "Hide done" : "Show done"}
                  </Button>
                </div>
              ) : null}
            </div>
          )}
        </CardContent>
      </Card>

      <TaskEditDialog
        task={editingTask}
        open={Boolean(editingTask)}
        onOpenChange={(open) => {
          if (!open) setEditingTask(null)
        }}
        onUpdated={handleTaskUpdated}
      />
    </div>
  )
}
