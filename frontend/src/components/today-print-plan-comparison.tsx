"use client"

import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { useAuth } from "@/lib/auth"

type TaskPosition = {
  title: string
  slot: string
  period: string
  assignees: string[]
  sections: string[]
}

const changeLabels = {
  added: "Shtuar sot",
  rescheduled: "Datë tjetër",
  completed: "Përfunduar",
  missing: "Nuk shfaqet sot",
}

type Change = {
  task_id: string
  kind: keyof typeof changeLabels | "changed"
  date?: string
  before: TaskPosition | null
  after: TaskPosition | null
}

type Comparison = {
  report_date: string
  status: "no_plan" | "no_archive"
} | {
  report_date: string
  status: "ready"
  saved_at: string
  is_frozen: boolean
  changes: Change[]
}

function formatDate(date: string) {
  return date.slice(0, 10).split("-").reverse().join(".")
}

function changeLabel({ kind, before, after }: Change) {
  if (kind !== "changed") return changeLabels[kind]
  if (!before || !after) return "Ndryshuar"
  const slotChanged = before.slot !== after.slot
  const oldSections = before.sections.filter((section) => section !== `1H ${before.slot}` && section !== "1H NO SLOT")
  const newSections = after.sections.filter((section) => section !== `1H ${after.slot}` && section !== "1H NO SLOT")
  return [
    slotChanged && "Sloti",
    before.period !== after.period && "AM/PM",
    before.assignees.join("\n") !== after.assignees.join("\n") && "Përgjegjësi",
    oldSections.join("\n") !== newSections.join("\n") && "Lloji",
  ].filter(Boolean).join(" · ") || "Ndryshuar"
}

function TaskPositionContent({ position }: { position: TaskPosition | null }) {
  if (!position) return <span className="text-muted-foreground">—</span>
  const sections = position.sections.filter((section) => section !== `1H ${position.slot}`)
    .map((section) => section === "1H NO SLOT" ? "Pa slot" : section)
  const timing = [position.slot, position.period, ...sections].filter(Boolean).join(" · ")
  return (
    <>
      {timing && <div className="font-medium tabular-nums">{timing}</div>}
      {position.assignees.length > 0 && <div className="text-muted-foreground">{position.assignees.join(", ")}</div>}
    </>
  )
}

export function TodayPrintPlanComparison({ reportDate, isFrozen }: { reportDate: string; isFrozen: boolean }) {
  const { apiFetch } = useAuth()
  const [open, setOpen] = useState(false)
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    void apiFetch(`/today-print-report/plan-comparison?report_date=${encodeURIComponent(reportDate)}`, {
      cache: "no-store",
      signal: controller.signal,
    }).then(async (response) => {
      if (!response.ok) throw new Error("Plan comparison request failed")
      const result = await response.json() as Comparison
      if (!controller.signal.aborted) {
        setError(false)
        setComparison(result)
      }
    }).catch(() => {
      if (!controller.signal.aborted) setError(true)
    })
    return () => controller.abort()
  }, [apiFetch, open, reportDate, isFrozen])

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => {
      setComparison(null)
      setError(false)
      setOpen(nextOpen)
    }}>
      <DialogTrigger asChild>
        <Button variant="outline" className="print:hidden">Krahaso me planin e ruajtur</Button>
      </DialogTrigger>
      <DialogContent className="min-w-0 sm:max-w-3xl print:hidden">
        <DialogHeader>
          <DialogTitle>Krahasimi me planin e ruajtur</DialogTitle>
          <DialogDescription>
            {formatDate(reportDate)}
            {comparison?.status === "ready" && (
              <> · Plani i {formatDate(comparison.saved_at)}
                {comparison.is_frozen ? " · Gjendja në 16:00" : ""}
              </>
            )}
          </DialogDescription>
        </DialogHeader>
        {error ? <p role="alert">Krahasimi nuk u ngarkua. Mbylle dhe provo përsëri.</p>
          : !comparison ? <p role="status">Po ngarkohet krahasimi…</p>
          : comparison.status === "no_plan" ? <p>Nuk ka plan të ruajtur në 17:00 për këtë datë.</p>
          : comparison.status === "no_archive" ? <p>Gjendja e arkivuar e Today nuk është e disponueshme për krahasim.</p>
          : comparison.status === "ready" && (comparison.changes.length ? (
            <>
              <p className="text-sm font-medium">{comparison.changes.length} {comparison.changes.length === 1 ? "detyrë me ndryshime" : "detyra me ndryshime"}</p>
              <div className="min-w-0 overflow-x-auto rounded-md border">
                <table className="w-full table-fixed border-collapse text-left text-xs sm:text-sm">
                  <colgroup><col className="w-2/5" /><col className="w-[30%]" /><col className="w-[30%]" /></colgroup>
                  <thead className="bg-muted text-xs">
                    <tr>
                      <th scope="col" className="p-2">DETYRA</th>
                      <th scope="col" className="border-l p-2">PLANI NË 17:00</th>
                      <th scope="col" className="border-l p-2">SOT</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparison.changes.map((row) => (
                      <tr key={row.task_id} className="border-t align-top [overflow-wrap:anywhere]">
                        <th scope="row" className="p-2 text-left font-medium">
                          <div>{row.after?.title ?? row.before?.title}</div>
                          <span className={row.kind === "completed" ? "mt-1 inline-block rounded bg-[#C4FDC4] px-1 text-xs text-slate-950" : "mt-1 block text-xs font-normal text-muted-foreground"}>
                            {changeLabel(row)}
                          </span>
                        </th>
                        <td className="border-l p-2"><TaskPositionContent position={row.before} /></td>
                        <td className="border-l p-2">
                          {row.date ? <span className="font-medium tabular-nums">{formatDate(row.date)}</span> : <TaskPositionContent position={row.after} />}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : <p>S’ka ndryshime nga plani i ruajtur.</p>)}
      </DialogContent>
    </Dialog>
  )
}
