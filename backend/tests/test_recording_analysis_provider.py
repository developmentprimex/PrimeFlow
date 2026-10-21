import unittest
import io
import json
import math
import wave
from datetime import date
from unittest.mock import AsyncMock, patch


def wav_bytes(samples):
    audio = io.BytesIO()
    with wave.open(audio, 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000)
        out.writeframes(samples)
    return audio.getvalue()


def tone(seconds, amplitude):
    import array
    values = array.array('h', (int(amplitude * math.sin(i / 8)) for i in range(int(16000 * seconds))))
    return values.tobytes()


def response(value):
    return {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(value, ensure_ascii=False)}]}]}


def action(**overrides):
    return {'title': 'Dërgo ofertën', 'description': '', 'evidence': 'Unë do ta dërgoj ofertën nesër.',
            'assignee_text': None, 'deadline_text': None, 'due_date': None, **overrides}


class RecordingAnalysisProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_segment_plan_bounds_multi_hour_recording(self):
        from app.services.recording_analysis_provider import segment_plan
        plan = segment_plan(43200)
        self.assertEqual(len(plan), 144)
        self.assertEqual(plan[-1], (42900, 300))
        with self.assertRaises(ValueError):
            segment_plan(float('nan'))

    async def test_evidence_matches_despite_punctuation_and_diacritics(self):
        from app.services.recording_analysis_provider import validate_notes
        transcript = 'Mirë. Une do ta dergoj oferten neser, pa problem.'
        result = validate_notes({'summary': 'Takim', 'decisions': [], 'actions': [action()]}, transcript)
        self.assertEqual(len(result['actions']), 1)

    async def test_unsupported_action_is_dropped_not_fatal(self):
        from app.services.recording_analysis_provider import validate_notes
        note = {'summary': 'Takim', 'decisions': ['Vendim'], 'actions': [
            action(), action(title='Thirr klientin', evidence='Thirre klientin sot.')]}
        result = validate_notes(note, 'Unë do ta dërgoj ofertën nesër.')
        self.assertEqual([a['title'] for a in result['actions']], ['Dërgo ofertën'])
        self.assertEqual(result['decisions'], ['Vendim'])

    async def test_elided_evidence_and_near_duplicate_titles(self):
        from app.services.recording_analysis_provider import validate_notes
        transcript = 'Arben, merre ti klientin e ri. Pastaj flasim. E dërgon ti ofertën deri të premten.'
        note = {'summary': '', 'decisions': [], 'actions': [
            action(title='Dërgo ofertën te klienti', evidence='Arben, merre ti klientin … deri të premten'),
            action(title='Dërgo oferten te klienti!', evidence='E dërgon ti ofertën deri të premten.')]}
        self.assertEqual(len(validate_notes(note, transcript)['actions']), 1)

    async def test_due_date_parsed_and_bounded(self):
        from app.services.recording_analysis_provider import validate_notes
        transcript = 'Unë do ta dërgoj ofertën nesër.'
        day = date(2026, 10, 20)
        good = validate_notes({'summary': '', 'decisions': [], 'actions': [action(due_date='2026-10-21')]}, transcript, day)
        self.assertEqual(good['actions'][0]['due_date'], date(2026, 10, 21))
        for bad in ['2020-01-01', 'nesër', None]:
            result = validate_notes({'summary': '', 'decisions': [], 'actions': [action(due_date=bad)]}, transcript, day)
            self.assertIsNone(result['actions'][0]['due_date'])

    async def test_malformed_response_fails(self):
        from app.services.recording_analysis_provider import validate_notes
        with self.assertRaises(ValueError):
            validate_notes({'summary': 'x'}, 'tekst')

    async def test_match_person(self):
        from app.services.recording_analysis_provider import match_person
        people = [('a', 'Arbën Krasniqi'), ('b', 'Blerta Gashi'), ('c', 'Arbër Hoxha')]
        self.assertEqual(match_person('Arben Krasniqi', people), 'a')
        self.assertEqual(match_person('blerta', people), 'b')
        self.assertIsNone(match_person('Dritoni', people))
        self.assertIsNone(match_person(None, people))

    async def test_evidence_segment_spans_boundary(self):
        from app.services.recording_analysis_provider import evidence_segment
        segments = [{'index': 0, 'text': 'Fillimi. Do ta'}, {'index': 1, 'text': 'dërgoj raportin. Fund.'}]
        self.assertEqual(evidence_segment('Do ta dërgoj raportin', segments), 0)
        self.assertEqual(evidence_segment('Fund', segments), 1)

    async def test_silence_and_quiet_noise_do_not_call_provider(self):
        from app.services.recording_analysis_provider import transcribe
        with patch('app.services.recording_analysis_provider.request', new=AsyncMock()) as request:
            self.assertEqual(await transcribe(wav_bytes(bytes(32000)), 'sq'), '')
            self.assertEqual(await transcribe(wav_bytes(tone(3, 40)), 'sq'), '')
            request.assert_not_awaited()

    async def test_transcription_request_uses_language_vocabulary_and_previous_text(self):
        from app.services.recording_analysis_provider import transcribe
        with patch('app.services.recording_analysis_provider.request', new=AsyncMock(return_value={'text': 'Mirëdita. Faleminderit që shikuat!'})) as request:
            text = await transcribe(wav_bytes(tone(3, 8000)), 'sq', vocabulary=['Arbën Krasniqi', 'PrimeFlow'], previous='fundi i pjesës')
        self.assertEqual(text, 'Mirëdita.')
        data = request.call_args.kwargs['data']
        self.assertNotIn('language', data)
        self.assertNotIn('languages[]', data)
        self.assertIn('Arbën Krasniqi', data['prompt'])
        self.assertIn('fundi i pjesës', data['prompt'])
        self.assertGreaterEqual(request.call_args.kwargs['timeout'], 120)

    async def test_auto_language_sends_no_language_code(self):
        from app.services.recording_analysis_provider import transcribe
        with patch('app.services.recording_analysis_provider.request', new=AsyncMock(return_value={'text': 'Hello, mirëdita.'})) as request:
            await transcribe(wav_bytes(tone(3, 8000)), 'auto')
        self.assertNotIn('language', request.call_args.kwargs['data'])
        self.assertNotIn('languages[]', request.call_args.kwargs['data'])

    async def test_gpt_transcribe_uses_plural_language_hint(self):
        from app.services import recording_analysis_provider as provider
        with patch.object(provider.settings, 'RECORDING_TRANSCRIBE_MODEL', 'gpt-transcribe'), \
                patch.object(provider.settings, 'RECORDING_TRANSCRIBE_LANGUAGE_HINT', True), \
                patch.object(provider, 'request', new=AsyncMock(return_value={'text': 'Hello.'})) as request:
            await provider.transcribe(wav_bytes(tone(3, 8000)), 'en')
        data = request.call_args.kwargs['data']
        self.assertEqual(data['languages[]'], ['en'])
        self.assertNotIn('language', data)

    async def test_legacy_transcription_keeps_singular_language_hint(self):
        from app.services import recording_analysis_provider as provider
        with patch.object(provider.settings, 'RECORDING_TRANSCRIBE_MODEL', 'whisper-1'), \
                patch.object(provider.settings, 'RECORDING_TRANSCRIBE_LANGUAGE_HINT', True), \
                patch.object(provider, 'request', new=AsyncMock(return_value={'text': 'Hallo.'})) as request:
            await provider.transcribe(wav_bytes(tone(3, 8000)), 'de')
        self.assertEqual(request.call_args.kwargs['data']['language'], 'de')

    async def test_transient_provider_failure_is_retried(self):
        from app.services.recording_analysis_provider import transcribe
        provider = AsyncMock(side_effect=[ValueError('meeting_provider_failed'), {'text': 'Po.'}])
        with patch('app.services.recording_analysis_provider.request', new=provider), \
                patch('app.services.recording_analysis_provider.RETRY_DELAYS', (0, 0)):
            self.assertEqual(await transcribe(wav_bytes(tone(3, 8000)), 'sq'), 'Po.')
        self.assertEqual(provider.await_count, 2)

    async def test_analysis_uses_whole_meeting_context_and_strict_schema(self):
        from app.services.recording_analysis_provider import analyze_meeting
        segments = [{'index': 0, 'start_seconds': 0, 'duration_seconds': 300, 'text': 'Unë do ta dërgoj ofertën nesër.'}]
        value = {'summary': '**Përmbledhja:** Oferta.', 'decisions': [], 'actions': [action(due_date='2026-10-21')]}
        with patch('app.services.recording_analysis_provider.request', new=AsyncMock(return_value=response(value))) as request:
            result = await analyze_meeting('Takim', segments, meeting_day=date(2026, 10, 20), participants=['Arbën Krasniqi'])
        payload = request.call_args.kwargs['json']
        self.assertFalse(payload['store'])
        self.assertNotIn('tools', payload)
        self.assertTrue(payload['text']['format']['strict'])
        content = json.loads(payload['input'][1]['content'])
        self.assertEqual(content['meeting_date'], '2026-10-20')
        self.assertEqual(content['participants'], ['Arbën Krasniqi'])
        self.assertIn('[00:00:00–00:05:00]', content['content'])
        self.assertEqual(result['actions'][0]['due_date'], date(2026, 10, 21))

    async def test_long_meeting_is_reduced_in_parts_and_checkpointed(self):
        from app.services import recording_analysis_provider as provider
        segments = [{'index': i, 'start_seconds': i * 300, 'duration_seconds': 300, 'text': f'Pjesa {i}. ' + 'fjalë ' * 2000}
                    for i in range(12)]
        segments[3]['text'] += ' Unë do ta dërgoj ofertën nesër.'
        part = {'summary': 'shënime', 'decisions': [], 'actions': []}
        final = {'summary': 'Fund', 'decisions': ['U vendos'], 'actions': [action()]}
        checkpoint = AsyncMock()
        calls = [response(part)] * 3 + [response(final)]
        with patch.object(provider, 'request', new=AsyncMock(side_effect=calls)) as request:
            result = await provider.analyze_meeting('Takim', segments, meeting_day=date(2026, 10, 20), checkpoint=checkpoint)
        self.assertEqual(request.await_count, 4)
        self.assertEqual(checkpoint.await_count, 4)
        self.assertEqual(len(result['actions']), 1)
        self.assertEqual(provider.evidence_segment(result['actions'][0]['evidence'], segments), 3)

    async def test_empty_transcript_is_rejected(self):
        from app.services.recording_analysis_provider import analyze_meeting
        with self.assertRaises(ValueError):
            await analyze_meeting('Takim', [{'index': 0, 'start_seconds': 0, 'duration_seconds': 300, 'text': ' '}], meeting_day=date.today())

    async def test_provider_failure_never_returns_empty_success(self):
        from app.services import recording_analysis_provider as provider
        segments = [{'index': 0, 'start_seconds': 0, 'duration_seconds': 300, 'text': 'Raporti duhet dërguar.'}]
        with patch.object(provider, 'request', new=AsyncMock(return_value={'output': []})):
            with self.assertRaises(ValueError):
                await provider.analyze_meeting('Takim', segments, meeting_day=date.today())


if __name__ == '__main__':
    unittest.main()
