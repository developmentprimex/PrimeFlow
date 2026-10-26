"""Reviewed, narrow M2 approval deployment with source backups and staged frontend."""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
remote = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow')
ops = Path(r'\\192.168.10.8\C$\PrimeFlowOps\M2Approvals-20261026')
files = ['backend/app/api/routers/__init__.py', 'backend/app/api/routers/discord_m2.py',
    'backend/app/api/routers/discord_m2_postponements.py', 'backend/app/api/routers/m2_reporting_points.py',
    'backend/app/api/routers/tasks.py', 'backend/app/models/__init__.py', 'backend/app/models/discord_m2_postponement.py',
    'backend/app/services/discord_m2.py', 'backend/app/services/discord_m2_postponements.py',
    'backend/app/services/m2_reporting_points.py', 'backend/discord_bot.py', 'backend/discord_m2_client.py',
    'backend/discord_m2_approvals.py', 'backend/alembic/versions/0163_discord_m2_approvals.py',
    'frontend/src/components/m2-reporting-points-view.tsx', 'frontend/src/lib/m2-reporting-points-draft.ts']


def verify():
    mismatches = []
    for file in files:
        target = remote / file
        assert target.resolve().is_relative_to(remote.resolve())
        if not target.exists():
            continue
        deployed = target.read_text(encoding='utf-8-sig')
        source = (root / file).read_text(encoding='utf-8-sig')
        if deployed == source:
            continue
        backup = ops / 'backup' / file
        if backup.exists():
            baseline = backup.read_text(encoding='utf-8-sig')
        else:
            try:
                baseline = subprocess.check_output(['git', 'show', 'HEAD:' + file], cwd=root, stderr=subprocess.DEVNULL).decode('utf-8-sig').replace('\r\n', '\n')
            except subprocess.CalledProcessError:
                baseline = None
        if deployed != baseline:
            mismatches.append(file)
    print(json.dumps({'files': len(files), 'unexpected_server_changes': mismatches}))
    if mismatches:
        raise RuntimeError('Refusing to overwrite unexpected server changes')


parser = argparse.ArgumentParser()
parser.add_argument('mode', choices=['check', 'publish'])
mode = parser.parse_args().mode
verify()
if mode == 'publish':
    ops.mkdir(parents=True, exist_ok=True)
    for file in files:
        target, source, backup = remote / file, root / file, ops / 'backup' / file
        if target.exists() and not backup.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        assert hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(target.read_bytes()).digest()
    shutil.copy2(root / 'tmp/restart-m2-apis.ps1', ops / 'restart-apis.ps1')
    (ops / 'activate-backend.cmd').write_text('@echo off\r\n'
        'powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\\PrimeFlowOps\\M2Approvals-20261026\\restart-apis.ps1 '
        '> C:\\PrimeFlowOps\\M2Approvals-20261026\\backend.log 2>&1\r\n'
        'if errorlevel 1 exit /b 1\r\nset PM2_HOME=C:\\pm2-system\r\n'
        'set PATH=C:\\npm-global;C:\\Program Files\\nodejs;%PATH%\r\n'
        'call C:\\npm-global\\pm2.cmd restart primeflow-discord >> C:\\PrimeFlowOps\\M2Approvals-20261026\\backend.log 2>&1\r\n'
        'exit /b %ERRORLEVEL%\r\n', encoding='ascii')
    shutil.copy2(root / 'tmp/build-m2-approvals-frontend.ps1', ops / 'frontend.ps1')
    (ops / 'frontend.cmd').write_text('@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\\PrimeFlowOps\\M2Approvals-20261026\\frontend.ps1 '
        '> C:\\PrimeFlowOps\\M2Approvals-20261026\\frontend.log 2>&1\r\nexit /b %ERRORLEVEL%\r\n', encoding='ascii')
    template = (root / 'tmp/m2-activate-task.xml').read_text(encoding='utf-8-sig')
    for role, command in [('Backend', 'activate-backend.cmd'), ('Frontend', 'frontend.cmd')]:
        xml = template.replace('encoding="UTF-8"', 'encoding="UTF-16"').replace('<LogonType>ServiceAccount</LogonType>', '')
        xml = xml.replace('PT5M', 'PT15M').replace('C:\\PrimeFlowOps\\M2-20261026\\activate.cmd', 'C:\\PrimeFlowOps\\M2Approvals-20261026\\' + command)
        file = root / f'tmp/m2-approvals-{role}.xml'
        file.write_text(xml, encoding='utf-16')
        name = f'PrimeFlow-M2-Approvals-{role}-20261026'
        subprocess.run(['schtasks.exe', '/Create', '/S', '192.168.10.8', '/TN', name, '/XML', str(file), '/F'], check=True)
        subprocess.run(['schtasks.exe', '/Run', '/S', '192.168.10.8', '/TN', name], check=True)
    print(json.dumps({'published': len(files), 'backup': str(ops / 'backup')}))
