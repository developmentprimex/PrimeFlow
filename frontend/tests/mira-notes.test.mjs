import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import vm from "node:vm"
import ts from "typescript"

const source = readFileSync(new URL("../src/components/px-notes-workspace.tsx", import.meta.url), "utf8")
const start = source.indexOf("const matchesTaskStatusFilter = (note: GaNote) => {")
const end = source.indexOf("const matchesContentFilter", start)
assert(start >= 0 && end > start)
const predicate = ts.transpileModule(source.slice(start, end), { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
function matches(note, taskStatusFilter, noteTaskInfo = new Map()) {
  return vm.runInNewContext(predicate + "\nmatchesTaskStatusFilter(note)", {
    note, taskStatusFilter, noteTaskInfo,
    normalizeTaskStatus: value => value || "UNKNOWN", aggregateTaskStatus: values => values[0],
  })
}

test("Mira notes enter regular PX filters only after explicit sharing", () => {
  for (const status of ["OPEN", "CLOSED"]) for (const converted of [true, false]) {
    const note = { id: "mira", from_mira: true, status, is_converted_to_task: converted }
    for (const filter of ["all", "notes", "tasks", "open", "closed", "TODO", "IN_PROGRESS", "DONE"]) {
      assert.equal(matches(note, filter), false)
    }
    assert.equal(matches({ ...note, mira_shared_to_px: true }, "all"), true)
    assert.equal(matches({ ...note, mira_shared_to_px: true }, "tasks"), converted)
    assert.equal(matches({ ...note, mira_shared_to_px: true }, "closed"), status === "CLOSED")
    assert.equal(matches(note, "mira"), !converted && status !== "CLOSED")
  }
})

test("regular notes and shared Mira tasks retain their ordinary status filters", () => {
  const regular = { id: "regular", status: "OPEN" }
  assert.equal(matches(regular, "all"), true)
  assert.equal(matches(regular, "notes"), true)
  assert.equal(matches(regular, "mira"), false)
  const miraTask = { id: "task", from_mira: true, mira_shared_to_px: true, is_converted_to_task: true }
  const taskInfo = new Map([["task", { taskStatus: "TODO" }]])
  assert.equal(matches(miraTask, "TODO", taskInfo), true)
  assert.equal(matches(miraTask, "DONE", taskInfo), false)
})

test("explicitly shared older closed Mira notes remain visible in the default all range", () => {
  const start = source.indexOf("const withinRange = (note: GaNote) => {")
  const end = source.indexOf("const matchesTaskStatusFilter", start)
  const predicate = ts.transpileModule(source.slice(start, end), { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
  const old = { from_mira: true, mira_shared_to_px: true, status: "CLOSED", completed_at: "2026-01-01T00:00:00Z" }
  const check = (note, rangeFilter) => vm.runInNewContext(predicate + "\nwithinRange(note)", {
    note, rangeFilter, closedCutoff: Date.parse("2026-09-28"), weekAgo: Date.parse("2026-10-21"),
  })
  assert.equal(check(old, "all"), true)
  assert.equal(check({ ...old, mira_shared_to_px: false }, "all"), false)
  assert.equal(check(old, "week"), false)
})
