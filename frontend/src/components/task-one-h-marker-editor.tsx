"use client"

import * as React from "react"
import { toast } from "sonner"
import { MessageCircle } from "lucide-react"
import { cn } from "@/lib/utils"
import { useMarkerComments } from "@/components/marker-comments-context"
import { useAuth } from "@/lib/auth"
import type { Task } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { TaskMarkerSelect } from "@/components/task-marker-select"
import { taskMarkerLabel } from "@/lib/task-markers"
import { Textarea } from "@/components/ui/textarea"

type TaskMarker = NonNullable<Task["one_h_marker"]>
const NONE = "__none__"
const MARKER_UPDATED_EVENT = "primeflow:task-marker-updated"

export function TaskOneHMarkerEditor({ taskId, noteId, noteSource = "ga-notes", onSaved, marker, markerByGa, markerComment, className }: {
  taskId?: string | null
  noteId?: string | null
  noteSource?: "ga-notes" | "plan-notes"
  onSaved?: (fields: Pick<Task, "one_h_marker" | "one_h_marker_by_ga" | "one_h_marker_comment">) => void
  marker?: Task["one_h_marker"]
  markerByGa?: boolean
  markerComment?: string | null
  className?: string
}) {
  const { apiFetch, user } = useAuth()
  const comments = useMarkerComments()
  const [value, setValue] = React.useState<TaskMarker | typeof NONE>(marker || NONE)
  const [byGa, setByGa] = React.useState(Boolean(markerByGa))
  const [comment, setComment] = React.useState(markerComment || "")
  const [draftComment, setDraftComment] = React.useState(markerComment || "")
  const [pendingMarker, setPendingMarker] = React.useState<TaskMarker | typeof NONE | null>(null)
  const [commentOpen, setCommentOpen] = React.useState(false)
  const [saving, setSaving] = React.useState(false)
  const resourceKey = taskId ? `task:${taskId}` : `${noteSource}:${noteId || ""}`
  const [previousProps, setPreviousProps] = React.useState({ resourceKey, marker, markerByGa, markerComment })
  // Reconcile changed inputs before rendering, while keeping optimistic edits
  // when the parent renders again with the same saved values.
  if (previousProps.resourceKey !== resourceKey || previousProps.marker !== marker ||
      previousProps.markerByGa !== markerByGa || previousProps.markerComment !== markerComment) {
    const resourceChanged = previousProps.resourceKey !== resourceKey
    setPreviousProps({ resourceKey, marker, markerByGa, markerComment })
    if (resourceChanged || previousProps.marker !== marker) setValue(marker || NONE)
    if (resourceChanged || previousProps.markerByGa !== markerByGa) setByGa(Boolean(markerByGa))
    if (resourceChanged || previousProps.markerComment !== markerComment) {
      setComment(markerComment || "")
      setDraftComment(markerComment || "")
    }
  }
  const inboxItem = taskId ? comments?.byTask.get(taskId) : undefined
  const appliedInboxRevision = React.useRef<string | null>(null)
  const hasComment = Boolean(comment.trim())
  const wrapperPositionClasses = ["order-last", "ml-auto", "shrink-0"]
    .filter((token) => className?.split(/\s+/).includes(token))
    .join(" ")
  const selectedLabel = taskMarkerLabel(value, byGa) || "—"
  const selectedDisplayLength = selectedLabel.length
  const commonViewWidth = value === NONE || selectedDisplayLength === 1
    ? 50
    : selectedDisplayLength <= 3
      ? 60
      : Math.min(160, 30 + selectedDisplayLength * 9)
  const compactCommonViewStyle = className?.split(/\s+/).includes("oneh-marker-select")
    ? { width: commonViewWidth, minWidth: commonViewWidth, maxWidth: commonViewWidth }
    : {}

  React.useEffect(() => {
    if (!inboxItem || saving || commentOpen || appliedInboxRevision.current === inboxItem.revision) return
    appliedInboxRevision.current = inboxItem.revision
    setValue((inboxItem.marker || NONE) as TaskMarker | typeof NONE)
    setByGa(Boolean(inboxItem.marker_by_ga))
    setComment(inboxItem.comment)
    setDraftComment(inboxItem.comment)
  }, [inboxItem, saving, commentOpen])
  React.useEffect(() => {
    if (!taskId || !marker || (markerByGa !== undefined && markerComment !== undefined)) return
    let active = true
    void apiFetch(`/tasks/${taskId}`).then(async (response) => {
      if (!response?.ok) return
      const task = await response.json() as { one_h_marker_by_ga?: boolean; one_h_marker_comment?: string | null }
      if (active) {
        setByGa(Boolean(task.one_h_marker_by_ga)); setComment(task.one_h_marker_comment || ""); setDraftComment(task.one_h_marker_comment || "")
        window.dispatchEvent(new CustomEvent(MARKER_UPDATED_EVENT, { detail: { taskId, marker, markerByGa: Boolean(task.one_h_marker_by_ga), markerComment: task.one_h_marker_comment || null } }))
      }
    }).catch(() => undefined)
    return () => { active = false }
  }, [apiFetch, marker, markerByGa, markerComment, taskId])

  React.useEffect(() => {
    const syncMarker = (event: Event) => {
      const detail = (event as CustomEvent<{ taskId: string; marker: TaskMarker | null; markerByGa: boolean; markerComment?: string | null }>).detail
      if (detail?.taskId === taskId) { setValue(detail.marker || NONE); setByGa(Boolean(detail.markerByGa)); setComment(detail.markerComment || "") }
    }
    window.addEventListener(MARKER_UPDATED_EVENT, syncMarker)
    return () => window.removeEventListener(MARKER_UPDATED_EVENT, syncMarker)
  }, [taskId])

  const updateMarker = async (next: TaskMarker | typeof NONE, nextComment = "") => {
    if ((!taskId && !noteId) || saving) return
    const previous = { value, byGa, comment }
    setValue(next)
    setByGa(Boolean(next !== NONE && user?.email?.trim().toLowerCase() === "ga@primexeu.com"))
    setComment(nextComment)
    setSaving(true)
    try {
      const response = await apiFetch(taskId ? `/tasks/${taskId}/one-h-marker` : `/${noteSource}/${noteId}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ one_h_marker: next === NONE ? null : next, one_h_marker_comment: nextComment.trim() || null }),
      })
      if (!response?.ok) throw new Error("Could not update task symbol")
      const updated = await response.json() as { one_h_marker_by_ga?: boolean; one_h_marker_comment?: string | null }
      const updatedByGa = Boolean(updated.one_h_marker_by_ga)
      const updatedComment = updated.one_h_marker_comment || ""
      setByGa(updatedByGa); setComment(updatedComment)
      if (taskId) window.dispatchEvent(new CustomEvent(MARKER_UPDATED_EVENT, { detail: { taskId, marker: next === NONE ? null : next, markerByGa: updatedByGa, markerComment: updatedComment } }))
      onSaved?.({ one_h_marker: next === NONE ? null : next, one_h_marker_by_ga: updatedByGa, one_h_marker_comment: updatedComment || null })
      toast.success("Task symbol updated")
    } catch (error) {
      setValue(previous.value); setByGa(previous.byGa); setComment(previous.comment)
      toast.error("Task symbol update failed", { description: String(error) })
    } finally { setSaving(false) }
  }

  const currentComment = async () => {
    if (!taskId || markerComment !== undefined) return comment
    setSaving(true)
    try {
      const response = await apiFetch(`/tasks/${taskId}`)
      if (!response?.ok) throw new Error("Could not load the task comment")
      const task = await response.json() as { one_h_marker_by_ga?: boolean; one_h_marker_comment?: string | null }
      const savedComment = task.one_h_marker_comment || ""
      setByGa(Boolean(task.one_h_marker_by_ga)); setComment(savedComment)
      return savedComment
    } finally { setSaving(false) }
  }
  const chooseMarker = async (nextValue: string) => {
    try {
      const savedComment = await currentComment()
      if (nextValue === NONE) { void updateMarker(NONE, savedComment); return }
      const next = nextValue as TaskMarker
      setPendingMarker(next); setDraftComment(savedComment); setCommentOpen(true)
    } catch { toast.error("Could not load the current task comment") }
  }
  const savePendingMarker = () => {
    if (!pendingMarker) return
    setCommentOpen(false); void updateMarker(pendingMarker, draftComment); setPendingMarker(null)
  }

  return (
    <>
    <span data-task-marker-print={taskId || noteId} className="hidden font-black text-red-600 print:inline-flex">{taskMarkerLabel(value, byGa)}</span>
    <div data-task-marker-id={taskId || noteId} data-task-marker-resource={taskId ? "task" : "note"}
      className={`relative inline-flex items-center print:hidden ${wrapperPositionClasses}`}
      onPointerDown={event => event.stopPropagation()} onClick={(event) => { event.preventDefault(); event.stopPropagation() }}>
      <TaskMarkerSelect value={value} byGa={byGa} onValueChange={chooseMarker} disabled={(!taskId && !noteId) || saving}
        className={`h-7 min-w-[64px] w-auto px-2 py-0 text-base font-black ${className || ""}`}
        style={{ color: value === NONE ? "#0F2A5F" : "#DC2626", ...compactCommonViewStyle }} aria-label="Task symbols (maximum 2)" title={comment || "Edit task symbols"} />
      {taskId || noteId ? (
        <button
          type="button"
          disabled={saving}
          className={cn(
            "absolute z-10 flex items-center justify-center rounded-full p-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700",
            hasComment
              ? "-right-2 -top-2 h-6 w-6 border-2 border-blue-950 bg-[#0055FF] text-white shadow-md ring-2 ring-white hover:bg-blue-700"
              : "-right-1 -top-1 h-4 w-4 border border-blue-300 bg-white text-blue-400 shadow-sm hover:bg-blue-50"
          )}
          title={hasComment ? comment : "Add task comment"}
          aria-label={hasComment ? "View task comment" : "Add task comment"}
          onClick={async () => {
            try {
              const savedComment = await currentComment()
              setPendingMarker(value); setDraftComment(savedComment); setCommentOpen(true)
              if (taskId && savedComment) comments?.markTaskRead(taskId, savedComment)
            } catch { toast.error("Could not load the current task comment") }
          }}
        >
          <MessageCircle className={hasComment ? "h-4 w-4" : "h-3 w-3"} strokeWidth={hasComment ? 3 : 2.5} aria-hidden="true" />
        </button>
      ) : null}
      <Dialog open={commentOpen} onOpenChange={setCommentOpen}>
        <DialogContent onClick={(event) => event.stopPropagation()}>
          <DialogHeader><DialogTitle>Task comment</DialogTitle><DialogDescription>Add a comment with or without a symbol. It appears above the task title wherever the task is shown.</DialogDescription></DialogHeader>
          <Textarea value={draftComment} onChange={(event) => setDraftComment(event.target.value)} maxLength={1000} placeholder="Write an optional comment..." rows={5} />
          <DialogFooter>
            {comment ? <Button type="button" variant="outline" onClick={() => void navigator.clipboard.writeText(comment)}>Copy current</Button> : null}
            <Button type="button" variant="outline" onClick={() => setCommentOpen(false)}>Cancel</Button>
            <Button type="button" onClick={savePendingMarker} disabled={saving}>Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
    </>
  )
}
