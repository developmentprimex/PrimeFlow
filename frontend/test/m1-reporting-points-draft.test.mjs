import assert from "node:assert/strict"
import test from "node:test"

import { clearSavedManualDraft, readManualDraft, shouldAdvanceReportDay, writeManualDraft } from "../src/lib/m1-reporting-points-draft.ts"
import { shouldRegenerateTaskData } from "../src/lib/m1-reporting-points-data.ts"

function memoryStorage() {
  const values = new Map()
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  }
}

test("M1 manual answers survive reload only for their report day", () => {
  const storage = memoryStorage()
  const answers = { plan_changes: "Po, prioritet i ri", reorganization: "Jo" }
  writeManualDraft(storage, "user-1", "2026-10-13", answers)
  assert.deepEqual(readManualDraft(storage, "user-1", "2026-10-13"), answers)
  assert.equal(readManualDraft(storage, "user-1", "2026-10-14"), null)
  clearSavedManualDraft(storage, "user-1", "2026-10-13", answers)
  assert.equal(readManualDraft(storage, "user-1", "2026-10-13"), null)
})

test("M1 moves to tomorrow only after today's edits are saved", () => {
  assert.equal(shouldAdvanceReportDay("2026-10-13", "2026-10-13", "2026-10-14", false), true)
  assert.equal(shouldAdvanceReportDay("2026-10-13", "2026-10-13", "2026-10-14", true), false)
  assert.equal(shouldAdvanceReportDay("2026-10-12", "2026-10-13", "2026-10-14", false), false)
})

test("M1 refreshes today's unsent report when task columns or order are old", () => {
  const report = { report_date: "2026-10-13", sent_at: null, data: { tasks: [{ id: "task", title: "Title" }] } }
  assert.equal(shouldRegenerateTaskData(report, "2026-10-13"), true)
  assert.equal(shouldRegenerateTaskData(report, "2026-10-14"), false)
  assert.equal(shouldRegenerateTaskData({ ...report, sent_at: "2026-10-13T09:00:00Z" }, "2026-10-13"), false)
  const enriched = { ...report, data: { tasks: [{ id: "task", assignees: "AT", department: "DEV", am_pm: "PM", task_type: "FT" }] } }
  assert.equal(shouldRegenerateTaskData(enriched, "2026-10-13"), true)
  assert.equal(shouldRegenerateTaskData({ ...enriched, data: { ...enriched.data, task_order_version: 1 } }, "2026-10-13"), false)
})
