const ts = require('../frontend/node_modules/typescript')
const path = require('node:path')
const root = path.resolve(__dirname, '../frontend')
const files = [
  'src/components/marker-comments-context.tsx', 'src/app/(app)/comments/page.tsx',
  'src/components/task-marker-comment.tsx', 'src/components/task-one-h-marker-editor.tsx',
  'src/components/sidebar.tsx', 'src/components/topbar.tsx', 'src/lib/auth.tsx',
  'src/app/(app)/layout.tsx', 'src/app/(app)/tomorrow-print-report/page.tsx',
  'src/components/comment-task-edit-dialog.tsx', 'src/components/px-notes-workspace.tsx',
  'src/components/task-edit-dialog.tsx',
  'src/app/(app)/ga-ka-notes/page.tsx',
].map(file => path.join(root, file))
const config = ts.readConfigFile(path.join(root, 'tsconfig.json'), ts.sys.readFile)
const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, root)
const program = ts.createProgram(files, { ...parsed.options, incremental: false, noEmit: true })
const diagnostics = ts.getPreEmitDiagnostics(program)
const own = diagnostics.filter(item => !item.file || files.includes(path.normalize(item.file.fileName)))
console.log(ts.formatDiagnosticsWithColorAndContext(own, { getCurrentDirectory: () => root, getCanonicalFileName: file => file, getNewLine: () => '\n' }))
console.log(`${own.length} TypeScript diagnostics in changed comment files; ${diagnostics.length - own.length} elsewhere in imported dependencies.`)
if (own.length) process.exitCode = 1
