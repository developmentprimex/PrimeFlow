import assert from "node:assert/strict"
import test from "node:test"

import { changedManualAnswers, clearSavedManualDraft, readManualDraft, shouldAdvanceReportDay, writeManualDraft } from "../src/lib/m1-reporting-points-draft.ts"
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
  const answers = { reorganization_form: "BZ M1: JO" }
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

test("M1 draft saves ignore the retired plan change answer", () => {
  const original = { plan_changes: "Jo", reorganization: "Jo" }
  assert.deepEqual(changedManualAnswers(original, { ...original, plan_changes: "Po" }), {})
  assert.deepEqual(changedManualAnswers(original, { plan_changes: "Jo" }), { reorganization: "" })
  const storage = memoryStorage()
  writeManualDraft(storage, "user-1", "2026-10-13", original)
  assert.deepEqual(readManualDraft(storage, "user-1", "2026-10-13"), { reorganization: "Jo" })
})

test("M1 refreshes today's unsent report when task columns or order are old", () => {
  const report = { report_date: "2026-10-13", sent_at: null, data: { tasks: [{ id: "task", title: "Title" }] } }
  assert.equal(shouldRegenerateTaskData(report, "2026-10-13"), true)
  assert.equal(shouldRegenerateTaskData(report, "2026-10-14"), false)
  assert.equal(shouldRegenerateTaskData({ ...report, sent_at: "2026-10-13T09:00:00Z" }, "2026-10-13"), false)
  const enriched = { ...report, data: { tasks: [{ id: "task", assignees: "AT", department: "DEV", am_pm: "PM", task_type: "FT", marker: "F", planned_for: "Sot", start_date: "2026-10-13" }] } }
  assert.equal(shouldRegenerateTaskData(enriched, "2026-10-13"), true)
  assert.equal(shouldRegenerateTaskData({ ...enriched, data: { ...enriched.data, task_order_version: 1 } }, "2026-10-13"), true)
  assert.equal(shouldRegenerateTaskData({ ...enriched, data: { ...enriched.data, task_order_version: 1, ga_progress: [], delivery: [] } }, "2026-10-13"), false)
})
