"use client"

import { Plus } from "lucide-react"
import { Fragment, useEffect, useId, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { AbbreviationLegend } from "./abbreviation-legend"
import { TaskStatusFilter } from "./task-status-filter"
import { canEditTime, groupWeekTasks } from "@/lib/ga-personal-week"
import { groups, dayLabel, GaOccurrence, GaStatus, PersonKey, localTime, localToday, moveDay, statuses, Workspace } from "@/lib/ga-personal"

const personInitials: Partial<Record<PersonKey, string>> = { mrika: "MC", lirza: "LC", rrita: "RRC" }
const personTextColors: Record<PersonKey, string> = {
  mrika: "text-violet-800 dark:text-violet-200", lirza: "text-sky-800 dark:text-sky-200",
  rrita: "text-orange-900 dark:text-orange-200", gane: "text-teal-800 dark:text-teal-200",
}
const statusColors: Record<GaStatus, string> = {
  pending: "border-pink-400 bg-[#FFC4ED] text-pink-950 dark:border-pink-500 dark:bg-pink-950 dark:text-pink-100",
  acknowledged: "border-cyan-400 bg-cyan-50 text-cyan-900 dark:border-cyan-700 dark:bg-cyan-950 dark:text-cyan-200",
  in_progress: "border-yellow-500 bg-[#FFFF00] text-yellow-950 dark:border-yellow-400 dark:bg-yellow-950 dark:text-yellow-100",
  needs_help: "border-red-500 bg-red-100 text-red-950 dark:border-red-500 dark:bg-red-950 dark:text-red-100",
  rescheduled: "border-amber-500 bg-amber-50 text-amber-900 dark:border-amber-600 dark:bg-amber-950 dark:text-amber-200",
  done: "border-green-500 bg-[#C4FDC4] text-green-950 dark:border-green-500 dark:bg-green-950 dark:text-green-100",
  cancelled: "border-zinc-300 bg-zinc-100 text-zinc-500 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-400",
}

function TaskTitle({ label, titles }: { label: string; titles: string[] }) {
  const id = useId()
  const trigger = useRef<HTMLButtonElement>(null)
  const [anchor, setAnchor] = useState<{ left: number; top: number; bottom: number } | null>(null)
  useEffect(() => {
    const reposition = () => setAnchor((current) => current && trigger.current ? trigger.current.getBoundingClientRect() : null)
    window.addEventListener("scroll", reposition, true)
    window.addEventListener("resize", reposition)
    return () => { window.removeEventListener("scroll", reposition, true); window.removeEventListener("resize", reposition) }
  }, [])
  return <>
    <button ref={trigger} type="button" className="min-h-11 w-full cursor-help break-words text-left font-semibold hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-describedby={anchor ? id : undefined}
      onMouseEnter={(e) => setAnchor(e.currentTarget.getBoundingClientRect())} onMouseLeave={() => setAnchor(null)} onFocus={(e) => setAnchor(e.currentTarget.getBoundingClientRect())} onBlur={() => setAnchor(null)} onClick={(e) => setAnchor(e.currentTarget.getBoundingClientRect())} onKeyDown={(e) => { if (e.key === "Escape") setAnchor(null) }}>{label}</button>
    {anchor && createPortal(<div id={id} role="tooltip" className="pointer-events-none fixed z-[150] w-[min(360px,calc(100vw-24px))] space-y-2 rounded-lg border bg-popover p-3 text-xs font-normal leading-relaxed text-popover-foreground shadow-lg" style={{ left: Math.max(12, Math.min(anchor.left, window.innerWidth - Math.min(360, window.innerWidth - 24) - 12)), ...(anchor.bottom > window.innerHeight - 240 ? { bottom: window.innerHeight - anchor.top + 6 } : { top: anchor.bottom + 6 }) }}>{titles.map((title) => <p key={title}>{title}</p>)}</div>, document.body)}
  </>
}

export function WeekTable({ rows, start, workspace, busy, selectedPerson, statusFilter, onStatusFilter, onOpen, onEditTime }: {
  rows: GaOccurrence[]; start: string; workspace: Workspace; busy: boolean; selectedPerson: string; statusFilter: string; onStatusFilter: (value: string) => void; onOpen: (rows: GaOccurrence[]) => void; onEditTime: (rows: GaOccurrence[]) => void
}) {
  const days = Array.from({ length: 7 }, (_, i) => moveDay(start, i))
  const tasks = groupWeekTasks(rows)
  const rowNumbers = new Map(tasks.map(({ id }, index) => [id, index + 1]))
  const today = localToday()
  const sections = [
    { key: "events", label: "Ngjarjet", tasks: tasks.filter((task) => task.isEvent) },
    ...Object.entries(groups).map(([group, label]) => ({ key: group, label, tasks: tasks.filter((task) => task.group === group && !task.isEvent) })),
  ].filter((section) => section.tasks.length)
  return <div className="min-w-0 space-y-3" data-testid="ga-week-table">
    <div className="flex flex-wrap items-center justify-end gap-2 rounded-lg bg-muted/30 px-3 py-2">
      <TaskStatusFilter value={statusFilter} onChange={onStatusFilter} />
      <AbbreviationLegend />
    </div>
    <p className="text-xs text-muted-foreground sm:hidden">Rrëshqit tabelën anash për të parë ditët. Prek një qelizë për detajet.</p>
    <div className="max-h-[68vh] w-full min-w-0 overflow-auto overscroll-x-contain rounded-xl border-2 border-slate-400 bg-card dark:border-slate-500" tabIndex={0} role="region" aria-label="Tabela e planit javor">
    <table className="w-full min-w-[1140px] table-fixed border-separate border-spacing-0 text-sm">
      <caption className="sr-only">Plani javor sipas rutinave</caption>
      <thead><tr className="border-y bg-muted/50"><th scope="col" className="sticky top-0 left-0 z-30 w-9 border-b-2 border-r border-slate-300 bg-muted px-1 py-3 text-center text-xs font-semibold dark:border-slate-600">Nr.</th><th scope="col" className="sticky top-0 left-9 z-30 w-28 border-b-2 border-slate-300 bg-card px-2 py-3 dark:border-slate-600 text-left">Detyra</th><th scope="col" className="sticky top-0 z-20 w-16 border-b-2 border-l border-slate-300 bg-card px-2 py-3 text-left dark:border-slate-600">Ora</th>{days.map((date) => {
        const daily = rows.filter((row) => row.local_date === date)
        return <th key={date} scope="col" className={`sticky top-0 z-20 border-b-2 border-l border-slate-300 dark:border-slate-600 px-3 py-3 text-left shadow-sm ${date === today ? "bg-blue-50 dark:bg-blue-950" : "bg-card"}`}>
          <span className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1"><span className="font-semibold">{["E hënë", "E martë", "E mërkurë", "E enjte", "E premte", "E shtunë", "E diel"][days.indexOf(date)]}</span>
            <span className="whitespace-nowrap text-[11px] font-normal text-muted-foreground">{dayLabel(date, true)}{date === today ? " · Sot" : ""}</span>
          </span>
          <span className="mt-2 block text-[11px] font-normal text-muted-foreground">{daily.length ? `${daily.filter((r) => r.status === "done").length}/${daily.length} të kryera` : "Pa detyra të krijuara"}</span>
          <span className="mt-2 block h-1.5 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label={`Progresi: ${dayLabel(date)}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={daily.length ? Math.round(daily.filter((r) => r.status === "done").length / daily.length * 100) : 0}><span className="block h-full rounded-full bg-emerald-500" style={{ width: `${daily.length ? daily.filter((r) => r.status === "done").length / daily.length * 100 : 0}%` }} /></span>
        </th>
      })}</tr></thead>
      <tbody>{sections.map(({ key, label, tasks: grouped }) => <Fragment key={key}><tr><th colSpan={10} scope="rowgroup" className={`border-b border-slate-300 px-4 py-2 text-left text-xs font-semibold dark:border-slate-600 ${key === "events" ? "bg-sky-50 text-sky-950 dark:bg-sky-950/50 dark:text-sky-100" : "bg-muted/60"}`}><span className="sticky left-4">{label}<span className="ml-2 font-normal text-muted-foreground">{grouped.length} detyra</span></span></th></tr>{grouped.map(({ id, entries, label: code, titles, isEvent }) => {
          const times = Array.from(new Set(entries.flatMap((row) => row.due_at ? [localTime(row.due_at)] : []))).sort()
          const editable = entries.filter(canEditTime)
          return <tr key={id} className={`border-b last:border-0 ${isEvent ? "bg-sky-50/35 dark:bg-sky-950/10" : ""}`}>
        <td className="sticky left-0 z-10 border-b border-r border-slate-300 bg-muted px-2 py-3 text-center text-xs font-semibold tabular-nums text-muted-foreground dark:border-slate-600">{rowNumbers.get(id)}</td>
        <th scope="row" className="sticky left-9 z-10 border-b border-slate-300 dark:border-slate-600 bg-card px-2 py-2 text-left align-middle text-[11px]"><div className="flex flex-col items-start gap-1"><TaskTitle label={code} titles={titles} />{isEvent && <span className="rounded bg-sky-100 px-1.5 py-0.5 text-[9px] font-semibold text-sky-800 dark:bg-sky-900 dark:text-sky-100">Ngjarje</span>}</div></th>
        <td className="relative border-b border-l border-slate-300 px-1 py-6 align-middle text-center tabular-nums dark:border-slate-600">
          <span className={`flex flex-col items-center gap-1 text-sm font-semibold ${times.length ? "text-foreground" : "text-muted-foreground/40"}`}>{times.length ? times.map((time) => <span key={time}>{time}</span>) : <span aria-label="Pa orar">—</span>}</span>
          {editable.length > 0 && <button type="button" disabled={busy} onClick={() => onEditTime(editable)} aria-label={`Cakto orën: ${code}`} title="Shto ose ndrysho orën" className="absolute inset-0 transition-colors hover:bg-blue-50/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:opacity-50 dark:hover:bg-blue-950/20"><span className="absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded border border-blue-200 bg-blue-50 text-blue-700 shadow-xs dark:border-blue-800 dark:bg-blue-950 dark:text-blue-300"><Plus className="h-3.5 w-3.5" aria-hidden="true" /></span></button>}
        </td>
        {days.map((date) => {
          const cell = entries.filter((row) => row.local_date === date)
          return <td key={date} className={`border-b border-l border-slate-300 dark:border-slate-600 p-1.5 align-middle ${date === today ? "bg-blue-50/40 dark:bg-blue-950/20" : cell.length ? "" : "bg-muted/25"}`}>
            {cell.length ? <button type="button" onClick={() => onOpen(cell)} className="flex min-h-11 w-full flex-wrap items-center gap-1 rounded-md p-0.5 text-left transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label={`${entries[0].snapshot.title}, ${dayLabel(date)}`}>
              {cell.map((row) => <Fragment key={row.id}>{(row.snapshot.assignees.length ? row.snapshot.assignees.filter((key) => selectedPerson === "all" || key === selectedPerson) : [null]).map((key) => {
                  const name = key ? workspace.members.find((m) => m.person_key === key)?.name || key : "Pa përgjegjës"
                  const initials = key ? personInitials[key] || name.split(/\s+/).map((part) => part[0]).slice(0, 3).join("") : "—"
                  const description = `${name} · ${statuses[row.status]}${row.period_key.startsWith("weekend:") ? " · Një herë gjatë vikendit" : ""}`
                  return <span key={key || "unassigned"} title={description} aria-label={description} role="img" className={`inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-2 text-[13px] font-bold leading-none ${statusColors[row.status]}`}>
                    <span aria-hidden="true" className={key ? personTextColors[key] : undefined}>{initials}</span>
                  </span>
                })}</Fragment>)}
            </button> : <span className="block text-center text-xs text-muted-foreground/40" aria-label="Pa detyrë të krijuar">—</span>}
          </td>
        })}
      </tr>})}</Fragment>)}</tbody>
    </table>
    </div>
    <p className="px-1 text-[11px] text-muted-foreground">Shfaqen vetëm detyrat e krijuara. Zgjidh qelizën e orës për ta ndryshuar ose qelizën e ditës për detajet e personave.</p>
  </div>
}
