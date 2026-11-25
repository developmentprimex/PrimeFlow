"""Compact email-backed PX Notes and read the original without altering notes."""

import re
from urllib.parse import urlsplit


_PREFIXES = {
    "INFO_PX_MAIL": "EM INFO PX",
    "IT_MAIL": "EM IT",
    "HF_MAIL": "EM HF",
    "PX_EU_MAIL": "EM PX EU",
    "GMAIL": "EM GMAIL",
}
EMAIL_NOTE_ORIGINS = tuple(_PREFIXES)
_MAIL_WEB_HOSTS = {
    "outlook.office.com", "outlook.office365.com", "outlook.live.com", "outlook.cloud.microsoft",
    "mail.google.com", "mail.yandex.com", "mail.yandex.ru", "mail.ya.ru",
}
_MANUAL_EMAIL_LINK = re.compile(r"^Email origjinal:\s*(\S+)\s*$", re.IGNORECASE)
_EMAIL_TITLE = re.compile(r"^(EM (?:INFO PX|IT|HF|PX EU|GA|GMAIL)):\s*\d{1,2}:\d{2}(?:[ \t]+(.+))?$", re.IGNORECASE)
_EMAIL_NOTE_PREFIX = re.compile(r"^EM(?:\s*:\s*|\s+)(?:INFO\s+PX|IT|HF|PX\s+EU|GA|GMAIL)\s*[:-]", re.I)
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


def is_email_note_content(content: str | None) -> bool:
    return bool(_EMAIL_NOTE_PREFIX.match((content or "").lstrip()))


def original_email_url(value: str | None) -> str | None:
    if not value or any(character.isspace() for character in value) or "\\" in value:
        return None
    try:
        url = urlsplit(value)
        if url.scheme == "https" and url.netloc.lower() in _MAIL_WEB_HOSTS:
            return value
    except ValueError:
        pass
    return None


def manual_original_email_url(content: str) -> str | None:
    link = _MANUAL_EMAIL_LINK.fullmatch(content.rstrip().rsplit("\n", 1)[-1].strip())
    return original_email_url(link[1]) if link else None


def email_preview(note) -> dict[str, str] | None:
    prefix = _PREFIXES.get(getattr(note, "knowledge_type", None))
    if not prefix:
        return None
    content = (note.content or "").lstrip()
    metadata = getattr(note, "email_metadata", None) or {}
    original = legacy_email(content)
    subject = metadata.get("subject") or (original[0] if original else "")
    heading, _, details = content.partition("\n")
    saved_title = metadata.get("title") or heading.strip()
    formatted = _EMAIL_TITLE.fullmatch(saved_title)
    # Structured notes store the summary and numbered steps under the title.
    # Legacy imports store the original message in that position instead.
    summary = details.strip() if not original and email_title_from_content(heading) else ""
    note_url = manual_original_email_url(summary)
    if note_url:
        summary = summary.rpartition("\n")[0].strip()
    source_url = original_email_url(metadata.get("original_email_url")) or note_url
    return {
        "id": str(note.id),
        "title": format_email_title(prefix, (formatted[2] if formatted else None) or subject),
        "subject": subject,
        "sender": metadata.get("sender") or (original[1] if original else ""),
        **({"summary": summary} if summary else {}),
        **({"original_email_url": source_url} if source_url else {}),
    }


def email_preview_text(preview: dict[str, str]) -> str:
    return " · ".join(" ".join(preview[key].replace("|", "｜").split()) for key in ("title", "subject", "sender") if preview.get(key))
