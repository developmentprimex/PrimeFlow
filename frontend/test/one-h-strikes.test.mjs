import assert from "node:assert/strict"
import test from "node:test"
import { applyTaskStrikeBadges, taskStrikeBadge, taskHasStrikes, reportStrikeTotal } from "../src/lib/one-h-strikes.ts"

const summary = {
  report_date: "2026-10-19", captured_at: "2026-10-19T11:30:00+02:00", active_slot: "11:00",
  active_interval: { start: "10:00", end: "11:00" },
  intervals: { "10:00": { start: "08:00", end: "10:00" }, "11:00": { start: "10:00", end: "11:00" } },
  tasks: { task: { "10:00": 3, "11:00": 0 } },
}

test("at 11:30 a task uses the last finished interval and displays zero despite earlier strikes", () => {
  assert.deepEqual(taskStrikeBadge(summary, "task"), { count: 0, label: "Strikes: 0 · 10:00–11:00" })
  assert.equal(taskStrikeBadge(summary, "missing"), null)
})

function cell(dataset, row = null) {
  return { dataset, badge: null, closest: () => row,
    querySelector() { return this.badge }, append(badge) { this.badge = badge } }
}

test("all cards use the active interval regardless of their row or saved slot", () => {
  const headingRow = { querySelectorAll: () => [{ textContent: "1" }, { textContent: "1H 10:00\nAT • HSH" }] }
  const continuationRow = { querySelectorAll: () => [], previousElementSibling: headingRow }
  const cards = [cell({ taskId: "task", taskOneHSlot: "11:00" }), cell({ taskId: "task" }, continuationRow)]
  const document = { querySelectorAll: () => cards, createElement: () => ({ dataset: {}, style: {} }) }
  applyTaskStrikeBadges(document, summary)
  assert.equal(cards[0].badge.textContent, "Strikes: 0 · 10:00–11:00")
  assert.equal(cards[1].badge.textContent, "Strikes: 0 · 10:00–11:00")
  const badge = cards[0].badge
  applyTaskStrikeBadges(document, { ...summary, tasks: { task: { "10:00": 3, "11:00": 2 } } })
  assert.equal(cards[0].badge, badge)
  assert.equal(badge.textContent, "Strikes: 2 · 10:00–11:00")
})

test("at 14:38 all cards show only strikes from the finished 11:50 to 14:20 interval", () => {
  const afternoon = { ...summary, active_slot: "14:20", active_interval: { start: "11:50", end: "14:20" },
    intervals: { ...summary.intervals, "14:20": { start: "11:50", end: "14:20" }, "16:00": { start: "14:20", end: "16:00" } },
    tasks: { task: { "10:00": 7, "14:20": 1, "16:00": 2 } } }
  assert.deepEqual(taskStrikeBadge(afternoon, "task"), { count: 1, label: "Strikes: 1 · 11:50–14:20" })
})

test("before 10:00 no incomplete interval count is displayed", () => {
  assert.equal(taskStrikeBadge({ ...summary, active_slot: null, active_interval: null }, "task"), null)
})

test("the strikes filter includes only positive counts in the last finished interval", () => {
  const counts = { ...summary, tasks: {
    positive: { "10:00": 0, "11:00": 2 },
    earlierOnly: { "10:00": 3, "11:00": 0 },
    zero: { "10:00": 0, "11:00": 0 },
  } }
  const tasks = ["positive", "earlierOnly", "zero", "missing"]
  assert.deepEqual(tasks.filter(id => taskHasStrikes(counts, id)), ["positive"])
  assert.equal(taskHasStrikes(undefined, "positive"), false)
  assert.equal(taskHasStrikes({ ...counts, active_slot: null }, "positive"), false)
  assert.deepEqual(tasks.filter(id => taskHasStrikes({ ...counts, active_slot: "10:00" }, id)), ["earlierOnly"])
})

test("the strikes filter composes with other filters and responds to refreshed counts", () => {
  const counts = { ...summary, tasks: { ef: { "11:00": 2 }, ra: { "11:00": 3 }, noStrikes: { "11:00": 0 } } }
  const tasks = [{ id: "ef", user: "EF" }, { id: "ra", user: "RA" }, { id: "noStrikes", user: "EF" }]
  const filter = data => tasks.filter(task => task.user === "EF" && taskHasStrikes(data, task.id))
  assert.deepEqual(filter(counts).map(task => task.id), ["ef"])
  assert.deepEqual(filter({ ...counts, tasks: { ...counts.tasks, ef: { "11:00": 0 }, noStrikes: { "11:00": 1 } } }).map(task => task.id), ["noStrikes"])
})

test("the total sums only the last completed interval across unique task IDs", () => {
  const counts = { ...summary, tasks: {
    sharedTask: { "10:00": 7, "11:00": 3 },
    anotherTask: { "10:00": 5, "11:00": 2 },
    zeroTask: { "11:00": 0 },
    earlierOnly: { "10:00": 4 },
  } }
  assert.deepEqual(reportStrikeTotal(counts), { count: 5, label: "Total strikes: 5 · 10:00–11:00" })
  // Rendering a shared task on multiple cards does not modify the task map.
  const cards = [cell({ taskId: "sharedTask" }), cell({ taskId: "sharedTask" }), cell({ taskId: "anotherTask" })]
  applyTaskStrikeBadges({ querySelectorAll: () => cards, createElement: () => ({ dataset: {}, style: {} }) }, counts)
  assert.equal(reportStrikeTotal(counts).count, 5)
})

test("the total supports zero, missing reports, and the transition to another completed interval", () => {
  assert.deepEqual(reportStrikeTotal(summary), { count: 0, label: "Total strikes: 0 · 10:00–11:00" })
  assert.equal(reportStrikeTotal(undefined), null)
  assert.equal(reportStrikeTotal({ ...summary, active_slot: null, active_interval: null }), null)
  assert.deepEqual(reportStrikeTotal({ ...summary, active_slot: "10:00", active_interval: null }),
    { count: 3, label: "Total strikes: 3 · 08:00–10:00" })
  assert.equal(reportStrikeTotal({ ...summary, tasks: { task: { "11:00": 4 } } }).count, 4)
})
