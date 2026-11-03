import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import vm from "node:vm"
import ts from "typescript"

const source = readFileSync(new URL("../src/components/px-notes-workspace.tsx", import.meta.url), "utf8")
const start = source.indexOf("const noteDisplayMarkers =")
const end = source.indexOf("type CommonLeaveItem", start)
assert(start >= 0 && end > start)
const helper = ts.transpileModule(source.slice(start, end), {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText
const display = (note, taskInfo) => JSON.parse(JSON.stringify(vm.runInNewContext(
  helper + "\nnoteDisplayMarkers(note, taskInfo)", { note, taskInfo },
)))
const note = { id: "note", is_converted_to_task: true, one_h_marker: "M3", one_h_marker_comment: "Old comment" }
const bundle = {
  taskId: "task",
  assignees: [{ id: "olsa", full_name: "Olsa Hajdari" }, { id: "second", full_name: "Second" }, { id: "third", full_name: "Third" }],
  assigneeStates: {
    olsa: { oneHMarker: "KA", oneHMarkerByGa: true, oneHMarkerComment: "Olsa comment" },
    second: { oneHMarker: "M2", oneHMarkerComment: "Second comment" },
    third: { oneHMarker: "QUESTION", oneHMarkerComment: "" },
  },
}

test("table displays all three assignee symbols and their own comments instead of the old note symbol", () => {
  const markers = display(note, bundle)
  assert.deepEqual(markers.map(item => item.marker), ["KA", "M2", "QUESTION"])
  assert.deepEqual(markers.map(item => item.person), ["Olsa Hajdari", "Second", "Third"])
  assert.equal(markers[0].byGa, true)
  assert.equal(markers[0].comment, "Olsa comment")
  assert.equal(markers[1].comment, "Second comment")
})

test("changing or clearing a person's symbol is reflected without reviving the note symbol", () => {
  const info = { ...bundle, assigneeStates: { olsa: { oneHMarker: "M2", oneHMarkerComment: "" } } }
  assert.deepEqual(display(note, info).map(item => item.marker), ["M2"])
  info.assigneeStates.olsa.oneHMarker = null
  assert.deepEqual(display(note, info), [])
  assert.deepEqual(display(note), [])
})

test("people with the same symbol retain separate badges", () => {
  const info = { ...bundle, assigneeStates: {
    olsa: { oneHMarker: "KA", oneHMarkerComment: "" },
    second: { oneHMarker: "KA", oneHMarkerComment: "" },
  } }
  assert.deepEqual(display(note, info).map(item => item.key), ["olsa", "second"])
})

test("unconverted notes keep their own symbol", () => {
  assert.equal(display({ ...note, is_converted_to_task: false })[0].marker, "M3")
})

test("symbol filters match any displayed assignee symbol", () => {
  const start = source.indexOf("const matchesOneHMarkerFilter =")
  const end = source.indexOf("const matchesSearchQuery", start)
  const predicate = ts.transpileModule(source.slice(start, end), {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText
  const matches = (oneHMarkerFilter, taskInfo = bundle) => vm.runInNewContext(
    helper + predicate + "\nmatchesOneHMarkerFilter(note)",
    { note, oneHMarkerFilter, noteTaskInfo: new Map([[note.id, taskInfo]]) },
  )
  for (const filter of ["all", "with", "KA", "M2", "QUESTION"]) assert.equal(matches(filter), true)
  for (const filter of ["none", "M3"]) assert.equal(matches(filter), false)
  assert.equal(matches("none", { ...bundle, assigneeStates: {} }), true)
  assert.equal(matches("with", { ...bundle, assigneeStates: {} }), false)
})
