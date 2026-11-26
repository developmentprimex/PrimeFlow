"use client"

import * as React from "react"
import { TaskPauseBadge } from "@/components/task-pause-field"
import { isTaskPausedOnDay } from "@/lib/task-pause"
import { CollapsibleTaskTitle } from "@/components/collapsible-task-title"
import { TaskOneHMarkerEditor } from "@/components/task-one-h-marker-editor"
import { TaskMarkerComment } from "@/components/task-marker-comment"
import { miraDictationLabel } from "@/lib/mira"
import { NextWorkdayTaskFeedback } from "@/components/next-workday-task-feedback"
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
import { financeTaskAlignment, financeTaskMatchesDates, financeTaskMatchesPerson, financeUserInitials as initials } from "@/lib/finance-task-rows"
import type { DailyReportResponse, Department, SystemTaskOut, SystemTaskTemplate, Task, User } from "@/lib/types"
import { weeklyPlanStatusBgClass } from "@/lib/weekly-plan-status"
import { updateTaskWithCompletion } from "@/lib/task-completion"

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
  alignment: ReturnType<typeof financeTaskAlignment>
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
  const labels = new Map<string, string>()

  const pushUser = (id?: string | null, fallbackLabel?: string | null) => {
    if (!id || seen.has(id)) return
    seen.add(id)
    ids.push(id)
    const label = userLabel(usersById.get(id)) || fallbackLabel || id
    labels.set(id, label)
  }

  if (task.assignees?.length) {
    for (const assignee of task.assignees) {
      pushUser(assignee.id, assignee.full_name || assignee.username || assignee.email || null)
    }
  }

  pushUser(task.assigned_to)

  const displayIds = [...new Set([task.assigned_to, ...ids, ...(task.shared_assignee_ids ?? [])])]
  const displayLabels = displayIds.flatMap((id) => {
    if (!id) return []
    const label = labels.get(id) || userLabel(usersById.get(id))
    return label ? [label] : []
  })
  return {
    ids,
    label: displayLabels.join(", ") || "Unassigned",
    initials: displayLabels.map(initials).filter(Boolean).join(", ") || "-",
  }
}

function isOpenStatus(status: string) {
  return status === "TODO" || status === "IN_PROGRESS" || status === "PAUSED" || status === "WAITING_CONFIRMATION"
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
  const canConfirmTomorrow = user?.full_name?.trim().toLowerCase() === "haxhere spahiu"
  const [department, setDepartment] = React.useState<Department | null>(null)
  const [tasks, setTasks] = React.useState<Task[]>([])
  const [users, setUsers] = React.useState<User[]>([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [selectedUserId, setSelectedUserId] = React.useState<string>(ALL_USERS_VALUE)
  const [viewFilter, setViewFilter] = React.useState<ViewFilter>(VIEW_ALL)
  const [tomorrowOpen, setTomorrowOpen] = React.useState(false)
  const selectedFinanceOwner = users.find((entry) => entry.id === selectedUserId)
  const canInspectTomorrow = user?.role === "ADMIN" && selectedFinanceOwner?.full_name?.trim().toLowerCase() === "haxhere spahiu"
  const canOpenTomorrow = canConfirmTomorrow || canInspectTomorrow
  const showTomorrow = canOpenTomorrow && tomorrowOpen
  const [dateFrom, setDateFrom] = React.useState("")
  const [dateTo, setDateTo] = React.useState("")
  const [showDone, setShowDone] = React.useState(false)
  const [updatingTaskIds, setUpdatingTaskIds] = React.useState<Record<string, boolean>>({})
  const [exportingExcel, setExportingExcel] = React.useState(false)
  const [editingTask, setEditingTask] = React.useState<Task | null>(null)
  const [viewingDescriptionTask, setViewingDescriptionTask] = React.useState<Task | null>(null)
  const [dailyReport, setDailyReport] = React.useState<DailyReportResponse | null>(null)
  const [systemTasksByTemplateId, setSystemTasksByTemplateId] = React.useState<Map<string, SystemTaskOut | SystemTaskTemplate>>(new Map())
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

      const financeUsers = nextUsers.filter((entry) => entry.is_active && entry.department_id === financeDepartment.id)
      const [tasksRes, systemTasksRes, templatesRes, ...relatedResponses] = await Promise.all([
        apiFetch(`/tasks?department_id=${encodeURIComponent(financeDepartment.id)}&include_done=true&include_all_done=true&include_shared_assignees=true`),
        apiFetch(`/system-tasks?department_id=${encodeURIComponent(financeDepartment.id)}`),
        apiFetch("/system-tasks/templates"),
        ...financeUsers.map(({ id }) => apiFetch(`/tasks?related_user_id=${encodeURIComponent(id)}&include_done=true&include_all_done=true&include_shared_assignees=true`)),
      ])

      if (!tasksRes.ok || !templatesRes.ok || relatedResponses.some((response) => !response.ok)) {
        throw new Error("Unable to load Finance tasks.")
      }

      const nextTasks = (await tasksRes.json()) as Task[]
      const systemTasks = systemTasksRes.ok ? ((await systemTasksRes.json()) as SystemTaskOut[]) : []
      const templates = (await templatesRes.json()) as SystemTaskTemplate[]
      const relatedTasks = await Promise.all(relatedResponses.map(async (response) => (await response.json()) as Task[]))
      const nextSystemTasks = new Map<string, SystemTaskOut | SystemTaskTemplate>(templates.map((item) => [item.id, item]))
      for (const item of systemTasks) nextSystemTasks.set(item.template_id, item)

      const nextTasksById = new Map(nextTasks.map((task) => [task.id, task]))
      relatedTasks.forEach((matches, index) => {
        const personId = financeUsers[index].id
        for (const task of matches) {
          const template = nextSystemTasks.get(task.system_template_origin_id ?? "")
          if (task.assigned_to === personId || task.assignees?.some((assignee) => assignee.id === personId)
            || task.alignment_user_ids?.includes(personId) || template?.alignment_user_ids?.includes(personId)) {
            nextTasksById.set(task.id, task)
          }
        }
      })

      setDepartment(financeDepartment)
      setUsers(nextUsers)
      setTasks([...nextTasksById.values()])
      setSystemTasksByTemplateId(nextSystemTasks)
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
    const userLabels = new Map(users.map((entry) => [entry.id, userLabel(entry)]))
    return [...tasks]
      .map((task) => {
        const assigneeInfo = taskAssigneeInfo(task, usersById)
        const statusValue = task.status || "TODO"
        const isManagerView = user?.role === "ADMIN" || user?.role === "MANAGER"
        const isAssignedToCurrentUser = Boolean(user?.id && assigneeInfo.ids.includes(user.id))
        const canEdit = Boolean((isManagerView || isAssignedToCurrentUser) && statusValue !== "DONE")
        const systemTask = systemTasksByTemplateId.get(task.system_template_origin_id ?? "")
        const systemFrequency = systemTask?.frequency || ""

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
          alignment: financeTaskAlignment(task.alignment_user_ids, systemTask, userLabels),
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
  }, [systemTasksByTemplateId, tasks, user?.id, user?.role, users, usersById])

  const selectableUsers = React.useMemo(() => {
    const ids = new Set<string>()
    for (const row of rows) {
      for (const id of row.assigneeIds) ids.add(id)
      for (const id of row.alignment.userIds) ids.add(id)
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
        !dateFrom && !dateTo && row.task.system_template_origin_id &&
        row.occurrenceDateIso &&
        row.occurrenceDateIso > currentWeekEndIso
      ) {
        return false
      }

      if (selectedUserId !== ALL_USERS_VALUE && !financeTaskMatchesPerson(row, selectedUserId)) {
        return false
      }

      return financeTaskMatchesDates(row, dateFrom, dateTo)
    })

    if (viewFilter === VIEW_TODAY) {
      return visibleRows.filter((row) => row.status !== "DONE" && financeTaskMatchesDates(row, todayIso, todayIso))
    }
    if (viewFilter === VIEW_OVERDUE) {
      return visibleRows.filter((row) => row.status !== "DONE" && (row.lateDays ?? 0) > 0)
    }
    if (viewFilter === VIEW_TODAY_OVERDUE) {
      return visibleRows.filter(
        (row) =>
          row.status !== "DONE" && (financeTaskMatchesDates(row, todayIso, todayIso) || (row.lateDays ?? 0) > 0)
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
      return {
        typeLabel: task.system_template_origin_id ? "SYS" : task.project_id ? "PRJK" : "FT",
        subtype: task.system_template_origin_id ? "SYS" : task.project_id ? "-" : fastReportSubtypeShort(task),
        frequency: row.systemFrequencyLabel,
        dateLabel: row.dueDateIso ? formatDateDMY(row.dueDateIso) : row.startDateIso ? formatDateDMY(row.startDateIso) : "-",
        bzMe: row.alignment.withLabel,
        kohaBz: row.alignment.time || "-",
        department: departmentLabel,
        period: resolvePeriod(task.finish_period),
        title: [task.title || "-", miraDictationLabel(task.mira_dictation_source)].filter(Boolean).join("\n"),
        description: task.description || "",
        details: formatInternalDetails(task.internal_notes),
        status: row.status,
        userInitials: row.assigneeInitials === "-" ? "" : row.assigneeInitials,
      }
    })
  }, [department?.code, department?.name, filteredRows])

  const handleTaskUpdated = React.useCallback((updatedTask: Task) => {
    setTasks((prev) => prev.map((task) => task.id === updatedTask.id
      ? { ...updatedTask, shared_assignee_ids: updatedTask.shared_assignee_ids ?? task.shared_assignee_ids }
      : task))
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

  const completionActorId = user?.id
  const handleMarkDone = React.useCallback(
    async (task: Task) => {
      const taskId = task.id
      setUpdatingTaskIds((prev) => ({ ...prev, [taskId]: true }))

      try {
        const updatedTask = await updateTaskWithCompletion(
          apiFetch, task, completionActorId, { status: "DONE" }, "Failed to mark task as done.",
        )
        if (!updatedTask) return
        handleTaskUpdated(updatedTask)
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
    [apiFetch, completionActorId, handleTaskUpdated]
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

  const tomorrowButton = canOpenTomorrow && (
    <Button
      variant={showTomorrow ? "default" : "outline"}
      aria-pressed={showTomorrow}
      onClick={() => setTomorrowOpen((open) => !open)}
    >
      Nesër
    </Button>
  )

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div className="space-y-1">
            <CardTitle>{department?.name || "Finance"} Department Tasks</CardTitle>
          </div>
          {!showTomorrow && <Button onClick={() => void loadData()} variant="outline">Refresh</Button>}
        </CardHeader>
        {!showTomorrow && <CardContent className="space-y-4">
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
              <Label htmlFor="finance-date-from">Date from</Label>
              <Input id="finance-date-from" type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="finance-date-to">Date to</Label>
              <Input id="finance-date-to" type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
            </div>
          </div>
        </CardContent>}
      </Card>

      {showTomorrow ? (
        <NextWorkdayTaskFeedback
          view="finance"
          personId={canConfirmTomorrow ? undefined : selectedUserId}
          headerAction={tomorrowButton}
          taskHeaders={["NR", "Title", "Freq.", "Type", "Slot", "Asg", "Created", "Start Date", "Due Date", "Late", "Symbol", "Status"].map((label) => (
            <TableHead key={label} className={label === "Title" ? "min-w-72" : "whitespace-nowrap"}>{label}</TableHead>
          ))}
          renderTaskCells={(task, index) => {
            const row = rows.find((item) => item.id === task.id)
            const status = row?.status ?? task.status
            return <>
              <TableCell className="font-semibold text-slate-700">{index + 1}</TableCell>
              <TableCell className="min-w-72 whitespace-normal font-medium text-slate-800">
                <CollapsibleTaskTitle title={row?.title ?? task.title} renderTitle={renderMarkedNoteContent} />
                {task.is_paused && <TaskPauseBadge />}
                {row?.task.mira_dictation_source && <span className="block text-xs text-muted-foreground">{miraDictationLabel(row.task.mira_dictation_source)}</span>}
              </TableCell>
              <TableCell>{row?.systemFrequencyDisplayLabel || "–"}</TableCell>
              <TableCell><Badge variant="outline">{row?.typeLabel ?? (task.is_system_task ? "SYS" : task.is_1h ? "1H" : "P")}</Badge></TableCell>
              <TableCell>{task.slot || (row ? getFinanceSlotDisplay(row.task) : "–")}</TableCell>
              <TableCell>{row?.assigneeInitials || initials(selectedFinanceOwner?.full_name || user?.full_name || "") || "–"}</TableCell>
              <TableCell className="text-xs text-slate-400">{row ? formatDateDMY(row.createdDateIso) : "–"}</TableCell>
              <TableCell>{formatDateDMY(row?.startDateIso || task.start_date || "")}</TableCell>
              <TableCell>{formatDateDMY(row?.dueDateIso || task.due_date || "")}</TableCell>
              <TableCell>{row?.lateDays ? <Badge variant="destructive">{row.lateDays}</Badge> : "–"}</TableCell>
              <TableCell>{row?.typeLabel === "SYS" || task.is_system_task ? "SYS" : row?.task.one_h_marker || "–"}</TableCell>
              <TableCell><span className={`inline-flex rounded px-2 py-1 text-xs font-medium uppercase ${weeklyPlanStatusBgClass(status)}`}>{status === "WAITING_CONFIRMATION" ? "WFC INT" : status}</span></TableCell>
            </>
          }}
        />
      ) : <Card>
        <CardHeader className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div className="space-y-1">
            <CardTitle>Finance Tasks</CardTitle>
            <CardDescription>
              {filteredRows.length} rows for {selectedUserLabel}
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {tomorrowButton}
            <Button
              variant="outline"
              onClick={() => void handleExportExcel()}
              disabled={loading || !!error || !financeExportRows.length || exportingExcel}
            >
              {exportingExcel ? "Exporting..." : "Export Excel"}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="text-sm text-slate-500">Loading Finance tasks...</div>
          ) : error ? (
            <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          ) : (
            <div className="@container space-y-4">
              <Table
                className="min-w-[1544px] table-fixed [--finance-row-number-width:36px]"
                containerClassName="max-h-[75dvh] overflow-auto rounded-lg border border-slate-200 bg-white @[1546px]:max-h-none @[1546px]:overflow-visible print:max-h-none print:overflow-visible"
              >
                <colgroup>
                  <col className="w-[var(--finance-row-number-width)]" />{/* NR */}
                  <col />{/* Title fills the remaining space */}
                  <col className="w-16" />{/* Freq. */}
                  <col className="w-[54px]" />{/* Type */}
                  <col className="w-20" />{/* Slot */}
                  <col className="w-14" />{/* Asg */}
                  <col className="w-[72px]" />{/* BZ ME */}
                  <col className="w-[76px]" />{/* KOHA BZ */}
                  <col className="w-[76px]" />{/* Created */}
                  <col className="w-[88px]" />{/* Start Date */}
                  <col className="w-[88px]" />{/* Due Date */}
                  <col className="w-[46px]" />{/* Late */}
                  <col className="w-[88px]" />{/* Symbol */}
                  <col className="w-[88px]" />{/* Status */}
                  <col className="w-[170px]" />{/* Arsyeja */}
                  <col className="w-[150px]" />{/* Koment */}
                  <col className="w-28" />{/* Actions */}
                </colgroup>
                <TableHeader className="sticky top-0 z-20 bg-slate-50 print:static">
                  <TableRow className="bg-slate-50">
                    <TableHead className="sticky left-0 z-10 bg-slate-50 print:static">NR</TableHead>
                    <TableHead className="sticky left-[var(--finance-row-number-width)] z-10 border-r border-slate-200 bg-slate-50 print:static">Title</TableHead>
                    <TableHead className="px-0 text-center" title="Frequency">Freq.</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead className="px-1 text-center" title="1H report time">
                      Slot
                    </TableHead>
                    <TableHead className="px-1 text-center" title="Assignee">Asg</TableHead>
                    <TableHead>BZ ME</TableHead>
                    <TableHead>KOHA BZ</TableHead>
                    <TableHead className="text-xs font-normal text-slate-400">Created</TableHead>
                    <TableHead>Start Date</TableHead>
                    <TableHead>Due Date</TableHead>
                    <TableHead>Late</TableHead>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Arsyeja</TableHead>
                    <TableHead>Koment</TableHead>
                    <TableHead className="sticky right-0 z-10 border-l border-slate-200 bg-slate-50 print:static">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredRows.length ? (
                    filteredRows.map((row, index) => (
                      <TableRow key={row.id} className="group/finance-row">
                        <TableCell className="sticky left-0 z-10 bg-background font-semibold text-slate-700 group-hover/finance-row:bg-muted print:static">{index + 1}</TableCell>
                        <TableCell className="sticky left-[var(--finance-row-number-width)] z-10 whitespace-normal border-r border-slate-200 bg-background font-medium text-slate-800 group-hover/finance-row:bg-muted print:static">
                          <div className="relative flex w-full items-start gap-2 pr-8">
                            <span className="min-w-0 flex-1 whitespace-pre-wrap break-words">
                              <TaskMarkerComment comment={row.task.one_h_marker_comment} taskId={row.task.id} />
                              <CollapsibleTaskTitle
                                title={row.title}
                                alignToggle
                                renderTitle={(title) => title.includes("[[") ? renderMarkedNoteContent(title, title) : title}
                              />
                              {row.task.mira_dictation_source && <span className="block text-xs text-muted-foreground">{miraDictationLabel(row.task.mira_dictation_source)}</span>}
                            </span>
                          </div>
                        </TableCell>
                        <TableCell className="px-0 text-center">
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
                        <TableCell className="px-1 text-center">
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
                        <TableCell className="px-1 text-center whitespace-normal" title={row.assigneeLabel}>
                          <span className="text-xs font-semibold text-slate-700">{row.assigneeInitials}</span>
                        </TableCell>
                        <TableCell className="whitespace-normal break-words">{row.alignment.withLabel || "—"}</TableCell>
                        <TableCell>{row.alignment.time || "—"}</TableCell>
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
                        <TableCell className="px-1 text-center">
                          {row.typeLabel === "SYS" ? (
                            <span className="text-xs font-semibold text-slate-600">SYS</span>
                          ) : (
                            <TaskOneHMarkerEditor taskId={row.task.id} marker={row.task.one_h_marker} className="mx-auto shrink-0" />
                          )}
                        </TableCell>
                        <TableCell>
                          <span className={`inline-block max-w-full rounded px-2 py-1 text-xs font-medium uppercase whitespace-normal [overflow-wrap:anywhere] ${row.statusClassName}`}>
                            {row.status === "PAUSED" ? "Stopped" : row.status === "WAITING_CONFIRMATION" ? "WFC INT" : row.status}
                          </span>
                          {isTaskPausedOnDay(row.task, todayIso) && <TaskPauseBadge />}
                        </TableCell>
                        <TableCell className="whitespace-normal [overflow-wrap:anywhere] [&_[data-slot=select-trigger]]:w-full [&_[data-slot=select-trigger]]:px-2">
                          <DailyRlzReasonCell
                            taskId={row.id}
                            day={todayIso}
                            state={dailyRlzStateForRow(row.id)}
                            subjectUserId={dailyRlzSubjectUserId}
                            onSaved={refreshDailyReport}
                          />
                        </TableCell>
                        <TableCell className="whitespace-normal [overflow-wrap:anywhere] [&_input]:min-w-0">
                          <DailyRlzCommentField
                            taskId={row.id}
                            day={todayIso}
                            state={dailyRlzStateForRow(row.id)}
                            subjectUserId={dailyRlzSubjectUserId}
                            onSaved={refreshDailyReport}
                          />
                        </TableCell>
                        <TableCell className="sticky right-0 z-10 border-l border-slate-200 bg-background group-hover/finance-row:bg-muted print:static">
                          <div className="flex flex-wrap items-center gap-1">
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-7 px-2"
                              onClick={() => setViewingDescriptionTask(row.task)}
                            >
                              Description
                            </Button>
                            {row.canEdit ? (
                              <Button size="sm" variant="outline" className="h-7 px-2" onClick={() => setEditingTask(row.task)}>
                                Edit
                              </Button>
                            ) : (
                              <span className="text-xs text-slate-400">No access</span>
                            )}
                            {row.canMarkDone ? (
                              <Button
                                size="sm"
                                className="h-7 bg-emerald-500 px-2 text-white hover:bg-emerald-600"
                                onClick={() => void handleMarkDone(row.task)}
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
                      <TableCell colSpan={17} className="py-8 text-center text-sm text-slate-500">
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
      </Card>}

      <TaskEditDialog
        task={editingTask}
        open={Boolean(editingTask)}
        onOpenChange={(open) => {
          if (!open) setEditingTask(null)
        }}
        onUpdated={(updatedTask) => {
          handleTaskUpdated(updatedTask)
          void loadData()
        }}
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
