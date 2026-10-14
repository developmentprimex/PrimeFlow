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
const fixture = (kind) => ({ report_type: kind, is_active: true, send_time: kind === "M1" ? "08:30" : kind === "M2" ? "12:15" : "16:20",
  weekdays: [0, 1, 2, 3, 4], timezone: "Europe/Tirane",
  recipients: { to: ["ga@primexeu.com", "info@primexeu.com"], cc: [], bcc: [] },
  manual_recipients: { to: ["manual@example.com"], cc: [], bcc: [] } })

function mount(kind, api, canManage = true) {
  const states = [], effects = [], queue = [], recipients = []
  let cursor = 0, effectCursor = 0, changed = true, tree
  const cache = new Map()
  const hooks = { ...React,
    useState(initial) {
      const index = cursor++
      if (!(index in states)) states[index] = typeof initial === "function" ? initial() : initial
      return [states[index], (value) => { states[index] = typeof value === "function" ? value(states[index]) : value; changed = true }]
    },
    useEffect(effect, dependencies) {
      const index = effectCursor++
      if (!effects[index] || dependencies.some((value, i) => !Object.is(value, effects[index].dependencies[i]))) {
        effects[index]?.cleanup?.()
        effects[index] = { dependencies }
        queue.push(() => { effects[index].cleanup = effect() })
      }
    },
  }
  function load(name) {
    if (name === "react") return hooks
    if (name === "@/lib/auth") return { useAuth: () => ({ apiFetch: api }) }
    if (!name.startsWith("@/")) return require(name)
    if (cache.has(name)) return cache.get(name)
    const base = path.join(src, name.slice(2))
    let source
    try { source = readFileSync(`${base}.tsx`, "utf8") } catch { source = readFileSync(`${base}.ts`, "utf8") }
    const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText
    const loaded = { exports: {} }
    vm.runInNewContext(compiled, { module: loaded, exports: loaded.exports, require: load, Error })
    cache.set(name, loaded.exports)
    return loaded.exports
  }
  const { ReportingPointsManagement } = load("@/components/reporting-points-management")
  const props = { api: `/${kind.toLowerCase()}-reporting-points`, reportType: kind, canManage,
    onRecipientsChange: (value) => recipients.push(value), children: React.createElement("div", null, "Veprimet e raportit") }
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
    recipients,
    async flush() {
      for (let i = 0; i < 20; i++) {
        if (changed) { changed = false; cursor = 0; effectCursor = 0; tree = ReportingPointsManagement(props) }
        while (queue.length) queue.shift()()
        await Promise.resolve()
      }
    },
    html: () => renderToStaticMarkup(tree),
    input: (id) => find(tree, (item) => item.type === "input" && item.props.id === id),
    submit: () => find(tree, (item) => item.type === "form").props.onSubmit({ preventDefault() {} }),
    checkbox: (name) => find(tree, (item) => item.type === "label" && React.Children.toArray(item.props.children).includes(name))?.props.children[0],
  }
}

for (const kind of ["M1", "M2", "M3"]) {
  test(`${kind} management starts collapsed and contains all controls and saved delivery details`, async () => {
    const page = mount(kind, async () => ({ ok: true, json: async () => fixture(kind) }))
    await page.flush()
    const html = page.html()
    assert.match(html, new RegExp(`data-report-management="${kind}"`))
    assert.doesNotMatch(html, /<details[^>]*\bopen=/)
    assert.match(html, /group-open:hidden/)
    assert.match(html, /group-open:inline/)
    assert.match(html, /Menaxhimi i raportit dhe email-it/)
    assert.match(html, /Veprimet e raportit/)
    assert.match(html, /Marrësit e dërgimit automatik/)
    assert.match(html, /Marrësit e dërgimit manual/)
    assert.match(html, /ga@primexeu.com, info@primexeu.com/)
    assert.match(html, /manual@example.com/)
    assert.equal(page.input(`${kind}-send-time`).props.value, kind === "M1" ? "08:30" : kind === "M2" ? "12:15" : "16:20")
    assert.equal(page.input(`${kind}-send-time`).props.min, kind === "M3" ? "16:15" : kind === "M1" ? "08:30" : undefined)
  })

  test(`${kind} saves editable recipients and time, updates manual send recipients and survives reload`, async () => {
    let server = fixture(kind)
    const requests = []
    const api = async (url, options) => {
      requests.push([url, options?.method || "GET"])
      if (options?.method === "PUT") server = { ...server, ...JSON.parse(options.body) }
      return { ok: true, json: async () => server }
    }
    const page = mount(kind, api)
    await page.flush()
    page.input(`${kind}-send-time`).props.onChange({ target: { value: "17:05" } })
    await page.flush()
    page.input(`${kind}-recipients-to`).props.onChange({ target: { value: " NEW@EXAMPLE.COM; new@example.com, other@example.com " } })
    await page.flush()
    page.input(`${kind}-manual_recipients-to`).props.onChange({ target: { value: "manual-new@example.com" } })
    await page.flush()
    page.checkbox("Dërgim automatik aktiv").props.onChange({ target: { checked: false } })
    await page.flush()
    page.checkbox("E shtunë").props.onChange({ target: { checked: true } })
    await page.flush()
    await page.submit()
    await page.flush()
    assert.equal(server.send_time, "17:05")
    assert.equal(server.is_active, false)
    assert.deepEqual(server.recipients.to, ["new@example.com", "other@example.com"])
    assert.deepEqual(server.weekdays, [0, 1, 2, 3, 4, 5])
    assert.equal(page.recipients.at(-1).to[0], "manual-new@example.com")
    assert.match(page.html(), /Konfigurimi u ruajt/)
    assert.ok(requests.every(([url]) => url.endsWith("/settings")))
    const reload = mount(kind, api)
    await reload.flush()
    assert.equal(reload.input(`${kind}-send-time`).props.value, "17:05")
    assert.equal(reload.checkbox("Dërgim automatik aktiv").props.checked, false)
    assert.equal(reload.input(`${kind}-recipients-to`).props.value, "new@example.com, other@example.com")
  })

  test(`${kind} keeps unsaved edits on failed save and reports the error`, async () => {
    const page = mount(kind, async (_, options) => options?.method === "PUT"
      ? { ok: false, status: 422, json: async () => ({ detail: "Ora nuk lejohet." }) }
      : { ok: true, json: async () => fixture(kind) })
    await page.flush()
    page.input(`${kind}-send-time`).props.onChange({ target: { value: "17:10" } })
    await page.flush()
    await page.submit()
    await page.flush()
    assert.match(page.html(), /Ora nuk lejohet/)
    assert.equal(page.input(`${kind}-send-time`).props.value, "17:10")
    assert.equal(page.recipients.length, 1)
  })
}

test("staff retains collapsed report controls without reading or editing recipient settings", async () => {
  const requests = []
  const page = mount("M2", async (url) => requests.push(url), false)
  await page.flush()
  assert.match(page.html(), /Veprimet e raportit/)
  assert.doesNotMatch(page.html(), /<form|Ruaj konfigurimin/)
  assert.equal(requests.length, 0)
})

test("invalid recipient text is rejected before a configuration request", async () => {
  const writes = []
  const page = mount("M2", async (_, options) => {
    if (options?.method === "PUT") writes.push(options)
    return { ok: true, json: async () => fixture("M2") }
  })
  await page.flush()
  page.input("M2-recipients-to").props.onChange({ target: { value: "invalid-email" } })
  await page.flush()
  await page.submit()
  await page.flush()
  assert.match(page.html(), /Kontrollo adresat e email-it/)
  assert.equal(writes.length, 0)
})
