"use client"

import * as React from "react"
import { taskMarkerLabel, TASK_MARKER_OPTIONS } from "@/lib/task-markers"
import type { Task } from "@/lib/types"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"

export function taskOneHMarkerLabel(marker?: Task["one_h_marker"], markerByGa = false) {
  const symbol = taskMarkerLabel(marker)
  if (!symbol) return null
  return markerByGa ? `(${symbol})` : symbol
}

export function TaskOneHMarkerFromLabel({ label }: { label?: string | null }) {
  const markerByGa = Boolean(label?.startsWith("(") && label.endsWith(")"))
  const symbol = markerByGa ? label?.slice(1, -1) : label
  const marker = symbol?.split(" + ").map(part => TASK_MARKER_OPTIONS.find(option => option.label === part)?.value).filter(Boolean).join(",") as Task["one_h_marker"]
  return marker ? <TaskOneHMarker marker={marker} markerByGa={markerByGa} /> : <>{label || "—"}</>
}

export function TaskOneHMarker({ marker, markerByGa, comment, className }: {
  marker?: Task["one_h_marker"]
  markerByGa?: boolean
  comment?: string | null
  className?: string
}) {
  const [open, setOpen] = React.useState(false)
  const shownSymbol = taskOneHMarkerLabel(marker, markerByGa)
  if (!shownSymbol) return null
  return (
    <>
      <button type="button" className={cn("inline-flex min-h-6 min-w-6 shrink-0 items-center justify-center rounded-md border border-blue-300 bg-blue-50 px-1.5 text-base font-black leading-none text-red-600 [text-shadow:0_0_0_currentColor]", className)} title={comment?.trim() || `Task symbol: ${shownSymbol}`} aria-label={`Task symbol ${shownSymbol}${comment ? ". View comment" : ""}`} onClick={(event) => { if (comment?.trim()) { event.stopPropagation(); setOpen(true) } }}>
        {shownSymbol}
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent onClick={(event) => event.stopPropagation()}>
          <DialogHeader><DialogTitle>Symbol comment</DialogTitle><DialogDescription>Comment attached to {shownSymbol}.</DialogDescription></DialogHeader>
          <div className="whitespace-pre-wrap rounded-md border bg-slate-50 p-3 text-sm">{comment}</div>
          <DialogFooter><Button type="button" variant="outline" onClick={() => void navigator.clipboard.writeText(comment || "")}>Copy</Button><Button type="button" onClick={() => setOpen(false)}>Close</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
