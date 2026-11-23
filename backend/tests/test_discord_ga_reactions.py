import asyncio
from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4
from zipfile import ZipFile

import discord
import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

import discord_ga_replies as worker
from app.config import settings
from app.services import after_break_report, morning_report
from app.services import discord_ga_reactions as service
from app.services.meetings_report import _section_report_blocks, render_section_report_docx, render_section_report_png
from app.services.primeflow_report import report_timezone


@pytest.mark.parametrize("normalize", [
    morning_report.normalize_morning_report_sections,
    after_break_report.normalize_after_break_report_sections,
])
@pytest.mark.parametrize("has_saved_reactions", [False, True])
def test_reports_rename_reactions_without_losing_saved_evidence(normalize, has_saved_reactions):
    original = "A KA REACTION TE GRUPI?"
    saved = [{"section_key": original, "title": original, "body": "Reagim i ruajtur"}] if has_saved_reactions else []

    reactions = [section for section in normalize(saved) if section["section_key"] == original]

    assert len(reactions) == 1
    assert reactions[0]["title"] == "(GA) A KA REACTION NGA GA TEK DETYRAT NGA STAFI PER GA?"
    assert reactions[0]["body"] == ("Reagim i ruajtur" if has_saved_reactions else service.REACTIONS_UNAVAILABLE)


@pytest.fixture(autouse=True)
def channel_settings(monkeypatch):
    monkeypatch.setattr(settings, "DISCORD_GUILD_ID", "10")
    monkeypatch.setattr(settings, "DISCORD_GA_REPLIES_CHANNEL_ID", "20")


def test_worker_captures_ga_on_old_staff_message_and_retries_with_same_id(monkeypatch):
    now = datetime.now(timezone.utc)
    message = SimpleNamespace(
        id=40, author=SimpleNamespace(id=50, bot=False, display_name="Stafi"),
        type=discord.MessageType.default, reference=None, content="Mesazh i vjetër",
        created_at=now - timedelta(days=90), mentions=[], attachments=[],
    )
    thread = Mock(spec=discord.Thread, parent_id=20, fetch_message=AsyncMock(return_value=message))
    thread.is_private.return_value = False
    guild = SimpleNamespace(get_channel_or_thread=Mock(return_value=None), fetch_channel=AsyncMock(return_value=thread))
    bot = SimpleNamespace(get_guild=Mock(return_value=guild), bridge=AsyncMock(side_effect=[
        {"ga_user_id": "30"}, httpx.ReadTimeout("simulated"), {"ok": True},
    ]))
    event = SimpleNamespace(guild_id=10, channel_id=21, user_id=30, message_id=40,
                            emoji=SimpleNamespace(id=None, name="👍"))
    monkeypatch.setattr(worker.asyncio, "sleep", AsyncMock())
    asyncio.run(worker.capture_reaction(bot, event, now))

    first, retry = bot.bridge.await_args_list[1:]
    assert first == retry
    route, payload = first.args
    assert route == "/bot/ga-reactions"
    assert payload["observed_at"] == now.isoformat()
    assert payload["message_author_id"] == "50"
    assert payload["emoji"] == "👍"
    thread.fetch_message.assert_awaited_once_with(40)


def test_worker_excludes_private_threads_and_reactions_from_other_people():
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


def test_bridge_only_stores_verified_staff_and_accepts_idempotent_retries(monkeypatch):
    from app.api.routers.discord_assistant import require_bot, router

    route = next(route for route in router.routes if route.path == "/bot/ga-reactions")
    assert require_bot in [dependency.call for dependency in route.dependant.dependencies]
    monkeypatch.setattr(service, "ga_identity", AsyncMock(return_value="30"))
    event = service.ReactionEvidence(
        event_id=uuid4(), guild_id="10", channel_id="20", ga_user_id="30", message_id="40",
        message_author_id="50", message_content="Mesazh i stafit https://example.test/internal",
        has_attachments=False, emoji="👍", observed_at=datetime.now(timezone.utc),
    )
    staff_lookup = Mock()
    db = SimpleNamespace(execute=AsyncMock(return_value=staff_lookup), commit=AsyncMock())

    with pytest.raises(HTTPException) as error:
        asyncio.run(service.record_reaction(db, event.model_copy(update={"ga_user_id": "99"})))
    assert error.value.status_code == 409
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
    db.commit.assert_awaited_once()


@pytest.mark.parametrize(("report", "module", "expected_start"), [
    ("M1", morning_report, (20, 16, 30)),
    ("M2", after_break_report, (23, 8, 0)),
])
def test_report_uses_observed_time_window_and_renders_table(report, module, expected_start):
    tz = report_timezone()
    cutoff = datetime(2026, 11, 23, 11, 30, tzinfo=tz)
    expected = datetime(2026, 11, *expected_start, tzinfo=tz)
    row = SimpleNamespace(staff_name="Emër Stafi", message_excerpt="Projekt | <detyrë>", emoji="👍",
                          observed_at=cutoff - timedelta(minutes=10))
    db = SimpleNamespace(scalars=AsyncMock(return_value=Mock(all=Mock(return_value=[row]))))
    body = asyncio.run(service.reaction_summary_for_day(db, cutoff.date(), report=report, generated_at=cutoff))
    query = db.scalars.await_args.args[0].compile()
    assert str(query).count("discord_ga_reactions.observed_at") >= 3
    assert {"10", "20", expected, cutoff} <= set(query.params.values())
    block, = _section_report_blocks(body)
    assert block["rows"] == [["1", "Emër Stafi", "Projekt ¦ <detyrë>", "👍", "23.11.2026", "11:20"]]

    sections = [{"title": service.GA_REACTIONS_SECTION_TITLE, "body": body}]
    html = module.render_html("Raporti", cutoff.date(), sections)
    assert "Projekt ¦ &lt;detyrë&gt;" in html and "👍" in html
    assert "11:20" in module.render_plain_text("Raporti", cutoff.date(), sections)
    docx = render_section_report_docx("Raporti", report, cutoff.date(), sections)
    with ZipFile(BytesIO(docx)) as document:
        xml = document.read("word/document.xml").decode("utf-8")
    assert "REAGIMI" in xml and "👍" in xml and "11:20" in xml
    png = render_section_report_png("Raporti", report, cutoff.date(), sections)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
