"use client"

import { RealizationReviewCells } from "@/components/realization-review-cells"
import { RealizationWeeklyDays } from "@/components/realization-weekly-days"
import { RealizationQuantityDelta, RealizationQuantitySummary } from "@/components/realization-quantity"
import { RealizationPlanSummary } from "@/components/realization-plan-summary"
import { RealizationDeadlineStatusGrid, RealizationExtraStatusGrid, RealizationPlanStatusGrid, RealizationStatusLegend, metricBand, metricCell, metricHeadline } from "@/components/realization-plan-status-grid"
import { RealizationDeadlineTasksPopover, criticalDeadlineCounts, criticalDeadlineSummary, deadlineAlarmCount, sortDeadlineTasks } from "@/components/realization-deadline-tasks"
import type { RealizationDeadlineTask, RealizationPersonResult, RealizationWeeklyResponse } from "@/lib/types"
import { compareRealizationDepartments, realizationDepartmentTag } from "@/lib/department-name"
import { cn } from "@/lib/utils"
import { weeklyRealizationPercent } from "@/lib/weekly-realization-percent"
import { mergeWeeklyDeadlineTasks, weeklyDeadlineTotals } from "@/lib/weekly-realization-deadlines"
import { compareWeeklyPlannerUsers, type WeeklyPlannerSortOrder } from "@/lib/weekly-planner-user-order"

export function weeklyMetrics(person: RealizationPersonResult) {
  const facts = person.facts_json
  const planned = facts.weekly_planned_count ?? person.planned_count
  const plannedCompleted = facts.weekly_completed_count ?? person.completed_on_time_count + person.completed_late_count
  const extra = facts.weekly_additional_count ?? person.additional_count
  const extraCompleted = facts.weekly_additional_completed_count ?? Math.max(0, (facts.weekly_all_completed_count ?? plannedCompleted) - plannedCompleted)
  const extraProgress = facts.weekly_additional_in_progress_count ?? 0
  const extraPostponed = facts.weekly_additional_postponed_count ?? 0
  const extraTodo = facts.weekly_additional_todo_count ?? facts.weekly_additional_no_progress_count ?? Math.max(0, extra - extraCompleted - extraProgress - extraPostponed)
  const extraDeferred = facts.weekly_additional_deferred_count ?? 0
  const completed = facts.weekly_all_completed_count ?? plannedCompleted + extraCompleted
  const progress = facts.weekly_in_progress_task_count ?? person.in_progress_count
  const postponed = facts.weekly_postponed_task_count ?? person.approved_postponement_count + person.unapproved_postponement_count
  const penaltyPoints = facts.weekly_penalty_points ?? postponed * 25
  const noProgress = facts.weekly_no_progress_task_count ?? person.no_progress_count + person.pending_count
  const quantityTasks = facts.weekly_quantity_task_count ?? 0
  const quantityPlanned = facts.weekly_quantity_planned_count ?? 0
  const quantityCompleted = facts.weekly_quantity_completed_count ?? 0
  const quantityDelta = facts.weekly_quantity_delta ?? quantityCompleted - quantityPlanned
  const deadlines = facts.weekly_deadline_count ?? 0
  const deadlinesCompleted = facts.weekly_deadline_completed_count ?? 0
  const deadlinesPostponed = facts.weekly_deadline_postponed_count ?? 0
  const deadlinesInProgress = facts.weekly_deadline_in_progress_count ?? 0
  const deadlinesNoProgress = facts.weekly_deadline_no_progress_count ?? Math.max(0, deadlines - deadlinesCompleted - deadlinesPostponed - deadlinesInProgress)
  const criticalDeadlines = facts.weekly_critical_deadline_count ?? 0
  const criticalDeadlinesCompleted = facts.weekly_critical_deadline_completed_count ?? 0
  const deadlineTasks = facts.weekly_deadline_tasks ?? []
  const wfe = facts.weekly_wfe_count ?? 0
  const diamonds = facts.weekly_diamond_count ?? 0
  const taskDiamonds = facts.weekly_task_diamond_count ?? 0
  const proposalDiamonds = facts.weekly_proposal_diamond_count ?? 0
  const diamondAwards = facts.weekly_diamonds ?? []
  return {
    planned, completed, extra, extraCompleted, extraProgress, extraPostponed, extraTodo, extraDeferred,
    progress, postponed, penaltyPoints, noProgress, quantityTasks, quantityPlanned, quantityCompleted, quantityDelta,
    deadlines, deadlinesCompleted, deadlinesPostponed, deadlinesInProgress, deadlinesNoProgress, criticalDeadlines, criticalDeadlinesCompleted, deadlineTasks, wfe,
    diamonds, taskDiamonds, proposalDiamonds, diamondAwards,
    percent: weeklyRealizationPercent(planned, completed, extra, penaltyPoints, wfe),
  }
}

export function hasWeeklyActivity(person: RealizationPersonResult) {
  if (person.facts_json.availability_status) return true
  const value = weeklyMetrics(person)
  return [
    value.planned,
    value.completed,
    value.extra,
    value.extraCompleted,
    value.extraProgress,
    value.extraPostponed,
    value.extraTodo,
    value.extraDeferred,
    value.progress,
    value.postponed,
    value.noProgress,
    value.quantityTasks,
    value.quantityPlanned,
    value.quantityCompleted,
    value.deadlines,
    value.deadlinesCompleted,
    value.deadlinesPostponed,
    value.deadlinesInProgress,
    value.deadlinesNoProgress,
    value.diamonds,
  ].some((metric) => metric !== 0)
}

export function WeeklyRealizationTable({ reports, personId, onSelect, loading, onReviewSaved, plannerOrderByUserId }: {
  reports: RealizationWeeklyResponse[]; personId: string; loading: boolean
  plannerOrderByUserId: WeeklyPlannerSortOrder
  onReviewSaved: () => void
  onSelect: (report: RealizationWeeklyResponse, person: RealizationPersonResult) => void
}) {
  const rows = reports.flatMap((report) => report.people.map((person) => ({ report, person })))
    .filter(({ person }) => personId === "ALL" || person.user_id === personId)
    .filter(({ person }) => hasWeeklyActivity(person))
    .sort((a, b) => compareRealizationDepartments({ name: a.report.department_name }, { name: b.report.department_name }) || compareWeeklyPlannerUsers(a.person, b.person, plannerOrderByUserId))

  const total = rows.reduce((sum, { person }) => {
    const value = weeklyMetrics(person)
    for (const key of ["planned", "completed", "extra", "extraCompleted", "extraProgress", "extraPostponed", "extraTodo", "extraDeferred", "progress", "postponed", "penaltyPoints", "noProgress", "quantityTasks", "quantityPlanned", "quantityCompleted", "quantityDelta", "deadlines", "deadlinesCompleted", "deadlinesPostponed", "deadlinesInProgress", "deadlinesNoProgress", "criticalDeadlines", "criticalDeadlinesCompleted", "wfe"] as const) sum[key] += value[key]
    // Pooled deadlines lose their owner, so the name is carried along.
    sum.deadlineTasks.push(...value.deadlineTasks.map((task) => ({ ...task, person: person.user_name })))
    return sum
  }, { planned: 0, completed: 0, extra: 0, extraCompleted: 0, extraProgress: 0, extraPostponed: 0, extraTodo: 0, extraDeferred: 0, progress: 0, postponed: 0, penaltyPoints: 0, noProgress: 0, quantityTasks: 0, quantityPlanned: 0, quantityCompleted: 0, quantityDelta: 0, deadlines: 0, deadlinesCompleted: 0, deadlinesPostponed: 0, deadlinesInProgress: 0, deadlinesNoProgress: 0, criticalDeadlines: 0, criticalDeadlinesCompleted: 0, wfe: 0, deadlineTasks: [] as RealizationDeadlineTask[] })
  total.deadlineTasks = sortDeadlineTasks(mergeWeeklyDeadlineTasks(total.deadlineTasks))
  Object.assign(total, weeklyDeadlineTotals(total.deadlineTasks))
  const totalPercent = weeklyRealizationPercent(total.planned, total.completed, total.extra, total.penaltyPoints, total.wfe)

  const planCell = (value: ReturnType<typeof weeklyMetrics> | typeof total) => <>
    <p className={cn(metricHeadline, "font-semibold text-slate-900")}><span className="tabular-nums">Plan {value.planned}</span> <span className="text-slate-400">+</span> <span className="tabular-nums text-blue-800">Ekstra {value.extra}</span> <span className="text-slate-400">=</span> <span className="text-base font-bold tabular-nums">{value.planned + value.extra} total</span></p>
    <RealizationPlanStatusGrid completed={value.completed} progress={value.progress} postponed={value.postponed} noProgress={value.noProgress} />
  </>
  const extraCell = (value: ReturnType<typeof weeklyMetrics> | typeof total) => <>
    <p className={cn(metricHeadline, "justify-center gap-1 font-semibold text-blue-900")}>
      <span className="text-lg tabular-nums">{value.extraCompleted}/{value.extra}</span>
      {value.extraDeferred ? <span
        className="self-start rounded border border-slate-300 bg-slate-100 px-1 text-[10px] font-bold tabular-nums text-slate-600"
        title={`${value.extraDeferred} detyra ekstra u shtuan, mbetën pa u nisur dhe u shtynë për më vonë, prandaj nuk numërohen si punë e kësaj jave`}
      >+{value.extraDeferred} shtyrë</span> : null}
    </p>
    <RealizationExtraStatusGrid progress={value.extraProgress} noProgress={value.extraTodo + value.extraPostponed} />
  </>
  const quantityCell = (value: ReturnType<typeof weeklyMetrics> | typeof total) => value.quantityTasks ? <>
    <p className={cn(metricHeadline, "font-semibold")}><span className="text-xl font-bold tabular-nums">{value.quantityCompleted}/{value.quantityPlanned}</span></p>
    <div className={cn(metricBand, "text-base font-bold")}><RealizationQuantityDelta value={value.quantityDelta} /></div>
  </> : <p className={cn(metricHeadline, "text-slate-400")}>Pa sasi</p>
  const deadlineCell = (value: ReturnType<typeof weeklyMetrics> | typeof total, personName?: string) => {
    return <RealizationDeadlineTasksPopover tasks={value.deadlineTasks} title={personName ? `Afatet e javës · ${personName}` : "Afatet e javës · të gjithë"}>
      <div className={cn(metricHeadline, "justify-between gap-2 font-semibold")}>
        <p><span className="text-base tabular-nums text-emerald-700">{value.deadlinesCompleted}/{value.deadlines}</span></p>
        {value.criticalDeadlines ? <span className="rounded border border-red-600 bg-red-200 px-1.5 py-0.5 text-[11px] font-bold tabular-nums text-red-950" title={criticalDeadlineSummary(value.deadlineTasks)}>{value.criticalDeadlinesCompleted}/{value.criticalDeadlines}</span> : null}
      </div>
      <RealizationDeadlineStatusGrid completed={value.deadlinesCompleted} progress={value.deadlinesInProgress} postponed={value.deadlinesPostponed} noProgress={value.deadlinesNoProgress} critical={criticalDeadlineCounts(value.deadlineTasks)} />
    </RealizationDeadlineTasksPopover>
  }
  const percentCell = (percent: number) => <><p className={cn(metricHeadline, "justify-center text-base font-bold tabular-nums", percent >= 100 ? "text-emerald-700" : percent >= 50 ? "text-amber-700" : "text-rose-700")}>{percent}%</p><div className="mx-auto mt-1 h-1.5 w-16 overflow-hidden rounded-full bg-slate-200"><div className={cn("h-full rounded-full", percent >= 100 ? "bg-emerald-500" : percent >= 50 ? "bg-amber-500" : "bg-rose-500")} style={{ width: `${percent}%` }} /></div></>

  return <>
    <RealizationPlanSummary metrics={{
      original_planned_count: total.planned,
      total_completed_today_count: total.completed,
      in_progress_count: total.progress,
      postponed_count: total.postponed,
      no_progress_count: total.noProgress,
      additional_count: total.extra,
      additional_completed_count: total.extraCompleted,
      raw_plan_realization: totalPercent,
      adjusted_plan_realization: null,
    }} />
    <RealizationQuantitySummary metrics={{
      quantity_task_count: total.quantityTasks,
      quantity_planned_count: total.quantityPlanned,
      quantity_completed_count: total.quantityCompleted,
      quantity_delta: total.quantityDelta,
    }} />
    <section className="overflow-hidden rounded-md border border-slate-300 bg-white" aria-label="Tabela e realizimit javor">
    <div className="flex items-center justify-between gap-3 border-b px-3 py-2 text-xs"><div className="flex min-w-0 items-center gap-4"><strong>Përmbledhje javore sipas përdoruesve</strong><RealizationStatusLegend /></div><span className="shrink-0 text-slate-500">{rows.length} përdorues</span></div>
    <div className="overflow-x-auto">
      <table style={{ width: "100%", minWidth: 1500 }} className="table-fixed border-collapse text-[13px] [&_th]:border [&_th]:border-slate-200 [&_th]:px-2 [&_th]:py-1.5 [&_td]:border [&_td]:border-slate-200 [&_td]:px-2 [&_td]:py-1">
        <colgroup>
          <col style={{ width: "3%" }} /><col style={{ width: "8%" }} /><col style={{ width: "4%" }} />
          <col style={{ width: "21%" }} /><col style={{ width: "10%" }} /><col style={{ width: "7%" }} />
          <col style={{ width: "13%" }} /><col style={{ width: "6%" }} /><col style={{ width: "10%" }} /><col style={{ width: "18%" }} />
        </colgroup>
        <thead className="bg-slate-100 text-left text-[11px] uppercase text-slate-700"><tr>
          <th className="text-center">Nr.</th><th>Punonjësi</th><th className="text-center">DEP</th><th>Plan · realizimi</th><th className="bg-blue-100">Ekstra Kryer / Totali</th><th className="bg-teal-100">Kryer / Totali</th><th className="bg-orange-100">Due date / Deadline Kryer/Totali</th><th className="text-center">Plan RLZ</th><th>Vlerësimi</th><th>Komenti nga përgjegjësi</th>
        </tr></thead>
        <tbody>
          <tr className="bg-slate-50 font-semibold"><td colSpan={3}>Gjithsej · {personId === "ALL" ? "Të gjithë" : "Përdoruesi i filtruar"}</td><td className={metricCell}>{planCell(total)}</td><td className={cn(metricCell, "bg-blue-50/70")}>{extraCell(total)}</td><td className={cn(metricCell, "bg-teal-50/60")}>{quantityCell(total)}</td><td className={cn(metricCell, "bg-orange-50/70", total.deadlinesNoProgress > 0 && "bg-pink-50/80", deadlineAlarmCount(total.deadlineTasks) > 0 && "!border-2 !border-red-600")}>{deadlineCell(total)}</td><td className={cn(metricCell, "text-center")}>{percentCell(totalPercent)}</td><td colSpan={2} className="text-slate-500">{total.completed} kryer gjithsej</td></tr>
          {loading ? <tr><td colSpan={10} className="p-4 text-center text-slate-500">Duke ngarkuar…</td></tr> : rows.length ? rows.map(({ report, person }, index) => {
            const value = weeklyMetrics(person)
            const availability = person.facts_json.availability_status
            if (availability) {
              const statusLabel = availability === "PV" ? "PV · Pushim vjetor gjatë gjithë javës" : availability === "MUNGESE" ? "Mungesë gjatë gjithë javës" : "PV / Mungesë gjatë gjithë javës"
              return <tr key={`${person.period_id}:${person.user_id}`} className="bg-slate-50/80 align-middle">
                <td className="text-center tabular-nums text-slate-500">{index + 1}</td>
                <td><span className="block whitespace-nowrap text-[15px] font-bold leading-5 text-slate-800">{person.user_name}</span></td>
                <td className="text-center text-xs font-bold uppercase text-slate-600" title={report.department_name || undefined}>{realizationDepartmentTag({ name: report.department_name })}</td>
                <td colSpan={5} className="bg-slate-100/80 text-center"><span className="inline-flex rounded-full border border-slate-300 bg-white px-4 py-1.5 text-sm font-bold text-slate-700">{statusLabel}</span><RealizationWeeklyDays result={person} compact /></td>
                <RealizationReviewCells periodId={report.period.id} userId={person.user_id} userName={person.user_name} result={person} refreshKey={person} locked={report.period.status === "LOCKED"} onSaved={onReviewSaved} />
              </tr>
            }
            return <tr key={`${person.period_id}:${person.user_id}`} className="align-middle hover:bg-slate-50/70">
              <td className="text-center tabular-nums text-slate-500">{index + 1}</td>
              <td><button type="button" onClick={() => onSelect(report, person)} className="block max-w-full whitespace-nowrap text-left text-[15px] font-bold leading-5 text-blue-800 hover:underline">{person.user_name}</button></td>
              <td className="text-center text-xs font-bold uppercase text-slate-600" title={report.department_name || undefined}>{realizationDepartmentTag({ name: report.department_name })}</td>
              <td className={cn(metricCell, value.noProgress > 0 && "bg-rose-50/60")}>{planCell(value)}<RealizationWeeklyDays result={person} compact /></td>
              <td className={cn(metricCell, "bg-blue-50/70")}>{extraCell(value)}</td>
              <td className={cn(metricCell, "bg-teal-50/60", value.quantityTasks > 0 && value.quantityDelta < 0 && "bg-rose-50/60")}>{quantityCell(value)}</td>
              <td className={cn(metricCell, "bg-orange-50/70", value.deadlinesNoProgress > 0 && "bg-pink-50/80", deadlineAlarmCount(value.deadlineTasks) > 0 && "!border-2 !border-red-600")}>{deadlineCell(value, person.user_name)}</td>
              <td className={cn(metricCell, "text-center")}>{percentCell(value.percent)}</td>
              <RealizationReviewCells periodId={report.period.id} userId={person.user_id} userName={person.user_name} result={person} refreshKey={person} locked={report.period.status === "LOCKED"} onSaved={onReviewSaved} />
            </tr>
          }) : <tr><td colSpan={10} className="p-4 text-center text-slate-500">Nuk ka të dhëna për filtrat e zgjedhur.</td></tr>}
        </tbody>
      </table>
    </div>
    <div className="grid gap-px border-t bg-slate-200 text-[11px] text-slate-500 md:grid-cols-3">
      <p className="bg-white px-3 py-2"><b className="text-slate-700">Plan:</b> detyrat unike të gjithë javës + ekstra = ngarkesa totale. E njëjta detyrë nuk numërohet përsëri çdo ditë.</p>
      <p className="bg-white px-3 py-2"><b className="text-slate-700">Ekstra:</b> detyrat e krijuara gjatë kësaj jave, të mbledhura nga të gjitha ditët dhe të ndara në kryer, progres, shtyrë dhe pa progres. Ato që u shtuan, mbetën pa u nisur dhe u shtynë për më vonë shfaqen veçmas si <b className="text-slate-700">shtyrë</b> dhe nuk hyjnë në ngarkesën e javës.</p>
      <p className="bg-white px-3 py-2"><b className="text-slate-700">Sasia:</b> totalet e të gjitha ditëve të javës. <b className="text-slate-700">Deadline:</b> çdo detyrë numërohet një herë gjatë javës, edhe te Të gjithë. Kliko qelizën për statusin javor dhe historikun e afateve. Detyrat important të pambyllura dallohen me të kuqe.</p>
    </div>
    </section>
  </>
}
