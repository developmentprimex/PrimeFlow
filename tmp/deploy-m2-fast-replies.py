"""Publish the fast delivery-answer path; preserve the current route for rollback."""
import hashlib
import argparse
import json
import shutil
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--purpose', choices=['fast', 'manual'], default='fast')
purpose = parser.parse_args().purpose
label = 'M2Manual-20261026' if purpose == 'manual' else 'M2Fast-20261026'
remote = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow\backend')
ops = Path(r'\\192.168.10.8\C$\PrimeFlowOps') / label
source, target = root / 'backend/app/api/routers/discord_m2.py', remote / 'app/api/routers/discord_m2.py'
backup = ops / 'discord_m2.before.py'
deployed = target.read_text(encoding='utf-8-sig')
if deployed != source.read_text(encoding='utf-8-sig'):
    if backup.exists() and deployed != backup.read_text(encoding='utf-8-sig'):
        raise RuntimeError('Unexpected server change')
    if purpose == 'fast' and not backup.exists() and '# Delivery changes only' in deployed:
        raise RuntimeError('Unexpected fast path already deployed')
    if purpose == 'manual' and not backup.exists() and "'postponed': 'postponed_comment'" not in deployed:
        raise RuntimeError('Unexpected mapping before the manual-comment fix')
ops.mkdir(parents=True, exist_ok=True)
if not backup.exists():
    shutil.copy2(target, backup)
shutil.copy2(source, target)
assert hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(target.read_bytes()).digest()
shutil.copy2(root / 'tmp/restart-m2-apis.ps1', ops / 'restart-apis.ps1')
(ops / 'restart.cmd').write_text(('@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\\PrimeFlowOps\\M2Fast-20261026\\restart-apis.ps1 > C:\\PrimeFlowOps\\M2Fast-20261026\\restart.log 2>&1\r\nexit /b %ERRORLEVEL%\r\n').replace('M2Fast-20261026', label), encoding='ascii')
xml = (root / 'tmp/m2-activate-task.xml').read_text(encoding='utf-8-sig')
xml = xml.replace('encoding="UTF-8"', 'encoding="UTF-16"').replace('<LogonType>ServiceAccount</LogonType>', '')
xml = xml.replace('C:\\PrimeFlowOps\\M2-20261026\\activate.cmd', 'C:\\PrimeFlowOps\\' + label + '\\restart.cmd')
task_file = root / 'tmp/m2-fast-task-utf16.xml'
task_file.write_text(xml, encoding='utf-16')
task_name = 'PrimeFlow-M2-Manual-20261026' if purpose == 'manual' else 'PrimeFlow-M2-Fast-20261026'
subprocess.run(['schtasks.exe', '/Create', '/S', '192.168.10.8', '/TN', task_name, '/XML', str(task_file), '/F'], check=True)
subprocess.run(['schtasks.exe', '/Run', '/S', '192.168.10.8', '/TN', task_name], check=True)
print(json.dumps({'copied': 1, 'restarting': ['primex-backend', 'backend-api-flow'], 'backup': str(backup)}))
