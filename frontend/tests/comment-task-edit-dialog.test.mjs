import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import { test } from "node:test"
import vm from "node:vm"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import ts from "typescript"

const require = createRequire(import.meta.url)
const placeholder = () => null
function load(path, overrides = {}) {
  const loaded = { exports: {} }
  const localRequire = (name) => {
    if (name in overrides) return overrides[name]
    if (name === "react") return React
    if (name === "next/dynamic") return { __esModule: true, default: () => placeholder }
    if (name === "@/components/comment-task-edit-dialog") return { CommentTaskEditDialog: placeholder }
    if (name === "@/lib/note-markup") return load("../src/lib/note-markup.tsx")
    if (name === "@/lib/auth") return { useAuth: () => ({ user: { id: "viewer" }, apiFetch: () => { throw new Error("Unexpected API request") } }) }
    if (name === "@/components/ui/button") return { Button: placeholder }
    if (name === "@/components/ui/dialog") return Object.fromEntries(["Dialog", "DialogContent", "DialogDescription", "DialogHeader", "DialogTitle"].map((key) => [key, placeholder]))
    if (name === "next/navigation") return { usePathname: () => "/comments" }
    return require(name)
  }
  const { outputText } = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
  })
  vm.runInNewContext(outputText, { module: loaded, exports: loaded.exports, require: localRequire, Map, Intl })
  return loaded.exports
}

const { loadCommentTaskEditor } = load("../src/components/comment-task-edit-dialog.tsx")
const response = (payload, ok = true) => ({ ok, json: async () => payload })

test("opening a note task loads its original PX note, not its shortened task title", async () => {
  for (const [field, prefix, source] of [["ga_note_origin_id", "ga-notes", "GA_KA"], ["plan_note_origin_id", "plan-notes", "PX_JAV"]]) {
    const calls = []
    const task = { id: "task", [field]: "note", title: "Short task title" }
    const note = { id: "note", content: "Full note with formatting", updated_at: "2026-10-19T10:00:00Z" }
    const result = await loadCommentTaskEditor(async (url) => {
      calls.push(url)
      return response(calls.length === 1 ? task : note)
    }, "task")
    assert.deepEqual(calls, ["/tasks/task", `/${prefix}/note`])
    assert.equal(result.note.content, note.content)
    assert.equal(result.note.updated_at, note.updated_at)
    assert.equal(result.note.source, source)
  }
})

test("ordinary tasks keep their task editor and failed lookups never open the wrong editor", async () => {
  let calls = 0
  const result = await loadCommentTaskEditor(async () => { calls++; return response({ id: "task", title: "Ordinary task" }) }, "task")
  assert.equal(result.note, null)
  assert.equal(result.task.id, "task")
  assert.equal(calls, 1)
  await assert.rejects(loadCommentTaskEditor(async () => response({}, false), "missing"), /Detyra nuk u ngarkua/)
  await assert.rejects(loadCommentTaskEditor(async (url) => url === "/tasks/task" ? response({ ga_note_origin_id: "missing" }) : response({}, false), "task"), /Shënimi i detyrës nuk u ngarkua/)
})

test("Hap detyrën keeps one open dialog while replacing the comment with the matching editor", () => {
  const states = []
  let cursor = 0
  const hooks = {
    ...React, useEffect: () => {}, useCallback: (fn) => fn, useMemo: (fn) => fn(), useRef: (value) => ({ current: value }),
    useState: (initial) => {
      const index = cursor++
      if (!(index in states)) states[index] = typeof initial === "function" ? initial() : initial
      return [states[index], (next) => { states[index] = typeof next === "function" ? next(states[index]) : next }]
    },
  }
  const { MarkerCommentsProvider } = load("../src/components/marker-comments-context.tsx", { react: hooks })
  const render = () => { cursor = 0; return MarkerCommentsProvider({ children: null }) }
  let tree = render()
  const title = "TT CASJET PER PIM?\n[[added]]Testo para takimet te henen[[/added]]\n[done]]E perfunduar[/done]]\n<script>alert('x')</script>"
  tree.props.value.open({ id: "comment", task_id: "task-to-edit", can_mark_read: false, title, symbol: "M2/3", comment: "Review\nwith KA", read_at: null })
  tree = render()
  const find = (node, match) => {
    if (!node || typeof node !== "object") return null
    if (Array.isArray(node)) return node.map((child) => find(child, match)).find(Boolean) || null
    return match(node) ? node : find(node.props?.children, match)
  }
  const button = find(tree, (node) => node.props?.children === "Hap detyrën")
  const dialogBefore = find(tree, (node) => typeof node.props?.open === "boolean" && typeof node.props?.onOpenChange === "function")
  assert.equal(dialogBefore.props.open, true)
  assert.ok(button)
  assert.equal(button.props.href, undefined)
  const taskSection = find(tree, (node) => node.props?.["aria-label"] === "Detyra")
  const html = renderToStaticMarkup(taskSection)
  assert.match(html, /TT CASJET PER PIM\?\n/)
  assert.match(html, /bg-blue-200/)
  assert.match(html, /line-through/)
  assert.match(html, /Testo para takimet te henen/)
  assert.match(html, /&lt;script&gt;/)
  assert.doesNotMatch(html, /\[\[?\/?(?:added|done)\]\]|<script>/)
  assert.match(html, /whitespace-pre-wrap/)
  const commentSection = find(tree, (node) => node.props?.["aria-label"] === "Komenti")
  assert.match(renderToStaticMarkup(commentSection), /Review\nwith KA/)
  button.props.onClick()
  tree = render()
  assert.ok(find(tree, (node) => node.props?.taskId === "task-to-edit" && typeof node.props.onSaved === "function"))
  assert.equal(find(tree, (node) => node.props?.children === "Hap detyrën"), null)
  const dialogAfter = find(tree, (node) => typeof node.props?.open === "boolean" && typeof node.props?.onOpenChange === "function")
  assert.equal(dialogAfter.type, dialogBefore.type)
  assert.equal(dialogAfter.props.open, true)
  dialogAfter.props.onOpenChange(false)
  tree = render()
  assert.equal(find(tree, (node) => typeof node.props?.open === "boolean").props.open, false)
  assert.equal(find(tree, (node) => node.props?.taskId === "task-to-edit"), null)
})
