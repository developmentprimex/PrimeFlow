from __future__ import annotations

import pytest

import unittest
import uuid
from io import BytesIO
from zipfile import ZipFile
from datetime import date, datetime, time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.api.deps import require_admin
from app.api.routers.meetings_report import DraftUpdate, RecipientsPayload, SectionPayload, router, update_draft
from app.models.enums import UserRole
from app.models.meetings_report_draft import MeetingsReportDraft
from app.services import meetings_report_scheduler
from app.services.meeting_point_manual_sync import (
    is_known_report_title, is_manual_section_title, section_group_label, with_section_keys,
)
from app.services.meetings_report import (
    DISPLAY_SECTION_TITLES,
    SECTION_TITLES,
    _completed_tasks_for_report_day,
    _common_meeting_lines,
    _common_task_metadata_by_title,
    _is_new_task_for_m3_day,
    _is_postponed_for_m3_day,
    _is_report_wfc_task,
    _is_system_task,
    _is_wfc_task,
    _is_without_progress_for_m3_day,
    _ka_genti_confirmer,
    _ka_genti_owner,
    _meeting_lines,
    _meeting_status_checkbox_table,
    _m3_department_label,
    _m3_added_week_label,
    _m3_status_table,
    _m3_task_type_label,
    _postponed_tasks_for_m3_day,
    _leave_lines,
    _render_ascii_table_html,
    _render_table_cell_html,
    _task_owners,
    _task_covers_report_day,
    _daily_baseline_task_ids,
    _tomorrow_common_section,
    _tomorrow_meeting_table,
    _tomorrow_task_table,
    normalize_meetings_report_sections,
    render_html,
    render_section_report_docx,
    render_section_report_png,
    section_report_attachments,
    send_meetings_report,
)


class M3TaskDateRangeTests(unittest.TestCase):
    def test_start_due_range_includes_each_working_day(self) -> None:
        task = SimpleNamespace(
            phase="MEETINGS",
            start_date=datetime(2026, 9, 16, 8, 0),
            due_date=datetime(2026, 9, 25, 17, 0),
            planned_for=None,
            created_at=datetime(2026, 9, 14, 9, 0),
        )
        self.assertTrue(_task_covers_report_day(task, date(2026, 9, 17)))
        self.assertTrue(_task_covers_report_day(task, date(2026, 9, 25)))
        self.assertFalse(_task_covers_report_day(task, date(2026, 9, 19)))
        self.assertFalse(_task_covers_report_day(task, date(2026, 9, 28)))

    def test_check_and_control_tasks_remain_single_date(self) -> None:
        task = SimpleNamespace(
            phase="CHECK",
            start_date=datetime(2026, 9, 16, 8, 0),
            due_date=datetime(2026, 9, 25, 17, 0),
            planned_for=None,
            created_at=datetime(2026, 9, 14, 9, 0),
        )
        self.assertFalse(_task_covers_report_day(task, date(2026, 9, 17)))
        self.assertTrue(_task_covers_report_day(task, date(2026, 9, 25)))


class ReportOwnerAndWfcTests(unittest.TestCase):
    def test_personal_and_wfc_sections_are_known_auto_sections(self) -> None:
        self.assertEqual(SECTION_TITLES[13], "N- DET PERSONALISHT ME KA/GENTIN?")
        self.assertEqual(SECTION_TITLES[14], "N- WFC ME KA/GENTIN?")
        self.assertEqual(SECTION_TITLES[15], "SHIKO DET ME SIMBOLE NE 1H SHTYPI NESER")
        self.assertTrue(is_manual_section_title("meetings", SECTION_TITLES[15]))
        self.assertFalse(is_manual_section_title("meetings", SECTION_TITLES[13]))
        self.assertFalse(is_manual_section_title("meetings", SECTION_TITLES[14]))
        self.assertEqual(section_group_label("meetings", SECTION_TITLES[14]), "AUTO-FILLED FROM PRIMEFLOW")

    def test_ka_and_genti_are_assigned_to_separate_owner_tables(self) -> None:
        self.assertEqual(_ka_genti_owner(SimpleNamespace(title="AT/KA: task")), "KA")
        self.assertEqual(_ka_genti_owner(SimpleNamespace(title="KA: task")), "KA")
        self.assertEqual(_ka_genti_owner(SimpleNamespace(title="ER/GENT: task")), "GENTI")
        self.assertEqual(_ka_genti_owner(SimpleNamespace(title="ER/GENTI: task")), "GENTI")
        self.assertEqual(_ka_genti_owner(SimpleNamespace(title="ER/GT: task")), "GENTI")
        self.assertEqual(_ka_genti_owner(SimpleNamespace(title="GT: task")), "GENTI")
        self.assertIsNone(_ka_genti_owner(SimpleNamespace(title="DM/GA: task")))
        self.assertIsNone(_ka_genti_owner(SimpleNamespace(title="ER/PX: unrelated task")))
        self.assertEqual(_ka_genti_owner(SimpleNamespace(title="EF/GA/KA: task")), "KA")
        self.assertEqual(_ka_genti_owner(SimpleNamespace(title="EF/GA/GT: task")), "GENTI")
        self.assertEqual(_ka_genti_owner(SimpleNamespace(title="EF/KA/GT/GA: task")), "GENTI")

    def test_wfc_is_waiting_confirmation_only(self) -> None:
        self.assertTrue(_is_wfc_task(SimpleNamespace(status="WAITING_CONFIRMATION")))
        self.assertTrue(_is_wfc_task(SimpleNamespace(status="WAITING")))
        self.assertFalse(_is_wfc_task(SimpleNamespace(status="WAITING_CLIENT")))
        self.assertFalse(_is_wfc_task(SimpleNamespace(status="TODO")))

    def test_report_wfc_requires_open_waiting_confirmation_status(self) -> None:
        base = {"status": "WAITING_CONFIRMATION", "completed_at": None}
        self.assertTrue(_is_report_wfc_task(SimpleNamespace(**base, title="AT/KA: confirm")))
        self.assertTrue(_is_report_wfc_task(SimpleNamespace(**base, title="ER/GENTI: confirm")))
        self.assertTrue(_is_report_wfc_task(SimpleNamespace(**base, title="DM/GA: confirm")))
        self.assertTrue(_is_report_wfc_task(SimpleNamespace(**base, title="ER/PX: confirm")))
        self.assertFalse(_is_report_wfc_task(SimpleNamespace(title="AT/KA: client", status="WAITING_CLIENT", completed_at=None)))

    def test_wfc_table_is_selected_from_confirmation_assignee(self) -> None:
        gent_id = uuid.uuid4()
        ka_id = uuid.uuid4()
        gane_id = uuid.uuid4()
        names = {
            gent_id: "Gent Arifaj",
            ka_id: "Klea Ameti",
            gane_id: "Gane Arifaj",
        }

        self.assertEqual(
            _ka_genti_confirmer(SimpleNamespace(confirmation_assignee_id=gent_id), names),
            "GENTI",
        )
        self.assertEqual(
            _ka_genti_confirmer(SimpleNamespace(confirmation_assignee_id=ka_id), names),
            "KA",
        )
        self.assertIsNone(
            _ka_genti_confirmer(SimpleNamespace(confirmation_assignee_id=gane_id), names)
        )


class FakeDraftDb:
    def __init__(self, draft: MeetingsReportDraft) -> None:
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


def make_draft() -> MeetingsReportDraft:
    return MeetingsReportDraft(
        id=uuid.uuid4(),
        report_date=date(2026, 8, 5),
        tomorrow_date=date(2026, 8, 6),
        subject="Saved subject",
        recipients={"to": ["old@example.com"], "cc": [], "bcc": []},
        sections=[{"title": "Section", "body": "Saved user edit"}],
        generated_snapshot={},
        status="DRAFT",
    )


class MeetingsReportWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def test_edited_auto_title_keeps_m3_identity_position_and_group(self) -> None:
        sections = normalize_meetings_report_sections(
            with_section_keys("meetings", [{"title": title, "body": str(i)} for i, title in enumerate(SECTION_TITLES)])
        )
        target_index = next(i for i, section in enumerate(sections) if section["section_key"] == SECTION_TITLES[1])
        sections[target_index]["title"] = "CUSTOM STD TITLE"

        normalized = normalize_meetings_report_sections(sections)
        affected = normalized[target_index]

        self.assertEqual(affected["title"], "CUSTOM STD TITLE")
        self.assertEqual(affected["section_key"], SECTION_TITLES[1])
        self.assertEqual(
            section_group_label("meetings", affected["title"], affected["section_key"]),
            "AUTO-FILLED FROM PRIMEFLOW",
        )

    def test_settings_routes_require_admin(self) -> None:
        settings_routes = [route for route in router.routes if route.path == "/settings"]
        self.assertEqual(len(settings_routes), 2)
        for route in settings_routes:
            dependencies = [dependency.call for dependency in route.dependant.dependencies]
            self.assertIn(require_admin, dependencies)

    async def test_staff_can_edit_report_content_but_not_recipients(self) -> None:
        draft = make_draft()
        db = FakeDraftDb(draft)
        staff = SimpleNamespace(id=uuid.uuid4(), role=UserRole.STAFF, full_name="Staff User")

        result = await update_draft(
            draft.id,
            DraftUpdate(
                subject="Edited subject",
                sections=[
                    SectionPayload(
                        title="Section",
                        body="+---+---+---+\n| NR | WHO | TITLE |\n+---+---+---+\n| 1 | AB | Added task |\n+---+---+---+",
                    )
                ],
            ),
            db,
            staff,
        )

        self.assertEqual(result["subject"], "Edited subject")
        self.assertEqual(result["sections"][0]["title"], "Section")
        self.assertIn("Added task", result["sections"][0]["body"])

        with self.assertRaises(HTTPException) as raised:
            await update_draft(
                draft.id,
                DraftUpdate(recipients=RecipientsPayload(to=["changed@example.com"])),
                db,
                staff,
            )
        self.assertEqual(raised.exception.status_code, 403)

    async def test_scheduler_regenerates_sections_before_sending(self) -> None:
        timezone = ZoneInfo("Europe/Tirane")
        draft = make_draft()
        settings = SimpleNamespace(
            is_active=True,
            timezone="Europe/Tirane",
            weekdays=[2],
            send_time=time(16, 30),
            recipients={"to": ["report@example.com"], "cc": [], "bcc": []},
            updated_at=datetime(2026, 8, 5, 12, 0, tzinfo=timezone),
            last_run_date=None,
        )
        db = SchedulerDb(settings, draft)
        regenerated = [{"title": "Section", "body": "Fresh auto content"}]
        build = AsyncMock(return_value=(date(2026, 8, 6), regenerated, {"counts": {}}))
        send = AsyncMock(return_value={"id": "gmail-id", "threadId": "thread-id"})
        render_plain = Mock(return_value="plain")
        render_html = Mock(return_value="html")

        with (
            patch.object(meetings_report_scheduler, "SessionLocal", return_value=db),
            patch.object(meetings_report_scheduler, "build_meetings_report_sections", build),
            patch.object(meetings_report_scheduler, "send_meetings_report", send),
            patch.object(meetings_report_scheduler, "render_plain_text", render_plain),
            patch.object(meetings_report_scheduler, "render_html", render_html),
            patch(
                "app.services.meeting_point_manual_sync.merge_common_view_manual_sections",
                AsyncMock(side_effect=lambda _db, sections, *_args: sections),
            ),
        ):
            sent = await meetings_report_scheduler.run_meetings_report_scheduler_once(
                datetime(2026, 8, 5, 17, 0, tzinfo=timezone)
            )

        self.assertTrue(sent)
        build.assert_awaited_once()
        self.assertEqual(draft.sections, regenerated)
        self.assertEqual(render_plain.call_args.args[3], regenerated)
        self.assertEqual(draft.recipients["to"], ["report@example.com"])
        self.assertEqual(draft.gmail_message_id, "gmail-id")

    async def test_scheduler_sends_fresh_m3_report_only_at_1630(self) -> None:
        timezone = ZoneInfo("Europe/Tirane")
        draft = make_draft()
        settings = SimpleNamespace(
            is_active=True,
            timezone="Europe/Tirane",
            weekdays=[2],
            send_time=time(16, 30),
            recipients={"to": ["report@example.com"], "cc": [], "bcc": []},
            updated_at=datetime(2026, 8, 5, 12, 0, tzinfo=timezone),
            last_run_date=None,
        )
        build = AsyncMock(return_value=(date(2026, 8, 6), [{"title": "Section", "body": "Fresh"}], {}))
        send = AsyncMock(return_value={"id": "gmail-id", "threadId": "thread-id"})
        session_local = Mock(
            side_effect=[SchedulerDb(settings, draft), SchedulerDb(settings, draft), SchedulerDb(settings, draft)]
        )

        with (
            patch.object(meetings_report_scheduler, "SessionLocal", session_local),
            patch.object(meetings_report_scheduler, "build_meetings_report_sections", build),
            patch.object(meetings_report_scheduler, "send_meetings_report", send),
            patch.object(meetings_report_scheduler, "render_plain_text", Mock(return_value="plain")),
            patch.object(meetings_report_scheduler, "render_html", Mock(return_value="html")),
            patch(
                "app.services.meeting_point_manual_sync.merge_common_view_manual_sections",
                AsyncMock(side_effect=lambda _db, sections, *_args: sections),
            ),
        ):
            first_sent = await meetings_report_scheduler.run_meetings_report_scheduler_once(
                datetime(2026, 8, 5, 15, 50, tzinfo=timezone)
            )
            second_sent = await meetings_report_scheduler.run_meetings_report_scheduler_once(
                datetime(2026, 8, 5, 16, 30, tzinfo=timezone)
            )
            no_third_send = await meetings_report_scheduler.run_meetings_report_scheduler_once(
                datetime(2026, 8, 5, 16, 31, tzinfo=timezone)
            )

        self.assertFalse(first_sent)
        self.assertTrue(second_sent)
        self.assertFalse(no_third_send)
        self.assertEqual(draft.auto_sent_slots, ["16:30"])
        self.assertEqual(build.await_count, 1)
        self.assertEqual(send.await_count, 1)


class MeetingsReportAttachmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_m3_ga_time_table_attachment_is_sent_only_to_ga(self) -> None:
        gmail = SimpleNamespace(send_verified=AsyncMock(return_value={"id": "gmail-id"}))
        ga_png = AsyncMock(return_value=b"ga-time-table-png")
        base_attachments = [
            ("PrimeFlow-M3-2026-08-10.docx", b"docx", "application/docx"),
            ("PrimeFlow-M3-2026-08-10.png", b"m3-png", "image/png"),
        ]
        with (
            patch("app.services.meetings_report.GmailService", return_value=gmail),
            patch(
                "app.services.meetings_report.section_report_attachments",
                side_effect=[list(base_attachments), list(base_attachments)],
            ),
            patch("app.services.one_h_ga_attachments.render_ga_time_table_png", ga_png),
        ):
            await send_meetings_report(
                "PrimeFlow M3",
                {"to": ["report@example.com"], "cc": ["ga@primexeu.com"], "bcc": []},
                "plain",
                "html",
                db=SimpleNamespace(),
                report_day=date(2026, 8, 10),
                tomorrow=date(2026, 8, 11),
                sections=[{"title": "Section", "body": "Body"}],
            )

        self.assertEqual(gmail.send_verified.await_count, 2)
        regular_call, ga_call = gmail.send_verified.await_args_list
        self.assertEqual(regular_call.args[1], {
            "to": ["report@example.com"], "cc": [], "bcc": [],
        })
        self.assertEqual(regular_call.kwargs["attachments"], base_attachments)
        self.assertEqual(ga_call.args[1], {
            "to": ["ga@primexeu.com"], "cc": [], "bcc": [],
        })
        self.assertEqual(ga_call.kwargs["attachments"][-1], (
            "GA-Time-Table-2026-08-10.png",
            b"ga-time-table-png",
            "image/png",
        ))


class MeetingsReportAliasDedupTests(unittest.TestCase):
    def test_task_symbol_is_emphasized_in_report_table_titles(self) -> None:
        rendered = _render_table_cell_html("TITULLI", "! ER/GA/KA: ODOO EXPERIENCE")

        self.assertIn('data-task-symbol="true"', rendered)
        self.assertIn("font-weight:900", rendered)
        self.assertIn(">!</strong>", rendered)

    def test_section_exports_keep_email_groups_tables_and_status_colors(self) -> None:
        sections = [
            {"title": "A JEMI BRENDA MESATARES ME PROJEKTE?", "body": "(Ploteso manualisht)"},
            {
                "title": "GA MBYLLJA E DET",
                "body": (
                    "TODO:\n+----+------+--------------------------------+\n"
                    "| NR | KUSH | TITULLI                        |\n"
                    "+----+------+--------------------------------+\n"
                    "| 1  | GA   | DetyrÃ« e re                    |\n"
                    "+----+------+--------------------------------+\n"
                    "DONE:\n+----+------+--------------------------------+\n"
                    "| NR | KUSH | TITULLI                        |\n"
                    "+----+------+--------------------------------+\n"
                    "| 1  | GA   | DetyrÃ« e kryer                 |\n"
                    "+----+------+--------------------------------+\n"
                    "DET ME DEADLINE:\n+----+------+--------------------------------+\n"
                    "| NR | KUSH | TITULLI                        |\n"
                    "+----+------+--------------------------------+\n"
                    "| 1  | GA   | Afat kritik                    |\n"
                    "+----+------+--------------------------------+\n"
                    "DET TE REJA LAST WEEK DHE THIS WEEK:\n"
                    "+----+------+---------+--------------------------------+\n"
                    "| NR | KUSH | KRIJUAR | TITULLI                        |\n"
                    "+----+------+---------+--------------------------------+\n"
                    "| 1  | GA   | This W  | Detyre e kesaj jave            |\n"
                    "+----+------+---------+--------------------------------+\n"
                    "| 2  | GA   | Last W  | Detyre e javes kaluar          |\n"
                    "+----+------+---------+--------------------------------+\n"
                    "SHTYER START DHE DUE DATE:\n"
                    "+----+-------------------------------+-------------------------------+------------------+\n"
                    "| NR | NGA                           | NE                            | TITULLI          |\n"
                    "+----+-------------------------------+-------------------------------+------------------+\n"
                    "| 1  | START: 10.08.2026 / DUE: 10.08.2026 | START: 11.08.2026 / DUE: 12.08.2026 | Detyre e shtyre |\n"
                    "+----+-------------------------------+-------------------------------+------------------+"
                ),
            },
        ]
        html_output = render_html(
            "PrimeFlow M3", date(2026, 8, 10), date(2026, 8, 11), sections
        )
        docx_bytes = render_section_report_docx("PrimeFlow M3", "M3", date(2026, 8, 10), sections)
        png_bytes = render_section_report_png("PrimeFlow M3", "M3", date(2026, 8, 10), sections)

        from docx import Document
        from PIL import Image

        document = Document(BytesIO(docx_bytes))
        document_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        table_text = "\n".join(cell.text for table in document.tables for row in table.rows for cell in row.cells)
        self.assertIn("PrimeFlow M3", document_text)
        self.assertIn("MANUAL QUESTIONS", table_text)
        self.assertIn("AUTO-FILLED FROM PRIMEFLOW", table_text)
        self.assertIn("TODO:", table_text)
        self.assertIn("DONE:", table_text)
        self.assertIn('class="deadline"', html_output)
        self.assertIn('bgcolor="#bae6fd"', html_output)
        self.assertIn('bgcolor="#fde68a"', html_output)
        self.assertIn("border-bottom:3px solid #334155", html_output)
        with ZipFile(BytesIO(docx_bytes)) as archive:
            document_xml = archive.read("word/document.xml").decode("utf-8")
        self.assertIn("fbcfe8", document_xml.lower())
        self.assertIn("d4ffe1", document_xml.lower())
        self.assertIn("dc2626", document_xml.lower())
        self.assertIn("bae6fd", document_xml.lower())
        self.assertIn("fde68a", document_xml.lower())
        self.assertIn("334155", document_xml.lower())
        self.assertIn('w:sz="12"', document_xml.lower())
        self.assertIn("w:pbdr", document_xml.lower())
        self.assertIn('w:w="432"', document_xml)  # Compact NR column, matching the email grid.
        image = Image.open(BytesIO(png_bytes))
        self.assertGreater(image.width, 1000)
        self.assertGreater(image.height, 400)
        colors = set(image.convert("RGB").getdata())
        self.assertIn((220, 38, 38), colors)
        self.assertIn((186, 230, 253), colors)
        self.assertIn((253, 230, 138), colors)
        self.assertIn((51, 65, 85), colors)

    def test_section_report_attachments_include_word_and_png(self) -> None:
        attachments = section_report_attachments(
            "PrimeFlow M3",
            "M3",
            date(2026, 8, 10),
            [{
                "title": "Section",
                "body": "TODO:\n+----+-----+\n| NR | TITLE |\n+----+-----+\n| 1  | Task  |\n+----+-----+",
            }],
            tomorrow=date(2026, 8, 11),
        )

        self.assertEqual([attachment[0] for attachment in attachments], [
            "PrimeFlow-M3-2026-08-10.docx",
            "PrimeFlow-M3-2026-08-10.png",
        ])
        self.assertTrue(attachments[0][1].startswith(b"PK"))
        self.assertTrue(attachments[1][1].startswith(b"\x89PNG"))

    def test_normalize_collapses_common_view_aliases_into_auto_sections(self) -> None:
        auto_tickets = "STD TICKETS: 2"
        normalized = normalize_meetings_report_sections(
            [
                {"title": "A JEMI BRENDA MESATARES ME PROJEKTE/", "body": "(Ploteso manualisht)"},
                {"title": "(GA) M3 DET GA MBYLLJA ME HV/OH?", "body": "(Ploteso manualisht)"},
                {"title": "(GA) TIKETAT E STD DHE TONAT? RAPORTOHEN NE M3", "body": "(Ploteso manualisht)"},
                {"title": SECTION_TITLES[1], "body": auto_tickets},
                {"title": "Brand new Common View pike", "body": "(Ploteso manualisht)"},
            ]
        )
        titles = [section["title"] for section in normalized]
        self.assertEqual(titles[0], SECTION_TITLES[0])  # manual first
        auto_titles = [title for title in titles if title == SECTION_TITLES[1]]
        self.assertEqual(auto_titles[0], SECTION_TITLES[1])  # tickets first among auto-filled
        self.assertEqual(titles.count(SECTION_TITLES[1]), 1)
        self.assertNotIn("GA MBYLLJA E DET", titles)
        self.assertNotIn("HV MBYLLJA E DET", titles)
        self.assertNotIn("(GA) M3 DET GA MBYLLJA ME HV/OH?", titles)
        self.assertNotIn("(GA) TIKETAT E STD DHE TONAT? RAPORTOHEN NE M3", titles)
        self.assertIn("Brand new Common View pike", titles)
        by_title = {section["title"]: section["body"] for section in normalized}
        self.assertEqual(by_title[SECTION_TITLES[1]], auto_tickets)

    def test_ticket_wording_variant_alone_maps_to_auto_title(self) -> None:
        normalized = normalize_meetings_report_sections(
            [
                {"title": "A JEMI BRENDA MESATARES ME PROJEKTE/", "body": "(Ploteso manualisht)"},
                {"title": "(GA) TIKETAT E STD DHE TONAT? RAPORTOHEN NE M3", "body": "(Ploteso manualisht)"},
            ]
        )
        titles = [section["title"] for section in normalized]
        self.assertNotIn("(GA) TIKETAT E STD DHE TONAT? RAPORTOHEN NE M3", titles)
        self.assertIn(SECTION_TITLES[1], titles)

    def test_ga_and_hv_closing_sections_are_removed_from_m3(self) -> None:
        normalized = normalize_meetings_report_sections(
            [
                {"title": SECTION_TITLES[0], "body": "(Ploteso manualisht)"},
                {"title": "GA MBYLLJA E DET", "body": "GA tasks"},
                {"title": "HV MBYLLJA E DET", "body": "HV tasks"},
            ]
        )

        self.assertEqual(
            [section["title"] for section in normalized],
            [SECTION_TITLES[0], SECTION_TITLES[15]],
        )

    def test_common_view_aliases_are_known_auto_not_manual(self) -> None:
        self.assertTrue(is_known_report_title("meetings", "(GA) M3 DET GA MBYLLJA ME HV/OH?"))
        self.assertTrue(is_known_report_title("meetings", "(GA) TIKETAT E STD DHE TONAT? RAPORTOHEN NE M3"))
        self.assertFalse(is_manual_section_title("meetings", "(GA) M3 DET GA MBYLLJA ME HV/OH?"))
        self.assertFalse(is_manual_section_title("meetings", "(GA) TIKETAT E STD DHE TONAT? RAPORTOHEN NE M3"))
        self.assertTrue(is_manual_section_title("meetings", "Brand new Common View pike"))


class MeetingsReportTaskTypeColumnTests(unittest.TestCase):
    def test_det_te_shtyera_is_known_auto_section_after_pink(self) -> None:
        postponed_title = "DET TE SHTYERA"

        self.assertIn(postponed_title, SECTION_TITLES)
        self.assertEqual(
            DISPLAY_SECTION_TITLES.index(postponed_title),
            DISPLAY_SECTION_TITLES.index(SECTION_TITLES[3]) + 1,
        )
        self.assertTrue(is_known_report_title("meetings", postponed_title))
        self.assertFalse(is_manual_section_title("meetings", postponed_title))

    def test_postponed_deadline_and_eight_am_tasks_keep_priority_styling(self) -> None:
        def task(title: str, *, deadline: bool = False) -> SimpleNamespace:
            return SimpleNamespace(
                id=uuid.uuid4(),
                title=title,
                status="TODO",
                assigned_to=None,
                completed_at=None,
                is_deadline_important=deadline,
                fast_task_order=None,
                created_at=None,
            )

        lines = _m3_status_table(
            "SHTYER START DHE DUE DATE",
            [task("Deadline task", deadline=True), task("08:00 task")],
            {},
            with_status=True,
            include_priority_tone=True,
        )
        html = _render_ascii_table_html(lines)

        self.assertIn('class="deadline"', html)
        self.assertIn('class="eight-am"', html)
        self.assertNotIn("[[pt:", html)

    def test_m3_postponement_uses_realization_final_deadline_rule(self) -> None:
        report_day = date(2026, 8, 28)
        task = SimpleNamespace(due_date=datetime(2026, 9, 4, 16, 0, tzinfo=ZoneInfo("Europe/Tirane")))
        due_event = SimpleNamespace(
            action="task.due_date_changed",
            before={"value": "2026-08-28T16:00:00+02:00"},
            after={"value": "2026-09-04T16:00:00+02:00"},
        )

        self.assertTrue(_is_postponed_for_m3_day(task, [due_event], report_day))

        start_only = SimpleNamespace(
            action="task.start_date_changed",
            before={"value": "2026-08-28T08:00:00+02:00"},
            after={"value": "2026-09-04T08:00:00+02:00"},
        )
        task.start_date = datetime(2026, 9, 4, 8, 0, tzinfo=ZoneInfo("Europe/Tirane"))
        self.assertTrue(_is_postponed_for_m3_day(task, [start_only], report_day))

        moved_back = SimpleNamespace(due_date=datetime(2026, 8, 28, 16, 0, tzinfo=ZoneInfo("Europe/Tirane")))
        self.assertFalse(_is_postponed_for_m3_day(moved_back, [due_event], report_day))

        future_to_later = SimpleNamespace(
            action="task.due_date_changed",
            before={"value": "2026-08-31T16:00:00+02:00"},
            after={"value": "2026-09-04T16:00:00+02:00"},
        )
        self.assertFalse(_is_postponed_for_m3_day(task, [future_to_later], report_day))

    def test_m3_postponement_scope_uses_daily_baseline_task_ids(self) -> None:
        first_id = uuid.uuid4()
        second_id = uuid.uuid4()
        snapshots = [
            SimpleNamespace(payload={"people": [
                {"tasks": [{"task_id": str(first_id)}, {"task_id": None}]},
                {"tasks": [{"task_id": str(second_id)}, {"task_id": str(first_id)}]},
            ]}),
        ]

        self.assertEqual(_daily_baseline_task_ids(snapshots), {first_id, second_id})

    def test_m3_completed_day_tasks_include_am_pm_and_inactive_but_exclude_system_and_reopened(self) -> None:
        timezone = ZoneInfo("Europe/Tirane")

        def task(title: str, hour: int, **overrides) -> SimpleNamespace:
            values = {
                "title": title,
                "completed_at": datetime(2026, 8, 24, hour, 0, tzinfo=timezone),
                "status": "DONE",
                "system_template_origin_id": None,
                "system_task_slot_id": None,
            }
            values.update(overrides)
            return SimpleNamespace(**values)

        tasks = [
            task("AM done", 9),
            task("PM done", 16),
            task("System done", 10, system_template_origin_id=uuid.uuid4()),
            task("Legacy system done", 11, system_task_slot_id=uuid.uuid4()),
            task("Inactive done", 14, is_active=False),
            task("Reopened", 8, status="TODO"),
            task("Yesterday", 18, completed_at=datetime(2026, 8, 23, 18, 0, tzinfo=timezone)),
        ]

        completed = _completed_tasks_for_report_day(tasks, date(2026, 8, 24))

        self.assertEqual(
            [item.title for item in completed],
            ["AM done", "PM done", "Inactive done"],
        )

    def test_m3_completed_day_table_has_requested_columns_and_green_rows(self) -> None:
        task = SimpleNamespace(
            id=uuid.uuid4(),
            title="Completed PM task",
            status="DONE",
            completed_at=datetime(2026, 8, 24, 16, 0, tzinfo=ZoneInfo("Europe/Tirane")),
            system_template_origin_id=None,
            system_task_slot_id=None,
            project_id=None,
            assigned_to=None,
            fast_task_order=None,
            is_deadline_important=False,
            is_bllok=False,
            is_r1=False,
            is_1h_report=False,
            is_personal=False,
            department_id="development",
            finish_period="PM",
            due_date=None,
            start_date=None,
            created_at=None,
        )

        rows = _m3_status_table(
            "DET E KRYERA SOT (AM/PM)",
            [task],
            {},
            with_status=True,
            include_type=True,
            include_department=True,
            include_am_pm=True,
            department_codes={"development": "DEV"},
        )
        header = next(row for row in rows if "KUSH" in row and "LLOJI" in row)
        html = _render_ascii_table_html(rows)

        for column in ("NR", "KUSH", "DEP", "AM/PM", "LLOJI", "TITULLI"):
            self.assertIn(column, header)
        self.assertIn("Completed PM task", html)
        self.assertIn('class="done"', html)

    def test_meeting_status_table_sorts_by_clock_time_not_source_date(self) -> None:
        meetings = [
            SimpleNamespace(
                id=uuid.uuid4(), title="13:15 meeting", starts_at=datetime(2026, 8, 1, 13, 15), recurrence_type="daily"
            ),
            SimpleNamespace(
                id=uuid.uuid4(), title="10:15 meeting", starts_at=datetime(2026, 8, 20, 10, 15), recurrence_type="once"
            ),
            SimpleNamespace(
                id=uuid.uuid4(), title="08:30 meeting", starts_at=datetime(2026, 8, 1, 8, 30), recurrence_type="daily"
            ),
        ]

        rows = _meeting_status_checkbox_table(meetings, {})
        meeting_rows = [row for row in rows if "meeting" in row]

        self.assertIn("08:30", meeting_rows[0])
        self.assertIn("10:15", meeting_rows[1])
        self.assertIn("13:15", meeting_rows[2])

    def test_pv_displays_date_range_or_one_day_partial_time_range(self) -> None:
        user_id = uuid.uuid4()
        entry = SimpleNamespace(assigned_to_user_id=user_id, created_by_user_id=None)

        rows = _leave_lines(
            [
                (entry, date(2026, 8, 10), date(2026, 8, 12), True, None, None, None, False),
                (entry, date(2026, 8, 13), date(2026, 8, 13), False, "08:00", "10:00", None, False),
            ],
            {user_id: "Finance Group"},
            {user_id: "FIN"},
        )

        header = next(row for row in rows if "KUSH" in row and "DEP" in row and "NGA" in row and "DERI" in row)
        self.assertLess(header.index("KUSH"), header.index("DEP"))
        self.assertLess(header.index("NGA"), header.index("DERI"))
        self.assertTrue(any("FG" in row and "FIN" in row for row in rows))
        self.assertTrue(any("10.08.2026" in row and "12.08.2026" in row for row in rows))
        self.assertTrue(any("08:00" in row and "10:00" in row for row in rows))

    def test_pv_uses_the_weekly_planner_user_order(self) -> None:
        first_user_id = uuid.uuid4()
        second_user_id = uuid.uuid4()
        first = SimpleNamespace(id=uuid.uuid4(), assigned_to_user_id=first_user_id, created_by_user_id=None)
        second = SimpleNamespace(id=uuid.uuid4(), assigned_to_user_id=second_user_id, created_by_user_id=None)

        rows = _leave_lines(
            [
                (second, date(2026, 8, 12), date(2026, 8, 12), True, None, None, None, False),
                (first, date(2026, 8, 12), date(2026, 8, 12), True, None, None, None, False),
            ],
            {first_user_id: "Zeta User", second_user_id: "Alpha User"},
            user_sort_keys={
                first_user_id: (0, "dev", 0, 1, "zeta user"),
                second_user_id: (0, "dev", 0, 2, "alpha user"),
            },
        )

        data_rows = [row for row in rows if "ZU" in row or "AU" in row]
        self.assertIn("ZU", data_rows[0])
        self.assertIn("AU", data_rows[1])

    def test_meeting_status_cells_use_green_and_red_backgrounds(self) -> None:
        html = _render_ascii_table_html(
            [
                "| NR | KOHA | MBAJTUR? | TITULLI |",
                "| 1 | 10:00 | ✓ | Held meeting |",
                "| 2 | 11:00 | ✕ | Canceled meeting |",
            ]
        )

        self.assertIn('class="n held"', html)
        self.assertIn('class="n canceled"', html)

    def test_non_daily_or_weekly_meetings_receive_a_blue_frame_and_title(self) -> None:
        html = _render_ascii_table_html(
            [
                "| NR | KOHA | TITULLI |",
                "| 1 | 10:00 | One-off meeting [[mc:meeting-red]] [[mt:non_daily_weekly]] |",
            ]
        )

        self.assertIn('class="meeting-red highlight"', html)
        self.assertIn('class="title"', html)
        self.assertIn('bgcolor="#FFD5DC"', html)
        self.assertNotIn("[[mt:non_daily_weekly]]", html)
        self.assertNotIn("[[mc:meeting-red]]", html)

    def test_common_view_one_time_meetings_receive_the_highlight_marker(self) -> None:
        lines = _common_meeting_lines(
            [
                {"id": "one-time", "title": "One-time meeting", "date": "2026-08-11", "time": "10:00", "recurrence_type": "none"},
                {"id": "weekly", "title": "Weekly meeting", "date": "2026-08-11", "time": "11:00", "recurrence_type": "weekly"},
            ],
            date(2026, 8, 11),
        )

        self.assertIn("[[mt:non_daily_weekly]]", lines[0])
        self.assertNotIn("[[mt:non_daily_weekly]]", lines[1])

    def test_common_view_meetings_are_sorted_by_time(self) -> None:
        lines = _common_meeting_lines(
            [
                {"id": "late", "title": "Later meeting", "date": "2026-08-11", "time": "13:15"},
                {"id": "early", "title": "Earlier meeting", "date": "2026-08-11", "time": "10:15"},
                {"id": "first", "title": "First meeting", "date": "2026-08-11", "time": "08:30"},
            ],
            date(2026, 8, 11),
        )

        self.assertEqual(
            lines,
            [
                "- 08:30: First meeting [[mc:meeting-blue]] [[mt:non_daily_weekly]]",
                "- 10:15: Earlier meeting [[mc:meeting-blue]] [[mt:non_daily_weekly]]",
                "- 13:15: Later meeting [[mc:meeting-blue]] [[mt:non_daily_weekly]]",
            ],
        )

    def test_database_meetings_are_sorted_by_clock_time_not_original_date(self) -> None:
        utc = ZoneInfo("UTC")
        lines = _meeting_lines(
            [
                SimpleNamespace(title="Recurring later", starts_at=datetime(2026, 8, 10, 11, 15, tzinfo=utc), recurrence_type="weekly"),
                SimpleNamespace(title="One-off earlier", starts_at=datetime(2026, 8, 11, 8, 15, tzinfo=utc), recurrence_type="none"),
            ]
        )

        self.assertTrue(lines[0].startswith("- 10:15: One-off earlier"))
        self.assertTrue(lines[1].startswith("- 13:15: Recurring later"))

    def test_m3_linked_internal_meetings_inherit_external_colors(self) -> None:
        external_id = uuid.uuid4()
        external = SimpleNamespace(
            id=external_id,
            title="External weekly",
            meeting_type="external",
            calendar_categories=["Brown"],
            calendar_imported=True,
            microsoft_event_id="calendar-event",
            recurrence_type="weekly",
        )
        linked_internal = SimpleNamespace(
            id=uuid.uuid4(),
            title="Internal before external",
            starts_at=datetime(2026, 8, 11, 12, 20),
            meeting_type="internal",
            paired_external_meeting_id=external_id,
            pre_external_meeting_id=None,
            recurrence_type="weekly",
            calendar_categories=[],
            calendar_imported=False,
            microsoft_event_id=None,
        )
        manual_internal = SimpleNamespace(
            id=uuid.uuid4(),
            title="Manual internal",
            starts_at=datetime(2026, 8, 11, 13, 20),
            meeting_type="internal",
            paired_external_meeting_id=None,
            pre_external_meeting_id=None,
            recurrence_type="weekly",
            calendar_categories=[],
            calendar_imported=False,
            microsoft_event_id=None,
        )

        lines = _meeting_lines(
            [linked_internal, manual_internal],
            {str(external_id): external},
        )

        self.assertIn("[[mc:meeting-brown]]", lines[0])
        self.assertIn("[CAL] Internal before external", lines[0])
        self.assertIn("[MANUAL] Manual internal [[mc:meeting-manual]]", lines[1])

    def test_common_view_meetings_include_manual_and_calendar_origin_badges(self) -> None:
        lines = _common_meeting_lines(
            [
                {
                    "id": "manual",
                    "title": "Manual internal",
                    "date": "2026-08-11",
                    "time": "08:10",
                },
                {
                    "id": "calendar",
                    "title": "Calendar internal",
                    "date": "2026-08-11",
                    "time": "08:30",
                    "paired_external_meeting_id": None,
                    "pairedExternalMeetingId": "external-id",
                    "linked_external_calendar_imported": False,
                    "linkedExternalCalendarImported": True,
                },
            ],
            date(2026, 8, 11),
            "internal",
        )

        self.assertIn("[MANUAL] Manual internal [[mc:meeting-manual]]", lines[0])
        self.assertIn("[CAL] Calendar internal", lines[1])
        table_lines = _tomorrow_meeting_table("TAK INTERNE", lines)
        html = _render_ascii_table_html(table_lines)
        self.assertIn('bgcolor="#FFD5DC"', html)
        self.assertIn('bgcolor="#FFF4CC"', html)

        sections = [{"title": SECTION_TITLES[5], "body": "\n".join(table_lines)}]
        docx = render_section_report_docx("PrimeFlow M3", "M3", date(2026, 8, 10), sections)
        with ZipFile(BytesIO(docx)) as archive:
            document_xml = archive.read("word/document.xml").decode("utf-8").lower()
        self.assertIn("ffd5dc", document_xml)
        self.assertIn("fff4cc", document_xml)

        from PIL import Image

        png = render_section_report_png("PrimeFlow M3", "M3", date(2026, 8, 10), sections)
        colors = set(Image.open(BytesIO(png)).convert("RGB").getdata())
        self.assertIn((255, 213, 220), colors)
        self.assertIn((255, 244, 204), colors)

    def test_many_assignees_display_as_all(self) -> None:
        assignee_ids = {uuid.uuid4() for _ in range(11)}
        task = SimpleNamespace(id=uuid.uuid4(), assigned_to=None)
        names = {user_id: f"User {index}" for index, user_id in enumerate(assignee_ids, start=1)}

        self.assertEqual(_task_owners(task, names, {task.id: assignee_ids}), "ALL")

    def test_task_type_labels(self) -> None:
        self.assertEqual(
            _m3_task_type_label(SimpleNamespace(system_template_origin_id=uuid.uuid4(), project_id=uuid.uuid4())),
            "SYS",
        )
        self.assertEqual(
            _m3_task_type_label(
                SimpleNamespace(
                    project_id=uuid.uuid4(),
                    ga_note_origin_id=uuid.uuid4(),
                    is_1h_report=True,
                )
            ),
            "PRJK",
        )
        self.assertEqual(
            _m3_task_type_label(SimpleNamespace(ga_note_origin_id=uuid.uuid4(), is_bllok=True)),
            "BLL",
        )
        self.assertEqual(_m3_task_type_label(SimpleNamespace(is_1h_report=True)), "1H")
        self.assertEqual(_m3_task_type_label(SimpleNamespace(is_r1=True)), "R1")
        self.assertEqual(_m3_task_type_label(SimpleNamespace(is_personal=True)), "P")
        self.assertEqual(
            _m3_task_type_label(SimpleNamespace(plan_note_origin_id=uuid.uuid4())),
            "FT",
        )
        self.assertEqual(_m3_task_type_label(SimpleNamespace()), "FT")

    def test_tomorrow_bllok_table_uses_full_afternoon_interval(self) -> None:
        rows = _tomorrow_common_section(
            common_items={},
            tomorrow=date(2026, 8, 27),
            fallback_external=[],
            fallback_internal=[],
            fallback_bz=[],
            fallback_blocked=[],
        )

        self.assertTrue(any("Bllok 14:30 - 16:00" in row for row in rows))
        self.assertFalse(any("Bllok 14:30 - 15:30" in row for row in rows))

    def test_status_table_includes_type_column(self) -> None:
        task = SimpleNamespace(
            id=uuid.uuid4(),
            title="KA: MODECO KONT",
            status="TODO",
            is_bllok=True,
            is_r1=False,
            is_1h_report=False,
            is_personal=False,
            is_deadline_important=False,
            ga_note_origin_id=None,
            plan_note_origin_id=None,
            system_template_origin_id=None,
            project_id=None,
            assigned_to=None,
            fast_task_order=None,
            due_date=None,
            start_date=None,
            completed_at=None,
            created_at=None,
        )
        rows = _m3_status_table("TODO", [task], {}, include_type=True)
        header = next(row for row in rows if "LLOJI" in row and "TITULLI" in row)
        self.assertIn("LLOJI", header)
        self.assertTrue(any("BLL" in row and "MODECO" in row for row in rows))

    def test_new_task_table_keeps_each_task_status_for_row_coloring(self) -> None:
        task_template = {
            "id": uuid.uuid4(),
            "system_template_origin_id": None,
            "project_id": None,
            "assigned_to": None,
            "fast_task_order": None,
            "is_deadline_important": False,
            "due_date": None,
            "start_date": None,
            "completed_at": None,
            "created_at": None,
        }
        tasks = [
            SimpleNamespace(**task_template, title="Todo task", status="TODO"),
            SimpleNamespace(**{**task_template, "id": uuid.uuid4()}, title="Progress task", status="IN_PROGRESS"),
            SimpleNamespace(**{**task_template, "id": uuid.uuid4()}, title="Waiting task", status="WAITING_CONFIRMATION"),
            SimpleNamespace(**{**task_template, "id": uuid.uuid4()}, title="Done task", status="DONE"),
        ]

        rows = _m3_status_table("DETYRAT E REJA", tasks, {}, with_status=True)
        html = _render_ascii_table_html(rows)

        self.assertIn('class="todo"', html)
        self.assertIn('class="in-progress"', html)
        self.assertIn('class="waiting"', html)
        self.assertIn('class="done"', html)

    def test_status_table_orders_system_tasks_before_fast_tasks(self) -> None:
        system_task = SimpleNamespace(
            id=uuid.uuid4(), title="System task", status="TODO", system_template_origin_id=uuid.uuid4(),
            project_id=None, assigned_to=None, fast_task_order=None, is_deadline_important=False,
            due_date=None, start_date=None, completed_at=None, created_at=None,
        )
        fast_task = SimpleNamespace(
            id=uuid.uuid4(), title="Fast task", status="TODO", system_template_origin_id=None,
            project_id=None, assigned_to=None, fast_task_order=None, is_deadline_important=False,
            due_date=None, start_date=None, completed_at=None, created_at=None,
        )

        rows = _m3_status_table("TODO", [fast_task, system_task], {}, include_type=True)
        task_rows = [row for row in rows if "System task" in row or "Fast task" in row]

        self.assertIn("System task", task_rows[0])
        self.assertIn("Fast task", task_rows[1])

    def test_late_system_task_table_includes_department_after_who(self) -> None:
        department_id = uuid.uuid4()
        task = SimpleNamespace(
            id=uuid.uuid4(),
            title="Late system task",
            status="TODO",
            finish_period="PM",
            system_template_origin_id=uuid.uuid4(),
            department_id=department_id,
            assigned_to=None,
            fast_task_order=None,
            is_deadline_important=False,
            due_date=None,
            start_date=None,
            completed_at=None,
            created_at=None,
        )
        rows = _m3_status_table(
            "LATE",
            [task],
            {},
            include_late_days=True,
            include_department=True,
            include_am_pm=True,
            department_codes={department_id: "FIN"},
        )
        header = next(row for row in rows if "KUSH" in row and "DEP" in row and "AM/PM" in row and "TITULLI" in row)
        self.assertLess(header.index("KUSH"), header.index("DEP"))
        self.assertLess(header.index("DEP"), header.index("AM/PM"))
        self.assertIn("T/Y/O", header)
        self.assertNotIn("LATE", header)
        self.assertLess(header.index("T/Y/O"), header.index("TITULLI"))
        self.assertLess(header.index("DEP"), header.index("TITULLI"))
        self.assertTrue(any("FIN" in row and "PM" in row and "Late system task" in row for row in rows))
        self.assertEqual(_m3_department_label(task, {department_id: "GDS"}), "GD")

    def test_late_system_task_table_uses_tyo_values(self) -> None:
        task = SimpleNamespace(
            id=uuid.uuid4(), title="Late system task", status="TODO", finish_period="AM",
            system_template_origin_id=uuid.uuid4(), department_id=None, assigned_to=None,
            fast_task_order=None, is_deadline_important=False, due_date=None, start_date=None,
            completed_at=None, created_at=None,
        )

        with patch("app.services.meetings_report._late_days", return_value=1):
            yesterday_rows = _m3_status_table("LATE", [task], {}, include_late_days=True)
        with patch("app.services.meetings_report._late_days", return_value=3):
            older_rows = _m3_status_table("LATE", [task], {}, include_late_days=True)

        self.assertTrue(any("Y" in row and "Late system task" in row for row in yesterday_rows))
        self.assertTrue(any("3" in row and "Late system task" in row for row in older_rows))

    def test_bz_table_includes_department_and_am_pm_after_who(self) -> None:
        rows = _tomorrow_task_table(
            "BZ ME GA",
            ["- [TODO] FG: BZ task"],
            with_status=True,
            task_metadata={"BZ task": ("FIN", "AM")},
            include_am_pm_times=True,
        )

        header = next(row for row in rows if "KUSH" in row and "DEP" in row and "AM/PM" in row)
        self.assertLess(header.index("KUSH"), header.index("DEP"))
        self.assertLess(header.index("DEP"), header.index("AM/PM"))
        self.assertTrue(any("FIN" in row and "AM (08:15)" in row and "BZ task" in row for row in rows))

    def test_common_view_task_metadata_uses_string_department_id(self) -> None:
        department_id = uuid.uuid4()
        metadata = _common_task_metadata_by_title(
            [
                {
                    "title": "Blocked task",
                    "date": "2026-08-12",
                    "department_id": str(department_id),
                    "finish_period": "PM",
                }
            ],
            date(2026, 8, 12),
            {department_id: "PRODUCT CONTENT"},
        )

        self.assertEqual(metadata, {"Blocked task": ("PCM", "PM")})

    def test_bz_table_orders_tasks_by_department(self) -> None:
        rows = _tomorrow_task_table(
            "BZ ME GA",
            ["- [TODO] A: PCM task", "- [TODO] B: GD task", "- [TODO] C: DEV task"],
            with_status=True,
            task_metadata={
                "PCM task": ("PCM", "AM"),
                "GD task": ("GD", "AM"),
                "DEV task": ("DEV", "AM"),
            },
        )

        task_rows = [row for row in rows if "task" in row]
        self.assertIn("DEV task", task_rows[0])
        self.assertIn("GD task", task_rows[1])
        self.assertIn("PCM task", task_rows[2])

    def test_task_tables_honor_weekly_planner_department_and_user_order(self) -> None:
        def task(title: str, weekly_order: tuple) -> SimpleNamespace:
            return SimpleNamespace(
                id=uuid.uuid4(), title=title, status="TODO", assigned_to=None,
                fast_task_order=None, is_deadline_important=False, due_date=None,
                start_date=None, completed_at=None, created_at=None,
                _weekly_planner_report_sort=weekly_order,
            )

        rows = _m3_status_table(
            "TODO",
            [
                task("PCM task", (2, "pcm", 0, 0, "DM")),
                task("DEV EF task", (0, "dev", 0, 2, "EF")),
                task("GD task", (1, "gd", 0, 0, "DM")),
                task("DEV AT task", (0, "dev", 0, 1, "AT")),
            ],
            {},
        )
        task_rows = [row for row in rows if "task" in row]

        self.assertIn("DEV AT task", task_rows[0])
        self.assertIn("DEV EF task", task_rows[1])
        self.assertIn("GD task", task_rows[2])
        self.assertIn("PCM task", task_rows[3])

    def test_new_tomorrow_table_marks_this_and_last_week_after_department(self) -> None:
        department_id = uuid.uuid4()
        this_week = SimpleNamespace(
            id=uuid.uuid4(), title="This week", status="TODO", department_id=department_id,
            finish_period="AM", assigned_to=None, fast_task_order=None, is_deadline_important=False,
            due_date=None, start_date=None, completed_at=None, created_at=date(2026, 8, 10),
        )
        last_week = SimpleNamespace(
            id=uuid.uuid4(), title="Last week", status="TODO", department_id=department_id,
            finish_period="PM", assigned_to=None, fast_task_order=None, is_deadline_important=False,
            due_date=None, start_date=None, completed_at=None, created_at=date(2026, 8, 7),
        )
        rows = _m3_status_table(
            "DET TE REJA LAST WEEK DHE THIS WEEK", [this_week, last_week], {},
            include_department=True, include_added_week=True, include_am_pm=True,
            department_codes={department_id: "DEV"}, week_start=date(2026, 8, 10),
        )

        header = next(row for row in rows if "DEP" in row and "KRIJUAR" in row and "AM/PM" in row)
        self.assertLess(header.index("DEP"), header.index("KRIJUAR"))
        self.assertLess(header.index("KRIJUAR"), header.index("AM/PM"))
        self.assertTrue(any("This W" in row for row in rows))
        self.assertTrue(any("Last W" in row for row in rows))
        self.assertEqual(_m3_added_week_label(this_week, date(2026, 8, 10)), "This W")
        rendered = _render_ascii_table_html(rows, "todo")
        self.assertIn('class="created-this-week"', rendered)
        self.assertIn('bgcolor="#bae6fd"', rendered)
        self.assertIn('class="created-last-week"', rendered)
        self.assertIn('bgcolor="#fde68a"', rendered)

    def test_new_m3_tasks_are_included_only_on_their_start_date(self) -> None:
        wednesday = date(2026, 8, 12)
        task = SimpleNamespace(
            start_date=wednesday,
            due_date=date(2026, 8, 14),
            created_at=date(2026, 8, 7),
            completed_at=None,
            status="TODO",
        )

        self.assertTrue(_is_new_task_for_m3_day(task, wednesday))
        self.assertFalse(_is_new_task_for_m3_day(task, date(2026, 8, 13)))

        no_start_date = SimpleNamespace(
            start_date=None,
            due_date=wednesday,
            created_at=date(2026, 8, 10),
            completed_at=None,
            status="TODO",
        )
        self.assertFalse(_is_new_task_for_m3_day(no_start_date, wednesday))

    def test_new_task_review_excludes_system_task_occurrences(self) -> None:
        regular_task = SimpleNamespace(system_template_origin_id=None, system_task_slot_id=None)
        system_task = SimpleNamespace(system_template_origin_id=uuid.uuid4(), system_task_slot_id=None)
        slot_based_system_task = SimpleNamespace(system_template_origin_id=None, system_task_slot_id=uuid.uuid4())

        self.assertFalse(_is_system_task(regular_task))
        self.assertTrue(_is_system_task(system_task))
        self.assertTrue(_is_system_task(slot_based_system_task))

    def test_todo_table_includes_department_after_who(self) -> None:
        department_id = uuid.uuid4()
        project_id = uuid.uuid4()
        task = SimpleNamespace(
            id=uuid.uuid4(),
            title="Pink task",
            status="TODO",
            system_template_origin_id=None,
            project_id=project_id,
            department_id=department_id,
            assigned_to=None,
            fast_task_order=None,
            is_deadline_important=False,
            due_date=None,
            start_date=None,
            completed_at=None,
            created_at=None,
        )
        rows = _m3_status_table(
            "TODO",
            [task],
            {},
            include_department=True,
            department_codes={department_id: "PCM"},
            project_titles_by_id={project_id: "PrimeFlow Task Manager"},
        )
        header = next(
            row
            for row in rows
            if "KUSH" in row and "DEP" in row and "PRJK" in row and "TITULLI" in row
        )
        self.assertLess(header.index("KUSH"), header.index("DEP"))
        self.assertLess(header.index("DEP"), header.index("PRJK"))
        self.assertTrue(
            any(
                "PCM" in row and "PrimeFlow Task Manager" in row and "Pink task" in row
                for row in rows
            )
        )
        rendered = _render_ascii_table_html(rows, "todo")
        self.assertIn("PRJK", rendered)
        self.assertIn("PrimeFlow Task Manager", rendered)
        self.assertIn('<col width="110">', rendered)

    def test_project_column_uses_dash_for_fast_tasks(self) -> None:
        task = SimpleNamespace(
            id=uuid.uuid4(), title="Standalone fast task", status="TODO",
            system_template_origin_id=None, project_id=None, assigned_to=None,
            fast_task_order=None, is_deadline_important=False, due_date=None,
            start_date=None, completed_at=None, created_at=None,
        )

        rows = _m3_status_table("TODO", [task], {}, project_titles_by_id={})
        header = next(row for row in rows if "PRJK" in row and "TITULLI" in row)
        data = next(row for row in rows if "Standalone fast task" in row)

        self.assertEqual(len(header.split("|")), len(data.split("|")))
        self.assertIn("| -", data)
        rendered = _render_ascii_table_html(rows, "todo")
        self.assertIn('<col width="44">', rendered)
        self.assertNotIn('<col width="110">', rendered)

    def test_without_progress_includes_task_active_before_later_due_date(self) -> None:
        task = SimpleNamespace(
            status="TO DO",
            completed_at=None,
            system_template_origin_id=None,
            system_task_slot_id=None,
            project_id=uuid.uuid4(),
            start_date=date(2026, 8, 18),
            due_date=date(2026, 8, 20),
        )

        self.assertTrue(_is_without_progress_for_m3_day(task, date(2026, 8, 18)))
        self.assertFalse(_is_without_progress_for_m3_day(task, date(2026, 8, 17)))

    def test_todo_table_includes_daily_rlz_reason_and_comment(self) -> None:
        task = SimpleNamespace(
            id=uuid.uuid4(), title="Platforma PrimeFlow", status="TODO",
            system_template_origin_id=None, department_id=None, assigned_to=None,
            fast_task_order=None, is_deadline_important=False, due_date=None,
            start_date=None, completed_at=None, created_at=None,
        )
        rows = _m3_status_table(
            "TODO", [task], {},
            daily_rlz_by_task={task.id: ("Urgjence tjeter", "Po pres inputin")},
        )

        header = next(row for row in rows if "ARSYEJA" in row and "KOMENT" in row)
        self.assertLess(header.index("TITULLI"), header.index("ARSYEJA"))
        self.assertTrue(any("Urgjence tjeter" in row and "Po pres inputin" in row for row in rows))
        rendered = _render_ascii_table_html(rows, "todo")
        self.assertIn("ARSYEJA", rendered)
        self.assertIn("Urgjence tjeter", rendered)
        self.assertIn("Po pres inputin", rendered)

    def test_late_system_table_includes_tyo_reason_and_comment(self) -> None:
        task = SimpleNamespace(
            id=uuid.uuid4(), title="Late system task", status="TODO",
            system_template_origin_id=uuid.uuid4(), department_id=None, assigned_to=None,
            fast_task_order=None, is_deadline_important=False,
            due_date=date(2026, 8, 29), start_date=date(2026, 8, 29),
            completed_at=None, created_at=None, finish_period=None,
            project_id=None, is_bllok=False, is_r1=False,
            is_1h_report=False, is_personal=False,
        )
        rows = _m3_status_table(
            "LATE",
            [task],
            {},
            include_late_days=True,
            daily_rlz_by_task={task.id: ("Urgjence tjeter", "Po pres inputin")},
        )

        header = next(row for row in rows if "T/Y/O" in row)
        self.assertLess(header.index("T/Y/O"), header.index("TITULLI"))
        self.assertLess(header.index("TITULLI"), header.index("ARSYEJA"))
        self.assertLess(header.index("ARSYEJA"), header.index("KOMENT"))
        self.assertTrue(any("Urgjence tjeter" in row and "Po pres inputin" in row for row in rows))


class MeetingsReportCombinedPostponementTests(unittest.IsolatedAsyncioTestCase):
    async def test_combined_start_due_dates_do_not_shift_task_title_column(self) -> None:
        task_id = uuid.uuid4()
        project_id = uuid.uuid4()
        report_day = date(2026, 9, 1)
        task = SimpleNamespace(
            id=task_id,
            title="Actual task title",
            status="TODO",
            start_date=datetime(2026, 9, 2, 8, 0, tzinfo=ZoneInfo("Europe/Tirane")),
            due_date=datetime(2026, 9, 3, 16, 0, tzinfo=ZoneInfo("Europe/Tirane")),
            completed_at=None,
            system_template_origin_id=None,
            system_task_slot_id=None,
            project_id=project_id,
            assigned_to=None,
            fast_task_order=None,
            is_deadline_important=False,
            is_bllok=False,
            is_r1=False,
            is_1h_report=False,
            is_personal=False,
            department_id=None,
            finish_period="PM",
            created_at=None,
        )
        snapshot = SimpleNamespace(payload={"people": [{"tasks": [{"task_id": str(task_id)}]}]})
        events = [
            SimpleNamespace(
                entity_id=task_id,
                action="task.start_date_changed",
                before={"value": "2026-09-01T08:00:00+02:00"},
                after={"value": "2026-09-02T08:00:00+02:00"},
            ),
            SimpleNamespace(
                entity_id=task_id,
                action="task.due_date_changed",
                before={"value": "2026-09-01T16:00:00+02:00"},
                after={"value": "2026-09-03T16:00:00+02:00"},
            ),
        ]

        class Result:
            def __init__(self, values):
                self.values = values

            def scalars(self):
                return self

            def all(self):
                return self.values

        db = SimpleNamespace(execute=AsyncMock(side_effect=[Result([snapshot]), Result(events)]))
        _, _, postponed_both, date_ranges = await _postponed_tasks_for_m3_day(
            db, report_day, [task]
        )

        self.assertEqual(postponed_both, [task])
        self.assertNotIn("|", date_ranges[task_id][0])
        self.assertNotIn("|", date_ranges[task_id][1])
        rows = _m3_status_table(
            "",
            postponed_both,
            {},
            date_range_by_task=date_ranges,
            project_titles_by_id={project_id: "Long Postponed Project Name"},
        )
        header = next(row for row in rows if "PRJK" in row and "TITULLI" in row)
        data = next(row for row in rows if "Actual task title" in row)
        self.assertEqual(len(header.split("|")), len(data.split("|")))
        self.assertTrue(any("Long Postponed Project" in row for row in rows))
        rendered = _render_ascii_table_html(rows)
        self.assertIn("START: 01.09.2026</div>", rendered)
        self.assertIn("DUE: 01.09.2026</div>", rendered)
        self.assertIn("START: 02.09.2026</div>", rendered)
        self.assertIn("DUE: 03.09.2026</div>", rendered)
        self.assertEqual(rendered.count("border-bottom:1px solid #94a3b8"), 2)
        self.assertIn("Actual task title", rendered)


if __name__ == "__main__":
    unittest.main()


from tests.report_attendance_fixtures import present_report_population
