"""Mira notes are meeting records, so they are excluded from report note lists."""
from sqlalchemy import or_

from app.models.ga_note import GaNote


def mira_note_expression():
    return or_(GaNote.from_mira, GaNote.from_mira_desktop)


def is_mira_note(note) -> bool:
    return bool(getattr(note, "from_mira", False) or getattr(note, "from_mira_desktop", False))
