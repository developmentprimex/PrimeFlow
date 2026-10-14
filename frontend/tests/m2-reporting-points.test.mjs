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
const auth = { user: { role: "STAFF", full_name: "Test User" }, loading: false, apiFetch: () => {} }

function load(name) {
  if (name === "@/lib/auth") return { useAuth: () => auth }
  if (!name.startsWith("@/")) return require(name)
  if (cache.has(name)) return cache.get(name)
  const base = path.join(src, name.slice(2))
  let source
  try { source = readFileSync(`${base}.tsx`, "utf8") }
  catch { source = readFileSync(`${base}.ts`, "utf8") }
  const loadedModule = { exports: {} }
  const { outputText } = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
    jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } })
  vm.runInNewContext(outputText, { module: loadedModule, exports: loadedModule.exports, require: load })
  cache.set(name, loadedModule.exports)
  return loadedModule.exports
}

const { M2ReportingPointsView } = load("@/components/m2-reporting-points-view")
const { readManualDraft, writeManualDraft, clearSavedManualDraft } = load("@/lib/m2-reporting-points-draft")
const Page = load("@/app/(app)/m2-reporting-points/page").default
const { reportResponseJson } = load("@/lib/report-response")

test("empty and non-JSON server errors retain the HTTP failure instead of JSON syntax errors", async () => {
  for (const content of [null, "Internal Server Error"]) {
    await assert.rejects(reportResponseJson(new Response(content, { status: 500 })), /HTTP 500/)
  }
  await assert.rejects(reportResponseJson(new Response(null, { status: 503 })), /HTTP 503/)
  await assert.rejects(reportResponseJson(new Response(null, { status: 401 })), /Sesioni/)
  await assert.rejects(reportResponseJson(new Response(null, { status: 200 })), /përgjigje të pavlefshme/)
  await assert.rejects(reportResponseJson(new Response('{"detail":"Gjenero raportin"}', { status: 409 })), /Gjenero raportin/)
  assert.deepEqual(await reportResponseJson(new Response('{"status":"DRAFT"}')), { status: "DRAFT" })
})
const taskId = "00000000-0000-0000-0000-000000000001"
const answerKey = `delivery:${taskId}`
const row = { task_id: taskId, title: "Detyra <script>", assignees: "EF", department: "DEV", project: "P", status: "TODO", progress: 0, am_pm: "AM", task_type: "1H", marker: "M2/3" }
const report = { id: "report", report_date: "2026-10-06", manual_answers: {}, data: { delivery: [row] }, status: "DRAFT" }

test("M2 presents all six points with a final per-task manual answer", () => {
  const html = renderToStaticMarkup(React.createElement(M2ReportingPointsView, {
    report, answers: { reorganization: "Riorganizo", [answerKey]: "Dorezuar", [`delivery_choice:${taskId}`]: "PO" }, disabled: false, onAnswerChange: () => {},
  }))
  assert.match(html, /2\. RIORGANIZIM\?/)
  assert.match(html, /3\. DET TE PAKRYERA, 08:00\/DEADLINE\/AM/)
  assert.match(html, /4\. A KA DET/)
  assert.match(html, /5\. PROGRESI I DET ME GA \(AM\)/)
  assert.match(html, /6\. SA PER DOREZIM M2\?/)
  assert.equal((html.match(/<textarea/g) || []).length, 3)
  assert.match(html, /Dorezuar/)
  assert.match(html, /M2\/3/)
  assert.match(html, />SIMBOLI<\/th><th[^>]*>TITULLI<\/th>/)
  assert.match(html, /font-bold">M2\/3<\/td><td[^>]*>Detyra &lt;script&gt;<\/td>/)
  const deliveryTable = html.slice(html.indexOf('id="m2-delivery"'))
  assert.doesNotMatch(deliveryTable, />STATUSI<|>ARSYEJA<|>KOMENTI</)
  assert.equal((deliveryTable.match(/<th /g) || []).length, 10)
  assert.match(deliveryTable, /<option value="PO" selected="">PO<\/option>/)
  assert.match(deliveryTable, /<option value="JO">JO<\/option>/)
  assert.match(html, /Detyra &lt;script&gt;/)
  assert.match(html, /P.RGJIGJJA MANUALE<\/th><\/tr>/)
})

test("unfinished priority tasks appear third with due labels and priority styling", () => {
  const priority = { assignees: "ER", department: "GD", am_pm: "AM", status: "IN_PROGRESS", priority: "DEADLINE / 08:00",
    task_type: "PRJK", title: "08:00 Detyre <test>", due_label: "SOT", deadline_important: true, eight_am: true }
  const html = renderToStaticMarkup(React.createElement(M2ReportingPointsView, {
    report: { ...report, data: { ...report.data, unfinished_priority: [priority] } }, answers: {}, disabled: false, onAnswerChange: () => {},
  }))
  const section = html.slice(html.indexOf('aria-labelledby="m2-unfinished-priority"'), html.indexOf('aria-labelledby="m2-postponed"'))
  assert.ok(html.indexOf('id="m2-reorganization"') < html.indexOf('id="m2-unfinished-priority"'))
  assert.match(section, /LLOJI<\/th><th[^>]*>TIPI<\/th>/)
  assert.match(section, /DUE DATE<\/th>/)
  assert.match(section, /08:00 Detyre &lt;test&gt;/)
  assert.match(section, />SOT<\/td>/)
  assert.match(section, /background:#dc2626;color:white/)
  assert.match(section, /border-top:3px solid #dc2626/)
  assert.doesNotMatch(section, /<textarea|<select|>STATUS<\/th>/)
})

test("read-only reports keep all manual fields disabled", () => {
  const html = renderToStaticMarkup(React.createElement(M2ReportingPointsView, {
    report, answers: {}, disabled: true, onAnswerChange: () => {},
  }))
  assert.equal((html.match(/<textarea[^>]*disabled/g) || []).length, 3)
})

test("delivery totals count only PO answers for tasks currently in the report", () => {
  const rows = [row, { ...row, task_id: "second" }, { ...row, task_id: "third" }]
  const props = { report: { ...report, data: { delivery: rows } }, disabled: false, onAnswerChange: () => {} }
  const answers = { [`delivery_choice:${taskId}`]: "PO", "delivery_choice:second": "JO", "delivery_choice:removed": "PO" }
  let html = renderToStaticMarkup(React.createElement(M2ReportingPointsView, { ...props, answers }))
  assert.match(html, /SA\/TOTALI: <span[^>]*>1\/3<\/span>/)
  html = renderToStaticMarkup(React.createElement(M2ReportingPointsView, { ...props, answers: { ...answers, "delivery_choice:second": "PO" } }))
  assert.match(html, /SA\/TOTALI: <span[^>]*>2\/3<\/span>/)
})

test("each postponement table has a saved manual comment per task", () => {
  for (const kind of ["start_due", "due", "start"]) {
    const commentKey = `postponed_comment:${taskId}`
    const html = renderToStaticMarkup(React.createElement(M2ReportingPointsView, {
      report: { ...report, data: { postponed: [{ ...row, postponement_kind: kind }] } },
      answers: { [commentKey]: "Koment i ruajtur" }, disabled: true, onAnswerChange: () => {},
    }))
    assert.match(html, /KOMENT MANUAL/)
    assert.match(html, /<textarea[^>]*disabled[^>]*>Koment i ruajtur<\/textarea>/)
    const map = new Map()
    const storage = { getItem: (key) => map.get(key) || null, setItem: (key, value) => map.set(key, value) }
    writeManualDraft(storage, "u1", report.report_date, { [commentKey]: "Koment i ruajtur" })
    assert.equal(readManualDraft(storage, "u1", report.report_date)[commentKey], "Koment i ruajtur")
  }
})

test("the M2 page is available to signed-in staff without send controls", () => {
  const html = renderToStaticMarkup(React.createElement(Page))
  assert.match(html, /Pikat p.r raportim M2/)
  assert.doesNotMatch(html, />D?rgo<\/button>/)
})

test("M2 drafts are scoped to date and user and retain newer per-task edits", () => {
  const map = new Map()
  const storage = { getItem: (key) => map.get(key) || null, setItem: (key, value) => map.set(key, value), removeItem: (key) => map.delete(key) }
  writeManualDraft(storage, "u1", "2026-10-06", { reorganization: "Po", [answerKey]: "E re" })
  assert.equal(readManualDraft(storage, "u2", "2026-10-06"), null)
  assert.equal(readManualDraft(storage, "u1", "2026-10-05"), null)
  clearSavedManualDraft(storage, "u1", "2026-10-06", { reorganization: "Po", [answerKey]: "E vjet?r" })
  assert.equal(readManualDraft(storage, "u1", "2026-10-06")[answerKey], "E re")
  clearSavedManualDraft(storage, "u1", "2026-10-06", { reorganization: "Po", [answerKey]: "E re" })
  assert.equal(readManualDraft(storage, "u1", "2026-10-06"), null)
})

function mountPage(storage, apiFetch) {
  const state = [], callbacks = [], effects = [], pending = [], timers = new Map()
  let cursor = 0, effectCursor = 0, callbackCursor = 0, timerId = 0, changed = true, tree
  const same = (left, right) => left && right && left.length === right.length && left.every((value, index) => Object.is(value, right[index]))
  const hooks = { ...React,
    useState(initial) {
      const index = cursor++
      if (!(index in state)) state[index] = typeof initial === "function" ? initial() : initial
      return [state[index], (value) => {
        const next = typeof value === "function" ? value(state[index]) : value
        if (!Object.is(next, state[index])) { state[index] = next; changed = true }
      }]
    },
    useCallback(callback, deps) {
      const index = callbackCursor++
      if (!same(callbacks[index]?.deps, deps)) callbacks[index] = { callback, deps }
      return callbacks[index].callback
    },
    useEffect(effect, deps) {
      const index = effectCursor++
      if (!same(effects[index]?.deps, deps)) {
        effects[index]?.cleanup?.()
        effects[index] = { deps }
        pending.push(() => { effects[index].cleanup = effect() })
      }
    },
  }
  const source = readFileSync(path.join(src, "app", "(app)", "m2-reporting-points", "page.tsx"), "utf8")
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText
  const pageModule = { exports: {} }
  vm.runInNewContext(compiled, {
    module: pageModule, exports: pageModule.exports,
    require: (name) => name === "react" ? hooks : name === "@/lib/auth" ? { useAuth: () => ({ user: { id: "manager", role: "MANAGER" }, loading: false, apiFetch }) } : load(name),
    window: { localStorage: storage,
      setTimeout: (callback) => { const id = ++timerId; timers.set(id, callback); return id },
      clearTimeout: (id) => timers.delete(id), setInterval: () => -1, clearInterval: () => {},
    },
  })
  const findNode = (node, predicate) => {
    if (!node || typeof node !== "object") return null
    if (predicate(node)) return node
    for (const child of React.Children.toArray(node.props?.children)) {
      const found = findNode(child, predicate)
      if (found) return found
    }
    return null
  }
  const findView = (node) => findNode(node, (item) => item.type === M2ReportingPointsView)
  const content = (node) => typeof node === "string" ? node : React.Children.toArray(node?.props?.children).map(content).join("")
  const button = (label) => {
    const node = findNode(tree, (item) => item.props?.onClick && content(item) === label)
    assert.ok(node, `Button missing: ${label}`)
    return node
  }
  return {
    async flush() {
      for (let round = 0; round < 20; round++) {
        if (changed) { changed = false; cursor = 0; effectCursor = 0; callbackCursor = 0; tree = pageModule.exports.default() }
        while (pending.length) pending.shift()()
        await Promise.resolve()
      }
    },
    edit(key, value) { findView(tree).props.onAnswerChange(key, value) },
    answers() { return findView(tree).props.answers },
    viewDisabled() { return findView(tree).props.disabled },
    buttonDisabled(label) { return !!button(label).props.disabled },
    click(label) { const node = button(label); assert.ok(!node.props.disabled); return node.props.onClick() },
    fireSave() {
      assert.equal(timers.size, 1)
      const [id, callback] = timers.entries().next().value
      timers.delete(id)
      return callback()
    },
    unmount() { for (const effect of effects) effect?.cleanup?.() },
  }
}

test("sent reports remain editable, regenerate, autosave and send repeatedly", async () => {
  const values = new Map()
  const storage = { getItem: (key) => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) }
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Tirane", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date())
  let server = { ...report, report_date: day, status: "SENT", sent_at: new Date().toISOString(), generated_at: new Date().toISOString() }
  let sends = 0, generations = 0
  const api = async (url, options) => {
    if (options?.method === "PUT") server = { ...server, status: "DRAFT", manual_answers: JSON.parse(options.body).manual_answers }
    if (url.includes("/generate?")) { generations++; server = { ...server, status: "DRAFT" } }
    if (url.endsWith("/send")) { sends++; server = { ...server, status: "SENT", sent_at: new Date().toISOString() } }
    return { ok: true, status: 200, json: async () => url.endsWith("/recipients") ? { recipients: { to: ["test@example.com"], cc: [], bcc: [] } } : { ...server } }
  }
  const page = mountPage(storage, api)
  await page.flush()
  assert.equal(page.viewDisabled(), false)
  assert.equal(page.buttonDisabled("Gjenero raportin"), false)
  assert.equal(page.buttonDisabled("Dërgo sërish"), false)
  await page.click("Gjenero raportin")
  await page.flush()
  assert.equal(generations, 1)
  for (let i = 0; i < 3; i++) {
    page.edit(answerKey, `Përgjigjja ${i}`)
    await page.flush()
    await page.fireSave()
    await page.flush()
    assert.equal(server.manual_answers[answerKey], `Përgjigjja ${i}`)
    assert.equal(page.buttonDisabled("Dërgo sërish"), false)
    page.click("Dërgo sërish")
    await page.flush()
    await page.click("Dërgo raportin")
    await page.flush()
    assert.equal(page.viewDisabled(), false)
    assert.equal(page.buttonDisabled("Gjenero raportin"), false)
  }
  assert.equal(sends, 3)
  page.unmount()
})

test("sent reports restore and autosave local edits after reload", async () => {
  const values = new Map()
  const storage = { getItem: (key) => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) }
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Tirane", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date())
  let server = { ...report, report_date: day, status: "SENT", sent_at: new Date().toISOString() }
  const api = async (url, options) => {
    if (options?.method === "PUT") server = { ...server, status: "DRAFT", manual_answers: JSON.parse(options.body).manual_answers }
    return { ok: true, status: 200, json: async () => url.endsWith("/recipients") ? { recipients: { to: [], cc: [], bcc: [] } } : { ...server } }
  }
  const first = mountPage(storage, api)
  await first.flush()
  first.edit(answerKey, "Ndryshim pas dërgimit")
  await first.flush()
  first.unmount()
  const reloaded = mountPage(storage, api)
  await reloaded.flush()
  assert.equal(reloaded.answers()[answerKey], "Ndryshim pas dërgimit")
  await reloaded.fireSave()
  await reloaded.flush()
  assert.equal(server.manual_answers[answerKey], "Ndryshim pas dërgimit")
  assert.equal(values.size, 0)
  reloaded.unmount()
})

test("answers survive immediate reload and automatically persist without pressing Save", async () => {
  const values = new Map()
  const storage = { getItem: (key) => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) }
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Tirane", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date())
  let server = { ...report, report_date: day, subject: "Report", generated_at: new Date().toISOString() }
  const api = async (url, options) => {
    if (options?.method === "PUT") server = { ...server, manual_answers: JSON.parse(options.body).manual_answers }
    return { ok: true, status: 200, json: async () => url.endsWith("/recipients") ? { recipients: { to: [], cc: [], bcc: [] } } : { ...server } }
  }
  const first = mountPage(storage, api)
  await first.flush()
  const commentKey = `postponed_comment:${taskId}`
  first.edit(commentKey, "Koment qe duhet te mbetet")
  await first.flush()
  first.edit(answerKey, "Përgjigje që duhet të mbetet")
  await first.flush()
  first.unmount() // Refresh before the debounce fires.
  const reloaded = mountPage(storage, api)
  await reloaded.flush()
  assert.equal(reloaded.answers()[commentKey], "Koment qe duhet te mbetet")
  assert.equal(reloaded.answers()[answerKey], "Përgjigje që duhet të mbetet")
  await reloaded.fireSave()
  await reloaded.flush()
  assert.equal(server.manual_answers[answerKey], "Përgjigje që duhet të mbetet")
  assert.equal(values.size, 0)
  reloaded.unmount()
  const reopened = mountPage(storage, api)
  await reopened.flush()
  assert.equal(reopened.answers()[commentKey], "Koment qe duhet te mbetet")
  reopened.unmount()
})

test("typing during a slow automatic save is kept and saved after the first request", async () => {
  const storageValues = new Map()
  const storage = { getItem: (key) => storageValues.get(key), setItem: (key, value) => storageValues.set(key, value), removeItem: (key) => storageValues.delete(key) }
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Tirane", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date())
  let server = { ...report, report_date: day }, resolveFirst
  const saved = []
  const api = async (url, options) => {
    if (options?.method === "PUT") {
      const answers = JSON.parse(options.body).manual_answers
      saved.push(answers[answerKey])
      if (saved.length === 1) await new Promise((resolve) => { resolveFirst = resolve })
      server = { ...server, manual_answers: answers }
    }
    return { ok: true, status: 200, json: async () => url.endsWith("/recipients") ? { recipients: { to: [], cc: [], bcc: [] } } : { ...server } }
  }
  const page = mountPage(storage, api)
  await page.flush()
  page.edit(answerKey, "Teksti fillestar")
  await page.flush()
  const firstSave = page.fireSave()
  await page.flush()
  page.edit(answerKey, "Teksti më i ri")
  await page.flush()
  resolveFirst()
  await firstSave
  await page.flush()
  assert.equal(page.answers()[answerKey], "Teksti më i ri")
  await page.fireSave()
  await page.flush()
  assert.deepEqual(saved, ["Teksti fillestar", "Teksti më i ri"])
  assert.equal(server.manual_answers[answerKey], "Teksti më i ri")
  page.unmount()
})

test("a failed automatic save preserves the entered answers and the reload draft", async () => {
  const values = new Map()
  const storage = { getItem: (key) => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) }
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Tirane", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date())
  const api = async (url, options) => options?.method === "PUT"
    ? { ok: false, status: 503, json: async () => ({ detail: "Ruajtja dështoi" }) }
    : { ok: true, status: 200, json: async () => url.endsWith("/recipients") ? { recipients: { to: [], cc: [], bcc: [] } } : { ...report, report_date: day } }
  const page = mountPage(storage, api)
  await page.flush()
  page.edit(answerKey, "Mos e humb përgjigjen")
  await page.flush()
  await page.fireSave()
  await page.flush()
  assert.equal(page.answers()[answerKey], "Mos e humb përgjigjen")
  page.unmount()
  const reloaded = mountPage(storage, api)
  await reloaded.flush()
  assert.equal(reloaded.answers()[answerKey], "Mos e humb përgjigjen")
  reloaded.unmount()
})


test("GA morning tasks appear after postponements with matching colors and eight columns", () => {
  const html = renderToStaticMarkup(React.createElement(M2ReportingPointsView, {
    report: { ...report, data: { ...report.data, ga_progress: [
      { ...row, marker: "GA", progress: 37.5, start_date: "2026-10-01", due_date: "2026-10-09", status: "IN_PROGRESS" },
      { ...row, task_id: "done", marker: "F", progress: 100, status: "DONE" },
    ] } }, answers: {}, disabled: false, onAnswerChange: () => {},
  }))
  assert.ok(html.indexOf('id="m2-postponed"') < html.indexOf('id="m2-ga-progress"'))
  assert.ok(html.indexOf('id="m2-ga-progress"') < html.indexOf('id="m2-delivery"'))
  const section = html.slice(html.indexOf('id="m2-ga-progress"'), html.indexOf('aria-labelledby="m2-delivery"'))
  assert.equal((section.match(/<th /g) || []).length, 8)
  assert.doesNotMatch(section, /START DATE|DUE DATE|PROGRESI<\/th>|37.5%|100%/)
  assert.match(section, /background:#FFFF00/)
  assert.match(section, /background:#C4FDC4/)
  assert.match(section, />GA<\/td>/)
  assert.doesNotMatch(section, /<textarea|<select/)
})


test("GA reply is the first manual point and its draft survives reload", () => {
  const html = renderToStaticMarkup(React.createElement(M2ReportingPointsView, {
    report, answers: { ga_reply: "GA u përgjigj" }, disabled: false, onAnswerChange: () => {},
  }))
  assert.match(html, /1\. \(GA\) A KA REPLY NGA GA TEK DETYRAT NGA STAFI PER GA\?/)
  assert.ok(html.indexOf('id="m2-ga-reply"') < html.indexOf('id="m2-reorganization"'))
  assert.match(html, /<textarea[^>]*id="ga_reply"[^>]*>GA u përgjigj<\/textarea>/)
  const map = new Map()
  const storage = { getItem: (key) => map.get(key) || null, setItem: (key, value) => map.set(key, value) }
  writeManualDraft(storage, "u1", report.report_date, { ga_reply: "GA u përgjigj" })
  assert.equal(readManualDraft(storage, "u1", report.report_date).ga_reply, "GA u përgjigj")
})
