import unittest
import io
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace

from fastapi import HTTPException
from openpyxl import Workbook, load_workbook
from openpyxl.cell.rich_text import CellRichText
from starlette.datastructures import UploadFile

from app.api.routers.exports import (
    OPEN_TASK_BASELINE_STATUS_VALUES,
    OPEN_TASK_EXPORT_HEADERS,
    OPEN_TASK_WHEN_VALUES,
    _normalize_open_task_baseline_value,
    _open_task_baseline_column_numbers,
    _open_task_id_column_number,
    _open_task_pf_display_value,
    _open_task_planned_status,
    _open_task_planning_when,
    _open_task_source_label,
    _open_task_should_compare_status,
    _open_task_values_match,
    _open_task_wrapped_line_count,
    _open_task_title_rich_text,
    export_open_tasks_xlsx,
    import_open_tasks_baseline,
    reset_open_tasks_baseline,
)
from app.models.enums import UserRole


class TestOpenTasksExportLayout(unittest.TestCase):
    def test_title_strikes_preserve_only_completed_segments(self) -> None:
        value = _open_task_title_rich_text(
            "Open\n[[done]]Done [[added]]also done[[/added]][[/done]]\nStill open"
        )
        self.assertIsInstance(value, CellRichText)
        self.assertEqual(str(value), "Open\nDone also done\nStill open")
        self.assertEqual([part.text for part in value if part.font.strike], ["Done also done"])
        self.assertEqual(_open_task_wrapped_line_count(value, 44), 3)

    def test_title_without_strikes_remains_plain_text(self) -> None:
        for source, expected in [(None, ""), ("<b>Title</b>", "Title"),
                                 ("[[added]]New[[/added]]", "New")]:
            self.assertEqual(_open_task_title_rich_text(source), expected)

    def test_wrapped_line_count_accounts_for_column_width(self) -> None:
        title = "AT/OH:EF/RA: ASC: DEF KO1/KO2/KOF PER KUZHINA (CLAIMS)"

        self.assertEqual(_open_task_wrapped_line_count(title, 44), 2)

    def test_wrapped_line_count_accounts_for_explicit_newlines(self) -> None:
        title = "First line\nSecond line\nThird line"

        self.assertEqual(_open_task_wrapped_line_count(title, 44), 3)

    def test_px_jav_task_uses_ga_ka_source_group(self) -> None:
        task = SimpleNamespace(
            ga_note_origin_id=None,
            plan_note_origin_id="plan-note-id",
            system_template_origin_id=None,
            project_id="project-id",
            is_bllok=False,
            is_r1=False,
            is_1h_report=False,
            is_personal=False,
        )

        self.assertEqual(_open_task_source_label(task), "GA/KA")

    def test_comparison_columns_are_paired_in_requested_order(self) -> None:
        self.assertEqual(
            OPEN_TASK_EXPORT_HEADERS[16:21],
            ["WHEN MANUAL", "STATUS MANUAL", "WHEN PF", "STATUS PF", "KOMENT"],
        )

    def test_baseline_columns_are_found_in_legacy_and_current_layouts(self) -> None:
        legacy_tail = ["WHEN", "WHEN PLANNED", "STATUS", "STATUS PLANNED", "KOMENT"]
        legacy_headers = [
            header for header in OPEN_TASK_EXPORT_HEADERS[:16] if header != "TASK ID"
        ] + legacy_tail
        previous_headers = OPEN_TASK_EXPORT_HEADERS[:16] + legacy_tail
        for headers, expected in (
            (legacy_headers, (16, 18, 20)),
            (previous_headers, (17, 19, 21)),
            (OPEN_TASK_EXPORT_HEADERS, (17, 18, 21)),
        ):
            workbook = Workbook()
            worksheet = workbook.active
            for column, header in enumerate(headers, start=1):
                worksheet.cell(4, column, header)
            self.assertEqual(_open_task_baseline_column_numbers(worksheet), expected)

    def test_visible_task_id_column_is_detected_only_in_current_layout(self) -> None:
        workbook = Workbook()
        worksheet = workbook.active
        for column, header in enumerate(OPEN_TASK_EXPORT_HEADERS, start=1):
            worksheet.cell(4, column, header)
        self.assertEqual(_open_task_id_column_number(worksheet), 2)

        worksheet.cell(4, 2, "OLD ID")
        self.assertIsNone(_open_task_id_column_number(worksheet))

    def test_planning_when_uses_upcoming_week_as_this_week(self) -> None:
        current_monday = date(2026, 9, 7)

        self.assertEqual(_open_task_planning_when(date(2026, 9, 11), current_monday), "SOT")
        self.assertEqual(_open_task_planning_when(date(2026, 9, 14), current_monday), "THIS WEEK")
        self.assertEqual(_open_task_planning_when(date(2026, 9, 18), current_monday), "THIS WEEK")
        self.assertEqual(_open_task_planning_when(date(2026, 9, 21), current_monday), "NEXT WEEK")
        self.assertEqual(_open_task_planning_when(date(2026, 9, 25), current_monday), "NEXT WEEK")
        self.assertEqual(_open_task_planning_when(date(2026, 9, 28), current_monday), "FUTURE")

    def test_planning_when_accepts_datetime_and_leaves_unplanned_dates_blank(self) -> None:
        current_monday = date(2026, 9, 7)

        self.assertEqual(
            _open_task_planning_when(datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc), current_monday),
            "THIS WEEK",
        )
        self.assertEqual(_open_task_planning_when(date(2026, 9, 10), current_monday), "")
        self.assertEqual(_open_task_planning_when(None, current_monday), "")

    def test_planned_status_uses_primeflow_task_flags(self) -> None:
        def task(**overrides):
            values = {"is_1h_report": False, "is_personal": False, "is_bllok": False, "is_r1": False}
            values.update(overrides)
            return SimpleNamespace(**values)

        self.assertEqual(_open_task_planned_status(task(is_1h_report=True)), "1H")
        self.assertEqual(_open_task_planned_status(task(is_personal=True)), "PERSONAL")
        self.assertEqual(_open_task_planned_status(task(is_bllok=True)), "BLLOK")
        self.assertEqual(_open_task_planned_status(task(is_r1=True)), "R1")
        self.assertEqual(_open_task_planned_status(task()), "")

    def test_pf_values_are_always_displayed_and_matches_are_detected(self) -> None:
        self.assertEqual(_open_task_pf_display_value("THIS WEEK", "THIS WEEK"), "THIS WEEK")
        self.assertEqual(_open_task_pf_display_value("THIS WEEK", "NEXT WEEK"), "NEXT WEEK")
        self.assertEqual(_open_task_pf_display_value("1H", "1H"), "1H")
        self.assertEqual(_open_task_pf_display_value("1H", "BLLOK"), "BLLOK")
        self.assertEqual(_open_task_pf_display_value("THIS WEEK", None), "UNPLANNED")
        self.assertEqual(_open_task_pf_display_value(None, None), "")
        self.assertTrue(_open_task_values_match(" this week ", "THIS WEEK"))
        self.assertFalse(_open_task_values_match("THIS WEEK", "NEXT WEEK"))

    def test_future_manual_tasks_skip_status_comparison(self) -> None:
        self.assertFalse(_open_task_should_compare_status("FUTURE"))
        self.assertFalse(_open_task_should_compare_status(" future "))
        self.assertTrue(_open_task_should_compare_status("THIS WEEK"))
        self.assertTrue(_open_task_should_compare_status(None))

    def test_baseline_import_normalizes_and_validates_values(self) -> None:
        self.assertEqual(
            _normalize_open_task_baseline_value(" this   week ", OPEN_TASK_WHEN_VALUES, "WHEN"),
            "THIS WEEK",
        )
        self.assertEqual(
            _normalize_open_task_baseline_value("bllok", OPEN_TASK_BASELINE_STATUS_VALUES, "STATUS"),
            "BLLOK",
        )
        self.assertIsNone(_normalize_open_task_baseline_value("", OPEN_TASK_WHEN_VALUES, "WHEN"))
        with self.assertRaises(HTTPException):
            _normalize_open_task_baseline_value("THIS MONTH", OPEN_TASK_WHEN_VALUES, "WHEN")


class _FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def unique(self):
        return self

    def all(self):
        return self.rows


class _FakeSession:
    def __init__(self, results):
        self.results = iter(results)
        self.statements = []
        self.added = []
        self.deleted = []
        self.committed = False

    async def execute(self, _statement):
        self.statements.append(_statement)
        return _FakeResult(next(self.results))

    def add(self, value):
        self.added.append(value)

    async def delete(self, value):
        self.deleted.append(value)

    async def commit(self):
        self.committed = True


class TestOpenTasksExportWorkbook(unittest.IsolatedAsyncioTestCase):
    async def test_import_uses_visible_task_ids_after_rows_are_reordered(self) -> None:
        first_task_id = uuid.uuid4()
        second_task_id = uuid.uuid4()
        workbook = Workbook()
        ws = workbook.active
        ws.title = "OPEN TASKS"
        for column, header in enumerate(OPEN_TASK_EXPORT_HEADERS, start=1):
            ws.cell(4, column, header)

        # Visible rows were reordered in Excel. IDs move with their manual
        # values, while the legacy hidden row map remains in export order.
        ws.cell(5, 2, str(second_task_id))
        ws.cell(5, 15, "Second task with an edited title")
        ws.cell(5, 17, "this week")
        ws.cell(5, 18, "1h")
        ws.cell(6, 2, str(first_task_id))
        ws.cell(6, 15, "First task renamed")
        ws.cell(6, 17, "next week")
        ws.cell(6, 18, "personal")

        metadata = workbook.create_sheet("_PRIMEFLOW")
        metadata.sheet_state = "veryHidden"
        metadata["A1"] = "OPEN_TASKS_BASELINE_V1"
        metadata["B1"] = "2026-09-14"
        metadata["A2"] = "EXCEL ROW"
        metadata["B2"] = "TASK ID"
        metadata["A3"] = 5
        metadata["B3"] = str(first_task_id)
        metadata["A4"] = 6
        metadata["B4"] = str(second_task_id)
        content = io.BytesIO()
        workbook.save(content)
        content.seek(0)

        tasks = [
            SimpleNamespace(id=first_task_id, department_id=None),
            SimpleNamespace(id=second_task_id, department_id=None),
        ]
        db = _FakeSession([tasks, []])
        user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN, department_id=None)

        result = await import_open_tasks_baseline(
            file=UploadFile(filename="OPEN_TASKS.xlsx", file=content), db=db, user=user
        )

        self.assertEqual(result["imported"], 2)
        saved = {baseline.task_id: baseline for baseline in db.added}
        self.assertEqual(saved[second_task_id].when_value, "THIS WEEK")
        self.assertEqual(saved[second_task_id].status_value, "1H")
        self.assertEqual(saved[first_task_id].when_value, "NEXT WEEK")
        self.assertEqual(saved[first_task_id].status_value, "PERSONAL")

    async def test_reset_deletes_only_the_requested_week_rows_returned_by_the_query(self) -> None:
        baselines = [SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4())]
        db = _FakeSession([baselines])
        user = SimpleNamespace(
            id=uuid.uuid4(),
            role=UserRole.ADMIN,
            department_id=None,
        )

        result = await reset_open_tasks_baseline(
            planning_week_start=date(2026, 9, 14),
            db=db,
            user=user,
        )

        self.assertEqual(result, {"planning_week_start": "2026-09-14", "deleted": 2})
        self.assertEqual(db.deleted, baselines)
        self.assertTrue(db.committed)

    async def test_import_saves_manual_values_for_the_planning_week(self) -> None:
        task_id = uuid.uuid4()
        workbook = Workbook()
        ws = workbook.active
        ws.title = "OPEN TASKS"
        legacy_headers = [
            header for header in OPEN_TASK_EXPORT_HEADERS[:16] if header != "TASK ID"
        ] + ["WHEN", "WHEN PLANNED", "STATUS", "STATUS PLANNED", "KOMENT"]
        for column, header in enumerate(legacy_headers, start=1):
            ws.cell(4, column, header)
        ws.cell(5, 16, " this week ")
        ws.cell(5, 18, "bllok")
        ws.cell(5, 20, "Move after customer reply")
        metadata = workbook.create_sheet("_PRIMEFLOW")
        metadata.sheet_state = "veryHidden"
        metadata["A1"] = "OPEN_TASKS_BASELINE_V1"
        metadata["B1"] = "2026-09-14"
        metadata["A2"] = "EXCEL ROW"
        metadata["B2"] = "TASK ID"
        metadata["A3"] = 5
        metadata["B3"] = str(task_id)
        content = io.BytesIO()
        workbook.save(content)
        content.seek(0)

        task = SimpleNamespace(id=task_id, department_id=None)
        db = _FakeSession([[task], []])
        user = SimpleNamespace(
            id=uuid.uuid4(),
            role=UserRole.ADMIN,
            department_id=None,
        )
        result = await import_open_tasks_baseline(
            file=UploadFile(filename="OPEN_TASKS.xlsx", file=content),
            db=db,
            user=user,
        )

        self.assertEqual(result, {"planning_week_start": "2026-09-14", "imported": 1})
        self.assertTrue(db.committed)
        self.assertEqual(len(db.added), 1)
        self.assertEqual(db.added[0].when_value, "THIS WEEK")
        self.assertEqual(db.added[0].status_value, "BLLOK")
        self.assertEqual(db.added[0].comment_value, "Move after customer reply")

    async def test_workbook_includes_system_tasks_and_keeps_task_metadata(self) -> None:
        task_id = uuid.uuid4()
        task = SimpleNamespace(
            id=task_id,
            title="Plan [[done]]customer[[/done]] report",
            description=None,
            project_id=None,
            department_id=None,
            assigned_to=None,
            assignees=[],
            ga_note_origin_id=None,
            plan_note_origin_id=None,
            system_template_origin_id=None,
            status="TODO",
            priority="NORMAL",
            finish_period="AM",
            start_date=datetime(2026, 9, 7, tzinfo=timezone.utc),
            due_date=datetime(2026, 9, 21, tzinfo=timezone.utc),
            created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            is_bllok=False,
            is_1h_report=True,
            is_r1=False,
            is_personal=False,
        )
        baseline = SimpleNamespace(
            task_id=task_id,
            when_value="THIS WEEK",
            status_value="1H",
            comment_value="Before planning",
        )
        system_task_values = vars(task).copy()
        system_task_id = uuid.uuid4()
        system_task_values.update(
            id=system_task_id,
            title="System task included in export",
            system_template_origin_id=uuid.uuid4(),
        )
        system_task = SimpleNamespace(**system_task_values)
        db = _FakeSession([[task, system_task], [], [], [baseline]])
        user = SimpleNamespace(
            id=uuid.uuid4(),
            role=UserRole.ADMIN,
            department_id=None,
            full_name="Test User",
            username="tester",
        )

        response = await export_open_tasks_xlsx(
            department_id=None,
            user_id=None,
            filter="all",
            status_filter="all",
            type_filter=None,
            search=None,
            this_week_start=date(2026, 9, 7),
            db=db,
            user=user,
        )
        content = b"".join([chunk async for chunk in response.body_iterator])
        workbook = load_workbook(io.BytesIO(content), data_only=False, rich_text=True)
        ws = workbook["OPEN TASKS"]

        self.assertEqual([ws.cell(4, column).value for column in range(17, 22)], OPEN_TASK_EXPORT_HEADERS[16:21])
        self.assertEqual(ws.cell(4, 2).value, "TASK ID")
        self.assertEqual(ws.cell(5, 2).value, str(task_id))
        title_value = ws.cell(5, 15).value
        self.assertIsInstance(title_value, CellRichText)
        self.assertEqual(str(title_value), "Plan customer report")
        self.assertEqual([part.text for part in title_value if part.font.strike], ["customer"])
        self.assertEqual(ws.max_row, 6)
        self.assertNotEqual(ws.cell(5, 4).value, "SYSTEM")
        self.assertEqual(ws.cell(6, 2).value, str(system_task_id))
        self.assertEqual(ws.cell(6, 4).value, "SYSTEM")
        self.assertEqual(ws.cell(6, 15).value, system_task.title)
        self.assertNotIn("tasks.system_template_origin_id IS NULL", str(db.statements[0]))
        self.assertEqual(
            [ws.cell(5, column).value for column in range(17, 22)],
            ["THIS WEEK", "1H", "NEXT WEEK", "1H", "Before planning"],
        )
        self.assertEqual(ws.cell(5, 19).fill.fgColor.rgb, "00FF0000")
        self.assertEqual(ws.cell(5, 19).font.color.rgb, "00FFFFFF")
        self.assertTrue(ws.cell(5, 19).font.bold)
        self.assertEqual(ws.cell(5, 20).fill.fill_type, None)
        self.assertEqual(ws.freeze_panes, "C5")
        self.assertEqual(workbook["_PRIMEFLOW"].sheet_state, "veryHidden")
        self.assertEqual(workbook["_PRIMEFLOW"]["B1"].value, "2026-09-14")
        self.assertEqual(workbook["_PRIMEFLOW"]["B3"].value, str(task_id))
        self.assertEqual(workbook["_PRIMEFLOW"]["B4"].value, str(system_task_id))


if __name__ == "__main__":
    unittest.main()
