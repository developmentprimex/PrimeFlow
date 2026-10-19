"""Free chat messages find the task the person means. Never logs in or calls AI."""
import importlib.util
import os
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/test")
os.environ.setdefault("JWT_SECRET", "discord-chat-test-secret")

from app.api.routers import discord_assistant as api
from app.services import discord_task_tools as tools

AVAILABLE = importlib.util.find_spec("discord") is not None
if AVAILABLE:
    import discord_bot as bot
    import discord_ui as ui


def task(title, status="TODO"):
    return {"id": str(uuid.uuid4()), "title": title, "status": status}


def payload(text, context=None):
    return api.Command(discord_user_id="12", guild_id="123", channel_id="44", request_id="1", instruction=text,
                       context_task_ids=[uuid.UUID(item["id"]) for item in context or []])


class ChooseTaskTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.link = SimpleNamespace(selected_task_id=None, pending_instruction=None)

    async def choose(self, text, today, context=None, answer=None):
        chooser = AsyncMock(return_value=answer or tools.TaskChoice(ref=None, question="Cilën?"))
        with patch.object(api, "daily_tasks", AsyncMock(return_value=today)), patch.object(tools, "choose_task", chooser):
            result = await api.choose_task(None, self.link, SimpleNamespace(), payload(text, context))
        return result, chooser

    async def test_single_task_needs_no_ai(self):
        only = task("EF/RA: 2 ASC- TICKET SYSTEM")
        (task_id, question), chooser = await self.choose("mbylle këtë detyrë", [only])
        self.assertEqual((str(task_id), question), (only["id"], None))
        chooser.assert_not_called()

    async def test_shown_tasks_come_first_with_the_numbers_the_person_sees(self):
        a, b, c = task("A"), task("[[done]]B[[/done]]\n1. point"), task("C")
        (task_id, _), chooser = await self.choose("detyra 2: strike piken 1", [a, b, c], context=[c, b],
                                                  answer=tools.TaskChoice(ref=2, question=None))
        candidates = chooser.call_args.args[1]
        self.assertEqual([(item["title"], item["shown_number"]) for item in candidates], [("C", 1), ("B", 2), ("A", None)])
        self.assertEqual(str(task_id), b["id"])

    async def test_unclear_message_asks_and_keeps_request_for_the_answer(self):
        today = [task("A"), task("B")]
        (task_id, question), _ = await self.choose("mbylle", today)
        self.assertIsNone(task_id)
        self.assertEqual(question, "Cilën?")
        self.link.pending_instruction = api.CHOICE_MARK + "\nmbylle\nPyetja: Cilën?"
        _, chooser = await self.choose("B", today, answer=tools.TaskChoice(ref=2, question=None))
        self.assertIn("mbylle", chooser.call_args.args[2])

    async def test_short_answer_sees_the_bots_question_about_the_selected_task(self):
        asked, other = task("REMPP KUCHEN"), task("ZHV")
        self.link.selected_task_id = uuid.UUID(asked["id"])
        self.link.pending_instruction = "mbylle detyren per rempp\nPyetja: Kush e konfirmon?"
        _, chooser = await self.choose("Elsa", [other, asked], context=[other])
        candidates, history = chooser.call_args.args[1], chooser.call_args.args[2]
        self.assertIn("Kush e konfirmon?", history)
        self.assertEqual([item["title"] for item in candidates if item["selected"]], ["REMPP KUCHEN"])

    async def test_unknown_ref_from_ai_becomes_a_question(self):
        with patch.object(tools, "_structured", AsyncMock(return_value=tools.TaskChoice(ref=9, question=None))):
            choice = await tools.choose_task("x", [{"ref": 1}, {"ref": 2}])
        self.assertIsNone(choice.ref)
        self.assertTrue(choice.question)


def done_plan(*extra):
    import json
    return tools.TaskPlan(question=None, actions=[tools.ToolAction(tool=name, arguments_json=json.dumps(args))
                                                  for name, args in (*extra, ("update_task", {"status": "DONE"}))])


class ClosingTests(unittest.TestCase):
    def operations(self, task, plan):
        from datetime import datetime, timezone
        return tools.compile_actions(tools.with_closing_steps(plan, task), task, [], [], "mbylle", datetime(2026, 10, 19, 9, tzinfo=timezone.utc))

    def test_close_strikes_every_open_point_and_comments_kryer(self):
        item = {"id": str(uuid.uuid4()), "title": "REMPP KUCHEN", "description": "1. [[done]]A[[/done]]\n2. B\n3. C", "user_comment": None}
        operations = self.operations(item, done_plan())
        self.assertEqual([op["path"].rsplit("/", 1)[-1] for op in operations], ["comment", item["id"]])
        self.assertEqual(operations[0]["body"]["comment"], "Kryer")
        body = operations[1]["body"]
        self.assertEqual(body["status"], "DONE")
        self.assertEqual([point["done"] for point in tools.text_points(body["description"], "description")], [True, True, True])
        self.assertNotIn("title", body)  # A one-line title is the task name, never struck.

    def test_title_heading_is_never_struck_only_the_steps_below_it(self):
        title = "KI-AUFTRAGSBEARBEITUNG: PRIMEX & REMPP KUCHEN\nME KUZHINA:\nCLAIMS,\nORDER PROCESSING"
        item = {"id": str(uuid.uuid4()), "title": title, "description": title, "user_comment": "ok"}
        body = self.operations(item, done_plan())[0]["body"]
        self.assertEqual([p["done"] for p in tools.text_points(body["title"], "title")], [False, True, True, True])
        self.assertTrue(body["title"].startswith("KI-AUFTRAGSBEARBEITUNG: PRIMEX & REMPP KUCHEN\n"))
        numbered = {"id": str(uuid.uuid4()), "title": "Heading\n1. A\n2. B", "description": "", "user_comment": "ok"}
        body = self.operations(numbered, done_plan())[0]["body"]
        self.assertTrue(body["title"].startswith("Heading\n"))
        self.assertEqual([p["done"] for p in tools.text_points(body["title"], "title")], [True, True])

    def test_existing_or_given_comment_is_not_replaced(self):
        item = {"id": str(uuid.uuid4()), "title": "T", "description": "", "user_comment": "U dërgua te klienti"}
        self.assertFalse(any(op["path"].endswith("/comment") for op in self.operations(item, done_plan())))
        item["user_comment"] = None
        operations = self.operations(item, done_plan(("comment", {"comment": "Rezultati"})))
        self.assertEqual([op["body"]["comment"] for op in operations if op["path"].endswith("/comment")], ["Rezultati"])

    def test_px_note_points_are_struck_before_the_task_is_closed(self):
        content = "Heading\n1. A\n2. B"
        item = {"id": str(uuid.uuid4()), "title": content, "description": content, "user_comment": "ok",
                "_px_note": {"collection": "ga-notes", "id": str(uuid.uuid4()), "content": content}}
        operations = self.operations(item, done_plan())
        self.assertEqual([op["label"] for op in operations], ["Strike u ruajt në PX Notes", "Detyra dhe pikat u përditësuan"])
        self.assertEqual([p["done"] for p in tools.text_points(operations[0]["body"]["content"], "title")], [True, True])

    def test_other_status_changes_are_untouched(self):
        import json
        plan = tools.TaskPlan(question=None, actions=[tools.ToolAction(tool="update_task", arguments_json=json.dumps({"status": "TODO"}))])
        self.assertIs(tools.with_closing_steps(plan, {"title": "T", "description": "1. A"}), plan)


@unittest.skipUnless(AVAILABLE, "Install requirements-discord.txt")
class ContextTests(unittest.IsolatedAsyncioTestCase):
    def test_reminder_list_and_card_task_ids_keep_display_order(self):
        items = [task("A"), task("B")]
        _, reminder = ui.report_intro("11:00", items, str(uuid.uuid4()), "3", join_url="https://discord.com/channels/1/2")
        _, listing = ui.list_view(list(reversed(items)), "Sot")
        card = ui.controls(items[0]["id"], "f" * 16, "TODO")
        for view, expected in ((reminder, [items[0]["id"], items[1]["id"]]), (listing, [items[1]["id"], items[0]["id"]]), (card, [items[0]["id"]])):
            self.assertEqual(bot.task_ids_in(SimpleNamespace(components=[SimpleNamespace(children=view.children)])), expected)

    async def test_reply_uses_the_replied_message_before_recent_history(self):
        client = object.__new__(bot.PrimeFlowBot)
        client._connection = SimpleNamespace(user=SimpleNamespace(id=99))
        replied_task = task("Replied")
        replied = SimpleNamespace(author=SimpleNamespace(id=99),
            components=[SimpleNamespace(children=ui.controls(replied_task["id"], "f" * 16, "TODO").children)])
        message = SimpleNamespace(reference=SimpleNamespace(message_id=5, resolved=None),
            channel=SimpleNamespace(fetch_message=AsyncMock(return_value=replied)))
        with patch.object(bot.discord, "Message", SimpleNamespace):
            self.assertEqual(await client.context_task_ids(message), [replied_task["id"]])

    async def test_chat_result_is_shown_as_the_updated_card(self):
        client = object.__new__(bot.PrimeFlowBot)
        item = {**task("Done task", "DONE"), "progress_percentage": 0}
        channel = SimpleNamespace(id=44, send=AsyncMock(), typing=lambda: AsyncNullContext())
        client.private_channel = AsyncMock(return_value=channel)
        client.context_task_ids = AsyncMock(return_value=[item["id"]])
        client.bridge = AsyncMock(return_value={"status": "DONE", "message": "Statusi: DONE", "task": item, "fingerprint": "a" * 16,
                                                "title_points": [], "description_points": []})
        message = SimpleNamespace(id=7, content="mbylle këtë detyrë", author=SimpleNamespace(id=12, bot=False),
            guild=SimpleNamespace(id=123), channel=SimpleNamespace(id=44, topic="PrimeFlow personal workspace: 12"))
        with patch.object(bot.settings, "DISCORD_MESSAGE_CONTENT_ENABLED", True), patch.object(bot.settings, "DISCORD_GUILD_ID", "123"):
            await client.on_message(message)
        self.assertEqual(client.bridge.call_args.args[1]["context_task_ids"], [item["id"]])
        kwargs = channel.send.call_args.kwargs
        self.assertEqual(kwargs["embed"].title, "Done task")
        self.assertTrue(channel.send.call_args.args[0].startswith("✓ "))


class AsyncNullContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


if __name__ == "__main__":
    unittest.main()
