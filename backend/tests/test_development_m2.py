import asyncio
import io
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from openpyxl import load_workbook

from app.api.routers.exports import export_department_internal_meetings_xlsx
from app.models.checklist_item import ChecklistItem
from app.models.enums import ChecklistItemType, UserRole
from app.services.development_m1 import DEVELOPMENT_CHECKLIST_KEY
from app.services.development_m2 import build_development_m2


def test_development_m2_uses_existing_questions_for_live_answers_and_excel():
    titles = [
        "A KA IMELLA TE REJA IT/STD?",
        "A KA SHENIME TE REJA PF PX NOTES / AI AGENTS TEAMS?",
        "DETYRAT E SECILIT, CKA KEMI PUNU DERI 12:00?",
        "CKA MBETET PER PM?",
        "A KA DICKA QE DUHET T'I DOREZOHET GA PARA PAUZES?",
    ]
    items = [
        ChecklistItem(id=uuid4(), item_type=ChecklistItemType.CHECKBOX, day="M2", title=title,
                      position=index, is_checked=index < 2)
        for index, title in enumerate(titles)
    ]
    items[-1].keyword = "development-m2:delivery"
    items[-1].title = "Dorëzimet"
    db = AsyncMock()
    db.scalar.return_value = SimpleNamespace(id=uuid4())
    db.scalars.return_value = Mock(**{"all.return_value": items})
    db.execute.return_value = Mock(**{"scalars.return_value.all.return_value": [SimpleNamespace(items=items)]})
    user = SimpleNamespace(role=UserRole.ADMIN, full_name="Dev Person", username="dev")
    tz = ZoneInfo("Europe/Tirane")
    received = datetime(2026, 11, 25, 10, 30, tzinfo=tz)

    async def download():
        response = await export_department_internal_meetings_xlsx(
            group_key=DEVELOPMENT_CHECKLIST_KEY, title="Development Internal Meetings", db=db, user=user,
        )
        return b"".join([part async for part in response.body_iterator])

    with (
        patch("app.services.development_m2.report_timezone", return_value=tz),
        patch("app.services.development_m2.datetime") as clock,
        patch("app.services.development_m2.load_new_email_mailboxes", new_callable=AsyncMock) as read_mail,
        patch("app.services.development_m2.load_blue_notes", new_callable=AsyncMock) as read_notes,
        patch("app.services.development_m2._delivery_rows", new_callable=AsyncMock) as read_delivery,
        patch("app.services.development_discord_notes.load_development_discord_notes", new_callable=AsyncMock) as read_discord,
        patch("app.api.routers.exports.build_development_m1", new=AsyncMock(return_value=None)),
        patch("app.api.routers.exports.read_development_reorganization", new=AsyncMock(
            return_value="KOMENT: Vetëm M2",
        )) as read_reorg,
    ):
        clock.now.return_value = received.replace(hour=15)
        read_mail.return_value = {"it": {"connected": True, "messages": [{
            "id": "mail", "subject": "Email për projektin", "sender": "Klienti",
            "received_at": "10:30", "received_datetime": received.isoformat(),
            "body": "Teksti i plotë\nRreshti i dytë",
            "original_email_url": "https://outlook.office.com/mail/inbox/id/test",
        }]}}
        read_notes.return_value = [
            ("note", ["1", "NO", "Shënim i ri", "DP", "10:35"]),
            ("mail-note", ["2", "NO", "EM IT: 08:00 PROJEKTI · Subjekti · Dërguesi", "-", "10:40"]),
        ]
        read_delivery.return_value = [{"id": "task", "title": "Dorëzo projektin", "detail": "", "marker": "M2"}]
        read_discord.return_value = {"rows": [{
            "id": "post", "title": "Autor Discord", "detail": "Shënimi nga zhvillim-text",
            "labels": ["25.11.2026 11:00"], "href": "https://discord.com/channels/1/2/3",
        }], "message": None}

        report = asyncio.run(build_development_m2(db, user))
        cutoff = received.replace(hour=12, minute=0)
        read_mail.assert_awaited_once_with(cutoff.date(), cutoff, sources=("it",))
        read_notes.assert_awaited_once_with(db, created_from=cutoff.replace(hour=8), created_before=cutoff)
        data = asyncio.run(download())
        read_reorg.assert_awaited_once_with(db, "m2", cutoff.date())

    assert report["cutoff"] == "12:00"
    assert report["item_sections"] == {
        str(items[0].id): "emails", str(items[1].id): "notes", str(items[4].id): "delivery",
    }
    email, = next(section["rows"] for section in report["sections"] if section["key"] == "emails")
    assert email["email_body"] == "Teksti i plotë\nRreshti i dytë"
    assert email["href"] == "https://outlook.office.com/mail/inbox/id/test"
    note_rows = next(section["rows"] for section in report["sections"] if section["key"] == "notes")
    assert "email_heading" not in note_rows[0]
    assert note_rows[1]["email_heading"] == "EM IT: 08:00 PROJEKTI"
    sheet = load_workbook(io.BytesIO(data)).active
    rows = list(sheet.values)
    notes_title = report["item_titles"][str(items[1].id)]
    questions = {row[1]: index for index, row in enumerate(rows) if row[0] in range(1, 6)}
    assert rows[questions[titles[0]]][2] == "✓"
    assert rows[questions[titles[0]] + 1][1] == "Email për projektin\n10:30 · Klienti"
    assert rows[questions[notes_title] + 1][1] == "Shënim i ri\nDP · 10:35"
    assert rows[questions[notes_title] + 2][1] == "EM IT: 08:00 PROJEKTI · Subjekti · Dërguesi\n- · 10:40"
    discord_cell = sheet.cell(questions[notes_title] + 5, 2)
    assert "Shënimi nga zhvillim-text" in discord_cell.value
    assert discord_cell.hyperlink.target == "https://discord.com/channels/1/2/3"
    assert questions[titles[2]] + 1 == questions[titles[3]]
    assert questions[titles[3]] + 1 == questions[items[-1].title]
    assert rows[questions[items[-1].title] + 1][1] == "Dorëzo projektin\nM2"
    assert rows[questions[items[-1].title] + 2][1] == "A KA RIORGANIZIM?"
    assert rows[questions[items[-1].title] + 4][1] == "KOMENT: Vetëm M2"
