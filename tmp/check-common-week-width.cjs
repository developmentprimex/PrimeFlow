const fs = require('fs');
const ts = require('../frontend/node_modules/typescript');
const { chromium } = require('../frontend/node_modules/@playwright/test');
const source = fs.readFileSync('frontend/src/app/(app)/common/page.tsx', 'utf8');
const result = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.Preserve, target: ts.ScriptTarget.ES2020 }, reportDiagnostics: true });
if (result.diagnostics.some(d => d.category === ts.DiagnosticCategory.Error)) throw new Error('TSX syntax error');
(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'msedge' });
  try {
    const page = await browser.newPage();
    const css = source.match(/        \.week-table \{\s+width: 100%;\s+table-layout: fixed;[\s\S]*?\n        \}/)[0];
    for (const width of [1000, 1580]) {
      await page.setViewportSize({ width, height: 800 });
      await page.setContent(`<style>${css}</style><table class="week-table"><thead><tr><th style="width:40px">NR</th><th style="width:86px">LLOJI</th>${Array(5).fill('<th>Day</th>').join('')}</tr></thead><tbody><tr><td>5</td><td>TAK EXT</td><td>${'LongMeetingTitle'.repeat(40)}</td>${Array(4).fill('<td>09:00 CAL</td>').join('')}</tr></tbody></table>`);
      const sizes = await page.locator('thead th').evaluateAll(els => els.slice(2).map(e => e.getBoundingClientRect().width));
      if (Math.max(...sizes) - Math.min(...sizes) > 1) throw new Error(`Unequal widths: ${sizes}`);
      if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error('Horizontal overflow');
      console.log(`Viewport ${width}: equal day columns, no horizontal overflow`);
    }
    console.log('TSX syntax OK');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
