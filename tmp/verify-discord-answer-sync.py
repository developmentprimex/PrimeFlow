"""Read-only confirmation of deployed synchronization and existing edited messages."""
import asyncio
import json
import sys
from pathlib import Path
import httpx
from dotenv import dotenv_values
from sqlalchemy import select, func
root = Path(__file__).resolve().parents[1]
remote = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow\backend')
config = dotenv_values(remote / '.env')
sys.path.insert(0, str(root / 'backend'))
from app.db import SessionLocal, engine
from app.models.discord_m2_question import DiscordM2Question as Question
from app.models.discord_assistant import DiscordMeetingAlert as Alert, DiscordLink

async def main():
    samples = []
    async with SessionLocal() as db:
        for name, model in (('m2', Question), ('meeting', Alert)):
            count = (await db.execute(select(func.count()).select_from(model).where(model.sync_hash.is_not(None)))).scalar_one()
            print(json.dumps({'source': name, 'messages_synchronized': count}))
            row = (await db.execute(select(model.message_id, DiscordLink.channel_id).join(DiscordLink, DiscordLink.id == model.link_id).where(
                model.sync_hash.is_not(None), DiscordLink.enabled.is_(True)).order_by(model.sent_at.desc()).limit(1))).first()
            if row:
                samples.append((name, row))
    async with httpx.AsyncClient(timeout=25) as client:
        for base in ('http://192.168.10.8:8000', 'http://192.168.10.8:8080', 'https://api-flow.primexeu.com'):
            result = await client.get(base + '/openapi.json')
            result.raise_for_status()
            assert '/api/discord/bot/answer-sync/claim' in result.json()['paths']
            print(json.dumps({'api': base, 'sync_route_active': True}))
        for name, row in samples:
            result = await client.get(f'https://discord.com/api/v10/channels/{row.channel_id}/messages/{row.message_id}',
                headers={'Authorization': 'Bot ' + config['DISCORD_BOT_TOKEN']})
            result.raise_for_status()
            message = result.json()
            print(json.dumps({'source': name, 'discord_message_exists': True,
                'message_edited': bool(message.get('edited_timestamp')),
                'active_answer_buttons': any(item.get('custom_id') for group in message.get('components', []) for item in group.get('components', []))}))
    await engine.dispose()
asyncio.run(main())
