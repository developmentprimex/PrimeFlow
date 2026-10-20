import unittest
import io
import wave
from unittest.mock import AsyncMock, patch


class RecordingAnalysisProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_segment_plan_bounds_multi_hour_recording(self):
        from app.services.recording_analysis_provider import segment_plan
        plan = segment_plan(43200)
        self.assertEqual(len(plan), 144)
        self.assertEqual(plan[-1], (42900, 300))
        with self.assertRaises(ValueError):
            segment_plan(float('nan'))

    async def test_actions_require_verbatim_transcript_evidence(self):
        from app.services.recording_analysis_provider import validate_notes
        note = {'summary': 'Takim', 'decisions': [], 'actions': [
            {'title': 'Dërgo raportin', 'description': '', 'evidence': 'Unë do ta dërgoj raportin.',
             'assignee_text': None, 'deadline_text': None}]}
        self.assertEqual(len(validate_notes(note, 'Unë do ta dërgoj raportin.')['actions']), 1)
        with self.assertRaises(ValueError):
            validate_notes(note, 'Nuk kemi veprime.')

    async def test_provider_failure_never_returns_empty_success(self):
        from app.services.recording_analysis_provider import extract_notes
        with patch('app.services.recording_analysis_provider.request', new=AsyncMock(return_value={'output': []})):
            with self.assertRaises(ValueError):
                await extract_notes('Raporti duhet dërguar.')

    async def test_silence_does_not_call_provider_and_invalid_format_rejected(self):
        from app.services.recording_analysis_provider import transcribe
        audio = io.BytesIO()
        with wave.open(audio, 'wb') as out:
            out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000)
            out.writeframes(bytes(32000))
        with patch('app.services.recording_analysis_provider.request', new=AsyncMock()) as request:
            self.assertEqual(await transcribe(audio.getvalue(), 'sq'), '')
            request.assert_not_awaited()

    async def test_structured_output_uses_no_tools_and_disables_storage(self):
        from app.services.recording_analysis_provider import extract_notes
        import json
        value = {'summary': 'Bisedë', 'decisions': [], 'actions': []}
        response = {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(value)}]}]}
        with patch('app.services.recording_analysis_provider.request', new=AsyncMock(return_value=response)) as request:
            self.assertEqual(await extract_notes('Bisedë pa veprime.'), value)
            payload = request.call_args.kwargs['json']
            self.assertFalse(payload['store'])
            self.assertNotIn('tools', payload)
            self.assertTrue(payload['text']['format']['strict'])


if __name__ == '__main__':
    unittest.main()
