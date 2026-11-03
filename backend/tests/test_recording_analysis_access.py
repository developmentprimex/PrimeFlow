"""Analysis start/retry permissions without external providers or a database."""
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from app.api.routers import recording_analysis as api


class RecordingAnalysisAccessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.viewer = SimpleNamespace(id=uuid.uuid4())
        self.recording = SimpleNamespace(id=uuid.uuid4(), created_by=uuid.uuid4(), status='READY', duration_seconds=96)
        self.db = SimpleNamespace(get=AsyncMock(return_value=None), add=Mock(), commit=AsyncMock())
        self.payload = api.AnalysisStart(consent_acknowledged=True, language='sq')

    async def start(self):
        with patch.object(api, 'load_recording', new=AsyncMock(return_value=self.recording)) as load, \
                patch.object(api, 'available', return_value=True), patch.object(api, 'audit') as audit:
            result = await api.start_analysis(self.recording.id, self.payload, self.db, self.viewer)
            load.assert_awaited_once_with(self.db, self.recording.id, self.viewer, lock=True)
            return result, audit

    async def test_viewer_can_start_and_requester_is_recorded(self):
        await self.start()
        job = self.db.add.call_args.args[0]
        self.assertEqual(job.recording_id, self.recording.id)
        self.assertEqual(job.requested_by, self.viewer.id)
        self.db.commit.assert_awaited_once()

    async def test_second_viewer_reuses_active_job(self):
        self.db.get.return_value = SimpleNamespace(status='QUEUED')
        result, audit = await self.start()
        self.assertEqual(result, {'status': 'QUEUED'})
        self.db.add.assert_not_called()
        audit.assert_not_called()

    async def test_viewer_can_retry_failed_job(self):
        job = SimpleNamespace(status='FAILED', language='sq', lease_until=None, attempts=3)
        self.db.get.return_value = job
        result, _ = await self.start()
        self.assertEqual(result, {'status': 'QUEUED'})
        self.assertEqual(job.attempts, 0)
        self.db.commit.assert_awaited_once()

    async def test_missing_or_inaccessible_recording_is_rejected(self):
        with patch.object(api, 'load_recording', new=AsyncMock(side_effect=HTTPException(404))):
            with self.assertRaises(HTTPException) as error:
                await api.start_analysis(self.recording.id, self.payload, self.db, self.viewer)
        self.assertEqual(error.exception.status_code, 404)
        self.db.add.assert_not_called()

    async def test_viewer_capability_does_not_grant_task_management(self):
        with patch.object(api, 'load_recording', new=AsyncMock(return_value=self.recording)), \
                patch.object(api, 'available', return_value=True):
            result = await api.get_analysis(self.recording.id, self.db, self.viewer)
        self.assertTrue(result['can_start_analysis'])
        self.assertFalse(result['can_manage'])


if __name__ == '__main__':
    unittest.main()
