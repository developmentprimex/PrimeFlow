"""Copy validated recordings to FILES; keep private local playback storage intact."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from app.services.meeting_recording_storage import (
    LocalMeetingStorage, StorageError, durable_replace, finalization_lock,
)


class MissingRecordingSource(StorageError):
    """The shared DB references media held by another storage root/API host."""


def reports_root(files_root: str, subdir: str) -> Path:
    root = Path(files_root)
    if not root.is_absolute():
        raise StorageError("FILES root must be an absolute path accessible to the API service")
    root = root.resolve()
    target = (root / subdir).resolve()
    if target == root or root not in target.parents:
        raise StorageError("Recording reports must be inside FILES")
    # Never create a replacement FILES root when a share/mount is unavailable.
    if not root.is_dir():
        raise StorageError("FILES storage is unavailable")
    return target


def digest_file(path: Path) -> tuple[int, str]:
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    return size, digest.hexdigest()


def archive_recording(row, store: LocalMeetingStorage, target_root: Path) -> Path:
    """Idempotent, bounded copy with read-back verification and a durable receipt.

    Only READY DB rows enter here. The local receipt is written last, so a crash
    or share outage leaves the READY recording eligible for the next retry.
    """
    if row.status != "READY":
        raise StorageError("Only validated recordings can be archived")
    folder = store.path(row.storage_key)
    extension = "webm" if row.mime_type == "video/webm" else "mp4"
    source = folder / f"recording.{extension}"
    try:
        source_stat = source.stat()
    except FileNotFoundError as exc:
        raise MissingRecordingSource(f"Recording {row.id} media is not present in {store.root}") from exc
    if not source.is_file():
        raise MissingRecordingSource(f"Recording {row.id} media is not a file in {store.root}")
    started = getattr(row, "recording_started_at", None)
    if started is None:
        started = datetime.fromtimestamp(source_stat.st_mtime)
    date = started.strftime("%d.%m.%Y")
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", row.title).strip(" .")[:80] or "Regjistrim"
    title = re.sub(r'^REGJISTRIM\s+', '', title, flags=re.IGNORECASE)
    filename = f"REGJISTRIM {title}_{date}.{extension}"
    target = LocalMeetingStorage(str(target_root)).path(filename)
    receipt = folder / "files-archive.json"
    # Shared local lock serializes filename allocation across API workers.
    with finalization_lock(store.root), finalization_lock(folder):
        saved = {}
        candidate_receipt = receipt if receipt.is_file() else folder / "files-archive-pending.json"
        if candidate_receipt.is_file():
            try:
                saved = json.loads(candidate_receipt.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                pass
        def matches_saved_path(candidate):
            return (saved.get("path") == str(candidate) or
                    (saved.get("recording_id") == str(row.id) and saved.get("relative_path") == candidate.name))

        if target.exists() and not matches_saved_path(target):
            target = target.with_name(f"{target.stem}_{row.id}{target.suffix}")
        if saved:
            try:
                if (matches_saved_path(target) and saved.get("size_bytes") == row.size_bytes
                        and target.stat().st_size == row.size_bytes):
                    return target
            except (ValueError, OSError):
                pass
        target.parent.mkdir(parents=True, exist_ok=True)
        # A fixed temp name is safe under the local per-recording OS lock and
        # is reused after a crash, avoiding accumulation of multi-GB partials.
        temporary = target.with_name(f".{target.name}.part")
        receipt_temp = folder / "files-archive.part"
        try:
            digest, size = hashlib.sha256(), 0
            with source.open("rb") as incoming, temporary.open("wb") as output:
                while block := incoming.read(1024 * 1024):
                    output.write(block)
                    digest.update(block)
                    size += len(block)
                output.flush()
                os.fsync(output.fileno())
            if size != row.size_bytes or digest_file(temporary) != (size, digest.hexdigest()):
                raise StorageError("FILES copy integrity check failed")
            data = {"recording_id": str(row.id), "title": row.title,
                    "path": str(target), "relative_path": target.name, "size_bytes": size, "sha256": digest.hexdigest()}
            with receipt_temp.open("w", encoding="utf-8") as output:
                json.dump(data, output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            # Track the destination before publication so deletion can recover
            # even if the process dies between remote rename and local receipt.
            pending = folder / "files-archive-pending.json"
            durable_replace(receipt_temp, pending)
            durable_replace(temporary, target)
            durable_replace(pending, receipt)
            return target
        finally:
            temporary.unlink(missing_ok=True)
            receipt_temp.unlink(missing_ok=True)


def purge_recording(row, store: LocalMeetingStorage, target_root: Path):
    """Retryable removal of only this recording's verified FILES copy and media."""
    if row.deleted_at is None:
        raise StorageError("Recording must be deleted before removing its media")
    folder = store.path(row.storage_key)
    if not folder.exists():
        # A workstation sharing the DB cannot acknowledge deletion for media
        # owned by another host. Leave the durable queue for that host to purge.
        raise MissingRecordingSource(f"Recording {row.id} storage is not present in {store.root}")
    with finalization_lock(store.root), finalization_lock(folder):
        for name in ("files-archive.json", "files-archive-pending.json"):
            receipt = folder / name
            if not receipt.is_file():
                continue
            saved = json.loads(receipt.read_text(encoding="utf-8"))
            target = (LocalMeetingStorage(str(target_root)).path(saved["relative_path"])
                      if saved.get("relative_path") else Path(saved["path"]).resolve())
            root = target_root.resolve()
            if root not in target.parents or saved["recording_id"] != str(row.id):
                raise StorageError("Archive receipt does not belong to this recording or FILES folder")
            try:
                actual = digest_file(target)
            except FileNotFoundError:
                continue
            if actual != (saved["size_bytes"], saved["sha256"]):
                raise StorageError("FILES recording was changed; refusing to remove a different file")
            target.unlink()
        # Keep receipts until remote deletion succeeds; a share outage retries.
        for child in folder.iterdir():
            if child.name == ".finalize.lock":
                continue
            if child.is_dir() and not child.is_symlink():
                if folder not in child.resolve().parents:
                    raise StorageError("Invalid local recording path")
                shutil.rmtree(child)
            else:
                child.unlink()
