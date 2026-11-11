from __future__ import annotations

import pytest

import unittest
import uuid
from datetime import date, datetime, time, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

from app.api.deps import require_admin
from app.api.routers.morning_report import DraftUpdate, SectionPayload, router, update_draft
from app.models.common_entry import CommonEntry
from app.models.enums import CommonApprovalStatus, CommonCategory, UserRole
from app.models.morning_report_draft import MorningReportDraft
from app.models.task import Task
from app.services import morning_report_scheduler
from app.services.morning_report_scheduler import _due_m1_send_slot
from app.services.after_break_report import _personal_section
from app.services.meetings_report import PERSONAL_GA
from app.services.meeting_point_manual_sync import section_group_label, with_section_keys
from app.services.morning_report import (
    DISPLAY_SECTION_TITLES,
    GA_HV_DV_TASKS_TITLE,
    GA_TASKS_TITLE,
    SECTION_TITLES,
    _attendance_section,
    _day_context_section,
    _email_task_source_label,
    _ga_hv_dv_task_rows,
    _ga_hv_dv_tables_body,
    normalize_morning_report_sections,
    render_html,
    subject_for,
)


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

    def test_ga_hv_dv_is_first_auto_filled_m1_section(self) -> None:
        self.assertEqual(DISPLAY_SECTION_TITLES[0], SECTION_TITLES[0])
        self.assertEqual(DISPLAY_SECTION_TITLES[1], GA_HV_DV_TASKS_TITLE)

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

        self.assertEqual(report_html.count("am-pm-divider"), 7)
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
        self.results = iter((ScalarResult(settings), ScalarResult(draft)))

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
    def test_personal_and_wfc_sections_are_labeled_as_auto_filled(self) -> None:
        self.assertEqual(SECTION_TITLES[7], "DET PERSONALISHT ME KA/GENTIN?")
        self.assertEqual(SECTION_TITLES[8], "WFC ME KA/GENTIN?")
        self.assertEqual(section_group_label("morning", SECTION_TITLES[7]), "AUTO-FILLED FROM PRIMEFLOW")
        self.assertEqual(section_group_label("morning", SECTION_TITLES[8]), "AUTO-FILLED FROM PRIMEFLOW")

    def test_edited_auto_title_keeps_m1_identity_position_and_group(self) -> None:
        sections = normalize_morning_report_sections(
            with_section_keys("morning", [{"title": title, "body": str(i)} for i, title in enumerate(SECTION_TITLES)])
        )
        sections[1]["title"] = "CUSTOM EMAIL TASKS TITLE"

        normalized = normalize_morning_report_sections(sections)

        self.assertEqual(normalized[1]["title"], "CUSTOM EMAIL TASKS TITLE")
        self.assertEqual(normalized[1]["section_key"], SECTION_TITLES[1])
        self.assertEqual(
            section_group_label("morning", normalized[1]["title"], normalized[1]["section_key"]),
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

        self.assertEqual([section["title"] for section in sections], SECTION_TITLES)
        self.assertEqual(sections[0]["body"], "GA replied at 07:55")
        self.assertIn("Email-source tasks load automatically", sections[1]["body"])
        self.assertIn("NDRYSHON PLANI", sections[2]["body"])

    def test_standard_email_task_source_tags_are_detected(self) -> None:
        self.assertEqual(_email_task_source_label(SimpleNamespace(title="EM: INFO PX: Update catalogue")), "EM: INFO PX")
        self.assertEqual(_email_task_source_label(SimpleNamespace(title="EM: IT: Reset account")), "EM: IT")
        self.assertEqual(_email_task_source_label(SimpleNamespace(title="EM: HF: Invoice issue")), "EM: HF")
        self.assertEqual(_email_task_source_label(SimpleNamespace(title="EM: PX EU: Customer request")), "EM: PX EU")
        self.assertIsNone(_email_task_source_label(SimpleNamespace(title="EM: PX: General mail")))

    def test_normalization_renames_the_previous_notes_section(self) -> None:
        previous_title = (
            "(GA) NOTES TE REJA?- SELEKTO NOTES TE KALTRA DHE DISKUTO (ADM & DSG) "
            "SECILEN A KRIJOHET DETYRE?"
        )

        sections = normalize_morning_report_sections(
            [{"title": previous_title, "body": "NOTES: 2"}]
        )

        self.assertEqual(sections[3], {"title": "(GA) NOTES TE REJA?", "body": "NOTES: 2"})

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

        self.assertEqual(len(sections), 6)
        self.assertEqual([section["title"] for section in sections], SECTION_TITLES)
        self.assertEqual(sections[1]["body"], "EMAIL INFO PX (KO SPAM): first")
        self.assertEqual(sections[5]["body"], "IN PROGRESS: 1")

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

        self.assertEqual(
            sections[1]["body"],
            "EMAIL INFO PX (KO SPAM): checked",
        )
        self.assertIn("NOTES: 1", sections[3]["body"])
        self.assertNotIn("EMAIL INFO PX", sections[3]["body"])

    def test_normalization_removes_retired_task_status_prompt(self) -> None:
        sections = normalize_morning_report_sections(
            [{
                "title": SECTION_TITLES[1],
                "body": "EMAIL INFO PX (KO SPAM): checked\nSTATUSI I DETYRAVE 1H: complete",
            }]
        )

        self.assertEqual(sections[1]["body"], "EMAIL INFO PX (KO SPAM): checked")

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
            ],
        )

        self.assertIn("Hapja e dites M1", html)
        self.assertIn("MANUAL QUESTIONS", html)
        self.assertIn("AUTO-FILLED FROM PRIMEFLOW", html)
        self.assertIn("max-width:600px", html)
        self.assertIn("@media only screen and (max-width:600px)", html)

    def test_email_html_renders_spaced_ascii_email_tables(self) -> None:
        # Editable saved drafts can contain blank spacer lines between every
        # ASCII table row.  The M1 email must still render it as an HTML table.
        spaced_table = "\n\n".join(
            [
                "EM: INFO PX: 1:",
                "+----+----------------------+-------+-------------+------------------------------------------------------------------+",
                "| NR | KUSH                 | DEP   | AM/PM       | TITULLI                                                          |",
                "+----+----------------------+-------+-------------+------------------------------------------------------------------+",
                "| 1  | EF                   | DEV   | -           | EM: INFO PX: DET TEST [[st:WAITING_CONFIRMATION]]               |",
                "+----+----------------------+-------+-------------+------------------------------------------------------------------+",
            ]
        )

        html = render_html(
            subject_for(date(2026, 8, 5)),
            date(2026, 8, 5),
            [{"title": SECTION_TITLES[1], "body": spaced_table}],
        )

        self.assertIn('class="report-table"', html)
        self.assertIn("EM: INFO PX: DET TEST", html)
        self.assertNotIn("<pre", html)

    def test_settings_routes_require_admin(self) -> None:
        settings_routes = [route for route in router.routes if route.path == "/settings"]
        self.assertEqual(len(settings_routes), 2)
        for route in settings_routes:
            dependencies = [dependency.call for dependency in route.dependant.dependencies]
            self.assertIn(require_admin, dependencies)

    async def test_saved_m1_content_can_be_edited(self) -> None:
        draft = make_draft()
        staff = SimpleNamespace(id=uuid.uuid4(), role=UserRole.STAFF, full_name="Staff User")

        result = await update_draft(
            draft.id,
            DraftUpdate(
                sections=[SectionPayload(title=SECTION_TITLES[2], body="Plan changes after 10:00")]
            ),
            FakeDraftDb(draft),
            staff,
        )

        self.assertEqual(result["sections"][2]["body"], "Plan changes after 10:00")

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
        regenerated = [{"title": SECTION_TITLES[2], "body": "Fresh VONESA: 0"}]
        build = AsyncMock(return_value=(regenerated, {"counts": {}}))
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
        build.assert_awaited_once()
        self.assertEqual(draft.sections, regenerated)
        self.assertEqual(render_plain.call_args.args[2], regenerated)
        self.assertEqual(draft.recipients["to"], ["report@example.com"])
        self.assertEqual(draft.gmail_message_id, "gmail-id")


if __name__ == "__main__":
    unittest.main()


from tests.report_attendance_fixtures import present_report_population
