"use client"

import * as React from "react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { DAILY_RLZ_REASONS } from "@/lib/daily-rlz-ui"
import type { PostponementDetails, PostponementExplanation } from "@/lib/task-postponement"

type Request = { id: number; details: PostponementDetails; finish: (answer: PostponementExplanation | null) => void }

export function TaskPostponementForm({ details, onFinish }: {
  details: PostponementDetails; onFinish: Request["finish"]
}) {
  const [reason, setReason] = React.useState("")
  const [comment, setComment] = React.useState("")
  const ready = !!reason && !!comment.trim()
  const date = (value: string) => value.split("-").reverse().join(".")
  return <Dialog open onOpenChange={(open) => { if (!open) onFinish(null) }}>
    <DialogContent className="sm:max-w-lg" onInteractOutside={(event) => event.preventDefault()}>
      <DialogHeader>
        <DialogTitle>Arsyeja e shtyrjes</DialogTitle>
        <DialogDescription>Për ta shtyrë detyrën, zgjidh arsyen dhe plotëso komentin.</DialogDescription>
      </DialogHeader>
      <form className="space-y-4" onSubmit={(event) => {
        event.preventDefault()
        if (ready) onFinish({ postponement_reason_code: reason, postponement_comment: comment.trim() })
      }}>
        <p className="max-h-28 overflow-y-auto whitespace-pre-wrap break-words text-sm font-medium">{details.task_title}</p>
        <ul className="text-sm text-muted-foreground">{details.changes.map((change) => <li key={change.field}>
          {change.field === "start_date" ? "Start Date" : "Due Date"}: {date(change.from)} → {date(change.to)}
        </li>)}</ul>
        <div className="space-y-2">
          <Label htmlFor="postponement-reason">Arsyeja *</Label>
          <select id="postponement-reason" required value={reason} onChange={(event) => setReason(event.target.value)}
            className="h-10 w-full rounded-md border bg-background px-3 text-sm">
            <option value="">Zgjidh arsyen</option>
            {DAILY_RLZ_REASONS.map(([code, title]) => <option key={code} value={code}>{title}</option>)}
          </select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="postponement-comment">Komenti *</Label>
          <Textarea id="postponement-comment" required rows={4} maxLength={10000} value={comment}
            placeholder="Shpjego pse po shtyhet detyra." onChange={(event) => setComment(event.target.value)} />
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => onFinish(null)}>Anulo</Button>
          <Button type="submit" disabled={!ready}>Ruaj shtyrjen</Button>
        </div>
      </form>
    </DialogContent>
  </Dialog>
}

export function useTaskPostponement(sessionId: string | null) {
  const session = React.useMemo(() => ({ id: sessionId }), [sessionId])
  const currentSession = React.useRef<typeof session | null>(session)
  const queue = React.useRef<Request[]>([])
  const sequence = React.useRef(0)
  const [active, setActive] = React.useState<Request | null>(null)
  const requestExplanation = React.useCallback((details: PostponementDetails, signal?: AbortSignal | null) =>
    new Promise<PostponementExplanation | null>((resolve) => {
      if (signal?.aborted || !session.id || currentSession.current !== session) { resolve(null); return }
      const request: Request = { id: ++sequence.current, details, finish: (answer) => {
        const index = queue.current.indexOf(request)
        if (index < 0) return
        queue.current.splice(index, 1)
        signal?.removeEventListener("abort", abort)
        resolve(currentSession.current === session ? answer : null)
        setActive(queue.current[0] || null)
      } }
      const abort = () => request.finish(null)
      signal?.addEventListener("abort", abort, { once: true })
      queue.current.push(request)
      setActive(queue.current[0])
    }), [session])
  React.useLayoutEffect(() => {
    currentSession.current = session
    return () => {
      currentSession.current = null
      for (const request of [...queue.current]) request.finish(null)
    }
  }, [session])
  return { requestExplanation, postponementDialog: active
    ? <TaskPostponementForm key={active.id} details={active.details} onFinish={active.finish} /> : null }
}
