from base64 import urlsafe_b64encode
from datetime import datetime, timezone

from sqlalchemy.dialects import postgresql

from app.services.gmail_px_notes import gmail_note_insert
from app.services.m1_gmail_pilot import GmailMessage, extract_gmail_text


def test_gmail_note_uses_the_message_id_and_preserves_review_state_on_retry():
    timestamp = datetime(2026, 11, 23, 9, 50, tzinfo=timezone.utc)
    message = GmailMessage("message-1", "Test email", "sender@example.com", timestamp)
    statement = gmail_note_insert([message])
    compiled = statement.compile(dialect=postgresql.dialect())
    values = compiled.params
    retry = gmail_note_insert([GmailMessage("message-1", "Edited subject", "", timestamp)])
    retry_values = retry.compile(dialect=postgresql.dialect()).params

    assert values["id_m0"] == retry_values["id_m0"]
    assert values["knowledge_type_m0"] == "GMAIL"
    assert values["created_at_m0"] == timestamp
    assert "Test email" in values["content_m0"]
    assert "sender@example.com" in values["content_m0"]
    assert "ON CONFLICT (id) DO NOTHING" in str(compiled)


def test_gmail_note_contains_full_plain_text():
    timestamp = datetime(2026, 11, 23, 9, 50, tzinfo=timezone.utc)
    message = GmailMessage("message-1", "Test email", "sender@example.com", timestamp, body="First line\n\nLast line")
    compiled = gmail_note_insert([message]).compile(dialect=postgresql.dialect())
    assert compiled.params["content_m0"].endswith("First line\n\nLast line")


def test_gmail_extracts_visible_html_text_and_ignores_attachments():
    def part(mime, content, filename=""):
        return {
            "filename": filename,
            "mimeType": mime,
            "body": {"data": urlsafe_b64encode(content.encode()).decode().rstrip("=")},
        }

    html = part("text/html", "<p>First <b>line</b></p><script>hidden</script><p>Last line</p>")
    assert extract_gmail_text({"parts": [html, part("text/plain", "attachment", "file.txt")]}) == "First line\nLast line"
    assert extract_gmail_text({"parts": [html, part("text/plain", "Prefer plain text")]}) == "Prefer plain text"
