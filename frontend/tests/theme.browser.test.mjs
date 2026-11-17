import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import path from "node:path"
import test from "node:test"
import vm from "node:vm"
import ts from "typescript"
import postcss from "postcss"
import tailwind from "@tailwindcss/postcss"
import { chromium } from "@playwright/test"

test("dark surfaces, live System changes, persistence and light printing", { timeout: 60000 }, async () => {
  const root = fileURLToPath(new URL("../", import.meta.url))
  const module = { exports: {} }
  vm.runInNewContext(ts.transpileModule(readFileSync(path.join(root, "src/lib/theme.ts"), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, { exports: module.exports })
  const css = await postcss([tailwind({ base: root })]).process(readFileSync(path.join(root, "src/app/globals.css"), "utf8"), { from: path.join(root, "src/app/globals.css") })
  const browser = await chromium.launch({ channel: "chrome", headless: true })
  try {
    const page = await browser.newPage({ colorScheme: "dark" })
    await page.route("http://theme.test/**", route => route.fulfill({ contentType: "text/html", body: `<html><head><style>${css.css}</style><script>${module.exports.THEME_SCRIPT}</script></head><body><main class="bg-background text-foreground"><div id="card" class="bg-white text-slate-800 border border-slate-200">Task card</div><span id="status" class="bg-red-100 text-red-800">Overdue</span><iframe srcdoc="<body style='background:white;color:black'>Report</body>"></iframe></main></body></html>` }))
    await page.goto("http://theme.test/")
    const colors = () => page.locator("#card").evaluate(node => ({ background: getComputedStyle(node).backgroundColor, text: getComputedStyle(node).color }))
    const dark = await colors()
    assert.equal(dark.background, "rgb(24, 34, 49)")
    assert.equal(dark.text, "rgb(241, 245, 249)")
    await page.emulateMedia({ colorScheme: "light" })
    await page.waitForFunction(() => !document.documentElement.classList.contains("dark"))
    const light = await colors()
    assert.equal(light.background, "rgb(255, 255, 255)")
    await page.evaluate(() => window.dispatchEvent(new CustomEvent("primex:set-theme", { detail: "dark" })))
    await page.reload()
    assert.deepEqual(await colors(), dark)
    assert.equal(await page.evaluate(() => localStorage.getItem("primex-theme")), "dark")
    assert.equal(await page.locator("iframe").contentFrame().locator("body").evaluate(node => getComputedStyle(node).backgroundColor), "rgb(255, 255, 255)")
    await page.emulateMedia({ media: "print" })
    assert.deepEqual(await colors(), light)
    await page.emulateMedia({ media: "screen" })
    assert.deepEqual(await colors(), dark)
  } finally {
    await browser.close()
  }
})
