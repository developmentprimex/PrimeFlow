import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import ts from "typescript"

process.env.TZ = "Europe/Tirane"
const source = readFileSync(new URL("../src/lib/meeting-overview-columns.ts", import.meta.url), "utf8")
const module = { exports: {} }
new Function("module", "exports", ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText)(module, module.exports)
const { isRecurringOverviewMeeting, meetingOverviewDateTime } = module.exports

test("past one-off meetings show their actual local date even across midnight", () => {
  const row = { meeting: { starts_at: "2026-11-09T23:30:00Z", recurrence_type: null }, next_session: null, last_session: "2026-11-10" }
  assert.equal(meetingOverviewDateTime(row), "10.11.2026 · 00:30")
  assert.equal(isRecurringOverviewMeeting(row), false)
})

test("recurring meetings use the upcoming occurrence and preserve the scheduled local clock across DST", () => {
  const row = { meeting: { starts_at: "2026-09-01T07:30:00Z", recurrence_type: "weekly" }, next_session: "2026-11-13", last_session: "2026-11-06" }
  assert.equal(meetingOverviewDateTime(row), "13.11.2026 · 09:30")
  assert.equal(isRecurringOverviewMeeting(row), true)
  assert.equal(meetingOverviewDateTime({ ...row, next_session: null }), "06.11.2026 · 09:30")
})

test("missing or invalid starts do not invent a meeting time", () => {
  for (const starts_at of [null, undefined, "invalid"]) {
    assert.equal(meetingOverviewDateTime({ meeting: { starts_at }, next_session: "2026-11-13" }), "—")
  }
  for (const recurrence_type of ["monthly", "yearly", "WEEKLY"]) {
    assert.equal(isRecurringOverviewMeeting({ meeting: { recurrence_type } }), true)
  }
})
