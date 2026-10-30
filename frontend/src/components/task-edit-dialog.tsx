"use client"

import * as React from "react"
import { PromptLinkButton } from "@/components/knowledge/prompt-link"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { TaskSkillField } from "@/components/task-skill-field"
import { TaskOneHMarkerEditor } from "@/components/task-one-h-marker-editor"
import { useAuth } from "@/lib/auth"
import { normalizeDueDateInput, toDateInputValue } from "@/lib/dates"
import { getConfirmerCandidates, isWaitingConfirmation, validateWaitingConfirmation } from "@/lib/task-confirmation"
import type { SkillCategory, Task, TaskFinishPeriod, UserLookup } from "@/lib/types"
import { fetchUsersLookupCached } from "@/lib/users-cache"

const TASK_STATUS_OPTIONS = [
  { value: "TODO", label: "To do" },
  { value: "IN_PROGRESS", label: "In progress" },
  { value: "WAITING_CLIENT", label: "WFE" },
  { value: "WAITING_CONFIRMATION", label: "Waiting for Confirmation" },
  { value: "DONE", label: "Done" },
] as const

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

const FINISH_PERIOD_OPTIONS: TaskFinishPeriod[] = ["AM", "PM"]
const FINISH_PERIOD_NONE_VALUE = "__none__"
const FINISH_PERIOD_NONE_LABEL = "None (all day)"
const ONE_H_REPORT_SLOT_NONE_VALUE = "__none__"
const ONE_H_REPORT_SLOT_OPTIONS = [
  { value: "10:00", label: "10:00" },
  { value: "11:00", label: "11:00" },
  { value: "11:50", label: "11:50" },
  { value: "14:20", label: "14:20" },
  { value: "16:00", label: "16:00" },
] as const
const ONE_H_REPORT_SLOT_SET = new Set<string>(ONE_H_REPORT_SLOT_OPTIONS.map((option) => option.value))
const EMAIL_TASK_TITLE_RE = /\bEM\b/i
const EIGHT_AM_TITLE_RE = /\b0?8:00\b/

type TaskStatusValue = typeof TASK_STATUS_OPTIONS[number]["value"]
type FastTaskTypeValue = typeof FAST_TASK_TYPES[number]["value"]
type ProjectTaskTypeValue = typeof PROJECT_TASK_TYPES[number]["value"]

function getOneHReportSlotValue(value?: string | null) {
  const normalized = (value || "").trim()
  return ONE_H_REPORT_SLOT_SET.has(normalized) ? normalized : ONE_H_REPORT_SLOT_NONE_VALUE
}

function isEmailTaskTitle(title: string) {
  return EMAIL_TASK_TITLE_RE.test(title)
}

function normalizeEmailTaskTitle(title: string) {
  const trimmed = title.trim()
  if (!isEmailTaskTitle(trimmed) || EIGHT_AM_TITLE_RE.test(trimmed)) return trimmed
  return `08:00 ${trimmed}`
}

function getCurrentFastTaskType(task: Task | null): FastTaskTypeValue {
  if (!task) return "N"
  if (task.is_bllok) return "BLL"
  if (task.is_r1) return "R1"
  if (task.is_1h_report) return "1H"
  if (task.is_personal) return "P:"
  return "N"
}

function isFastTask(task: Task | null) {
  if (!task) return false
  return task.project_id == null && task.dependency_task_id == null && task.system_template_origin_id == null
}

function isProjectTask(task: Task | null) {
  if (!task) return false
  return task.project_id != null && task.system_template_origin_id == null
}

function getCurrentProjectTaskType(task: Task | null): ProjectTaskTypeValue {
  if (!task) return "NORMAL"
  if (task.is_1h_report) return "1H"
  if (task.is_r1) return "R1"
  if (task.is_personal) return "PERSONAL"
  if (task.is_bllok) return "BLLOK"
  if (task.priority === "HIGH") return "HIGH"
  return "NORMAL"
}

export function TaskEditDialog({
  task,
  open,
  onOpenChange,
  onUpdated,
  showDescriptionField = false,
  embedded = false,
}: {
  task: Task | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onUpdated: (task: Task) => void | Promise<void>
  showDescriptionField?: boolean
  embedded?: boolean
}) {
  const { apiFetch } = useAuth()
  const isNoteOriginTask = Boolean(task?.ga_note_origin_id || task?.plan_note_origin_id)
  const [title, setTitle] = React.useState("")
  const [description, setDescription] = React.useState("")
  const [statusValue, setStatusValue] = React.useState<TaskStatusValue>("TODO")
  const [fastTaskType, setFastTaskType] = React.useState<FastTaskTypeValue>("N")
  const [projectTaskType, setProjectTaskType] = React.useState<ProjectTaskTypeValue>("NORMAL")
  const [startDate, setStartDate] = React.useState("")
  const [dueDate, setDueDate] = React.useState("")
  const [finishPeriod, setFinishPeriod] = React.useState<TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE>(FINISH_PERIOD_NONE_VALUE)
  const [oneHReportSlot, setOneHReportSlot] = React.useState<string>(ONE_H_REPORT_SLOT_NONE_VALUE)
  const [confirmationAssigneeId, setConfirmationAssigneeId] = React.useState("")
  const [isRepetitive, setIsRepetitive] = React.useState(false)
  const [skillCategory, setSkillCategory] = React.useState<SkillCategory | null>(null)
  const [users, setUsers] = React.useState<UserLookup[]>([])
  const [saving, setSaving] = React.useState(false)

  React.useEffect(() => {
    if (!task) return
    setTitle(task.title || "")
    setDescription(task.description || "")
    setStatusValue((task.status as TaskStatusValue | undefined) || "TODO")
    setFastTaskType(getCurrentFastTaskType(task))
    setProjectTaskType(getCurrentProjectTaskType(task))
    setStartDate(toDateInputValue(task.start_date))
    setDueDate(toDateInputValue(task.due_date))
    setFinishPeriod(task.finish_period || FINISH_PERIOD_NONE_VALUE)
    setOneHReportSlot(getOneHReportSlotValue(task.one_h_report_slot))
    setConfirmationAssigneeId(task.confirmation_assignee_id || "")
    setIsRepetitive(Boolean(task.is_repetitive))
    setSkillCategory(task.skill_category || null)
  }, [task])

  const supportsWaitingConfirmation = Boolean(
    task
    && !task.system_template_origin_id
    && (
      isNoteOriginTask
      || (isFastTask(task) && ["BLL", "R1", "1H", "P:"].includes(fastTaskType))
      || (isProjectTask(task) && ["1H", "R1", "PERSONAL", "BLLOK"].includes(projectTaskType))
      || task.is_bllok || task.is_1h_report || task.is_r1 || task.is_personal
    )
  )
  const waitingNeedsConfirmer = isWaitingConfirmation(statusValue)
  const confirmerCandidates = React.useMemo(() => getConfirmerCandidates(users), [users])

  React.useEffect(() => {
    if (!open || !waitingNeedsConfirmer) return
    let cancelled = false
    void fetchUsersLookupCached(apiFetch).then((result) => {
      if (!cancelled && result) setUsers(result as UserLookup[])
    })
    return () => { cancelled = true }
  }, [apiFetch, open, waitingNeedsConfirmer])

  const statusOptions = React.useMemo(() => {
    if (!task) return TASK_STATUS_OPTIONS
    return TASK_STATUS_OPTIONS.filter((option) => {
      if (isNoteOriginTask) return true
      if (option.value !== "WAITING_CONFIRMATION") return true
      return supportsWaitingConfirmation
    })
  }, [isNoteOriginTask, supportsWaitingConfirmation, task])

  const closeDialog = React.useCallback(() => {
    if (saving) return
    onOpenChange(false)
  }, [onOpenChange, saving])

  const handleSave = React.useCallback(async () => {
    if (!task) return

    const nextTitle = normalizeEmailTaskTitle(title)
    if (!isNoteOriginTask && nextTitle.length < 2) {
      toast.error("Title must be at least 2 characters.")
      return
    }

    const confirmationValidation = validateWaitingConfirmation(statusValue, confirmationAssigneeId)
    if (confirmationValidation) {
      toast.error(confirmationValidation)
      return
    }

    setSaving(true)
    try {
      const currentFastTaskType = getCurrentFastTaskType(task)
      const currentProjectTaskType = getCurrentProjectTaskType(task)
      const nextIsOneH = isFastTask(task)
        ? fastTaskType === "1H"
        : isProjectTask(task)
          ? projectTaskType === "1H"
          : Boolean(task.is_1h_report)
      const nextIsR1 = isFastTask(task)
        ? fastTaskType === "R1"
        : isProjectTask(task)
          ? projectTaskType === "R1"
          : Boolean(task.is_r1)
      const nextDescription = description.trim() || null
      const nextStartDate = startDate || null
      const nextDueDate = dueDate || null
      const nextFinishPeriod = finishPeriod === FINISH_PERIOD_NONE_VALUE ? null : finishPeriod
      const nextOneHReportSlot =
        (nextIsOneH || nextIsR1) && oneHReportSlot !== ONE_H_REPORT_SLOT_NONE_VALUE ? oneHReportSlot : null
      const currentStartDate = toDateInputValue(task.start_date) || null
      const currentDueDate = toDateInputValue(task.due_date) || null
      const currentFinishPeriod = task.finish_period || null
      const currentOneHReportSlot =
        getOneHReportSlotValue(task.one_h_report_slot) === ONE_H_REPORT_SLOT_NONE_VALUE
          ? null
          : getOneHReportSlotValue(task.one_h_report_slot)

      // PATCH only fields the user actually changed. This avoids unintended
      // updates and keeps restricted GA-note fields (such as title) out of a
      // date/type-only edit.
      const updates: Record<string, unknown> = {
        ...(!isNoteOriginTask && nextTitle !== (task.title || "") ? { title: nextTitle } : {}),
        ...(showDescriptionField && description !== (task.description || "")
          ? { description: nextDescription }
          : {}),
        ...(statusValue !== task.status ? { status: statusValue } : {}),
        ...(waitingNeedsConfirmer ? { confirmation_assignee_id: confirmationAssigneeId } : {}),
        ...(nextStartDate !== currentStartDate ? { start_date: nextStartDate } : {}),
        ...(nextDueDate !== currentDueDate ? { due_date: nextDueDate } : {}),
        ...(nextFinishPeriod !== currentFinishPeriod ? { finish_period: nextFinishPeriod } : {}),
        ...(isRepetitive !== Boolean(task.is_repetitive) ? { is_repetitive: isRepetitive } : {}),
        ...(skillCategory !== (task.skill_category || null) ? { skill_category: skillCategory } : {}),
        ...(nextOneHReportSlot !== currentOneHReportSlot ? { one_h_report_slot: nextOneHReportSlot } : {}),
        ...(isFastTask(task) && fastTaskType !== currentFastTaskType
          ? {
              is_bllok: fastTaskType === "BLL",
              is_r1: fastTaskType === "R1",
              is_1h_report: fastTaskType === "1H",
              is_personal: fastTaskType === "P:",
            }
          : {}),
        ...(isProjectTask(task) && projectTaskType !== currentProjectTaskType
          ? {
              priority: projectTaskType === "HIGH" ? "HIGH" : "NORMAL",
              is_1h_report: projectTaskType === "1H",
              is_r1: projectTaskType === "R1",
              is_personal: projectTaskType === "PERSONAL",
              is_bllok: projectTaskType === "BLLOK",
            }
          : {}),
      }

      if (Object.keys(updates).length === 0) {
        onOpenChange(false)
        return
      }

      const res = await apiFetch(`/tasks/${task.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updates),
      })

      if (!res.ok) {
        let detail = "Failed to update task."
        try {
          const payload = (await res.json()) as { detail?: string }
          if (payload?.detail) detail = payload.detail
        } catch {
          // Ignore non-JSON error bodies.
        }
        throw new Error(detail)
      }

      const updatedTask = (await res.json()) as Task
      await onUpdated(updatedTask)
      toast.success("Task updated")
      onOpenChange(false)
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to update task."
      toast.error(message)
    } finally {
      setSaving(false)
    }
  }, [
    apiFetch,
    confirmationAssigneeId,
    isRepetitive,
    description,
    dueDate,
    fastTaskType,
    finishPeriod,
    isNoteOriginTask,
    oneHReportSlot,
    onOpenChange,
    onUpdated,
    projectTaskType,
    showDescriptionField,
    skillCategory,
    startDate,
    statusValue,
    task,
    title,
    waitingNeedsConfirmer,
  ])

  if (!task) return null

  const content = (
    <>
        <DialogHeader className="shrink-0">
          <DialogTitle>Edit task</DialogTitle>
          <DialogDescription>
            Update the title, type, status, start date, and due date without leaving this table.
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain pr-1">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2 md:col-span-2">
              <Label>Symbol</Label>
              <TaskOneHMarkerEditor taskId={task?.id} marker={task?.one_h_marker} markerByGa={task?.one_h_marker_by_ga} markerComment={task?.one_h_marker_comment} className="w-full max-w-none" />
            </div>
            <div className="space-y-2 md:col-span-2">
              <Label htmlFor="task-edit-title">Title</Label>
              <Textarea
                id="task-edit-title"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                rows={2}
                className="h-24 min-h-24 max-h-24 overflow-y-auto resize-none whitespace-pre-wrap [overflow-wrap:anywhere]"
                disabled={saving || isNoteOriginTask}
              />
            </div>

            {showDescriptionField ? (
              <div className="space-y-2 md:col-span-2">
                <Label htmlFor="task-edit-description">Description</Label>
                <PromptLinkButton text={description} />
                <Textarea
                  id="task-edit-description"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  rows={3}
                  className="h-28 min-h-28 max-h-28 resize-none overflow-y-auto whitespace-pre-wrap [overflow-wrap:anywhere]"
                  disabled={saving}
                />
              </div>
            ) : null}

            <div className="md:col-span-2">
              <label className="flex items-center gap-3 rounded-md border px-3 py-2">
                <input type="checkbox" checked={isRepetitive} onChange={(event) => setIsRepetitive(event.target.checked)} disabled={saving} />
                <span className="text-sm font-medium">Detyrë e përsëritur</span>
              </label>
              <TaskSkillField value={skillCategory} onChange={setSkillCategory} disabled={saving} />
            </div>

            <div className={`grid gap-4 md:col-span-2 ${waitingNeedsConfirmer ? "sm:grid-cols-3" : "md:grid-cols-2"}`}>
              {isFastTask(task) ? (
                <div className="space-y-2">
                  <Label>Type</Label>
                  <Select value={fastTaskType} onValueChange={(value) => setFastTaskType(value as FastTaskTypeValue)}>
                    <SelectTrigger disabled={saving} className="w-full min-w-0 [&_[data-slot=select-value]]:min-w-0 [&_[data-slot=select-value]]:truncate">
                      <SelectValue placeholder="Type" />
                    </SelectTrigger>
                    <SelectContent>
                      {FAST_TASK_TYPES.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              ) : null}

              {isProjectTask(task) ? (
                <div className="space-y-2">
                  <Label>Type</Label>
                  <Select value={projectTaskType} onValueChange={(value) => setProjectTaskType(value as ProjectTaskTypeValue)}>
                    <SelectTrigger disabled={saving} className="w-full min-w-0 [&_[data-slot=select-value]]:min-w-0 [&_[data-slot=select-value]]:truncate">
                      <SelectValue placeholder="Type" />
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

              <div className="space-y-2">
                <Label>Status</Label>
                <Select value={statusValue} onValueChange={(value) => setStatusValue(value as TaskStatusValue)}>
                  <SelectTrigger disabled={saving} className="w-full min-w-0 [&_[data-slot=select-value]]:min-w-0 [&_[data-slot=select-value]]:truncate">
                    <SelectValue placeholder="Status" />
                  </SelectTrigger>
                  <SelectContent>
                    {statusOptions.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {waitingNeedsConfirmer ? (
                <div className="space-y-2">
                  <Label title="Manager/Admin/GA">Confirm by</Label>
                  <Select
                    value={confirmationAssigneeId || "__none__"}
                    onValueChange={(value) => setConfirmationAssigneeId(value === "__none__" ? "" : value)}
                  >
                    <SelectTrigger disabled={saving} className="w-full min-w-0 [&_[data-slot=select-value]]:min-w-0 [&_[data-slot=select-value]]:truncate">
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
            </div>

            <div className="space-y-2">
              <Label htmlFor="task-edit-start-date">Start date</Label>
              <Input
                id="task-edit-start-date"
                type="date"
                value={startDate}
                onChange={(event) => setStartDate(normalizeDueDateInput(event.target.value))}
                disabled={saving}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="task-edit-due-date">Due date</Label>
              <Input
                id="task-edit-due-date"
                type="date"
                value={dueDate}
                onChange={(event) => setDueDate(normalizeDueDateInput(event.target.value))}
                disabled={saving}
              />
            </div>

            <div className="space-y-2">
              <Label>Finish by (optional)</Label>
              <Select
                value={finishPeriod}
                onValueChange={(value) => setFinishPeriod(value as TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE)}
              >
                <SelectTrigger disabled={saving}>
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

            {((isFastTask(task) && (fastTaskType === "1H" || fastTaskType === "R1"))
              || (isProjectTask(task) && (projectTaskType === "1H" || projectTaskType === "R1"))) ? (
              <div className="space-y-2">
                <Label>{fastTaskType === "R1" || projectTaskType === "R1" ? "R1 report time" : "1H report time"}</Label>
                <Select
                  value={oneHReportSlot}
                  onValueChange={(value) => {
                    if (EIGHT_AM_TITLE_RE.test(normalizeEmailTaskTitle(title)) && value !== "10:00") {
                      toast.warning("08:00 tasks are 1H tasks and must use the 10:00 slot.")
                      setOneHReportSlot("10:00")
                      return
                    }
                    setOneHReportSlot(value)
                  }}
                >
                  <SelectTrigger disabled={saving}>
                    <SelectValue placeholder="Select time" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ONE_H_REPORT_SLOT_NONE_VALUE}>Unassigned</SelectItem>
                    {ONE_H_REPORT_SLOT_OPTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : null}
          </div>
        </div>

        <DialogFooter className="shrink-0 border-t bg-background pt-4">
          <Button type="button" variant="outline" onClick={closeDialog} disabled={saving}>
            Cancel
          </Button>
          <Button type="button" onClick={() => void handleSave()} disabled={saving}>
            {saving ? "Saving..." : "Save changes"}
          </Button>
        </DialogFooter>
    </>
  )

  return embedded ? content : (
    <Dialog open={open} onOpenChange={(nextOpen) => (!saving ? onOpenChange(nextOpen) : undefined)}>
      <DialogContent className="flex max-h-[calc(100dvh-2rem)] flex-col overflow-hidden sm:max-w-2xl lg:max-w-4xl">{content}</DialogContent>
    </Dialog>
  )
}
