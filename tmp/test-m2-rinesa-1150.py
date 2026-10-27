"""Requested M2 simulation for Rinesa only, using today's real tasks and meetings."""
import argparse
import asyncio
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
import httpx
from dotenv import dotenv_values
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
ROOT = Path(__file__).resolve().parents[1]
config = dotenv_values(Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow\backend\.env'))
for key in ('DISCORD_ASSISTANT_ENABLED', 'DISCORD_BRIDGE_SECRET', 'DISCORD_GUILD_ID', 'FRONTEND_URL'):
    if config.get(key):
        os.environ[key] = config[key]
sys.path.insert(0, str(ROOT / 'backend'))
from app.db import SessionLocal, engine
from app.models.discord_assistant import DiscordLink, DiscordMeetingAlert as Alert
from app.models.discord_m2_question import DiscordM2Question as Question
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.user import User
from app.api.routers.discord_m2 import collect_questions, data_with_moves
from app.services import discord_m2, discord_meetings, discord_answer_sync
from app.services.primeflow_report import report_timezone
import discord_m2_client as ui
import discord_ui as meeting_ui

UID = uuid.UUID('e2e3568f-0e54-4067-be33-013c6177d47b')
BASE = (config.get('PRIMEFLOW_API_BASE_URL') or 'https://api-flow.primexeu.com').rstrip('/') + '/api/discord'

async def main(mode):
    now = datetime.now(timezone.utc)
    day = now.astimezone(report_timezone()).date()
    simulated = datetime.combine(day, time(11, 50), report_timezone())
    async with SessionLocal() as db:
        user = await db.get(User, UID)
        assert user.username == 'rinesa.ahmedi' and user.is_active
        link = (await db.execute(select(DiscordLink).where(DiscordLink.user_id == UID, DiscordLink.enabled.is_(True)))).scalar_one()
        assert link.discord_user_id == '1493239399150915696' and link.guild_id == config['DISCORD_GUILD_ID'] and link.channel_id
        actor = {key: getattr(link, key) for key in ('discord_user_id', 'guild_id', 'channel_id')}
        data = await data_with_moves(db, day)
        candidates = discord_m2.question_rows(data)
        existing = {(q.kind, q.context_key): q for q in (await db.execute(select(Question).where(Question.day == day, Question.link_id == link.id))).scalars()}
        eligible = []
        for kind, row in candidates:
            task_id = uuid.UUID(row['task_id'])
            task = await db.get(Task, task_id)
            owned = task and (task.assigned_to == UID or (await db.execute(select(TaskAssignee.task_id).where(TaskAssignee.task_id == task_id, TaskAssignee.user_id == UID))).first())
            if not owned or not task.is_active:
                continue
            question = existing.get((kind, discord_m2.context_key(kind, row)))
            if question:
                effective = await discord_answer_sync.m2_payload(db, question, link)
                if effective.get('answered') or effective.get('platform_status'):
                    continue
            eligible.append((kind, row, question))
        meetings = await discord_meetings.m2_due_alerts(db, simulated, [UID])
        print(json.dumps({'user': user.full_name, 'simulated_at': simulated.isoformat(),
            'task_questions': [{'kind': kind, 'title': row['title']} for kind, row, _ in eligible],
            'meeting_questions': [meeting.title for meeting, *_ in meetings]}, ensure_ascii=True))
        if mode == 'preview':
            await engine.dispose()
            return
        # The standard collector is explicitly scoped to this user; it does not
        # bypass ownership checks or send anything to other employees.
        collected = await collect_questions(db, now=simulated, only_user_id=UID)
        new_ids = {job['id'] for job in collected['jobs']}
        task_ids = []
        for kind, row, original in eligible:
            question = (await db.execute(select(Question).where(Question.link_id == link.id, Question.day == day,
                Question.kind == kind, Question.context_key == discord_m2.context_key(kind, row)))).scalar_one_or_none()
            if question:
                task_ids.append((str(question.id), question.message_id))
        meeting_jobs = []
        for meeting, user_id, occurrence, kind in meetings:
            assert user_id == UID
            alert = (await db.execute(select(Alert).where(Alert.link_id == link.id, Alert.meeting_id == meeting.id,
                Alert.occurrence_starts_at == occurrence, Alert.kind == kind))).scalar_one_or_none()
            if not alert:
                alert = Alert(link_id=link.id, meeting_id=meeting.id, occurrence_starts_at=occurrence,
                    kind=kind, lease_until=now + timedelta(minutes=2))
                db.add(alert)
                await db.flush()
            meeting_jobs.append({'id': str(alert.id), 'message_id': alert.message_id, 'kind': kind, **actor,
                'meeting': {'id': str(meeting.id), 'title': meeting.title, 'type': meeting.meeting_type,
                    'platform': meeting.platform, 'starts_at': occurrence.isoformat()}})
        await db.commit()
    sent = []
    async with httpx.AsyncClient(timeout=60) as client:
        async def bridge(path, payload):
            response = await client.post(BASE + path, json=payload, headers={'X-Primeflow-Discord-Secret': config['DISCORD_BRIDGE_SECRET']})
            if response.is_error:
                raise RuntimeError(f'Bridge {path}: HTTP {response.status_code}')
            return response.json()
        async def discord(method, path, payload=None):
            response = await client.request(method, 'https://discord.com/api/v10' + path, json=payload,
                headers={'Authorization': 'Bot ' + config['DISCORD_BOT_TOKEN']})
            if response.is_error:
                raise RuntimeError(f'Discord {method}: HTTP {response.status_code}')
            return response.json()
        async def deliver(source, object_id, content, components, message_id):
            payload = {'content': '**TEST M2 · sot, sikur ora 11:50**\n' + content,
                'components': components, 'allowed_mentions': {'parse': [], 'users': [actor['discord_user_id']]}}
            if message_id:
                message = await discord('PATCH', f"/channels/{actor['channel_id']}/messages/{message_id}", payload)
                action = 'updated'
            else:
                payload.update(nonce=hashlib.sha256(f'm2:{source}:{object_id}'.encode()).hexdigest()[:24], enforce_nonce=True)
                message = await discord('POST', f"/channels/{actor['channel_id']}/messages", payload)
                action = 'sent'
            path = f'/bot/m2/{object_id}/ack' if source == 'task' else f'/bot/meetings/{object_id}/ack'
            await bridge(path, {**actor, 'message_id': message['id']})
            sent.append({'source': source, 'id': object_id, 'message_id': message['id'], 'action': action,
                'url': f"https://discord.com/channels/{actor['guild_id']}/{actor['channel_id']}/{message['id']}"})
        for qid, message_id in task_ids:
            job = await bridge(f'/bot/m2/{qid}/open', actor)
            if not job['answered'] and not job.get('platform_status'):
                await deliver('task', qid, ui.prompt(job), ui.controls(job).to_components(), message_id)
        for job in meeting_jobs:
            content, embed, view = meeting_ui.meeting_alert(job)
            # Include the title and time in the text so the simulated question
            # stays compact and edits the same existing message when present.
            content += '\n' + embed.description
            await deliver('meeting', job['id'], content, view.to_components(), job['message_id'])
    manifest = ROOT / 'tmp' / f'm2-rinesa-1150-{day.isoformat()}.json'
    manifest.write_text(json.dumps(sent, indent=2), encoding='utf-8')
    print(json.dumps({'delivered': sent, 'only_user': 'rinesa.ahmedi'}))
    await engine.dispose()

parser = argparse.ArgumentParser()
parser.add_argument('mode', choices=['preview', 'send'])
asyncio.run(main(parser.parse_args().mode))
