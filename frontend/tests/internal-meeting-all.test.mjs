import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import ts from "typescript"

const source = readFileSync(new URL("../src/app/(app)/common/page.tsx", import.meta.url), "utf8")

function meetingSelection(participantIds = []) {
  const code = source.match(/  const internalMeetingActivePersons =[\s\S]*?(?=  const selectedCommonUserLabel =)/)?.[0]
  assert.ok(code, "Common View defines the internal meeting selection")
  let selectedIds = participantIds
  let departmentId = "development"
  let selectAll = false
  const users = [
    { id: "dev-user", isActive: true },
    { id: "design-user", isActive: true },
    { id: "inactive-user", isActive: false },
  ]
  const evaluate = new Function(
    "commonUserFilterOptions", "internalMeetingParticipantIds", "internalMeetingSelectAll",
    "setInternalMeetingParticipantIds", "setInternalMeetingDepartmentId", "setInternalMeetingSelectAll",
    ts.transpileModule(code + "\nreturn { internalMeetingAllSelected, selectInternalMeetingDepartment }", {
      compilerOptions: { target: ts.ScriptTarget.ES2020 },
    }).outputText,
  )
  return {
    ids: () => selectedIds,
    department: () => departmentId,
    selection: () => evaluate(users, selectedIds, selectAll,
      (ids) => { selectedIds = ids }, (id) => { departmentId = id }, (all) => { selectAll = all }),
  }
}

test("ALL selects active staff across departments and retains the meeting department", () => {
  const form = meetingSelection(["dev-user"])
  assert.equal(form.selection().internalMeetingAllSelected, false)
  form.selection().selectInternalMeetingDepartment("__all__")
  assert.deepEqual(form.ids(), ["dev-user", "design-user"])
  assert.equal(form.department(), "development")
  assert.equal(form.selection().internalMeetingAllSelected, true)
})

test("selecting a department after ALL clears the bulk selection", () => {
  const form = meetingSelection()
  form.selection().selectInternalMeetingDepartment("__all__")
  form.selection().selectInternalMeetingDepartment("graphic-design")
  assert.deepEqual(form.ids(), [])
  assert.equal(form.department(), "graphic-design")
  assert.equal(form.selection().internalMeetingAllSelected, false)
})

test("changing departments preserves a manual partial selection", () => {
  const form = meetingSelection(["dev-user"])
  form.selection().selectInternalMeetingDepartment("graphic-design")
  assert.deepEqual(form.ids(), ["dev-user"])
  assert.equal(form.department(), "graphic-design")
})
