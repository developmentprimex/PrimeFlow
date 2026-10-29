import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from dotenv import dotenv_values


class KujtesaDeployTests(unittest.TestCase):
    def test_readiness_rejects_old_build_and_stale_or_malformed_status(self):
        from scripts.check_kujtesa_worker import status
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "status.json"
            self.assertFalse(status(path, "new", now)["ready"])
            data = {"pid": 123, "build": "new", "guild_id": "111111111111111111", "last_seen_at": now.isoformat(), "reminders_enabled": True}
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertTrue(status(path, "new", now)["ready"])
            self.assertFalse(status(path, "old", now)["ready"])
            self.assertFalse(status(path, "new", now+timedelta(seconds=91))["ready"])
            path.write_text("not-json", encoding="utf-8")
            self.assertFalse(status(path, "new", now)["ready"])
    def config(self, **changes):
        from scripts.configure_kujtesa_server import build_config
        return build_config({"KUJTESA_DISCORD_TOKEN": "separate.kujtesa.token", "GA_PERSONAL_DISCORD_BRIDGE_SECRET": "k"*48,
                             "KUJTESA_ENABLED": "true", "KUJTESA_REMINDERS_ENABLED": "true", **changes})

    def test_uses_only_dedicated_secrets_and_loopback_api(self):
        config = self.config(DISCORD_BOT_TOKEN="work.mira.token", DISCORD_BRIDGE_SECRET="work-key")
        self.assertEqual(config["DISCORD_TOKEN"], "separate.kujtesa.token")
        self.assertEqual(config["PRIMEFLOW_GA_BRIDGE_KEY"], "k"*48)
        self.assertEqual(config["PRIMEFLOW_API_URL"], "http://127.0.0.1:8000/api")
        self.assertEqual(config["REMINDERS_ENABLED"], "1")

    def test_missing_secrets_leave_optional_bot_disabled(self):
        from scripts.configure_kujtesa_server import build_config
        config = build_config({"DISCORD_BOT_TOKEN": "mira-only"})
        self.assertEqual(config["KUJTESA_ENABLED"], "false")
        self.assertEqual(config["DISCORD_TOKEN"], "")
        self.assertEqual(config["REMINDERS_ENABLED"], "0")

    def test_partial_config_and_multiline_secrets_fail_without_echo(self):
        for changes in ({"GA_PERSONAL_DISCORD_BRIDGE_SECRET": ""}, {"KUJTESA_DISCORD_TOKEN": "secret\nINJECTED=1"},
                        {"KUJTESA_REMINDERS_ENABLED": "yes"}, {"KUJTESA_DISCORD_TOKEN": "${DISCORD_BOT_TOKEN}"}):
            with self.subTest(changes=list(changes)):
                with self.assertRaises(ValueError) as error:
                    self.config(**changes)
                self.assertNotIn("secret\n", str(error.exception))

    def test_disabled_configuration_explicitly_clears_delivery_switch(self):
        self.assertEqual(self.config(KUJTESA_ENABLED="false")["REMINDERS_ENABLED"], "0")

    def test_private_config_roundtrip_and_receipts_survive_reconfiguration(self):
        from scripts.configure_kujtesa_server import write_config
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            receipts = root / ".primeflow-receipts.json"
            receipts.write_text('{"pending":"preserve"}', encoding="utf-8")
            path = root / ".env"
            config = self.config()
            write_config(path, config)
            write_config(path, {**config, "REMINDERS_ENABLED": "0"})
            saved = dotenv_values(path, interpolate=False)
            self.assertEqual(saved["DISCORD_TOKEN"], config["DISCORD_TOKEN"])
            self.assertEqual(saved["REMINDERS_ENABLED"], "0")
            self.assertEqual(receipts.read_text(encoding="utf-8"), '{"pending":"preserve"}')
            self.assertEqual(path.read_text().count("DISCORD_TOKEN="), 1)

    def test_pm2_has_one_isolated_supervised_kujtesa_and_mira_is_preserved(self):
        backend = Path(__file__).resolve().parents[1]
        js = "const c=require('./ecosystem.config.cjs');console.log(JSON.stringify(c.apps.filter(a=>['primeflow-kujtesa','primeflow-discord'].includes(a.name))));"
        result = subprocess.run(["node", "-e", js], cwd=backend, capture_output=True, text=True, check=True)
        apps = {app["name"]: app for app in json.loads(result.stdout)}
        self.assertEqual(len(apps), 2)
        worker = apps["primeflow-kujtesa"]
        self.assertEqual(worker["args"], "integrations/kujtesa/primeflow_bot.py")
        self.assertEqual(worker["instances"], 1)
        self.assertEqual(worker["exec_mode"], "fork")
        self.assertTrue(worker["autorestart"])
        self.assertIn("PrimeFlowData", worker["env"]["KUJTESA_ENV_FILE"])
        self.assertNotIn("DISCORD_TOKEN", worker["env"])
        self.assertEqual(apps["primeflow-discord"]["args"], "discord_bot.py")

    def test_installed_runtime_reads_dedicated_file_and_persistent_state(self):
        import importlib.util
        backend = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("kujtesa_deploy_runtime", backend / "integrations/kujtesa/primeflow_bot.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            env = root / ".env"
            env.write_text('DISCORD_TOKEN="dedicated.example.token"\nPRIMEFLOW_GA_BRIDGE_KEY="'+'k'*48+'"\n', encoding="utf-8")
            with patch.dict(os.environ, {"KUJTESA_ENV_FILE": str(env), "KUJTESA_STATE_DIR": str(root)}, clear=True):
                module.load_env()
                self.assertEqual(os.environ["DISCORD_TOKEN"], "dedicated.example.token")
                self.assertEqual(module.runtime_paths()["receipts"], root / ".primeflow-receipts.json")


if __name__ == "__main__":
    unittest.main()
