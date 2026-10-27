"""Publish the tested M2 meeting follow-up without touching other work."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
root = Path(__file__).resolve().parents[1]
remote = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow\backend')
ops = Path(r'\\192.168.10.8\C$\PrimeFlowOps\DiscordM2Meetings-20261027')
files = {'app/services/discord_meetings.py': '88d53b40f74a26a062ae8f0e566f751f131dacab4dd11fa7f421cb47483f0320',
    'app/api/routers/discord_assistant.py': '78c591ddaac792648449067009d27eda26f202945f351744b18838aa23fb0a58',
    'discord_ui.py': '8ccb0462f2c4a3456452e6bb71f78aba4f6af67aca65e5f034a13d57ee2c7e3a'}
for file, expected in files.items():
    target, source = remote / file, root / 'backend' / file
    assert target.resolve().is_relative_to(remote.resolve())
    assert hashlib.sha256(target.read_bytes()).hexdigest() in (expected, hashlib.sha256(source.read_bytes()).hexdigest()), 'Unexpected server changes: ' + file
ops.mkdir(parents=True, exist_ok=True)
for file in files:
    target, source, backup = remote / file, root / 'backend' / file, ops / 'backup' / file
    if not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
    shutil.copy2(source, target)
    assert target.read_bytes() == source.read_bytes()
shutil.copy2(root / 'tmp/restart-m2-apis.ps1', ops / 'restart-apis.ps1')
(ops / 'activate.cmd').write_text('@echo off\r\n'
    'powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\\PrimeFlowOps\\DiscordM2Meetings-20261027\\restart-apis.ps1 > C:\\PrimeFlowOps\\DiscordM2Meetings-20261027\\activate.log 2>&1\r\n'
    'if errorlevel 1 exit /b 1\r\nset PM2_HOME=C:\\pm2-system\r\nset PATH=C:\\npm-global;C:\\Program Files\\nodejs;%PATH%\r\n'
    'call C:\\npm-global\\pm2.cmd restart primeflow-discord >> C:\\PrimeFlowOps\\DiscordM2Meetings-20261027\\activate.log 2>&1\r\nexit /b %ERRORLEVEL%\r\n', encoding='ascii')
template = (root / 'tmp/m2-activate-task.xml').read_text(encoding='utf-8-sig')
template = template.replace('encoding="UTF-8"', 'encoding="UTF-16"').replace('<LogonType>ServiceAccount</LogonType>', '')
template = template.replace('C:\\PrimeFlowOps\\M2-20261026\\activate.cmd', 'C:\\PrimeFlowOps\\DiscordM2Meetings-20261027\\activate.cmd')
xml = root / 'tmp/discord-m2-meetings-task.xml'
xml.write_text(template, encoding='utf-16')
name = 'PrimeFlow-DiscordM2Meetings-20261027'
subprocess.run(['schtasks.exe', '/Create', '/S', '192.168.10.8', '/TN', name, '/XML', str(xml), '/F'], check=True)
subprocess.run(['schtasks.exe', '/Run', '/S', '192.168.10.8', '/TN', name], check=True)
print(json.dumps({'published': list(files), 'task': name}))
