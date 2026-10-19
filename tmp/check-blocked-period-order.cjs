const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { execFileSync } = require('node:child_process')
const ts = require('../frontend/node_modules/typescript')
const { ESLint } = require('../frontend/node_modules/eslint')

const root = path.resolve(__dirname, '..')
const file = 'frontend/src/app/(app)/common/page.tsx'
const source = fs.readFileSync(path.join(root, file), 'utf8')
const ast = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
assert.equal(ast.parseDiagnostics.length, 0)
const names = new Set(['getFinishPeriodIndicatorLabel', 'getCommonTaskPeriodLabel', 'getCommonTaskPeriodSortRank', 'sortTasksByOrder', 'sortTasksForReportPrint'])
const declarations = []
function visit(node) {
  if (ts.isVariableDeclaration(node) && names.has(node.name.getText(ast))) declarations.push('const ' + node.getText(ast) + ';')
  ts.forEachChild(node, visit)
}
visit(ast)
assert.equal(declarations.length, names.size)
const compiled = ts.transpileModule(declarations.join('\n') + '\n({sortTasksByOrder,sortTasksForReportPrint})', { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText
const byPerson = (a, b) => a.person.localeCompare(b.person)
const sorts = vm.runInNewContext(compiled, { React: { useCallback: fn => fn }, compareTaskOrder: byPerson, compareReportPrintOrder: byPerson })
const items = [
  { id: 'pm-a', person: 'A', finishPeriod: 'PM', date: '2026-10-19' },
  { id: 'am-b', person: 'B', finishPeriod: 'AM', date: '2026-10-19' },
  { id: 'all-a', person: 'A', finishPeriod: null, date: '2026-10-19' },
  { id: 'am-a', person: 'A', finishPeriod: ' am ', date: '2026-10-19' },
  { id: 'pm-b', person: 'B', finishPeriod: 'PM', date: '2026-10-19' },
  { id: 'all-b', person: 'B', finishPeriod: 'AM/PM', date: '2026-10-19' },
]
const ids = values => Array.from(values, item => item.id)
const expected = ['all-a', 'am-a', 'am-b', 'all-b', 'pm-a', 'pm-b']
assert.deepEqual(ids(sorts.sortTasksByOrder(items, false, true)), expected)
assert.deepEqual(ids(sorts.sortTasksForReportPrint(items, true)), expected)
assert.deepEqual(ids(sorts.sortTasksByOrder(items, false)), ids([...items].sort(byPerson)))
assert.deepEqual(ids(sorts.sortTasksForReportPrint(items)), ids([...items].sort(byPerson)))
assert.equal(items[0].id, 'pm-a')
const previousDay = { id: 'previous-pm', person: 'Z', finishPeriod: 'PM', date: '2026-10-18' }
assert.deepEqual(ids(sorts.sortTasksByOrder([...items, previousDay], true, true)), ['previous-pm', ...expected])
console.log('Common View sorting passed: period, person, date, print, unchanged other rows, no mutation.')

async function lint() {
  const eslint = new ESLint({ cwd: path.join(root, 'frontend') })
  const staged = execFileSync('git', ['show', ':' + file], { cwd: root, encoding: 'utf8' })
  const current = await eslint.lintText(source, { filePath: path.join(root, file) })
  const baseline = await eslint.lintText(staged, { filePath: path.join(root, file) })
  const signatures = results => results.flatMap(result => result.messages.map(message => `${message.severity}:${message.ruleId}:${message.message.replace(/at line \d+/g, 'at line N')}`)).sort()
  assert.deepEqual(signatures(current), signatures(baseline))
  console.log('ESLint: no new errors or warnings compared with the existing file.')
}
lint().catch(error => { console.error(error); process.exitCode = 1 })
