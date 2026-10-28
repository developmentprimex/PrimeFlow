from __future__ import annotations

import unittest
from datetime import date, datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image

from app.services.ga_time_table import DEFAULT_GA_TIME_TABLE_ROWS
from app.services.meetings_report import _section_report_blocks
from app.services.one_h_ga_attachments import (
    _render_ga_hv_status_tables_html,
    build_ga_only_1h_attachments,
    render_ga_tables_html,
    render_ga_time_table_html,
    render_ga_time_table_png,
)
from app.services.primeflow_report_delivery import _regular_recipient_document, split_ga_recipient_map
from app.services.primeflow_report import (
    ReportReminderQuestion,
    build_report_document,
    render_html,
    render_plain_text,
)


def _result(rows):
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


class GaOnlyOneHAttachmentTests(unittest.IsolatedAsyncioTestCase):
    def test_question_blocks_are_kept_for_ga_and_removed_for_regular_recipients(self) -> None:
        ga_document = build_report_document(
            {"guardrails": {"truncated": {}}, "items": {}},
            date(2026, 8, 24),
            "10:00",
            reminders=[ReportReminderQuestion(text="Hap doc dhe det")],
        )

        regular_document = _regular_recipient_document(ga_document)
        ga_html = render_html(ga_document)
        regular_html = render_html(regular_document)
        regular_text = render_plain_text(regular_document)

        self.assertIn("PYETJET PER 1H - BORD", ga_html)
        self.assertIn("STAFF - HAPAT PER 1H", ga_html)
        self.assertNotIn("PYETJET PER 1H - BORD", regular_html)
        self.assertNotIn("STAFF - HAPAT PER 1H", regular_html)
        self.assertNotIn("PYETJET PER 1H - BORD", regular_text)
        self.assertNotIn("STAFF - HAPAT PER 1H", regular_text)
        self.assertTrue(ga_document.board_reminders)
        self.assertTrue(ga_document.reminders)
        self.assertEqual(regular_document.board_reminders, [])
        self.assertEqual(regular_document.reminders, [])

    def test_ga_hv_email_hides_tables_for_empty_statuses(self) -> None:
        body = """TODO:
+----+-------+---------+------------------+
| NR | KUSH  | LLOJI  | TITULLI          |
+----+-------+---------+------------------+
| 1  | GA    | SYS     | Todo task        |
+----+-------+---------+------------------+

IN PROGRESS:
+----+-------+---------+------------------+
| NR | KUSH  | LLOJI  | TITULLI          |
+----+-------+---------+------------------+
| -  | -     | -       | (Asnje detyre)   |
+----+-------+---------+------------------+

DONE:
+----+-------+---------+------------------+
| NR | KUSH  | LLOJI  | TITULLI          |
+----+-------+---------+------------------+
| 1  | GA    | SYS     | Done task        |
+----+-------+---------+------------------+

LATE:
+----+-------+---------+------------------+--------------+
| NR | KUSH  | LLOJI  | TITULLI          | LATE         |
+----+-------+---------+------------------+--------------+
| 1  | GA    | SYS     | Late task        | 2 days       |
+----+-------+---------+------------------+--------------+"""

        rendered = _render_ga_hv_status_tables_html(body)

        self.assertEqual(rendered.count('data-ga-hv-status-table="true"'), 3)
        self.assertEqual(rendered.count('data-ga-hv-empty-status="true"'), 1)
        self.assertIn("IN PROGRESS: 0", rendered)
        self.assertIn('background-color:#FBCFE8', rendered)
        self.assertIn('background-color:#D4FFE1', rendered)
        self.assertIn('background-color:#FEE2E2', rendered)
        self.assertNotIn("(Asnje detyre)", rendered)
        self.assertIn("<th", rendered)
        self.assertNotIn("<pre", rendered)

        png_blocks = _section_report_blocks(body)
        png_tables = [block for block in png_blocks if block["kind"] == "table"]
        png_text = "\n".join(
            line
            for block in png_blocks
            if block["kind"] == "text"
            for line in block["lines"]
        )
        self.assertEqual(len(png_tables), 3)
        self.assertIn("IN PROGRESS: 0", png_text)

    def test_130_stays_with_regular_recipients_and_only_ga_gets_extra_content(self) -> None:
        regular, ga = split_ga_recipient_map({
            "to": ["staff@primexeu.com"],
            "cc": ["130PRIMEX.EU@GMAIL.COM", "manager@primexeu.com"],
            "bcc": ["130primex.eu@gmail.com", "audit@primexeu.com"],
        })

        self.assertEqual(regular, {
            "to": ["staff@primexeu.com"],
            "cc": ["130PRIMEX.EU@GMAIL.COM", "manager@primexeu.com"],
            "bcc": ["audit@primexeu.com"],
        })
        self.assertEqual(ga, {
            "to": ["ga@primexeu.com"],
            "cc": [],
            "bcc": [],
        })

    def test_130_remains_the_regular_to_recipient(self) -> None:
        regular, ga = split_ga_recipient_map({
            "to": ["130primex.eu@gmail.com"],
            "cc": ["manager@primexeu.com"],
            "bcc": [],
        })

        self.assertEqual(regular["to"], ["130primex.eu@gmail.com"])
        self.assertEqual(regular["cc"], ["manager@primexeu.com"])
        self.assertIsNotNone(ga)

    def test_ga_is_the_only_recipient_isolated_for_extra_content(self) -> None:
        regular, ga = split_ga_recipient_map({
            "to": ["ga@primexeu.com"],
            "cc": [],
            "bcc": [],
        })

        self.assertEqual(regular["to"], [])
        self.assertEqual(ga, {
            "to": ["ga@primexeu.com"],
            "cc": [],
            "bcc": [],
        })

    async def test_empty_timetable_still_renders_a_valid_week_png(self) -> None:
        db = SimpleNamespace(execute=AsyncMock(side_effect=[
            _result(list(DEFAULT_GA_TIME_TABLE_ROWS)),
            _result([SimpleNamespace(id="ga-user")]),
            _result([]),
            _result([]),
            _result([]),
        ]))

        png = await render_ga_time_table_png(db, date(2026, 8, 24))

        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        image = Image.open(BytesIO(png))
        self.assertGreater(image.width, 1500)
        self.assertGreater(image.height, 700)

    async def test_attachment_bundle_has_weekly_timetable_and_daily_ga_hv_png(self) -> None:
        with (
            patch(
                "app.services.one_h_ga_attachments.render_ga_time_table_png",
                new=AsyncMock(return_value=b"\x89PNG-time"),
            ),
            patch(
                "app.services.one_h_ga_attachments.render_ga_hv_tasks_png",
                new=AsyncMock(return_value=b"\x89PNG-tasks"),
            ),
        ):
            attachments = await build_ga_only_1h_attachments(
                SimpleNamespace(),
                date(2026, 8, 26),
                today_print_png=("1H-SHTYPI-Today-2026-08-26.png", b"\x89PNG-shtypi", "image/png"),
            )

        self.assertEqual(
            [(name, mime) for name, _, mime in attachments],
            [
                ("GA-Time-Table-2026-08-24.png", "image/png"),
                ("GA-HV-Tasks-2026-08-26.png", "image/png"),
                ("1H-SHTYPI-Today-2026-08-26.png", "image/png"),
            ],
        )

    async def test_timetable_email_version_is_a_native_html_table(self) -> None:
        db = SimpleNamespace(execute=AsyncMock(side_effect=[
            _result(list(DEFAULT_GA_TIME_TABLE_ROWS)),
            _result([SimpleNamespace(id="ga-user")]),
            _result([]),
            _result([]),
            _result([]),
        ]))

        rendered = await render_ga_time_table_html(db, date(2026, 8, 24))

        self.assertIn('data-ga-time-table="true"', rendered)
        self.assertIn("24.08.2026", rendered)
        self.assertIn("28.08.2026", rendered)
        self.assertIn('<col width="30" style="width:30px;">', rendered)
        self.assertIn('<col width="46" style="width:46px;">', rendered)
        self.assertEqual(rendered.count('<col width="180" style="width:180px;">'), 2)
        self.assertIn("H = 24.08.2026", rendered)
        self.assertIn("P = 28.08.2026", rendered)
        self.assertIn('<td colspan="2"', rendered)
        self.assertIn("07:30<br>08:00", rendered)
        self.assertNotIn("<img", rendered)

    async def test_timetable_email_includes_synced_reminders(self) -> None:
        reminder = SimpleNamespace(
            day_date=date(2026, 8, 24),
            start_time=DEFAULT_GA_TIME_TABLE_ROWS[2].start_time,
            content="REMINDER 00:00: Follow up tomorrow",
            source_type="reminder",
            created_at=datetime(2026, 8, 24, 6, 0),
        )
        db = SimpleNamespace(execute=AsyncMock(side_effect=[
            _result(list(DEFAULT_GA_TIME_TABLE_ROWS)),
            _result([SimpleNamespace(id="ga-user")]),
            _result([]),
            _result([reminder]),
            _result([]),
        ]))

        rendered = await render_ga_time_table_html(db, date(2026, 8, 24))

        self.assertIn("R: 00:00: Follow up tomorrow", rendered)
        self.assertNotIn("REMINDER 00:00: Follow up tomorrow", rendered)
        self.assertIn("background-color:#FEF3C7", rendered)

    async def test_timetable_email_uses_common_view_meeting_visibility(self) -> None:
        def meeting(
            title: str,
            meeting_type: str,
            hour: int,
            *,
            calendar_imported: bool = False,
            paired_external_meeting_id: str | None = None,
        ):
            return SimpleNamespace(
                id=title,
                title=title,
                meeting_type=meeting_type,
                starts_at=datetime(2026, 8, 24, hour, 0),
                created_at=datetime(2026, 8, 24, hour, 0),
                recurrence_type="none",
                recurrence_days_of_week=None,
                recurrence_days_of_month=None,
                calendar_categories=[],
                calendar_imported=calendar_imported,
                microsoft_event_id=title if calendar_imported else None,
                calendar_sync_status="active",
                paired_external_meeting_id=paired_external_meeting_id,
                pre_external_meeting_id=None,
            )

        meetings = [
            meeting("Visible external", "external", 9),
            meeting("Visible internal", "internal", 10),
            meeting("Linked internal", "internal", 10, paired_external_meeting_id="Visible external"),
            meeting("DV PV 24.08-28.08.2026", "external", 11, calendar_imported=True),
        ]
        db = SimpleNamespace(execute=AsyncMock(side_effect=[
            _result(list(DEFAULT_GA_TIME_TABLE_ROWS)),
            _result([SimpleNamespace(id="ga-user")]),
            _result([]),
            _result([]),
            _result(meetings),
            _result([]),
        ]))

        rendered = await render_ga_time_table_html(db, date(2026, 8, 24))

        self.assertIn("TAK EXT: Visible external", rendered)
        self.assertIn("TAK INT: Visible internal", rendered)
        self.assertNotIn("TAK INT: Linked internal", rendered)
        self.assertNotIn("DV PV 24.08-28.08.2026", rendered)

    async def test_timetable_email_reloads_latest_saved_content_on_each_render(self) -> None:
        def entry(content: str):
            return SimpleNamespace(
                day_of_week=0,
                start_time=DEFAULT_GA_TIME_TABLE_ROWS[3].start_time,
                content=content,
                background_color="#FFFFFF",
                text_color="#0F172A",
                is_bold=False,
                is_italic=False,
            )

        db = SimpleNamespace(execute=AsyncMock(side_effect=[
            _result(list(DEFAULT_GA_TIME_TABLE_ROWS)),
            _result([SimpleNamespace(id="ga-user")]),
            _result([entry("OLD TIMETABLE VALUE")]),
            _result([]),
            _result([]),
            _result(list(DEFAULT_GA_TIME_TABLE_ROWS)),
            _result([SimpleNamespace(id="ga-user")]),
            _result([entry("LATEST TIMETABLE VALUE")]),
            _result([]),
            _result([]),
        ]))

        first = await render_ga_time_table_html(db, date(2026, 8, 24))
        latest = await render_ga_time_table_html(db, date(2026, 8, 24))

        self.assertIn("OLD TIMETABLE VALUE", first)
        self.assertNotIn("OLD TIMETABLE VALUE", latest)
        self.assertIn("LATEST TIMETABLE VALUE", latest)
        for call_index in (0, 2, 3, 4, 5, 7, 8, 9):
            statement = db.execute.await_args_list[call_index].args[0]
            self.assertTrue(statement.get_execution_options().get("populate_existing"))

    async def test_inline_tables_are_inserted_before_the_first_slot(self) -> None:
        document = build_report_document(
            {"guardrails": {"truncated": {}}, "items": {}},
            date(2026, 8, 24),
            "10:00",
        )

        with (
            patch(
                "app.services.one_h_ga_attachments.render_ga_time_table_html",
                new=AsyncMock(return_value='<table data-ga-time-table="true"></table>'),
            ),
            patch(
                "app.services.one_h_ga_attachments.render_ga_hv_tasks_html",
                new=AsyncMock(return_value='<table data-ga-hv-tasks="true"></table>'),
            ),
        ):
            tables = await render_ga_tables_html(
                SimpleNamespace(),
                date(2026, 8, 24),
                today_print_html='<div data-today-print-report="true">SHTYPI</div>',
            )
        rendered = render_html(document, pre_sections_html=tables, content_width=1200)

        inline_position = rendered.index('data-ga-inline-tables="true"')
        timetable_position = rendered.index('data-ga-time-table="true"')
        ga_hv_position = rendered.index('data-ga-hv-tasks="true"')
        today_print_position = rendered.index('data-today-print-report="true"')
        reminders_position = rendered.index('data-board-reminder-columns="true"')
        first_slot_position = rendered.index("10:00 SLOTI 24.08.2026")
        self.assertLess(timetable_position, ga_hv_position)
        self.assertLess(ga_hv_position, today_print_position)
        self.assertLess(today_print_position, reminders_position)
        self.assertLess(inline_position, first_slot_position)
        self.assertIn('data-ga-time-table="true"', rendered)
        self.assertIn('data-ga-hv-tasks="true"', rendered)
        self.assertNotIn("cid:primeflow-ga", rendered)
        self.assertIn('width="1200"', rendered)


if __name__ == "__main__":
    unittest.main()
