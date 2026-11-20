"""iPhone "R:" reminders, To Do edge cases and Discord mentions in the GA assistant (no database)."""
import os
import unittest
from datetime import date, datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

os.environ.setdefault("JWT_SECRET", "test-only-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")

from app.services import ga_assistant as svc  # noqa: E402
from app.services import ga_discord_mentions as mentions  # noqa: E402

TZ = ZoneInfo("Europe/Belgrade")
TODAY = date(2026, 11, 20)


def reminder(title, *, source, day=TODAY, start=None, key=None):
    key = key or f"{'todo:L::' if source == 'microsoft_todo' else 'tt:'}{title}"
    return svc.AgendaItem(id=key, item_key=key, source=source, kind=svc.KIND_REMINDER, title=title, day=day, start=start)


class ReminderContentTests(unittest.TestCase):
    def test_timed_reminder(self) -> None:
        self.assertEqual(svc.parse_reminder_content("REMINDER 09:30: Thirr bankën"), (time(9, 30), True, "Thirr bankën", None))

    def test_midnight_is_date_only(self) -> None:
        self.assertEqual(svc.parse_reminder_content("REMINDER 00:00: Pagesa"), (None, True, "Pagesa", None))

    def test_no_clock_and_notes(self) -> None:
        self.assertEqual(svc.parse_reminder_content("REMINDER: Blej letër · 2 pako"), (None, False, "Blej letër", "2 pako"))

    def test_unknown_format_keeps_text(self) -> None:
        self.assertEqual(svc.parse_reminder_content("diçka tjetër"), (None, False, "diçka tjetër", None))


class DedupeTests(unittest.TestCase):
    def test_same_reminder_in_todo_and_iphone_is_returned_once_as_todo(self) -> None:
        todo = reminder("Thirr  Bankën", source="microsoft_todo")
        phone = reminder("thirr bankën", source=svc.SOURCE_IPHONE_SYNC, start=datetime(2026, 11, 20, 10, 30, tzinfo=TZ))
        other = reminder("Tjetër", source=svc.SOURCE_IPHONE_SYNC)
        kept = svc.dedupe_reminders([todo, phone, other])
        self.assertEqual([item.id for item in kept], [todo.id, other.id])
        self.assertEqual(todo.linked_ids, [phone.id])
        self.assertEqual(todo.start, phone.start)  # the phone's time fills an untimed To Do

    def test_different_days_are_not_merged(self) -> None:
        todo = reminder("A", source="microsoft_todo")
        phone = reminder("A", source=svc.SOURCE_IPHONE_SYNC, day=date(2026, 11, 21))
        self.assertEqual(len(svc.dedupe_reminders([todo, phone])), 2)


class TodoListFilterTests(unittest.TestCase):
    def test_flagged_emails_list_is_skipped(self) -> None:
        self.assertTrue(svc.is_flagged_email_list({"wellknownListName": "flaggedEmails", "displayName": "Flagged Emails"}))
        self.assertTrue(svc.is_flagged_email_list({"displayName": "Flagged Emails"}))
        self.assertFalse(svc.is_flagged_email_list({"wellknownListName": "defaultList", "displayName": "Tasks"}))


class DiscordSelectionTests(unittest.TestCase):
    def item(self, status, day=TODAY):
        return svc.AgendaItem(id="dc:1", item_key="dc:1", source="discord", kind=svc.KIND_DISCORD, title="LH", day=day, status=status)

    def test_untimed_today_and_agenda_include_open_mentions(self) -> None:
        mention = self.item("seen")
        self.assertEqual(svc.select_untimed([mention], TODAY), [mention])
        start = datetime(2026, 11, 20, 0, 0, tzinfo=TZ)
        self.assertEqual(svc.select_agenda([mention], start, datetime(2026, 11, 21, tzinfo=TZ), include_untimed=True), [mention])

    def test_leftovers_only_keep_unmarked_mentions(self) -> None:
        as_of = datetime(2026, 11, 20, 9, 0, tzinfo=TZ)
        new, seen = self.item("new", date(2026, 11, 19)), self.item("seen", date(2026, 11, 19))
        self.assertEqual(svc.select_leftovers([new, seen], as_of), [new])
        self.assertEqual(new.days_late, 1)


class MentionStoreTests(unittest.TestCase):
    def test_bridge_secret_is_derived_and_stable(self) -> None:
        self.assertEqual(len(mentions.bridge_secret()), 64)
        self.assertEqual(mentions.bridge_secret(), mentions.bridge_secret())

    def test_mention_out_uses_primeflow_name_and_local_time(self) -> None:
        row = SimpleNamespace(
            id="123", author_user_id="u1", author_name="laurent", channel_name="development", channel_id="9",
            created_at=datetime(2026, 11, 20, 8, 15, tzinfo=ZoneInfo("UTC")), edited_at=None, content="Shiko këtë",
            jump_url="https://discord.com/channels/1/9/123", attachments=[{"name": "a.pdf", "url": "u"}],
            reasons=["mention"], status="new",
        )
        out = mentions.mention_out(row, {"u1": "Laurent Hoxha"}, TZ)
        self.assertEqual((out["id"], out["author"], out["author_initials"], out["channel"]),
                         ("dc:123", "Laurent Hoxha", "LH", "#development"))
        self.assertEqual(out["time"], "2026-11-20T09:15:00+01:00")


class BotFilterTests(unittest.TestCase):
    """The bot keeps only messages that concern the GA."""

    def setUp(self) -> None:
        try:
            import discord  # noqa: F401
        except ImportError:  # pragma: no cover - discord.py is in requirements-discord.txt
            self.skipTest("discord.py is not installed")
        import discord_ga_mentions as bot

        self.bot = bot

    def message(self, *, users=(), roles=(), reply_author=None):
        import discord

        resolved = None
        if reply_author is not None:
            resolved = discord.Message.__new__(discord.Message)
            resolved.author = SimpleNamespace(id=reply_author)
        reference = SimpleNamespace(resolved=resolved, message_id=5) if resolved is not None else None
        return SimpleNamespace(raw_mentions=list(users), raw_role_mentions=list(roles), reference=reference)

    def test_reasons(self) -> None:
        ga, roles = 42, {7}
        self.assertEqual(self.bot.mention_reasons(self.message(users=[42]), ga, roles), ["mention"])
        self.assertEqual(self.bot.mention_reasons(self.message(roles=[7]), ga, roles), ["role"])
        self.assertEqual(self.bot.mention_reasons(self.message(reply_author=42), ga, roles), ["reply"])
        self.assertEqual(self.bot.mention_reasons(self.message(users=[1], roles=[8], reply_author=3), ga, roles), [])


if __name__ == "__main__":
    unittest.main()
