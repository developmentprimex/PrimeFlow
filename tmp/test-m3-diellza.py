"""User-requested 15:50 and 16:10 simulation, exclusively for Diellza Veliu."""
import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, time
from pathlib import Path
import httpx
from dotenv import dotenv_values
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
REMOTE = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow\backend')
config = dotenv_values(REMOTE / '.env')
for key in ('DISCORD_ASSISTANT_ENABLED', 'DISCORD_BRIDGE_SECRET', 'DISCORD_GUILD_ID', 'FRONTEND_URL'):
    if config.get(key):
        os.environ[key] = config[key]
sys.path.insert(0, str(ROOT / 'backend'))
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
from app.db import SessionLocal, engine
from app.models.user import User
from app.models.discord_assistant import DiscordLink
from app.models.discord_m3_question import DiscordM3Question as Question
from app.api.routers import discord_m3 as api
import discord_m3_client as ui

BASE = 'http://192.168.10.8:8000/api/discord'


async def main(mode, username='diellza.veliu'):
    compact_refresh = mode == 'compact-refresh'
    if compact_refresh:
        mode = 'tomorrow-test'
    day = datetime.now(api.report_timezone()).date()
    test_version = '-per-task-v2' if mode in {'tomorrow-test', 'full-test'} else ''
    recipient = username.split('.')[0]
    manifest_path = ROOT / 'tmp' / f'm3-{recipient}-test{test_version}-{day.isoformat()}.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else []
    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == username, User.is_active.is_(True)))).scalar_one()
        display_name = user.full_name or user.username
        uid = user.id
        link = (await db.execute(select(DiscordLink).where(DiscordLink.user_id == uid,
            DiscordLink.enabled.is_(True), DiscordLink.guild_id == config['DISCORD_GUILD_ID']))).scalar_one()
        assert link.channel_id and link.discord_user_id
        actor = {key: getattr(link, key) for key in ('discord_user_id', 'guild_id', 'channel_id')}
        data = await api.reports.build_task_data(db, day)
        rows, owners, names = await api.tomorrow_data(db, api.rules.target_day(day))
        personal = [row for row in rows if uid in owners.get(row['task_id'], set())]
        m3ids = {row['task_id'] for kind in ('untouched', 'delivery') for row in data.get(kind, [])}
        from app.models.task import Task
        import uuid
        tasks = (await db.execute(select(Task).where(Task.id.in_([uuid.UUID(tid) for tid in m3ids])))).scalars().all()
        today_owners = await api.task_owners(db, tasks)
        meetings = await api.meeting_candidates(db, datetime.combine(day, time(15, 50), api.report_timezone()), {uid})
        preview = {'user': user.full_name or user.username, 'day': str(day),
            '15:50': {kind: sum(uid in today_owners.get(row['task_id'], set()) for row in data.get(kind, [])) for kind in ('untouched', 'delivery')},
            '16:10': {'tasks': len(personal), 'due_tomorrow': sum(row['due_tomorrow'] for row in personal),
                '1h_tasks': sum(row['is_1h'] for row in personal),
                'slot_questions': sum(uid in owners.get(row['task_id'], set()) for row in api.rules.slot_questions(rows, owners, names))}}
        preview['15:50']['meetings'] = len(meetings)
        print(json.dumps({'preview': preview}))
    if mode == 'preview':
        await engine.dispose()
        return

    async with httpx.AsyncClient(timeout=90) as client:
        async def discord(method, path, payload=None):
            for attempt in range(5):
                response = await client.request(method, 'https://discord.com/api/v10' + path, json=payload,
                    headers={'Authorization': 'Bot ' + config['DISCORD_BOT_TOKEN']})
                if response.status_code == 429:
                    await asyncio.sleep(min(10, float(response.json().get('retry_after', 1))))
                    continue
                if response.is_error:
                    raise RuntimeError(f'Discord {method}: HTTP {response.status_code}')
                return response.json()
            raise RuntimeError('Discord rate limit; retry the same script safely')

        async def bridge(path, payload):
            response = await client.post(BASE + path, json=payload,
                headers={'X-Primeflow-Discord-Secret': config['DISCORD_BRIDGE_SECRET']})
            if response.is_error:
                raise RuntimeError(f'Bridge {path}: HTTP {response.status_code}')
            return response.json()

        # Validate the existing personal workspace before any question is created.
        channel = await discord('GET', f"/channels/{actor['channel_id']}")
        bot = await discord('GET', '/users/@me')
        assert channel['guild_id'] == actor['guild_id']
        assert channel.get('topic') == f"PrimeFlow personal workspace: {actor['discord_user_id']}"
        overwrites = channel.get('permission_overwrites', [])
        everyone = next(item for item in overwrites if item['id'] == actor['guild_id'] and item['type'] == 0)
        assert int(everyone['deny']) & 1024 and not int(everyone['allow']) & 1024
        assert any(item['id'] == actor['discord_user_id'] and item['type'] == 1 and int(item['allow']) & 1024 for item in overwrites)
        assert all(not int(item['allow']) & 1024 or item['id'] in {actor['discord_user_id'], bot['id']} for item in overwrites)

        phases = [('m3', time(15, 50), {'untouched', 'delivery', 'meeting'}),
                  ('tomorrow', time(16, 10), {'tomorrow', 'tomorrow_task', 'slot'})]
        if mode == 'tomorrow-test':
            # Send each current task once, then collect the final button only
            # after the task cards are acknowledged. Preserve every real reply.
            phases = [('tomorrow', time(16, 10), {'tomorrow_task', 'slot'}),
                      ('tomorrow', time(16, 10), {'tomorrow'})]
        if mode == 'full-test':
            phases = [('m3', time(15, 50), {'untouched', 'delivery', 'meeting'}),
                      ('tomorrow', time(16, 10), {'tomorrow_task', 'slot'}),
                      ('tomorrow', time(16, 10), {'tomorrow'})]
        delivered_now = []
        for phase, at, kinds in phases:
            simulated = datetime.combine(day, at, api.report_timezone())
            async with SessionLocal() as db:
                await api.collect_questions(db, now=simulated, phase=phase, only_user_id=uid)
                query = select(Question).where(Question.link_id == link.id, Question.day == day, Question.kind.in_(kinds))
                if mode != 'tomorrow-test':
                    query = query.where(Question.answered_at.is_(None))
                questions = (await db.execute(query.order_by(Question.kind, Question.id))).scalars().all()
                queued = [(str(q.id), None if mode == 'tomorrow-test' else q.message_id) for q in questions]
            for qid, message_id in queued:
                job = await bridge(f'/bot/m3/{qid}/open', actor)
                assert all(job[key] == actor[key] for key in actor)
                if (job.get('answered') and mode != 'tomorrow-test') or job.get('resolved'):
                    continue
                previous = next((item for item in manifest if item['question_id'] == qid), None)
                if compact_refresh and previous is None:
                    continue
                message_id = message_id or (previous or {}).get('message_id')
                label = at.strftime('%H:%M')
                payload = {'content': f'**TEST M3 · {display_name} · sikur ora {label}**\n' + ui.prompt(job),
                    'flags': 4, 'embeds': [],
                    'components': ui.controls(job).to_components(),
                    'allowed_mentions': {'parse': [], 'users': [actor['discord_user_id']]}}
                if compact_refresh:
                    payload['content'] = '🧪 TEST · ' + ui.prompt(job)
                if message_id:
                    message = await discord('PATCH', f"/channels/{actor['channel_id']}/messages/{message_id}", payload)
                    action = 'updated'
                else:
                    payload.update(nonce=hashlib.sha256(f'm3{test_version}:{qid}'.encode()).hexdigest()[:24], enforce_nonce=True)
                    message = await discord('POST', f"/channels/{actor['channel_id']}/messages", payload)
                    action = 'sent'
                item = {'question_id': qid, 'kind': job['kind'], 'simulated_at': label,
                    'message_id': message['id'], 'action': action,
                    'url': f"https://discord.com/channels/{actor['guild_id']}/{actor['channel_id']}/{message['id']}"}
                manifest = [old for old in manifest if old['question_id'] != qid] + [item]
                manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
                await bridge(f'/bot/m3/{qid}/ack', {**actor, 'message_id': message['id']})
                verified = await discord('GET', f"/channels/{actor['channel_id']}/messages/{message['id']}")
                assert verified['content'].startswith('🧪 TEST' if compact_refresh else '**TEST M3') and verified.get('components')
                if mode in {'tomorrow-test', 'full-test'} and job['kind'] == 'tomorrow_task':
                    labels = [component.get('label') for row in verified['components'] for component in row.get('components', [])]
                    assert labels[:3] == ['Po, kryhet' if job['snapshot']['due_tomorrow'] else 'Po, punohet', 'Jo — shtyje', 'Koment']
                    assert '\n' not in ui.prompt(job)
                if mode in {'tomorrow-test', 'full-test'} and job['kind'] == 'tomorrow':
                    assert verified['components'][0]['components'][0]['label'] == 'Po për të gjitha'
                delivered_now.append(item)
                print(json.dumps({'delivered': item}))
        print(json.dumps({'only_user': username, 'verified_messages': len(manifest),
            'by_kind': dict(Counter(item['kind'] for item in manifest)), 'channel_url': f"https://discord.com/channels/{actor['guild_id']}/{actor['channel_id']}"}))
    await engine.dispose()


parser = argparse.ArgumentParser()
parser.add_argument('mode', choices=['preview', 'send', 'tomorrow-test', 'compact-refresh', 'full-test'])
parser.add_argument('--user', choices=['diellza.veliu', 'rinesa.ahmedi'], default='diellza.veliu')
args = parser.parse_args()
asyncio.run(main(args.mode, args.user))
