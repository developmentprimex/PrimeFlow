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
const utils = { cn: (...values) => values.filter(Boolean).join(" ") }
const { dailyRealizationTableItems, dailyRealizationColumnKind } = load("../src/lib/realization-table-items.ts")
const { RealizationPlanStatusGrid, RealizationDeadlineStatusGrid } = load("../src/components/realization-plan-status-grid.tsx")
const { RealizationTaskList } = load("../src/components/realization-task-list.tsx", {
  "@/lib/utils": utils,
  "@/components/realization-deadline-tasks": { firstLineTitle: title => title.split("\n")[0] },
})
const item = (task_id, overrides = {}) => ({ task_id, title: `Detyra ${task_id}`, kind: "NO_PROGRESS", planned: true, share: 1, credit: 0, penalty: 0, approved: false, deadline: true, critical: false, ...overrides })
const deadline = (task_id, state, overrides = {}) => ({ task_id, title: `Detyra ${task_id}`, state, critical: false, day: null, ...overrides })

test("extra deadlines use the existing three status columns without changing metrics or confirmation evidence", () => {
  const metrics = {
    realization_items: [item("p", { kind: "EXTRA_OPEN", planned: false, penalty: 50, confirmation_evidence_key: "evidence" }), item("n", { kind: "EXTRA_OPEN", planned: false })],
    deadline_tasks: [deadline("p", "IN_PROGRESS"), deadline("n", "NO_PROGRESS"), deadline("s", "POSTPONED")],
    raw_plan_realization: 37.9,
  }
  const before = JSON.stringify(metrics)
  const items = dailyRealizationTableItems(metrics, [{ task_id: "s", in_original_plan: false, classification: "POSTPONED_APPROVED" }])
  assert.equal(items.length, 3)
  assert.equal(items[0].kind, "IN_PROGRESS")
  assert.equal(items[1].kind, "NO_PROGRESS")
  assert.equal(items[2].kind, "POSTPONED")
  assert.equal(items[2].planned, false)
  assert.equal(items[2].approved, true)
  assert.equal(items[0].penalty, 50)
  assert.equal(items[0].confirmation_evidence_key, "evidence")
  assert.equal(JSON.stringify(metrics), before)
})

test("deadline tasks missing from realization items stay visible and equal titles with distinct IDs stay separate", () => {
  const metrics = { realization_items: [item("a")], deadline_tasks: [deadline("a", "NO_PROGRESS"), deadline("b", "COMPLETED", { title: "Detyra a" })] }
  const items = dailyRealizationTableItems(metrics)
  assert.equal(items.length, 2)
  assert.equal(items[1].kind, "COMPLETED")
  assert.equal(items[1].task_id, "b")
})

test("only task titles are shown; unfinished deadlines stay red even when penalties are waived", () => {
  for (const kind of ["IN_PROGRESS", "POSTPONED", "NO_PROGRESS"]) {
    const html = renderToStaticMarkup(React.createElement(RealizationTaskList, {
      items: [item(kind, { kind, critical: true, share: 0.5, credit: 0.5, penalty: 25, confirmation: { confirmed: true } })], onSelect() {},
    }))
    assert.match(html, /font-bold text-red-700/)
    assert.doesNotMatch(html, /border-l-4|bg-red|Deadline|Due date|pa penalizim|pikë|në ditë/)
    assert.match(html.replace(/<[^>]+>/g, ""), new RegExp(`^${kind === "POSTPONED" ? "Shtyrë:" : ""}Detyra ${kind}$`))
    assert.match(html, /<button/)
  }
  const html = renderToStaticMarkup(React.createElement(RealizationTaskList, { items: [item("done", { kind: "EXTRA_COMPLETED" })], onSelect() {} }))
  assert.doesNotMatch(html, /text-red|Due date|<span/)
  assert.match(html, /text-slate-800/)
})

test("ordinary work has no deadline alarm, while deadline cards can identify a deadline missing from item flags", () => {
  const ordinary = item("a", { deadline: false, critical: true })
  const render = deadlines => renderToStaticMarkup(React.createElement(RealizationTaskList, { items: [ordinary], deadlines, onSelect() {} }))
  assert.doesNotMatch(render([]), /text-red/)
  assert.match(render([deadline("a", "NO_PROGRESS")]), /font-bold text-red-700/)
})

test("daily postponed and idle tasks share a column while their real kind and evidence remain intact", () => {
  const postponed = item("s", { kind: "POSTPONED", confirmation_evidence_key: "original" })
  const idle = item("n")
  const completed = item("done", { kind: "COMPLETED" })
  const combined = [postponed, idle, completed].filter(row => dailyRealizationColumnKind(row.kind) === "NO_PROGRESS")
  assert.equal(combined.length, 2)
  assert.equal(combined[0], postponed)
  assert.equal(combined[0].kind, "POSTPONED")
  assert.equal(combined[0].confirmation_evidence_key, "original")
  assert.equal(dailyRealizationColumnKind("IN_PROGRESS"), "IN_PROGRESS")
})

test("weekly grids merge idle and postponed totals once, retaining the postponed subset and critical alarms", () => {
  const props = { completed: 1, progress: 2, postponed: 3, noProgress: 4, combinePostponed: true, critical: { completed: 0, progress: 0, postponed: 2, noProgress: 1 } }
  for (const component of [RealizationPlanStatusGrid, RealizationDeadlineStatusGrid]) {
    const html = renderToStaticMarkup(React.createElement(component, props))
    assert.match(html, /grid-cols-3/)
    assert.match(html, /aria-label="Pa progres: 7"/)
    assert.match(html, /3 shtyrë/)
    assert.doesNotMatch(html, /aria-label="Shtyrë: 3"/)
    const separate = renderToStaticMarkup(React.createElement(component, { ...props, combinePostponed: false }))
    assert.match(separate, /grid-cols-4/)
    assert.match(separate, /aria-label="Shtyrë: 3"/)
    assert.match(separate, /aria-label="Pa progres: 4"/)
  }
  const html = renderToStaticMarkup(React.createElement(RealizationDeadlineStatusGrid, props))
  assert.match(html, /alarm: 3 me deadline important/)
})
