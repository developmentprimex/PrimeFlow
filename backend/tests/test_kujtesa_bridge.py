"""The adapter is tested without connecting to Discord or a live API."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock


def adapter():
    spec = importlib.util.spec_from_file_location("kujtesa_primeflow_adapter", Path(__file__).resolve().parents[1] / "integrations/kujtesa/primeflow_bot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class KujtesaBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_readiness_requires_discord_membership_and_is_removed_on_disconnect(self):
        m = adapter()
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "worker.json"
            bot = m.KujtesaBridge("http://127.0.0.1:8000/api", "test-key", status_path=path)
            bot.expected_guild_id = "111111111111111111"
            bot.is_ready = Mock(return_value=True)
            bot.get_guild = Mock(return_value=object())
            bot.publish_ready_status()
            self.assertTrue(path.exists())
            await bot.on_disconnect()
            self.assertFalse(path.exists())
            bot.get_guild.return_value = None
            bot.publish_ready_status()
            self.assertFalse(path.exists())
            await bot.close()

    async def test_disabled_delivery_only_sends_a_health_request(self):
        m = adapter()
        bot = m.KujtesaBridge("http://127.0.0.1:8000/api", "test-bridge-key", reminders_enabled=False)
        bot.api = AsyncMock(return_value={"enabled": False, "deliveries": [], "updates": []})
        bot.deliver = AsyncMock()
        await bot.tick()
        bot.api.assert_awaited_once_with("/poll", {"delivery_enabled": False})
        bot.deliver.assert_not_awaited()
        await bot.close()

    async def test_each_send_revalidates_and_failed_prepare_cannot_send(self):
        m = adapter()
        bot = m.KujtesaBridge("http://127.0.0.1:8000/api", "test-bridge-key", reminders_enabled=True)
        bot.api = AsyncMock(side_effect=m.BridgeError(409, "changed"))
        bot.destination = AsyncMock()
        await bot.deliver({"id": "id", "lease": "lease"})
        bot.destination.assert_not_awaited()
        await bot.close()

    async def test_dm_failure_never_falls_back_to_the_shared_channel(self):
        m = adapter()
        bot = m.KujtesaBridge("http://127.0.0.1:8000/api", "test-bridge-key", reminders_enabled=True)
        card = {"id": "id", "lease": "lease", "target": {"kind": "dm", "user_id": "111111111111111111"}}
        bot.api = AsyncMock(return_value=card)
        bot.destination = AsyncMock(side_effect=m.DeliveryFailure("blocked_dm"))
        bot.record = AsyncMock()
        await bot.deliver(card)
        bot.destination.assert_awaited_once_with(card)
        self.assertEqual(bot.record.call_args.args[1]["outcome"], "failed")
        self.assertEqual(bot.record.call_args.args[1]["error"], "blocked_dm")
        await bot.close()

    async def test_receipt_survives_restart_until_server_acknowledges(self):
        m = adapter()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "receipts.json"
            store = m.ReceiptStore(path)
            body = {"lease": "test-lease", "outcome": "sent", "channel_id": "1", "message_id": "2"}
            store.put("delivery", body)
            self.assertEqual(m.ReceiptStore(path).pending(), {"delivery": body})
            store.remove("delivery")
            self.assertEqual(m.ReceiptStore(path).pending(), {})

    async def test_failed_card_refresh_reports_backoff_without_sending_a_message(self):
        m = adapter()
        bot = m.KujtesaBridge("http://127.0.0.1:8000/api", "test-bridge-key", reminders_enabled=True)
        card = {"id": "id", "channel_id": "555555555555555555", "message_id": "666666666666666666", "sync_key": "a"*64}
        bot.api = AsyncMock(side_effect=[{"enabled": True, "deliveries": [], "updates": [card]}, {"recorded": True}])
        bot.destination = AsyncMock(side_effect=m.DeliveryFailure("permissions"))
        await bot.tick()
        self.assertEqual(bot.api.await_count, 2)
        self.assertEqual(bot.api.call_args.args[0], "/deliveries/id/sync")
        self.assertEqual(bot.api.call_args.args[1]["error"], "permissions")
        await bot.close()

    async def test_card_mentions_are_disabled_and_custom_ids_use_only_server_references(self):
        m = adapter()
        card = {"id": "11111111-1111-4111-8111-111111111111", "title": "@everyone Test", "names": ["A"],
                "due_at": "2026-11-07T16:00:00+00:00", "phase": "after", "status": "pending"}
        view = m.card_view(card)
        self.assertTrue(all(item.custom_id.startswith("gap:"+card["id"]+":") for item in view.children))
        self.assertIn("konfirmo", m.card_text(card).lower())
        self.assertLessEqual(len(m.card_text({**card, "title": "x" * 3000})), 2000)


if __name__ == "__main__":
    unittest.main()
