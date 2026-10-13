import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import vm from "node:vm"
import { test } from "node:test"
import ts from "typescript"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"

const require = createRequire(import.meta.url)
function load(path, overrides = {}) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8")
  const loaded = { exports: {} }
  const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } })
  vm.runInNewContext(outputText, { module: loaded, exports: loaded.exports, require: name => overrides[name] || require(name) })
  return loaded.exports
}
const { mergeWeeklyDeadlineTasks, weeklyDeadlineTotals } = load("../src/lib/weekly-realization-deadlines.ts")
const deadline = (task_id, overrides = {}) => ({ task_id, title: "Raporti", day: "2026-10-12", state: "POSTPONED", critical: true, ...overrides })

test("All counts shared tasks once and retains all owners and dated outcomes", () => {
  const history = [
    { day: "2026-10-12", state: "POSTPONED", critical: true },
    { day: "2026-10-13", state: "POSTPONED", critical: true },
  ]
  const input = [deadline("A", { person: "Elsa", history }), deadline("A", { person: "Rinesa", history }), deadline("A", { person: "Elsa", history })]
  const before = JSON.stringify(input)
  const merged = mergeWeeklyDeadlineTasks(input)
  assert.equal(merged.length, 1)
  assert.equal(merged[0].person, "Elsa, Rinesa")
  assert.equal(merged[0].history.length, 2)
  const totals = weeklyDeadlineTotals(merged)
  assert.equal(totals.deadlines, 1)
  assert.equal(totals.deadlinesPostponed, 1)
  assert.equal(totals.criticalDeadlines, 1)
  assert.equal(JSON.stringify(input), before)
})

test("a completed shared task has one completed weekly deadline and no postponed total", () => {
  const merged = mergeWeeklyDeadlineTasks([deadline("A"), deadline("A", { state: "COMPLETED", day: "2026-10-13" })])
  const totals = weeklyDeadlineTotals(merged)
  assert.equal(totals.deadlines, 1)
  assert.equal(totals.deadlinesCompleted, 1)
  assert.equal(totals.deadlinesPostponed, 0)
  assert.equal(totals.criticalDeadlinesCompleted, 1)
})

test("latest pending deadline determines status and completion survives an older view", () => {
  const merged = mergeWeeklyDeadlineTasks([deadline("A", { day: "2026-10-13", state: "NO_PROGRESS" }), deadline("A")])
  assert.equal(merged[0].state, "NO_PROGRESS")
  const completed = mergeWeeklyDeadlineTasks([deadline("A", { state: "COMPLETED" }), deadline("A", { day: "2026-10-13" })])
  assert.equal(completed[0].state, "COMPLETED")
})

test("same titles with distinct or unknown IDs never merge; legacy match keys can merge", () => {
  assert.equal(mergeWeeklyDeadlineTasks([deadline("A"), deadline("B")]).length, 2)
  assert.equal(mergeWeeklyDeadlineTasks([deadline(null), deadline(null)]).length, 2)
  assert.equal(mergeWeeklyDeadlineTasks([deadline(null, { match_key: "system:1" }), deadline(null, { match_key: "system:1" })]).length, 1)
})

test("every unique deadline has one status and critical subset counts agree", () => {
  const tasks = mergeWeeklyDeadlineTasks([
    deadline("A", { state: "COMPLETED" }), deadline("B", { state: "IN_PROGRESS", critical: false }),
    deadline("C"), deadline("D", { state: "NO_PROGRESS" }), deadline("A", { state: "COMPLETED" }),
  ])
  const totals = weeklyDeadlineTotals(tasks)
  assert.equal(totals.deadlines, 4)
  assert.equal(totals.deadlinesCompleted + totals.deadlinesPostponed + totals.deadlinesInProgress + totals.deadlinesNoProgress, 4)
  assert.equal(totals.criticalDeadlines, 3)
})

test("the deadline popover shows a single task with its separate postponement history", () => {
  const { RealizationDeadlineTasksPopover } = load("../src/components/realization-deadline-tasks.tsx", {
    "@/components/cell-popover": { CellPopover: ({ panel, children }) => React.createElement("div", null, children, panel) },
    "@/lib/note-markup": { getPlainMarkedText: value => value },
    "@/lib/utils": { cn: (...values) => values.filter(Boolean).join(" ") },
  })
  const tasks = [deadline("A", { state: "COMPLETED", history: [
    { day: "2026-10-12", state: "POSTPONED", critical: true },
    { day: "2026-10-13", state: "COMPLETED", critical: true },
  ] })]
  const html = renderToStaticMarkup(React.createElement(RealizationDeadlineTasksPopover, { tasks, title: "Afatet e javës" }, "1/1"))
  assert.equal((html.match(/Raporti/g) || []).length, 1)
  assert.ok(html.includes("Historiku i afateve (2)"))
  assert.ok(html.includes("12/10") && html.includes("13/10") && html.includes("Shtyrë"))
  assert.ok(html.includes("Të gjitha u kryen"))
})

test("the weekly table uses unique deadline counts in its All row", () => {
  const popovers = [], grids = []
  const empty = () => null
  const { WeeklyRealizationTable } = load("../src/app/(app)/realization/components/WeeklyRealizationTable.tsx", {
    "@/components/realization-review-cells": { RealizationReviewCells: empty },
    "@/components/realization-weekly-days": { RealizationWeeklyDays: empty },
    "@/components/realization-quantity": { RealizationQuantityDelta: empty, RealizationQuantitySummary: empty },
    "@/components/realization-plan-summary": { RealizationPlanSummary: empty },
    "@/components/realization-plan-status-grid": {
      RealizationPlanStatusGrid: empty, RealizationExtraStatusGrid: empty, RealizationStatusLegend: empty,
      RealizationDeadlineStatusGrid: props => { grids.push(props); return null },
      metricBand: "", metricCell: "", metricHeadline: "",
    },
    "@/components/realization-deadline-tasks": {
      RealizationDeadlineTasksPopover: props => { popovers.push(props); return props.children },
      criticalDeadlineCounts: () => ({}), criticalDeadlineSummary: () => "", deadlineAlarmCount: () => 0, sortDeadlineTasks: tasks => tasks,
    },
    "@/lib/department-name": { compareRealizationDepartments: () => 0, realizationDepartmentTag: () => "DEV" },
    "@/lib/utils": { cn: (...values) => values.filter(Boolean).join(" ") },
    "@/lib/weekly-realization-percent": { weeklyRealizationPercent: () => 0 },
    "@/lib/weekly-realization-deadlines": { mergeWeeklyDeadlineTasks, weeklyDeadlineTotals },
    "@/lib/weekly-planner-user-order": { compareWeeklyPlannerUsers: () => 0 },
  })
  const people = ["Elsa", "Rinesa"].map((name, index) => ({
    id: `result-${index}`, user_id: `user-${index}`, user_name: name, period_id: "week",
    planned_count: 1, completed_on_time_count: 0, completed_late_count: 0, additional_count: 0,
    in_progress_count: 0, approved_postponement_count: 1, unapproved_postponement_count: 0,
    no_progress_count: 0, pending_count: 0,
    facts_json: { weekly_deadline_count: 1, weekly_deadline_postponed_count: 1, weekly_deadline_tasks: [deadline("shared")] },
  }))
  renderToStaticMarkup(React.createElement(WeeklyRealizationTable, {
    reports: [{ period: { id: "week", status: "OPEN" }, department_name: "DEV", people }],
    personId: "ALL", loading: false, plannerOrderByUserId: {}, onReviewSaved: () => {}, onSelect: () => {},
  }))
  assert.equal(popovers.length, 3)
  assert.equal(popovers[0].tasks.length, 1)
  assert.equal(popovers[0].tasks[0].person, "Elsa, Rinesa")
  assert.equal(grids[0].postponed, 1)
  assert.equal(grids[0].completed + grids[0].progress + grids[0].postponed + grids[0].noProgress, 1)
})
