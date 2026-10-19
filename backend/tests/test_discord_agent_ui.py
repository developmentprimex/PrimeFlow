import importlib
import importlib.util
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from tests.test_discord_agent_api import TASK, ACTOR, run_fixture
from app.services.discord_agents import serialize_run

import discord


class AgentUiTests(unittest.IsolatedAsyncioTestCase):
    def ui(self):
        self.assertIsNotNone(importlib.util.find_spec("discord_agent_ui"), "Agent UI missing")
        return importlib.import_module("discord_agent_ui")

    def client(self):
        self.assertIsNotNone(importlib.util.find_spec("discord_agent_client"), "Agent client missing")
        return importlib.import_module("discord_agent_client")

    def detail(self):
        return {"task": TASK, "fingerprint": "a"*16,
            "title_points": [{"number": n, "text": "• Same " + "x"*250, "done": False} for n in range(1, 91)],
            "description_points": [{"number": n, "text": "• Same", "done": False} for n in range(1, 32)]}

    def validate_view(self, view):
        ids = [item.custom_id for item in view.children if item.custom_id]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(len(value) <= 100 for value in ids))
        for child in view.children:
            if isinstance(child, discord.ui.Select):
                self.assertLessEqual(len(child.options), 25)
                self.assertTrue(all(1 <= len(o.label) <= 100 for o in child.options))
        self.assertTrue(view.is_persistent())

    async def test_target_pages_keep_original_numbers_and_unique_ids(self):
        ui = self.ui()
        numbers = set()
        for page in range(4):
            view = ui.target_view(self.detail(), page)
            self.validate_view(view)
            for child in view.children:
                if isinstance(child, discord.ui.Select) and child.custom_id.endswith(":t"):
                    numbers.update(int(option.value) for option in child.options)
        self.assertEqual(numbers, set(range(1, 91)))

    async def test_modes_and_result_controls_fit_discord(self):
        ui = self.ui()
        self.validate_view(ui.mode_view(TASK["id"], "a"*16, "description", 90))
        for status in ("QUEUED", "RUNNING", "READY", "FAILED", "CANCELLED"):
            self.validate_view(ui.run_view(serialize_run(run_fixture(status=status))))

    async def test_long_result_and_all_citations_survive_in_attachment_and_embeds(self):
        ui = self.ui()
        run = serialize_run(run_fixture(result_text="Përmbajtje ëç\n"*1200,
            sources=[{"title": "Source " + "x"*100, "url": f"https://example.com/{i}"} for i in range(80)]))
        message = ui.result_message(run)
        self.assertLessEqual(len(message["embed"]), 6000)
        content = message["file"].fp.read().decode("utf-8")
        self.assertIn(run["result_text"], content)
        for source in run["sources"]:
            self.assertIn(source["url"], content)
        source_text = "\n".join(embed.description for embed in message["source_embeds"])
        for source in run["sources"]: self.assertIn(source["url"], source_text)
        self.assertTrue(all(len(embed) <= 6000 for embed in message["source_embeds"]))

    async def test_instruction_modal_sends_exact_task_mode_target_and_version(self):
        ui = self.ui()
        bot = SimpleNamespace(private_channel=AsyncMock(), bridge=AsyncMock(return_value=serialize_run(run_fixture(status="QUEUED"))), error_message=lambda e: str(e))
        modal = ui.AgentInstructionModal(bot, TASK["id"], "a"*16, "RESEARCH", "description", 2)
        modal.instruction._value = "Find competitors"
        interaction = SimpleNamespace(id=1234, guild_id=123, channel_id=44, user=SimpleNamespace(id=12),
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        await modal.on_submit(interaction)
        path, payload = bot.bridge.call_args.args
        self.assertEqual(path, "/bot/agents/runs")
        self.assertEqual(payload["field"], "description")
        self.assertEqual(payload["number"], 2)
        self.assertEqual(payload["mode"], "RESEARCH")
        self.assertEqual(payload["expected_fingerprint"], "a"*16)

    async def test_revision_fetches_current_authorized_parent_and_creates_new_run(self):
        ui = self.ui()
        parent = serialize_run(run_fixture())
        from app.services.discord_agents import task_detail
        bot = SimpleNamespace(private_channel=AsyncMock(), bridge=AsyncMock(side_effect=[parent, task_detail(TASK), parent]), error_message=lambda e: str(e))
        modal = ui.AgentRevisionModal(bot, parent["id"])
        modal.instruction._value = "Add more details"
        interaction = SimpleNamespace(id=1234, guild_id=123, channel_id=44, user=SimpleNamespace(id=12),
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        await modal.on_submit(interaction)
        payload = bot.bridge.call_args.args[1]
        self.assertEqual(payload["parent_run_id"], parent["id"])
        self.assertEqual(payload["number"], 2)
        self.assertEqual(payload["instruction"], "Add more details")

    async def test_interaction_acceptance_refreshes_card_and_cancel_uses_backend(self):
        client = self.client()
        for action in ("accept", "strike", "cancel"):
            run = serialize_run(run_fixture())
            bot = SimpleNamespace(private_channel=AsyncMock(), bridge=AsyncMock(return_value={"run": run, "task_detail": self.detail()} if action in {"accept", "strike"} else run),
                show_task=AsyncMock(), error_message=lambda e: str(e))
            interaction = SimpleNamespace(id=1234, guild_id=123, channel_id=44, user=SimpleNamespace(id=12),
                data={"custom_id": f"pf:agent:{action}:{run['id']}"}, response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
            self.assertTrue(await client.handle_agent_interaction(bot, interaction))
            self.assertTrue(bot.bridge.call_args.args[0].endswith("/accept" if action in {"accept", "strike"} else "/cancel"))
            if action == "strike": bot.show_task.assert_awaited_once()

    async def test_delivery_uses_bot_auth_stable_nonce_and_privacy_before_read(self):
        client = self.client()
        run = serialize_run(run_fixture())
        job = {"run_id": run["id"], "lease_token": str(uuid.uuid4()), **ACTOR}
        channel = SimpleNamespace(id=44)
        bot = SimpleNamespace(private_channel=AsyncMock(return_value=channel), bridge=AsyncMock(side_effect=[{"jobs": [job]}, run, {"ok": True}]))
        with patch.object(client, "send_durable_result", AsyncMock(return_value=["100"])) as send:
            await client.deliver_agent_results(bot)
            await client.deliver_agent_results(SimpleNamespace(bridge=AsyncMock(return_value={"jobs": []})))
        send.assert_awaited_once_with(bot, channel, run)
        self.assertEqual(bot.bridge.call_args.args[1]["message_ids"], ["100"])
        bot.private_channel.assert_awaited_once()
        self.assertEqual(client.delivery_nonce(run["id"], 0), client.delivery_nonce(run["id"], 0))

    async def test_lost_ack_restart_finds_existing_bot_message_without_resending(self):
        client = self.client()
        run = serialize_run(run_fixture())
        message = SimpleNamespace(id=100, author=SimpleNamespace(id=99), embeds=[discord.Embed().set_footer(text=client.delivery_marker(run["id"], 0))])
        async def history(**kwargs): yield message
        bot = SimpleNamespace(user=SimpleNamespace(id=99), http=SimpleNamespace(send_message=AsyncMock()))
        channel = SimpleNamespace(id=44, history=history)
        ids = await client.send_durable_result(bot, channel, run)
        self.assertEqual(ids, ["100"])
        bot.http.send_message.assert_not_called()

    async def test_actual_bot_http_send_includes_enforced_nonce(self):
        client = self.client()
        run = serialize_run(run_fixture())
        async def history(**kwargs):
            if False: yield None
        bot = SimpleNamespace(user=SimpleNamespace(id=99), http=SimpleNamespace(send_message=AsyncMock(return_value={"id": "101"})))
        await client.send_durable_result(bot, SimpleNamespace(id=44, history=history), run)
        params = bot.http.send_message.call_args.kwargs["params"]
        self.assertIs(params.payload["enforce_nonce"], True)
        self.assertEqual(params.payload["nonce"], client.delivery_nonce(run["id"], 0))
        self.assertEqual(params.payload["allowed_mentions"], {"parse": []})

    async def test_task_card_exposes_agent_controls(self):
        self.ui()
        import discord_ui
        menu = next(item for item in discord_ui.controls(TASK["id"], "a"*16, "IN_PROGRESS").children if isinstance(item, discord.ui.Select))
        self.assertTrue(menu.custom_id.startswith("pf:more:"))
        self.assertTrue({"agent", "history"} <= {option.value for option in menu.options})
