import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import { test } from "node:test"
import vm from "node:vm"
import ts from "typescript"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"

const require = createRequire(import.meta.url)
const source = readFileSync(new URL("../src/components/realization-weekly-postponements.tsx", import.meta.url), "utf8")
const markup = { exports: {} }
const markupSource = readFileSync(new URL("../src/lib/note-markup.tsx", import.meta.url), "utf8")
vm.runInNewContext(ts.transpileModule(markupSource, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText, { module: markup, exports: markup.exports, require })
const loaded = { exports: {} }
const reasons = { exports: {} }
vm.runInNewContext(ts.transpileModule(readFileSync(new URL("../src/lib/daily-rlz-ui.ts", import.meta.url), "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
}).outputText, { module: reasons, exports: reasons.exports })
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } })
vm.runInNewContext(outputText, { module: loaded, exports: loaded.exports, require: name => name === "@/lib/note-markup" ? markup.exports :
  name === "@/lib/daily-rlz-ui" ? reasons.exports :
  name === "@/components/ui/button" ? { Button: props => React.createElement("button", props) } :
  name === "@/components/ui/textarea" ? { Textarea: props => React.createElement("textarea", props) } : require(name) })
const { weeklyPostponements, RealizationWeeklyPostponements } = loaded.exports
const task = { task_id: "task1", title: "First line\nHidden second line", adjustment_status: "PENDING", timeline: [
  { id: "event1", type: "POSTPONED", old_value: "2026-10-05", new_value: "2026-10-09" },
] }
const report = tasks => ({ facts_json: { daily_timeline: tasks.map((items, index) => ({ date: `2026-10-0${index + 5}`, tasks: items })) } })

test("repeated daily appearances show one task and its latest postponement", () => {
  const latest = { ...task, timeline: [...task.timeline, { id: "event2", type: "POSTPONED_AGAIN" }] }
  const rows = weeklyPostponements(report([[task], [latest]]))
  assert.equal(rows.length, 1)
  assert.equal(rows[0].event.id, "event2")
})
test("only first title line is displayed and read-only users cannot approve", () => {
  const result = report([[task]])
  const html = renderToStaticMarkup(React.createElement(RealizationWeeklyPostponements, { result, canEdit: false, busy: false }))
  assert.ok(html.includes("First line"))
  assert.ok(!html.includes("Hidden second line"))
  assert.ok(!html.includes("<button"))
})
test("approved tasks show the decision and no approval action", () => {
  const result = report([[{ ...task, adjustment_status: "APPROVED", manager_decision: { decided_by_name: "Manager" } }]])
  const html = renderToStaticMarkup(React.createElement(RealizationWeeklyPostponements, { result, canEdit: true, busy: false }))
  assert.ok(html.includes("Aprovuar"))
  assert.ok(html.includes("Manager"))
  assert.ok(!html.includes("<button"))
})
test("the original postponement reason and comment remain separate from the manager decision", () => {
  const result = report([[{ ...task, timeline: [{ ...task.timeline[0], metadata: { reason: "WAITING_CLIENT", comment: "Original user explanation" } }],
    manager_decision: { comment: "Manager decision comment" } }]])
  const html = renderToStaticMarkup(React.createElement(RealizationWeeklyPostponements, { result, canEdit: false, busy: false }))
  assert.match(html, /Original user explanation/)
  assert.match(html, /Manager decision comment/)
  assert.match(html, /Arsyeja e shtyrjes/)
})
