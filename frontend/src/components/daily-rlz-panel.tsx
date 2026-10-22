"use client"

import * as React from "react"
import { AlertTriangle, CheckCircle2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { useAuth } from "@/lib/auth"
import type { DailyReportResponse } from "@/lib/types"
import { cn } from "@/lib/utils"
import { DAILY_RLZ_REASONS } from "@/lib/daily-rlz-ui"

export { DAILY_RLZ_REASONS } from "@/lib/daily-rlz-ui"

const DAILY_RLZ_EMPTY_REASON = "__EMPTY__"
const DAILY_RLZ_VALIDATION_EVENT = "primeflow:daily-rlz-validation"
const pendingDailyRlzSaves = new Set<Promise<void>>()

function trackDailyRlzSave(operation: Promise<void>) {
  pendingDailyRlzSaves.add(operation)
  void operation.finally(() => pendingDailyRlzSaves.delete(operation))
  return operation
}

async function waitForPendingDailyRlzSaves() {
  while (pendingDailyRlzSaves.size) {
    await Promise.allSettled([...pendingDailyRlzSaves])
  }
}

export type DailyRlzTaskState = NonNullable<DailyReportResponse["tasks_today"][number]["rlz_daily_state"]>
type Blocker = { task_id: string; title: string; status: string; minimum_due_date?: string | null;
  issues: Array<{ code: string; message: string }> }

function blockerTitle(title: string) {
  return title.split(/\r?\n/).map(line => line.trim()).find(Boolean) || title
}

function publishValidationErrors(blockers: Blocker[]) {
  const errors = Object.fromEntries(blockers.map(blocker => [blocker.task_id, blocker.issues.map(issue => issue.code)]))
  window.dispatchEvent(new CustomEvent(DAILY_RLZ_VALIDATION_EVENT, { detail: errors }))
}

function useFailedValidation(taskId: string | null | undefined, code: string, stillMissing: boolean) {
  const [failed, setFailed] = React.useState(false)
  React.useEffect(() => { if (!stillMissing) queueMicrotask(() => setFailed(false)) }, [stillMissing])
  React.useEffect(() => {
    const listener = (event: Event) => {
      const errors = (event as CustomEvent<Record<string, string[]>>).detail || {}
      setFailed(Boolean(taskId && errors[taskId]?.includes(code)))
    }
    window.addEventListener(DAILY_RLZ_VALIDATION_EVENT, listener)
    return () => window.removeEventListener(DAILY_RLZ_VALIDATION_EVENT, listener)
  }, [taskId, code])
  return failed && stillMissing
}

export function dailyRlzStateByTask(report: DailyReportResponse | null) {
  const map = new Map<string, DailyRlzTaskState>()
  for (const item of [...(report?.tasks_today || []), ...(report?.tasks_overdue || [])]) {
    if (item.rlz_daily_state) map.set(item.task.id, item.rlz_daily_state)
  }
  for (const item of [...(report?.system_today || []), ...(report?.system_overdue || [])]) {
    if (item.rlz_daily_state) map.set(item.task.id, item.rlz_daily_state)
  }
  return map
}

export function DailyRlzReasonCell({ taskId, day, state, subjectUserId, onSaved }: {
  taskId?: string | null
  day: string
  state?: DailyRlzTaskState | null
  subjectUserId?: string
  onSaved: () => Promise<void> | void
}) {
  const { apiFetch } = useAuth()
  const [saving, setSaving] = React.useState(false)
  const failed = useFailedValidation(taskId, "REASON_MISSING", Boolean(state?.reason_missing))
  if (!taskId) return <span>—</span>
  if (!state?.reason_required) return <span className="text-slate-400">{state?.reason_label || "—"}</span>
  return <Select value={state?.reason_code || ""} disabled={!state?.is_editable || saving}
    onValueChange={async reasonCode => {
      setSaving(true)
      try {
        const response = await apiFetch(`/reports/daily-rlz-state/${taskId}`, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            day,
            user_id: subjectUserId,
            reason_code: reasonCode === DAILY_RLZ_EMPTY_REASON ? null : reasonCode,
            // Preserve whatever comment was already saved for this day — never wipe it
            // just because the reason dropdown changed.
            comment: state?.comment ?? null,
          }),
        })
        if (!response.ok) {
          const payload = await response.json().catch(() => ({}))
          throw new Error(payload?.detail?.message || payload?.detail || "Arsyeja nuk u ruajt")
        }
        await onSaved()
      } catch (error) { toast.error(error instanceof Error ? error.message : "Arsyeja nuk u ruajt") }
      finally { setSaving(false) }
    }}>
    <SelectTrigger title={state.reason_missing ? "Kërkon sqarim" : undefined} className={cn("h-7 min-w-[150px] bg-white text-[11px]", state.reason_missing && "border-amber-500 bg-amber-50", failed && "border-red-500 bg-red-50 ring-1 ring-red-300")}><SelectValue placeholder="Zgjidh arsyen"/></SelectTrigger>
    <SelectContent>
      <SelectItem value={DAILY_RLZ_EMPTY_REASON}>Empty</SelectItem>
      {DAILY_RLZ_REASONS.map(([code,label]) => <SelectItem key={code} value={code}>{label}</SelectItem>)}
    </SelectContent>
  </Select>
}

// Day-scoped comment field for the RLZ Daily Report table. Writes into the same
// TaskDailyRlzState row as DailyRlzReasonCell (via /reports/daily-rlz-state/{taskId}),
// so the comment is actually part of the daily RLZ evidence instead of overwriting the
// task's single, non-dated Task.comment field.
export function DailyRlzCommentField({ taskId, day, state, subjectUserId, onSaved }: {
  taskId?: string | null
  day: string
  state?: DailyRlzTaskState | null
  subjectUserId?: string
  onSaved: () => Promise<void> | void
}) {
  const { apiFetch } = useAuth()
  const [value, setValue] = React.useState(state?.comment ?? "")
  const [saving, setSaving] = React.useState(false)
  const failed = useFailedValidation(taskId, "COMMENT_MISSING", Boolean(state?.comment_missing))

  React.useEffect(() => { queueMicrotask(() => setValue(state?.comment ?? "")) }, [state?.comment, taskId])

  if (!taskId) return <span>—</span>

  const save = async () => {
    const trimmed = value.trim()
    if (trimmed === (state?.comment ?? "").trim()) return
    setSaving(true)
    try {
      const response = await apiFetch(`/reports/daily-rlz-state/${taskId}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          day,
          user_id: subjectUserId,
          reason_code: state?.reason_code || null,
          comment: trimmed || null,
        }),
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}))
        throw new Error(payload?.detail?.message || payload?.detail || "Komenti nuk u ruajt")
      }
      await onSaved()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Komenti nuk u ruajt")
      setValue(state?.comment ?? "")
    } finally { setSaving(false) }
  }

  if (!state?.comment_required) return <span className="text-slate-400">{state?.comment || "—"}</span>
  return <div className={cn("flex items-center gap-2 rounded px-1", state.comment_missing && "bg-amber-50", failed && "border border-red-400 bg-red-50 ring-1 ring-red-200")}>
    {state.comment_missing ? <span className="text-[10px] text-amber-700" title="Kërkon sqarim">!</span> : null}
    <input type="text" aria-label="Koment" className="h-4 w-full border-b border-slate-300 bg-transparent"
      value={value} disabled={!state?.is_editable || saving}
      onChange={e => setValue(e.target.value)}
      onBlur={() => void trackDailyRlzSave(save())} />
    <button type="button" className="print:hidden text-[10px] font-semibold uppercase text-slate-500 hover:text-slate-700 disabled:text-slate-300"
      disabled={!state?.is_editable || saving} onClick={() => void trackDailyRlzSave(save())}>
      {saving ? "Saving" : "Save"}
    </button>
  </div>
}

export function DailyRlzSaveButton({ day, report, onSaved }: {
  day: string
  report: DailyReportResponse | null
  onSaved: () => Promise<void> | void
}) {
  const { apiFetch, user } = useAuth()
  const [saving, setSaving] = React.useState(false)
  const [blockers, setBlockers] = React.useState<Blocker[]>([])
  const [closeOpen, setCloseOpen] = React.useState(false)
  const [dailyComment, setDailyComment] = React.useState("")
  const [prepared, setPrepared] = React.useState<null | {
    periodId: string
    resultId: string
    pulse: string | null
    metrics: Record<string, number | null>
  }>(null)
  const state = report?.rlz_close_state

  const prepareClose = async () => {
    if (!user?.id || !user.department_id) return
    setSaving(true)
    try {
      if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
      await waitForPendingDailyRlzSaves()
      const checkResponse = await apiFetch(`/reports/daily-rlz-compliance?day=${day}`)
      const check = await checkResponse.json().catch(() => ({}))
      if (!checkResponse.ok || check.blockers?.length) {
        const nextBlockers = check.blockers || check.detail?.blockers || []
        setBlockers(nextBlockers)
        publishValidationErrors(nextBlockers)
        return
      }
      const dailyResponse = await apiFetch(`/realization/daily/prepare?department_id=${user.department_id}&day=${day}`, {
        method: "POST",
      })
      if (!dailyResponse.ok) {
        const payload = await dailyResponse.json().catch(() => ({}))
        throw new Error(payload?.detail?.message || payload?.detail || "Realization Daily nuk është gati")
      }
      const daily = await dailyResponse.json()
      const person = daily.people?.find((entry: { user_id: string }) => entry.user_id === user.id)
      if (!person) throw new Error("Rezultati yt ditor i Realization nuk u gjet")
      const liveResponse = await apiFetch(`/realization/daily?department_id=${user.department_id}&day=${day}&user_id=${user.id}`)
      const livePayload = await liveResponse.json().catch(() => ({}))
      if (!liveResponse.ok) throw new Error(livePayload?.detail || "Përmbledhja ditore nuk u gjet")
      const livePerson = livePayload.live?.people?.find((entry: { user_id: string }) => entry.user_id === user.id)
      setPrepared({
        periodId: daily.period.id,
        resultId: person.id,
        pulse: person.facts_json?.pulse?.pulse || null,
        metrics: livePerson?.metrics || {},
      })
      setDailyComment("")
      setCloseOpen(true)
    } catch (error) { toast.error(error instanceof Error ? error.message : "Dita nuk mund të përgatitej") }
    finally { setSaving(false) }
  }

  const closeDay = async () => {
    if (!prepared || !dailyComment.trim()) return
    setSaving(true)
    try {
      const response = await apiFetch(`/realization/periods/${prepared.periodId}/results/${prepared.resultId}/close-day`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ daily_comment: dailyComment.trim(), confirmed_pulse: prepared.pulse }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        if (payload?.detail?.code === "RLZ_DAILY_REPORT_VALIDATION_FAILED") {
          const nextBlockers = payload.detail.blockers || []
          setBlockers(nextBlockers)
          publishValidationErrors(nextBlockers)
          return
        }
        throw new Error(payload?.detail?.message || payload?.detail || "Dita nuk u mbyll")
      }
      toast.success("Dita u mbyll")
      setCloseOpen(false)
      setPrepared(null)
      await onSaved()
    } catch (error) { toast.error(error instanceof Error ? error.message : "Dita nuk u mbyll") }
    finally { setSaving(false) }
  }

  const closeTime = state?.saved_at ? new Intl.DateTimeFormat("sq-AL", {
    timeZone: "Europe/Tirane", hour: "2-digit", minute: "2-digit",
  }).format(new Date(state.saved_at)) : null
  const actionLabel = state?.status === "STALE" ? "Rimbyll ditën" : state?.status === "REOPENED" ? "Mbyll përsëri ditën" : "Mbyll ditën"
  const metrics = prepared?.metrics || {}
  const realization = [
    ["PLAN", metrics.original_planned_count], ["KRYER", metrics.planned_completed_today_count],
    ["NË PROGRES", metrics.in_progress_count], ["SHTYRË", metrics.postponed_count],
    ["PA PROGRES", metrics.no_progress_count], ["EKSTRA", metrics.additional_completed_count],
  ] as const
  const deadlines = [
    ["Deadline sot", metrics.deadlines_today_count], ["Kryer", metrics.deadlines_completed_count],
    ["Shtyrë", metrics.deadlines_postponed_count], ["Hapur", metrics.deadlines_open_count],
  ] as const

  return <>
    <div className="ml-auto flex flex-wrap items-center justify-end gap-2 print:hidden">
      {state?.status === "SAVED" ? <span className="text-xs font-medium text-emerald-700"><CheckCircle2 className="mr-1 inline h-4 w-4"/>Dita e mbyllur{closeTime ? ` · ${closeTime}` : ""}</span> : null}
      {state?.status === "NOT_SAVED" ? <span className="text-xs font-medium text-slate-600">Dita e hapur</span> : null}
      {state?.status === "STALE" ? <span className="max-w-[310px] text-xs font-medium text-amber-700"><AlertTriangle className="mr-1 inline h-4 w-4"/>Ka ndryshime pas mbylljes<span className="block font-normal">Realizimi ka ndryshuar pas mbylljes së ditës.</span></span> : null}
      {state?.status === "REOPENED" ? <span className="text-xs font-medium text-blue-700">Dita është rihapur</span> : null}
      {state?.status === "CLOSED_EDIT_WINDOW" ? <span className="text-xs font-medium text-rose-700">Kjo ditë nuk është e hapur për mbyllje</span> : null}
      {state?.status !== "SAVED" && state?.status !== "CLOSED_EDIT_WINDOW" ? <Button type="button" className="h-8 bg-blue-600 px-3 text-xs hover:bg-blue-700" onClick={() => void prepareClose()}
        disabled={saving || !state?.is_editable}>
        {saving ? "Duke kontrolluar…" : actionLabel}
      </Button> : null}
    </div>
    <Dialog open={closeOpen} onOpenChange={open => { if (!saving) setCloseOpen(open) }}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>MBYLL DITËN</DialogTitle>
          <DialogDescription>{day.split("-").reverse().join(".")}<br/>Kontrollo realizimin para se ta mbyllësh ditën.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-2 rounded-xl border bg-slate-50 p-3 sm:grid-cols-6">
            {realization.map(([label, value]) => <div key={label}><p className="text-[9px] font-semibold text-slate-500">{label}</p><p className="text-lg font-bold tabular-nums">{value ?? 0}</p></div>)}
          </div>
          <div className="rounded-xl border border-blue-100 bg-blue-50/50 p-3">
            <div className="flex items-center justify-between"><span className="text-xs font-semibold text-blue-700">PLAN RLZ</span><strong>{metrics.raw_plan_realization == null ? "—" : `${metrics.raw_plan_realization}%`}</strong></div>
            <div className="mt-3 grid grid-cols-4 gap-2">{deadlines.map(([label, value]) => <div key={label}><p className="text-[10px] text-slate-500">{label}</p><b className="tabular-nums">{value ?? 0}</b></div>)}</div>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="daily-close-comment" className="text-xs font-semibold uppercase tracking-wide text-slate-700">Përmbledhja e ditës</label>
            <Textarea id="daily-close-comment" autoFocus rows={4} value={dailyComment} onChange={event => setDailyComment(event.target.value)} placeholder="Shkruaj shkurt çfarë duhet ditur për ditën e sotme..." />
          </div>
        </div>
        <DialogFooter><Button variant="outline" onClick={() => setCloseOpen(false)} disabled={saving}>Anulo</Button><Button className="bg-blue-600 hover:bg-blue-700" onClick={() => void closeDay()} disabled={saving || !dailyComment.trim()}>{saving ? "Duke mbyllur…" : "Mbyll ditën"}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
    <Dialog open={blockers.length > 0} onOpenChange={open => { if (!open) setBlockers([]) }}><DialogContent>
      <DialogHeader><DialogTitle>DITA NUK MUND TË MBYLLET</DialogTitle><DialogDescription>Plotëso pikat e mëposhtme para se ta mbyllësh ditën.</DialogDescription></DialogHeader>
      <div className="max-h-[55vh] space-y-3 overflow-y-auto">{blockers.map((blocker, index) => <div key={blocker.task_id} className="rounded border border-red-200 bg-red-50 p-3">
        <p className="font-semibold">{index + 1}. {blockerTitle(blocker.title)}</p><ul className="mt-1 list-disc pl-5 text-sm">{blocker.issues.map(issue => <li key={issue.code}>{issue.message}{issue.code === "DUE_DATE_NOT_MOVED" && blocker.minimum_due_date ? ` · Shtyje në ${blocker.minimum_due_date} ose më vonë` : ""}</li>)}</ul>
      </div>)}</div>
    </DialogContent></Dialog>
  </>
}
