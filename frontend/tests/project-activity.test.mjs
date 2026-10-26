import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import { test } from "node:test"
import vm from "node:vm"
import ts from "typescript"

const realRequire = createRequire(import.meta.url)
const source = readFileSync(new URL("../src/components/project-activity.tsx", import.meta.url), "utf8")

function load(role, apiFetch = async () => {}, onToast = () => {}) {
  const loaded = { exports: {} }
  const require = name => {
    if (name === "react") return { __esModule: true, useState: () => [false, () => {}] }
    if (name === "@/lib/auth") return { useAuth: () => ({ user: { role }, apiFetch }) }
    if (name === "@/lib/department-bootstrap-cache") return { clearDepartmentBootstrapCache: () => {} }
    if (name === "sonner") return { toast: { success: onToast, error: onToast } }
    if (name === "@/components/ui/select") return Object.fromEntries(
      ["Select", "SelectTrigger", "SelectValue", "SelectContent", "SelectItem"].map(name => [name, name]))
    return realRequire(name)
  }
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText, { module: loaded, exports: loaded.exports, require })
  return loaded.exports
}

test("activity filtering remains independent of workflow and includes legacy active projects", () => {
  const { matchesProjectActivity } = load("STAFF")
  const projects = [
    { id: "open", is_active: true, current_phase: "PLANNING" },
    { id: "closed", is_active: true, current_phase: "CLOSED" },
    { id: "inactive", is_active: false, current_phase: "PLANNING" },
    { id: "legacy" },
  ]
  assert.deepEqual(projects.filter(p => matchesProjectActivity(p, "active")).map(p => p.id), ["open", "closed", "legacy"])
  assert.deepEqual(projects.filter(p => matchesProjectActivity(p, "inactive")).map(p => p.id), ["inactive"])
  assert.equal(projects.filter(p => matchesProjectActivity(p, "all")).length, 4)
})

test("staff and read-only views see a badge while admin and manager get a dropdown", () => {
  for (const role of ["STAFF", "ADMIN", "MANAGER"]) {
    const { ProjectActivityControl } = load(role)
    const props = { project: { id: "p", is_active: false }, onChange: () => {} }
    assert.equal(ProjectActivityControl(props).type, role === "STAFF" ? "span" : "Select")
    assert.equal(ProjectActivityControl({ ...props, readOnly: true }).type, "span")
  }
})

test("dropdown selection changes only activity and keeps clicks inside the control", async () => {
  for (const active of [true, false]) {
    let request, changed, stopped = false
    let finish
    const done = new Promise(resolve => { finish = resolve })
    const { ProjectActivityControl } = load("MANAGER", async (url, options) => {
      request = { url, options }
      return { ok: true, json: async () => ({ id: "p", is_active: !active }) }
    }, finish)
    const element = ProjectActivityControl({ project: { id: "p", is_active: active }, onChange: value => { changed = value } })
    element.props.children[0].props.onClick({ stopPropagation: () => { stopped = true } })
    element.props.onValueChange(active ? "inactive" : "active")
    await done
    assert.equal(request.url, "/projects/p")
    assert.equal(request.options.method, "PATCH")
    assert.deepEqual(JSON.parse(request.options.body), { is_active: !active })
    assert.equal(changed.is_active, !active)
    assert.ok(stopped)
  }
})

test("failed updates retain the current project", async () => {
  let changed = false, finish
  const done = new Promise(resolve => { finish = resolve })
  const { ProjectActivityControl } = load("ADMIN", async () => ({ ok: false }), finish)
  const element = ProjectActivityControl({ project: { id: "p" }, onChange: () => { changed = true } })
  element.props.onValueChange("inactive")
  await done
  assert.equal(changed, false)
})


test("empty My View explains membership instead of implying projects were removed", () => {
  const { ProjectListEmptyState } = load("STAFF")
  const element = ProjectListEmptyState({ projects: [], visibleCount: 0, mine: true, membersLoaded: true })
  assert.match(element.props.children, /listed as a member/)
  const loading = ProjectListEmptyState({ projects: [], visibleCount: 0, mine: true, membersLoaded: false })
  assert.match(loading.props.children, /Loading/)
  assert.equal(ProjectListEmptyState({ projects: [], visibleCount: 1, mine: true, membersLoaded: true }), null)
})
