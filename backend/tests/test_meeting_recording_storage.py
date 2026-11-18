import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

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

    def test_media_availability_checks_actual_file_and_size_across_roots(self):
        key = "2026/10/session"
        self.assertIsNone(self.storage.available_media(key, "video/webm", 9))
        file = self.storage.path(f"{key}/recording.webm")
        file.parent.mkdir(parents=True)
        file.write_bytes(b"persisted")
        self.assertEqual(self.storage.available_media(key, "video/webm", 9), file)
        self.assertIsNone(self.storage.available_media(key, "video/webm", 10))
        # A DB row alone cannot make the file available under another checkout.
        other = LocalMeetingStorage(str(Path(self.tmp.name) / "other-checkout"))
        self.assertIsNone(other.available_media(key, "video/webm", 9))
        persistent = LocalMeetingStorage(str(self.storage.root))
        self.assertEqual(persistent.available_media(key, "video/webm", 9), file)

    def test_concurrent_finalizers_are_excluded_even_without_a_database_lock(self):
        folder = self.storage.path("2026/10/session")
        folder.mkdir(parents=True)
        with finalization_lock(folder):
            with self.assertRaises(StorageBusy):
                self.storage.finalize("2026/10/session", [], "video/webm", "ffmpeg", "ffprobe", 10)
        with finalization_lock(folder):
            pass

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
    def test_finalizes_and_publishes_audio_only_fragments(self):
        for mime, extension, codec, flags in (
            ("audio/webm", "webm", "libopus", []),
            ("audio/mp4", "m4a", "aac", ["-movflags", "+frag_keyframe+empty_moov"]),
        ):
            with self.subTest(mime=mime):
                key = f"2026/11/{extension}"
                folder = self.storage.path(key)
                chunks_dir = folder / "chunks"
                chunks_dir.mkdir(parents=True)
                sample = folder / f"sample.{extension}"
                subprocess.run([
                    "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-c:a", codec, *flags, str(sample),
                ], check=True, timeout=30)
                data = sample.read_bytes()
                chunks = []
                split = len(data) // 2
                for index, fragment in enumerate((data[:split], data[split:])):
                    (chunks_dir / f"{index:08d}.chunk").write_bytes(fragment)
                    chunks.append(SimpleNamespace(index=index, size_bytes=len(fragment), sha256=hashlib.sha256(fragment).hexdigest()))
                result = self.storage.finalize(key, chunks, mime, "ffmpeg", "ffprobe", 10)
                self.assertTrue(result["has_audio"])
                self.assertIsNone(result["video_width"])
                self.assertIsNone(result["video_height"])
                self.assertAlmostEqual(result["duration_seconds"], 1, delta=0.1)
                self.assertEqual(self.storage.available_media(key, mime, result["size_bytes"]), folder / f"recording.{extension}")


if __name__ == "__main__":
    unittest.main()
