"""Authorized repair: retire disabled Admin identity, link Elza, provision fresh private channel."""
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
import httpx
from dotenv import dotenv_values
ROOT = Path(__file__).resolve().parents[1]
config = dotenv_values(Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow\backend\.env'))
for key in ('DISCORD_ASSISTANT_ENABLED', 'DISCORD_BRIDGE_SECRET', 'DISCORD_GUILD_ID'):
    if config.get(key):
        os.environ[key] = config[key]
sys.path.insert(0, str(ROOT / 'backend'))
from sqlalchemy import select
from app.db import SessionLocal, engine
from app.models.user import User
from app.models.discord_assistant import DiscordLink
from app.api.routers.discord_assistant import create_link_code
from app.services.audit import add_audit_log

DID = '1493249068556750968'
UID = uuid.UUID('5e4bb1bc-aad2-43e6-bf47-076774c8aa3d')
GUILD = config['DISCORD_GUILD_ID']
BASE = 'https://discord.com/api/v10'
API = (config.get('PRIMEFLOW_API_BASE_URL') or 'https://api-flow.primexeu.com').rstrip('/') + '/api/discord'

async def main():
    async with httpx.AsyncClient(timeout=45) as client:
        async def discord(method, path, value=None):
            response = await client.request(method, BASE + path, json=value,
                headers={'Authorization': 'Bot ' + config['DISCORD_BOT_TOKEN'], 'X-Audit-Log-Reason': 'Authorized Elza Preniqi account relink'})
            if response.is_error:
                raise RuntimeError(f'Discord {method} {path}: HTTP {response.status_code}')
            return response.json() if response.content else None
        async def bridge(path, value):
            response = await client.post(API + path, json=value, headers={'X-Primeflow-Discord-Secret': config['DISCORD_BRIDGE_SECRET']})
            if response.is_error:
                raise RuntimeError(f'Bridge {path}: HTTP {response.status_code}')
            return response.json()
        member = await discord('GET', f'/guilds/{GUILD}/members/{DID}')
        assert member['user']['username'] == 'elzapreniqi', 'Unexpected Discord identity'
        bot = await discord('GET', '/users/@me')
        async with SessionLocal() as db:
            elza = await db.get(User, UID)
            assert elza.username == 'elza.preniqi' and elza.is_active
            old = (await db.execute(select(DiscordLink).where(DiscordLink.guild_id == GUILD,
                DiscordLink.discord_user_id == DID).with_for_update())).scalar_one_or_none()
            if old and old.user_id != UID:
                owner = await db.get(User, old.user_id)
                assert owner.username == 'admin' and not old.enabled, 'Refusing to replace an active or unexpected owner'
                old_channel = old.channel_id
                retired = 'retired:' + old.id.hex[:24]
                old.discord_user_id = retired
                old.selected_task_id = old.pending_instruction = old.selected_fingerprint = old.selected_at = None
                add_audit_log(db=db, actor_user_id=None, entity_type='discord_link', entity_id=old.id,
                    action='discord.identity_released', before={'discord_user_id': DID, 'owner': 'admin', 'enabled': False},
                    after={'discord_user_id': retired, 'reason': 'User requested relink to verified Elza Preniqi', 'target_user_id': str(UID)})
                # Keep the Admin channel and all historical rows, without exposing
                # its messages as Elza's new workspace.
                if old_channel:
                    permissions = [{'id': GUILD, 'type': 0, 'allow': '0', 'deny': '1024'},
                        {'id': bot['id'], 'type': 1, 'allow': '68624', 'deny': '0'}]
                    await discord('PATCH', '/channels/' + old_channel, {
                        'topic': 'PrimeFlow archived workspace: admin', 'permission_overwrites': permissions})
                await db.commit()
                print(json.dumps({'old_admin_link': 'retired', 'history_preserved': True}))
            issued = await create_link_code(user=elza, db=db)
        linked = await bridge('/bot/link', {'code': issued['code'], 'discord_user_id': DID, 'guild_id': GUILD})
        if linked.get('channel_id'):
            channel = await discord('GET', '/channels/' + linked['channel_id'])
        else:
            channels = await discord('GET', f'/guilds/{GUILD}/channels')
            topic = f'PrimeFlow personal workspace: {DID}'
            channel = next((c for c in channels if c.get('topic') == topic), None)
            permissions = [{'id': GUILD, 'type': 0, 'allow': '0', 'deny': '1024'},
                {'id': DID, 'type': 1, 'allow': '68608', 'deny': '0'},
                {'id': bot['id'], 'type': 1, 'allow': '68624', 'deny': '0'}]
            if channel:
                channel = await discord('PATCH', '/channels/' + channel['id'], {'permission_overwrites': permissions})
            else:
                value = {'name': 'primeflow-elza-preniqi', 'type': 0, 'topic': topic, 'permission_overwrites': permissions}
                if config.get('DISCORD_CATEGORY_ID'):
                    value['parent_id'] = config['DISCORD_CATEGORY_ID']
                channel = await discord('POST', f'/guilds/{GUILD}/channels', value)
            await bridge('/bot/bind-channel', {'discord_user_id': DID, 'guild_id': GUILD, 'channel_id': channel['id']})
        result = await bridge('/bot/tasks', {'discord_user_id': DID, 'guild_id': GUILD, 'channel_id': channel['id']})
        assert result['full_name'] == 'Elza Preniqi'
        async with SessionLocal() as db:
            link = (await db.execute(select(DiscordLink).where(DiscordLink.user_id == UID))).scalar_one()
            assert link.enabled and link.discord_user_id == DID and link.channel_id == channel['id']
        print(json.dumps({'linked': result['full_name'], 'verified': True,
            'channel_url': f"https://discord.com/channels/{GUILD}/{channel['id']}"}))
    await engine.dispose()

asyncio.run(main())
