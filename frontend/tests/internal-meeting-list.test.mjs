import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import vm from "node:vm"
import ts from "typescript"

const source = readFileSync(new URL("../src/lib/internal-meeting-list.ts", import.meta.url), "utf8")
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } })
const module = { exports: {} }
vm.runInNewContext(outputText, { module, exports: module.exports, Date })
const { internalMeetingWeekDate, internalMeetingDateOn } = module.exports
const now = new Date(2026, 9, 22, 12)
const meeting = (starts_at, extra = {}) => ({ starts_at, recurrence_type: "none", ...extra })

test("week filters include Monday through Sunday and exclude the following Monday", () => {
  assert.ok(internalMeetingWeekDate(meeting("2026-10-19T00:00:00"), "this_week", now))
  assert.ok(internalMeetingWeekDate(meeting("2026-10-25T23:59:59"), "this_week", now))
  assert.equal(internalMeetingWeekDate(meeting("2026-10-26T00:00:00"), "this_week", now), null)
  assert.ok(internalMeetingWeekDate(meeting("2026-10-26T00:00:00"), "next_week", now))
  assert.ok(internalMeetingWeekDate(meeting("2026-11-01T23:59:59"), "next_week", now))
  assert.equal(internalMeetingWeekDate(meeting("2026-11-02T00:00:00"), "next_week", now), null)
})

test("recurring meetings resolve inside the requested week, including already held weekdays", () => {
  const weekly = meeting("2026-09-01T09:30:00", { recurrence_type: "weekly", recurrence_days_of_week: [0] })
  const thisWeek = internalMeetingWeekDate(weekly, "this_week", now)
  const nextWeek = internalMeetingWeekDate(weekly, "next_week", now)
  assert.equal(thisWeek.getDate(), 19)
  assert.equal(nextWeek.getDate(), 26)
  assert.equal(nextWeek.getHours(), 9)
  assert.equal(nextWeek.getMinutes(), 30)
})

test("monthly and yearly recurrence use the requested week", () => {
  const monthly = meeting("2026-01-01T10:00:00", { recurrence_type: "monthly", recurrence_days_of_month: [30] })
  assert.equal(internalMeetingWeekDate(monthly, "this_week", now), null)
  assert.equal(internalMeetingWeekDate(monthly, "next_week", now).getDate(), 30)
  const yearly = meeting("2025-10-24T10:00:00", { recurrence_type: "yearly", recurrence_days_of_month: [24] })
  assert.equal(internalMeetingWeekDate(yearly, "this_week", now).getDate(), 24)
  assert.equal(internalMeetingWeekDate(yearly, "next_week", now), null)
})

test("Sunday remains in the current week and invalid dates are excluded", () => {
  const sunday = new Date(2026, 9, 25, 23)
  assert.ok(internalMeetingWeekDate(meeting("2026-10-19T10:00:00"), "this_week", sunday))
  assert.equal(internalMeetingWeekDate(meeting("invalid"), "next_week", now), null)
  assert.equal(internalMeetingWeekDate(meeting("2026-10-22T10:00:00"), "all", now), null)
})

test("date filter includes only the chosen local day", () => {
  assert.ok(internalMeetingDateOn(meeting("2026-10-22T00:00:00"), "2026-10-22"))
  assert.ok(internalMeetingDateOn(meeting("2026-10-22T23:59:59"), "2026-10-22"))
  assert.equal(internalMeetingDateOn(meeting("2026-10-23T00:00:00"), "2026-10-22"), null)
  assert.equal(internalMeetingDateOn(meeting("2026-10-21T23:59:59"), "2026-10-22"), null)
})

test("date filter resolves recurring meetings on that day at their original time", () => {
  const weekly = meeting("2026-09-01T09:30:00", { recurrence_type: "weekly", recurrence_days_of_week: [3] })
  const occurrence = internalMeetingDateOn(weekly, "2026-10-29")
  assert.equal(occurrence.getDate(), 29)
  assert.equal(occurrence.getHours(), 9)
  assert.equal(occurrence.getMinutes(), 30)
  assert.equal(internalMeetingDateOn(weekly, "2026-10-30"), null)
})

test("date filter rejects empty, malformed and nonexistent dates", () => {
  const item = meeting("2026-10-22T10:00:00")
  for (const date of ["", "22/10/2026", "2026-02-30", "2026-13-01"]) {
    assert.equal(internalMeetingDateOn(item, date), null)
  }
})
