from __future__ import annotations

import copy
import unittest
import uuid
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.api.routers import today_print_report as routes
from app.services import today_print_report_freeze as freeze

DAY = date(2026, 10, 2)
TZ = ZoneInfo("Europe/Tirane")


def clock(hour=16, minute=0, second=0, day=2):
    return datetime(2026, 10, day, hour, minute, second, tzinfo=TZ)


def report():
    return {"target_date": DAY.isoformat(), "subject": "1H SHTYPI SOT", "html": '<table style="background:#FFFF00">Before</table>',
            "content_html": "Before", "plain_text": "Before", "attachments": [
                ("report.png", b"original png", "image/png"),
                ("report.xlsx", b"original xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ]}


def row():
    stored = freeze.pack_report(report())
    stored.update({"frozen_at": clock().isoformat(), "source_captured_at": clock(15, 59, 59).isoformat()})
    return SimpleNamespace(id=uuid.uuid4(), report_kind=freeze.FROZEN_KIND, report_date=DAY,
                           report_payload=stored, generated_by_user_id=None, updated_at=clock())


class FreezeTests(unittest.IsolatedAsyncioTestCase):
    def test_cutoff_timezone_and_next_day_are_date_scoped(self):
        self.assertFalse(freeze.is_closed(DAY, clock(15, 59, 59)))
        self.assertTrue(freeze.is_closed(DAY, clock()))
        self.assertTrue(freeze.is_closed(DAY, clock().astimezone(ZoneInfo("UTC"))))
        self.assertFalse(freeze.is_closed(date(2026, 10, 3), clock(0, 0, day=3)))
        self.assertTrue(freeze.is_closed(DAY, clock(0, 0, day=3)))
        self.assertEqual(freeze.view_metadata(DAY, clock())["next_day_at"], clock(0, 0, day=3).isoformat())

    async def test_after_cutoff_html_and_attachment_bytes_are_immutable(self):
        stored = row()
        before = copy.deepcopy(stored.report_payload)
        with patch.object(freeze, "local_now", return_value=clock(18)), \
             patch.object(freeze, "get_one_h_print_snapshot", AsyncMock(return_value=stored)), \
             patch.object(freeze, "build_today_print_report", AsyncMock()) as live:
            preview = await freeze.today_report(AsyncMock(), DAY)
            email = await freeze.today_report(AsyncMock(), DAY, include_attachment=True)
        live.assert_not_awaited()
        self.assertEqual(preview["html"], report()["html"])
        self.assertNotIn("attachments", preview)
        self.assertNotIn("frozen_attachments", preview)
        self.assertEqual(email["attachments"], report()["attachments"])
        self.assertTrue(email["is_frozen"])
        self.assertEqual(stored.report_payload, before)

    async def test_before_cutoff_uses_latest_data_and_next_day_is_live(self):
        for day, now in [(DAY, clock(15, 59)), (date(2026, 10, 3), clock(8, day=3))]:
            with patch.object(freeze, "local_now", return_value=now), \
                 patch.object(freeze, "build_today_print_report", AsyncMock(return_value=report())) as live, \
                 patch.object(freeze, "get_one_h_print_snapshot", AsyncMock()) as snapshot:
                result = await freeze.today_report(AsyncMock(), day)
            live.assert_awaited_once_with(day, include_attachment=False)
            snapshot.assert_not_awaited()
            self.assertFalse(result["is_frozen"])

    async def test_in_flight_generation_crossing_cutoff_returns_frozen_data(self):
        with patch.object(freeze, "is_closed", side_effect=[False, True]), \
             patch.object(freeze, "local_now", return_value=clock(15, 59)), \
             patch.object(freeze, "build_today_print_report", AsyncMock(return_value={"html": "Late"})), \
             patch.object(freeze, "frozen_report", AsyncMock(return_value={"html": "Before", "is_frozen": True})) as frozen:
            result = await freeze.today_report(AsyncMock(), DAY)
        self.assertEqual(result["html"], "Before")
        frozen.assert_awaited_once()

    async def test_missing_archive_does_not_reconstruct_from_post_cutoff_data(self):
        with patch.object(freeze, "local_now", return_value=clock(18)), \
             patch.object(freeze, "get_one_h_print_snapshot", AsyncMock(return_value=None)), \
             patch.object(freeze, "build_today_print_report", AsyncMock()) as live:
            with self.assertRaises(freeze.TodayPrintFreezeMissing):
                await freeze.today_report(AsyncMock(), DAY)
        live.assert_not_awaited()

    async def test_capture_uses_one_repeatable_read_for_friday_and_monday_meetings(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.execute.return_value.scalar = MagicMock(return_value=True)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=db)
        context.__aexit__ = AsyncMock(return_value=None)
        payload = {"week_end": "2026-10-04", "items": {}}
        async def get_snapshot(*args):
            return db.add.call_args.args[0] if db.add.called else None
        with patch.object(freeze, "local_now", return_value=clock(15, 59, 59)), \
             patch.object(freeze, "SessionLocal", return_value=context), \
             patch.object(freeze, "get_one_h_print_snapshot", side_effect=get_snapshot), \
             patch.object(freeze, "_source_payload", AsyncMock(return_value=payload)) as source, \
             patch.object(freeze, "build_today_print_report", AsyncMock(return_value=report())) as render:
            self.assertTrue(await freeze.capture_today_print_report())
        self.assertEqual([call.args[1] for call in source.await_args_list], [DAY, date(2026, 10, 5)])
        self.assertIn("REPEATABLE READ", str(db.execute.await_args_list[0].args[0]))
        self.assertIs(render.await_args.kwargs["payload"], payload)
        self.assertIs(render.await_args.kwargs["next_day_payload"], payload)
        saved = db.add.call_args.args[0]
        self.assertEqual(saved.report_kind, freeze.FROZEN_KIND)
        self.assertEqual(saved.report_payload["source_captured_at"], clock(15, 59, 59).isoformat())
        self.assertTrue(saved.report_payload["frozen_attachments"])
        self.assertEqual(saved.report_payload["one_h_strikes"]["captured_at"], clock(15, 59, 59).isoformat())
        self.assertEqual(db.commit.await_count, 2)
        self.assertNotIn("freeze_source", saved.report_payload)

    async def test_export_failure_can_recover_from_saved_source_after_cutoff(self):
        db = AsyncMock()
        pending = row()
        pending.report_payload = {
            "frozen_at": clock().isoformat(), "source_captured_at": clock(15, 59, 59).isoformat(),
            "freeze_source": {"payload": {"items": {"before": []}}, "next_day_payload": {"items": {}}},
        }
        with patch.object(freeze, "local_now", return_value=clock(18)), \
             patch.object(freeze, "get_one_h_print_snapshot", AsyncMock(return_value=pending)), \
             patch.object(freeze, "build_today_print_report", AsyncMock(side_effect=[RuntimeError("export failed"), report()])) as render, \
             patch.object(freeze, "_source_payload", AsyncMock()) as live_source:
            with self.assertRaises(RuntimeError):
                await freeze.frozen_report(db, DAY)
            self.assertIn("freeze_source", pending.report_payload)
            result = await freeze.frozen_report(db, DAY, include_attachment=True)
        self.assertEqual(result["attachments"], report()["attachments"])
        self.assertEqual(render.await_args.kwargs["payload"], {"items": {"before": []}})
        live_source.assert_not_awaited()
        self.assertNotIn("freeze_source", pending.report_payload)

    async def test_frozen_total_only_includes_tasks_in_rendered_report(self):
        shown_id, excluded_id = str(uuid.uuid4()), str(uuid.uuid4())
        summary = {"active_slot": "16:00", "tasks": {shown_id: {"16:00": 3}, excluded_id: {"16:00": 7}}}
        pending = row()
        pending.report_payload = {
            "frozen_at": clock().isoformat(), "source_captured_at": clock(15, 59, 59).isoformat(),
            "freeze_source": {"payload": {"items": {}, "one_h_strikes": summary}, "next_day_payload": {}},
        }
        rendered = {**report(), "html": f'<td data-task-id="{shown_id}">Task</td><td data-task-id="{shown_id}">Repeated</td>'}
        with patch.object(freeze, "get_one_h_print_snapshot", AsyncMock(return_value=pending)), \
             patch.object(freeze, "build_today_print_report", AsyncMock(return_value=rendered)), \
             patch.object(freeze, "task_strike_summary", AsyncMock()) as live_counts:
            result = await freeze._finish_frozen_report(AsyncMock(), DAY)
        self.assertEqual(result.report_payload["one_h_strikes"]["tasks"], {shown_id: {"16:00": 3}})
        self.assertEqual(summary["tasks"][excluded_id]["16:00"], 7)
        live_counts.assert_not_awaited()

    async def test_capture_skips_existing_archive_and_refuses_connection_delay_past_cutoff(self):
        db = AsyncMock()
        db.execute.return_value.scalar = MagicMock(return_value=True)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=db)
        context.__aexit__ = AsyncMock(return_value=None)
        for times in ([clock(15, 59, 59)] * 3, [clock(15, 59, 59), clock(), clock()]):
            with patch.object(freeze, "local_now", side_effect=times), \
                 patch.object(freeze, "SessionLocal", return_value=context), \
                 patch.object(freeze, "get_one_h_print_snapshot", AsyncMock(return_value=row())), \
                 patch.object(freeze, "_source_payload", AsyncMock()) as source:
                self.assertFalse(await freeze.capture_today_print_report())
            source.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_capture_never_backfills_and_is_idempotent_across_workers(self):
        with patch.object(freeze, "local_now", return_value=clock()), \
             patch.object(freeze, "SessionLocal") as session:
            self.assertFalse(await freeze.capture_today_print_report())
            session.assert_not_called()
        db = AsyncMock()
        db.execute.return_value.scalar = MagicMock(return_value=False)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=db)
        context.__aexit__ = AsyncMock(return_value=None)
        with patch.object(freeze, "local_now", return_value=clock(15, 59, 59)), \
             patch.object(freeze, "SessionLocal", return_value=context), \
             patch.object(freeze, "_source_payload", AsyncMock()) as source:
            self.assertFalse(await freeze.capture_today_print_report())
        source.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_all_today_read_routes_and_regenerate_use_frozen_copy(self):
        with patch.object(routes, "is_closed", return_value=True), \
             patch.object(routes, "frozen_report", AsyncMock(return_value={"html": "Before", "is_frozen": True})), \
             patch.object(routes, "today_report", AsyncMock(return_value={"html": "Before", "is_frozen": True})), \
             patch.object(routes, "save_one_h_print_snapshot", AsyncMock()) as save:
            db = AsyncMock()
            user = SimpleNamespace(id=uuid.uuid4())
            for endpoint in [routes.get_snapshot, routes.generate_snapshot, routes.preview, routes.print_preview]:
                kwargs = {"report_date": DAY, "db": db, "user" if endpoint == routes.generate_snapshot else "_": user}
                self.assertEqual((await endpoint(**kwargs))["html"], "Before")
            save.assert_not_awaited()

    async def test_next_day_does_not_load_yesterdays_snapshot(self):
        day = date(2026, 10, 3)
        with patch.object(routes, "is_closed", return_value=False), \
             patch.object(routes, "get_one_h_print_snapshot", AsyncMock(return_value=None)) as get:
            with self.assertRaises(HTTPException) as error:
                await routes.get_snapshot(report_date=day, db=AsyncMock(), _=None)
        self.assertEqual(error.exception.status_code, 404)
        self.assertEqual(get.await_args.args[2], day)

    async def test_manual_send_uses_archived_html_and_exact_artifacts(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)
        settings = SimpleNamespace(recipients={"to": ["test@example.com"], "cc": [], "bcc": []})
        frozen = {**report(), "is_frozen": True}
        with patch.object(routes, "_settings_row", AsyncMock(return_value=settings)), \
             patch.object(routes, "_report", AsyncMock(return_value=frozen)) as build, \
             patch.object(routes, "send_tomorrow_print_report", AsyncMock(return_value={"id": "test"})) as smtp:
            await routes.send(report_date=DAY, db=db, _=None)
        build.assert_awaited_once_with(db, DAY, include_attachment=True)
        self.assertIs(smtp.await_args.args[0], frozen)
        self.assertEqual(smtp.await_args.args[0]["attachments"], report()["attachments"])


if __name__ == "__main__":
    unittest.main()
