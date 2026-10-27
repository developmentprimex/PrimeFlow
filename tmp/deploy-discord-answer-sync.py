"""Deploy only tested platform-answer synchronization files with exact backups."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
root = Path(__file__).resolve().parents[1]
remote = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow\backend')
ops = Path(r'\\192.168.10.8\C$\PrimeFlowOps\DiscordAnswerSync-20261027')
files = {'app/api/routers/__init__.py':'fcb2abfdbc40343570ad0e8e51d9158796f2bcd034ed1fc7ff9de4bfe4fd366f',
'app/api/routers/discord_m2.py':'4a9e913234ff70e6202cf3cb55ca96ba56f43627875b7bdc476d043e37844d48',
'app/api/routers/m2_reporting_points.py':'3d464d7820e5edd35fa10ddd3020ce7edd2d67d2350e387ca8b55d12e614e32f',
'app/models/discord_assistant.py':'98c2e0ec632030d7a367deac73e44beb69f93dbf440fcdd7e20f25fad7b4c61a',
'app/models/discord_m2_question.py':'caddb69e57959bd178f8e31e59c6d756b908ab6f52dc8c57f437e2920165d02a',
'discord_bot.py':'e9906b05d76c3fa2b145e8511574af4318cbe9d0a2b825c5dfc04c159696f8d0',
'discord_m2_client.py':'0bb24ed9cd86205ca58af277187b1df6147df0c9e9b4696be1ca292dc377ccc5',
'app/api/routers/discord_answer_sync.py':None, 'app/services/discord_answer_sync.py':None,
'discord_answer_sync.py':None, 'alembic/versions/0168_discord_answer_sync.py':None}
for file, expected in files.items():
    target, source = remote / file, root / 'backend' / file
    assert target.resolve().is_relative_to(remote.resolve())
    if target.exists():
        assert hashlib.sha256(target.read_bytes()).hexdigest() in (expected, hashlib.sha256(source.read_bytes()).hexdigest()), 'Unexpected production changes: ' + file
print(json.dumps({'preflight': 'passed', 'files': len(files)}))
if '--publish' not in __import__('sys').argv:
    raise SystemExit(0)
ops.mkdir(parents=True, exist_ok=True)
for file in files:
    target, source, backup = remote / file, root / 'backend' / file, ops / 'backup' / file
    if target.exists() and not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    assert target.read_bytes() == source.read_bytes()
shutil.copy2(root / 'tmp/restart-m2-apis.ps1', ops / 'restart-apis.ps1')
(ops / 'activate.cmd').write_text('@echo off\r\n'
'powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\\PrimeFlowOps\\DiscordAnswerSync-20261027\\restart-apis.ps1 > C:\\PrimeFlowOps\\DiscordAnswerSync-20261027\\activate.log 2>&1\r\n'
'if errorlevel 1 exit /b 1\r\nset PM2_HOME=C:\\pm2-system\r\nset PATH=C:\\npm-global;C:\\Program Files\\nodejs;%PATH%\r\n'
'call C:\\npm-global\\pm2.cmd restart primeflow-discord >> C:\\PrimeFlowOps\\DiscordAnswerSync-20261027\\activate.log 2>&1\r\nexit /b %ERRORLEVEL%\r\n', encoding='ascii')
template = (root / 'tmp/m2-activate-task.xml').read_text(encoding='utf-8-sig').replace('encoding="UTF-8"', 'encoding="UTF-16"').replace('<LogonType>ServiceAccount</LogonType>', '')
template = template.replace('C:\\PrimeFlowOps\\M2-20261026\\activate.cmd', 'C:\\PrimeFlowOps\\DiscordAnswerSync-20261027\\activate.cmd')
xml = root / 'tmp/discord-answer-sync-task.xml'
xml.write_text(template, encoding='utf-16')
name = 'PrimeFlow-DiscordAnswerSync-20261027'
subprocess.run(['schtasks.exe', '/Create', '/S', '192.168.10.8', '/TN', name, '/XML', str(xml), '/F'], check=True)
subprocess.run(['schtasks.exe', '/Run', '/S', '192.168.10.8', '/TN', name], check=True)
print(json.dumps({'published': len(files), 'task': name}))
