"""Operator-requested M2 test: scoped to Rinesa, using normal production controls."""
import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from dotenv import dotenv_values
import httpx

ROOT = Path(__file__).resolve().parents[1]
REMOTE = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow\backend')
remote_env = dotenv_values(REMOTE / '.env')
# Keep credentials in memory; never place them in arguments, files or output.
for key in ('DISCORD_ASSISTANT_ENABLED', 'DISCORD_BRIDGE_SECRET', 'DISCORD_BOT_TOKEN', 'DISCORD_GUILD_ID', 'FRONTEND_URL'):
    if remote_env.get(key):
        os.environ[key] = remote_env[key]
sys.path.insert(0, str(ROOT / 'backend'))
from app.config import settings
from app.db import SessionLocal, engine
from app.api.routers.discord_m2 import collect_questions
from app.models.discord_assistant import DiscordLink
from app.models.discord_m2_question import DiscordM2Question
from app.models.m2_reporting_points import M2ReportingPointsReport
from app.models.task_user_comment import TaskUserComment
from app.models.audit_log import AuditLog
from sqlalchemy import select, text
import discord_m2_client as ui

USER_ID = uuid.UUID('e2e3568f-0e54-4067-be33-013c6177d47b')
MANIFEST = ROOT / 'tmp/m2-rinesa-live-test.json'
API = (remote_env.get('PRIMEFLOW_API_BASE_URL') or 'https://api-flow.primexeu.com').rstrip('/') + '/api/discord'


async def main(mode):
    async with SessionLocal() as db:
        link = (await db.execute(select(DiscordLink).where(DiscordLink.user_id == USER_ID, DiscordLink.enabled.is_(True)))).scalar_one()
        actor = {'discord_user_id': link.discord_user_id, 'guild_id': link.guild_id, 'channel_id': link.channel_id}
        version = (await db.execute(text('SELECT version_num FROM alembic_version'))).scalar_one()
    async with httpx.AsyncClient(timeout=60) as client:
        async def bridge(path, payload):
            response = await client.post(API + path, json=payload, headers={'X-Primeflow-Discord-Secret': settings.DISCORD_BRIDGE_SECRET})
            if response.status_code >= 400:
                raise RuntimeError(f'Bridge {path}: HTTP {response.status_code}: {response.text[:400]}')
            return response.json()
        if mode == 'check':
            qid = json.loads(MANIFEST.read_text(encoding='utf-8'))[0]['question_id'] if MANIFEST.exists() else str(uuid.uuid4())
            response = await client.post(API + '/bot/m2/' + qid + '/open', json=actor,
                headers={'X-Primeflow-Discord-Secret': settings.DISCORD_BRIDGE_SECRET})
            result = response.json()
            for base in ('http://192.168.10.8:8000/api/discord', 'http://192.168.10.8:8080/api/discord'):
                try:
                    probe = await client.post(base + '/bot/m2/' + qid + '/open', json=actor,
                        headers={'X-Primeflow-Discord-Secret': settings.DISCORD_BRIDGE_SECRET})
                    print(json.dumps({'probe': base, 'status': probe.status_code, 'edit_version_available': 'answered_at' in probe.json()}))
                except Exception as exc:
                    print(json.dumps({'probe': base, 'error': type(exc).__name__}))
            print(json.dumps({'migration': version, 'api_test_status': response.status_code,
                              'edit_version_available': 'answered_at' in result, 'current_choice': result.get('choice'),
                              'bot_status': json.loads((REMOTE / '.discord-worker-status.json').read_text(encoding='utf-8'))}))
            dump = json.loads(Path(r'\\192.168.10.8\C$\pm2-system\dump.pm2').read_text(encoding='utf-8-sig'))
            for process in dump:
                if process.get('name') == 'primeflow-discord':
                    print(json.dumps({key: process.get(key) for key in ('name', 'pm_err_log_path', 'pm_out_log_path', 'args')}))
        elif mode == 'send':
            async with SessionLocal() as db:
                jobs = (await collect_questions(db, now=datetime.now(timezone.utc), only_user_id=USER_ID))['jobs']
            sent = []
            for job in jobs:
                assert job['discord_user_id'] == actor['discord_user_id'] and job['channel_id'] == actor['channel_id']
                job = await bridge(f"/bot/m2/{job['id']}/open", actor)
                if job['answered']:
                    continue
                import hashlib
                payload = {'content': '**PROVË M2 — sikur ora 11:45**\n' + ui.prompt(job),
                           'components': ui.controls(job).to_components(),
                           'allowed_mentions': {'parse': [], 'users': [actor['discord_user_id']]},
                           'nonce': hashlib.sha256(f"m2:{job['id']}".encode()).hexdigest()[:24], 'enforce_nonce': True}
                response = await client.post(f"https://discord.com/api/v10/channels/{actor['channel_id']}/messages",
                    json=payload, headers={'Authorization': 'Bot ' + settings.DISCORD_BOT_TOKEN})
                if response.status_code >= 400:
                    raise RuntimeError(f'Discord send: HTTP {response.status_code}: {response.text[:300]}')
                message = response.json()
                await bridge(f"/bot/m2/{job['id']}/ack", {**actor, 'message_id': message['id']})
                sent.append({'question_id': job['id'], 'task_id': job['task_id'], 'kind': job['kind'],
                             'title': job['snapshot']['title'], 'message_id': message['id'],
                             'url': f"https://discord.com/channels/{actor['guild_id']}/{actor['channel_id']}/{message['id']}"})
            MANIFEST.write_text(json.dumps(sent, indent=2, ensure_ascii=False), encoding='utf-8')
            print(json.dumps({'sent': sent}, ensure_ascii=True))
        elif mode == 'message':
            for item in json.loads(MANIFEST.read_text(encoding='utf-8')):
                response = await client.get(f"https://discord.com/api/v10/channels/{actor['channel_id']}/messages/{item['message_id']}",
                    headers={'Authorization': 'Bot ' + settings.DISCORD_BOT_TOKEN})
                response.raise_for_status()
                message = response.json()
                print(json.dumps({'message_id': message['id'], 'edited_at': message.get('edited_timestamp'),
                                  'buttons': [component.get('label') for row in message.get('components', []) for component in row.get('components', [])],
                                  'content': message.get('content')}, ensure_ascii=True))
        elif mode == 'refresh':
            for item in json.loads(MANIFEST.read_text(encoding='utf-8')):
                job = await bridge(f"/bot/m2/{item['question_id']}/open", actor)
                response = await client.patch(f"https://discord.com/api/v10/channels/{actor['channel_id']}/messages/{item['message_id']}",
                    json={'content': '**PROVË M2 — sikur ora 11:45**\n' + ui.prompt(job),
                          'components': ui.controls(job).to_components(), 'allowed_mentions': {'parse': []}},
                    headers={'Authorization': 'Bot ' + settings.DISCORD_BOT_TOKEN})
                if response.status_code >= 400:
                    raise RuntimeError(f'Discord refresh: HTTP {response.status_code}')
                print(json.dumps({'updated_existing_message': item['message_id'], 'choice': job.get('choice'),
                                  'comment_optional': job.get('choice') == 'PO'}))
        elif mode == 'verify':
            manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
            async with SessionLocal() as db:
                for item in manifest:
                    question = await db.get(DiscordM2Question, uuid.UUID(item['question_id']))
                    report = (await db.execute(select(M2ReportingPointsReport).where(M2ReportingPointsReport.report_date == question.day))).scalar_one()
                    task_comment = (await db.execute(select(TaskUserComment.comment).where(
                        TaskUserComment.task_id == question.task_id, TaskUserComment.user_id == USER_ID))).scalar_one_or_none()
                    answers = report.manual_answers or {}
                    print(json.dumps({'question_id': item['question_id'], 'answered_at': str(question.answered_at) if question.answered_at else None,
                        'choice': question.choice, 'reason_code': question.reason_code, 'comment': question.comment,
                        'report_choice': answers.get(f'delivery_choice:{question.task_id}'),
                        'report_comment': answers.get(f'delivery:{question.task_id}'),
                        'task_comment_contains_reply': bool(question.comment and question.comment in (task_comment or ''))}, ensure_ascii=True))
    await engine.dispose()

parser = argparse.ArgumentParser()
parser.add_argument('mode', choices=['check', 'send', 'message', 'refresh', 'verify'])
asyncio.run(main(parser.parse_args().mode))
