const { execFileSync } = require('child_process');
const { ESLint } = require('../frontend/node_modules/eslint');
(async () => {
  const path = 'src/app/(app)/tomorrow-print-report/page.tsx';
  const eslint = new ESLint();
  const before = execFileSync('git', ['show', 'HEAD:frontend/' + path], { encoding: 'utf8' });
  for (const [label, results] of [['before', await eslint.lintText(before, { filePath: path })], ['after', await eslint.lintFiles([path])]]) {
    console.log(label, results[0].messages.map(message => ({ rule: message.ruleId, line: message.line })));
  }
})();
