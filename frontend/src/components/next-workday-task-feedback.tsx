"use client"

import * as React from "react"
import { toast } from "sonner"
import { TaskPauseBadge } from "@/components/task-pause-field"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { useAuth } from "@/lib/auth"
import { getPlainMarkedText, renderMarkedNoteContent } from "@/lib/note-markup"

type Response = { continuation: "" | "PO" | "JO"; comment: string }
type Task = Response & {
  id: string
  title: string
  start_date: string | null
  due_date: string | null
  status: string
  slot: string | null
  is_system_task: boolean
  is_1h: boolean
  is_paused?: boolean
}
type Plan = { target_date: string; tasks: Task[] }

function FeedbackRow({ task, save, taskCells, readOnly }: {
  task: Task
  save: (change: Partial<Response>) => Promise<boolean>
  taskCells?: React.ReactNode
  readOnly: boolean
}) {
  const [comment, setComment] = React.useState(task.comment)
  const [savedComment, setSavedComment] = React.useState(task.comment)
  const [continuation, setContinuation] = React.useState(task.continuation)
  const [savingAnswer, setSavingAnswer] = React.useState(false)
  const [savingComment, setSavingComment] = React.useState(false)
  const title = getPlainMarkedText(task.title)
  return (
    <TableRow>
      {taskCells ?? <TableCell>{renderMarkedNoteContent(task.title)} {task.is_paused && <TaskPauseBadge />}</TableCell>}
      <TableCell className={continuation === "PO" ? "bg-green-100 text-green-800" : continuation === "JO" ? "bg-red-100 text-red-800" : ""}>
        <select
          aria-label={`Vazhdon? ${title}`}
          value={continuation}
          disabled={readOnly || savingAnswer}
          className="rounded border border-slate-400 bg-transparent px-2 py-1"
          onChange={async (event) => {
            const value = event.target.value as Response["continuation"]
            setSavingAnswer(true)
            const saved = await save({ continuation: value })
            if (saved) setContinuation(value)
            setSavingAnswer(false)
          }}
        >
          <option value="">–</option>
          <option value="PO" aria-label="Po">✓</option>
          <option value="JO" aria-label="Jo">X</option>
        </select>
      </TableCell>
      <TableCell className={taskCells ? "w-64 min-w-44" : "w-2/5 min-w-44"}>
        <Textarea
          aria-label={`Koment për ${title}`}
          value={comment}
          onChange={(event) => setComment(event.target.value)}
          onBlur={async () => {
            if (savingComment || comment === savedComment) return
            setSavingComment(true)
            const saved = await save({ comment })
            if (saved) setSavedComment(comment)
            setSavingComment(false)
          }}
          readOnly={readOnly || savingComment}
          rows={1}
          maxLength={4000}
          className="min-h-8"
        />
      </TableCell>
    </TableRow>
  )
}

export function NextWorkdayTaskFeedback({ view, personId, headerAction, taskHeaders, renderTaskCells, readOnly = false }: {
  view: "ga" | "finance"
  personId?: string
  headerAction?: React.ReactNode
  taskHeaders?: React.ReactNode
  renderTaskCells?: (task: Task, index: number) => React.ReactNode
  readOnly?: boolean
}) {
  const { apiFetch } = useAuth()
  const [plan, setPlan] = React.useState<Plan | null>(null)
  const [error, setError] = React.useState(false)
  const [reload, setReload] = React.useState(0)
  const endpoint = "/morning-report/next-workday"
  const query = new URLSearchParams({ view, ...(personId ? { person_id: personId } : {}) }).toString()
  React.useEffect(() => {
    const controller = new AbortController()
    async function load() {
      try {
        const response = await apiFetch(`${endpoint}?${query}`, { signal: controller.signal })
        if (!response.ok) throw new Error()
        const data: Plan = await response.json()
        if (!controller.signal.aborted) setPlan(data)
      } catch {
        if (!controller.signal.aborted) setError(true)
      }
    }
    void load()
    return () => controller.abort()
  }, [apiFetch, query, reload])

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-3">
        <CardTitle>Nesër {plan && <span className="ml-2 text-sm font-normal">{plan.target_date.split("-").reverse().join(".")}</span>}</CardTitle>
        <div className="flex flex-wrap items-center gap-2">
          {headerAction}
          <Button variant="outline" onClick={() => {
            setPlan(null)
            setError(false)
            setReload((current) => current + 1)
          }}>Rifresko</Button>
        </div>
      </CardHeader>
      <CardContent>
        {error ? <p role="alert">Plani nuk u ngarkua.</p> : !plan ? <p>Po ngarkohet…</p> : !plan.tasks.length ? (
          <p>Asnjë detyrë e planifikuar.</p>
        ) : (
          <Table
            className={view === "ga" && taskHeaders ? "all-tasks-table min-w-[820px] text-[10px] sm:min-w-[1020px]" : taskHeaders ? "min-w-[1460px]" : undefined}
            containerClassName={taskHeaders ? "rounded-lg border border-slate-200 bg-white" : undefined}
          >
            <TableHeader className={taskHeaders ? "bg-slate-50" : undefined}>
              <TableRow>
                {taskHeaders ?? <TableHead>Detyra</TableHead>}
                <TableHead className={view === "ga" ? "h-8 px-1.5 text-[10px] font-bold uppercase text-slate-600" : undefined}>Vazhdon?</TableHead>
                <TableHead className={view === "ga" ? "h-8 px-1.5 text-[10px] font-bold uppercase text-slate-600" : undefined}>Koment</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {plan.tasks.map((task, index) => (
                <FeedbackRow key={`${reload}:${plan.target_date}:${task.id}`} task={task} readOnly={readOnly} taskCells={renderTaskCells?.(task, index)} save={async (change) => {
                  try {
                    const response = await apiFetch(`${endpoint}/${task.id}?${query}`, {
                      method: "PATCH",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ ...change, target_date: plan.target_date }),
                    })
                    if (!response.ok) {
                      const detail = (await response.json()).detail
                      throw new Error(typeof detail === "string" ? detail : "")
                    }
                    return true
                  } catch (error) {
                    toast.error("Ndryshimi nuk u ruajt", { description: error instanceof Error ? error.message : undefined })
                    return false
                  }
                }} />
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
