from collections import Counter, defaultdict
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ga_note_attachment import GaNoteAttachment
from app.services.after_break_report import BLUE_NOTE_COLUMNS, NOTE_REFERENCES, load_blue_notes
from app.services.meetings_report import _section_report_table_rows


def _row_key(values: list[str]) -> tuple[str, ...]:
    return tuple(" ".join(value.split()) for value in values)


async def note_attachments_by_row(
    db: AsyncSession, note_ids: dict[str, str],
) -> dict[str, list[dict[str, str]]]:
    if not note_ids:
        return {}
    ids = {UUID(note_id) for note_id in note_ids.values()}
    attachments = (await db.execute(
        select(GaNoteAttachment)
        .where(GaNoteAttachment.note_id.in_(ids))
        .order_by(GaNoteAttachment.created_at, GaNoteAttachment.id)
    )).scalars().all()
    by_note: dict[str, list[dict[str, str]]] = defaultdict(list)
    for attachment in attachments:
        by_note[str(attachment.note_id)].append({
            "id": str(attachment.id),
            "original_filename": attachment.original_filename,
        })
    return {number: by_note[note_id] for number, note_id in note_ids.items() if note_id in by_note}


async def match_note_attachments(
    db: AsyncSession, visible_rows: list[list[str]], snapshot: dict | None,
    *, generated_at: str | None = None,
) -> dict[str, list[dict[str, str]]]:
    visible_rows = [row for row in visible_rows if row[0].isdecimal()]
    if not visible_rows:
        return {}
    references = (snapshot or {}).get(NOTE_REFERENCES)
    # Legacy reports have no IDs. Match their text, initials and time only
    # when they identify a single source note.
    legacy = references is None
    if legacy:
        generated_at = generated_at or (snapshot or {}).get("ga_replies_generated_at")
        references = await load_blue_notes(
            db, created_before=datetime.fromisoformat(generated_at) if generated_at else None,
        )
    candidates: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for note_id, values in references:
        candidates[_row_key(values[1:] if legacy else values)].append(note_id)
    row_counts = Counter(row[0] for row in visible_rows)
    visible_keys = Counter(_row_key(row[1:]) for row in visible_rows) if legacy else {}
    note_ids = {}
    for row in visible_rows:
        number = row[0]
        key = _row_key(row[1:] if legacy else row)
        matches = candidates.get(key, [])
        if len(matches) == 1 and row_counts[number] == 1 and (not legacy or visible_keys[key] == 1):
            note_ids[number] = matches[0]
    return await note_attachments_by_row(db, note_ids)


async def section_note_attachments(
    db: AsyncSession, sections: list[dict], title: str, snapshot: dict | None,
) -> dict[str, list[dict[str, str]]]:
    section = next((item for item in sections if (item.get("section_key") or item["title"]) == title), None)
    if section is None:
        return {}
    header, rows = _section_report_table_rows(section["body"].strip().splitlines())
    if header != [column for column, _ in BLUE_NOTE_COLUMNS]:
        return {}
    return await match_note_attachments(db, rows, snapshot)
