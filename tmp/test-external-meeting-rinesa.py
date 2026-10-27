"""Create the requested external test meeting and ask only Rinesa if it was held."""
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
ROOT = Path(__file__).resolve().parents[1]
config = dotenv_values(Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow\backend\.env'))
for key in ('JWT_SECRET', 'DISCORD_GUILD_ID', 'DISCORD_BRIDGE_SECRET', 'DISCORD_ASSISTANT_ENABLED'):
    if config.get(key):
        os.environ[key] = config[key]
sys.path.insert(0, str(ROOT / 'backend'))
from app.db import SessionLocal, engine
from app.auth.security import create_access_token
from app.models.user import User
from app.models.meeting import Meeting, MeetingParticipant
from app.models.meeting_occurrence_status import MeetingOccurrenceStatus
from app.models.discord_assistant import DiscordLink, DiscordMeetingAlert as Alert
from app.services.discord_meetings import m2_due_alerts
from app.services.primeflow_report import report_timezone
import discord_ui as ui

async def main():
    uid = uuid.UUID('e2e3568f-0e54-4067-be33-013c6177d47b')
    day = datetime.now(report_timezone()).date()
    simulated = datetime.combine(day, time(11, 50), report_timezone())
    title = f'TEST M2 — TAK EXTERN — Rinesa — {day:%d.%m.%Y}'
    async with SessionLocal() as db:
        user = await db.get(User, uid)
        assert user.username == 'rinesa.ahmedi' and user.is_active
        link = (await db.execute(select(DiscordLink).where(DiscordLink.user_id == uid, DiscordLink.enabled.is_(True)))).scalar_one()
        assert link.discord_user_id == '1493239399150915696' and link.guild_id == config['DISCORD_GUILD_ID']
        actor = {key: getattr(link, key) for key in ('discord_user_id', 'guild_id', 'channel_id')}
        token = create_access_token(user_id=user.id, role=user.role.value, department_id=user.department_id)
        department_id = str(user.department_id)
        existing = (await db.execute(select(Meeting.id).where(Meeting.title == title, Meeting.created_by == uid))).scalar_one_or_none()
    base = (config.get('PRIMEFLOW_API_BASE_URL') or 'https://api-flow.primexeu.com').rstrip('/')
    async with httpx.AsyncClient(timeout=60) as client:
        if existing:
            mid = existing
        else:
            response = await client.post(base + '/api/meetings', headers={'Authorization': 'Bearer ' + token}, json={
                'title': title, 'meeting_type': 'external', 'platform': 'TEST Discord M2',
                'starts_at': datetime.combine(day, time(7), report_timezone()).isoformat(),
                'ends_at': datetime.combine(day, time(7, 15), report_timezone()).isoformat(),
                'department_id': department_id, 'participant_ids': [str(uid)], 'create_internal_meeting': False,
                'recurrence_type': 'none'})
            if response.is_error:
                raise RuntimeError(f'Meeting create: HTTP {response.status_code}: {response.text[:300]}')
            mid = uuid.UUID(response.json()['id'])
        async with SessionLocal() as db:
            assigned = (await db.execute(select(MeetingParticipant.user_id).where(MeetingParticipant.meeting_id == mid,
                MeetingParticipant.assignment_source == 'manual'))).scalars().all()
            assert assigned == [uid], 'Test must have only Rinesa assigned'
            status = (await db.execute(select(MeetingOccurrenceStatus.status).where(MeetingOccurrenceStatus.meeting_id == mid,
                MeetingOccurrenceStatus.occurrence_date == day))).scalar_one_or_none()
            if status:
                print(json.dumps({'meeting_id': str(mid), 'already_answered': status}))
                await engine.dispose()
                return
            due = [item for item in await m2_due_alerts(db, simulated, [uid]) if item[0].id == mid]
            assert len(due) == 1
            meeting, target, occurrence, kind = due[0]
            alert = (await db.execute(select(Alert).where(Alert.meeting_id == mid, Alert.link_id == link.id,
                Alert.occurrence_starts_at == occurrence, Alert.kind == kind))).scalar_one_or_none()
            if not alert:
                alert = Alert(meeting_id=mid, link_id=link.id, occurrence_starts_at=occurrence, kind=kind,
                    lease_until=datetime.now(timezone.utc) + timedelta(minutes=2))
                db.add(alert)
                await db.flush()
            job = {'id': str(alert.id), 'kind': kind, **actor, 'meeting': {'id': str(mid), 'title': title,
                'type': 'external', 'platform': meeting.platform, 'starts_at': occurrence.isoformat()}}
            prior_message = alert.message_id
            await db.commit()
        content, embed, view = ui.meeting_alert(job)
        if prior_message:
            message_id = prior_message
        else:
            response = await client.post(f"https://discord.com/api/v10/channels/{actor['channel_id']}/messages",
                headers={'Authorization': 'Bot ' + config['DISCORD_BOT_TOKEN']}, json={
                    'content': '**TEST M2 · sikur sot ora 11:50**\n' + content,
                    'embeds': [embed.to_dict()], 'components': view.to_components(),
                    'allowed_mentions': {'parse': [], 'users': [actor['discord_user_id']]},
                    'nonce': hashlib.sha256(f"meeting:{job['id']}".encode()).hexdigest()[:24], 'enforce_nonce': True})
            if response.is_error:
                raise RuntimeError(f'Discord question: HTTP {response.status_code}')
            message_id = response.json()['id']
            response = await client.post(base + f"/api/discord/bot/meetings/{job['id']}/ack",
                headers={'X-Primeflow-Discord-Secret': config['DISCORD_BRIDGE_SECRET']}, json={**actor, 'message_id': message_id})
            if response.is_error:
                raise RuntimeError(f'Meeting ACK: HTTP {response.status_code}')
        result = {'meeting_id': str(mid), 'title': title, 'only_assignee': 'Rinesa Ahmedi', 'question_id': job['id'],
            'message_id': message_id, 'url': f"https://discord.com/channels/{actor['guild_id']}/{actor['channel_id']}/{message_id}"}
        (ROOT / 'tmp' / f'meeting-rinesa-test-{day.isoformat()}.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=True))
    await engine.dispose()

asyncio.run(main())
