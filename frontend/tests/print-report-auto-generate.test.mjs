import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import path from "node:path"
import { fileURLToPath } from "node:url"
import vm from "node:vm"
import { test } from "node:test"
import React from "react"
import ts from "typescript"

const require = createRequire(import.meta.url)
const src = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src")
const preview = (frozen = false) => ({ subject: "Fresh report", html: "<p>Latest tasks</p>", target_date: "2026-10-22",
  report_date: "2026-10-22", snapshot_id: "snapshot", generated_at: "2026-10-22T09:00:00Z", is_frozen: frozen })

function mount({ today = false, api, strict = false, user = { id: "staff", role: "STAFF" }, loading = false }) {
  const state = [], refs = [], callbacks = [], effects = [], queue = []
  let cursor, refCursor, callbackCursor, effectCursor, changed = true, tree, replayed = false
  const same = (left, right) => left && right && left.length === right.length && left.every((value, i) => Object.is(value, right[i]))
  const hooks = { ...React,
    useState(initial) {
      const index = cursor++
      if (!(index in state)) state[index] = typeof initial === "function" ? initial() : initial
      return [state[index], value => {
        const next = typeof value === "function" ? value(state[index]) : value
        if (!Object.is(next, state[index])) { state[index] = next; changed = true }
      }]
    },
    useRef(initial) { const index = refCursor++; return refs[index] ||= { current: initial } },
    useCallback(callback, deps) {
      const index = callbackCursor++
      if (!same(callbacks[index]?.deps, deps)) callbacks[index] = { callback, deps }
      return callbacks[index].callback
    },
    useEffect(effect, deps) {
      const index = effectCursor++
      if (!same(effects[index]?.deps, deps)) {
        effects[index]?.cleanup?.()
        effects[index] = { effect, deps }
        queue.push(() => { effects[index].cleanup = effect() })
      }
    },
  }
  const document = { visibilityState: "visible", addEventListener() {}, removeEventListener() {} }
  const window = { document, setInterval: () => 1, clearInterval() {}, confirm() { throw new Error("Automatic generation must not ask for confirmation") } }
  const cache = new Map()
  function load(name) {
    if (name === "react") return hooks
    if (name === "@/lib/auth") return { useAuth: () => ({ user, loading, apiFetch: api }) }
    if (name === "@/components/marker-comments-context") return { useMarkerComments: () => null }
    if (!name.startsWith("@/")) return require(name)
    if (cache.has(name)) return cache.get(name)
    const base = path.join(src, name.slice(2))
    let source
    try { source = readFileSync(`${base}.tsx`, "utf8") } catch { source = readFileSync(`${base}.ts`, "utf8") }
    const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText
    const loaded = { exports: {} }
    vm.runInNewContext(compiled, { module: loaded, exports: loaded.exports, require: load, window, document, Error })
    cache.set(name, loaded.exports)
    return loaded.exports
  }
  const { PrintReportPage } = load("@/app/(app)/tomorrow-print-report/page")
  function find(node, predicate) {
    if (!node || typeof node !== "object") return null
    if (predicate(node)) return node
    for (const child of React.Children.toArray(node.props?.children)) {
      const found = find(child, predicate)
      if (found) return found
    }
    return null
  }
  return {
    async flush() {
      for (let round = 0; round < 30; round++) {
        if (changed) { changed = false; cursor = refCursor = callbackCursor = effectCursor = 0; tree = PrintReportPage({ today }) }
        while (queue.length) queue.shift()()
        if (strict && !replayed) {
          replayed = true
          for (const entry of effects) { entry.cleanup?.(); entry.cleanup = entry.effect() }
        }
        await Promise.resolve()
      }
    },
    html() { return find(tree, node => node.type === "iframe")?.props.srcDoc },
    selectHistory(day) { find(tree, node => node.props.id === "today-frozen-history").props.onChange({ target: { value: day } }) },
    text() { return JSON.stringify(tree) },
    unmount() { for (const effect of effects) effect.cleanup?.() },
  }
}

function apiFixture(result = preview()) {
  const calls = []
  return { calls, api: async (url, options) => {
    calls.push({ url, method: options?.method || "GET" })
    return { ok: true, status: 200, json: async () => url.endsWith("/frozen-history") ? []
      : url.endsWith("/freeze-status") ? { report_date: "2026-10-22", is_frozen: result.is_frozen, freeze_ready: true } : result }
  } }
}

for (const today of [true, false]) {
  test(`${today ? "Today" : "Tomorrow"} regenerates on each visit for signed-in staff without a confirmation`, async () => {
    const { api, calls } = apiFixture()
    const base = today ? "/today-print-report" : "/tomorrow-print-report"
    for (let visit = 0; visit < 2; visit++) {
      const page = mount({ today, api })
      await page.flush()
      assert.match(page.html(), /Latest tasks/)
      page.unmount()
    }
    assert.equal(calls.filter(call => call.url === `${base}/generate` && call.method === "POST").length, 2)
    assert.equal(calls.filter(call => call.url.endsWith("/snapshot")).length, 0)
  })
}

test("React effect replay shares one pending generation instead of generating twice", async () => {
  const { api, calls } = apiFixture()
  const page = mount({ api, strict: true })
  await page.flush()
  assert.equal(calls.filter(call => call.url.endsWith("/generate")).length, 1)
  assert.match(page.html(), /Latest tasks/)
  page.unmount()
})

test("Today keeps the frozen response and reads history without regenerating it", async () => {
  const { api, calls } = apiFixture(preview(true))
  const page = mount({ today: true, api })
  await page.flush()
  assert.match(page.text(), /Raport i ngrirë/)
  page.selectHistory("2026-10-21")
  await page.flush()
  assert.equal(calls.filter(call => call.url.endsWith("/generate")).length, 1)
  assert.ok(calls.some(call => call.url === "/today-print-report/snapshot?report_date=2026-10-21" && call.method === "GET"))
  page.unmount()
})

test("automatic generation failure is visible and does not cause a request loop", async () => {
  let count = 0
  const page = mount({ api: async () => { count++; return { ok: false, status: 503, json: async () => ({ detail: "Generation unavailable" }) } } })
  await page.flush()
  await page.flush()
  assert.equal(count, 1)
  assert.match(page.text(), /Generation unavailable/)
  page.unmount()
})

test("an unauthenticated visitor cannot start generation", async () => {
  const { api, calls } = apiFixture()
  const page = mount({ api, user: null })
  await page.flush()
  assert.equal(calls.length, 0)
  page.unmount()
})
