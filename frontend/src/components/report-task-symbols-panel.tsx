"use client"

import * as React from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useAuth } from "@/lib/auth"
import { updateTaskMarkersInTree, useTaskMarkerUpdates } from "@/lib/task-marker-updates"
import type { Task } from "@/lib/types"
import { TaskOneHMarkerEditor } from "@/components/task-one-h-marker-editor"

/** M1/M2/M3 text rows have no task IDs; edit explicit live tasks alongside them. */
export function ReportTaskSymbolsPanel({ reportDate }: { reportDate: string }) {
  const { apiFetch } = useAuth()
  const [open, setOpen] = React.useState(false)
  const [tasks, setTasks] = React.useState<Task[]>([])
  const [search, setSearch] = React.useState("")
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState("")
  useTaskMarkerUpdates(update => setTasks(current => updateTaskMarkersInTree(current, update)))
  const load = async () => {
    setLoading(true); setError("")
    try {
      const params = new URLSearchParams({ include_done: "true", include_all_departments: "true", window_from: reportDate, window_to: reportDate })
      const response = await apiFetch(`/tasks?${params}`)
      if (!response.ok) throw new Error("Could not load tasks")
      const data = await response.json()
      if (!Array.isArray(data)) throw new Error("Unexpected task response")
      setTasks(data)
    } catch { setError("Detyrat nuk u ngarkuan. Provo përsëri.") }
    finally { setLoading(false) }
  }
  const visible = tasks.filter(task => [task.title, ...(task.assignees || []).map(person => person.full_name || person.email)]
    .join(" ").toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))
  return <section className="rounded-lg border bg-white p-3 print:hidden">
    <Button type="button" variant="outline" aria-expanded={open} onClick={() => {
      setOpen(value => !value)
      if (!open) void load()
    }}>Simbolet e detyrave</Button>
    {open ? <div className="mt-3 space-y-3">
      <p className="text-sm text-muted-foreground">Detyrat aktuale për {reportDate}. Simbolet ruhen te detyra e personit. Më pas rifresko raportin që të përditësohet edhe teksti i tij.</p>
      <Input aria-label="Kërko detyrë ose person" placeholder="Kërko detyrë ose person..." value={search} onChange={event => setSearch(event.target.value)} />
      {loading ? <p role="status">Duke ngarkuar detyrat...</p> : error ? <p role="alert">{error}</p> :
        <div className="max-h-96 space-y-2 overflow-y-auto">
          {visible.length ? visible.map(task => <div key={task.id} className="flex items-center gap-3 rounded-md border p-2">
            <TaskOneHMarkerEditor taskId={task.id} marker={task.one_h_marker} markerByGa={task.one_h_marker_by_ga} markerComment={task.one_h_marker_comment} />
            <div className="min-w-0"><p className="whitespace-pre-wrap text-sm">{task.title}</p>
              <p className="text-xs text-muted-foreground">{task.assignees?.map(person => person.full_name || person.email).join(", ")}</p>
            </div>
          </div>) : <p>Nuk ka detyra për këtë përzgjedhje.</p>}
        </div>}
    </div> : null}
  </section>
}
