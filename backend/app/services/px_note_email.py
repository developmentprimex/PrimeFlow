"""Compact email-backed PX Notes and read the original without altering notes."""

import re
from zoneinfo import ZoneInfo

from app.config import settings


_PREFIXES = {
    "INFO_PX_MAIL": "EM INFO PX",
    "IT_MAIL": "EM IT",
    "HF_MAIL": "EM HF",
    "PX_EU_MAIL": "EM PX EU",
    "GMAIL": "EM GMAIL",
}
EMAIL_NOTE_ORIGINS = tuple(_PREFIXES)
_LEGACY_HEADER = re.compile(
    r"^(EM INFO PX|EM IT|EM HF|EM PX EU) - (?P<subject>[^\r\n]*)\r?\nDërguesi: (?P<sender>[^\r\n]*)"
    r"|^EM: GMAIL: (?P<gmail_subject>[^\r\n]*)\r?\nDërguesi: (?P<gmail_sender>[^\r\n]*)"
)


def legacy_email(content: str) -> tuple[str, str, str] | None:
    match = _LEGACY_HEADER.match(content)
    if match is None:
        return None
    subject = match["subject"] if match["subject"] is not None else match["gmail_subject"]
    sender = match["sender"] if match["sender"] is not None else match["gmail_sender"]
    return subject, sender, content[match.end():].lstrip("\r\n")


def email_preview(note) -> dict[str, str] | None:
    prefix = _PREFIXES.get(getattr(note, "knowledge_type", None))
    if not prefix:
        return None
    content = note.content or ""
    metadata = getattr(note, "email_metadata", None) or {}
    original = legacy_email(content)
    first_line = content.split("\n", 1)[0].strip()
    created_at = getattr(note, "created_at", None)
    time = created_at.astimezone(ZoneInfo(settings.APP_TIMEZONE)).strftime("%H:%M") if created_at else ""
    title = first_line if first_line.startswith(f"{prefix}: ") else f"{prefix}: {time}".rstrip()
    return {
        "id": str(note.id),
        "title": metadata.get("title") or title,
        "subject": metadata.get("subject") or (original[0] if original else ""),
        "sender": metadata.get("sender") or (original[1] if original else ""),
    }


def email_preview_text(preview: dict[str, str]) -> str:
    return " · ".join(" ".join(preview[key].replace("|", "｜").split()) for key in ("title", "subject", "sender") if preview.get(key))
