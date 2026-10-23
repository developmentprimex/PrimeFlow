"""Idempotent backfill: link existing recording tasks to ordinary PX Notes."""
import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from sqlalchemy import select
from app.db import SessionLocal, engine
from app.models.meeting_recording import MeetingRecording
from app.models.recording_analysis import RecordingAction
from app.models.task import Task
from app.models.user import User
from app.services.audit import add_audit_log
from app.services.recording_task_notes import create_recording_note


async def main():
    async with SessionLocal() as db:
        query = (select(RecordingAction, Task, MeetingRecording.title)
                 .join(Task, Task.id == RecordingAction.created_task_id)
                 .join(MeetingRecording, MeetingRecording.id == RecordingAction.recording_id)
                 .where(Task.is_active.is_(True), MeetingRecording.deleted_at.is_(None))
                 .order_by(RecordingAction.id))
        rows = list((await db.execute(query.with_for_update() if '--apply' in sys.argv else query)).all())
        for action, task, recording_title in rows:
            if task.ga_note_origin_id:
                print(json.dumps({'task_id': str(task.id), 'note_id': str(task.ga_note_origin_id), 'already_linked': True}))
                continue
            if task.plan_note_origin_id:
                raise RuntimeError('Existing plan-note origin must not be replaced')
            copies = [task]
            if task.fast_task_group_id:
                copies = list((await db.execute(select(Task).where(Task.fast_task_group_id == task.fast_task_group_id)
                                                .order_by(Task.id).with_for_update())).scalars())
                if any(copy.ga_note_origin_id or copy.plan_note_origin_id for copy in copies):
                    raise RuntimeError('Group has an existing note origin; manual reconciliation required')
            result = {'recording': recording_title, 'task_id': str(task.id), 'title': task.title.split('\n')[0],
                      'status': getattr(task.status, 'value', task.status), 'copies': len(copies), 'apply': '--apply' in sys.argv}
            if '--apply' in sys.argv:
                actor = await db.get(User, action.confirmed_by or task.created_by)
                if actor is None:
                    raise RuntimeError('Task creator was not found')
                note = await create_recording_note(db, action.id, task, actor, task.title)
                for copy in copies:
                    copy.ga_note_origin_id = note.id
                    copy.fast_task_group_id = None
                    add_audit_log(db=db, actor_user_id=actor.id, entity_type='task', entity_id=copy.id,
                                  action='recording_px_note_linked', after={'ga_note_origin_id': str(note.id),
                                  'recording_id': str(action.recording_id), 'action_id': str(action.id)})
                result['note_id'] = str(note.id)
            print(json.dumps(result, ensure_ascii=True))
        if '--apply' in sys.argv:
            await db.commit()
    await engine.dispose()

asyncio.run(main())
