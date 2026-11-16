import { useEffect } from "react"
import type { Task } from "@/lib/types"

export const TASK_MARKER_UPDATED_EVENT = "primeflow:task-marker-updated"
export type TaskMarkerUpdate = {
  taskId: string
  marker: Task["one_h_marker"]
  markerByGa: boolean
  markerComment?: string | null
}

/** Update live JSON data without replacing unrelated edits or historical snapshots. */
export function updateTaskMarkersInTree<T>(value: T, update: TaskMarkerUpdate): T {
  if (!value || typeof value !== "object") return value
  if (Array.isArray(value)) {
    const next = value.map(item => updateTaskMarkersInTree(item, update))
    return (next.some((item, index) => item !== value[index]) ? next : value) as T
  }
  const row = value as Record<string, unknown>
  let next = row
  if (row.id === update.taskId || row.task_id === update.taskId || row.taskId === update.taskId) {
    next = row.taskId === update.taskId
      ? { ...row, oneHMarker: update.marker, oneHMarkerByGa: update.markerByGa, oneHMarkerComment: update.markerComment ?? null }
      : { ...row, one_h_marker: update.marker, one_h_marker_by_ga: update.markerByGa, one_h_marker_comment: update.markerComment ?? null }
  }
  for (const [key, item] of Object.entries(row)) {
    if (!item || typeof item !== "object") continue
    const updated = updateTaskMarkersInTree(item, update)
    if (updated !== item) {
      if (next === row) next = { ...row }
      next[key] = updated
    }
  }
  return next as T
}

export function useTaskMarkerUpdates(onUpdate: (update: TaskMarkerUpdate) => void) {
  useEffect(() => {
    const listener = (event: Event) => {
      const update = (event as CustomEvent<TaskMarkerUpdate>).detail
      if (update?.taskId) onUpdate(update)
    }
    window.addEventListener(TASK_MARKER_UPDATED_EVENT, listener)
    return () => window.removeEventListener(TASK_MARKER_UPDATED_EVENT, listener)
  }, [onUpdate])
}
