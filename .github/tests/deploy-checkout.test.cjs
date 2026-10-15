const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');

const workflow = fs.readFileSync(path.join(__dirname, '../workflows/deploy.yml'), 'utf8');
const checkout = workflow.split('      - name: Checkout Code')[1].split('      - name: Configure Server Tooling')[0];
const run = checkout.match(/        run: \|\r?\n([\s\S]*)/);
const script = run && run[1].split(/\r?\n/).map(line => line.replace(/^          /, '')).join('\n');

function git(cwd, ...args) {
  const result = spawnSync('git', args, { cwd, encoding: 'utf8', windowsHide: true });
  assert.equal(result.status, 0, result.stderr || result.error?.message);
  return result.stdout.trim();
}

for (const mode of ['missing metadata', 'wrong origin', 'failed fetch']) {
  test('checkout preserves locked runtime directories with ' + mode, async () => {
    assert.ok(script, 'Checkout must synchronize in place instead of recreating the live workspace');
    const base = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'primeflow-checkout-'));
    const source = path.join(base, 'source');
    const workspace = path.join(base, 'workspace');
    const remote = path.join(base, 'origin.git');
    fs.mkdirSync(source);
    git(source, 'init', '-b', 'main');
    git(source, 'config', 'user.email', 'test@example.com');
    git(source, 'config', 'user.name', 'Deploy Test');
    fs.mkdirSync(path.join(source, 'backend'));
    fs.mkdirSync(path.join(source, 'frontend'));
    fs.writeFileSync(path.join(source, '.gitignore'), 'backend/.env\nfrontend/.next/\n');
    fs.writeFileSync(path.join(source, 'backend/app.txt'), 'requested build');
    fs.writeFileSync(path.join(source, 'frontend/app.txt'), 'requested frontend');
    git(source, 'add', '.');
    git(source, 'commit', '-m', 'requested build');
    const expected = git(source, 'rev-parse', 'HEAD');
    fs.writeFileSync(path.join(source, 'backend/app.txt'), 'newer build');
    git(source, 'commit', '-am', 'newer build');
    git(base, 'clone', '--bare', source, remote);
    git(base, 'clone', remote, workspace);
    if (mode === 'missing metadata') fs.rmSync(path.join(workspace, '.git'), { recursive: true });
    else git(workspace, 'remote', 'set-url', 'origin', path.join(base, 'wrong.git'));
    fs.writeFileSync(path.join(workspace, 'backend/.env'), 'preserved runtime settings');
    fs.mkdirSync(path.join(workspace, 'frontend/.next'));
    fs.writeFileSync(path.join(workspace, 'frontend/.next/BUILD_ID'), 'live build');
    const scriptPath = path.join(base, 'checkout.ps1');
    fs.writeFileSync(scriptPath, script);
    const holder = spawn('powershell.exe', ['-NoProfile', '-Command', 'Write-Output ready; [Console]::ReadLine() | Out-Null'], {
      cwd: path.join(workspace, 'backend'), stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true,
    });
    try {
      await new Promise((resolve, reject) => { holder.stdout.once('data', resolve); holder.once('error', reject); holder.once('exit', code => reject(new Error('Lock holder exited: ' + code))); });
      // Confirm that this fixture actually reproduces the Windows directory lock.
      assert.throws(() => fs.renameSync(path.join(workspace, 'backend'), path.join(workspace, 'backend-moved')));
      const result = spawnSync('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', scriptPath], {
        cwd: workspace, encoding: 'utf8', windowsHide: true,
        env: { ...process.env, GITHUB_WORKSPACE: workspace, GITHUB_SERVER_URL: base.replace(/\\/g, '/'),
          GITHUB_REPOSITORY: mode === 'failed fetch' ? 'absent.git' : 'origin.git', GITHUB_SHA: expected, GH_TOKEN: 'test-token' },
      });
      assert.equal(result.status, mode === 'failed fetch' ? 1 : 0, result.stdout + result.stderr);
      if (mode === 'failed fetch') assert.match(result.stderr, /Deployment git command failed: fetch/);
      assert.equal(fs.readFileSync(path.join(workspace, 'backend/.env'), 'utf8'), 'preserved runtime settings');
      assert.equal(fs.readFileSync(path.join(workspace, 'frontend/.next/BUILD_ID'), 'utf8'), 'live build');
      assert.equal(fs.readFileSync(path.join(workspace, 'backend/app.txt'), 'utf8'), mode === 'failed fetch' ? 'newer build' : 'requested build');
      if (mode !== 'failed fetch') assert.equal(git(workspace, 'rev-parse', 'HEAD'), expected);
      assert.ok(!fs.readFileSync(path.join(workspace, '.git/config'), 'utf8').includes('test-token'));
    } finally {
      holder.stdin.end('\n');
      await new Promise(resolve => holder.once('exit', resolve));
      fs.rmSync(base, { recursive: true, force: true });
    }
  });
}
