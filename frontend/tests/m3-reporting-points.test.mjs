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

const { M3ReportingPointsView, ReportingTaskTable } = load("@/components/m3-reporting-points-view")
const Page = load("@/app/(app)/m3-reporting-points/page").default
const row = { task_id: "task", title: "Detyra", assignees: "EF", department: "DEV", project: "P", status: "TODO", progress: 65, am_pm: "PM", task_type: "1H" }
const report = {
  id: "report", report_date: "2026-10-05", manual_answers: {}, data: {}, realization: null,
  realization_captured_at: null, status: "DRAFT",
}

test("due date postponements display their saved reason and comment", () => {
  const html = render({ data: { postponed: [{ ...row, postponement_kind: "due", reason: "Saved postponement reason", comment: "Saved postponement comment" }] } })
  assert.match(html, /Saved postponement reason/)
  assert.match(html, /Saved postponement comment/)
})

test("M1 plan changes show the explanation captured by each postponement", () => {
  const { M1ReportingPointsView } = load("@/components/m1-reporting-points-view")
  const html = renderToStaticMarkup(React.createElement(M1ReportingPointsView, {
    report: { ...report, data: { postponed: [{ ...row, postponement_kind: "start", postponement_period: "AM", reason: "M1 saved reason", comment: "M1 saved comment" }] } },
    answers: {}, disabled: false, onAnswerChange: () => {},
  }))
  assert.match(html, /M1 saved reason/)
  assert.match(html, /M1 saved comment/)
})

function render(overrides = {}, answers = {}, disabled = false) {
  return renderToStaticMarkup(React.createElement(M3ReportingPointsView, {
    report: { ...report, ...overrides }, answers, disabled, onAnswerChange: () => {},
  }))
}

test("M3 delivery shows symbols, PO/JO, manual answers and a live total before realization", () => {
  const id = "11111111-1111-4111-8111-111111111111"
  const answers = { [`delivery_choice:${id}`]: "PO", [`delivery:${id}`]: "Dorezuar" }
  const data = { delivery: [{ ...row, task_id: id, marker: "M3" }, { ...row, task_id: "second", marker: "M2/3" }] }
  const html = render({ data }, answers)
  assert.match(html, /5\. SA PER DOREZIM M3\?/)
  assert.match(html, /SA\/TOTALI:.*1\/2/)
  assert.match(html, /M2\/3/)
  assert.match(html, /<option value="PO" selected="">PO<\/option>/)
  assert.match(html, /<textarea[^>]*>Dorezuar<\/textarea>/)
  assert.ok(html.indexOf("5. SA PER DOREZIM M3?") < html.indexOf("6. REALIZIMI"))
  assert.match(render({ data }, answers, true), /<select[^>]*disabled=""/)
  const { readManualDraft, writeManualDraft } = load("@/lib/m3-reporting-points-draft")
  const values = new Map()
  const storage = { getItem: key => values.get(key) || null, setItem: (key, value) => values.set(key, value) }
  writeManualDraft(storage, "user", "2026-10-05", answers)
  assert.deepEqual(JSON.parse(JSON.stringify(readManualDraft(storage, "user", "2026-10-05"))), answers)
})

test("point two edits the existing My View comment column per task including SYS", () => {
  const ids = ["11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"]
  const answers = { [`untouched_comment:${ids[0]}`]: "Manual FT", [`untouched_comment:${ids[1]}`]: "Manual SYS" }
  const data = { untouched: ids.map((task_id, index) => ({ ...row, task_id, task_type: index ? "SYS" : "FT", reason: "My View reason", comment: "My View comment" })) }
  const html = render({ data }, answers)
  assert.doesNotMatch(html, /KOMENT MANUAL<\/th>/)
  assert.equal((html.match(/KOMENTI<\/th>/g) || []).length, 2)
  assert.equal((html.match(/My View reason/g) || []).length, 2)
  assert.doesNotMatch(html, /My View comment/)
  assert.equal((render({ data }).match(/My View comment/g) || []).length, 2)
  assert.match(html, /<textarea[^>]*>Manual FT<\/textarea>/)
  assert.match(html, /<textarea[^>]*>Manual SYS<\/textarea>/)
  assert.match(render({ data }, answers, true), /<textarea[^>]*aria-label="Komenti p.r[^>]*disabled=""/)
  const missing = { untouched: [{ ...row, comment: "-" }] }
  assert.match(render({ data: missing }), /<textarea[^>]*><\/textarea>/)
  const cleared = { [`untouched_comment:${ids[0]}`]: "", [`untouched_comment:${ids[1]}`]: "" }
  assert.doesNotMatch(render({ data }, cleared), /My View comment/)
  const { readManualDraft, writeManualDraft } = load("@/lib/m3-reporting-points-draft")
  const values = new Map()
  const storage = { getItem: key => values.get(key) || null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }
  writeManualDraft(storage, "user", "2026-10-05", answers)
  assert.deepEqual(JSON.parse(JSON.stringify(readManualDraft(storage, "user", "2026-10-05"))), answers)
})

test("M3 contains three editable manual answers without the removed GA section", () => {
  const html = render({}, { underload: "Përgjigje e ruajtur", ga_reorganization: "Riorganizo ekipin" })
  assert.match(html, /PIKAT PËR RAPORTIM M3/)
  assert.doesNotMatch(html, /PIKAT PËR RAPORTIM PËR GA/)
  assert.equal((html.match(/<textarea/g) || []).length, 3)
  assert.match(html, /Përgjigje e ruajtur/)
  assert.doesNotMatch(html, /Riorganizo ekipin/)
  assert.match(html, /brenda intervalit Start–Due/)
})

test("postponements separate morning and afternoon audit windows regardless of task period", () => {
  const html = render({ data: { postponed_today: [
    { ...row, task_id: "morning", title: "Morning change", am_pm: "PM", postponement_period: "AM", postponement_kind: "due" },
    { ...row, task_id: "afternoon", title: "Afternoon change", am_pm: "AM", postponement_period: "PM", postponement_kind: "due" },
  ] } })
  const morning = html.slice(html.indexOf("AM — PARA PAUZËS"), html.indexOf("PM — PAS PAUZËS"))
  const afternoon = html.slice(html.indexOf("PM — PAS PAUZËS"))
  assert.match(morning, /Morning change/)
  assert.doesNotMatch(morning, /Afternoon change/)
  assert.match(afternoon, /Afternoon change/)
  assert.doesNotMatch(afternoon, /Morning change/)
})

test("legacy GA rows and answers stay out of the report and the GA filter is removed", () => {
  const html = render({ data: { ga_postponed: [{ ...row, title: "Old GA-only task" }] } }, { ga_reorganization: "GA saved answer" })
  assert.doesNotMatch(html, /GA saved answer|Old GA-only task|ga-points-title/)
  const page = renderToStaticMarkup(React.createElement(Page))
  assert.doesNotMatch(page, />GA<\/button>|M3 \/ GA/)
})

test("untouched splits SYS tasks and priority styling overrides status colors", () => {
  const html = renderToStaticMarkup(React.createElement(ReportingTaskTable, { kind: "untouched", rows: [
    { ...row, task_id: "regular", title: "Deadline task", deadline_important: true },
    { ...row, task_id: "system", title: "08:00 System task", task_type: "SYS", is_system_task: true, marker: "👁" },
  ] }))
  assert.equal((html.match(/<table /g) || []).length, 2)
  assert.match(html, /DET FT DHE PRJK PA PROGRES:/)
  assert.match(html, /DETYRAT E SISTEMIT PA PROGRES:/)
  assert.match(html, /background-color:#dc2626;color:#ffffff/)
  assert.match(html, /border-top:3px solid #dc2626/)
  assert.match(html, /border-right:3px solid #dc2626/)
  assert.equal((html.match(/Deadline task/g) || []).length, 1)
  assert.equal((html.match(/08:00 System task/g) || []).length, 1)
  assert.match(html, /data-task-symbol="true">👁<\/strong>/)
})

test("realization includes saved department percentages and missing data", () => {
  const html = render({ realization: { percent: 62, comment: "Staff summary", employees: 8, departments: [
    { department_id: "dev", code: "DEV", percent: 75, comment: "Above 50" },
    { department_id: "gd", code: "GD", percent: 25, comment: "Below 50" },
    { department_id: "pcm", code: "PCM", percent: null, comment: "Missing baseline" },
    { department_id: "ga", code: "GA", percent: null, comment: "Hidden GA comment" },
    { department_id: "hr", code: "HR", percent: null, comment: "Hidden HR comment" },
  ] } })
  assert.match(html, /62%/)
  assert.match(html, /75%/)
  assert.match(html, /25%/)
  assert.match(html, /Pa të dhëna/)
  assert.match(html, />DEP<\/th>/)
  assert.doesNotMatch(html, /Hidden GA comment|Hidden HR comment|>GA<\/td>|>HR<\/td>/)
})

test("postponement cells carry risk colors and My View comments while status stays implicit", () => {
  const rows = [{ ...row, task_id: "safe", postponement_kind: "start_due", risk: "OK", comment: "Klienti kërkoi ndryshim" },
                { ...row, task_id: "risky", postponement_kind: "start_due", risk: "RREZIK", comment: "Për të premten" }]
  const html = renderToStaticMarkup(React.createElement(ReportingTaskTable, { rows, kind: "postponed" }))
  assert.match(html, /<td[^>]*bg-green-100[^>]*>OK<\/td>/)
  assert.match(html, /<td[^>]*bg-red-100[^>]*>RREZIK<\/td>/)
  assert.match(html, /Klienti kërkoi ndryshim/)
  assert.match(html, />KOMENTI<\/th>/)
  assert.doesNotMatch(html, /STATUSI/)
  assert.match(html, />AM\/PM<\/th>/)
  assert.match(html, />LLOJI<\/th>/)
  assert.match(html, />EF<\/td>/)
  assert.match(html, />DEV<\/td>/)
  assert.match(html, />1H<\/td>/)
})

test("task tables show status colors and uppercase headers without progress columns", () => {
  const html = render({ data: { untouched: [row], postponed: [{ ...row, task_id: "done", status: "DONE", progress: 100 }] } })
  assert.match(html, /TODO/)
  assert.doesNotMatch(html, /65%/)
  assert.doesNotMatch(html, />DONE<\/td>/)
  assert.doesNotMatch(html, /100%/)
  assert.match(html, /background-color:#FFC4ED/)
  assert.match(html, /background-color:#C4FDC4/)
  assert.match(html, />TITULLI<\/th>/)
  assert.match(html, />KUSH<\/th>/)
  assert.doesNotMatch(html, />STATUSI<\/th>/)
  assert.doesNotMatch(html, /<th[^>]*>[^<]*[Pp][Rr][Oo][Gg][Rr][Ee][Ss][Ii]/)
})

test("postponements use separate tables and stacked NGA NE dates with wrapped title width", () => {
  const both = { ...row, task_id: "both", title: "Të dyja datat", old_start_date: "2026-10-05", start_date: "2026-10-07", old_due_date: "2026-10-05", due_date: "2026-10-08", postponement_kind: "start_due" }
  const due = { ...row, task_id: "due", title: "Vetëm Due", old_start_date: "2026-10-05", start_date: "2026-10-05", old_due_date: "2026-10-05", due_date: "2026-10-09", postponement_kind: "due" }
  const html = renderToStaticMarkup(React.createElement(ReportingTaskTable, { rows: [due, both], kind: "postponed" }))
  assert.equal((html.match(/<table /g) || []).length, 2)
  assert.match(html, /SHTYER START DHE DUE DATE:/)
  assert.match(html, /SHTYER DUE DATE:/)
  assert.match(html, />NGA<\/th>/)
  assert.match(html, />NE<\/th>/)
  assert.match(html, /START: 05.10.2026<\/span>/)
  assert.match(html, /border-b-\[3px\] border-black/)
  assert.match(html, /DUE: 08.10.2026<\/span>/)
  assert.equal((html.match(/Të dyja datat<\/div>/g) || []).length, 1)
  assert.equal((html.match(/Vetëm Due<\/div>/g) || []).length, 1)
  assert.match(html, /table-fixed/)
  assert.match(html, /width:28px/)
  assert.match(html, /width:42px/)
  assert.match(html, /width:44px/)
  assert.match(html, /width:88px/)
  assert.match(html, /<col\/><col style="width:124px"/)
  assert.match(html, /w-full whitespace-normal break-words/)
})

test("TODO and same-day hide dates and same-day excludes Done tasks", () => {
  const untouched = renderToStaticMarkup(React.createElement(ReportingTaskTable, { rows: [row], kind: "untouched" }))
  assert.doesNotMatch(untouched, />START<\/th>|>DUE<\/th>/)
  const rows = [{ ...row, task_id: "done", title: "Done title", status: "DONE" },
                { ...row, task_id: "active", title: "Active title", status: "IN_PROGRESS" },
                { ...row, task_id: "todo", title: "Todo title" }]
  const html = renderToStaticMarkup(React.createElement(ReportingTaskTable, { rows, kind: "same_day" }))
  assert.doesNotMatch(html, />CREATION \/ START \/ DUE<\/th>|CREATION:|START:|DUE:/)
  assert.match(html, />ARSYEJA<\/th>/)
  assert.match(html, />KOMENTI<\/th>/)
  assert.ok(html.indexOf("Active title</div>") < html.indexOf("Todo title</div>"))
  assert.doesNotMatch(html, /Done title/)
  const empty = renderToStaticMarkup(React.createElement(ReportingTaskTable, { rows: [rows[0]], kind: "same_day" }))
  assert.match(empty, /Asnjë detyrë për këtë pikë/)
  assert.doesNotMatch(empty, /<table/)
})

test("manual questions are stacked and the header matches the M3 workspace structure", () => {
  const html = render()
  assert.doesNotMatch(html, /md:grid-cols-2/)
  auth.user = { role: "MANAGER", full_name: "Test Manager" }
  const page = renderToStaticMarkup(React.createElement(Page))
  assert.match(page, /Rifresko/)
  assert.match(page, /Gjenero raportin/)
  assert.match(page, /Titulli i email-it/)
  assert.match(page, /role="tab"/)
  assert.match(page, /Raporti/)
  assert.match(page, /Historiku/)
  assert.doesNotMatch(page, />GA<\/button>/)
})

test("manual draft survives a reload, stays scoped to user and day, and protects newer edits", () => {
  const { readManualDraft, writeManualDraft, clearSavedManualDraft } = load("@/lib/m3-reporting-points-draft")
  const values = new Map()
  const storage = { getItem: (key) => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) }
  writeManualDraft(storage, "user", "2026-10-05", { underload: "Përgjigje me\nrreshta" })
  assert.equal(readManualDraft(storage, "user", "2026-10-05").underload, "Përgjigje me\nrreshta")
  assert.equal(readManualDraft(storage, "other-user", "2026-10-05"), null)
  assert.equal(readManualDraft(storage, "user", "2026-10-06"), null)
  writeManualDraft(storage, "user", "2026-10-05", { underload: "Teksti më i ri" })
  clearSavedManualDraft(storage, "user", "2026-10-05", { underload: "Përgjigje me\nrreshta" })
  assert.equal(readManualDraft(storage, "user", "2026-10-05").underload, "Teksti më i ri")
  clearSavedManualDraft(storage, "user", "2026-10-05", { underload: "Teksti më i ri" })
  assert.equal(readManualDraft(storage, "user", "2026-10-05"), null)
  assert.equal(readManualDraft(null, "user", "2026-10-05"), null)
})

test("only the task title is rendered even for an older multiline saved report", () => {
  const html = render({ data: { untouched: [{ ...row, title: "[[added]]DT: Titulli due 16:00[[/added]]\n1. Pershkrimi i plote\n2. Hapi tjeter" }] } })
  assert.match(html, /DT: Titulli/)
  assert.doesNotMatch(html, /Pershkrimi i plote|Hapi tjeter|\[\[added\]\]|due 16:00/)
})

test("the stored realization is displayed and missing data never becomes zero", () => {
  const html = render({ realization: { percent: 62, employees: 10, comment: "Jemi mbi 50%", people: [] }, realization_captured_at: "2026-10-05T16:15:00+02:00" })
  assert.match(html, /62%/)
  assert.match(html, /16:15/)
  assert.match(html, /10 persona/)
  assert.doesNotMatch(render(), />0%/)
  assert.match(render(), /Nuk ka ende një vlerë të ruajtur/)
})

test("view-only reports keep manual fields disabled", () => {
  const html = render({ status: "SENT" }, {}, true)
  assert.equal((html.match(/<textarea[^>]*disabled=""/g) || []).length, 3)
})

test("staff can open the report and generate it while management actions remain restricted", () => {
  auth.user = { role: "STAFF", full_name: "Test User" }
  const html = renderToStaticMarkup(React.createElement(Page))
  assert.match(html, /Gjenero raportin/)
  assert.match(html, /Historiku/)
  assert.doesNotMatch(html, /Hyr në platformë|Ruaj përgjigjet/)
  assert.doesNotMatch(html, /<button[^>]*>[^<]*Dërgo<\/button>/)
})

test("report managers retain manual answers and send controls", () => {
  auth.user = { role: "MANAGER", full_name: "Test Manager" }
  const html = renderToStaticMarkup(React.createElement(Page))
  assert.match(html, /Gjenero raportin/)
  assert.match(html, /Ruaj përgjigjet/)
  assert.match(html, /Dërgo<\/button>/)
})

// Exercise the page's save effects and user events without browser dependencies.
function mountPage(storage, apiFetch, user = { id: "manager", role: "MANAGER" }) {
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
  const source = readFileSync(path.join(src, "app", "(app)", "m3-reporting-points", "page.tsx"), "utf8")
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText
  const pageModule = { exports: {} }
  vm.runInNewContext(compiled, {
    module: pageModule, exports: pageModule.exports,
    require: (name) => name === "react" ? hooks : name === "@/lib/auth" ? { useAuth: () => ({ user, loading: false, apiFetch }) } : load(name),
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
  const findView = (node) => findNode(node, (item) => item.type === M3ReportingPointsView)
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
    meetingCommentsDisabled() { return findView(tree).props.meetingCommentsDisabled },
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
  let server = { ...report, report_date: day, status: "SENT", sent_at: new Date().toISOString(), generated_at: new Date().toISOString(), realization_captured_at: new Date().toISOString() }
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
    page.edit("underload", `Përgjigjja ${i}`)
    await page.flush()
    await page.fireSave()
    await page.flush()
    assert.equal(server.manual_answers["underload"], `Përgjigjja ${i}`)
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

test("M3 delivery choices and answers survive reload and autosave", async () => {
  const id = "11111111-1111-4111-8111-111111111111"
  const values = new Map()
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Tirane", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date())
  let server = { ...report, report_date: day, data: { delivery: [{ ...row, task_id: id, marker: "M3" }] } }
  const api = async (url, options) => {
    if (options?.method === "PUT") server = { ...server, manual_answers: JSON.parse(options.body).manual_answers }
    return { ok: true, status: 200, json: async () => url.endsWith("/recipients") ? { recipients: { to: [], cc: [], bcc: [] } } : { ...server } }
  }
  const first = mountPage(storage, api)
  await first.flush()
  first.edit(`delivery_choice:${id}`, "PO")
  await first.flush()
  first.edit(`delivery:${id}`, "Dorezuar M3")
  await first.flush()
  first.unmount()
  const reloaded = mountPage(storage, api)
  await reloaded.flush()
  assert.equal(reloaded.answers()[`delivery_choice:${id}`], "PO")
  assert.equal(reloaded.answers()[`delivery:${id}`], "Dorezuar M3")
  await reloaded.fireSave()
  await reloaded.flush()
  assert.equal(server.manual_answers[`delivery_choice:${id}`], "PO")
  assert.equal(server.manual_answers[`delivery:${id}`], "Dorezuar M3")
  assert.equal(values.size, 0)
  reloaded.unmount()
})

test("send waits for realization capture while answers remain editable", async () => {
  const storage = { getItem: () => null, setItem: () => {}, removeItem: () => {} }
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Tirane", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date())
  let server = { ...report, report_date: day, generated_at: new Date().toISOString() }
  const api = async (url) => {
    if (url.includes("/generate?")) server = { ...server, realization_captured_at: new Date().toISOString() }
    return { ok: true, status: 200, json: async () => url.endsWith("/recipients") ? { recipients: { to: ["test@example.com"], cc: [], bcc: [] } } : { ...server } }
  }
  const page = mountPage(storage, api)
  await page.flush()
  assert.equal(page.viewDisabled(), false)
  assert.equal(page.buttonDisabled("Dërgo"), true)
  await page.click("Gjenero raportin")
  await page.flush()
  assert.equal(page.buttonDisabled("Dërgo"), false)
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
  first.edit("underload", "Ndryshim pas dërgimit")
  await first.flush()
  first.unmount()
  const reloaded = mountPage(storage, api)
  await reloaded.flush()
  assert.equal(reloaded.answers()["underload"], "Ndryshim pas dërgimit")
  await reloaded.fireSave()
  await reloaded.flush()
  assert.equal(server.manual_answers["underload"], "Ndryshim pas dërgimit")
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
  first.edit("underload", "Përgjigje që duhet të mbetet")
  await first.flush()
  first.unmount() // Refresh before the debounce fires.
  const reloaded = mountPage(storage, api)
  await reloaded.flush()
  assert.equal(reloaded.answers().underload, "Përgjigje që duhet të mbetet")
  await reloaded.fireSave()
  await reloaded.flush()
  assert.equal(server.manual_answers.underload, "Përgjigje që duhet të mbetet")
  assert.equal(values.size, 0)
  reloaded.unmount()
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
      saved.push(answers.underload)
      if (saved.length === 1) await new Promise((resolve) => { resolveFirst = resolve })
      server = { ...server, manual_answers: answers }
    }
    return { ok: true, status: 200, json: async () => url.endsWith("/recipients") ? { recipients: { to: [], cc: [], bcc: [] } } : { ...server } }
  }
  const page = mountPage(storage, api)
  await page.flush()
  page.edit("underload", "Teksti fillestar")
  await page.flush()
  const firstSave = page.fireSave()
  await page.flush()
  page.edit("underload", "Teksti më i ri")
  await page.flush()
  resolveFirst()
  await firstSave
  await page.flush()
  assert.equal(page.answers().underload, "Teksti më i ri")
  await page.fireSave()
  await page.flush()
  assert.deepEqual(saved, ["Teksti fillestar", "Teksti më i ri"])
  assert.equal(server.manual_answers.underload, "Teksti më i ri")
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
  page.edit("underload", "Mos e humb përgjigjen")
  await page.flush()
  await page.fireSave()
  await page.flush()
  assert.equal(page.answers().underload, "Mos e humb përgjigjen")
  page.unmount()
  const reloaded = mountPage(storage, api)
  await reloaded.flush()
  assert.equal(reloaded.answers().underload, "Mos e humb përgjigjen")
  reloaded.unmount()
})


test("M3 shows only canceled meetings in separate EXT and INT tables with M3 RAP columns and colours", () => {
  const intId = "11111111-1111-4111-8111-111111111111"
  const extId = "22222222-2222-4222-8222-222222222222"
  const data = { unheld_meetings: [
    { meeting_id: intId, meeting_type: "INT", occurrence_date: report.report_date, title: "Team sync", time: "10:00", status: "canceled", status_label: "Anuluar", origin: "MANUAL", fill: "#FFF4CC", highlighted: true },
    { meeting_id: extId, meeting_type: "EXT", occurrence_date: report.report_date, title: "Client call", time: "15:00", status: "canceled", status_label: "Anuluar", origin: "CAL", fill: "#C9A98A", highlighted: true },
    { meeting_id: "held", occurrence_date: report.report_date, meeting_type: "INT", title: "Already held", status: "held" },
    { meeting_id: "unmarked", occurrence_date: report.report_date, meeting_type: "INT", title: "Not marked yet", status: "" },
    { meeting_id: "yesterday", occurrence_date: "2026-10-04", meeting_type: "EXT", title: "Canceled yesterday", status: "canceled" },
  ] }
  const answers = { ["meeting_plan:" + intId]: "Nesër 10:00", ["meeting_plan:" + extId]: "Të premten" }
  const html = render({ data }, answers)
  assert.match(html, /4\. TAK INT\/EXT TË ANULUARA/)
  assert.match(html, /Kur planifikohen\?/)
  assert.match(html, /Nesër 10:00/)
  assert.match(html, /Të premten/)
  assert.match(html, /aria-label="TAK EXTERNE"/)
  assert.match(html, /aria-label="TAK INTERNE"/)
  assert.match(html, />KOHA<\/th>/)
  assert.match(html, />MBAJTUR\?<\/th>/)
  assert.match(html, /background-color:#FFF4CC/)
  assert.match(html, /background-color:#C9A98A/)
  assert.match(html, /border-y-blue-600/)
  assert.match(html, />CAL<\/strong>/)
  assert.match(html, />MANUAL<\/strong>/)
  assert.ok(html.indexOf("Client call") < html.indexOf("Team sync"))
  assert.doesNotMatch(html, /Already held|Not marked yet|Canceled yesterday|>TIPI<\/th>|>STATUSI<\/th>/)
  assert.equal((html.match(/<textarea/g) || []).length, 5)
  assert.equal((render({ data }, answers, true).match(/<textarea[^>]*disabled=""/g) || []).length, 5)
})


test("meeting planning comments survive reload, autosave, and Generate independently", async () => {
  const values = new Map()
  const storage = { getItem: (key) => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) }
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Tirane", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date())
  const key = "meeting_plan:11111111-1111-4111-8111-111111111111"
  const secondKey = "meeting_plan:22222222-2222-4222-8222-222222222222"
  let server = { ...report, report_date: day, generated_at: new Date().toISOString(), manual_answers: { [secondKey]: "Pasnesër" } }
  const api = async (url, options) => {
    if (options?.method === "PUT") server = { ...server, manual_answers: JSON.parse(options.body).manual_answers }
    return { ok: true, status: 200, json: async () => url.endsWith("/recipients") ? { recipients: { to: [], cc: [], bcc: [] } } : { ...server } }
  }
  const first = mountPage(storage, api)
  await first.flush()
  first.edit(key, "Nesër 10:00")
  await first.flush()
  first.unmount()
  const reloaded = mountPage(storage, api)
  await reloaded.flush()
  assert.equal(reloaded.answers()[key], "Nesër 10:00")
  assert.equal(reloaded.answers()[secondKey], "Pasnesër")
  await reloaded.fireSave()
  await reloaded.flush()
  assert.equal(server.manual_answers[key], "Nesër 10:00")
  assert.equal(server.manual_answers[secondKey], "Pasnesër")
  assert.equal(values.size, 0)
  await reloaded.click("Gjenero raportin")
  await reloaded.flush()
  assert.equal(reloaded.answers()[key], "Nesër 10:00")
  reloaded.unmount()
})


test("staff meeting comments are editable and autosave only comments after reload", async () => {
  const values = new Map()
  const storage = { getItem: (key) => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) }
  const key = "meeting_plan:11111111-1111-4111-8111-111111111111"
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Tirane", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date())
  const user = { id: "staff", role: "STAFF", full_name: "Staff" }
  let server = { ...report, report_date: day, status: "SENT", manual_answers: { underload: "Manager answer" } }
  const api = async (url, options) => {
    if (options?.method === "PUT") {
      const changed = JSON.parse(options.body).manual_answers
      assert.deepEqual(Object.keys(changed), [key])
      server = { ...server, manual_answers: { ...server.manual_answers, ...changed } }
    }
    return { ok: true, status: 200, json: async () => ({ ...server }) }
  }
  const first = mountPage(storage, api, user)
  await first.flush()
  assert.equal(first.viewDisabled(), true)
  assert.equal(first.meetingCommentsDisabled(), false)
  first.edit(key, "Nesër pas pauzës")
  await first.flush()
  first.unmount()
  const reloaded = mountPage(storage, api, user)
  await reloaded.flush()
  assert.equal(reloaded.answers()[key], "Nesër pas pauzës")
  await reloaded.fireSave()
  await reloaded.flush()
  assert.equal(server.manual_answers[key], "Nesër pas pauzës")
  assert.equal(server.manual_answers.underload, "Manager answer")
  assert.equal(values.size, 0)
  reloaded.unmount()
})


test("meeting comments stay editable during Generate and newer text survives its response", async () => {
  const values = new Map()
  const storage = { getItem: (key) => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) }
  const key = "meeting_plan:11111111-1111-4111-8111-111111111111"
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Tirane", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date())
  let server = { ...report, report_date: day }, finishGenerate
  const api = async (url, options) => {
    if (url.includes("/generate?")) await new Promise((resolve) => { finishGenerate = resolve })
    if (options?.method === "PUT") server = { ...server, manual_answers: JSON.parse(options.body).manual_answers }
    return { ok: true, status: 200, json: async () => url.endsWith("/recipients") ? { recipients: { to: [], cc: [], bcc: [] } } : { ...server } }
  }
  const page = mountPage(storage, api)
  await page.flush()
  const generating = page.click("Gjenero raportin")
  await page.flush()
  assert.equal(page.viewDisabled(), true)
  assert.equal(page.meetingCommentsDisabled(), false)
  page.edit(key, "Koment gjatë gjenerimit")
  await page.flush()
  finishGenerate()
  await generating
  await page.flush()
  assert.equal(page.answers()[key], "Koment gjatë gjenerimit")
  await page.fireSave()
  await page.flush()
  assert.equal(server.manual_answers[key], "Koment gjatë gjenerimit")
  page.unmount()
})


test("meeting textarea remains enabled while manager question fields are locked", () => {
  const data = { unheld_meetings: [{ meeting_id: "11111111-1111-4111-8111-111111111111", occurrence_date: report.report_date,
    meeting_type: "INT", title: "Canceled meeting", time: "10:00", status: "canceled", status_label: "Anuluar" }] }
  const html = renderToStaticMarkup(React.createElement(M3ReportingPointsView, {
    report: { ...report, data }, answers: {}, disabled: true, meetingCommentsDisabled: false, onAnswerChange: () => {},
  }))
  const fields = html.match(/<textarea[^>]*>/g) || []
  assert.equal(fields.length, 4)
  assert.equal(fields.filter((field) => field.includes('disabled=""')).length, 3)
  const comment = fields.find((field) => field.includes('aria-label="Kur planifikohen?'))
  assert.ok(comment)
  assert.doesNotMatch(comment, /\sdisabled(?:=|\s|>)/)
})


test("INT meetings display Common View PARA and PAS badges without labeling standalone meetings", () => {
  const rows = [
    { meeting_id: "before", meeting_type: "INT", occurrence_date: report.report_date, title: "Prep", time: "12:00", status: "canceled", meeting_relation: "PARA", origin: "CAL", fill: "#C9A98A" },
    { meeting_id: "after", meeting_type: "INT", occurrence_date: report.report_date, title: "Follow-up", time: "14:20", status: "canceled", meeting_relation: "PAS", origin: "CAL", fill: "#C9A98A" },
    { meeting_id: "manual", meeting_type: "INT", occurrence_date: report.report_date, title: "Standalone", time: "14:14", status: "canceled", meeting_relation: null, origin: "MANUAL", fill: "#FFF4CC" },
  ]
  const html = render({ data: { unheld_meetings: rows } })
  assert.match(html, /title="Para takimit extern">PARA<\/span>/)
  assert.match(html, /title="Pas takimit extern">PAS<\/span>/)
  assert.equal((html.match(/takimit extern/g) || []).length, 2)
  assert.match(html, /Standalone/)
})
