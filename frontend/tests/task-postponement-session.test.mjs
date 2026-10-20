import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import { test } from "node:test"
import vm from "node:vm"
import React from "react"
import ts from "typescript"

const require = createRequire(import.meta.url)
function mount() {
  let cursor = 0
  const cells = [], effects = []
  const changed = (old, deps) => !old || deps.some((value, i) => old.deps[i] !== value)
  const hooks = { ...React,
    useRef(value) { const i = cursor++; return cells[i] ||= { current: value } },
    useState(initial) { const i = cursor++; if (!(i in cells)) cells[i] = initial; return [cells[i], value => { cells[i] = value }] },
    useMemo(create, deps) { const i = cursor++; if (changed(cells[i], deps)) cells[i] = { deps, value: create() }; return cells[i].value },
    useCallback(value, deps) { return hooks.useMemo(() => value, deps) },
    useEffect(effect, deps) { const i = cursor++; if (changed(cells[i], deps)) effects.push(() => { cells[i]?.cleanup?.(); cells[i] = { deps, cleanup: effect() } }) },
  }
  hooks.useLayoutEffect = hooks.useEffect
  const module = { exports: {} }
  const source = readFileSync(new URL("../src/components/task-postponement-dialog.tsx", import.meta.url), "utf8")
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText, { module, exports: module.exports, require: name => name === "react" ? hooks : name.startsWith("@/") ? {} : require(name) })
  return { render(session) { cursor = 0; const value = module.exports.useTaskPostponement(session); while (effects.length) effects.shift()(); return value },
    unmount() { for (const cell of cells) cell?.cleanup?.() } }
}
const details = { task_id: "task", task_title: "Task", changes: [] }

test("a conflict arriving after logout cannot open or retry the former user's operation", async () => {
  const hook = mount()
  const oldRequest = hook.render("first-user").requestExplanation
  hook.render(null)
  hook.render("second-user")
  let settled = false, value
  oldRequest(details).then(answer => { settled = true; value = answer })
  await Promise.resolve()
  assert.equal(settled, true)
  assert.equal(value, null)
  assert.equal(hook.render("second-user").postponementDialog, null)
  hook.unmount()
})

test("concurrent operations are explained separately and logout cancels pending operations", async () => {
  const hook = mount()
  const request = hook.render("user").requestExplanation
  const first = request(details), second = request(details)
  const firstDialog = hook.render("user").postponementDialog
  firstDialog.props.onFinish({ postponement_reason_code: "OTHER", postponement_comment: "First reason" })
  assert.equal((await first).postponement_comment, "First reason")
  const secondDialog = hook.render("user").postponementDialog
  assert.notEqual(firstDialog.key, secondDialog.key)
  hook.render(null)
  assert.equal(await second, null)
  hook.unmount()
})
