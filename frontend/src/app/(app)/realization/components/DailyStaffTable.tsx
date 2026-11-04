"use client"

import { ArrowDownUp } from "lucide-react"
import * as React from "react"
import { toast } from "sonner"
import { useAuth } from "@/lib/auth"
import { realizationTaskGroups } from "@/lib/realization-task-groups"
import { dailyRealizationColumnKind, dailyRealizationTableItems } from "@/lib/realization-table-items"
import { RealizationTaskDetails } from "@/components/realization-task-details"
import { RealizationTaskList } from "@/components/realization-task-list"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { RealizationReviewCells } from "@/components/realization-review-cells"
import { RealizationDailyPersonComment } from "@/components/realization-daily-person-comment"
import { RealizationQuantityDelta } from "@/components/realization-quantity"
import { RealizationStatusLegend, metricBand, metricCell, metricHeadline } from "@/components/realization-plan-status-grid"
import { RealizationPlanRlzPopover } from "@/components/realization-plan-rlz-popover"
import { realizationDepartmentTag } from "@/lib/department-name"
import type { DailyRealizationPerson, Department, RealizationItem, RealizationPersonResult } from "@/lib/types"
import { cn } from "@/lib/utils"

export function DailyStaffTable({ people, filterPeople, departments, departmentId, personFilter, onDepartmentFilter, onPersonFilter, periodIds, results, sort, onSort, onSelect, reviewVersion, onReviewSaved, onPrepareResult, day, canConfirm = false }: {
  canConfirm?: boolean
  day: string
  people: DailyRealizationPerson[]; departments: Department[]; periodIds: Record<string, string>
  results: Record<string, RealizationPersonResult>
  filterPeople: DailyRealizationPerson[]; departmentId: string; personFilter: string
  onDepartmentFilter: (value: string) => void; onPersonFilter: (value: string) => void
  sort: string; onSort: (value: string) => void; onSelect: (userId: string) => void; reviewVersion: number
  onReviewSaved: () => void | Promise<void>
  onPrepareResult: (departmentId: string, userId: string) => Promise<void>
}) {
  const { apiFetch } = useAuth()
  const [saving, setSaving] = React.useState(false)
  const [selectedTask, setSelectedTask] = React.useState<{ person: DailyRealizationPerson; item: RealizationItem } | null>(null)
  const savingRef = React.useRef(false)
  const tableRows = people.map(person => ({ person, items: dailyRealizationTableItems(person.metrics, person.tasks) }))
  const groups = realizationTaskGroups.filter(group => tableRows.some(row => row.items.some(item => dailyRealizationColumnKind(item.kind) === group.kind)))
  const confirm = async (person: DailyRealizationPerson, item: RealizationItem, confirmed: boolean) => {
    if (!canConfirm || savingRef.current || !item.task_id || !item.confirmation_evidence_key) return
    savingRef.current = true
    setSaving(true)
    try {
      const response = await apiFetch(`/realization/daily/tasks/${item.task_id}/confirmation`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: person.user_id, day, confirmed, evidence_key: item.confirmation_evidence_key }),
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}))
        throw new Error(typeof payload.detail === "string" ? payload.detail : "Konfirmimi nuk u ruajt")
      }
      toast.success(confirmed ? "Detyra u konfirmua pa penalizim" : "Konfirmimi u hoq")
      setSelectedTask(null)
      await onReviewSaved()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Konfirmimi nuk u ruajt")
    } finally {
      savingRef.current = false
      setSaving(false)
    }
  }

  return <Card className="gap-0 rounded-md py-0 shadow-sm">
    <CardHeader className="flex-row items-center justify-between border-b px-3 py-2">
      <div className="flex min-w-0 items-center gap-4"><CardTitle className="text-xs uppercase tracking-wider">Stafi</CardTitle><RealizationStatusLegend deadlineLabel="Due date / Deadline i pambyllur" /></div>
      <Select value={sort} onValueChange={onSort}>
        <SelectTrigger className="h-8 w-52 text-xs"><ArrowDownUp className="h-4 w-4" /><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value="planner">Renditja e Weekly Planner</SelectItem>
          <SelectItem value="lowest">Realizimi më i ulët</SelectItem><SelectItem value="postponed">Më shumë shtyrje</SelectItem>
          <SelectItem value="no-progress">Më shumë pa progres</SelectItem><SelectItem value="name">Emri</SelectItem>
        </SelectContent>
      </Select>
    </CardHeader>
    <CardContent className="min-w-0 p-0">
      <Table style={{ width: "100%" }} className="table-fixed text-[11px] [&_th]:whitespace-normal [&_th]:break-words [&_td]:whitespace-normal [&_td]:break-words [&_[data-slot=button]]:min-w-0 [&_[data-slot=button]]:whitespace-normal [&_[data-slot=button]]:text-[11px] [&_th]:border [&_th]:border-slate-200 [&_th]:px-2 [&_th]:py-1.5 [&_td]:border [&_td]:border-slate-200 [&_td]:px-2 [&_td]:py-1">
        <colgroup>
          <col style={{ width: "3%" }} /><col style={{ width: "9%" }} /><col style={{ width: "3%" }} />
          {groups.map(group => <col key={group.kind} style={{ width: `${54 / Math.max(1, groups.length)}%` }} />)}
          <col style={{ width: "5%" }} /><col style={{ width: "5%" }} /><col style={{ width: "8%" }} /><col style={{ width: "13%" }} />
        </colgroup>
        <TableHeader className="sticky top-0 z-20 bg-slate-100">
          <TableRow className="bg-white">
            <TableHead className="w-11" />
            <TableHead><Select value={personFilter} onValueChange={onPersonFilter}><SelectTrigger size="sm" aria-label="Filtro personin" className="w-full min-w-0 gap-1 bg-white px-2 text-[11px] [&_[data-slot=select-value]]:min-w-0"><SelectValue placeholder="Të gjithë" /></SelectTrigger><SelectContent><SelectItem value="ALL">Të gjithë</SelectItem>{[...new Map(filterPeople.map(person => [person.user_id, person])).values()].sort((a, b) => a.user_name.localeCompare(b.user_name)).map(person => <SelectItem key={person.user_id} value={person.user_id}>{person.user_name}</SelectItem>)}</SelectContent></Select></TableHead>
            <TableHead><Select value={departmentId} onValueChange={onDepartmentFilter}><SelectTrigger size="sm" aria-label="Filtro departamentin" className="w-full min-w-0 gap-1 bg-white px-1 text-[11px] [&_[data-slot=select-value]]:min-w-0"><SelectValue placeholder="DEP" /></SelectTrigger><SelectContent><SelectItem value="ALL">Të gjitha</SelectItem>{departments.map(department => <SelectItem key={department.id} value={department.id}>{realizationDepartmentTag(department)}</SelectItem>)}</SelectContent></Select></TableHead>
            <TableHead colSpan={groups.length + 4} />
          </TableRow>
          <TableRow>
            <TableHead className="w-11 text-center text-[11px] uppercase">Nr.</TableHead>
            <TableHead className="text-[11px] uppercase">Punonjësi</TableHead>
            <TableHead className="text-center text-[11px] uppercase">DEP</TableHead>
            {groups.map(group => <TableHead key={group.kind} className={cn("text-[11px] uppercase", group.className)}>{group.label}</TableHead>)}
            <TableHead className="bg-teal-100 text-[11px] uppercase">Kryer / Totali</TableHead>
            <TableHead className="text-center text-[11px] uppercase">Plan RLZ</TableHead>
            <TableHead className="text-[11px] uppercase">Vlerësimi</TableHead>
            <TableHead className="text-[11px] uppercase">Koment ditor</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {tableRows.map(({ person, items: tableItems }, index) => {
            const metrics = person.metrics
            const realization = metrics.raw_plan_realization == null ? null : Math.min(100, metrics.raw_plan_realization)
            const department = departments.find(item => item.id === person.department_id)
            if (person.availability_status) {
              const statusLabel = person.availability_status === "PV" ? "PV · Pushim vjetor" : person.availability_status === "MUNGESE" ? "Mungesë" : "PV / Mungesë"
              return <TableRow key={`${person.department_id}:${person.user_id}`} className="bg-slate-50/80 align-middle">
                <TableCell className="text-center tabular-nums text-slate-500">{index + 1}</TableCell>
                <TableCell><span className="block whitespace-normal text-[12px] font-bold leading-5 text-slate-800">{person.user_name}</span></TableCell>
                <TableCell className="text-center text-xs font-bold uppercase text-slate-600" title={department?.name}>{realizationDepartmentTag(department)}</TableCell>
                <TableCell colSpan={groups.length + 3} className="bg-slate-100/80 text-center"><span className="inline-flex rounded-full border border-slate-300 bg-white px-4 py-1.5 text-sm font-bold text-slate-700">{statusLabel}</span></TableCell>
                <TableCell><RealizationDailyPersonComment compact periodId={periodIds[person.department_id] || ""} userId={person.user_id} userName={person.user_name} day={day} /></TableCell>
              </TableRow>
            }
            return <TableRow key={`${person.department_id}:${person.user_id}`} className="align-middle hover:bg-slate-50/70">
              <TableCell className="text-center tabular-nums text-slate-500">{index + 1}</TableCell>
              <TableCell>
                <button type="button" onClick={() => onSelect(person.user_id)} className="block max-w-full whitespace-normal break-words text-left text-[12px] font-bold leading-5 text-blue-800 hover:underline">{person.user_name}</button>
              </TableCell>
              <TableCell className="text-center text-xs font-bold uppercase text-slate-600" title={department?.name}>{realizationDepartmentTag(department)}</TableCell>
              {groups.map(group => {
                const items = tableItems.filter(item => dailyRealizationColumnKind(item.kind) === group.kind)
                return <TableCell key={group.kind} className={cn("align-top", group.className)}>
                  {items.length ? <p className="pt-1 text-[10px] font-semibold">{items.length} detyra</p> : null}
                  <RealizationTaskList items={items} deadlines={metrics.deadline_tasks} onSelect={item => setSelectedTask({ person, item })} />
                </TableCell>
              })}
              <TableCell className={cn(metricCell, "bg-teal-50/60", metrics.quantity_task_count > 0 && metrics.quantity_delta < 0 && "bg-rose-50/60")}>
                {metrics.quantity_task_count
                  ? <><p className={cn(metricHeadline, "font-semibold")}><span className="text-xl font-bold tabular-nums">{metrics.quantity_completed_count}/{metrics.quantity_planned_count}</span></p><div className={cn(metricBand, "text-base font-bold")}><RealizationQuantityDelta value={metrics.quantity_delta} /></div></>
                  : <p className={cn(metricHeadline, "text-slate-400")}>Pa sasi</p>}
              </TableCell>
              <TableCell className={cn(metricCell, "text-center")}>
                <RealizationPlanRlzPopover metrics={metrics} title={`Plan RLZ · ${person.user_name}`}>
                  <p className={cn(metricHeadline, "justify-center text-base font-bold tabular-nums", realization == null ? "text-slate-400" : realization >= 100 ? "text-emerald-700" : realization >= 50 ? "text-amber-700" : "text-rose-700", realization != null && "cursor-pointer hover:underline")}>{realization == null ? "—" : `${realization}%`}</p>
                  {realization != null ? <div className="mx-auto mt-1 h-1.5 w-full max-w-16 overflow-hidden rounded-full bg-slate-200"><div className={cn("h-full rounded-full", realization >= 100 ? "bg-emerald-500" : realization >= 50 ? "bg-amber-500" : "bg-rose-500")} style={{ width: `${realization}%` }} /></div> : null}
                </RealizationPlanRlzPopover>
              </TableCell>
              <RealizationReviewCells
                periodId={periodIds[person.department_id] || ""} userId={person.user_id} userName={person.user_name}
                result={results[`${person.department_id}:${person.user_id}`]} scope="daily" fitCell refreshKey={reviewVersion}
                onSaved={onReviewSaved} onPrepareResult={() => onPrepareResult(person.department_id, person.user_id)}
                commentCell={<TableCell><RealizationDailyPersonComment compact periodId={periodIds[person.department_id] || ""} userId={person.user_id} userName={person.user_name} day={day} /></TableCell>}
              />
            </TableRow>
          })}
          {!people.length && <TableRow><TableCell colSpan={groups.length + 7} className="text-center text-slate-500">Nuk ka aktivitet për këtë ditë.</TableCell></TableRow>}
        </TableBody>
      </Table>
      <div className="grid gap-px border-t bg-slate-200 text-[11px] text-slate-500 md:grid-cols-3">
        <p className="bg-white px-3 py-2"><b className="text-slate-700">Detyrat:</b> Pa progres përfshin edhe detyrat e shtyra, me shënimin Shtyrë pranë titullit. Kliko detyrën për detajet dhe konfirmimin.</p>
        <p className="bg-white px-3 py-2"><b className="text-slate-700">Sasia:</b> kryer / planifikuar. Diferenca tregon mungesën ose tejkalimin e produkteve/pikëve.</p>
        <p className="bg-white px-3 py-2"><b className="text-slate-700">Afatet:</b> titulli i kuq tregon afat të pambyllur. Kliko titullin për detajet.</p>
      </div>
    </CardContent>
    <RealizationTaskDetails selection={selectedTask} day={day} canConfirm={canConfirm} busy={saving} onClose={() => setSelectedTask(null)} onConfirm={confirmed => { if (selectedTask) void confirm(selectedTask.person, selectedTask.item, confirmed) }} />
  </Card>
}
