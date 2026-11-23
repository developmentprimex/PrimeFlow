"""Import messages explicitly labeled for the Gmail pilot as PX Notes."""

import logging
import uuid

import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.db import SessionLocal
from app.models.ga_note import GaNote
from app.services.m1_gmail_pilot import GmailMessage, read_labeled_gmail_messages


GMAIL_NOTE_ORIGIN = "GMAIL"
_NOTE_NAMESPACE = uuid.UUID("ab44f361-4bfa-4961-bf8e-bdc896b494ac")
logger = logging.getLogger(__name__)


def gmail_note_insert(messages: list[GmailMessage]):
    values = []
    for message in messages:
        subject = " ".join(message.subject.replace("|", "｜").split()) or "(Pa subjekt)"
        sender = " ".join(message.sender.replace("|", "｜").split()) or "-"
        content = f"EM: GMAIL: {subject}\nDërguesi: {sender}"
        if message.body:
            content += "\n\n" + message.body.replace("\x00", "").replace("|", "｜")
        values.append({
            "id": uuid.uuid5(_NOTE_NAMESPACE, message.id),
            "content": content,
            "knowledge_type": GMAIL_NOTE_ORIGIN,
            "created_at": message.received_at,
            "start_date": message.received_at,
        })
    return insert(GaNote.__table__).values(values).on_conflict_do_nothing(index_elements=["id"])


async def sync_gmail_px_notes() -> None:
    if not settings.M1_GMAIL_NOTES_IMPORT_ENABLED:
        return
    try:
        messages = await read_labeled_gmail_messages(include_body=True)
        if not messages:
            return
        async with SessionLocal() as db:
            await db.execute(gmail_note_insert(messages))
            await db.commit()
    except (httpx.HTTPError, OSError, KeyError, ValueError, TypeError, SQLAlchemyError) as exc:
        logger.warning("gmail_px_notes_sync_failed error_type=%s", type(exc).__name__)
