"""No Discord messages or external requests are sent by these tests."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

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


def table_rows(body):
    from app.services.meetings_report import _section_report_blocks

    return next(block["rows"] for block in _section_report_blocks(body) if block["kind"] == "table")


class DiscordGaRepliesTests(unittest.TestCase):
    def test_m1_and_m2_use_their_own_local_start_and_the_generation_cutoff(self):
        tz = ZoneInfo("Europe/Tirane")
        cutoff = datetime(2026, 11, 17, 11, 30, tzinfo=tz)
        def at(day, hour, minute=0, second=0):
            return datetime(2026, 11, day, hour, minute, second, tzinfo=tz).isoformat()

        messages = [
            message(1, content="Pyetja origjinale", created_at=at(16, 15)),
            message(2, GA, "Para intervalit", reference_id="1", created_at=at(16, 16, 29, 59)),
            message(3, GA, "Në 16:30", reference_id="1", created_at=at(16, 16, 30)),
            message(4, GA, "Pak para 08:00", created_at=at(17, 7, 59, 59)),
            message(5, GA, "Në 08:00", reference_id="1", created_at=at(17, 8)),
            message(6, GA, "Në çastin e gjenerimit", created_at=at(17, 11, 30)),
            message(7, GA, "Pas gjenerimit", reference_id="1", created_at=at(17, 11, 30, 1)),
        ]
        source = evidence(messages)
        with patch.object(service, "report_timezone", return_value=tz):
            m1 = table_rows(service.render_summary(source, cutoff, cutoff,
                            window=service._report_window(cutoff.date(), "M1", cutoff)))
            m2 = table_rows(service.render_summary(source, cutoff, cutoff,
                            window=service._report_window(cutoff.date(), "M2", cutoff)))
        assert [row[-1] for row in m1] == ["Në 16:30", "Pak para 08:00", "Në 08:00", "Në çastin e gjenerimit"]
        assert [row[-1] for row in m2] == ["Në 08:00", "Në çastin e gjenerimit"]
        assert m2[0][2] == "Pyetja origjinale"

    def test_generated_replies_are_reused_on_read_and_send_until_regeneration(self):
        sections = [{"title": service.GA_REPLIES_SECTION_TITLE, "body": "Generated table"}]
        with patch.object(service, "summary_for_day", AsyncMock()) as summary:
            result = asyncio.run(service.refresh_ga_reply_section(
                None, sections, datetime.now(service.report_timezone()).date(), report="M2",
                generated_snapshot={"ga_replies_generated_at": NOW.isoformat()},
            ))
        assert result == sections
        summary.assert_not_awaited()

    def test_m1_keeps_verified_rows_from_a_stale_capture(self):
        captured = NOW - timedelta(minutes=12)
        source = evidence([message(1, GA, "Koment i verifikuar", created_at=captured.isoformat())])
        window = (captured - timedelta(hours=1), NOW)
        body = service.render_summary(source, captured, NOW, window=window, allow_verified_stale=True)
        assert body.startswith(service.STALE_REPLY_NOTE)
        assert table_rows(body) == [["1", "", "", "Koment i verifikuar"]]
        assert service.render_summary(evidence(), captured, NOW, window=window, allow_verified_stale=True) == service.UNAVAILABLE

    def test_m1_recovers_unavailable_rows_using_original_generate_cutoff(self):
        sections = [{"title": service.GA_REPLIES_SECTION_TITLE, "body": service.UNAVAILABLE}]
        with patch.object(service, "summary_for_day", AsyncMock(return_value="Recovered table")) as summary:
            refreshed = asyncio.run(service.refresh_m1_section(
                None, sections, NOW.date(), refresh_current=False,
                generated_snapshot={"ga_replies_generated_at": NOW.isoformat()},
            ))
        assert refreshed[0]["body"] == "Recovered table"
        summary.assert_awaited_once_with(None, NOW.date(), report="M1", generated_at=NOW)

    def test_m2_recovers_when_a_later_capture_confirms_no_reply_before_generate(self):
        cutoff = datetime(2026, 11, 19, 11, 30, tzinfo=timezone.utc)
        captured = cutoff + timedelta(seconds=10)
        snapshot = SimpleNamespace(captured_at=captured, evidence=evidence([
            message(1, GA, "Pas gjenerimit", created_at=captured.isoformat()),
        ]))
        sections = [{"section_key": service.GA_REPLIES_SECTION_TITLE, "body": service.UNAVAILABLE}]
        with (patch.object(service, "_snapshot_for_day", new=AsyncMock(return_value=snapshot)),
              patch.object(service, "ga_identity", new=AsyncMock(return_value=GA))):
            result = asyncio.run(service.refresh_ga_reply_section(
                None, sections, cutoff.date(), report="M2",
                generated_snapshot={"ga_replies_generated_at": cutoff.isoformat()},
            ))
        assert table_rows(result[0]["body"]) == [["-", "", "", service.EMPTY_REPLY_ROW]]

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
        assert table_rows(body) == [["1", "S", "Dy pyetje në një kërkesë", "Përgjigjja"], ["2", "", "", "Folderat?"]]

    def test_reply_chains_threads_deduplication_and_deleted_replies(self):
        messages = [message(1), message(2), message(3, reference_id="1"),
                    message(4, GA, "Përgjigje në zinxhir", reference_id="3"),
                    message(5, GA, "Koment në thread", thread_root_id="2")]
        result = service.requests_with_replies(messages + [messages[-1]], GA)
        assert [(row["id"], row["reply_id"]) for row in result] == [("1", "4"), ("2", "5")]
        assert table_rows(service.render_summary(evidence(messages), NOW, NOW)) == [
            ["1", "S", "@GA Kërkesë për projektin", "Përgjigje në zinxhir"],
            ["2", "S", "@GA Kërkesë për projektin", "Koment në thread"],
        ]
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
            assert body == service.UNAVAILABLE
        assert service.render_summary(evidence(status="PARTIAL"), NOW, NOW) == service.UNAVAILABLE
        assert table_rows(service.render_summary(evidence(), NOW, NOW)) == [["-", "", "", "Asnjë reply"]]
        assert table_rows(service.render_summary(evidence([message(1, GA, "Koment")]), NOW, NOW)) == [
            ["1", "", "", "Koment"], ["-", "", "", "Asnjë reply"],
        ]

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
        with patch.object(settings, "DISCORD_GUILD_ID", "1493866119700807722"):
            result = asyncio.run(service.summary_for_day(db, day))
        assert table_rows(result) == [["-", "", "", "Asnjë reply"]]
        assert db.get.call_args.args[1][2] == day
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW
        with patch.object(service, "datetime", Clock), patch.object(settings, "DISCORD_GUILD_ID", "1493866119700807722"), \
             patch.object(service, "ga_identity", AsyncMock(return_value="other-account")):
            assert asyncio.run(service.summary_for_day(db, NOW.date())) == service.UNAVAILABLE

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

    def test_m2_manual_placeholder_is_filled_from_evidence_before_its_send_time(self):
        captured = evidence([message(1, GA, "Koment para M2"),
                             message(2, GA, "Koment pas M2", created_at=(NOW + timedelta(minutes=1)).isoformat())])
        db = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(evidence=captured, captured_at=NOW)))
        sections = [{"title": service.GA_REPLIES_SECTION_TITLE, "body": "(Ploteso manualisht)"}]
        with patch.object(settings, "DISCORD_GUILD_ID", captured["guild_id"]):
            result = asyncio.run(service.refresh_ga_reply_section(
                db, sections, NOW.date(), refresh_current=False, sent_at=NOW, populate_missing=True,
            ))
        assert table_rows(result[0]["body"]) == [["1", "", "", "Koment para M2"], ["-", "", "", "Asnjë reply"]]

    def test_m1_html_displays_the_original_author_first_sentence_and_escaped_reply(self):
        from app.services.morning_report import SECTION_TITLES, render_html
        messages = [{**message(1, content="<@123> Pyetja e parë? Fjalia tjetër. https://example.com/request"),
                     "author": "Florent"},
                    message(2, GA, '<script>alert("x")</script> [Dokumenti](https://example.com/file) https://example.com/', reference_id="1")]
        body = service.render_summary(evidence(messages), NOW, NOW, initials_by_user={"20": "FG"})
        html = render_html("M1", NOW.date(), [{"title": SECTION_TITLES[0], "body": body}])
        assert "Dokumenti" in html
        assert "<table" in html and ">FG</td>" in html and "Pyetja e parë?" in html
        assert "Fjalia tjetër" not in html
        assert "https://" not in html
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "AUTO-FILLED" in html

    def test_saved_legacy_report_uses_only_the_original_reply_ids(self):
        from app.services.morning_report import SECTION_TITLES
        captured = evidence([message(1), message(2, GA, "Koment i raportuar", reference_id="1"),
                             message(3, GA, "Koment i mëvonshëm", reference_id="1")])
        db = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(evidence=captured, captured_at=NOW)),
                             execute=AsyncMock(return_value=Mock(all=Mock(return_value=[]))))
        body = (
            "GA është përgjigjur në 1 nga 1 kërkesa; 0 pa reply të lidhur.\n"
            "Burimi: #det-nga-stafi-per-ga\n"
            "Përgjigjja GA: https://discord.com/channels/1493866119700807722/1572160944358953042/2"
        )
        sections = [{"title": SECTION_TITLES[0], "body": body}]
        with patch.object(settings, "DISCORD_GUILD_ID", "1493866119700807722"):
            result = asyncio.run(service.refresh_m1_section(db, sections, NOW.date(), refresh_current=False))
        assert table_rows(result[0]["body"]) == [["1", "S", "@GA Kërkesë për projektin", "Koment i raportuar"]]
        assert db.get.call_args.args[1][2] == NOW.date()

    def test_report_only_instance_recovers_saved_reply_using_the_channel_date_and_send_time(self):
        from app.services.morning_report import SECTION_TITLES
        later = (NOW + timedelta(minutes=1)).isoformat()
        captured = evidence([message(1), message(2, GA, "Koment para dërgimit", reference_id="1"),
                             message(3, GA, "Koment pas dërgimit", reference_id="1", created_at=later)])
        snapshot = SimpleNamespace(evidence=captured, captured_at=NOW + timedelta(minutes=2))
        db = SimpleNamespace(execute=AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=snapshot),
                                                               all=Mock(return_value=[]))))
        with patch.object(settings, "DISCORD_GUILD_ID", None):
            for old_body in (service.UNAVAILABLE, "Koment para dërgimit",
                             "Përgjigje për Stafi — «@GA Kërkesë për projektin»\nKoment para dërgimit", "Përgjigje manuale"):
                sections = [{"title": SECTION_TITLES[0], "body": old_body}]
                result = asyncio.run(service.refresh_m1_section(db, sections, NOW.date(), refresh_current=False, sent_at=NOW))
                if old_body == "Përgjigje manuale":
                    assert result[0]["body"] == old_body
                else:
                    assert table_rows(result[0]["body"]) == [["1", "S", "@GA Kërkesë për projektin", "Koment para dërgimit"]]
        assert NOW.date() in db.execute.call_args_list[0].args[0].compile().params.values()

    def test_saved_table_uses_linked_initials_without_replacing_saved_messages(self):
        from app.services.after_break_report import _ascii_table
        from app.services.morning_report import SECTION_TITLES

        body = "\n".join(_ascii_table(service.GA_MESSAGES_CAPTION,
            [("NR", 2), ("PËR KË", 19), ("MESAZHI ORIGJINAL", 40), ("PËRGJIGJJA E GA", 52)],
            [["1", "Florent", "Pyetja", "Përgjigjja e ruajtur"]]))
        captured = evidence([{**message(1), "author": "Florent"}, message(2, GA, "Tekst tjetër", reference_id="1")])
        db = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(evidence=captured)),
                             execute=AsyncMock(return_value=Mock(all=Mock(return_value=[("20", "Florent Gara")]))))
        with patch.object(settings, "DISCORD_GUILD_ID", captured["guild_id"]):
            sections = [{"title": SECTION_TITLES[0], "body": body}]
            result = asyncio.run(service.refresh_m1_section(db, sections, NOW.date(), refresh_current=False, sent_at=NOW))
        assert table_rows(result[0]["body"]) == [["1", "FG", "Pyetja", "Përgjigjja e ruajtur"]]

    def test_standalone_comments_use_report_date_and_do_not_inherit_context(self):
        messages = [message(1, GA, "Koment i datës së kaluar", created_at=(NOW - timedelta(days=1)).isoformat()),
                    message(2, content="Mesazh pranë komentit"),
                    message(3, GA, "<@20> Foto letrën"),
                    message(4, GA, "Reply me origjinal të munguar", reference_id="99")]
        assert table_rows(service.render_summary(evidence(messages), NOW, NOW)) == [
            ["1", "", "", "Foto letrën"], ["2", "", "", "Reply me origjinal të munguar"],
        ]

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
