import asyncio
import io
import json
import unittest
import uuid
from copy import deepcopy
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from zipfile import ZipFile
from lxml import etree as ET

QUOTE = 'PRIMEX will send the revised quotation by 6 November 2026. The client will approve the drawings.'


def sample():
    fact = lambda text: {'text': text, 'evidence': QUOTE}
    return {'project': None, 'location': None, 'objective': fact('Agree the quotation and drawing approvals.'),
        'attendees': [], 'items': [
            {'kind': 'ACTION', 'description': fact('Send the revised quotation.'), 'party': 'PRIMEX',
             'responsible': fact('PRIMEX'), 'deadline': fact('06.11.2026'), 'status': None},
            {'kind': 'ACTION', 'description': fact('Approve the drawings.'), 'party': 'CLIENT',
             'responsible': fact('Client'), 'deadline': None, 'status': None}]}


def source():
    return {'date': '2026-11-02', 'display_date': '02.11.2026', 'time': '10:00', 'transcript': QUOTE,
        'title': 'Quotation review', 'summary': 'Summary', 'decisions': [], 'proposed_actions': []}


class ProtocolProviderTests(unittest.IsolatedAsyncioTestCase):
    def test_evidence_and_party_guards(self):
        from app.services.recording_protocol import validate_content
        self.assertEqual(validate_content(sample(), QUOTE), sample())
        bad = sample()
        bad['items'][0]['deadline']['evidence'] = 'We agreed to deliver on Friday.'
        with self.assertRaises(ValueError): validate_content(bad, QUOTE)
        bad = sample()
        bad['items'][0]['responsible'] = None
        with self.assertRaises(ValueError): validate_content(bad, QUOTE)

    def test_both_templates_preserve_package_and_expand_rows(self):
        from app.services.recording_protocol import render_protocol, TEMPLATES, NS
        for language in ('en', 'de'):
            content = sample()
            content['attendees'] = [{'name': 'Jürgen Müller', 'party': 'CLIENT', 'evidence': QUOTE}]
            content['items'] = content['items'] * 7
            with ZipFile(io.BytesIO(render_protocol(content, source(), language))) as output, ZipFile(TEMPLATES / f'{language}.docx') as template:
                self.assertEqual(output.namelist(), template.namelist())
                for name in template.namelist():
                    if name not in ('word/document.xml', 'word/settings.xml'):
                        self.assertEqual(output.read(name), template.read(name), name)
                root = ET.fromstring(output.read('word/document.xml'))
                tables = root.findall('.//w:tbl', NS)
                self.assertEqual(len(tables[2].findall('w:tr', NS)), 15)
                text = ' '.join(root.xpath('//w:t/text()', namespaces=NS))
                self.assertIn('Jürgen Müller', text)
                self.assertIn('02.11.2026', text)
                self.assertNotIn(QUOTE, text)
                self.assertIn('Nicht festgelegt' if language == 'de' else 'Not specified', text)
                settings = ET.fromstring(output.read('word/settings.xml'))
                self.assertEqual(settings.find('w:view', NS).get('{'+NS['w']+'}val'), 'print')
                self.assertIn(b'primex_logo.png', output.read('word/header1.xml'))
                self.assertEqual(output.read('word/media/image1.png'), template.read('word/media/image1.png'))
                self.assertEqual(ET.tostring(root.find('.//w:sectPr', NS)),
                    ET.tostring(ET.fromstring(template.read('word/document.xml')).find('.//w:sectPr', NS)))

    async def test_generation_is_schema_validated_and_checkpoints_paid_calls(self):
        from app.services.recording_protocol import generate_content
        response = {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(sample())}]}],
            'usage': {'input_tokens': 100, 'output_tokens': 200}}
        cache = {}
        async def save(value): cache.update(value)
        with patch('app.services.recording_protocol.request', new=AsyncMock(return_value=response)) as request:
            result = await generate_content(source(), 'de', checkpoint=save)
            self.assertEqual(result, sample())
            self.assertEqual(await generate_content(source(), 'de', cache), sample())
            request.assert_awaited_once()
            payload = request.call_args.kwargs['json']
            self.assertFalse(payload['store'])
            self.assertTrue(payload['text']['format']['strict'])
            self.assertEqual(json.loads(payload['input'][1]['content'])['language'], 'de')
            self.assertEqual(next(iter(cache.values()))['usage']['input_tokens'], 100)

    async def test_long_meeting_reads_last_chunk_and_rejects_invented_facts(self):
        from app.services.recording_protocol import generate_content
        response = {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(sample())}]}]}
        long_source = source()
        long_source['transcript'] = (QUOTE + '\n') * 900 + 'END OF MEETING'
        with patch('app.services.recording_protocol.request', new=AsyncMock(return_value=response)) as request:
            await generate_content(long_source, 'en')
            self.assertGreater(request.await_count, 2)
            self.assertTrue(any('END OF MEETING' in call.kwargs['json']['input'][1]['content'] for call in request.call_args_list))
        bad = sample()
        bad['objective']['evidence'] = 'This sentence was never spoken.'
        response['output'][0]['content'][0]['text'] = json.dumps(bad)
        with patch('app.services.recording_protocol.request', new=AsyncMock(return_value=response)):
            with self.assertRaises(ValueError): await generate_content(source(), 'en')


from recording_test_support import TEST_URL
import test_recording_analysis_api as fixtures


@unittest.skipUnless(TEST_URL, 'Requires isolated primeflow_recorder_test database')
class ProtocolApiTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.AnalysisApiTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.AnalysisApiTests.tearDownClass.__func__)
    auth = fixtures.AnalysisApiTests.auth
    saved = fixtures.AnalysisApiTests.saved

    def seed(self, sid):
        from app.models.recording_analysis import RecordingAnalysis, RecordingTranscript
        async def run():
            async with self.session() as db:
                db.add(RecordingAnalysis(recording_id=uuid.UUID(sid), requested_by=uuid.UUID(self.fixture['owner']['id']),
                    status='READY', language='sq', total_segments=1, segments_done=1, summary='Summary', decisions=[]))
                await db.flush()
                db.add(RecordingTranscript(recording_id=uuid.UUID(sid), index=0, start_seconds=0, duration_seconds=60, text=QUOTE))
                await db.commit()
        asyncio.run(run())
        from app.api.routers.recording_protocol import router
        if not getattr(self.__class__, 'protocol_routes', False):
            self.app.include_router(router, prefix='/api/meeting-recordings')
            self.__class__.protocol_routes = True

    def test_authorization_idempotency_cached_binary_and_independent_languages(self):
        from app.jobs.recording_protocol import process_recording_protocols
        sid = self.saved()
        self.seed(sid)
        path = f'/api/meeting-recordings/{sid}/protocols'
        self.assertEqual(self.client.post(path, headers=self.auth('participant'), json={'language': 'en'}).status_code, 404)
        self.assertEqual(self.client.get(path, headers=self.auth('other')).status_code, 200)
        self.assertIn(self.client.get(path).status_code, (401, 403))
        self.assertEqual(self.client.post(path, headers=self.auth(), json={'language': 'sq'}).status_code, 422)
        for language in ('en', 'de'):
            for _ in range(2):
                self.assertEqual(self.client.post(path, headers=self.auth(), json={'language': language}).status_code, 202)
        self.assertEqual(len(self.client.get(path, headers=self.auth()).json()['protocols']), 2)
        self.assertEqual(self.client.get(path + '/en/download', headers=self.auth()).status_code, 409)
        with patch('app.jobs.recording_protocol.provider.generate_content', new=AsyncMock(return_value=sample())) as generate:
            for _ in range(3): asyncio.run(process_recording_protocols(self.session))
            self.assertEqual(generate.await_count, 2)
            first = self.client.get(path + '/en/download', headers=self.auth('participant'))
            second = self.client.get(path + '/en/download', headers=self.auth())
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.content, second.content)
            self.assertTrue(first.content.startswith(b'PK'))
            self.client.post(path, headers=self.auth(), json={'language': 'en'})
            asyncio.run(process_recording_protocols(self.session))
            self.assertEqual(generate.await_count, 2)
        self.assertEqual(self.client.get(path + '/en/download', headers=self.auth('other')).status_code, 200)
        self.assertIn(self.client.get(path + '/en/download').status_code, (401, 403))
        async def remove():
            from app.models.meeting_recording import MeetingRecording
            from app.jobs.recording_protocol import now
            async with self.session() as db:
                recording = await db.get(MeetingRecording, uuid.UUID(sid))
                recording.deleted_at = now()
                await db.commit()
        asyncio.run(remove())
        self.assertEqual(self.client.get(path + '/en/download', headers=self.auth()).status_code, 404)

    def test_failed_render_retries_without_repaying_ai_and_expired_lease_recovers(self):
        from app.jobs.recording_protocol import process_recording_protocols, now
        from app.models.recording_protocol import RecordingProtocol
        sid = self.saved()
        self.seed(sid)
        path = f'/api/meeting-recordings/{sid}/protocols'
        self.client.post(path, headers=self.auth(), json={'language': 'en'})
        with patch('app.jobs.recording_protocol.provider.generate_content', new=AsyncMock(return_value=sample())) as generate:
            with patch('app.jobs.recording_protocol.provider.render_protocol', side_effect=RuntimeError('mock render failure')):
                asyncio.run(process_recording_protocols(self.session))
            self.assertEqual(self.client.get(path, headers=self.auth()).json()['protocols'][0]['status'], 'FAILED')
            self.client.post(path, headers=self.auth(), json={'language': 'en'})
            async def expire():
                async with self.session() as db:
                    job = await db.get(RecordingProtocol, (uuid.UUID(sid), 'en'))
                    job.status, job.lease_token, job.lease_until = 'GENERATING', uuid.uuid4(), now() - timedelta(seconds=1)
                    await db.commit()
            asyncio.run(expire())
            asyncio.run(process_recording_protocols(self.session))
            generate.assert_awaited_once()
        self.assertEqual(self.client.get(path + '/en/download', headers=self.auth()).status_code, 200)
