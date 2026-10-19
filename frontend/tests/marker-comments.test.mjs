import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import { test } from "node:test"
import vm from "node:vm"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import ts from "typescript"

const require = createRequire(import.meta.url)
let context
let pathname = "/common"
let searchParams = ""
let teamItems = []
const item = {
  id: "receipt", task_id: "task", task_ids: ["task", "copy"], revision: "revision",
  title: "Task title", marker: "QUESTION", symbol: "?", comment: "Review with KA",
  author_name: "Comment author", updated_at: "2026-10-19T08:30:00Z", read_at: null,
  can_mark_read: true, is_mine: true, recipients: [{ user_id: "user", name: "First", initials: "F", read_at: null }],
  recipient_count: 1, read_count: 0, all_read: false,
}
const noop = () => {}
const component = (tag = "div") => ({ children }) => React.createElement(tag, null, children)
function load(relativePath, mockContextHook = false) {
  const source = readFileSync(new URL(relativePath, import.meta.url), "utf8")
  const loaded = { exports: {} }
  const localRequire = name => {
    if (name === "react") return { ...React, useContext: () => context, useState: initial => React.useState(Array.isArray(initial) ? teamItems : initial) }
    if (name === "next/navigation") return { usePathname: () => pathname, useSearchParams: () => new URLSearchParams(searchParams), useRouter: () => ({ replace: noop }) }
    if (name === "next/link") return { __esModule: true, default: ({ children, href }) => React.createElement("a", { href }, children) }
    if (name === "@/components/marker-comments-context") {
      if (mockContextHook) return { useMarkerComments: () => context }
      return load("../src/components/marker-comments-context.tsx")
    }
    if (name === "@/lib/auth") return { useAuth: () => ({ user: { id: "user" }, apiFetch: noop }) }
    if (name === "@/components/comment-task-edit-dialog") return { CommentTaskEditDialog: component() }
    if (name === "@/lib/note-markup") return load("../src/lib/note-markup.tsx")
    if (name === "@/lib/utils") return { cn: (...values) => values.filter(Boolean).join(" ") }
    if (name === "@/components/ui/button") return { Button: ({ children, ...props }) => {
      delete props.variant
      delete props.size
      delete props.asChild
      return React.createElement("button", props, children)
    } }
    if (name === "@/components/ui/dialog") return Object.fromEntries(["Dialog", "DialogContent", "DialogDescription", "DialogHeader", "DialogTitle"].map(name => [name, component()]))
    return require(name)
  }
  const { outputText } = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020,
    jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } })
  vm.runInNewContext(outputText, { module: loaded, exports: loaded.exports, require: localRequire, Map, Intl, URLSearchParams })
  return loaded.exports
}

const { TaskMarkerComment } = load("../src/components/task-marker-comment.tsx", true)
const { MarkerCommentsPanel } = load("../src/components/marker-comments-context.tsx")
const { default: CommentsPage } = load("../src/app/(app)/comments/page.tsx")
function setContext(values = [item]) {
  context = {
    items: values, unread: values.filter(item => !item.read_at),
    byTask: new Map(values.flatMap(item => item.task_ids.map(id => [id, item]))),
    loading: false, error: null, open: noop, openTask: noop, refresh: noop, markRead: noop,
  }
}

test("a shared task copy shows NEW only for its matching unread comment", () => {
  setContext()
  const render = comment => renderToStaticMarkup(React.createElement(TaskMarkerComment, { taskId: "copy", comment }))
  assert.match(render(item.comment), /E RE/)
  assert.match(render(item.comment), /role="button"/)
  assert.match(render(item.comment), /tabindex="0"/)
  assert.doesNotMatch(render("Older snapshot comment"), /E RE/)
  setContext([{ ...item, read_at: "2026-10-19T09:00:00Z" }])
  assert.doesNotMatch(render(item.comment), /E RE/)
})

test("comments remain available to open after reading and text is escaped", () => {
  setContext([])
  const html = renderToStaticMarkup(React.createElement(TaskMarkerComment, { taskId: "task", comment: '<script>alert("x")</script>' }))
  assert.match(html, /role="button"/)
  assert.match(html, /&lt;script&gt;/)
  assert.doesNotMatch(html, /<script>/)
})

test("persistent attention panel appears on Common View and department views", () => {
  setContext()
  for (const route of ["/common", "/departments/development", "/today-print-report"]) {
    pathname = route
    const html = renderToStaticMarkup(React.createElement(MarkerCommentsPanel))
    assert.match(html, /Simbole dhe komente të palexuara/)
    assert.match(html, /href="\/comments"/)
    assert.match(html, /aria-expanded="false"/)
  }
  setContext([])
  assert.equal(renderToStaticMarkup(React.createElement(MarkerCommentsPanel)), "")
})

test("the dedicated inbox displays unread comments with authors and both filters", () => {
  setContext([item, { ...item, id: "read", task_id: "other", task_ids: ["other"], read_at: "2026-10-19T09:00:00Z", comment: "Already read" }])
  const html = renderToStaticMarkup(React.createElement(CommentsPage))
  assert.match(html, /Të palexuara \(1\)/)
  assert.match(html, /Të miat \(2\)/)
  assert.match(html, /Gjendja e leximit/)
  assert.match(html, /Review with KA/)
  assert.match(html, /Comment author/)
  assert.match(html, /title="Comment author"[^>]*>CA<\/span>/)
  assert.doesNotMatch(html, />Comment author<\/td>/)
  assert.match(html, /<tr class="group bg-blue-100 text-blue-950 hover:bg-blue-200">/)
  assert.match(html, /Leximin e konfirmojnë vetëm personat përgjegjës të detyrës/)
  assert.match(html, /<table/)
  for (const column of ["NR", "SIMBOLI", "DETYRA", "KOMENTI", "NGA", "PËR", "DATA, ORA", "LEXIMI", "VEPRIMET"]) {
    assert.match(html, new RegExp(`scope="col"[^>]*>${column}</th>`))
  }
  assert.match(html, /Already read/)
  assert.match(html, /option value="all" selected=""/)
})

test("team viewers can only view; blue rows show pending recipients and completion names", () => {
  setContext([])
  searchParams = "scope=all&read=all"
  const read_at = "2026-10-19T09:00:00Z"
  const recipient = item.recipients[0]
  try {
    teamItems = [{ ...item, can_mark_read: false, is_mine: false, recipient_count: 2, read_count: 1,
      recipients: [{ ...recipient, read_at }, { user_id: "second", name: "Second", initials: "S", read_at: null }] }]
    let html = renderToStaticMarkup(React.createElement(CommentsPage))
    assert.match(html, /Lexuar 1\/2/)
    assert.match(html, /group bg-blue-100/)
    assert.match(html, />Shiko<\/button>/)
    assert.doesNotMatch(html, /Shëno si të lexuar|>Lexo komentin<\/button>/)
    assert.match(html, /First: Lexuar/)
    assert.match(html, /Second: Pa lexuar/)

    teamItems = [{ ...teamItems[0], read_count: 2, all_read: true }]
    html = renderToStaticMarkup(React.createElement(CommentsPage))
    assert.match(html, /Lexuar 2\/2/)
    assert.match(html, /group bg-white/)
    assert.doesNotMatch(html, /group bg-blue-100/)

    teamItems = [{ ...item, can_mark_read: false, is_mine: false, read_count: 1, all_read: true, recipients: [{ ...recipient, read_at }] }]
    html = renderToStaticMarkup(React.createElement(CommentsPage))
    assert.match(html, /Lexuar nga F/)
    teamItems = [{ ...item, can_mark_read: true, is_mine: true }]
    html = renderToStaticMarkup(React.createElement(CommentsPage))
    assert.match(html, />Lexo komentin<\/button>/)
    assert.match(html, /Shëno si të lexuar/)
  } finally { searchParams = ""; teamItems = [] }
})

test("the PX Notes destination selects comments across all departments", () => {
  setContext([])
  searchParams = "scope=all&read=all"
  try {
    const html = renderToStaticMarkup(React.createElement(CommentsPage))
    assert.match(html, /Simbolet dhe komentet e të gjithë përdoruesve, pavarësisht departamentit/)
    assert.match(html, /aria-pressed="true"[^>]*>Të gjitha/)
    assert.match(html, /option value="all" selected=""/)
  } finally { searchParams = "" }
})

test("new symbols without comments show unread with recipient initials and full names on hover", () => {
  setContext([{ ...item, marker: "M3", symbol: "M3", comment: "", recipient_count: 2, recipients: [
    { user_id: "ef", name: "Elsa Ferati", initials: "EF", read_at: null },
    { user_id: "ra", name: "Rinesa Ahmedi", initials: "RA", read_at: null },
  ] }])
  const html = renderToStaticMarkup(React.createElement(CommentsPage))
  assert.match(html, /Pa koment/)
  assert.match(html, />Lexo simbolin<\/button>/)
  assert.match(html, /group bg-blue-100/)
  assert.match(html, />E RE<\/span>/)
  assert.match(html, /title="Elsa Ferati"[^>]*>EF<\/span>/)
  assert.match(html, /title="Rinesa Ahmedi"[^>]*>RA<\/span>/)
})
