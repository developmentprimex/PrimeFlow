import io
import unittest
from types import SimpleNamespace

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from app.api.routers.exports import AllTasksReportExportIn, export_all_tasks_report_xlsx
from app.models.enums import UserRole


class TestAllTasksReportExport(unittest.IsolatedAsyncioTestCase):
    async def test_bz_column_is_compact_only_for_finance(self):
        for title, width in (("ALL FINANCE TASK REPORT", 10), ("ALL TASKS REPORT", 14)):
            with self.subTest(title=title):
                response = await export_all_tasks_report_xlsx(
                    AllTasksReportExportIn(title=title, rows=[{"bzMe": "GA, HS", "kohaBz": "13:30"}]),
                    user=SimpleNamespace(role=UserRole.ADMIN, full_name="HS", username="hs"),
                )
                sheet = load_workbook(io.BytesIO(b"".join([chunk async for chunk in response.body_iterator]))).active
                column = next(cell.column for cell in sheet[4] if cell.value == "BZ ME")
                self.assertEqual(sheet.column_dimensions[get_column_letter(column)].width, width)
                self.assertEqual(sheet.cell(5, column).value, "GA, HS")
                self.assertEqual(sheet.cell(5, column + 1).value, "13:30")

    async def test_finance_export_removes_markup_and_preserves_text_and_breaks(self):
        for frequency in (None, "3M"):
            with self.subTest(frequency=frequency):
                payload = AllTasksReportExportIn(
                    title="ALL FINANCE TASK REPORT",
                    rows=[{
                        "title": "[[added]]HS:[[/added]] [[ADDED]]BORXH HC[[/ADDED]]",
                        "description": "<p>Muaji &amp; raporti</p>[[done]]Drafti[[/done]]<br>GA<br/>MAX<BR />25",
                        "details": "&lt;br&gt;[[added]]REGJ: 0[[/added]]\r\n<div>PATH: 0</div>",
                        "frequency": frequency,
                        "department": "FIN",
                        "status": "TODO",
                        "userInitials": "HS",
                    }, {}],
                )
                response = await export_all_tasks_report_xlsx(
                    payload,
                    user=SimpleNamespace(role=UserRole.ADMIN, full_name="HS", username="hs"),
                )
                content = b"".join([chunk async for chunk in response.body_iterator])
                worksheet = load_workbook(io.BytesIO(content)).active
                columns = {cell.value: cell.column for cell in worksheet[4]}
                expected = {
                    "TITULLI": "HS: BORXH HC",
                    "PERSHKRIMI": "Muaji & raporti\nDrafti\nGA\nMAX\n25",
                    "REGJ/PATH/CHECKLISTA/TRAINING/GROUP": "REGJ: 0\nPATH: 0",
                    "DEP": "FIN",
                    "STATUS": "TODO",
                    "USER": "HS",
                }
                for header, value in expected.items():
                    cell = worksheet.cell(5, columns[header])
                    self.assertEqual(cell.value, value)
                    self.assertTrue(cell.alignment.wrap_text)
                self.assertEqual(worksheet.cell(6, columns["TITULLI"]).value, "-")
                self.assertIsNone(worksheet.cell(6, columns["PERSHKRIMI"]).value)
                self.assertEqual("F" in columns, frequency is not None)


from tests.report_attendance_fixtures import present_report_population
