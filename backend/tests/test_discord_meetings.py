"""Discord meeting alerts: due rules, message layout and delivery. Never logs in."""
import asyncio
import importlib.util
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/test")
os.environ.setdefault("JWT_SECRET", "discord-meeting-test-secret")

from app.models.meeting import Meeting
from app.services import discord_meetings

AVAILABLE = importlib.util.find_spec("discord") is not None
if AVAILABLE:
    import discord
    import discord_ui as ui
    import discord_bot as bot

START = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)


class Result:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


def meeting(kind="internal", minutes=15):
    return Meeting(id=uuid.uuid4(), title="Sync", meeting_type=kind, reminder_minutes_before=minutes, starts_at=START, recurrence_type="none")


def due(item, current, canceled=(), statuses=()):
    user = uuid.uuid4()
    rows = [(meeting_id, day, "canceled") for meeting_id, day in canceled] + list(statuses)
    db = SimpleNamespace(execute=AsyncMock(side_effect=[Result([(item, user)]), Result(rows)]))
    with patch.object(discord_meetings.settings, "APP_TIMEZONE", "UTC"):
        return [kind for *_, kind in asyncio.run(discord_meetings.due_alerts(db, current, [user]))]


class DueAlertTests(unittest.TestCase):
    def test_internal_meeting_reminds_before_then_calls_at_start(self):
        item = meeting("internal")
        self.assertEqual(due(item, START - timedelta(minutes=20)), [])
        self.assertEqual(due(item, START - timedelta(minutes=10)), ["before"])
        self.assertEqual(due(item, START + timedelta(minutes=1)), ["start"])
        self.assertEqual(due(item, START + timedelta(minutes=6)), [])

    def test_external_meeting_only_reminds_unless_reminder_is_at_start(self):
        self.assertEqual(due(meeting("external"), START + timedelta(minutes=1)), ["before"])
        self.assertEqual(due(meeting("external", 0), START), ["start"])

    def test_canceled_occurrence_is_skipped(self):
        item = meeting("internal")
        self.assertEqual(due(item, START - timedelta(minutes=5), canceled=[(item.id, START.date())]), [])


    def test_participants_are_asked_after_the_meeting_whether_it_was_held(self):
        item = meeting("external")
        self.assertEqual(due(item, START + timedelta(minutes=29)), [])
        self.assertEqual(due(item, START + timedelta(minutes=31)), ["after"])
        self.assertEqual(due(item, START + timedelta(hours=3)), [])

    def test_after_question_waits_for_the_planned_end(self):
        item = meeting("internal")
        item.ends_at = START + timedelta(minutes=90)
        self.assertEqual(due(item, START + timedelta(minutes=60)), [])
        self.assertEqual(due(item, START + timedelta(minutes=91)), ["after"])

    def test_no_after_question_once_marked_in_common_view(self):
        item = meeting("external")
        for status in ("held", "canceled"):
            self.assertEqual(due(item, START + timedelta(minutes=40), statuses=[(item.id, START.date(), status)]), [])

    def test_no_after_question_for_another_day(self):
        self.assertEqual(due(meeting("external"), START + timedelta(days=1, minutes=40)), [])


@unittest.skipUnless(AVAILABLE, "Install requirements-discord.txt")
class MeetingMessageTests(unittest.IsolatedAsyncioTestCase):
    def job(self, kind="before", meeting_type="internal", url="https://zoom.us/j/1"):
        return {"id": str(uuid.uuid4()), "kind": kind, "discord_user_id": "3", "guild_id": "1", "channel_id": "2",
                "meeting": {"title": "Sync", "platform": "Zoom", "url": url, "type": meeting_type, "minutes_before": 15,
                            "starts_at": START.isoformat(), "others": [{"name": "Anisa Ternava", "discord_user_id": "4"}]}}

    def test_internal_start_pings_and_links_voice_room(self):
        content, embed, view = ui.meeting_alert(self.job("start"), "https://discord.com/channels/1/9")
        self.assertTrue(content.startswith("<@3> 🔴 **Takimi po fillon tani**"))
        self.assertIn("Anisa Ternava", embed.description)
        self.assertEqual([item.label for item in view.children], ["🔗 Hap takimin", "🎧 Hyr në kanalin zanor"])

    def test_after_question_offers_held_or_canceled(self):
        job = self.job("after")
        content, _, view = ui.meeting_alert(job, "https://discord.com/channels/1/9")
        self.assertIn("A u mbajt takimi?", content)
        self.assertEqual([(item.label, item.custom_id) for item in view.children],
                         [("✅ Mbajtur", f"pf:mheld:{job['id']}:held"), ("✖ Anuluar", f"pf:mheld:{job['id']}:canceled")])
        self.assertIn("Anuluar", ui.meeting_held_text("Sync", "canceled", "Laurent Hoxha"))

    def test_push_notice_is_polite_and_mentions_the_person(self):
        text = ui.push_notice("3", "Laurent Hoxha", 5, "Rregullime te raportet")
        self.assertTrue(text.startswith("<@3> "))
        self.assertIn("5 minuta", text)
        self.assertIn("Rregullime te raportet", text)
        self.assertIn("PrimeFlow u përditësua", ui.push_done("3"))

    def test_external_reminder_has_no_voice_room_and_ignores_non_web_links(self):
        content, _, view = ui.meeting_alert(self.job(meeting_type="external", url="Office 2"), "https://discord.com/channels/1/9")
        self.assertIn("Takim pas 15 min", content)
        self.assertEqual(view.children, [])

    async def test_delivery_mentions_only_the_person_and_acknowledges(self):
        client = object.__new__(bot.PrimeFlowBot)
        job = self.job()
        acks = []

        async def bridge(path, payload):
            if path == "/bot/meetings/claim":
                return {"jobs": [job]}
            acks.append((path, payload["message_id"]))
            return {"ok": True}
        client.bridge = bridge
        client.private_channel = AsyncMock(return_value=SimpleNamespace(id=2))
        client.voice_url = lambda guild_id: None
        client.http = SimpleNamespace(request=AsyncMock(return_value={"id": "88"}))
        await bot.PrimeFlowBot.meeting_alerts.coro(client)
        payload = client.http.request.call_args.kwargs["json"]
        self.assertEqual(payload["allowed_mentions"], {"parse": [], "users": ["3"]})
        self.assertTrue(payload["enforce_nonce"])
        self.assertEqual(acks, [(f"/bot/meetings/{job['id']}/ack", "88")])

    def test_migration_creates_every_model_column(self):
        from app.models.discord_assistant import DiscordMeetingAlert
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0151_discord_meeting_alerts.py").read_text(encoding="utf-8")
        sync_columns = {'sync_hash', 'sync_pending_hash', 'sync_lease_until'}
        for column in DiscordMeetingAlert.__table__.c:
            if column.name not in sync_columns:
                self.assertIn(f'"{column.name}"', source)
        self.assertIn("uq_discord_meeting_alert", source)


if __name__ == "__main__":
    unittest.main()
