"""Deploy and restart only the Discord client for the simplified M2 interaction."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
remote = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow\backend')
ops = Path(r'\\192.168.10.8\C$\PrimeFlowOps\M2Order-20261026')
source, target = root / 'backend/discord_m2_client.py', remote / 'discord_m2_client.py'
backup = ops / 'discord_m2_client.before.py'
deployed = target.read_text(encoding='utf-8-sig')
if deployed != source.read_text(encoding='utf-8-sig'):
    if backup.exists() and deployed != backup.read_text(encoding='utf-8-sig'):
        raise RuntimeError('Unexpected server change')
    if not backup.exists() and ('modal.initial_save' not in deployed or 'for choice, label, style in' not in deployed):
        raise RuntimeError('Unexpected client version before button-order update')
ops.mkdir(parents=True, exist_ok=True)
if not backup.exists():
    shutil.copy2(target, backup)
shutil.copy2(source, target)
assert hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(target.read_bytes()).digest()
(ops / 'restart.cmd').write_text(
    '@echo off\r\nset PM2_HOME=C:\\pm2-system\r\n'
    'set PATH=C:\\npm-global;C:\\Program Files\\nodejs;%PATH%\r\n'
    'call C:\\npm-global\\pm2.cmd restart primeflow-discord > C:\\PrimeFlowOps\\M2Order-20261026\\restart.log 2>&1\r\n'
    'exit /b %ERRORLEVEL%\r\n', encoding='ascii')
xml = (root / 'tmp/m2-activate-task.xml').read_text(encoding='utf-8-sig')
xml = xml.replace('encoding="UTF-8"', 'encoding="UTF-16"').replace('<LogonType>ServiceAccount</LogonType>', '')
xml = xml.replace('C:\\PrimeFlowOps\\M2-20261026\\activate.cmd', 'C:\\PrimeFlowOps\\M2Order-20261026\\restart.cmd')
task_file = root / 'tmp/m2-simple-task-utf16.xml'
task_file.write_text(xml, encoding='utf-16')
task_name = 'PrimeFlow-M2-Order-20261026'
subprocess.run(['schtasks.exe', '/Create', '/S', '192.168.10.8', '/TN', task_name, '/XML', str(task_file), '/F'], check=True)
subprocess.run(['schtasks.exe', '/Run', '/S', '192.168.10.8', '/TN', task_name], check=True)
print(json.dumps({'copied': 1, 'restart': 'primeflow-discord', 'backup': str(backup)}))
