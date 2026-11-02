import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import vm from "node:vm"
import ts from "typescript"

const source = readFileSync(new URL("../src/lib/dates.ts", import.meta.url), "utf8")
const module = { exports: {} }
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
} }).outputText, { module, exports: module.exports, Date })
const { nextWorkingDay, toDateInputValue } = module.exports

for (const [from, expected] of [
  ["2026-10-30", "2026-11-02"],
  ["2026-10-31", "2026-11-02"],
  ["2026-11-01", "2026-11-02"],
  ["2026-11-02", "2026-11-03"],
  ["2026-10-29", "2026-10-30"],
  ["2027-12-31", "2028-01-03"],
  ["2026-03-27", "2026-03-30"],
]) {
  test(`next working day after ${from} is ${expected}`, () => {
    const input = new Date(`${from}T15:30:00`)
    const original = input.getTime()
    const result = nextWorkingDay(input)
    assert.equal(toDateInputValue(result), expected)
    assert.equal(result.getHours(), 0)
    assert.equal(input.getTime(), original)
  })
}
