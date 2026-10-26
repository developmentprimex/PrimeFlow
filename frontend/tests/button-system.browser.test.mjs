import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { test } from "node:test"
import vm from "node:vm"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { chromium } from "@playwright/test"
import { compile } from "@tailwindcss/node"
import ts from "typescript"

const require = createRequire(import.meta.url)
const root = fileURLToPath(new URL("../", import.meta.url))

function loadButton() {
  const loaded = { exports: {} }
  const source = readFileSync(new URL("../src/components/ui/button.tsx", import.meta.url), "utf8")
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText, { module: loaded, exports: loaded.exports, require(name) {
    if (name === "@/lib/utils") return { cn: (...classes) => require("tailwind-merge").twMerge(require("clsx").clsx(classes)) }
    return require(name)
  } })
  return loaded.exports.Button
}

test("shared buttons, legacy controls, tabs and button links use one shape across pages and portals", async () => {
  const Button = loadButton()
  const fixture = React.createElement("main", null,
    React.createElement(Button, { id: "primary", className: "rounded-full" }, "New Project"),
    React.createElement(Button, { id: "secondary", variant: "outline", size: "sm", className: "rounded-none" }, "Print"),
    React.createElement(Button, { id: "large", size: "lg", variant: "destructive" }, "Delete"),
    React.createElement(Button, { id: "compact", className: "h-5 w-5 rounded-full p-0" }, "×"),
    React.createElement(Button, { asChild: true }, React.createElement("a", { id: "button-link", href: "#projects" }, "Projects")),
    React.createElement(Button, { id: "avatar", "data-button-shape": "circle", className: "size-10 p-0" }, "RA"),
    React.createElement(Button, { id: "disabled", disabled: true }, "Saving"))
  const html = renderToStaticMarkup(fixture) + `
    <button id="native-tab" class="rounded-none px-3 py-1">Projects</button>
    <button id="native-filter" class="rounded-full px-3 py-1">Active (15)</button>
    <button id="legacy" class="btn-outline">Department</button>
    <a id="legacy-link" class="btn-primary" href="#projects">Open</a>
    <a id="custom-link" class="inline-flex border rounded-full" href="#projects">Export</a>
    <a id="text-link" href="#projects">View details</a>
    <span id="badge" class="rounded-full">Active</span>
    <button id="checkbox" role="checkbox" aria-checked="false" class="rounded-[5px]">✓</button>
    <div id="date-group" data-slot="button-group" class="inline-flex rounded-full border p-1"><button>Today</button><button>Yesterday</button></div>
    <div id="view-group" data-slot="button-group" class="inline-flex rounded-full border p-1"><button>Department</button><button>My View</button></div>
    <div id="tabs-group" data-slot="tabs-list" class="rounded-2xl p-1"><button role="tab">All</button><button role="tab">Projects</button></div>
    <div role="dialog"><button id="dialog-action" class="rounded-2xl">Save</button></div>`
  const candidates = [...html.matchAll(/class="([^"]*)"/g)].flatMap(match => match[1].split(/\s+/))
  const compiled = await compile(readFileSync(path.join(root, "src/app/globals.css"), "utf8"), {
    base: path.join(root, "src/app"), onDependency() {},
  })
  const css = compiled.build(candidates)
  const browser = await chromium.launch({ headless: true, channel: "chrome" })
  try {
    const page = await browser.newPage()
    await page.setContent(`<style>${css}</style><style>.btn-outline,.btn-primary{border-radius:999px!important}</style>${html}`)
    const values = await page.evaluate(() => Object.fromEntries([...document.querySelectorAll("[id]")].map(element => {
      const style = getComputedStyle(element)
      return [element.id, { radius: style.borderRadius, height: style.height, opacity: style.opacity }]
    })))
    for (const id of ["primary", "secondary", "large", "compact", "button-link", "native-tab", "native-filter", "legacy", "legacy-link", "custom-link", "dialog-action"])
      assert.equal(values[id].radius, "8px", id)
    assert.equal(values.primary.height, "36px")
    assert.equal(values.secondary.height, "32px")
    assert.equal(values.large.height, "40px")
    assert.equal(values.compact.height, "20px", "Dense project cards keep their existing dimensions")
    assert.equal(values.avatar.radius, "50%")
    assert.equal(values.checkbox.radius, "5px")
    for (const id of ["date-group", "view-group", "tabs-group"]) assert.equal(values[id].radius, "12px", id)
    assert.notEqual(values.badge.radius, "8px")
    assert.equal(values["text-link"].radius, "0px")
    assert.equal(values.disabled.opacity, "0.5")
    await page.keyboard.press("Tab")
    const focus = await page.locator("#primary").evaluate(element => {
      const style = getComputedStyle(element)
      return { focused: document.activeElement === element, style: style.outlineStyle, width: style.outlineWidth }
    })
    assert.deepEqual(focus, { focused: true, style: "solid", width: "2px" })
    await page.emulateMedia({ reducedMotion: "reduce" })
    assert.equal(await page.locator("#primary").evaluate(element => getComputedStyle(element).transitionDuration), "0s")
  } finally {
    await browser.close()
  }
})
