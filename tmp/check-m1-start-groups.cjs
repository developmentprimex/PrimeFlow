const path = require('node:path')
const fs = require('node:fs')
const vm = require('node:vm')
const assert = require('node:assert/strict')
const { createRequire } = require('node:module')
const frontend = path.resolve(__dirname, '../frontend')
const requireFrontend = createRequire(path.join(frontend, 'package.json'))
const ts = requireFrontend('typescript')
const config = ts.readConfigFile(path.join(frontend, 'tsconfig.json'), ts.sys.readFile)
config.config.include = ['src/components/m1-reporting-points-view.tsx', 'src/app/(app)/m1-reporting-points/page.tsx']
config.config.compilerOptions.incremental = false
config.config.compilerOptions.typeRoots = [path.join(frontend, 'node_modules/@types')]
const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, frontend)
const program = ts.createProgram(parsed.fileNames, parsed.options)
const diagnostics = ts.getPreEmitDiagnostics(program)
if (diagnostics.length) {
  console.error(ts.formatDiagnosticsWithColorAndContext(diagnostics, {
    getCurrentDirectory: () => frontend, getCanonicalFileName: (name) => name, getNewLine: () => '\n',
  }))
  process.exit(1)
}
const cache = new Map()
function load(name) {
  if (!name.startsWith('@/')) return requireFrontend(name)
  if (cache.has(name)) return cache.get(name)
  const base = path.join(frontend, 'src', name.slice(2))
  const file = ['.tsx', '.ts'].map((suffix) => base + suffix).find(fs.existsSync)
  const module = { exports: {} }
  const result = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } })
  vm.runInNewContext(result.outputText, { module, exports: module.exports, require: load })
  cache.set(name, module.exports)
  return module.exports
}
const React = requireFrontend('react')
const { renderToStaticMarkup } = requireFrontend('react-dom/server')
const { M1ReportingPointsView } = load('@/components/m1-reporting-points-view')
const tasks = [
  { id: 'today', title: 'Starts today', start_date: '2026-10-16', planned_for: '23.10.2026' },
  { id: 'other', title: 'Starts another day', start_date: '2026-10-23', planned_for: 'Sot' },
  { id: 'none', title: 'Missing start', start_date: null },
].map((task) => ({ status: 'TODO', created_at: '2026-10-16T08:00:00+02:00', ...task }))
const html = renderToStaticMarkup(React.createElement(M1ReportingPointsView, {
  report: { report_date: '2026-10-16', data: { tasks } }, answers: {}, disabled: false, onAnswerChange() {},
}))
const start = html.indexOf('1. TË KRIJUARA SOT ME START DATE SOT')
const split = html.indexOf('2. TË KRIJUARA SOT ME START DATE NË DITË TJETËR')
const first = html.slice(start, split)
const second = html.slice(split, html.indexOf('6. A DUHET RIORGANIZIM?'))
assert.match(first, /Starts today/)
assert.doesNotMatch(first, /Starts another day|Missing start/)
assert.match(second, /Starts another day/)
assert.match(second, /Missing start/)
assert.doesNotMatch(second, /Starts today/)
console.log('M1 TypeScript and rendered Start Date groups passed.')
