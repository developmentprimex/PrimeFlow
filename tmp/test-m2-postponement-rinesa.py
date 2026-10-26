"""User-authorized fixture: create today's test task, move both dates, ask its owner."""
import asyncio
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from dotenv import dotenv_values
import httpx

ROOT = Path(__file__).resolve().parents[1]
REMOTE = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow\backend')
env = dotenv_values(REMOTE / '.env')
for key in ('DISCORD_ASSISTANT_ENABLED', 'DISCORD_BRIDGE_SECRET', 'DISCORD_BOT_TOKEN', 'DISCORD_GUILD_ID', 'FRONTEND_URL'):
    if env.get(key):
        os.environ[key] = env[key]
sys.path.insert(0, str(ROOT / 'backend'))
from sqlalchemy import select
from app.db import SessionLocal, engine
from app.models.task import Task
from app.models.user import User
from app.models.discord_assistant import DiscordLink
from app.schemas.task import TaskCreate
from app.api.routers.tasks import create_task_in_session
from app.api.routers.discord_m2 import collect_questions, data_with_moves
from app.services.daily_realization_events import record_task_semantic_events, semantic_local_day
from app.services.audit import add_audit_log
from app.services.primeflow_report import report_timezone
from app.config import settings
import discord_m2_client as ui

USER_ID = uuid.UUID('e2e3568f-0e54-4067-be33-013c6177d47b')
MANIFEST = ROOT / 'tmp/m2-postponement-rinesa-test.json'
TITLE = 'TEST M2 — RA — SHTYRJE SOT/SOT'
API = (env.get('PRIMEFLOW_API_BASE_URL') or 'https://api-flow.primexeu.com').rstrip('/') + '/api/discord'


def save_manifest(value):
    MANIFEST.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


async def main():
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8')) if MANIFEST.exists() else {}
    now = datetime.now(report_timezone())
    day, tomorrow = now.date(), now.date() + timedelta(days=1)
    today_start, today_due = datetime.combine(day, time(8), report_timezone()), datetime.combine(day, time(12), report_timezone())
    if manifest and manifest.get('day') != day.isoformat():
        raise RuntimeError('This fixture belongs to another day; do not silently reuse it.')
    async with SessionLocal() as db:
        user = await db.get(User, USER_ID)
        assert user and user.is_active
        if not manifest.get('task_id'):
            # Use the ordinary task creation flow, including assignment and audit.
            created = await create_task_in_session(TaskCreate(title=TITLE,
                description='Detyrë TEST për provën e pyetjeve M2 në Discord. Fillimisht sot/sot; shtyrë për nesër. Arsyeja dhe komenti plotësohen nga Rinesa në Discord.',
                department_id=user.department_id, assigned_to=USER_ID, assignees=[USER_ID],
                start_date=today_start, due_date=today_due, finish_period='AM', status='TODO',
                priority='NORMAL', is_1h_report=False), db, user)
            manifest = {'day': day.isoformat(), 'task_id': str(created.id), 'title': TITLE}
            save_manifest(manifest)
        task_id = uuid.UUID(manifest['task_id'])
        task = (await db.execute(select(Task).where(Task.id == task_id).with_for_update())).scalar_one()
        assert task.title == TITLE and task.assigned_to == USER_ID and task.is_active
        if not manifest.get('shifted'):
            if semantic_local_day(task.start_date) == day and semantic_local_day(task.due_date) == day:
                old = {'start_date': task.start_date.isoformat(), 'due_date': task.due_date.isoformat()}
                task.start_date = datetime.combine(tomorrow, time(8), report_timezone())
                task.due_date = datetime.combine(tomorrow, time(12), report_timezone())
                task.moved_days = 1
                events = record_task_semantic_events(db=db, task_id=task.id, actor_user_id=USER_ID,
                    before=old, after={'start_date': task.start_date.isoformat(), 'due_date': task.due_date.isoformat()},
                    old_assignee_ids=[USER_ID], new_assignee_ids=[USER_ID])
                add_audit_log(db=db, actor_user_id=USER_ID, entity_type='task', entity_id=task.id,
                    action='task.discord_m2_test_fixture', after={'case': 'SOT/SOT -> tomorrow; start_due',
                        'unexplained_test_only': True, 'semantic_events': [str(event.id) for event in events],
                        'purpose': 'User requested a test of the missing-postponement-reason question. No production validation was changed.'})
                await db.commit()
            elif not (semantic_local_day(task.start_date) == tomorrow and semantic_local_day(task.due_date) == tomorrow):
                raise RuntimeError('Unexpected test task dates; refusing to alter them.')
            manifest.update(shifted=True, old_start=day.isoformat(), old_due=day.isoformat(),
                            start=tomorrow.isoformat(), due=tomorrow.isoformat())
            save_manifest(manifest)
    async with SessionLocal() as db:
        data = await data_with_moves(db, day)
        matches = {section: [row for row in data.get(section, []) if row.get('task_id') == str(task_id)]
                   for section in ('postponed', 'postponed_am')}
        if not matches['postponed'] or matches['postponed'][0]['postponement_kind'] != 'start_due':
            raise RuntimeError('Test task did not enter the expected M2 postponement section.')
        jobs = (await collect_questions(db, now=datetime.now(timezone.utc), only_user_id=USER_ID))['jobs']
        jobs = [job for job in jobs if job['task_id'] == str(task_id) and job['kind'] == 'postponed']
        manifest['report_sections'] = [section for section, rows in matches.items() if rows]
        save_manifest(manifest)
    async with httpx.AsyncClient(timeout=60) as client:
        async def bridge(path, payload):
            response = await client.post(API + path, json=payload, headers={'X-Primeflow-Discord-Secret': settings.DISCORD_BRIDGE_SECRET})
            if response.status_code >= 400:
                raise RuntimeError(f'Bridge {path}: HTTP {response.status_code}: {response.text[:300]}')
            return response.json()
        for job in jobs:
            actor = {key: job[key] for key in ('discord_user_id', 'guild_id', 'channel_id')}
            assert job['discord_user_id'] == '1493239399150915696'
            job = await bridge(f"/bot/m2/{job['id']}/open", actor)
            manifest['question_id'] = job['id']
            save_manifest(manifest)
            response = await client.post(f"https://discord.com/api/v10/channels/{actor['channel_id']}/messages",
                headers={'Authorization': 'Bot ' + settings.DISCORD_BOT_TOKEN},
                json={'content': '**PROVË M2 — Pse u shty detyra?**\n' + ui.prompt(job),
                      'components': ui.controls(job).to_components(),
                      'allowed_mentions': {'parse': [], 'users': [actor['discord_user_id']]},
                      'nonce': hashlib.sha256(f"m2:{job['id']}".encode()).hexdigest()[:24], 'enforce_nonce': True})
            if response.status_code >= 400:
                raise RuntimeError(f'Discord send: HTTP {response.status_code}: {response.text[:300]}')
            message = response.json()
            manifest.update(message_id=message['id'], channel_id=actor['channel_id'], guild_id=actor['guild_id'],
                url=f"https://discord.com/channels/{actor['guild_id']}/{actor['channel_id']}/{message['id']}")
            save_manifest(manifest)
            await bridge(f"/bot/m2/{job['id']}/ack", {**actor, 'message_id': message['id']})
        if not manifest.get('message_id'):
            raise RuntimeError('No new question was claimed. The task exists; inspect its question lease before retrying.')
    await engine.dispose()
    print(json.dumps(manifest, ensure_ascii=True))

asyncio.run(main())
