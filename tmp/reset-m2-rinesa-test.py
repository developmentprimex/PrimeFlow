"""Reset only the user's identified M2 trial, retaining its audit history."""
import asyncio
import json
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from sqlalchemy import select
from app.db import SessionLocal, engine
from app.models.audit_log import AuditLog
from app.models.discord_assistant import DiscordLink
from app.models.task_user_comment import TaskUserComment
from app.api.routers.discord_assistant import Actor, identity
from app.api.routers.discord_m2 import own_question, update_report_answers
from app.services import m2_reporting_points as reports
from app.services.discord_m2 import KINDS
from app.services.audit import add_audit_log

USER_ID = uuid.UUID('e2e3568f-0e54-4067-be33-013c6177d47b')
QUESTION_ID = uuid.UUID('cd2eb945-5ee1-44fe-a1b1-e16f45cd81d5')
TASK_ID = uuid.UUID('970919f4-9b05-438f-bd58-e828407d42fb')


async def main():
    async with SessionLocal() as db:
        link = (await db.execute(select(DiscordLink).where(DiscordLink.user_id == USER_ID))).scalar_one()
        # The normal identity checks bind this reset to the user's active private workspace.
        from app.config import settings
        settings.DISCORD_GUILD_ID = link.guild_id
        actor = Actor(discord_user_id=link.discord_user_id, guild_id=link.guild_id, channel_id=link.channel_id)
        question, _, user = await own_question(db, QUESTION_ID, actor)
        assert question.task_id == TASK_ID and question.kind == 'delivery' and user.id == USER_ID
        report = await reports.locked_report(db, question.day)
        task_comment = (await db.execute(select(TaskUserComment).where(TaskUserComment.task_id == TASK_ID,
            TaskUserComment.user_id == USER_ID).with_for_update())).scalar_one_or_none()
        prior = {'choice': question.choice, 'comment': question.comment, 'reason_code': question.reason_code,
                 'answered_at': question.answered_at.isoformat() if question.answered_at else None,
                 'report_choice': (report.manual_answers or {}).get(f'delivery_choice:{TASK_ID}'),
                 'report_comment': (report.manual_answers or {}).get(f'delivery:{TASK_ID}'),
                 'task_comment': task_comment.comment if task_comment else None}
        events = (await db.execute(select(AuditLog).where(AuditLog.entity_id == TASK_ID,
            AuditLog.actor_user_id == USER_ID, AuditLog.action == 'task.discord_m2_answer',
            AuditLog.after['question_id'].astext == str(QUESTION_ID)))).scalars().all()
        bodies = set()
        for event in events:
            answer = event.after or {}
            bodies.add(f'M2 {question.day:%d.%m.%Y} — {KINDS[question.kind]}\n'
                       + f'Dorëzuar: {answer["choice"]}\n' + (answer.get('comment') or ''))
        if task_comment and task_comment.comment:
            cleaned = task_comment.comment
            for body in sorted(bodies, key=len, reverse=True):
                cleaned = re.sub(r'(?:\A|\n\n)' + re.escape(body) + r'(?=\n\n|\Z)', '', cleaned)
            if cleaned.startswith('\n\n'):
                cleaned = cleaned[2:]
            task_comment.comment = cleaned or None
        question.choice = question.comment = question.reason_code = question.answered_at = None
        await db.flush()
        await update_report_answers(db, report, question)
        report.status, report.last_error = 'DRAFT', None
        report.updated_by = USER_ID
        add_audit_log(db=db, actor_user_id=USER_ID, entity_type='task', entity_id=TASK_ID,
            action='task.discord_m2_test_reset', before=prior,
            after={'question_id': str(QUESTION_ID), 'choice': None, 'comment': None,
                   'removed_trial_comment_blocks': len(bodies), 'reason': 'User requested a clean retry of the M2 trial.'})
        await db.commit()
        print(json.dumps({'question_id': str(QUESTION_ID), 'answered': False,
            'report_choice': report.manual_answers.get(f'delivery_choice:{TASK_ID}'),
            'report_comment': report.manual_answers.get(f'delivery:{TASK_ID}'),
            'task_comment': task_comment.comment if task_comment else None,
            'audit_history_preserved': True}, ensure_ascii=True))
    await engine.dispose()

asyncio.run(main())
