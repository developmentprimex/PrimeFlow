import re
import unittest
import uuid
from datetime import date, datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image, ImageDraw

from app.services import one_h_ga_attachments as service
from app.services.ga_time_table import DEFAULT_GA_TIME_TABLE_ROWS


def result(values):
    response = MagicMock()
    response.scalars.return_value.all.return_value = values
    return response


def fixture():
    meetings = [SimpleNamespace(
        id=uuid.uuid4(), title=title, meeting_type=kind,
        starts_at=datetime(2026, 10, 26, 8, minute), recurrence_type="weekly",
        recurrence_days_of_week=[0, 1, 2], calendar_categories=[],
        calendar_imported=False, microsoft_event_id=None, calendar_sync_status="active",
        paired_external_meeting_id=None, pre_external_meeting_id=None,
    ) for title, kind, minute in (("External recurring", "external", 5), ("Internal recurring", "internal", 30))]
    statuses = [SimpleNamespace(meeting_id=meetings[index].id, occurrence_date=day, status=status)
                for index, day, status in (
                    (0, date(2026, 10, 26), "canceled"), (0, date(2026, 10, 27), "held"),
                    (1, date(2026, 10, 26), "held"), (1, date(2026, 10, 27), "canceled"),
                    (1, date(2026, 10, 28), "planned"),
                )]
    row = next(row for row in DEFAULT_GA_TIME_TABLE_ROWS if row.start_time.hour == 8)
    return meetings, statuses, row


class GaTimetableMeetingStatusTests(unittest.IsolatedAsyncioTestCase):
    async def render(self, renderer):
        meetings, statuses, row = fixture()
        db = SimpleNamespace(execute=AsyncMock(side_effect=[result(meetings), result(statuses)]))
        with patch.object(service, "get_ga_time_table_rows", AsyncMock(return_value=[row])), \
             patch.object(service, "_ga_user", AsyncMock(return_value=None)):
            rendered = await renderer(db, date(2026, 10, 28))
        status_query = db.execute.await_args_list[1].args[0]
        self.assertTrue(status_query.get_execution_options()["populate_existing"])
        self.assertIn(date(2026, 10, 26), status_query.compile().params.values())
        self.assertIn(date(2026, 10, 30), status_query.compile().params.values())
        return rendered

    async def test_email_and_report_preview_use_date_scoped_status_and_cancellations_last(self):
        rendered = await self.render(service.render_ga_time_table_html)
        body = re.search(r"<tbody>(.*?)</tbody>", rendered, re.S).group(1)
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", body, re.S)
        monday, tuesday, wednesday = cells[3:6]
        self.assertLess(monday.index("Internal recurring"), monday.index("External recurring"))
        self.assertLess(tuesday.index("External recurring"), tuesday.index("Internal recurring"))
        for cell in (monday, tuesday):
            self.assertEqual(cell.count('data-meeting-status="held"'), 1)
            self.assertEqual(cell.count('data-meeting-status="canceled"'), 1)
            self.assertIn(">Mbajtur</span>", cell)
            self.assertIn(">Anuluar X</span>", cell)
            self.assertEqual(cell.count('data-meeting-canceled="true"'), 1)
        self.assertIn("External recurring", wednesday)
        self.assertIn("Internal recurring", wednesday)
        self.assertNotIn("data-meeting-status", wednesday)
        self.assertNotIn("data-meeting-canceled", wednesday)
        self.assertNotIn("data-meeting-status", cells[6] + cells[7])

    async def test_png_attachment_draws_status_labels_and_x_on_canceled_titles(self):
        with patch.object(ImageDraw.ImageDraw, "text", autospec=True, side_effect=ImageDraw.ImageDraw.text) as draw_text, \
             patch.object(ImageDraw.ImageDraw, "line", autospec=True, side_effect=ImageDraw.ImageDraw.line) as draw_line:
            png = await self.render(service.render_ga_time_table_png)
        image = Image.open(BytesIO(png))
        self.assertEqual(image.format, "PNG")
        labels = [call.args[2] for call in draw_text.call_args_list]
        self.assertEqual(labels.count("Mbajtur"), 2)
        self.assertEqual(labels.count("Anuluar X"), 2)
        self.assertEqual(len([call for call in draw_line.call_args_list if call.kwargs.get("fill") == "#DB8BA6"]), 4)

    async def test_new_generation_reloads_status_changes_and_reset(self):
        meetings, _, row = fixture()
        statuses = [SimpleNamespace(meeting_id=meetings[0].id, occurrence_date=date(2026, 10, 26), status="canceled")]
        held = [SimpleNamespace(meeting_id=meetings[0].id, occurrence_date=date(2026, 10, 26), status="held")]
        db = SimpleNamespace(execute=AsyncMock(side_effect=[
            result(meetings), result(statuses), result(meetings), result(held), result(meetings), result([]),
        ]))
        with patch.object(service, "get_ga_time_table_rows", AsyncMock(return_value=[row])), \
             patch.object(service, "_ga_user", AsyncMock(return_value=None)):
            canceled = await service.render_ga_time_table_html(db, date(2026, 10, 28))
            held = await service.render_ga_time_table_html(db, date(2026, 10, 28))
            reset = await service.render_ga_time_table_html(db, date(2026, 10, 28))
        self.assertIn("Anuluar X", canceled)
        self.assertIn("Mbajtur", held)
        self.assertNotIn("Anuluar", held)
        self.assertNotIn("data-meeting-status", reset)
        self.assertNotIn("data-meeting-canceled", reset)
