import assert from "node:assert/strict"
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from "node:fs"
import { createRequire } from "node:module"
import path from "node:path"
import { tmpdir } from "node:os"
import { fileURLToPath } from "node:url"
import { test } from "node:test"
import { chromium } from "@playwright/test"
import ts from "typescript"

const require = createRequire(import.meta.url)
const root = fileURLToPath(new URL("../", import.meta.url))

test("expanding and collapsing long My View titles keeps column and toggle positions", { timeout: 60000 }, async () => {
  const directory = mkdtempSync(path.join(tmpdir(), "my-view-layout-"))
  let browser
  try {
    writeFileSync(path.join(directory, "loader.cjs"), `module.exports = source => require(${JSON.stringify(require.resolve("typescript"))}).transpileModule(source, {compilerOptions:{module:99,jsx:4,target:7}}).outputText;`)
    writeFileSync(path.join(directory, "fixture.tsx"), `
      import * as React from 'react';
      import {createRoot} from 'react-dom/client';
      import {CollapsibleTaskTitle} from '${path.join(root, "src/components/collapsible-task-title").replaceAll("\\", "/")}';
      import {MyViewTaskColumns} from '${path.join(root, "src/components/my-view-task-columns").replaceAll("\\", "/")}';
      createRoot(document.getElementById('root')).render(<>
        <div style={{height:500}} />
        <table style={{tableLayout:'fixed',width:'100%'}}><MyViewTaskColumns kind="project" />
          <thead><tr>{Array.from({length:11},(_,i)=><th key={i}>Col {i}</th>)}</tr></thead>
          <tbody>{[0,1].map(n=><tr key={n}>{Array.from({length:11},(_,i)=><td key={i}>
            {i===4 ? <div style={{position:'relative',paddingRight:32}}><CollapsibleTaskTitle alignToggle title={'Short preview '+n+'\\n'+('Long detailed title with multiple words and important notes '.repeat(15))} /><span> GA · 1H</span></div> : 'Value'}
          </td>)}</tr>)}</tbody>
        </table><div style={{height:1500}} />
      </>);
    `)
    const compiler = require("next/dist/compiled/webpack/webpack").webpack({
      mode: "development", devtool: false, entry: path.join(directory, "fixture.tsx"),
      output: { path: directory, filename: "bundle.js" },
      resolve: { extensions: [".tsx", ".ts", ".js"], modules: [path.join(root, "node_modules"), "node_modules"] },
      module: { rules: [{ test: /\.tsx?$/, use: path.join(directory, "loader.cjs") }] },
    })
    await new Promise((resolve, reject) => compiler.run((error, stats) => compiler.close(() => error ? reject(error) : stats.hasErrors() ? reject(new Error(stats.toString({all:false,errors:true}))) : resolve())))
    const bundle = readFileSync(path.join(directory, "bundle.js"), "utf8")
    browser = await chromium.launch({ headless: true, channel: "chrome" })
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
    await page.route("http://my-view.test/**", route => route.fulfill(route.request().url().endsWith("bundle.js")
      ? {contentType:"text/javascript",body:bundle}
      : {contentType:"text/html",body:`<style>td{vertical-align:top;padding:8px;overflow-wrap:anywhere} .inline-flex{display:inline-flex}.max-w-full{max-width:100%}.min-w-0{min-width:0}.whitespace-pre-wrap{white-space:pre-wrap}.absolute{position:absolute}.right-0{right:0}.top-0{top:0} button{width:26px}</style><div id="root"></div><script src="/bundle.js"></script>`}))
    await page.goto("http://my-view.test/")
    const button = page.getByRole("button", { name: "Expand task title" }).first()
    await button.waitFor()
    const widths = () => page.locator("th").evaluateAll(nodes => nodes.map(n => ({ x:n.getBoundingClientRect().x,width:n.getBoundingClientRect().width })))
    const before = await widths()
    const buttonX = (await button.boundingBox()).x
    await button.click()
    assert.deepEqual(await widths(), before)
    const collapse = page.getByRole("button", { name: "Collapse task title" })
    assert.equal((await collapse.boundingBox()).x, buttonX)
    await collapse.click()
    assert.deepEqual(await widths(), before)
    assert.equal((await button.boundingBox()).x, buttonX)
  } finally {
    if (browser) await browser.close()
    const resolved = path.resolve(directory)
    assert.ok(resolved.startsWith(path.resolve(tmpdir()) + path.sep) && path.basename(resolved).startsWith("my-view-layout-"))
    rmSync(resolved, { recursive:true, force:true })
  }
})

test("department files remain syntactically valid after fixing the My View table widths", () => {
  for (const department of ['development','graphic-design','project-content-manager','finance']) {
    const filename = path.join(root, `src/app/(app)/departments/${department}/department-kanban.tsx`)
    const ast = ts.createSourceFile(filename, readFileSync(filename, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
    assert.equal(ast.parseDiagnostics.length, 0, department)
  }
})
