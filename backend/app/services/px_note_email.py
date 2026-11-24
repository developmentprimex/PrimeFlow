"""Compact email-backed PX Notes and read the original without altering notes."""

import re


_PREFIXES = {
    "INFO_PX_MAIL": "EM INFO PX",
    "IT_MAIL": "EM IT",
    "HF_MAIL": "EM HF",
    "PX_EU_MAIL": "EM PX EU",
    "GMAIL": "EM GMAIL",
}
EMAIL_NOTE_ORIGINS = tuple(_PREFIXES)
_EMAIL_TITLE = re.compile(r"^(EM (?:INFO PX|IT|HF|PX EU|GA|GMAIL)):\s*\d{1,2}:\d{2}(?:[ \t]+(.+))?$", re.IGNORECASE)
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


def format_email_title(prefix: str, label: str) -> str:
    name = " ".join(label.replace("|", "｜").split()).upper()
    return f"{prefix.upper()}: 08:00 {name}".rstrip()


def email_title_from_content(content: str) -> str | None:
    first_line = content.lstrip().split("\n", 1)[0].strip()
    match = _EMAIL_TITLE.fullmatch(first_line)
    return format_email_title(match[1], match[2] or "") if match else None


def email_preview(note) -> dict[str, str] | None:
    prefix = _PREFIXES.get(getattr(note, "knowledge_type", None))
    if not prefix:
        return None
    content = note.content or ""
    metadata = getattr(note, "email_metadata", None) or {}
    original = legacy_email(content)
    subject = metadata.get("subject") or (original[0] if original else "")
    saved_title = metadata.get("title") or content.split("\n", 1)[0].strip()
    formatted = _EMAIL_TITLE.fullmatch(saved_title)
    return {
        "id": str(note.id),
        "title": format_email_title(prefix, (formatted[2] if formatted else None) or subject),
        "subject": subject,
        "sender": metadata.get("sender") or (original[1] if original else ""),
    }


def email_preview_text(preview: dict[str, str]) -> str:
    return " · ".join(" ".join(preview[key].replace("|", "｜").split()) for key in ("title", "subject", "sender") if preview.get(key))
