import assert from "node:assert/strict"
import { test } from "node:test"
import { taskMarkers as markers } from "./helpers/task-markers.mjs"

test("two symbols can be selected, removed and replaced without accepting a third", () => {
  let value = markers.toggleTaskMarker(null, "CLIENT_URGENT")
  value = markers.toggleTaskMarker(value, "M3")
  assert.equal(value, "CLIENT_URGENT,M3")
  assert.equal(markers.toggleTaskMarker(value, "KA"), value)
  value = markers.toggleTaskMarker(value, "M3")
  assert.equal(value, "CLIENT_URGENT")
  value = markers.toggleTaskMarker(value, "KA")
  assert.equal(value, "CLIENT_URGENT,KA")
  assert.equal(markers.toggleTaskMarker("KA", "KA"), null)
})

test("existing and combined symbols retain their order and GA attribution", () => {
  assert.equal(markers.taskMarkerLabel("CLIENT_URGENT"), "!!!")
  assert.equal(markers.taskMarkerLabel("CLIENT_URGENT,M3"), "!!! + M3")
  assert.equal(markers.taskMarkerLabel("M3,CLIENT_URGENT", true), "(M3 + !!!)")
  assert.equal(markers.taskMarkerLabel(null), "")
  assert.equal(markers.taskMarkerLabel("__none__"), "")
})
