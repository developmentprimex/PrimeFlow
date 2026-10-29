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

    def test_dedicated_keys_roundtrip_and_missing_role_keys_never_borrow_general(self):
        role_keys = {'MIRA_NOTES_OPENAI_API_KEY': 'notes&"test\\value',
                     'MIRA_HOST_OPENAI_API_KEY': 'host-test', 'KUJTESA_OPENAI_API_KEY': 'family-test'}
        values = build_config({**self.env(), **role_keys})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            write_config(path, values)
            loaded = dotenv_values(path, interpolate=False)
            for key, value in role_keys.items():
                self.assertEqual(loaded[key], value)
            write_config(path, build_config(self.env()))
            self.assertTrue(all(dotenv_values(path)[key] == '' for key in role_keys))

    def test_dedicated_key_injection_is_rejected_without_exposing_value(self):
        for key in ('MIRA_NOTES_OPENAI_API_KEY', 'MIRA_HOST_OPENAI_API_KEY', 'KUJTESA_OPENAI_API_KEY',
                    'GA_PERSONAL_DISCORD_BRIDGE_SECRET'):
            for value in ('private\nOTHER=bad', 'private${OTHER}'):
                with self.subTest(key=key), self.assertRaises(ValueError) as error:
                    build_config({**self.env(), key: value})
                self.assertNotIn('private', str(error.exception))

    def test_private_host_server_settings_are_opt_in_and_do_not_enable_work_bot(self):
        default = build_config({})
        self.assertEqual(default['KUJTESA_HOST_ENABLED'], 'false')
        enabled = build_config({'KUJTESA_HOST_ENABLED': 'true', 'KUJTESA_HOST_MODEL': 'test-realtime',
                                'KUJTESA_HOST_VOICE': 'marin', 'KUJTESA_OPENAI_API_KEY': 'family-test',
                                'GA_PERSONAL_ENABLED': 'true', 'GA_PERSONAL_DISCORD_BRIDGE_SECRET': 'bridge-test' * 4})
        self.assertEqual(enabled['KUJTESA_HOST_ENABLED'], 'true')
        self.assertEqual(enabled['KUJTESA_HOST_MODEL'], 'test-realtime')
        self.assertEqual(enabled['DISCORD_ASSISTANT_ENABLED'], 'false')
        with self.assertRaises(ValueError):
            build_config({'KUJTESA_HOST_ENABLED': 'yes'})

    def test_enabling_each_role_requires_its_own_key(self):
        cases = [({'DISCORD_MEETING_NOTES_ENABLED': 'true'}, 'MIRA_NOTES_OPENAI_API_KEY'),
                 ({'MIRA_HOST_ENABLED': 'true', 'MIRA_HOST_BOT_TOKEN': 'host-bot-test'}, 'MIRA_HOST_OPENAI_API_KEY'),
                 ({'KUJTESA_HOST_ENABLED': 'true', 'GA_PERSONAL_ENABLED': 'true',
                   'GA_PERSONAL_DISCORD_BRIDGE_SECRET': 'bridge-test' * 4}, 'KUJTESA_OPENAI_API_KEY')]
        for options, required_key in cases:
            with self.subTest(role=required_key):
                with self.assertRaisesRegex(ValueError, required_key):
                    build_config({**self.env(), **options})
                self.assertEqual(build_config({**self.env(), **options, required_key: 'dedicated-test'})[required_key],
                                 'dedicated-test')

    def test_family_bridge_roundtrips_safely_and_replaces_old_settings(self):
        secret = 'bridge&"test\\value' + 'x' * 32
        values = build_config({'GA_PERSONAL_ENABLED': 'true', 'GA_PERSONAL_DISCORD_BRIDGE_SECRET': secret,
                               'KUJTESA_HOST_ENABLED': 'true', 'KUJTESA_OPENAI_API_KEY': 'family-test'})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('DATABASE_URL=unchanged\nGA_PERSONAL_ENABLED=false\nGA_PERSONAL_DISCORD_BRIDGE_SECRET=old\n',
                            encoding='utf-8')
            write_config(path, values)
            write_config(path, values)
            loaded = dotenv_values(path, interpolate=False)
            self.assertEqual(loaded['GA_PERSONAL_ENABLED'], 'true')
            self.assertEqual(loaded['GA_PERSONAL_DISCORD_BRIDGE_SECRET'], secret)
            self.assertEqual(loaded['DATABASE_URL'], 'unchanged')
            self.assertEqual(path.read_text().count('GA_PERSONAL_DISCORD_BRIDGE_SECRET='), 1)

    def test_family_host_requires_family_module_and_private_bridge(self):
        base = {'KUJTESA_HOST_ENABLED': 'true', 'KUJTESA_OPENAI_API_KEY': 'family-test'}
        cases = [({'GA_PERSONAL_ENABLED': 'false', 'GA_PERSONAL_DISCORD_BRIDGE_SECRET': 'bridge-test' * 4},
                  'GA_PERSONAL_ENABLED'),
                 ({'GA_PERSONAL_ENABLED': 'true'}, 'GA_PERSONAL_DISCORD_BRIDGE_SECRET'),
                 ({'GA_PERSONAL_ENABLED': 'true', 'GA_PERSONAL_DISCORD_BRIDGE_SECRET': 'short-private'},
                  'GA_PERSONAL_DISCORD_BRIDGE_SECRET')]
        for options, required in cases:
            with self.subTest(required=required):
                with self.assertRaisesRegex(ValueError, required) as error:
                    build_config({**base, **options})
                self.assertNotIn('short-private', str(error.exception))

    def test_family_off_does_not_require_private_bridge(self):
        defaults = build_config({})
        self.assertEqual(defaults['GA_PERSONAL_ENABLED'], 'false')
        self.assertEqual(defaults['GA_PERSONAL_DISCORD_BRIDGE_SECRET'], '')
        self.assertEqual(build_config({'GA_PERSONAL_ENABLED': 'false'})['KUJTESA_HOST_ENABLED'], 'false')
        with self.assertRaisesRegex(ValueError, 'GA_PERSONAL_ENABLED'):
            build_config({'GA_PERSONAL_ENABLED': 'sometimes'})

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
