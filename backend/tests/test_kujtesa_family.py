"""Synthetic Discord and isolated PostgreSQL schemas; no live bot or app DB."""
import os
import tempfile
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy import select, func
from app.models.ga_personal import GaPersonalDiscordNotice as Notice, GaPersonalEvent as Event
from app.models.ga_personal import GaPersonalOccurrence as Occurrence, GaPersonalTemplate as Template, GaPersonalSpace as Space
from app.schemas.ga_personal import TemplateDefinition
from app.services import kujtesa_family as family, kujtesa_family_pack as pack, ga_personal as tasks
from integrations.kujtesa.primeflow_bot import KujtesaBridge
from tests import test_ga_personal as fixtures
from tests import test_ga_personal_devices as device_fixtures


class RulesTests(unittest.TestCase):
    def test_notice_migration_contains_only_private_queue_and_no_task_mutations(self):
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from alembic.operations import Operations
        from alembic.migration import MigrationContext
        from io import StringIO
        config = Config(); config.set_main_option("script_location", "alembic")
        migration = ScriptDirectory.from_config(config).get_revision("0180_kujtesa_family").module
        output = StringIO()
        operations = Operations(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}))
        with patch.object(migration, "op", operations):
            migration.upgrade()
        self.assertIn("CREATE TABLE ga_personal.discord_notices", output.getvalue())
        self.assertNotIn("INSERT", output.getvalue())
        self.assertNotIn("UPDATE", output.getvalue())

    def test_pack_is_self_contained_valid_and_covers_all_new_routines(self):
        entries = pack.definitions()
        self.assertEqual(len(entries), len({e["source_id"] for e in entries}))
        by_id = {e["source_id"]: TemplateDefinition.model_validate(e["definition"]) for e in entries}
        self.assertGreater(len(entries), 50)
        self.assertEqual(by_id["nala_evening"].due_time.strftime("%H:%M"), "20:30")
        self.assertEqual(by_id["nala_care"].recurrence_interval_weeks, 6)
        self.assertEqual(by_id["rrita_school_return"].agenda_time.strftime("%H:%M"), "14:40")
        self.assertIsNone(by_id["rrita_school_return"].due_time)
        self.assertTrue(by_id["lirza_room"].weekday_steps["6"])

    def test_three_day_recurrence_across_month_boundary(self):
        definition = next(e["definition"] for e in pack.definitions() if e["source_id"] == "lirza_braces")
        for day, expected in [("2026-11-01", False), ("2026-11-02", True), ("2026-11-03", False), ("2026-12-02", True)]:
            self.assertEqual(tasks.scheduled(definition, date.fromisoformat(day)), expected)
        with self.assertRaises(ValueError):
            TemplateDefinition(title="x", assignees=["rrita"], recurrence_interval_days=3)

    def test_extra_event_daily_weekly_and_monthly_repeats_and_tombstones(self):
        event = {"date": "2026-11-02", "repeat": {"unit": "week", "every": 2, "days": [0, 2]}}
        self.assertTrue(family.on_day(event, date(2026, 11, 4)))
        self.assertFalse(family.on_day(event, date(2026, 11, 9)))
        self.assertTrue(family.on_day(event, date(2026, 11, 16)))
        self.assertFalse(family.on_day({**event, "deleted": True}, date(2026, 11, 16)))
        monthly = {"date": "2026-01-31", "repeat": {"unit": "month", "every": 1}}
        self.assertFalse(family.on_day(monthly, date(2026, 2, 28)))
        self.assertTrue(family.on_day(monthly, date(2026, 3, 31)))


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_replaces_legacy_guild_commands_after_bridge_health_check(self):
        import discord
        bot = KujtesaBridge("http://localhost/api", "test")
        bot.api = AsyncMock(return_value={"guild_id": "111111111111111111"})
        bot.tree.sync = AsyncMock()
        with patch.object(bot.worker, "start", Mock()) as start:
            await bot.setup_hook()
            start.assert_called_once()
        self.assertEqual(bot.tree.sync.await_count, 2)
        self.assertIn("sot", {c.name for c in bot.tree.get_commands(guild=discord.Object(id=111111111111111111))})
        await bot.close()

    async def test_ai_conversation_cannot_start_during_chime_connection(self):
        from integrations.kujtesa.voice_host import KujtesaHost, HostError
        bot = KujtesaBridge("http://localhost/api", "test")
        bot.family_chime_starting = True
        with self.assertRaises(HostError):
            await KujtesaHost(bot).start(NS())
        await bot.close()

    async def test_disabled_worker_cannot_send_notices(self):
        bot = KujtesaBridge("http://localhost/api", "test")
        bot.api = AsyncMock(return_value={"enabled": True, "notices": [{"id": "x"}]})
        bot.deliver = AsyncMock()
        await bot.tick()
        bot.deliver.assert_not_awaited()
        self.assertIsNotNone(bot.tree.get_command("sot"))
        self.assertIsNotNone(bot.tree.get_command("zgjova"))
        await bot.close()

    async def test_notice_delivery_uses_same_private_destination_and_durable_receipts(self):
        with tempfile.TemporaryDirectory() as root:
            bot = KujtesaBridge("http://localhost/api", "test", reminders_enabled=True, receipt_path=Path(root)/"receipts.json")
            identity = str(uuid.uuid4())
            card = {"id": identity, "lease": "a"*48, "kind": "notice", "text": "Agjenda",
                    "guild_id": "111111111111111111", "target": {"kind": "dm", "user_id": "333333333333333333"}}
            bot.api = AsyncMock(side_effect=[card, {"recorded": True}])
            channel = NS(id=555555555555555555, send=AsyncMock(return_value=NS(id=666666666666666666)))
            bot.destination = AsyncMock(return_value=channel)
            await bot.deliver(card)
            self.assertEqual(bot.api.call_args_list[0].args[0], f"/notices/{identity}/prepare")
            self.assertEqual(bot.api.call_args_list[1].args[0], f"/notices/{identity}/result")
            self.assertIsNone(channel.send.call_args.kwargs["view"])
            self.assertEqual(bot.receipts.pending(), {})
            await bot.close()


@unittest.skipUnless(os.getenv("GA_PERSONAL_TEST_DATABASE_URL"), "Disposable PostgreSQL required")
class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.GaPersonalDatabaseTests.asyncSetUp
    asyncTearDown = fixtures.GaPersonalDatabaseTests.asyncTearDown
    as_person = fixtures.GaPersonalDatabaseTests.as_person
    add_template = fixtures.GaPersonalDatabaseTests.add_template
    generate = fixtures.GaPersonalDatabaseTests.generate
    bridge_setup = fixtures.GaPersonalDatabaseTests.bridge_setup
    bridge_poll = fixtures.GaPersonalDatabaseTests.bridge_poll

    async def command(self, command, *, actor="333333333333333333", interaction="777777777777777777", delivery=True):
        with patch("app.services.ga_personal_discord.utcnow", return_value=datetime(2026, 11, 7, 7, tzinfo=timezone.utc)):
            return await self.client.post("/api/ga-personal/bridge/command", headers={"X-GA-Bridge-Key": "test-only-bridge-secret-which-is-long-enough"},
                json={"command": command, "actor_id": actor, "guild_id": None, "channel_id": "555555555555555555",
                      "interaction_id": interaction, "delivery_enabled": delivery})

    async def enable_notices(self):
        settings = (await self.client.get("/api/ga-personal/discord/settings")).json()
        response = await self.client.put("/api/ga-personal/discord/settings", json={
            key: settings[key] for key in ("enabled", "guild_id", "channel_id", "user_ids")
        } | {"daily_agenda": True, "presence_notifications": True, "expected_version": settings["version"]})
        self.assertEqual(response.status_code, 200, response.text)

    async def test_pack_preview_apply_repeat_preserves_manual_edits_and_rotation(self):
        await self.add_template()
        async with self.sessions() as db:
            row = (await db.execute(select(Template))).scalar_one()
            row.source_id = "nala_evening"
            row.definition = {**row.definition, "title": "Ora ime", "due_time": "21:15:00"}
            await db.commit()
        endpoint = "/api/ga-personal/discord/family-pack"
        preview = await self.client.get(endpoint)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(next(t for t in preview.json()["tasks"] if t["source_id"] == "nala_evening")["action"], "existing")
        async with self.sessions() as db:
            space = await db.get(Space, self.space_id)
            space.config = {**space.config, "discord": {"last_seen_at": tasks.utcnow().isoformat()},
                            "automatic_generation": {"last_checked_at": tasks.utcnow().isoformat(), "future_generated_through": "2026-11-15"}}
            await db.commit()
        result = await self.client.post(endpoint, json={"expected_hash": preview.json()["hash"]})
        self.assertEqual(result.status_code, 200, result.text)
        repeat = (await self.client.get(endpoint)).json()
        self.assertEqual(repeat["counts"]["create"], 0)
        self.assertEqual(repeat["counts"]["update"], 0)
        async with self.sessions() as db:
            self.assertEqual((await db.get(Space, self.space_id)).config["rotation_anchor"], "2026-10-30")
            row = (await db.execute(select(Template).where(Template.source_id == "nala_evening"))).scalar_one()
            self.assertEqual(row.definition["due_time"], "21:15:00")
        self.assertEqual((await self.client.post(endpoint, json={"expected_hash": preview.json()["hash"]})).status_code, 409)
        self.as_person("mrika")
        self.assertEqual((await self.client.get(endpoint)).status_code, 403)

    async def test_commands_are_scoped_and_presence_retry_is_idempotent(self):
        await self.bridge_setup()
        self.assertEqual((await self.command("sot", actor="999999999999999999")).status_code, 403)
        result = await self.command("sot")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIn("Puna e provës", result.json()["text"])
        for _ in range(2):
            self.assertEqual((await self.command("zgjova")).status_code, 200)
        async with self.sessions() as db:
            self.assertEqual((await db.execute(select(func.count(Event.id)).where(Event.kind == "woke"))).scalar_one(), 1)
        self.assertEqual((await self.command("kujto")).status_code, 403)
        self.assertEqual((await self.command("kujto", actor="444444444444444444", delivery=False)).status_code, 409)

    async def test_pack_refreshes_pre_generated_pending_duties_but_keeps_history_and_overrides(self):
        await self.bridge_setup()
        await self.generate("2026-11-08")
        await self.generate("2026-11-09")
        async with self.sessions() as db:
            template = (await db.execute(select(Template))).scalar_one()
            template.source_id = "rrita_room"
            template.import_hash = tasks.document_hash(template.definition)
            rows = {r.local_date: r for r in (await db.execute(select(Occurrence))).scalars()}
            rows["2026-11-08"].status = "done"
            rows["2026-11-08"].completed_at = tasks.utcnow()
            rows["2026-11-09"].snapshot = {**rows["2026-11-09"].snapshot, "schedule_overridden": True}
            await db.commit()
            identities = {day: row.id for day, row in rows.items()}
        with patch("app.services.ga_personal.utcnow", return_value=datetime(2026, 11, 7, 7, tzinfo=timezone.utc)):
            preview = (await self.client.get("/api/ga-personal/discord/family-pack")).json()
            self.assertEqual(preview["counts"]["update"], 1)
            response = await self.client.post("/api/ga-personal/discord/family-pack", json={"expected_hash": preview["hash"]})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["refreshed_pending_occurrences"], 1)
        async with self.sessions() as db:
            pending = await db.get(Occurrence, identities["2026-11-07"])
            self.assertEqual(tasks.aware(pending.due_at).astimezone(tasks.TZ).strftime("%H:%M"), "20:20")
            self.assertEqual(pending.snapshot["routine_key"], "rooms")
            for day in ("2026-11-08", "2026-11-09"):
                row = await db.get(Occurrence, identities[day])
                self.assertEqual(tasks.aware(row.due_at).astimezone(tasks.TZ).strftime("%H:%M"), "17:00")
            self.assertEqual((await db.get(Occurrence, identities["2026-11-08"])).status, "done")

    async def test_notice_deduplication_revalidation_and_uncertain_send(self):
        await self.bridge_setup()
        await self.enable_notices()
        day = date(2026, 11, 7)
        with patch("app.services.ga_personal_discord.utcnow", return_value=datetime(2026, 11, 7, 7, tzinfo=timezone.utc)):
            first = (await self.bridge_poll("2026-11-07T07:00:00+00:00")).json()
            self.assertEqual(len(first["notices"]), 1)
            notice = first["notices"][0]
            self.assertEqual(notice["kind"], "notice")
            self.assertEqual(notice["target"]["kind"], "dm")
            headers = {"X-GA-Bridge-Key": "test-only-bridge-secret-which-is-long-enough"}
            root = f'/api/ga-personal/bridge/notices/{notice["id"]}'
            prepared = await self.client.post(root + "/prepare", headers=headers, json={"lease": notice["lease"]})
            self.assertEqual(prepared.status_code, 200, prepared.text)
            again = (await self.bridge_poll("2026-11-07T07:00:10+00:00")).json()
            self.assertEqual(again["notices"], [])
        self.assertEqual((await self.bridge_poll("2026-11-07T07:02:00+00:00")).json()["notices"], [])
        async with self.sessions() as db:
            self.assertEqual((await db.get(Notice, uuid.UUID(notice["id"]))).status, "uncertain")

    async def test_disabled_delivery_claims_neither_agendas_nor_task_cards(self):
        await self.bridge_setup()
        await self.enable_notices()
        response = await self.client.post("/api/ga-personal/bridge/poll", headers={"X-GA-Bridge-Key": "test-only-bridge-secret-which-is-long-enough"},
            json={"delivery_enabled": False})
        self.assertEqual(response.status_code, 200, response.text)
        async with self.sessions() as db:
            self.assertEqual((await db.execute(select(func.count(Notice.id)))).scalar_one(), 0)

    async def test_agenda_preferences_do_not_regenerate_already_claimed_task_phase(self):
        await self.bridge_setup()
        first = (await self.bridge_poll("2026-11-07T15:55:00+00:00")).json()["deliveries"][0]
        await self.enable_notices()
        result = (await self.bridge_poll("2026-11-07T15:55:10+00:00")).json()
        self.assertEqual(result["deliveries"], [])
        with patch("app.services.ga_personal_discord.utcnow", return_value=datetime(2026, 11, 7, 15, 55, 10, tzinfo=timezone.utc)):
            prepared = await self.client.post(f'/api/ga-personal/bridge/deliveries/{first["id"]}/prepare',
                headers={"X-GA-Bridge-Key": "test-only-bridge-secret-which-is-long-enough"}, json={"lease": first["lease"]})
            self.assertEqual(prepared.status_code, 200, prepared.text)

    async def test_kaki_changes_only_eligible_evening_and_reverts_without_duplicates(self):
        await self.bridge_setup()
        async with self.sessions() as db:
            member = (await db.execute(select(fixtures.Member).where(fixtures.Member.person_key == "gane"))).scalar_one()
            for source, time in [("nala_afternoon", "16:30"), ("nala_evening", "20:30")]:
                d = fixtures.definition(); d.update(assignees=["rrita"], due_time=time, reminder_group="nala")
                db.add(Template(space_id=self.space_id, source_id=source, created_by=member.user_id, definition=d))
            await db.commit()
            await tasks.generate(db, member, fixtures.api.GenerateRequest(day=date(2026, 11, 7)))
            space = await db.get(Space, self.space_id)
            with patch("app.services.ga_personal_discord.utcnow", return_value=datetime(2026, 11, 7, 15, tzinfo=timezone.utc)):
                await family.apply_kaki(db, space, "2026-11-07", "jo", actor_id=member.user_id, request_id="test-1")
                await db.commit()
                evening = (await db.execute(select(Occurrence).join(Template).where(Template.source_id == "nala_evening"))).scalar_one()
                self.assertEqual(tasks.aware(evening.due_at).astimezone(tasks.TZ).strftime("%H:%M"), "19:30")
                await family.apply_kaki(db, space, "2026-11-07", "po", actor_id=member.user_id, request_id="test-2")
                self.assertEqual(tasks.aware(evening.due_at).astimezone(tasks.TZ).strftime("%H:%M"), "20:30")
                evening.snapshot = {**evening.snapshot, "schedule_overridden": True}
                await family.apply_kaki(db, space, "2026-11-07", "jo", actor_id=member.user_id, request_id="test-3")
                self.assertEqual(tasks.aware(evening.due_at).astimezone(tasks.TZ).strftime("%H:%M"), "20:30")

    async def test_routine_completion_updates_every_task_once(self):
        await self.bridge_setup()
        for title in ("Shtrati", "Çelësat"):
            d = fixtures.definition(); d.update(title=title, assignees=["rrita"], reminder_group="morning", routine_key="morning")
            await self.add_template(d)
        await self.generate()
        response = await self.bridge_poll("2026-11-07T15:55:00+00:00")
        self.assertEqual(response.status_code, 200, response.text)
        values = response.json()["deliveries"]
        headers = {"X-GA-Bridge-Key": "test-only-bridge-secret-which-is-long-enough"}
        card = None
        for value in values:
            with patch("app.services.ga_personal_discord.utcnow", return_value=datetime(2026, 11, 7, 15, 55, tzinfo=timezone.utc)):
                prepared = await self.client.post(f'/api/ga-personal/bridge/deliveries/{value["id"]}/prepare', headers=headers, json={"lease": value["lease"]})
            self.assertEqual(prepared.status_code, 200, prepared.text)
            if prepared.json().get("parts"):
                card = prepared.json()
        self.assertIsNotNone(card)
        self.assertEqual(len(card["parts"]), 2)
        root = f'/api/ga-personal/bridge/deliveries/{card["id"]}'
        report = {"lease": card["lease"], "outcome": "sent", "channel_id": "555555555555555555", "message_id": "666666666666666666"}
        self.assertEqual((await self.client.post(root + "/result", headers=headers, json=report)).status_code, 200)
        action = {"actor_id": "333333333333333333", "guild_id": None, "channel_id": report["channel_id"],
                  "message_id": report["message_id"], "interaction_id": "777777777777777777", "action": "done"}
        for _ in range(2):
            result = await self.client.post(root + "/action", headers=headers, json=action)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["card"]["status"], "done")
        async with self.sessions() as db:
            rows = (await db.execute(select(Occurrence).where(Occurrence.snapshot["routine_key"].as_string() == "morning"))).scalars().all()
            self.assertEqual([r.status for r in rows], ["done", "done"])
            self.assertEqual((await db.execute(select(func.count(Event.id)).where(Event.kind == "status_changed"))).scalar_one(), 2)

    async def test_manual_nala_request_is_idempotent_and_uses_existing_delivery_pipeline(self):
        await self.bridge_setup()
        async with self.sessions() as db:
            row = (await db.execute(select(Occurrence))).scalar_one()
            row.snapshot = {**row.snapshot, "reminder_group": "nala"}
            await db.commit()
        for _ in range(2):
            response = await self.command("kujto", actor="444444444444444444")
            self.assertEqual(response.status_code, 200, response.text)
        result = await self.bridge_poll("2026-11-07T07:00:01+00:00")
        self.assertEqual(result.status_code, 200, result.text)
        cards = result.json()["deliveries"]
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["phase"], "manual")
        self.assertEqual((await self.bridge_poll("2026-11-07T07:00:02+00:00")).json()["deliveries"], [])

    async def test_changed_child_schedule_prevents_sending_stale_routine(self):
        await self.bridge_setup()
        for title in ("Shtrati", "Çelësat"):
            d = fixtures.definition(); d.update(title=title, assignees=["rrita"], reminder_group="morning", routine_key="morning")
            await self.add_template(d)
        await self.generate()
        values = (await self.bridge_poll("2026-11-07T15:55:00+00:00")).json()["deliveries"]
        from app.models.ga_personal import GaPersonalDiscordDelivery as Outbox
        async with self.sessions() as db:
            child = (await db.execute(select(Outbox).where(Outbox.status == "bundled"))).scalar_one()
            leader_id = child.details["bundle_leader"]
            occurrence = await db.get(Occurrence, child.occurrence_id)
            occurrence.due_at += timedelta(hours=1)
            await db.commit()
        leader = next(v for v in values if v["id"] == leader_id)
        with patch("app.services.ga_personal_discord.utcnow", return_value=datetime(2026, 11, 7, 15, 55, tzinfo=timezone.utc)):
            response = await self.client.post(f'/api/ga-personal/bridge/deliveries/{leader_id}/prepare',
                headers={"X-GA-Bridge-Key": "test-only-bridge-secret-which-is-long-enough"}, json={"lease": leader["lease"]})
            self.assertEqual(response.status_code, 409, response.text)

    async def test_notice_prepare_rejects_changed_privacy_and_revoked_grant(self):
        await self.bridge_setup()
        await self.enable_notices()
        values = (await self.bridge_poll("2026-11-07T07:00:00+00:00")).json()["notices"]
        notice = values[0]
        async with self.sessions() as db:
            space = await db.get(Space, self.space_id)
            space.password_version += 1
            await db.commit()
        with patch("app.services.ga_personal_discord.utcnow", return_value=datetime(2026, 11, 7, 7, tzinfo=timezone.utc)):
            response = await self.client.post(f'/api/ga-personal/bridge/notices/{notice["id"]}/prepare',
                headers={"X-GA-Bridge-Key": "test-only-bridge-secret-which-is-long-enough"}, json={"lease": notice["lease"]})
            self.assertEqual(response.status_code, 409, response.text)


@unittest.skipUnless(os.getenv("GA_PERSONAL_TEST_DATABASE_URL"), "Disposable PostgreSQL required")
class DeviceExtensionsTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = device_fixtures.DeviceDatabaseTests.asyncSetUp
    asyncTearDown = device_fixtures.DeviceDatabaseTests.asyncTearDown
    as_person = fixtures.GaPersonalDatabaseTests.as_person
    create = device_fixtures.DeviceDatabaseTests.create
    headers = device_fixtures.DeviceDatabaseTests.headers

    async def test_wake_arrival_and_historical_kaki_roundtrip_and_retry(self):
        created = await self.create()
        headers = self.headers(created["code"])
        # Bind the device before using its operations endpoint.
        await self.client.get("/api/ga-personal/device/state", headers=headers)
        moment = datetime(2026, 11, 7, 7, tzinfo=timezone.utc)
        stamp = int(moment.timestamp() * 1000)
        operations = [
            {"type": "wake", "op_id": str(uuid.uuid4()), "at": stamp, "person_id": "rrita", "day": "2026-11-07"},
            {"type": "arrival", "op_id": str(uuid.uuid4()), "at": stamp + 1, "person_id": "rrita", "day": "2026-11-07"},
            {"type": "kaki", "op_id": str(uuid.uuid4()), "at": stamp, "answer": "jo", "date": "2026-11-06"},
        ]
        with patch("app.services.ga_personal_discord.utcnow", return_value=moment):
            for _ in range(2):
                result = await self.client.post("/api/ga-personal/device/ops", headers=headers,
                    json={"device_id": device_fixtures.TABLET, "ops": operations})
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(result.json()["accepted"], [o["op_id"] for o in operations])
        state = (await self.client.get("/api/ga-personal/device/state", headers=headers)).json()
        self.assertEqual(state["wakes"], [{"person_id": "rrita", "day": "2026-11-07", "at": stamp}])
        self.assertEqual(state["arrivals"], [{"person_id": "rrita", "day": "2026-11-07", "at": stamp + 1}])
        self.assertEqual(state["kaki"][0]["answer"], "jo")
        older = {**operations[2], "op_id": str(uuid.uuid4()), "at": stamp - 1, "answer": "po"}
        result = await self.client.post("/api/ga-personal/device/ops", headers=headers,
            json={"device_id": device_fixtures.TABLET, "ops": [older]})
        self.assertEqual(result.status_code, 200, result.text)
        state = (await self.client.get("/api/ga-personal/device/state", headers=headers)).json()
        self.assertEqual(state["kaki"][0]["answer"], "jo")


if __name__ == "__main__":
    unittest.main()
