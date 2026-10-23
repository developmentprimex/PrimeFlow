import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.services.meeting_recording_storage import LocalMeetingStorage, StorageError
from app.services.recording_files_archive import MissingRecordingSource, archive_recording, purge_recording, reports_root


class RecordingFilesArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.store = LocalMeetingStorage(str(base / "private"))
        self.target = base / "files" / "02_REPORTS"
        self.row = SimpleNamespace(id="session", status="READY", title="Takimi javor ë",
                                   storage_key="2026/10/session", mime_type="video/webm", size_bytes=7)
        self.source = self.store.path("2026/10/session/recording.webm")
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b"example")
        self.row.recording_started_at = datetime(2026, 10, 23, tzinfo=timezone.utc)

    def test_copy_manifest_idempotency_and_deleted_destination_recovery(self):
        target = archive_recording(self.row, self.store, self.target)
        self.assertEqual(target.read_bytes(), b"example")
        self.assertEqual(target.parent, self.target.resolve())
        self.assertEqual(target.name, 'REGJISTRIM Takimi javor ë_23.10.2026.webm')
        self.assertEqual(list(self.target.iterdir()), [target])
        self.assertEqual(json.loads(self.source.with_name("files-archive.json").read_text(encoding="utf-8"))["title"], self.row.title)
        with patch("app.services.recording_files_archive.digest_file", side_effect=AssertionError("copied twice")):
            self.assertEqual(archive_recording(self.row, self.store, self.target), target)
        target.unlink()
        archive_recording(self.row, self.store, self.target)
        self.assertEqual(target.read_bytes(), b"example")

    def test_failed_integrity_check_retains_local_and_retries_after_restart(self):
        with patch("app.services.recording_files_archive.digest_file", return_value=(7, "wrong")):
            with self.assertRaises(StorageError):
                archive_recording(self.row, self.store, self.target)
        self.assertEqual(self.source.read_bytes(), b"example")
        self.assertFalse(self.source.with_name("files-archive.json").exists())
        self.assertFalse(list(self.target.rglob("*.part")))
        restarted = LocalMeetingStorage(str(self.store.root))
        self.assertEqual(archive_recording(self.row, restarted, self.target).read_bytes(), b"example")

    def test_unavailable_share_retains_local_and_can_retry(self):
        self.target.parent.write_bytes(b"unavailable")
        with self.assertRaises(OSError):
            archive_recording(self.row, self.store, self.target)
        self.assertFalse(self.source.with_name("files-archive.json").exists())
        self.target.parent.unlink()
        self.assertEqual(archive_recording(self.row, self.store, self.target).read_bytes(), b"example")

    def test_unfinished_recording_never_copied(self):
        self.row.status = "UPLOADING"
        with self.assertRaises(StorageError):
            archive_recording(self.row, self.store, self.target)
        self.assertFalse(self.target.exists())

    def test_recording_owned_by_another_host_does_not_create_empty_folders(self):
        self.row.storage_key = '2026/10/other-host'
        self.row.recording_started_at = None
        with self.assertRaises(MissingRecordingSource):
            archive_recording(self.row, self.store, self.target)
        self.assertFalse(self.store.path(self.row.storage_key).exists())
        self.assertFalse(self.target.exists())
        self.row.deleted_at = datetime.now(timezone.utc)
        with self.assertRaises(MissingRecordingSource):
            purge_recording(self.row, self.store, self.target)

    def test_missing_video_in_existing_folder_is_not_archived(self):
        self.source.unlink()
        with self.assertRaises(MissingRecordingSource):
            archive_recording(self.row, self.store, self.target)
        self.assertFalse(self.target.exists())

    def test_purge_deletes_both_copies_and_is_retryable(self):
        target = archive_recording(self.row, self.store, self.target)
        self.row.deleted_at = datetime.now(timezone.utc)
        with patch('app.services.recording_files_archive.digest_file', side_effect=OSError('share offline')):
            with self.assertRaises(OSError):
                purge_recording(self.row, self.store, self.target)
        self.assertTrue(self.source.exists())
        self.assertTrue(self.source.with_name('files-archive.json').exists())
        purge_recording(self.row, self.store, self.target)
        self.assertFalse(target.exists())
        self.assertFalse(self.source.exists())
        purge_recording(self.row, self.store, self.target)

    def test_purge_refuses_modified_or_unrelated_remote_file(self):
        target = archive_recording(self.row, self.store, self.target)
        self.row.deleted_at = datetime.now(timezone.utc)
        target.write_bytes(b'changed by someone else')
        with self.assertRaises(StorageError):
            purge_recording(self.row, self.store, self.target)
        self.assertTrue(self.source.exists())
        self.assertTrue(target.exists())
        saved_path = self.source.with_name('files-archive.json')
        saved = json.loads(saved_path.read_text(encoding='utf-8'))
        saved['path'] = str(Path(self.tmp.name) / 'unrelated.webm')
        saved.pop('relative_path', None)
        saved_path.write_text(json.dumps(saved), encoding='utf-8')
        with self.assertRaises(StorageError):
            purge_recording(self.row, self.store, self.target)

    def test_receipt_works_with_server_local_and_unc_names_for_the_same_share(self):
        target = archive_recording(self.row, self.store, self.target)
        receipt = self.source.with_name('files-archive.json')
        saved = json.loads(receipt.read_text(encoding='utf-8'))
        saved['path'] = 'F:\\FILES\\' + target.name
        receipt.write_text(json.dumps(saved), encoding='utf-8')
        self.assertEqual(archive_recording(self.row, self.store, self.target), target)
        self.assertEqual(list(self.target.iterdir()), [target])
        self.row.deleted_at = datetime.now(timezone.utc)
        purge_recording(self.row, self.store, self.target)
        self.assertFalse(target.exists())

    def test_unsafe_title_and_duplicate_titles_stay_flat_and_distinct(self):
        self.row.title = '../Takimi: test/\\?*'
        first = archive_recording(self.row, self.store, self.target)
        self.row.id = 'second-session'
        self.source.with_name('files-archive.json').unlink()
        second = archive_recording(self.row, self.store, self.target)
        self.assertEqual(first.parent, self.target.resolve())
        self.assertEqual(second.parent, first.parent)
        self.assertNotEqual(first, second)
        self.assertEqual(len(list(self.target.iterdir())), 2)

    def test_reports_root_confined_and_missing_mount_not_created(self):
        root = Path(self.tmp.name)
        self.assertEqual(reports_root(str(root), "project/02_REPORTS"), root / "project/02_REPORTS")
        for subdir in ("../outside", str(root.parent)):
            with self.assertRaises(StorageError):
                reports_root(str(root), subdir)
        with self.assertRaises(StorageError):
            reports_root(str(root / "missing-share"), "02_REPORTS")
        self.assertFalse((root / "missing-share").exists())


if __name__ == "__main__":
    unittest.main()
