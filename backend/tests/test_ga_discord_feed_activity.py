import asyncio
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

os.environ.setdefault("JWT_SECRET", "test-only-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")

from app.api.deps import get_current_user
from app.config import settings
from app.db import get_db
from app.models.enums import UserRole
from app.services import ga_discord_mentions as mentions


def event(sequence, kind, user_id=None, emoji="✅", *, burst=False):
    return SimpleNamespace(sequence=sequence, kind=kind, user_id=user_id, emoji_key=emoji, burst=burst)


def snapshot(users, sequence):
    return SimpleNamespace(
        reactions=[{"emoji": "✅", "count": len(users), "users": users}],
        reactions_synced_at=True,
        reaction_sequence=sequence,
    )


GA = {"discord_id": "42", "name": "GA"}
BOT = {"discord_id": "99", "name": "GA bot", "ga_bot": True, "bot": True}
LIRA = {"discord_id": "4", "name": "Lira"}
ARTA = {"discord_id": "5", "name": "Arta"}


def test_staff_reactors_use_observed_add_order_and_names():
    row = snapshot([GA, LIRA, ARTA], 3)
    events = [event(3, "add", "5"), event(1, "add", "4"), event(2, "add", "42")]
    assert mentions.feed_reaction_activity(row, events, "42", {"4": "Lira Hoxha"}) == (True, ["Lira Hoxha"], True)


def test_our_bot_counts_as_ga_and_a_readd_replaces_the_original_position():
    row = snapshot([LIRA, BOT], 4)
    events = [event(1, "add", "4"), event(2, "add", "99"), event(3, "remove", "4"), event(4, "add", "4")]
    assert mentions.feed_reaction_activity(row, events, "42", {}) == (True, [], True)


def test_emoji_clear_removes_prior_evidence():
    row = snapshot([LIRA, GA], 5)
    events = [
        event(1, "add", "4"), event(2, "add", "42"), event(3, "clear_emoji"),
        event(4, "add", "42"), event(5, "add", "4"),
    ]
    assert mentions.feed_reaction_activity(row, events, "42", {}) == (True, [], True)


@pytest.mark.parametrize("events", [[], [event(1, "add", "4"), event(3, "add", "42")]])
def test_snapshot_or_incomplete_gateway_history_does_not_imply_order(events):
    row = snapshot([LIRA, GA], 3)
    assert mentions.feed_reaction_activity(row, events, "42", {}) == (True, [], False)


def test_no_current_ga_reaction_leaves_a_staff_reaction_without_a_cutoff():
    row = snapshot([LIRA], 1)
    assert mentions.feed_reaction_activity(row, [event(1, "add", "4")], "42", {}) == (False, [], False)


def test_gateway_events_stay_in_the_staff_archive_and_order_resets_on_disconnect():
    discord = pytest.importorskip("discord")
    from discord_ga_mentions import GaMentionsBot

    async def exercise():
        bot = GaMentionsBot()
        bot.context = {"guild_id": "1", "staff_channel_id": "20"}
        bot.post_batch = AsyncMock(return_value=True)
        public_thread = discord.Thread.__new__(discord.Thread)
        public_thread.parent_id = 20
        public_thread._type = discord.ChannelType.public_thread
        private_thread = discord.Thread.__new__(discord.Thread)
        private_thread.parent_id = 20
        private_thread._type = discord.ChannelType.private_thread
        bot.get_channel = {50: public_thread, 51: private_thread}.get
        try:
            def make(channel_id):
                return SimpleNamespace(guild_id=1, channel_id=channel_id, message_id=33, user_id=4, emoji="✅")

            await bot.on_raw_reaction_add(make(51))
            await bot.on_raw_reaction_add(make(50))
            await bot.on_raw_reaction_remove(make(50))
            await bot.on_disconnect()
            await bot.on_raw_reaction_add(make(50))
            events = [call.args[1] for call in bot.post_batch.await_args_list]
            assert [(item["kind"], item["parent_channel_id"], item["sequence"]) for item in events] == [
                ("add", "20", 1), ("remove", "20", 2), ("add", "20", 1),
            ]
            assert events[0]["session_id"] == events[1]["session_id"] != events[2]["session_id"]
        finally:
            tasks = list(bot.pending_reactions.values())
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await bot.close()

    asyncio.run(exercise())


@pytest.mark.skipif(
    os.environ.get("PRIMEFLOW_DB_TESTS") != "1"
    or not (make_url(settings.DATABASE_URL).database or "").endswith("_test"),
    reason="Needs a migrated *_test PostgreSQL database",
)
def test_feed_surfaces_reply_and_order_for_staff_mentions(monkeypatch):
    monkeypatch.setattr(settings, "DISCORD_GUILD_ID", "1")
    monkeypatch.setattr(settings, "DISCORD_GA_REPLIES_CHANNEL_ID", "20")
    monkeypatch.setattr(settings, "GA_DISCORD_USER_ID", "42")
    monkeypatch.setattr(settings, "GA_DISCORD_MENTIONS_BOT_TOKEN", "test-token")
    asyncio.run(_exercise_bridge_and_feed())


async def _exercise_bridge_and_feed():
    from app.api.routers import ga_assistant, ga_discord_bot

    now = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
    session = "a" * 32
    anchor = {
        "id": "500", "guild_id": "1", "channel_id": "20", "channel_name": "staff",
        "author_discord_id": "77", "author_name": "Sender", "created_at": now.isoformat(),
        "content": "@GA please review", "jump_url": "https://discord.com/channels/1/20/500",
    }
    thread = {**anchor, "id": "501", "channel_id": "500", "parent_channel_id": "20",
              "created_at": (now + timedelta(minutes=1)).isoformat()}
    reply = {**thread, "id": "502", "author_discord_id": "42", "author_name": "GA", "content": "Reviewed"}
    legacy = {**anchor, "id": "499", "created_at": (now - timedelta(minutes=1)).isoformat()}
    app = FastAPI()
    app.include_router(ga_assistant.router, prefix="/assistant")
    app.include_router(ga_discord_bot.router, prefix="/bot")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=UserRole.ADMIN)
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as conn, conn.begin() as transaction:  # noqa: SIM117
            async with AsyncSession(bind=conn, join_transaction_mode="create_savepoint") as db:
                app.dependency_overrides[get_db] = lambda: db
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    bot = {"X-GA-Mentions-Secret": mentions.bridge_secret()}

                    async def bridge(path, data):
                        response = await client.post(f"/bot/{path}", json=data, headers=bot)
                        assert response.status_code == 200, response.text

                    await bridge("mentions", {"messages": [
                        {**item, "reasons": ["mention"]} for item in (anchor, thread, legacy)
                    ]})
                    for seq, user_id in ((2, "99"), (1, "4"), (3, "5"), (2, "99")):
                        await bridge("reaction-events", {
                            "message_id": "500", "guild_id": "1", "channel_id": "20", "session_id": session,
                            "sequence": seq, "kind": "add", "user_id": user_id, "emoji_key": "✅",
                        })
                    snapshot_time = (now + timedelta(minutes=5)).isoformat()
                    reactions = [{"emoji": "✅", "count": 3, "users": [BOT, LIRA, ARTA]}]
                    live = {**anchor, "reactions": reactions, "reactions_synced_at": snapshot_time,
                            "reaction_session_id": session, "reaction_sequence": 3}
                    historical = {**legacy, "reactions": reactions, "reactions_synced_at": snapshot_time}
                    await bridge("channel-messages", {"messages": [live, thread, reply, historical]})
                    await bridge("reactions", {"message_id": "500", "reactions": reactions, "observed_at": snapshot_time})

                    response = await client.get("/assistant/discord/mentions/feed")
                    assert response.status_code == 200, response.text
                    active, old = response.json()["items"]
                    assert [active["id"], old["id"]] == ["dc:500", "dc:499"]
                    assert active["ga_replied"] and active["ga_reacted"]
                    assert active["context"]["përgjigjet"][1]["id"] == "dc:502"
                    assert active["others_reacted_before_ga"]
                    assert active["others_reacted_before_ga_names"] == ["Lira"]
                    assert active["others_reacted_before_ga_known"]
                    assert old["ga_reacted"] and not old["ga_replied"] and not old["others_reacted_before_ga_known"]
                    assert (await client.get("/assistant/discord/mentions/feed", params={"before": "501"})).status_code == 422
                await transaction.rollback()
    finally:
        await engine.dispose()
