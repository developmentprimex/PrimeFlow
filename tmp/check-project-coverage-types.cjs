const ts = require('../frontend/node_modules/typescript');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const configFile = ts.readConfigFile('frontend/tsconfig.json', ts.sys.readFile);
const config = ts.parseJsonConfigFileContent(configFile.config, ts.sys, path.resolve('frontend'));
config.options.incremental = false;
const changed = ['frontend/src/app/(app)/common/page.tsx', ...['development', 'graphic-design', 'project-content-manager'].map(name => `frontend/src/app/(app)/departments/${name}/department-kanban.tsx`)];
const originals = new Map(changed.map(file => [path.resolve(file).toLowerCase(), execFileSync('git', ['show', `HEAD:${file}`], {encoding:'utf8', maxBuffer: 8e6})]));
function diagnostics(baseline) {
  const host = ts.createCompilerHost(config.options);
  const read = host.readFile;
  host.readFile = file => baseline && originals.has(path.resolve(file).toLowerCase()) ? originals.get(path.resolve(file).toLowerCase()) : read(file);
  const program = ts.createProgram(config.fileNames, config.options, host);
  return ts.getPreEmitDiagnostics(program).map(d => ({file:d.file?.fileName || '', code:d.code, message:ts.flattenDiagnosticMessageText(d.messageText, '\n')}));
}
const before = diagnostics(true);
const counts = new Map();
for (const d of before) { const key=JSON.stringify(d); counts.set(key,(counts.get(key)||0)+1); }
const after = diagnostics(false);
const added = after.filter(d => { const key=JSON.stringify(d), n=counts.get(key)||0; if(n){counts.set(key,n-1);return false;} return true; });
console.log(JSON.stringify({baselineErrors:before.length,currentErrors:after.length,newErrors:added},null,2));
process.exitCode = added.length ? 1 : 0;
