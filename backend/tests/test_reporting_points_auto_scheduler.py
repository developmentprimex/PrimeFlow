import unittest
import uuid
from contextlib import ExitStack
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.models.m2_reporting_points import M2ReportingPointsReport
from app.models.m3_reporting_points import M3ReportingPointsReport
from app.services import m2_reporting_points as m2, m3_reporting_points as m3
from app.services import reporting_points_auto_scheduler as scheduler
from app.services.reporting_points_settings import default_settings
from tests.test_migration_graph import migration_scripts

DAY = date(2026, 10, 5)


def row_for(model):
    return model(id=uuid.uuid4(), report_date=DAY, data={}, status="SENT", auto_sent_at=None,
                 manual_answers={"reorganization": "Përgjigje e ruajtur"},
                 sent_at=datetime(2026, 10, 5, 9, tzinfo=timezone.utc))


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    def setup_scheduler(self, stack):
        stack.enter_context(patch.object(scheduler, "REPORT_SERVICES", (("M2", m2), ("M3", m3))))
        self.rows = {m2: row_for(M2ReportingPointsReport), m3: row_for(M3ReportingPointsReport)}
        self.db = AsyncMock()
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=self.db)
        context.__aexit__ = AsyncMock(return_value=False)
        self.session = stack.enter_context(patch.object(scheduler, "SessionLocal", return_value=context))
        self.settings = {name: default_settings(name) for name in ("M2", "M3")}
        async def configured(db, name, **kwargs):
            return self.settings[name]
        self.get_settings = stack.enter_context(patch.object(scheduler, "get_delivery_settings", new=AsyncMock(side_effect=configured)))
        self.locks, self.refreshes, self.sends = {}, {}, {}
        for service in (m2, m3):
            self.locks[service] = stack.enter_context(patch.object(service, "locked_report", new=AsyncMock(return_value=self.rows[service])))
            self.refreshes[service] = stack.enter_context(patch.object(service, "refresh_report", new=AsyncMock()))

            async def delivered(db, row, recipients, *, automatic):
                self.assertTrue(automatic)
                row.auto_sent_at = datetime.now(timezone.utc)

            self.sends[service] = stack.enter_context(patch.object(service, "send_report", new=AsyncMock(side_effect=delivered)))

    async def test_due_times_weekdays_and_timezone_conversion(self):
        for stamp, expected in (
            ("2026-10-05T12:14:59+02:00", (False, False)),
            ("2026-10-05T12:15:00+02:00", (True, False)),
            ("2026-10-05T16:19:59+02:00", (True, False)),
            ("2026-10-05T16:20:00+02:00", (True, True)),
            ("2026-10-05T10:15:00+00:00", (True, False)),
            ("2026-01-05T11:15:00+00:00", (True, False)),
            ("2026-10-03T16:20:00+02:00", (False, False)),
            ("2026-10-04T16:20:00+02:00", (False, False)),
        ):
            with self.subTest(stamp=stamp), ExitStack() as stack:
                self.setup_scheduler(stack)
                self.assertEqual(await scheduler.run_reporting_points_auto_scheduler_once(datetime.fromisoformat(stamp)), any(expected))
                for service, due in zip((m2, m3), expected):
                    self.assertEqual(self.sends[service].await_count, int(due))

    async def test_refreshes_even_after_manual_send_and_uses_exact_automatic_recipients(self):
        with ExitStack() as stack:
            self.setup_scheduler(stack)
            now = datetime.fromisoformat("2026-10-05T16:20:00+02:00")
            self.assertTrue(await scheduler.run_reporting_points_auto_scheduler_once(now))
            for service in (m2, m3):
                row = self.rows[service]
                self.locks[service].assert_awaited_once_with(self.db, DAY, wait=False)
                self.refreshes[service].assert_awaited_once_with(self.db, row, now)
                self.sends[service].assert_awaited_once_with(
                    self.db, row, {"to": ["ga@primexeu.com", "info@primexeu.com"], "cc": [], "bcc": []}, automatic=True)
                self.assertEqual(row.manual_answers, {"reorganization": "Përgjigje e ruajtur"})

    async def test_completed_automatic_deliveries_are_not_repeated_in_later_ticks_or_restarts(self):
        with ExitStack() as stack:
            self.setup_scheduler(stack)
            for row in self.rows.values():
                row.auto_sent_at = datetime.fromisoformat("2026-10-05T16:20:00+02:00")
                # Regeneration/manual edits cannot clear the durable marker.
                row.status = "DRAFT"
            for stamp in ("2026-10-05T16:20:30+02:00", "2026-10-05T20:00:00+02:00"):
                self.assertFalse(await scheduler.run_reporting_points_auto_scheduler_once(datetime.fromisoformat(stamp)))
            for service in (m2, m3):
                self.refreshes[service].assert_not_awaited()
                self.sends[service].assert_not_awaited()

    async def test_busy_daily_lock_skips_delivery_until_next_tick(self):
        with ExitStack() as stack:
            self.setup_scheduler(stack)
            self.locks[m2].side_effect = [None, self.rows[m2], self.rows[m2]]
            now = datetime.fromisoformat("2026-10-05T12:15:00+02:00")
            self.assertFalse(await scheduler.run_reporting_points_auto_scheduler_once(now))
            self.assertTrue(await scheduler.run_reporting_points_auto_scheduler_once(now))
            self.assertFalse(await scheduler.run_reporting_points_auto_scheduler_once(now))
            self.sends[m2].assert_awaited_once()

    async def test_m2_failure_does_not_block_m3_and_is_retried_without_resending_m3(self):
        with ExitStack() as stack:
            self.setup_scheduler(stack)
            deliver = self.sends[m2].side_effect
            self.sends[m2].side_effect = RuntimeError("SMTP failure")
            now = datetime.fromisoformat("2026-10-05T16:20:00+02:00")
            self.assertTrue(await scheduler.run_reporting_points_auto_scheduler_once(now))
            self.assertIsNone(self.rows[m2].auto_sent_at)
            self.sends[m2].side_effect = deliver
            self.assertTrue(await scheduler.run_reporting_points_auto_scheduler_once(now))
            self.assertEqual(self.sends[m2].await_count, 2)
            self.sends[m3].assert_awaited_once()

    async def test_refresh_failure_is_recorded_and_remains_due(self):
        with ExitStack() as stack:
            self.setup_scheduler(stack)
            self.refreshes[m2].side_effect = RuntimeError("Data unavailable")
            self.assertFalse(await scheduler.run_reporting_points_auto_scheduler_once(datetime.fromisoformat("2026-10-05T12:15:00+02:00")))
            self.assertEqual(self.rows[m2].status, "FAILED")
            self.assertEqual(self.rows[m2].last_error, "Data unavailable")
            self.assertIsNone(self.rows[m2].auto_sent_at)
            self.sends[m2].assert_not_awaited()
            self.db.commit.assert_awaited_once()

    async def test_new_report_day_gets_its_own_delivery_after_same_day_catchup(self):
        with ExitStack() as stack:
            self.setup_scheduler(stack)
            late = datetime.fromisoformat("2026-10-05T23:30:00+02:00")
            self.assertTrue(await scheduler.run_reporting_points_auto_scheduler_once(late))
            for service, model in ((m2, M2ReportingPointsReport), (m3, M3ReportingPointsReport)):
                self.rows[service] = row_for(model)
                self.rows[service].report_date = date(2026, 10, 6)
                self.locks[service].return_value = self.rows[service]
            self.assertTrue(await scheduler.run_reporting_points_auto_scheduler_once(datetime.fromisoformat("2026-10-06T16:20:00+02:00")))
            for service in (m2, m3):
                self.assertEqual(self.sends[service].await_count, 2)

    async def test_saved_settings_change_time_recipients_days_and_enablement(self):
        with ExitStack() as stack:
            self.setup_scheduler(stack)
            settings = self.settings["M2"]
            settings.send_time = datetime.strptime("14:00", "%H:%M").time()
            settings.weekdays = [5]
            settings.recipients = {"to": ["changed@example.com"], "cc": ["copy@example.com"], "bcc": ["hidden@example.com"]}
            self.settings["M3"].is_active = False
            self.assertFalse(await scheduler.run_reporting_points_auto_scheduler_once(datetime.fromisoformat("2026-10-05T16:20:00+02:00")))
            self.assertFalse(await scheduler.run_reporting_points_auto_scheduler_once(datetime.fromisoformat("2026-10-03T13:59:00+02:00")))
            self.assertTrue(await scheduler.run_reporting_points_auto_scheduler_once(datetime.fromisoformat("2026-10-03T14:00:00+02:00")))
            self.assertEqual(self.sends[m2].await_args.args[2], settings.recipients)
            self.sends[m3].assert_not_awaited()

    async def test_busy_configuration_lock_skips_sending(self):
        with ExitStack() as stack:
            self.setup_scheduler(stack)
            self.get_settings.side_effect = None
            self.get_settings.return_value = None
            self.assertFalse(await scheduler.run_reporting_points_auto_scheduler_once(datetime.fromisoformat("2026-10-05T16:20:00+02:00")))
            for service in (m2, m3):
                self.locks[service].assert_not_awaited()


@pytest.mark.parametrize("service,model,export_path", [
    (m2, M2ReportingPointsReport, "app.services.m2_reporting_points.report_attachments"),
    (m3, M3ReportingPointsReport, "app.services.m3_reporting_points_attachments.report_attachments"),
])
def test_auto_marker_commits_with_success_and_manual_send_remains_independent(service, model, export_path):
    import asyncio

    async def scenario():
        row = row_for(model)
        previous_manual = row.sent_at
        db = AsyncMock()
        committed = []
        db.commit.side_effect = lambda: committed.append(row.auto_sent_at)
        gmail = SimpleNamespace(send_verified=AsyncMock(side_effect=[RuntimeError("SMTP failure"), {"id": "auto"}, {"id": "manual"}]))
        with patch.object(service, "GmailService", return_value=gmail), patch(export_path, return_value=[]):
            with pytest.raises(RuntimeError, match="SMTP failure"):
                await service.send_report(db, row, default_settings("M2").recipients, automatic=True)
            assert row.auto_sent_at is None and row.sent_at == previous_manual
            await service.send_report(db, row, default_settings("M2").recipients, automatic=True)
            automatic_time = row.auto_sent_at
            assert automatic_time == row.sent_at
            # Manual sends remain available, using their configured recipients.
            await service.send_report(db, row, {"to": ["manual@example.com"]})
        assert row.status == "SENT" and row.gmail_message_id == "manual"
        assert row.auto_sent_at == automatic_time
        assert committed == [None, automatic_time, automatic_time]
        assert gmail.send_verified.await_count == 3
        assert gmail.send_verified.await_args.args[1]["to"] == ["manual@example.com"]

    asyncio.run(scenario())


@pytest.mark.parametrize("service", [m2, m3])
def test_daily_lock_contention_does_not_read_or_create_a_report(service):
    import asyncio
    db = AsyncMock()
    result = MagicMock()
    result.scalar.return_value = False
    db.execute.return_value = result
    assert asyncio.run(service.locked_report(db, DAY, wait=False)) is None
    db.execute.assert_awaited_once()
    assert "pg_try_advisory_xact_lock" in str(db.execute.await_args.args[0])
    db.flush.assert_not_awaited()


def test_auto_send_migration_preserves_existing_reports_and_manual_answers():
    migration = migration_scripts().get_revision("0144_reporting_points_auto_send").module
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            tables = ("m2_reporting_points_reports", "m3_reporting_points_reports")
            for table in tables:
                connection.execute(sa.text(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, manual_answers TEXT, sent_at TIMESTAMP)"))
                connection.execute(sa.text(f"INSERT INTO {table} (id, manual_answers) VALUES ('existing', 'Saved answer')"))
            with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
                migration.upgrade()
                for table in tables:
                    assert connection.execute(sa.text(f"SELECT manual_answers, auto_sent_at FROM {table}")).one() == ("Saved answer", None)
                    connection.execute(sa.text(f"UPDATE {table} SET auto_sent_at = '2026-10-05 16:20:00'"))
                migration.downgrade()
                for table in tables:
                    assert connection.execute(sa.text(f"SELECT manual_answers FROM {table}")).scalar() == "Saved answer"
                    assert "auto_sent_at" not in {column["name"] for column in sa.inspect(connection).get_columns(table)}
    finally:
        engine.dispose()


@pytest.mark.parametrize("stamp, expected", [
    ("2026-10-05T08:29:59+02:00", False),
    ("2026-10-05T08:30:00+02:00", True),
    ("2026-10-05T06:30:00+00:00", True),
    ("2026-01-05T07:30:00+00:00", True),
    ("2026-10-03T08:30:00+02:00", False),
])
def test_m1_automatic_delivery_is_due_at_0830_local_and_independent_of_manual_send(stamp, expected):
    import asyncio
    from app.models.m1_reporting_points import M1ReportingPointsReport
    from app.services import m1_reporting_points as m1
    async def scenario():
        now = datetime.fromisoformat(stamp)
        row = row_for(M1ReportingPointsReport)
        row.report_date = now.date()
        db = AsyncMock()
        db.execute.return_value = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = []
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=db)
        context.__aexit__ = AsyncMock(return_value=False)
        deliveries = []
        async def send_verified(subject, recipients, plain, html, **kwargs):
            deliveries.append((subject, recipients, plain, html, kwargs))
            return {"id": "m1-automatic"}
        gmail = SimpleNamespace(send_verified=send_verified)
        async def refresh(db, current, capture):
            current.data = {"captured_until": capture.isoformat()}
            current.generated_at = capture
        with (
            patch.object(scheduler, "REPORT_SERVICES", (("M1", m1),)),
            patch.object(scheduler, "SessionLocal", return_value=context),
            patch.object(scheduler, "get_delivery_settings", new=AsyncMock(return_value=default_settings("M1"))),
            patch.object(m1, "locked_report", new=AsyncMock(return_value=row)),
            patch.object(m1, "refresh_report", side_effect=refresh),
            patch.object(m1, "GmailService", return_value=gmail),
        ):
            assert await scheduler.run_reporting_points_auto_scheduler_once(now) is expected
            if expected:
                assert row.auto_sent_at is not None and row.status == "SENT"
                assert row.manual_answers == {"reorganization": "Përgjigje e ruajtur"}
                assert deliveries[0][1] == {"to": ["ga@primexeu.com", "info@primexeu.com"], "cc": [], "bcc": []}
                assert "Përgjigje e ruajtur" in deliveries[0][2]
                assert {name.rsplit(".", 1)[-1] for name, _, _ in deliveries[0][4]["attachments"]} == {"html", "docx", "png", "xlsx"}
                assert not await scheduler.run_reporting_points_auto_scheduler_once(now)
                assert len(deliveries) == 1
                await m1.send_report(db, row, deliveries[0][1])
                assert len(deliveries) == 2 and row.auto_sent_at is not None
            else:
                assert not deliveries and row.auto_sent_at is None
    asyncio.run(scenario())
