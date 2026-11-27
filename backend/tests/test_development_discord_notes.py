import asyncio
from datetime import datetime, time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.services import development_discord_notes as service


def test_windows_split_the_day_and_include_the_weekend_in_monday_m1():
    monday = datetime(2026, 11, 30, 17, 0, tzinfo=ZoneInfo("Europe/Tirane"))
    start, end = service._window("M1", monday)
    assert (start.day, start.time(), end.time()) == (27, time(16, 30), time(8, 15))
    assert service._window("M2", monday)[0] == end
    assert service._window("M3", monday)[0] == service._window("M2", monday)[1]
    assert service._window("M3", monday)[1].time() == time(16, 30)


@pytest.mark.parametrize("allowed", [True, False])
def test_only_linked_members_with_channel_history_can_read_posts(monkeypatch, allowed):
    monkeypatch.setattr(service.settings, "DISCORD_GUILD_ID", "1")
    monkeypatch.setattr(service.settings, "DISCORD_BOT_TOKEN", "test-token")
    db = SimpleNamespace(scalar=AsyncMock(return_value="4"))
    requested = []
    channel = {
        "id": "2", "name": "zhvillim-text", "type": 0,
        "permission_overwrites": [] if allowed else [
            {"id": "4", "type": 1, "allow": "0", "deny": str(service.READ_PERMISSIONS)},
        ],
    }
    sample = {"id": "3", "channel_id": "2", "timestamp": "2026-11-27T10:00:00+01:00",
              "content": "Shënim\nRreshti 2", "author": {"username": "Autor"},
              "attachments": [{"filename": "udhëzime.pdf"}]}
    responses = {
        "/api/v10/guilds/1": {"id": "1", "owner_id": "99", "roles": [
            {"id": "1", "permissions": str(service.READ_PERMISSIONS)},
        ]},
        "/api/v10/guilds/1/channels": [channel, {**channel, "id": "6", "type": 2}],
        "/api/v10/guilds/1/members/4": {"roles": []},
        "/api/v10/guilds/1/members/5": {"roles": []},
        "/api/v10/users/@me": {"id": "5"},
        "/api/v10/channels/2/messages": [sample, {**sample, "id": "7", "channel_id": "6"},
                                        {**sample, "id": "8", "timestamp": "2026-11-27T12:00:00+01:00"}],
    }

    def respond(request):
        requested.append(request.url.path)
        return httpx.Response(200, json=responses[request.url.path])

    client = httpx.AsyncClient
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs))
    result = asyncio.run(service.load_development_discord_notes(
        db, SimpleNamespace(id="user"), "M2", datetime(2026, 11, 27, 13, tzinfo=ZoneInfo("Europe/Tirane")),
    ))
    assert any(path.endswith("/messages") for path in requested) == allowed
    if allowed:
        assert result["rows"] == [{
            "id": "3", "title": "Autor", "detail": "Shënim\nRreshti 2\nSkedarë: udhëzime.pdf",
            "labels": ["27.11.2026 10:00"], "href": "https://discord.com/channels/1/2/3",
        }]
    else:
        assert result["rows"] == []
        assert "nuk ka leje leximi" in result["message"]
