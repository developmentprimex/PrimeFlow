const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const path = require('node:path');
const { spawn } = require('node:child_process');

const helper = path.resolve(__dirname, '../../frontend/scripts/wait-for-readiness.ps1');
const quote = value => "'" + value.replaceAll("'", "''") + "'";

async function probe(handler, { expected = 'candidate', timeout = 6, requestTimeout = 5 } = {}) {
  const server = http.createServer((req, res) => {
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    handler(req, res);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const script = `$ErrorActionPreference = 'Stop'; . ${quote(helper)}; ` +
    `$ready = Wait-PrimeFlowFrontend -BaseUri 'http://127.0.0.1:${server.address().port}' ` +
    `-ExpectedDeploymentId ${quote(expected)} -TimeoutSeconds ${timeout} ` +
    `-RequestTimeoutSeconds ${requestTimeout} -RetrySeconds 1; if ($ready) { exit 0 } else { exit 1 }`;
  const started = Date.now();
  try {
    return await new Promise((resolve, reject) => {
      const child = spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], {
        windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
      });
      let output = '';
      const watchdog = setTimeout(() => { child.kill(); reject(new Error('Readiness probe exceeded test deadline')); }, 20000);
      child.stdout.on('data', data => { output += data; });
      child.stderr.on('data', data => { output += data; });
      child.once('error', error => { clearTimeout(watchdog); reject(error); });
      child.once('exit', code => {
        clearTimeout(watchdog);
        resolve({ code, output, elapsed: Date.now() - started });
      });
    });
  } finally {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
}

test('accepts a first page response that takes longer than the old three-second limit', async () => {
  const result = await probe((req, res) => {
    assert.equal(req.headers['cache-control'], 'no-cache');
    assert.equal(req.url, '/admin-tasks?deploy-check=candidate');
    setTimeout(() => res.end('<script src="/chunk.js?dpl=candidate"></script>'), 4000);
  });
  assert.equal(result.code, 0, result.output);
});

test('retries during warmup and reports the HTTP failure', async () => {
  let requests = 0;
  const result = await probe((req, res) => {
    if (++requests === 1) { res.writeHead(503); res.end('warming up'); }
    else res.end('<script src="/chunk.js?dpl=candidate"></script>');
  });
  assert.equal(result.code, 0, result.output);
  assert.match(result.output, /503/);
  assert.equal(requests, 2);
});

test('rejects a healthy stale deployment until the deadline', async () => {
  const result = await probe((req, res) => res.end('<script src="/chunk.js?dpl=previous"></script>'), { timeout: 3 });
  assert.equal(result.code, 1, result.output);
  assert.match(result.output, /HTTP 200, but the page does not contain deployment candidate/);
  assert.match(result.output, /timed out after 3 s/);
  assert.ok(result.elapsed < 8000, result.output);
});

test('bounds an unresponsive page and exposes the request error', async () => {
  const result = await probe(() => {}, { timeout: 3, requestTimeout: 2 });
  assert.equal(result.code, 1, result.output);
  assert.match(result.output, /Last failure: .+/);
  assert.doesNotMatch(result.output, /no response yet/);
  assert.ok(result.elapsed < 8000, result.output);
});

test('allows a restored build when no deployment ID is required', async () => {
  const result = await probe((req, res) => res.end('previous frontend'), { expected: '' });
  assert.equal(result.code, 0, result.output);
});
