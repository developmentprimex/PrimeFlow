import hashlib
import tempfile
import unittest
from pathlib import Path

from app.services.meeting_recording_storage import LocalMeetingStorage, StorageBusy, StorageError, finalization_lock


class RecordingStorageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.storage = LocalMeetingStorage(self.tmp.name)

    async def body(self, *parts):
        for part in parts:
            yield part

    async def test_stream_hash_limit_and_atomic_write(self):
        path, size, digest = await self.storage.receive("2026/10/session", self.body(b"abc", b"def"), 6)
        self.assertEqual(size, 6)
        self.assertEqual(digest, hashlib.sha256(b"abcdef").hexdigest())
        self.assertEqual(path.read_bytes(), b"abcdef")
        path.unlink()
        with self.assertRaises(StorageError):
            await self.storage.receive("2026/10/session", self.body(b"abc", b"def"), 5)
        self.assertFalse(list(self.storage.path("2026/10/session").glob("*.part")))

    async def test_empty_upload_and_traversal_rejected(self):
        with self.assertRaises(StorageError):
            await self.storage.receive("2026/10/session", self.body(b""), 5)
        for key in ("../outside", "/absolute", "C:/outside", "a/../../outside", "a\\..\\outside"):
            with self.subTest(key=key), self.assertRaises(StorageError):
                self.storage.path(key)

    def test_default_and_relative_root_are_backend_relative(self):
        expected = Path(__file__).resolve().parents[1]
        self.assertEqual(LocalMeetingStorage("").root, expected / "uploads/meeting-recordings")
        self.assertEqual(LocalMeetingStorage("private/recordings").root, expected / "private/recordings")

    def test_restart_reads_same_logical_key(self):
        file = self.storage.path("2026/10/session/recording.webm")
        file.parent.mkdir(parents=True)
        file.write_bytes(b"persisted")
        restarted = LocalMeetingStorage(self.tmp.name)
        self.assertEqual(restarted.path("2026/10/session/recording.webm").read_bytes(), b"persisted")

    def test_concurrent_finalizers_are_excluded_even_without_a_database_lock(self):
        folder = self.storage.path("2026/10/session")
        folder.mkdir(parents=True)
        with finalization_lock(folder):
            with self.assertRaises(StorageBusy):
                self.storage.finalize("2026/10/session", [], "video/webm", "ffmpeg", "ffprobe", 10)
        with finalization_lock(folder):
            pass


if __name__ == "__main__":
    unittest.main()
