"""Read-only checks of the activated M3 API, schema, bundle, and bot readiness."""
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import httpx
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'backend'))
from sqlalchemy import text
from app.db import engine
from app.models.discord_m3_question import DiscordM3Question

remote = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow\backend')
ops = Path(r'\\192.168.10.8\C$\PrimeFlowOps\DiscordM3-20261027')
if '--status' in sys.argv:
    status = json.loads((remote / '.discord-worker-status.json').read_text(encoding='utf-8'))
    print(json.dumps({'discord_connected_at': status['connected_at'], 'pid': status['pid']}))
    raise SystemExit(0)
if '--inspect' in sys.argv:
    print((ops / 'activate.log').read_text(encoding='utf-8-sig', errors='replace')[-7000:])
    status = json.loads((remote / '.discord-worker-status.json').read_text(encoding='utf-8'))
    print(json.dumps({'discord_connected_at': status['connected_at'], 'pid': status['pid']}))
    logs = Path(r'\\192.168.10.8\C$\pm2-system\logs')
    for path in logs.glob('*error*.log'):
        if not any(name in path.name for name in ('primex-backend', 'backend-api-flow', 'primeflow-discord')):
            continue
        with path.open('rb') as stream:
            stream.seek(max(0, path.stat().st_size - 65536))
            lines = stream.read(65536).decode('utf-8', errors='replace').splitlines()[-150:]
        print(path.name)
        print('\n'.join(line for line in lines if any(token in line for token in ('Error:', 'ImportError', 'Traceback', 'startup', 'server process', 'Uvicorn running', 'polling failed', 'M3 delivery'))))
    raise SystemExit(0)
manifest = json.loads((ops / 'manifest.json').read_text(encoding='utf-8'))
for item in manifest:
    if hashlib.sha256((remote / item['path']).read_bytes()).hexdigest() != item['sha256']:
        raise RuntimeError('Server file changed: ' + item['path'])
log = (ops / 'activate.log').read_text(encoding='utf-8-sig', errors='replace')
if 'DISCORD_M3_ACTIVATED' not in log:
    raise RuntimeError('M3 activation has not completed')

async def check():
    async with engine.connect() as connection:
        version = (await connection.execute(text('SELECT version_num FROM alembic_version'))).scalar_one()
        if version != '0169_discord_m3_questions':
            raise RuntimeError('Unexpected schema revision: ' + version)
        columns = set((await connection.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='discord_m3_questions'"))).scalars())
        if columns != set(DiscordM3Question.__table__.columns.keys()):
            raise RuntimeError('M3 schema columns are missing')
    await engine.dispose()
    checks = []
    async with httpx.AsyncClient(timeout=30) as client:
        for port in (8000, 8080):
            health = await client.get(f'http://192.168.10.8:{port}/health')
            health.raise_for_status()
            schema = await client.get(f'http://192.168.10.8:{port}/openapi.json')
            schema.raise_for_status()
            if '/api/discord/bot/m3/claim' not in schema.json()['paths']:
                raise RuntimeError('M3 route is missing on port ' + str(port))
            checks.append({'port': port, 'health': health.json()['status'], 'm3_route': True})
            print(json.dumps(checks[-1]))
    status = json.loads((remote / '.discord-worker-status.json').read_text(encoding='utf-8'))
    connected = datetime.fromisoformat(status['connected_at'])
    activated = datetime.fromtimestamp((ops / 'activate.ps1').stat().st_mtime, timezone.utc)
    if connected < activated:
        raise RuntimeError('Discord worker has not reconnected after activation')
    print(json.dumps({'schema': version, 'files_verified': len(manifest), 'apis': checks,
        'discord_connected_at': connected.isoformat(), 'discord_pid': status['pid']}))

asyncio.run(check())
