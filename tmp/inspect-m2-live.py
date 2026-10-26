import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.config import settings
from app.db import engine
from sqlalchemy import text


async def main():
    print(json.dumps({'local_discord_enabled': settings.DISCORD_ASSISTANT_ENABLED,
        'token_present': bool(settings.DISCORD_BOT_TOKEN), 'bridge_present': bool(settings.DISCORD_BRIDGE_SECRET),
        'api_base': settings.PRIMEFLOW_API_BASE_URL, 'guild_id': settings.DISCORD_GUILD_ID}))
    async with engine.connect() as conn:
        rows = await conn.execute(text('SELECT u.id, u.full_name, u.username, d.discord_user_id, d.guild_id, d.channel_id, d.enabled FROM users u JOIN discord_links d ON u.id=d.user_id WHERE u.is_active=true'))
        for row in rows.mappings():
            print(json.dumps(dict(row), default=str, ensure_ascii=True))
    await engine.dispose()

asyncio.run(main())
dump = Path(r'\\192.168.10.8\C$\pm2-system\dump.pm2')
for process in json.loads(dump.read_text(encoding='utf-8-sig')):
    if any(word in process.get('name', '') for word in ('discord', 'backend', 'public-api')):
        print(json.dumps({key: process.get(key) for key in ('name', 'pm_cwd', 'pm_exec_path', 'exec_interpreter')}))
