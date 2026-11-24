from __future__ import annotations

import pytest

from io import BytesIO
import unittest
import uuid
from datetime import date, datetime, time, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

from docx import Document

from app.api.deps import require_manager_or_admin
from app.api.routers import morning_report as morning_api
from app.api.routers.morning_report import DraftUpdate, SectionPayload, router, update_draft
from app.models.common_entry import CommonEntry
from app.models.enums import CommonApprovalStatus, CommonCategory, UserRole
from app.models.morning_report_draft import MorningReportDraft
from app.models.task import Task
from app.services import morning_report_scheduler
from app.services.discord_ga_reactions import GA_REACTIONS_SECTION_KEY
from app.services.morning_report_scheduler import _due_m1_send_slot
from app.services.after_break_report import _personal_section
from app.services.meetings_report import PERSONAL_GA, render_section_report_docx, render_section_report_png
from app.services.meeting_point_manual_sync import is_known_report_title, merge_common_view_manual_sections, section_group_label, with_section_keys
from app.services.morning_report import (
    DISPLAY_SECTION_TITLES,
    GA_HV_DV_TASKS_TITLE,
    GA_PF_COMMENTS_TITLE,
    MANUAL_SECTION_TITLES,
    GA_TASKS_TITLE,
    KA_GENT_QUESTIONS_TITLE,
    MARKER_TASK_SECTIONS,
    PHYSICAL_GA_TITLE,
    SECTION_TITLES,
    TASK_FEEDBACK_OVERRIDES,
    TASK_FEEDBACK_ROWS,
    _attendance_section,
    _day_context_section,
    _ga_hv_dv_task_rows,
    _ga_hv_dv_task_section,
    _ga_hv_dv_tables_body,
    _group_marked_tasks,
    _marker_task_table,
    _marked_tasks_for_day,
    _load_symbol_comments,
    _symbol_comment_table,
    normalize_morning_report_sections,
    render_html,
    render_plain_text,
    subject_for,
)
from app.services.report_section_merge import preserve_manual_sections


class GaHvDvTodayTaskRowsTests(unittest.TestCase):
    @staticmethod
    def _task(title: str, **overrides):
        values = {
            "id": title,
            "title": title,
            "status": "TODO",
            "completed_at": None,
            "assigned_to": "ga-user",
            "start_date": datetime(2026, 9, 1, 8, 0),
            "due_date": datetime(2026, 9, 1, 16, 0),
            "phase": "MEETINGS",
            "fast_task_order": None,
            "is_deadline_important": False,
            "created_at": datetime(2026, 9, 1, 7, 0),
            "department_id": "development",
            "finish_period": "AM",
            "system_template_origin_id": None,
            "project_id": None,
            "is_bllok": False,
            "is_r1": False,
            "is_1h_report": False,
            "is_personal": False,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_includes_today_open_tasks_plus_open_overdue_tasks(self) -> None:
        report_day = date(2026, 9, 1)
        tasks = [
            self._task("GA today"),
            self._task("HV today", assigned_to="hv-user", status="IN_PROGRESS"),
            self._task("DV waiting", assigned_to="dv-user", status="WAITING_CLIENT"),
            self._task("Other user", assigned_to="other-user"),
            self._task("Done today", status="DONE", completed_at=datetime(2026, 9, 1, 9, 0)),
            self._task("Late", start_date=datetime(2026, 8, 31, 8, 0), due_date=datetime(2026, 8, 31, 16, 0)),
            self._task("Future", start_date=datetime(2026, 9, 2, 8, 0), due_date=datetime(2026, 9, 2, 16, 0)),
            self._task("Multi-day today", start_date=datetime(2026, 8, 31, 8, 0), due_date=datetime(2026, 9, 2, 16, 0)),
            self._task("GA secondary", assigned_to="other-user"),
        ]
        assignees = {task.id: {task.assigned_to} for task in tasks}
        assignees["GA secondary"].add("ga-user")
        names = {
            "ga-user": "Gane Arifaj",
            "hv-user": "Hana Vela",
            "dv-user": "Drita Vela",
            "other-user": "Example User",
        }

        rows = _ga_hv_dv_task_rows(
            tasks, names, assignees, report_day, {"development": "DEV"}
        )

        self.assertEqual(
            {row[7] for row in rows},
            {
                "GA today", "HV today", "DV waiting", "Late",
                "Multi-day today", "GA secondary",
            },
        )
        self.assertNotIn("Done today", {row[7] for row in rows})
        self.assertNotIn("Future", {row[7] for row in rows})
        status_by_title = {row[7]: row[5] for row in rows}
        self.assertEqual(status_by_title["Late"], "LATE")
        tyo_by_title = {row[7]: row[6] for row in rows}
        self.assertEqual(tyo_by_title["GA today"], "T")
        self.assertEqual(tyo_by_title["Late"], "Y")
        self.assertEqual(tyo_by_title["Multi-day today"], "T")

    def test_requested_section_order_is_used_in_m1_and_email(self) -> None:
        comments = GA_PF_COMMENTS_TITLE
        expected = [
            SECTION_TITLES[2], GA_HV_DV_TASKS_TITLE, PHYSICAL_GA_TITLE, SECTION_TITLES[1],
            SECTION_TITLES[0], GA_REACTIONS_SECTION_KEY, comments, SECTION_TITLES[3],
            SECTION_TITLES[4], SECTION_TITLES[5], KA_GENT_QUESTIONS_TITLE, *SECTION_TITLES[7:9],
        ]
        manual = {"title": "Pyetje manuale", "section_key": "manual:custom:1:test", "body": "Manual"}
        saved = [
            {"title": title, "section_key": title, "body": "Saved content"}
            for title in reversed(expected) if title != comments
        ]
        sections = normalize_morning_report_sections([manual, *saved])
        self.assertEqual([section["section_key"] for section in sections], [manual["section_key"], *expected])
        self.assertIn("(Asnje koment te simbolet)", sections[7]["body"])
        self.assertEqual(section_group_label("morning", comments, comments), "AUTO-FILLED FROM PRIMEFLOW")
        report_day = date(2026, 9, 1)
        document = Document(BytesIO(render_section_report_docx("M1", "M1", report_day, sections)))
        for output in (
            render_html("M1", report_day, sections),
            render_plain_text("M1", report_day, sections),
            document.element.body.xml,
        ):
            offsets = [output.index(section["title"]) for section in sections]
            self.assertEqual(offsets, sorted(offsets))

        regenerated = preserve_manual_sections(normalize_morning_report_sections([]), [
            {"title": comments, "section_key": comments, "body": "Dy komente për diskutim"},
        ], MANUAL_SECTION_TITLES)
        self.assertIn("(Asnje koment te simbolet)", normalize_morning_report_sections(regenerated)[6]["body"])

    def test_symbol_comments_use_a_saved_table_in_every_m1_format(self) -> None:
        report_day = date(2026, 9, 1)
        body = _symbol_comment_table([[
            "1", "GA", "DEV", "AM", "SYS", "TODO", "!", "Verify task",
            "Only the saved comment", "01.09.2026 08:35",
        ]])
        sections = [{"title": GA_PF_COMMENTS_TITLE, "section_key": GA_PF_COMMENTS_TITLE, "body": body}]
        document = Document(BytesIO(render_section_report_docx("M1", "M1", report_day, sections)))
        for output in (
            render_html("M1", report_day, sections),
            render_plain_text("M1", report_day, sections),
            document.element.body.xml,
        ):
            self.assertIn("Verify task", output)
            self.assertIn("Only the saved comment", output)
        self.assertTrue(render_section_report_png("M1", "M1", report_day, sections).startswith(b"\x89PNG"))

    def test_symbol_comments_use_the_previous_calendar_day_and_generation_cutoff(self) -> None:
        import asyncio

        zone = ZoneInfo("Europe/Budapest")
        generated_at = datetime(2026, 9, 7, 8, 35, tzinfo=zone)
        event = SimpleNamespace(
            task_id="task", marker="P!", comment="New | comment",
            created_at=datetime(2026, 9, 6, 16, 30, tzinfo=zone),
        )
        task = self._task("Review task", id="task", one_h_marker="F")
        other = self._task("Without comment", id="other")
        db = Mock()
        result = Mock()
        result.scalars.return_value.all.return_value = [event]
        db.execute = AsyncMock(return_value=result)
        with patch("app.services.morning_report.report_timezone", return_value=zone):
            rows = asyncio.run(_load_symbol_comments(db, generated_at.date(), generated_at, [task, other], {}, {}, {}))
        statement = db.execute.await_args.args[0]
        self.assertEqual(list(statement.compile().params.values()), [
            datetime(2026, 9, 6, 16, 30, tzinfo=zone), generated_at, datetime(2026, 9, 8, tzinfo=zone),
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][7:], ["Review task", "New ｜ comment", "06.09.2026 16:30"])

    def test_physical_ga_includes_the_report_day_within_the_local_task_range(self) -> None:
        report_day = date(2026, 9, 1)
        tasks = [
            self._task("Physical today", one_h_marker="F"),
            self._task("Physical done", one_h_marker="SHARE,F", status="DONE"),
            self._task("Physical after local midnight", one_h_marker="F,SHARE",
                       start_date=datetime(2026, 8, 31, 22, 15, tzinfo=timezone.utc)),
            self._task("Missing start", one_h_marker="F", start_date=None),
            self._task("Spans days", one_h_marker="F", due_date=datetime(2026, 9, 2, 16)),
            self._task("Ends on report day", one_h_marker="F", start_date=datetime(2026, 8, 31, 8)),
            self._task("GA only", one_h_marker="FLAG"),
        ]
        markers, caption = MARKER_TASK_SECTIONS[PHYSICAL_GA_TITLE]
        selected = _marked_tasks_for_day(tasks, report_day, markers)
        self.assertEqual(selected, tasks[:-1])
        body = _marker_task_table(caption, selected, {"ga-user": "Gane Arifaj"}, {}, {"development": "DEV"})
        self.assertLess(body.index("Physical today"), body.index("Physical done"))
        html = render_html(subject_for(report_day), report_day, [{"title": PHYSICAL_GA_TITLE, "body": body}])
        self.assertIn("<table", html)
        self.assertIn("Physical after local midnight", html)
        self.assertIn("Physical done", html)
        self.assertIn('data-task-symbol="true"', html)
        self.assertRegex(html, r'<tr[^>]*class="todo"')
        self.assertRegex(html, r'<tr[^>]*class="done"')
        self.assertNotIn("[[", html)

    def test_ka_gent_questions_include_either_symbol_and_list_each_task_once(self) -> None:
        tasks = [
            self._task("Ask KA", one_h_marker="KA"),
            self._task("Ask Gent", one_h_marker="F,GENT"),
            self._task("Ask both", one_h_marker="KA,GENT"),
            self._task("Range covers today", one_h_marker="GENT", start_date=datetime(2026, 8, 31, 8), due_date=datetime(2026, 9, 2, 16)),
            self._task("Ask later", one_h_marker="GENT", start_date=datetime(2026, 9, 2, 8), due_date=datetime(2026, 9, 2, 16)),
            self._task("Already due", one_h_marker="KA", start_date=datetime(2026, 8, 31, 8), due_date=datetime(2026, 8, 31, 16)),
            self._task("GA and physical", one_h_marker="FLAG,F"),
            self._task("KA in title only"),
        ]
        markers, _ = MARKER_TASK_SECTIONS[KA_GENT_QUESTIONS_TITLE]
        self.assertEqual(_marked_tasks_for_day(tasks, date(2026, 9, 1), markers), tasks[:4])

    def test_marker_tables_group_copies_with_the_same_symbols_and_union_assignees(self) -> None:
        names = {"ga-user": "Gane Arifaj", "dv-user": "Drita Vela", "hv-user": "Hana Vela"}
        first = self._task("Shared task", id="one", fast_task_group_id="shared", one_h_marker="F,KA", status="DONE")
        second = self._task("Shared task", id="two", fast_task_group_id="shared", one_h_marker="KA,F", assigned_to="dv-user")
        owners = {"one": {"ga-user"}, "two": {"dv-user", "hv-user"}}

        for title in (PHYSICAL_GA_TITLE, KA_GENT_QUESTIONS_TITLE):
            with self.subTest(title=title):
                markers, caption = MARKER_TASK_SECTIONS[title]
                selected = _marked_tasks_for_day([first, second], date(2026, 9, 1), markers)
                grouped, grouped_owners = _group_marked_tasks(selected, names, owners)
                self.assertEqual(grouped, [second])
                self.assertEqual(grouped_owners, {"two": set(names)})
                body = _marker_task_table(caption, grouped, names, grouped_owners, {"development": "DEV"})
                self.assertEqual(body.count("Shared task"), 1)
                self.assertIn("DV / GA / HV", body)
                self.assertIn("DV / GA / HV", render_html("M1", date(2026, 9, 1), [{"title": title, "body": body}]))
        self.assertEqual(owners["two"], {"dv-user", "hv-user"})

    def test_marker_groups_preserve_distinct_symbols_and_independently_created_project_tasks(self) -> None:
        tasks = [
            self._task("Review project", id="one", project_id="project", one_h_marker="KA"),
            self._task("Review project", id="two", project_id="project", one_h_marker="KA", assigned_to="dv-user"),
            self._task("Review project", id="three", project_id="project", one_h_marker="GENT"),
            self._task("Review project", id="four", project_id="project", one_h_marker="KA", created_at=datetime(2026, 9, 1, 7, 1)),
        ]
        grouped, owners = _group_marked_tasks(tasks, {"ga-user": "Gane Arifaj", "dv-user": "Drita Vela"}, {})
        self.assertEqual(len(grouped), 3)
        self.assertTrue({"ga-user", "dv-user"} in owners.values())
        self.assertIn("three", owners)
        self.assertIn("four", owners)

    def test_hv_table_uses_finance_department_instead_of_hv_assignee(self) -> None:
        report_day = date(2026, 9, 1)
        finance_task = self._task(
            "Finance task assigned to HS",
            assigned_to="hs-user",
            department_id="finance",
        )
        hv_assigned_dev_task = self._task(
            "Development task assigned to HV",
            assigned_to="hv-user",
            department_id="development",
        )
        names = {
            "hs-user": "Haxhere Spahiu",
            "hv-user": "Hana Vela",
        }
        assignees = {
            finance_task.id: {"hs-user"},
            hv_assigned_dev_task.id: {"hv-user"},
        }

        rows = _ga_hv_dv_task_rows(
            [finance_task, hv_assigned_dev_task],
            names,
            assignees,
            report_day,
            {"finance": "FIN", "development": "DEV"},
            "HV",
        )

        self.assertEqual([row[7] for row in rows], ["Finance task assigned to HS"])

    def test_ga_hv_dv_uses_one_section_with_three_separate_tables(self) -> None:
        body = _ga_hv_dv_tables_body({
            GA_TASKS_TITLE: [["1", "GA", "GA", "AM", "P", "TODO", "T", "GA task"]],
            "HV TASKS": [],
            "DV TASKS": [["1", "DV", "PCM", "PM", "PRJK", "LATE", "Y", "DV task"]],
        })

        self.assertEqual(body.count("GA TASKS:"), 1)
        self.assertEqual(body.count("HV TASKS:"), 1)
        self.assertEqual(body.count("DV TASKS:"), 1)
        self.assertLess(body.index("HV TASKS:"), body.index("DV TASKS:"))
        self.assertLess(body.index("DV TASKS:"), body.index("GA TASKS:"))
        self.assertNotIn("HV TASKS: 0", body)
        self.assertIn("(Asnje detyre)", body)
        self.assertIn("T/Y/O", body)
        self.assertIn("VAZHDON?", body)
        self.assertIn("KOMENT", body)
        self.assertEqual(body.count("BZ ME"), 1)
        report_html = render_html(
            subject_for(date(2026, 9, 1)),
            date(2026, 9, 1),
            [{"title": GA_HV_DV_TASKS_TITLE, "body": body}],
        )
        self.assertIn('class="n tyo-overdue"', report_html)
        self.assertIn("background-color:#dc2626!important", report_html)
        self.assertIn("font-weight:400;text-align:left", report_html)
        normalized = normalize_morning_report_sections([
            {"title": "GA TASKS", "body": "old ga"},
            {"title": "HV TASKS", "body": "old hv"},
            {"title": "DV TASKS", "body": "old dv"},
        ])
        self.assertEqual(
            [section["title"] for section in normalized].count(GA_HV_DV_TASKS_TITLE), 1
        )

    def test_ga_hv_dv_html_has_dark_divider_between_am_and_pm(self) -> None:
        body = _ga_hv_dv_tables_body({
            GA_TASKS_TITLE: [
                ["1", "GA", "GA", "AM", "SYS", "TODO", "T", "AM task"],
                ["2", "GA", "GA", "PM", "SYS", "TODO", "T", "PM task"],
            ],
            "HV TASKS": [],
            "DV TASKS": [],
        })

        report_html = render_html(
            subject_for(date(2026, 9, 1)),
            date(2026, 9, 1),
            [{"title": GA_HV_DV_TASKS_TITLE, "body": body}],
        )

        self.assertEqual(report_html.count("am-pm-divider"), 10)
        self.assertIn("border-top:3px solid #334155!important", report_html)

        unrelated_body = _ga_hv_dv_tables_body({
            GA_TASKS_TITLE: [],
            "HV TASKS": [],
            "DV TASKS": [],
        })
        unrelated_table = body.replace("GA TASKS:", "TODO:", 1)
        unrelated_html = render_html(
            subject_for(date(2026, 9, 1)),
            date(2026, 9, 1),
            [{"title": "OTHER REPORT", "body": unrelated_table + unrelated_body}],
        )
        # The copied AM/PM table is not an M1 GA/HV/DV table once relabeled.
        self.assertEqual(unrelated_html.count("am-pm-divider"), 0)

    def test_orders_by_period_then_type_then_status(self) -> None:
        report_day = date(2026, 9, 1)
        ga_id = uuid.uuid4()
        names = {ga_id: "Gane Arifaj"}
        tasks = [
            self._task("PM system todo", assigned_to=ga_id, finish_period="PM", system_template_origin_id=uuid.uuid4()),
            self._task("AM project late", assigned_to=ga_id, finish_period="AM", project_id=uuid.uuid4(), due_date=datetime(2026, 8, 31, tzinfo=timezone.utc)),
            self._task("AM fast progress", assigned_to=ga_id, finish_period="AM", status="IN_PROGRESS"),
            self._task("AM fast todo", assigned_to=ga_id, finish_period="AM", status="TODO"),
            self._task("AM system done", assigned_to=ga_id, finish_period="AM", status="DONE", completed_at=datetime(2026, 9, 1, tzinfo=timezone.utc), system_template_origin_id=uuid.uuid4()),
        ]

        rows = _ga_hv_dv_task_rows(tasks, names, {}, report_day, target_initials="GA")

        self.assertEqual(
            [row[7] for row in rows],
            [
                "AM fast todo",
                "AM fast progress",
                "AM project late",
                "PM system todo",
            ],
        )

    def test_overdue_system_tasks_are_placed_at_the_end(self) -> None:
        report_day = date(2026, 9, 2)
        ga_id = uuid.uuid4()
        names = {ga_id: "Gane Arifaj"}
        tasks = [
            self._task(
                "Late AM system",
                assigned_to=ga_id,
                finish_period="AM",
                system_template_origin_id=uuid.uuid4(),
                start_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
                due_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
            ),
            self._task(
                "Today PM project",
                assigned_to=ga_id,
                finish_period="PM",
                project_id=uuid.uuid4(),
                start_date=datetime(2026, 9, 2, tzinfo=timezone.utc),
                due_date=datetime(2026, 9, 2, tzinfo=timezone.utc),
            ),
            self._task(
                "Today PM system",
                assigned_to=ga_id,
                finish_period="PM",
                system_template_origin_id=uuid.uuid4(),
                start_date=datetime(2026, 9, 2, tzinfo=timezone.utc),
                due_date=datetime(2026, 9, 2, tzinfo=timezone.utc),
            ),
        ]

        rows = _ga_hv_dv_task_rows(tasks, names, {}, report_day, target_initials="GA")

        self.assertEqual(
            [row[7] for row in rows],
            ["Today PM system", "Today PM project", "Late AM system"],
        )
        self.assertEqual(rows[-1][6], "Y")


class FakeDraftDb:
    def __init__(self, draft: MorningReportDraft) -> None:
        self.draft = draft

    async def get(self, _model, _draft_id):
        return self.draft

    async def execute(self, _query):
        return Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=[]))))

    async def commit(self) -> None:
        return None

    async def refresh(self, _row) -> None:
        return None


class ScalarResult:
    def __init__(self, value) -> None:
        self.value = value

    def scalars(self):
        return self

    def first(self):
        return self.value

    def scalar_one_or_none(self):
        return self.value


class SchedulerDb:
    def __init__(self, settings, draft) -> None:
        self.results = iter((ScalarResult(settings), ScalarResult(draft), ScalarResult(None)))

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
        return None

    async def execute(self, _query):
        return next(self.results)

    async def commit(self) -> None:
        return None


def make_draft() -> MorningReportDraft:
    return MorningReportDraft(
        id=uuid.uuid4(),
        report_date=date(2026, 8, 5),
        subject="Saved M1 subject",
        recipients={"to": ["old@example.com"], "cc": [], "bcc": []},
        sections=[{"title": SECTION_TITLES[2], "body": "Saved manual plan change"}],
        generated_snapshot={},
        status="DRAFT",
    )


class MorningReportWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_ga_next_workday_is_readable_by_staff_but_not_editable(self) -> None:
        from fastapi import HTTPException

        db = AsyncMock()
        staff = SimpleNamespace(id=uuid.uuid4(), role=UserRole.STAFF, username="other-staff")
        ga = SimpleNamespace(id=uuid.uuid4(), username="gane.arifaj", is_active=True)
        target = date(2026, 11, 23)
        with (
            patch.object(morning_api, "resolve_ga_user", new=AsyncMock(return_value=ga)),
            patch.object(morning_api, "_next_workday_tasks", new=AsyncMock(return_value=(target, []))) as tasks,
        ):
            result = await morning_api.get_next_workday_feedback("ga", db=db, user=staff)
        tasks.assert_awaited_once_with(db, ga, "ga")
        self.assertEqual(result, {"target_date": target, "tasks": []})
        with self.assertRaises(HTTPException) as forbidden:
            await morning_api.save_next_workday_feedback(
                uuid.uuid4(), "ga",
                morning_api.NextWorkdayFeedbackEdit(target_date=target, comment="Test"), db, staff,
            )
        self.assertEqual(forbidden.exception.status_code, 403)

    async def test_admin_can_save_ga_next_workday_feedback_with_audit(self) -> None:
        db = AsyncMock()
        db.add = Mock()
        ga = SimpleNamespace(id=uuid.uuid4(), username="gane.arifaj", is_active=True)
        admin = SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN)
        task_id = uuid.uuid4()
        target = date(2026, 11, 23)
        with (
            patch.object(morning_api, "resolve_ga_user", new=AsyncMock(return_value=ga)),
            patch.object(morning_api, "_next_workday_tasks", new=AsyncMock(
                return_value=(target, [{"task_id": str(task_id)}]),
            )) as tasks,
        ):
            await morning_api.save_next_workday_feedback(
                task_id, "ga", morning_api.NextWorkdayFeedbackEdit(target_date=target, continuation="PO"), db, admin,
            )
        tasks.assert_awaited_once_with(db, ga, "ga")
        self.assertEqual(db.execute.await_args.args[0].compile().params["user_id"], ga.id)
        self.assertEqual(db.add.call_args.args[0].actor_user_id, admin.id)
        db.commit.assert_awaited_once()

    async def test_friday_admin_finance_comment_is_saved_for_hv_on_monday(self) -> None:
        from app.api.routers import discord_m3

        friday = datetime(2026, 11, 20, 16, tzinfo=ZoneInfo("Europe/Budapest"))
        monday = date(2026, 11, 23)
        hv = SimpleNamespace(id=uuid.uuid4(), full_name="Haxhere Spahiu", is_active=True)
        admin = SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN)
        task_id, department_id = uuid.uuid4(), uuid.uuid4()
        db = AsyncMock()
        db.add = Mock()
        db.get.return_value = hv
        db.execute.side_effect = [Mock(all=Mock(return_value=[(task_id, department_id, "FIN")])), Mock()]
        with (
            patch.object(morning_api, "datetime", wraps=datetime) as clock,
            patch.object(discord_m3, "tomorrow_data", new=AsyncMock(
                return_value=([{"task_id": str(task_id)}], {}, {}),
            )) as tomorrow,
        ):
            clock.now.side_effect = lambda tz: friday.astimezone(tz)
            await morning_api.save_next_workday_feedback(
                task_id, "finance", morning_api.NextWorkdayFeedbackEdit(
                    target_date=monday, continuation="JO", comment="Komenti i së premtes",
                ), db, admin, person_id=hv.id,
            )
        tomorrow.assert_awaited_once_with(db, monday, user_id=hv.id)
        params = db.execute.await_args.args[0].compile().params
        self.assertEqual(params["target_date"], monday)
        self.assertEqual(params["user_id"], hv.id)
        self.assertEqual(params["comment"], "Komenti i së premtes")
        self.assertEqual(db.add.call_args.args[0].actor_user_id, admin.id)
        db.commit.assert_awaited_once()

    async def test_next_workday_task_feedback_rejects_other_users_and_stale_dates(self) -> None:
        from fastapi import HTTPException
        db = AsyncMock()
        outsider = SimpleNamespace(id=uuid.uuid4(), full_name="Other user")
        with self.assertRaises(HTTPException) as forbidden:
            await morning_api.get_next_workday_feedback("finance", db=db, user=outsider)
        self.assertEqual(forbidden.exception.status_code, 403)
        db.execute.assert_not_awaited()

        task_id = uuid.uuid4()
        target = date(2026, 11, 23)
        user = SimpleNamespace(id=uuid.uuid4(), full_name="Haxhere Spahiu")
        with patch.object(morning_api, "_next_workday_tasks", new=AsyncMock(
            return_value=(target, [{"task_id": str(task_id)}]),
        )):
            with self.assertRaises(HTTPException) as stale:
                await morning_api.save_next_workday_feedback(task_id, "finance",
                    morning_api.NextWorkdayFeedbackEdit(target_date=date(2026, 11, 20), comment="Stale"), db, user)
            self.assertEqual(stale.exception.status_code, 409)
            db.execute.assert_not_awaited()
            await morning_api.save_next_workday_feedback(task_id, "finance",
                morning_api.NextWorkdayFeedbackEdit(target_date=target, comment=""), db, user)
        self.assertIn("ON CONFLICT", str(db.execute.await_args.args[0]))
        db.commit.assert_awaited_once()

    async def test_task_feedback_uses_owner_and_task_id_and_keeps_manual_fields(self) -> None:
        report_day = date(2026, 9, 1)
        ga = GaHvDvTodayTaskRowsTests._task("Same title", id=uuid.uuid4(), system_template_origin_id=uuid.uuid4())
        dv = GaHvDvTodayTaskRowsTests._task(
            "Same title", id=uuid.uuid4(), assigned_to="dv-user",
            start_date=datetime(2026, 9, 2, 8, 0), due_date=datetime(2026, 9, 2, 16, 0),
        )
        finance = GaHvDvTodayTaskRowsTests._task(
            "Finance task", id=uuid.uuid4(), assigned_to="hs-user", department_id="finance",
        )
        db = AsyncMock()
        db.execute.side_effect = [
            Mock(all=Mock(return_value=[
                (ga.id, "ga-user", {"action": "PO"}, "Discord GA", None),
                (ga.id, "other-user", {"action": "JO"}, "Wrong owner", None),
                (dv.id, "dv-user", {"action": "postpone"}, "Discord DV", None),
                (finance.id, "hs-user", {"action": "comment"}, "Older finance comment", None),
            ])),
            Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=[
                SimpleNamespace(task_id=finance.id, user_id="hs-user", continuation=None,
                                comment="Finance comment from PrimeFlow", updated_at=datetime.now(timezone.utc)),
            ])))),
            Mock(all=Mock(return_value=[(ga.id, "other-user")])),
            Mock(all=Mock(return_value=[
                (ga.system_template_origin_id, "oh-user", ["ga-user", "oh-user"], "ga-user"),
            ])),
            Mock(all=Mock(return_value=[("oh-user", "Owner Hoxha", "owner.hoxha")])),
        ]
        body, feedback = await _ga_hv_dv_task_section(
            db, [ga, dv, finance],
            {"ga-user": "Gane Arifaj", "dv-user": "Diellza Veliu", "hs-user": "Haxhere Spahiu"},
            {ga.id: {"ga-user", "other-user"}}, report_day, {"finance": "FIN"},
            {
                f"GA TASKS:{ga.id}": {"comment": "Manual GA"},
                "plan:HV": {"continuation": "PO", "comment": "Ndryshim në Finance"},
                "plan:DV": {"continuation": "JO"},
            },
        )
        self.assertEqual(feedback["GA TASKS"][0]["continuation"], "PO")
        self.assertEqual(feedback["GA TASKS"][0]["comment"], "Manual GA")
        self.assertEqual(feedback["DV TASKS"][0]["continuation"], "JO")
        self.assertEqual(feedback["HV TASKS"][0]["continuation"], "")
        self.assertIn("✓", body)
        self.assertIn("Discord DV", body)
        self.assertIn("Finance comment from PrimeFlow", body)
        self.assertEqual(len(feedback["plan"]), 3)
        self.assertIn("A prishet plani për sot? (HV): Po · Ndryshim në Finance", body)
        self.assertIn("A prishet plani për sot? (DV): Jo", body)
        self.assertIn("A prishet plani për sot? (GA): –", body)
        self.assertNotIn("Older finance comment", body)
        self.assertNotIn("Wrong owner", body)
        self.assertRegex(body, r"\| Same title\s+\| OH\s+\| ✓\s+\| Manual GA")
        sections = [{"title": GA_HV_DV_TASKS_TITLE, "body": body}]
        subject = subject_for(report_day)
        html = render_html(subject, report_day, sections)
        self.assertIn("Ndryshim në Finance", html)
        self.assertRegex(html, r"<td[^>]*>OH</td>")
        self.assertRegex(html, r'<td[^>]*bgcolor="#DCFCE7"[^>]*>✓</td>')
        self.assertRegex(html, r'<td[^>]*bgcolor="#FEE2E2"[^>]*>X</td>')
        from docx import Document
        document = Document(BytesIO(render_section_report_docx(subject, "M1", report_day, sections)))
        cells = [cell.text for table in document.tables for row in table.rows for cell in row.cells]
        self.assertIn("✓", cells)
        self.assertIn("X", cells)
        self.assertIn("Discord DV", cells)
        self.assertIn("BZ ME", cells)
        self.assertIn("OH", cells)
        self.assertTrue(render_section_report_png(subject, "M1", report_day, sections).startswith(b"\x89PNG"))

    async def test_task_feedback_patch_keeps_other_fields_and_saves_an_explicit_blank(self) -> None:
        draft = make_draft()
        key = f"GA TASKS:{uuid.uuid4()}"
        draft.generated_snapshot = {TASK_FEEDBACK_OVERRIDES: {key: {"continuation": "JO"}}}
        feedback_rows = {"GA TASKS": [{"key": key, "continuation": "JO", "comment": ""}]}
        refreshed = [{
            "section_key": GA_HV_DV_TASKS_TITLE, "title": GA_HV_DV_TASKS_TITLE,
            "body": "Updated table", TASK_FEEDBACK_ROWS: feedback_rows,
        }]
        db = AsyncMock()
        db.get.return_value = draft
        with (
            patch.object(morning_api, "refresh_morning_task_tables", new=AsyncMock(return_value=refreshed)) as refresh,
            patch.object(morning_api, "filter_report_sections", new=AsyncMock(side_effect=lambda _, sections, __: sections)),
        ):
            result = await update_draft(
                draft.id, DraftUpdate(task_feedback={key: {"comment": ""}}),
                db, SimpleNamespace(id=uuid.uuid4(), role=UserRole.STAFF),
            )
        overrides = {key: {"continuation": "JO", "comment": ""}}
        self.assertEqual(refresh.await_args.kwargs["task_feedback_overrides"], overrides)
        self.assertEqual(draft.generated_snapshot[TASK_FEEDBACK_OVERRIDES], overrides)
        self.assertEqual(result[TASK_FEEDBACK_ROWS], feedback_rows)
        db.commit.assert_awaited_once()

    async def test_read_returns_refreshed_f_table_without_overwriting_draft(self) -> None:
        old = [{"section_key": PHYSICAL_GA_TITLE, "title": PHYSICAL_GA_TITLE, "body": "Old table"}]
        fresh = [{**old[0], "body": "Updated F table"}]
        row = SimpleNamespace(report_date=date(2026, 11, 19), sections=old, status="SENT", sent_at=None,
                              generated_snapshot={})
        db = AsyncMock()
        db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=row))
        with (patch.object(morning_api, "refresh_morning_task_tables", new=AsyncMock(return_value=fresh)),
              patch.object(morning_api, "refresh_m1_section", new=AsyncMock(return_value=fresh)),
              patch.object(morning_api, "_get_or_create_settings", new=AsyncMock(return_value=SimpleNamespace(manual_questions=[]))),
              patch.object(morning_api, "merge_common_view_manual_sections", new=AsyncMock(return_value=fresh)),
              patch.object(morning_api, "_draft", new=AsyncMock(return_value={"sections": fresh})) as result):
            payload = await morning_api.get_draft(row.report_date, db, None)
        result.assert_awaited_once_with(db, row, fresh)
        self.assertEqual(payload["sections"][0]["body"], "Updated F table")
        self.assertEqual(row.sections, old)
        db.commit.assert_not_awaited()

    async def test_generating_existing_m1_keeps_both_automatic_symbol_tables(self) -> None:
        row = make_draft()
        marker_sections = [
            {"section_key": title, "title": title, "body": f"Updated {caption}"}
            for title, (_, caption) in MARKER_TASK_SECTIONS.items()
        ]
        manual = {"section_key": "manual:custom:1:retained", "title": "Another question", "body": "Keep this answer"}
        row.sections = [*normalize_morning_report_sections([]), manual]
        db = AsyncMock()
        db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=row),
                                       scalars=Mock(return_value=Mock(all=Mock(return_value=[]))))
        user = SimpleNamespace(id=uuid.uuid4())
        with (
            patch.object(morning_api, "_default_draft_recipients", AsyncMock(return_value=row.recipients)),
            patch.object(morning_api, "_get_or_create_settings", AsyncMock(return_value=SimpleNamespace(manual_questions=[]))),
            patch.object(morning_api, "build_morning_report_sections", AsyncMock(return_value=(marker_sections, {}))),
            patch("app.services.meeting_point_manual_sync.load_common_view_extra_titles", AsyncMock(return_value=[])),
        ):
            payload = await morning_api.generate_draft(row.report_date, db, user)

        for sections in (row.sections, payload["sections"]):
            by_key = {section["section_key"]: section for section in sections}
            for section in [*marker_sections, manual]:
                self.assertEqual(by_key[section["section_key"]]["body"], section["body"])

    async def test_retired_questions_are_removed_from_saved_and_regenerated_m1(self) -> None:
        retired = [
            {"title": "3. Pikat e ditës sot", "section_key": "manual:custom:3:retired", "body": "Old answer"},
            {"title": "2. EP: A është lëshuar Mira? (Para TAK 1–2 min)",
             "section_key": "manual:custom:2:retired", "body": "Old Mira answer"},
        ]
        retained = {"title": "Another question", "section_key": "manual:custom:2:retained", "body": "Keep this answer"}
        sections = normalize_morning_report_sections([*retired, retained, {"title": "PIKAT E DITES SOT", "body": "Legacy"}])
        self.assertEqual([section["section_key"] for section in sections], [retained["section_key"], *DISPLAY_SECTION_TITLES])
        for question in retired:
            self.assertTrue(is_known_report_title("morning", question["title"]))
            self.assertFalse(is_known_report_title("after_break", question["title"]))
            self.assertFalse(is_known_report_title("meetings", question["title"]))

        with patch("app.services.meeting_point_manual_sync.load_common_view_extra_titles", new_callable=AsyncMock) as load:
            load.return_value = ["PIKAT E DITES SOT", "EP: A ESHTE LESHUAR MIRA? (PARA TAK 1-2 MIN)"]
            regenerated = await merge_common_view_manual_sections(None, sections, "morning", retired, retired)
        self.assertEqual(regenerated, sections)
        html = render_html("M1", date(2026, 9, 1), regenerated)
        self.assertNotIn("Old answer", html)
        self.assertNotIn("Old Mira answer", html)
        self.assertIn("Keep this answer", html)

    async def test_marker_tables_replace_legacy_manual_questions_without_duplicates(self) -> None:
        legacy = [
            {"title": "4. Fizikisht me GA?", "section_key": "manual:custom:4:physical", "body": "Manual"},
            {"title": "5. A ka pyetje/sqarime me KA/Gentin?", "section_key": "manual:custom:5:questions", "body": "Manual"},
        ]
        sections = normalize_morning_report_sections(legacy)
        self.assertEqual([section["section_key"] for section in sections], DISPLAY_SECTION_TITLES)
        for section in (section for section in sections if section["section_key"] in MARKER_TASK_SECTIONS):
            self.assertIn("Asnje detyre", section["body"])
            self.assertEqual(section_group_label("morning", section["title"]), "AUTO-FILLED FROM PRIMEFLOW")

        with patch("app.services.meeting_point_manual_sync.load_common_view_extra_titles", new_callable=AsyncMock) as load:
            load.return_value = [question["title"] for question in legacy] + ["Another question"]
            merged = await merge_common_view_manual_sections(None, sections, "morning", legacy, legacy)
        self.assertEqual(merged[0]["title"], "Another question")
        self.assertEqual([section["section_key"] for section in merged[1:]], DISPLAY_SECTION_TITLES)

    def test_personal_and_wfc_sections_are_labeled_as_auto_filled(self) -> None:
        self.assertEqual(SECTION_TITLES[7], "DET PERSONALISHT ME KA/GENTIN?")
        self.assertEqual(SECTION_TITLES[8], "WFC ME KA/GENTIN?")
        self.assertEqual(section_group_label("morning", SECTION_TITLES[7]), "AUTO-FILLED FROM PRIMEFLOW")
        self.assertEqual(section_group_label("morning", SECTION_TITLES[8]), "AUTO-FILLED FROM PRIMEFLOW")

    def test_edited_auto_title_keeps_m1_identity_position_and_group(self) -> None:
        sections = normalize_morning_report_sections(
            with_section_keys("morning", [{"title": title, "body": str(i)} for i, title in enumerate(SECTION_TITLES)])
        )
        email_index = DISPLAY_SECTION_TITLES.index(SECTION_TITLES[1])
        sections[email_index]["title"] = "CUSTOM EMAIL TASKS TITLE"

        normalized = normalize_morning_report_sections(sections)

        self.assertEqual(normalized[email_index]["title"], "CUSTOM EMAIL TASKS TITLE")
        self.assertEqual(normalized[email_index]["section_key"], SECTION_TITLES[1])
        self.assertEqual(
            section_group_label("morning", normalized[email_index]["title"], normalized[email_index]["section_key"]),
            "AUTO-FILLED FROM PRIMEFLOW",
        )

    def test_m1_auto_delivery_uses_only_the_0700_and_0900_slots(self) -> None:
        timezone = ZoneInfo("Europe/Tirane")
        self.assertIsNone(_due_m1_send_slot(datetime(2026, 8, 5, 6, 59, tzinfo=timezone), set()))
        self.assertEqual(_due_m1_send_slot(datetime(2026, 8, 5, 7, 0, tzinfo=timezone), set()), "07:00")
        self.assertEqual(_due_m1_send_slot(datetime(2026, 8, 5, 9, 0, tzinfo=timezone), {"07:00"}), "09:00")
        # Deploying after 09:00 must not backfill 07:00 and 09:00 as two rapid emails.
        self.assertEqual(_due_m1_send_slot(datetime(2026, 8, 5, 9, 15, tzinfo=timezone), set()), "09:00")
        self.assertIsNone(
            _due_m1_send_slot(datetime(2026, 8, 5, 9, 15, tzinfo=timezone), {"07:00", "09:00"})
        )

    def test_normalization_keeps_all_six_m1_questions_and_saved_edits(self) -> None:
        sections = normalize_morning_report_sections(
            [{"title": SECTION_TITLES[0], "body": "GA replied at 07:55"}]
        )

        self.assertEqual([section["section_key"] for section in sections], DISPLAY_SECTION_TITLES)
        bodies = {section["section_key"]: section["body"] for section in sections}
        self.assertEqual(bodies[SECTION_TITLES[0]], "GA replied at 07:55")
        self.assertEqual(bodies[SECTION_TITLES[1]], "")
        self.assertIn("NDRYSHON PLANI", bodies[SECTION_TITLES[2]])

    def test_old_pv_table_moves_into_first_automatic_section_once(self) -> None:
        from io import BytesIO
        from docx import Document
        from app.services.meetings_report import render_section_report_docx
        from app.services.morning_report import preserve_morning_plan_note, render_plain_text

        pv = "PV\n+----+------+------+------------+------------+\n| NR | KUSH | DEP | NGA | DERI |\n+----+------+------+------------+------------+\n| 1 | DV | PCM | 23.11.2026 | 27.11.2026 |\n+----+------+------+------------+------------+"
        existing = [
            {"title": SECTION_TITLES[0], "body": "GA reply"},
            {"title": SECTION_TITLES[2], "section_key": SECTION_TITLES[2],
             "body": "VONESA: 0\n\nMUNGESA: 0\n\nNDRYSHON PLANI: Ruaje këtë vendim"},
            {"title": SECTION_TITLES[4], "body": f"{pv}\n\nFESTA EXTERNE: 0\n\nTAKIMET EXTERNE: 0"},
            {"title": "Pyetje manuale", "section_key": "manual:custom:1:test", "body": "Manual"},
        ]
        sections = normalize_morning_report_sections(existing)
        self.assertEqual(sections[0]["title"], "Pyetje manuale")
        first_auto = sections[1]
        self.assertEqual(first_auto["section_key"], SECTION_TITLES[2])
        self.assertIn("VONESA/MUNGESA/PV", first_auto["title"])
        self.assertEqual(first_auto["body"], f"VONESA: 0\n\nMUNGESA: 0\n\n{pv}\n\nNDRYSHON PLANI: Ruaje këtë vendim")
        context = next(section for section in sections if section["section_key"] == SECTION_TITLES[4])
        self.assertEqual(context["body"], "FESTA EXTERNE: 0\n\nTAKIMET EXTERNE: 0")
        self.assertEqual(normalize_morning_report_sections(sections), sections)
        generated = preserve_morning_plan_note(normalize_morning_report_sections([]), existing)
        self.assertIn("Ruaje këtë vendim", generated[0]["body"])
        report_day = date(2026, 11, 23)
        rendered = [
            render_html("M1", report_day, sections),
            render_plain_text("M1", report_day, sections),
            Document(BytesIO(render_section_report_docx("M1", "M1", report_day, sections))).element.body.xml,
        ]
        for output in rendered:
            self.assertLess(output.index("27.11.2026"), output.index("GA reply"))

    def test_normalization_renames_the_previous_notes_section(self) -> None:
        previous_title = (
            "(GA) NOTES TE REJA?- SELEKTO NOTES TE KALTRA DHE DISKUTO (ADM & DSG) "
            "SECILEN A KRIJOHET DETYRE?"
        )

        sections = normalize_morning_report_sections(
            [{"title": previous_title, "body": "NOTES: 2"}]
        )

        notes = next(section for section in sections if section["section_key"] == SECTION_TITLES[3])
        self.assertEqual(notes["title"], "(GA) NOTES TE REJA ( NOT DISSCUSED)?")
        self.assertEqual(notes["body"], "NOTES: 2")

    def test_normalization_drops_duplicate_near_match_email_section(self) -> None:
        variant_emails_title = (
            "(GA) EM: INFO PX (KO SPAM), EM: INFO HF (KO SPAM), EM: PRIMEX EU (GMAIL KO SPAM). "
            "VENDOS DET: STATUS (1H: EM(08:00), 08:00, DL, AM.AM&PM.PM/P/R1)"
        )
        sections = normalize_morning_report_sections(
            [
                {"title": SECTION_TITLES[1], "body": "EMAIL INFO PX (KO SPAM): first"},
                {"title": variant_emails_title, "body": "EMAIL INFO PX (KO SPAM): duplicate"},
                {"title": SECTION_TITLES[5], "body": "IN PROGRESS: 1"},
            ]
        )

        self.assertEqual([section["section_key"] for section in sections], DISPLAY_SECTION_TITLES)
        bodies = {section["section_key"]: section["body"] for section in sections}
        self.assertEqual(bodies[SECTION_TITLES[1]], "EMAIL INFO PX (KO SPAM): first")
        self.assertEqual(bodies[SECTION_TITLES[5]], "IN PROGRESS: 1")

    def test_normalization_splits_legacy_notes_emails_into_manual_section(self) -> None:
        legacy_notes = (
            "(GA) NOTES TE REJA?- SELEKTO NOTES TE KALTRA DHE DISKUTO (ADM & DSG) SECILEN A KRIJOHET "
            "DETYRE? EM: INFO PX (KO SPAM), EM:INFO HF, (KO SPAM) EM: PRIMEX EU (GMAIL-KO SPAM), "
            "VENDOS DET: STATUS (1H: EM(08:00),08:00,DL,AM,AM&PM,PM/P/R1)"
        )
        sections = normalize_morning_report_sections(
            [
                {
                    "title": legacy_notes,
                    "body": "NOTES: 1\n\nEMAIL INFO PX (KO SPAM): checked\nSTATUSI I DETYRAVE 1H: ok",
                }
            ]
        )

        bodies = {section["section_key"]: section["body"] for section in sections}
        self.assertEqual(bodies[SECTION_TITLES[1]], "EMAIL INFO PX (KO SPAM): checked")
        self.assertIn("NOTES: 1", bodies[SECTION_TITLES[3]])
        self.assertNotIn("EMAIL INFO PX", bodies[SECTION_TITLES[3]])

    def test_normalization_removes_retired_task_status_prompt(self) -> None:
        sections = normalize_morning_report_sections(
            [{
                "title": SECTION_TITLES[1],
                "body": "EMAIL INFO PX (KO SPAM): checked\nSTATUSI I DETYRAVE 1H: complete",
            }]
        )

        emails = next(section for section in sections if section["section_key"] == SECTION_TITLES[1])
        self.assertEqual(emails["body"], "EMAIL INFO PX (KO SPAM): checked")

    def test_attendance_section_formats_delays_absences_and_manual_plan_decision(self) -> None:
        user_id = uuid.uuid4()
        entries = [
            CommonEntry(
                id=uuid.uuid4(),
                category=CommonCategory.delays,
                title="Delay",
                description="Date: 2026-08-05 Start: 08:00 Until: 08:25 Traffic",
                entry_date=date(2026, 8, 5),
                created_by_user_id=user_id,
                assigned_to_user_id=user_id,
                approval_status=CommonApprovalStatus.approved,
            ),
            CommonEntry(
                id=uuid.uuid4(),
                category=CommonCategory.absences,
                title="Absent",
                description="Date: 2026-08-05 From: 08:00 - To: 12:00 Doctor",
                entry_date=date(2026, 8, 5),
                created_by_user_id=user_id,
                assigned_to_user_id=user_id,
                approval_status=CommonApprovalStatus.approved,
            ),
        ]

        body = _attendance_section(entries, {user_id: "Drita Vela"}, date(2026, 8, 5))

        self.assertIn("08:00-08:25", body)
        self.assertIn("08:00-12:00", body)
        self.assertIn("NDRYSHON PLANI: (Ploteso manualisht)", body)

    async def test_day_context_renders_annual_leave_without_tuple_unpack_error(self) -> None:
        user_id = uuid.uuid4()
        leave = CommonEntry(
            id=uuid.uuid4(),
            category=CommonCategory.annual_leave,
            title="Annual leave",
            description="Date: 2026-08-05 (Full day)",
            entry_date=date(2026, 8, 5),
            created_by_user_id=user_id,
            assigned_to_user_id=user_id,
            approval_status=CommonApprovalStatus.approved,
        )
        empty_result = SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: []),
            all=lambda: [],
        )
        db = SimpleNamespace(execute=AsyncMock(return_value=empty_result))

        with (
            patch("app.services.morning_report._all_participant_user_ids", new=AsyncMock(return_value=set())),
            patch("app.services.morning_report._bz_alignment_lines", new=AsyncMock(return_value=[])),
        ):
            body, count = await _day_context_section(
                db,
                [leave],
                {user_id: "Drita Vela"},
                [],
                {},
                date(2026, 8, 5),
                {user_id: "DEV"},
            )

        self.assertEqual(count, 1)
        self.assertIn("05.08.2026", body)
        self.assertIn("DEV", body)

    async def test_m1_linked_internal_meeting_inherits_external_color(self) -> None:
        report_day = date(2026, 8, 5)
        external_id = uuid.uuid4()
        common_fields = {
            "recurrence_days_of_week": None,
            "recurrence_days_of_month": None,
            "calendar_sync_status": "active",
        }
        external = SimpleNamespace(
            **common_fields,
            id=external_id,
            title="External physical meeting",
            starts_at=datetime(2026, 8, 5, 11, 0),
            created_at=datetime(2026, 8, 5, 11, 0),
            meeting_type="external",
            recurrence_type="none",
            calendar_categories=["Event"],
            calendar_imported=True,
            microsoft_event_id="calendar-event",
            paired_external_meeting_id=None,
            pre_external_meeting_id=None,
        )
        linked_internal = SimpleNamespace(
            **common_fields,
            id=uuid.uuid4(),
            title="Internal before external",
            starts_at=datetime(2026, 8, 5, 8, 15),
            created_at=datetime(2026, 8, 5, 8, 15),
            meeting_type="internal",
            recurrence_type="none",
            calendar_categories=[],
            calendar_imported=False,
            microsoft_event_id=None,
            paired_external_meeting_id=external_id,
            pre_external_meeting_id=None,
        )
        manual_internal = SimpleNamespace(
            **common_fields,
            id=uuid.uuid4(),
            title="Manual internal",
            starts_at=datetime(2026, 8, 5, 8, 30),
            created_at=datetime(2026, 8, 5, 8, 30),
            meeting_type="internal",
            recurrence_type="none",
            calendar_categories=[],
            calendar_imported=False,
            microsoft_event_id=None,
            paired_external_meeting_id=None,
            pre_external_meeting_id=None,
        )
        meetings = [external, linked_internal, manual_internal]
        meeting_result = SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: meetings),
            all=lambda: [],
        )
        empty_result = SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: []),
            all=lambda: [],
        )
        db = SimpleNamespace(execute=AsyncMock(side_effect=[meeting_result, empty_result]))

        with (
            patch("app.services.morning_report._all_participant_user_ids", new=AsyncMock(return_value=set())),
            patch("app.services.morning_report._bz_alignment_lines", new=AsyncMock(return_value=[])),
        ):
            body, _ = await _day_context_section(db, [], {}, [], {}, report_day)

        self.assertIn("[CAL] Internal before external [[mc:meeting-teal]]", body)
        self.assertIn("[MANUAL] Manual internal [[mc:meeting-manual]]", body)
        report_html = render_html(
            subject_for(report_day),
            report_day,
            [{"title": SECTION_TITLES[4], "body": body}],
        )
        self.assertIn('bgcolor="#CCEFF1"', report_html)
        self.assertIn('bgcolor="#FFF4CC"', report_html)

    def test_email_html_is_mobile_safe_and_contains_m1_heading(self) -> None:
        subject = subject_for(date(2026, 8, 5))
        html = render_html(
            subject,
            date(2026, 8, 5),
            [
                {"title": SECTION_TITLES[0], "body": "EMAIL INFO PX (KO SPAM): ok"},
                {"title": SECTION_TITLES[2], "body": "VONESA: 0"},
                {"title": "PYETJE SHTESË", "section_key": "manual:pyetjeshtese", "body": "Përgjigje"},
            ],
        )

        self.assertIn("M1 - PrimeFlow Hapja e dites - 05.08.2026", html)
        self.assertIn("MANUAL QUESTIONS", html)
        self.assertIn("AUTO-FILLED FROM PRIMEFLOW", html)
        self.assertIn("max-width:600px", html)
        self.assertIn("@media only screen and (max-width:600px)", html)

    def test_saved_email_section_keeps_only_the_mailbox_table(self) -> None:
        task_table = "\n\n".join([
            "+----+------+",
            "| NR | KUSH |",
            "+----+------+",
            "| 1  | EF   |",
            "+----+------+",
        ])
        mailbox = "\n\n".join([
            "EMAIL-E NGA GMAIL: 1",
            "+----+------------------+",
            "| NR | TITULLI          |",
            "+----+------------------+",
            "| 1  | Customer message |",
            "+----+------------------+",
        ])
        body = "\n\n".join([
            *(f"EM: {source}: 1:\n\n{task_table}" for source in ("INFO PX", "IT", "HF", "PX EU")),
            mailbox,
        ])
        sections = normalize_morning_report_sections([{"title": SECTION_TITLES[1], "body": body}])
        email_section = next(section for section in sections if section["section_key"] == SECTION_TITLES[1])
        self.assertEqual(email_section["body"], mailbox)
        report_day = date(2026, 8, 5)
        html = render_html("M1", report_day, [email_section])
        self.assertIn('class="report-table"', html)
        self.assertNotIn("<pre", html)
        outputs = [
            html,
            render_plain_text("M1", report_day, sections),
            Document(BytesIO(render_section_report_docx("M1", "M1", report_day, sections))).element.body.xml,
        ]
        for output in outputs:
            self.assertIn("Customer message", output)
            self.assertNotIn("EM: INFO PX:", output)

    def test_settings_routes_require_manager_or_admin(self) -> None:
        settings_routes = [route for route in router.routes if route.path == "/settings"]
        self.assertEqual(len(settings_routes), 2)
        for route in settings_routes:
            dependencies = [dependency.call for dependency in route.dependant.dependencies]
            self.assertIn(require_manager_or_admin, dependencies)

    async def test_saved_m1_content_can_be_edited(self) -> None:
        draft = make_draft()
        staff = SimpleNamespace(id=uuid.uuid4(), role=UserRole.STAFF, full_name="Staff User")

        result = await update_draft(
            draft.id,
            DraftUpdate(
                sections=[SectionPayload(title=SECTION_TITLES[2], body="NDRYSHON PLANI: Changes after 10:00")]
            ),
            FakeDraftDb(draft),
            staff,
        )

        attendance = next(section for section in result["sections"] if section["section_key"] == SECTION_TITLES[2])
        self.assertIn("NDRYSHON PLANI: Changes after 10:00", attendance["body"])

    async def test_existing_m1_personal_section_remains_ga_only(self) -> None:
        assignee_id = uuid.uuid4()
        ka_task = Task(
            id=uuid.uuid4(),
            title="AT/KA: DET PERSONALISHT",
            status="TODO",
            phase="MEETINGS",
            is_personal=True,
            is_active=True,
            assigned_to=assignee_id,
            start_date=datetime(2026, 8, 5, 8, 0, tzinfo=ZoneInfo("Europe/Tirane")),
            due_date=datetime(2026, 8, 5, 10, 0, tzinfo=ZoneInfo("Europe/Tirane")),
        )
        ga_task = Task(
            id=uuid.uuid4(),
            title="DM/GA: BZ GA - P/P PARA PF",
            status="IN_PROGRESS",
            phase="MEETINGS",
            is_personal=True,
            is_active=True,
            assigned_to=assignee_id,
            start_date=datetime(2026, 8, 5, 8, 0, tzinfo=ZoneInfo("Europe/Tirane")),
            due_date=datetime(2026, 8, 5, 10, 0, tzinfo=ZoneInfo("Europe/Tirane")),
        )
        gent_task = Task(
            id=uuid.uuid4(),
            title="AT/GENTI: DET PERSONALISHT",
            status="TODO",
            phase="MEETINGS",
            is_personal=True,
            is_active=True,
            assigned_to=assignee_id,
            start_date=datetime(2026, 8, 5, 8, 0, tzinfo=ZoneInfo("Europe/Tirane")),
            due_date=datetime(2026, 8, 5, 10, 0, tzinfo=ZoneInfo("Europe/Tirane")),
        )

        with patch("app.services.after_break_report._all_participant_user_ids", new=AsyncMock(return_value=set())):
            lines = await _personal_section(
                SimpleNamespace(),
                [ka_task, ga_task, gent_task],
                {assignee_id: "Arta Test"},
                {ka_task.id: {assignee_id}, ga_task.id: {assignee_id}, gent_task.id: {assignee_id}},
                date(2026, 8, 5),
                title_pattern=PERSONAL_GA,
            )
        body = "\n".join(lines)

        self.assertIn("DM/GA: BZ GA - P/P PARA PF", body)
        self.assertNotIn("AT/KA: DET PERSONALISHT", body)
        self.assertNotIn("AT/GENTI: DET PERSONALISHT", body)

    async def test_scheduler_regenerates_sections_before_sending(self) -> None:
        timezone = ZoneInfo("Europe/Tirane")
        draft = make_draft()
        overrides = {f"GA TASKS:{uuid.uuid4()}": {"continuation": "JO"}}
        draft.generated_snapshot = {TASK_FEEDBACK_OVERRIDES: overrides}
        settings = SimpleNamespace(
            is_active=True,
            timezone="Europe/Tirane",
            weekdays=[2],
            send_time=time(8, 0),
            recipients={"to": ["report@example.com"], "cc": [], "bcc": []},
            updated_at=datetime(2026, 8, 5, 7, 0, tzinfo=timezone),
            last_run_date=None,
        )
        db = SchedulerDb(settings, draft)
        regenerated = [
            {"title": SECTION_TITLES[2], "body": "Fresh VONESA: 0"},
            {"section_key": PHYSICAL_GA_TITLE, "title": PHYSICAL_GA_TITLE, "body": "FG:GA DEVICES"},
        ]
        build = AsyncMock(return_value=(regenerated, {"counts": {}, TASK_FEEDBACK_OVERRIDES: overrides}))
        send = AsyncMock(return_value={"id": "gmail-id", "threadId": "thread-id"})
        render_plain = Mock(return_value="plain")
        render_html_mock = Mock(return_value="html")

        with (
            patch.object(morning_report_scheduler, "SessionLocal", return_value=db),
            patch.object(morning_report_scheduler, "build_morning_report_sections", build),
            patch.object(morning_report_scheduler, "send_morning_report", send),
            patch.object(morning_report_scheduler, "render_plain_text", render_plain),
            patch.object(morning_report_scheduler, "render_html", render_html_mock),
        ):
            sent = await morning_report_scheduler.run_morning_report_scheduler_once(
                datetime(2026, 8, 5, 8, 5, tzinfo=timezone)
            )

        self.assertTrue(sent)
        build.assert_awaited_once_with(db, draft.report_date, task_feedback_overrides=overrides)
        self.assertEqual(draft.sections, regenerated)
        self.assertEqual(draft.generated_snapshot[TASK_FEEDBACK_OVERRIDES], overrides)
        self.assertEqual(render_plain.call_args.args[2], regenerated)
        self.assertEqual(draft.recipients["to"], ["report@example.com"])
        self.assertEqual(draft.gmail_message_id, "gmail-id")


if __name__ == "__main__":
    unittest.main()


from tests.report_attendance_fixtures import present_report_population
