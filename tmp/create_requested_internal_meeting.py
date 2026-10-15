import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from sqlalchemy import select, text
import app.models
from app.config import settings
from app.db import SessionLocal, engine
from app.models.meeting import Meeting, MeetingParticipant
from app.models.user import User
from app.services.meeting_scheduler import one_h_schedule_conflicts
from app.services.meeting_system_tasks import reconcile_tak_int_one_h_tasks_for_meeting

TITLE = 'TAK INT NEW TESTINGS/ZHV'
NAMES = ['Rinesa Ahmedi', 'Laurent Hoxha', 'Elsa Ferati', 'Endi Hyseni']

async def main():
    tz = ZoneInfo(settings.APP_TIMEZONE)
    starts_at = datetime(2026, 10, 16, 15, 0, tzinfo=tz)
    async with SessionLocal() as db:
        # Serialize this request and make retries safe.
        await db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:title))'), {'title': TITLE})
        users = (await db.execute(select(User).where(User.full_name.in_(NAMES), User.is_active.is_(True)))).scalars().all()
        assert len(users) == 4 and {u.full_name for u in users} == set(NAMES), 'Participants do not match'
        departments = {u.department_id for u in users}
        assert len(departments) == 1 and None not in departments, 'Department is ambiguous'
        department_id = next(iter(departments))
        existing = (await db.execute(select(Meeting).where(Meeting.title == TITLE))).scalars().all()
        assert len(existing) <= 1, 'Multiple existing meetings require review'
        if existing:
            meeting = existing[0]
            assert meeting.meeting_type == 'internal' and meeting.recurrence_type == 'weekly'
            assert meeting.recurrence_days_of_week == [4] and meeting.department_id == department_id
            assert meeting.starts_at.astimezone(tz).strftime('%H:%M') == '15:00'
            action = 'already_exists'
        else:
            conflicts, _ = await one_h_schedule_conflicts(
                db, participant_ids={u.id for u in users},
                starts_at=starts_at.astimezone(timezone.utc),
                ends_at=(starts_at + timedelta(minutes=30)).astimezone(timezone.utc),
            )
            if conflicts:
                print(json.dumps({'result': 'conflict', 'conflicts': [c.model_dump(mode='json') for c in conflicts]}, default=str))
                return
            meeting = Meeting(title=TITLE, meeting_type='internal', starts_at=starts_at,
                              recurrence_type='weekly', recurrence_days_of_week=[4],
                              department_id=department_id, created_by=None)
            db.add(meeting)
            await db.flush()
            for user in users:
                db.add(MeetingParticipant(meeting_id=meeting.id, user_id=user.id, assignment_source='manual', assigned_by_user_id=None))
            await db.flush()
            await reconcile_tak_int_one_h_tasks_for_meeting(db, meeting)
            action = 'created'
        participants = (await db.execute(select(MeetingParticipant.user_id).where(MeetingParticipant.meeting_id == meeting.id, MeetingParticipant.assignment_source == 'manual'))).scalars().all()
        assert set(participants) == {u.id for u in users}, 'Participant verification failed'
        meeting_id = meeting.id
        await db.commit()
    # Verify the committed data using an independent session.
    async with SessionLocal() as db:
        saved = await db.get(Meeting, meeting_id)
        names = (await db.execute(select(User.full_name).join(MeetingParticipant, MeetingParticipant.user_id == User.id).where(MeetingParticipant.meeting_id == meeting_id, MeetingParticipant.assignment_source == 'manual'))).scalars().all()
        assert set(names) == set(NAMES)
        print(json.dumps({'result': action, 'id': str(saved.id), 'title': saved.title,
                          'starts_at_local': saved.starts_at.astimezone(tz).isoformat(),
                          'recurrence_type': saved.recurrence_type,
                          'recurrence_days_of_week': saved.recurrence_days_of_week,
                          'participants': sorted(names)}, ensure_ascii=False))
    await engine.dispose()

asyncio.run(main())
