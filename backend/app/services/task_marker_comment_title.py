"""Keep newly written symbol comments immediately below the task headline."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import noload

from app.models.ga_note import GaNote
from app.models.plan_note import PlanNote
from app.services.note_markup import NOTE_MARK_TOKEN_RE


def comment_title_line(comment: str | None) -> str | None:
    text = " ".join((comment or "").split())
    return f"COM: {text}" if text else None


def update_comment_in_title(content: str, previous_comment: str | None, comment: str | None) -> str:
    """Replace only the matching COM annotation; preserve all other note text.

    Called for a new/changed comment, never when merely reading or changing
    the symbol of an existing comment. Historical comments are not backfilled.
    """
    old_line, new_line = comment_title_line(previous_comment), comment_title_line(comment)
    if old_line == new_line:
        return content
    newline = "\r\n" if "\r\n" in content else "\n"
    lines = content.split(newline)
    if old_line:
        remaining = []
        carry = ""
        for line in lines:
            if NOTE_MARK_TOKEN_RE.sub("", line).strip() != old_line:
                remaining.append(carry + line)
                carry = ""
                continue
            # Preserve marks that span this line and adjacent note text.
            tokens = list(NOTE_MARK_TOKEN_RE.finditer(line))
            counts = {kind: sum((1 if match.group(1) else -1) for match in tokens
                                if (match.group(1) or match.group(2)).lower() == kind)
                      for kind in ("added", "done")}
            if any(counts.values()):
                carry += "".join(match.group(0) for match in tokens)
        if carry:
            remaining.append(carry)
        lines = remaining
    if new_line and not any(NOTE_MARK_TOKEN_RE.sub("", line).strip() == new_line for line in lines):
        first = next((index for index, line in enumerate(lines) if NOTE_MARK_TOKEN_RE.sub("", line).strip()), None)
        if first is not None:
            lines.insert(first + 1, new_line)
    return newline.join(lines)


async def sync_comment_title(db, tasks, previous_comment, comment, *, source_note=None):
    if comment_title_line(previous_comment) == comment_title_line(comment):
        return
    for task in tasks:
        task.title = update_comment_in_title(task.title, previous_comment, comment)
    for model, origin in ((GaNote, "ga_note_origin_id"), (PlanNote, "plan_note_origin_id")):
        ids = {getattr(task, origin, None) for task in tasks} - {None}
        if source_note is not None and isinstance(source_note, model):
            ids.add(source_note.id)
        if not ids:
            continue
        notes = (await db.execute(select(model).options(noload(model.attachments)).where(model.id.in_(ids)))).scalars().all()
        for note in notes:
            # Knowledge text has its own meaning; its task still gets COM.
            if getattr(note, "knowledge_type", None) in ("PROMPT", "DEFINITION", "REGULATION"):
                continue
            note.content = update_comment_in_title(note.content, previous_comment, comment)
