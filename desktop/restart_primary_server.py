"""Explicitly approved replacement of the one identified stale API listener.

No file deployment, schema migration, Discord changes, or other process stops.
"""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(r'C:\actions-runner\_work\PrimeFlow\PrimeFlow\backend')
OPS=Path(__file__).resolve().parent
os.environ['PM2_HOME']=r'C:\pm2-system'
os.environ['PATH']=r'C:\npm-global;C:\Program Files\nodejs;'+os.environ.get('PATH','')


def run(args):
    result=subprocess.run(args,cwd=ROOT,capture_output=True,encoding='utf-8',errors='replace',timeout=90)
    with (OPS/'primary-restart.log').open('a',encoding='utf-8') as handle:
        handle.write(result.stdout+'\n'+result.stderr+'\n')
    if result.returncode:raise RuntimeError('primary_command_failed')


async def preflight():
    from app.db import engine
    from sqlalchemy import text
    async with engine.connect() as db:
        await db.execute(text('SET TRANSACTION READ ONLY'))
        active=await db.scalar(text("SELECT count(*) FROM discord_voice_meetings WHERE status IN ('STARTING','LISTENING') AND heartbeat_at>now()-interval '60 seconds'"))
        version=list((await db.execute(text('SELECT version_num FROM alembic_version'))).scalars())
    await engine.dispose()
    if active or version!=['0165_mira_desktop']:raise RuntimeError('primary_preflight_defer')


def main():
    if sys.argv[1:]!=['--approved-pid','6620']:raise RuntimeError('explicit_pid_approval_required')
    os.chdir(ROOT);sys.path.insert(0,str(ROOT));asyncio.run(preflight())
    # Snapshot identity and listener before stopping PM2. Then recheck every
    # field immediately before stopping the exact approved PID, without /T.
    script=r'''
$ErrorActionPreference='Stop'
$approvedId=6620
$expectedPython='C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe'
$candidate=Get-CimInstance Win32_Process -Filter "ProcessId=$approvedId"
if (-not $candidate) { throw 'Approved PID no longer exists; diagnose again' }
$line=$candidate.CommandLine -replace '"',''
$listeners=@(Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object -ExpandProperty OwningProcess -Unique)
if ($listeners.Count -ne 1 -or $listeners[0] -ne $approvedId) { throw 'Approved PID does not own port8000' }
if ($candidate.ExecutablePath -ne $expectedPython -or $line -notmatch '\buvicorn\s+app\.main:app\b' -or $line -notmatch '--port\s+8000(?:\s|$)') { throw 'Refusing unrelated process' }
& 'C:\npm-global\pm2.cmd' stop primex-backend
if ($LASTEXITCODE -ne 0) { throw 'PM2 stop failed' }
$fresh=Get-CimInstance Win32_Process -Filter "ProcessId=$approvedId"
if ($fresh) {
    if ($fresh.CreationDate -ne $candidate.CreationDate -or $fresh.CommandLine -ne $candidate.CommandLine -or $fresh.ExecutablePath -ne $expectedPython) { throw 'Process identity changed' }
    & taskkill.exe /PID 6620 /F
    if ($LASTEXITCODE -ne 0) { throw 'Approved old API could not stop' }
}
'''
    helper=OPS/'approved-primary-stop.ps1';helper.write_text(script,encoding='utf-8-sig')
    try:
        run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(helper)])
    finally:
        # Restore the managed API even if an identity check refused the old PID.
        run(['cmd.exe','/d','/c',r'C:\npm-global\pm2.cmd','restart','primex-backend'])
    from activate_server import verify
    verify(8000)
    (OPS/'primary-result.json').write_text(json.dumps(dict(ok=True,port=8000,old_pid=6620,
        discord_unchanged=True)),encoding='utf-8')


if __name__=='__main__':
    try:main()
    except Exception as exc:
        (OPS/'primary-result.json').write_text(json.dumps(dict(ok=False,error=type(exc).__name__)),encoding='utf-8')
        sys.exit(1)
