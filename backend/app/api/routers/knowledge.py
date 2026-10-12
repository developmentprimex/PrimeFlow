"""Knowledge PX libraries and notes for prompts, definitions and regulations.

Prompt notes are regular PX Notes (``ga_notes``) tagged with ``knowledge_type='PROMPT'``,
so they show up in PX Notes automatically and can be turned into tasks with the
existing ``POST /tasks`` flow (``ga_note_origin_id``).

When the task is done, the assignee adds the prompt (text and/or file). A prompt then
needs two other people: one who tests it, and a manager/admin who approves it into the
Prompt Library.
"""

from __future__ import annotations

import mimetypes
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import ensure_department_access
from app.api.deps import get_current_user
from app.config import settings
from app.db import get_db
from app.models.enums import GaNotePriority, GaNoteStatus, GaNoteType, UserRole
from app.models.ga_note import GaNote
from app.models.knowledge_prompt import KnowledgePrompt
from app.models.knowledge_kind import KnowledgeType, KNOWLEDGE_TYPES, KNOWLEDGE_ROUTES, author_task_title, review_task_title
from app.models.task import Task
from app.models.user import User
from app.schemas.knowledge import (
    KnowledgePromptBrief,
    KnowledgePromptOut,
    KnowledgeUserRef,
    PromptNoteCreate,
    PromptNoteOut,
    PromptNoteTaskOut,
    PromptNoteUpdate,
    PromptReviewAction,
)

router = APIRouter()

KNOWLEDGE_TYPE_PROMPT = "PROMPT"

STATUS_PENDING_TEST = "PENDING_TEST"
STATUS_PENDING_APPROVAL = "PENDING_APPROVAL"
STATUS_APPROVED = "APPROVED"
STATUS_REJECTED = "REJECTED"
PROMPT_STATUSES = {STATUS_PENDING_TEST, STATUS_PENDING_APPROVAL, STATUS_APPROVED, STATUS_REJECTED}

TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".json", ".yaml", ".yml", ".prompt", ".xml", ".csv"}
PROMPT_SERVER_EXTENSIONS = {".txt", ".md", ".markdown", ".prompt"}
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *{f"COM{i}" for i in range(1, 10)},
    *{f"LPT{i}" for i in range(1, 10)},
}
MAX_KEYWORDS = 30


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_manager(user: User) -> bool:
    return user.role in (UserRole.ADMIN, UserRole.MANAGER)


def _upload_base_dir() -> Path:
    base = Path(settings.GA_NOTES_UPLOAD_DIR).parent / "knowledge-prompts"
    if not base.is_absolute():
        base = Path(__file__).resolve().parents[3] / base
    return base


def _prompt_filename(title: str) -> str:
    """Return a Windows-safe filename for a prompt saved into a directory."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", title).strip().rstrip(". ")
    if name.upper() in WINDOWS_RESERVED_NAMES:
        name = f"_{name}"
    return f"{(name or 'prompt')[:240]}.txt"


def _resolve_files_server_path(raw_path: str) -> str:
    """Translate mapped/client paths to the Files PX path on the server."""
    requested = raw_path.strip().strip('"').replace("/", "\\")
    storage_root = settings.FILES_SERVER_STORAGE_ROOT.strip().rstrip("\\/")
    aliases = [value.strip().rstrip("\\/") for value in settings.FILES_SERVER_PATH_ALIASES.split(";")]
    for alias in (value for value in aliases if value):
        requested_key = requested.casefold()
        alias_key = alias.casefold()
        if requested_key == alias_key or requested_key.startswith(f"{alias_key}\\"):
            relative = requested[len(alias) :].lstrip("\\/")
            return f"{storage_root}\\{relative}" if relative else storage_root
    return requested


def _canonical_files_path(raw_path: str) -> Path:
    return Path(_resolve_files_server_path(raw_path)).resolve(strict=False)


def _require_path_inside_files_storage(target: Path) -> Path:
    storage_root = Path(settings.FILES_SERVER_STORAGE_ROOT).resolve(strict=False)
    resolved_target = target.resolve(strict=False)
    try:
        resolved_target.relative_to(storage_root)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Promptet mund të ruhen vetëm brenda Files PX (F:\\FILES).",
        )
    return resolved_target


def _save_prompt_text_to_server(
    raw_path: str,
    title: str,
    content: str,
    *,
    existing_path: str | None = None,
) -> str:
    """Write only the prompt body to an absolute server path and return that path.

    A path to an existing directory creates ``<prompt title>.txt`` inside it. A
    path without an extension gets ``.txt`` appended. Existing files are
    replaced atomically so readers never see a partially written prompt.
    """
    requested = _resolve_files_server_path(raw_path)
    if not requested:
        return ""
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Shkruaj tekstin e promptit para se ta ruash n\u00eb server.",
        )

    target = Path(requested)
    if not target.is_absolute():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path-i i serverit duhet t\u00eb jet\u00eb absolut, p.sh. F:\\FILES\\Prompts\\prompt.txt.",
        )
    if target.exists() and target.is_dir():
        target = target / _prompt_filename(title)
    elif not target.suffix:
        target = target.with_suffix(".txt")

    target = _require_path_inside_files_storage(target)

    if target.suffix.lower() not in PROMPT_SERVER_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Skedari i promptit n\u00eb server duhet t\u00eb jet\u00eb .txt, .md ose .prompt.",
        )
    if target.stem.upper() in WINDOWS_RESERVED_NAMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Emri i skedarit nuk lejohet n\u00eb Windows.",
        )
    if not target.parent.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Folderi nuk ekziston n\u00eb server: {target.parent}",
        )

    if target.exists():
        can_edit_existing = bool(existing_path) and target == _canonical_files_path(existing_path or "")
        if not can_edit_existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Skedari ekziston tashmë dhe nuk i përket këtij prompti: {target}. "
                    "Zgjidh një folder tjetër ose ndrysho titullin e promptit."
                ),
            )

    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        temporary.replace(target)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Prompti nuk mund t\u00eb ruhej n\u00eb server te {target}: {exc}",
        ) from exc
    return str(target)


def parse_keywords(raw: str | list[str] | None) -> list[str]:
    """Split on comma/semicolon/newline/#, trim, de-duplicate case-insensitively."""
    if raw is None:
        return []
    parts = raw if isinstance(raw, list) else re.split(r"[,;\n#]+", raw)
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        word = re.sub(r"\s+", " ", str(part)).strip()
        if not word:
            continue
        word = word[:100]
        key = word.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(word)
        if len(out) >= MAX_KEYWORDS:
            break
    return out


async def _user_map(db: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, KnowledgeUserRef]:
    clean = {i for i in ids if i is not None}
    if not clean:
        return {}
    rows = (await db.execute(select(User.id, User.full_name).where(User.id.in_(clean)))).all()
    return {row.id: KnowledgeUserRef(id=row.id, full_name=row.full_name) for row in rows}


def _prompt_user_ids(prompt: KnowledgePrompt) -> set[uuid.UUID | None]:
    return {prompt.created_by, prompt.tester_id, prompt.tested_by, prompt.approved_by, prompt.rejected_by}


def _status_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


async def _task_status_map(db: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    clean = {i for i in ids if i is not None}
    if not clean:
        return {}
    rows = (await db.execute(select(Task.id, Task.status, Task.is_active).where(Task.id.in_(clean)))).all()
    return {row.id: _status_value(row.status) for row in rows if row.is_active}


def _prompt_out(
    prompt: KnowledgePrompt,
    users: dict[uuid.UUID, KnowledgeUserRef],
    task_statuses: dict[uuid.UUID, str] | None = None,
) -> KnowledgePromptOut:
    ref = lambda uid: users.get(uid) if uid else None  # noqa: E731
    return KnowledgePromptOut(
        id=prompt.id,
        knowledge_type=prompt.knowledge_type,
        title=prompt.title,
        content=prompt.content or "",
        keywords=list(prompt.keywords or []),
        files_path=prompt.files_path,
        source_note_id=prompt.source_note_id,
        status=prompt.status,
        created_by=ref(prompt.created_by),
        tester=ref(prompt.tester_id),
        test_task_id=prompt.test_task_id,
        test_task_status=(task_statuses or {}).get(prompt.test_task_id) if prompt.test_task_id else None,
        tested_by=ref(prompt.tested_by),
        tested_at=prompt.tested_at,
        test_comment=prompt.test_comment,
        approved_by=ref(prompt.approved_by),
        approved_at=prompt.approved_at,
        rejected_by=ref(prompt.rejected_by),
        rejected_at=prompt.rejected_at,
        rejection_reason=prompt.rejection_reason,
        file_original_name=prompt.file_original_name,
        file_content_type=prompt.file_content_type,
        file_size=prompt.file_size,
        created_at=prompt.created_at,
        updated_at=prompt.updated_at,
    )


async def _single_prompt_out(db: AsyncSession, prompt: KnowledgePrompt) -> KnowledgePromptOut:
    await db.refresh(prompt)
    return _prompt_out(
        prompt,
        await _user_map(db, _prompt_user_ids(prompt)),
        await _task_status_map(db, {prompt.test_task_id}),
    )


# ---------------------------------------------------------------------------
# Tester + "PROMPT: TESTO: ..." task
# ---------------------------------------------------------------------------


def test_task_title(prompt_title: str, knowledge_type: str = "PROMPT") -> str:
    return review_task_title(prompt_title, knowledge_type)


def creator_task_title(prompt_title: str, knowledge_type: str = "PROMPT") -> str:
    return author_task_title(prompt_title, knowledge_type)


PROMPT_LINK_MARKER = "/knowledge/prompts?prompt="


def prompt_link(request: Request | None, prompt_id: uuid.UUID, knowledge_type: str = "PROMPT") -> str:
    """Link to the full prompt in Knowledge PX; the task description holds only this link."""
    origin = (request.headers.get("origin") if request is not None else None) or settings.FRONTEND_URL
    return f"{origin.rstrip('/')}/knowledge/{KNOWLEDGE_ROUTES[knowledge_type]}?prompt={prompt_id}"


async def _sync_creator_tasks(db: AsyncSession, prompt: KnowledgePrompt, link: str) -> None:
    """The prompt creator's task(s) from the Prompt Note: title "PROMPT: <title>",
    description = link to the full prompt (never the prompt text itself)."""
    if prompt.source_note_id is None:
        return
    tasks = (
        await db.execute(
            select(Task)
            .where(Task.ga_note_origin_id == prompt.source_note_id)
            .where(Task.is_active.is_(True))
        )
    ).scalars().all()
    changed = False
    for task in tasks:
        title = creator_task_title(prompt.title, prompt.knowledge_type)
        if task.title != title:
            task.title = title
            changed = True
        if task.description != link:
            task.description = link
            changed = True
    if changed:
        await db.commit()


async def _validate_tester(db: AsyncSession, tester_id: uuid.UUID, author_id: uuid.UUID | None, knowledge_type: str = "PROMPT") -> User:
    reviewer = "Testuesi" if knowledge_type == "PROMPT" else "Kontrolluesi"
    tester = (await db.execute(select(User).where(User.id == tester_id))).scalar_one_or_none()
    if tester is None or not tester.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{reviewer} nuk u gjet")
    if author_id is not None and tester.id == author_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{reviewer} duhet të jetë person tjetër nga autori",
        )
    return tester


async def _create_test_task(
    db: AsyncSession, prompt: KnowledgePrompt, tester: User, actor: User, link: str
) -> uuid.UUID | None:
    """Create the tester's task through the regular task endpoint logic (baselines, assignees, notifications)."""
    from app.api.routers.tasks import create_task  # local import: avoid import cycle at module load
    from app.schemas.task import TaskCreate

    description = link  # only the link to the full prompt, not the prompt text
    try:
        out = await create_task(
            payload=TaskCreate(
                title=test_task_title(prompt.title, prompt.knowledge_type),
                description=description,
                status="TODO",
                priority="NORMAL",
                department_id=tester.department_id,
                assigned_to=tester.id,
                assignees=[tester.id],
            ),
            db=db,
            user=actor,
        )
    except HTTPException:
        await db.rollback()
        return None
    return out.id


async def _deactivate_test_task(db: AsyncSession, task_id: uuid.UUID | None) -> None:
    if task_id is None:
        return
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if task is not None and _status_value(task.status) != "DONE":
        task.is_active = False


async def _complete_test_task(db: AsyncSession, prompt: KnowledgePrompt, tester: User, comment: str) -> None:
    """Close the tester's task: the test comment doubles as the RLZ result comment."""
    if prompt.test_task_id is None:
        return
    from app.api.routers.tasks import update_task  # local import: avoid import cycle at module load
    from app.models.task_user_comment import TaskUserComment
    from app.schemas.task import TaskUpdate

    task = (await db.execute(select(Task).where(Task.id == prompt.test_task_id))).scalar_one_or_none()
    if task is None or not task.is_active or _status_value(task.status) == "DONE":
        return
    existing = (
        await db.execute(
            select(TaskUserComment).where(TaskUserComment.task_id == task.id, TaskUserComment.user_id == tester.id)
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(TaskUserComment(task_id=task.id, user_id=tester.id, comment=comment))
    elif not (existing.comment or "").strip():
        existing.comment = comment
    await db.commit()
    task._knowledge_autoclose = True  # allowed through the Knowledge PX task guard
    try:
        await update_task(task_id=task.id, payload=TaskUpdate(status="DONE"), db=db, user=tester)
    except HTTPException:
        await db.rollback()


async def _complete_author_tasks(db: AsyncSession, prompt: KnowledgePrompt, tester: User) -> None:
    """Close the prompt author's task(s) from the Prompt Note once the prompt is tested,
    exactly as if the assignee had set them to DONE in the department view / PX Notes."""
    if prompt.source_note_id is None:
        return
    from app.api.routers.tasks import update_task  # local import: avoid import cycle at module load
    from app.schemas.task import TaskUpdate

    tasks = (
        await db.execute(
            select(Task)
            .where(Task.ga_note_origin_id == prompt.source_note_id)
            .where(Task.is_active.is_(True))
        )
    ).scalars().all()
    for task in tasks:
        if _status_value(task.status) == "DONE":
            continue
        actor = None
        if task.assigned_to is not None:
            actor = (await db.execute(select(User).where(User.id == task.assigned_to))).scalar_one_or_none()
        task._knowledge_autoclose = True  # allowed through the Knowledge PX task guard
        try:
            await update_task(task_id=task.id, payload=TaskUpdate(status="DONE"), db=db, user=actor or tester)
        except HTTPException:
            await db.rollback()


async def _get_prompt_or_404(db: AsyncSession, prompt_id: uuid.UUID) -> KnowledgePrompt:
    prompt = (
        await db.execute(select(KnowledgePrompt).where(KnowledgePrompt.id == prompt_id))
    ).scalar_one_or_none()
    if prompt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompti nuk u gjet")
    return prompt


async def _get_prompt_note_or_404(db: AsyncSession, note_id: uuid.UUID) -> GaNote:
    note = (await db.execute(select(GaNote).where(GaNote.id == note_id))).scalar_one_or_none()
    if note is None or note.knowledge_type not in KNOWLEDGE_TYPES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shënimi i promptit nuk u gjet")
    return note


def _reset_review(prompt: KnowledgePrompt) -> None:
    prompt.status = STATUS_PENDING_TEST
    prompt.tested_by = None
    prompt.tested_at = None
    prompt.test_comment = None
    prompt.approved_by = None
    prompt.approved_at = None
    prompt.rejected_by = None
    prompt.rejected_at = None
    prompt.rejection_reason = None


async def _store_upload(prompt: KnowledgePrompt, upload: UploadFile) -> tuple[Path, bytes | None]:
    """Save the uploaded file; return its path and the raw bytes when it is a small text file."""
    max_bytes = settings.GA_NOTES_MAX_FILE_MB * 1024 * 1024
    original_name = (upload.filename or "prompt.txt").strip()[:255] or "prompt.txt"
    extension = Path(original_name).suffix.lower()
    stored_name = f"{uuid.uuid4()}{extension}"
    target_dir = _upload_base_dir() / str(prompt.id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / stored_name

    size = 0
    text_buffer = bytearray() if extension in TEXT_EXTENSIONS else None
    with target.open("wb") as fh:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                fh.close()
                target.unlink(missing_ok=True)
                await upload.close()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Skedari është shumë i madh. Maksimumi {settings.GA_NOTES_MAX_FILE_MB}MB.",
                )
            fh.write(chunk)
            if text_buffer is not None:
                text_buffer.extend(chunk)
    await upload.close()

    old_stored = prompt.file_stored_name
    prompt.file_original_name = original_name
    prompt.file_stored_name = stored_name
    prompt.file_content_type = upload.content_type or mimetypes.guess_type(original_name)[0]
    prompt.file_size = size
    if old_stored and old_stored != stored_name:
        (target_dir / old_stored).unlink(missing_ok=True)
    return target, bytes(text_buffer) if text_buffer is not None else None


def _decode_text(raw: bytes | None) -> str:
    if not raw:
        return ""
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return raw.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return ""


# ---------------------------------------------------------------------------
# Prompt notes
# ---------------------------------------------------------------------------


@router.get("/prompt-notes", response_model=list[PromptNoteOut])
async def list_prompt_notes(
    knowledge_type: KnowledgeType = "PROMPT",
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[PromptNoteOut]:
    notes = (
        await db.execute(
            select(GaNote)
            .where(GaNote.knowledge_type == knowledge_type)
            .order_by(GaNote.created_at.desc())
        )
    ).scalars().all()
    note_ids = [n.id for n in notes]

    tasks: list[Task] = []
    prompts: list[KnowledgePrompt] = []
    if note_ids:
        tasks = (
            await db.execute(
                select(Task)
                .where(Task.ga_note_origin_id.in_(note_ids))
                .where(Task.is_active.is_(True))
                .order_by(Task.created_at.asc())
            )
        ).scalars().all()
        prompts = (
            await db.execute(
                select(KnowledgePrompt)
                .where(KnowledgePrompt.source_note_id.in_(note_ids))
                .order_by(KnowledgePrompt.created_at.asc())
            )
        ).scalars().all()

    users = await _user_map(
        db,
        {n.created_by for n in notes}
        | {n.knowledge_tester_id for n in notes}
        | {t.assigned_to for t in tasks}
        | {p.tester_id for p in prompts}
        | {p.created_by for p in prompts}
        | {p.tested_by for p in prompts},
    )
    test_statuses = await _task_status_map(db, {p.test_task_id for p in prompts})

    tasks_by_note: dict[uuid.UUID, list[PromptNoteTaskOut]] = {}
    for task in tasks:
        tasks_by_note.setdefault(task.ga_note_origin_id, []).append(
            PromptNoteTaskOut(
                id=task.id,
                title=task.title,
                status=task.status.value if hasattr(task.status, "value") else str(task.status),
                assignee=users.get(task.assigned_to) if task.assigned_to else None,
                due_date=task.due_date,
                completed_at=task.completed_at,
            )
        )
    prompts_by_note: dict[uuid.UUID, list[KnowledgePromptBrief]] = {}
    for prompt in prompts:
        prompts_by_note.setdefault(prompt.source_note_id, []).append(
            KnowledgePromptBrief(
                id=prompt.id,
                knowledge_type=prompt.knowledge_type,
                title=prompt.title,
                status=prompt.status,
                created_by=users.get(prompt.created_by) if prompt.created_by else None,
                tested_by=users.get(prompt.tested_by) if prompt.tested_by else None,
                tested_at=prompt.tested_at,
                tester=users.get(prompt.tester_id) if prompt.tester_id else None,
                test_task_status=test_statuses.get(prompt.test_task_id) if prompt.test_task_id else None,
            )
        )

    return [
        PromptNoteOut(
            id=note.id,
            knowledge_type=note.knowledge_type,
            content=note.content,
            status=note.status.value,
            priority=note.priority.value if note.priority else None,
            department_id=note.department_id,
            is_converted_to_task=note.is_converted_to_task,
            created_by=users.get(note.created_by) if note.created_by else None,
            created_at=note.created_at,
            updated_at=note.updated_at,
            completed_at=note.completed_at,
            tasks=tasks_by_note.get(note.id, []),
            prompts=prompts_by_note.get(note.id, []),
            tester=users.get(note.knowledge_tester_id) if note.knowledge_tester_id else None,
        )
        for note in notes
    ]


@router.post("/prompt-notes", response_model=PromptNoteOut, status_code=status.HTTP_201_CREATED)
async def create_prompt_note(
    payload: PromptNoteCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> PromptNoteOut:
    department_id = payload.department_id or user.department_id
    if department_id is None and not _is_manager(user):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Zgjidh departamentin")
    if department_id is not None and payload.department_id is not None:
        ensure_department_access(user, department_id)

    note = GaNote(
        content=payload.content.strip(),
        created_by=user.id,
        note_type=GaNoteType.GA,
        status=GaNoteStatus.OPEN,
        priority=GaNotePriority(payload.priority) if payload.priority else None,
        department_id=department_id,
        knowledge_type=payload.knowledge_type,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return PromptNoteOut(
        id=note.id,
        knowledge_type=note.knowledge_type,
        content=note.content,
        status=note.status.value,
        priority=note.priority.value if note.priority else None,
        department_id=note.department_id,
        is_converted_to_task=note.is_converted_to_task,
        created_by=KnowledgeUserRef(id=user.id, full_name=user.full_name),
        created_at=note.created_at,
        updated_at=note.updated_at,
        completed_at=note.completed_at,
    )


@router.patch("/prompt-notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def update_prompt_note(
    note_id: uuid.UUID,
    payload: PromptNoteUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> None:
    note = await _get_prompt_note_or_404(db, note_id)
    changes_note = payload.content is not None or payload.status is not None
    if changes_note and note.created_by != user.id and not _is_manager(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Vetëm autori ose menaxheri")
    if payload.tester_id is not None:
        reviewer = "Testuesi" if note.knowledge_type == "PROMPT" else "Kontrolluesi"
        # Anyone who creates the task may choose the tester (same openness as PX Notes).
        tester = (await db.execute(select(User).where(User.id == payload.tester_id))).scalar_one_or_none()
        if tester is None or not tester.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{reviewer} nuk u gjet")
        assignee_ids = set(
            (
                await db.execute(
                    select(Task.assigned_to)
                    .where(Task.ga_note_origin_id == note.id)
                    .where(Task.is_active.is_(True))
                )
            ).scalars().all()
        )
        if tester.id in assignee_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{reviewer} duhet të jetë person tjetër nga ai që e krijon materialin",
            )
        note.knowledge_tester_id = tester.id
    if payload.content is not None:
        note.content = payload.content.strip()
    if payload.status is not None:
        note.status = GaNoteStatus(payload.status)
        note.completed_at = _now() if note.status == GaNoteStatus.CLOSED else None
    await db.commit()


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


@router.get("/prompts", response_model=list[KnowledgePromptOut])
async def list_prompts(
    status_filter: str | None = None,
    knowledge_type: KnowledgeType = "PROMPT",
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[KnowledgePromptOut]:
    stmt = select(KnowledgePrompt).where(KnowledgePrompt.knowledge_type == knowledge_type).order_by(KnowledgePrompt.updated_at.desc())
    if status_filter:
        wanted = {s.strip().upper() for s in status_filter.split(",") if s.strip()}
        unknown = wanted - PROMPT_STATUSES
        if unknown:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Status i panjohur")
        stmt = stmt.where(KnowledgePrompt.status.in_(wanted))
    prompts = (await db.execute(stmt)).scalars().all()
    ids: set[uuid.UUID | None] = set()
    for prompt in prompts:
        ids |= _prompt_user_ids(prompt)
    users = await _user_map(db, ids)
    task_statuses = await _task_status_map(db, {p.test_task_id for p in prompts})
    return [_prompt_out(p, users, task_statuses) for p in prompts]


@router.get("/prompts/{prompt_id}", response_model=KnowledgePromptOut)
async def get_prompt(
    prompt_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> KnowledgePromptOut:
    return await _single_prompt_out(db, await _get_prompt_or_404(db, prompt_id))


@router.post("/prompts", response_model=KnowledgePromptOut, status_code=status.HTTP_201_CREATED)
async def create_prompt(
    request: Request,
    title: str = Form(...),
    knowledge_type: KnowledgeType = Form("PROMPT"),
    content: str = Form(""),
    keywords: str = Form(""),
    files_path: str = Form(""),
    source_note_id: uuid.UUID | None = Form(None),
    tester_id: uuid.UUID | None = Form(None),
    file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> KnowledgePromptOut:
    title = title.strip()
    if len(title) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Titulli i promptit mungon")
    source_note: GaNote | None = None
    if source_note_id is not None:
        source_note = await _get_prompt_note_or_404(db, source_note_id)
        if source_note.knowledge_type != knowledge_type:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Kategoria e kërkesës nuk përputhet")
    if tester_id is None and source_note is not None:
        tester_id = source_note.knowledge_tester_id
    if tester_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Zgjidh personin për testim ose kontroll")
    tester = await _validate_tester(db, tester_id, user.id, knowledge_type)
    if source_note is not None and source_note.knowledge_tester_id != tester.id:
        source_note.knowledge_tester_id = tester.id

    prompt = KnowledgePrompt(
        id=uuid.uuid4(),
        knowledge_type=knowledge_type,
        title=title[:300],
        content=content.strip(),
        keywords=parse_keywords(keywords),
        files_path=files_path.strip()[:1000] or None,
        source_note_id=source_note_id,
        status=STATUS_PENDING_TEST,
        created_by=user.id,
        tester_id=tester.id,
    )
    stored_path: Path | None = None
    if file is not None and (file.filename or "").strip():
        stored_path, raw_text = await _store_upload(prompt, file)
        if not prompt.content:
            prompt.content = _decode_text(raw_text)
    if not prompt.content and not prompt.file_stored_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Shto tekstin e promptit ose ngarko një skedar",
        )
    if prompt.files_path:
        try:
            prompt.files_path = _save_prompt_text_to_server(prompt.files_path, prompt.title, prompt.content)
        except HTTPException:
            if stored_path is not None:
                stored_path.unlink(missing_ok=True)
            raise
    db.add(prompt)
    try:
        await db.commit()
    except Exception:
        if stored_path is not None:
            stored_path.unlink(missing_ok=True)
        raise

    prompt_id = prompt.id
    link = prompt_link(request, prompt_id, prompt.knowledge_type)
    await _sync_creator_tasks(db, prompt, link)
    prompt = await _get_prompt_or_404(db, prompt_id)
    task_id = await _create_test_task(db, prompt, tester, user, link)
    prompt = await _get_prompt_or_404(db, prompt_id)
    if task_id is not None:
        prompt.test_task_id = task_id
        await db.commit()
    return await _single_prompt_out(db, prompt)


@router.patch("/prompts/{prompt_id}", response_model=KnowledgePromptOut)
async def update_prompt(
    request: Request,
    prompt_id: uuid.UUID,
    title: str | None = Form(None),
    content: str | None = Form(None),
    keywords: str | None = Form(None),
    files_path: str | None = Form(None),
    tester_id: uuid.UUID | None = Form(None),
    remove_file: bool = Form(False),
    file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> KnowledgePromptOut:
    prompt = await _get_prompt_or_404(db, prompt_id)
    original_files_path = prompt.files_path
    is_author = prompt.created_by == user.id
    if not _is_manager(user) and not (is_author and prompt.status != STATUS_APPROVED):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vetëm autori (para aprovimit) ose menaxheri mund ta ndryshojë promptin",
        )

    if title is not None:
        if len(title.strip()) < 2:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Titulli i promptit mungon")
        prompt.title = title.strip()[:300]
    if content is not None:
        prompt.content = content.strip()
    if keywords is not None:
        prompt.keywords = parse_keywords(keywords)
    if files_path is not None:
        prompt.files_path = files_path.strip()[:1000] or None
    if remove_file and prompt.file_stored_name:
        (_upload_base_dir() / str(prompt.id) / prompt.file_stored_name).unlink(missing_ok=True)
        prompt.file_original_name = None
        prompt.file_stored_name = None
        prompt.file_content_type = None
        prompt.file_size = None
    if file is not None and (file.filename or "").strip():
        _, raw_text = await _store_upload(prompt, file)
        if not prompt.content:
            prompt.content = _decode_text(raw_text)
    if not prompt.content and not prompt.file_stored_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Shto tekstin e promptit ose ngarko një skedar",
        )

    new_tester: User | None = None
    if tester_id is not None and tester_id != prompt.tester_id and prompt.status != STATUS_APPROVED:
        new_tester = await _validate_tester(db, tester_id, prompt.created_by, prompt.knowledge_type)
        await _deactivate_test_task(db, prompt.test_task_id)
        prompt.tester_id = new_tester.id
        prompt.test_task_id = None

    # Any change to a prompt that is not yet in the library restarts the review.
    if prompt.status != STATUS_APPROVED:
        _reset_review(prompt)
    if prompt.files_path:
        prompt.files_path = _save_prompt_text_to_server(
            prompt.files_path,
            prompt.title,
            prompt.content,
            existing_path=original_files_path,
        )
    await db.commit()

    link = prompt_link(request, prompt.id, prompt.knowledge_type)
    prompt_id = prompt.id
    await _sync_creator_tasks(db, prompt, link)
    prompt = await _get_prompt_or_404(db, prompt_id)

    # Make sure the (new) tester has an open "PROMPT: TESTO" task.
    if prompt.status == STATUS_PENDING_TEST and prompt.tester_id is not None:
        needs_task = prompt.test_task_id is None
        if not needs_task:
            current = (await db.execute(select(Task).where(Task.id == prompt.test_task_id))).scalar_one_or_none()
            if current is None or not current.is_active:
                needs_task = True
            elif _status_value(current.status) == "DONE":
                # Re-test after changes: a finished test task is not reused.
                needs_task = True
            elif current.title != test_task_title(prompt.title, prompt.knowledge_type):
                current.title = test_task_title(prompt.title, prompt.knowledge_type)
                await db.commit()
        if needs_task:
            tester = new_tester or (await db.execute(select(User).where(User.id == prompt.tester_id))).scalar_one()
            prompt_id = prompt.id
            task_id = await _create_test_task(db, prompt, tester, user, link)
            prompt = await _get_prompt_or_404(db, prompt_id)
            if task_id is not None:
                prompt.test_task_id = task_id
                await db.commit()
    return await _single_prompt_out(db, prompt)


@router.post("/prompts/{prompt_id}/confirm-test", response_model=KnowledgePromptOut)
@router.post("/prompts/{prompt_id}/confirm-control", response_model=KnowledgePromptOut)
async def confirm_prompt_test(
    prompt_id: uuid.UUID,
    payload: PromptReviewAction,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> KnowledgePromptOut:
    prompt = await _get_prompt_or_404(db, prompt_id)
    if prompt.status != STATUS_PENDING_TEST:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Materiali nuk është në pritje të shqyrtimit")
    if prompt.created_by == user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Shqyrtimin duhet ta konfirmojë një person tjetër, jo autori",
        )
    if prompt.tester_id is not None and prompt.tester_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Shqyrtimin e konfirmon vetëm personi i caktuar",
        )
    comment = (payload.comment or "").strip()
    prompt.status = STATUS_PENDING_APPROVAL
    prompt.tested_by = user.id
    prompt.tested_at = _now()
    prompt.test_comment = comment or None
    prompt.rejected_by = None
    prompt.rejected_at = None
    prompt.rejection_reason = None
    await db.commit()
    prompt_id = prompt.id
    reviewed = "Prompti u testua" if prompt.knowledge_type == "PROMPT" else "Materiali u kontrollua"
    await _complete_test_task(db, prompt, user, comment or f"{reviewed}: {prompt.title}")
    prompt = await _get_prompt_or_404(db, prompt_id)
    await _complete_author_tasks(db, prompt, user)
    return await _single_prompt_out(db, await _get_prompt_or_404(db, prompt_id))


@router.post("/prompts/{prompt_id}/approve", response_model=KnowledgePromptOut)
async def approve_prompt(
    prompt_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> KnowledgePromptOut:
    if not _is_manager(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Vetëm menaxherët mund ta aprovojnë")
    prompt = await _get_prompt_or_404(db, prompt_id)
    if prompt.status != STATUS_PENDING_APPROVAL:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Materiali duhet të testohet ose kontrollohet para aprovimit")
    if user.id in (prompt.created_by, prompt.tested_by):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Aprovimin duhet ta bëjë një person tjetër nga autori dhe personi që e shqyrtoi",
        )
    now = _now()
    prompt.status = STATUS_APPROVED
    prompt.approved_by = user.id
    prompt.approved_at = now

    # The request is fulfilled: close the source prompt note (also closes it in PX Notes).
    if prompt.source_note_id is not None:
        note = (await db.execute(select(GaNote).where(GaNote.id == prompt.source_note_id))).scalar_one_or_none()
        if note is not None and note.status != GaNoteStatus.CLOSED:
            note.status = GaNoteStatus.CLOSED
            note.completed_at = now
    await db.commit()
    return await _single_prompt_out(db, prompt)


@router.post("/prompts/{prompt_id}/reject", response_model=KnowledgePromptOut)
async def reject_prompt(
    prompt_id: uuid.UUID,
    payload: PromptReviewAction,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> KnowledgePromptOut:
    prompt = await _get_prompt_or_404(db, prompt_id)
    reason = (payload.comment or "").strip()
    if not reason:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Shkruaj arsyen e kthimit")
    if prompt.status == STATUS_PENDING_TEST:
        if prompt.created_by == user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Autori nuk mund ta refuzojë vetë")
        if prompt.tester_id is not None and prompt.tester_id != user.id and not _is_manager(user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Vetëm testuesi i caktuar")
    elif prompt.status in (STATUS_PENDING_APPROVAL, STATUS_APPROVED):
        if not _is_manager(user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Vetëm menaxherët")
    else:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Prompti është refuzuar tashmë")
    prompt.status = STATUS_REJECTED
    prompt.rejected_by = user.id
    prompt.rejected_at = _now()
    prompt.rejection_reason = reason
    prompt.approved_by = None
    prompt.approved_at = None
    await db.commit()
    return await _single_prompt_out(db, prompt)


@router.delete("/prompts/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_prompt(
    prompt_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> None:
    prompt = await _get_prompt_or_404(db, prompt_id)
    if not _is_manager(user) and not (prompt.created_by == user.id and prompt.status != STATUS_APPROVED):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Nuk keni leje ta fshini")
    # Files PX is create/update only. Deleting the PrimeFlow record must never
    # remove the external file referenced by prompt.files_path.
    if prompt.file_stored_name:
        (_upload_base_dir() / str(prompt.id) / prompt.file_stored_name).unlink(missing_ok=True)
    await _deactivate_test_task(db, prompt.test_task_id)
    await db.delete(prompt)
    await db.commit()


@router.get("/prompts/{prompt_id}/file")
async def download_prompt_file(
    prompt_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> FileResponse:
    prompt = await _get_prompt_or_404(db, prompt_id)
    if not prompt.file_stored_name:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ky prompt nuk ka skedar")
    path = _upload_base_dir() / str(prompt.id) / prompt.file_stored_name
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skedari mungon në server")
    return FileResponse(
        path,
        media_type=prompt.file_content_type or "application/octet-stream",
        filename=prompt.file_original_name or path.name,
    )
