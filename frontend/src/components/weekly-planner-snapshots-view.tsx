"use client"

import * as React from "react"

import { useAuth } from "@/lib/auth"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import {
  buildLegendSwatches,
  buildLegendDisplayEntries,
  type LegendEntry,
} from "@/components/weekly-planner-legend-table"
import { WeeklyPlanPerformanceView, type WeeklyPlanPerformanceResponse } from "@/components/weekly-plan-performance-view"
import { formatDepartmentName } from "@/lib/department-name"
import { formatDateTimeDMY } from "@/lib/dates"
import { toast } from "sonner"
import { Printer } from "lucide-react"
import { TaskOneHMarker, taskOneHMarkerLabel } from "@/components/task-one-h-marker"
import { TaskMarkerComment } from "@/components/task-marker-comment"
import type { Task } from "@/lib/types"

type SnapshotType = "PLANNED" | "FINAL"
type SlotType = "am" | "pm"

const sanitizeDownloadFilename = (value: string) => {
  const trimmed = (value || "").trim()
  const withoutUnsafe = trimmed.replace(/[\\/:*?"<>|]/g, "_")
  const withoutControls = withoutUnsafe.replace(/[\u0000-\u001F\u007F]/g, "")
  const collapsed = withoutControls.replace(/\s+/g, " ").trim()
  if (!collapsed) return "download"
  // Keep some headroom for OS/path limitations.
  return collapsed.length > 180 ? collapsed.slice(0, 180).trim() : collapsed
}

const parseFilenameFromDisposition = (headerValue: string | null) => {
  if (!headerValue) return null
  const match = headerValue.match(/filename=\"?([^\";]+)\"?/i)
  return match ? match[1] : null
}

const triggerBlobDownload = (blob: Blob, filename: string) => {
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = sanitizeDownloadFilename(filename)
  link.style.display = "none"
  document.body.appendChild(link)
  link.click()
  link.remove()
  // Some browsers may cancel the download if we revoke immediately.
  window.setTimeout(() => {
    window.URL.revokeObjectURL(url)
  }, 30_000)
}

type SnapshotVersion = {
  id: string
  department_id: string
  week_start_date: string
  week_end_date: string
  snapshot_type: SnapshotType
  created_by: string | null
  created_at: string
  is_official: boolean
}

type SnapshotTaskEntry = {
  task_id: string | null
  task_title?: string
  title?: string
  phase?: string | null
  status?: string | null
  daily_status?: string | null
  created_at?: string | null
  completed_at?: string | null
  daily_products: number | null
  total_products?: number | null
  completed_products?: number | null
  finish_period?: string | null
  fast_task_type?: string | null
  is_bllok: boolean
  is_1h_report: boolean
  is_r1: boolean
  is_personal: boolean
  is_deadline_important?: boolean
  ga_note_origin_id: string | null
  one_h_marker?: Task["one_h_marker"]
  one_h_marker_by_ga?: boolean
  one_h_marker_comment?: string | null
}

type SnapshotProjectEntry = {
  project_id: string
  project_title: string
  project_total_products: number | null
  project_current_phase?: string | null
  project_type?: string | null
  task_count: number
  tasks: SnapshotTaskEntry[]
  is_late?: boolean
}

type SnapshotUserDay = {
  user_id: string
  user_name: string
  am_projects: SnapshotProjectEntry[]
  pm_projects: SnapshotProjectEntry[]
  am_system_tasks: SnapshotTaskEntry[]
  pm_system_tasks: SnapshotTaskEntry[]
  am_fast_tasks: SnapshotTaskEntry[]
  pm_fast_tasks: SnapshotTaskEntry[]
}

type SnapshotDay = {
  date: string
  users: SnapshotUserDay[]
}

type SnapshotDepartment = {
  department_id: string
  department_name: string
  days: SnapshotDay[]
}

type SnapshotLeaveBlock = {
  entry_id: string
  user_id: string
  start_date: string
  end_date: string
  full_day: boolean
  start_time: string | null
  end_time: string | null
  note: string | null
}

type SnapshotPayload = {
  week_start: string
  week_end: string
  department: SnapshotDepartment | null
  legend_entries: LegendEntry[]
  pv_fest_blocks: SnapshotLeaveBlock[]
}

type SnapshotData = SnapshotVersion & {
  payload: SnapshotPayload
}

type SnapshotOverviewWeek = {
  week_start: string
  week_end: string
  label: "last_last_week" | "last_week" | "this_week" | string
  planned_official_id: string | null
  planned_versions: number
  final_official_id: string | null
  final_versions: number
}

type SnapshotOverviewResponse = {
  weeks: SnapshotOverviewWeek[]
}

type SnapshotCompareResponse = {
  week_start: string
  week_end: string
  planned_official: SnapshotData | null
  final_official: SnapshotData | null
  planned_versions: SnapshotVersion[]
  final_versions: SnapshotVersion[]
}

type WeeklyPlannerSnapshotsViewProps = {
  departmentId: string
  allDepartmentsValue: string
}

const OVERVIEW_LABELS: Record<string, string> = {
  last_last_week: "Last Last Week",
  last_week: "Last Week",
  this_week: "This Week",
  next_week: "Next Week",
}

const PLAN_VS_FINAL_PRINT_ROOT_ID = "plan-vs-final-report-print-root"

const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

const formatDate = (iso: string) => {
  const parsed = new Date(iso)
  return parsed.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  })
}

const formatDateTime = (iso: string) => {
  return formatDateTimeDMY(iso)
}

const timeToMinutes = (value?: string | null) => {
  if (!value) return null
  const [h, m] = value.split(":").map(Number)
  if (!Number.isFinite(h) || !Number.isFinite(m)) return null
  return h * 60 + m
}

const getStatusCardClasses = (status?: string | null) => {
  const normalized = (status || "TODO").toUpperCase()
  if (normalized === "PAUSED") return "border-[#64748B] bg-[#CBD5E1] text-[#1E293B]"
  if (normalized === "IN_PROGRESS") {
    return "border-[#000000] bg-[#FFFF00] text-[#000000]"
  }
  if (normalized === "WAITING_CONFIRMATION") {
    return "border-[#C2410C] bg-[#FFEDD5] text-[#9A3412]"
  }
  if (normalized === "WAITING_CLIENT") {
    return "border-[#B8860B] bg-[#E2C15B] text-[#4F3A00]"
  }
  if (normalized === "DONE") {
    return "border-[#000000] bg-[#C4FDC4] text-[#000000]"
  }
  if (normalized === "TODO") {
    return "border-[#000000] bg-[#FFC4ED] text-[#000000]"
  }
  return "border-[#000000] bg-[#f1f5f9] text-[#000000]"
}

const getStatusCardClassesForDay = (
  status?: string | null,
  completedAt?: string | null,
  dayDate?: string | null,
  dailyStatus?: string | null
) => {
  const normalized = (status || "TODO").toUpperCase()

  const normalizedDaily = dailyStatus ? dailyStatus.toUpperCase() : null

  if (normalizedDaily === "DONE") {
    return getStatusCardClasses("DONE")
  }
  if (normalizedDaily === "WAITING_CONFIRMATION") {
    return getStatusCardClasses("WAITING_CONFIRMATION")
  }
  if (normalizedDaily === "PAUSED") return getStatusCardClasses("PAUSED")
  if (normalizedDaily === "WAITING_CLIENT") {
    return getStatusCardClasses("WAITING_CLIENT")
  }

  if (completedAt && dayDate) {
    const completedDate = completedAt.slice(0, 10)
    const currentDate = dayDate.slice(0, 10)
    if (currentDate >= completedDate) {
      return getStatusCardClasses("DONE")
    }
    if (normalized === "DONE") {
      return getStatusCardClasses("IN_PROGRESS")
    }
  }

  if (normalized === "DONE") {
    return getStatusCardClasses("DONE")
  }

  if (normalizedDaily === "IN_PROGRESS") {
    return getStatusCardClasses("IN_PROGRESS")
  }
  if (normalizedDaily) {
    return getStatusCardClasses("TODO")
  }

  if (normalized === "WAITING_CONFIRMATION") {
    return getStatusCardClasses("TODO")
  }
  if (normalized === "PAUSED") return getStatusCardClasses("PAUSED")
  if (normalized === "WAITING_CLIENT") {
    return getStatusCardClasses("WAITING_CLIENT")
  }
  return getStatusCardClasses(normalized === "TODO" ? "TODO" : "IN_PROGRESS")
}

const getStatusValueForDay = (
  status?: string | null,
  completedAt?: string | null,
  dayDate?: string | null,
  dailyStatus?: string | null
) => {
  const normalized = (status || "TODO").toUpperCase()

  const normalizedDaily = dailyStatus ? dailyStatus.toUpperCase() : null

  if (normalizedDaily === "DONE") {
    return "DONE"
  }
  if (normalizedDaily === "WAITING_CONFIRMATION") {
    return "WAITING_CONFIRMATION"
  }
  if (normalizedDaily === "PAUSED") return "PAUSED"
  if (normalizedDaily === "WAITING_CLIENT") {
    return "WAITING_CLIENT"
  }

  if (completedAt && dayDate) {
    const completedDate = completedAt.slice(0, 10)
    const currentDate = dayDate.slice(0, 10)
    if (currentDate >= completedDate) {
      return "DONE"
    }
    if (normalized === "DONE") {
      return "IN_PROGRESS"
    }
  }

  if (normalized === "DONE") {
    return "DONE"
  }

  if (normalizedDaily === "IN_PROGRESS") {
    return "IN_PROGRESS"
  }
  if (normalizedDaily) {
    return "TODO"
  }

  if (normalized === "WAITING_CONFIRMATION") {
    return "TODO"
  }
  if (normalized === "PAUSED") return "PAUSED"
  if (normalized === "WAITING_CLIENT") {
    return "WAITING_CLIENT"
  }
  return normalized === "TODO" ? "TODO" : "IN_PROGRESS"
}

const isTaskNewForWeek = (createdAt?: string | null, weekStart?: string | null) => {
  if (!createdAt || !weekStart) return false
  const createdAtMs = Date.parse(createdAt)
  const weekStartMs = Date.parse(`${weekStart}T00:00:00`)
  if (!Number.isFinite(createdAtMs) || !Number.isFinite(weekStartMs)) return false
  return createdAtMs >= weekStartMs
}

const getTaskCardClassesForDay = (
  status?: string | null,
  completedAt?: string | null,
  dayDate?: string | null,
  dailyStatus?: string | null,
  createdAt?: string | null,
  weekStart?: string | null,
  isDeadlineImportant?: boolean
) => {
  if (isDeadlineImportant) {
    return "border-red-800 bg-red-600 text-white"
  }
  const statusValue = getStatusValueForDay(status, completedAt, dayDate, dailyStatus)
  const isNew = isTaskNewForWeek(createdAt, weekStart)
  if (isNew) {
    if (statusValue === "DONE") {
      return "border-[#059669] bg-[#02e6c7] text-[#064e3b]"
    }
    if (statusValue === "WAITING_CONFIRMATION") {
      return getStatusCardClasses("WAITING_CONFIRMATION")
    }
    if (statusValue === "PAUSED") return getStatusCardClasses("PAUSED")
    if (statusValue === "IN_PROGRESS") {
      return getStatusCardClasses("IN_PROGRESS")
    }
    return "border-[#1d4ed8] bg-[#dbeafe] text-[#0f172a]"
  }
  return getStatusCardClassesForDay(status, completedAt, dayDate, dailyStatus)
}

const getTaskStatusBadge = (task: SnapshotTaskEntry): { label: string; className: string } => {
  if (task.is_bllok) {
    return { label: "BLL", className: "border-red-200 bg-red-50 text-red-700" }
  }
  if (task.is_r1) {
    return { label: "R1", className: "border-indigo-200 bg-indigo-50 text-indigo-700" }
  }
  if (task.is_1h_report) {
    return { label: "1H", className: "border-amber-200 bg-amber-50 text-amber-700" }
  }
  if (task.is_personal) {
    return { label: "P:", className: "border-emerald-200 bg-emerald-50 text-emerald-700" }
  }
  return { label: "N", className: "border-slate-200 bg-slate-50 text-slate-700" }
}

const getFastTaskBadge = (task: SnapshotTaskEntry): { label: string; className: string } => {
  const badge = getTaskStatusBadge(task)
  if (badge) return badge
  if (task.fast_task_type) {
    const fastTaskBadgeStyles: Record<string, string> = {
      BLL: "border-red-200 bg-red-50 text-red-700",
      R1: "border-indigo-200 bg-indigo-50 text-indigo-700",
      "1H": "border-amber-200 bg-amber-50 text-amber-700",
      "P:": "border-emerald-200 bg-emerald-50 text-emerald-700",
      N: "border-slate-200 bg-slate-50 text-slate-700",
    }
    if (task.fast_task_type === "GA") {
      return { label: "N", className: "border-slate-200 bg-slate-50 text-slate-700" }
    }
    return {
      label: task.fast_task_type,
      className: fastTaskBadgeStyles[task.fast_task_type] || "border-slate-200 bg-slate-50 text-slate-700",
    }
  }
  return { label: "N", className: "border-slate-200 bg-slate-50 text-slate-700" }
}

const getFastTaskSortLabel = (task: SnapshotTaskEntry) => getFastTaskBadge(task).label

const sortFastTasks = (tasks: SnapshotTaskEntry[]) => {
  const order = ["BLL", "1H", "P:", "R1", "N"]
  const rank = new Map<string, number>(order.map((label, index) => [label, index]))
  return tasks
    .map((task, index) => ({ task, index }))
    .sort((a, b) => {
      const aLabel = getFastTaskSortLabel(a.task)
      const bLabel = getFastTaskSortLabel(b.task)
      const aRank = rank.get(aLabel) ?? order.length
      const bRank = rank.get(bLabel) ?? order.length
      if (aRank !== bRank) return aRank - bRank
      return a.index - b.index
    })
    .map((entry) => entry.task)
}

const getProjectDisplayTitle = (project: SnapshotProjectEntry) => {
  return project.project_title || "Untitled project"
}

const getBlockForSlot = (
  blocks: SnapshotLeaveBlock[],
  userId: string,
  dayIso: string,
  slot: SlotType
) => {
  const slotStart = slot === "am" ? 0 : 12 * 60
  const slotEnd = slot === "am" ? 12 * 60 : 24 * 60
  return (
    blocks.find((block) => {
      if (block.user_id !== userId) return false
      if (!block.start_date || !block.end_date) return false
      if (dayIso < block.start_date || dayIso > block.end_date) return false
      if (block.full_day) return true
      const start = timeToMinutes(block.start_time) ?? 0
      const end = timeToMinutes(block.end_time) ?? 24 * 60
      if (end <= start) return true
      return start < slotEnd && end > slotStart
    }) || null
  )
}

function SnapshotLegend({ snapshot }: { snapshot: SnapshotData }) {
  const department = snapshot.payload.department
  if (!department) return null

  const displayEntries = buildLegendDisplayEntries({
    entries: snapshot.payload.legend_entries,
    departmentId: department.department_id,
    weekStart: snapshot.payload.week_start,
    departmentName: department.department_name,
  })
  const legendSwatches = buildLegendSwatches(displayEntries)

  if (displayEntries.length === 0) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Legend / Questions (Read-only)</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 md:grid-cols-[400px_minmax(0,1fr)]">
          <div className="overflow-x-auto rounded-lg border border-slate-300 bg-slate-50/40 p-3">
            <div className="mb-2 text-sm font-semibold text-slate-800">Color Labels</div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16 text-center">Color</TableHead>
                  <TableHead>Label</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {legendSwatches.map((swatch) => (
                  <TableRow key={swatch.key}>
                    <TableCell className="p-2">
                      <div
                        className="h-8 w-12 rounded border border-gray-300"
                        style={{ backgroundColor: swatch.color }}
                      />
                    </TableCell>
                    <TableCell className="font-semibold">{swatch.displayLabel}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          <div className="overflow-x-auto rounded-lg border border-slate-300 bg-white p-3">
            <div className="mb-2 text-sm font-semibold text-slate-800">Questions / Answers</div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Question</TableHead>
                  <TableHead>Answer</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {displayEntries.map((entry) => (
                  <TableRow key={entry.id}>
                    <TableCell>{entry.question_text || "-"}</TableCell>
                    <TableCell>{entry.answer_text?.trim() ? entry.answer_text : "-"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function SnapshotDepartmentTable({ snapshot }: { snapshot: SnapshotData }) {
  const department = snapshot.payload.department
  const days = React.useMemo(() => department?.days ?? [], [department?.days])

  const allUsers = React.useMemo(() => {
    const map = new Map<string, SnapshotUserDay>()
    days.forEach((day) => {
      day.users.forEach((userDay) => {
        if (!map.has(userDay.user_id)) {
          map.set(userDay.user_id, userDay)
        }
      })
    })
    return Array.from(map.values())
  }, [days])

  const blocks = React.useMemo(() => snapshot.payload.pv_fest_blocks || [], [snapshot.payload.pv_fest_blocks])

  const renderCellContent = React.useCallback(
    (
      projects: SnapshotProjectEntry[],
      systemTasks: SnapshotTaskEntry[],
      fastTasks: SnapshotTaskEntry[],
      timeSlot: SlotType,
      dayDate: string,
      userId: string
    ) => {
      const projectsList = projects || []
      const systemTasksList = systemTasks || []
      const fastTasksList = sortFastTasks(fastTasks || [])
      const hasContent =
        projectsList.length > 0 || systemTasksList.length > 0 || fastTasksList.length > 0
      const block = getBlockForSlot(blocks, userId, dayDate, timeSlot)
      const isBlocked = Boolean(block)

      if (!hasContent && !isBlocked) {
        return <div className="min-h-20 text-xs text-muted-foreground/50">-</div>
      }

      return (
        <div
          className={[
            "min-h-20",
            isBlocked ? "relative rounded-md border border-slate-300 bg-slate-100/70 text-slate-600" : "",
          ].join(" ")}
          title={isBlocked ? `PV/FEST${block?.note ? `: ${block.note}` : ""}` : undefined}
        >
          {isBlocked ? <div className="absolute inset-0 bg-slate-200/50 pointer-events-none" /> : null}
          {isBlocked ? (
            <div className="absolute top-1 right-1 z-10 rounded bg-slate-200/90 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600">
              PV/FEST
            </div>
          ) : null}
          <div className={isBlocked ? "relative z-0 opacity-70" : ""}>
            {!hasContent ? (
              <div className="min-h-20 text-xs text-muted-foreground/50">-</div>
            ) : (
              <div className="min-h-20 space-y-2">
                {projectsList.map((project, projectIndex) => (
                  <div
                    key={project.project_id}
                    className={[
                      "rounded-md p-1.5",
                      project.is_late
                        ? "border-2 border-red-500 bg-red-50"
                        : "border border-primary/20 bg-primary/5",
                    ].join(" ")}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 truncate whitespace-nowrap text-sm font-semibold text-slate-900">
                        {projectIndex + 1}. {getProjectDisplayTitle(project)}
                      </div>
                      {project.is_late ? (
                        <span className="inline-flex h-5 items-center justify-center rounded-full bg-red-500 px-2 text-[10px] font-semibold text-white">
                          LATE
                        </span>
                      ) : null}
                    </div>

                    {project.tasks && project.tasks.length > 0 ? (
                      <div className="mt-1 space-y-0.5">
                        {project.tasks.map((task, taskIndex) => {
                          const statusBadge = getTaskStatusBadge(task)
                          const isNew = isTaskNewForWeek(task.created_at, snapshot.payload.week_start)
                          const titleColorClass = task.is_deadline_important ? "text-white" : "text-slate-900"
                          return (
                            <div
                              key={`${project.project_id}-${task.task_id || taskIndex}`}
                              className={[
                                "flex items-center justify-between gap-1 rounded border px-1.5 py-0.5 text-[11px]",
                                getTaskCardClassesForDay(
                                  task.status,
                                  task.completed_at,
                                  dayDate,
                                  task.daily_status,
                                  task.created_at,
                                  snapshot.payload.week_start,
                                  task.is_deadline_important
                                ),
                              ].join(" ")}
                            >
                              <TaskOneHMarker
                                marker={task.one_h_marker}
                                markerByGa={task.one_h_marker_by_ga}
                                comment={task.one_h_marker_comment}
                                className="h-4 min-h-4 min-w-4 rounded px-0.5 text-[10px] !text-red-600"
                              />
                              <span className={["min-w-0 flex-1 break-words font-semibold", titleColorClass].join(" ")}>
                                <TaskMarkerComment comment={task.one_h_marker_comment} />
                                {projectIndex + 1}.{taskIndex + 1}. {task.task_title || task.title || "-"}
                              </span>
                              <div className="flex items-center gap-1">
                                {isNew ? (
                                  <span className="inline-flex h-4 items-center justify-center rounded-full border border-blue-300 bg-blue-100 px-1 text-[9px] font-semibold tracking-tight text-blue-700">
                                    NEW
                                  </span>
                                ) : null}
                                {statusBadge ? (
                                  <span
                                    className={[
                                      "inline-flex h-5 min-w-[1.5rem] items-center justify-center rounded-full border px-1 text-[10px] font-semibold",
                                      statusBadge.className,
                                    ].join(" ")}
                                  >
                                    {statusBadge.label}
                                  </span>
                                ) : null}
                                {task.daily_products != null ? (
                                  <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                                    {task.daily_products} pcs
                                  </span>
                                ) : null}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    ) : null}
                  </div>
                ))}

                {systemTasksList.length > 0 ? (
                  <div className="space-y-1">
                    <div className="mb-1 text-[11px] font-semibold text-slate-900">System Tasks</div>
                    {systemTasksList.map((task, idx) => {
                      const statusBadge = getTaskStatusBadge(task)
                      const isNew = isTaskNewForWeek(task.created_at, snapshot.payload.week_start)
                      const titleColorClass = task.is_deadline_important ? "text-white" : "text-slate-900"
                      return (
                        <div
                          key={`${task.task_id || task.title || "system"}-${idx}`}
                          className={[
                            "flex items-center justify-between rounded border p-1 text-[11px]",
                            getTaskCardClassesForDay(
                              task.status,
                              task.completed_at,
                              dayDate,
                              task.daily_status,
                              task.created_at,
                              snapshot.payload.week_start,
                              task.is_deadline_important
                            ),
                          ].join(" ")}
                        >
                          <TaskOneHMarker
                            marker={task.one_h_marker}
                            markerByGa={task.one_h_marker_by_ga}
                            comment={task.one_h_marker_comment}
                            className="h-4 min-h-4 min-w-4 rounded px-0.5 text-[10px] !text-red-600"
                          />
                          <span className={["min-w-0 flex-1 break-words font-semibold", titleColorClass].join(" ")}>
                            <TaskMarkerComment comment={task.one_h_marker_comment} />
                            {idx + 1}. {task.title || task.task_title || "-"}
                          </span>
                          <div className="flex items-center gap-1">
                            {isNew ? (
                              <span className="inline-flex h-4 items-center justify-center rounded-full border border-blue-300 bg-blue-100 px-1 text-[9px] font-semibold tracking-tight text-blue-700">
                                NEW
                              </span>
                            ) : null}
                            {statusBadge ? (
                              <span
                                className={[
                                  "inline-flex h-5 min-w-[1.5rem] items-center justify-center rounded-full border px-1 text-[10px] font-semibold",
                                  statusBadge.className,
                                ].join(" ")}
                              >
                                {statusBadge.label}
                              </span>
                            ) : null}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                ) : null}

                {fastTasksList.length > 0 ? (
                  <div className="space-y-1">
                    {fastTasksList.map((task, idx) => {
                      const statusBadge = getFastTaskBadge(task)
                      const isNew = isTaskNewForWeek(task.created_at, snapshot.payload.week_start)
                      const titleColorClass = task.is_deadline_important ? "text-white" : "text-slate-900"
                      return (
                        <div
                          key={`${task.task_id || task.title || "fast"}-${idx}`}
                          className={[
                            "flex items-center justify-between rounded border p-1 text-[11px]",
                            getTaskCardClassesForDay(
                              task.status,
                              task.completed_at,
                              dayDate,
                              task.daily_status,
                              task.created_at,
                              snapshot.payload.week_start,
                              task.is_deadline_important
                            ),
                          ].join(" ")}
                        >
                          <TaskOneHMarker
                            marker={task.one_h_marker}
                            markerByGa={task.one_h_marker_by_ga}
                            comment={task.one_h_marker_comment}
                            className="h-4 min-h-4 min-w-4 rounded px-0.5 text-[10px] !text-red-600"
                          />
                          <span className={["min-w-0 flex-1 break-words font-semibold", titleColorClass].join(" ")}>
                            <TaskMarkerComment comment={task.one_h_marker_comment} />
                            {idx + 1}. {task.title || task.task_title || "-"}
                          </span>
                          <div className="flex items-center gap-1">
                            {isNew ? (
                              <span className="inline-flex h-4 items-center justify-center rounded-full border border-blue-300 bg-blue-100 px-1 text-[9px] font-semibold tracking-tight text-blue-700">
                                NEW
                              </span>
                            ) : null}
                            <span
                              className={[
                                "inline-flex h-5 min-w-[1.5rem] items-center justify-center rounded-full border px-1 text-[10px] font-semibold",
                                statusBadge.className,
                              ].join(" ")}
                            >
                              {statusBadge.label}
                            </span>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                ) : null}
              </div>
            )}
          </div>
        </div>
      )
    },
    [blocks, snapshot.payload.week_start]
  )

  if (!department) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Snapshot Plan (Read-only)</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-sm text-muted-foreground">No department payload saved for this snapshot.</div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{formatDepartmentName(department.department_name)} (Read-only Snapshot)</CardTitle>
      </CardHeader>
      <CardContent>
        <Table
          className="table-fixed w-full"
          containerProps={{
            className: "max-h-[75vh] overflow-x-auto overflow-y-auto",
            style: {
              scrollbarWidth: "thin",
              scrollbarColor: "#94a3b8 #e2e8f0",
              touchAction: "pan-y",
            },
          }}
        >
          <TableHeader>
            <TableRow>
              <TableHead className="sticky top-0 left-0 z-30 w-24 min-w-24 bg-background text-xs font-bold uppercase">
                Day
              </TableHead>
              <TableHead className="sticky top-0 left-24 z-30 w-10 min-w-10 bg-background text-center text-xs font-bold uppercase">
                Time
              </TableHead>
              <TableHead className="sticky top-0 left-34 z-30 w-10 min-w-10 bg-background text-center text-xs font-bold uppercase">
                LL
              </TableHead>
              {allUsers.map((user) => (
                <TableHead
                  key={user.user_id}
                  className="sticky top-0 z-20 w-56 min-w-56 bg-background text-center text-xs font-bold uppercase"
                >
                  <div className="font-semibold">{user.user_name}</div>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {department.days.map((day, dayIndex) => (
              <React.Fragment key={`${day.date}-${dayIndex}`}>
                <TableRow>
                  <TableCell className="sticky left-0 z-10 w-24 min-w-24 bg-background align-top font-medium" rowSpan={4}>
                    <div className="flex flex-col">
                      <div className="font-bold text-slate-900">{DAY_NAMES[dayIndex] || "Day"}</div>
                      <div className="mt-1 text-xs font-semibold text-slate-900">{formatDate(day.date)}</div>
                    </div>
                  </TableCell>
                  <TableCell className="sticky left-24 z-10 w-10 min-w-10 bg-background text-center align-top">
                    <div className="text-xs font-medium text-primary">AM</div>
                  </TableCell>
                  <TableCell className="sticky left-34 z-10 w-10 min-w-10 bg-background text-center align-top text-xs font-bold uppercase">
                    PRJK
                  </TableCell>
                  {allUsers.map((user) => {
                    const userDay = day.users.find((item) => item.user_id === user.user_id)
                    return (
                      <TableCell key={`${user.user_id}-am-prjk`} className="w-56 min-w-56 align-top">
                        {userDay
                          ? renderCellContent(
                              userDay.am_projects || [],
                              userDay.am_system_tasks || [],
                              [],
                              "am",
                              day.date,
                              user.user_id
                            )
                          : <div className="min-h-20 text-xs text-muted-foreground/50">-</div>}
                      </TableCell>
                    )
                  })}
                </TableRow>

                <TableRow className="border-t border-border">
                  <TableCell className="sticky left-24 z-10 w-10 min-w-10 bg-background text-center align-top">
                    <div className="text-xs font-medium text-primary">AM</div>
                  </TableCell>
                  <TableCell className="sticky left-34 z-10 w-10 min-w-10 bg-background text-center align-top text-xs font-bold uppercase">
                    FT
                  </TableCell>
                  {allUsers.map((user) => {
                    const userDay = day.users.find((item) => item.user_id === user.user_id)
                    return (
                      <TableCell key={`${user.user_id}-am-ft`} className="w-56 min-w-56 align-top">
                        {userDay
                          ? renderCellContent([], [], userDay.am_fast_tasks || [], "am", day.date, user.user_id)
                          : <div className="min-h-20 text-xs text-muted-foreground/50">-</div>}
                      </TableCell>
                    )
                  })}
                </TableRow>

                <TableRow className="border-t-2 border-border">
                  <TableCell className="sticky left-24 z-10 w-10 min-w-10 bg-background text-center align-top">
                    <div className="text-xs font-medium text-primary">PM</div>
                  </TableCell>
                  <TableCell className="sticky left-34 z-10 w-10 min-w-10 bg-background text-center align-top text-xs font-bold uppercase">
                    PRJK
                  </TableCell>
                  {allUsers.map((user) => {
                    const userDay = day.users.find((item) => item.user_id === user.user_id)
                    return (
                      <TableCell key={`${user.user_id}-pm-prjk`} className="w-56 min-w-56 align-top">
                        {userDay
                          ? renderCellContent(
                              userDay.pm_projects || [],
                              userDay.pm_system_tasks || [],
                              [],
                              "pm",
                              day.date,
                              user.user_id
                            )
                          : <div className="min-h-20 text-xs text-muted-foreground/50">-</div>}
                      </TableCell>
                    )
                  })}
                </TableRow>

                <TableRow className="border-t border-border">
                  <TableCell className="sticky left-24 z-10 w-10 min-w-10 bg-background text-center align-top">
                    <div className="text-xs font-medium text-primary">PM</div>
                  </TableCell>
                  <TableCell className="sticky left-34 z-10 w-10 min-w-10 bg-background text-center align-top text-xs font-bold uppercase">
                    FT
                  </TableCell>
                  {allUsers.map((user) => {
                    const userDay = day.users.find((item) => item.user_id === user.user_id)
                    return (
                      <TableCell key={`${user.user_id}-pm-ft`} className="w-56 min-w-56 align-top">
                        {userDay
                          ? renderCellContent([], [], userDay.pm_fast_tasks || [], "pm", day.date, user.user_id)
                          : <div className="min-h-20 text-xs text-muted-foreground/50">-</div>}
                      </TableCell>
                    )
                  })}
                </TableRow>
              </React.Fragment>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

export function WeeklyPlannerSnapshotsView({
  departmentId,
  allDepartmentsValue,
}: WeeklyPlannerSnapshotsViewProps) {
  const { apiFetch, user } = useAuth()

  const [overview, setOverview] = React.useState<SnapshotOverviewWeek[]>([])
  const [selectedWeekStart, setSelectedWeekStart] = React.useState<string>("")
  const [selectedPlanType, setSelectedPlanType] = React.useState<SnapshotType>("PLANNED")
  const [compare, setCompare] = React.useState<SnapshotCompareResponse | null>(null)
  const [snapshotById, setSnapshotById] = React.useState<Record<string, SnapshotData>>({})
  const [selectedPlannedVersionId, setSelectedPlannedVersionId] = React.useState<string>("")
  const [selectedFinalVersionId, setSelectedFinalVersionId] = React.useState<string>("")
  const [isLoadingOverview, setIsLoadingOverview] = React.useState(false)
  const [isLoadingCompare, setIsLoadingCompare] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [isExporting, setIsExporting] = React.useState(false)
  const [isExportingPlanVsFinal, setIsExportingPlanVsFinal] = React.useState(false)
  const [planVsFinal, setPlanVsFinal] = React.useState<WeeklyPlanPerformanceResponse | null>(null)
  const [isLoadingPlanVsFinal, setIsLoadingPlanVsFinal] = React.useState(false)
  const [planVsFinalError, setPlanVsFinalError] = React.useState<string | null>(null)

  const fetchSnapshot = React.useCallback(
    async (snapshotId: string) => {
      const res = await apiFetch(`/planners/weekly-snapshots/${snapshotId}`)
      if (!res.ok) {
        throw new Error("Failed to load snapshot version")
      }
      return (await res.json()) as SnapshotData
    },
    [apiFetch]
  )

  const loadOverview = React.useCallback(async () => {
    if (!departmentId || departmentId === allDepartmentsValue) {
      setOverview([])
      setCompare(null)
      setError(null)
      return
    }
    setIsLoadingOverview(true)
    setError(null)
    try {
      const qs = new URLSearchParams()
      qs.set("department_id", departmentId)
      const res = await apiFetch(`/planners/weekly-snapshots/overview?${qs.toString()}`)
      if (!res.ok) {
        throw new Error("Failed to load snapshot overview")
      }
      const data = (await res.json()) as SnapshotOverviewResponse
      setOverview(data.weeks)
      const preferred = data.weeks.find((week) => week.label === "this_week") ?? data.weeks[0]
      setSelectedWeekStart((current) =>
        data.weeks.some((week) => week.week_start === current) ? current : (preferred?.week_start ?? "")
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load snapshot overview")
      setOverview([])
      setSelectedWeekStart("")
      setCompare(null)
    } finally {
      setIsLoadingOverview(false)
    }
  }, [allDepartmentsValue, apiFetch, departmentId])

  const loadCompare = React.useCallback(async () => {
    if (!departmentId || departmentId === allDepartmentsValue || !selectedWeekStart) {
      setCompare(null)
      return
    }
    setIsLoadingCompare(true)
    setError(null)
    try {
      const qs = new URLSearchParams()
      qs.set("department_id", departmentId)
      qs.set("week_start", selectedWeekStart)
      const res = await apiFetch(`/planners/weekly-snapshots/compare?${qs.toString()}`)
      if (!res.ok) {
        throw new Error("Failed to load snapshot comparison")
      }
      const data = (await res.json()) as SnapshotCompareResponse
      setCompare(data)
      setSnapshotById(() => {
        const next: Record<string, SnapshotData> = {}
        if (data.planned_official) next[data.planned_official.id] = data.planned_official
        if (data.final_official) next[data.final_official.id] = data.final_official
        return next
      })
      setSelectedPlannedVersionId(data.planned_official?.id ?? "")
      setSelectedFinalVersionId(data.final_official?.id ?? "")
      if (!data.planned_versions.length && data.final_versions.length) {
        setSelectedPlanType("FINAL")
      } else {
        setSelectedPlanType("PLANNED")
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load snapshot comparison")
      setCompare(null)
    } finally {
      setIsLoadingCompare(false)
    }
  }, [allDepartmentsValue, apiFetch, departmentId, selectedWeekStart])

  React.useEffect(() => {
    void loadOverview()
  }, [loadOverview])

  React.useEffect(() => {
    void loadCompare()
  }, [loadCompare])

  React.useEffect(() => {
    setPlanVsFinal(null)
    setPlanVsFinalError(null)
  }, [departmentId, selectedWeekStart])

  const loadPlanVsFinal = React.useCallback(async () => {
    if (!departmentId || departmentId === allDepartmentsValue || !selectedWeekStart) {
      setPlanVsFinal(null)
      setPlanVsFinalError(null)
      return
    }
    if (isLoadingPlanVsFinal) return

    setIsLoadingPlanVsFinal(true)
    setPlanVsFinalError(null)
    try {
      const qs = new URLSearchParams()
      qs.set("department_id", departmentId)
      qs.set("week_start", selectedWeekStart)
      const res = await apiFetch(`/planners/weekly-snapshots/plan-vs-final?${qs.toString()}`)
      if (!res.ok) {
        const message = await res.text().catch(() => "Failed to load plan vs final report")
        throw new Error(message || "Failed to load plan vs final report")
      }
      const payload = (await res.json()) as WeeklyPlanPerformanceResponse
      setPlanVsFinal(payload)
    } catch (err) {
      setPlanVsFinal(null)
      setPlanVsFinalError(err instanceof Error ? err.message : "Failed to load plan vs final report")
    } finally {
      setIsLoadingPlanVsFinal(false)
    }
  }, [allDepartmentsValue, apiFetch, departmentId, isLoadingPlanVsFinal, selectedWeekStart])

  const activeVersions = selectedPlanType === "PLANNED"
    ? (compare?.planned_versions ?? [])
    : (compare?.final_versions ?? [])

  const selectedVersionId = selectedPlanType === "PLANNED"
    ? selectedPlannedVersionId
    : selectedFinalVersionId

  const handleVersionChange = React.useCallback(
    async (snapshotId: string) => {
      if (selectedPlanType === "PLANNED") {
        setSelectedPlannedVersionId(snapshotId)
      } else {
        setSelectedFinalVersionId(snapshotId)
      }
      if (!snapshotId || snapshotById[snapshotId]) return
      try {
        const data = await fetchSnapshot(snapshotId)
        setSnapshotById((prev) => ({ ...prev, [snapshotId]: data }))
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load snapshot version")
      }
    },
    [fetchSnapshot, selectedPlanType, snapshotById]
  )

  const activeSnapshot = selectedVersionId ? snapshotById[selectedVersionId] ?? null : null

  const exportSnapshotExcel = React.useCallback(async () => {
    if (!activeSnapshot) return
    if (isExporting) return
    setIsExporting(true)
    try {
      const qs = new URLSearchParams()
      qs.set("snapshot_id", activeSnapshot.id)
      const res = await apiFetch(`/exports/weekly-snapshot.xlsx?${qs.toString()}`)
      if (!res.ok) {
        const message = await res.text().catch(() => "Failed to export snapshot")
        toast.error(message || "Failed to export snapshot")
        return
      }
      const blob = await res.blob()
      if (blob.size === 0) {
        toast.error("Export returned an empty file.")
        return
      }
      const filename = parseFilenameFromDisposition(res.headers.get("content-disposition"))
      triggerBlobDownload(blob, filename || "weekly_snapshot.xlsx")
    } catch (err) {
      console.error("Failed to export snapshot", err)
      toast.error("Failed to export snapshot")
    } finally {
      setIsExporting(false)
    }
  }, [activeSnapshot, apiFetch, isExporting])

  const exportPlanVsFinalExcel = React.useCallback(async () => {
    if (!departmentId || departmentId === allDepartmentsValue || !selectedWeekStart) return
    if (isExportingPlanVsFinal) return
    setIsExportingPlanVsFinal(true)
    try {
      const qs = new URLSearchParams()
      qs.set("department_id", departmentId)
      qs.set("week_start", selectedWeekStart)
      const res = await apiFetch(`/exports/weekly-plan-vs-final.xlsx?${qs.toString()}`)
      if (!res.ok) {
        const message = await res.text().catch(() => "Failed to export plan vs final report")
        toast.error(message || "Failed to export plan vs final report")
        return
      }
      const blob = await res.blob()
      if (blob.size === 0) {
        toast.error("Export returned an empty file.")
        return
      }
      const filename = parseFilenameFromDisposition(res.headers.get("content-disposition"))
      triggerBlobDownload(blob, filename || "plan_vs_final_report.xlsx")
    } catch (err) {
      console.error("Failed to export plan vs final report", err)
      toast.error("Failed to export plan vs final report")
    } finally {
      setIsExportingPlanVsFinal(false)
    }
  }, [allDepartmentsValue, apiFetch, departmentId, isExportingPlanVsFinal, selectedWeekStart])

  const handlePrintPlanVsFinal = React.useCallback(() => {
    if (!planVsFinal) return

    const printWindow = window.open("", "_blank")
    if (!printWindow) return

    const weekRange = `${formatDate(planVsFinal.week_start)} - ${formatDate(planVsFinal.week_end)}`
    const departmentLabel = formatDepartmentName(planVsFinal.department_name || "")
    const printedAt = new Date()
    const printedAtLabel = formatDateTimeDMY(printedAt)

    const root = document.getElementById(PLAN_VS_FINAL_PRINT_ROOT_ID)
    const table = root?.querySelector("table")
    const reportHtml = table?.outerHTML || root?.innerHTML || ""
    if (!reportHtml) {
      toast.error("Nothing to print for plan vs final report.")
      printWindow.close()
      return
    }

    const baselineLabel = planVsFinal.snapshot_created_at ? formatDateTimeDMY(planVsFinal.snapshot_created_at) : ""
    const finalLabel = planVsFinal.final_snapshot_created_at ? formatDateTimeDMY(planVsFinal.final_snapshot_created_at) : ""

    const html = `
      <!DOCTYPE html>
      <html>
        <head>
          <title>Plan vs Final Report - ${weekRange}</title>
          <style>
            @media print {
              @page { size: letter landscape; margin: 0.35in; }
            }

            body { font-family: Arial, sans-serif; font-size: 11px; color: #000; }
            .print-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 8px; }
            .print-title { font-size: 16px; font-weight: 700; margin: 0; }
            .print-meta { font-size: 11px; margin-top: 2px; }
            .print-datetime { font-size: 11px; text-align: right; white-space: nowrap; }

            table { width: 100%; border-collapse: collapse; table-layout: fixed; }
            th, td { border: 1px solid #000; padding: 6px; vertical-align: top; }
            th { font-weight: 700; }

            a { color: #000; text-decoration: none; }
            td div { margin-bottom: 4px; }
            tr { break-inside: avoid; page-break-inside: avoid; }
          </style>
        </head>
        <body>
          <div class="print-header">
            <div>
              <h1 class="print-title">PLAN VS FINAL REPORT</h1>
              <div class="print-meta"><strong>Week:</strong> ${weekRange}</div>
              <div class="print-meta"><strong>Department:</strong> ${departmentLabel || "-"}</div>
              ${baselineLabel ? `<div class="print-meta"><strong>Baseline plan saved:</strong> ${baselineLabel}</div>` : ""}
              ${finalLabel ? `<div class="print-meta"><strong>Final snapshot saved:</strong> ${finalLabel}</div>` : ""}
            </div>
            <div class="print-datetime">
              <div><strong>Printed:</strong> ${printedAtLabel}</div>
            </div>
          </div>
          ${reportHtml}
        </body>
      </html>
    `

    printWindow.document.open()
    printWindow.document.write(html)
    printWindow.document.close()
    printWindow.focus()

    setTimeout(() => {
      printWindow.print()
    }, 200)
  }, [planVsFinal])

  const handlePrintSnapshot = React.useCallback(() => {
    if (!activeSnapshot) return
    const department = activeSnapshot.payload.department
    if (!department) return

    const printWindow = window.open("", "_blank")
    if (!printWindow) return

    const weekRange = `${formatDate(activeSnapshot.payload.week_start)} - ${formatDate(activeSnapshot.payload.week_end)}`
    const selectedDept = formatDepartmentName(department.department_name)
    const printedAt = new Date()
    const printedAtLabel = formatDateTimeDMY(printedAt)
    const printInitials = (user?.full_name || user?.username || "")
      .trim()
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join("") || "?"

    const versionLabel = `${activeSnapshot.is_official ? "Official - " : ""}${formatDateTime(activeSnapshot.created_at)}`
    const planLabel = activeSnapshot.snapshot_type === "FINAL" ? "Final Snapshot" : "Planned Snapshot"

    const legendEntries = buildLegendDisplayEntries({
      entries: activeSnapshot.payload.legend_entries || [],
      departmentId: department.department_id,
      weekStart: activeSnapshot.payload.week_start,
      departmentName: department.department_name,
    })

    const allUsers = (() => {
      const map = new Map<string, { user_id: string; user_name: string }>()
      department.days.forEach((day) => {
        day.users.forEach((userDay) => {
          if (!map.has(userDay.user_id)) {
            map.set(userDay.user_id, { user_id: userDay.user_id, user_name: (userDay.user_name || "").trim() })
          }
        })
      })
      return Array.from(map.values())
        .filter((entry) => entry.user_name.length > 0)
        .sort((a, b) => a.user_name.localeCompare(b.user_name))
    })()

    const buildBadgeClass = (label: string) => {
      if (label === "BLL") return "badge-bll"
      if (label === "R1") return "badge-r1"
      if (label === "1H") return "badge-1h"
      if (label === "GA") return "badge-ga"
      if (label === "P:") return "badge-p"
      if (label === "N") return "badge-n"
      return ""
    }

    const getTaskDisplayTitle = (task: SnapshotTaskEntry) => task.task_title || task.title || "-"
    const getPrintTaskStatusClass = (
      task: Pick<SnapshotTaskEntry, "status" | "completed_at" | "daily_status" | "created_at" | "is_deadline_important">,
      dayIso: string
    ) => {
      if (task.is_deadline_important) return "task-status-deadline"
      const statusValue = getStatusValueForDay(task.status, task.completed_at, dayIso, task.daily_status)
      const isNew = isTaskNewForWeek(task.created_at, activeSnapshot.payload.week_start)
      if (isNew) {
        if (statusValue === "DONE") return "task-status-new-done"
        if (statusValue === "WAITING_CONFIRMATION") return "task-status-waiting"
        if (statusValue === "WAITING_CLIENT") return "task-status-waiting-client"
        if (statusValue === "PAUSED") return "task-status-paused"
        if (statusValue === "IN_PROGRESS") return "task-status-in-progress"
        return "task-status-new-open"
      }
      if (statusValue === "DONE") return "task-status-done"
      if (statusValue === "WAITING_CONFIRMATION") return "task-status-waiting"
      if (statusValue === "WAITING_CLIENT") return "task-status-waiting-client"
      if (statusValue === "PAUSED") return "task-status-paused"
      if (statusValue === "IN_PROGRESS") return "task-status-in-progress"
      return "task-status-todo"
    }
    const buildPrintNewBadge = (createdAt?: string | null) => {
      if (!isTaskNewForWeek(createdAt, activeSnapshot.payload.week_start)) return ""
      return ` <span class="badge badge-new">NEW</span>`
    }
    const buildPrintTaskMarker = (task: Pick<SnapshotTaskEntry, "one_h_marker" | "one_h_marker_by_ga">) => {
      const label = taskOneHMarkerLabel(task.one_h_marker, task.one_h_marker_by_ga)
      return label ? `<span class="task-marker">${label}</span>` : ""
    }

    const renderDayGroupHtml = (day: SnapshotDay, dayIndex: number, usersChunk: { user_id: string; user_name: string }[]) => {
      const dayName = DAY_NAMES[dayIndex] || ""
      const dayDate = formatDate(day.date)
      const dayIso = day.date

      let html = `
        <tr>
          <td class="day-cell" rowspan="4" style="text-align: left; padding: 1px;">
            <div style="display: flex; flex-direction: column;">
              <strong class="print-subhead">${dayName}</strong>
              <span class="print-subhead" style="margin-top: 0.5px;">${dayDate}</span>
            </div>
          </td>
          <td class="print-subhead time-cell" rowspan="2">AM</td>
          <td class="ll-cell print-subhead">PRJK</td>
      `

      usersChunk.forEach((u) => {
        const userDay = day.users.find((item) => item.user_id === u.user_id)
        const projects = userDay?.am_projects || []
        const systemTasks = userDay?.am_system_tasks || []

        html += `<td>`
        if (projects.length > 0 || systemTasks.length > 0) {
          projects.forEach((project, projectIndex) => {
            html += `<div class="project-card">
              <div class="project-title">${projectIndex + 1}. ${getProjectDisplayTitle(project)}</div>`
            if (project.tasks && project.tasks.length > 0) {
              project.tasks.forEach((task, taskIndex) => {
                const statusClass = getPrintTaskStatusClass(task, dayIso)
                const taskNumber = `${projectIndex + 1}.${taskIndex + 1}`
                html += `<div class="task-item ${statusClass}">${taskNumber}. ${buildPrintTaskMarker(task)}${getTaskDisplayTitle(task)}`
                if (task.daily_products) {
                  html += ` <span class="products">${task.daily_products} pcs</span>`
                }
                const badge = getTaskStatusBadge(task)
                if (badge) {
                  html += ` <span class="badge ${buildBadgeClass(badge.label)}">${badge.label}</span>`
                }
                html += buildPrintNewBadge(task.created_at)
                html += `</div>`
              })
            }
            html += `</div>`
          })
          if (systemTasks.length > 0) {
            html += `<div style="margin-top: 1px; font-size: 4pt; color: #1e40af;"><strong>System Tasks:</strong>`
            systemTasks.forEach((task, taskIndex) => {
              const statusClass = getPrintTaskStatusClass(task, dayIso)
              html += `<div class="task-item ${statusClass}">${taskIndex + 1}. ${buildPrintTaskMarker(task)}${getTaskDisplayTitle(task)}`
              const badge = getTaskStatusBadge(task)
              if (badge) {
                html += ` <span class="badge ${buildBadgeClass(badge.label)}">${badge.label}</span>`
              }
              html += buildPrintNewBadge(task.created_at)
              html += `</div>`
            })
            html += `</div>`
          }
        } else {
          html += `<div class="empty-cell">-</div>`
        }
        html += `</td>`
      })
      html += `</tr>`

      html += `<tr>`
      html += `<td class="ll-cell print-subhead">FT</td>`
      usersChunk.forEach((u) => {
        const userDay = day.users.find((item) => item.user_id === u.user_id)
        const fastTasks = sortFastTasks(userDay?.am_fast_tasks || [])

        html += `<td>`
        if (fastTasks.length > 0) {
          html += `<div style="font-size: 4pt; color: #0f172a;">`
          fastTasks.forEach((task, taskIndex) => {
            const statusClass = getPrintTaskStatusClass(task, dayIso)
            html += `<div class="task-item ${statusClass}">${taskIndex + 1}. ${buildPrintTaskMarker(task)}${getTaskDisplayTitle(task)}`
            const badge = getFastTaskBadge(task)
            if (badge) {
              html += ` <span class="badge ${buildBadgeClass(badge.label)}">${badge.label}</span>`
            }
            html += buildPrintNewBadge(task.created_at)
            html += `</div>`
          })
          html += `</div>`
        } else {
          html += `<div class="empty-cell">-</div>`
        }
        html += `</td>`
      })
      html += `</tr>`

      html += `<tr style="border-top: 2px solid #000;">`
      html += `<td class="print-subhead time-cell" rowspan="2">PM</td>`
      html += `<td class="ll-cell print-subhead">PRJK</td>`
      usersChunk.forEach((u) => {
        const userDay = day.users.find((item) => item.user_id === u.user_id)
        const projects = userDay?.pm_projects || []
        const systemTasks = userDay?.pm_system_tasks || []

        html += `<td>`
        if (projects.length > 0 || systemTasks.length > 0) {
          projects.forEach((project, projectIndex) => {
            html += `<div class="project-card">
              <div class="project-title">${projectIndex + 1}. ${getProjectDisplayTitle(project)}</div>`
            if (project.tasks && project.tasks.length > 0) {
              project.tasks.forEach((task, taskIndex) => {
                const statusClass = getPrintTaskStatusClass(task, dayIso)
                const taskNumber = `${projectIndex + 1}.${taskIndex + 1}`
                html += `<div class="task-item ${statusClass}">${taskNumber}. ${buildPrintTaskMarker(task)}${getTaskDisplayTitle(task)}`
                if (task.daily_products) {
                  html += ` <span class="products">${task.daily_products} pcs</span>`
                }
                const badge = getTaskStatusBadge(task)
                if (badge) {
                  html += ` <span class="badge ${buildBadgeClass(badge.label)}">${badge.label}</span>`
                }
                html += buildPrintNewBadge(task.created_at)
                html += `</div>`
              })
            }
            html += `</div>`
          })
          if (systemTasks.length > 0) {
            html += `<div style="margin-top: 1px; font-size: 4pt; color: #1e40af;"><strong>System Tasks:</strong>`
            systemTasks.forEach((task, taskIndex) => {
              const statusClass = getPrintTaskStatusClass(task, dayIso)
              html += `<div class="task-item ${statusClass}">${taskIndex + 1}. ${buildPrintTaskMarker(task)}${getTaskDisplayTitle(task)}`
              const badge = getTaskStatusBadge(task)
              if (badge) {
                html += ` <span class="badge ${buildBadgeClass(badge.label)}">${badge.label}</span>`
              }
              html += buildPrintNewBadge(task.created_at)
              html += `</div>`
            })
            html += `</div>`
          }
        } else {
          html += `<div class="empty-cell">-</div>`
        }
        html += `</td>`
      })
      html += `</tr>`

      html += `<tr>`
      html += `<td class="ll-cell print-subhead">FT</td>`
      usersChunk.forEach((u) => {
        const userDay = day.users.find((item) => item.user_id === u.user_id)
        const fastTasks = sortFastTasks(userDay?.pm_fast_tasks || [])

        html += `<td>`
        if (fastTasks.length > 0) {
          html += `<div style="font-size: 4pt; color: #0f172a;">`
          fastTasks.forEach((task, taskIndex) => {
            const statusClass = getPrintTaskStatusClass(task, dayIso)
            html += `<div class="task-item ${statusClass}">${taskIndex + 1}. ${buildPrintTaskMarker(task)}${getTaskDisplayTitle(task)}`
            const badge = getFastTaskBadge(task)
            if (badge) {
              html += ` <span class="badge ${buildBadgeClass(badge.label)}">${badge.label}</span>`
            }
            html += buildPrintNewBadge(task.created_at)
            html += `</div>`
          })
          html += `</div>`
        } else {
          html += `<div class="empty-cell">-</div>`
        }
        html += `</td>`
      })
      html += `</tr>`

      return html
    }

    const doc = printWindow.document

    const baseHtml = `
      <!DOCTYPE html>
      <html>
        <head>
          <title>Weekly Snapshot - ${weekRange}</title>
          <style>
            @media print {
              @page {
                size: letter portrait;
                margin-top: 0.35in;
                margin-bottom: 0.35in;
                margin-left: 0.4in;
                margin-right: 0.4in;
              }
              body { margin: 0; padding: 0; }
              .print-page { page-break-after: avoid; page-break-inside: avoid; }
              .print-page:last-child { page-break-after: avoid; }
              table { page-break-inside: avoid; }
              tr { page-break-inside: avoid; }
              tbody { page-break-inside: avoid; }
            }
            * {
              box-sizing: border-box;
              -webkit-print-color-adjust: exact;
              print-color-adjust: exact;
              line-height: 1.1;
            }
            body {
              font-family: Arial, sans-serif;
              font-size: 5.5pt;
              margin: 0;
              padding: 0;
              width: 100%;
              margin-left: auto;
              margin-right: auto;
              direction: ltr;
            }
            .print-page {
              position: relative;
              height: calc(11in - 0.7in);
              width: 100%;
              display: grid;
              grid-template-rows: auto auto 1fr auto;
            }
            .print-header {
              display: grid;
              grid-template-columns: 1fr auto 1fr;
              align-items: center;
              margin-bottom: 2px;
            }
            .print-header.compact {
              grid-template-columns: 1fr auto;
              margin-bottom: 2px;
            }
            .print-title {
              margin: 0;
              font-size: 8pt;
              font-weight: 700;
              text-transform: uppercase;
              text-align: center;
              color: #0f172a;
              line-height: 1.1;
            }
            .print-datetime {
              text-align: right;
              font-size: 6pt;
              color: #334155;
            }
            .print-meta {
              text-align: center;
              margin-bottom: 2px;
              font-size: 6pt;
              color: #334155;
            }
            .print-meta.compact {
              margin-bottom: 2px;
              font-size: 0;
              line-height: 0;
              height: 0;
              overflow: hidden;
            }
            .print-content {
              width: 100%;
              min-height: 0;
              overflow: visible;
              max-height: calc(11in - 0.7in - 70px);
              padding-left: 0.05in;
              padding-right: 0.05in;
            }
            .print-dept-title {
              margin-top: 2px;
              margin-bottom: 1px;
              font-size: 7pt;
              font-weight: 700;
            }
            .print-legend {
              margin-top: 2px;
              margin-bottom: 6px;
              break-inside: avoid;
              page-break-inside: avoid;
            }
            .print-legend-title {
              font-size: 6.5pt;
              font-weight: 700;
              margin-bottom: 2px;
              color: #0f172a;
            }
            .legend-panels {
              display: flex;
              gap: 6px;
              align-items: stretch;
            }
            .legend-panel {
              border: 0.5px solid #cbd5e1;
              border-radius: 3px;
              padding: 2px;
            }
            .legend-panel-colors {
              width: 35%;
              flex: 0 0 35%;
            }
            .legend-panel-qa {
              width: 65%;
              flex: 0 0 65%;
            }
            .legend-table {
              width: 100%;
              border-collapse: collapse;
              margin: 0;
            }
            .legend-table th,
            .legend-table td {
              font-size: 6pt;
              padding: 1px;
              vertical-align: middle;
            }
            .legend-table th {
              border-bottom: 0.5px solid #000;
            }
            .legend-color-box {
              width: 18px;
              height: 10px;
              border: 0.5px solid #000;
            }
            .legend-question {
              color: #991b1b;
              font-weight: 600;
            }
            .legend-answer-line {
              height: 9px;
              border-bottom: 0.5px solid #000;
            }
            .print-legend-spacer {
              height: 0.18in;
            }
            table {
              width: 100%;
              border-collapse: collapse;
              table-layout: fixed;
              margin-bottom: 0.01in;
              direction: ltr;
            }
            thead {
              display: table-header-group;
            }
            tbody.day-group {
              break-inside: avoid;
              page-break-inside: avoid;
            }
            tr {
              break-inside: avoid;
              page-break-inside: avoid;
            }
            .print-content {
              max-height: calc(11in - 0.7in - 70px);
              overflow: visible;
            }
            th {
              background-color: #e2e8f0;
              border: 0.5px solid #000;
              padding: 1px;
              text-align: left;
              font-weight: bold;
              font-size: 5.5pt;
              text-transform: uppercase;
              vertical-align: bottom;
              line-height: 1.1;
              overflow-wrap: anywhere;
              word-break: break-word;
            }
            th.user-header {
              white-space: normal;
              word-break: break-word;
              font-size: 5.5pt;
              line-height: 1.05;
            }
            td {
              border: 0.5px solid #000;
              padding: 0.5px;
              vertical-align: bottom;
              font-size: 5.5pt;
              line-height: 1.1;
              text-align: left;
              overflow-wrap: anywhere;
              word-break: break-word;
            }
            .day-cell {
              font-weight: bold;
              background-color: #f9f9f9;
              text-align: left;
              width: 70px;
              vertical-align: bottom;
              white-space: nowrap;
            }
            .ll-cell {
              font-weight: bold;
              background-color: #f9f9f9;
              text-align: left;
              width: 32px;
              vertical-align: bottom;
              font-size: 4.5pt;
              line-height: 1;
              letter-spacing: -0.2px;
              white-space: nowrap;
              padding-left: 0.5px;
              padding-right: 0.5px;
            }
            .time-cell {
              width: 22px;
              text-align: left;
              padding-left: 1px;
              padding-right: 1px;
              vertical-align: bottom;
            }
            .print-subhead {
              font-weight: bold;
              text-transform: uppercase;
              font-size: 6pt;
            }
            .project-card {
              margin: 1px 0;
              padding: 1px;
              background-color: #f5f5f5;
              border: 0.5px solid #ddd;
              border-radius: 2px;
              break-inside: avoid;
              page-break-inside: avoid;
            }
            .project-title {
              font-weight: bold;
              margin-bottom: 0.5px;
              line-height: 1.1;
              overflow-wrap: anywhere;
              word-break: break-word;
            }
            .task-item {
              font-size: 5pt;
              margin: 0.5px 0;
              padding: 0.5px 1px;
              border: 0.5px solid #000;
              border-radius: 2px;
              background-color: #fff;
              break-inside: avoid;
              page-break-inside: avoid;
              line-height: 1.1;
              overflow-wrap: anywhere;
              word-break: break-word;
            }
            .task-marker { color: #dc2626; font-weight: 900; margin-right: 2px; }
            .task-status-todo { background-color: #FFC4ED; }
            .task-status-in-progress { background-color: #FFFF00; }
            .task-status-paused { background-color: #CBD5E1; }
            .task-status-waiting { background-color: #FFEDD5; border-color: #C2410C; color: #9A3412; }
            .task-status-waiting-client { background-color: #E2C15B; border-color: #B8860B; color: #4F3A00; }
            .task-status-done { background-color: #C4FDC4; }
            .task-status-new-open { background-color: #dbeafe; border-color: #1d4ed8; }
            .task-status-new-done { background-color: #6ee7b7; border-color: #059669; }
            .task-status-deadline { background-color: #dc2626; border-color: #991b1b; color: #ffffff; }
            .badge {
              display: inline-block;
              padding: 0.5px 2px;
              border-radius: 2px;
              font-size: 5pt;
              font-weight: bold;
              margin-left: 1px;
              line-height: 1.1;
            }
            .badge-bll { background-color: #fee2e2; color: #991b1b; }
            .badge-r1 { background-color: #e0e7ff; color: #3730a3; }
            .badge-1h { background-color: #fef3c7; color: #92400e; }
            .badge-ga { background-color: #dbeafe; color: #1e40af; }
            .badge-p { background-color: #d1fae5; color: #065f46; }
            .badge-n { background-color: #f1f5f9; color: #475569; }
            .badge-new {
              background-color: #dbeafe;
              color: #1e40af;
            }
            .products {
              color: #2563eb;
              font-weight: bold;
              font-size: 5pt;
            }
            .empty-cell {
              text-align: left;
              color: #999;
            }
            .pm-row {
              border-top: 1px solid #000 !important;
            }
            .table-narrow th,
            .table-narrow td {
              font-size: 5pt;
            }
            .table-narrow .task-item,
            .table-narrow .badge,
            .table-narrow .products {
              font-size: 4pt;
            }
            .table-compact th,
            .table-compact td {
              font-size: 5pt;
              padding: 0.5px;
            }
            .table-compact .task-item,
            .table-compact .badge,
            .table-compact .products {
              font-size: 4pt;
            }
            .table-compact th.user-header {
              font-size: 5pt;
              line-height: 1;
            }
            .table-ultra-compact th,
            .table-ultra-compact td {
              font-size: 4.5pt;
              padding: 0.25px;
            }
            .table-ultra-compact .task-item,
            .table-ultra-compact .badge,
            .table-ultra-compact .products {
              font-size: 3.5pt;
            }
            .table-ultra-compact th.user-header {
              font-size: 4.5pt;
              line-height: 1;
            }
            .print-footer {
              margin-top: auto;
              display: grid;
              grid-template-columns: 1fr auto 1fr;
              padding-left: 0.1in;
              padding-right: 0.04in;
              padding-bottom: 0.05in;
              font-size: 6pt;
              color: #334155;
              background: #fff;
            }
            .print-page-count {
              text-align: center;
            }
            .print-initials {
              text-align: right;
            }
            .print-measure {
              position: absolute;
              left: -9999px;
              top: 0;
              visibility: hidden;
              width: 7.7in;
            }
          </style>
        </head>
        <body>
          <div id="print-root"></div>
        </body>
      </html>
    `

    printWindow.document.open()
    printWindow.document.write(baseHtml)
    printWindow.document.close()
    printWindow.focus()

    const root = doc.getElementById("print-root")
    if (!root) return

    const createHeader = (showTitle: boolean) => {
      const header = doc.createElement("div")
      header.className = showTitle ? "print-header" : "print-header compact"
      header.innerHTML = showTitle
        ? `
        <div></div>
        <div class="print-title">Weekly Snapshot</div>
        <div class="print-datetime">${printedAtLabel}</div>
      `
        : `
        <div></div>
        <div class="print-datetime">${printedAtLabel}</div>
      `
      return header
    }

    const createMeta = (showMeta: boolean) => {
      const meta = doc.createElement("div")
      meta.className = showMeta ? "print-meta" : "print-meta compact"
      meta.innerHTML = showMeta
        ? `<strong>Week:</strong> ${weekRange} | <strong>Department:</strong> ${selectedDept} | <strong>Plan:</strong> ${planLabel} | <strong>Version:</strong> ${versionLabel}`
        : ""
      return meta
    }

    const createFooter = () => {
      const footer = doc.createElement("div")
      footer.className = "print-footer"
      footer.innerHTML = `
        <div></div>
        <div class="print-page-count"></div>
        <div class="print-initials">PUNOI: ${printInitials}</div>
      `
      return footer
    }

    const createLegendSection = (entries: LegendEntry[]) => {
      if (!entries || entries.length === 0) return null

      const wrapper = doc.createElement("div")
      wrapper.className = "print-legend"

      const title = doc.createElement("div")
      title.className = "print-legend-title"
      title.textContent = "Legend / Questions"
      wrapper.appendChild(title)

      const panels = doc.createElement("div")
      panels.className = "legend-panels"

      const swatches = buildLegendSwatches(entries)
      const colorPanel = doc.createElement("div")
      colorPanel.className = "legend-panel legend-panel-colors"
      const colorTable = doc.createElement("table")
      colorTable.className = "legend-table"
      colorTable.innerHTML = `
        <thead>
          <tr>
            <th>Color</th>
            <th>Label</th>
          </tr>
        </thead>
      `
      const colorBody = doc.createElement("tbody")
      swatches.forEach((swatch) => {
        const row = doc.createElement("tr")
        const colorCell = doc.createElement("td")
        const colorBox = doc.createElement("div")
        colorBox.className = "legend-color-box"
        colorBox.style.backgroundColor = swatch.color
        colorCell.appendChild(colorBox)
        row.appendChild(colorCell)

        const labelCell = doc.createElement("td")
        labelCell.textContent = swatch.displayLabel
        row.appendChild(labelCell)
        colorBody.appendChild(row)
      })
      colorTable.appendChild(colorBody)
      colorPanel.appendChild(colorTable)
      panels.appendChild(colorPanel)

      const qaPanel = doc.createElement("div")
      qaPanel.className = "legend-panel legend-panel-qa"
      const qaTable = doc.createElement("table")
      qaTable.className = "legend-table"
      qaTable.innerHTML = `
        <thead>
          <tr>
            <th>Question</th>
            <th>Answer</th>
          </tr>
        </thead>
      `
      const qaBody = doc.createElement("tbody")
      entries.forEach((entry) => {
        const row = doc.createElement("tr")
        const questionCell = doc.createElement("td")
        if (entry.question_text) {
          const question = doc.createElement("span")
          question.className = "legend-question"
          question.textContent = entry.question_text
          questionCell.appendChild(question)
        } else {
          questionCell.textContent = "-"
        }
        row.appendChild(questionCell)

        const answerCell = doc.createElement("td")
        const answer = entry.answer_text?.trim() || ""
        if (answer) {
          answerCell.textContent = answer
        } else {
          const answerLine = doc.createElement("div")
          answerLine.className = "legend-answer-line"
          answerCell.appendChild(answerLine)
        }
        row.appendChild(answerCell)
        qaBody.appendChild(row)
      })
      qaTable.appendChild(qaBody)
      qaPanel.appendChild(qaTable)
      panels.appendChild(qaPanel)

      wrapper.appendChild(panels)
      return wrapper
    }

    const createPage = (options?: { showTitle?: boolean; showMeta?: boolean }) => {
      const { showTitle = true, showMeta = true } = options || {}
      const page = doc.createElement("div")
      page.className = "print-page"
      page.appendChild(createHeader(showTitle))
      page.appendChild(createMeta(showMeta))
      const content = doc.createElement("div")
      content.className = "print-content"
      page.appendChild(content)
      page.appendChild(createFooter())
      return { page, content }
    }

    const dayColWidth = 70
    const llColWidth = 32
    const timeColWidth = 22
    const minUserColWidth = 48
    const targetUserColWidth = 72

    const measure = doc.createElement("div")
    measure.className = "print-measure"
    root.appendChild(measure)

    const getPrintableWidth = () => {
      if (measure.clientWidth) return measure.clientWidth
      return Math.max(0, Math.floor(printWindow.innerWidth * 0.9))
    }

    const getUserColumnWidth = (userCount: number) => {
      const measureWidth = getPrintableWidth() ? Math.floor(getPrintableWidth() * 0.98) : 0
      const fixedWidth = dayColWidth + llColWidth + timeColWidth
      const availableWidth = Math.max(0, measureWidth - fixedWidth)
      if (userCount <= 0) return minUserColWidth
      return Math.max(minUserColWidth, Math.floor(availableWidth / userCount))
    }

    const getMaxUsersPerPage = (totalUsers: number) => {
      if (totalUsers <= 0) return 1
      const printableWidth = getPrintableWidth()
      const fixedWidth = dayColWidth + llColWidth + timeColWidth
      const availableWidth = Math.max(0, printableWidth - fixedWidth)
      if (availableWidth <= 0) return 1
      const maxByTarget = Math.max(1, Math.floor(availableWidth / targetUserColWidth))
      return Math.min(totalUsers, maxByTarget)
    }

    const chunkUsers = (usersList: { user_id: string; user_name: string }[], chunkSize: number) => {
      if (chunkSize <= 0) return [usersList]
      const chunks: { user_id: string; user_name: string }[][] = []
      for (let i = 0; i < usersList.length; i += chunkSize) {
        chunks.push(usersList.slice(i, i + chunkSize))
      }
      return chunks
    }

    const createTable = (usersChunk: { user_id: string; user_name: string }[]) => {
      const userCount = usersChunk.length
      const userColWidth = getUserColumnWidth(userCount)
      const table = doc.createElement("table")
      if (userColWidth <= 55) {
        table.classList.add("table-narrow")
      }
      if (userCount >= 8) {
        table.classList.add("table-compact")
      }
      if (userCount >= 12) {
        table.classList.add("table-ultra-compact")
      }
      const colgroup = doc.createElement("colgroup")
      colgroup.innerHTML = `
        <col style="width: ${dayColWidth}px;" />
        <col style="width: ${timeColWidth}px;" />
        <col style="width: ${llColWidth}px;" />
        ${usersChunk.map(() => `<col style="width: ${userColWidth}px;" />`).join("")}
      `
      const thead = doc.createElement("thead")
      thead.innerHTML = `
        <tr>
          <th class="day-cell" rowspan="2">Day</th>
          <th class="time-cell" style="width: ${timeColWidth}px;">Time</th>
          <th style="width: ${llColWidth}px;">LL</th>
          ${usersChunk.map((u) => `<th class="user-header">${u.user_name.toUpperCase()}</th>`).join("")}
        </tr>
      `
      table.appendChild(colgroup)
      table.appendChild(thead)
      return table
    }

    const fitContentToWidth = (content: HTMLElement) => {
      const tables = Array.from(content.querySelectorAll("table")) as HTMLTableElement[]
      const maxTableWidth = tables.reduce((max, table) => Math.max(max, table.scrollWidth), 0)
      const availableWidth = Math.max(0, content.clientWidth - 2)
      if (maxTableWidth > 0 && availableWidth > 0) {
        const scale = Math.min(1, (availableWidth / maxTableWidth) * 0.98)
        if (scale < 1) {
          content.style.transform = `scale(${scale})`
          content.style.transformOrigin = "top left"
          content.style.width = `${Math.round((1 / scale) * 1000) / 10}%`
          return
        }
      }
      content.style.transform = ""
      content.style.transformOrigin = ""
      content.style.width = "100%"
    }

    const pages: HTMLDivElement[] = []
    const maxUsersPerPage = getMaxUsersPerPage(allUsers.length)
    const userChunks = chunkUsers(allUsers, maxUsersPerPage)
    if (userChunks.length === 0) userChunks.push([])

    userChunks.forEach((chunk, chunkIndex) => {
      const isFirstPage = pages.length === 0
      const { page, content } = createPage({ showTitle: isFirstPage, showMeta: isFirstPage })
      measure.appendChild(page)
      pages.push(page)

      if (legendEntries && legendEntries.length > 0 && chunkIndex === 0) {
        const legend = createLegendSection(legendEntries)
        if (legend) content.appendChild(legend)
        const legendSpacer = doc.createElement("div")
        legendSpacer.className = "print-legend-spacer"
        content.appendChild(legendSpacer)
      }

      const deptTitle = doc.createElement("div")
      deptTitle.className = "print-dept-title"
      let chunkLabel = ""
      if (allUsers.length > 0 && userChunks.length > 1) {
        const chunkStart = chunkIndex * maxUsersPerPage + 1
        const chunkEnd = Math.min(allUsers.length, chunkStart + chunk.length - 1)
        chunkLabel = ` (${chunkStart}-${chunkEnd} of ${allUsers.length})`
      }
      deptTitle.textContent = `${selectedDept}${chunkLabel}`
      content.appendChild(deptTitle)

      const table = createTable(chunk)
      content.appendChild(table)

      department.days.forEach((day, dayIndex) => {
        const tbody = doc.createElement("tbody")
        tbody.className = "day-group"
        tbody.innerHTML = renderDayGroupHtml(day, dayIndex, chunk)
        table.appendChild(tbody)
      })

      fitContentToWidth(content)
    })

    const renderPages = () => {
      root.innerHTML = ""
      pages.forEach((page, index) => {
        const countEl = page.querySelector(".print-page-count")
        if (countEl) {
          countEl.textContent = `Page ${index + 1} / ${pages.length}`
        }
        root.appendChild(page)
      })
    }

    setTimeout(() => {
      renderPages()
      requestAnimationFrame(() => {
        pages.forEach((page) => {
          const content = page.querySelector(".print-content") as HTMLElement | null
          if (content) {
            fitContentToWidth(content)
          }
        })
        printWindow.print()
      })
    }, 200)
  }, [activeSnapshot, user])

  if (!departmentId || departmentId === allDepartmentsValue) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Saved Weekly Snapshots</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-sm text-muted-foreground">
            Select a specific department to view saved weekly snapshots.
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <CardTitle>Saved Weekly Snapshots</CardTitle>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={() => void loadPlanVsFinal()} disabled={!selectedWeekStart || isLoadingPlanVsFinal}>
              {isLoadingPlanVsFinal ? "Loading..." : "Plan vs Final Report"}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-3">
            <div className="space-y-2">
              <Label>Week</Label>
              <Select value={selectedWeekStart} onValueChange={setSelectedWeekStart} disabled={isLoadingOverview}>
                <SelectTrigger>
                  <SelectValue placeholder="Select week" />
                </SelectTrigger>
                <SelectContent>
                  {overview.map((week) => (
                    <SelectItem key={week.week_start} value={week.week_start}>
                      {OVERVIEW_LABELS[week.label] ?? week.label} ({formatDate(week.week_start)} - {formatDate(week.week_end)})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Plan</Label>
              <Select value={selectedPlanType} onValueChange={(value) => setSelectedPlanType(value as SnapshotType)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="PLANNED">Planned Snapshot</SelectItem>
                  <SelectItem value="FINAL">Final Snapshot</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Version</Label>
              <Select
                value={selectedVersionId}
                onValueChange={(value) => void handleVersionChange(value)}
                disabled={activeVersions.length === 0}
              >
                <SelectTrigger>
                  <SelectValue placeholder={activeVersions.length === 0 ? "No snapshot saved" : "Select version"} />
                </SelectTrigger>
                <SelectContent>
                  {activeVersions.map((version) => (
                    <SelectItem key={version.id} value={version.id}>
                      {version.is_official ? "Official - " : ""}
                      {formatDateTime(version.created_at)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {isLoadingOverview ? <div className="text-sm text-muted-foreground">Loading overview...</div> : null}
          {isLoadingCompare ? <div className="text-sm text-muted-foreground">Loading comparison...</div> : null}
          {error ? <div className="text-sm text-destructive">{error}</div> : null}

          {activeSnapshot ? (
            <div className="text-sm text-muted-foreground">
              Week: {formatDate(activeSnapshot.payload.week_start)} - {formatDate(activeSnapshot.payload.week_end)}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">
              No {selectedPlanType === "PLANNED" ? "planned" : "final"} snapshot saved for the selected week.
            </div>
          )}
        </CardContent>
      </Card>

      {planVsFinalError ? <div className="text-sm text-destructive">{planVsFinalError}</div> : null}

      {planVsFinal ? (
        <Card>
          <CardHeader className="flex flex-col gap-2 pb-2 md:flex-row md:items-center md:justify-between">
            <CardTitle className="text-base">Plan vs Final Report</CardTitle>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                onClick={() => void exportPlanVsFinalExcel()}
                disabled={!departmentId || departmentId === allDepartmentsValue || !selectedWeekStart || isExportingPlanVsFinal}
              >
                {isExportingPlanVsFinal ? "Exporting..." : "Export Excel"}
              </Button>
              <Button variant="outline" onClick={() => void handlePrintPlanVsFinal()}>
                <Printer className="mr-2 h-4 w-4" />
                Print
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {(() => {
              const sourceSnapshot = compare?.planned_official ?? compare?.final_official ?? activeSnapshot
              const userMap = new Map<string, string>()
              sourceSnapshot?.payload?.department?.days?.forEach((day) => {
                day.users?.forEach((u) => {
                  if (!userMap.has(u.user_id)) userMap.set(u.user_id, u.user_name)
                })
              })
              const columns = Array.from(userMap.entries()).map(([user_id, user_name]) => ({
                assignee_id: user_id,
                assignee_name: user_name,
              }))
              return (
                <WeeklyPlanPerformanceView
                  data={planVsFinal}
                  assigneeColumns={columns}
                  printRootId={PLAN_VS_FINAL_PRINT_ROOT_ID}
                />
              )
            })()}
          </CardContent>
        </Card>
      ) : null}

      {activeSnapshot ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-end gap-2 print:hidden">
            <Button variant="outline" onClick={() => void exportSnapshotExcel()} disabled={!activeSnapshot || isExporting}>
              {isExporting ? "Exporting..." : "Export Excel"}
            </Button>
            <Button variant="outline" onClick={() => void handlePrintSnapshot()} disabled={!activeSnapshot}>
              <Printer className="mr-2 h-4 w-4" />
              Print
            </Button>
          </div>
          <SnapshotLegend snapshot={activeSnapshot} />
          <SnapshotDepartmentTable snapshot={activeSnapshot} />
        </div>
      ) : null}
    </div>
  )
}
