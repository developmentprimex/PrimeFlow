import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import path from "node:path"
import { fileURLToPath } from "node:url"
import vm from "node:vm"
import { test } from "node:test"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import ts from "typescript"

const require = createRequire(import.meta.url)
const src = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "src")
const cache = new Map()

function load(name) {
  if (name === "@/lib/auth") return { useAuth: () => ({ apiFetch: async () => { throw new Error("Unexpected request during render") } }) }
  if (!name.startsWith("@/")) return require(name)
  if (cache.has(name)) return cache.get(name)
  const base = path.join(src, name.slice(2))
  let source
  try { source = readFileSync(`${base}.tsx`, "utf8") }
  catch { source = readFileSync(`${base}.ts`, "utf8") }
  const loadedModule = { exports: {} }
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
    },
  })
  vm.runInNewContext(outputText, { module: loadedModule, exports: loadedModule.exports, require: load })
  cache.set(name, loadedModule.exports)
  return loadedModule.exports
}

const { DailyRlzReasonCell, DailyRlzCommentField } = load("@/components/daily-rlz-panel")
const state = {
  is_editable: true, editable_until: null,
  reason_required: true, comment_required: true,
  reason_missing: false, comment_missing: false,
}

function render(component, overrides = {}) {
  return renderToStaticMarkup(React.createElement(component, {
    taskId: "system-task", day: "2026-10-01", state: { ...state, ...overrides },
    onSaved: () => {},
  }))
}

test("TODO system tasks show reason and comment controls", () => {
  assert.match(render(DailyRlzReasonCell), /role="combobox"/)
  const comment = render(DailyRlzCommentField)
  assert.match(comment, /aria-label="Koment"/)
  assert.match(comment, />Save<\/button>/)
  assert.doesNotMatch(comment, /disabled=""/)
})

test("system task controls show saved evidence and respect server editing permissions", () => {
  assert.match(render(DailyRlzReasonCell, { is_editable: false }), /disabled=""/)
  const comment = render(DailyRlzCommentField, { is_editable: false, comment: "Kontrolli u krye" })
  assert.match(comment, /value="Kontrolli u krye"/)
  assert.match(comment, /disabled=""/)
})

test("DONE and other non-required tasks display saved evidence without input controls", () => {
  const overrides = { reason_required: false, comment_required: false, reason_label: "Problem teknik", comment: "Koment i ruajtur" }
  assert.doesNotMatch(render(DailyRlzReasonCell, overrides), /role="combobox"/)
  assert.match(render(DailyRlzReasonCell, overrides), /Problem teknik/)
  assert.doesNotMatch(render(DailyRlzCommentField, overrides), /<input/)
  assert.match(render(DailyRlzCommentField, overrides), /Koment i ruajtur/)
})
