import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import { test } from "node:test"
import vm from "node:vm"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import ts from "typescript"

const require = createRequire(import.meta.url)
function load(file, imports = {}) {
  const module = { exports: {} }
  const source = readFileSync(new URL(file, import.meta.url), "utf8")
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
  })
  vm.runInNewContext(outputText, {
    module, exports: module.exports,
    require: (name) => imports[name] ?? require(name),
  })
  return module.exports
}

const { canceledMeetingIds } = load("../src/lib/use-canceled-meetings.ts", {
  "@/lib/auth": {}, "@/lib/use-visible-refresh": {},
})
const rows = [
  { meeting_id: "external", occurrence_date: "2026-10-22", status: "canceled" },
  { meeting_id: "held", occurrence_date: "2026-10-22", status: "held" },
  { meeting_id: "other-day", occurrence_date: "2026-10-21", status: "canceled" },
]

test("cancellation applies only to its meeting occurrence date", () => {
  assert.deepEqual([...canceledMeetingIds(rows, "2026-10-22")], ["external"])
  assert.deepEqual([...canceledMeetingIds(rows, "2026-10-23")], [])
})

test("daily report retains external meeting and labels only canceled occurrences", () => {
  const badge = load("../src/components/meeting-canceled-badge.tsx")
  const { DailyReportMeetingsTable } = load("../src/components/daily-report-meetings-table.tsx", {
    "@/components/meeting-canceled-badge": badge,
    "@/lib/use-canceled-meetings": { useCanceledMeetings: (day) => canceledMeetingIds(rows, day) },
  })
  const meetings = ["external", "held"].map((id) => ({
    id, title: id, meeting_type: "external", starts_at: "2026-10-22T09:00:00",
    recurrence_type: "weekly", recurrence_days_of_week: [3],
  }))
  const render = (day) => renderToStaticMarkup(React.createElement(DailyReportMeetingsTable, {
    meetings, users: [], reportDateIso: day,
  }))
  const canceledDay = render("2026-10-22")
  assert.match(canceledDay, /external/)
  assert.match(canceledDay, /held/)
  assert.equal((canceledDay.match(/ANULUAR/g) || []).length, 1)
  assert.doesNotMatch(render("2026-10-29"), /ANULUAR/)
})
