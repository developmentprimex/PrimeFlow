"""GA assistant agenda and actions against a real PostgreSQL schema.

Opt-in: set PRIMEFLOW_DB_TESTS=1 and point DATABASE_URL at a throwaway database
whose name ends with "_test" (schema at Alembic head). The test refuses any other
database, creates its own rows and deletes them afterwards.
"""
import os
import unittest
import uuid
from datetime import date, datetime, time, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

os.environ.setdefault("JWT_SECRET", "test-only-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")

from sqlalchemy.engine import make_url  # noqa: E402

from app.config import settings  # noqa: E402

DB_TESTS = os.getenv("PRIMEFLOW_DB_TESTS") == "1" and (make_url(settings.DATABASE_URL).database or "").endswith("_test")
TZ = ZoneInfo(settings.GA_TIMEZONE)

if DB_TESTS:
    # Every IsolatedAsyncioTestCase test has its own event loop; pooled asyncpg
    # connections cannot cross loops, so the test process uses an unpooled engine.
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import app.db as app_db

    app_db.engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    app_db.SessionLocal = async_sessionmaker(app_db.engine, expire_on_commit=False, class_=AsyncSession)


@unittest.skipUnless(DB_TESTS, "needs PRIMEFLOW_DB_TESTS=1 and a *_test database")
class GaAssistantDbTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        import httpx
        from app.auth.security import create_access_token
        from app.db import SessionLocal
        from app.main import app
        from app.models.audit_log import AuditLog
        from app.models.department import Department
        from app.models.enums import UserRole
        from app.models.meeting import Meeting
        from app.models.system_task_template import SystemTaskTemplate
        from app.models.system_task_template_alignment_user import SystemTaskTemplateAlignmentUser
        from app.models.task import Task
        from app.models.task_alignment_user import TaskAlignmentUser
        from app.models.task_assignee import TaskAssignee
        from app.models.user import User

        self.Task, self.AuditLog, self.SessionLocal = Task, AuditLog, SessionLocal
        self.today = datetime.now(TZ).date()
        today = self.today

        def at(day: date, hour: int = 0, minute: int = 0) -> datetime:
            return datetime.combine(day, time(hour, minute), tzinfo=TZ)

        self.at = at
        suffix = uuid.uuid4().hex[:6]
        async with SessionLocal() as db:
            # A *_test database only (guarded by DB_TESTS): start every test from empty tables.
            from sqlalchemy import text

            names = (await db.execute(text(
                "select string_agg(format('%I.%I', schemaname, tablename), ', ') from pg_tables "
                "where schemaname not in ('pg_catalog', 'information_schema') and tablename <> 'alembic_version'"
            ))).scalar_one()
            await db.execute(text(f"TRUNCATE {names} CASCADE"))
            dept = Department(name=f"GA test {suffix}", code=f"T{suffix[:5]}")
            db.add(dept)
            await db.flush()
            self.ga = User(email=settings.GA_USER_EMAIL, username=settings.GA_USERNAME, full_name="GA Test",
                           password_hash="x", role=UserRole.ADMIN, department_id=dept.id)
            self.colleague = User(email=f"coll{suffix}@example.com", username=f"coll{suffix}", full_name="Colleague Test",
                                  password_hash="x", role=UserRole.STAFF, department_id=dept.id)
            db.add_all([self.ga, self.colleague])
            await db.flush()
            tpl = SystemTaskTemplate(title="BZ template", frequency="DAILY", alignment_time=time(11, 50), requires_alignment=True)
            db.add(tpl)
            await db.flush()
            db.add(SystemTaskTemplateAlignmentUser(template_id=tpl.id, user_id=self.ga.id))

            def task(title, **kw):
                kw.setdefault("start_date", kw.get("due_date"))
                row = Task(title=title, department_id=dept.id, status=kw.pop("status", "TODO"), **kw)
                db.add(row)
                return row

            self.t_untimed = task("GA untimed", assigned_to=self.ga.id, due_date=at(today))
            self.t_1h = task("GA 1H", assigned_to=self.ga.id, due_date=at(today), is_1h_report=True, one_h_report_slot="10:00")
            self.t_bz = task("Colleague with GA BZ", assigned_to=self.colleague.id, due_date=at(today))
            self.t_tpl = task("Template BZ", assigned_to=self.colleague.id, due_date=at(today, 9),
                              system_template_origin_id=tpl.id)
            self.t_f = task("Colleague F", assigned_to=self.colleague.id, due_date=at(today), one_h_marker="M2,F")
            self.t_late = task("GA late", assigned_to=self.ga.id, due_date=at(today - timedelta(days=3)))
            self.t_done = task("GA done", assigned_to=self.ga.id, due_date=at(today - timedelta(days=1)),
                               status="DONE", completed_at=at(today - timedelta(days=1), 12))
            self.t_other = task("Unrelated", assigned_to=self.colleague.id, due_date=at(today))
            await db.flush()
            for row in (self.t_untimed, self.t_1h, self.t_late, self.t_done):
                db.add(TaskAssignee(task_id=row.id, user_id=self.ga.id))
            for row in (self.t_bz, self.t_tpl, self.t_f, self.t_other):
                db.add(TaskAssignee(task_id=row.id, user_id=self.colleague.id))
            db.add(TaskAlignmentUser(task_id=self.t_bz.id, user_id=self.ga.id))
            self.meeting = Meeting(title="Klient X", department_id=dept.id, meeting_type="external",
                                   starts_at=at(today, 14, 20), ends_at=at(today, 15, 0))
            db.add(self.meeting)
            await db.commit()
            self.ids = {"dept": dept.id, "tpl": tpl.id}
        self.ga_token = create_access_token(user_id=self.ga.id, role="ADMIN", department_id=self.ga.department_id)
        self.staff_token = create_access_token(user_id=self.colleague.id, role="STAFF", department_id=self.colleague.department_id)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.ms = patch("app.services.ga_assistant.collect_microsoft_items", AsyncMock(return_value=([], [])))
        self.ms.start()

    async def asyncTearDown(self) -> None:
        self.ms.stop()
        await self.client.aclose()

    def h(self, token=None):
        return {"Authorization": f"Bearer {token or self.ga_token}"}

    async def get(self, path, **params):
        res = await self.client.get(f"/api/ga-assistant{path}", params=params, headers=self.h())
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    async def post(self, path, body, token=None, expect=200):
        res = await self.client.post(f"/api/ga-assistant{path}", json=body, headers=self.h(token))
        self.assertEqual(res.status_code, expect, res.text)
        return res.json()

    async def test_discord_artifact_feed_filters_the_channel_and_shows_reaction_changes(self) -> None:
        from app.models.ga_discord_mention import GaDiscordMention
        from app.services.ga_discord_mentions import bridge_secret

        path = "/discord/mentions/feed"
        created_at = self.at(self.today)

        def message(id, *, channel="20", guild="10", reasons=("mention",)):
            return {
                "id": id, "guild_id": guild, "channel_id": channel, "channel_name": "det-nga-stafi-per-ga",
                "author_discord_id": "77", "author_name": "Dërguesi", "created_at": created_at.isoformat(),
                "content": "<@42> Kontrolloje detyrën", "jump_url": f"https://discord.com/channels/{guild}/{channel}/{id}",
                "attachments": [{"name": "plan.pdf", "url": "https://cdn.discordapp.com/attachments/20/300/plan.pdf?ex=old"}]
                if id == "1002" else [],
                "reasons": list(reasons),
            }

        with patch.multiple(settings, DISCORD_GUILD_ID="10", DISCORD_GA_REPLIES_CHANNEL_ID="20",
                            GA_DISCORD_USER_ID="42", GA_DISCORD_MENTIONS_BOT_TOKEN="test-token"):
            bot_headers = {"X-GA-Mentions-Secret": bridge_secret()}
            bridge = "/api/ga-discord-bot"
            response = await self.client.post(f"{bridge}/mentions", headers=bot_headers, json={"messages": [
                message("1001"), message("1002", reasons=("mention", "reply")), message("1003", channel="21"),
                message("1004", reasons=("role",)), message("1005", reasons=("reply",)),
            ]})
            self.assertEqual(response.json(), {"stored": 5, "skipped": 0})
            async with self.SessionLocal() as db:
                db.add(GaDiscordMention(**{**message("1006", guild="11"), "created_at": created_at}))
                await db.commit()

            api_path = f"/api/ga-assistant{path}"
            self.assertIn((await self.client.get(api_path)).status_code, {401, 403})
            self.assertEqual((await self.client.get(api_path, headers=self.h(self.staff_token))).status_code, 403)
            for params in ({"before": "1003"}, {"before": "1004"}, {"before": "1006"}, {"limit": "51"}):
                self.assertEqual((await self.client.get(api_path, headers=self.h(), params=params)).status_code, 422)

            page = await self.get(path, limit=1)
            self.assertEqual((page["channel_id"], page["next_before"]), ("20", "1002"))
            self.assertEqual([item["id"] for item in page["items"]], ["dc:1002"])
            self.assertIsNone(page["items"][0]["reactions_synced_at"])
            self.assertEqual(page["items"][0]["attachments"], [{"name": "plan.pdf"}])
            older = await self.get(path, limit=1, before=page["next_before"])
            self.assertEqual([item["id"] for item in older["items"]], ["dc:1001"])
            self.assertEqual(older["items"][0]["attachments"], [])
            self.assertIsNone(older["next_before"])

            import httpx

            attachment_path = "/discord/mentions/feed/1002/attachments"
            source_url = "https://discord.com/api/v10/channels/20/messages/1002"
            fresh_url = "https://cdn.discordapp.com/attachments/20/300/plan.pdf?ex=fresh"
            discord_source = {
                "id": "1002", "channel_id": "20", "author": {"id": "77"}, "mentions": [{"id": "42"}],
                "attachments": [
                    {"id": "300", "filename": "plan.pdf", "content_type": "application/pdf", "url": fresh_url},
                    {"id": "301", "filename": "outside.png", "url": "https://cdn.discordapp.com/attachments/21/301/outside.png"},
                    {"id": "302", "filename": "unsafe.png", "url": "https://invalid.example/attachments/20/302/unsafe.png"},
                ],
            }
            request = httpx.Request("GET", source_url)
            discord_get = AsyncMock(return_value=httpx.Response(200, request=request, json=discord_source))
            async def fake_discord_get(_client, url, **kwargs):
                if url == source_url:
                    return await discord_get(url, **kwargs)
                return await original_get(_client, url, **kwargs)

            original_get = httpx.AsyncClient.get
            with patch.object(httpx.AsyncClient, "get", fake_discord_get):
                actual = await self.get(attachment_path)
                self.assertEqual(actual, {"id": "dc:1002", "attachments": [
                    {"name": "plan.pdf", "url": fresh_url, "content_type": "application/pdf"},
                ]})
                discord_get.assert_awaited_once_with(source_url, headers={"Authorization": "Bot test-token"})
                for id in ("1003", "1004", "1005", "1006"):
                    response = await self.client.get(f"{api_path}/{id}/attachments", headers=self.h())
                    self.assertEqual(response.status_code, 404)
                response = await self.client.get(f"/api/ga-assistant{attachment_path}", headers=self.h(self.staff_token))
                self.assertEqual(response.status_code, 403)
                self.assertEqual(discord_get.await_count, 1)
                discord_source["mentions"] = []
                discord_get.return_value = httpx.Response(200, request=request, json=discord_source)
                response = await self.client.get(f"/api/ga-assistant{attachment_path}", headers=self.h())
                self.assertEqual(response.status_code, 404)

            reaction = {"emoji": "👍", "count": 1, "users": [{"discord_id": "66", "name": "Arta Berisha"}]}
            for reactions in ([reaction], []):
                response = await self.client.post(f"{bridge}/reactions", headers=bot_headers, json={
                    "message_id": "1002", "reactions": reactions,
                })
                self.assertEqual(response.json(), {"updated": True})
                item = (await self.get(path))["items"][0]
                expected = [{"emoji": "👍", "count": 1, "users": [{"name": "Arta Berisha", "initials": "AB"}]}] if reactions else []
                self.assertEqual(item["reactions"], expected)
                self.assertIsNotNone(item["reactions_synced_at"])
                self.assertEqual(item["url"], "https://discord.com/channels/10/20/1002")

            await self.post("/discord/mentions/dc:1002/status", {"status": "done"})
            self.assertEqual((await self.get(path))["items"][0]["status"], "done")

    async def test_staff_discord_archive_joins_context_and_limits_attachment_access(self) -> None:
        import httpx

        from app.services.ga_discord_mentions import bridge_secret

        at = self.at(self.today) - timedelta(minutes=10)
        bridge = "/api/ga-discord-bot"

        def message(mid, seconds, *, author="77", channel="20", parent=None, reply=None):
            return {
                "id": mid, "guild_id": "10", "channel_id": channel, "channel_name": "staff",
                "parent_channel_id": parent, "author_discord_id": author, "author_name": "Stafi",
                "created_at": (at + timedelta(seconds=seconds)).isoformat(), "content": f"Mesazhi {mid}",
                "reply_to_message_id": reply, "jump_url": f"https://discord.com/channels/10/{channel}/{mid}",
                "attachments": [{"name": "plan.pdf", "url": "https://cdn.discordapp.com/attachments/20/30/plan.pdf"}],
            }

        with patch.multiple(settings, DISCORD_GUILD_ID="10", DISCORD_GA_REPLIES_CHANNEL_ID="20",
                            GA_DISCORD_USER_ID="42", GA_DISCORD_MENTIONS_BOT_TOKEN="test-token"):
            headers = {"X-GA-Mentions-Secret": bridge_secret()}
            mention = message("200", 0, reply="100")
            records = [
                message("100", -480, author="80"),
                message("190", -121), message("191", -120), message("192", -30, author="80"),
                mention, message("201", 120), message("202", 121),
                message("203", 180, author="42", reply="200"),
                message("204", 181, author="80", channel="200", parent="20"),
                message("205", 182, author="80", channel="999", parent="20"),
                message("206", 10, channel="21"),
            ]
            posted = await self.client.post(f"{bridge}/channel-messages", headers=headers, json={"messages": records})
            self.assertEqual(posted.json(), {"stored": 10, "skipped": 1})
            edited = {**records[2], "content": "Mesazhi 191", "edited_at": (at + timedelta(seconds=5)).isoformat()}
            stale = {**records[2], "content": "Kopja e vjetër"}
            for batch in ([edited, records[5]], [stale]):
                posted = await self.client.post(f"{bridge}/channel-messages", headers=headers, json={
                    "messages": batch, "checkpoint_channel_id": "20",
                })
                self.assertEqual(posted.status_code, 200, posted.text)
            bot_context = await self.client.get(f"{bridge}/context", headers=headers)
            self.assertEqual(bot_context.json()["archive_checkpoints"], {"20": "201"})
            posted = await self.client.post(f"{bridge}/mentions", headers=headers, json={
                "messages": [{**mention, "reasons": ["mention"]}],
            })
            self.assertEqual(posted.json()["stored"], 1)

            paths = ("/discord/mentions/feed", "/discord/mentions")
            for path in paths:
                result = await self.get(path, **({"since": (at - timedelta(minutes=1)).isoformat()} if path == paths[1] else {}))
                self.assertEqual([item["id"] for item in result["items"]], ["dc:200"])
                context = result["items"][0]["context"]
                self.assertEqual([item["id"] for item in context["para"]], ["dc:191"])
                self.assertEqual([item["id"] for item in context["pas"]], ["dc:201"])
                self.assertEqual(context["reply"]["id"], "dc:100")
                self.assertEqual([item["id"] for item in context["përgjigjet"]], ["dc:203", "dc:204"])
                previous = context["para"][0]
                self.assertEqual(previous["attachments"], [{"name": "plan.pdf"}])
                self.assertEqual(previous["text"], "Mesazhi 191")

            reaction = {"emoji": "✅", "count": 1, "users": [{"discord_id": "66", "name": "Arta Berisha"}]}
            response = await self.client.post(f"{bridge}/reactions", headers=headers, json={
                "message_id": "191", "reactions": [reaction],
            })
            self.assertEqual(response.json(), {"updated": True})
            await self.client.post(f"{bridge}/channel-messages", headers=headers, json={"messages": [
                {**stale, "reactions": [], "reactions_synced_at": at.isoformat()},
            ]})
            item = (await self.get(paths[0]))["items"][0]["context"]["para"][0]
            self.assertEqual(item["reactions"][0]["users"][0]["name"], "Arta Berisha")

            from sqlalchemy import select
            from app.models.enums import UserRole
            from app.models.user import User

            replies_path = "/discord/mentions/feed/191"
            url = "https://discord.com/api/v10/channels/20/messages/191"
            source = {"id": "191", "channel_id": "20", "author": {"id": "77"}, "mentions": []}
            original_request = httpx.AsyncClient.request
            discord_calls = []

            async def request(client, method, address, **kwargs):
                if not address.startswith("https://discord.com/api/v10/"):
                    return await original_request(client, method, address, **kwargs)
                discord_calls.append((method, address, kwargs))
                req = httpx.Request(method, address)
                if method == "GET":
                    return httpx.Response(200, request=req, json=source)
                if method == "POST":
                    return httpx.Response(200, request=req, json={
                        "id": "300", "channel_id": "20", "author": {"id": "99", "username": "GA bot", "bot": True},
                        "timestamp": (at + timedelta(minutes=8)).isoformat(), "content": "GA: Mirë @everyone",
                        "message_reference": {"message_id": "191"}, "attachments": [],
                    })
                return httpx.Response(204, request=req)

            with patch.object(httpx.AsyncClient, "request", request):
                reply = await self.post(replies_path + "/reply", {"text": "Mirë @everyone", "nonce": "abcdef"})
                self.assertEqual(reply, {"id": "dc:300", "url": "https://discord.com/channels/10/20/300"})
                post_call = discord_calls[1]
                self.assertEqual(post_call[1], "https://discord.com/api/v10/channels/20/messages")
                self.assertEqual(post_call[2]["json"], {
                    "content": "GA: Mirë @everyone", "message_reference": {"message_id": "191", "fail_if_not_exists": True},
                    "allowed_mentions": {"parse": [], "replied_user": False}, "nonce": "abcdef", "enforce_nonce": True,
                })
                responses = (await self.get(paths[0]))["items"][0]["context"]["përgjigjet"]
                self.assertIn("dc:300", [item["id"] for item in responses])
                for remove, method in ((False, "PUT"), (True, "DELETE")):
                    result = await self.post(replies_path + "/react", {"emoji": "👀", "remove": remove})
                    self.assertEqual(result, {"id": "dc:191", "emoji": "👀", "removed": remove})
                    self.assertEqual(discord_calls[-1][:2], (method, url + "/reactions/%F0%9F%91%80/@me"))

                before = len(discord_calls)
                await self.post("/discord/mentions/feed/190/reply", {"text": "test"}, expect=404)
                await self.post(replies_path + "/react", {"emoji": "not an emoji"}, expect=422)
                await self.post(replies_path + "/react", {"emoji": "👍"}, token=self.staff_token, expect=403)
                async with self.SessionLocal() as db:
                    other = await db.scalar(select(User).where(User.id == self.colleague.id))
                    other.role = UserRole.ADMIN
                    await db.commit()
                await self.post(replies_path + "/reply", {"text": "test"}, token=self.staff_token, expect=403)
                self.assertEqual(len(discord_calls), before)

            url = "https://discord.com/api/v10/channels/20/messages/191"
            fresh = "https://cdn.discordapp.com/attachments/20/30/plan.pdf?ex=fresh"
            original_get = httpx.AsyncClient.get
            discord_get = AsyncMock(return_value=httpx.Response(200, request=httpx.Request("GET", url), json={
                "id": "191", "channel_id": "20", "author": {"id": "77"}, "mentions": [],
                "attachments": [{"id": "30", "filename": "plan.pdf", "url": fresh}],
            }))

            async def fake_discord_get(client, address, **kwargs):
                if address == url:
                    return await discord_get(address, **kwargs)
                return await original_get(client, address, **kwargs)

            with patch.object(httpx.AsyncClient, "get", fake_discord_get):
                self.assertEqual((await self.get(f"{paths[0]}/191/attachments"))["attachments"][0]["url"], fresh)
                for mid in ("190", "192", "205", "206"):
                    response = await self.client.get(f"/api/ga-assistant{paths[0]}/{mid}/attachments", headers=self.h())
                    self.assertEqual(response.status_code, 404)
                self.assertEqual(discord_get.await_count, 1)

    async def test_agenda_classifies_like_admin_tasks_and_respects_window(self) -> None:
        start, end = self.at(self.today, 8), self.at(self.today, 12)
        data = await self.get("/agenda", start=start.isoformat(), end=end.isoformat())
        by_title = {item["title"]: item for item in data["items"]}
        self.assertEqual(set(by_title), {"GA 1H", "Template BZ"})
        self.assertEqual(by_title["GA 1H"]["time_basis"], "one_h_slot")
        self.assertEqual(by_title["Template BZ"]["kind"], "BZ")
        self.assertEqual(by_title["Template BZ"]["time_basis"], "koha_bz")
        self.assertTrue(by_title["Template BZ"]["start"].startswith(f"{self.today.isoformat()}T11:50"))
        self.assertEqual(by_title["Template BZ"]["bz_with"], ["Colleague Test"])

        data = await self.get("/agenda", start=self.at(self.today).isoformat(),
                              end=self.at(self.today + timedelta(days=1)).isoformat(), include_untimed="true")
        kinds = {item["title"]: item["kind"] for item in data["items"]}
        self.assertEqual(kinds["GA untimed"], "GA_TASK")
        self.assertEqual(kinds["Colleague with GA BZ"], "BZ")
        self.assertEqual(kinds["Colleague F"], "F_TASK")
        self.assertEqual(kinds[f"TAK EXT: Klient X"], "MEETING")
        self.assertNotIn("Unrelated", kinds)
        self.assertNotIn("GA done", kinds)
        self.assertNotIn("GA late", kinds)  # overdue work is reported by leftovers

    async def test_leftovers_and_untimed(self) -> None:
        data = await self.get("/leftovers", as_of=self.at(self.today, 12).isoformat())
        titles = [item["title"] for item in data["items"]]
        self.assertEqual(titles[0], "GA late")
        self.assertGreaterEqual(data["items"][0]["days_late"], 1)
        self.assertIn("GA 1H", titles)  # 10:00 slot is before 12:00
        self.assertNotIn("GA done", titles)
        data = await self.get("/untimed", day=self.today.isoformat())
        self.assertEqual({item["title"] for item in data["items"]}, {"GA untimed", "Colleague with GA BZ", "Colleague F"})

    async def test_done_for_each_relation_and_audit(self) -> None:
        from sqlalchemy import select

        # Closing needs GA's result comment (PrimeFlow RLZ rule); without it nothing changes.
        refused = await self.post("/items/done", {"item_id": f"pf_task:{self.t_untimed.id}"}, expect=409)
        self.assertEqual(refused["detail"]["code"], "RLZ_COMPLETION_OVERRIDE_REASON_REQUIRED")
        done = await self.post("/items/done", {"item_id": f"pf_task:{self.t_untimed.id}", "comment": "U krye"})
        self.assertEqual(done["result"], "done")
        bz = await self.post("/items/done", {"item_id": f"pf_task:{self.t_bz.id}"})
        self.assertEqual(bz["result"], "bz_held")
        await self.post("/items/done", {"item_id": f"pf_task:{self.t_f.id}"}, expect=409)
        held = await self.post("/items/done", {"item_id": f"pf_meeting:{self.meeting.id}@{self.today.isoformat()}"})
        self.assertEqual(held["status"], "Mbajtur")
        async with self.SessionLocal() as db:
            untimed = await db.get(self.Task, self.t_untimed.id)
            colleague_task = await db.get(self.Task, self.t_bz.id)
            self.assertEqual(untimed.status, "DONE")
            self.assertIsNotNone(untimed.completed_at)
            self.assertEqual(colleague_task.status, "TODO")  # BZ never closes the colleague's task
            actions = set((await db.execute(
                select(self.AuditLog.action).where(self.AuditLog.actor_user_id == self.ga.id)
            )).scalars().all())
        self.assertTrue({"GA_ASSISTANT_DONE", "GA_ASSISTANT_BZ_HELD", "GA_ASSISTANT_MEETING_HELD"} <= actions)
        data = await self.get("/agenda", start=self.at(self.today, 14).isoformat(), end=self.at(self.today, 15).isoformat())
        self.assertEqual(data["items"][0]["status"], "Mbajtur")

    async def test_postpone_set_time_and_remove_from_day(self) -> None:
        tomorrow = self.today + timedelta(days=1)
        await self.post("/items/postpone", {"item_id": f"pf_task:{self.t_late.id}", "new_date": tomorrow.isoformat(), "new_time": "09:30"})
        async with self.SessionLocal() as db:
            late = await db.get(self.Task, self.t_late.id)
            self.assertEqual(late.due_date.astimezone(TZ).date(), tomorrow)
            self.assertEqual(late.original_due_date.astimezone(TZ).date(), self.today - timedelta(days=3))
        data = await self.get("/agenda", start=self.at(tomorrow, 9).isoformat(), end=self.at(tomorrow, 10).isoformat())
        self.assertEqual([(i["title"], i["time_basis"]) for i in data["items"]], [("GA late", "assistant")])

        await self.post("/items/set-time", {"item_id": f"pf_task:{self.t_bz.id}", "time": "11:00"})
        data = await self.get("/agenda", start=self.at(self.today, 11).isoformat(), end=self.at(self.today, 11, 30).isoformat())
        self.assertEqual([i["title"] for i in data["items"]], ["Colleague with GA BZ"])
        await self.post("/items/set-time", {"item_id": f"pf_task:{self.t_bz.id}", "time": None})
        data = await self.get("/agenda", start=self.at(self.today, 11).isoformat(), end=self.at(self.today, 11, 30).isoformat())
        self.assertEqual(data["items"], [])
        async with self.SessionLocal() as db:
            self.assertEqual((await db.get(self.Task, self.t_bz.id)).due_date, self.at(self.today))  # task untouched

        await self.post("/items/postpone", {"item_id": f"pf_task:{self.t_bz.id}", "new_date": tomorrow.isoformat()}, expect=409)
        await self.post("/items/remove-from-day", {"item_id": f"pf_task:{self.t_f.id}", "reason": "jo sot"})
        data = await self.get("/untimed", day=self.today.isoformat())
        self.assertNotIn("Colleague F", {item["title"] for item in data["items"]})
        async with self.SessionLocal() as db:
            self.assertIsNotNone(await db.get(self.Task, self.t_f.id))  # soft: nothing deleted

    async def test_f_tasks_follow_the_m1_interval_and_group_copies(self) -> None:
        from app.models.enums import UserRole
        from app.models.task import Task
        from app.models.task_assignee import TaskAssignee
        from app.models.user import User

        group = uuid.uuid4()
        start, due = self.at(self.today - timedelta(days=1)), self.at(self.today + timedelta(days=2))
        async with self.SessionLocal() as db:
            third = User(email=f"third{group.hex[:6]}@example.com", username=f"third{group.hex[:6]}", full_name="Third Test",
                         password_hash="x", role=UserRole.STAFF, department_id=self.ids["dept"])
            db.add(third)
            await db.flush()
            copies = [
                Task(title="F shumeditore", department_id=self.ids["dept"], assigned_to=owner, status="TODO",
                     start_date=start, due_date=due, one_h_marker="F", fast_task_group_id=group)
                for owner in (self.colleague.id, third.id)
            ]
            db.add_all(copies)
            await db.flush()
            for copy in copies:
                db.add(TaskAssignee(task_id=copy.id, user_id=copy.assigned_to))
            await db.commit()
        weekdays = [d for d in (self.today, self.today + timedelta(days=1)) if d.weekday() < 5]
        for day in weekdays:
            data = await self.get("/untimed", day=day.isoformat())
            rows = [item for item in data["items"] if item["title"] == "F shumeditore"]
            self.assertEqual(len(rows), 1, f"one grouped row on {day}")
            self.assertEqual(rows[0]["kind"], "F_TASK")
            self.assertEqual(sorted(rows[0]["assignees"]), ["Colleague Test", "Third Test"])

    async def test_comment_and_permissions(self) -> None:
        from sqlalchemy import select

        from app.models.task_user_comment import TaskUserComment

        await self.post("/items/comment", {"item_id": f"pf_task:{self.t_1h.id}", "text": "Fol me klientin"})
        async with self.SessionLocal() as db:
            comment = (await db.execute(select(TaskUserComment.comment).where(
                TaskUserComment.task_id == self.t_1h.id, TaskUserComment.user_id == self.ga.id))).scalar_one()
        self.assertIn("Fol me klientin", comment)
        res = await self.client.get("/api/ga-assistant/agenda", params={"start": "2026-11-19", "end": "2026-11-20"},
                                    headers=self.h(self.staff_token))
        self.assertEqual(res.status_code, 403)
        await self.post("/items/done", {"item_id": "ms_event:abc"}, expect=409)
        await self.post("/items/done", {"item_id": "nope:1"}, expect=422)

    async def test_todo_actions_go_through_graph_and_are_audited(self) -> None:
        from sqlalchemy import select

        client = AsyncMock()
        client.get.return_value = {"id": "T", "body": {"content": "shënim\n☐ hapi"}, "isReminderOn": False,
                                   "dueDateTime": {"dateTime": f"{self.today.isoformat()}T00:00:00", "timeZone": "UTC"}}
        client.update.return_value = {"id": "T", "title": "x", "status": "notStarted"}
        with patch("app.api.routers.ga_assistant._todo_client", AsyncMock(return_value=client)):
            await self.post("/items/done", {"item_id": "todo:L::T"})
            client.update.assert_awaited_with("L", "T", {"status": "completed"})
            await self.post("/items/set-time", {"item_id": "todo:L::T", "time": "11:00"})
            body = client.update.await_args.args[2]
            self.assertTrue(body["isReminderOn"])
            self.assertEqual(body["reminderDateTime"]["timeZone"], "UTC")
            await self.post("/items/comment", {"item_id": "todo:L::T", "text": "shtesë"})
            self.assertEqual(client.update.await_args.args[2]["body"]["content"], "shënim\nshtesë\n\n☐ hapi")
            res = await self.client.put("/api/ga-assistant/todo/todo:L::T/steps", headers=self.h(),
                                        json={"steps": [{"text": "a", "done": True}, {"text": "b"}]})
            self.assertEqual(res.status_code, 200, res.text)
            self.assertEqual(client.update.await_args.args[2]["body"]["content"], "shënim\n\n☑ a\n☐ b")
        async with self.SessionLocal() as db:
            actions = set((await db.execute(
                select(self.AuditLog.action).where(self.AuditLog.actor_user_id == self.ga.id)
            )).scalars().all())
        self.assertTrue({"GA_ASSISTANT_TODO_DONE", "GA_ASSISTANT_TODO_SET_TIME", "GA_ASSISTANT_TODO_COMMENT",
                         "GA_ASSISTANT_TODO_STEPS"} <= actions)


    async def test_iphone_reminders_discord_mentions_and_dedupe(self) -> None:
        from sqlalchemy import select
        from app.models.discord_assistant import DiscordLink
        from app.models.ga_discord_mention import GaDiscordMention
        from app.models.ga_icloud_sync_connection import GaIcloudSyncConnection
        from app.models.ga_time_slot_entry import GaTimeSlotEntry
        from app.services import ga_discord_mentions as mentions

        today = self.today
        async with self.SessionLocal() as db:
            conn = GaIcloudSyncConnection(ga_user_id=self.ga.id, calendar_name="cal", reminder_list_name="REMINDER",
                                          token_hash="x" * 64, last_synced_at=self.at(today, 8))
            db.add(conn)
            await db.flush()

            def row(day, content, key, start=time(0, 0)):
                db.add(GaTimeSlotEntry(user_id=self.ga.id, day_date=day, start_time=start, end_time=time(0, 1),
                                       content=content, sync_connection_id=conn.id, source_type="reminder",
                                       source_external_id=key, source_name="REMINDER"))

            row(today, "REMINDER 10:30: Thirr bankën", "timed", time(10, 0))
            row(today, "REMINDER 00:00: Pagesa e qirasë", "dateonly")
            row(today - timedelta(days=7), "REMINDER: Pa datë", "undated")
            row(today - timedelta(days=2), "REMINDER 09:00: E vjetër", "late", time(9, 0))
            row(today - timedelta(days=10), "REMINDER: Jashtë dritares", "stale")
            db.add(DiscordLink(user_id=self.ga.id, discord_user_id="42", guild_id="1"))
            db.add(DiscordLink(user_id=self.colleague.id, discord_user_id="77", guild_id="1"))
            await db.commit()

        with patch.object(settings, "GA_DISCORD_MENTIONS_BOT_TOKEN", "t"), patch.object(settings, "DISCORD_GUILD_ID", "1"):
            bot = {"X-GA-Mentions-Secret": mentions.bridge_secret()}
            bad = await self.client.get("/api/ga-discord-bot/context", headers={"X-GA-Mentions-Secret": "nope"})
            self.assertEqual(bad.status_code, 401)
            context = (await self.client.get("/api/ga-discord-bot/context", headers=bot)).json()
            self.assertEqual(context["ga_discord_id"], "42")
            sent = self.at(today, 9, 5).isoformat()
            message = {"id": "1001", "guild_id": "1", "channel_id": "9", "channel_name": "development",
                       "author_discord_id": "77", "author_name": "coll", "created_at": sent,
                       "content": "Kontrolloje detyrën", "jump_url": "https://discord.com/channels/1/9/1001",
                       "attachments": [{"name": "plan.pdf", "url": "https://cdn.discordapp.com/a/plan.pdf"}],
                       "reasons": ["mention"]}
            own = {**message, "id": "1002", "author_discord_id": "42", "jump_url": "https://discord.com/channels/1/9/1002"}
            other_server = {**message, "id": "1003", "guild_id": "2", "jump_url": "https://discord.com/channels/2/9/1003"}
            res = await self.client.post("/api/ga-discord-bot/mentions", headers=bot,
                                         json={"messages": [message, own, other_server]})
            self.assertEqual(res.json(), {"stored": 1, "skipped": 2})

            # Reactions: who reviewed the message before GA (approval emoji, not the author, not GA).
            context = (await self.client.get("/api/ga-discord-bot/context", headers=bot)).json()
            self.assertIn("1001", context["tracked_message_ids"])
            self.assertIn({"id": "1001", "channel_id": "9"}, context["reactions_unsynced"])
            first = (await self.get("/discord/mentions"))["items"][0]
            self.assertEqual((first["reactions"], first["reviewed_by"], first["ready_for_ga"]), ([], [], False))
            reactions = [
                {"emoji": "✅", "count": 2, "users": [{"discord_id": "77", "name": "coll"}, {"discord_id": "42", "name": "ga"}]},
                {"emoji": "😀", "count": 1, "users": [{"discord_id": "66", "name": "Arta Berisha"}]},
            ]
            res = await self.client.post("/api/ga-discord-bot/reactions", headers=bot, json={"message_id": "1001", "reactions": reactions})
            self.assertEqual(res.json(), {"updated": True})
            item = (await self.get("/discord/mentions"))["items"][0]
            self.assertEqual(item["reactions"][0]["users"][0], {"name": "Colleague Test", "initials": "CT"})
            self.assertEqual((item["reviewed_by"], item["ready_for_ga"]), ([], False))  # author + GA + non-approval emoji
            self.assertEqual((await self.get("/discord/mentions", only_ready="true"))["count"], 0)
            reactions.append({"emoji": "👍🏽", "count": 1, "users": [{"discord_id": "55", "name": "Laurent Hoxha"}]})
            await self.client.post("/api/ga-discord-bot/reactions", headers=bot, json={"message_id": "1001", "reactions": reactions})
            ready = await self.get("/discord/mentions", only_ready="true")
            self.assertEqual([(m["id"], m["reviewed_by"], m["ready_for_ga"]) for m in ready["items"]], [("dc:1001", ["LH"], True)])
            # An edit (no reactions in the payload) keeps the stored reactions; unknown messages are ignored.
            await self.client.post("/api/ga-discord-bot/mentions", headers=bot, json={"messages": [{**message, "content": "ndryshuar"}]})
            self.assertEqual(len((await self.get("/discord/mentions"))["items"][0]["reactions"]), 3)
            res = await self.client.post("/api/ga-discord-bot/reactions", headers=bot, json={"message_id": "999", "reactions": []})
            self.assertEqual(res.json(), {"updated": False})
            context = (await self.client.get("/api/ga-discord-bot/context", headers=bot)).json()
            self.assertNotIn({"id": "1001", "channel_id": "9"}, context["reactions_unsynced"])

            agenda = await self.get("/agenda", start=self.at(today).isoformat(),
                                    end=self.at(today + timedelta(days=1)).isoformat(), include_untimed="true")
            by_id = {item["id"]: item for item in agenda["items"]}
            self.assertEqual(by_id["tt:timed"]["start"][11:16], "10:30")
            self.assertEqual((by_id["tt:timed"]["source"], by_id["tt:timed"]["can_complete"]), ("iphone_sync", False))
            self.assertIsNone(by_id["tt:dateonly"]["start"])
            self.assertEqual(by_id["tt:undated"]["day"], today.isoformat())  # undated: today until done
            self.assertNotIn("tt:stale", by_id)
            dc = by_id["dc:1001"]
            self.assertEqual((dc["kind"], dc["assignees"]), ("DISCORD", ["Colleague Test"]))
            self.assertTrue(dc["title"].startswith("CT në #development"))

            leftovers = {item["id"]: item for item in (await self.get("/leftovers", as_of=self.at(today, 12).isoformat()))["items"]}
            self.assertEqual(leftovers["tt:late"]["days_late"], 2)
            self.assertIn("tt:timed", leftovers)
            self.assertNotIn("tt:stale", leftovers)

            res = await self.client.post("/api/ga-assistant/items/done", json={"item_id": "tt:timed"}, headers=self.h())
            self.assertEqual(res.status_code, 409)
            self.assertIn("iPhone", res.json()["detail"])
            await self.post("/discord/mentions/dc:1001/status", {"status": "seen"})
            listed = await self.get("/discord/mentions")
            self.assertEqual([(m["id"], m["author_initials"], m["status"]) for m in listed["items"]], [("dc:1001", "CT", "seen")])
            await self.post("/items/done", {"item_id": "dc:1001"})
            self.assertEqual((await self.get("/discord/mentions"))["count"], 0)
            self.assertEqual((await self.get("/discord/mentions", only_open="false"))["items"][0]["status"], "done")

            # Same reminder in To Do and on the phone: returned once, as the To Do item.
            from app.services import ga_assistant as svc
            svc_item = svc.AgendaItem(id="todo:L::T", item_key="todo:L::T", source="microsoft_todo", kind="REMINDER",
                                      title="thirr bankën", day=today, can_complete=True)
            with patch("app.services.ga_assistant.collect_microsoft_items", AsyncMock(return_value=([svc_item], []))):
                agenda = await self.get("/agenda", start=self.at(today).isoformat(),
                                        end=self.at(today + timedelta(days=1)).isoformat(), include_untimed="true")
            ids = [item["id"] for item in agenda["items"]]
            self.assertIn("todo:L::T", ids)
            self.assertNotIn("tt:timed", ids)
            todo = next(item for item in agenda["items"] if item["id"] == "todo:L::T")
            self.assertEqual((todo["linked_ids"], todo["start"][11:16]), (["tt:timed"], "10:30"))
        async with self.SessionLocal() as db:
            stored = await db.get(GaDiscordMention, "1001")
            self.assertEqual(stored.status_changed_by, self.ga.id)
            actions = set((await db.execute(select(self.AuditLog.action).where(self.AuditLog.actor_user_id == self.ga.id))).scalars().all())
        self.assertIn("GA_ASSISTANT_DISCORD_MARK", actions)

if __name__ == "__main__":
    unittest.main()
