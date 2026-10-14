from io import BytesIO
import asyncio
import re
from datetime import date
from unittest.mock import patch

import pytest
from openpyxl import load_workbook
from openpyxl.cell.rich_text import CellRichText

from app.config import settings
from app.services.tomorrow_print_report import (
    _comment_user_initials,
    _comments_table_html,
    _dated_meetings_html,
    _docx_table_attachment,
    _excel_table_attachment,
    _html_table,
    _meeting_rows,
    _meeting_title,
    _meeting_relation,
    _missing_blocked_initials,
    _missing_one_h_initials,
    _one_h_checklists_html,
    _png_table_attachment,
    _task_marker_legend_html,
    _task_badges_html,
    _task_rows,
    build_today_print_report,
    build_tomorrow_print_report,
    ensure_required_shtypi_recipient,
    send_tomorrow_print_report,
)


@pytest.mark.parametrize("tomorrow", [False, True])
@pytest.mark.parametrize("absence", [
    {"date": "2026-09-08", "from": "8:00", "to": "16:00"},
    {"date": "2026-09-08"},
    {"startDate": "2026-09-07", "endDate": "2026-09-09", "fullDay": True},
])
def test_full_day_absence_hides_tasks_in_both_reports(tomorrow, absence) -> None:
    bucket = "leave" if "startDate" in absence else "absent"
    items = {
        name: [{
            "title": f"Hidden {name} work", "date": "2026-09-08", "user_id": "ef",
            "assignees": ["Era Fana"], "oneHReportSlot": "10:00",
        }] for name in ("oneH", "blocked", "important", "r1", "personal")
    }
    items["oneH"].extend([
        {"title": "Present work", "date": "2026-09-08", "userId": "ra", "oneHReportSlot": "10:00"},
        {"title": "Shared work", "date": "2026-09-08", "userId": "ef",
         "assignees": ["Era Fana", "Rina Aliu"], "oneHReportSlot": "11:00"},
    ])
    items[bucket] = [{**absence, "userId": "ef"}]
    payload = {"items": items, "users": [
        {"id": "ef", "full_name": "Era Fana", "role": "STAFF"},
        {"id": "ra", "full_name": "Rina Aliu", "role": "STAFF"},
    ]}
    build = build_tomorrow_print_report if tomorrow else build_today_print_report
    report = asyncio.run(build(date(2026, 9, 7) if tomorrow else date(2026, 9, 8),
                              payload=payload, include_attachment=True))
    assert "Hidden" not in report["html"]
    assert "Present work" in report["html"]
    assert "Shared work" in report["html"]
    workbook = load_workbook(BytesIO(report["attachments"][0][1]))
    exported = "\n".join(str(cell.value or "") for row in workbook.active for cell in row)
    assert "Hidden" not in exported
    assert "Present work" in exported
    assert "Shared work" in exported
    assert _missing_one_h_initials(payload, date(2026, 9, 8))["14:20"] == ["RA"]
    assert _missing_blocked_initials(payload, date(2026, 9, 8)) == ["RA"]


@pytest.mark.parametrize("bucket, absence", [
    ("absent", {"date": "2026-09-08", "from": "08:00", "to": "12:00"}),
    ("absent", {"date": "2026-09-09", "from": "08:00", "to": "23:00"}),
    ("leave", {"startDate": "2026-09-08", "endDate": "2026-09-08",
               "fullDay": False, "from": "08:00", "to": "12:00"}),
])
def test_partial_or_other_day_absence_keeps_tasks_and_missing_slots(bucket, absence) -> None:
    payload = {"users": [{"id": "ef", "full_name": "Era Fana", "role": "STAFF"}],
               "items": {bucket: [{**absence, "userId": "ef", "person": "Era Fana"}],
                         "oneH": [{"title": "Visible work", "date": "2026-09-08",
                                   "userId": "ef", "oneHReportSlot": "10:00"}]}}
    report = asyncio.run(build_today_print_report(date(2026, 9, 8), payload=payload))
    assert "Visible work" in report["html"]
    assert _missing_one_h_initials(payload, date(2026, 9, 8))["14:20"] == ["EF"]


def test_full_day_absence_matches_legacy_person_and_all_users_leave() -> None:
    items = {"oneH": [{"title": "Legacy work", "date": "2026-09-08",
                       "person": "Era Fana", "oneHReportSlot": "10:00"}],
             "absent": [{"date": "2026-09-08", "person": "Era Fana"}]}
    assert all(not tasks for _, tasks, _ in _task_rows(items, date(2026, 9, 8)))
    items["absent"] = []
    items["leave"] = [{"startDate": "2026-09-08", "endDate": "2026-09-08",
                       "fullDay": True, "isAllUsers": True}]
    assert all(not tasks for _, tasks, _ in _task_rows(items, date(2026, 9, 8)))


def test_task_marker_legend_explains_the_report_symbols() -> None:
    legend_html = _task_marker_legend_html()

    assert 'data-task-marker-legend="true"' in legend_html
    assert "PAQARTESI" in legend_html
    assert "KËRKON MONITORIM NGA DIKUSH TJETËR" in legend_html
    assert "⚑" not in legend_html
    assert "GA" in legend_html
    assert "F</strong> - DET FIZIKISHT" in legend_html
    assert "BZ1N1</strong>" in legend_html
    assert "color:#0F2A5F" in legend_html
    assert "color:#DC2626" in legend_html
    assert "background:#EFF6FF" in legend_html
    assert "?</strong> - PYETJE/PAQARTESI" in legend_html
    assert "!</strong> - DYSHIM/ NUK KUPTOHET DET" in legend_html
    assert "!!!</strong> - KLIENT/URGJENT" in legend_html
    assert "👁</strong> - KËRKON" in legend_html
    assert "X</strong> - MBYLL DETYREN" in legend_html
    assert "GA</strong> - PYETJE/SQARIM ME GA" in legend_html
    assert "KA</strong> - PYETJE/SQARIM ME KA" in legend_html
    assert "GENT</strong> - PYETJE/SQARIM ME GENTIN" in legend_html
    assert "M2</strong> - DOREZIM DERI NE PAUZE" in legend_html
    assert "M3</strong> - DOREZIM DERI NE FUND TE DITES" in legend_html
    assert "M2/3</strong> - DOREZIM EDHE NE M2 EDHE M3" in legend_html
    assert legend_html.count('aria-hidden="true"') == 12


def test_missing_one_h_users_exclude_leave_admin_and_management_initials() -> None:
    payload = {
        "users": [
            {"id": "ef", "full_name": "Era Fana", "role": "STAFF", "is_active": True,
             "weekly_planner_sort_order": 0},
            {"id": "ra", "full_name": "Rina Aliu", "role": "STAFF", "is_active": True,
             "weekly_planner_sort_order": 1},
            {"id": "at", "full_name": "Arta Tafa", "role": "STAFF", "is_active": True,
             "weekly_planner_sort_order": 2},
            {"id": "hs", "full_name": "Haxhere Sopa", "role": "STAFF", "is_active": True},
            {"id": "hsh", "full_name": "Haris Shaqiri", "username": "haris.shaqiri",
             "role": "STAFF", "is_active": True, "weekly_planner_sort_order": 3},
            {"id": "ga", "username": "gane.arifaj", "role": "MANAGER", "is_active": True},
            {"id": "admin", "full_name": "Besa Kola", "role": "ADMIN", "is_active": True},
        ],
        "items": {
            "oneH": [{
                "title": "EF: Task", "date": "2026-09-08", "oneHReportSlot": "10:00",
                "userId": "ef", "assignees": ["Era Fana"],
            }],
            "leave": [{
                "startDate": "2026-09-08", "endDate": "2026-09-08", "userId": "at",
            }],
            "absent": [],
        },
    }

    missing = _missing_one_h_initials(payload, date(2026, 9, 8))

    assert missing["10:00"] == ["RA", "HSH"]
    assert missing["11:00"] == ["EF", "RA", "HSH"]


def test_missing_one_h_users_render_in_red_below_report_slot() -> None:
    report_html = _html_table(
        [("1H 10:00", [], False)],
        missing_one_h_by_slot={"10:00": ["EF", "RA", "AT"]},
    )

    assert 'data-missing-one-h-users="true"' in report_html
    assert "color:#DC2626" in report_html
    assert "EF &bull; RA &bull; AT" in report_html


def test_blocked_row_shows_present_users_without_a_blocked_task_in_red() -> None:
    payload = {
        "users": [
            {"id": "ef", "full_name": "Era Fana", "role": "STAFF", "is_active": True},
            {"id": "ra", "full_name": "Rina Aliu", "role": "STAFF", "is_active": True},
            {"id": "fg", "full_name": "Fiona Gashi", "role": "STAFF", "is_active": True},
            {"id": "at", "full_name": "Arta Tafa", "role": "STAFF", "is_active": True},
            {"id": "admin", "full_name": "Besa Kola", "role": "ADMIN", "is_active": True},
        ],
        "items": {
            "blocked": [{"title": "EF: Blocked work", "date": "2026-09-28", "userId": "ef"}],
            "leave": [{"startDate": "2026-09-28", "endDate": "2026-09-28", "userId": "at"}],
            "absent": [],
        },
    }

    missing = _missing_blocked_initials(payload, date(2026, 9, 28))
    report_html = _html_table(
        [("BLL\n14:30 - 16:00\nRAP 16:10", payload["items"]["blocked"], False)],
        missing_blocked_initials=missing,
    )

    assert missing == ["FG", "RA"]
    assert 'data-missing-blocked-users="true"' in report_html
    assert "color:#DC2626" in report_html
    assert "RA" in report_html and "FG" in report_html
    assert "EF &bull;" not in report_html
    assert "AT &bull;" not in report_html

    generated = asyncio.run(build_today_print_report(date(2026, 9, 28), payload=payload))
    assert 'data-missing-blocked-users="true"' in generated["html"]
    assert "FG &bull; RA" in generated["html"]


@pytest.mark.parametrize("tomorrow", [False, True])
def test_blocked_row_separates_users_with_one_h_at_16_on_a_green_line(tomorrow: bool) -> None:
    payload = {
        "users": [
            {"id": user_id, "full_name": name, "role": "STAFF", "is_active": True}
            for user_id, name in [
                ("at", "Arta Tafa"), ("ef", "Era Fana"), ("ra", "Rina Aliu"),
                ("fg", "Fiona Gashi"), ("ep", "Elira Pula"), ("es", "Era Sopa"),
            ]
        ],
        "items": {
            "blocked": [{"title": "EF: BLL", "date": "2026-09-30", "userId": "ef"}],
            "oneH": [
                {"title": "AT: Test", "date": "2026-09-30", "oneHReportSlot": "16:00",
                 "assignees": ["Arta Tafa"]},
                {"title": "EF: Task", "date": "2026-09-30", "oneHReportSlot": "16:00", "userId": "ef"},
                {"title": "FG: Another day", "date": "2026-09-29", "oneHReportSlot": "16:00", "userId": "fg"},
                {"title": "EP: WFE", "date": "2026-09-30", "oneHReportSlot": "16:00",
                 "userId": "ep", "status": "WAITING_CLIENT"},
                {"title": "ES: On leave", "date": "2026-09-30", "oneHReportSlot": "16:00", "userId": "es"},
            ],
            "leave": [{"startDate": "2026-09-30", "endDate": "2026-09-30", "userId": "es"}],
        },
    }
    if tomorrow:
        report = asyncio.run(build_tomorrow_print_report(date(2026, 9, 29), payload=payload))
    else:
        report = asyncio.run(build_today_print_report(date(2026, 9, 30), payload=payload))
    red = re.search(r'<span data-missing-blocked-users="true"[^>]*>(.*?)</span>', report["html"])
    green = re.search(r'<span data-missing-blocked-with-one-h-at-16-users="true"[^>]*>(.*?)</span>', report["html"])

    assert red is not None and green is not None
    assert set(red.group(1).split(" &bull; ")) == {"EP", "FG", "RA"}
    assert green.group(1) == "AT"
    assert "display:block" in green.group(0) and "color:#15803D" in green.group(0)
    assert "color:#DC2626" in red.group(0)
    assert red.end() <= green.start()


def test_blocked_row_can_show_only_the_green_line() -> None:
    report_html = _html_table(
        [("BLL\n14:30 - 16:00\nRAP 16:10", [], False)],
        missing_blocked_initials=["AT", "RA"],
        missing_blocked_with_one_h_at_16_initials=["AT", "RA"],
    )
    assert 'data-missing-blocked-users="true"' not in report_html
    assert 'data-missing-blocked-with-one-h-at-16-users="true"' in report_html
    assert "AT &bull; RA" in report_html


@pytest.mark.parametrize("tomorrow", [False, True])
def test_one_h_at_16_separates_users_with_blocked_tasks_on_a_green_line(tomorrow: bool) -> None:
    payload = {
        "users": [
            {"id": user_id, "full_name": name, "role": "STAFF", "is_active": True}
            for user_id, name in [
                ("at", "Arta Tafa"), ("ef", "Era Fana"), ("ra", "Rina Aliu"),
                ("fg", "Fiona Gashi"), ("ep", "Elira Pula"), ("es", "Era Sopa"),
            ]
        ],
        "items": {
            "blocked": [
                {"title": "AT: BLL - test 1H 16:00", "date": "2026-09-30", "assignees": ["Arta Tafa"]},
                {"title": "EF: BLL", "date": "2026-09-30", "userId": "ef"},
                {"title": "FG: Another day", "date": "2026-09-29", "userId": "fg"},
                {"title": "EP: WFE", "date": "2026-09-30", "userId": "ep", "status": "WAITING_CLIENT"},
                {"title": "ES: On leave", "date": "2026-09-30", "userId": "es"},
            ],
            "oneH": [
                {"title": "AT: Another slot", "date": "2026-09-30", "oneHReportSlot": "10:00", "userId": "at"},
                {"title": "EF: Task", "date": "2026-09-30", "oneHReportSlot": "16:00", "userId": "ef"},
            ],
            "leave": [{"startDate": "2026-09-30", "endDate": "2026-09-30", "userId": "es"}],
        },
    }
    if tomorrow:
        report = asyncio.run(build_tomorrow_print_report(date(2026, 9, 29), payload=payload))
    else:
        report = asyncio.run(build_today_print_report(date(2026, 9, 30), payload=payload))
    slot_label = re.search(r'<th\b[^>]*>1H 16:00(.*?)</th>', report["html"], re.S).group(1)
    red = re.search(r'<span data-missing-one-h-users="true"[^>]*>(.*?)</span>', slot_label)
    green = re.search(r'<span data-missing-one-h-with-blocked-users="true"[^>]*>(.*?)</span>', slot_label)

    assert red is not None and green is not None
    assert set(red.group(1).split(" &bull; ")) == {"EP", "FG", "RA"}
    assert green.group(1) == "AT"
    assert "display:block" in green.group(0) and "color:#15803D" in green.group(0)
    assert red.end() <= green.start()
    assert report["html"].count('data-missing-one-h-with-blocked-users="true"') == 1


def test_one_h_blocked_green_line_is_only_for_the_16_slot_and_can_stand_alone() -> None:
    report_html = _html_table(
        [("1H 10:00", [], False), ("1H 16:00", [], False)],
        missing_one_h_by_slot={"10:00": ["AT"], "16:00": ["AT"]},
        missing_one_h_at_16_with_blocked_initials=["AT"],
    )
    early_label = report_html.split("1H 10:00", 1)[1].split("</th>", 1)[0]
    late_label = report_html.split("1H 16:00", 1)[1].split("</th>", 1)[0]
    assert 'data-missing-one-h-users="true"' in early_label
    assert 'data-missing-one-h-with-blocked-users="true"' not in early_label
    assert 'data-missing-one-h-users="true"' not in late_label
    assert 'data-missing-one-h-with-blocked-users="true"' in late_label


def test_missing_one_h_users_follow_the_same_department_and_person_order_as_tasks() -> None:
    payload = {
        "departments": [
            {"id": "pcm", "code": "PCM", "name": "Project Content Manager"},
            {"id": "gd", "code": "GD", "name": "Graphic Design"},
            {"id": "dev", "code": "DEV", "name": "Development"},
        ],
        "users": [
            {"id": "pcm-1", "full_name": "Bora Kola", "department_id": "pcm", "role": "STAFF",
             "is_active": True, "weekly_planner_sort_order": 0},
            {"id": "dev-2", "full_name": "Rina Aliu", "department_id": "dev", "role": "STAFF",
             "is_active": True, "weekly_planner_sort_order": 2},
            {"id": "gd-1", "full_name": "Fiona Gashi", "department_id": "gd", "role": "STAFF",
             "is_active": True, "weekly_planner_sort_order": 0},
            {"id": "dev-1", "full_name": "Era Fana", "department_id": "dev", "role": "STAFF",
             "is_active": True, "weekly_planner_sort_order": 1},
        ],
        "items": {"oneH": [], "leave": [], "absent": []},
    }

    missing = _missing_one_h_initials(payload, date(2026, 9, 8))

    assert missing["10:00"] == ["EF", "RA", "FG", "BK"]


def test_required_shtypi_recipients_are_always_in_to_without_duplicates() -> None:
    assert ensure_required_shtypi_recipient({
        "to": ["ga@primexeu.com"], "cc": ["info@primexeu.com"], "bcc": []
    }) == {
        "to": [
            "ga@primexeu.com",
            "130primex.eu@gmail.com",
            "313primex.eu@gmail.com",
            "131primex.eu@gmail.com",
            "info@primexeu.com",
        ],
        "cc": [],
        "bcc": [],
    }
    assert ensure_required_shtypi_recipient({
        "to": ["ga@primexeu.com", "313PRIMEX.EU@GMAIL.COM"],
        "cc": ["130PRIMEX.EU@GMAIL.COM"],
        "bcc": ["INFO@PRIMEXEU.COM"],
    }) == {
        "to": [
            "ga@primexeu.com",
            "313PRIMEX.EU@GMAIL.COM",
            "130primex.eu@gmail.com",
            "131primex.eu@gmail.com",
            "info@primexeu.com",
        ],
        "cc": [],
        "bcc": [],
    }


def test_shtypi_send_uses_dedicated_130_mailbox(monkeypatch) -> None:
    monkeypatch.setenv("EMAIL_USER", "315primex.eu@gmail.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "existing-130-password")
    smtp_calls = {}

    class FakeSmtp:
        def __init__(self, host, port, timeout):
            smtp_calls["connection"] = (host, port, timeout)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def ehlo(self):
            return None

        def starttls(self, **kwargs):
            return None

        def login(self, sender, password):
            smtp_calls["login"] = (sender, password)

        def send_message(self, message, *, from_addr, to_addrs):
            smtp_calls["from_header"] = message["From"]
            smtp_calls["from_addr"] = from_addr
            smtp_calls["to_addrs"] = to_addrs

    with patch("app.services.primeflow_report.smtplib.SMTP", FakeSmtp):
        asyncio.run(send_tomorrow_print_report(
            {"subject": "1H", "plain_text": "plain", "html": "<p>html</p>"},
            {"to": ["ga@primexeu.com"], "cc": [], "bcc": []},
        ))

    assert smtp_calls["login"] == (
        "130primex.eu@gmail.com", "existing-130-password"
    )
    assert smtp_calls["from_header"] == "130primex.eu@gmail.com"
    assert smtp_calls["from_addr"] == "130primex.eu@gmail.com"


def test_shtypi_send_requires_existing_email_password(monkeypatch) -> None:
    monkeypatch.delenv("EMAIL_PASSWORD", raising=False)

    with patch.object(settings, "EMAIL_PASSWORD", None):
        try:
            asyncio.run(send_tomorrow_print_report(
                {"subject": "1H", "plain_text": "plain", "html": "<p>html</p>"},
                {"to": ["ga@primexeu.com"], "cc": [], "bcc": []},
            ))
        except ValueError as exc:
            assert str(exc) == "Missing email configuration: EMAIL_PASSWORD"
        else:
            raise AssertionError("SHTYPI delivery must require the existing SMTP password")


def test_staff_comment_users_keep_fixed_order_then_pcm_weekly_plan_order() -> None:
    payload = {
        "departments": [
            {"id": "pcm", "code": "PCM", "name": "Project Content Manager"},
            {"id": "dev", "code": "DEV", "name": "Development"},
        ],
        "users": [
            {"full_name": "Zana Meta", "department_id": "pcm", "is_active": True,
             "weekly_planner_sort_order": 2},
            {"full_name": "Bora Kola", "department_id": "pcm", "is_active": True,
             "weekly_planner_sort_order": 0},
            {"full_name": "Inactive User", "department_id": "pcm", "is_active": False,
             "weekly_planner_sort_order": 1},
            {"full_name": "Dev User", "department_id": "dev", "is_active": True,
             "weekly_planner_sort_order": 0},
            {"full_name": "Elsa Hoxha", "department_id": "pcm", "is_active": True,
             "weekly_planner_sort_order": 1},
        ],
    }

    assert _comment_user_initials(payload) == ["AT", "EF", "RA", "EH", "LH", "FG", "BK", "ZM"]


def test_staff_comments_use_compact_write_in_lines_in_all_formats() -> None:
    initials = ["AT", "RA", "EF", "EH", "LH", "FG", "BK"]
    html = _comments_table_html(initials)
    assert 'data-user-comments-lines="true"' in html
    assert html.count('data-user-comment-line="true"') == 2
    assert html.count('data-comment-department=') == 2
    assert '<strong>DEV:</strong>' in html
    assert '<strong>PX:</strong>' in html
    assert '<strong>GD:</strong>' not in html
    assert '<strong>PCM:</strong>' not in html
    assert html.index("<strong>AT:</strong>") < html.index("<strong>EF:</strong>")
    assert html.index("<strong>EF:</strong>") < html.index("<strong>RA:</strong>")
    assert html.index("<strong>AT:</strong>") < html.index("<strong>BK:</strong>")
    assert html.count("data-user-comment=") == len(initials)
    assert html.count('width="100%"') >= 3
    assert "border-bottom:1px solid #111827" in html
    assert ">INC<" not in html
    assert ">KOM<" not in html

    _, workbook_bytes, _ = _excel_table_attachment(
        [], [], date(2026, 8, 14), include_meetings=False, comment_initials=initials
    )
    sheet = load_workbook(BytesIO(workbook_bytes)).active
    title_cells = [cell for row in sheet.iter_rows() for cell in row if cell.value == "KOMENTE PER STAF"]
    assert len(title_cells) == 1
    title_row = title_cells[0].row
    assert sheet.cell(title_row + 1, 1).value.startswith("DEV: AT: ____________________")
    assert "EF: ____________________" in sheet.cell(title_row + 1, 1).value
    assert "LH: ____________________" in sheet.cell(title_row + 1, 1).value
    assert sheet.cell(title_row + 2, 1).value.startswith("PX: FG: ____________________")
    assert "BK: ____________________" in sheet.cell(title_row + 2, 1).value
    assert "GD:" not in sheet.cell(title_row + 2, 1).value
    assert "PCM:" not in sheet.cell(title_row + 2, 1).value
    values = [str(cell.value or "") for row in sheet.iter_rows() for cell in row]
    assert "INC" not in values
    assert "KOM" not in values

    _, png, _ = _png_table_attachment([], date(2026, 8, 14), initials)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_html_table_keeps_grid_styles_inline_for_email_clients() -> None:
    report_html = _html_table(
        [("P", [{"title": "DM/GA: A task"}, {"title": "ER: A task"}], True)]
    )

    assert '<table role="presentation" width="100%" border="1"' in report_html
    assert 'style="width:100%;border-collapse:collapse;table-layout:fixed' in report_html
    assert 'style="border:1px solid #000;padding:5px' in report_html
    assert '<col width="2.5%"><col width="10.5%"><col width="14.5%" span="6">' in report_html
    assert ">LLOJI DHE SLOTI</th>" in report_html
    assert '<th colspan="6"' in report_html
    assert ">TASKS</th>" in report_html
    assert ">TASK 1</th>" not in report_html
    assert ">TASK 6</th>" not in report_html
    assert 'bgcolor="#D8B4FE"' in report_html
    assert report_html.count('background-color:#D8B4FE') == 2
    assert 'data-task-card-row="content"' in report_html
    assert 'data-task-card-row="dates"' in report_html
    assert '<style>' not in report_html


def test_html_table_marks_important_deadline_tasks_for_filtering() -> None:
    report_html = _html_table(
        [("1H 10:00", [
            {"task_id": "important", "title": "Important", "is_deadline_important": True,
             "start_date": "2026-09-29", "created_at": "2026-09-20T08:00:00"},
            {"task_id": "regular", "title": "Regular", "is_deadline_important": False,
             "start_date": "2026-09-28"},
        ], False)],
        report_date=date(2026, 9, 29),
    )

    assert ('data-task-id="important" data-task-marker="" '
            'data-task-deadline-important="true" data-task-starts-today="true"') in report_html
    assert ('data-task-id="regular" data-task-marker="" '
            'data-task-deadline-important="false" data-task-starts-today="false"') in report_html


def test_task_title_text_is_larger_and_sits_lower_without_changing_cell_layout() -> None:
    report_html = _html_table(
        [("1H 10:00", [{"title": "GA: A task", "finishPeriod": "AM"}], False)]
    )

    assert (
        '<span data-task-title-text="true" style="display:inline-block;font-size:17px;line-height:1.25;padding-top:4px">'
        '1. A task</span>'
    ) in report_html
    assert '<col width="2.5%"><col width="10.5%"><col width="14.5%" span="6">' in report_html
    assert 'border:1px solid #000;padding:5px;vertical-align:top;text-align:left' in report_html
    assert 'vertical-align:bottom;height:25px' in report_html


def test_meeting_titles_are_larger_and_sit_lower_in_print_tables() -> None:
    report_html = _html_table(
        [("TAK EXT", [{"title": "Client meeting", "time": "10:00"}], False)],
        meeting=True,
    )

    assert "font-size:14px;line-height:1.3;padding-top:8px" in report_html
    assert "1. Client meeting 10:00" in report_html


def test_task_grid_uses_light_dividers_inside_a_slot_and_bold_slot_labels() -> None:
    report_html = _html_table(
        [("BLL", [{"title": f"Task {index}"} for index in range(7)], False)]
    )

    assert "border-top:2px solid #111827" in report_html
    assert "border-top:1px solid #cbd5e1" in report_html
    assert "border-bottom:2px solid #111827" in report_html
    assert "border:3px solid #111827" in report_html
    assert "border-top:3px solid #111827;border-bottom:3px solid #111827" in report_html
    assert 'style="border:1px solid #000;padding:5px;vertical-align:top;text-align:left;overflow-wrap:anywhere;word-break:break-word;font-weight:700;border-top:2px solid #111827;border-bottom:2px solid #111827">BLL</th>' in report_html


def test_excel_task_grid_has_thick_header_outer_frame_and_category_edges() -> None:
    _, content, _ = _excel_table_attachment(
        [
            ("1H 10:00", [{"title": f"Task {index}"} for index in range(7)], False),
            ("1H 11:00", [{"title": "Next task"}], False),
        ],
        [],
        date(2026, 8, 14),
        include_meetings=False,
    )
    sheet = load_workbook(BytesIO(content)).active

    # Row 6 is the task header; rows 7-8 are one multi-line category; row 9 is the next category.
    assert sheet["A6"].border.top.style == "medium"
    assert sheet["A6"].border.bottom.style == "medium"
    assert sheet["A6"].border.left.style == "medium"
    assert sheet["H6"].border.right.style == "medium"
    assert sheet["C7"].border.top.style == "medium"
    assert sheet["C7"].border.bottom.style == "thin"
    assert sheet["C8"].border.top.style == "thin"
    assert sheet["C8"].border.bottom.style == "medium"
    assert sheet["C9"].border.top.style == "medium"
    assert sheet["C9"].border.bottom.style == "medium"
    assert sheet["A9"].border.left.style == "medium"
    assert sheet["H9"].border.right.style == "medium"


def test_one_h_checklists_render_side_by_side_before_the_task_grid() -> None:
    checklists_html = _one_h_checklists_html()

    assert checklists_html.count("PYETJET SHTESE: 0") == 1
    assert 'data-day-specific-question-label="true"' in checklists_html
    assert 'data-day-specific-checklist-columns="true"' not in checklists_html
    assert 'data-one-h-checklist-columns="true"' in checklists_html
    assert 'width="50%"' in checklists_html
    assert "PYETJET PER 1H - BORD" in checklists_html
    assert "STAFF - HAPAT PER 1H" in checklists_html
    assert "Slotin paraprak/aktual" in checklists_html
    assert 'data-board-checklist-columns="true"' in checklists_html
    assert "1. Notes te reja? Data? AM/PM? Kujt" in checklists_html
    assert "2. Done? / Strikes?" in checklists_html
    assert "3. BZ Det nga Stafi per GA" in checklists_html
    assert "4. BZ Notes" in checklists_html
    assert "Secili i lexon vet para BZ me GA" in checklists_html
    assert "Share screen side by side DET/REZULTATIN" in checklists_html
    assert "4. BZ Det nga Stafi per GA" in checklists_html
    assert "Komunikimi GA teams Det nga Stafi/ KA email" in checklists_html
    assert checklists_html.count('data-compact-checklist-row="true"') == 2
    assert checklists_html.index('data-board-checklist-section="follow-up"') < checklists_html.index('data-board-checklist-section="primary"')
    assert 'font-size:20px;font-weight:900' in checklists_html

    _, content, _ = _excel_table_attachment([], [], date(2026, 8, 14))
    sheet = load_workbook(BytesIO(content)).active
    assert sheet["A2"].value == "PYETJET SHTESE: 0"
    assert sheet["A3"].value == "STAFF - HAPAT PER 1H"
    assert sheet["E3"].value == "PYETJET PER 1H - BORD"
    assert sheet["A4"].value.startswith("1. Hap doc dhe det / 2. Share screen")
    assert "4. BZ Det nga Stafi per GA (Komunikimi GA teams Det nga Stafi/ KA email)" in sheet["A4"].value
    assert sheet["E4"].value == "1. Notes te reja? Data? AM/PM? Kujt / 2. Done? / Strikes? / 3. BZ Det nga Stafi per GA (Komunikimi GA teams Det nga Stafi/ KA email) / 4. BZ Notes (Secili i lexon vet para BZ me GA)"
    assert sheet["E5"].value.startswith("1. Slotin paraprak/aktual / 2. A ke filluar")
    assert sheet["B6"].value == "LLOJI DHE SLOTI"
    assert sheet["C6"].value == "TASKS"
    assert "C6:H6" in {str(cell_range) for cell_range in sheet.merged_cells.ranges}


def test_thursday_checklists_add_week_closing_questions_in_html_and_excel() -> None:
    thursday = date(2026, 9, 3)
    checklists_html = _one_h_checklists_html(thursday)

    assert "Planifikimi javor short" in checklists_html
    assert "Emails per missing info, per me vazhdu javen tjeter" in checklists_html
    assert "Shikohen det qe mbesin vetem per neser (te premten)" in checklists_html
    assert checklists_html.count("E ENJTE- PYETJET E TE ENJTES") == 1
    weekday_row = re.search(r'<div data-day-specific-question-label="true".*?</div>', checklists_html).group()
    assert "Emails per missing info" in weekday_row
    assert "Planifikimi javor short" in weekday_row
    assert '<span data-extra-checklist-question="true" style="display:inline;"><strong>M1 - 1. Planifikimi javor short</strong></span>' in checklists_html
    assert '<span data-extra-checklist-question="true" style="display:inline;"><strong>M1 - 1. Emails per missing info, per me vazhdu javen tjeter</strong></span>' in checklists_html
    assert '<span data-extra-checklist-question="true" style="display:inline;"><strong>M3 - 2. Shikohen det qe mbesin vetem per neser (te premten)</strong></span>' in checklists_html
    assert checklists_html.index("E ENJTE- PYETJET E TE ENJTES") < checklists_html.index("Emails per missing info")
    assert checklists_html.index("Shikohen det qe mbesin") < checklists_html.index("STAFF - HAPAT PER 1H")
    assert checklists_html.index("Planifikimi javor short") < checklists_html.index("PYETJET PER 1H - BORD")
    assert 'data-day-specific-question-label="true"' in checklists_html
    assert 'data-day-specific-checklist-columns="true"' in checklists_html

    _, content, _ = _excel_table_attachment([], [], date(2026, 9, 4), checklist_date=thursday)
    sheet = load_workbook(BytesIO(content)).active
    compact = str(sheet["A3"].value)
    assert compact.startswith("E ENJTE- PYETJET E TE ENJTES  M1 - 1.")
    assert "M3 - 2. Shikohen det qe mbesin" in compact
    assert "M1 - 1. Planifikimi javor short" in compact
    assert sheet["A4"].value == "STAFF - HAPAT PER 1H"
    assert sheet["A5"].value.startswith("1. Hap doc dhe det")
    assert sheet["A3"].font.color.rgb == "00B91C1C"
    assert sheet["A3"].fill.fgColor.rgb == "00FFF7F7"


def test_tomorrow_report_uses_target_day_for_thursday_questions() -> None:
    import asyncio

    sent_wednesday = asyncio.run(
        build_tomorrow_print_report(
            date(2026, 9, 2), include_attachment=True, payload={"items": {}}
        )
    )
    sent_tuesday = asyncio.run(
        build_tomorrow_print_report(date(2026, 9, 1), payload={"items": {}})
    )

    assert sent_wednesday["target_date"] == "2026-09-03"
    assert "Planifikimi javor short" in sent_wednesday["html"]
    assert "Emails per missing info, per me vazhdu javen tjeter" in sent_wednesday["plain_text"]
    assert sent_wednesday["plain_text"].count("E ENJTE- PYETJET E TE ENJTES") == 1
    assert "Planifikimi javor short" not in sent_tuesday["html"]
    assert "PYETJET SHTESE: 0" in sent_tuesday["html"]
    assert "PYETJET SHTESE: 0" in sent_tuesday["plain_text"]
    thursday_excel = load_workbook(BytesIO(sent_wednesday["attachments"][0][1])).active
    thursday_excel_values = [
        str(cell.value or "") for row in thursday_excel.iter_rows() for cell in row
    ]
    assert any(value.startswith("E ENJTE- PYETJET E TE ENJTES") for value in thursday_excel_values)
    assert any("Planifikimi javor short" in value for value in thursday_excel_values)
    assert any("Shikohen det qe mbesin vetem per neser" in value for value in thursday_excel_values)


def test_friday_checklists_add_staff_questions_and_keep_board_unchanged() -> None:
    friday = date(2026, 9, 4)
    checklists_html = _one_h_checklists_html(friday)

    assert checklists_html.index("BZ PERSONALISHT ME GA: KOMENTET TEK OPEN TASKS EXCEL") < checklists_html.index("BZ PERSONALISHT ME GA: DET GA TEK PER/NGA STAFI PER GA TEAMS") < checklists_html.index("Barazimi i planifikimit")
    assert "Barazimi i planifikimit javor - next week" in checklists_html
    assert "Barazimi i realizimit javor - this week" in checklists_html
    assert "Emails per missing info, per me vazhdu javen tjeter" in checklists_html
    assert "Planifikimi javor short" not in checklists_html
    assert checklists_html.count("E PREMTE") == 1
    weekday_row = re.search(r'<div data-day-specific-question-label="true".*?</div>', checklists_html).group()
    assert "BZ PERSONALISHT ME GA: KOMENTET TEK OPEN TASKS EXCEL" in weekday_row
    assert "Emails per missing info" in weekday_row
    assert '<span data-extra-checklist-question="true" style="display:inline;"><strong>M1 - 3. Barazimi i planifikimit javor - next week</strong></span>' in checklists_html
    assert '<span data-extra-checklist-question="true" style="display:inline;"><strong>M1 - 4. Barazimi i realizimit javor - this week</strong></span>' in checklists_html
    assert '<span data-extra-checklist-question="true" style="display:inline;"><strong>M1 - 5. Emails per missing info, per me vazhdu javen tjeter</strong></span>' in checklists_html
    assert checklists_html.index("E PREMTE") < checklists_html.index("Barazimi i planifikimit")
    assert checklists_html.index("Emails per missing info") < checklists_html.index("STAFF - HAPAT PER 1H")

    _, content, _ = _excel_table_attachment([], [], date(2026, 9, 7), checklist_date=friday)
    sheet = load_workbook(BytesIO(content)).active
    compact = str(sheet["A3"].value)
    assert compact.startswith("E PREMTE  M1 - 1. BZ PERSONALISHT ME GA: KOMENTET TEK OPEN TASKS EXCEL")
    assert "M1 - 2. BZ PERSONALISHT ME GA: DET GA TEK PER/NGA STAFI PER GA TEAMS" in compact
    assert "M1 - 3. Barazimi i planifikimit" in compact
    assert "M1 - 4. Barazimi i realizimit" in compact
    assert "M1 - 5. Emails per missing info" in compact
    assert sheet["A4"].value == "STAFF - HAPAT PER 1H"
    assert sheet["A5"].value.startswith("1. Hap doc dhe det")



def test_tomorrow_report_uses_target_day_for_friday_questions() -> None:
    import asyncio

    report = asyncio.run(
        build_tomorrow_print_report(
            date(2026, 9, 3), include_attachment=True, payload={"items": {}}
        )
    )

    assert report["plain_text"].count("E PREMTE") == 1

    assert report["target_date"] == "2026-09-04"
    assert "Barazimi i planifikimit javor - next week" in report["html"]
    assert "Barazimi i realizimit javor - this week" in report["plain_text"]
    friday_excel = load_workbook(BytesIO(report["attachments"][0][1])).active
    friday_excel_values = [
        str(cell.value or "") for row in friday_excel.iter_rows() for cell in row
    ]
    assert any(value.startswith("E PREMTE") for value in friday_excel_values)
    assert any("Barazimi i planifikimit javor - next week" in value for value in friday_excel_values)
    assert any("Barazimi i realizimit javor - this week" in value for value in friday_excel_values)


def test_tomorrow_report_sent_friday_does_not_use_friday_questions_for_monday() -> None:
    report = asyncio.run(
        build_tomorrow_print_report(date(2026, 9, 4), payload={"items": {}})
    )

    assert report["target_date"] == "2026-09-07"
    assert "E PREMTE" not in report["html"]
    assert "Barazimi i planifikimit javor - next week" not in report["html"]
    assert report["html"].count("PYETJET SHTESE: 0") == 1
    assert report["plain_text"].count("PYETJET SHTESE: 0") == 1


def test_today_report_puts_thursday_questions_under_the_weekday_title() -> None:
    report = asyncio.run(
        build_today_print_report(date(2026, 9, 3), payload={"items": {}})
    )

    html = report["html"]
    assert report["target_date"] == "2026-09-03"
    assert html.index("E ENJTE- PYETJET E TE ENJTES") < html.index("Emails per missing info")
    assert html.index("Shikohen det qe mbesin") < html.index("STAFF - HAPAT PER 1H")
    assert html.index("Planifikimi javor short") < html.index("PYETJET PER 1H - BORD")
    assert html.count('data-day-specific-question-label="true"') == 1


def test_email_table_removes_added_and_done_editor_markers() -> None:
    report_html = _html_table(
        [("1H 10:00", [{"title": "LH: [[added]]New[[/added]] [[done]]completed[[/done]] task"}], False)]
    )

    assert "[[added]]" not in report_html
    assert "[[/added]]" not in report_html
    assert "[[done]]" not in report_html
    assert "[[/done]]" not in report_html
    assert "New completed task" in report_html


def test_downloadable_email_table_uses_clean_task_text() -> None:
    filename, content, mime_type = _excel_table_attachment(
        [("1H 10:00", [{"title": "LH: [[added]]New task[[/added]]"}], False)],
        [("TAK EXT", [{"title": "[[added]]Meeting[[/added]]", "time": "10:00"}], False)],
        date(2026, 8, 14),
    )

    workbook = load_workbook(BytesIO(content))
    values = [str(cell.value or "") for row in workbook.active.iter_rows() for cell in row]
    assert filename == "1H_SHTYPI_2026-08-14.xlsx"
    assert mime_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert any("New task" in value for value in values)
    assert any("Meeting 10:00" in value for value in values)
    assert not any("[[added]]" in value or "[[/added]]" in value for value in values)


def test_task_status_colours_apply_to_email_cells_but_ga_personal_stays_purple() -> None:
    report_html = _html_table(
        [
            (
                "1H 10:00",
                [
                    {"title": "TODO task", "status": "TODO"},
                    {"title": "Progress task", "status": "IN_PROGRESS"},
                    {"title": "Waiting task", "status": "WAITING_CONFIRMATION"},
                    {"title": "Done task", "status": "DONE"},
                ],
                False,
            ),
            ("P", [{"title": "GA: Personal task", "status": "TODO"}], True),
        ]
    )

    assert 'bgcolor="#FFC4ED"' in report_html
    assert 'bgcolor="#FFFF00"' in report_html
    assert 'bgcolor="#FFEDD5"' in report_html
    assert 'bgcolor="#C4FDC4"' in report_html
    assert 'bgcolor="#D8B4FE"' in report_html


def test_task_cards_show_their_am_pm_period_in_email_and_excel() -> None:
    tasks = [
        {"title": "Morning task", "finishPeriod": "AM"},
        {"title": "Afternoon task", "finish_period": "pm"},
        {"title": "Unscheduled period"},
    ]

    report_html = _html_table([("1H 10:00", tasks, False)])

    assert report_html.count('data-task-badge="finish-period"') == 3
    assert 'data-task-badge="finish-period" style=' in report_html
    assert '>AM</span>' in report_html
    assert '>PM</span>' in report_html
    assert '>AM/PM</span>' in report_html
    assert "background-color:#E0F2FE" in report_html
    assert "border:1px solid #BAE6FD" in report_html
    assert "color:#0369A1" in report_html
    assert "border-radius:999px" in report_html

    _, content, _ = _excel_table_attachment(
        [("1H 10:00", tasks, False)], [], date(2026, 8, 14)
    )
    sheet = load_workbook(BytesIO(content)).active
    assert "[AM]\n" in sheet["C7"].value
    assert "[PM]\n" in sheet["D7"].value
    assert "[AM/PM]\n" in sheet["E7"].value

    _, png, _ = _png_table_attachment(
        [("1H 10:00", tasks, False)], date(2026, 8, 14)
    )
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_one_h_marker_is_a_separate_badge_next_to_am_pm() -> None:
    tasks = [
        {"taskId": "flagged", "title": "Flagged task", "finishPeriod": "AM", "one_h_marker": "FLAG"},
        {"taskId": "monitor", "title": "Question task", "finishPeriod": "PM", "oneHMarker": "MONITOR", "oneHMarkerComment": "Check again with KA"},
        {"taskId": "ga-question", "title": "GA question task", "finishPeriod": "AM", "one_h_marker": "QUESTION", "one_h_marker_by_ga": True},
    ]

    report_html = _html_table([("1H 10:00", tasks, False)])

    assert report_html.count('data-task-badge="finish-period"') == 3
    assert report_html.count('data-task-badge="one-h-marker"') == 3
    assert '>GA</span>' in report_html
    assert '>(?)</span>' in report_html
    assert 'data-task-badge="finish-period"' in report_html
    assert 'data-task-badge="one-h-marker"' in report_html
    assert ">👁</span>" in report_html
    assert "COM:</strong> Check again with KA" in report_html
    assert 'data-task-marker-comment="Check again with KA"' in report_html
    assert report_html.index("COM:</strong> Check again with KA") < report_html.index("2. Question task")
    assert "width:fit-content;max-width:min(100%,150px)" in report_html
    assert "white-space:nowrap;overflow:hidden;text-overflow:ellipsis" in report_html
    assert 'title="Check again with KA"' in report_html
    assert "border:1px solid #BFDBFE" in report_html
    assert "background:#EFF6FF" in report_html

    _, content, _ = _excel_table_attachment(
        [("1H 10:00", tasks, False)], [], date(2026, 8, 14)
    )
    sheet = load_workbook(BytesIO(content)).active
    assert "[AM] [GA]\n" in sheet["C7"].value
    assert "[PM] [👁]\n" in sheet["D7"].value
    assert "COM: Check again with KA" in sheet["D7"].value
    assert sheet["D7"].value.index("COM: Check again with KA") < sheet["D7"].value.index("Question task")
    assert "[AM] (?)\n" in sheet["E7"].value


def test_0800_and_am_pm_badges_keep_their_distinct_designs_together() -> None:
    report_html = _html_table(
        [(
            "1H NO SLOT",
            [{"title": "08:00 Combined task", "finishPeriod": None, "status": "DONE"}],
            False,
        )],
        report_date=date(2026, 8, 14),
    )

    assert report_html.count('data-task-badge="finish-period"') == 1
    assert report_html.count('data-task-badge="08:00"') == 1
    assert "background-color:#E0F2FE;border:1px solid #BAE6FD;color:#0369A1" in report_html
    assert "background-color:#DC2626;border:1px solid #B91C1C;color:#FFFFFF" in report_html


def test_em_title_without_time_is_treated_as_0800() -> None:
    report_html = _html_table(
        [("1H NO SLOT", [{"title": "EF: EM TEST", "status": "TODO"}], False)],
        report_date=date(2026, 8, 14),
    )

    assert 'data-task-badge="08:00"' in report_html


def test_deadline_and_0800_tasks_are_highlighted_in_email_and_excel() -> None:
    tasks = [
        {
            "title": "Deadline task",
            "status": "TODO",
            "is_deadline_important": True,
            "start_date": "2026-08-13T08:00:00+02:00",
            "due_date": "2026-08-14T16:00:00+02:00",
        },
        {
            "title": "Morning task", "status": "TODO",
            "created_at": "2026-08-14T07:00:00+02:00",
            "start_date": "2026-08-14T08:00:00+02:00",
            "due_date": "2026-08-14T08:00:00+02:00",
        },
    ]
    report_html = _html_table([("DEADLINE / 08:00", tasks, False)], report_date=date(2026, 8, 14))

    assert 'bgcolor="#DC2626"' in report_html
    assert 'bgcolor="#FFC4ED"' in report_html
    assert "border:2px solid #DC2626" in report_html
    assert 'data-task-badge="08:00"' in report_html
    assert report_html.count('data-task-badge="start-date"') == 2
    assert report_html.count('data-task-badge="start-today"') == 1
    assert report_html.count('data-task-badge="due-date"') == 2
    assert 'data-badge-position="bottom-right"' in report_html
    assert 'data-due-today="true"' in report_html
    assert ">13.08.2026</span>" in report_html
    assert report_html.count(">14.08.2026</span>") == 1
    assert report_html.count(">SOT</span>") == 2
    assert report_html.count(">START SOT</span>") == 1
    assert "DUE TODAY" not in report_html
    assert "background-color:#EFF6FF" in report_html
    assert "border:1px solid #93C5FD" in report_html
    assert "color:#1D4ED8" in report_html
    assert "background-color:#DC2626" in report_html
    assert "border:1px solid #B91C1C" in report_html
    assert "color:#FFFFFF" in report_html
    assert "height:26px" in report_html
    assert "padding:3px 9px" in report_html
    assert "font-size:14px" in report_html
    assert "font-weight:900" in report_html
    assert "box-shadow:0 1px 3px rgba(127,29,29,0.45)" in report_html


    assert 'data-task-card-row="dates"' in report_html
    assert 'height="25" valign="bottom"' in report_html
    assert 'align="left"' in report_html
    assert 'align="right"' in report_html
    assert 'height="19" valign="bottom"' in report_html
    assert "position:absolute" not in report_html

    _, content, _ = _excel_table_attachment([("DEADLINE / 08:00", tasks, False)], [], date(2026, 8, 14))
    sheet = load_workbook(BytesIO(content)).active
    assert sheet["C7"].fill.fgColor.rgb.endswith("DC2626")
    assert "[START: 13.08.2026]" in sheet["C7"].value
    assert "[DUE: SOT]" in sheet["C7"].value
    assert "[START: 14.08.2026]" in sheet["D7"].value
    assert "[DUE: SOT]" in sheet["D7"].value
    assert "DUE TODAY" not in sheet["C7"].value
    assert "[08:00]" in sheet["D7"].value
    assert sheet["D7"].border.left.color.rgb.endswith("DC2626")


def test_start_today_badge_is_directly_above_start_date() -> None:
    top_badges, date_badges = _task_badges_html(
        {"created_at": "2026-08-14T07:00:00+02:00", "start_date": "2026-08-14", "due_date": "2026-08-14"},
        date(2026, 8, 14),
    )

    assert 'data-task-badge="start-today"' not in top_badges
    assert date_badges.index('data-task-badge="start-today"') < date_badges.index('data-task-badge="start-date"')
    assert '>START SOT</span><span data-task-badge="start-date"' in date_badges

    for task in (
        {"created_at": "2026-08-13T07:00:00+02:00", "start_date": "2026-08-14", "due_date": "2026-08-14"},
        {"created_at": "2026-08-14T07:00:00+02:00", "start_date": "2026-08-13", "due_date": "2026-08-14"},
        {"created_at": "2026-08-14T07:00:00+02:00", "start_date": "2026-08-14", "due_date": "2026-08-15"},
    ):
        _, badges = _task_badges_html(task, date(2026, 8, 14))
        assert 'data-task-badge="start-today"' not in badges


def test_ga_personal_purple_overrides_deadline_red_in_email_and_excel() -> None:
    ga_deadline = {
        "title": "EF/GA: Personal deadline",
        "status": "TODO",
        "is_deadline_important": True,
        "due_date": "2026-08-14",
    }
    other_deadline = {
        "title": "ER/KA: Personal deadline",
        "status": "TODO",
        "is_deadline_important": True,
        "due_date": "2026-08-14",
    }
    rows = [("P: GA", [ga_deadline], True), ("P: KA", [other_deadline], True)]

    report_html = _html_table(rows, report_date=date(2026, 8, 14))
    assert 'bgcolor="#D8B4FE"' in report_html
    assert 'bgcolor="#DC2626"' in report_html
    assert report_html.count('data-task-badge="due-date"') == 2
    assert report_html.count(">SOT</span>") == 2

    _, content, _ = _excel_table_attachment(rows, [], date(2026, 8, 14))
    sheet = load_workbook(BytesIO(content)).active
    assert sheet["C7"].fill.fgColor.rgb.endswith("D8B4FE")
    assert sheet["C8"].fill.fgColor.rgb.endswith("DC2626")


def test_done_task_stays_green_even_when_it_is_a_deadline() -> None:
    task = {
        "title": "EH: 08:00 DERGO EMAIL STD",
        "status": "DONE",
        "isDone": True,
        "is_deadline_important": True,
        "due_date": "2026-09-03",
    }
    rows = [("1H 10:00", [task], False)]

    report_html = _html_table(rows, report_date=date(2026, 9, 3))
    assert 'bgcolor="#C4FDC4"' in report_html
    assert 'bgcolor="#DC2626"' not in report_html
    assert 'data-due-today="true"' in report_html
    assert "background-color:#DC2626" in report_html
    assert "border:1px solid #991B1B" in report_html
    assert "color:#FFFFFF" in report_html
    assert ">SOT</span>" in report_html

    _, content, _ = _excel_table_attachment(rows, [], date(2026, 9, 3))
    sheet = load_workbook(BytesIO(content), rich_text=True).active
    assert sheet["C7"].fill.fgColor.rgb.endswith("C4FDC4")


def test_wfc_title_token_is_red_and_uses_white_highlight_on_red_deadline_cards() -> None:
    rows = [
        ("1H 10:00", [{"title": "EF: PF: WFC TEST P", "status": "TODO"}], False),
        (
            "1H 11:00",
            [{"title": "EF: PF: WFC DEADLINE", "is_deadline_important": True, "due_date": "2026-08-14"}],
            False,
        ),
        (
            "P: GA",
            [{"title": "EF/GA: WFC PERSONAL", "is_deadline_important": True, "due_date": "2026-08-14"}],
            True,
        ),
    ]

    report_html = _html_table(rows, report_date=date(2026, 8, 14))
    assert report_html.count('data-task-token="wfc"') == 3
    assert report_html.count("color:#DC2626;font-weight:800;") == 3
    assert report_html.count("background-color:#FFFFFF;border-radius:2px;padding:0 2px;") == 1
    assert 'bgcolor="#DC2626"' in report_html
    assert 'bgcolor="#D8B4FE"' in report_html

    _, content, _ = _excel_table_attachment(rows, [], date(2026, 8, 14))
    sheet = load_workbook(BytesIO(content), rich_text=True).active
    assert isinstance(sheet["C7"].value, CellRichText)
    assert isinstance(sheet["C8"].value, CellRichText)
    assert isinstance(sheet["C9"].value, CellRichText)
    normal_wfc = next(block for block in sheet["C7"].value if getattr(block, "text", "") == "WFC")
    red_card_wfc = next(block for block in sheet["C8"].value if getattr(block, "text", "") == "WFC")
    purple_card_wfc = next(block for block in sheet["C9"].value if getattr(block, "text", "") == "WFC")
    assert normal_wfc.font.color.rgb == "FFDC2626"
    assert red_card_wfc.font.color.rgb == "FFFFFF00"
    assert purple_card_wfc.font.color.rgb == "FFDC2626"


def test_future_deadline_uses_the_due_date_chip_on_the_red_cell() -> None:
    report_html = _html_table(
        [
            (
                "1H 10:00",
                [{"title": "Future deadline", "is_deadline_important": True, "due_date": "2026-08-15"}],
                False,
            )
        ],
        report_date=date(2026, 8, 14),
    )

    assert 'data-due-today="false"' in report_html
    assert ">15.08.2026</span>" in report_html
    assert "DUE" not in report_html
    assert 'bgcolor="#DC2626"' in report_html
    assert "border:3px solid #B91C1C" in report_html
    assert "background-color:#EFF6FF" in report_html
    assert "color:#1D4ED8" in report_html


def test_overdue_deadline_uses_the_due_date_chip_on_the_red_cell() -> None:
    report_html = _html_table(
        [(
            "1H 10:00",
            [{"title": "Overdue", "is_deadline_important": True, "due_date": "2026-08-13"}],
            False,
        )],
        report_date=date(2026, 8, 14),
    )

    assert 'bgcolor="#DC2626"' in report_html
    assert ">13.08.2026</span>" in report_html
    assert "border:3px solid #B91C1C" in report_html
    assert "background-color:#EFF6FF" in report_html
    assert "color:#1D4ED8" in report_html
    assert "DUE" not in report_html


def test_deadline_and_0800_tasks_have_a_dedicated_printed_row() -> None:
    rows = _task_rows(
        {
            "important": [
                {"title": "Deadline task", "date": "2026-08-14", "is_deadline_important": True},
                {"title": "08:00 task", "date": "2026-08-14"},
            ]
        },
        date(2026, 8, 14),
    )

    important_row = next(row for row in rows if row[0] == "DEADLINE / 08:00")
    assert [item["title"] for item in important_row[1]] == ["Deadline task", "08:00 task"]


def test_wfe_tasks_move_to_a_dedicated_row_without_duplicates() -> None:
    rows = _task_rows(
        {
            "oneH": [
                {
                    "title": "WFE 1H task",
                    "date": "2026-08-14",
                    "status": "WAITING_CLIENT",
                    "oneHReportSlot": "10:00",
                    "finishPeriod": "AM",
                    "oneHMarker": "QUESTION",
                },
                {
                    "title": "Regular 1H task",
                    "date": "2026-08-14",
                    "status": "TODO",
                    "oneHReportSlot": "10:00",
                },
            ],
            "blocked": [
                {"title": "Legacy WFE task", "date": "2026-08-14", "status": "WFE"},
            ],
            "personal": [
                {"title": "GA: Waiting for client", "date": "2026-08-14", "status": "WAITING_FOR_CLIENT"},
            ],
        },
        date(2026, 8, 14),
    )

    wfe_index = next(index for index, row in enumerate(rows) if row[0] == "WFE")
    blocked_index = next(index for index, row in enumerate(rows) if row[0].startswith("BLL"))
    assert wfe_index < blocked_index
    assert {item["title"] for item in rows[wfe_index][1]} == {
        "WFE 1H task",
        "Legacy WFE task",
        "GA: Waiting for client",
    }
    assert [item["title"] for item in rows[0][1]] == ["Regular 1H task"]
    assert sum(
        item["title"] == "WFE 1H task"
        for _, row_items, _ in rows
        for item in row_items
    ) == 1

    report_html = _html_table(rows, report_date=date(2026, 8, 14))
    assert ">WFE<" in report_html
    assert 'data-task-badge="finish-period"' in report_html
    assert 'data-task-badge="one-h-marker"' in report_html


def test_personal_tasks_are_split_exclusively_into_ga_ka_gent_and_px_rows() -> None:
    rows = _task_rows(
        {
            "personal": [
                {"title": "EF/GA: WFC", "date": "2026-08-14"},
                    {"title": "GA/KA: KA wins", "date": "2026-08-14"},
                {"title": "ER: KA: Teams", "date": "2026-08-14"},
                {"title": "ER/GENT: Personal Gent", "date": "2026-08-14"},
                {"title": "ER/GENTI: Personal Genti", "date": "2026-08-14"},
                {"title": "ER/GT: Personal GT", "date": "2026-08-14"},
                {"title": "EP/ESH: Personal PX", "date": "2026-08-14"},
                {"title": "Personal task without initials", "date": "2026-08-14"},
            ]
        },
        date(2026, 8, 14),
    )
    personal_rows = [row for row in rows if row[2]]

    assert [row[0] for row in personal_rows] == [
        "P: GA\n08:15 / 13:15",
        "P: KA\n08:30 / 13:15",
        "P: GENT",
        "P: PX\n08:45 / 14:00",
    ]
    assert {item["title"] for item in personal_rows[0][1]} == {"EF/GA: WFC"}
    assert {item["title"] for item in personal_rows[1][1]} == {"GA/KA: KA wins", "ER: KA: Teams"}
    assert {item["title"] for item in personal_rows[2][1]} == {
        "ER/GENT: Personal Gent",
        "ER/GENTI: Personal Genti",
        "ER/GT: Personal GT",
    }
    assert {item["title"] for item in personal_rows[3][1]} == {
        "EP/ESH: Personal PX",
        "Personal task without initials",
    }
    assert sum(len(row[1]) for row in personal_rows) == 8
    report_html = _html_table(personal_rows)
    assert "font-size:10px" in report_html
    assert "P: GA" in report_html
    assert "P: KA" in report_html
    assert "P: GENT" in report_html
    assert "P: PX" in report_html
    assert 'P: GA<br><span style="font-size:13px;line-height:1.2;font-weight:800;white-space:nowrap">08:15 / 13:15</span>' in report_html
    assert 'P: KA<br><span style="font-size:13px;line-height:1.2;font-weight:800;white-space:nowrap">08:30 / 13:15</span>' in report_html
    assert 'P: PX<br><span style="font-size:13px;line-height:1.2;font-weight:800;white-space:nowrap">08:45 / 14:00</span>' in report_html


def test_wfc_tasks_are_appended_after_personal_tasks_and_removed_from_original_rows() -> None:
    rows = _task_rows(
        {
            "oneH": [
                {
                    "title": "EF: WFC for KA",
                    "date": "2026-08-14",
                    "status": "WAITING_CONFIRMATION",
                    "confirmation_owner": "KA",
                    "one_h_report_slot": "10:00",
                }
            ],
            "r1": [
                {
                    "title": "RA: WFC for Gent",
                    "date": "2026-08-14",
                    "status": "WAITING_CONFIRMATION",
                    "confirmation_owner": "GENT",
                }
            ],
            "personal": [
                {"title": "AT/KA: Personal first", "date": "2026-08-14", "is_personal_task": True},
                {"title": "LH/GENTI: Personal first", "date": "2026-08-14", "is_personal_task": True},
                {
                    "title": "EF: WFC for KA",
                    "date": "2026-08-14",
                    "status": "WAITING_CONFIRMATION",
                    "confirmation_owner": "KA",
                    "is_personal_task": False,
                },
                {
                    "title": "RA: WFC for Gent",
                    "date": "2026-08-14",
                    "status": "WAITING_CONFIRMATION",
                    "confirmation_owner": "GENT",
                    "is_personal_task": False,
                },
            ],
        },
        date(2026, 8, 14),
    )

    ka_row = next(row for row in rows if row[0].startswith("P: KA"))
    gent_row = next(row for row in rows if row[0] == "P: GENT")
    assert [item["title"] for item in ka_row[1]] == ["AT/KA: Personal first", "EF: WFC for KA"]
    assert [item["title"] for item in gent_row[1]] == ["LH/GENTI: Personal first", "RA: WFC for Gent"]
    assert not any(
        item["title"] in {"EF: WFC for KA", "RA: WFC for Gent"}
        for label, items, personal in rows
        if not personal
        for item in items
    )
    report_html = _html_table([ka_row, gent_row], report_date=date(2026, 8, 14))
    assert report_html.count('data-task-badge="wfc"') == 2


def test_blocked_row_label_uses_full_afternoon_interval_and_keeps_report_time() -> None:
    rows = _task_rows({}, date(2026, 8, 14))
    blocked_row = next(row for row in rows if row[0].startswith("BLL"))

    assert blocked_row[0] == "BLL\n14:30 - 16:00\nRAP 16:10"


def test_excel_status_colours_and_done_overrides_ga_personal() -> None:
    _, content, _ = _excel_table_attachment(
        [
            ("1H 10:00", [{"title": "TODO task", "status": "TODO"}, {"title": "Progress", "status": "IN_PROGRESS"}], False),
            ("P", [{"title": "GA: Personal", "status": "DONE"}], True),
        ],
        [],
        date(2026, 8, 14),
    )

    sheet = load_workbook(BytesIO(content)).active
    assert sheet["C7"].fill.fgColor.rgb.endswith("FFC4ED")
    assert sheet["D7"].fill.fgColor.rgb.endswith("FFFF00")
    assert sheet["C8"].fill.fgColor.rgb.endswith("C4FDC4")


def test_done_tasks_are_excluded_but_other_statuses_remain() -> None:
    rows = _task_rows(
        {
            "oneH": [
                {"title": "Done task", "date": "2026-08-14", "status": "DONE", "oneHReportSlot": "10:00"},
                {"title": "Completed task", "date": "2026-08-14", "status": "COMPLETED", "oneHReportSlot": "10:00"},
                {"title": "Complete task", "date": "2026-08-14", "status": "COMPLETE", "oneHReportSlot": "10:00"},
                {"title": "Todo task", "date": "2026-08-14", "status": "TODO", "oneHReportSlot": "10:00"},
                {"title": "Progress task", "date": "2026-08-14", "status": "IN_PROGRESS", "oneHReportSlot": "10:00"},
                {"title": "Waiting confirmation task", "date": "2026-08-14", "status": "WAITING_CONFIRMATION", "oneHReportSlot": "10:00"},
                {"title": "Waiting client task", "date": "2026-08-14", "status": "WAITING_CLIENT", "oneHReportSlot": "10:00"},
            ],
        },
        date(2026, 8, 14),
    )

    first_slot_items = rows[0][1]
    assert {item["title"] for item in first_slot_items} == {
        "Todo task",
        "Progress task",
        "Waiting confirmation task",
    }
    waiting_client_row = next(row for row in rows if row[0].startswith("WFE"))
    assert [item["title"] for item in waiting_client_row[1]] == ["Waiting client task"]
    assert not any(
        item["title"] in {"Done task", "Completed task", "Complete task"}
        for _, items, _ in rows
        for item in items
    )


def test_today_report_includes_only_tasks_completed_on_its_day(monkeypatch) -> None:
    monkeypatch.setenv("PRIMEFLOW_REPORT_TIMEZONE", "Europe/Tirane")
    report_day = date(2026, 8, 14)
    def task(title: str, status: str, completed_at: str | None = None) -> dict:
        return {
            "title": title, "date": report_day.isoformat(), "status": status,
            "oneHReportSlot": "10:00", "completed_at": completed_at,
        }

    items = {"oneH": [
        task("Done today", "DONE", "2026-08-14T09:00:00+02:00"),
        task("Completed today", "COMPLETED", "2026-08-13T22:30:00Z"),
        task("Done yesterday", "DONE", "2026-08-13T12:00:00+02:00"),
        task("Done tomorrow", "DONE", "2026-08-14T22:30:00Z"),
        task("Done without timestamp", "DONE"),
        task("Still open", "IN_PROGRESS"),
    ]}
    today_rows = _task_rows(items, report_day, include_completed_today=True)
    today_titles = [item["title"] for item in today_rows[0][1]]
    assert today_titles == ["Still open", "Completed today", "Done today"]

    tomorrow_rows = _task_rows(items, report_day)
    assert [item["title"] for item in tomorrow_rows[0][1]] == ["Still open"]

    report = asyncio.run(build_today_print_report(report_day, payload={"items": items}))
    assert "Done today" in report["html"]
    assert "Completed today" in report["html"]
    assert "Done yesterday" not in report["html"]
    assert "Done without timestamp" not in report["html"]


def test_today_report_places_done_tasks_after_open_tasks_without_changing_user_order(monkeypatch) -> None:
    monkeypatch.setenv("PRIMEFLOW_REPORT_TIMEZONE", "Europe/Tirane")
    report_day = date(2026, 8, 14)
    items = {"oneH": [
        {"title": "Alice done", "person": "Alice", "date": "2026-08-14", "status": "DONE",
         "completed_at": "2026-08-14T10:00:00+02:00", "oneHReportSlot": "10:00"},
        {"title": "Zoe open", "person": "Zoe", "date": "2026-08-14", "status": "TODO",
         "oneHReportSlot": "10:00"},
        {"title": "Bob done", "person": "Bob", "date": "2026-08-14", "status": "DONE",
         "completed_at": "2026-08-14T11:00:00+02:00", "oneHReportSlot": "10:00"},
        {"title": "Alice open", "person": "Alice", "date": "2026-08-14", "status": "TODO",
         "oneHReportSlot": "10:00"},
    ]}

    rows = _task_rows(items, report_day, include_completed_today=True)
    assert [item["title"] for item in rows[0][1]] == [
        "Alice open", "Zoe open", "Alice done", "Bob done",
    ]


def test_same_task_details_for_separate_assignees_are_not_deduplicated() -> None:
    shared = {
        "title": "RA/EF: 2 FRG: RREG PRICELISTAT",
        "date": "2026-09-15",
        "status": "TODO",
        "oneHReportSlot": "14:20",
        "finishPeriod": "PM",
    }
    rows = _task_rows(
        {
            "oneH": [
                {**shared, "id": "task:elsa:2026-09-15", "task_id": "elsa", "assignees": ["Elsa Ferati"]},
                {**shared, "id": "task:rinesa:2026-09-15", "task_id": "rinesa", "assignees": ["Rinesa Ahmedi"]},
            ]
        },
        date(2026, 9, 15),
    )

    slot_items = next(row[1] for row in rows if row[0] == "1H 14:20")
    assert {item["task_id"] for item in slot_items} == {"elsa", "rinesa"}

    report_html = _html_table(rows, report_date=date(2026, 9, 15))
    assert "EF: 2 FRG: RREG PRICELISTAT" in report_html
    assert "RA: 2 FRG: RREG PRICELISTAT" in report_html

    _, content, _ = _excel_table_attachment(rows, [], date(2026, 9, 15))
    excel_values = [
        str(cell.value or "")
        for row in load_workbook(BytesIO(content)).active.iter_rows()
        for cell in row
    ]
    assert any("EF: 2 FRG: RREG PRICELISTAT" in value for value in excel_values)
    assert any("RA: 2 FRG: RREG PRICELISTAT" in value for value in excel_values)


def test_same_task_repeated_across_buckets_is_still_deduplicated() -> None:
    shared = {
        "id": "task:same:2026-09-15",
        "task_id": "same",
        "title": "EF: Waiting client",
        "date": "2026-09-15",
        "status": "WAITING_CLIENT",
        "oneHReportSlot": "10:00",
        "assignees": ["Elsa Ferati"],
    }
    rows = _task_rows(
        {"oneH": [shared], "blocked": [dict(shared)]},
        date(2026, 9, 15),
    )

    waiting_items = next(row[1] for row in rows if row[0] == "WFE")
    assert [item["task_id"] for item in waiting_items] == ["same"]


def test_non_daily_or_weekly_meetings_get_blue_borders_in_email_and_excel() -> None:
    meetings = [
        ("TAK EXT", [
            {"title": "One-off", "time": "10:00", "recurrence_type": "none"},
            {"title": "Weekly", "time": "11:00", "recurrence_type": "weekly"},
        ], False)
    ]

    report_html = _html_table(meetings, meeting=True)
    assert "border:2px solid #2563EB" in report_html
    assert report_html.count("border:2px solid #2563EB") == 1

    _, content, _ = _excel_table_attachment([], meetings, date(2026, 8, 14))
    sheet = load_workbook(BytesIO(content)).active
    assert sheet["C9"].border.left.color.rgb.endswith("2563EB")
    assert sheet["C9"].fill.fgColor.rgb.endswith("DCECFF")
    assert sheet["D9"].fill.fgColor.rgb.endswith("C9A98A")
    assert sheet["D9"].border.left.style == "thin"


def test_email_meetings_use_grouped_today_tomorrow_columns() -> None:
    sections = [
        (
            date(2026, 8, 25),
            "SOT",
            [
                ("TAK EXT", [{"title": "Today one-off", "time": "10:00", "recurrence_type": "none"}], False),
                ("TAK INT", [{"title": "Today early internal", "time": "8:15", "recurrence_type": "weekly"}], False),
            ],
        ),
        (
            date(2026, 8, 26),
            "NESER",
            [("TAK EXT", [
                {"title": "Tomorrow weekly", "time": "11:00", "recurrence_type": "weekly"},
                {"title": "Tomorrow second", "time": "13:00", "recurrence_type": "weekly"},
            ], False)],
        ),
    ]

    report_html = _dated_meetings_html(sections)

    assert 'data-side-by-side-meetings="true"' in report_html
    assert "border:4px solid #111827" in report_html
    assert report_html.count("border:3px solid #111827") >= 6
    assert "TAKIMET SOT - 25.08.2026" in report_html
    assert "TAKIMET NESER - 26.08.2026" in report_html
    assert report_html.count(">LLOJI</th>") == 2
    assert report_html.count(">KOHA</th>") == 2
    assert report_html.count(">USER</th>") == 2
    assert report_html.count(">TAKIMET</th>") == 2
    assert report_html.count('data-meeting-time="true"') == 6
    assert report_html.count('data-meeting-users="true"') == 6
    assert ">10:00</td>" in report_html
    assert "Today one-off 10:00" not in report_html
    assert "border-left:4px solid #2563EB" in report_html
    assert report_html.count("border:2px solid #2563EB") == 8
    assert report_html.count("border-top:4px solid #111827") == 10
    assert report_html.count('data-meeting-row="true"') == 3
    assert report_html.count('rowspan="2"') == 2
    assert 'bgcolor="#DCECFF"' in report_html
    assert report_html.count('bgcolor="#FFF4CC"') >= 3
    assert 'data-manual-internal-meeting="true"' in report_html
    assert report_html.count('bgcolor="#C9A98A"') >= 4
    assert report_html.index("Today one-off") < report_html.index("Today early internal")
    assert report_html.index("Tomorrow weekly") < report_html.index("Tomorrow second")

    _, png, _ = _png_table_attachment([], date(2026, 8, 25), meeting_sections=sections)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")

    _, content, _ = _excel_table_attachment(
        [], [], date(2026, 8, 25), meeting_sections=sections
    )
    values = [str(cell.value or "") for row in load_workbook(BytesIO(content)).active.iter_rows() for cell in row]
    assert "KOHA" in values
    assert "8:15 MANUAL" in values
    assert "10:00" in values
    assert "1. Today one-off" in values
    assert "2. Today early internal" in values


@pytest.mark.parametrize("link_field, prefix", [
    ("preExternalMeetingId", "PARA"),
    ("pre_external_meeting_id", "PARA"),
    ("pairedExternalMeetingId", "PAS"),
    ("paired_external_meeting_id", "PAS"),
])
def test_linked_meeting_title_uses_explicit_relationship(link_field, prefix) -> None:
    item = {"title": "Client workshop", link_field: "external-id"}
    assert _meeting_relation(item) == prefix
    assert _meeting_title(item) == "Client workshop"
    assert item["title"] == "Client workshop"
    assert _meeting_title({"title": "Manual internal"}) == "Manual internal"
    assert _meeting_relation({"title": "Manual internal"}) == ""


def test_calendar_linked_internal_meeting_inherits_external_tone_and_cal_badge() -> None:
    sections = [(
        date(2026, 8, 25),
        "SOT",
        [
            ("TAK EXT", [{
                "title": "Calendar external",
                "time": "10:00",
                "assignees": ["Luan Gashi"],
                "calendarImported": True,
                "calendarCategories": ["Event"],
            }], False),
            ("TAK INT", [
                {
                    "title": "Linked calendar internal",
                    "time": "10:30",
                    # The normalized report payload can carry both naming styles.
                    # Empty snake-case defaults must not hide the populated API aliases.
                    "paired_external_meeting_id": None,
                    "pairedExternalMeetingId": "external-id",
                    "linked_external_calendar_imported": False,
                    "linkedExternalCalendarImported": True,
                    "linked_external_calendar_categories": [],
                    "linkedExternalCalendarCategories": ["Event"],
                    "assignees": ["Arben Krasniqi", "Dren Veliu"],
                },
                {
                    "title": "Manual internal",
                    "time": "11:00",
                    "assignees": ["Gane Arifaj"],
                },
            ], False),
        ],
    )]

    report_html = _dated_meetings_html(sections)

    assert report_html.count('data-calendar-meeting="true"') == 2
    assert report_html.count('bgcolor="#CCEFF1"') == 8
    assert report_html.count('bgcolor="#FFF4CC"') == 4
    assert report_html.count('data-meeting-users="true"') == 6
    assert report_html.count(">USER</th>") == 2
    assert "AK/DV" in report_html
    assert report_html.count("color:#64748B") == 3
    external_title_cell = report_html.split('1. Calendar external</td>')[0].rsplit('<td ', 1)[1]
    linked_internal_title_cell = report_html.split('1. Linked calendar internal</td>')[0].rsplit('<td ', 1)[1]
    assert "font-weight:800" in external_title_cell
    assert "font-weight:800" not in linked_internal_title_cell
    assert report_html.count('data-manual-internal-meeting="true"') == 1
    assert "10:00" in report_html and "10:30" in report_html
    assert "11:00" in report_html

    _, content, _ = _excel_table_attachment(
        [], [], date(2026, 8, 25), meeting_sections=sections
    )
    sheet = load_workbook(BytesIO(content)).active
    time_cells = {
        str(cell.value): cell
        for row in sheet.iter_rows()
        for cell in row
        if cell.value in {"10:00 CAL", "10:30 CAL", "11:00 MANUAL"}
    }
    assert set(time_cells) == {"10:00 CAL", "10:30 CAL", "11:00 MANUAL"}
    assert time_cells["10:00 CAL"].fill.fgColor.rgb.endswith("CCEFF1")
    assert sheet.cell(time_cells["10:00 CAL"].row, 6).font.bold
    assert not sheet.cell(time_cells["10:30 CAL"].row, 6).font.bold
    assert sheet.cell(time_cells["10:30 CAL"].row, 5).value == "PAS"
    assert time_cells["10:30 CAL"].fill.fgColor.rgb.endswith("CCEFF1")
    assert time_cells["10:30 CAL"].font.color.rgb.endswith("64748B")
    assert sheet.cell(time_cells["10:30 CAL"].row, 4).value == "AK/DV"
    assert sheet.cell(time_cells["10:30 CAL"].row, 4).font.color.rgb.endswith("64748B")
    assert time_cells["10:30 CAL"].border.top.style == "thick"
    assert time_cells["10:30 CAL"].border.top.color.rgb.endswith("111827")
    assert time_cells["11:00 MANUAL"].fill.fgColor.rgb.endswith("FFF4CC")


def test_unavailable_meeting_users_are_red_only_when_the_status_covers_meeting_time() -> None:
    target_date = date(2026, 9, 16)
    items = {
        "external": [],
        "internal": [
            {
                "title": "Morning internal",
                "date": target_date.isoformat(),
                "time": "11:00",
                "assignees": ["Luan Hoxha", "Arben Berisha", "Dren Veliu"],
                "assigneeUserIds": ["lh-id", "ab-id", "dv-id"],
            },
            {
                "title": "Afternoon internal",
                "date": target_date.isoformat(),
                "time": "14:00",
                "assignees": ["Luan Hoxha"],
                "assigneeUserIds": ["lh-id"],
            },
        ],
        "leave": [
            {
                "person": "Luan Hoxha",
                "userId": "lh-id",
                "startDate": target_date.isoformat(),
                "endDate": target_date.isoformat(),
                "fullDay": False,
                "from": "08:00",
                "to": "12:00",
            }
        ],
        "absent": [
            {
                "person": "Arben Berisha",
                "userId": "ab-id",
                "date": target_date.isoformat(),
                "from": "10:30",
                "to": "11:30",
            }
        ],
        "late": [],
        "externalHoliday": [],
    }

    rows = [(label, values, False) for label, values in _meeting_rows(items, target_date)]
    report_html = _dated_meetings_html([(target_date, "SOT", rows)])

    assert report_html.count('data-unavailable-meeting-user="true"') == 2
    assert 'color:#DC2626;font-weight:800">LH</span>' in report_html
    assert 'color:#DC2626;font-weight:800">AB</span>' in report_html
    assert 'color:#DC2626;font-weight:800">DV</span>' not in report_html
    assert report_html.count(">LH</span>") == 1


@pytest.mark.parametrize("day", [date(2026, 10, 8), date(2026, 10, 9)])
def test_day_specific_export_questions_share_the_title_row(day) -> None:
    from docx import Document

    _, content, _ = _docx_table_attachment([], day, checklist_date=day)
    document = Document(BytesIO(content))
    paragraph = next(
        p for table in document.tables for row in table.rows for cell in row.cells
        for p in cell.paragraphs if p.text.startswith("E PREMTE" if day.weekday() == 4 else "E ENJTE")
    )
    assert "M1 - 1." in paragraph.text
    assert " / " in paragraph.text
    assert paragraph.runs[0].bold
    assert all(run.bold and run.font.size.pt == 14 for run in paragraph.runs if run.text == " / ")
    if day.weekday() == 4:
        assert "M1 - 2. BZ PERSONALISHT ME GA" in paragraph.text

    _, content, _ = _excel_table_attachment([], [], day, checklist_date=day)
    sheet = load_workbook(BytesIO(content), rich_text=True).active
    parts = sheet["A3"].value
    assert str(parts) == paragraph.text
    assert parts[0].font.b
    assert all(part.font.b and part.font.sz == 14 for part in parts if part.text == " / ")
    assert sheet["A3"].alignment.wrap_text


def test_word_export_preserves_task_markers_and_unavailable_meeting_users() -> None:
    from docx import Document

    target_date = date(2026, 9, 16)
    _, content, _ = _docx_table_attachment(
        [("1H", [
            {"title": "Task with marker", "oneHMarker": "QUESTION"},
            {"title": "GA task with marker", "oneHMarker": "QUESTION", "oneHMarkerByGa": True},
        ], False)],
        target_date,
        meeting_sections=[(target_date, "SOT", [("TAK INT", [{
            "title": "Internal meeting",
            "preExternalMeetingId": "external-id",
            "time": "11:00",
            "assignees": ["Luan Hoxha", "Dren Veliu"],
            "_unavailableUserInitials": ["LH"],
        }], False)])],
    )
    document = Document(BytesIO(content))
    meeting_row = next(row for table in document.tables for row in table.rows if any("Internal meeting" in cell.text for cell in row.cells))
    assert meeting_row.cells[3].text == "PARA"
    assert meeting_row.cells[4].text == "1. Internal meeting"
    cells = [cell for table in document.tables for row in table.rows for cell in row.cells]
    task_cell = next(cell for cell in cells if "Task with marker" in cell.text)
    marker_run = next(run for paragraph in task_cell.paragraphs for run in paragraph.runs if "[?]" in run.text)
    assert marker_run.bold
    assert str(marker_run.font.color.rgb) == "DC2626"
    ga_task_cell = next(cell for cell in cells if "GA task with marker" in cell.text)
    assert "(?)" in ga_task_cell.text
    ga_marker_run = next(run for paragraph in ga_task_cell.paragraphs for run in paragraph.runs if "(?)" in run.text)
    assert str(ga_marker_run.font.color.rgb) == "DC2626"
    assert "[(?)]" not in ga_task_cell.text
    user_cell = next(cell for cell in cells if cell.text == "LH/DV")
    user_runs = {run.text: run for paragraph in user_cell.paragraphs for run in paragraph.runs}
    assert str(user_runs["LH"].font.color.rgb) == "DC2626"
    assert str(user_runs["DV"].font.color.rgb) == "000000"


def test_meetings_are_ordered_chronologically_even_without_leading_zero() -> None:
    rows = _meeting_rows(
        {
            "external": [
                {"title": "Late", "date": "2026-08-25", "time": "13:00"},
                {"title": "Early", "date": "2026-08-25", "time": "8:15"},
                {"title": "Middle", "date": "2026-08-25", "time": "10:00"},
            ]
        },
        date(2026, 8, 25),
    )

    assert [item["title"] for item in rows[0][1]] == ["Early", "Middle", "Late"]


def test_today_and_tomorrow_reports_separate_two_days_of_meetings(monkeypatch) -> None:
    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def common_view(self, target_date: date) -> dict:
            return {
                "items": {
                    "oneH": [
                        {"title": "GA: Today task", "date": target_date.isoformat(), "oneHReportSlot": "10:00"},
                        {"title": "GA: Done task for selected day", "date": target_date.isoformat(), "status": "DONE", "oneHReportSlot": "10:00"},
                        {"title": "GA: Tomorrow task", "date": "2026-08-25", "oneHReportSlot": "10:00"},
                    ],
                    "external": [
                        {"title": "Today meeting", "date": "2026-08-24", "time": "10:00"},
                        {"title": "Tomorrow meeting", "date": "2026-08-25", "time": "11:00"},
                        {"title": "Following meeting", "date": "2026-08-26", "time": "12:00"},
                    ],
                    "internal": [
                        {"title": "Preparation", "date": target_date.isoformat(), "time": "09:00",
                         "preExternalMeetingId": "external-id"},
                        {"title": "Follow-up", "date": target_date.isoformat(), "time": "13:00",
                         "pairedExternalMeetingId": "external-id"},
                        {"title": "Standalone internal", "date": target_date.isoformat(), "time": "14:00"},
                    ],
                }
            }

    monkeypatch.setenv("PRIMEFLOW_API_BASE_URL", "http://primeflow.test")
    monkeypatch.setattr("app.services.tomorrow_print_report.PrimeFlowClient", FakeClient)

    import asyncio

    report = asyncio.run(build_today_print_report(date(2026, 8, 24), include_attachment=True))

    assert report["target_date"] == "2026-08-24"
    assert report["subject"] == "1H SHTYPI SOT (Shiko simbolet) — 24.08.2026"
    assert "1H SHTYPI SOT (Shiko simbolet) — 24.08.2026" in report["html"]
    assert "Today task" in report["html"]
    assert "Tomorrow task" not in report["html"]
    assert "Done task for selected day" not in report["html"]
    assert "Done task for selected day" not in report["plain_text"]
    assert "Today meeting" in report["html"]
    assert "Tomorrow meeting" in report["html"]
    assert "Following meeting" not in report["html"]
    assert "SOT - 24.08.2026" in report["html"]
    assert "NESER - 25.08.2026" in report["html"]
    assert 'data-side-by-side-meetings="true"' in report["html"]
    assert report["html"].index("Today meeting") < report["html"].index("Tomorrow meeting")
    assert 'data-today-print-report="true"' in report["content_html"]
    assert [attachment[2] for attachment in report["attachments"]] == [
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "image/png",
    ]
    assert report["attachments"][1][1].startswith(b"\x89PNG\r\n\x1a\n")
    workbook = load_workbook(BytesIO(report["attachments"][0][1]))
    values = [str(cell.value or "") for row in workbook.active.iter_rows() for cell in row]
    assert "TAKIMET SOT - 24.08.2026" in values
    assert "TAKIMET NESER - 25.08.2026" in values
    assert any("Today meeting" in value for value in values)
    assert any("Tomorrow meeting" in value for value in values)
    assert not any("Done task for selected day" in value for value in values)

    tomorrow = asyncio.run(build_tomorrow_print_report(date(2026, 8, 24), include_attachment=True))
    assert tomorrow["target_date"] == "2026-08-25"
    assert tomorrow["subject"] == "1H SHTYPI NESER (Shiko simbolet) — 25.08.2026"
    assert "1H SHTYPI NESER (Shiko simbolet) — 25.08.2026" in tomorrow["html"]
    assert "Today meeting" not in tomorrow["html"]
    assert "Tomorrow meeting" in tomorrow["html"]
    assert "Following meeting" in tomorrow["html"]
    assert "Done task for selected day" not in tomorrow["html"]
    assert "Done task for selected day" not in tomorrow["plain_text"]
    assert "NESER - 25.08.2026" in tomorrow["html"]
    assert "PAS NESER - 26.08.2026" in tomorrow["html"]
    assert "DITA PAS NESER" not in tomorrow["html"]
    tomorrow_workbook = load_workbook(BytesIO(tomorrow["attachments"][0][1]))
    tomorrow_values = [str(cell.value or "") for row in tomorrow_workbook.active.iter_rows() for cell in row]
    assert not any("Done task for selected day" in value for value in tomorrow_values)
    for result, cell_values in ((report, values), (tomorrow, tomorrow_values)):
        assert result["html"].count(">PARA/PAS</th>") == 2
        for relation, title in (("PARA", "Preparation"), ("PAS", "Follow-up")):
            assert f">{relation}</td>" in result["html"]
            assert re.search(rf'data-meeting-relation="true"[^>]*>{relation}</td><td data-meeting-cell="true"[^>]*>\d+\. {title}</td>', result["html"])
            assert f">{relation}</td>" in result["content_html"]
            assert f"[{relation}] {title}" in result["plain_text"]
            assert relation in cell_values
            assert any(title in value for value in cell_values)
        assert "PARA TAK EXT -" not in result["html"]
        assert "PAS TAK EXT -" not in result["html"]
    for workbook in (workbook, tomorrow_workbook):
        for row in workbook.active.iter_rows():
            title = str(row[5].value or "")
            if "Preparation" in title:
                assert row[4].value == "PARA"
            elif "Follow-up" in title:
                assert row[4].value == "PAS"
            elif "Standalone internal" in title:
                assert row[4].value is None
