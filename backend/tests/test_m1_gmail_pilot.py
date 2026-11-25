import asyncio
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock

from app.services import morning_report
from app.services.m1_gmail_pilot import GmailMessage


def test_m1_gmail_rows_are_refreshed_without_duplication_and_rendered(monkeypatch):
    day = date(2026, 11, 23)
    title = morning_report.SECTION_TITLES[1]
    entries = [GmailMessage(
        "m1-test", "PrimeFlow M1 TEST", "sender@example.com",
        datetime(2026, 11, 23, 9, 50, tzinfo=timezone.utc), body="The email body belongs in M1.",
    )]
    monkeypatch.setattr(morning_report, "read_m1_gmail_messages", AsyncMock(return_value=entries))
    sections = [{"section_key": title, "title": title, "body": ""}]

    sections = asyncio.run(morning_report.refresh_m1_gmail_section(sections, day))
    sections = morning_report.normalize_morning_report_sections(sections)
    sections = asyncio.run(morning_report.refresh_m1_gmail_section(sections, day))
    rendered = morning_report.render_html("M1", day, sections)
    plain = morning_report.render_plain_text("M1", day, sections)

    assert plain.count("PrimeFlow M1 TEST") == 1
    assert "sender@example.com" in rendered
    assert "PrimeFlow M1 TEST" in rendered
    assert "PËRMBAJTJA" in rendered
    assert "The email body belongs in M1." in rendered
    assert "The email body belongs in M1." in plain
    assert rendered.index("DERGUESI</th>") < rendered.index("PËRMBAJTJA</th>")
    assert rendered.index("PËRMBAJTJA</th>") < rendered.index("ORA</th>", rendered.index("DERGUESI</th>"))
    assert '<th width="140" class="gmail-sender">DERGUESI</th>' in rendered
    assert '<th width="125">TITULLI</th>' in rendered


def test_m1_gmail_refresh_preserves_historical_sent_reports(monkeypatch):
    read_gmail = AsyncMock()
    monkeypatch.setattr(morning_report, "read_m1_gmail_messages", read_gmail)
    title = morning_report.SECTION_TITLES[1]
    sections = [{"section_key": title, "title": title, "body": "EMAIL-E NGA GMAIL: 0"}]

    assert asyncio.run(morning_report.refresh_m1_gmail_section(sections, date(2020, 1, 1), sent=True)) == sections
    read_gmail.assert_not_awaited()
