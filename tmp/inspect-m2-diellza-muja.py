"""Read-only explanation of Diellza Muja's M2 eligibility."""
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from dotenv import dotenv_values
from sqlalchemy import select, or_
root = Path(__file__).resolve().parents[1]
remote = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow\backend')
config = dotenv_values(remote / '.env')
os.environ['DISCORD_GUILD_ID'] = config['DISCORD_GUILD_ID']
sys.path.insert(0, str(root / 'backend'))
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
from app.db import SessionLocal, engine
from app.models.user import User
from app.models.discord_m2_question import DiscordM2Question
from app.models.discord_assistant import DiscordLink
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.meeting import Meeting, MeetingParticipant
from app.models.meeting_occurrence_status import MeetingOccurrenceStatus
from app.services import m2_reporting_points as reports, discord_meetings
from app.services.primeflow_report import report_timezone
from app.services.daily_realization_events import semantic_local_day

async def main():
    now = datetime.now(report_timezone())
    username = 'rinesa.ahmedi' if '--rinesa' in sys.argv else 'diellza.muja'
    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == username))).scalar_one()
        if '--delivery' in sys.argv:
            pairs = (await db.execute(select(DiscordM2Question, DiscordLink).join(DiscordLink,
                DiscordLink.id == DiscordM2Question.link_id).where(DiscordLink.user_id == user.id,
                DiscordM2Question.day == now.date()))).all()
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                for q, link in pairs:
                    item = {'kind': q.kind, 'title': q.snapshot['title'].splitlines()[0],
                        'sent_at': str(q.sent_at), 'message_id': q.message_id,
                        'answered_at': str(q.answered_at), 'choice': q.choice,
                        'platform_answered_at': str(q.platform_answered_at), 'platform_answer': q.platform_answer}
                    from app.services.discord_answer_sync import m2_payload
                    effective = await m2_payload(db, q, link)
                    item['effective_answered'] = effective.get('answered')
                    item['platform_status'] = effective.get('platform_status')
                    if q.message_id:
                        response = await client.get(f'https://discord.com/api/v10/channels/{link.channel_id}/messages/{q.message_id}',
                            headers={'Authorization': 'Bot ' + config['DISCORD_BOT_TOKEN']})
                        response.raise_for_status()
                        message = response.json()
                        item.update(verified=True, content=message['content'],
                            url=f'https://discord.com/channels/{link.guild_id}/{link.channel_id}/{q.message_id}')
                    print(json.dumps(item))
            print(json.dumps({'user': user.username, 'questions': len(pairs)}))
            await engine.dispose()
            return
        tasks = (await db.execute(select(Task).where(Task.is_active.is_(True), or_(Task.assigned_to == user.id,
            Task.id.in_(select(TaskAssignee.task_id).where(TaskAssignee.user_id == user.id)))))).scalars().all()
        for task in tasks:
            if task.status == 'DONE':
                continue
            sections = reports.select_task_sections([task], [], now.date())
            print(json.dumps({'title': task.title.splitlines()[0][:160], 'status': task.status,
                'start': str(semantic_local_day(task.start_date)), 'due': str(semantic_local_day(task.due_date)),
                'finish_period': task.finish_period, 'marker': task.one_h_marker,
                'marker_date': str(task.one_h_marker_date), 'deadline': task.is_deadline_important,
                'system': bool(task.system_template_origin_id or task.system_task_slot_id),
                'm2_sections': [key for key, rows in sections.items() if rows]}))
        due = await discord_meetings.m2_due_alerts(db, now, [user.id])
        print(json.dumps({'user': user.full_name, 'active_tasks': len(tasks), 'm2_meeting_questions_due': len(due)}))
        meetings = (await db.execute(select(Meeting).join(MeetingParticipant, MeetingParticipant.meeting_id == Meeting.id)
            .where(MeetingParticipant.user_id == user.id, MeetingParticipant.assignment_source == 'manual'))).scalars().all()
        for meeting in meetings:
            held = discord_meetings.held_question_at(meeting, now, report_timezone())
            if held:
                status = (await db.execute(select(MeetingOccurrenceStatus.status).where(MeetingOccurrenceStatus.meeting_id == meeting.id,
                    MeetingOccurrenceStatus.occurrence_date == now.date()))).scalar_one_or_none()
                print(json.dumps({'meeting': meeting.title, 'start': held[0].isoformat(), 'ends': held[1].isoformat(), 'status': status}))
    await engine.dispose()
asyncio.run(main())
