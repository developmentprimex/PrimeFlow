"""Create a synthetic, validated recording and optionally export it to FILES."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import uuid

workspace = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(workspace / "backend"))
from app.services.meeting_recording_storage import LocalMeetingStorage
from app.services.recording_files_archive import archive_recording, digest_file, reports_root

parser = argparse.ArgumentParser()
parser.add_argument("--archive", action="store_true")
parser.add_argument("--flatten-test", action="store_true")
parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
parser.add_argument("--ffprobe", default=shutil.which("ffprobe"))
args = parser.parse_args()
base = workspace / "tmp" / "recording-files-smoke"
base.mkdir(parents=True, exist_ok=True)
state = base / "test.json"
store = LocalMeetingStorage(str(base / "private"))
if not args.archive:
    recording_id = str(uuid.uuid4())
    key = f"{datetime.now(timezone.utc):%Y/%m}/{recording_id}"
    folder = store.path(key)
    (folder / "chunks").mkdir(parents=True)
    fixture = folder / "fixture.webm"
    subprocess.run([args.ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi",
                    "-i", "testsrc=size=640x360:rate=15", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=48000", "-t", "5", "-c:v", "libvpx",
                    "-pix_fmt", "yuv420p", "-c:a", "libopus", str(fixture)], check=True)
    chunk = folder / "chunks" / "00000000.chunk"
    shutil.copyfile(fixture, chunk)
    data = chunk.read_bytes()
    result = store.finalize(key, [SimpleNamespace(index=0, size_bytes=len(data),
                            sha256=hashlib.sha256(data).hexdigest())], "video/webm",
                            args.ffmpeg, args.ffprobe, 30)
    row = {"id": recording_id, "title": "TEST - PrimeFlow - video dhe ze prove 5 sekonda",
           "status": "READY", "storage_key": key, "mime_type": result["mime_type"],
           "size_bytes": result["size_bytes"]}
    state.write_text(json.dumps(row, indent=2), encoding="utf-8")
    print(json.dumps({"prepared": True, "duration_seconds": result["duration_seconds"],
                      "has_audio": result["has_audio"], "size_bytes": row["size_bytes"]}))
else:
    row = SimpleNamespace(**json.loads(state.read_text(encoding="utf-8")))
    row.title = "TEST"
    row.recording_started_at = datetime(2026, 10, 23, tzinfo=timezone.utc)
    root = reports_root(r"\\192.168.10.8\files", "10_ZHVILLIM/04_PROJECTS/26_PRIMEFLOW/08_TAKIMET")
    destination = archive_recording(row, store, root)
    source = store.path(f"{row.storage_key}/recording.webm")
    assert digest_file(source) == digest_file(destination), "Exported recording differs"
    probe = subprocess.run([args.ffprobe, "-v", "error", "-show_format", "-show_streams",
                            "-of", "json", str(destination)], check=True, capture_output=True, text=True)
    media = json.loads(probe.stdout)
    assert {"video", "audio"} <= {s["codec_type"] for s in media["streams"]}
    assert 4.5 < float(media["format"]["duration"]) < 6
    if args.flatten_test:
        old = LocalMeetingStorage(str(root)).path(f"{row.storage_key}/recording.webm")
        # Remove only this exact earlier synthetic test after verifying its copy.
        assert root.resolve() in old.resolve().parents and old != destination
        if old.is_file() and digest_file(old) == digest_file(destination):
            metadata = old.with_name("metadata.json")
            if metadata.is_file():
                manifest = json.loads(metadata.read_text(encoding="utf-8"))
                assert manifest["recording_id"] == row.id
                metadata.unlink()
            old.unlink()
            parent = old.parent
            while parent != root.resolve():
                try:
                    parent.rmdir()  # Only empty directories; never recursive.
                except OSError:
                    break
                parent = parent.parent
    print(json.dumps({"verified": True, "path": str(destination),
                      "duration_seconds": media["format"]["duration"], "sha256": digest_file(destination)[1]}))
