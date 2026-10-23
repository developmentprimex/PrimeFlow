"""Recording tasks use the existing PX Notes/task link and editing workflow."""
import uuid
from datetime import datetime, timezone

from app.models.enums import GaNotePriority, GaNoteStatus, GaNoteType
from app.models.ga_note import GaNote
from app.services.task_marker import current_effective_marker_date, marker_is_by_ga, normalize_marker_comment
from app.services.task_strike_events import record_title_strike_events
from sqlalchemy import select


async def create_recording_note(db, action_id, fields, user, title):
    """Called inside the recording confirmation transaction; never commits."""
    note = GaNote(
        id=uuid.uuid5(uuid.NAMESPACE_URL, f"primeflow:recording-action:{action_id}"),
        content=title, created_by=user.id, note_type=GaNoteType.GA, status=GaNoteStatus.OPEN,
        priority=GaNotePriority.HIGH if getattr(fields.priority, 'value', fields.priority) == 'HIGH' else GaNotePriority.NORMAL,
        start_date=fields.start_date or datetime.now(timezone.utc), due_date=fields.due_date,
        project_id=fields.project_id, department_id=fields.department_id,
        is_converted_to_task=True, is_discussed=False, knowledge_type='RECORDING',
        one_h_marker=fields.one_h_marker,
        one_h_marker_date=current_effective_marker_date() if fields.one_h_marker else None,
        one_h_marker_by_ga=bool(fields.one_h_marker and marker_is_by_ga(user.email)),
        one_h_marker_comment=normalize_marker_comment(fields.one_h_marker, fields.one_h_marker_comment),
    )
    db.add(note)
    await db.flush()
    return note


async def sync_recording_note_from_task(db, note, task, fields, actor_id):
    """Keep recording-editor changes visible in the same PX Notes row."""
    if getattr(note, 'knowledge_type', None) != 'RECORDING':
        return
    if 'title' in fields:
        from app.models.task import Task
        note.content = task.title
        siblings = (await db.execute(select(Task).where(
            Task.ga_note_origin_id == note.id, Task.id != task.id, Task.is_active.is_(True)))).scalars().all()
        for sibling in siblings:
            record_title_strike_events(db, task_id=sibling.id, actor_user_id=actor_id,
                                      before_title=sibling.title, after_title=task.title)
            sibling.title = task.title
    for field in ('project_id', 'department_id', 'due_date', 'start_date'):
        if field in fields:
            value = getattr(task, field)
            if field != 'start_date' or value is not None:
                setattr(note, field, value)
