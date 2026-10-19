"use client"

import * as React from "react"
import { useParams, useRouter, useSearchParams } from "next/navigation"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useAuth } from "@/lib/auth"
import { TaskReviewsPanel } from "@/components/task-reviews-panel"
import { TaskOneHMarker } from "@/components/task-one-h-marker"
import { TaskMarkerComment } from "@/components/task-marker-comment"
import { PromptLinkButton } from "@/components/knowledge/prompt-link"
import { clearDepartmentBootstrapCacheByPrefix } from "@/lib/department-bootstrap-cache"
import { formatDateDMY, normalizeDueDateInput, toDateInputValue } from "@/lib/dates"
import { loadGaNoteTaskAssigneeIds, replaceGaNoteTaskAssignees } from "@/lib/ga-note-task-membership"
import { buildMarkedAppendOnlyText, getPlainMarkedText, renderMarkedNoteContent } from "@/lib/note-markup"
import { getConfirmerCandidates, isWaitingConfirmation, validateWaitingConfirmation } from "@/lib/task-confirmation"
import type { GaNoteAttachment, Task, TaskFinishPeriod, User, UserLookup } from "@/lib/types"

const TASK_STATUS_OPTIONS = [
  { value: "TODO", label: "To do" },
  { value: "IN_PROGRESS", label: "In progress" },
  { value: "WAITING_CLIENT", label: "WFE" },
  { value: "WAITING_CONFIRMATION", label: "Waiting Confirmation" },
  { value: "DONE", label: "Done" },
] as const

const TASK_PRIORITY_LABELS: Record<string, string> = {
  NORMAL: "Normal",
  HIGH: "High",
}

const FINISH_PERIOD_NONE_VALUE = "__none__"
const formatFileSize = (bytes?: number) => {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) return "-"
  const kb = bytes / 1024
  if (kb < 1024) return `${kb.toFixed(1)} KB`
  return `${(kb / 1024).toFixed(1)} MB`
}

const FAST_TASK_TYPES = [
  { value: "N", label: "N (Normal)" },
  { value: "BLL", label: "BLL (BLLOK)" },
  { value: "R1", label: "R1" },
  { value: "1H", label: "1H (1 Hour Report)" },
  { value: "P:", label: "P: (Personal)" },
] as const

const PROJECT_TASK_TYPES = [
  { value: "NORMAL", label: "Normal" },
  { value: "HIGH", label: "High" },
  { value: "1H", label: "1H (1 Hour Report)" },
  { value: "R1", label: "R1" },
  { value: "PERSONAL", label: "P: (Personal)" },
  { value: "BLLOK", label: "BLLOK" },
] as const

type FastTaskType = typeof FAST_TASK_TYPES[number]["value"]
type ProjectTaskType = typeof PROJECT_TASK_TYPES[number]["value"]

function getCurrentFastTaskType(task: Task | null): FastTaskType {
  if (!task) return "N"
  if (task.is_bllok) return "BLL"
  if (task.is_r1) return "R1"
  if (task.is_1h_report) return "1H"
  if (task.is_personal) return "P:"
  return "N"
}

function isFastTask(task: Task | null): boolean {
  if (!task) return false
  // Fast tasks: no project, no dependency, no system template
  return (
    task.project_id === null &&
    task.dependency_task_id === null &&
    task.system_template_origin_id === null
  )
}

function isProjectTask(task: Task | null): boolean {
  if (!task) return false
  return task.project_id !== null && task.system_template_origin_id === null
}

function getCurrentProjectTaskType(task: Task | null): ProjectTaskType {
  if (!task) return "NORMAL"
  if (task.is_1h_report) return "1H"
  if (task.is_r1) return "R1"
  if (task.is_personal) return "PERSONAL"
  if (task.is_bllok) return "BLLOK"
  if (task.priority === "HIGH") return "HIGH"
  return "NORMAL"
}

function formatDate(value?: string | null) {
  return formatDateDMY(value)
}

function statusLabel(value?: string | null) {
  if (!value) return "-"
  const hit = TASK_STATUS_OPTIONS.find((option) => option.value === value)
  return hit?.label ?? value
}

import { BoldOnlyEditor } from "@/components/bold-only-editor"

export default function TaskDetailsPage() {
  const UNASSIGNED_VALUE = "__unassigned__"
  const params = useParams<{ id: string }>()
  const taskId = String(params.id)
  const searchParams = useSearchParams()
  const router = useRouter()
  const returnTo = searchParams.get("returnTo")
  const { apiFetch, user } = useAuth()

  const [task, setTask] = React.useState<Task | null>(null)
  const [loadError, setLoadError] = React.useState<string | null>(null)
  const [users, setUsers] = React.useState<UserLookup[]>([])

  const load = React.useCallback(async () => {
    const taskRes = await apiFetch(`/tasks/${taskId}`)
    if (!taskRes.ok) {
      let detail = `Failed to load task (${taskRes.status})`
      try {
        const data = (await taskRes.json()) as { detail?: string }
        if (data?.detail) detail = data.detail
      } catch {
        // ignore parse errors
      }
      setLoadError(detail)
      setTask(null)
      return
    }
    setLoadError(null)
    const t = (await taskRes.json()) as Task
    setTask(t)

    const uRes = await apiFetch("/users/lookup")
    if (uRes.ok) setUsers((await uRes.json()) as UserLookup[])
  }, [apiFetch, taskId])

  React.useEffect(() => {
    void load()
  }, [load])

  React.useEffect(() => {
    const changed = () => { void load() }
    window.addEventListener("primex:tasks-changed", changed)
    return () => window.removeEventListener("primex:tasks-changed", changed)
  }, [load])

  const [saving, setSaving] = React.useState(false)
  const [title, setTitle] = React.useState("")
  const [description, setDescription] = React.useState("")
  const [statusValue, setStatusValue] = React.useState<Task["status"] | "">("")
  const [startDate, setStartDate] = React.useState("")
  const [dueDate, setDueDate] = React.useState("")
  const [deadlineImportant, setDeadlineImportant] = React.useState(false)
  const [assignedTo, setAssignedTo] = React.useState(UNASSIGNED_VALUE)
  const [confirmationAssigneeId, setConfirmationAssigneeId] = React.useState("")
  const [assignees, setAssignees] = React.useState<string[]>([])
  const [initialAssignees, setInitialAssignees] = React.useState<string[]>([])
  const [selectAssigneesOpen, setSelectAssigneesOpen] = React.useState(false)
  const [reminder, setReminder] = React.useState(false)
  const [fastTaskType, setFastTaskType] = React.useState<FastTaskType>("N")
  const [projectTaskType, setProjectTaskType] = React.useState<ProjectTaskType>("NORMAL")
  const [finishPeriod, setFinishPeriod] = React.useState<TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE>(
    FINISH_PERIOD_NONE_VALUE
  )
  const [gaNoteAttachments, setGaNoteAttachments] = React.useState<GaNoteAttachment[]>([])
  const [loadingAttachments, setLoadingAttachments] = React.useState(false)
  const [previewUrl, setPreviewUrl] = React.useState<string | null>(null)
  const [previewTitle, setPreviewTitle] = React.useState<string | null>(null)

  const currentTaskAssigneeIds = React.useMemo(() => {
    if (!task) return [] as string[]
    if (task.assignees && task.assignees.length > 0) {
      return task.assignees.map((a) => a.id).filter((id): id is string => Boolean(id))
    }
    if (task.assigned_to) return [task.assigned_to]
    return []
  }, [task])

  const sameIdSet = (a: string[], b: string[]) => {
    if (a.length !== b.length) return false
    const aSet = new Set(a)
    if (aSet.size !== b.length) return false
    for (const id of b) {
      if (!aSet.has(id)) return false
    }
    return true
  }

  React.useEffect(() => {
    if (!task) return
    setTitle(getPlainMarkedText(task.title))
    setDescription(task.description || "")
    setStatusValue(
      (task.ga_note_origin_id || task.plan_note_origin_id) && !["TODO", "IN_PROGRESS", "DONE"].includes(task.status || "")
        ? "TODO"
        : (task.status || "")
    )
    setStartDate(toDateInputValue(task.start_date))
    setDueDate(toDateInputValue(task.due_date))
    setDeadlineImportant(Boolean(task.is_deadline_important))
    setAssignedTo(task.assigned_to || UNASSIGNED_VALUE)
    setConfirmationAssigneeId(task.confirmation_assignee_id || "")
    // Get assignees from assignees array, fallback to assigned_to for backward compatibility
    const assigneeIds = task.assignees && task.assignees.length > 0
      ? task.assignees.map(a => a.id).filter((id): id is string => Boolean(id))
      : (task.assigned_to ? [task.assigned_to] : [])
    setAssignees(assigneeIds)
    setInitialAssignees(assigneeIds)
    if (task.ga_note_origin_id) {
      void loadGaNoteTaskAssigneeIds(apiFetch, task.ga_note_origin_id)
        .then((gaAssigneeIds) => {
          setAssignees(gaAssigneeIds)
          setInitialAssignees(gaAssigneeIds)
        })
        .catch((error) => console.warn("Failed to load GA task membership", error))
    }
    setReminder(Boolean(task.reminder_enabled))
    // Initialize fast task type
    setFastTaskType(getCurrentFastTaskType(task))
    setProjectTaskType(getCurrentProjectTaskType(task))
    setFinishPeriod(task.finish_period || FINISH_PERIOD_NONE_VALUE)
  }, [apiFetch, task])

  React.useEffect(() => {
    let cancelled = false
    const loadAttachments = async () => {
      if (!task?.ga_note_origin_id) {
        setGaNoteAttachments([])
        return
      }
      setLoadingAttachments(true)
      try {
        const noteRes = await apiFetch(`/ga-notes/${encodeURIComponent(task.ga_note_origin_id)}`)
        if (!noteRes.ok) throw new Error("Failed to load attachments")
        const note = (await noteRes.json()) as { attachments?: GaNoteAttachment[] }
        if (!cancelled) setGaNoteAttachments(note.attachments || [])
      } catch {
        if (!cancelled) {
          setGaNoteAttachments([])
          toast.error("Failed to load GA/KA attachments")
        }
      } finally {
        if (!cancelled) setLoadingAttachments(false)
      }
    }
    void loadAttachments()
    return () => {
      cancelled = true
    }
  }, [apiFetch, task?.ga_note_origin_id])

  React.useEffect(() => {
    return () => {
      if (previewUrl) {
        window.URL.revokeObjectURL(previewUrl)
      }
    }
  }, [previewUrl])

  const downloadAttachment = async (attachment: GaNoteAttachment) => {
    try {
      const res = await apiFetch(`/ga-notes/attachments/${attachment.id}`)
      if (!res?.ok) {
        let detail = `Failed to download file (${res?.status || "unknown"})`
        try {
          const contentType = res?.headers?.get("content-type") || ""
          if (contentType.includes("application/json")) {
            const data = await res.json()
            if (data?.detail) detail = String(data.detail)
          }
        } catch {
          // ignore
        }
        toast.error(detail)
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
      const res = await apiFetch(`/ga-notes/attachments/${attachment.id}`)
      if (!res?.ok) {
        let detail = `Failed to open file (${res?.status || "unknown"})`
        try {
          const contentType = res?.headers?.get("content-type") || ""
          if (contentType.includes("application/json")) {
            const data = await res.json()
            if (data?.detail) detail = String(data.detail)
          }
        } catch {
          // ignore
        }
        toast.error(detail)
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

  const isNoteOriginTask = Boolean(task?.ga_note_origin_id || task?.plan_note_origin_id)
  const canAssign = !task?.plan_note_origin_id

  const save = async () => {
    if (!task) return
    setSaving(true)
    try {
      const trimmedTitle = title.trim()
      if (!isNoteOriginTask && trimmedTitle.length < 2) {
        toast.error("Title must be at least 2 characters")
        return
      }
      if (startDate && dueDate && startDate > dueDate) {
        toast.error("Start date cannot be after due date")
        return
      }

      const payload: Record<string, unknown> = isNoteOriginTask
        ? { reminder_enabled: reminder }
        : {
            title: buildMarkedAppendOnlyText(task.title, trimmedTitle),
            description,
            reminder_enabled: reminder,
          }
      let gaMembershipChanged = false
      let removedCurrentCopy = false
      if (statusValue) payload.status = statusValue
      if (isNoteOriginTask && statusValue && !["TODO", "IN_PROGRESS", "WAITING_CLIENT", "WAITING_CONFIRMATION", "DONE"].includes(statusValue)) {
        toast.error("Note task status must be To Do, In Progress, WFE, Waiting Confirmation, or Done")
        return
      }
      const confirmationValidation = isNoteOriginTask
        ? null
        : validateWaitingConfirmation(statusValue || null, confirmationAssigneeId)
      if (confirmationValidation) {
        toast.error(confirmationValidation)
        return
      }
      if (!isNoteOriginTask && isWaitingConfirmation(statusValue || null)) {
        payload.confirmation_assignee_id = confirmationAssigneeId
      }
      if (canAssign) {
        payload.start_date = startDate || null
        payload.due_date = dueDate || null
        payload.finish_period = finishPeriod === FINISH_PERIOD_NONE_VALUE ? null : finishPeriod
        payload.is_deadline_important = deadlineImportant
        // Only send assignees if the user actually changed them.
        // For fast tasks, sending assignees can trigger backend "group membership" logic
        // (and potentially create per-user copies). Status-only changes shouldn't do that.
        const assigneesChanged = !sameIdSet(
          assignees,
          task.ga_note_origin_id ? initialAssignees : currentTaskAssigneeIds
        )
        if (assigneesChanged && task.ga_note_origin_id) {
          const membershipRes = await replaceGaNoteTaskAssignees(apiFetch, task.ga_note_origin_id, assignees)
          if (!membershipRes.ok) {
            let detail = "Failed to update GA task assignees"
            try {
              const data = (await membershipRes.json()) as { detail?: string }
              if (typeof data.detail === "string") detail = data.detail
            } catch {
              // Keep fallback.
            }
            toast.error(detail)
            return
          }
          gaMembershipChanged = true
          removedCurrentCopy = Boolean(task.assigned_to && !assignees.includes(task.assigned_to))
        } else if (assigneesChanged) {
          payload.assigned_to = assignees.length > 0 ? assignees[0] : null
          payload.assignees = assignees
        }
      }

      if (removedCurrentCopy) {
        clearDepartmentBootstrapCacheByPrefix("department:")
        toast.success("Task assignees updated")
        router.push(returnTo || "/open-tasks")
        return
      }

      // Handle fast task type changes (only for fast tasks)
      if (isFastTask(task)) {
        const currentType = getCurrentFastTaskType(task)
        if (fastTaskType !== currentType) {
          // Reset all flags first
          payload.is_bllok = false
          payload.is_r1 = false
          payload.is_1h_report = false
          payload.is_personal = false
          
          // Set the appropriate flag based on selected type
          switch (fastTaskType) {
            case "BLL":
              payload.is_bllok = true
              break
            case "R1":
              payload.is_r1 = true
              break
            case "1H":
              payload.is_1h_report = true
              break
            case "P:":
              payload.is_personal = true
              break
            case "N":
              // Normal - all flags already false
              break
          }
        }
      }

      if (isProjectTask(task)) {
        const currentType = getCurrentProjectTaskType(task)
        if (projectTaskType !== currentType) {
          payload.priority = projectTaskType === "HIGH" ? "HIGH" : "NORMAL"
          payload.is_1h_report = projectTaskType === "1H"
          payload.is_r1 = projectTaskType === "R1"
          payload.is_personal = projectTaskType === "PERSONAL"
          payload.is_bllok = projectTaskType === "BLLOK"
        }
      }

      const res = await apiFetch(`/tasks/${task.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        if (res.status === 403) {
          toast.error("Forbidden: You don't have permission to edit this task")
          return
        }
        let errorMessage = "Failed to update task"
        try {
          const errorData = await res.json()
          if (errorData.detail) {
            errorMessage = typeof errorData.detail === "string" ? errorData.detail : "Failed to update task"
          }
        } catch {
          // ignore
        }
        toast.error(errorMessage)
        return
      }
      if (gaMembershipChanged) {
        clearDepartmentBootstrapCacheByPrefix("department:")
      }
      toast.success("Task updated")
      if (returnTo) {
        clearDepartmentBootstrapCacheByPrefix("department:")
        router.push(returnTo)
        return
      }
      await load()
    } finally {
      setSaving(false)
    }
  }

  // Get all assignees for display - must be before conditional return
  const assignedUser = task ? users.find((u) => u.id === task.assigned_to) || null : null
  const allAssignees = task
    ? (task.assignees && task.assignees.length > 0
        ? task.assignees
        : (task.assigned_to ? [{ id: task.assigned_to, full_name: assignedUser?.full_name, username: assignedUser?.username }] : []))
    : []
  
  const assigneeLabel = React.useMemo(() => {
    if (assignees.length === 0) return "Unassigned"
    if (users.length && assignees.length === users.length) return "All users"
    if (assignees.length === 1) {
      const selected = users.find((u) => u.id === assignees[0])
      return selected?.full_name || selected?.username || "1 selected"
    }
    return `${assignees.length} selected`
  }, [users, assignees])
  const confirmerCandidates = React.useMemo(() => getConfirmerCandidates(users), [users])
  const requiresConfirmer = isWaitingConfirmation(statusValue || null)

  if (loadError) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-sky-50 px-4 py-8">
        <div className="max-w-2xl mx-auto rounded-lg border border-rose-200 bg-white p-6 shadow-sm">
          <div className="text-base font-semibold text-rose-700 mb-2">Unable to load task</div>
          <div className="text-sm text-rose-600">{loadError}</div>
          <Button variant="outline" className="mt-4" onClick={() => void load()}>
            Retry
          </Button>
        </div>
      </div>
    )
  }

  if (!task) return <div className="text-sm text-muted-foreground">Loading...</div>

  const statusText = statusLabel(task.status)
  const priorityText = task.priority ? TASK_PRIORITY_LABELS[task.priority] || task.priority : "-"
  const planningBrief = task.planning_brief
  const planningUserNames = (ids?: string[], fallback?: string | null) => {
    const names = (ids || []).map((id) => {
      const person = users.find((item) => item.id === id)
      return person?.full_name || person?.username || id
    })
    return names.length ? names.join(", ") : fallback || "—"
  }

  return (
    <>
      <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-sky-50">
      <div className="mx-auto max-w-6xl px-4 py-8 space-y-6">
        <Card className="border-slate-200/70 bg-white/80 shadow-sm">
          <CardContent className="p-6">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="space-y-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    if (returnTo) {
                      router.push(returnTo)
                    } else {
                      router.back()
                    }
                  }}
                  className="px-0"
                >
                  Back
                </Button>
                <div className="flex items-start gap-2 text-2xl font-semibold text-slate-900">
                  <TaskOneHMarker marker={task.one_h_marker} markerByGa={task.one_h_marker_by_ga} comment={task.one_h_marker_comment} className="mt-1" />
                  <span className="min-w-0"><TaskMarkerComment comment={task.one_h_marker_comment} taskId={task.id} />{renderMarkedNoteContent(title || task.title, title || task.title)}</span>
                </div>
                <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                  <span>Status: {statusText}</span>
                  <span>•</span>
                  <span>Priority: {priorityText}</span>
                  {task.phase ? (
                    <>
                      <span>•</span>
                      <span>Phase: {task.phase}</span>
                    </>
                  ) : null}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                {task.task_type === "system" ? <Badge variant="secondary">System</Badge> : null}
                {task.reminder_enabled ? <Badge variant="secondary">1h Reminder</Badge> : null}
                {task.is_carried_over ? <Badge variant="secondary">Carried</Badge> : null}
              </div>
            </div>
          </CardContent>
        </Card>

        <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
          <Card className="border-slate-200/70 bg-white/90 shadow-sm">
            <CardHeader>
              <CardTitle className="text-sm">Update Task</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {isNoteOriginTask ? (
                <div className="rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-800">
                  This is your independent note task copy. Edit its status and scheduling here; shared details are managed in {task.plan_note_origin_id ? "PX JAV" : "GA Notes"}.
                </div>
              ) : null}
              <div className="space-y-2">
                <Label htmlFor="task-title">Title</Label>
                <Input
                  id="task-title"
                  value={title}
                  disabled={isNoteOriginTask}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Task title"
                />
                <div className="text-xs text-muted-foreground">
                  Preview:{" "}
                  <span className="text-slate-900">
                    {renderMarkedNoteContent(buildMarkedAppendOnlyText(task?.title, title), title)}
                  </span>
                </div>
              </div>
              <div className="space-y-2">
                <Label>Status</Label>
                <Select value={statusValue} onValueChange={(value) => setStatusValue(value as typeof statusValue)}>
                  <SelectTrigger>
                    <SelectValue placeholder="Status" />
                  </SelectTrigger>
                  <SelectContent>
                    {TASK_STATUS_OPTIONS.filter((option) =>
                      !isNoteOriginTask || ["TODO", "IN_PROGRESS", "DONE"].includes(option.value)
                    ).map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {requiresConfirmer ? (
                <div className="space-y-2">
                  <Label>Confirm by (Manager/Admin)</Label>
                  <Select value={confirmationAssigneeId || UNASSIGNED_VALUE} onValueChange={(value) => {
                    setConfirmationAssigneeId(value === UNASSIGNED_VALUE ? "" : value)
                  }}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select confirmer" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={UNASSIGNED_VALUE}>Select confirmer</SelectItem>
                      {confirmerCandidates.map((candidate) => (
                        <SelectItem key={candidate.id} value={candidate.id}>
                          {candidate.full_name || candidate.username || "-"}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              ) : null}

              <div className="space-y-2">
                <Label>Description</Label>
                <PromptLinkButton text={description} />
                {isNoteOriginTask ? (
                  <div className="min-h-[44px] rounded-md border bg-slate-50 px-3 py-2 text-sm text-slate-700">
                    {description || "—"}
                  </div>
                ) : (
                  <BoldOnlyEditor value={description} onChange={setDescription} />
                )}
              </div>

              {isFastTask(task) ? (
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label>Type</Label>
                    <Select
                      value={fastTaskType}
                      onValueChange={(value) => setFastTaskType(value as FastTaskType)}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select type" />
                      </SelectTrigger>
                      <SelectContent>
                        {FAST_TASK_TYPES.map((option) => (
                          <SelectItem
                            key={option.value}
                            value={option.value}
                          >
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-2">
                    <Label>Finish period</Label>
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
                        <SelectItem value={FINISH_PERIOD_NONE_VALUE}>All day</SelectItem>
                        <SelectItem value="AM">AM</SelectItem>
                        <SelectItem value="PM">PM</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              ) : null}

              {isProjectTask(task) ? (
                <div className="space-y-2">
                  <Label>Type</Label>
                  <Select
                    value={projectTaskType}
                    onValueChange={(value) => setProjectTaskType(value as ProjectTaskType)}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select type" />
                    </SelectTrigger>
                    <SelectContent>
                      {PROJECT_TASK_TYPES.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              ) : null}

              {isNoteOriginTask && canAssign && isProjectTask(task) ? (
                <div className="space-y-2">
                  <Label>Finish period</Label>
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
                      <SelectItem value={FINISH_PERIOD_NONE_VALUE}>All day</SelectItem>
                      <SelectItem value="AM">AM</SelectItem>
                      <SelectItem value="PM">PM</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              ) : null}

              {canAssign ? (
                <div className="grid gap-3 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label>Start date</Label>
                    <Input
                      type="date"
                      value={startDate}
                      onChange={(e) => setStartDate(normalizeDueDateInput(e.target.value))}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Due date</Label>
                    <Input
                      type="date"
                      value={dueDate}
                      onChange={(e) => setDueDate(normalizeDueDateInput(e.target.value))}
                    />
                  </div>
                </div>
              ) : null}
              {canAssign ? (
                <label className="flex items-center gap-3 rounded-md border px-3 py-2">
                  <Checkbox
                    checked={deadlineImportant}
                    onCheckedChange={(checked) => setDeadlineImportant(checked === true)}
                  />
                  <span className="text-sm font-medium">Deadline important</span>
                </label>
              ) : null}
              {canAssign ? (
                <div className="space-y-2">
                  <Label>Assign to</Label>
                  <Dialog open={selectAssigneesOpen} onOpenChange={setSelectAssigneesOpen}>
                    <DialogTrigger asChild>
                      <Button
                        type="button"
                        variant="outline"
                        className="w-full justify-start"
                      >
                        {assigneeLabel}
                      </Button>
                    </DialogTrigger>
                    <DialogContent className="sm:max-w-md">
                      <DialogHeader>
                        <DialogTitle>Select Assignees</DialogTitle>
                      </DialogHeader>
                      <div className="mt-4 max-h-[400px] overflow-y-auto space-y-2">
                        {users.length ? (
                            users.map((u) => {
                                const isSelected = assignees.includes(u.id)
                                return (
                                  <div
                                    key={u.id}
                                    className="flex items-center space-x-2 p-2 rounded-lg hover:bg-slate-50 cursor-pointer"
                                    onClick={() => {
                                      if (isSelected) {
                                        setAssignees((prev) => prev.filter((id) => id !== u.id))
                                      } else {
                                        setAssignees((prev) => [...prev, u.id])
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
                        <Button variant="outline" onClick={() => setAssignees([])}>
                          Clear
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() => {
                            setAssignees(users.map((u) => u.id))
                          }}
                          disabled={!users.length}
                        >
                          All users
                        </Button>
                        <Button onClick={() => setSelectAssigneesOpen(false)}>
                          Done
                        </Button>
                      </div>
                    </DialogContent>
                  </Dialog>
                </div>
              ) : null}

              <div className="flex flex-wrap items-center gap-4 pt-1">
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox checked={reminder} onCheckedChange={(v) => setReminder(Boolean(v))} />
                  1h Reminder
                </label>
              </div>

              <div className="flex justify-end">
                <Button
                  disabled={saving || (requiresConfirmer && !confirmationAssigneeId)}
                  onClick={() => void save()}
                >
                  {saving ? "Saving..." : "Save"}
                </Button>
              </div>
            </CardContent>
          </Card>

          {planningBrief ? (
            <Card className="border-violet-200 bg-violet-50/60 shadow-sm lg:col-start-1 lg:row-start-2">
              <CardHeader>
                <div className="flex items-center justify-between gap-3">
                  <CardTitle className="text-sm text-violet-950">Planifikimi nga PX JAV</CardTitle>
                  <Badge variant="outline" className="border-violet-200 bg-white text-violet-700">Vetëm për lexim</Badge>
                </div>
              </CardHeader>
              <CardContent>
                <dl className="divide-y divide-violet-100 overflow-hidden rounded-lg border border-violet-100 bg-white text-sm">
                  <div className="grid sm:grid-cols-[120px_minmax(0,1fr)]">
                    <dt className="bg-violet-50 px-3 py-3 text-xs font-semibold text-violet-700">DL</dt>
                    <dd className="whitespace-pre-wrap px-3 py-3 text-slate-800">{planningBrief.dl || "—"}</dd>
                  </div>
                  <div className="grid sm:grid-cols-[120px_minmax(0,1fr)]">
                    <dt className="bg-violet-50 px-3 py-3 text-xs font-semibold text-violet-700">DG</dt>
                    <dd className="whitespace-pre-wrap px-3 py-3 text-slate-800">
                      {typeof planningBrief.dg !== "boolean"
                        ? "—"
                        : planningBrief.dg
                          ? `Po — ${planningUserNames(planningBrief.dg_kush_user_ids, planningBrief.dg_kush)}`
                          : "Jo"}
                    </dd>
                  </div>
                  <div className="grid sm:grid-cols-[120px_minmax(0,1fr)]">
                    <dt className="bg-violet-50 px-3 py-3 text-xs font-semibold text-violet-700">HAPAT</dt>
                    <dd className="whitespace-pre-wrap px-3 py-3 text-slate-800">{planningBrief.hapat || "—"}</dd>
                  </div>
                  <div className="grid sm:grid-cols-[120px_minmax(0,1fr)]">
                    <dt className="bg-violet-50 px-3 py-3 text-xs font-semibold text-violet-700">KUSH</dt>
                    <dd className="whitespace-pre-wrap px-3 py-3 text-slate-800">{planningUserNames(planningBrief.kush_user_ids, planningBrief.kush)}</dd>
                  </div>
                  <div className="grid sm:grid-cols-[120px_minmax(0,1fr)]">
                    <dt className="bg-violet-50 px-3 py-3 text-xs font-semibold text-violet-700">SQ</dt>
                    <dd className="whitespace-pre-wrap px-3 py-3 text-slate-800">{planningBrief.sq || "—"}</dd>
                  </div>
                  <div className="grid sm:grid-cols-[120px_minmax(0,1fr)]">
                    <dt className="bg-violet-50 px-3 py-3 text-xs font-semibold text-violet-700">LLOJI DET</dt>
                    <dd className="whitespace-pre-wrap px-3 py-3 text-slate-800">{planningBrief.lloji_det || "—"}</dd>
                  </div>
                </dl>
                <p className="mt-3 text-xs text-violet-700">Ndryshimet e këtij planifikimi menaxhohen në PX JAV.</p>
              </CardContent>
            </Card>
          ) : null}

          <Card className="border-slate-200/70 bg-white/90 shadow-sm lg:col-start-2 lg:row-start-1">
            <CardHeader>
              <CardTitle className="text-sm">Task Info</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-4">
                <div className="grid gap-3 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Assignee{allAssignees.length > 1 ? "s" : ""}</span>
                    <span className="font-medium text-slate-900">
                      {allAssignees.length > 0
                        ? allAssignees.map((a) => a.full_name || a.username || "-").join(", ")
                        : "Unassigned"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Start date</span>
                    <span className="font-medium text-slate-900">{formatDate(task.start_date)}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Due date</span>
                    <span className="font-medium text-slate-900">{formatDate(task.due_date)}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Created</span>
                    <span className="font-medium text-slate-900">{formatDate(task.created_at)}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Updated</span>
                    <span className="font-medium text-slate-900">{formatDate(task.updated_at)}</span>
                  </div>
                </div>
              </div>

              <div className="space-y-2">
                <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Flags</div>
                <div className="flex flex-wrap gap-2">
                  {task.is_bllok ? <Badge variant="secondary">BLLOK</Badge> : null}
                  {task.is_1h_report ? <Badge variant="secondary">1H</Badge> : null}
                  {task.is_r1 ? <Badge variant="secondary">R1</Badge> : null}
                  {task.is_personal ? <Badge variant="secondary">P</Badge> : null}
                  {!task.is_bllok && !task.is_1h_report && !task.is_r1 && !task.is_personal ? (
                    <span className="text-sm text-muted-foreground">No special flags.</span>
                  ) : null}
                </div>
              </div>

              {task.ga_note_origin_id ? (
                <div className="space-y-2">
                  <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Attachments</div>
                  {loadingAttachments ? (
                    <div className="text-sm text-muted-foreground">Loading attachments...</div>
                  ) : gaNoteAttachments.length ? (
                    <div className="space-y-2">
                      {gaNoteAttachments.map((attachment) => {
                        const isImage = (attachment.content_type || "").startsWith("image/")
                        return (
                          <div key={attachment.id} className="flex items-center justify-between gap-2 rounded border border-slate-200 bg-white px-2 py-1">
                            <div className="flex flex-col">
                              <span className="text-xs font-medium text-slate-700">
                                {attachment.original_filename}
                              </span>
                              <span className="text-[10px] text-slate-500">
                                {formatFileSize(attachment.size_bytes)}
                              </span>
                            </div>
                            <div className="flex items-center gap-2">
                              {isImage ? (
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="h-6 text-[10px]"
                                  onClick={() => void openAttachmentPreview(attachment)}
                                >
                                  View
                                </Button>
                              ) : null}
                              <Button
                                variant="outline"
                                size="sm"
                                className="h-6 text-[10px]"
                                onClick={() => void downloadAttachment(attachment)}
                              >
                                Download
                              </Button>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  ) : (
                    <div className="text-sm text-muted-foreground">No attachments.</div>
                  )}
                </div>
              ) : null}
            </CardContent>
          </Card>
          <TaskReviewsPanel task={task} />
        </div>
      </div>
    </div>
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
    </>
  )
}
