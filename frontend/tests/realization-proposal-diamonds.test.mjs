import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import vm from "node:vm"
import { test } from "node:test"
import ts from "typescript"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"

const require = createRequire(import.meta.url)
function evaluate(source, globals = {}, overrides = {}) {
  const loaded = { exports: {} }
  const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } })
  vm.runInNewContext(outputText, { module: loaded, exports: loaded.exports, require: name => overrides[name] || require(name), ...globals })
  return loaded.exports
}
const noticeSource = readFileSync(new URL("../src/components/realization-proposal-notice.tsx", import.meta.url), "utf8")
const { RealizationProposalNotice } = evaluate(noticeSource)
const cellsSource = readFileSync(new URL("../src/components/realization-review-cells.tsx", import.meta.url), "utf8")
const rowSource = cellsSource.slice(cellsSource.indexOf("function ManualQuestion("), cellsSource.indexOf("export function RealizationReviewCells"))
const ManualQuestion = evaluate(rowSource + "\nmodule.exports = ManualQuestion", {
  Textarea: "textarea", Button: "button", RealizationProposalNotice,
  cn: (...values) => values.filter(Boolean).join(" "),
})

function renderRow(value, comment, { touched = true, proposal = true } = {}) {
  return renderToStaticMarkup(React.createElement("table", null, React.createElement("tbody", null,
    React.createElement(ManualQuestion, {
      number: 11, label: "A dha propozim për përmirësim këtë ditë?", proposal,
      draft: { values: [value], comment, touched }, disabled: false, onChange: () => {}, onSaveComment: () => {},
    }))))
}

test("proposal question is emphasized and explains the automatic diamond", () => {
  const html = renderRow("NO", "")
  assert.ok(html.includes("border-cyan-300"))
  assert.ok(html.includes("font-bold text-cyan-950"))
  assert.ok(html.includes("Po me koment jep automatikisht 1 diamant"))
  assert.ok(html.includes("Javori përmbledh"))
})

test("Yes requires the proposal description and a whitespace-only comment blocks saving", () => {
  for (const comment of ["", "  \n\t"]) {
    const html = renderRow("YES", comment)
    assert.ok(/<textarea[^>]* required=""/.test(html))
    assert.ok(/<button[^>]*disabled=""/.test(html))
    assert.ok(html.includes("Përshkruaj propozimin dhe përfitimin"))
    assert.ok(html.includes("rows=\"3\""))
  }
})

test("Yes with a description permits saving and saved answer shows one diamond", () => {
  const draft = renderRow("YES", "Automatizimi kursen 20 minuta")
  assert.ok(!/<button[^>]*disabled=""/.test(draft))
  assert.ok(draft.includes("merr automatikisht 1 diamant"))
  const saved = renderRow("YES", "Automatizimi kursen 20 minuta", { touched: false })
  assert.ok(saved.includes("1 diamant për propozimin"))
  assert.ok(saved.includes("Reviews dhe te Common"))
  assert.ok(saved.includes("nuk jep diamant tjetër"))
})

test("other questions keep their normal style and have no diamond notice", () => {
  const html = renderRow("NO", "", { proposal: false })
  assert.ok(!html.includes("border-cyan-300"))
  assert.ok(!html.includes("diamant"))
  assert.ok(!/<textarea[^>]* required=""/.test(html))
})

test("Reviews renders proposal origins without invalid task links or task review actions", () => {
  const overview = {
    completed_count: 0, reviewed_count: 0, unreviewed_count: 0, diamonds_total: 1, proposal_count: 1, users: [],
    rows: [{ task_id: null, task_title: "Propozim për përmirësim", source: "REALIZATION_PROPOSAL", reviewee_user_id: "elsa",
      reviewee_name: "Elsa", completed_at: "2026-10-13T12:00:00Z", review: { id: "answer-result", comment: "Kursen kohë" } }],
  }
  const react = { ...React, useEffect: () => {}, useState: initial => [typeof initial === "object" && initial?.rows ? overview : initial === true ? false : initial, () => {}] }
  const element = tag => ({ children, className, title, href, disabled }) => React.createElement(tag, { className, title, href, disabled }, children)
  const ui = names => Object.fromEntries(names.map(name => [name, element(name.startsWith("Table") ? "div" : "div")]))
  const source = readFileSync(new URL("../src/app/(app)/reviews/page.tsx", import.meta.url), "utf8")
  const { default: ReviewsPage } = evaluate(source, {}, {
    react, "next/link": { default: element("a") },
    "@/components/task-review-dialog": { DiamondAward: () => "Diamond", TaskReviewDialog: () => null },
    "@/components/providers/confirm-dialog-provider": { useConfirm: () => () => {} },
    "@/lib/auth": { useAuth: () => ({ apiFetch: () => {}, user: { id: "manager", role: "MANAGER" } }) },
    "@/lib/dates": { formatDateDMY: value => value }, "@/lib/note-markup": { getPlainMarkedText: value => value },
    "@/components/ui/badge": ui(["Badge"]), "@/components/ui/button": { Button: element("button") },
    "@/components/ui/card": ui(["Card", "CardContent", "CardHeader", "CardTitle"]),
    "@/components/ui/input": { Input: element("input") }, "@/components/ui/label": { Label: element("label") },
    "@/components/ui/select": ui(["Select", "SelectContent", "SelectItem", "SelectTrigger", "SelectValue"]),
    "@/components/ui/table": ui(["Table", "TableBody", "TableCell", "TableHead", "TableHeader", "TableRow"]),
  })
  const html = renderToStaticMarkup(React.createElement(ReviewsPage))
  assert.ok(html.includes("Propozim · Realizimi"))
  assert.ok(html.includes("Kursen kohë"))
  assert.ok(html.includes("href=\"/realization\""))
  assert.ok(!html.includes("/tasks/null"))
  assert.ok(!html.includes("Delete review"))
  assert.ok(!html.includes("Self-review disabled"))
})
