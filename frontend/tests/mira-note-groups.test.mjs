import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import vm from "node:vm"
import ts from "typescript"

const source = readFileSync(new URL("../src/lib/mira-note-groups.ts", import.meta.url), "utf8")
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText
const context = { exports: {} }
vm.runInNewContext(compiled, context)
const group = context.exports.miraNoteGroup

test("AI Agent and 1H notes stay separate, including old Discord titles", () => {
  assert.equal(group({ title: "1H 820/10/11/1150 · 29.10.2026", source: "DISCORD" }), "1H")
  assert.equal(group({ title: "AI AGENT 08-05 & 12-00 · 29.10.2026", source: "DISCORD" }), "AI_AGENT")
  assert.equal(group({ title: "Custom title", source: "DISCORD", meeting_group: "AI_AGENT" }), "AI_AGENT")
  assert.equal(group({ title: "AI Agent", source: "DESKTOP" }), "OTHER")
  assert.equal(group({ title: "Other notes", source: "DISCORD" }), "OTHER")
})
