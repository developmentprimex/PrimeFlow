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

async function buildProjectCard(directory) {
  const source = readFileSync(new URL("../src/app/(app)/departments/development/department-kanban.tsx", import.meta.url), "utf8")
  const ast = ts.createSourceFile("department.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  let card
  function visit(node) {
    if (ts.isJsxElement(node) && node.openingElement.attributes.properties.some(attribute =>
      ts.isJsxAttribute(attribute) && attribute.name.text === "className" && attribute.initializer?.text === "group block")) card = node
    ts.forEachChild(node, visit)
  }
  visit(ast)
  assert.ok(card, "Render the real Development project card")
  writeFileSync(path.join(directory, "auth.js"), `export function useAuth() { return { user: {role: 'ADMIN'}, apiFetch: async (url, options) => {
    window.activityRequests.push({url, body: JSON.parse(options.body)});
    return { ok: true, json: async () => ({id: 'test-project', title: 'Test project', ...JSON.parse(options.body)}) };
  } } }`)
  writeFileSync(path.join(directory, "cache.js"), "export function clearDepartmentBootstrapCache() {}")
  writeFileSync(path.join(directory, "toast.js"), "export const toast = {success() {}, error() {}}")
  writeFileSync(path.join(directory, "loader.cjs"), `module.exports = source => require(${JSON.stringify(require.resolve("typescript"))}).transpileModule(source, {
    compilerOptions: {module: 99, jsx: 4, target: 7}
  }).outputText;`)
  writeFileSync(path.join(directory, "fixture.tsx"), `
    import * as React from 'react';
    import {createRoot} from 'react-dom/client';
    import {Trash2} from 'lucide-react';
    import {ProjectActivityControl} from '@/components/project-activity';
    import {Card} from '@/components/ui/card';
    const Link = ({children, ...props}) => <a {...props}>{children}</a>;
    const Badge = ({children, ...props}) => <span {...props}>{children}</span>;
    const Button = ({children, variant, size, ...props}) => <button {...props}>{children}</button>;
    window.activityRequests = [];
    function Fixture() {
      const [projects, setProjects] = React.useState([{id: 'test-project', title: 'Test project', is_active: true}]);
      const project = projects[0];
      const isClosed = false, badgeUser = null, badgeTitle = '', canDeleteProjects = true;
      const deletingProjectId = null, deleteProject = () => {}, resolveProjectTitle = p => p.title;
      const initials = () => 'T', phase = 'DEVELOPMENT', PHASE_LABELS = {DEVELOPMENT: 'Development'};
      const taskCount = 7, formatDeadline = () => '-', visibleMembers = [], remainingMembers = 0;
      return (${card.getText(ast)});
    }
    createRoot(document.getElementById('root')).render(<Fixture/>);
  `)
  const { webpack } = require("next/dist/compiled/webpack/webpack")
  const compiler = webpack({
    mode: "development", devtool: false, context: root,
    entry: path.join(directory, "fixture.tsx"), output: { path: directory, filename: "bundle.js" },
    resolve: { extensions: [".tsx", ".ts", ".js"], modules: [path.join(root, "node_modules")], alias: {
      "@/lib/auth$": path.join(directory, "auth.js"),
      "@/lib/department-bootstrap-cache$": path.join(directory, "cache.js"),
      "sonner$": path.join(directory, "toast.js"), "@": path.join(root, "src"),
    } },
    module: { rules: [{ test: /\.tsx?$/, use: path.join(directory, "loader.cjs") }] },
  })
  await new Promise((resolve, reject) => compiler.run((error, stats) => {
    compiler.close(() => {
      if (error) reject(error)
      else if (stats.hasErrors()) reject(new Error(stats.toString({ all: false, errors: true })))
      else resolve()
    })
  }))
  return readFileSync(path.join(directory, "bundle.js"), "utf8")
}

test("styled activity menu saves both choices without navigation or changing card height", { timeout: 60_000 }, async () => {
  const directory = mkdtempSync(path.join(tmpdir(), "project-activity-browser-"))
  let browser
  try {
    const bundle = await buildProjectCard(directory)
    browser = await chromium.launch({ headless: true, channel: "chrome" })
    const page = await browser.newPage()
    await page.route("http://project-card.test/**", route => {
      if (route.request().url().endsWith("bundle.js")) return route.fulfill({contentType: "text/javascript", body: bundle})
      return route.fulfill({ contentType: "text/html", body: `
        <style>
          .relative { position: relative; } .z-10 { z-index: 10; }
          [class~="after:absolute"]::after { content: ''; position: absolute; inset: 0; }
          [class~="group"] { width: 380px; } [class~="relative"][class~="bg-white"] { padding: 12px; }
        </style><div id="root"></div><script src="/bundle.js"></script>` })
    })
    await page.goto("http://project-card.test/")
    const dropdown = page.getByRole("combobox", { name: "Activity for project Test project" })
    await dropdown.waitFor()
    assert.equal(await dropdown.evaluate(element => element.closest("a") === null), true)
    const cardHeight = await page.locator('[data-slot="card"]').evaluate(element => element.getBoundingClientRect().height)
    await dropdown.click()
    await page.getByRole("option", { name: "Inactive", exact: true }).click()
    await page.waitForFunction(() => window.activityRequests.length === 1)
    assert.equal(await dropdown.innerText(), "Inactive")
    assert.equal(page.url(), "http://project-card.test/")
    await dropdown.click()
    await page.getByRole("option", { name: "Active", exact: true }).click()
    await page.waitForFunction(() => window.activityRequests.length === 2)
    assert.equal(await dropdown.innerText(), "Active")
    assert.deepEqual(await page.evaluate(() => window.activityRequests.map(request => request.body)), [{is_active: false}, {is_active: true}])
    assert.equal(await page.locator('[data-slot="card"]').evaluate(element => element.getBoundingClientRect().height), cardHeight)
    await Promise.all([
      page.waitForURL("http://project-card.test/projects/test-project"),
      page.getByRole("link", { name: /View details/ }).click(),
    ])
  } finally {
    if (browser) await browser.close()
    const resolvedDirectory = path.resolve(directory)
    assert.ok(resolvedDirectory.startsWith(path.resolve(tmpdir()) + path.sep) && path.basename(resolvedDirectory).startsWith('project-activity-browser-'))
    rmSync(resolvedDirectory, { recursive: true, force: true })
  }
})
