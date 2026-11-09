from copy import deepcopy
from datetime import date
from io import BytesIO
from zipfile import ZipFile

import pytest

from app.services.primeflow_report import (
    SLOTS, build_report_document, render_docx, render_html, render_plain_text,
)


DAY = date(2026, 11, 9)


def payload(bucket, attendance):
    task = {
        "id": "absent-task", "title": "Hidden work", "person": "Era Fana",
        "assignees": ["Era Fana"], "user_id": "ef", "date": DAY.isoformat(),
        "status": "TODO", "one_h_report_slot": "10:00", "one_h_marker": "FLAG",
    }
    present = {**task, "id": "present-task", "title": "Present work",
               "person": "Rina Aliu", "assignees": ["Rina Aliu"], "user_id": "ra"}
    return {
        "users": [{"id": "ef", "full_name": "Era Fana", "role": "STAFF", "department_id": "dev"},
                  {"id": "ra", "full_name": "Rina Aliu", "role": "STAFF", "department_id": "dev"}],
        "departments": [{"id": "dev", "code": "DEV"}],
        "items": {**{name: [deepcopy(task), deepcopy(present)]
                     for name in ("oneH", "personal", "r1", "blocked", "important")},
                  bucket: [attendance]},
        "tasks": [deepcopy(task), deepcopy(present)],
    }


@pytest.mark.parametrize("slot", SLOTS)
@pytest.mark.parametrize("bucket,attendance", [
    ("absent", {"date": DAY.isoformat(), "userId": "ef", "from": "8:00", "to": "16:00"}),
    ("absent", {"date": DAY.isoformat(), "userId": "ef"}),
    ("absent", {"date": DAY.isoformat(), "person": "Era Fana"}),
    ("leave", {"startDate": "2026-11-08", "endDate": "2026-11-10", "userId": "ef", "fullDay": True}),
    ("leave", {"start_date": DAY.isoformat(), "end_date": DAY.isoformat(), "user_id": "ef",
               "full_day": False, "from": "08:00", "to": "16:00"}),
])
def test_full_day_unavailable_excluded_from_every_slot_and_summary(slot, bucket, attendance):
    data = payload(bucket, attendance)
    for row in data["items"]["oneH"] + data["tasks"]:
        row["one_h_report_slot"] = "14:20" if slot == "14:10" else slot
    original = deepcopy(data)
    report = build_report_document(data, DAY, slot)
    assert report.task_count > 0
    for section in report.sections:
        assert all(employee.name == "RA" for employee in section.employees)
    assert [row.person for row in report.ga_task_summary] == ["RA"]
    assert all(row.total == 1 for row in report.ga_task_summary)
    assert data == original
    for output in (render_html(report), render_plain_text(report)):
        assert "Hidden work" not in output
        assert "Present work" in output
    if slot == "10:00":
        xml = ZipFile(BytesIO(render_docx(report))).read("word/document.xml").decode()
        assert "Hidden work" not in xml
        assert "Present work" in xml


@pytest.mark.parametrize("bucket,attendance", [
    ("absent", {"date": DAY.isoformat(), "userId": "ef", "from": "08:00", "to": "12:00"}),
    ("absent", {"date": "2026-11-10", "userId": "ef"}),
    ("leave", {"startDate": DAY.isoformat(), "endDate": DAY.isoformat(), "userId": "ef",
               "fullDay": False, "from": "08:00", "to": "12:00"}),
    ("leave", {"startDate": "2026-11-10", "endDate": "2026-11-11", "userId": "ef", "fullDay": True}),
])
def test_partial_or_other_day_attendance_keeps_tasks(bucket, attendance):
    report = build_report_document(payload(bucket, attendance), DAY, "10:00")
    assert "Hidden work" in render_plain_text(report)
    assert {row.person for row in report.ga_task_summary} == {"EF", "RA"}


def test_shared_work_keeps_only_present_owners_in_sections_and_summary():
    data = payload("absent", {"date": DAY.isoformat(), "userId": "ef"})
    for bucket in ("oneH", "personal", "r1", "blocked", "important"):
        data["items"][bucket] = [{**data["items"][bucket][0], "title": "Shared work",
                                  "person": "Era Fana, Rina Aliu", "assignees": ["Era Fana", "Rina Aliu"]}]
    report = build_report_document(data, DAY, "10:00")
    assert report.task_count == 3
    assert {employee.name for section in report.sections for employee in section.employees} == {"RA"}
    assert [row.person for row in report.ga_task_summary] == ["RA"]
    xml = ZipFile(BytesIO(render_docx(report))).read("word/document.xml").decode()
    assert "Shared work" in xml
    assert "Hidden work" not in xml


def test_all_users_leave_also_excludes_legacy_fallback_tasks():
    data = payload("leave", {"startDate": DAY.isoformat(), "endDate": DAY.isoformat(),
                             "fullDay": True, "isAllUsers": True})
    data["items"].pop("oneH")
    report = build_report_document(data, DAY, "10:00")
    assert report.task_count == 0
    assert report.ga_task_summary == []


def test_filtered_one_h_bucket_does_not_restore_absent_fallback():
    data = payload("absent", {"date": DAY.isoformat(), "userId": "ef"})
    data["items"]["oneH"] = data["items"]["oneH"][:1]
    data["tasks"] = data["tasks"][:1]
    report = build_report_document(data, DAY, "11:00")
    assert report.task_count == 0


def test_shared_legacy_owner_label_keeps_present_person():
    data = payload("absent", {"date": DAY.isoformat(), "person": "Era Fana"})
    shared = {**data["items"]["oneH"][0], "person": "Era Fana, Rina Aliu"}
    shared.pop("assignees")
    data["items"] = {"oneH": [shared], "absent": data["items"]["absent"]}
    report = build_report_document(data, DAY, "10:00")
    assert report.task_count == 1
    assert report.sections[0].employees[0].name == "RA"
    assert [row.person for row in report.ga_task_summary] == ["RA"]
