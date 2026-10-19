"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

const MARKER_UPDATED_EVENT = "primeflow:task-marker-updated"

export function TaskMarkerComment({ comment, taskId, className }: {
  comment?: string | null
  taskId?: string | null
  className?: string
}) {
  const [current, setCurrent] = React.useState(comment || "")

  React.useEffect(() => setCurrent(comment || ""), [comment])
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
  if (!text) return null
  return (
    <span title={text} style={{ maxWidth: "min(100%, 150px)", printColorAdjust: "exact", WebkitPrintColorAdjust: "exact" }} className={cn("mb-0.5 block w-fit overflow-hidden text-ellipsis whitespace-nowrap rounded border border-blue-950 bg-[#0055FF] px-1.5 py-0.5 text-[11px] font-bold leading-snug text-white", className)}>
      <strong>COM:</strong> {text}
    </span>
  )
}
