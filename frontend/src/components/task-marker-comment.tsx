"use client"

import * as React from "react"
import { cn } from "@/lib/utils"
import { useMarkerComments } from "@/components/marker-comments-context"

const MARKER_UPDATED_EVENT = "primeflow:task-marker-updated"

export function TaskMarkerComment({ comment, taskId, className }: {
  comment?: string | null
  taskId?: string | null
  className?: string
}) {
  const comments = useMarkerComments()
  const [current, setCurrent] = React.useState(comment || "")
  const inboxItem = taskId ? comments?.byTask.get(taskId) : undefined

  React.useEffect(() => setCurrent(comment || ""), [comment])
  React.useEffect(() => { if (inboxItem) setCurrent(inboxItem.comment) }, [inboxItem])
  React.useEffect(() => {
    if (!taskId) return
    const sync = (event: Event) => {
      const detail = (event as CustomEvent<{ taskId: string; markerComment?: string | null }>).detail
      if (detail?.taskId === taskId) setCurrent(detail.markerComment || "")
    }
    window.addEventListener(MARKER_UPDATED_EVENT, sync)
    return () => window.removeEventListener(MARKER_UPDATED_EVENT, sync)
  }, [taskId])

  const text = current.trim()
  const isUnread = Boolean(inboxItem && !inboxItem.read_at && inboxItem.comment.trim() === text)
  if (!text) return null
  return (
    <span title={text} role={comments ? "button" : undefined} tabIndex={comments ? 0 : undefined}
      aria-label={`${isUnread ? "Koment i palexuar. " : ""}${text}`}
      onClick={(event) => { if (comments) { event.stopPropagation(); comments.openTask(taskId, text) } }}
      onKeyDown={(event) => { if (comments && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); event.stopPropagation(); comments.openTask(taskId, text) } }}
      style={{ maxWidth: "min(100%, 150px)", printColorAdjust: "exact", WebkitPrintColorAdjust: "exact" }}
      className={cn("mb-0.5 block w-fit cursor-pointer overflow-hidden text-ellipsis whitespace-nowrap rounded border border-blue-950 bg-[#0055FF] px-1.5 py-0.5 text-[11px] font-bold leading-snug text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700", isUnread && "ring-2 ring-blue-300 ring-offset-1", className)}>
      {isUnread && <strong className="mr-1 text-yellow-200 print:hidden">E RE ·</strong>}<strong>COM:</strong> {text}
    </span>
  )
}
