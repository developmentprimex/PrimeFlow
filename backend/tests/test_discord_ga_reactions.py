import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4
from zipfile import ZipFile

import discord
import httpx
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

import discord_ga_replies as worker
from app.config import settings
from app.services import after_break_report, morning_report
from app.services import discord_ga_reactions as service
from app.services.meetings_report import _section_report_blocks, render_section_report_docx, render_section_report_png
from app.services.primeflow_report import report_timezone


class DiscordGaReactionsTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(settings, "DISCORD_GUILD_ID", "10"))
        self.enterContext(patch.object(settings, "DISCORD_GA_REPLIES_CHANNEL_ID", "20"))

    def test_reports_rename_reactions_without_losing_saved_evidence(self):
        for normalize in (
            morning_report.normalize_morning_report_sections,
            after_break_report.normalize_after_break_report_sections,
        ):
            for has_saved_reactions in (False, True):
                with self.subTest(report=normalize.__name__, has_saved_reactions=has_saved_reactions):
                    original = "A KA REACTION TE GRUPI?"
                    saved = [{"section_key": original, "title": original, "body": "Reagim i ruajtur"}]
                    reactions = [
                        section for section in normalize(saved if has_saved_reactions else [])
                        if section["section_key"] == original
                    ]

                    assert len(reactions) == 1
                    assert reactions[0]["title"] == "(GA) A KA REACTION NGA GA TEK DETYRAT NGA STAFI PER GA?"
                    expected = "Reagim i ruajtur" if has_saved_reactions else service.REACTIONS_UNAVAILABLE
                    assert reactions[0]["body"] == expected

    def test_worker_captures_ga_on_old_staff_message_and_retries_with_same_id(self):
        now = datetime.now(timezone.utc)
        message = SimpleNamespace(
            id=40, author=SimpleNamespace(id=50, bot=False, display_name="Stafi"),
            type=discord.MessageType.default, reference=None, content="Mesazh i vjetër",
            created_at=now - timedelta(days=90), mentions=[], attachments=[object()],
        )
        thread = Mock(spec=discord.Thread, parent_id=20, fetch_message=AsyncMock(return_value=message))
        thread.is_private.return_value = False
        guild = SimpleNamespace(get_channel_or_thread=Mock(return_value=None), fetch_channel=AsyncMock(return_value=thread))
        bot = SimpleNamespace(get_guild=Mock(return_value=guild), bridge=AsyncMock(side_effect=[
            {"ga_user_id": "30"}, httpx.ReadTimeout("simulated"), {"ok": True},
        ]))
        event = SimpleNamespace(guild_id=10, channel_id=21, user_id=30, message_id=40,
                                emoji=SimpleNamespace(id=None, name="👍"))
        with patch.object(worker.asyncio, "sleep", AsyncMock()):
            asyncio.run(worker.capture_reaction(bot, event, now))

        first, retry = bot.bridge.await_args_list[1:]
        assert first == retry
        route, payload = first.args
        assert route == "/bot/ga-reactions"
        assert payload["observed_at"] == now.isoformat()
        assert payload["message_author_id"] == "50"
        assert payload["message_channel_id"] == "21"
        assert payload["attachment_count"] == 1
        assert payload["emoji"] == "👍"
        thread.fetch_message.assert_awaited_once_with(40)


    def test_worker_excludes_private_threads_and_reactions_from_other_people(self):
        thread = Mock(spec=discord.Thread, parent_id=20, fetch_message=AsyncMock())
        thread.is_private.return_value = True
        guild = SimpleNamespace(get_channel_or_thread=Mock(return_value=thread))
        bot = SimpleNamespace(get_guild=Mock(return_value=guild), bridge=AsyncMock(return_value={"ga_user_id": "30"}))
        event = SimpleNamespace(guild_id=10, channel_id=21, user_id=99, message_id=40)

        asyncio.run(worker.capture_reaction(bot, event, datetime.now(timezone.utc)))
        bot.bridge.assert_not_awaited()
        thread.is_private.return_value = False
        asyncio.run(worker.capture_reaction(bot, event, datetime.now(timezone.utc)))
        bot.bridge.assert_awaited_once_with("/bot/ga-replies/context", {})
        thread.fetch_message.assert_not_awaited()


    def test_bridge_only_stores_verified_staff_and_accepts_idempotent_retries(self):
        from app.api.routers.discord_assistant import require_bot, router

        route = next(route for route in router.routes if route.path == "/bot/ga-reactions")
        assert require_bot in [dependency.call for dependency in route.dependant.dependencies]
        self.enterContext(patch.object(service, "ga_identity", AsyncMock(return_value="30")))
        event = service.ReactionEvidence(
            event_id=uuid4(), guild_id="10", channel_id="20", ga_user_id="30", message_id="40",
            message_author_id="50", message_content="Mesazh i stafit https://example.test/internal",
            message_channel_id="21", has_attachments=True, attachment_count=1, emoji="👍", observed_at=datetime.now(timezone.utc),
        )
        staff_lookup = Mock()
        db = SimpleNamespace(execute=AsyncMock(return_value=staff_lookup), commit=AsyncMock())

        with self.assertRaises(HTTPException) as error:
            asyncio.run(service.record_reaction(db, event.model_copy(update={"ga_user_id": "99"})))
        assert error.exception.status_code == 409
        db.execute.assert_not_awaited()

        staff_lookup.scalar_one_or_none.return_value = None
        asyncio.run(service.record_reaction(db, event))
        db.commit.assert_not_awaited()

        staff_lookup.scalar_one_or_none.return_value = "Emër Stafi"
        asyncio.run(service.record_reaction(db, event))
        statement = db.execute.await_args.args[0].compile(dialect=postgresql.dialect())
        assert "ON CONFLICT (event_id) DO NOTHING" in str(statement)
        assert statement.params["event_id"] == event.event_id
        assert statement.params["message_excerpt"] == "Mesazh i stafit"
        assert statement.params["message_author_id"] == "50"
        assert statement.params["message_channel_id"] == "21"
        assert statement.params["attachment_count"] == 1
        db.commit.assert_awaited_once()

    def test_report_uses_observed_time_window_and_renders_table(self):
        for report, module, expected_start in (
            ("M1", morning_report, (20, 16, 30)),
            ("M2", after_break_report, (23, 8, 0)),
        ):
            with self.subTest(report=report):
                self.assert_report_table(report, module, expected_start)

    def test_drafts_recover_late_reaction_records_at_the_original_generation_cutoff(self):
        cutoff = datetime(2026, 11, 23, 11, 30, tzinfo=report_timezone())
        sections = [{"section_key": service.GA_REACTIONS_SECTION_KEY, "body": service.NO_REACTIONS_RECORDED}]
        snapshot = {"ga_replies_generated_at": cutoff.isoformat()}
        for report in ("M1", "M2"):
            with self.subTest(report=report), patch.object(service, "reaction_summary_for_day", AsyncMock(return_value="Recovered")) as summary:
                refreshed = asyncio.run(service.refresh_ga_reaction_section(
                    None, sections, cutoff.date(), report=report, generated_snapshot=snapshot, sent=False,
                ))
                assert refreshed[0]["body"] == "Recovered"
                frozen = asyncio.run(service.refresh_ga_reaction_section(
                    None, sections, cutoff.date(), report=report, generated_snapshot=snapshot, sent=True,
                ))
                assert frozen == sections
                summary.assert_awaited_once_with(None, cutoff.date(), report=report, generated_at=cutoff)

    def test_legacy_m2_draft_uses_the_same_cutoff_for_replies_and_reactions(self):
        sections = [
            {"section_key": after_break_report.GA_REPLIES_SECTION_TITLE, "body": "Old replies"},
            {"section_key": service.GA_REACTIONS_SECTION_KEY, "body": "Old reactions"},
        ]
        day = datetime.now(report_timezone()).date()
        with patch.object(after_break_report, "summary_for_day", AsyncMock(return_value="New replies")) as replies:
            with patch.object(service, "reaction_summary_for_day", AsyncMock(return_value="New reactions")) as reactions:
                refreshed = asyncio.run(after_break_report.refresh_after_break_discord_sections(
                    None, sections, day, generated_snapshot=None, sent=False, sent_at=None,
                ))
        assert [section["body"] for section in refreshed] == ["New replies", "New reactions"]
        assert replies.await_args == reactions.await_args
        assert replies.await_args.kwargs["report"] == "M2"

    def test_report_only_instance_reads_the_channel_and_recovers_a_sent_unavailable_section(self):
        cutoff = datetime(2026, 11, 24, 9, 3, tzinfo=report_timezone())
        snapshot = {"ga_replies_generated_at": cutoff.isoformat()}
        sections = [{"section_key": service.GA_REACTIONS_SECTION_KEY, "body": service.REACTIONS_UNAVAILABLE}]
        row = SimpleNamespace(staff_name="Laurent", message_excerpt="Po mendon Puris apo?", emoji="👍",
                              observed_at=cutoff - timedelta(minutes=10), attachment_count=0)
        with patch.object(settings, "DISCORD_GUILD_ID", None):
            for report, expected_start in (("M1", (23, 16, 30)), ("M2", (24, 8, 0))):
                with self.subTest(report=report):
                    db = SimpleNamespace(scalars=AsyncMock(return_value=Mock(all=Mock(return_value=[row]))))
                    refreshed = asyncio.run(service.refresh_ga_reaction_section(
                        db, sections, cutoff.date(), report=report, generated_snapshot=snapshot, sent=True,
                    ))
                    query = db.scalars.await_args.args[0].compile()
                    start = datetime(2026, 11, *expected_start, tzinfo=cutoff.tzinfo)
                    assert {"20", start, cutoff} <= set(query.params.values())
                    assert "discord_ga_reactions.guild_id =" not in str(query)
                    assert "Laurent" not in refreshed[0]["body"] and "👍" in refreshed[0]["body"]
                    assert _section_report_blocks(refreshed[0]["body"])[0]["rows"][0][1] == "L"

    def test_attachment_lookup_requires_reaction_evidence_and_reads_the_message_thread(self):
        cutoff = datetime(2026, 11, 23, 11, 30, tzinfo=report_timezone())
        row = SimpleNamespace(message_id="40", message_author_id="50", message_channel_id="21", attachment_count=1)
        scalar = Mock(all=Mock(return_value=[row]))
        db = SimpleNamespace(scalars=AsyncMock(return_value=scalar))
        fetch = self.enterContext(patch.object(service, "fetch_discord_message_attachments", AsyncMock(return_value=[{"image": True}])))
        files = asyncio.run(service.reaction_attachment_links(db, cutoff.date(), "M2", cutoff, "40"))
        assert files == [{"image": True}]
        assert {"40", "20", "10", cutoff} <= set(db.scalars.await_args.args[0].compile().params.values())
        fetch.assert_awaited_once_with("21", "40", "50")

        scalar.all.return_value = []
        with self.assertRaises(HTTPException) as error:
            asyncio.run(service.reaction_attachment_links(db, cutoff.date(), "M2", cutoff, "41"))
        assert error.exception.status_code == 404
        fetch.assert_awaited_once()

    def test_old_sent_table_recovers_a_photo_from_matching_discord_evidence(self):
        cutoff = datetime(2026, 11, 23, 11, 30, tzinfo=report_timezone())
        reaction = SimpleNamespace(
            guild_id="10", channel_id="20", message_id="40", attachment_count=None,
            staff_name="Laurent Hoxha", message_excerpt="Foto e projektit", emoji="👍",
            observed_at=cutoff - timedelta(minutes=10),
        )
        evidence = {"guild_id": "10", "channel_id": "20", "messages": [
            {"id": "40", "thread_root_id": "21", "author_id": "50", "attachments": 1},
        ]}
        self.enterContext(patch.object(service, "_snapshot_for_day", AsyncMock(return_value=SimpleNamespace(evidence=evidence))))
        db = SimpleNamespace(scalars=AsyncMock(return_value=Mock(all=Mock(return_value=[reaction]))))
        columns = [column for column in service._COLUMNS if column[0] != "SKEDARËT"]
        body = "\n".join(after_break_report._ascii_table(service._CAPTION, columns, [
            ["1", "Laurent Hoxha", "Foto e projektit", "👍", "23.11.2026", "11:20"],
        ]))
        sections = [{"section_key": service.GA_REACTIONS_SECTION_KEY, "body": body}]
        refreshed = asyncio.run(service.refresh_ga_reaction_section(
            db, sections, cutoff.date(), report="M2", sent=True,
            generated_snapshot={"ga_replies_generated_at": cutoff.isoformat()},
        ))
        assert _section_report_blocks(refreshed[0]["body"])[0]["rows"][0] == [
            "1", "LH", "Foto e projektit", "👍", "1 https://discord.com/channels/10/21/40", "23.11.2026", "11:20",
        ]
        assert sections[0]["body"] == body

    def assert_report_table(self, report, module, expected_start):
        tz = report_timezone()
        cutoff = datetime(2026, 11, 23, 11, 30, tzinfo=tz)
        expected = datetime(2026, 11, *expected_start, tzinfo=tz)
        row = SimpleNamespace(staff_name="Emër Stafi", message_excerpt="Projekt | <detyrë>", emoji="👍",
                              observed_at=cutoff - timedelta(minutes=10), guild_id="10", channel_id="20",
                              message_id="40", message_channel_id="21", message_author_id="50", attachment_count=1)
        db = SimpleNamespace(scalars=AsyncMock(return_value=Mock(all=Mock(return_value=[row]))))
        body = asyncio.run(service.reaction_summary_for_day(db, cutoff.date(), report=report, generated_at=cutoff))
        query = db.scalars.await_args.args[0].compile()
        assert str(query).count("discord_ga_reactions.observed_at") >= 3
        assert {"10", "20", expected, cutoff} <= set(query.params.values())
        block, = _section_report_blocks(body)
        assert block["rows"] == [["1", "ES", "Projekt ¦ <detyrë>", "👍", "1 https://discord.com/channels/10/21/40", "23.11.2026", "11:20"]]

        sections = [{"title": service.GA_REACTIONS_SECTION_TITLE, "body": body}]
        html = module.render_html("Raporti", cutoff.date(), sections)
        assert "Projekt ¦ &lt;detyrë&gt;" in html and "👍" in html
        assert 'href="https://discord.com/channels/10/21/40"' in html
        assert "11:20" in module.render_plain_text("Raporti", cutoff.date(), sections)
        docx = render_section_report_docx("Raporti", report, cutoff.date(), sections)
        with ZipFile(BytesIO(docx)) as document:
            xml = document.read("word/document.xml").decode("utf-8")
        assert "REAGIMI" in xml and "👍" in xml and "11:20" in xml
        png = render_section_report_png("Raporti", report, cutoff.date(), sections)
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
