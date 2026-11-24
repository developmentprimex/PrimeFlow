"""Read the HOMEFACE Yandex inbox without changing message state."""

import re
import ssl
from datetime import date, datetime, timedelta
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from imaplib import IMAP4_SSL
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from app.integrations.microsoft_mail import Mailbox


NOTE_ORIGIN = "HF_MAIL"
MAILBOX = Mailbox(4, "info@homeface.de", "EM HF", NOTE_ORIGIN, None, None, None)
_HOST = "imap.yandex.com"
_INTERNAL_DATE = re.compile(rb'INTERNALDATE "([^"]+)"')


def _imap_date(day: date) -> str:
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{day.day:02d}-{months[day.month - 1]}-{day.year}"


def _message_body(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content(errors="replace")
    except LookupError:
        content = (part.get_payload(decode=True) or b"").decode("utf-8", errors="replace")
    if part.get_content_subtype() == "html":
        soup = BeautifulSoup(content, "html.parser")
        for tag in soup(["head", "script", "style", "template"]):
            tag.decompose()
        return soup.get_text("\n", strip=True)
    return content.strip()


def read_inbox(password: str, report_day: date, tz: ZoneInfo) -> list[dict]:
    rows = []
    with IMAP4_SSL(_HOST, 993, ssl_context=ssl.create_default_context(), timeout=12) as inbox:
        inbox.login(MAILBOX.email, password)
        status, _ = inbox.select("INBOX", readonly=True)
        if status != "OK":
            raise ValueError("The HOMEFACE inbox could not be opened.")
        _, validity = inbox.response("UIDVALIDITY")
        if not validity or not validity[-1] or not validity[-1].isdigit():
            raise ValueError("The HOMEFACE inbox did not supply UIDVALIDITY.")
        # IMAP searches by the server's message date. Confirm the exact report
        # date after applying the received timestamp's timezone offset.
        status, candidates = inbox.uid(
            "SEARCH", None, "SINCE", _imap_date(report_day - timedelta(days=2)),
            "BEFORE", _imap_date(report_day + timedelta(days=3)),
        )
        if status != "OK":
            raise ValueError("The HOMEFACE inbox could not be searched.")
        for uid in (candidates[0] or b"").split():
            status, metadata = inbox.uid("FETCH", uid, "(INTERNALDATE)")
            if status != "OK":
                raise ValueError("The HOMEFACE message date could not be read.")
            raw_date = next(
                (match[1] for item in metadata if isinstance(item, bytes) and (match := _INTERNAL_DATE.search(item))),
                None,
            )
            if raw_date is None:
                continue
            received = datetime.strptime(raw_date.decode("ascii").strip(), "%d-%b-%Y %H:%M:%S %z").astimezone(tz)
            if received.date() != report_day:
                continue
            status, data = inbox.uid("FETCH", uid, "(BODY.PEEK[])")
            if status != "OK":
                raise ValueError("The HOMEFACE message could not be read.")
            raw_message = next((item[1] for item in data if isinstance(item, tuple)), None)
            if raw_message is None:
                continue
            message = BytesParser(policy=policy.default).parsebytes(raw_message)
            rows.append({
                "id": f"{validity[-1].decode('ascii')}:{uid.decode('ascii')}",
                "subject": str(message.get("Subject") or "(Pa subjekt)"),
                "sender": str(message.get("From") or "-"),
                "received_at": received.strftime("%H:%M"),
                "received_datetime": received.isoformat(),
                "body": _message_body(message),
            })
    return sorted(rows, key=lambda row: datetime.fromisoformat(row["received_datetime"]).timestamp(), reverse=True)
