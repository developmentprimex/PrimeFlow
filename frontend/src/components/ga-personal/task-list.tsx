"use client"

import { Check, CheckCircle2, CircleHelp, Clock3, Pencil, Play } from "lucide-react"
import { Button } from "@/components/ui/button"
import { dayLabel, GaOccurrence, GaStatus, groups, localTime, PersonKey, statuses, Workspace } from "@/lib/ga-personal"

const personColors: Record<PersonKey, string> = {
  mrika: "bg-violet-100 text-violet-800 dark:bg-violet-950 dark:text-violet-200",
  rrita: "bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-200",
  lirza: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-200",
  gane: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200",
}

export function TaskList({ rows, workspace, busy, showDate, onEdit, onAction, onDefer }: {
  rows: GaOccurrence[]; workspace: Workspace; busy: boolean; showDate: boolean
  onEdit: (row: GaOccurrence) => void; onAction: (row: GaOccurrence, status: GaStatus) => void
  onDefer: (row: GaOccurrence) => void
}) {
  return <div className="space-y-6">{Object.entries(groups).map(([key, label]) => {
    const tasks = rows.filter((row) => row.snapshot.reminder_group === key)
    if (!tasks.length) return null
    return <section key={key} aria-label={label} className="space-y-3">
      <div className="flex items-center gap-3 px-1"><h2 className="font-semibold">{label}</h2><span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">{tasks.length}</span></div>
      <div className="space-y-3">{tasks.map((row) => {
        const owners = row.snapshot.assignees.map((person) => workspace.members.find((m) => m.person_key === person)?.name || person)
        const canAct = row.snapshot.assignees.includes(workspace.person_key) || (workspace.is_admin && workspace.person_key === "gane")
        const terminal = ["done", "cancelled"].includes(row.status)
        const owner = row.snapshot.assignees[0]
        const initials = owners[0]?.split(/\s+/).map((p) => p[0]).slice(0, 2).join("")
        return <article key={row.id} className={`rounded-xl border bg-card p-4 transition-colors sm:p-5 ${row.status === "done" ? "border-emerald-200 bg-emerald-50/40 dark:border-emerald-900 dark:bg-emerald-950/20" : ""}`}>
          <div className="flex items-start gap-3">
            <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${personColors[owner] || "bg-muted"}`}>{row.status === "done" ? <Check className="h-5 w-5" /> : initials}</div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0 space-y-1"><h3 className={`font-semibold leading-snug ${row.status === "done" ? "text-muted-foreground" : ""}`}>{row.snapshot.short_code && <span className="mr-2 text-xs font-medium text-muted-foreground">{row.snapshot.short_code}</span>}{row.snapshot.title}</h3>
                  <p className="text-sm text-muted-foreground">{owners.join(", ")}{showDate ? ` · ${dayLabel(row.local_date, true)}` : ""}</p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {row.can_edit && !terminal ? <>
                    <Button size="sm" variant="outline" className="h-8 gap-1.5 text-xs" disabled={busy} onClick={() => onEdit(row)} aria-label={`Ndrysho orën: ${row.snapshot.title}`}><Clock3 className="h-3.5 w-3.5" />{row.due_at ? localTime(row.due_at) : "Cakto orën"}</Button>
                    <Button size="sm" variant="ghost" className="h-8 gap-1.5 px-2 text-xs" disabled={busy} onClick={() => onEdit(row)}><Pencil className="h-3.5 w-3.5" /><span>Ndrysho</span></Button>
                  </> : <span className="flex items-center gap-1 rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground"><Clock3 className="h-3 w-3" />{row.due_at ? localTime(row.due_at) : "Pa orar"}</span>}
                </div>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <span className={`rounded-full px-2 py-0.5 text-xs ${row.status === "needs_help" ? "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200" : row.status === "done" ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200" : "bg-muted text-muted-foreground"}`}>{statuses[row.status]}</span>
                {(row.snapshot.steps.length > 0 || row.snapshot.description) && <details className="w-full text-sm">
                  <summary className="w-fit cursor-pointer select-none text-muted-foreground hover:text-foreground">Si bëhet? · Shiko udhëzimet</summary>
                  <div className="mt-3 space-y-2 rounded-lg bg-muted/50 p-3"><p className="whitespace-pre-wrap text-muted-foreground">{row.snapshot.description}</p>
                    <ol className="list-decimal space-y-1 pl-5">{row.snapshot.steps.map((step, i) => <li key={i}>{step}</li>)}</ol>
                  </div>
                </details>}
              </div>
              {canAct && !terminal && <div className="mt-4 flex flex-wrap items-center gap-2">
                {["pending", "acknowledged", "in_progress"].includes(row.status) && <Button size="sm" className="gap-1.5" disabled={busy} onClick={() => onAction(row, "done")}><CheckCircle2 className="h-4 w-4" />U kry</Button>}
                {row.status === "pending" && <Button size="sm" variant="outline" disabled={busy} onClick={() => onAction(row, "acknowledged")}>E pashë</Button>}
                {["pending", "acknowledged", "needs_help"].includes(row.status) && <Button size="sm" variant="outline" className="gap-1.5" disabled={busy} onClick={() => onAction(row, "in_progress")}><Play className="h-3.5 w-3.5" />Po ia nisi</Button>}
                {["pending", "acknowledged", "in_progress"].includes(row.status) && <Button size="sm" variant="ghost" className="gap-1.5 text-muted-foreground" disabled={busy} onClick={() => onAction(row, "needs_help")}><CircleHelp className="h-4 w-4" />Më duhet ndihmë</Button>}
                {row.status === "rescheduled" ? <Button size="sm" variant="outline" disabled={busy} onClick={() => onAction(row, "pending")}>Riktheje</Button>
                  : <Button size="sm" variant="ghost" className="gap-1.5 text-muted-foreground" disabled={busy} onClick={() => onDefer(row)}><Clock3 className="h-4 w-4" />Më duhet kohë</Button>}
              </div>}
            </div>
          </div>
        </article>
      })}</div>
    </section>
  })}</div>
}
