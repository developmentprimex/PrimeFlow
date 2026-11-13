"use client"

import * as React from "react"
import { CollapsibleTaskTitle } from "@/components/collapsible-task-title"
import { TaskOneHMarkerEditor } from "@/components/task-one-h-marker-editor"
import { TaskMarkerComment } from "@/components/task-marker-comment"
import { useVisibleRefresh } from "@/lib/use-visible-refresh"
import { toast } from "sonner"

import { TaskEditDialog } from "@/components/task-edit-dialog"
import {
  DailyRlzCommentField,
  DailyRlzReasonCell,
  dailyRlzStateByTask,
} from "@/components/daily-rlz-panel"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useAuth } from "@/lib/auth"
import { formatDateDMY, toDateInputValue } from "@/lib/dates"
import { renderMarkedNoteContent } from "@/lib/note-markup"
import type { DailyReportResponse, Department, SystemTaskOut, Task, User } from "@/lib/types"
import { weeklyPlanStatusBgClass } from "@/lib/weekly-plan-status"

const ALL_USERS_VALUE = "__all__"
const VIEW_ALL = "all"
const VIEW_TODAY = "today"
const VIEW_OVERDUE = "overdue"
const VIEW_TODAY_OVERDUE = "today_overdue"
const ONE_H_REPORT_SLOT_NONE_VALUE = "__none__"
const ONE_H_REPORT_SLOT_OPTIONS = ["10:00", "11:00", "11:50", "14:20", "16:00"] as const

type ViewFilter = typeof VIEW_ALL | typeof VIEW_TODAY | typeof VIEW_OVERDUE | typeof VIEW_TODAY_OVERDUE

type RowView = {
  task: Task
  id: string
  title: string
  typeLabel: string
  period: "AM" | "PM" | "AM/PM"
  oneHReportSlot: string
  assigneeIds: string[]
  assigneeLabel: string
  assigneeInitials: string
  systemFrequency: string
  systemFrequencyLabel: string
  systemFrequencyDisplayLabel: string
  occurrenceDateIso: string
  createdDateIso: string
  startDateIso: string
  dueDateIso: string
  priority: string
  lateDays: number | null
  status: string
  statusClassName: string
  canEdit: boolean
  canMarkDone: boolean
}

type FinanceExportRow = {
  typeLabel: string
  subtype: string
  frequency: string
  dateLabel: string
  bzMe: string
  kohaBz: string
  department: string
  period: string
  title: string
  description: string
  details: string
  status: string
  userInitials: string
}

function userLabel(user?: User | null) {
  if (!user) return ""
  return user.full_name || user.username || user.email || ""
}

function initials(src: string) {
  return src
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("")
}

function parseFilenameFromDisposition(headerValue: string | null) {
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

function resolvePeriod(finishPeriod?: Task["finish_period"] | null): RowView["period"] {
  if (finishPeriod === "PM") return "PM"
  if (finishPeriod === "AM") return "AM"
  return "AM/PM"
}

function fastReportSubtypeShort(task: Task) {
  if (task.is_bllok) return "BLL"
  if (task.is_1h_report) return "1H"
  if (task.is_r1) return "R1"
  if (task.is_personal) return "P:"
  if (task.ga_note_origin_id) return "GA"
  return "N"
}

function financeTaskTypeLabel(task: Task) {
  if (task.system_template_origin_id || task.task_type === "system") return "SYS"
  if (task.project_id) return "PRJK"
  return fastReportSubtypeShort(task)
}

function systemFrequencyShortLabel(frequency?: string | null) {
  const normalized = (frequency || "").toUpperCase()
  if (normalized === "DAILY") return "D"
  if (normalized === "WEEKLY") return "W"
  if (normalized === "MONTHLY") return "M"
  if (normalized === "YEARLY") return "Y"
  if (normalized === "3_MONTHS") return "3M"
  if (normalized === "6_MONTHS") return "6M"
  return normalized ? normalized.slice(0, 1) : ""
}

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

function normalizeOneHReportSlot(value?: string | null) {
  const normalized = (value || "").trim()
  return ONE_H_REPORT_SLOT_OPTIONS.includes(normalized as (typeof ONE_H_REPORT_SLOT_OPTIONS)[number]) ? normalized : ""
}

function getFinanceSlotDisplay(task: Task) {
  if (task.system_template_origin_id || task.task_type === "system") return "SYS"
  if (task.is_bllok) return "BLL"
  if (task.is_personal) return "P"
  return "-"
}

function isoOrEmpty(value?: string | null) {
  return toDateInputValue(value || null)
}

function endOfCurrentWeekIso(referenceDate: Date) {
  const weekEnd = new Date(referenceDate)
  const mondayBasedDay = (weekEnd.getDay() + 6) % 7
  weekEnd.setDate(weekEnd.getDate() + (6 - mondayBasedDay))
  return toDateInputValue(weekEnd)
}

function taskAssigneeInfo(task: Task, usersById: Map<string, User>) {
  const seen = new Set<string>()
  const ids: string[] = []
  const labels: string[] = []

  const pushUser = (id?: string | null, fallbackLabel?: string | null) => {
    if (!id || seen.has(id)) return
    seen.add(id)
    ids.push(id)
    const label = userLabel(usersById.get(id)) || fallbackLabel || id
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
    initials: labels.length ? labels.map(initials).filter(Boolean).join(", ") : "-",
  }
}

function isOpenStatus(status: string) {
  return status === "TODO" || status === "IN_PROGRESS" || status === "WAITING_CONFIRMATION"
}

function rowMatchesToday(row: RowView, todayIso: string) {
  if (row.startDateIso && row.dueDateIso) {
    const start = row.startDateIso <= row.dueDateIso ? row.startDateIso : row.dueDateIso
    const end = row.startDateIso <= row.dueDateIso ? row.dueDateIso : row.startDateIso
    return start <= todayIso && todayIso <= end
  }
  return [row.startDateIso, row.dueDateIso].filter(Boolean).includes(todayIso)
}

function isIsoWithinInclusiveRange(value: string, from: string, to: string) {
  if (!value) return false
  if (from && value < from) return false
  if (to && value > to) return false
  return true
}

function rowMatchesDateFilter(row: RowView, dateFrom: string, dateTo: string) {
  const candidateDates = [row.startDateIso, row.dueDateIso].filter(Boolean)
  if (!candidateDates.length) return false
  if (!dateFrom && !dateTo) return true
  if (dateFrom && !dateTo) return candidateDates.includes(dateFrom)
  if (!dateFrom && dateTo) return candidateDates.includes(dateTo)
  const start = dateFrom <= dateTo ? dateFrom : dateTo
  const end = dateFrom <= dateTo ? dateTo : dateFrom
  return candidateDates.some((value) => isIsoWithinInclusiveRange(value, start, end))
}

function rowSortDate(row: RowView) {
  return row.dueDateIso || row.startDateIso || ""
}

function rowPriorityRank(row: RowView) {
  const isLate = (row.lateDays ?? 0) > 0
  const isOpen = isOpenStatus(row.status)

  if (isLate && isOpen) return 0
  if (row.status === "TODO") return 1
  if (row.status === "IN_PROGRESS") return 2
  if (row.status === "WAITING_CONFIRMATION") return 3
  if (isOpen) return 4
  if (row.status === "DONE") return 6
  return 5
}

export default function DepartmentKanban() {
  const { apiFetch, user } = useAuth()
  const [department, setDepartment] = React.useState<Department | null>(null)
  const [tasks, setTasks] = React.useState<Task[]>([])
  const [users, setUsers] = React.useState<User[]>([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [selectedUserId, setSelectedUserId] = React.useState<string>(ALL_USERS_VALUE)
  const [viewFilter, setViewFilter] = React.useState<ViewFilter>(VIEW_ALL)
  const [dateFrom, setDateFrom] = React.useState("")
  const [dateTo, setDateTo] = React.useState("")
  const [showDone, setShowDone] = React.useState(false)
  const [updatingTaskIds, setUpdatingTaskIds] = React.useState<Record<string, boolean>>({})
  const [exportingExcel, setExportingExcel] = React.useState(false)
  const [editingTask, setEditingTask] = React.useState<Task | null>(null)
  const [viewingDescriptionTask, setViewingDescriptionTask] = React.useState<Task | null>(null)
  const [dailyReport, setDailyReport] = React.useState<DailyReportResponse | null>(null)
  const [systemTaskFrequencyByTemplateId, setSystemTaskFrequencyByTemplateId] = React.useState<Record<string, string>>({})
  const todayIso = React.useMemo(() => toDateInputValue(new Date()), [])
  const currentWeekEndIso = React.useMemo(() => endOfCurrentWeekIso(new Date()), [])

  const loadData = React.useCallback(async () => {
    setLoading(true)
    setError(null)

    try {
      const [departmentsRes, usersRes] = await Promise.all([apiFetch("/departments"), apiFetch("/users")])
      if (!departmentsRes.ok || !usersRes.ok) {
        throw new Error("Unable to load Finance department data.")
      }

      const nextDepartments = (await departmentsRes.json()) as Department[]
      const nextUsers = (await usersRes.json()) as User[]
      const financeDepartment =
        nextDepartments.find((entry) => entry.code.toUpperCase() === "FIN") ||
        nextDepartments.find((entry) => entry.name.trim().toLowerCase() === "finance")

      if (!financeDepartment) {
        throw new Error("Finance department was not found.")
      }

      const [tasksRes, systemTasksRes] = await Promise.all([
        apiFetch(`/tasks?department_id=${encodeURIComponent(financeDepartment.id)}&include_done=true&include_all_done=true`),
        apiFetch(`/system-tasks?department_id=${encodeURIComponent(financeDepartment.id)}`),
      ])

      if (!tasksRes.ok) {
        throw new Error("Unable to load Finance tasks.")
      }

      const nextTasks = (await tasksRes.json()) as Task[]
      const systemTasks = systemTasksRes.ok ? ((await systemTasksRes.json()) as SystemTaskOut[]) : []
      const nextSystemTaskFrequencyByTemplateId = systemTasks.reduce<Record<string, string>>((acc, item) => {
        if (item.template_id && item.frequency) acc[item.template_id] = item.frequency
        return acc
      }, {})
      const financeUsers = nextUsers.filter(
        (entry) => entry.is_active && entry.department_id === financeDepartment.id
      )

      setDepartment(financeDepartment)
      setUsers(nextUsers)
      setTasks(nextTasks)
      setSystemTaskFrequencyByTemplateId(nextSystemTaskFrequencyByTemplateId)
      setSelectedUserId((prev) => {
        if (prev !== ALL_USERS_VALUE && nextUsers.some((entry) => entry.id === prev)) return prev
        if (financeUsers.length === 1) return financeUsers[0]!.id
        return ALL_USERS_VALUE
      })
    } catch (loadError) {
      const message = loadError instanceof Error ? loadError.message : "Unable to load Finance tasks."
      setError(message)
    } finally {
      setLoading(false)
    }
  }, [apiFetch])

  React.useEffect(() => {
    void loadData()
  }, [loadData])

  const dailyReportUserId = selectedUserId === ALL_USERS_VALUE ? user?.id : selectedUserId

  const refreshDailyReport = React.useCallback(async () => {
    if (!department?.id || !dailyReportUserId) {
      setDailyReport(null)
      return
    }

    const query = new URLSearchParams({
      day: todayIso,
      department_id: department.id,
      user_id: dailyReportUserId,
    })
    const response = await apiFetch(`/reports/daily?${query.toString()}`)
    if (!response.ok) throw new Error("Unable to load today's Daily Report details.")
    setDailyReport((await response.json()) as DailyReportResponse)
  }, [apiFetch, dailyReportUserId, department?.id, todayIso])

  useVisibleRefresh(async () => { await loadData(); await refreshDailyReport() })

  React.useEffect(() => {
    let cancelled = false

    const loadDailyReport = async () => {
      setDailyReport(null)
      try {
        if (!department?.id || !dailyReportUserId) {
          setDailyReport(null)
          return
        }
        const query = new URLSearchParams({
          day: todayIso,
          department_id: department.id,
          user_id: dailyReportUserId,
        })
        const response = await apiFetch(`/reports/daily?${query.toString()}`)
        if (!response.ok) throw new Error("Unable to load today's Daily Report details.")
        const payload = (await response.json()) as DailyReportResponse
        if (!cancelled) setDailyReport(payload)
      } catch {
        if (!cancelled) setDailyReport(null)
      }
    }

    void loadDailyReport()
    return () => {
      cancelled = true
    }
  }, [apiFetch, dailyReportUserId, department?.id, todayIso])

  const dailyRlzStates = React.useMemo(() => dailyRlzStateByTask(dailyReport), [dailyReport])

  const canManageDailyRlz = user?.role === "ADMIN" || user?.role === "MANAGER"
  const dailyRlzSubjectUserId =
    canManageDailyRlz && dailyReportUserId && dailyReportUserId !== user?.id ? dailyReportUserId : undefined

  const dailyRlzStateForRow = React.useCallback(
    (taskId: string) => {
      const state = dailyRlzStates.get(taskId)
      if (!state || dailyReportUserId === user?.id || canManageDailyRlz) return state
      return { ...state, is_editable: false }
    },
    [canManageDailyRlz, dailyReportUserId, dailyRlzStates, user?.id]
  )

  const usersById = React.useMemo(() => {
    const map = new Map<string, User>()
    for (const entry of users) {
      map.set(entry.id, entry)
    }
    return map
  }, [users])

  const rows = React.useMemo<RowView[]>(() => {
    return [...tasks]
      .map((task) => {
        const assigneeInfo = taskAssigneeInfo(task, usersById)
        const statusValue = task.status || "TODO"
        const isManagerView = user?.role === "ADMIN" || user?.role === "MANAGER"
        const isAssignedToCurrentUser = Boolean(user?.id && assigneeInfo.ids.includes(user.id))
        const canEdit = Boolean((isManagerView || isAssignedToCurrentUser) && statusValue !== "DONE")
        const systemFrequency = task.system_template_origin_id
          ? systemTaskFrequencyByTemplateId[task.system_template_origin_id] || ""
          : ""

        return {
          task,
          id: task.id,
          title: task.title || "-",
          typeLabel: financeTaskTypeLabel(task),
          period: resolvePeriod(task.finish_period),
          oneHReportSlot: normalizeOneHReportSlot(task.one_h_report_slot),
          assigneeIds: assigneeInfo.ids,
          assigneeLabel: assigneeInfo.label,
          assigneeInitials: assigneeInfo.initials,
          systemFrequency,
          systemFrequencyLabel: systemFrequencyShortLabel(systemFrequency),
          systemFrequencyDisplayLabel: systemFrequencyDisplayLabel(systemFrequency),
          occurrenceDateIso: isoOrEmpty(task.origin_run_at || task.start_date || task.due_date),
          createdDateIso: isoOrEmpty(task.created_at),
          startDateIso: isoOrEmpty(task.start_date),
          dueDateIso: isoOrEmpty(task.due_date),
          priority: task.priority || "NORMAL",
          lateDays: task.late_days ?? null,
          status: statusValue,
          statusClassName: weeklyPlanStatusBgClass(statusValue),
          canEdit,
          canMarkDone: canEdit && statusValue !== "DONE",
        }
      })
      .sort((a, b) => {
        const rankDiff = rowPriorityRank(a) - rowPriorityRank(b)
        if (rankDiff !== 0) return rankDiff

        const aLate = a.lateDays ?? 0
        const bLate = b.lateDays ?? 0
        if (aLate !== bLate) return bLate - aLate

        const aDate = rowSortDate(a)
        const bDate = rowSortDate(b)
        if (aDate !== bDate) return aDate.localeCompare(bDate)

        return a.title.localeCompare(b.title)
      })
  }, [systemTaskFrequencyByTemplateId, tasks, user?.id, user?.role, usersById])

  const selectableUsers = React.useMemo(() => {
    const ids = new Set<string>()
    for (const row of rows) {
      for (const id of row.assigneeIds) ids.add(id)
    }

    return users
      .filter((entry) => ids.has(entry.id))
      .sort((a, b) => (userLabel(a) || a.email).localeCompare(userLabel(b) || b.email))
  }, [rows, users])

  React.useEffect(() => {
    if (selectedUserId === ALL_USERS_VALUE) return
    if (selectableUsers.some((entry) => entry.id === selectedUserId)) return
    setSelectedUserId(ALL_USERS_VALUE)
  }, [selectableUsers, selectedUserId])

  const filteredRows = React.useMemo(() => {
    const visibleRows = rows.filter((row) => {
      if (
        row.task.system_template_origin_id &&
        row.occurrenceDateIso &&
        row.occurrenceDateIso > currentWeekEndIso
      ) {
        return false
      }

      if (selectedUserId !== ALL_USERS_VALUE && !row.assigneeIds.includes(selectedUserId)) {
        return false
      }

      return rowMatchesDateFilter(row, dateFrom, dateTo)
    })

    if (viewFilter === VIEW_TODAY) {
      return visibleRows.filter((row) => row.status !== "DONE" && rowMatchesToday(row, todayIso))
    }
    if (viewFilter === VIEW_OVERDUE) {
      return visibleRows.filter((row) => row.status !== "DONE" && (row.lateDays ?? 0) > 0)
    }
    if (viewFilter === VIEW_TODAY_OVERDUE) {
      return visibleRows.filter(
        (row) =>
          row.status !== "DONE" && (rowMatchesToday(row, todayIso) || (row.lateDays ?? 0) > 0)
      )
    }

    const openRows = visibleRows.filter((row) => row.status !== "DONE")
    if (!showDone) return openRows
    const doneRows = visibleRows.filter((row) => row.status === "DONE")
    return [...openRows, ...doneRows]
  }, [currentWeekEndIso, dateFrom, dateTo, rows, selectedUserId, showDone, todayIso, viewFilter])

  const selectedUserLabel = React.useMemo(() => {
    if (selectedUserId === ALL_USERS_VALUE) return "All people"
    const selectedUser = users.find((entry) => entry.id === selectedUserId)
    return userLabel(selectedUser) || selectedUser?.email || "Selected user"
  }, [selectedUserId, users])

  const financeExportRows = React.useMemo<FinanceExportRow[]>(() => {
    const departmentLabel = department?.code || department?.name || "FIN"
    return filteredRows.map((row) => {
      const task = row.task
      const alignmentInitials = (task.alignment_user_ids || [])
        .map((id) => {
          const entry = usersById.get(id)
          return entry ? initials(userLabel(entry)) : ""
        })
        .filter(Boolean)
        .join(", ")

      const assigneeInitials = Array.from(new Set(row.assigneeIds))
        .map((id) => {
          const entry = usersById.get(id)
          if (entry) return initials(userLabel(entry))
          const fallback = task.assignees?.find((assignee) => assignee.id === id)
          return fallback ? initials(fallback.full_name || fallback.username || fallback.email || "") : ""
        })
        .filter(Boolean)
        .join(", ")

      return {
        typeLabel: task.system_template_origin_id ? "SYS" : task.project_id ? "PRJK" : "FT",
        subtype: task.system_template_origin_id ? "SYS" : task.project_id ? "-" : fastReportSubtypeShort(task),
        frequency: row.systemFrequencyLabel,
        dateLabel: row.dueDateIso ? formatDateDMY(row.dueDateIso) : row.startDateIso ? formatDateDMY(row.startDateIso) : "-",
        bzMe: alignmentInitials,
        kohaBz: "-",
        department: departmentLabel,
        period: resolvePeriod(task.finish_period),
        title: task.title || "-",
        description: task.description || "",
        details: formatInternalDetails(task.internal_notes),
        status: row.status,
        userInitials: assigneeInitials,
      }
    })
  }, [department?.code, department?.name, filteredRows, usersById])

  const handleTaskUpdated = React.useCallback((updatedTask: Task) => {
    setTasks((prev) => prev.map((task) => (task.id === updatedTask.id ? updatedTask : task)))
  }, [])

  const saveOneHReportSlot = React.useCallback(
    async (taskId: string, slotValue: string) => {
      const nextSlot = slotValue === ONE_H_REPORT_SLOT_NONE_VALUE ? null : normalizeOneHReportSlot(slotValue)
      setUpdatingTaskIds((prev) => ({ ...prev, [taskId]: true }))
      try {
        const res = await apiFetch(`/tasks/${taskId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ one_h_report_slot: nextSlot }),
        })

        if (!res.ok) {
          let detail = "Failed to save 1H slot."
          try {
            const payload = (await res.json()) as { detail?: string }
            if (payload?.detail) detail = payload.detail
          } catch {
            // Ignore JSON parse errors for non-JSON error bodies.
          }
          throw new Error(detail)
        }

        const updatedTask = (await res.json()) as Task
        handleTaskUpdated(updatedTask)
        toast.success("Slot updated")
      } catch (slotError) {
        const message = slotError instanceof Error ? slotError.message : "Failed to save 1H slot."
        toast.error(message)
      } finally {
        setUpdatingTaskIds((prev) => {
          const next = { ...prev }
          delete next[taskId]
          return next
        })
      }
    },
    [apiFetch, handleTaskUpdated]
  )

  const handleMarkDone = React.useCallback(
    async (taskId: string) => {
      const task = tasks.find((item) => item.id === taskId)
      const skipsResultComment = Boolean(
        task && (
          task.ga_note_origin_id || task.plan_note_origin_id || task.is_bllok || task.is_1h_report || task.is_r1 || task.is_personal
        )
      )
      const resultComment = skipsResultComment
        ? null
        : window.prompt("Para mbylljes, shto komentin për rezultatin e kësaj detyre.")?.trim()
      if (!skipsResultComment && !resultComment) {
        toast.error("Para mbylljes, shto komentin për rezultatin e kësaj detyre.")
        return
      }
      setUpdatingTaskIds((prev) => ({ ...prev, [taskId]: true }))

      try {
        if (resultComment) {
          const commentRes = await apiFetch(`/tasks/${taskId}/comment`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ comment: resultComment }),
          })
          if (!commentRes.ok) throw new Error("Komenti i rezultatit nuk u ruajt.")
        }
        const res = await apiFetch(`/tasks/${taskId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: "DONE" }),
        })

        if (!res.ok) {
          let detail = "Failed to mark task as done."
          try {
            const payload = (await res.json()) as { detail?: string }
            if (payload?.detail) detail = payload.detail
          } catch {
            // Ignore JSON parse errors for non-JSON error bodies.
          }
          throw new Error(detail)
        }

        const updatedTask = (await res.json()) as Task
        setTasks((prev) => prev.map((task) => (task.id === taskId ? updatedTask : task)))
        toast.success("Task marked as done")
      } catch (markError) {
        const message = markError instanceof Error ? markError.message : "Failed to mark task as done."
        toast.error(message)
      } finally {
        setUpdatingTaskIds((prev) => {
          const next = { ...prev }
          delete next[taskId]
          return next
        })
      }
    },
    [apiFetch, tasks]
  )

  const handleExportExcel = React.useCallback(async () => {
    if (exportingExcel || !financeExportRows.length) return
    setExportingExcel(true)
    try {
      const usersInitials = Array.from(
        new Set(
          financeExportRows
            .map((row) => row.userInitials.trim().toUpperCase())
            .filter(Boolean)
        )
      ).sort().join("_")

      const res = await apiFetch(`/exports/all-tasks-report.xlsx`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: "ALL FINANCE TASK REPORT",
          usersInitials,
          rows: financeExportRows,
        }),
      })

      if (!res.ok) {
        let detail = "Failed to export Finance tasks."
        try {
          detail = (await res.text()) || detail
        } catch {
          // Ignore body parse errors for export failures.
        }
        throw new Error(detail)
      }

      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = parseFilenameFromDisposition(res.headers.get("content-disposition")) || "ALL_FINANCE_TASK_REPORT.xlsx"
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (exportError) {
      const message = exportError instanceof Error ? exportError.message : "Failed to export Finance tasks."
      console.error("Failed to export Finance tasks", exportError)
      toast.error(message)
    } finally {
      setExportingExcel(false)
    }
  }, [apiFetch, exportingExcel, financeExportRows])

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div className="space-y-1">
            <CardTitle>{department?.name || "Finance"} Department Tasks</CardTitle>
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
                  <SelectValue placeholder="All people" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_USERS_VALUE}>All people</SelectItem>
                  {selectableUsers.map((entry) => (
                    <SelectItem key={entry.id} value={entry.id}>
                      {userLabel(entry) || entry.email}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>View</Label>
              <Select value={viewFilter} onValueChange={(value) => setViewFilter(value as ViewFilter)}>
                <SelectTrigger>
                  <SelectValue placeholder="Choose a view" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={VIEW_ALL}>All</SelectItem>
                  <SelectItem value={VIEW_TODAY}>Today</SelectItem>
                  <SelectItem value={VIEW_OVERDUE}>Overdue</SelectItem>
                  <SelectItem value={VIEW_TODAY_OVERDUE}>Today + Overdue</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Date from</Label>
              <Input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>Date to</Label>
              <Input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div className="space-y-1">
            <CardTitle>Finance Tasks</CardTitle>
            <CardDescription>
              {filteredRows.length} rows for {selectedUserLabel}
            </CardDescription>
          </div>
          <Button
            variant="outline"
            onClick={() => void handleExportExcel()}
            disabled={loading || !!error || !financeExportRows.length || exportingExcel}
          >
            {exportingExcel ? "Exporting..." : "Export Excel"}
          </Button>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="text-sm text-slate-500">Loading Finance tasks...</div>
          ) : error ? (
            <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          ) : (
            <div className="space-y-4">
              <Table className="min-w-[2100px] table-fixed" containerClassName="rounded-lg border border-slate-200 bg-white">
                <colgroup>
                  {[44, 480, 64, 90, 112, 48, 105, 105, 105, 65, 100, 120, 170, 190, 90].map((width, index) => (
                    <col key={index} style={{ width }} />
                  ))}
                </colgroup>
                <TableHeader className="bg-slate-50">
                  <TableRow className="bg-slate-50">
                    <TableHead>NR</TableHead>
                    <TableHead className="w-[480px] min-w-[480px]">Title</TableHead>
                    <TableHead className="w-16 min-w-16 max-w-16 px-0 text-center" title="Frequency">Freq.</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead className="w-28 min-w-28 px-1 text-center" title="1H report time">
                      Slot
                    </TableHead>
                    <TableHead className="w-12 min-w-12 px-1 text-center" title="Assignee">Asg</TableHead>
                    <TableHead className="text-xs font-normal text-slate-400">Created</TableHead>
                    <TableHead>Start Date</TableHead>
                    <TableHead>Due Date</TableHead>
                    <TableHead>Late</TableHead>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="min-w-[170px]">Arsyeja</TableHead>
                    <TableHead className="min-w-[190px]">Koment</TableHead>
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredRows.length ? (
                    filteredRows.map((row, index) => (
                      <TableRow key={row.id}>
                        <TableCell className="font-semibold text-slate-700">{index + 1}</TableCell>
                        <TableCell className="w-[480px] min-w-[480px] whitespace-normal font-medium text-slate-800">
                          <div className="relative flex w-full items-start gap-2 pr-8">
                            <span className="min-w-0 flex-1 whitespace-pre-wrap break-words">
                              <TaskMarkerComment comment={row.task.one_h_marker_comment} taskId={row.task.id} />
                              <CollapsibleTaskTitle
                                title={row.title}
                                alignToggle
                                renderTitle={(title) => title.includes("[[") ? renderMarkedNoteContent(title, title) : title}
                              />
                            </span>
                          </div>
                        </TableCell>
                        <TableCell className="w-16 min-w-16 max-w-16 px-0 text-center">
                          {row.systemFrequencyDisplayLabel ? (
                            <span
                              className="inline-flex h-5 items-center justify-center rounded-full border border-slate-200 px-2 text-[10px] font-semibold text-slate-600"
                              title={systemFrequencyTitle(row.systemFrequency)}
                            >
                              {row.systemFrequencyDisplayLabel}
                            </span>
                          ) : null}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline">{row.typeLabel}</Badge>
                        </TableCell>
                        <TableCell className="w-28 min-w-28 px-1 text-center">
                          {row.task.is_1h_report || row.task.is_r1 || row.oneHReportSlot ? (
                            row.canEdit ? (
                              <select
                                className="h-7 w-full rounded-md border border-amber-300 bg-amber-50 px-2 text-[11px] font-semibold text-amber-900 shadow-sm outline-none focus:border-amber-500 disabled:cursor-not-allowed disabled:opacity-60"
                                value={row.oneHReportSlot || ONE_H_REPORT_SLOT_NONE_VALUE}
                                disabled={Boolean(updatingTaskIds[row.id])}
                                aria-label="1H report time"
                                onClick={(event) => event.stopPropagation()}
                                onChange={(event) => {
                                  event.stopPropagation()
                                  void saveOneHReportSlot(row.id, event.target.value)
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
                              <span
                                className="inline-flex h-5 items-center justify-center rounded-full border border-slate-200 px-2 text-[10px] font-semibold text-slate-600"
                                title="1H report time"
                              >
                                {row.oneHReportSlot || "No slot"}
                              </span>
                            )
                          ) : (
                            getFinanceSlotDisplay(row.task)
                          )}
                        </TableCell>
                        <TableCell className="w-12 min-w-12 px-1 text-center" title={row.assigneeLabel}>
                          <span className="text-xs font-semibold text-slate-700">{row.assigneeInitials}</span>
                        </TableCell>
                        <TableCell className="text-xs font-normal text-slate-400">
                          {formatDateDMY(row.createdDateIso)}
                        </TableCell>
                        <TableCell>{formatDateDMY(row.startDateIso)}</TableCell>
                        <TableCell>{formatDateDMY(row.dueDateIso)}</TableCell>
                        <TableCell>
                          {row.lateDays != null && row.lateDays > 0 ? (
                            <Badge variant="destructive">{row.lateDays}</Badge>
                          ) : (
                            "-"
                          )}
                        </TableCell>
                        <TableCell className="w-[100px] min-w-[100px] px-2 py-2 text-center align-middle">
                          {row.typeLabel === "SYS" ? (
                            <span className="text-xs font-semibold text-slate-600">SYS</span>
                          ) : (
                            <TaskOneHMarkerEditor taskId={row.task.id} marker={row.task.one_h_marker} className="mx-auto shrink-0" />
                          )}
                        </TableCell>
                        <TableCell>
                          <span className={`inline-flex rounded px-2 py-1 text-xs font-medium uppercase ${row.statusClassName}`}>
                            {row.status}
                          </span>
                        </TableCell>
                        <TableCell className="min-w-[170px]">
                          <DailyRlzReasonCell
                            taskId={row.id}
                            day={todayIso}
                            state={dailyRlzStateForRow(row.id)}
                            subjectUserId={dailyRlzSubjectUserId}
                            onSaved={refreshDailyReport}
                          />
                        </TableCell>
                        <TableCell className="min-w-[190px]">
                          <DailyRlzCommentField
                            taskId={row.id}
                            day={todayIso}
                            state={dailyRlzStateForRow(row.id)}
                            subjectUserId={dailyRlzSubjectUserId}
                            onSaved={refreshDailyReport}
                          />
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-2">
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => setViewingDescriptionTask(row.task)}
                            >
                              Description
                            </Button>
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
                      <TableCell colSpan={15} className="py-8 text-center text-sm text-slate-500">
                        No Finance tasks match the selected filters.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>

              {viewFilter === VIEW_ALL ? (
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
        showDescriptionField
      />

      <Dialog
        open={Boolean(viewingDescriptionTask)}
        onOpenChange={(open) => {
          if (!open) setViewingDescriptionTask(null)
        }}
      >
        <DialogContent className="flex flex-col overflow-hidden sm:max-w-lg">
          <DialogHeader className="min-h-0 shrink overflow-y-auto overscroll-contain pr-6 [overflow-wrap:anywhere]">
            <DialogTitle>{viewingDescriptionTask?.title || "Task Description"}</DialogTitle>
          </DialogHeader>
          <div className="min-h-0 flex-1 space-y-2 overflow-y-auto overscroll-contain pr-2">
            <Label>Description</Label>
            {viewingDescriptionTask?.description && viewingDescriptionTask.description.trim().length > 0 ? (
              <div className=" rounded-md border border-slate-200 bg-slate-50 p-3 text-sm whitespace-pre-wrap [overflow-wrap:anywhere]">
                {viewingDescriptionTask.description}
              </div>
            ) : (
              <div className="rounded-md border border-dashed border-slate-200 p-3 text-sm text-slate-500">
                No description.
              </div>
            )}
          </div>
          <DialogFooter className="shrink-0">
            <Button type="button" variant="outline" onClick={() => setViewingDescriptionTask(null)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
