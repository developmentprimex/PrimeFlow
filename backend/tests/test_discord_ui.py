import importlib.util
import json
import os
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/test")
os.environ.setdefault("JWT_SECRET", "discord-ui-test-secret")
AVAILABLE = importlib.util.find_spec("discord") is not None
if AVAILABLE:
    import discord
    import discord_ui as ui
    import discord_bot as bot


@unittest.skipUnless(AVAILABLE, "Install requirements-discord.txt")
class DiscordUiTests(unittest.IsolatedAsyncioTestCase):
    def task(self, text="Task\n1. [[done]][[added]]Point A[[/added]][[/done]]\n2. Point B"):
        return {"id": str(uuid.uuid4()), "title": text, "status": "IN_PROGRESS", "finish_period": "AM",
                "one_h_report_slot": "11:50", "progress_percentage": 40, "priority": "HIGH"}

    def detail(self, count=3):
        return {"task": self.task(), "fingerprint": "a" * 16,
                "title_points": [{"number": i + 1, "text": f"{i + 1}. [[added]]Point {i + 1}[[/added]]", "done": i % 3 == 0} for i in range(count)],
                "description_points": []}

    def test_five_cards_fit_discord_embed_budget_and_show_planning(self):
        tasks = [self.task("Title\n" + "Long point " * 1000) for _ in range(5)]
        cards = ui.overview_embeds(tasks, 0)
        self.assertEqual(len(cards), 5)
        self.assertLessEqual(sum(len(card) for card in cards), 6000)
        self.assertTrue(all(len(card.title) <= 256 and len(card.description) <= 4096 for card in cards))
        self.assertEqual(cards[0].fields[1].value, "1H 11:50 · AM")
        self.assertNotIn("[[", json.dumps([card.to_dict() for card in cards]))

    def test_detail_shows_completed_points_without_editor_markers(self):
        detail = self.detail()
        embed = ui.card(detail["task"], detail=detail)
        self.assertIn("✓ ~~", embed.description)
        self.assertIn("○ ", embed.description)
        self.assertNotIn("[[", embed.description)
        self.assertLessEqual(len(embed), 6000)

    def test_strike_picker_keeps_original_point_numbers_and_has_pagination(self):
        detail = self.detail(90)
        view = ui.points_view(detail, 1)
        selects = [item for item in view.children if isinstance(item, discord.ui.Select)]
        self.assertEqual(len(selects), 2)
        self.assertTrue(all(len(item.options) <= 25 and item.max_values <= 25 for item in selects))
        for item in selects:
            desired_done = item.custom_id.endswith(":1")
            for option in item.options:
                source = detail["title_points"][int(option.value) - 1]
                self.assertNotEqual(source["done"], desired_done)
        self.assertTrue(any(isinstance(item, discord.ui.Button) and item.label == "→" for item in view.children))

    def test_controls_persist_and_custom_ids_fit_discord(self):
        detail = self.detail()
        view = ui.controls(detail["task"]["id"], detail["fingerprint"], [("AI", "")])
        self.assertTrue(view.is_persistent())
        self.assertTrue(all(len(item.custom_id) <= 100 for item in view.children if item.custom_id))
        for row in range(5):
            items = [item for item in view.children if item.row == row]
            if any(isinstance(item, discord.ui.Select) for item in items):
                self.assertEqual(len(items), 1)
            else:
                self.assertLessEqual(len(items), 5)

    def test_edit_preserves_annotations_around_unchanged_text(self):
        original = "Task\n1. [[done]][[added]]Point A[[/added]][[/done]]\n2. Point B"
        changed = ui.preserve_markers(original, "Task renamed\n1. Point A\n2. Point B edited")
        self.assertIn("[[done]][[added]]Point A[[/added]][[/done]]", changed)
        self.assertIn("Point B edited", changed)
        self.assertEqual(ui.plain(changed), "Task renamed\n1. Point A\n2. Point B edited")

    async def test_metadata_edit_does_not_erase_title_strikes(self):
        client = SimpleNamespace(run_direct=AsyncMock())
        modal = ui.EditModal(client, self.detail())
        modal.inputs["progress_percentage"]._value = "75"
        interaction = SimpleNamespace(response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        await modal.on_submit(interaction)
        actions = client.run_direct.call_args.args[3]
        self.assertEqual(json.loads(actions[0]["arguments_json"]), {"progress_percentage": 75})

    async def test_completion_comment_is_submitted_with_done_without_ai(self):
        client = SimpleNamespace(run_direct=AsyncMock())
        modal = ui.CommentModal(client, str(uuid.uuid4()), "a" * 16, complete=True)
        modal.comment._value = "Rezultati u kontrollua."
        interaction = SimpleNamespace(response=SimpleNamespace(defer=AsyncMock()))
        await modal.on_submit(interaction)
        actions = client.run_direct.call_args.args[3]
        self.assertEqual([action["tool"] for action in actions], ["comment", "update_task"])
        self.assertEqual(json.loads(actions[1]["arguments_json"]), {"status": "DONE"})

    async def test_selected_points_route_to_exact_field_and_numbers(self):
        client = object.__new__(bot.PrimeFlowBot)
        client.run_direct = AsyncMock()
        task_id = str(uuid.uuid4())
        interaction = SimpleNamespace(type=discord.InteractionType.component,
            data={"custom_id": f"pf:pointset:{task_id}:{'a' * 16}:d:1", "values": ["2", "7"]},
            response=SimpleNamespace(defer=AsyncMock()))
        await client.on_interaction(interaction)
        arguments = json.loads(client.run_direct.call_args.args[3][0]["arguments_json"])
        self.assertEqual(arguments, {"field": "description", "numbers": [2, 7], "done": True})

    async def test_strike_result_updates_cached_card_instead_of_posting_another(self):
        client = object.__new__(bot.PrimeFlowBot)
        client.task_details, client.task_cards = {}, {}
        detail = self.detail()
        key = (123, 456, 789, detail["task"]["id"])
        existing = SimpleNamespace(edit=AsyncMock())
        client.task_cards[key] = existing
        interaction = SimpleNamespace(guild_id=123, channel_id=456, user=SimpleNamespace(id=789), message=None,
            followup=SimpleNamespace(send=AsyncMock()))
        await client.show_task(interaction, detail, notice="Pikat u përditësuan", update=True)
        existing.edit.assert_awaited_once()
        self.assertTrue(interaction.followup.send.call_args.kwargs["ephemeral"])
        self.assertEqual(client.task_details[key]["fingerprint"], detail["fingerprint"])


if __name__ == "__main__":
    unittest.main()
