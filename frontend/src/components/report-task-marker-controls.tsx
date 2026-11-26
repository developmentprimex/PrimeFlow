"use client"

import * as React from "react"
import { toast } from "sonner"
import { useAuth } from "@/lib/auth"
import type { Task } from "@/lib/types"
import { TaskOneHMarkerEditor } from "@/components/task-one-h-marker-editor"

/** Attach controls to identified live task cards, never to free text or Notes. */
export function ReportTaskMarkerControls({ frame, html, onSaved }: {
  frame: React.RefObject<HTMLIFrameElement | null>
  html?: string
  onSaved: () => void
}) {
  const { apiFetch } = useAuth()
  const [task, setTask] = React.useState<Task | null>(null)
  const editor = React.useRef<HTMLDivElement>(null)
  React.useEffect(() => {
    if (task) editor.current?.querySelector<HTMLButtonElement>('button[aria-haspopup="dialog"]')?.click()
  }, [task])
  React.useEffect(() => {
    const iframe = frame.current
    if (!iframe) return
    const install = () => {
      const document = iframe.contentDocument
      if (!document) return
      if (!document.querySelector('[data-report-marker-print-style]')) {
        const style = document.createElement("style")
        style.dataset.reportMarkerPrintStyle = "true"
        style.textContent = "@media print { [data-edit-report-symbols] { display:none !important; } }"
        document.head.append(style)
      }
      document.querySelectorAll<HTMLElement>('[data-report-task="true"][data-task-id]').forEach(card => {
        const taskId = card.dataset.taskId
        if (!taskId || !/^[0-9a-f-]{36}$/i.test(taskId) || card.querySelector('[data-edit-report-symbols]')) return
        const button = document.createElement("button")
        button.type = "button"
        button.dataset.editReportSymbols = taskId
        button.textContent = "Simbolet"
        button.setAttribute("aria-label", "Edit task symbols")
        button.style.cssText = "display:inline-flex;margin:6px 4px;padding:3px 8px;border:1px solid #93c5fd;border-radius:5px;background:#eff6ff;color:#1e3a8a;font:bold 12px Arial;cursor:pointer"
        button.onclick = async event => {
          event.preventDefault(); event.stopPropagation(); button.disabled = true
          try {
            const response = await apiFetch(`/tasks/${taskId}`)
            if (!response.ok) throw new Error("Could not load the current task")
            setTask(await response.json() as Task)
          } catch {
            toast.error("Could not load task symbols")
          } finally { button.disabled = false }
        }
        const host = card.matches("table, tr")
          ? card.querySelector("[data-report-marker-host]") ?? card.querySelector("td:last-child")
          : card
        host?.append(button)
      })
    }
    install()
    iframe.addEventListener("load", install)
    return () => iframe.removeEventListener("load", install)
  }, [apiFetch, frame, html])
  return <div ref={editor} hidden>
    {task ? <TaskOneHMarkerEditor key={task.id} taskId={task.id} marker={task.one_h_marker}
      markerByGa={task.one_h_marker_by_ga} markerComment={task.one_h_marker_comment} onSaved={onSaved} /> : null}
  </div>
}
