import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import { test } from "node:test"
import vm from "node:vm"
import React from "react"
import ts from "typescript"

const require = createRequire(import.meta.url)
function load(path, overrides = {}) {
  const result = { exports: {} }
  const source = readFileSync(new URL(path, import.meta.url), "utf8")
  const { outputText } = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } })
  vm.runInNewContext(outputText, { module: result, exports: result.exports, document: overrides.document,
    require: name => overrides[name] || require(name) })
  return result.exports
}
const titleModule = load("../src/lib/browser-tab-title.ts")
const { browserTabTitle } = titleModule

test("tabs identify the current page, department, and comments scope", () => {
  for (const [url, title] of [
    ["/ga-ka-notes", "PX Notes"], ["/common", "Common View"], ["/dashboard", "Dashboard"],
    ["/departments/development?view=mine&daily=full", "My View · Development"],
    ["/departments/graphic-design?view=mine", "My View · Graphic Design"],
    ["/departments/project-content-manager", "Product Content"],
    ["/departments/finance", "Finance"], ["/departments/human-resource", "Human Resources"],
    ["/comments?scope=all&read=all", "Simbolet dhe komentet · Të gjitha"],
    ["/comments?scope=mine&read=unread", "Simbolet dhe komentet · Të miat"],
    ["/today-print-report", "1H SHTYPI Today"], ["/tomorrow-print-report", "1H SHTYPI Tomorrow"],
    ["/knowledge/prompts", "Prompts · Knowledge PX"], ["/weekly-planner", "Weekly Planner"],
    ["/reports/weekly-planning-audit", "Weekly Planning Check"],
    ["/projects/dev/123", "Project · Development"], ["/tasks/123", "Task Details"],
    ["/unknown", "PrimeFlow"],
  ]) {
    const parsed = new URL(url, "https://example.test")
    assert.equal(browserTabTitle(parsed.pathname, parsed.searchParams), title, url)
  }
})

test("navigation and local My View changes update the browser tab without leaking the old title", () => {
  let pathname = "/ga-ka-notes"
  let params = new URLSearchParams()
  let override = null
  const document = { title: "PrimeFlow" }
  const cleanup = []
  const setPageTitle = value => { override = typeof value === "function" ? value(override) : value }
  const hooks = { ...React, useState: () => [override, setPageTitle], useContext: () => setPageTitle,
    useEffect: effect => { const dispose = effect(); if (dispose) cleanup.push(dispose) } }
  const { BrowserTabTitleProvider, useBrowserTabTitle } = load("../src/components/browser-tab-title.tsx", {
    react: hooks, "next/navigation": { usePathname: () => pathname, useSearchParams: () => params },
    "@/lib/browser-tab-title": titleModule, document,
  })
  const update = () => {
    const tree = BrowserTabTitleProvider({ children: null })
    const watcher = tree.props.children[0].props.children
    watcher.type(watcher.props)
  }
  update()
  assert.equal(document.title, "PX Notes")
  pathname = "/common"
  update()
  assert.equal(document.title, "Common View")
  pathname = "/departments/development"
  useBrowserTabTitle("My View · Development")
  update()
  assert.equal(document.title, "My View · Development")
  while (cleanup.length) cleanup.pop()()
  useBrowserTabTitle("Development")
  update()
  assert.equal(document.title, "Development")
  pathname = "/comments"
  params = new URLSearchParams("scope=all")
  update()
  assert.equal(document.title, "Simbolet dhe komentet · Të gjitha")
  while (cleanup.length) cleanup.pop()()
  pathname = "/ga-ka-notes"
  update()
  assert.equal(document.title, "PX Notes")
})
