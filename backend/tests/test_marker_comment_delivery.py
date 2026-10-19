import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.db import get_db
from app.services.marker_comments import marker_comment_source_key


def test_logical_comment_identity_prefers_the_note_over_per_user_task_copies():
    assert marker_comment_source_key(SimpleNamespace(id="first", ga_note_origin_id="shared")) == marker_comment_source_key(SimpleNamespace(id="second", ga_note_origin_id="shared"))
    assert marker_comment_source_key(SimpleNamespace(id="first", fast_task_group_id="shared")) == "group:shared"
    assert marker_comment_source_key(SimpleNamespace(id="plain")) == "task:plain"


def test_realtime_notifications_are_delivered_only_after_successful_endpoint():
    async def exercise():
        notification = SimpleNamespace(id="notification", user_id="recipient")
        session = SimpleNamespace(info={"pending_marker_notifications": [notification]})
        context = AsyncMock()
        context.__aenter__.return_value = session
        with patch("app.db.SessionLocal", return_value=context), patch("app.services.notifications.publish_notification", new_callable=AsyncMock) as publish:
            dependency = get_db()
            assert await anext(dependency) is session
            publish.assert_not_awaited()
            with pytest.raises(StopAsyncIteration):
                await anext(dependency)
            publish.assert_awaited_once_with(user_id="recipient", notification=notification)
            assert "pending_marker_notifications" not in session.info

        session.info["pending_marker_notifications"] = [notification]
        with patch("app.db.SessionLocal", return_value=context), patch("app.services.notifications.publish_notification", new_callable=AsyncMock) as publish:
            dependency = get_db()
            await anext(dependency)
            with pytest.raises(RuntimeError):
                await dependency.athrow(RuntimeError("endpoint rolled back"))
            publish.assert_not_awaited()
    asyncio.run(exercise())
