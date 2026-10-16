import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from dotenv import dotenv_values
from scripts.configure_discord import build_config, write_config


class DiscordDeployTests(unittest.TestCase):
    def env(self):
        return {"DISCORD_BOT_TOKEN": "example.discord.token", "DISCORD_GUILD_ID": "1560234235715919932",
                "DISCORD_BRIDGE_SECRET": "x" * 43, "OPENAI_API_KEY": "example-openai-key"}

    def test_all_secrets_enable_chat_and_assistant(self):
        values = build_config(self.env())
        self.assertEqual(values["DISCORD_ASSISTANT_ENABLED"], "true")
        self.assertEqual(values["DISCORD_MESSAGE_CONTENT_ENABLED"], "true")

    def test_no_secrets_leave_deploy_disabled(self):
        self.assertEqual(build_config({})["DISCORD_ASSISTANT_ENABLED"], "false")

    def test_explicit_opt_out_is_supported(self):
        values = build_config({"DISCORD_ASSISTANT_ENABLED": "false", "DISCORD_BOT_TOKEN": "example"})
        self.assertEqual(values["DISCORD_ASSISTANT_ENABLED"], "false")

    def test_partial_secrets_fail_with_key_names_not_values(self):
        with self.assertRaises(ValueError) as error:
            build_config({"DISCORD_BOT_TOKEN": "example-secret-value"})
        self.assertIn("DISCORD_GUILD_ID", str(error.exception))
        self.assertNotIn("example-secret-value", str(error.exception))

    def test_openai_key_and_actual_server_id_are_required(self):
        for changes in ({"OPENAI_API_KEY": ""}, {"DISCORD_GUILD_ID": "PRIMEFLOW SERVER"}, {"DISCORD_BRIDGE_SECRET": "short"}):
            with self.assertRaises(ValueError):
                build_config({**self.env(), **changes})

    def test_env_injection_is_rejected(self):
        for secret in ("x" * 32 + "\nDISCORD_ASSISTANT_ENABLED=false", "x" * 32 + "${OTHER_KEY}"):
            with self.assertRaises(ValueError):
                build_config({**self.env(), "DISCORD_BRIDGE_SECRET": secret})

    def test_config_write_roundtrips_metacharacters_without_touching_existing_keys(self):
        values = build_config({**self.env(), "DISCORD_BRIDGE_SECRET": 'A&"B\\C' + "x" * 32})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("DATABASE_URL=unchanged\nDISCORD_BOT_TOKEN=old\n", encoding="utf-8")
            write_config(path, values)
            write_config(path, values)
            loaded = dotenv_values(path)
            self.assertEqual(loaded["DATABASE_URL"], "unchanged")
            self.assertEqual(loaded["DISCORD_BRIDGE_SECRET"], values["DISCORD_BRIDGE_SECRET"])
            self.assertEqual(path.read_text().count("DISCORD_BOT_TOKEN="), 1)

    def test_pm2_has_exactly_one_worker_and_uses_private_api(self):
        backend = Path(__file__).resolve().parents[1]
        script = "const c=require('./ecosystem.config.cjs'); console.log(JSON.stringify(c.apps.filter(a=>a.name==='primeflow-discord').map(a=>({args:a.args,instances:a.instances,mode:a.exec_mode,url:a.env.PRIMEFLOW_API_BASE_URL}))));"
        result = subprocess.run(["node", "-e", script], cwd=backend, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), [{"args": "discord_bot.py", "instances": 1, "mode": "fork", "url": "http://127.0.0.1:8000"}])

    def test_agent_model_and_all_discord_tests_reach_deploy(self):
        workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
        self.assertIn("DISCORD_AGENT_MODEL: ${{ vars.DISCORD_AGENT_MODEL }}", workflow)
        self.assertIn('unittest discover -s tests -p "test_discord*.py"', workflow)
        self.assertEqual(build_config(self.env())["DISCORD_AGENT_MODEL"], "gpt-6-luna")
        self.assertEqual(build_config({**self.env(), "DISCORD_AGENT_MODEL": "gpt-6-luna"})["DISCORD_AGENT_MODEL"], "gpt-6-luna")


if __name__ == "__main__":
    unittest.main()
