"""Mira notes are meeting records, so they are excluded from report note lists."""
from sqlalchemy import or_

from app.models.ga_note import GaNote
from app.services.mira_development_name import NAME


def mira_note_expression():
    return or_(GaNote.from_mira, GaNote.from_mira_desktop, GaNote.mira_dictation_source.is_not(None))


def is_mira_note(note) -> bool:
    return bool(getattr(note, "from_mira", False) or getattr(note, "from_mira_desktop", False)
                or getattr(note, "mira_dictation_source", None))


def append_mira_dictation_label(content: str, source: str | None) -> str:
    label = {"1h": "Nga Mira 1H", "ai_agent": f"Nga {NAME}"}.get(source)
    return f"{content}\n{label}" if label else content
