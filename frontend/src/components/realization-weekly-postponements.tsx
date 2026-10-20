"use client"

import * as React from "react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { parseMarkedNoteContent } from "@/lib/note-markup"
import { DAILY_RLZ_REASONS } from "@/lib/daily-rlz-ui"
import type { RealizationPersonResult, RealizationTaskFact } from "@/lib/types"

export function weeklyPostponements(result: RealizationPersonResult) {
  const entries = new Map<string, { task: RealizationTaskFact; event: NonNullable<RealizationTaskFact["timeline"]>[number]; date: string }>()
  for (const day of [...(result.facts_json.daily_timeline || [])].sort((a, b) => a.date.localeCompare(b.date))) {
    for (const task of day.tasks || []) {
      const event = [...(task.timeline || [])].reverse().find(item => item.type === "POSTPONED" || item.type === "POSTPONED_AGAIN")
      if (!task.task_id || !event || !task.adjustment_status) continue
      entries.set(task.task_id, { task, event, date: day.date })
    }
  }
  return [...entries.values()]
}

export function RealizationWeeklyPostponements({ result, canEdit, busy, onDecide }: {
  result: RealizationPersonResult
  canEdit: boolean
  busy: boolean
  onDecide: (taskId: string, eventId: string, status: "APPROVED" | "REJECTED", comment: string) => Promise<boolean>
}) {
  const [decisions, setDecisions] = React.useState<Record<string, "APPROVED" | "REJECTED">>({})
  const [comments, setComments] = React.useState<Record<string, string>>({})
  const rows = weeklyPostponements(result)
  if (!rows.length) return null
  const dateLabel = (value: unknown) => typeof value === "string" ? value.slice(0, 10).split("-").reverse().join(".") : "—"
  return <details aria-label="Shtyrjet për aprovim">
    <summary className="cursor-pointer rounded py-1 text-sm font-semibold text-blue-700 focus-visible:outline-2 focus-visible:outline-blue-600">Shih shtyrjet ({rows.length})</summary>
    <div className="mt-2 overflow-x-auto rounded-lg border border-slate-200 bg-white">
      <table className="w-full min-w-[740px] table-fixed text-left text-xs">
        <colgroup><col /><col className="w-24" /><col className="w-24" /><col className="w-32" /><col className="w-20" /><col className="w-40" /></colgroup>
        <thead className="bg-slate-100 text-[10px] uppercase tracking-wide text-slate-600"><tr className="divide-x divide-slate-200"><th className="px-3 py-2.5" scope="col">Detyra</th><th className="px-2 py-2.5" scope="col">Afati i mëparshëm</th><th className="px-2 py-2.5" scope="col">Afati i ri</th><th className="px-2 py-2.5" scope="col">Statusi</th><th className="px-2 py-2.5" scope="col">Ruajtja</th><th className="px-2 py-2.5" scope="col">Komenti</th></tr></thead>
        <tbody>{rows.map(({ task, event, date }) => {
          const title = parseMarkedNoteContent(task.title).text.split(/\r?\n/).find(line => line.trim())?.trim() || "Pa titull"
          const status = decisions[event.id] || (task.adjustment_status === "REJECTED" ? "REJECTED" : "APPROVED")
          const comment = comments[event.id] ?? task.manager_decision?.comment ?? ""
          const dirty = status !== task.adjustment_status || comment.trim() !== (task.manager_decision?.comment || "")
          return <tr key={task.task_id} className="divide-x divide-slate-200 border-t border-slate-200 align-middle even:bg-slate-50">
            <th scope="row" className="px-3 py-1.5 text-left font-medium"><p className="truncate" title={title}>{title}</p><p className="mt-0.5 text-[10px] font-normal text-slate-500">Dita: {dateLabel(date)}</p>
              {event.metadata?.reason ? <p className="mt-1 break-words text-xs font-normal text-slate-600"><b>Arsyeja e shtyrjes:</b> {DAILY_RLZ_REASONS.find(([code]) => code === event.metadata?.reason)?.[1] || event.metadata.reason}</p> : null}
              {event.metadata?.comment ? <p className="mt-1 whitespace-pre-wrap break-words text-xs font-normal text-slate-600"><b>Komenti i shtyrjes:</b> {event.metadata.comment}</p> : null}
            </th>
            <td className="px-2 py-1.5 tabular-nums text-slate-600">{dateLabel(event.old_value)}</td>
            <td className="px-2 py-1.5 font-semibold tabular-nums text-slate-800">{dateLabel(event.new_value)}</td>
            <td className="px-2 py-1.5">
              {canEdit ? <select aria-label={`Aprovimi: ${title}`} value={status} disabled={busy} onChange={e => setDecisions(current => ({ ...current, [event.id]: e.target.value as "APPROVED" | "REJECTED" }))} className={`h-8 w-full rounded-md border px-2 text-xs font-medium ${status === "APPROVED" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-rose-200 bg-rose-50 text-rose-800"}`}>
                <option value="APPROVED">Aprovuar</option><option value="REJECTED">Jo aprovuar</option>
              </select> : <span className="text-xs">{task.adjustment_status === "APPROVED" ? "Aprovuar" : task.adjustment_status === "REJECTED" ? "Jo aprovuar" : "Pret aprovim"}</span>}
            </td>
            <td className="px-3 py-1.5">
              {canEdit && dirty ? <Button type="button" size="sm" className="h-7 px-3 text-xs" disabled={busy} onClick={() => void onDecide(task.task_id!, event.id, status, comment.trim())}>Ruaj</Button> : <p className="truncate text-[11px] text-slate-500" title={task.manager_decision?.decided_by_name || undefined}>{task.manager_decision?.decided_by_name || "—"}</p>}
            </td>
            <td className="px-2 py-1.5">
              {canEdit ? <Textarea rows={1} maxLength={2000} className="min-h-8 resize-y bg-white px-2 py-1.5 text-xs" aria-label={`Komenti për shtyrjen: ${title}`} placeholder="Koment (opsional)" value={comment} disabled={busy} onChange={e => setComments(current => ({ ...current, [event.id]: e.target.value }))} /> : <p className="break-words text-slate-600">{comment || "—"}</p>}
            </td>
          </tr>
        })}</tbody>
      </table>
    </div>
  </details>
}
