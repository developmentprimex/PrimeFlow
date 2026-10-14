"use client"

import * as React from "react"
import type { RealizationPersonResult } from "@/lib/types"
import { weeklyChecklistLabels } from "@/lib/realization-checklist"
import { parseMarkedNoteContent } from "@/lib/note-markup"

type Props = { result: RealizationPersonResult; compact?: boolean }
const firstTaskLine = (title: string) => parseMarkedNoteContent(title).text.split(/\r?\n/).find(line => line.trim())?.trim() || "Pa titull"
const weekdays = ["Di", "Hën", "Mar", "Mër", "Enj", "Pre", "Sht"]
const weekdayNames = ["E diel", "E hënë", "E martë", "E mërkurë", "E enjte", "E premte", "E shtunë"]
const taskStates: Record<string, string> = {
  COMPLETED: "Kryer", COMPLETED_ON_TIME: "Kryer në kohë", COMPLETED_LATE: "Kryer me vonesë",
  COMPLETED_EARLY: "Kryer para afatit", REALIZED_AS_PLANNED: "Kryer sipas planit",
  ADDITIONAL_COMPLETED: "Ekstra e kryer", IN_PROGRESS: "Në progres", ADDITIONAL_IN_PROGRESS: "Ekstra në progres",
  POSTPONED: "Shtyrë", POSTPONED_APPROVED: "Shtyrë me konfirmim", POSTPONED_UNAPPROVED: "Shtyrë pa konfirmim",
  NO_PROGRESS: "Pa progres", PENDING: "Në pritje", TODO: "Pa filluar",
}

function taskStatusColor(classification: string) {
  if (classification === "NO_PROGRESS") return "border-pink-200 bg-pink-100 text-pink-800"
  if (classification.startsWith("POSTPONED")) return "border-violet-200 bg-violet-100 text-violet-800"
  if (classification === "IN_PROGRESS" || classification === "ADDITIONAL_IN_PROGRESS") return "border-blue-200 bg-blue-100 text-blue-800"
  if (classification === "PENDING" || classification === "TODO") return "border-amber-200 bg-amber-100 text-amber-800"
  if (classification.startsWith("COMPLETED") || classification === "REALIZED_AS_PLANNED" || classification === "ADDITIONAL_COMPLETED") return "border-emerald-200 bg-emerald-100 text-emerald-800"
  return "border-slate-200 bg-slate-100 text-slate-700"
}

export function RealizationWeeklyDays({ result, compact = false }: Props) {
  const [selectedDate, setSelectedDate] = React.useState<string | null>(null)
  const panelId = React.useId()
  const days = result.facts_json.daily_timeline || []
  if (!days.length) return <p className="text-xs text-slate-400">Pa të dhëna ditore</p>
  return <div className={compact ? "mt-2 flex flex-wrap gap-1" : "space-y-2"}>
    {days.map(day => {
      const comments: Array<{ label: string; text: string; author?: string | null }> = [
        ...(day.person_comment ? [{ label: "Komenti ditor", author: day.person_comment.author, text: day.person_comment.comment }] : []),
        ...Object.entries(day.manual_answers || {}).filter(([, answer]) => answer.comment).map(([key, answer]) => ({ label: weeklyChecklistLabels[key] || key, text: answer.comment! })),
        ...(day.close_event?.daily_comment ? [{ label: "Mbyllja ditore", text: day.close_event.daily_comment }] : []),
        ...(day.tasks || []).filter(task => task.daily_report_comment).map(task => ({ label: firstTaskLine(task.title), text: task.daily_report_comment! })),
      ]
      const label = day.on_leave ? "Pushim" : day.future ? "Në vijim" : day.daily_progress_percent == null ? "Pa të dhëna" : `${day.daily_progress_percent}%`
      const dateLabel = day.date.split("-").reverse().join(".")
      const weekday = new Date(`${day.date}T12:00:00`).getDay()
      const content = <div className="min-w-0 space-y-4 text-left font-normal">
          {compact ? <p className="font-semibold">{dateLabel}</p> : null}
          <dl className="flex flex-wrap gap-2">
            {[
              { label: "Plan", value: day.planned_count, color: "border-slate-200 bg-slate-50 text-slate-700" },
              { label: "Kryer gjithsej", value: day.completed_count, color: "border-emerald-200 bg-emerald-50 text-emerald-800" },
              { label: "Ekstra", value: day.additional_count, color: "border-blue-200 bg-blue-50 text-blue-800" },
            ].map(metric => <div key={metric.label} className={`flex items-center gap-3 rounded-md border px-3 py-2 ${metric.color}`}><dt className="text-xs">{metric.label}</dt><dd className="text-sm font-semibold tabular-nums">{metric.value}</dd></div>)}
          </dl>
          {comments.length ? <div className="space-y-2">{comments.map((comment, index) => (
            <article key={index} className="overflow-hidden rounded-lg border border-slate-200 bg-slate-50">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-3 py-2">
                <p className="text-xs font-semibold text-slate-700">{comment.label}</p>
                {comment.author ? <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[11px] text-slate-600">Nga {comment.author}</span> : null}
              </div>
              <p className="whitespace-pre-wrap break-words px-3 py-3 text-sm leading-6 text-slate-800">{comment.text}</p>
            </article>
          ))}</div> : null}
          {!comments.length ? <p className="text-slate-400">Pa komente të regjistruara.</p> : null}
          {(day.tasks || []).length ? <div>
            <p className="font-semibold text-slate-700">Detyrat e ditës ({day.tasks!.length})</p>
            <ol className="mt-2 overflow-hidden rounded-md border border-slate-200">
              {day.tasks!.map((task, index) => {
                const title = firstTaskLine(task.title)
                const classification = task.classification?.toUpperCase() || ""
                const status = taskStates[classification]
                return <li key={index} className="flex min-w-0 items-center gap-2 border-b border-slate-200 px-3 py-2 last:border-b-0 even:bg-slate-50">
                  <span className="w-5 shrink-0 text-slate-400">{index + 1}.</span>
                  <span className="min-w-0 flex-1 truncate font-medium text-slate-700" title={title}>{title}</span>
                  {status ? <span className={`shrink-0 rounded-md border px-2 py-1 text-[10px] font-semibold ${taskStatusColor(classification)}`}>{status}</span> : null}
                </li>
              })}
            </ol>
          </div> : null}
        </div>
      if (compact) return <details key={day.date} className="rounded border bg-white p-1 text-[11px]">
        <summary className="cursor-pointer font-semibold" title={`${dateLabel} · ${comments.length} komente`}>
          {weekdays[weekday]} · {label}{comments.length ? ` · ${comments.length} komente` : ""}
        </summary>
        <div className="mt-2 min-w-48">{content}</div>
      </details>
      const selected = selectedDate === day.date
      const id = `${panelId}-${day.date}`
      return <React.Fragment key={day.date}>
        <button
          type="button"
          id={`${id}-button`}
          aria-expanded={selected}
          aria-controls={id}
          onClick={() => setSelectedDate(selected ? null : day.date)}
          className={`grid w-full min-w-0 grid-cols-[5rem_5rem_5rem_minmax(0,1fr)_0.75rem] items-center gap-2 rounded-lg border p-3 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 sm:grid-cols-[6rem_6rem_6rem_minmax(0,1fr)_0.75rem] sm:gap-3 ${selected ? "border-blue-500 bg-blue-50 ring-1 ring-blue-500" : "border-slate-200 bg-white hover:border-blue-300 hover:bg-slate-50"}`}
        >
          <span className="block text-xs font-semibold text-slate-800">{weekdayNames[weekday]}</span>
          <span className="text-xs tabular-nums text-slate-500">{dateLabel}</span>
          <span className={`text-sm font-semibold ${day.on_leave || day.future || day.daily_progress_percent == null ? "text-slate-500" : day.daily_progress_percent >= 100 ? "text-emerald-700" : "text-amber-700"}`}>{label}</span>
          <span className="min-w-0 whitespace-pre-wrap break-words text-sm text-slate-700">{comments.length ? comments.map(comment => comment.text).join("\n") : "Pa komente"}</span>
          <span aria-hidden="true" className="text-xs text-slate-500">{selected ? "▴" : "▾"}</span>
        </button>
        <div id={id} role="region" aria-labelledby={`${id}-button`} hidden={!selected} className="min-w-0 rounded-lg border border-blue-200 bg-white p-3 text-xs">
          <p className="mb-3 font-semibold text-slate-800">{weekdayNames[weekday]} · {dateLabel} · {label}</p>
          {content}
        </div>
      </React.Fragment>
    })}
  </div>
}
