import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import deploy_mira_release as releases


class MiraReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {
            "PM2_HOME": temporary, "RUNNER_TEMP": temporary,
            "GITHUB_RUN_ID": "501", "GITHUB_RUN_ATTEMPT": "1",
        }))
        self.deployment = releases.Deployment()
        self.old = self.release("a", "previous")
        self.new = self.release("b", "candidate")
        releases.write_json(self.deployment.active, self.old)
        releases.write_json(self.deployment.plan, {"previous": self.old, "candidate": self.new, "switching": False})

    def release(self, prefix, kind):
        runtime = self.deployment.root / f"{prefix * 12}-501-1-{kind}"
        (runtime / "backend").mkdir(parents=True)
        return {"path": str(runtime), "build": prefix * 40, "roles": ["primeflow-discord"], "probe": True, "voice": True}

    def test_activation_opens_new_release_only_after_readiness(self):
        ready = Path(self.new["path"]) / "traffic.ready"

        def verify(release):
            self.assertEqual(release, self.new)
            self.assertFalse(ready.exists())
            self.assertEqual(releases.read_json(self.deployment.active), self.old)

        with patch.object(self.deployment, "delete_processes"), patch.object(self.deployment, "start") as start, \
                patch.object(self.deployment, "verify", side_effect=verify):
            self.deployment.activate()
        start.assert_called_once_with(self.new)
        self.assertTrue(ready.is_file())
        self.assertEqual(releases.read_json(self.deployment.active), self.new)
        self.assertTrue(Path(self.old["path"]).is_dir())

    def test_failed_readiness_restores_previous_files_and_process(self):
        ready = Path(self.new["path"]) / "traffic.ready"
        with patch.object(self.deployment, "delete_processes") as delete, patch.object(self.deployment, "start") as start, \
                patch.object(self.deployment, "verify", side_effect=[RuntimeError("probe failed"), None]), \
                patch.object(releases, "pm2") as pm2:
            with self.assertRaisesRegex(RuntimeError, "probe failed"):
                self.deployment.activate()
            self.assertFalse(ready.exists())
            self.deployment.recover()
        self.assertEqual(delete.call_count, 2)
        self.assertEqual([call.args for call in start.call_args_list], [(self.new,), (self.old,)])
        self.assertEqual(releases.read_json(self.deployment.active), self.old)
        pm2.assert_called_once_with("save")

    def test_ready_status_must_belong_to_candidate_and_include_panel_and_voice(self):
        name = "primeflow-discord"
        status = {"pid": 7, "build": self.new["build"], "panel_ready": True, "voice_ready": True}
        file = Path(self.new["path"]) / "backend" / releases.PROCESSES[name]
        current = {name: {"pid": 7, "pm2_env": {"status": "online", "pm_cwd": str(file.parent)}}}
        file.write_text(json.dumps({**status, "voice_ready": False}), encoding="utf-8")
        with patch.object(releases, "processes", return_value=current), \
                patch.object(releases.time, "monotonic", side_effect=[0, 0, 91]), \
                patch.object(releases.time, "sleep", Mock()):
            with self.assertRaisesRegex(RuntimeError, "readiness checks timed out"):
                self.deployment.verify(self.new)
        file.write_text(json.dumps(status), encoding="utf-8")
        with patch.object(releases, "processes", return_value=current):
            self.deployment.verify(self.new)

    @unittest.skipUnless(os.name == "nt", "Windows venv executables use a redirector")
    def test_matches_the_actual_python_worker_started_by_the_windows_venv_launcher(self):
        with subprocess.Popen(
            [sys.executable, "-c", "import os; print(os.getpid(), flush=True); input()"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        ) as launcher:
            try:
                pid = int(launcher.stdout.readline())
                self.assertTrue(releases.matches_worker_pid(launcher.pid, pid))
                self.assertFalse(releases.matches_worker_pid(os.getpid(), pid if launcher.pid != pid else 0))
            finally:
                launcher.communicate("\n", timeout=10)
