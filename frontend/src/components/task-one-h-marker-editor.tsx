"use client"

import * as React from "react"
import { toast } from "sonner"
import { MessageCircle } from "lucide-react"
import { cn } from "@/lib/utils"
import { useAuth } from "@/lib/auth"
import type { Task } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"

type TaskMarker = NonNullable<Task["one_h_marker"]>
const NONE = "__none__"
const MARKER_UPDATED_EVENT = "primeflow:task-marker-updated"
const OPTIONS: Array<{ value: TaskMarker; label: string }> = [
  { value: "QUESTION", label: "?" }, { value: "EXCLAMATION", label: "!" },
  { value: "CLIENT_URGENT", label: "!!!" },
  { value: "SHARE", label: "SHARE" },
  { value: "MONITOR", label: "👁" }, { value: "CLOSE", label: "X" },
  { value: "M2", label: "M2" }, { value: "M3", label: "M3" }, { value: "M2_M3", label: "M2/3" },
  { value: "GENT", label: "GENT" }, { value: "KA", label: "KA" }, { value: "FLAG", label: "GA" },
  { value: "F", label: "F" }, { value: "BZ1N1", label: "BZ1N1" },
]

export function TaskOneHMarkerEditor({ taskId, marker, markerByGa, markerComment, className }: {
  taskId?: string | null
  marker?: Task["one_h_marker"]
  markerByGa?: boolean
  markerComment?: string | null
  className?: string
}) {
  const { apiFetch, user } = useAuth()
  const [value, setValue] = React.useState<TaskMarker | typeof NONE>(marker || NONE)
  const [byGa, setByGa] = React.useState(Boolean(markerByGa))
  const [comment, setComment] = React.useState(markerComment || "")
  const [draftComment, setDraftComment] = React.useState(markerComment || "")
  const [pendingMarker, setPendingMarker] = React.useState<TaskMarker | null>(null)
  const [commentOpen, setCommentOpen] = React.useState(false)
  const [saving, setSaving] = React.useState(false)
  const hasComment = Boolean(comment.trim())
  const wrapperPositionClasses = ["order-last", "ml-auto", "shrink-0"]
    .filter((token) => className?.split(/\s+/).includes(token))
    .join(" ")
  const selectedLabel = OPTIONS.find((option) => option.value === value)?.label || "—"
  const selectedDisplayLength = selectedLabel.length + (byGa && value !== NONE ? 2 : 0)
  const commonViewWidth = value === NONE || selectedDisplayLength === 1
    ? 50
    : selectedDisplayLength <= 3
      ? 60
      : 70
  const compactCommonViewStyle = className?.split(/\s+/).includes("oneh-marker-select")
    ? { width: commonViewWidth, minWidth: commonViewWidth, maxWidth: commonViewWidth }
    : {}

  React.useEffect(() => setValue(marker || NONE), [marker])
  React.useEffect(() => setByGa(Boolean(markerByGa)), [markerByGa])
  React.useEffect(() => { setComment(markerComment || ""); setDraftComment(markerComment || "") }, [markerComment])
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
    if (!taskId || saving) return
    const previous = { value, byGa, comment }
    setValue(next)
    setByGa(Boolean(next !== NONE && user?.email?.trim().toLowerCase() === "ga@primexeu.com"))
    setComment(next === NONE ? "" : nextComment)
    setSaving(true)
    try {
      const response = await apiFetch(`/tasks/${taskId}/one-h-marker`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ one_h_marker: next === NONE ? null : next, one_h_marker_comment: next === NONE ? null : nextComment.trim() || null }),
      })
      if (!response?.ok) throw new Error("Could not update task symbol")
      const updated = await response.json() as { one_h_marker_by_ga?: boolean; one_h_marker_comment?: string | null }
      const updatedByGa = Boolean(updated.one_h_marker_by_ga)
      const updatedComment = updated.one_h_marker_comment || ""
      setByGa(updatedByGa); setComment(updatedComment)
      window.dispatchEvent(new CustomEvent(MARKER_UPDATED_EVENT, { detail: { taskId, marker: next === NONE ? null : next, markerByGa: updatedByGa, markerComment: updatedComment } }))
      toast.success("Task symbol updated")
    } catch (error) {
      setValue(previous.value); setByGa(previous.byGa); setComment(previous.comment)
      toast.error("Task symbol update failed", { description: String(error) })
    } finally { setSaving(false) }
  }

  const chooseMarker = (nextValue: string) => {
    if (nextValue === NONE) { void updateMarker(NONE); return }
    const next = nextValue as TaskMarker
    setPendingMarker(next); setDraftComment(next === value ? comment : ""); setCommentOpen(true)
  }
  const savePendingMarker = () => {
    if (!pendingMarker) return
    setCommentOpen(false); void updateMarker(pendingMarker, draftComment); setPendingMarker(null)
  }

  return (
    <div className={`relative inline-flex items-center ${wrapperPositionClasses}`} onClick={(event) => event.stopPropagation()}>
      <Select value={value} onValueChange={chooseMarker} disabled={!taskId || saving}>
        <SelectTrigger className={`h-7 min-w-[64px] max-w-[82px] border-blue-300 bg-blue-50 px-2 py-0 text-base font-black leading-none [text-shadow:0_0_0_currentColor] ${className || ""}`} style={{ color: value === NONE ? "#0F2A5F" : "#DC2626", ...compactCommonViewStyle }} aria-label="Task symbol" title={comment || "Edit task symbol"}>
          <SelectValue placeholder="—" className="relative -top-px leading-none" />
        </SelectTrigger>
        <SelectContent className="font-black text-[#0F2A5F]">
          <SelectItem value={NONE}>—</SelectItem>
          {OPTIONS.map((option) => <SelectItem key={option.value} value={option.value} className="font-black text-red-600 focus:text-red-700">{byGa && value === option.value ? `(${option.label})` : option.label}</SelectItem>)}
        </SelectContent>
      </Select>
      {value !== NONE ? (
        <button
          type="button"
          className={cn(
            "absolute z-10 flex items-center justify-center rounded-full p-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700",
            hasComment
              ? "-right-2 -top-2 h-6 w-6 border-2 border-blue-950 bg-[#0055FF] text-white shadow-md ring-2 ring-white hover:bg-blue-700"
              : "-right-1 -top-1 h-4 w-4 border border-blue-300 bg-white text-blue-400 shadow-sm hover:bg-blue-50"
          )}
          title={hasComment ? comment : "Add symbol comment"}
          aria-label={hasComment ? "View symbol comment" : "Add symbol comment"}
          onClick={() => { setPendingMarker(value); setDraftComment(comment); setCommentOpen(true) }}
        >
          <MessageCircle className={hasComment ? "h-4 w-4" : "h-3 w-3"} strokeWidth={hasComment ? 3 : 2.5} aria-hidden="true" />
        </button>
      ) : null}
      <Dialog open={commentOpen} onOpenChange={setCommentOpen}>
        <DialogContent onClick={(event) => event.stopPropagation()}>
          <DialogHeader><DialogTitle>Symbol comment</DialogTitle><DialogDescription>Add an optional comment. It appears above the task title wherever the task is shown.</DialogDescription></DialogHeader>
          <Textarea value={draftComment} onChange={(event) => setDraftComment(event.target.value)} maxLength={1000} placeholder="Write an optional comment..." rows={5} />
          <DialogFooter>
            {comment ? <Button type="button" variant="outline" onClick={() => void navigator.clipboard.writeText(comment)}>Copy current</Button> : null}
            <Button type="button" variant="outline" onClick={() => setCommentOpen(false)}>Cancel</Button>
            <Button type="button" onClick={savePendingMarker} disabled={saving}>Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
