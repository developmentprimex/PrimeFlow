"use client"

import * as React from "react"
import { TASK_MARKER_OPTIONS, splitTaskMarkers, toggleTaskMarker } from "@/lib/task-markers"
import { TaskMarkerDisplay } from "@/components/task-marker-display"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog"
import { cn } from "@/lib/utils"

export function TaskMarkerSelect({ value, onValueChange, disabled, className, style, id, byGa, "aria-label": ariaLabel = "Simbolet (maksimumi 2)", title }: {
  value?: string | null
  onValueChange: (value: string) => void
  disabled?: boolean
  className?: string
  style?: React.CSSProperties
  id?: string
  "aria-label"?: string
  title?: string
  byGa?: boolean
}) {
  const [open, setOpen] = React.useState(false)
  const [draft, setDraft] = React.useState(value || "")
  const selected = splitTaskMarkers(draft)
  return <>
    <Button id={id} type="button" variant="outline" disabled={disabled} aria-label={ariaLabel} aria-haspopup="dialog" title={title}
      className={cn("w-full justify-between border-blue-300 bg-blue-50 font-black text-red-600", className)} style={style}
      onClick={() => { setDraft(value || ""); setOpen(true) }}>
      <TaskMarkerDisplay value={value} byGa={byGa} /><span aria-hidden="true" className="ml-1 text-xs text-blue-950">⌄</span>
    </Button>
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent onClick={event => event.stopPropagation()}>
        <DialogHeader><DialogTitle>Simbolet</DialogTitle><DialogDescription>Zgjidh deri në 2 simbole. Hiq njërin për ta zëvendësuar.</DialogDescription></DialogHeader>
        <div className="grid grid-cols-3 gap-2">
          {TASK_MARKER_OPTIONS.map(option => <label key={option.value} className={cn("flex items-center gap-2 rounded-md border p-3 font-black text-red-600", selected.length >= 2 && !selected.includes(option.value) && "opacity-40")}>
            <input type="checkbox" checked={selected.includes(option.value)} disabled={selected.length >= 2 && !selected.includes(option.value)}
              onChange={() => setDraft(toggleTaskMarker(draft, option.value) || "")} />{option.label}
          </label>)}
        </div>
        <DialogFooter><Button type="button" variant="outline" onClick={() => setDraft("")}>Hiqi të gjitha</Button><Button type="button" variant="outline" onClick={() => setOpen(false)}>Anulo</Button><Button type="button" onClick={() => { onValueChange(draft || "__none__"); setOpen(false) }}>Ruaj</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </>
}
