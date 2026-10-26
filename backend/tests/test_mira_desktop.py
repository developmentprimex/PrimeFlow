import io
import os
import wave
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@127.0.0.1/primeflow_test')
os.environ.setdefault('JWT_SECRET', 'desktop-test-secret')
from fastapi import HTTPException
from app.services import mira_desktop as service


def wav(frames=480, channels=2):
    out = io.BytesIO()
    with wave.open(out, 'wb') as w:
        w.setnchannels(channels); w.setsampwidth(2); w.setframerate(48000)
        w.writeframes(b'\x01\x00' * channels * frames)
    return out.getvalue()


class DesktopTests(unittest.IsolatedAsyncioTestCase):
    def test_wav_bounds_and_duration_are_enforced(self):
        self.assertEqual(service.validate_audio(wav(), 0, 10), wav())
        for data, start, end in [(wav(), 0, 20), (wav(channels=1), 0, 10),
                                 (wav(480001), 0, 10000), (wav(), -1, 9),
                                 (wav(), 14400000, 14400010), (wav()[:-1], 0, 10)]:
            with self.assertRaises(HTTPException): service.validate_audio(data, start, end)

    async def test_summary_overrides_speaker_references_and_caches(self):
        payloads = []
        async def cached(payload, cache, checkpoint, parse):
            payloads.append(payload)
            return 'Përmbledhja'
        with patch.object(service.provider, 'cached', cached):
            result = await service.summarize('Call', [{'sequence': 0, 'start_ms': 0,
                'end_ms': 10, 'transcript': 'Po'}], {}, None)
        self.assertIn('Përmbledhja', result)
        self.assertIn(service.NO_SPEAKERS, payloads[0]['input'][0]['content'])
        self.assertNotIn('speaker', payloads[0]['input'][1]['content'])

    async def test_silence_skips_provider(self):
        with patch.object(service.provider, 'cached', AsyncMock()) as call:
            self.assertEqual(await service.summarize('Call', [], {}, None), '')
            call.assert_not_awaited()
