"""Read-only process ownership diagnostic. Never emits environment variables."""
from pathlib import Path
import json
import subprocess
import os

OPS=Path(__file__).resolve().parent
os.environ['PM2_HOME']=r'C:\pm2-system'
os.environ['PATH']=r'C:\npm-global;C:\Program Files\nodejs;'+os.environ.get('PATH','')
result=subprocess.run(['cmd.exe','/d','/c',r'C:\npm-global\pm2.cmd','jlist'],capture_output=True,
    encoding='utf-8',errors='replace',timeout=30)
items=json.loads(result.stdout)
managed=[dict(name=p.get('name'),pid=p.get('pid'),cwd=p.get('pm2_env',{}).get('pm_cwd'),
    args=p.get('pm2_env',{}).get('args'),status=p.get('pm2_env',{}).get('status')) for p in items
    if p.get('name') in ('primex-backend','backend-api-flow','primeflow-discord')]
script=r'''
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$listeners = Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object LocalPort -in @(8000,8080) | Select-Object LocalAddress,LocalPort,OwningProcess
$processes = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'uvicorn.*app.main:app' -or $_.CommandLine -match 'discord_bot.py' } | Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine
@{listeners=@($listeners);processes=@($processes)} | ConvertTo-Json -Depth 5 -Compress
'''
probe=subprocess.run(['powershell.exe','-NoProfile','-Command',script],capture_output=True,
    encoding='utf-8',errors='replace',timeout=45)
if probe.returncode:raise RuntimeError('process_probe_failed')
(OPS/'processes.json').write_text(json.dumps(dict(managed=managed,system=json.loads(probe.stdout))),encoding='utf-8')
