"""Single-message navigation and one-click slot reports. Never logs in."""
import importlib.util
import json
import os
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/test")
os.environ.setdefault("JWT_SECRET", "discord-flow-test-secret")
AVAILABLE = importlib.util.find_spec("discord") is not None
if AVAILABLE:
    import discord
    import discord_ui as ui
    import discord_bot as bot


def task(title="Task", status="IN_PROGRESS", **extra):
    return {"id": str(uuid.uuid4()), "title": title, "status": status, **extra}


def detail_of(item):
    return {"task": item, "fingerprint": "f" * 16, "title_points": [], "description_points": []}


@unittest.skipUnless(AVAILABLE, "Install requirements-discord.txt")
class SimpleFlowTests(unittest.IsolatedAsyncioTestCase):
    def click(self, custom_id="pf:x", values=None):
        return SimpleNamespace(type=discord.InteractionType.component, id=555, guild_id=1, channel_id=2, user=SimpleNamespace(id=3),
            data={"custom_id": custom_id, "values": values or []}, message=Mock(),
            response=SimpleNamespace(type=discord.InteractionResponseType.deferred_message_update, defer=AsyncMock(),
                is_done=Mock(return_value=True), send_modal=AsyncMock()),
            edit_original_response=AsyncMock(), followup=SimpleNamespace(send=AsyncMock()))

    def client(self):
        client = object.__new__(bot.PrimeFlowBot)
        client.task_details, client.task_cards = {}, {}
        client.private_channel = AsyncMock()
        return client

    def test_card_hides_title_only_point_and_shortens_long_text(self):
        item = task("STD OPEN AI API", "TODO", description="x", due_date="2026-10-19T07:00:00Z", one_h_report_slot="11:00")
        detail = {**detail_of(item), "title_points": [{"number": 1, "text": "1. STD OPEN AI API", "done": False}],
                  "description_points": [{"number": n, "text": f"{n}. " + "word " * 80, "done": False} for n in range(1, 12)]}
        embed = ui.card(item, detail=detail)
        self.assertTrue(embed.description.startswith("🟣 To Do · Sloti 11:00 · Afati 19.10"))
        self.assertNotIn("Pikat e titullit", embed.description)
        self.assertIn("11. ⬜ word", embed.description)
        self.assertNotIn("%", embed.description)
        self.assertIn("Teksti i plotë", embed.description)
        self.assertEqual(len(embed.fields), 0)
        self.assertIn("11. ⬜ " + "word " * 10, ui.full_text(item, detail))

    def test_struck_points_are_all_visible_with_strike_time_and_count(self):
        item = task("Heading", "IN_PROGRESS", description="d")
        detail = {**detail_of(item), "description_points": [
            {"number": n, "text": f"{n}. Point {n}" + (" 14:20 16.10" if n % 2 else ""), "done": bool(n % 2)} for n in range(1, 21)]}
        embed = ui.card(item, detail=detail)
        self.assertIn("☑ 10/20 pika", embed.description.splitlines()[0])
        self.assertIn("19. ✅ ~~Point 19~~ · 🕘 14:20 16.10", embed.description)
        self.assertIn("20. ⬜ Point 20", embed.description)
        self.assertNotIn("pika të tjera", embed.description)

    async def test_pink_todo_circle_is_uploaded_once_and_used_everywhere(self):
        client = object.__new__(bot.PrimeFlowBot)
        original = dict(ui.STATUS_ICONS)
        try:
            client.fetch_application_emojis = AsyncMock(return_value=[])
            client.create_application_emoji = AsyncMock(return_value="<:pf_todo:42>")
            await client.ensure_status_emojis()
            image = client.create_application_emoji.call_args.kwargs["image"]
            self.assertTrue(image.startswith(b"\x89PNG"))
            self.assertIn("`1.` <:pf_todo:42> A", ui.list_view([task("A", "TODO")], "Sot")[0])
            client.fetch_application_emojis = AsyncMock(return_value=[SimpleNamespace(name="pf_todo", __str__=None)])
            client.create_application_emoji.reset_mock()
            await client.ensure_status_emojis()
            client.create_application_emoji.assert_not_called()
            self.assertEqual(ui.status_text("DONE"), "🟢 E kryer")
        finally:
            ui.STATUS_ICONS.clear()
            ui.STATUS_ICONS.update(original)

    def test_buttons_follow_status(self):
        def labels(status):
            return [item.label for item in ui.controls(str(uuid.uuid4()), "f" * 16, status).children if item.row == 0]
        self.assertEqual(labels("TODO")[:2], ["▶ Fillo", "✅ Mbylle"])
        self.assertEqual(labels("IN_PROGRESS")[:2], ["✅ Mbylle", "⏸ WFE"])
        menu = next(item for item in ui.controls(str(uuid.uuid4()), "f" * 16, "TODO").children if isinstance(item, discord.ui.Select))
        values = [option.value for option in menu.options]
        self.assertNotIn("todo", values)
        self.assertNotIn("progress", values)
        self.assertIn("wfe", values)

    async def test_closing_opens_next_task_in_same_message(self):
        first, second = task("First"), task("Second")
        client = self.client()
        client.bridge = AsyncMock(side_effect=lambda path, payload: {
            "/bot/command": {"status": "DONE", "message": "ok", "task": {**first, "status": "DONE"}, "fingerprint": "e" * 16},
            "/bot/select": detail_of(second)}.get(path) or {"tasks": [first, second] if not client.closed else [second]})
        client.closed = False
        original_apply = client.apply

        async def apply(*args, **kwargs):
            result = await original_apply(*args, **kwargs)
            client.closed = True
            return result
        client.apply = apply
        interaction = self.click()
        await client.quick(interaction, first["id"], "f" * 16, "done")
        interaction.response.defer.assert_awaited_once_with()
        kwargs = interaction.edit_original_response.call_args.kwargs
        self.assertIn("U mbyll: First", kwargs["content"])
        self.assertEqual(kwargs["embed"].title, "Second")
        interaction.followup.send.assert_not_called()

    async def test_out_of_date_card_still_changes_status_with_fresh_version(self):
        item = task("A", "TODO")
        client = self.client()
        sent = []

        async def bridge(path, payload):
            if path == "/bot/select":
                return {**detail_of(item), "fingerprint": "1" * 16}
            sent.append(payload)
            return {"status": "DONE", "message": "ok", "task": {**item, "status": "IN_PROGRESS"}, "fingerprint": "2" * 16}
        client.bridge = bridge
        interaction = self.click()
        await client.quick(interaction, item["id"], "0" * 16, "progress")
        self.assertEqual(sent[0]["expected_fingerprint"], "1" * 16)
        self.assertIn("🟡", interaction.edit_original_response.call_args.kwargs["embed"].description)

    def test_report_summary_uses_singular_forms(self):
        self.assertEqual(ui.report_summary("10:00", [1, 1, 0, 1]), "✓ **Sloti 10:00 u raportua** · 1 e kryer · 1 vazhdon · 1 e kaluar")
        self.assertIn("2 vazhdojnë", ui.report_summary("10:00", [0, 2, 0, 0]))

    async def test_refused_close_stays_on_card_with_hint(self):
        item = task("Needs comment")
        client = self.client()
        client.bridge = AsyncMock(side_effect=lambda path, payload: {
            "/bot/command": {"status": "QUESTION", "message": "Kërkohet komenti i përfundimit."},
            "/bot/select": detail_of(item)}.get(path) or {"tasks": [item]})
        interaction = self.click()
        await client.quick(interaction, item["id"], "f" * 16, "done")
        kwargs = interaction.edit_original_response.call_args.kwargs
        self.assertIn("Kërkohet komenti", kwargs["content"])
        self.assertIn("Mbylle me koment", kwargs["content"])
        self.assertEqual(kwargs["embed"].title, "Needs comment")

    async def test_next_wraps_and_list_returns_numbered_buttons(self):
        items = [task("A"), task("B")]
        client = self.client()
        client.bridge = AsyncMock(side_effect=lambda path, payload: detail_of(next(i for i in items if i["id"] == payload["task_id"]))
            if path == "/bot/select" else {"tasks": items})
        interaction = self.click()
        await client.navigate(interaction, items[1]["id"], "next")
        self.assertEqual(interaction.edit_original_response.call_args.kwargs["embed"].title, "A")
        await client.navigate(interaction, items[1]["id"], "list")
        kwargs = interaction.edit_original_response.call_args.kwargs
        self.assertIsNone(kwargs["embed"])
        self.assertEqual([item.label for item in kwargs["view"].children], ["1", "2"])

    async def test_more_menu_routes_agent_to_existing_flow(self):
        client = self.client()
        item_id = str(uuid.uuid4())
        interaction = self.click(f"pf:more:{item_id}:{'f' * 16}", ["agent"])
        handler = AsyncMock()
        original, bot.agent_client.handle_agent_interaction = bot.agent_client.handle_agent_interaction, handler
        try:
            await client.on_interaction(interaction)
        finally:
            bot.agent_client.handle_agent_interaction = original
        self.assertEqual(handler.call_args.args[2], f"pf:agent:targets:{item_id}:{'f' * 16}")

    def test_slot_reminder_calls_people_into_the_1h_meeting(self):
        url = bot.PrimeFlowBot.one_h_url("11:00", 1493866119700807722)
        self.assertEqual(url, "https://discord.com/channels/1493866119700807722/1493866120338477119")
        self.assertIsNone(bot.PrimeFlowBot.one_h_url("AM", 1))
        content, view = ui.report_intro("11:00", [task("A")], str(uuid.uuid4()), "3", join_url=url)
        self.assertIn("Takimi 1H fillon në 11:00", content)
        button = next(item for item in view.children if getattr(item, "url", None))
        self.assertEqual((button.label, button.url, button.row), ("🎧 Kyçu në takimin 1H", url, 0))
        content, view = ui.report_intro("PM", [task("A")], str(uuid.uuid4()), "3")
        self.assertNotIn("1H", content)
        self.assertFalse(any(getattr(item, "url", None) for item in view.children))

    def test_report_controls_fit_discord_and_mention_user(self):
        rid = str(uuid.uuid4())
        items = [task(f"T{n}") for n in range(30)]
        content, view = ui.report_intro("11:00", items, rid, "123")
        self.assertTrue(content.startswith("<@123> ⏰ **Sloti 11:00** · 30 detyra"))
        self.assertLessEqual(len(content), 2000)
        self.assertLessEqual(len(view.children[1].options), 25)
        _, _, step = ui.report_step("PM", items[0], rid, [99, 99, 99, 99], 1, 30)
        self.assertTrue(all(len(item.custom_id) <= 100 for item in [*view.children, *step.children]))

    async def test_report_step_applies_status_and_moves_on_then_summarises(self):
        rid, items = str(uuid.uuid4()), [task("A", "TODO"), task("B")]
        client = self.client()
        calls = []

        async def bridge(path, payload):
            calls.append((path, payload))
            if path.startswith("/bot/reminders/"):
                return {"tasks": items, "bucket": "11:00"}
            if path == "/bot/select":
                return detail_of(items[0])
            return {"status": "DONE", "message": "ok"}
        client.bridge = bridge
        interaction = self.click()
        await client.report(interaction, uuid.UUID(rid).hex, uuid.UUID(items[0]["id"]).hex, "0.0.0.0", "cont")
        command = next(payload for path, payload in calls if path == "/bot/command")
        self.assertEqual(json.loads(command["direct_actions"][0]["arguments_json"]), {"status": "IN_PROGRESS"})
        kwargs = interaction.edit_original_response.call_args.kwargs
        self.assertEqual(kwargs["content"], "⏰ **Sloti 11:00** · 2/2")
        self.assertEqual(kwargs["embed"].title, "B")
        self.assertTrue(kwargs["view"].children[0].custom_id.endswith(":0.1.0.0:done"))
        calls.clear()
        # B is already in progress: "Vazhdon" needs no write.
        await client.report(interaction, uuid.UUID(rid).hex, uuid.UUID(items[1]["id"]).hex, "0.1.0.0", "cont")
        self.assertFalse(any(path == "/bot/command" for path, _ in calls))
        self.assertIn("2 vazhdojnë", interaction.edit_original_response.call_args.kwargs["content"])

    async def test_refused_report_close_keeps_the_step(self):
        rid, item = str(uuid.uuid4()), task("A")
        client = self.client()
        client.bridge = AsyncMock(side_effect=lambda path, payload: {"tasks": [item], "bucket": "PM"} if path.startswith("/bot/reminders/")
            else detail_of(item) if path == "/bot/select" else {"status": "QUESTION", "message": "Kërkohet koment."})
        interaction = self.click()
        await client.report(interaction, uuid.UUID(rid).hex, uuid.UUID(item["id"]).hex, "0.0.0.0", "done")
        interaction.edit_original_response.assert_not_called()
        self.assertTrue(interaction.followup.send.call_args.kwargs["ephemeral"])

    async def test_bulk_done_uses_distinct_request_ids(self):
        rid, items = str(uuid.uuid4()), [task("A"), task("B"), task("C")]
        client = self.client()
        requests = []

        async def bridge(path, payload):
            if path.startswith("/bot/reminders/"):
                return {"tasks": items if not requests else items[2:], "bucket": "AM"}
            if path == "/bot/select":
                return detail_of(items[0])
            requests.append(payload["request_id"])
            return {"status": "DONE", "message": "ok"}
        client.bridge = bridge
        interaction = self.click()
        await client.report_done(interaction, uuid.UUID(rid).hex, [items[0]["id"], items[1]["id"]])
        self.assertEqual(requests, ["55500", "55501"])
        content = interaction.edit_original_response.call_args.kwargs["content"]
        self.assertIn("U mbyllën 2", content)
        self.assertIn("1 detyra", content)

    async def test_empty_reminder_sends_nothing_and_slot_report_stays_available(self):
        client = self.client()
        client._connection = SimpleNamespace(user=SimpleNamespace(id=99))
        old = SimpleNamespace(author=SimpleNamespace(id=99), components=[object()], edit=AsyncMock())
        channel = SimpleNamespace(id=2, fetch_message=AsyncMock(return_value=old))
        client.private_channel = AsyncMock(return_value=channel)
        acks = []

        async def bridge(path, payload):
            if path == "/bot/reminders/claim":
                return {"jobs": [{"id": str(uuid.uuid4()), "bucket": "PM", "discord_user_id": "3", "guild_id": "1", "channel_id": "2",
                                  "previous": {"bucket": "16:00", "message_ids": ["77"]}}]}
            if path.endswith("/ack"):
                acks.append(payload["message_ids"])
                return {"ok": True}
            return {"tasks": [], "bucket": "PM"}
        client.bridge = bridge
        client.http = SimpleNamespace(request=AsyncMock())
        await bot.PrimeFlowBot.reminders.coro(client)
        client.http.request.assert_not_called()
        self.assertEqual(acks, [[]])
        old.edit.assert_not_awaited()
        await client.retire_reminder(channel, {'bucket': 'AM', 'message_ids': ['77']})
        self.assertIn('Raportimi AM', old.edit.call_args.kwargs['content'])
        self.assertIsNone(old.edit.call_args.kwargs['view'])


if __name__ == "__main__":
    unittest.main()
