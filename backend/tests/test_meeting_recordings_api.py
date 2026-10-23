import hashlib
import os
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from recording_test_support import TEST_URL


@unittest.skipUnless(TEST_URL, "Set RECORDINGS_TEST_DATABASE_URL to the isolated test database")
class RecordingApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from recording_test_support import prepare_database
        cls.fixture = prepare_database()
        from app.config import settings
        cls.settings = settings
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.routers.meeting_recordings import router
        from app.db import get_db
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from sqlalchemy.pool import NullPool
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root_patch = patch.object(settings, "MEETING_RECORDINGS_ROOT", cls.tmp.name)
        cls.root_patch.start()
        cls.app = FastAPI()
        cls.engine = create_async_engine(TEST_URL.replace("postgresql://", "postgresql+asyncpg://", 1), poolclass=NullPool)
        session = async_sessionmaker(cls.engine, expire_on_commit=False)
        async def test_db():
            async with session() as db:
                yield db
        cls.app.dependency_overrides[get_db] = test_db
        cls.app.include_router(router, prefix="/api/meeting-recordings")
        cls.client = TestClient(cls.app)
        media = Path(cls.tmp.name) / "fixture.webm"
        subprocess.run([settings.MEETING_RECORDINGS_FFMPEG, "-nostdin", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10", "-f", "lavfi", "-i", "sine=frequency=440", "-t", "1.2", "-c:v", "libvpx", "-c:a", "libopus", str(media)], check=True)
        cls.media = media.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.root_patch.stop()
        cls.tmp.cleanup()

    def auth(self, person="owner"):
        return {"Authorization": "Bearer " + self.fixture[person]["token"]}

    def create(self, meeting=False):
        response = self.client.post("/api/meeting-recordings", headers=self.auth(), json={
            "title": "Test " + str(uuid.uuid4()), "capture_source_type": "browser", "mime_type": "video/webm",
            "consent_acknowledged": True, "has_system_audio": True,
            "meeting_id": self.fixture["meeting_id"] if meeting else None,
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def upload(self, id, index, data, person="owner", digest=None):
        return self.client.put(f"/api/meeting-recordings/{id}/chunks/{index}", headers={
            **self.auth(person), "Content-Type": "application/octet-stream", "X-Chunk-SHA256": digest or hashlib.sha256(data).hexdigest(),
        }, content=data)

    def abandon(self, id):
        self.client.post(f"/api/meeting-recordings/{id}/fail", headers=self.auth())

    def ready(self, meeting=False):
        id = self.create(meeting)
        for index, part in enumerate([self.media[:100], self.media[100:]]):
            response = self.upload(id, index, part)
            self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post(f"/api/meeting-recordings/{id}/complete", headers=self.auth(), json={"chunks": 2})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "READY")
        self.assertGreater(response.json()["duration_seconds"], 0)
        self.assertEqual(response.json()["video_width"], 160)
        return id

    def test_duplicate_order_hash_and_incomplete_upload(self):
        id = self.create()
        try:
            self.assertEqual(self.upload(id, 1, b"wrong order").status_code, 409)
            self.assertEqual(self.upload(id, 0, b"first", digest="0" * 64).status_code, 422)
            self.assertEqual(self.upload(id, 0, b"first").status_code, 200)
            self.assertTrue(self.upload(id, 0, b"first").json()["duplicate"])
            self.assertEqual(self.upload(id, 0, b"different").status_code, 409)
            self.assertEqual(self.client.get(f"/api/meeting-recordings/{id}", headers=self.auth()).json()["chunks_received"], 1)
            self.assertEqual(self.client.post(f"/api/meeting-recordings/{id}/complete", headers=self.auth(), json={"chunks": 2}).status_code, 409)
            self.assertEqual(self.client.post(f"/api/meeting-recordings/{id}/complete", headers=self.auth(), json={"chunks": 1}).status_code, 422)
            self.assertEqual(self.client.get(f"/api/meeting-recordings/{id}", headers=self.auth()).json()["status"], "FAILED")
        finally:
            self.abandon(id)

    def test_authorized_range_download_and_playback_after_app_restart(self):
        id = self.ready()
        from fastapi.testclient import TestClient
        with TestClient(self.app) as restarted:
            response = restarted.get(f"/api/meeting-recordings/{id}/stream", headers={**self.auth(), "Range": "bytes=0-31"})
            self.assertEqual(response.status_code, 206, response.text)
            self.assertEqual(len(response.content), 32)
            self.assertIn("no-store", response.headers["cache-control"])
            self.assertEqual(restarted.get(f"/api/meeting-recordings/{id}/stream", headers={**self.auth(), "Range": "bytes=999999999-"}).status_code, 416)
        self.assertEqual(self.client.get(f"/api/meeting-recordings/{id}/download", headers=self.auth()).status_code, 200)
        self.assertEqual(self.client.post(f"/api/meeting-recordings/{id}/complete", headers=self.auth(), json={"chunks": 2}).json()["status"], "READY")

    def test_all_users_can_read_but_only_owner_can_write(self):
        id = self.ready(meeting=True)
        for operation, path, kwargs in [
            ("post", "/complete", {"json": {"chunks": 2}}), ("post", "/fail", {}),
        ]:
            with self.subTest(operation=operation, path=path):
                self.assertEqual(getattr(self.client, operation)(f"/api/meeting-recordings/{id}{path}", headers=self.auth("other"), **kwargs).status_code, 404)
        self.assertEqual(self.upload(id, 0, b"injection", person="other").status_code, 404)
        for person in ["other", "participant", "manager"]:
            self.assertEqual(self.client.get(f"/api/meeting-recordings/{id}", headers=self.auth(person)).status_code, 200)
            self.assertEqual(self.client.get(f"/api/meeting-recordings/{id}/stream", headers=self.auth(person)).status_code, 200)
            self.assertEqual(self.client.get(f"/api/meeting-recordings/{id}/download", headers=self.auth(person)).status_code, 200)
            self.assertEqual(self.client.post(f"/api/meeting-recordings/{id}/playback", headers=self.auth(person)).status_code, 200)
            self.assertEqual(self.client.post(f"/api/meeting-recordings/{id}/fail", headers=self.auth(person)).status_code, 404)
        other_list = self.client.get("/api/meeting-recordings", headers=self.auth("other")).json()
        self.assertIn(id, [r["id"] for r in other_list])
        grant = self.client.post(f"/api/meeting-recordings/{id}/playback", headers=self.auth()).json()["token"]
        self.assertEqual(self.client.get(f"/api/meeting-recordings/{id}/stream", headers={"Authorization": "Bearer " + grant}).status_code, 200)
        self.assertEqual(self.client.get(f"/api/meeting-recordings/{uuid.uuid4()}/stream", headers={"Authorization": "Bearer " + grant}).status_code, 401)
        self.assertEqual(self.client.get(f"/api/meeting-recordings/{id}", headers={"Authorization": "Bearer " + grant}).status_code, 401)

    def test_unlinked_recording_is_shared_but_anonymous_denied(self):
        id = self.ready()
        self.assertEqual(self.client.get(f"/api/meeting-recordings/{id}", headers=self.auth("participant")).status_code, 200)
        for path in ["", f"/{id}", f"/{id}/stream", f"/{id}/download"]:
            self.assertEqual(self.client.get("/api/meeting-recordings" + path).status_code, 401)

    def test_saved_history_reports_missing_file_and_recovers_after_restore(self):
        id = self.ready()
        detail_url = f"/api/meeting-recordings/{id}"
        self.assertTrue(self.client.get(detail_url, headers=self.auth()).json()['media_available'])
        files = list(Path(self.tmp.name).glob(f"*/*/{id}/recording.webm"))
        self.assertEqual(len(files), 1)
        original = files[0]
        backup = original.with_suffix('.backup')
        original.rename(backup)
        try:
            self.assertFalse(self.client.get(detail_url, headers=self.auth()).json()['media_available'])
            rows = self.client.get('/api/meeting-recordings', headers=self.auth()).json()
            self.assertFalse(next(r for r in rows if r['id'] == id)['media_available'])
            self.assertEqual(self.client.get(detail_url + '/stream', headers=self.auth()).status_code, 503)
        finally:
            backup.rename(original)
        self.assertTrue(self.client.get(detail_url, headers=self.auth()).json()['media_available'])
        self.assertEqual(self.client.get(detail_url + '/stream', headers=self.auth()).status_code, 200)

    def test_upload_limit_and_session_survives_new_client(self):
        id = self.create()
        try:
            with patch.object(self.settings, "MEETING_RECORDINGS_MAX_CHUNK_BYTES", 3):
                self.assertEqual(self.upload(id, 0, b"too big").status_code, 413)
            self.assertEqual(self.upload(id, 0, self.media[:100]).status_code, 200)
            from fastapi.testclient import TestClient
            with TestClient(self.app) as restarted:
                response = restarted.put(f"/api/meeting-recordings/{id}/chunks/0", headers={**self.auth(), "Content-Type": "application/octet-stream", "X-Chunk-SHA256": hashlib.sha256(self.media[:100]).hexdigest()}, content=self.media[:100])
                self.assertTrue(response.json()["duplicate"])
            self.assertEqual(self.upload(id, 1, self.media[100:]).status_code, 200)
            self.assertEqual(self.client.post(f"/api/meeting-recordings/{id}/complete", headers=self.auth(), json={"chunks": 2}).json()["status"], "READY")
        finally:
            self.abandon(id)


if __name__ == "__main__":
    unittest.main()
