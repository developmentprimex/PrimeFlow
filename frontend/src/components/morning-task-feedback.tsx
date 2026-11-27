"use client"

import * as React from "react"
import { ReportSectionPreview, reportSectionPreviewText } from "@/components/report-section-editor"
import { Textarea } from "@/components/ui/textarea"

export const TASK_FEEDBACK_SECTION = "GA/HV/DV TASKS"
export type TaskFeedback = { continuation: "" | "PO" | "JO"; comment: string }
export type TaskFeedbackRow = TaskFeedback & { key: string; title: string; owners: string }
export type TaskFeedbackRows = Record<string, TaskFeedbackRow[]>

function InlineTaskComment({ row, onSave }: {
  row: TaskFeedbackRow
  onSave: (comment: string) => void
}) {
  const [comment, setComment] = React.useState<string | null>(null)
  React.useEffect(() => {
    setComment((current) => current === row.comment ? null : current)
  }, [row.comment])
  return (
    <Textarea
      aria-label={`Koment për ${row.title} (${row.owners})`}
      value={comment ?? row.comment}
      onChange={(event) => setComment(event.target.value)}
      onBlur={() => {
        if (comment !== null && comment !== row.comment) onSave(comment)
      }}
      rows={1}
      maxLength={4000}
      className="min-h-6 min-w-36 resize-y border-slate-400 bg-white/60 px-1 py-0.5 text-xs print:border-0"
    />
  )
}

export function MorningTaskFeedback({ body, rows, onSave }: {
  body: string
  rows?: TaskFeedbackRows
  onSave?: (row: TaskFeedbackRow, edit: Partial<TaskFeedback>) => void
}) {
  return <ReportSectionPreview
    body={reportSectionPreviewText(body)}
    compactBzColumn
    renderLine={onSave ? (line) => {
      const plans = rows?.plan ?? []
      const row = plans.find((plan) =>
        line.startsWith(`${plan.title} (${plan.owners}):`),
      )
      if (!row) {
        return plans.some((plan) =>
          line.trim() === `${plan.owners} TASKS:` &&
          body.includes(`${plan.title} (${plan.owners}):`),
        ) ? false : null
      }
      return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b bg-slate-50 px-3 py-2">
          <span className="shrink-0 font-semibold">{row.owners} TASKS:</span>
          <label className="flex items-center gap-2 font-semibold">
            {row.title} <span className="sr-only">({row.owners})</span>
            <select
              className={`rounded border px-2 py-0.5 ${
                row.continuation === "PO"
                  ? "border-red-300 bg-red-100 font-semibold text-red-800"
                  : row.continuation === "JO"
                    ? "border-green-300 bg-green-100 font-semibold text-green-800"
                    : "border-slate-400 bg-background font-normal"
              }`}
              value={row.continuation}
              onChange={(event) => onSave(row, { continuation: event.target.value as TaskFeedback["continuation"] })}
            >
              <option value="">–</option>
              <option value="PO">Po</option>
              <option value="JO">Jo</option>
            </select>
          </label>
          <div className="min-w-44 flex-1">
            <InlineTaskComment key={row.key} row={row} onSave={(comment) => onSave(row, { comment })} />
          </div>
        </div>
      )
    } : undefined}
    renderCell={onSave ? (label, number, header) => {
      if (!/^[1-9]\d*$/.test(number)) return null
      const row = rows?.[label.trim().replace(/:$/, "").toUpperCase()]?.[Number(number) - 1]
      if (!row) return null
      if (header === "KOMENT") {
        return <InlineTaskComment key={row.key} row={row} onSave={(comment) => onSave(row, { comment })} />
      }
      if (header !== "VAZHDON?") return null
      return (
        <select
          aria-label={`Vazhdon? ${row.title} (${row.owners})`}
          className="w-full rounded border border-slate-400 bg-transparent px-1"
          value={row.continuation}
          onChange={(event) => onSave(row, { continuation: event.target.value as TaskFeedback["continuation"] })}
        >
          <option value="">–</option>
          <option value="PO" aria-label="Po">✓</option>
          <option value="JO" aria-label="Jo">X</option>
        </select>
      )
    } : undefined}
  />
}
