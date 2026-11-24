from collections import Counter, defaultdict
from datetime import datetime
from uuid import UUID

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import noload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ga_note_attachment import GaNoteAttachment
from app.models.ga_note import GaNote
from app.services.after_break_report import BLUE_NOTE_COLUMNS, NOTE_REFERENCES, load_blue_notes
from app.services.meetings_report import _section_report_table_rows
from app.services.px_note_email import EMAIL_NOTE_ORIGINS, email_preview, email_preview_text


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


async def match_note_rows(
    db: AsyncSession, visible_rows: list[list[str]], snapshot: dict | None,
    *, generated_at: str | None = None,
) -> dict[str, str]:
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
            db, created_before=datetime.fromisoformat(generated_at) if generated_at else None, compact_email=False,
        )
    candidates: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for note_id, values in references:
        candidates[_row_key(values[1:] if legacy else values)].add(note_id)
    row_counts = Counter(row[0] for row in visible_rows)
    visible_keys = Counter(_row_key(row[1:]) for row in visible_rows) if legacy else {}
    note_ids = {}
    for row in visible_rows:
        number = row[0]
        key = _row_key(row[1:] if legacy else row)
        matches = candidates.get(key, [])
        if len(matches) == 1 and row_counts[number] == 1 and (not legacy or visible_keys[key] == 1):
            note_ids[number] = next(iter(matches))
    return note_ids


async def mail_previews_by_row(db: AsyncSession, note_ids: dict[str, str]) -> dict[str, dict[str, str]]:
    if not note_ids:
        return {}
    notes = (await db.scalars(select(GaNote).options(noload(GaNote.attachments)).where(
        GaNote.id.in_({UUID(note_id) for note_id in note_ids.values()}),
        GaNote.knowledge_type.in_(EMAIL_NOTE_ORIGINS),
    ))).all()
    previews = {str(note.id): email_preview(note) for note in notes}
    return {number: previews[note_id] for number, note_id in note_ids.items() if previews.get(note_id)}


async def note_controls_by_row(db: AsyncSession, note_ids: dict[str, str]) -> dict:
    return {
        "note_attachments": await note_attachments_by_row(db, note_ids),
        "note_emails": await mail_previews_by_row(db, note_ids),
    }


def compact_report_note_html(html: str, emails: dict[str, dict[str, str]]) -> str:
    if not emails:
        return html
    document = BeautifulSoup(html, "html.parser")
    for table in document.select("table.report-table-notes, table[data-closing-table], table[data-undiscussed-notes-table]"):
        rows = table.find_all("tr")
        headers = [cell.get_text(strip=True) for cell in rows[0].find_all(["td", "th"])] if rows else []
        if not headers or headers[0] != "NR" or "NOTE" not in headers:
            continue
        note_column = headers.index("NOTE")
        for row in rows[1:]:
            cells = row.find_all("td", recursive=False)
            if len(cells) > note_column and (email := emails.get(cells[0].get_text(strip=True))):
                cells[note_column].string = email_preview_text(email)
    return str(document)


async def match_note_attachments(
    db: AsyncSession, visible_rows: list[list[str]], snapshot: dict | None, *, generated_at: str | None = None,
) -> dict[str, list[dict[str, str]]]:
    return await note_attachments_by_row(db, await match_note_rows(db, visible_rows, snapshot, generated_at=generated_at))


def _section_note_rows(sections: list[dict], title: str) -> list[list[str]]:
    section = next((item for item in sections if (item.get("section_key") or item["title"]) == title), None)
    if section is None:
        return []
    header, rows = _section_report_table_rows(section["body"].strip().splitlines())
    if header != [column for column, _ in BLUE_NOTE_COLUMNS]:
        return []
    return rows


async def section_note_controls(
    db: AsyncSession, sections: list[dict], title: str, snapshot: dict | None,
) -> dict:
    return await note_controls_by_row(db, await match_note_rows(db, _section_note_rows(sections, title), snapshot))


async def section_note_attachments(
    db: AsyncSession, sections: list[dict], title: str, snapshot: dict | None,
) -> dict[str, list[dict[str, str]]]:
    return await match_note_attachments(db, _section_note_rows(sections, title), snapshot)
