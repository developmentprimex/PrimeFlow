"use client"

import * as React from "react"
import { Button } from "@/components/ui/button"
import { DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useAuth } from "@/lib/auth"
import type { GaNote, Task } from "@/lib/types"

const PxNotesWorkspace = React.lazy(() => import("@/components/px-notes-workspace"))
const TaskEditDialog = React.lazy(() => import("@/components/task-edit-dialog").then((module) => ({ default: module.TaskEditDialog })))

function LoadingEditor() {
  return <><DialogHeader className="shrink-0"><DialogTitle>Hap detyrën</DialogTitle></DialogHeader><div className="min-h-0 flex-1" role="status">Duke ngarkuar detyrën…</div></>
}

type EditorData = { task: Task; note: (GaNote & { source: "GA_KA" | "PX_JAV" }) | null }

export async function loadCommentTaskEditor(apiFetch: ReturnType<typeof useAuth>["apiFetch"], taskId: string): Promise<EditorData> {
  const response = await apiFetch(`/tasks/${taskId}`)
  if (!response?.ok) throw new Error("Detyra nuk u ngarkua. Provo përsëri.")
  const task = await response.json() as Task
  const noteId = task.plan_note_origin_id || task.ga_note_origin_id
  if (!noteId) return { task, note: null }
  const isPlan = Boolean(task.plan_note_origin_id)
  const noteResponse = await apiFetch(`/${isPlan ? "plan-notes" : "ga-notes"}/${noteId}`)
  if (!noteResponse?.ok) throw new Error("Shënimi i detyrës nuk u ngarkua. Provo përsëri.")
  const note = await noteResponse.json() as GaNote
  return { task, note: { ...note, source: isPlan ? "PX_JAV" : "GA_KA" } }
}

export function CommentTaskEditDialog({ taskId, onClose, onSaved }: {
  taskId: string
  onClose: () => void
  onSaved: () => void
}) {
  const { apiFetch } = useAuth()
  const [data, setData] = React.useState<EditorData | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [attempt, setAttempt] = React.useState(0)

  React.useEffect(() => {
    let cancelled = false
    setData(null)
    setError(null)
    void loadCommentTaskEditor(apiFetch, taskId).then((result) => {
      if (!cancelled) setData(result)
    }).catch((failure) => {
      if (!cancelled) setError(failure instanceof Error ? failure.message : "Detyra nuk u ngarkua.")
    })
    return () => { cancelled = true }
  }, [apiFetch, taskId, attempt])

  if (!data) return <>
    <DialogHeader className="shrink-0"><DialogTitle>Hap detyrën</DialogTitle></DialogHeader>
      {error ? <><p role="alert" className="text-sm text-red-700">{error}</p><Button variant="outline" onClick={() => setAttempt((value) => value + 1)}>Provo përsëri</Button></> : <p role="status">Duke ngarkuar detyrën…</p>}
  </>

  return <React.Suspense fallback={<LoadingEditor />}>
    {data.note
      ? <PxNotesWorkspace key={`${data.note.source}:${data.note.id}`} editorNote={data.note} onEditorClose={onClose} onEditorSaved={onSaved} embeddedEditor />
      : <TaskEditDialog task={data.task} open onOpenChange={(open) => { if (!open) onClose() }} onUpdated={onSaved} showDescriptionField embedded />}
  </React.Suspense>
}
