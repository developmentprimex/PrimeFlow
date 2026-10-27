"""Preflight or publish the tested M3 bundle, preserving exact server backups."""
import hashlib
import difflib
import json
import shutil
import subprocess
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

root = Path(__file__).resolve().parents[1]
remote = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow\backend')
ops = Path(r'\\192.168.10.8\C$\PrimeFlowOps\DiscordM3-20261027')
files = [
    'app/api/routers/__init__.py', 'app/api/routers/m3_reporting_points.py',
    'app/api/routers/meetings.py', 'app/api/routers/tasks.py', 'app/models/__init__.py',
    'discord_bot.py',
    'app/api/routers/discord_m3.py', 'app/models/discord_m3_question.py',
    'app/services/discord_m3.py', 'discord_m3_client.py',
    'alembic/versions/0169_discord_m3_questions.py',
]
# Exact server versions reviewed with --inspect; Git's shared index may change
# while another task commits unrelated work in this workspace.
reviewed = {
    'app/api/routers/__init__.py': '9f47f5e93421c38838bfbaa35401b1abe233387e11e040dc7ef43aafca79616b',
    'app/api/routers/m3_reporting_points.py': '63f00b4593ac436d811a547883f1bb2596b38982712f3ff2c144a728846e534f',
    'app/api/routers/meetings.py': 'f029b7131811465898b7a1af33ed5491b10aa244767912636b9d17f9ce0f175e',
    'app/api/routers/tasks.py': 'b4afc21a12a2c875648a3515a2eccb5020f3dad89ae4bfb027bc734e16303fb3',
    'app/models/__init__.py': '4846551dc6db7b36828e1a8dac6eb1e5599c659a7d31d0df371cdd407baeaf91',
    'discord_bot.py': 'e26204304349a5daaaecdb9826043c5096c20f37b6dcd67e70a323cfc5945954',
    'discord_m2_approvals.py': '6c00dfa3880c12f7cf82a978700b2113ea971c8b8611ad352b37454d259dc8ab',
}


def normalized(value):
    return value.decode('utf-8-sig').replace('\r\n', '\n')


for prerequisite in ('alembic/versions/0168_discord_answer_sync.py', 'discord_answer_sync.py'):
    if not (remote / prerequisite).is_file():
        raise RuntimeError('Deploy prerequisite is missing: ' + prerequisite)

manifest = []
for name in files:
    source, target = root / 'backend' / name, remote / name
    if not target.resolve().is_relative_to(remote.resolve()):
        raise RuntimeError('Target is outside the backend')
    local = source.read_bytes()
    baseline = subprocess.run(['git', 'show', ':backend/' + name], cwd=root,
        capture_output=True, check=False)
    if target.exists():
        current = target.read_bytes()
        allowed = {normalized(local)}
        if baseline.returncode == 0:
            allowed.add(normalized(baseline.stdout))
        if normalized(current) not in allowed and hashlib.sha256(current).hexdigest() != reviewed.get(name):
            if '--inspect' in sys.argv:
                base = normalized(baseline.stdout) if baseline.returncode == 0 else ''
                print(json.dumps({'unexpected': name, 'sha256': hashlib.sha256(current).hexdigest()}))
                print(''.join(difflib.unified_diff(base.splitlines(True), normalized(current).splitlines(True), fromfile='index/' + name, tofile='server/' + name)))
                continue
            raise RuntimeError('Unexpected server changes: ' + name)
    manifest.append({'path': name, 'existed': target.exists(),
        'sha256': hashlib.sha256(local).hexdigest()})

print(json.dumps({'preflight': 'passed', 'files': len(files), 'migration': '0169_discord_m3_questions'}))
if '--publish' not in sys.argv:
    raise SystemExit(0)

ops.mkdir(parents=True, exist_ok=True)
for item in manifest:
    name = item['path']
    source, target, backup = root / 'backend' / name, remote / name, ops / 'backup' / name
    if target.exists() and not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if hashlib.sha256(target.read_bytes()).hexdigest() != item['sha256']:
        raise RuntimeError('Copy verification failed: ' + name)
(ops / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
shutil.copy2(root / 'tmp/restart-m2-apis.ps1', ops / 'restart-apis.ps1')
(ops / 'activate.ps1').write_text(
    "$ErrorActionPreference = 'Stop'\n"
    "$env:PM2_HOME = 'C:\\pm2-system'\n"
    "$env:PATH = 'C:\\npm-global;C:\\Program Files\\nodejs;' + $env:PATH\n"
    "Set-Location 'C:\\actions-runner\\_work\\PrimeFlow\\PrimeFlow\\backend'\n"
    "& 'C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python313\\python.exe' -m alembic upgrade 0169_discord_m3_questions\n"
    "if ($LASTEXITCODE -ne 0) { throw 'M3 migration failed' }\n"
    "& 'C:\\PrimeFlowOps\\DiscordM3-20261027\\restart-apis.ps1'\n"
    "& 'C:\\npm-global\\pm2.cmd' restart primeflow-discord\n"
    "if ($LASTEXITCODE -ne 0) { throw 'Discord restart failed' }\n"
    "Write-Output 'DISCORD_M3_ACTIVATED'\n", encoding='utf-8')
(ops / 'activate.cmd').write_text('@echo off\r\n'
    'powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\\PrimeFlowOps\\DiscordM3-20261027\\activate.ps1 > C:\\PrimeFlowOps\\DiscordM3-20261027\\activate.log 2>&1\r\n'
    'exit /b %ERRORLEVEL%\r\n', encoding='ascii')
template = (root / 'tmp/m2-activate-task.xml').read_text(encoding='utf-8-sig')
template = template.replace('encoding="UTF-8"', 'encoding="UTF-16"').replace('<LogonType>ServiceAccount</LogonType>', '')
template = template.replace('C:\\PrimeFlowOps\\M2-20261026\\activate.cmd', 'C:\\PrimeFlowOps\\DiscordM3-20261027\\activate.cmd')
xml = root / 'tmp/discord-m3-activate-task.xml'
xml.write_text(template, encoding='utf-16')
name = 'PrimeFlow-DiscordM3-20261027'
subprocess.run(['schtasks.exe', '/Create', '/S', '192.168.10.8', '/TN', name, '/XML', str(xml), '/F'], check=True)
subprocess.run(['schtasks.exe', '/Run', '/S', '192.168.10.8', '/TN', name], check=True)
print(json.dumps({'published': len(files), 'task': name, 'backup': str(ops / 'backup')}))
