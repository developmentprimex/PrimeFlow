"""Publish the reviewed M2 backend files, preserving previous files for rollback."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
remote = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow')
ops = Path(r'\\192.168.10.8\C$\PrimeFlowOps\M2-20261026')
files = ['backend/app/api/routers/__init__.py', 'backend/app/models/__init__.py', 'backend/discord_bot.py',
         'backend/app/api/routers/m2_reporting_points.py', 'backend/app/services/m2_reporting_points.py',
         'backend/app/api/routers/discord_m2.py', 'backend/app/models/discord_m2_question.py',
         'backend/app/services/discord_m2.py', 'backend/discord_m2_client.py',
         'backend/alembic/versions/0162_discord_m2_questions.py']

# Validate every target before writing any file. Never overwrite an unexpected
# server edit, or replace the first rollback copy when this helper is retried.
for file in files:
    target = remote / file
    assert target.resolve().is_relative_to(remote.resolve())
    if target.exists() and not (ops / 'backup' / file).exists():
        try:
            base = subprocess.check_output(['git', 'show', 'HEAD:' + file], cwd=root, stderr=subprocess.DEVNULL).decode('utf-8-sig').replace('\r\n', '\n')
        except subprocess.CalledProcessError:
            base = (root / file).read_text(encoding='utf-8-sig')
        if target.read_text(encoding='utf-8-sig') != base and target.read_text(encoding='utf-8-sig') != (root / file).read_text(encoding='utf-8-sig'):
            raise RuntimeError('Unexpected server changes: ' + file)

for file in files:
    source, target, backup = root / file, remote / file, ops / 'backup' / file
    if target.exists() and not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(target.read_bytes()).digest():
        raise RuntimeError('Copy verification failed: ' + file)

ops.mkdir(parents=True, exist_ok=True)
(ops / 'activate.cmd').write_text(
    '@echo off\r\nset PM2_HOME=C:\\pm2-system\r\nset RUNNER_TRACKING_ID=\r\n'
    'set PATH=C:\\npm-global;C:\\Program Files\\nodejs;%PATH%\r\n'
    'cd /d C:\\actions-runner\\_work\\PrimeFlow\\PrimeFlow\\backend\r\n'
    'call C:\\npm-global\\pm2.cmd restart primex-backend backend-api-flow primeflow-discord '
    '> C:\\PrimeFlowOps\\M2-20261026\\activate.log 2>&1\r\n'
    'set M2_EXIT=%ERRORLEVEL%\r\n'
    'echo M2_EXIT=%M2_EXIT% >> C:\\PrimeFlowOps\\M2-20261026\\activate.log\r\n'
    'exit /b %M2_EXIT%\r\n', encoding='ascii')
print(json.dumps({'copied': len(files), 'backup': str(ops / 'backup'),
                  'pm2_available': Path(r'\\192.168.10.8\C$\npm-global\pm2.cmd').is_file()}))
