"use client"

import * as React from "react"

import Link from "next/link"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { formatDateTimeDMY } from "@/lib/dates"

export type WeeklyPlanPerformanceTaskAssignee = {
  assignee_id: string | null
  assignee_name: string
}

export type WeeklyPlanPerformanceTaskOccurrence = {
  day: string | null
  time_slot: string | null
  assignee_id: string | null
  assignee_name: string | null
}

export type WeeklyPlanPerformanceTask = {
  match_key: string
  task_id: string | null
  fallback_key: string | null
  title: string
  project_id: string | null
  project_title: string | null
  source_type: string
  status: string | null
  daily_status: string | null
  completed_at: string | null
  is_completed: boolean
  finish_period: string | null
  priority: string | null
  tags: string[]
  assignees: WeeklyPlanPerformanceTaskAssignee[]
  occurrences: WeeklyPlanPerformanceTaskOccurrence[]
}

export type WeeklyPlanPerformanceSummary = {
  total_planned: number
  completed: number
  in_progress: number
  pending: number
  late: number
  additional: number
  removed_or_canceled: number
  not_completed: number
  added_during_week: number
}

export type WeeklyPlanPerformanceAssigneeGroup = {
  assignee_id: string | null
  assignee_name: string
  completed: WeeklyPlanPerformanceTask[]
  in_progress: WeeklyPlanPerformanceTask[]
  pending: WeeklyPlanPerformanceTask[]
  late: WeeklyPlanPerformanceTask[]
  additional: WeeklyPlanPerformanceTask[]
  removed_or_canceled: WeeklyPlanPerformanceTask[]
  not_completed: WeeklyPlanPerformanceTask[]
  added_during_week: WeeklyPlanPerformanceTask[]
}

export type WeeklyPlanPerformanceResponse = {
  week_start: string
  week_end: string
  department_id: string
  department_name: string | null
  snapshot_id: string | null
  snapshot_created_at: string | null
  snapshot_created_by: string | null
  final_snapshot_id?: string | null
  final_snapshot_created_at?: string | null
  final_snapshot_created_by?: string | null
  message: string | null
  summary: WeeklyPlanPerformanceSummary
  completed: WeeklyPlanPerformanceTask[]
  in_progress: WeeklyPlanPerformanceTask[]
  pending: WeeklyPlanPerformanceTask[]
  late: WeeklyPlanPerformanceTask[]
  additional: WeeklyPlanPerformanceTask[]
  removed_or_canceled: WeeklyPlanPerformanceTask[]
  not_completed: WeeklyPlanPerformanceTask[]
  added_during_week: WeeklyPlanPerformanceTask[]
  by_assignee: WeeklyPlanPerformanceAssigneeGroup[]
}

export type WeeklyPlanPerformanceAssigneeColumn = {
  assignee_id: string | null
  assignee_name: string
}

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

const getStatusCardClasses = (status?: string | null) => {
  const normalized = (status || "TODO").toUpperCase()
  if (normalized === "IN_PROGRESS") return "border-[#000000] bg-[#FFFF00] text-[#000000]"
  if (normalized === "PAUSED") return "border-[#64748B] bg-[#CBD5E1] text-[#1E293B]"
  if (normalized === "WAITING_CONFIRMATION") return "border-[#C2410C] bg-[#FFEDD5] text-[#9A3412]"
  if (normalized === "DONE") return "border-[#000000] bg-[#C4FDC4] text-[#000000]"
  if (normalized === "TODO") return "border-[#000000] bg-[#FFC4ED] text-[#000000]"
  return "border-[#000000] bg-[#f1f5f9] text-[#000000]"
}

const formatPlannerStatusLabel = (value?: string | null) => {
  const normalized = (value || "TODO")
    .trim()
    .toUpperCase()
    .replace(/\s+/g, "_")
  if (normalized === "IN_PROGRESS") return "In Progress"
  if (normalized === "PAUSED") return "Stopped"
  if (normalized === "WAITING_CLIENT") return "WFE"
  if (normalized === "WAITING_CONFIRMATION") return "Waiting Confirmation"
  if (normalized === "DONE") return "Done"
  return "To Do"
}

const renderTaskList = (tasks: WeeklyPlanPerformanceTask[]) => {
  if (!tasks.length) {
    return <div className="text-xs text-muted-foreground">-</div>
  }
  return (
    <div className="space-y-2">
      {tasks.map((task) => {
        const statusValue = task.daily_status || task.status || "TODO"
        const assigneeLabel = task.assignees.map((assignee) => assignee.assignee_name).join(", ")
        const occurrencePreview = (task.occurrences || [])
          .slice(0, 2)
          .map((occurrence) => {
            const dateLabel = occurrence.day ? formatDate(occurrence.day) : "-"
            return `${dateLabel} ${occurrence.time_slot || ""}`.trim()
          })
          .join(", ")
        return (
          <div key={task.match_key} className="rounded border p-2">
            <div className="flex items-start justify-between gap-2">
              {task.task_id ? (
                <Link href={`/tasks/${task.task_id}`} className="font-medium hover:underline">
                  {task.title}
                </Link>
              ) : (
                <div className="font-medium">{task.title}</div>
              )}
              <span
                className={[
                  "inline-flex items-center rounded px-2 py-0.5 text-[10px] font-semibold",
                  getStatusCardClasses(statusValue),
                ].join(" ")}
              >
                {formatPlannerStatusLabel(statusValue)}
              </span>
            </div>
            <div className="mt-1 text-xs text-muted-foreground">
              {task.project_title ? `Project: ${task.project_title}` : `Type: ${task.source_type}`}
            </div>
            <div className="text-xs text-muted-foreground">Assignee: {assigneeLabel || "Unassigned"}</div>
            <div className="text-xs text-muted-foreground">Slots: {occurrencePreview || "-"}</div>
            {task.tags.length > 0 ? (
              <div className="mt-1 flex flex-wrap gap-1">
                {task.tags.map((tag) => (
                  <span key={`${task.match_key}-${tag}`} className="rounded border px-1.5 py-0.5 text-[10px]">
                    {tag}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

export function WeeklyPlanPerformanceView({
  data,
  assigneeColumns,
  printRootId,
}: {
  data: WeeklyPlanPerformanceResponse
  assigneeColumns?: WeeklyPlanPerformanceAssigneeColumn[]
  printRootId?: string
}) {
  const completed = data.completed ?? []
  const inProgress = data.in_progress ?? []
  const pending = data.pending ?? []
  const late = data.late ?? []
  const additional = data.additional ?? data.added_during_week ?? []
  const removedOrCanceled = data.removed_or_canceled ?? []

  const assigneeGroups = React.useMemo(() => {
    const groups = (data.by_assignee ?? []).filter((g) => (g.assignee_name || "").trim().length > 0)
    if (groups.length > 0) {
      return [...groups].sort((a, b) => (a.assignee_name || "").localeCompare(b.assignee_name || ""))
    }

    const columns = (assigneeColumns ?? []).filter((c) => (c.assignee_name || "").trim().length > 0)
    if (columns.length === 0) return []

    const blankGroups: WeeklyPlanPerformanceAssigneeGroup[] = columns.map((col) => ({
      assignee_id: col.assignee_id,
      assignee_name: col.assignee_name,
      completed: [],
      in_progress: [],
      pending: [],
      late: [],
      additional: [],
      removed_or_canceled: [],
      not_completed: [],
      added_during_week: [],
    }))

    const groupIndex = new Map(
      blankGroups.map((g) => [g.assignee_id ?? `name:${g.assignee_name.toLowerCase()}`, g] as const)
    )

    const add = (
      bucket: keyof Pick<
        WeeklyPlanPerformanceAssigneeGroup,
        "completed" | "in_progress" | "pending" | "late" | "additional" | "removed_or_canceled"
      >,
      tasks: WeeklyPlanPerformanceTask[]
    ) => {
      for (const task of tasks) {
        const assignees =
          task.assignees && task.assignees.length > 0
            ? task.assignees
            : [{ assignee_id: null, assignee_name: "Unassigned" }]
        for (const assignee of assignees) {
          const key = assignee.assignee_id ?? `name:${(assignee.assignee_name || "unassigned").toLowerCase()}`
          const group = groupIndex.get(key)
          if (!group) continue
          group[bucket].push(task)
        }
      }
    }

    add("completed", completed)
    add("in_progress", inProgress)
    add("pending", pending)
    add("late", late)
    add("additional", additional)
    add("removed_or_canceled", removedOrCanceled)

    for (const g of blankGroups) {
      g.not_completed = [...g.in_progress, ...g.pending, ...g.late]
      g.added_during_week = [...g.additional]
    }

    return blankGroups
  }, [additional, assigneeColumns, completed, data.by_assignee, inProgress, late, pending, removedOrCanceled])

  const categoryRows = React.useMemo(
    () =>
      [
        { key: "completed", label: "Completed", pick: (g: WeeklyPlanPerformanceAssigneeGroup) => g.completed ?? [] },
        { key: "in_progress", label: "In Progress", pick: (g: WeeklyPlanPerformanceAssigneeGroup) => g.in_progress ?? [] },
        { key: "pending", label: "Pending", pick: (g: WeeklyPlanPerformanceAssigneeGroup) => g.pending ?? [] },
        { key: "late", label: "Late", pick: (g: WeeklyPlanPerformanceAssigneeGroup) => g.late ?? [] },
        { key: "additional", label: "Additional", pick: (g: WeeklyPlanPerformanceAssigneeGroup) => g.additional ?? g.added_during_week ?? [] },
        { key: "removed_or_canceled", label: "Removed/Canceled", pick: (g: WeeklyPlanPerformanceAssigneeGroup) => g.removed_or_canceled ?? [] },
      ] as const,
    []
  )

  const renderTaskCell = (tasks: WeeklyPlanPerformanceTask[]) => {
    if (!tasks.length) return <div className="text-xs text-muted-foreground">-</div>
    return (
      <div className="space-y-1">
        <div className="text-xs font-semibold">{tasks.length}</div>
        <div className="space-y-1 max-h-64 overflow-y-auto pr-2">
          {tasks.map((task) => (
            <div key={task.match_key} className="rounded border px-2 py-1">
              {task.task_id ? (
                <Link href={`/tasks/${task.task_id}`} className="text-xs font-medium hover:underline">
                  {task.title}
                </Link>
              ) : (
                <div className="text-xs font-medium">{task.title}</div>
              )}
              <div className="text-[11px] text-muted-foreground">
                {task.project_title ? task.project_title : task.source_type}
              </div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div id={printRootId} className="space-y-4">
      <div className="text-sm text-muted-foreground">
        Week: {formatDate(data.week_start)} - {formatDate(data.week_end)}
      </div>
      {data.snapshot_created_at ? (
        <div className="text-xs text-muted-foreground">Baseline plan saved: {formatDateTime(data.snapshot_created_at)}</div>
      ) : null}
      {data.final_snapshot_created_at ? (
        <div className="text-xs text-muted-foreground">Final snapshot saved: {formatDateTime(data.final_snapshot_created_at)}</div>
      ) : null}
      {data.message ? (
        <div className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">{data.message}</div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Total Planned</CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold">{data.summary.total_planned}</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Completed</CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold">{data.summary.completed}</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">In Progress</CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold">{data.summary.in_progress ?? 0}</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Pending</CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold">{data.summary.pending ?? 0}</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Late</CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold">{data.summary.late ?? 0}</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Additional</CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold">{data.summary.additional ?? data.summary.added_during_week ?? 0}</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Removed/Canceled</CardTitle>
          </CardHeader>
          <CardContent className="text-xl font-semibold">{data.summary.removed_or_canceled ?? 0}</CardContent>
        </Card>
      </div>

      <Card>
        <CardContent>
          {assigneeGroups.length === 0 ? (
            <div className="text-sm text-muted-foreground">No assignees found for this comparison.</div>
          ) : (
            <div className="overflow-x-auto border-2 border-black">
              <Table className="table-fixed w-full border-collapse">
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-12 min-w-12 border border-black align-bottom font-bold">Nr</TableHead>
                    <TableHead className="w-44 min-w-44 border border-black align-bottom font-bold">STATUS</TableHead>
                    {assigneeGroups.map((group) => (
                      <TableHead
                        key={group.assignee_id || `name:${group.assignee_name.toLowerCase()}`}
                        className="min-w-72 border border-black align-bottom font-bold"
                      >
                        {(group.assignee_name || "").toUpperCase()}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {categoryRows.map((row, idx) => (
                    <TableRow key={row.key}>
                      <TableCell className="border border-black align-bottom font-semibold">{idx + 1}</TableCell>
                      <TableCell className="border border-black align-bottom font-semibold">{row.label}</TableCell>
                      {assigneeGroups.map((group) => (
                        <TableCell
                          key={`${row.key}:${group.assignee_id || `name:${group.assignee_name.toLowerCase()}`}`}
                          className="border border-black align-bottom"
                        >
                          {renderTaskCell(row.pick(group))}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}

          {/* Keep overall fallback lists (useful when no by_assignee is returned) */}
          {assigneeGroups.length === 0 ? (
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <div className="text-sm font-semibold">Completed ({completed.length})</div>
                {renderTaskList(completed)}
              </div>
              <div className="space-y-2">
                <div className="text-sm font-semibold">In Progress ({inProgress.length})</div>
                {renderTaskList(inProgress)}
              </div>
              <div className="space-y-2">
                <div className="text-sm font-semibold">Pending ({pending.length})</div>
                {renderTaskList(pending)}
              </div>
              <div className="space-y-2">
                <div className="text-sm font-semibold">Late ({late.length})</div>
                {renderTaskList(late)}
              </div>
              <div className="space-y-2">
                <div className="text-sm font-semibold">Additional ({additional.length})</div>
                {renderTaskList(additional)}
              </div>
              <div className="space-y-2">
                <div className="text-sm font-semibold">Removed/Canceled ({removedOrCanceled.length})</div>
                {renderTaskList(removedOrCanceled)}
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}
