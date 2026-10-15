import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import ts from "typescript"
import vm from "node:vm"

function load(path, require = () => {}) {
  const loaded = { exports: {} }
  const source = readFileSync(new URL(path, import.meta.url), "utf8")
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText,
    { module: loaded, exports: loaded.exports, require })
  return loaded.exports
}
const coverage = load("../src/lib/one-h-project-coverage.ts")
const { dailyCoverageNotices } = load("../src/lib/daily-project-coverage.ts", () => coverage)
const display = row => row.oneHReportSlot || ""

test("PCM and Design projects justify AM and PM independently", () => {
  for (const department of ["PCM", "GD"]) {
    const am = dailyCoverageNotices([{ typeLabel: "PRJK", period: "AM" }], department, display)
    assert.equal(am.find(x => x.key === "am").covered, true)
    assert.equal(am.find(x => x.key === "bll").covered, false)
    const pm = dailyCoverageNotices([{ typeLabel: "PRJK", period: "PM" }], department, display)
    assert.equal(pm.find(x => x.key === "am").covered, false)
    assert.equal(pm.find(x => x.key === "bll").covered, true)
    assert.equal(dailyCoverageNotices([{ typeLabel: "PRJK", period: "AM/PM" }], department, display).every(x => x.covered), true)
  }
})

test("Development projects do not replace required slots or BLL", () => {
  const notices = dailyCoverageNotices([{ typeLabel: "PRJK", period: "AM/PM" }], "DEV", display)
  assert.equal(notices.every(x => !x.covered), true)
})

test("existing slots and BLL suppress missing notices and 16:00 justifies BLL", () => {
  const notices = dailyCoverageNotices([{ subtype: "1H", oneHReportSlot: "10:00", period: "AM" }, { subtype: "BLL", period: "PM" }], "DEV", display)
  assert.equal(notices.length, 0)
  const late = dailyCoverageNotices([{ subtype: "1H", oneHReportSlot: "16:00", period: "PM" }], "DEV", display)
  assert.equal(late.find(x => x.key === "bll").covered, true)
})
