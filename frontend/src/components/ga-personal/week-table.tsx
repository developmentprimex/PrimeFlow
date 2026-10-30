"use client"

import { Check, Circle, Clock3, HelpCircle, Play } from "lucide-react"
import { Fragment } from "react"
import { groups, dayLabel, GaOccurrence, GaStatus, PersonKey, localTime, localToday, moveDay, statuses, Workspace } from "@/lib/ga-personal"

const statusIcons = { pending: Circle, acknowledged: Check, in_progress: Play, needs_help: HelpCircle, rescheduled: Clock3, done: Check, cancelled: Circle }
const personColors: Record<PersonKey, string> = {
  mrika: "bg-violet-100 text-violet-900 dark:bg-violet-900 dark:text-violet-100",
  rrita: "bg-orange-100 text-orange-900 dark:bg-orange-900 dark:text-orange-100",
  lirza: "bg-sky-100 text-sky-900 dark:bg-sky-900 dark:text-sky-100",
  gane: "bg-teal-100 text-teal-900 dark:bg-teal-900 dark:text-teal-100",
}
const statusColors: Record<GaStatus, string> = {
  pending: "border-slate-300 bg-slate-50 text-slate-700 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200",
  acknowledged: "border-cyan-400 bg-cyan-50 text-cyan-900 dark:border-cyan-700 dark:bg-cyan-950 dark:text-cyan-200",
  in_progress: "border-blue-500 bg-blue-50 text-blue-900 dark:border-blue-600 dark:bg-blue-950 dark:text-blue-200",
  needs_help: "border-rose-500 bg-rose-50 text-rose-900 dark:border-rose-600 dark:bg-rose-950 dark:text-rose-200",
  rescheduled: "border-amber-500 bg-amber-50 text-amber-900 dark:border-amber-600 dark:bg-amber-950 dark:text-amber-200",
  done: "border-emerald-500 bg-emerald-50 text-emerald-900 dark:border-emerald-600 dark:bg-emerald-950 dark:text-emerald-200",
  cancelled: "border-zinc-300 bg-zinc-100 text-zinc-500 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-400",
}

export function WeekTable({ rows, start, workspace, onOpen }: {
  rows: GaOccurrence[]; start: string; workspace: Workspace; onOpen: (rows: GaOccurrence[]) => void
}) {
  const days = Array.from({ length: 7 }, (_, i) => moveDay(start, i))
  const tasks = new Map<string, GaOccurrence[]>()
  for (const row of rows) tasks.set(row.template_id, [...(tasks.get(row.template_id) || []), row])
  const orderedTasks = Object.keys(groups).flatMap((group) => Array.from(tasks.entries())
    .filter(([, entries]) => entries[0].snapshot.reminder_group === group)
    .sort((a, b) => a[1][0].snapshot.title.localeCompare(b[1][0].snapshot.title, "sq")))
  const rowNumbers = new Map(orderedTasks.map(([id], index) => [id, index + 1]))
  const today = localToday()
  const completed = rows.filter((r) => r.status === "done").length
  const inProgress = rows.filter((r) => r.status === "in_progress").length
  const needHelp = rows.filter((r) => r.status === "needs_help").length
  return <div className="space-y-3" data-testid="ga-week-table">
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[
      ["Detyra të javës", rows.length, "text-foreground"],
      ["Të përfunduara", completed, "text-emerald-600"],
      ["Në proces", inProgress, "text-blue-600"],
      ["Kërkojnë ndihmë", needHelp, "text-rose-600"],
    ].map(([label, value, color]) => <div key={label} className="rounded-xl border bg-card px-4 py-3"><p className="text-xs font-medium text-muted-foreground">{label}</p><p className={`mt-1 text-2xl font-semibold tabular-nums ${color}`}>{value}</p></div>)}</div>
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-muted/40 px-4 py-2.5"><p className="text-sm font-semibold">{dayLabel(start, true)} – {dayLabel(days[6], true)}</p><div className="flex flex-wrap gap-2 text-[11px]">{(["pending", "in_progress", "needs_help", "done"] as GaStatus[]).map((status) => { const Icon = statusIcons[status]; return <span key={status} className={`inline-flex items-center gap-1 rounded px-2 py-1 ${statusColors[status]}`}><Icon className="h-3 w-3" />{statuses[status]}</span> })}</div></div>
    <div className="max-h-[68vh] overflow-auto rounded-xl border-2 border-slate-400 bg-card dark:border-slate-500" tabIndex={0} role="region" aria-label="Tabela e planit javor">
    <table className="w-full min-w-[1050px] table-fixed border-separate border-spacing-0 text-sm">
      <caption className="sr-only">Plani javor sipas rutinave</caption>
      <thead><tr className="border-y bg-muted/50"><th scope="col" className="sticky top-0 left-0 z-30 w-12 border-b-2 border-r border-slate-300 bg-muted px-2 py-3 text-center text-xs font-semibold dark:border-slate-600">Nr.</th><th scope="col" className="sticky top-0 left-12 z-30 w-60 min-w-60 border-b-2 border-slate-300 bg-card p-4 dark:border-slate-600 text-left">Detyra</th>{days.map((date) => {
        const daily = rows.filter((row) => row.local_date === date)
        return <th key={date} scope="col" className={`sticky top-0 z-20 border-b-2 border-l border-slate-300 dark:border-slate-600 px-3 py-3 text-left shadow-sm ${date === today ? "bg-blue-50 dark:bg-blue-950" : "bg-card"}`}>
          <span className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1"><span className="font-semibold">{["E hënë", "E martë", "E mërkurë", "E enjte", "E premte", "E shtunë", "E diel"][days.indexOf(date)]}</span>
            <span className="whitespace-nowrap text-[11px] font-normal text-muted-foreground">{dayLabel(date, true)}{date === today ? " · Sot" : ""}</span>
          </span>
          <span className="mt-2 block text-[11px] font-normal text-muted-foreground">{daily.length ? `${daily.filter((r) => r.status === "done").length}/${daily.length} të kryera` : "Pa detyra të krijuara"}</span>
          <span className="mt-2 block h-1.5 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label={`Progresi: ${dayLabel(date)}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={daily.length ? Math.round(daily.filter((r) => r.status === "done").length / daily.length * 100) : 0}><span className="block h-full rounded-full bg-emerald-500" style={{ width: `${daily.length ? daily.filter((r) => r.status === "done").length / daily.length * 100 : 0}%` }} /></span>
        </th>
      })}</tr></thead>
      <tbody>{Object.entries(groups).map(([group, label]) => {
        const grouped = Array.from(tasks.entries()).filter(([, entries]) => entries[0].snapshot.reminder_group === group).sort((a, b) => a[1][0].snapshot.title.localeCompare(b[1][0].snapshot.title, "sq"))
        if (!grouped.length) return null
        return <Fragment key={group}><tr><th colSpan={9} scope="rowgroup" className="border-b border-slate-300 dark:border-slate-600 bg-muted/60 px-4 py-2 text-left text-xs font-semibold"><span className="sticky left-4">{label}<span className="ml-2 font-normal text-muted-foreground">{grouped.length} detyra</span></span></th></tr>{grouped.map(([id, entries]) => <tr key={id} className="border-b last:border-0">
        <td className="sticky left-0 z-10 border-b border-r border-slate-300 bg-muted px-2 py-3 text-center text-xs font-semibold tabular-nums text-muted-foreground dark:border-slate-600">{rowNumbers.get(id)}</td>
        <th scope="row" className="sticky left-12 z-10 border-b border-slate-300 dark:border-slate-600 bg-card px-4 py-3 text-left align-middle text-[13px] font-medium">{entries[0].snapshot.title}{entries[0].snapshot.short_code && <span className="mt-1 block text-xs text-muted-foreground">{entries[0].snapshot.short_code}</span>}</th>
        {days.map((date) => {
          const cell = entries.filter((row) => row.local_date === date)
          return <td key={date} className={`border-b border-l border-slate-300 dark:border-slate-600 p-1.5 align-middle ${date === today ? "bg-blue-50/40 dark:bg-blue-950/20" : cell.length ? "" : "bg-muted/25"}`}>
            {cell.length ? <button type="button" onClick={() => onOpen(cell)} className="w-full space-y-1 rounded-md text-left transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label={`${entries[0].snapshot.title}, ${dayLabel(date)}`}>
              {cell.map((row) => <span key={row.id} className={`block space-y-1.5 rounded-md px-2 py-1.5 ${row.status === "done" ? "bg-emerald-50 dark:bg-emerald-950/30" : ""}`}>
                <span className="flex flex-wrap gap-1">{row.snapshot.assignees.length ? row.snapshot.assignees.map((key) => {
                  const name = workspace.members.find((m) => m.person_key === key)?.name || key
                  return <span key={key} title={name} className={`inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 text-xs font-semibold ${personColors[key]}`}><span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white/60 text-[9px] dark:bg-black/20" aria-hidden="true">{name.split(/\s+/).map((part) => part[0]).slice(0, 2).join("")}</span>{name.split(" ")[0]}</span>
                }) : <span className="text-xs font-semibold">Pa përgjegjës</span>}</span>
                <span className="flex flex-wrap items-center gap-1.5"><span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium ${statusColors[row.status]}`}>{(() => { const Icon = statusIcons[row.status]; return <Icon className="h-3 w-3" /> })()}{statuses[row.status]}</span>{row.due_at && <span className="text-[10px] tabular-nums text-muted-foreground">{localTime(row.due_at)}</span>}</span>
                {row.period_key.startsWith("weekend:") && <span className="block text-xs text-muted-foreground">Një herë gjatë vikendit</span>}
              </span>)}
            </button> : <span className="block text-center text-xs text-muted-foreground/40" aria-label="Pa detyrë të krijuar">—</span>}
          </td>
        })}
      </tr>)}</Fragment>
      })}</tbody>
    </table>
    </div>
    <p className="px-1 text-[11px] text-muted-foreground">Shfaqen vetëm detyrat e krijuara. Ora shfaqet kur është caktuar. Zgjidh një qelizë për detajet.</p>
  </div>
}
