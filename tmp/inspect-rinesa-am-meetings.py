"""Read-only explanation of Rinesa's AM meeting questions."""
import asyncio
import json
import sys
import uuid
from datetime import datetime, time
from pathlib import Path
from sqlalchemy import select
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.db import SessionLocal, engine
from app.models.meeting import Meeting, MeetingParticipant
from app.models.meeting_occurrence_status import MeetingOccurrenceStatus
from app.models.discord_assistant import DiscordMeetingAlert, DiscordLink
from app.services.primeflow_report import report_timezone
from app.services.meeting_occurrence import meeting_occurs_on_date
from app.services.discord_meetings import m2_occurrence

async def main():
    uid = uuid.UUID('e2e3568f-0e54-4067-be33-013c6177d47b')
    now = datetime.now(report_timezone())
    simulated = datetime.combine(now.date(), time(11, 50), report_timezone())
    async with SessionLocal() as db:
        assignments = (await db.execute(select(MeetingParticipant).where(MeetingParticipant.user_id == uid))).scalars().all()
        for assignment in assignments:
            meeting = await db.get(Meeting, assignment.meeting_id)
            if not meeting or not meeting_occurs_on_date(meeting, now.date(), local_timezone=report_timezone()):
                continue
            status = (await db.execute(select(MeetingOccurrenceStatus).where(MeetingOccurrenceStatus.meeting_id == meeting.id,
                MeetingOccurrenceStatus.occurrence_date == now.date()))).scalar_one_or_none()
            alerts = (await db.execute(select(DiscordMeetingAlert.kind, DiscordMeetingAlert.message_id).join(
                DiscordLink, DiscordLink.id == DiscordMeetingAlert.link_id).where(DiscordMeetingAlert.meeting_id == meeting.id,
                    DiscordLink.user_id == uid))).all()
            print(json.dumps({'id': str(meeting.id), 'title': meeting.title, 'type': meeting.meeting_type,
                'starts': str(meeting.starts_at.astimezone(report_timezone()) if meeting.starts_at else None),
                'ends': str(meeting.ends_at.astimezone(report_timezone()) if meeting.ends_at else None),
                'assignment_source': assignment.assignment_source, 'assigned_at': str(assignment.created_at),
                'status': status.status if status else None, 'status_checked_at': str(status.checked_at) if status else None,
                'calendar_sync_status': meeting.calendar_sync_status,
                'eligible_at_1150': m2_occurrence(meeting, simulated, report_timezone()) is not None,
                'existing_alerts': [dict(item._mapping) for item in alerts]}, ensure_ascii=True))
    await engine.dispose()
asyncio.run(main())
