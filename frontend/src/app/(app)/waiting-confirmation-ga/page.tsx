"use client"

import * as React from "react"
import { Check, Pencil, RefreshCw } from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { TaskOneHMarkerEditor } from "@/components/task-one-h-marker-editor"
import { TaskMarkerComment } from "@/components/task-marker-comment"
import { useAuth } from "@/lib/auth"
import { formatDepartmentName } from "@/lib/department-name"
import type { Department, Project, Task, TaskAssignee } from "@/lib/types"
import { useWaitingConfirmationGa } from "@/components/waiting-confirmation-ga-context"

const TASK_STATUS_STYLES: Record<string, string> = {
  WAITING_CONFIRMATION: "bg-teal-100 text-teal-900 border-teal-300",
  IN_PROGRESS: "bg-amber-50 text-amber-700 border-amber-200",
  PAUSED: "bg-slate-200 text-slate-800 border-slate-400",
  TODO: "bg-slate-100 text-slate-700 border-slate-200",
  DONE: "bg-emerald-50 text-emerald-700 border-emerald-200",
}

function formatShortDate(value?: string | null) {
  if (!value) return "-"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "-"
  const day = date.getDate().toString().padStart(2, "0")
  const month = (date.getMonth() + 1).toString().padStart(2, "0")
  const year = date.getFullYear()
  return `${day}.${month}.${year}`
}

function getInitials(label: string) {
  const trimmed = label.trim()
  if (!trimmed) return "?"
  const parts = trimmed.split(/\s+/)
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase()
}

function assigneeLabel(assignee?: TaskAssignee | null) {
  if (!assignee) return "Unknown"
  return assignee.full_name || assignee.username || assignee.email || "Unknown"
}

function abbreviateDepartmentName(name?: string | null) {
  if (!name) return ""
  const lowerName = name.toLowerCase()
  if (lowerName.includes("development")) return "DEV"
  if (lowerName.includes("graphic") && lowerName.includes("design")) return "GDS"
  if (lowerName.includes("product") && lowerName.includes("content")) return "PCM"
  return name.slice(0, 3).toUpperCase()
}

export default function WaitingConfirmationGaPage() {
  const { apiFetch, user } = useAuth()
  const { tasks, loading, error, refresh, applyTaskResult } = useWaitingConfirmationGa()
  const [projects, setProjects] = React.useState<Project[]>([])
  const [departments, setDepartments] = React.useState<Department[]>([])
  const [metaLoading, setMetaLoading] = React.useState(true)
  const [metaError, setMetaError] = React.useState<string | null>(null)
  const [refreshing, setRefreshing] = React.useState(false)
  const [updatingTaskId, setUpdatingTaskId] = React.useState<string | null>(null)
  const [editOpen, setEditOpen] = React.useState(false)
  const [editingTaskId, setEditingTaskId] = React.useState<string | null>(null)
  const [editTitle, setEditTitle] = React.useState("")
  const [editDescription, setEditDescription] = React.useState("")
  const [savingEdit, setSavingEdit] = React.useState(false)
  const canManageWaitingConfirmation = Boolean(user?.id)

  const loadMetadata = React.useCallback(async () => {
    setMetaLoading(true)
    setMetaError(null)
    try {
      const [projectsRes, departmentsRes] = await Promise.all([
        apiFetch("/projects"),
        apiFetch("/departments"),
      ])
      if (!projectsRes.ok || !departmentsRes.ok) {
        throw new Error("metadata_failed")
      }
      setProjects((await projectsRes.json()) as Project[])
      setDepartments((await departmentsRes.json()) as Department[])
    } catch {
      setMetaError("Could not load project or department data.")
    } finally {
      setMetaLoading(false)
    }
  }, [apiFetch])

  React.useEffect(() => {
    void loadMetadata()
  }, [loadMetadata])

  const handleRefresh = React.useCallback(async () => {
    setRefreshing(true)
    await Promise.all([refresh(), loadMetadata()])
    setRefreshing(false)
  }, [loadMetadata, refresh])

  const projectMap = React.useMemo(() => new Map(projects.map((project) => [project.id, project])), [projects])
  const departmentMap = React.useMemo(
    () => new Map(departments.map((department) => [department.id, department])),
    [departments]
  )

  const updateTask = React.useCallback(
    async (taskId: string, payload: Record<string, unknown>, successMessage: string) => {
      if (!canManageWaitingConfirmation) {
        toast.error("Only the selected confirmation recipient can update these tasks.")
        return false
      }
      setUpdatingTaskId(taskId)
      try {
        const res = await apiFetch(`/tasks/${taskId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        })
        if (!res.ok) {
          let detail = "Failed to update task."
          try {
            const data = (await res.json()) as { detail?: string }
            if (typeof data.detail === "string" && data.detail.trim()) detail = data.detail
          } catch {
            // ignore
          }
          toast.error(detail)
          return false
        }
        const updatedTask = (await res.json()) as Task
        applyTaskResult(updatedTask)
        toast.success(successMessage)
        return true
      } catch {
        toast.error("Failed to update task.")
        return false
      } finally {
        setUpdatingTaskId(null)
      }
    },
    [apiFetch, applyTaskResult, canManageWaitingConfirmation]
  )

  const startEditTask = React.useCallback((task: Task) => {
    if (!canManageWaitingConfirmation) {
      toast.error("Only the selected confirmation recipient can edit these tasks.")
      return
    }
    setEditingTaskId(task.id)
    setEditTitle(task.title || "")
    setEditDescription(task.description || "")
    setEditOpen(true)
  }, [canManageWaitingConfirmation])

  const saveEditTask = React.useCallback(async () => {
    if (!editingTaskId) return
    setSavingEdit(true)
    try {
      const ok = await updateTask(
        editingTaskId,
        {
          title: editTitle.trim(),
          description: editDescription.trim() || null,
        },
        "Task updated."
      )
      if (ok) {
        setEditOpen(false)
        setEditingTaskId(null)
      }
    } finally {
      setSavingEdit(false)
    }
  }, [editDescription, editTitle, editingTaskId, updateTask])

  const combinedError = error || metaError
  const isLoading = loading || metaLoading

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <h1 className="text-xl font-semibold tracking-tight">WFC INT</h1>
          <p className="text-sm text-muted-foreground">
            Tasks waiting for your confirmation.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void handleRefresh()} disabled={isLoading || refreshing}>
          <RefreshCw className={`mr-2 h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {combinedError ? (
        <div className="rounded-md border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{combinedError}</div>
      ) : null}

      {isLoading ? (
        <div className="rounded-md border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
          Loading WFC INT tasks...
        </div>
      ) : null}

      {!isLoading && !combinedError && tasks.length === 0 ? (
        <div className="rounded-md border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
          No WFC INT tasks.
        </div>
      ) : null}

      {!isLoading && !combinedError && tasks.length > 0 ? (
        <Table
          containerClassName="rounded-lg border border-slate-200 bg-white"
          className="min-w-[1180px] text-[11px]"
        >
          <TableHeader>
            <TableRow className="bg-slate-50 [&>th]:border-r [&>th]:border-slate-300 [&>th:last-child]:border-r-0">
              {["#", "TITLE", "ASSIGNEES", "PROJECT", "DEPARTMENT", "DUE", "DESCRIPTION", "STATUS", "ACTIONS"].map((label) => (
                <TableHead key={label} className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                  {label}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {tasks.map((task, index) => {
              const project = task.project_id ? projectMap.get(task.project_id) : undefined
              const department = task.department_id
                ? departmentMap.get(task.department_id)
                : project?.department_id
                  ? departmentMap.get(project.department_id)
                  : undefined
              const assignees = task.assignees || []
              const status = task.status || "WAITING_CONFIRMATION"
              const isUpdating = updatingTaskId === task.id

              return (
                <TableRow key={task.id} className="h-12 [&>td]:border-r [&>td]:border-slate-300 [&>td:last-child]:border-r-0">
                  <TableCell className="font-semibold text-slate-700">{index + 1}</TableCell>
                  <TableCell className="whitespace-normal font-medium text-slate-900">
                    <div className="flex flex-col gap-2">
                      <div className="sm:hidden flex flex-wrap items-center gap-1.5">
                        {department?.name ? (
                          <Badge
                            variant="outline"
                            className="h-5 rounded-full px-1.5 text-[9px] font-semibold leading-none bg-amber-50 text-amber-700 border-amber-200"
                          >
                            {abbreviateDepartmentName(department.name)}
                          </Badge>
                        ) : null}
                        {assignees.length > 0 ? (
                          assignees.map((assignee) => {
                            const label = assigneeLabel(assignee)
                            return (
                              <div
                                key={`mobile-top-${task.id}-${assignee.id}`}
                                className="inline-flex h-5 min-w-5 items-center justify-center rounded-full border border-slate-200 bg-slate-100 px-1 text-[9px] font-semibold text-slate-700"
                                title={label}
                              >
                                {getInitials(label)}
                              </div>
                            )
                          })
                        ) : null}
                      </div>
                      <span className="flex items-start gap-1.5">
                        <TaskOneHMarkerEditor taskId={task.id} marker={task.one_h_marker} markerByGa={task.one_h_marker_by_ga} markerComment={task.one_h_marker_comment} onSaved={fields => applyTaskResult({ ...task, ...fields })} />
                        <span className="min-w-0"><TaskMarkerComment comment={task.one_h_marker_comment} taskId={task.id} />{task.title || "-"}</span>
                      </span>
                      {canManageWaitingConfirmation ? (
                        <div className="flex flex-nowrap items-center gap-1.5 sm:hidden">
                          <Button
                            variant="outline"
                            size="icon"
                            className="h-7 w-7 border-emerald-200 text-emerald-700 hover:bg-emerald-50"
                            disabled={isUpdating}
                            aria-label="Mark as done"
                            title="Mark as done"
                            onClick={() => void updateTask(task.id, { status: "DONE" }, "Task marked as done.")}
                          >
                            <Check className="h-4 w-4" />
                          </Button>
                          <Select
                            value=""
                            onValueChange={(value) => {
                              void updateTask(task.id, { status: value }, `Task moved to ${value.replace("_", " ").toLowerCase()}.`)
                            }}
                            disabled={isUpdating}
                          >
                            <SelectTrigger size="sm" className="h-7 w-[104px] px-2 text-[11px]">
                              <SelectValue placeholder="Change status" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="TODO">To do</SelectItem>
                              <SelectItem value="IN_PROGRESS">In progress</SelectItem>
                            </SelectContent>
                          </Select>
                          <Button
                            variant="outline"
                            size="icon"
                            className="h-7 w-7 border-slate-200 text-slate-500 hover:border-blue-200 hover:text-blue-600"
                            title="Edit title and description"
                            aria-label={`Edit ${task.title || "task"}`}
                            disabled={isUpdating}
                            onClick={() => startEditTask(task)}
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell className="whitespace-normal">
                    <div className="flex flex-wrap gap-1.5">
                      {assignees.length > 0 ? (
                        assignees.map((assignee) => {
                          const label = assigneeLabel(assignee)
                          return (
                            <div
                              key={`${task.id}-${assignee.id}`}
                              className="inline-flex h-7 min-w-7 items-center justify-center rounded-full border border-slate-200 bg-slate-50 px-2 text-[11px] font-semibold text-slate-700"
                              title={label}
                            >
                              {getInitials(label)}
                            </div>
                          )
                        })
                      ) : (
                        <span className="text-xs text-slate-500">No assignees</span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="whitespace-normal text-slate-700">
                    {project?.display_title || project?.title || project?.name || "-"}
                  </TableCell>
                  <TableCell className="whitespace-normal text-slate-700">
                    {formatDepartmentName(department?.name) || "-"}
                  </TableCell>
                  <TableCell className="text-slate-700">
                    {formatShortDate(task.due_date || task.start_date || task.created_at)}
                  </TableCell>
                  <TableCell className="max-w-[320px] whitespace-normal text-slate-700">
                    {task.description || "-"}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className={TASK_STATUS_STYLES[status] || TASK_STATUS_STYLES.TODO}>
                      {status === "WAITING_CONFIRMATION" ? "WFC INT" : status}
                    </Badge>
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    {canManageWaitingConfirmation ? (
                      <div className="flex flex-nowrap items-center gap-1.5">
                        <Button
                          variant="outline"
                          size="icon"
                          className="h-7 w-7 border-emerald-200 text-emerald-700 hover:bg-emerald-50"
                          disabled={isUpdating}
                          aria-label="Mark as done"
                          title="Mark as done"
                          onClick={() => void updateTask(task.id, { status: "DONE" }, "Task marked as done.")}
                        >
                          <Check className="h-4 w-4" />
                        </Button>
                        <Select
                          value=""
                          onValueChange={(value) => {
                            void updateTask(task.id, { status: value }, `Task moved to ${value.replace("_", " ").toLowerCase()}.`)
                          }}
                          disabled={isUpdating}
                        >
                          <SelectTrigger size="sm" className="h-7 w-[104px] px-2 text-[11px]">
                            <SelectValue placeholder="Change status" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="TODO">To do</SelectItem>
                            <SelectItem value="IN_PROGRESS">In progress</SelectItem>
                          </SelectContent>
                        </Select>
                        <Button
                          variant="outline"
                          size="icon"
                          className="h-7 w-7 border-slate-200 text-slate-500 hover:border-blue-200 hover:text-blue-600"
                          title="Edit title and description"
                          aria-label={`Edit ${task.title || "task"}`}
                          disabled={isUpdating}
                          onClick={() => startEditTask(task)}
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    ) : (
                      <span className="text-xs text-slate-400">-</span>
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      ) : null}

      <Dialog
        open={editOpen}
        onOpenChange={(open) => {
          setEditOpen(open)
          if (!open) {
            setEditingTaskId(null)
          }
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Edit Task</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="waiting-ga-title">Title</Label>
              <Input
                id="waiting-ga-title"
                value={editTitle}
                onChange={(event) => setEditTitle(event.target.value)}
                placeholder="Task title"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="waiting-ga-description">Description</Label>
              <Textarea
                id="waiting-ga-description"
                value={editDescription}
                onChange={(event) => setEditDescription(event.target.value)}
                placeholder="Task description"
                rows={6}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditOpen(false)}>
              Cancel
            </Button>
            <Button disabled={savingEdit || !editingTaskId} onClick={() => void saveEditTask()}>
              {savingEdit ? "Saving..." : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
