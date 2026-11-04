"""Spoken Albanian preserves task identity and numeric meaning."""
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.mira_host_speech import speech_text
from app.services import mira_host as host
from app.models.mira_host import Mira1HMeeting
from tests.test_mira_host_service import DAY, item, payload


class SpeechTests(unittest.TestCase):
    def test_technical_acronyms_use_albanian_letter_names(self):
        self.assertEqual(speech_text('API, UI/UX, HTML/CSS; SQL CSV JSON XML URL HTTP HTTPS'),
            'a pë i, u i/u xë, hë të më lë/cë së së; së që lë cë së vë jë së o në xë më lë u rë lë hë të të pë hë të të pë së')
        self.assertEqual(speech_text('EF: PDF WFE', ['EF']), 'e fë: pë dë fë dubël vë fë e')

    def test_percentages_keep_whole_and_decimal_values(self):
        self.assertEqual(speech_text('Progresi 0%, 50 % dhe 12.5%; mbetet 37,5%.'),
            'Progresi 0 për qind, 50 për qind dhe 12 presje 5 për qind; mbetet 37 presje 5 për qind.')

    def test_identifiers_names_and_unknown_words_are_preserved(self):
        text = ('Visual Studio, Primex, OFERTA, GENT, WKF, API_KEY; '
                'https://primex.test/API/PDF?rate=50% api@PDF.test oferta.PDF '
                'src/API.ts C:\\work\\PDF.json ./API/PDF.json /API/PDF; v2.1 3.12.4')
        self.assertEqual(speech_text(text), text)

    def test_speech_preparation_is_idempotent_and_keeps_source_task(self):
        row = item('EF', '10:00', 'API OFERTA 50%', rank=0)
        original = dict(row)
        line = host.task_line(row)
        self.assertEqual(row, original)
        self.assertIn('API OFERTA 50%', line['title'])
        self.assertEqual(line['spoken'], 'API OFERTA 50%')
        self.assertEqual(line['read_aloud'], 'a pë i OFERTA 50 për qind')
        self.assertEqual(speech_text(line['read_aloud']), line['read_aloud'])
        self.assertEqual(line['task_id'], str(row['task_id']))

    def test_status_hints_are_albanian_without_claiming_no_work_was_done(self):
        expected = {'TODO': 'pa progres të regjistruar', 'WAITING_CLIENT': 'në pritje të klientit',
                    'WAITING_CONFIRMATION': 'në pritje të konfirmimit', 'IN_PROGRESS': 'në proces', 'DONE': 'kryer'}
        for status, label in expected.items():
            with self.subTest(status=status):
                line = host.task_line(item('EF', '10:00', 'OFERTA', rank=0, status=status))
                self.assertEqual(line['status'], status)
                self.assertEqual(line['status_label'], label)


class NoteSpeechTests(unittest.IsolatedAsyncioTestCase):
    async def test_note_budget_does_not_cut_through_a_pronunciation_or_percentage(self):
        original = 'API ' * 9 + '50%'
        note = {'note_id': str(uuid.uuid4()), 'number': 1, 'text': original}
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='10:00', status='GA_PHASE')
        with patch.object(host, 'common_payload', AsyncMock(return_value=payload([]))), \
             patch.object(host, 'open_notes', AsyncMock(return_value=[note])):
            out = await host.run_tool(SimpleNamespace(add=lambda _: None), meeting, 'list_new_px_notes', {})
        self.assertEqual(out['notes'][0]['text'], original)
        self.assertEqual(out['notes'][0]['read_aloud'], ' '.join(['a pë i'] * 9))
        self.assertLessEqual(len(out['notes'][0]['read_aloud'].split()), 28)
