"use client"

import { Fragment } from "react"
import { CheckCircle2, CircleHelp, Clock3, Play } from "lucide-react"
import { Button } from "@/components/ui/button"
import { GaOccurrence, GaStatus, groups, localTime, PersonKey, statuses, Workspace } from "@/lib/ga-personal"
import { isGaEvent } from "@/lib/ga-personal-week"

const personInitials: Record<PersonKey, string> = { mrika: "MC", rrita: "RRC", lirza: "LC", gane: "GA" }
const personTextColors: Record<PersonKey, string> = {
  mrika: "text-violet-800 dark:text-violet-200", rrita: "text-orange-900 dark:text-orange-200",
  lirza: "text-sky-800 dark:text-sky-200", gane: "text-teal-800 dark:text-teal-200",
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

export function DailyTaskTable({ rows, workspace, busy, selectedPerson, onEdit, onAction, onDefer }: {
  rows: GaOccurrence[]; workspace: Workspace; busy: boolean; selectedPerson: string
  onEdit: (row: GaOccurrence) => void; onAction: (row: GaOccurrence, status: GaStatus) => void
  onDefer: (row: GaOccurrence) => void
}) {
  let index = 0
  const sections = [
    { key: "events", label: "Ngjarjet", tasks: rows.filter(isGaEvent) },
    ...Object.entries(groups).filter(([group]) => group !== "events").map(([group, label]) => ({ key: group, label, tasks: rows.filter((row) => !isGaEvent(row) && row.snapshot.reminder_group === group) })),
  ].filter((section) => section.tasks.length)
  return <div className="min-w-0 space-y-3" data-testid="ga-day-table">
    <div className="max-h-[68vh] w-full min-w-0 overflow-auto overscroll-contain rounded-xl border-2 border-slate-400 bg-card dark:border-slate-500" role="region" aria-label="Tabela e detyrave të ditës" tabIndex={0}>
      <table className="w-full min-w-[780px] table-fixed border-separate border-spacing-0 text-sm">
        <caption className="sr-only">Detyrat e ditës sipas rutinave</caption>
        <thead><tr className="bg-muted/50 text-left"><th scope="col" className="sticky top-0 z-30 w-10 border-b-2 bg-muted px-2 py-3 text-center text-xs">Nr.</th><th scope="col" className="sticky top-0 z-30 w-[220px] border-b-2 bg-muted px-3 py-3">Detyra</th><th scope="col" className="sticky top-0 z-30 w-24 border-b-2 bg-muted px-3 py-3">Ora</th><th scope="col" className="sticky top-0 z-30 w-24 border-b-2 bg-muted px-3 py-3">Progresi</th><th scope="col" className="sticky top-0 z-30 w-[300px] border-b-2 bg-muted px-3 py-3">Veprimet</th></tr></thead>
        <tbody>{sections.map(({ key, label, tasks }) => <Fragment key={key}><tr><th colSpan={5} scope="rowgroup" className={`border-b px-4 py-2 text-left text-xs font-semibold ${key === "events" ? "bg-sky-50 text-sky-950 dark:bg-sky-950/50 dark:text-sky-100" : "bg-muted/60"}`}>{label}<span className="ml-2 font-normal text-muted-foreground">{tasks.length} detyra</span></th></tr>{tasks.map((row) => {
            index += 1
            const terminal = ["done", "cancelled"].includes(row.status)
            const isEvent = isGaEvent(row)
            const canAct = row.snapshot.assignees.includes(workspace.person_key) || (workspace.is_admin && workspace.person_key === "gane")
            const owners = row.snapshot.assignees.filter((key) => selectedPerson === "all" || key === selectedPerson).map((key) => ({ key, name: workspace.members.find((member) => member.person_key === key)?.name || key }))
            return <tr key={row.id} className={`align-middle hover:bg-muted/20 ${isEvent ? "bg-sky-50/35 dark:bg-sky-950/10" : ""}`}>
              <td className="border-b border-r bg-muted/30 px-2 py-3 text-center text-xs tabular-nums text-muted-foreground">{index}</td>
              <th scope="row" className="border-b px-3 py-3 text-left"><div className="space-y-1"><p className="font-semibold leading-snug"><span title={row.snapshot.title}>{row.snapshot.short_code || row.snapshot.title}</span></p>{isEvent && <span className="inline-flex rounded bg-sky-100 px-1.5 py-0.5 text-[10px] font-semibold text-sky-800 dark:bg-sky-900 dark:text-sky-100">Ngjarje</span>}</div></th>
              <td className="border-b px-3 py-3 font-medium tabular-nums">{row.due_at ? localTime(row.due_at) : <span className="text-muted-foreground">Pa orar</span>}</td>
              <td className="border-b px-3 py-3"><div className="flex flex-wrap gap-1.5" aria-label={statuses[row.status]}>{owners.length ? owners.map(({ key, name }) => <span key={key} role="img" aria-label={`${name} · ${statuses[row.status]}`} title={`${name} · ${statuses[row.status]}`} className={`inline-flex h-10 w-10 items-center justify-center rounded-full border-2 text-[13px] font-bold leading-none ${statusColors[row.status]}`}><span className={personTextColors[key]}>{personInitials[key]}</span></span>) : <span role="img" aria-label={statuses[row.status]} title={statuses[row.status]} className={`inline-flex h-10 w-10 items-center justify-center rounded-full border-2 text-sm font-semibold ${statusColors[row.status]}`}>—</span>}</div></td>
              <td className="border-b px-3 py-2"><div className="flex flex-wrap gap-1.5">
                {row.can_edit && !terminal && <Button size="sm" variant="outline" className="h-8" disabled={busy} onClick={() => onEdit(row)}>{row.due_at ? "Ndrysho" : "Cakto orën"}</Button>}
                {canAct && !terminal && <>
                  {row.status === "pending" && <Button size="sm" variant="outline" className="h-8" disabled={busy} onClick={() => onAction(row, "acknowledged")}>E pashë</Button>}
                  {["pending", "acknowledged", "in_progress"].includes(row.status) && <Button size="sm" className="h-8" disabled={busy} onClick={() => onAction(row, "done")}><CheckCircle2 className="mr-1 h-3.5 w-3.5" />U kry</Button>}
                  {["pending", "acknowledged", "needs_help"].includes(row.status) && <Button size="sm" variant="outline" className="h-8" disabled={busy} onClick={() => onAction(row, "in_progress")}><Play className="mr-1 h-3.5 w-3.5" />Po ia nisi</Button>}
                  {["pending", "acknowledged", "in_progress"].includes(row.status) && <Button size="sm" variant="ghost" className="h-8" disabled={busy} onClick={() => onAction(row, "needs_help")}><CircleHelp className="mr-1 h-3.5 w-3.5" />Ndihmë</Button>}
                  <Button size="sm" variant="ghost" className="h-8" disabled={busy} onClick={() => onDefer(row)}><Clock3 className="mr-1 h-3.5 w-3.5" />Shtyje</Button>
                </>}
                {!row.can_edit && !canAct && <span className="text-xs text-muted-foreground">Pa veprime</span>}
              </div></td>
            </tr>
          })}</Fragment>)}</tbody>
      </table>
    </div>
    <p className="px-1 text-xs text-muted-foreground sm:hidden">Rrëshqit tabelën anash për të parë veprimet.</p>
  </div>
}
