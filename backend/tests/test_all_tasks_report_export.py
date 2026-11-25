import io
import unittest
from types import SimpleNamespace

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from app.api.routers.exports import (
    AllTasksReportExportIn, CommonViewExportIn, export_all_tasks_report_xlsx, export_common_view_xlsx,
)
from app.models.enums import UserRole


class TestAllTasksReportExport(unittest.IsolatedAsyncioTestCase):
    async def test_common_view_distinguishes_the_waiting_rows(self):
        response = await export_common_view_xlsx(
            CommonViewExportIn(
                title="Common View",
                columns=["NR", "LLOJI", "MON"],
                rows=[["1", "WFE", "Client reply"], ["2", "WFC INT", "[CON: HS] Internal approval"]],
            ),
            user=SimpleNamespace(role=UserRole.ADMIN, full_name="HS", username="hs"),
        )
        sheet = load_workbook(io.BytesIO(b"".join([chunk async for chunk in response.body_iterator]))).active
        self.assertEqual(sheet["B5"].fill.fgColor.rgb, "00E2C15B")
        self.assertEqual(sheet["B6"].fill.fgColor.rgb, "0099F6E4")
        self.assertEqual(sheet["C6"].value, "[CON: HS] Internal approval")

    async def test_finance_places_user_after_compact_bz_column(self):
        for title, width in (("ALL FINANCE TASK REPORT", 10), ("ALL TASKS REPORT", 14)):
            with self.subTest(title=title):
                response = await export_all_tasks_report_xlsx(
                    AllTasksReportExportIn(
                        title=title,
                        rows=[{"bzMe": "GA, HS", "kohaBz": "13:30", "userInitials": "OH, HS", "status": "WAITING_CONFIRMATION"}],
                    ),
                    user=SimpleNamespace(role=UserRole.ADMIN, full_name="HS", username="hs"),
                )
                sheet = load_workbook(io.BytesIO(b"".join([chunk async for chunk in response.body_iterator]))).active
                headers = [cell.value for cell in sheet[4]]
                column = headers.index("BZ ME") + 1
                self.assertEqual(sheet.column_dimensions[get_column_letter(column)].width, width)
                self.assertEqual(sheet.cell(5, column).value, "GA, HS")
                status_cell = sheet.cell(5, headers.index("STATUS") + 1)
                self.assertEqual(status_cell.value, "WFC INT")
                self.assertEqual(status_cell.fill.fgColor.rgb, "0099F6E4")
                if title == "ALL FINANCE TASK REPORT":
                    self.assertEqual(headers[column:column + 2], ["USER", "KOHA BZ"])
                    self.assertEqual(sheet.cell(5, column + 1).value, "OH, HS")
                    self.assertEqual(sheet.cell(5, column + 2).value, "13:30")
                else:
                    self.assertEqual(headers[column], "KOHA BZ")
                    self.assertEqual(headers[-1], "USER")
                    self.assertEqual(sheet.cell(5, column + 1).value, "13:30")
                    self.assertEqual(sheet.cell(5, len(headers)).value, "OH, HS")

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
