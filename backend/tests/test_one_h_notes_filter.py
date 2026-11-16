import asyncio
import io
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import uuid
import zipfile

from app.api.routers import primeflow_1h_reports as api
from app.services.primeflow_report import (
    ReportUndiscussedNote, notes_only_document, render_docx, render_html, render_plain_text, render_png,
)
from tests.test_one_h_report_strike_counts import fresh_document


class NotesFilterTests(unittest.TestCase):
    def setUp(self):
        self.full, _, _ = fresh_document()
        self.full.undiscussed_notes = [ReportUndiscussedNote(content='Discuss only this note <PX>', author='EF')]

    def test_filtered_copy_preserves_full_report_and_exports_only_notes(self):
        before = self.full.model_dump()
        filtered = notes_only_document(self.full)
        self.assertEqual(self.full.model_dump(), before)
        self.assertEqual(filtered.undiscussed_notes, self.full.undiscussed_notes)
        self.assertEqual(filtered.content_count_label, '1 notes')
        self.assertIsNone(filtered.strike_total)
        plain = render_plain_text(filtered)
        html = render_html(filtered)
        word = zipfile.ZipFile(io.BytesIO(render_docx(filtered))).read('word/document.xml').decode()
        for output in (plain, html, word):
            self.assertIn('Discuss only this note', output)
            self.assertNotIn('Hourly task', output)
            self.assertNotIn('COLOR LEGEND', output)
            self.assertNotIn('PYETJET SHTESE', output)
        self.assertIn('&lt;PX&gt;', html)
        from PIL import ImageDraw
        original_text = ImageDraw.ImageDraw.text
        drawn = []

        def capture(draw, xy, text, *args, **kwargs):
            drawn.append(str(text))
            return original_text(draw, xy, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, 'text', capture):
            png = render_png(filtered)
        self.assertTrue(png.startswith(b'\x89PNG'))
        self.assertIn('Discuss only this note <PX>', '\n'.join(drawn))
        self.assertNotIn('Hourly task', '\n'.join(drawn))
        self.assertNotIn('COLOR LEGEND', drawn)

    def test_preview_and_download_formats_honor_notes_only_without_ga_supplements(self):
        for format in ('json', 'docx', 'png', 'txt'):
            with self.subTest(format=format), \
                 patch.object(api, '_recipient_map', AsyncMock(return_value={})), \
                 patch.object(api, 'load_common_view', AsyncMock(return_value={})), \
                 patch.object(api, 'generate_fresh', AsyncMock(return_value=self.full)), \
                 patch.object(api, 'render_ga_recipient_email_html', AsyncMock()) as ga:
                response = asyncio.run(api.preview(api.PreviewRequest(
                    report_date=self.full.report_date, report_slot='11:00', format=format, notes_only=True,
                ), AsyncMock(), SimpleNamespace()))
                ga.assert_not_awaited()
                if format == 'json':
                    self.assertEqual(response['note_count'], 1)
                    self.assertEqual(response['task_count'], 0)
                    self.assertNotIn('Hourly task', response['html'])
                else:
                    self.assertIn('_Notes.', response.headers['content-disposition'])

    def test_unfiltered_preview_still_uses_full_ga_email_and_supplies_notes_preview(self):
        with patch.object(api, '_recipient_map', AsyncMock(return_value={})), \
             patch.object(api, 'load_common_view', AsyncMock(return_value={})), \
             patch.object(api, 'generate_fresh', AsyncMock(return_value=self.full)), \
             patch.object(api, 'render_ga_recipient_email_html', AsyncMock(return_value='FULL GA REPORT')):
            result = asyncio.run(api.preview(api.PreviewRequest(
                report_date=self.full.report_date, report_slot='11:00'), AsyncMock(), SimpleNamespace()))
        self.assertEqual(result['html'], 'FULL GA REPORT')
        self.assertGreater(result['task_count'], 0)
        self.assertNotIn('Hourly task', result['notes_html'])
        self.assertIn('Discuss only this note', result['notes_html'])

    def test_send_ignores_preview_filter_and_keeps_full_delivery(self):
        delivery = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4(), status='SENT', gmail_message_id='sent'))
        with patch.object(api, '_recipient_map', AsyncMock(return_value={})), \
             patch.object(api, 'deliver_report', delivery), patch.object(api, 'add_audit_log'), \
             patch.object(api, '_run', return_value={'status': 'SENT'}):
            asyncio.run(api.manual_send(api.SendRequest(
                report_date=self.full.report_date, report_slot='11:00', reason='manual report', notes_only=True,
            ), AsyncMock(), SimpleNamespace(id=uuid.uuid4())))
        self.assertNotIn('notes_only', delivery.call_args.kwargs)


if __name__ == '__main__':
    unittest.main()
