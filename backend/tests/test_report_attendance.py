import asyncio
import re
import uuid
from copy import deepcopy
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.common_entry import CommonEntry
from app.models.enums import CommonCategory
from app.models.user import User
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.department import Department
from app.models.audit_log import AuditLog
from app.models.project import Project
from app.models.ga_note import GaNote
from app.models.plan_note import PlanNote
from app.models.task_daily_rlz_state import TaskDailyRlzState
from app.models.task_daily_progress import TaskDailyProgress
from app.models.daily_planner_snapshot import DailyPlannerSnapshot
from app.services import report_attendance as service
from app.services.after_break_report import _ascii_table
from app.services.primeflow_report import build_report_document
from app.services.tomorrow_print_report import (
    _task_rows, _meeting_rows, _comment_user_initials, build_today_print_report,
)


DAY = date(2026, 11, 9)
ABSENT, PRESENT = uuid.uuid4(), uuid.uuid4()
USERS = [SimpleNamespace(id=ABSENT, full_name="Era Fana", username="era", email="era@test.test"),
         SimpleNamespace(id=PRESENT, full_name="Rina Aliu", username="rina", email="rina@test.test")]


class Result:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return self

    def all(self):
        return self.values


class AttendanceDb:
    def __init__(self, entries):
        self.entries = entries
        self.info = {}

    async def execute(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        if entity is CommonEntry:
            return Result(self.entries)
        if entity is User:
            return Result(USERS)
        raise AssertionError(str(statement))


def entry(category=CommonCategory.absences, description=None):
    return SimpleNamespace(id=uuid.uuid4(), category=category, assigned_to_user_id=ABSENT,
                           created_by_user_id=PRESENT, entry_date=DAY,
                           created_at=datetime(2026, 11, 9, tzinfo=timezone.utc),
                           title="Era Fana", description=description)


@pytest.mark.parametrize("record,hidden", [
    (entry(description="From: 08:00 - To: 16:00"), True),
    (entry(description="From: 08:00 - To: 12:00"), False),
    (entry(), True),
    (entry(description="Date: 2026-11-10"), False),
    (entry(CommonCategory.annual_leave, "2026-11-08 - 2026-11-10 (Full day)"), True),
    (entry(CommonCategory.annual_leave, "2026-11-09 (08:00 - 16:00)"), True),
    (entry(CommonCategory.annual_leave, "2026-11-09 (08:00 - 12:00)"), False),
])
def test_database_policy_matches_one_h_attendance(record, hidden):
    policy = asyncio.run(service.load_report_attendance(AttendanceDb([record]), DAY))
    assert policy.excludes(ABSENT) is hidden
    assert policy.excludes(name="Era Fana") is hidden
    assert ("EF" in policy.labels) is hidden
    assert not policy.excludes(PRESENT)


def test_task_context_keeps_shared_work_and_never_edits_assignments():
    solo, shared = [SimpleNamespace(id=uuid.uuid4(), assigned_to=ABSENT) for _ in range(2)]
    original_owners = {solo.id: {ABSENT}, shared.id: {ABSENT, PRESENT}}
    policy = service.ReportAttendance(user_ids={str(ABSENT)}).with_users(USERS)
    tasks, names, owners = policy.task_context([solo, shared], {u.id: u.full_name for u in USERS}, original_owners)
    assert tasks == [shared]
    assert names == {PRESENT: "Rina Aliu"}
    assert owners == {shared.id: {PRESENT}}
    assert shared.assigned_to == ABSENT
    assert original_owners[shared.id] == {ABSENT, PRESENT}


@pytest.mark.parametrize("bucket,record", [
    ("absent", {"date": str(DAY), "userId": str(ABSENT), "from": "08:00", "to": "16:00"}),
    ("leave", {"startDate": str(DAY), "endDate": str(DAY), "userId": str(ABSENT), "fullDay": True}),
])
def test_shtypi_shared_owners_summary_comments_and_meetings_match_one_h(bucket, record):
    users = [{**vars(user), "id": str(user.id), "role": "STAFF", "department_id": "pcm"} for user in USERS]
    shared = {"id": "shared", "task_id": "shared", "title": "Shared work", "date": str(DAY),
              "userId": str(ABSENT), "person": "Era Fana, Rina Aliu", "assignees": ["Era Fana", "Rina Aliu"],
              "status": "TODO", "oneHReportSlot": "10:00", "one_h_report_slot": "10:00", "one_h_marker": "FLAG"}
    items = {"oneH": [shared], bucket: [{**record, "person": "Era Fana"}],
             "external": [{"title": "Meeting", "date": str(DAY), "time": "10:00",
                                   "assignees": ["Era Fana", "Rina Aliu"],
                                   "assigneeUserIds": [str(ABSENT), str(PRESENT)]}]}
    payload = {"items": items, "users": users, "departments": [{"id": "pcm", "code": "PCM"}]}
    before = deepcopy(payload)
    report = asyncio.run(build_today_print_report(DAY, payload=payload))
    assert [row["person"] for row in report["ga_task_summary"]] == ["RA"]
    assert 'data-task-users="RA"' in report["html"]
    assert 'data-user-comment="EF"' not in report["html"]
    assert "EF" not in _comment_user_initials(payload, DAY)
    assert _task_rows(items, DAY, users=users)[0][1][0]["assignees"] == ["Rina Aliu"]
    meetings = [row for _, rows in _meeting_rows(items, DAY) for row in rows]
    assert meetings[0]["assignees"] == ["RA"]
    regular = build_report_document(payload, DAY, "10:00")
    assert [row.person for row in regular.ga_task_summary] == ["RA"]
    assert payload == before


@pytest.mark.parametrize("owner_column", ["KUSH", "WHO", "PERSONI", "FROM"])
def test_saved_m1_m2_m3_ascii_tables_filter_by_the_section_date(monkeypatch, owner_column):
    today = service.ReportAttendance(user_ids={str(ABSENT)}).with_users(USERS)
    tomorrow = service.ReportAttendance(user_ids={str(PRESENT)}).with_users(USERS)
    async def load(_db, day):
        return today if day == DAY else tomorrow
    monkeypatch.setattr(service, "load_report_attendance", load)
    table = "\n".join(_ascii_table("TASKS", [("NR", 2), (owner_column, 8), ("TITULLI", 20)], [
        ["1", "EF", "Absent solo"], ["2", "EF RA", "Shared work"], ["3", "RA", "Present solo"]]))
    original = [{"title": title, "body": table} for title in ("M1", "M2", "M3", "N- DET TE REJA")]
    filtered = asyncio.run(service.filter_report_sections(None, original, DAY, tomorrow=date(2026, 11, 10)))
    for section in filtered[:3]:
        assert "Absent solo" not in section["body"]
        assert "EF" not in section["body"]
        assert "Shared work" in section["body"]
        assert "Present solo" in section["body"]
    assert "RA" not in filtered[-1]["body"]
    assert "Absent solo" in filtered[-1]["body"]
    assert all(section["body"] == table for section in original)


@pytest.mark.parametrize("code", ["M1", "M2", "M3"])
def test_saved_points_hide_solo_tasks_and_trim_shared_tasks_in_every_section(monkeypatch, code):
    policy = service.ReportAttendance(user_ids={str(ABSENT)}).with_users(USERS)
    monkeypatch.setattr(service, "load_report_attendance", AsyncMock(return_value=policy))
    rows = [{"task_id": "one", "assignees": "EF", "title": "Absent"},
            {"task_id": "two", "assignees": "EF RA", "title": "Shared"}]
    report = {"report_date": str(DAY), "subject": code, "data": {
        key: deepcopy(rows) for key in ("tasks", "untouched", "delivery", "unfinished_priority", "postponed", "pm_continuation")}}
    before = deepcopy(report)
    filtered = asyncio.run(service.filter_points_payload(None, report))
    assert all(rows == [{"task_id": "two", "assignees": "RA", "title": "Shared"}] for rows in filtered["data"].values())
    assert report == before


class TaskDb(AttendanceDb):
    def __init__(self, records, tasks):
        super().__init__(records)
        self.tasks = tasks

    async def execute(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        if entity in {CommonEntry, User}:
            return await super().execute(statement)
        if entity is Task:
            return Result(self.tasks)
        if entity is TaskAssignee:
            return Result([(task.id, uid) for task in self.tasks for uid in (
                [ABSENT, PRESENT] if task.title == "Shared work" else [ABSENT])])
        if entity is Department:
            if len(statement.column_descriptions) == 2:
                return Result([(uuid.UUID(int=10), "DEV")])
            return Result([SimpleNamespace(id=uuid.UUID(int=10), code="DEV")])
        if entity in {AuditLog, Project, TaskDailyRlzState, TaskDailyProgress, GaNote, PlanNote, DailyPlannerSnapshot}:
            return Result([])
        raise AssertionError(str(statement))


def report_tasks(marker="FLAG"):
    return [Task(id=uuid.uuid4(), title=title, assigned_to=ABSENT,
                 department_id=uuid.UUID(int=10), status="TODO", progress_percentage=0,
                 created_at=datetime(2026, 11, 9, 8, tzinfo=timezone.utc),
                 start_date=datetime(2026, 11, 9, 8, tzinfo=timezone.utc),
                 due_date=datetime(2026, 11, 9, 16, tzinfo=timezone.utc),
                 finish_period="AM", one_h_marker=marker, is_deadline_important=False,
                 is_personal=False, completed_at=None, project_id=None)
            for title in ("Solo work", "Shared work")]


@pytest.mark.parametrize("code", ["M1", "M2", "M3"])
@pytest.mark.parametrize("record", [entry(), entry(CommonCategory.annual_leave, "2026-11-09 (Full day)")])
def test_actual_points_builders_exclude_solo_and_trim_shared_owners(monkeypatch, code, record):
    from app.services import m1_reporting_points as m1, m2_reporting_points as m2, m3_reporting_points as m3
    monkeypatch.setattr(m3, "apply_weekly_planner_task_order", AsyncMock())
    tasks = report_tasks("M3" if code == "M3" else "FLAG")
    db = TaskDb([record], tasks)
    selector = {"M1": m1.select_ga_tasks, "M2": m2.select_task_sections, "M3": m3.select_task_sections}[code]
    data = asyncio.run(m3.build_task_data(db, DAY, section_selector=selector))
    rows = [row for rows in data.values() for row in rows]
    assert rows
    assert {row["task_id"] for row in rows} == {str(tasks[1].id)}
    assert {row["assignees"] for row in rows} == {"RA"}
    assert all(task.assigned_to == ABSENT for task in tasks)


def test_generic_report_export_proxy_does_not_reassign_database_tasks():
    tasks = report_tasks()
    db = TaskDb([entry()], tasks)
    visible = asyncio.run(service.filter_export_tasks(db, tasks, DAY))
    assert len(visible) == 1
    assert visible[0].title == "Shared work"
    assert visible[0].assigned_to == PRESENT
    assert visible[0].report_owner_names == ["Rina Aliu"]
    assert tasks[1].assigned_to == ABSENT
    assert db.info["report_attendance"].excludes(ABSENT)


def test_period_report_keeps_partial_week_staff_and_excludes_full_week_leave():
    friday = date(2026, 11, 13)
    partial = asyncio.run(service.load_period_attendance(AttendanceDb([entry()]), DAY, friday))
    assert not partial.excludes(ABSENT)
    leave = entry(CommonCategory.annual_leave, "2026-11-09 - 2026-11-13 (Full day)")
    full = asyncio.run(service.load_period_attendance(AttendanceDb([leave]), DAY, friday))
    assert full.excludes(ABSENT)
    assert not full.excludes(PRESENT)


def test_tomorrow_native_closing_tables_exclude_absent_owners(monkeypatch):
    from app.services import tomorrow_closing_sections as closing
    monkeypatch.setattr(closing, "apply_weekly_planner_task_order", AsyncMock())
    monkeypatch.setattr(closing, "_all_participant_user_ids", AsyncMock(return_value={ABSENT, PRESENT}))
    tasks = report_tasks()
    sections = asyncio.run(closing.build_tomorrow_closing_sections(TaskDb([entry()], tasks), DAY))
    rows = [row for section in sections for table in section.tables for row in table.rows]
    assert rows
    assert not any("EF" in row.values for row in rows)
    assert not any("Solo work" in row.values for row in rows)
    assert any("Shared work" in row.values and "RA" in row.values for row in rows)


def test_all_tasks_excel_filters_client_supplied_owner_rows(monkeypatch):
    from io import BytesIO
    from openpyxl import load_workbook
    from app.api.routers import exports
    from app.models.enums import UserRole
    policy = service.ReportAttendance(user_ids={str(ABSENT)}).with_users(USERS)
    monkeypatch.setattr(exports, "load_report_attendance", AsyncMock(return_value=policy))
    payload = exports.AllTasksReportExportIn(rows=[
        {"title": "Solo work", "userInitials": "EF"},
        {"title": "Shared work", "userInitials": "EF/RA"},
    ])
    async def build():
        response = await exports.export_all_tasks_report_xlsx(payload, user=SimpleNamespace(role=UserRole.ADMIN, full_name="Test Admin", username="admin"), db=None)
        return b"".join([chunk async for chunk in response.body_iterator])
    sheet = load_workbook(BytesIO(asyncio.run(build()))).active
    values = [str(cell.value) for row in sheet for cell in row if cell.value is not None]
    assert "Solo work" not in values
    assert "Shared work" in values
    assert "EF" not in values
    assert "RA" in values
    assert payload.rows[1].userInitials == "EF/RA"


def test_all_users_leave_does_not_restore_comment_names_in_excel_or_png():
    from io import BytesIO
    from openpyxl import load_workbook
    users = [{**vars(user), "id": str(user.id), "role": "STAFF"} for user in USERS]
    payload = {"users": users, "items": {"leave": [{
        "startDate": str(DAY), "endDate": str(DAY), "fullDay": True, "isAllUsers": True,
    }]}}
    report = asyncio.run(build_today_print_report(DAY, payload=payload, include_attachment=True))
    assert report["ga_task_summary"] == []
    assert 'data-user-comment="EF"' not in report["html"]
    assert 'data-user-comment="RA"' not in report["html"]
    assert any(mime == "image/png" and content for _, content, mime in report["attachments"])
    excel = next(content for _, content, mime in report["attachments"] if "spreadsheetml" in mime)
    sheet = load_workbook(BytesIO(excel)).active
    text = "\n".join(str(cell.value or "") for row in sheet for cell in row)
    assert "EF:" not in text
    assert "RA:" not in text


def test_saved_m3_preview_and_send_use_filtered_sections(monkeypatch):
    from app.api.routers import meetings_report as api
    from app.models.enums import UserRole
    table = "\n".join(_ascii_table("TASKS", [("NR", 2), ("KUSH", 8), ("TITULLI", 20)], [
        ["1", "EF", "Solo work"], ["2", "EF RA", "Shared work"]]))
    row = SimpleNamespace(id=uuid.uuid4(), report_date=DAY, tomorrow_date=date(2026, 11, 10),
        subject="M3", recipients={"to": ["preview@example.test"], "cc": [], "bcc": []},
        sections=[{"title": "DET PA PROGRES PINK (FT DHE PRJK)", "body": table}], generated_snapshot={},
        status="DRAFT", sent_at=None, gmail_message_id=None, gmail_thread_id=None, last_error=None,
        created_at=None, updated_at=None)
    db = AttendanceDb([entry()])
    db.get = AsyncMock(return_value=row)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    sender = AsyncMock(return_value={"id": "local-test"})
    monkeypatch.setattr(api, "send_meetings_report", sender)
    monkeypatch.setattr(api, "_validate_gmail_config", lambda: None)
    preview = asyncio.run(api.preview_draft(row.id, db=db))
    assert "Solo work" not in preview["html"]
    assert not re.search(r"\bEF\b", preview["plain_text"])
    assert "Shared work" in preview["html"]
    asyncio.run(api.send_draft(row.id, db=db, user=SimpleNamespace(id=PRESENT, role=UserRole.ADMIN)))
    args, kwargs = sender.call_args
    assert "Solo work" not in args[2] + args[3]
    assert "EF" not in kwargs["sections"][0]["body"]
    assert row.sections[0]["body"] == table
