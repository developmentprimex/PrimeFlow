import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  parsePxJavDate, pxJavAfterNextWeek, pxJavCommentOptions, pxJavCommentPlan,
  pxJavCommentWithPlan, type PxJavCommentOption,
} from "@/lib/px-jav-planning"
import { taskDateKey } from "@/lib/task-calendar-date"

export function PxJavCommentSelect({ comment, referenceDay, disabled, onSave }: {
  comment: string
  referenceDay: string
  disabled: boolean
  onSave: (value: string, reviewDate: string | null) => Promise<boolean>
}) {
  const [draft, setDraft] = useState<{ option: PxJavCommentOption; date: string } | null>(null)
  const current = pxJavCommentPlan(comment, referenceDay)
  const reviewDate = draft ? parsePxJavDate(draft.date, referenceDay) : current?.reviewDate

  async function apply(option: PxJavCommentOption | null, date: string | null) {
    const next = pxJavCommentWithPlan(comment, option, date, referenceDay)
    if (next === comment.trim() && !date) { setDraft(null); return }
    if (await onSave(next, date)) setDraft(null)
  }

  function choose(option: PxJavCommentOption | "clear") {
    if (option === "clear") { void apply(null, null); return }
    if (option === "custom-date") {
      setDraft({ option, date: current?.reviewDate ?? "" })
      return
    }
    const today = taskDateKey(new Date().toISOString()) ?? referenceDay
    const date = option === "year-end" ? `${today.slice(0, 4)}-12-31` :
      option === "after-next-week" ? pxJavAfterNextWeek(today) : null
    void apply(option, date)
  }

  return (
    <div className="mb-1 space-y-1">
      <select
        aria-label="Koment standard"
        className="h-7 w-full rounded-sm border border-slate-300 bg-white px-1.5 text-xs text-slate-900"
        value=""
        disabled={disabled}
        onChange={(event) => choose(event.target.value as PxJavCommentOption | "clear")}
      >
        <option value="" disabled>Koment standard…</option>
        {pxJavCommentOptions.map(({ id, label }) => <option key={id} value={id}>{label}</option>)}
        {current && <option value="clear">Hiq komentin standard</option>}
      </select>
      {current?.waiting && !draft && (
        <Button type="button" variant="ghost" size="sm" className="h-6 px-1 text-xs" disabled={disabled}
          onClick={() => setDraft({ option: current.option, date: current.reviewDate ?? "" })}>
          {current.reviewDate ? "Ndrysho rikontrollin" : "Cakto rikontrollin"}
        </Button>
      )}
      {draft && (
        <div className="flex flex-wrap gap-1">
          <Input
            aria-label="Data e rikontrollit"
            type="date"
            className="h-7 min-w-0 flex-1 rounded-sm px-1.5 text-xs"
            value={draft.date}
            disabled={disabled}
            onChange={(event) => setDraft({ ...draft, date: event.target.value })}
          />
          <Button type="button" size="sm" variant="outline" className="h-7 px-2 text-xs"
            disabled={disabled || !reviewDate} onClick={() => void apply(draft.option, reviewDate ?? null)}>
            Ruaj
          </Button>
          <Button type="button" size="sm" variant="ghost" className="h-7 px-2 text-xs"
            disabled={disabled} onClick={() => setDraft(null)}>
            Kthehu
          </Button>
        </div>
      )}
    </div>
  )
}
