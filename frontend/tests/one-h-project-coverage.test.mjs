import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import vm from "node:vm"
import ts from "typescript"

const source = readFileSync(new URL("../src/lib/one-h-project-coverage.ts", import.meta.url), "utf8")
const loaded = { exports: {} }
vm.runInNewContext(ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText, { module: loaded, exports: loaded.exports })
const { projectUsersForOneHSlot } = loaded.exports
const projects = [
  { date: "2026-10-15", department_name: "Graphic Design", projectTaskAssigneesByPeriod: { AM: ["am-user", "both"], PM: ["pm-user", "both"] } },
  { date: "2026-10-16", department_name: "PCM", projectTaskAssigneesByPeriod: { AM: ["tomorrow"] } },
  { date: "2026-10-15", department_name: "Development", projectTaskAssigneesByPeriod: { AM: ["dev"], PM: ["dev"] } },
  { date: "2026-10-15" },
]

test("project tasks justify every slot in their own AM or PM period", () => {
  for (const slot of ["10:00", "11:00", "11:50"]) {
    assert.deepEqual([...projectUsersForOneHSlot(projects, "2026-10-15", slot)].sort(), ["am-user", "both"])
  }
  for (const slot of ["14:20", "16:00"]) {
    assert.deepEqual([...projectUsersForOneHSlot(projects, "2026-10-15", slot)].sort(), ["both", "pm-user"])
  }
})

test("PCM project work qualifies while Development project work requires its own slot", () => {
  const entries = [{ date: "2026-10-15", department_name: "Project Content Manager", projectTaskAssigneesByPeriod: { AM: ["pcm"] } }, ...projects]
  assert.equal(projectUsersForOneHSlot(entries, "2026-10-15", "10:00").has("pcm"), true)
  assert.equal(projectUsersForOneHSlot(entries, "2026-10-15", "10:00").has("dev"), false)
})

test("other dates, missing periods and no-slot rows do not justify a missing slot", () => {
  assert.equal(projectUsersForOneHSlot(projects, "2026-10-17", "10:00").size, 0)
  assert.equal(projectUsersForOneHSlot([{ date: "2026-10-15" }], "2026-10-15", "10:00").size, 0)
  assert.equal(projectUsersForOneHSlot(projects, "2026-10-15", "").size, 0)
})
