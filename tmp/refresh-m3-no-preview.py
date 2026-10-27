"""Update existing M3 task cards in place: compact, no unfurl, full-text button."""
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
import httpx
from dotenv import dotenv_values
from sqlalchemy import select

root = Path(__file__).resolve().parents[1]
remote = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow\backend')
config = dotenv_values(remote / '.env')
for key in ('DISCORD_GUILD_ID', 'DISCORD_ASSISTANT_ENABLED', 'DISCORD_BRIDGE_SECRET', 'FRONTEND_URL'):
    if config.get(key):
        os.environ[key] = config[key]
sys.path.insert(0, str(root / 'backend'))
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
from app.db import SessionLocal, engine
from app.models.discord_m3_question import DiscordM3Question as Question
from app.models.discord_assistant import DiscordLink
from app.models.user import User
from app.services.primeflow_report import report_timezone
import discord_m3_client as ui


async def main():
    async with SessionLocal() as db:
        pairs = (await db.execute(select(Question, DiscordLink).join(DiscordLink, DiscordLink.id == Question.link_id)
            .join(User, User.id == DiscordLink.user_id).where(Question.day == datetime.now(report_timezone()).date(),
                Question.kind == 'tomorrow_task', Question.message_id.is_not(None), DiscordLink.enabled.is_(True),
                DiscordLink.guild_id == config['DISCORD_GUILD_ID'], User.is_active.is_(True)))).all()
        jobs = [{'id': str(q.id), 'message_id': q.message_id,
            **{key: getattr(link, key) for key in ('discord_user_id', 'guild_id', 'channel_id')}} for q, link in pairs]
    await engine.dispose()
    async with httpx.AsyncClient(timeout=60) as client:
        async def discord(method, path, payload=None):
            for _ in range(8):
                response = await client.request(method, 'https://discord.com/api/v10' + path, json=payload,
                    headers={'Authorization': 'Bot ' + config['DISCORD_BOT_TOKEN']})
                if response.status_code == 429:
                    await asyncio.sleep(min(10, float(response.json().get('retry_after', 1))))
                    continue
                if response.is_error:
                    raise RuntimeError(f'Discord {method}: HTTP {response.status_code}')
                return response.json()
            raise RuntimeError('Rate limit persisted')
        updated = []
        for claimed in jobs:
            actor = {key: claimed[key] for key in ('discord_user_id', 'guild_id', 'channel_id')}
            response = await client.post(f"http://192.168.10.8:8000/api/discord/bot/m3/{claimed['id']}/open", json=actor,
                headers={'X-Primeflow-Discord-Secret': config['DISCORD_BRIDGE_SECRET']})
            if response.is_error:
                raise RuntimeError(f'Bridge open: HTTP {response.status_code}')
            job = response.json()
            path = f"/channels/{claimed['channel_id']}/messages/{claimed['message_id']}"
            current = await discord('GET', path)
            trial = 'TEST' in current['content'].split('\n', 1)[0]
            await discord('PATCH', path, {'content': ('🧪 TEST · ' if trial else '') + ui.prompt(job),
                'components': ui.controls(job).to_components(), 'flags': int(current.get('flags', 0)) | 4,
                'embeds': [], 'allowed_mentions': {'parse': []}})
            checked = await discord('GET', path)
            assert int(checked['flags']) & 4 and not checked.get('embeds')
            labels = [item.get('label') for group in checked['components'] for item in group.get('components', [])]
            assert 'Hap detyrën' in labels
            updated.append(claimed['message_id'])
            print(json.dumps({'updated': claimed['message_id'], 'preview_removed': True, 'full_text_button': True}))
        print(json.dumps({'updated_existing': len(updated), 'new_messages': 0, 'answers_changed': False}))

asyncio.run(main())
