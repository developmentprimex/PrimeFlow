"""Knowledge PX: tasks of a prompt request close only after the prompt is tested.

Two kinds of tasks are protected, whatever screen or endpoint tries to set them to DONE
(department views, PX Notes, planners, daily progress, ...):

* the author's task(s): tasks created from a Prompt Note (``ga_note_origin_id`` points to a
  note with ``knowledge_type='PROMPT'``) while no prompt from that note has been tested yet;
* the tester's task ("PROMPT: TESTO: ...") while its prompt still waits for the test.

Both are closed automatically by the Knowledge PX "confirm test" action, which marks the
task objects with ``_knowledge_autoclose = True`` before completing them. Closing the
Prompt Note itself (Mbyll) lifts the lock for the author's tasks.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from app.models.ga_note import GaNote
from app.models.knowledge_prompt import KnowledgePrompt
from app.models.knowledge_kind import KNOWLEDGE_TYPES, KNOWLEDGE_ROUTES
from app.models.task import Task

KNOWLEDGE_TYPE_PROMPT = "PROMPT"
TESTED_STATUSES = ("PENDING_APPROVAL", "APPROVED")
WAITING_TEST_STATUSES = ("PENDING_TEST", "REJECTED")

AUTHOR_TASK_LOCKED = (
    "Kjo detyrë mbyllet automatikisht pasi prompti të testohet nga testuesi. "
    "Shto promptin te Knowledge PX → Prompts → Notes."
)
TEST_TASK_LOCKED = (
    "Kjo detyrë mbyllet automatikisht kur e konfirmon testimin te Knowledge PX → Prompts (butoni \"E testova\")."
)


def _status_value(value) -> str:
    return str(getattr(value, "value", value) or "")


def _becomes_done(task: Task) -> bool:
    if _status_value(task.status) != "DONE":
        return False
    history = inspect(task).attrs.status.history
    if not history.has_changes():
        return False
    return not any(_status_value(old) == "DONE" for old in (history.deleted or ()))


def locked_reason(session: Session, task: Task) -> str | None:
    """Why this task may not be completed manually right now (None = allowed)."""
    review = session.execute(
        select(KnowledgePrompt.status, KnowledgePrompt.knowledge_type).where(KnowledgePrompt.test_task_id == task.id)
    ).one_or_none()
    if review is not None and review.status in WAITING_TEST_STATUSES:
        if review.knowledge_type == "PROMPT":
            return TEST_TASK_LOCKED
        return (
            "Kjo detyrë mbyllet automatikisht kur e konfirmon kontrollin te Knowledge PX → "
            f"{KNOWLEDGE_ROUTES[review.knowledge_type].capitalize()} (butoni \"E kontrollova\")."
        )

    if task.ga_note_origin_id is None:
        return None
    note = session.execute(
        select(GaNote.knowledge_type, GaNote.status).where(GaNote.id == task.ga_note_origin_id)
    ).one_or_none()
    if note is None or note.knowledge_type not in KNOWLEDGE_TYPES:
        return None
    if _status_value(note.status) == "CLOSED":
        return None
    tested = session.execute(
        select(KnowledgePrompt.id)
        .where(KnowledgePrompt.source_note_id == task.ga_note_origin_id)
        .where(KnowledgePrompt.status.in_(TESTED_STATUSES))
        .limit(1)
    ).scalar_one_or_none()
    if tested is not None:
        return None
    if note.knowledge_type == "PROMPT":
        return AUTHOR_TASK_LOCKED
    return (
        "Kjo detyrë mbyllet automatikisht pasi materiali të kontrollohet nga kontrolluesi. "
        f"Shto materialin te Knowledge PX → {KNOWLEDGE_ROUTES[note.knowledge_type].capitalize()} → Notes."
    )


@event.listens_for(Session, "before_flush")
def _guard_prompt_tasks(session: Session, flush_context, instances) -> None:  # noqa: ARG001
    candidates = [
        obj
        for obj in session.dirty
        if isinstance(obj, Task)
        and not getattr(obj, "_knowledge_autoclose", False)
        and obj.is_active
        and _becomes_done(obj)
    ]
    if not candidates:
        return
    with session.no_autoflush:
        for task in candidates:
            reason = locked_reason(session, task)
            if reason:
                # Plain-string detail: every task screen shows string details as a toast.
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)
