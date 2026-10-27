"""Publish the task-name UI correction and restart only the Discord worker."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
root = Path(__file__).resolve().parents[1]
remote = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow\backend\discord_m2_approvals.py')
source = root / 'backend/discord_m2_approvals.py'
ops = Path(r'\\192.168.10.8\C$\PrimeFlowOps\DiscordPostponementContext-20261027')
expected = '1f45b2f018d51bffed7a10111d2136a6aef3fc39ba9f22c993174d545c1ab380'
live = hashlib.sha256(remote.read_bytes()).hexdigest()
assert live in (expected, hashlib.sha256(source.read_bytes()).hexdigest()), 'Unexpected worker source changes'
ops.mkdir(parents=True, exist_ok=True)
backup = ops / 'discord_m2_approvals.backup.py'
if not backup.exists():
    shutil.copy2(remote, backup)
shutil.copy2(source, remote)
assert remote.read_bytes() == source.read_bytes()
(ops / 'activate.cmd').write_text('@echo off\r\nset PM2_HOME=C:\\pm2-system\r\nset PATH=C:\\npm-global;C:\\Program Files\\nodejs;%PATH%\r\ncall C:\\npm-global\\pm2.cmd restart primeflow-discord > C:\\PrimeFlowOps\\DiscordPostponementContext-20261027\\activate.log 2>&1\r\nexit /b %ERRORLEVEL%\r\n', encoding='ascii')
template = (root / 'tmp/m2-activate-task.xml').read_text(encoding='utf-8-sig')
template = template.replace('encoding="UTF-8"', 'encoding="UTF-16"').replace('<LogonType>ServiceAccount</LogonType>', '')
template = template.replace('C:\\PrimeFlowOps\\M2-20261026\\activate.cmd', 'C:\\PrimeFlowOps\\DiscordPostponementContext-20261027\\activate.cmd')
xml = root / 'tmp/discord-postponement-context-task.xml'
xml.write_text(template, encoding='utf-16')
name = 'PrimeFlow-DiscordPostponementContext-20261027'
subprocess.run(['schtasks.exe', '/Create', '/S', '192.168.10.8', '/TN', name, '/XML', str(xml), '/F'], check=True)
subprocess.run(['schtasks.exe', '/Run', '/S', '192.168.10.8', '/TN', name], check=True)
print(json.dumps({'published': 'discord_m2_approvals.py', 'task': name}))
