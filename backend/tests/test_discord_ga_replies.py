"""No Discord messages or external requests are sent by these tests."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
import unittest
from fastapi import HTTPException

import discord_ga_replies as worker
from app.config import settings
from app.services import discord_ga_replies as service

NOW = datetime(2026, 11, 17, 8, 0, tzinfo=timezone.utc)
GA = "1425896175839608933"


def message(id, author="20", content="@GA Kërkesë për projektin", **changes):
    return {"id": str(id), "author_id": author, "author": "Stafi", "content": content,
            "created_at": NOW.isoformat(), "mentions_ga": True, "reference_id": None,
            "thread_root_id": None, "attachments": 0, **changes}


def evidence(messages=(), **changes):
    return {"guild_id": "1493866119700807722", "channel_id": "1572160944358953042",
            "ga_user_id": GA, "captured_at": NOW.isoformat(),
            "window_start": (NOW - timedelta(days=30)).isoformat(), "status": "OK",
            "messages": list(messages), **changes}


def async_items(items):
    async def iterator():
        for item in items:
            yield item
    return iterator()


class DiscordGaRepliesTests(unittest.TestCase):
    def test_only_explicit_ga_replies_count_and_requests_are_not_individual_questions(self):
        messages = [message(1, content="Dy pyetje në një kërkesë"), message(2),
                    message(3, GA, "Përgjigjja", reference_id="1"),
                    message(4, GA, "Folderat?"),
                    message(5, "30", "Koment i stafit", reference_id="2"),
                    message(6, content="<@1425896175839608933>"),
                    message(7, content="", mentions_ga=False, attachments=1),
                    message(8, "30", "Mesazh pa përmendje", mentions_ga=False)]
        result = service.requests_with_replies(messages, GA)
        assert [(row["id"], row["reply_id"]) for row in result] == [("1", "3"), ("2", None)]
        body = service.render_summary(evidence(messages), NOW, NOW)
        assert "1 nga 2 kërkesa; 1 pa reply të lidhur" in body
        assert "/1572160944358953042/3" in body
        assert "30 ditëve" in body

    def test_reply_chains_threads_deduplication_and_deleted_replies(self):
        messages = [message(1), message(2), message(3, reference_id="1"),
                    message(4, GA, reference_id="3"), message(5, GA, thread_root_id="2")]
        result = service.requests_with_replies(messages + [messages[-1]], GA)
        assert [(row["id"], row["reply_id"]) for row in result] == [("1", "4"), ("2", "5")]
        assert "/2/5" in service.render_summary(evidence(messages), NOW, NOW)
        messages = [m for m in messages if m["id"] not in {"4", "5"}]
        assert all(row["reply_id"] is None for row in service.requests_with_replies(messages, GA))

    def test_missing_ancestors_cycles_and_empty_replies_do_not_close_requests(self):
        messages = [message(1), message(2, GA, reference_id="999"),
                    message(3, reference_id="4"), message(4, GA, reference_id="3"),
                    message(5, GA, "", reference_id="1")]
        assert service.requests_with_replies(messages, GA)[0]["reply_id"] is None

    def test_missing_stale_or_failed_source_never_claims_zero_pending(self):
        for value, captured in [(None, NOW), (evidence(status="UNAVAILABLE"), NOW),
                                (evidence(), NOW - timedelta(minutes=6))]:
            body = service.render_summary(value, captured, NOW)
            assert "Nuk mund të konfirmohet" in body
            assert "0 nga 0" not in body
        assert "KONTROLL I PJESSHËM" in service.render_summary(evidence(status="PARTIAL"), NOW, NOW)
        assert "0 nga 0" in service.render_summary(evidence(), NOW, NOW)

    def test_evidence_rejects_wrong_channel_identity_time_and_out_of_window_messages(self):
        with patch.object(settings, "DISCORD_GUILD_ID", "1493866119700807722"):
            valid = service.ChannelEvidence(**evidence([message(1)]))
            service.validate_evidence(valid, GA, NOW)
            for changes in [{"channel_id": "12"}, {"ga_user_id": "13"},
                            {"captured_at": NOW - timedelta(minutes=6)},
                            {"window_start": NOW - timedelta(days=60)},
                            {"messages": [message(1, created_at=(NOW + timedelta(seconds=1)).isoformat())]}]:
                with self.assertRaises(HTTPException):
                    service.validate_evidence(service.ChannelEvidence(**evidence(**changes)), GA, NOW)

    def test_worker_ignores_bots_and_system_messages_and_does_not_fetch_attachments(self):
        msg = SimpleNamespace(id=1, author=SimpleNamespace(bot=False, id=20, display_name="Stafi"),
                              type=discord.MessageType.default, reference=None, content="Pyetje",
                              created_at=NOW, mentions=[SimpleNamespace(id=int(GA))], attachments=[object()])
        assert worker.message_evidence(msg, GA)["attachments"] == 1
        msg.author.bot = True
        assert worker.message_evidence(msg, GA) is None
        msg.author.bot = False
        msg.type = discord.MessageType.pins_add
        assert worker.message_evidence(msg, GA) is None

    def test_failed_read_publishes_unavailable_not_empty_success(self):
        context = {k: v for k, v in evidence().items() if k not in {"status", "messages"}}
        bot = SimpleNamespace(bridge=AsyncMock(side_effect=[context, {"ok": True}]))
        with patch.object(worker, "collect", AsyncMock(side_effect=ValueError("No history permission"))):
            asyncio.run(worker.sync(bot))
        assert bot.bridge.call_args.args[1]["status"] == "UNAVAILABLE"
        assert bot.bridge.call_args.args[1]["messages"] == []

    def test_today_requires_current_identity_but_historical_evidence_is_date_scoped(self):
        db = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(captured_at=NOW, evidence=evidence([message(1)]))))
        # A past date reads that day's stored snapshot, never today's source.
        day = datetime.now(timezone.utc).date() - timedelta(days=1)
        result = asyncio.run(service.summary_for_day(db, day))
        assert "0 nga 1" in result
        assert db.get.call_args.args[1][2] == day
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW
        with patch.object(service, "datetime", Clock), patch.object(settings, "DISCORD_ASSISTANT_ENABLED", True), \
             patch.object(service, "ga_identity", AsyncMock(return_value="other-account")):
            assert "Nuk mund të konfirmohet" in asyncio.run(service.summary_for_day(db, NOW.date()))

    def test_m1_section_refresh_preserves_other_sections_and_edited_title(self):
        from app.services.morning_report import SECTION_TITLES, MANUAL_SECTION_TITLES
        sections = [{"section_key": SECTION_TITLES[0], "title": "Titull i redaktuar", "body": "Përgjigje e vjetër"},
                    {"title": SECTION_TITLES[2], "body": "NDRYSHON PLANI: Teksti manual"}]
        with patch.object(service, "summary_for_day", AsyncMock(return_value="GA: 1 nga 2")):
            result = asyncio.run(service.refresh_m1_section(None, sections, datetime.now(service.report_timezone()).date()))
        assert result[0]["title"] == "Titull i redaktuar"
        assert result[0]["body"] == "GA: 1 nga 2"
        assert result[1] == sections[1]
        assert SECTION_TITLES[0] not in MANUAL_SECTION_TITLES

    def test_refresh_keeps_historical_drafts_frozen(self):
        sections = [{"title": "(GA) A KA REPLY NGA GA TEK DETYRAT NGA STAFI PER GA?", "body": "Përgjigjja historike"}]
        with patch.object(service, "summary_for_day", AsyncMock()) as summary:
            result = asyncio.run(service.refresh_m1_section(None, sections, datetime.now(service.report_timezone()).date() - timedelta(days=1)))
        assert result == sections
        summary.assert_not_awaited()

    def test_m1_html_links_evidence_and_escapes_untrusted_channel_text(self):
        from app.services.morning_report import SECTION_TITLES, render_html
        body = service.render_summary(evidence([message(1, content='<script>alert("x")</script>')]), NOW, NOW)
        html = render_html("M1", NOW.date(), [{"title": SECTION_TITLES[0], "body": body}])
        assert '<a href="https://discord.com/channels/1493866119700807722/1572160944358953042/1"' in html
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "AUTO-FILLED" in html

    def test_channel_evidence_endpoints_require_bot_authentication(self):
        from app.api.routers.discord_assistant import router, require_bot
        routes = [r for r in router.routes if r.path.startswith("/bot/ga-replies/")]
        assert len(routes) == 2
        for route in routes:
            assert require_bot in [dependency.call for dependency in route.dependant.dependencies]
        with patch.object(settings, "DISCORD_ASSISTANT_ENABLED", True), \
             patch.object(settings, "DISCORD_GUILD_ID", "1493866119700807722"), \
             patch.object(settings, "DISCORD_BRIDGE_SECRET", "x" * 32):
            with self.assertRaises(HTTPException) as error:
                require_bot("invalid")
            assert error.exception.status_code == 401

    def test_collector_reads_only_selected_channel_and_its_public_threads(self):
        context = {k: v for k, v in evidence().items() if k not in {"messages", "status"}}
        def msg(id, author, reference=None):
            return SimpleNamespace(id=id, author=SimpleNamespace(bot=False, id=author, display_name="Person"),
                type=discord.MessageType.reply if reference else discord.MessageType.default,
                reference=SimpleNamespace(message_id=reference) if reference else None,
                content="Kërkesa / përgjigjja", created_at=NOW - timedelta(seconds=1),
                mentions=[SimpleNamespace(id=int(GA))], attachments=[])
        thread = SimpleNamespace(id=1, parent_id=int(context["channel_id"]), is_private=lambda: False,
                                 history=Mock(side_effect=lambda **kwargs: async_items([msg(2, int(GA))])))
        unrelated = SimpleNamespace(id=99, parent_id=999, is_private=lambda: False)
        private = SimpleNamespace(id=3, parent_id=int(context["channel_id"]), is_private=lambda: True)
        guild = SimpleNamespace(id=int(context["guild_id"]), me=object(),
                                active_threads=AsyncMock(return_value=[thread, unrelated, private]))
        channel = Mock(spec=discord.TextChannel)
        channel.id, channel.guild = int(context["channel_id"]), guild
        channel.permissions_for.return_value = SimpleNamespace(view_channel=True, read_message_history=True)
        channel.history.side_effect = lambda **kwargs: async_items([msg(1, 20)])
        channel.archived_threads.side_effect = lambda **kwargs: async_items([])
        guild.get_channel = Mock(return_value=channel)
        bot = SimpleNamespace(get_guild=Mock(return_value=guild))
        with patch.object(settings, "DISCORD_GUILD_ID", context["guild_id"]), \
             patch.object(settings, "DISCORD_MESSAGE_CONTENT_ENABLED", True):
            result = asyncio.run(worker.collect(bot, context))
        assert result["status"] == "OK"
        assert len(result["messages"]) == 2
        assert service.requests_with_replies(result["messages"], GA)[0]["reply_id"] == "2"
        assert thread.history.call_args.kwargs["before"] == NOW
        channel.send.assert_not_called()
        channel.edit.assert_not_called()

    def test_snapshot_upsert_does_not_allow_an_older_poll_to_replace_newer_evidence(self):
        from app.api.routers.discord_assistant import save_ga_reply_snapshot
        from sqlalchemy.dialects import postgresql
        payload = service.ChannelEvidence(**evidence([message(1)]))
        db = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW
        with patch("app.api.routers.discord_assistant.ga_replies.ga_identity", AsyncMock(return_value=GA)), \
             patch("app.api.routers.discord_assistant.datetime", Clock), \
             patch.object(settings, "DISCORD_GUILD_ID", payload.guild_id):
            asyncio.run(save_ga_reply_snapshot(payload, db))
        sql = str(db.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
        assert "ON CONFLICT (guild_id, channel_id, day) DO UPDATE" in sql
        assert "discord_ga_reply_snapshots.captured_at <= excluded.captured_at" in sql
        assert db.commit.await_count == 1
