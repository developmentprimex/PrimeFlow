import { readFileSync } from "node:fs"
import vm from "node:vm"
import ts from "typescript"

const source = readFileSync(new URL("../../src/lib/task-markers.ts", import.meta.url), "utf8")
const module = { exports: {} }
export const taskMarkersCode = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
} }).outputText
vm.runInNewContext(taskMarkersCode, { module, exports: module.exports })
export const taskMarkers = module.exports
