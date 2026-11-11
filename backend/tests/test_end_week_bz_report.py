import pytest
from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.services.end_week_bz_report import (
    MEETING_COLUMNS,
    SECTION_TITLES,
    WFC_COLUMNS,
    _meeting_rows,
    _is_wfc_task,
    _personal_group,
    normalize_sections,
    render_html,
    subject_for,
)


def task(title: str):
    return SimpleNamespace(title=title)


def test_personal_tasks_follow_ka_genti_ga_px_priority() -> None:
    assert _personal_group(task("DM/GA: Review")) == "GA"
    assert _personal_group(task("AT/KA: Review")) == "KA"
    assert _personal_group(task("ER: Personal work")) == "PX"
    assert _personal_group(task("stored title"), "RA/EF/KA: Review\nmore") == "KA"
    assert _personal_group(task("EF/GA/KA: Review")) == "KA"
    assert _personal_group(task("EF/PX/GT: Review")) == "GENT"
    assert _personal_group(task("EF/GA/GT: Review")) == "GENT"
    assert _personal_group(task("EF/KA/GT/GA: Review")) == "GENT"


def test_wfc_columns_and_both_status_labels_are_explicit() -> None:
    assert [name for name, _ in WFC_COLUMNS] == ["NR", "WHO", "TYPE", "DEP", "AM/PM", "TITLE", "STATUS"]
    sections = normalize_sections([{"section_key": "WFC TASKS", "title": "WFC TASKS", "body": "WFE: 0\n\nWAITING CONFIRMATION: 0"}])
    assert "WFE" in sections[1]["body"]
    assert "WAITING CONFIRMATION" in sections[1]["body"]
    assert _is_wfc_task(SimpleNamespace(status="WAITING_CLIENT", completed_at=None))
    assert _is_wfc_task(SimpleNamespace(status="WAITING_CONFIRMATION", completed_at=None))
    assert not _is_wfc_task(SimpleNamespace(status="IN_PROGRESS", completed_at=None))


def test_meeting_time_column_is_before_title() -> None:
    assert [name for name, _ in MEETING_COLUMNS] == ["NR", "WHO", "TIME", "TITLE", "RECURRENCE", "STATUS"]
    meeting = SimpleNamespace(
        id="m1", title="Client sync", starts_at=datetime(2026, 9, 4, 10, 30, tzinfo=timezone.utc),
        recurrence_type="weekly", participants=[],
    )
    row = _meeting_rows([meeting], {"m1": "held"}, {})[0]
    assert row[2] == "12:30"  # Europe/Tirane report timezone in September.
    assert row[3] == "Client sync [[mc:meeting-brown]]"
    assert row[4:] == ["WEEKLY", "HELD"]


def test_one_time_meeting_gets_shared_blue_border_marker() -> None:
    meeting = SimpleNamespace(
        id="m2", title="One-off sync", starts_at=datetime(2026, 9, 4, 10, 30, tzinfo=timezone.utc),
        recurrence_type="none", participants=[],
    )
    row = _meeting_rows([meeting], {}, {})[0]
    assert "[[mc:meeting-blue]]" in row[3]
    assert "[[mt:non_daily_weekly]]" in row[3]
    assert row[4] == "ONE-TIME"


def test_report_normalization_keeps_fixed_section_order_and_html_tables() -> None:
    sections = normalize_sections([])
    assert [section["section_key"] for section in sections] == SECTION_TITLES
    html = render_html(subject_for(date(2026, 9, 4)), date(2026, 9, 4), [{
        "section_key": SECTION_TITLES[5],
        "title": SECTION_TITLES[5],
        "body": "+----+------+\n| NR | TIME |\n+----+------+",
    }])
    assert "PIKAT E BZ FIN JAV" in html
    assert "<table" in html


def test_requested_priority_and_meeting_styles_use_shared_report_markers() -> None:
    html = render_html("Styled", date(2026, 9, 4), [
        {
            "title": "TASKS WITH DEADLINE",
            "body": "TASKS WITH DEADLINE:\n+----+----------+--------+\n| NR | TYPE     | TITLE  |\n+----+----------+--------+\n| 1  | DEADLINE | Task A |\n+----+----------+--------+",
        },
        {
            "title": "08:00 TASKS",
            "body": "08:00 TASKS:\n+----+-------+--------+\n| NR | TYPE  | TITLE  |\n+----+-------+--------+\n| 1  | 08:00 | Task B |\n+----+-------+--------+",
        },
        {
            "title": "EXTERNAL/INTERNAL MEETINGS",
            "body": "TAK EXT:\n+----+-------+------------------------------------------+\n| NR | TIME  | TITLE                                    |\n+----+-------+------------------------------------------+\n| 1  | 10:00 | One off [[mt:non_daily_weekly]]         |\n+----+-------+------------------------------------------+",
        },
    ])
    assert "background-color:#dc2626" in html
    assert 'class="eight-am"' in html
    assert 'class="highlight"' in html
    assert "border-top:3px solid #2563eb" in html


from tests.report_attendance_fixtures import present_report_population
