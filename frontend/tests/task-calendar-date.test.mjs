import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import vm from "node:vm"
import ts from "typescript"

const source = readFileSync(new URL("../src/lib/task-calendar-date.ts", import.meta.url), "utf8")
const module = { exports: {} }
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
} }).outputText, { module, exports: module.exports })
const { taskDateKey } = module.exports

test("PX Notes reads postponed deadlines on the local calendar day", () => {
  assert.equal(taskDateKey("2026-10-21T22:00:00+00:00"), "2026-10-22")
  assert.equal(taskDateKey("2026-10-21T22:00:00Z"), "2026-10-22")
  assert.equal(taskDateKey("2026-10-22T00:00:00+02:00"), "2026-10-22")
  assert.equal(taskDateKey("2026-12-21T23:00:00Z"), "2026-12-22")
  assert.equal(taskDateKey("2026-10-22"), "2026-10-22")
  assert.equal(taskDateKey("2026-10-22T00:00:00Z"), "2026-10-22")
  assert.equal(taskDateKey(null), null)
  assert.equal(taskDateKey("invalid"), null)
})
