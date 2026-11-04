from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from io import BytesIO

from docx import Document
from openpyxl import load_workbook

import pytest

from app.services.calendar_meeting_time import calendar_meeting_time_range, meeting_time_columns
from app.services.meetings_report import _common_meeting_lines, _meeting_lines, _meeting_status_checkbox_table, _tomorrow_meeting_table, render_html
from app.services.tomorrow_print_report import _meeting_time_sort_key, _meeting_time_display, _dated_meetings_html, _excel_table_attachment, _docx_table_attachment

TZ = ZoneInfo("Europe/Tirane")


def meeting(**overrides):
    values = dict(id="calendar", title="Client meeting", meeting_type="external", calendar_imported=True,
                  microsoft_event_id="event", starts_at=datetime.fromisoformat("2026-11-04T09:00:00+00:00"),
                  ends_at=datetime.fromisoformat("2026-11-04T10:30:00+00:00"), recurrence_type="none")
    return SimpleNamespace(**(values | overrides))


@pytest.mark.parametrize("overrides,expected", [
    ({}, "10:00 - 11:30"),
    ({"ends_at": None}, None),
    ({"ends_at": datetime.fromisoformat("2026-11-04T08:00:00+00:00")}, None),
    ({"meeting_type": "internal"}, None),
    ({"calendar_imported": False, "microsoft_event_id": None}, None),
    ({"ends_at": datetime.fromisoformat("2026-11-05T01:00:00+00:00")}, "10:00 - 02:00"),
    ({"starts_at": datetime.fromisoformat("2026-10-25T00:30:00+00:00"),
      "ends_at": datetime.fromisoformat("2026-10-25T01:30:00+00:00")}, "02:30 - 02:30"),
])
def test_calendar_window_uses_local_times_and_requires_valid_end(overrides, expected):
    assert calendar_meeting_time_range(meeting(**overrides), TZ) == expected


def test_m1_m2_m3_meeting_tables_and_email_keep_the_complete_window():
    value = meeting()
    m1 = _tomorrow_meeting_table("TAK EXTERNE", _meeting_lines([value]))
    status = _meeting_status_checkbox_table([value], {value.id: "held"})
    for rows in (m1, status):
        row = next(row for row in rows if "Client meeting" in row)
        assert [cell.strip() for cell in row.split("|")[2:4]] == ["10:00", "11:30"]
        html = render_html("Calendar window", date(2026, 11, 4), date(2026, 11, 5), [{"title": "TAK EXTERNE", "body": "\n".join(rows)}])
        assert "PREJ" in html and "DERI" in html
        assert "10:00" in html and "11:30" in html
        assert "10:00 - 11:30" not in html


def test_common_payload_window_survives_m3_and_shtypi_sorting():
    item = {"id": "calendar", "date": "2026-11-04", "title": "Client meeting",
            "time": calendar_meeting_time_range(meeting(), TZ), "calendarImported": True}
    rows = _tomorrow_meeting_table("TAK EXTERNE", _common_meeting_lines([item], date(2026, 11, 4)))
    assert any("10:00" in row and "11:30" in row and "Client meeting" in row for row in rows)
    assert _meeting_time_sort_key(item)[2:4] == (10, 0)
    assert _meeting_time_display(item, meeting_type="external") == "10:00 - 11:30"


def test_old_day_offset_is_omitted_and_missing_end_is_not_invented():
    assert meeting_time_columns("23:00 - 01:00 (+1d)") == ("23:00", "01:00")
    assert meeting_time_columns("10:00") == ("10:00", "-")


def test_shtypi_html_excel_and_word_use_distinct_time_columns():
    day = date(2026, 11, 4)
    items = [{"title": "Night meeting", "time": "23:00 - 01:00 (+1d)", "calendarImported": True,
              "assignees": ["Laurent Hoxha"], "recurrence_type": "none", "occurrenceStatus": "canceled"}]
    sections = [(day, "SOT", [("TAK EXT", items, False)])]
    html = _dated_meetings_html(sections)
    assert ">PREJ</th>" in html and ">DERI</th>" in html
    assert 'data-meeting-to="true"' in html and ">01:00</td>" in html
    assert "+1d" not in html and "23:00 - 01:00" not in html
    from_cell = html.split('data-meeting-time="true"', 1)[1].split("</td>", 1)[0]
    title_cell = html.split('data-meeting-cell="true"', 1)[1].split("</td>", 1)[0]
    assert "CAL" not in from_cell and "Anuluar" in from_cell
    assert "CAL" in title_cell and "Anuluar" not in title_cell

    _, content, _ = _excel_table_attachment([], [], day, meeting_sections=sections)
    sheet = load_workbook(BytesIO(content)).active
    row = next(row for row in sheet.iter_rows() if any("Night meeting" in str(cell.value) for cell in row))
    assert [row[index].value for index in (0, 2, 3, 4)] == ["TAK EXT", "23:00\nAnuluar X", "01:00", "LH"]
    assert row[6].value == "1. [CAL] Night meeting"
    assert row[2].border.right.style and row[3].border.left.style

    _, content, _ = _docx_table_attachment([], day, meeting_sections=sections)
    document = Document(BytesIO(content))
    row = next(row for table in document.tables for row in table.rows if any("Night meeting" in cell.text for cell in row.cells))
    assert [cell.text for cell in row.cells[:4]] == ["TAK EXT", "23:00\nAnuluar X", "01:00", "LH"]
    assert row.cells[5].text == "1. [CAL] Night meeting"
