"use client"

import { ChevronDown, ListFilter } from "lucide-react"
import Link from "next/link"
import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useAuth } from "@/lib/auth"
import { reportPlannerNameOrder } from "@/lib/one-h-report-users"
import { personInitials } from "@/lib/person-initials"
import { useReportLinkDate } from "@/lib/report-link-date"
import type { Department, UserLookup } from "@/lib/types"
import { weeklyPlanStatusBgClass } from "@/lib/weekly-plan-status"

const dateFields = { due_date: "Due date", start_date: "Start date" } as const
type TaskDates = Partial<Record<keyof typeof dateFields, string | null>>

type TaskPosition = TaskDates & {
  title: string
  slot: string
  period: string
  assignees: string[]
  sections: string[]
  status?: string
}

const changeLabels = {
  added: "Shtuar sot",
  missing: "Nuk shfaqet sot",
}

type Change = {
  task_id: string
  kind: keyof typeof changeLabels | "changed" | "completed" | "rescheduled"
  current_dates?: TaskDates
  current_status?: string
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

function positionFields(position: TaskPosition | null) {
  const sections = position?.sections.map((section) => /^1H (NO SLOT|\d{2}:\d{2})$/.test(section) ? "1H" : section)
  return {
    slot: position?.slot ?? "",
    period: position?.period ?? "",
    type: [...new Set(sections)].sort().join(" · "),
  }
}

const scheduleLabels = { type: "Task Type", slot: "1H slot", period: "AM/PM" } as const
const scheduleFields = ["slot", "period", "type"] as const
const scheduleFallbacks = { type: "Pa lloj", slot: "Pa slot", period: "Pa periudhë" }
const changeLineClass = "-mx-3 border-t px-3 py-1 first:border-t-0 first:pt-0 last:pb-0"
const changeFilterOptions = [...Object.values(dateFields), ...Object.values(scheduleLabels), "Assignee", ...Object.values(changeLabels)]

function AssigneeInitials({ names, fallback }: { names: string[]; fallback: string }) {
  return names.length ? names.map((name, index) => (
    <span key={name}>
      {index > 0 && ", "}
      <abbr title={name} className="no-underline">{personInitials(name)}</abbr>
    </span>
  )) : fallback
}

function describeChange(row: Change, compareNames: (a: string, b: string) => number) {
  if (row.kind === "completed" || row.after?.status === "DONE") return null
  const before = positionFields(row.before)
  const after = positionFields(row.after)
  const beforeAssignees = [...(row.before?.assignees ?? [])].sort(compareNames)
  const afterAssignees = [...(row.after?.assignees ?? [])].sort(compareNames)
  const userChanged = Boolean(row.before && row.after) && beforeAssignees.join("\n") !== afterAssignees.join("\n")
  const changedFields = row.before && row.after
    ? scheduleFields.filter((field) => before[field] !== after[field]) : []
  const currentDates = row.after ?? row.current_dates
  const dateChanges = (Object.keys(dateFields) as Array<keyof TaskDates>).flatMap((field) => {
    const previous = row.before?.[field]
    const current = currentDates?.[field]
    return previous !== undefined && current !== undefined && previous !== current
      ? [{ label: dateFields[field], before: previous ? formatDate(previous) : "Pa datë", after: current ? formatDate(current) : "Pa datë" }]
      : []
  })
  if (row.kind !== "added" && row.kind !== "missing" && !userChanged && !changedFields.length && !dateChanges.length) return null
  const valueRows = [
    ...dateChanges,
    ...(["period", "slot", "type"] as const).filter((field) => changedFields.includes(field)).map((field) => ({
      label: scheduleLabels[field],
      before: before[field] || scheduleFallbacks[field],
      after: after[field] || scheduleFallbacks[field],
    })),
  ]
  if (userChanged) valueRows.push({ label: "Assignee", before: "", after: "" })
  const status = row.kind === "added" || row.kind === "missing" ? changeLabels[row.kind] : null
  return { row, before, after, beforeAssignees, afterAssignees, userChanged, valueRows, status }
}

function ComparisonRow({ change, rowNumber }: {
  change: NonNullable<ReturnType<typeof describeChange>>
  rowNumber: number
}) {
  const { row, before, after, beforeAssignees, afterAssignees, userChanged, valueRows, status } = change
  const taskStatus = row.after?.status ?? row.current_status ?? row.before?.status
  const taskColor = weeklyPlanStatusBgClass(taskStatus)
  const renderValues = (side: "before" | "after") => {
    if (valueRows.length || !status) {
      return valueRows.map((value) => (
        <div key={value.label} className={`${changeLineClass} font-semibold`}>
          {value[side] || <span aria-hidden="true">&nbsp;</span>}
        </div>
      ))
    }
    const position = side === "before" ? before : after
    const slot = position.slot || (row[side]?.sections.includes("1H NO SLOT") ? "Pa slot" : "")
    const schedule = [slot, position.period, position.type].filter(Boolean).join(" · ")
    return schedule || <span className="text-muted-foreground">—</span>
  }

  return (
    <TableRow className="border-b-2 border-b-black [overflow-wrap:anywhere] print:[print-color-adjust:exact]">
      <TableCell className={`border-r px-1 py-2.5 text-center align-top tabular-nums ${taskColor || "text-muted-foreground"}`}>{rowNumber}</TableCell>
      <TableCell className={`border-r px-1 py-2.5 text-center align-top whitespace-normal ${taskColor}`}>
        {userChanged ? (
          <dl className="space-y-1">
            <div><dt className="text-xs text-muted-foreground">Në plan</dt><dd><AssigneeInitials names={beforeAssignees} fallback="Pa përgjegjës" /></dd></div>
            <div><dt className="text-xs text-muted-foreground">Sot</dt><dd className="font-semibold"><AssigneeInitials names={afterAssignees} fallback="Pa përgjegjës" /></dd></div>
          </dl>
        ) : <AssigneeInitials names={row.after ? afterAssignees : beforeAssignees} fallback="—" />}
      </TableCell>
      <th scope="row" className={`px-3 py-2.5 text-left align-top font-medium ${taskColor}`} title={taskStatus?.replaceAll("_", " ")}>
        {row.after?.title ?? row.before?.title}
      </th>
      <TableCell className="border-l px-3 py-2.5 align-top whitespace-normal">
        {valueRows.map(({ label }) => <div key={label} className={`${changeLineClass} font-medium`}>{label}</div>)}
        {status && <span className="inline-block rounded bg-muted px-1 text-xs font-medium">{status}</span>}
      </TableCell>
      <TableCell className="border-l px-3 py-2.5 align-top whitespace-normal tabular-nums">
        {renderValues("before")}
      </TableCell>
      <TableCell className="border-l px-3 py-2.5 align-top whitespace-normal tabular-nums">
        {renderValues("after")}
      </TableCell>
    </TableRow>
  )
}

export default function TodayPlanComparisonPage() {
  const { apiFetch } = useAuth()
  const linkedDate = useReportLinkDate()
  const [attempt, setAttempt] = useState(0)
  const [request, setRequest] = useState<{ date: string; attempt: number; result: Comparison | null } | null>(null)
  const [plannerNames, setPlannerNames] = useState<string[]>([])
  const [changeFilter, setChangeFilter] = useState("")
  const current = request?.date === linkedDate && request.attempt === attempt ? request : null
  const comparison = current?.result
  const reportDate = comparison?.report_date || linkedDate
  const todayHref = reportDate ? `/today-print-report?date=${reportDate}` : "/today-print-report"
  const ranks = new Map(plannerNames.map((name, index) => [name.trim().toLowerCase(), index]))
  const rank = (name: string) => ranks.get(name.trim().toLowerCase()) ?? ranks.size
  const compareNames = (a: string, b: string) => rank(a) - rank(b) || a.localeCompare(b)
  const changes = comparison?.status === "ready" ? comparison.changes
    .map((row) => describeChange(row, compareNames))
    .filter((change) => change !== null)
    .sort((a, b) => {
      const aNames = a.row.after ? a.afterAssignees : a.beforeAssignees
      const bNames = b.row.after ? b.afterAssignees : b.beforeAssignees
      if (!aNames.length || !bNames.length) return Number(!aNames.length) - Number(!bNames.length)
      return compareNames(aNames[0], bNames[0])
    }) : []
  const visibleChanges = changes.filter((change) => !changeFilter || change.status === changeFilter || change.valueRows.some(({ label }) => label === changeFilter))

  useEffect(() => {
    const controller = new AbortController()
    const { signal } = controller
    void Promise.all([apiFetch("/users/lookup", { signal }), apiFetch("/departments", { signal })]).then(async ([people, teams]) => {
      if (!people.ok || !teams.ok) return
      const [users, departments] = await Promise.all([people.json() as Promise<UserLookup[]>, teams.json() as Promise<Department[]>])
      if (!signal.aborted) setPlannerNames(reportPlannerNameOrder(users, departments))
    }).catch(() => {})
    return () => controller.abort()
  }, [apiFetch])

  useEffect(() => {
    const controller = new AbortController()
    const query = linkedDate ? `?report_date=${encodeURIComponent(linkedDate)}` : ""
    void apiFetch(`/today-print-report/plan-comparison${query}`, {
      cache: "no-store",
      signal: controller.signal,
    }).then(async (response) => {
      if (!response.ok) throw new Error("Plan comparison request failed")
      const result = await response.json() as Comparison
      if (!controller.signal.aborted) {
        setRequest({ date: linkedDate, attempt, result })
      }
    }).catch(() => {
      if (!controller.signal.aborted) setRequest({ date: linkedDate, attempt, result: null })
    })
    return () => controller.abort()
  }, [apiFetch, attempt, linkedDate])

  useEffect(() => {
    const refreshRestoredPage = (event: PageTransitionEvent) => {
      if (event.persisted) setAttempt((value) => value + 1)
    }
    window.addEventListener("pageshow", refreshRestoredPage)
    return () => window.removeEventListener("pageshow", refreshRestoredPage)
  }, [])

  return (
    <section className="mx-auto max-w-7xl space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b pb-4">
        <div>
          <h1 className="text-2xl font-semibold">Krahasimi me planin e ruajtur</h1>
          {reportDate && (
            <p className="mt-1 text-sm text-muted-foreground">
              {formatDate(reportDate)}
              {comparison?.status === "ready" && (
                <> · Plani i {formatDate(comparison.saved_at)}
                  {comparison.is_frozen ? " · Gjendja në 16:00" : ""}
                </>
              )}
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2 print:hidden">
          <Button variant="outline" asChild><Link href={todayHref}>Kthehu te 1H SHTYPI Today</Link></Button>
          <Button variant="outline" onClick={() => setAttempt((value) => value + 1)} disabled={!current}>Rifresko</Button>
        </div>
      </header>
      <div className="space-y-3 text-sm">
        {!current ? <p role="status">Po ngarkohet krahasimi…</p>
          : !comparison ? <p role="alert">Krahasimi nuk u ngarkua. Provo ta rifreskosh.</p>
          : comparison.status === "no_plan" ? <p>Nuk ka plan të ruajtur në 17:00 për këtë datë.</p>
          : comparison.status === "no_archive" ? <p>Gjendja e arkivuar e Today nuk është e disponueshme për krahasim.</p>
          : comparison.status === "ready" && (changes.length ? (
            <>
              <p className="text-sm font-medium" aria-live="polite">{visibleChanges.length} {visibleChanges.length === 1 ? "detyrë me ndryshime" : "detyra me ndryshime"}</p>
              <Table
                aria-label="Krahasimi i detyrave"
                className="min-w-[47rem] table-fixed border-collapse text-left text-xs sm:text-sm print:min-w-0"
                containerClassName="max-h-[70dvh] overflow-auto rounded-md border focus-visible:outline-2 focus-visible:outline-ring xl:max-h-none xl:overflow-visible print:max-h-none print:overflow-visible"
                containerProps={{ role: "region", "aria-label": "Ndryshimet e planit", tabIndex: 0 }}
              >
                <colgroup><col className="w-8" /><col className="w-12" /><col /><col className="w-1/5" /><col className="w-[18%]" /><col className="w-[18%]" /></colgroup>
                <TableHeader className="sticky top-0 z-10 bg-muted text-xs shadow-[0_1px_0_var(--border)] print:static print:shadow-none">
                  <TableRow className="hover:bg-muted">
                    <TableHead scope="col" className="border-r px-1 text-center font-semibold">Nr.</TableHead>
                    <TableHead scope="col" className="border-r px-1 text-center font-semibold">KUSH</TableHead>
                    <TableHead scope="col" className="px-3 font-semibold">DETYRA</TableHead>
                    <TableHead scope="col" aria-label="ÇFARË NDRYSHOI" className="border-l px-3 font-semibold">
                      <div className="flex items-center justify-between gap-1">
                        <span className="whitespace-normal">ÇFARË NDRYSHOI</span>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              type="button"
                              variant={changeFilter ? "default" : "outline"}
                              size="sm"
                              className="gap-1 has-[>svg]:px-2 focus-visible:ring-2 focus-visible:ring-ring print:hidden"
                              aria-label="Filtro sipas ndryshimit"
                              title={changeFilter || "Filtro sipas ndryshimit"}
                            >
                              <ListFilter aria-hidden="true" />
                              <ChevronDown className="size-3" aria-hidden="true" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuRadioGroup value={changeFilter} onValueChange={setChangeFilter}>
                              <DropdownMenuRadioItem value="">Të gjitha</DropdownMenuRadioItem>
                              {changeFilterOptions.map((label) => <DropdownMenuRadioItem key={label} value={label}>{label}</DropdownMenuRadioItem>)}
                            </DropdownMenuRadioGroup>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </TableHead>
                    <TableHead scope="col" className="border-l px-3 font-semibold">PLANI NË 17:00</TableHead>
                    <TableHead scope="col" className="border-l px-3 font-semibold">SOT</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visibleChanges.map((change, index) => <ComparisonRow key={change.row.task_id} change={change} rowNumber={index + 1} />)}
                  {visibleChanges.length === 0 && <TableRow><TableCell colSpan={6} className="p-4 text-center text-muted-foreground">S’ka detyra që përputhen me filtrin.</TableCell></TableRow>}
                </TableBody>
              </Table>
            </>
          ) : <p>S’ka ndryshime nga plani i ruajtur.</p>)}
      </div>
    </section>
  )
}
