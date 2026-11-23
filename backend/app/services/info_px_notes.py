"""Persist inbox messages as PX Notes."""

from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.microsoft_mail import Mailbox
from app.models.ga_note import GaNote

async def save_mailbox_notes(db: AsyncSession, messages: list[dict], mailbox: Mailbox) -> None:
    if not messages:
        return

    notes = {}
    for message in messages:
        note_id = uuid5(NAMESPACE_URL, f"primeflow:{mailbox.email}:{message['id']}")
        received_at = datetime.fromisoformat(message["received_datetime"])
        subject = " ".join(message["subject"].replace("|", "｜").split())
        sender = " ".join(message["sender"].replace("|", "｜").split())
        body = message["body"].replace("\x00", "").replace("|", "｜").strip()
        content = f"{mailbox.label} - {subject}\nDërguesi: {sender}"
        if body:
            content += f"\n\n{body}"
        notes[note_id] = {
            "id": note_id,
            "content": content,
            "knowledge_type": mailbox.note_origin,
            "created_at": received_at,
            "start_date": received_at,
        }
    statement = insert(GaNote).values([notes[note_id] for note_id in sorted(notes)])
    await db.execute(statement.on_conflict_do_nothing(index_elements=["id"]))
    await db.commit()
