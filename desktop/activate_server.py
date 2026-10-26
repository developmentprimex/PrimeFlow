"""One-shot scoped deployment. Run on the server only after staging/backups."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

OPS = Path(__file__).resolve().parent
ROOT = Path(r'C:\actions-runner\_work\PrimeFlow\PrimeFlow\backend')
PYTHON = Path(r'C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe')
PM2 = Path(r'C:\npm-global\pm2.cmd')


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def command(args):
    result = subprocess.run(args, cwd=ROOT, text=True, encoding='utf-8', errors='replace',
        capture_output=True, timeout=150)
    with (OPS/'commands.log').open('a',encoding='utf-8') as log:
        log.write(result.stdout+'\n'+result.stderr+'\n')
    if result.returncode:raise RuntimeError('deployment_command_failed')


def verify(port):
    for _ in range(35):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/openapi.json',timeout=5) as response:
                spec = json.load(response)
            if '/api/mira-desktop/capabilities' in spec['paths']:
                try:urllib.request.urlopen(f'http://127.0.0.1:{port}/api/mira-desktop/capabilities',timeout=5)
                except urllib.error.HTTPError as exc:
                    if exc.code==401:return
                raise RuntimeError('desktop_auth_guard_failed')
        except (OSError,ValueError):time.sleep(2)
    raise RuntimeError('api_not_ready')


def main():
    os.chdir(ROOT)
    sys.path.insert(0,str(ROOT))
    from app.config import settings
    if not settings.OPENAI_API_KEY:raise RuntimeError('openai_not_configured')
    plan = json.loads((OPS/'manifest.json').read_text(encoding='utf-8'))
    # Compare again immediately before any mutation; preserve concurrent work.
    for entry in plan:
        target=ROOT/entry['path']
        if ROOT.resolve() not in target.resolve().parents:raise RuntimeError('invalid_target')
        if digest(target)!=entry['before']:raise RuntimeError('server_source_changed')
        if digest(OPS/'staged'/entry['path'])!=entry['after']:raise RuntimeError('staged_source_changed')
    protected = {name:digest(ROOT/name) for name in (
        'discord_bot.py','discord_voice_meetings.py','discord_voice_client.py','discord-voice/worker.mjs')}
    # Read metadata only; do not restart the API during an active capture.
    import asyncio
    from sqlalchemy import text
    from app.db import engine
    async def preflight():
        async with engine.connect() as conn:
            await conn.execute(text('SET TRANSACTION READ ONLY'))
            versions=list((await conn.execute(text('SELECT version_num FROM alembic_version'))).scalars())
            activity_column=await conn.scalar(text("SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='projects' AND column_name='is_active'"))
            active=await conn.scalar(text("SELECT count(*) FROM discord_voice_meetings WHERE status IN ('STARTING','LISTENING') AND heartbeat_at > now()-interval '60 seconds'"))
            host=await conn.scalar(text("SELECT count(*) FROM mira_1h_meetings WHERE status IN ('GA_PHASE','STAFF_PHASE') AND ended_at IS NULL AND started_at > now()-interval '2 hours'"))
        await engine.dispose()
        return versions,active,host,activity_column
    versions,active,host,activity_column=asyncio.run(preflight())
    (OPS/'preflight.json').write_text(json.dumps(dict(versions=versions,active_captures=active,active_host=host)),encoding='utf-8')
    if active or host:raise RuntimeError('active_meeting_defer')
    if versions not in (['0164_project_is_active'],['0165_mira_desktop'],['0166_merge_mira_repetitive']) or activity_column!=1:
        raise RuntimeError('unexpected_database_revision')
    backup=OPS/'backup'
    for entry in plan:
        target=ROOT/entry['path']
        if target.exists():
            saved=backup/entry['path'];saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
    installed=False
    try:
        installed=True
        for entry in plan:
            target=ROOT/entry['path'];target.parent.mkdir(parents=True,exist_ok=True)
            temporary=target.with_suffix(target.suffix+'.mira-new')
            shutil.copy2(OPS/'staged'/entry['path'],temporary);os.replace(temporary,target)
        # Only the new additive migration; no downgrade or existing data rewrite.
        if versions==['0164_project_is_active']:
            command([str(PYTHON),'-m','alembic','upgrade','0165_mira_desktop'])
        command([str(PYTHON),'-c','from app.main import app; assert any(r.path == "/api/mira-desktop/capabilities" for r in app.routes)'])
        os.environ['PM2_HOME']=r'C:\pm2-system'
        os.environ['PATH']=r'C:\npm-global;C:\Program Files\nodejs;'+os.environ.get('PATH','')
        for name,port in [('primex-backend',8000),('backend-api-flow',8080)]:
            command(['cmd.exe','/d','/c',str(PM2),'restart',name]);verify(port)
        for name,value in protected.items():
            if digest(ROOT/name)!=value:raise RuntimeError('discord_source_changed_during_deployment')
        (OPS/'result.json').write_text(json.dumps(dict(ok=True,migration='0165_mira_desktop',
            ports=[8000,8080],discord_sources_unchanged=True)),encoding='utf-8')
    except Exception:
        # Leave additive tables/migration in place; preserve any data already
        # accepted. Disable the new router by restoring registration files.
        if installed:
            for name in (entry['path'] for entry in plan):
                if (backup/name).exists():shutil.copy2(backup/name,ROOT/name)
            for name in ('primex-backend','backend-api-flow'):
                try:command(['cmd.exe','/d','/c',str(PM2),'restart',name])
                except Exception:pass
        raise


if __name__=='__main__':
    try:main()
    except Exception as exc:
        # Codes only: exception text could include deployment configuration.
        code=str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__
        import traceback
        frames=[dict(file=Path(frame.filename).name,line=frame.lineno,function=frame.name)
            for frame in traceback.extract_tb(exc.__traceback__)]
        (OPS/'result.json').write_text(json.dumps(dict(ok=False,error=code,frames=frames)),encoding='utf-8')
        sys.exit(1)
