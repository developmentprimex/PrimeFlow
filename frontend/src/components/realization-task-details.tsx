"use client"

import * as React from "react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { firstLineTitle } from "@/components/realization-deadline-tasks"
import { dailyRlzReasonLabel, DAILY_RLZ_REASONS } from "@/lib/daily-rlz-ui"
import { useAuth } from "@/lib/auth"
import type { DailyRealizationPerson, DailyRealizationTask, RealizationItem } from "@/lib/types"

const dateLabel = (value: unknown) => {
  if (typeof value === "string" && value.includes("T") && !Number.isNaN(Date.parse(value))) return new Intl.DateTimeFormat("sq-AL", { timeZone: "Europe/Tirane", day: "2-digit", month: "2-digit", year: "numeric" }).format(new Date(value))
  const match = typeof value === "string" ? value.match(/^(\d{4})-(\d{2})-(\d{2})/) : null
  return match ? `${match[3]}.${match[2]}.${match[1]}` : "—"
}

type Selection = { person: DailyRealizationPerson; item: RealizationItem }
export function RealizationTaskDetails({ selection, day, canConfirm, busy, onClose, onConfirm }: {
  selection: Selection | null; day: string; canConfirm: boolean; busy: boolean
  onClose: () => void; onConfirm: (confirmed: boolean) => void
}) {
  return <Dialog open={Boolean(selection)} onOpenChange={open => { if (!open && !busy) onClose() }}>
    <DialogContent className="sm:max-w-2xl" showCloseButton={!busy}>
      {selection ? <TaskDetails key={`${selection.person.user_id}:${selection.item.task_id}:${day}`} selection={selection} day={day} canConfirm={canConfirm} busy={busy} onClose={onClose} onConfirm={onConfirm} /> : null}
    </DialogContent>
  </Dialog>
}

function TaskDetails({ selection, day, canConfirm, busy, onClose, onConfirm }: {
  selection: Selection; day: string; canConfirm: boolean; busy: boolean
  onClose: () => void; onConfirm: (confirmed: boolean) => void
}) {
  const { apiFetch } = useAuth()
  const [data, setData] = React.useState<{ task: DailyRealizationTask; confirmation_item: RealizationItem | null } | null>(null)
  const [error, setError] = React.useState("")
  const [retry, setRetry] = React.useState(0)
  const { person, item } = selection
  React.useEffect(() => {
    const controller = new AbortController()
    const params = new URLSearchParams({ day, user_id: person.user_id, department_id: person.department_id })
    void (async () => {
      try {
        const response = await apiFetch(`/realization/daily/tasks/${item.task_id}/timeline?${params}`, { signal: controller.signal, cache: "no-store" })
        if (!response.ok) throw new Error("Detajet nuk u ngarkuan. Provo përsëri.")
        const payload = await response.json()
        if (!controller.signal.aborted) { setData(payload); setError("") }
      } catch (error) {
        if (!controller.signal.aborted) setError(error instanceof Error ? error.message : "Detajet nuk u ngarkuan")
      }
    })()
    return () => controller.abort()
  }, [apiFetch, day, person.user_id, person.department_id, item.task_id, retry])
  const task = data?.task
  const moves = task?.timeline.filter(event => event.type === "POSTPONED" || event.type === "POSTPONED_AGAIN") ?? []
  const lastMove = moves.at(-1)
  const confirmed = Boolean(data?.confirmation_item?.confirmation?.confirmed)
  const approved = Boolean(data?.confirmation_item?.approved)
  const stale = Boolean(data && data.confirmation_item?.confirmation_evidence_key !== item.confirmation_evidence_key)
  const eligible = Boolean(data?.confirmation_item?.unconfirmed_penalty && !approved && !stale)
  return <>
    <DialogHeader>
      <DialogTitle>{item.kind === "POSTPONED" ? "Detyra e shtyrë" : "Detajet e detyrës"}</DialogTitle>
      <DialogDescription>{person.user_name} · Realizimi i datës {dateLabel(day)}</DialogDescription>
    </DialogHeader>
    <p className="break-words text-sm font-semibold">{firstLineTitle(item.title)}</p>
    {!data && !error ? <p role="status" className="text-sm text-slate-500">Duke ngarkuar datat dhe komentin…</p> : null}
    {error ? <div role="alert" className="space-y-2 text-sm text-rose-700"><p>{error}</p><Button variant="outline" size="sm" onClick={() => setRetry(value => value + 1)}>Provo përsëri</Button></div> : null}
    {task ? <div className="space-y-4 text-sm">
      <div className="grid grid-cols-2 gap-3 rounded-lg border border-violet-200 bg-violet-50 p-3">
        <div><p className="text-xs font-semibold text-violet-700">Datat e mëparshme</p><p className="mt-2">Start: <b>{dateLabel(task.original_start_date)}</b></p><p>Due: <b>{dateLabel(moves[0]?.old_value ?? task.baseline_due_date)}</b></p></div>
        <div><p className="text-xs font-semibold text-violet-700">Datat pas ndryshimit</p><p className="mt-2">Start: <b>{dateLabel(task.start_date_on_day)}</b></p><p>Due: <b>{dateLabel(lastMove?.new_value ?? task.current_due_date)}</b></p></div>
      </div>
      {moves.map(event => <section key={event.id} className="space-y-1 rounded-lg border p-3">
        <p className="font-semibold">Shtyrë nga {dateLabel(event.old_value)} për {dateLabel(event.new_value)}</p>
        <p className="text-xs text-slate-500">{event.actor_name ? `Nga ${event.actor_name} · ` : ""}{event.timestamp ? new Intl.DateTimeFormat("sq-AL", { timeZone: "Europe/Tirane", dateStyle: "short", timeStyle: "short" }).format(new Date(event.timestamp)) : dateLabel(day)}</p>
        <p><b>Arsyeja:</b> {event.metadata?.reason ? DAILY_RLZ_REASONS.find(([code]) => code === event.metadata?.reason)?.[1] || event.metadata.reason : "Nuk është shënuar"}</p>
        <p className="whitespace-pre-wrap break-words"><b>Komenti i shtyrjes:</b> {event.metadata?.comment || "Nuk është shënuar"}</p>
      </section>)}
      {task.comment && task.comment !== lastMove?.metadata?.comment ? <p className="whitespace-pre-wrap break-words"><b>Komenti ditor:</b> {task.comment}</p> : null}
      {!moves.length ? <p><b>Arsyeja:</b> {dailyRlzReasonLabel(task.reason_code) || "Nuk është shënuar"}</p> : null}
      {confirmed || approved ? <p className="rounded bg-emerald-50 p-2 text-emerald-800">Konfirmuar · pa penalizim{data?.confirmation_item?.confirmation?.decided_by_name || task.manager_decision?.decided_by_name ? ` · ${data?.confirmation_item?.confirmation?.decided_by_name || task.manager_decision?.decided_by_name}` : ""}</p> : <p className="text-xs text-slate-500">Konfirmimi heq penalizimin e kësaj detyre për {dateLabel(day)}.</p>}
      {stale ? <p role="alert" className="text-amber-700">Detyra ka ndryshuar. Mbyll dritaren dhe rifresko tabelën para konfirmimit.</p> : null}
    </div> : null}
    <DialogFooter>
      <Button variant="outline" disabled={busy} onClick={onClose}>Mbyll</Button>
      {canConfirm && eligible ? <Button disabled={busy} onClick={() => onConfirm(!confirmed)}>{busy ? "Duke ruajtur…" : confirmed ? "Hiq konfirmimin" : "Konfirmo"}</Button> : null}
    </DialogFooter>
  </>
}
