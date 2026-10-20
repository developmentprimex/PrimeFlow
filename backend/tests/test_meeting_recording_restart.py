import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import httpx
from recording_test_support import TEST_URL


@unittest.skipUnless(TEST_URL and os.environ.get("RECORDINGS_TEST_PROCESS_RESTART") == "true", "Opt-in isolated process restart test")
class RecordingProcessRestartTests(unittest.TestCase):
    def test_acknowledged_upload_and_ready_playback_survive_real_api_process_restarts(self):
        from recording_test_support import prepare_database
        fixture = prepare_database()
        backend = Path(__file__).resolve().parents[1]
        (backend.parent / "tmp/recorder-fixture.json").write_text(json.dumps(fixture), encoding="utf-8")
        with tempfile.TemporaryDirectory() as temp:
            environment = {**os.environ, "MEETING_RECORDINGS_ROOT": temp}
            ffmpeg = environment["MEETING_RECORDINGS_FFMPEG"]
            media = Path(temp) / "fixture.webm"
            subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10", "-t", "1", "-c:v", "libvpx", str(media)], check=True)
            data = media.read_bytes()
            headers = {"Authorization": "Bearer " + fixture["owner"]["token"]}
            process = None

            def stop():
                nonlocal process
                if process is not None:
                    process.terminate()
                    process.wait(timeout=10)
                    process = None

            def start():
                nonlocal process
                process = subprocess.Popen([sys.executable, "tests/serve_recordings_test.py"], cwd=backend, env=environment,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.fail("Test API did not start")
                    try:
                        if httpx.get("http://127.0.0.1:8012/docs", timeout=1).status_code == 200:
                            return
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                self.fail("Test API startup timed out")

            try:
                start()
                with httpx.Client(base_url="http://127.0.0.1:8012/api/meeting-recordings", headers=headers, timeout=30, follow_redirects=True) as client:
                    created = client.post("", json={"title": "Process restart", "capture_source_type": "monitor", "mime_type": "video/webm", "consent_acknowledged": True})
                    self.assertEqual(created.status_code, 201, created.text)
                    id = created.json()["id"]

                    def put(index, content):
                        return client.put(f"/{id}/chunks/{index}", headers={"Content-Type": "application/octet-stream", "X-Chunk-SHA256": hashlib.sha256(content).hexdigest()}, content=content)

                    self.assertEqual(put(0, data[:100]).status_code, 200)
                    stop(); start()
                    self.assertEqual(client.get(f"/{id}").json()["chunks_received"], 1)
                    self.assertTrue(put(0, data[:100]).json()["duplicate"])
                    self.assertEqual(put(1, data[100:]).status_code, 200)
                    completed = client.post(f"/{id}/complete", json={"chunks": 2})
                    self.assertEqual(completed.status_code, 200, completed.text)
                    self.assertEqual(completed.json()["status"], "READY")
                    stop(); start()
                    playback = client.get(f"/{id}/stream", headers={"Range": "bytes=0-31"})
                    self.assertEqual(playback.status_code, 206)
                    self.assertEqual(len(playback.content), 32)
            finally:
                stop()
