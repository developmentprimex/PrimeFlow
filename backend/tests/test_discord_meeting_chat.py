"""Creating TAK INT / TAK EXT meetings from Discord chat. Never logs in or calls AI."""
import importlib.util
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/test")
os.environ.setdefault("JWT_SECRET", "discord-meeting-chat-secret")

from fastapi import HTTPException

from app.api.routers import discord_assistant as api
from app.services import discord_task_tools as tools

AVAILABLE = importlib.util.find_spec("discord") is not None
if AVAILABLE:
    import discord_bot as bot
    import discord_ui as ui

ME, ENDI, RINESA = (str(uuid.uuid4()) for _ in range(3))
DEPARTMENT = uuid.uuid4()
PEOPLE = [{"id": ME, "full_name": "Laurent Hoxha", "username": "lh", "department_id": str(DEPARTMENT)},
          {"id": ENDI, "full_name": "Endi Hyseni", "username": "eh", "department_id": str(DEPARTMENT)},
          {"id": RINESA, "full_name": "Rinesa Ahmedi", "username": "ra", "department_id": str(DEPARTMENT)}]
TOMORROW = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)


def draft(**changes):
    values = {"is_meeting_request": True, "question": None, "title": None, "meeting_type": "internal",
              "starts_at": TOMORROW.isoformat(), "platform": None, "meeting_url": None, "participant_ids": [ME, ENDI, RINESA]}
    return tools.MeetingDraft(**{**values, **changes})


def command(text, request_id="555"):
    return api.Command(discord_user_id="12", guild_id="123", channel_id="44", request_id=request_id, instruction=text)


class MeetingDraftTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.link = SimpleNamespace(id=uuid.uuid4(), pending_instruction=None, selected_task_id=None)
        self.user = SimpleNamespace(id=uuid.UUID(ME), full_name="Laurent Hoxha", department_id=DEPARTMENT)
        self.added = []
        self.db = SimpleNamespace(add=self.added.append, commit=AsyncMock())

    async def reply(self, text, answer):
        with patch.object(tools, "user_api", AsyncMock(return_value=PEOPLE)), \
             patch.object(tools, "draft_meeting", AsyncMock(return_value=answer)) as drafter:
            return await api.meeting_draft_reply(self.db, self.link, self.user, command(text)), drafter

    async def test_complete_request_becomes_a_draft_to_confirm(self):
        reply, _ = await self.reply("krijo tak int per neser ora 15 me une, endi, rinesa", draft())
        self.assertEqual(reply["status"], "MEETING_DRAFT")
        self.assertEqual(reply["meeting"]["participants"], ["Laurent Hoxha", "Endi Hyseni", "Rinesa Ahmedi"])
        self.assertEqual(reply["meeting"]["title"], "TAK INT")
        stored = self.added[0]
        self.assertEqual((stored.id, stored.status, stored.task_id), ("555", "MEETING_DRAFT", None))
        self.assertEqual(stored.result["meeting"]["department_id"], str(DEPARTMENT))
        self.assertEqual(stored.result["meeting"]["participant_ids"], [ME, ENDI, RINESA])

    async def test_missing_time_is_asked_and_the_answer_continues_the_draft(self):
        reply, _ = await self.reply("krijo tak int me endi", draft(question="Në çfarë ore?", starts_at=None))
        self.assertEqual(reply, {"message": "Në çfarë ore?", "status": "QUESTION"})
        self.assertTrue(self.link.pending_instruction.startswith(api.MEETING_MARK))
        self.assertEqual(self.added, [])
        _, drafter = await self.reply("ora 15", draft())
        self.assertIn("krijo tak int me endi", drafter.call_args.args[3])

    async def test_unknown_person_or_past_time_never_reaches_a_draft(self):
        reply, _ = await self.reply("krijo tak", draft(participant_ids=[str(uuid.uuid4())]))
        self.assertEqual(reply["status"], "QUESTION")
        reply, _ = await self.reply("krijo tak", draft(starts_at=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()))
        self.assertIn("ka kaluar", reply["message"])
        self.assertEqual(self.added, [])

    async def test_other_messages_fall_back_to_tasks(self):
        self.link.pending_instruction = api.MEETING_MARK + "old"
        reply, _ = await self.reply("mbylle tak fiz luxdev", draft(is_meeting_request=False))
        self.assertIsNone(reply)
        self.assertIsNone(self.link.pending_instruction)

    async def test_command_routes_meeting_words_and_pending_answers_only(self):
        db = SimpleNamespace(get=AsyncMock(return_value=None))
        with patch.object(api, "identity", AsyncMock(return_value=(self.link, self.user))), \
             patch.object(api, "meeting_draft_reply", AsyncMock(return_value={"status": "MEETING_DRAFT"})) as drafting:
            self.assertEqual((await api.command(command("krijo takim per neser"), db))["status"], "MEETING_DRAFT")
            self.link.pending_instruction = api.MEETING_MARK + "krijo tak int\nPyetja: Ora?"
            await api.command(command("ora 15", "556"), db)
            self.assertEqual(drafting.await_count, 2)


class ConfirmTests(unittest.IsolatedAsyncioTestCase):
    def action(self, status="MEETING_DRAFT"):
        link = SimpleNamespace(id=uuid.uuid4())
        result = {"meeting": {"title": "TAK INT", "participant_ids": [ME]}}
        if status == "DONE":
            result["created_reply"] = {"status": "DONE", "message": "Takimi u krijua në PrimeFlow."}
        self.action_row = SimpleNamespace(link_id=link.id, status=status, result=result)
        db = SimpleNamespace(get=AsyncMock(return_value=self.action_row), commit=AsyncMock())
        return link, db

    async def confirm(self, response, *, force=False, status="MEETING_DRAFT"):
        link, db = self.action(status)
        payload = api.MeetingDecision(discord_user_id="12", guild_id="123", channel_id="44", force=force)
        with patch.object(api, "identity", AsyncMock(return_value=(link, SimpleNamespace(id=ME)))), \
             patch.object(tools, "user_api", response) as request:
            return await api.confirm_meeting_draft("555", payload, db), request

    async def test_confirm_creates_once_through_the_normal_api(self):
        result, request = await self.confirm(AsyncMock(return_value={"id": "m1"}))
        self.assertEqual(result["status"], "DONE")
        self.assertEqual(request.call_args.args[1:3], ("POST", "/api/meetings"))
        self.assertFalse(request.call_args.kwargs["body"]["allow_one_h_conflict"])
        self.assertEqual(self.action_row.status, "DONE")
        again, request = await self.confirm(AsyncMock(), status="DONE")
        request.assert_not_called()
        self.assertEqual(again["status"], "DONE")

    async def test_one_h_conflict_offers_create_anyway(self):
        conflict = HTTPException(409, {"code": "one_h_conflict", "message": "1H", "conflicts": [
            {"title": "1H 11:00", "starts_at": "2026-10-20T09:00:00+00:00", "ends_at": "2026-10-20T09:30:00+00:00"}]})
        result, _ = await self.confirm(AsyncMock(side_effect=conflict))
        self.assertEqual((result["status"], self.action_row.status), ("CONFLICT", "MEETING_CONFLICT"))
        result, request = await self.confirm(AsyncMock(return_value={"id": "m1"}), force=True, status="MEETING_CONFLICT")
        self.assertTrue(request.call_args.kwargs["body"]["allow_one_h_conflict"])
        self.assertEqual(result["status"], "DONE")

    async def test_refusal_keeps_the_draft_retryable(self):
        result, _ = await self.confirm(AsyncMock(side_effect=HTTPException(403, "Department access denied")))
        self.assertEqual((result["status"], self.action_row.status), ("ERROR", "MEETING_DRAFT"))


@unittest.skipUnless(AVAILABLE, "Install requirements-discord.txt")
class MeetingUiTests(unittest.IsolatedAsyncioTestCase):
    def test_draft_card_shows_type_time_and_people(self):
        embed = ui.meeting_draft_card({"title": "TAK INT", "meeting_type": "internal", "starts_at": "2026-10-20T13:00:00+00:00",
                                       "platform": None, "meeting_url": None, "participants": ["Laurent Hoxha", "Endi Hyseni"]})
        self.assertIn("TAK INT · takim i brendshëm", embed.description)
        self.assertIn("20.10.2026 · 🕘 15:00", embed.description)
        self.assertIn("Laurent Hoxha, Endi Hyseni", embed.description)
        self.assertEqual([item.custom_id for item in ui.meeting_draft_view("555").children], ["pf:mtg:555:ok", "pf:mtg:555:no"])

    async def test_confirm_click_turns_the_card_into_the_result(self):
        client = object.__new__(bot.PrimeFlowBot)
        client.private_channel = AsyncMock()
        client.bridge = AsyncMock(return_value={"status": "DONE", "message": "Takimi u krijua në PrimeFlow.", "url": "https://x/common?meeting=1"})
        interaction = SimpleNamespace(guild_id=1, channel_id=2, user=SimpleNamespace(id=3), edit_original_response=AsyncMock(),
                                      followup=SimpleNamespace(send=AsyncMock()))
        await client.decide_meeting(interaction, "555", "ok")
        self.assertEqual(client.bridge.call_args.args[0], "/bot/meeting-drafts/555/confirm")
        kwargs = interaction.edit_original_response.call_args.kwargs
        self.assertTrue(kwargs["content"].startswith("✅"))
        self.assertEqual(kwargs["view"].children[0].url, "https://x/common?meeting=1")


if __name__ == "__main__":
    unittest.main()
