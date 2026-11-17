"use client"

import * as React from "react"
import { toast } from "sonner"
import { useAuth } from "@/lib/auth"
import type { Task } from "@/lib/types"
import { TASK_MARKER_UPDATED_EVENT } from "@/lib/task-marker-updates"
import { taskMarkerLabel } from "@/lib/task-markers"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { TaskMarkerSelect } from "@/components/task-marker-select"
import { TaskMarkerDisplay } from "@/components/task-marker-display"
import { TaskOneHMarkerEditor } from "@/components/task-one-h-marker-editor"

type Target = {
  taskId: string
  person: string
  marker?: Task["one_h_marker"]
  markerByGa?: boolean
  markerComment?: string | null
}

/** One card control; individual records remain independently editable inside. */
export function TaskGroupMarkerEditor({ targets }: { targets: Target[] }) {
  const { apiFetch } = useAuth()
  const [open, setOpen] = React.useState(false)
  const [individual, setIndividual] = React.useState(false)
  const [draft, setDraft] = React.useState("")
  const [changed, setChanged] = React.useState(false)
  const [saving, setSaving] = React.useState(false)
  const [error, setError] = React.useState("")
  const unique = Array.from(new Map(targets.map(target => [target.taskId, target])).values())
  const same = unique.every(target => (target.marker || "") === (unique[0]?.marker || ""))
  const summary = unique.map(target => `${target.person}: ${taskMarkerLabel(target.marker, target.markerByGa) || "—"}`).join(" · ")

  const saveAll = async () => {
    if (saving || !changed) return
    setSaving(true)
    setError("")
    try {
      // Load every record first: missing data must never erase a saved comment.
      const current = await Promise.all(unique.map(async target => {
        const response = await apiFetch(`/tasks/${target.taskId}`)
        if (!response.ok) throw new Error(`Nuk u ngarkua detyra për ${target.person}.`)
        return { target, task: await response.json() as Task }
      }))
      const failed: string[] = []
      for (const { target, task } of current) {
        try {
          const response = await apiFetch(`/tasks/${target.taskId}/one-h-marker`, {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ one_h_marker: draft || null, one_h_marker_comment: task.one_h_marker_comment || null }),
          })
          if (!response.ok) throw new Error("Save failed")
          const saved = await response.json() as Task
          window.dispatchEvent(new CustomEvent(TASK_MARKER_UPDATED_EVENT, { detail: {
            taskId: target.taskId, marker: saved.one_h_marker ?? null,
            markerByGa: Boolean(saved.one_h_marker_by_ga), markerComment: saved.one_h_marker_comment ?? null,
          } }))
        } catch { failed.push(target.person) }
      }
      if (failed.length) {
        setError(`Nuk u ruajt për: ${failed.join(", ")}. ${failed.length < current.length ? "Ndryshimet e tjera u ruajtën. " : ""}Provo përsëri.`)
      } else {
        toast.success("Simbolet u ruajtën për të gjithë")
        setOpen(false)
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Detyrat nuk u ngarkuan. Provo përsëri.")
    } finally { setSaving(false) }
  }

  return <span data-task-marker-group={unique.map(target => target.taskId).join(",")}
    onPointerDown={event => event.stopPropagation()} onClick={event => event.stopPropagation()}>
    <span className="hidden print:inline">{unique.map(target => `${target.person}: ${taskMarkerLabel(target.marker, target.markerByGa) || "—"}`).join("; ")}</span>
    <Button type="button" variant="outline" aria-label="Simbolet e grupit" aria-haspopup="dialog"
      title={`${summary}\nNdrysho simbolet për të gjithë ose sipas personit`}
      className={`h-6 min-w-[50px] px-1.5 py-0 text-[10px] font-black print:hidden ${same ? "border-blue-300 bg-blue-50 text-red-600" : "border-slate-300 bg-slate-50 text-slate-600"}`}
      onClick={event => {
        event.preventDefault()
        setDraft(same ? unique[0]?.marker || "" : "")
        setIndividual(false); setChanged(false); setError(""); setOpen(true)
      }}>{same ? <TaskMarkerDisplay value={unique[0]?.marker} byGa={unique.every(target => target.markerByGa)} /> : <span aria-hidden="true">⋯</span>}<span aria-hidden="true" className="ml-1 text-blue-950">⌄</span></Button>
    <Dialog open={open} onOpenChange={value => { if (!saving) setOpen(value) }}>
      <DialogContent onClick={event => event.stopPropagation()}>
        <DialogHeader>
          <DialogTitle>Simbolet e grupit</DialogTitle>
          <DialogDescription>Zbato të njëjtat simbole për të gjithë, ose ndryshoji sipas personit.</DialogDescription>
        </DialogHeader>
        <div className="flex gap-2" role="group" aria-label="Mënyra e ndryshimit">
          <Button type="button" variant={individual ? "outline" : "default"} aria-pressed={!individual} disabled={saving} onClick={() => setIndividual(false)}>Për të gjithë</Button>
          <Button type="button" variant={individual ? "default" : "outline"} aria-pressed={individual} disabled={saving} onClick={() => setIndividual(true)}>Sipas personit</Button>
        </div>
        {individual ? <div className="max-h-80 space-y-3 overflow-y-auto">
          {unique.map(target => <div key={target.taskId} className="flex items-center justify-between gap-3 rounded border p-3">
            <span className="text-sm font-medium">{target.person}</span>
            <TaskOneHMarkerEditor taskId={target.taskId} marker={target.marker} markerByGa={target.markerByGa} markerComment={target.markerComment} />
          </div>)}
        </div> : <div className="space-y-3">
          <p className="text-sm">{unique.map(target => target.person).join(", ")}</p>
          {!same ? <p className="text-sm text-muted-foreground">Aktualisht kanë simbole të ndryshme. Zgjedhja e re zbatohet për të gjithë.</p> : null}
          <TaskMarkerSelect value={draft} disabled={saving} aria-label="Simbolet për të gjithë" onValueChange={value => { setDraft(value === "__none__" ? "" : value); setChanged(true) }} />
          <p className="text-xs text-muted-foreground">Komentet ekzistuese të secilit ruhen.</p>
        </div>}
        {error ? <p role="alert" className="text-sm text-red-700">{error}</p> : null}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" disabled={saving} onClick={() => setOpen(false)}>{individual ? "Mbyll" : "Anulo"}</Button>
          {!individual ? <Button type="button" disabled={saving || !changed} onClick={() => void saveAll()}>{saving ? "Duke ruajtur..." : "Ruaj për të gjithë"}</Button> : null}
        </div>
      </DialogContent>
    </Dialog>
  </span>
}
