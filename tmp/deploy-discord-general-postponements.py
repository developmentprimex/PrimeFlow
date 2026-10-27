"""Publish only the approved general task postponement changes, with backups."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
root = Path(__file__).resolve().parents[1]
remote = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow')
ops = Path(r'\\192.168.10.8\C$\PrimeFlowOps\DiscordTaskPostponements-20261027')
files = ['backend/discord_ui.py', 'backend/discord_m2_approvals.py',
    'backend/app/api/routers/discord_m2_postponements.py', 'backend/app/models/discord_m2_postponement.py',
    'backend/alembic/versions/0167_discord_task_postponements.py']
for file in files:
    target = remote / file
    assert target.resolve().is_relative_to(remote.resolve())
    if target.exists():
        current = target.read_text(encoding='utf-8-sig')
        local = (root / file).read_text(encoding='utf-8-sig')
        baseline = subprocess.check_output(['git', 'show', 'HEAD:' + file], cwd=root).decode('utf-8-sig').replace('\r\n', '\n')
        saved = ops / 'backup' / file
        if saved.exists():
            baseline = saved.read_text(encoding='utf-8-sig')
        if current not in (baseline, local):
            raise RuntimeError('Unexpected production changes: ' + file)
print(json.dumps({'preflight': 'passed', 'files': len(files)}))
if '--publish' not in __import__('sys').argv:
    raise SystemExit(0)
ops.mkdir(parents=True, exist_ok=True)
for file in files:
    target, source, backup = remote / file, root / file, ops / 'backup' / file
    if target.exists() and not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
    shutil.copy2(source, target)
    assert hashlib.sha256(target.read_bytes()).digest() == hashlib.sha256(source.read_bytes()).digest()
shutil.copy2(root / 'tmp/restart-m2-apis.ps1', ops / 'restart-apis.ps1')
(ops / 'activate.cmd').write_text('@echo off\r\n'
    'powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\\PrimeFlowOps\\DiscordTaskPostponements-20261027\\restart-apis.ps1 > C:\\PrimeFlowOps\\DiscordTaskPostponements-20261027\\activate.log 2>&1\r\n'
    'if errorlevel 1 exit /b 1\r\nset PM2_HOME=C:\\pm2-system\r\n'
    'set PATH=C:\\npm-global;C:\\Program Files\\nodejs;%PATH%\r\n'
    'call C:\\npm-global\\pm2.cmd restart primeflow-discord >> C:\\PrimeFlowOps\\DiscordTaskPostponements-20261027\\activate.log 2>&1\r\n'
    'exit /b %ERRORLEVEL%\r\n', encoding='ascii')
template = (root / 'tmp/m2-activate-task.xml').read_text(encoding='utf-8-sig')
template = template.replace('encoding="UTF-8"', 'encoding="UTF-16"').replace('<LogonType>ServiceAccount</LogonType>', '')
template = template.replace('C:\\PrimeFlowOps\\M2-20261026\\activate.cmd', 'C:\\PrimeFlowOps\\DiscordTaskPostponements-20261027\\activate.cmd')
xml = root / 'tmp/discord-general-postponements-task.xml'
xml.write_text(template, encoding='utf-16')
name = 'PrimeFlow-DiscordTaskPostponements-20261027'
subprocess.run(['schtasks.exe', '/Create', '/S', '192.168.10.8', '/TN', name, '/XML', str(xml), '/F'], check=True)
subprocess.run(['schtasks.exe', '/Run', '/S', '192.168.10.8', '/TN', name], check=True)
print(json.dumps({'published': len(files), 'task': name}))
