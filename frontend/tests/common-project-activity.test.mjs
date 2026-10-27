import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import vm from "node:vm"
import ts from "typescript"

test("Common View fallback excludes inactive PRJK while retaining active project dates and assignees", () => {
  const source = readFileSync(new URL("../src/app/(app)/common/page.tsx", import.meta.url), "utf8")
  const start = source.indexOf("const expandedPriority: PriorityItem[] = []")
  const end = source.indexOf("allData.priority = expandedPriority", start) + "allData.priority = expandedPriority".length
  const context = {
    weekStartIso: "2026-10-26", weekEndIso: "2026-10-30", productContentDeptId: "pcm",
    departmentNameById: new Map([["dev", "Development"]]), allData: { priority: [] },
    projectInfoById: new Map([
      ["std", { id: "std", title: "STD", department_id: "dev", is_active: false }],
      ["active", { id: "active", title: "PrimeFlow", department_id: "dev", is_active: true }],
    ]),
    priorityMap: new Map(["std", "active"].map(id => [id, {
      project: id === "std" ? "STD" : "PrimeFlow", dates: new Set(["2026-10-26"]),
      assigneesByDate: new Map([["2026-10-26", new Set(["LH"])]]), taskAssigneesByDatePeriod: new Map(),
    }])),
  }
  const code = ts.transpileModule(source.slice(start, end), {
    compilerOptions: { target: ts.ScriptTarget.ES2020 },
  }).outputText
  vm.runInNewContext(code, context)
  assert.deepEqual(Array.from(context.allData.priority, item => item.project), ["PrimeFlow"])
  assert.equal(context.allData.priority[0].date, "2026-10-26")
  assert.deepEqual(Array.from(context.allData.priority[0].assignees), ["LH"])
  context.projectInfoById.get("std").is_active = true
  const reactivated = { ...context, allData: { priority: [] } }
  vm.runInNewContext(code, reactivated)
  assert.deepEqual(Array.from(reactivated.allData.priority, item => item.project), ["STD", "PrimeFlow"])
})
