import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import { test } from "node:test"
import vm from "node:vm"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import ts from "typescript"

const require = createRequire(import.meta.url)

function load(file, dependencies = {}) {
  const loadedModule = { exports: {} }
  const source = readFileSync(new URL(`../${file}`, import.meta.url), "utf8")
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  })
  vm.runInNewContext(outputText, {
    module: loadedModule, exports: loadedModule.exports,
    require: (name) => dependencies[name] ?? require(name),
    URLSearchParams,
  })
  return loadedModule.exports
}

const types = load("src/components/knowledge/prompt-types.ts")
const search = load("src/components/knowledge/prompt-search.tsx")
const config = load("src/components/knowledge/knowledge-config.tsx")

function prompt(id, status, extra = {}) {
  return {
    id, status, title: `Prompt ${id}`, content: `Content ${id}`, keywords: [],
    created_by: { id: "author", full_name: "Author" },
    created_at: "2026-10-01T10:00:00Z", updated_at: "2026-10-01T10:00:00Z",
    ...extra,
  }
}

function note(id, tasks = [], prompts = [], extra = {}) {
  return { id, content: `Request ${id}`, status: "OPEN", tasks, prompts, created_at: "2026-10-01T10:00:00Z", ...extra }
}

test("active requests include unassigned notes, author tasks and every pending review stage", () => {
  const cases = [
    note("no-task"),
    ...["TODO", "IN_PROGRESS", "WAITING_CLIENT", "WAITING_CONFIRMATION", "DONE"].map((status) => note(status, [{ status }])),
    ...["PENDING_TEST", "PENDING_APPROVAL", "REJECTED"].map((status) => note(status, [{ status: "DONE" }], [prompt(status, status)])),
  ]
  for (const request of cases) assert.equal(types.promptNoteMatchesFilter(request, "ACTIVE"), true, request.id)
  assert.equal(types.promptNoteStage(cases.find((n) => n.id === "DONE")), "READY")
})

test("an approved prompt does not hide another prompt still waiting on the same request", () => {
  for (const status of ["PENDING_TEST", "PENDING_APPROVAL", "REJECTED"]) {
    const request = note("mixed", [{ status: "DONE" }], [prompt("approved", "APPROVED"), prompt("pending", status)], { status: "CLOSED" })
    assert.equal(types.promptNoteStage(request), "IN_REVIEW")
    assert.equal(types.promptNoteMatchesFilter(request, "ACTIVE"), true)
    assert.equal(types.promptNoteMatchesFilter(request, status), true)
  }
})

test("fulfilled and manually closed requests stay in history and not the active queue", () => {
  for (const request of [note("fulfilled", [], [prompt("approved", "APPROVED")]), note("closed", [], [], { status: "CLOSED" })]) {
    assert.equal(types.promptNoteMatchesFilter(request, "ACTIVE"), false)
    assert.equal(types.promptNoteMatchesFilter(request, "ALL"), true)
  }
})

test("unfinished author tasks remain visible even after the prompt is approved", () => {
  const request = note("unfinished", [{ status: "WAITING_CONFIRMATION" }], [prompt("approved", "APPROVED")], { status: "CLOSED" })
  assert.equal(types.promptNoteStage(request), "TASK_OPEN")
  assert.equal(types.promptNoteMatchesFilter(request, "ACTIVE"), true)
})

test("review filters distinguish testing, approval and rejected prompts", () => {
  for (const status of ["PENDING_TEST", "PENDING_APPROVAL", "REJECTED"]) {
    const request = note("review", [], [prompt("review", status)])
    assert.equal(types.promptNoteMatchesFilter(request, status), true)
    assert.equal(types.promptNoteMatchesFilter(request, "IN_REVIEW"), true)
    assert.equal(types.promptNoteMatchesFilter(request, "READY"), false)
  }
})

test("all-prompts filter includes standalone prompts in every status while library includes only approved", () => {
  for (const status of ["PENDING_TEST", "PENDING_APPROVAL", "APPROVED", "REJECTED"]) {
    const entry = prompt("standalone", status)
    assert.equal(types.promptMatchesFilter(entry, "ALL"), true)
    assert.equal(types.promptMatchesFilter(entry, "APPROVED"), status === "APPROVED")
  }
})

test("my-action filter includes both test and approval and preserves author/tester separation", () => {
  const testPrompt = prompt("test", "PENDING_TEST", { tester: { id: "manager" } })
  const approvalPrompt = prompt("approval", "PENDING_APPROVAL", { tested_by: { id: "tester" } })
  assert.equal(types.promptMatchesFilter(testPrompt, "WAITING_FOR_ME", "manager", true), true)
  assert.equal(types.promptMatchesFilter(approvalPrompt, "WAITING_FOR_ME", "manager", true), true)
  assert.equal(types.promptMatchesFilter(testPrompt, "WAITING_FOR_ME", "author", true), false)
  assert.equal(types.promptMatchesFilter(testPrompt, "WAITING_FOR_ME", "someone-else", true), false)
  assert.equal(types.promptMatchesFilter(approvalPrompt, "WAITING_FOR_ME", "tester", true), false)
  assert.equal(types.promptMatchesFilter(approvalPrompt, "WAITING_FOR_ME", "author", true), false)
  assert.equal(types.promptMatchesFilter(approvalPrompt, "WAITING_FOR_ME", "staff", false), false)
})

function renderPage(view, kind = "PROMPT") {
  const approved = prompt("approved", "APPROVED")
  const testing = prompt("testing", "PENDING_TEST", { source_note_id: "test", tester: { id: "manager" }, test_task_status: "TODO" })
  const approval = prompt("approval", "PENDING_APPROVAL", { source_note_id: "approval", tested_by: { id: "tester" } })
  const standaloneTest = prompt("standalone-test", "PENDING_TEST", { tester: { id: "manager" } })
  const standaloneApproval = prompt("standalone-approval", "PENDING_APPROVAL", { tested_by: { id: "tester" } })
  const requests = [
    note("new"),
    note("author", [{ id: "task", title: "Author task", status: "WAITING_CONFIRMATION" }]),
    note("test", [], [testing]),
    note("approval", [{ id: "completed", title: "Completed author task", status: "DONE" }], [approval]),
  ]
  // Supply the three loaded page datasets; all other hooks retain their real initial values.
  const datasets = [[approved, testing, approval, standaloneTest, standaloneApproval], requests, []]
  const react = {
    ...React,
    useState(initial) {
      if (Array.isArray(initial) && datasets.length) initial = datasets.shift()
      if (initial === true) initial = false // loading flags
      return React.useState(initial)
    },
  }
  const passthrough = ({ children }) => React.createElement("div", null, children)
  const params = new URLSearchParams(view ? { view } : {})
  const Page = load("src/components/knowledge/knowledge-page.tsx", {
    react,
    "./knowledge-config": config,
    "next/navigation": { usePathname: () => "/knowledge/prompts", useRouter: () => ({}), useSearchParams: () => params },
    "@/lib/auth": { useAuth: () => ({ user: { id: "manager", role: "MANAGER" }, apiFetch: () => {} }) },
    "@/lib/utils": { cn: (...values) => values.filter(Boolean).join(" ") },
    "@/components/knowledge/prompt-types": types,
    "@/components/knowledge/prompt-search": search,
    "@/components/knowledge/prompt-dialogs": { PromptDetailDialog: () => null, PromptFormDialog: () => null },
    "@/components/ui/button": { Button: ({ children, ...props }) => React.createElement("button", props, children) },
    "@/components/ui/input": { Input: (props) => React.createElement("input", props) },
    "@/components/ui/textarea": { Textarea: (props) => React.createElement("textarea", props) },
    "@/components/ui/select": Object.fromEntries(["Select", "SelectContent", "SelectItem", "SelectTrigger", "SelectValue"].map((name) => [name, passthrough])),
  }).default
  return renderToStaticMarkup(React.createElement(Page, { kind }))
}

test("default Prompts page renders notes, author/test tasks and testing/approval prompts immediately", () => {
  const html = renderPage()
  for (const text of ["Request new", "Author task", "PROMPT: TESTO: Prompt testing", "Request approval", "Content standalone-test", "Content standalone-approval"]) {
    assert.ok(html.includes(text), `Missing ${text}`)
  }
  assert.match(html, /aria-selected="true"[^>]*>[^]*?Notes/)
  assert.ok(!html.includes("Content approved"))
})

test("explicit library view preserves the approved library", () => {
  const html = renderPage("library")
  assert.ok(html.includes("Content approved"))
  assert.ok(!html.includes("Content testing"))
  assert.ok(!html.includes("Content approval"))
  assert.ok(!html.includes("Author task"))
})

test("existing Notes link still shows requests in test and confirmation", () => {
  const html = renderPage("notes")
  assert.ok(html.includes("Request test"))
  assert.ok(html.includes("Request approval"))
  assert.ok(!html.includes("Content approved"))
})

for (const [kind, title, prefix] of [["DEFINITION", "Definime", "DEFINIM"], ["REGULATION", "Rregullore", "RREGULLORE"]]) {
  test(`${title} uses the same notes and library with control labels`, () => {
    const html = renderPage("notes", kind)
    assert.ok(html.includes(title))
    assert.ok(html.includes(`${prefix}: KONTROLLO: Prompt testing`))
    assert.ok(html.includes("Në pritje të kontrollit"))
    assert.ok(!html.includes("PROMPT: TESTO:"))
    assert.ok(!html.includes("Në testim"))
    // Stored titles/content retain their original text, even when they contain 'Prompt'.
    assert.ok(html.includes("Prompt testing"))
    const library = renderPage("library", kind)
    assert.ok(library.includes("Content approved"))
    assert.ok(!library.includes("Content testing"))
  })
}

test("category interface copy distinguishes control from testing", () => {
  for (const kind of ["DEFINITION", "REGULATION"]) {
    assert.equal(config.knowledgeText(kind, "E testova"), "E kontrollova")
    assert.equal(config.knowledgeText(kind, "Zgjidh personin që do ta testojë"), "Zgjidh personin që do ta kontrollojë")
    assert.match(config.knowledgeText(kind, "Komenti i testimit (opsional)"), /kontrollit/)
  }
  assert.equal(config.knowledgeText("PROMPT", "E testova"), "E testova")
})

test("task links open the correct knowledge category", () => {
  const links = load("src/components/knowledge/prompt-link.tsx", { "next/link": () => null })
  const id = "12345678-1234-1234-1234-123456789abc"
  for (const category of ["prompts", "definime", "rregullore"]) {
    assert.equal(links.promptHrefFromText(`https://example.com/knowledge/${category}?prompt=${id}`), `/knowledge/${category}?prompt=${id}`)
  }
  assert.equal(links.promptHrefFromText("Regular task"), null)
})

for (const kind of ["DEFINITION", "REGULATION", "PROMPT"]) {
  test(`${kind} review confirmation calls the appropriate action`, async () => {
    const entry = prompt("review", "PENDING_TEST", { knowledge_type: kind, tester: { id: "reviewer" } })
    const calls = []
    const states = [false, "test", "Checked"]
    const passthrough = ({ children }) => React.createElement("div", null, children)
    const dialogs = load("src/components/knowledge/prompt-dialogs.tsx", {
      react: { ...React, useState: () => [states.shift(), () => {}], useEffect: () => {} },
      "./knowledge-config": { useKnowledge: () => ({ kind, text: (value) => config.knowledgeText(kind, value) }) },
      "./prompt-types": types,
      "@/lib/auth": { useAuth: () => ({ user: { id: "reviewer", role: "STAFF" }, apiFetch: async (path, options) => { calls.push({ path, options }); return { ok: true, json: async () => ({ ...entry, status: "PENDING_APPROVAL" }) } } }) },
      "@/lib/utils": { cn: (...values) => values.filter(Boolean).join(" ") },
      "@/lib/users-cache": {},
      "@/components/ui/button": { Button: ({ children }) => React.createElement("button", null, children) },
      "@/components/ui/badge": { Badge: passthrough },
      "@/components/ui/input": { Input: () => null },
      "@/components/ui/label": { Label: passthrough },
      "@/components/ui/textarea": { Textarea: () => null },
      "@/components/ui/select": Object.fromEntries(["Select", "SelectContent", "SelectItem", "SelectTrigger", "SelectValue"].map((name) => [name, passthrough])),
      "@/components/ui/dialog": Object.fromEntries(["Dialog", "DialogContent", "DialogDescription", "DialogFooter", "DialogHeader", "DialogTitle"].map((name) => [name, passthrough])),
    })
    let changed
    const tree = dialogs.PromptDetailDialog({ prompt: entry, onClose() {}, onChanged(value) { changed = value }, onDeleted() {}, onEdit() {} })
    const actionLabel = kind === "PROMPT" ? "Konfirmo testimin" : "Konfirmo kontrollin"
    let confirm
    function find(node) {
      if (Array.isArray(node)) return node.forEach(find)
      if (!React.isValidElement(node)) return
      if (node.props.onClick && renderToStaticMarkup(node).includes(actionLabel)) confirm = node
      find(node.props.children)
    }
    find(tree)
    assert.ok(confirm, `Missing ${actionLabel}`)
    await confirm.props.onClick()
    // UI handlers launch the promise without returning it.
    await new Promise((resolve) => setImmediate(resolve))
    assert.equal(calls[0].path, `/knowledge/prompts/review/${kind === "PROMPT" ? "confirm-test" : "confirm-control"}`)
    assert.equal(JSON.parse(calls[0].options.body).comment, "Checked")
    assert.equal(changed.status, "PENDING_APPROVAL")
  })
}
