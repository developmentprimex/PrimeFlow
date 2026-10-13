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
const { RealizationWeeklyDiamonds } = load("../src/components/realization-weekly-diamonds.tsx", {
  "next/link": { default: ({ href, children, className }) => React.createElement("a", { href, className }, children) },
  "@/components/cell-popover": { CellPopover: ({ panel, children }) => React.createElement("div", null, children, panel) },
  "@/lib/note-markup": { getPlainMarkedText: value => value },
})
const empty = () => null
const diamondCells = []
const { WeeklyRealizationTable, weeklyMetrics, hasWeeklyActivity } = load("../src/app/(app)/realization/components/WeeklyRealizationTable.tsx", {
  "@/components/realization-review-cells": { RealizationReviewCells: () => React.createElement(React.Fragment, null, React.createElement("td"), React.createElement("td")) },
  "@/components/realization-weekly-days": { RealizationWeeklyDays: empty },
  "@/components/realization-weekly-diamonds": { RealizationWeeklyDiamonds: props => { diamondCells.push(props); return null } },
  "@/components/realization-quantity": { RealizationQuantityDelta: empty, RealizationQuantitySummary: empty },
  "@/components/realization-plan-summary": { RealizationPlanSummary: empty },
  "@/components/realization-plan-status-grid": { RealizationPlanStatusGrid: empty, RealizationExtraStatusGrid: empty,
    RealizationStatusLegend: empty, RealizationDeadlineStatusGrid: empty, metricBand: "", metricCell: "", metricHeadline: "" },
  "@/components/realization-deadline-tasks": { RealizationDeadlineTasksPopover: ({ children }) => children,
    criticalDeadlineCounts: () => ({}), criticalDeadlineSummary: () => "", deadlineAlarmCount: () => 0, sortDeadlineTasks: tasks => tasks },
  "@/lib/department-name": { compareRealizationDepartments: () => 0, realizationDepartmentTag: () => "DEV" },
  "@/lib/utils": { cn: (...values) => values.filter(Boolean).join(" ") },
  "@/lib/weekly-realization-percent": { weeklyRealizationPercent: () => 0 },
  "@/lib/weekly-realization-deadlines": { mergeWeeklyDeadlineTasks: tasks => tasks, weeklyDeadlineTotals: () => ({}) },
  "@/lib/weekly-planner-user-order": { compareWeeklyPlannerUsers: () => 0 },
})
const award = (id, proposal = false) => ({ task_id: proposal ? null : `task-${id}`, task_title: proposal ? "Propozim për përmirësim" : "Raporti",
  source: proposal ? "REALIZATION_PROPOSAL" : "TASK", reviewee_user_id: "elsa", reviewee_name: "Elsa",
  completed_at: "2026-10-13T12:00:00Z", review: { id, comment: "Kursen kohë", reviewer_name: "Manager", diamond_score: 1 } })
const person = (id, facts = {}) => ({ id, user_id: id, user_name: id, period_id: "week", planned_count: 0,
  completed_on_time_count: 0, completed_late_count: 0, additional_count: 0, in_progress_count: 0,
  approved_postponement_count: 0, unapproved_postponement_count: 0, no_progress_count: 0, pending_count: 0, facts_json: facts })

function renderTable(people, personId = "ALL", loading = false) {
  diamondCells.length = 0
  return renderToStaticMarkup(React.createElement(WeeklyRealizationTable, {
    reports: [{ period: { id: "week", status: "OPEN" }, department_name: "DEV", people }],
    personId, loading, plannerOrderByUserId: {}, onReviewSaved: () => {}, onSelect: () => {},
  }))
}

test("weekly diamond details show both origins, comments and valid task links", () => {
  const html = renderToStaticMarkup(React.createElement(RealizationWeeklyDiamonds, { count: 2, taskCount: 1, proposalCount: 1, awards: [award("one"), award("two", true)] }))
  assert.ok(html.includes("1 taska · 1 propozime"))
  assert.ok(html.includes("Propozim për përmirësim") && html.includes("Taskë e vlerësuar"))
  assert.ok(html.includes("Kursen kohë") && html.includes("Manager") && html.includes("Elsa"))
  assert.ok(html.includes("/tasks/task-one") && html.includes("/realization"))
  assert.ok(!html.includes("/tasks/null"))
})

test("zero diamonds have an explicit zero and no empty details panel", () => {
  const html = renderToStaticMarkup(React.createElement(RealizationWeeklyDiamonds, { count: 0, taskCount: 0, proposalCount: 0, awards: [], person: "Elsa" }))
  assert.ok(html.includes("Diamantat e javës · Elsa: 0"))
  assert.ok(!html.includes("<ul"))
})

test("a person with only proposal diamonds remains visible without diamonds in the outer table", () => {
  const first = person("Elsa", { weekly_diamond_count: 2, weekly_task_diamond_count: 1, weekly_proposal_diamond_count: 1, weekly_diamonds: [award("one"), award("two", true)] })
  const second = person("Rinesa", { weekly_diamond_count: 1, weekly_proposal_diamond_count: 1, weekly_diamonds: [award("three", true)] })
  assert.equal(hasWeeklyActivity(first), true)
  assert.equal(weeklyMetrics(first).diamonds, 2)
  const html = renderTable([first, second])
  assert.ok(html.includes("Elsa") && html.includes("Rinesa"))
  assert.ok(!html.includes("Diamanta") && !html.includes("Kursen kohë"))
  assert.equal(diamondCells.length, 0)
})

test("person filter retains diamond-only people without showing their awards outside", () => {
  const html = renderTable([person("Elsa", { weekly_diamond_count: 2, weekly_task_diamond_count: 2 }), person("Rinesa", { weekly_diamond_count: 1, weekly_proposal_diamond_count: 1 })], "Rinesa")
  assert.ok(html.includes("Rinesa") && !html.includes("Elsa"))
  assert.equal(diamondCells.length, 0)
})

test("table keeps ten columns including leave, totals, loading and empty states", () => {
  const leave = person("Elsa", { availability_status: "PV", weekly_diamond_count: 1, weekly_proposal_diamond_count: 1 })
  const html = renderTable([leave])
  assert.equal((html.match(/<col style=/g) || []).length, 10)
  for (const row of html.matchAll(/<tr[^>]*>(.*?)<\/tr>/g)) {
    const width = [...row[1].matchAll(/<(?:td|th)(?:\s[^>]*)?>/g)].reduce((sum, cell) => sum + Number(cell[0].match(/colSpan="(\d+)"/)?.[1] || 1), 0)
    assert.equal(width, 10)
  }
  assert.ok(renderTable([]).includes('colSpan="10"'))
  assert.ok(renderTable([], "ALL", true).includes('colSpan="10"'))
})

test("opening a person renders their diamond details; a closed person section renders none", () => {
  const pageSource = readFileSync(new URL("../src/app/(app)/realization/page.tsx", import.meta.url), "utf8")
  const detailsFragment = pageSource.match(/\{detailsOpen \? <RealizationWeeklyDiamonds[\s\S]*?\/> : null\}/)?.[0]
  assert.ok(detailsFragment)
  const loaded = { exports: {} }
  const { outputText } = ts.transpileModule(`function Details({selected, detailsOpen}) { return <div>${detailsFragment}</div> }; module.exports = Details`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  })
  vm.runInNewContext(outputText, { module: loaded, exports: loaded.exports, require, RealizationWeeklyDiamonds })
  const selected = person("Elsa", { weekly_diamond_count: 2, weekly_task_diamond_count: 1,
    weekly_proposal_diamond_count: 1, weekly_diamonds: [award("one"), award("two", true)] })
  const closed = renderToStaticMarkup(React.createElement(loaded.exports, { selected, detailsOpen: false }))
  assert.ok(!closed.includes("Diamantat"))
  const opened = renderToStaticMarkup(React.createElement(loaded.exports, { selected, detailsOpen: true }))
  assert.ok(opened.includes("Diamantat e javës · Elsa: 2"))
  assert.ok(opened.includes("1 taska · 1 propozime"))
  assert.ok(opened.includes("Kursen kohë"))
})
