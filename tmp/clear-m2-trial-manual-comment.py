"""Remove only the Discord-generated value from the highlighted manual field."""
import asyncio
import json
import sys
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from sqlalchemy import select
from app.db import SessionLocal, engine
from app.models.discord_m2_question import DiscordM2Question
from app.models.m2_reporting_points import M2ReportingPointsReport
from app.models.user import User
from app.models.task_daily_rlz_state import TaskDailyRlzState
from app.services.m2_reporting_points import locked_report
from app.services.audit import add_audit_log


async def main():
    manifest = json.loads((Path(__file__).parent / 'm2-postponement-rinesa-test.json').read_text(encoding='utf-8'))
    user_id = uuid.UUID('e2e3568f-0e54-4067-be33-013c6177d47b')
    async with SessionLocal() as db:
        question = await db.get(DiscordM2Question, uuid.UUID(manifest['question_id']))
        user = await db.get(User, user_id)
        assert question.task_id == uuid.UUID(manifest['task_id']) and question.kind == 'postponed'
        report = await locked_report(db, question.day)
        key = f'postponed_comment:{question.task_id}'
        answers = dict(report.manual_answers or {})
        before = answers.get(key)
        expected = f'{user.full_name or user.username}: {question.comment}'
        if before and before != expected:
            raise RuntimeError('Manual text differs from the generated Discord answer; refusing to erase it.')
        answers.pop(key, None)
        report.manual_answers, report.updated_by = answers, user_id
        add_audit_log(db=db, actor_user_id=user_id, entity_type='m2_reporting_points', entity_id=report.id,
            action='REMOVE_DISCORD_MANUAL_COMMENT', before={key: before},
            after={key: '', 'question_id': str(question.id), 'reason': 'User requested Discord replies only in the ordinary comment column.'})
        await db.commit()
        state = (await db.execute(select(TaskDailyRlzState).where(TaskDailyRlzState.task_id == question.task_id,
            TaskDailyRlzState.user_id == user_id, TaskDailyRlzState.day_date == question.day))).scalar_one()
        print(json.dumps({'task_id': str(question.task_id), 'manual_comment': '',
            'ordinary_comment': state.comment, 'reason_code': state.reason_code}, ensure_ascii=True))
    await engine.dispose()

asyncio.run(main())
