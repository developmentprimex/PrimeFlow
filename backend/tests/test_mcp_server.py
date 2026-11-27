import unittest
from unittest.mock import AsyncMock, patch

import mcp_server


class TestMcpDateHelpers(unittest.TestCase):
    def test_day_bounds_stay_inside_requested_day(self) -> None:
        day, start, end = mcp_server._day_bounds("2026-07-15")

        self.assertEqual(day, "2026-07-15")
        self.assertTrue(start.startswith("2026-07-15T00:00:00"))
        self.assertTrue(end.startswith("2026-07-15T23:59:59.999999"))

    def test_parse_day_supports_albanian_relative_words(self) -> None:
        today = mcp_server._parse_day("sot")

        self.assertEqual(mcp_server._parse_day("neser").toordinal(), today.toordinal() + 1)
        self.assertEqual(mcp_server._parse_day("dje").toordinal(), today.toordinal() - 1)

    def test_explicit_week_start_is_normalized_to_monday(self) -> None:
        self.assertEqual(mcp_server._week_start("2026-07-15"), "2026-07-13")


class TestMcpResolution(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        mcp_server._lookup_cache.clear()

    async def test_user_resolution_can_be_scoped_to_department(self) -> None:
        users = [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "full_name": "Endi Hyseni",
                "username": "endi.dev",
                "email": "endi.dev@example.com",
                "department_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            },
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "full_name": "Endi Hyseni",
                "username": "endi.other",
                "email": "endi.other@example.com",
                "department_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            },
        ]

        async def fake_request(method: str, path: str, **kwargs):
            if path == "/api/users":
                return users
            if path == "/api/departments":
                return [
                    {
                        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                        "name": "Development",
                        "code": "DEV",
                    }
                ]
            raise AssertionError(path)

        with patch.object(mcp_server, "_request", side_effect=fake_request):
            user_id = await mcp_server._resolve_user_id("Endi Hyseni", "Development")

        self.assertEqual(user_id, "11111111-1111-1111-1111-111111111111")


class TestMcpReorganizationTools(unittest.IsolatedAsyncioTestCase):
    async def test_structured_updates_preserve_unspecified_fields_and_allow_explicit_clear(self) -> None:
        with patch.object(mcp_server, "_request", new_callable=AsyncMock) as request:
            await mcp_server.ga_m1_reorg("2026-11-27", discussion="po", overload="jo", plan="")
            request.assert_awaited_once_with(
                "POST", "/api/ga-assistant/m1/reorg",
                json={"date": "2026-11-27", "discussion": "po", "overload": "jo", "plan": ""},
            )
            request.reset_mock()
            await mcp_server.ga_m1_reorg("2026-11-27", answer=None)
            request.assert_awaited_once_with(
                "POST", "/api/ga-assistant/m1/reorg", json={"date": "2026-11-27", "answer": None},
            )


class TestMcpTaskTools(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        mcp_server._lookup_cache.clear()

    async def test_user_day_query_does_not_include_tomorrow_boundary(self) -> None:
        async def fake_request(method: str, path: str, **kwargs):
            if path == "/api/tasks":
                self.assertTrue(kwargs["params"]["window_from"].startswith("2026-07-15T00:00:00"))
                self.assertTrue(kwargs["params"]["window_to"].startswith("2026-07-15T23:59:59.999999"))
                return []
            if path == "/api/users":
                return [{"id": "11111111-1111-1111-1111-111111111111", "full_name": "Endi Hyseni"}]
            raise AssertionError(path)

        with (
            patch.object(mcp_server, "_request", side_effect=fake_request),
            patch.object(
                mcp_server,
                "_resolve_user_id",
                AsyncMock(return_value="11111111-1111-1111-1111-111111111111"),
            ),
        ):
            result = await mcp_server.get_user_tasks_for_day("Endi Hyseni", "2026-07-15")

        self.assertEqual(result["day"], "2026-07-15")
        self.assertEqual(result["count"], 0)

    async def test_create_task_resolves_names_and_builds_backend_payload(self) -> None:
        request = AsyncMock(return_value={"id": "task-id", "title": "Test task"})
        with (
            patch.object(mcp_server, "_request", request),
            patch.object(
                mcp_server,
                "_resolve_department_id",
                AsyncMock(return_value="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            ),
            patch.object(mcp_server, "_resolve_project_id", AsyncMock(return_value=None)),
            patch.object(
                mcp_server,
                "_resolve_user_id",
                AsyncMock(return_value="11111111-1111-1111-1111-111111111111"),
            ),
        ):
            result = await mcp_server.create_task(
                title="Test task",
                department_ref="Development",
                assignee_name="Endi Hyseni",
                priority="HIGH",
                due_date="2026-07-15T16:00:00+02:00",
            )

        self.assertEqual(result["id"], "task-id")
        payload = request.await_args.kwargs["json"]
        self.assertEqual(payload["department_id"], "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        self.assertEqual(payload["assigned_to"], "11111111-1111-1111-1111-111111111111")
        self.assertEqual(payload["assignees"], ["11111111-1111-1111-1111-111111111111"])
        self.assertEqual(payload["priority"], "HIGH")

    async def test_registered_write_tools_have_enum_schemas(self) -> None:
        tools = {tool.name: tool for tool in await mcp_server.mcp.list_tools()}

        self.assertIn("create_meeting", tools)
        self.assertIn("create_plan_note", tools)
        self.assertIn("create_internal_note", tools)
        self.assertIn("create_common_entry", tools)
        meeting_type = tools["create_meeting"].inputSchema["properties"]["meeting_type"]
        self.assertEqual(meeting_type["enum"], ["internal", "external"])


class TestTaskTypeHelpers(unittest.TestCase):
    def test_normalize_task_type_accepts_aliases(self) -> None:
        self.assertEqual(mcp_server._normalize_task_type("1h"), "1H")
        self.assertEqual(mcp_server._normalize_task_type("P:"), "P")
        self.assertEqual(mcp_server._normalize_task_type("bllok"), "BLL")
        self.assertIsNone(mcp_server._normalize_task_type("ALL"))
        self.assertIsNone(mcp_server._normalize_task_type(None))
        with self.assertRaises(ValueError):
            mcp_server._normalize_task_type("XYZ")

    def test_task_type_code_mirrors_backend_priority(self) -> None:
        self.assertEqual(mcp_server._task_type_code({"is_bllok": True, "is_1h_report": True}), "BLL")
        self.assertEqual(mcp_server._task_type_code({"is_1h_report": True}), "1H")
        self.assertEqual(mcp_server._task_type_code({"ga_note_origin_id": "x"}), "GA")
        self.assertEqual(mcp_server._task_type_code({"is_personal": True}), "P")
        self.assertIsNone(mcp_server._task_type_code({}))

    def test_task_matches_type_filters_by_flag(self) -> None:
        task = {"is_1h_report": True, "is_personal": True}
        self.assertTrue(mcp_server._task_matches_type(task, "1H"))
        self.assertTrue(mcp_server._task_matches_type(task, "P"))
        self.assertFalse(mcp_server._task_matches_type(task, "BLL"))
        self.assertTrue(mcp_server._task_matches_type(task, None))


class TestNewTaskViewTools(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        mcp_server._lookup_cache.clear()
        self.users = [
            {"id": "11111111-1111-1111-1111-111111111111", "full_name": "Endi Hyseni"},
            {"id": "22222222-2222-2222-2222-222222222222", "full_name": "Laurent Hoxha"},
        ]
        self.tasks = [
            {
                "id": "aaaa",
                "title": "1H task",
                "status": "IN_PROGRESS",
                "is_1h_report": True,
                "one_h_report_slot": "10:00",
                "assignees": [self.users[0]],
            },
            {
                "id": "bbbb",
                "title": "Personal task",
                "status": "TODO",
                "is_personal": True,
                "assignees": [self.users[1]],
            },
        ]

    async def test_get_tasks_today_filters_type_and_groups_by_person(self) -> None:
        async def fake_request(method: str, path: str, **kwargs):
            if path == "/api/tasks":
                return list(self.tasks)
            if path == "/api/users":
                return self.users
            raise AssertionError(path)

        with patch.object(mcp_server, "_request", side_effect=fake_request):
            result = await mcp_server.get_tasks_today(task_type="1H")

        self.assertEqual(result["task_type"], "1H")
        self.assertEqual(result["total_tasks"], 1)
        self.assertEqual(len(result["people"]), 1)
        self.assertEqual(result["people"][0]["name"], "Endi Hyseni")
        self.assertEqual(result["people"][0]["tasks"][0]["type"], "1H")

    async def test_get_all_open_tasks_by_person_groups_everyone(self) -> None:
        async def fake_request(method: str, path: str, **kwargs):
            if path == "/api/tasks":
                self.assertFalse(kwargs["params"]["include_done"])
                return list(self.tasks)
            if path == "/api/users":
                return self.users
            raise AssertionError(path)

        with patch.object(mcp_server, "_request", side_effect=fake_request):
            result = await mcp_server.get_all_open_tasks_by_person()

        self.assertEqual(result["people_count"], 2)
        self.assertEqual(result["total_open_tasks"], 2)
        names = {person["name"] for person in result["people"]}
        self.assertEqual(names, {"Endi Hyseni", "Laurent Hoxha"})


class TestWeeklyPlanTools(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        mcp_server._lookup_cache.clear()

    async def test_save_weekly_plan_creates_when_no_plan_exists(self) -> None:
        calls = []

        async def fake_request(method: str, path: str, **kwargs):
            calls.append((method, path))
            if method == "GET" and path == "/api/planners/weekly-plans":
                return []
            if method == "POST" and path == "/api/planners/weekly-plans":
                return {"id": "plan-id", **kwargs["json"]}
            raise AssertionError((method, path))

        with (
            patch.object(mcp_server, "_request", side_effect=fake_request),
            patch.object(
                mcp_server,
                "_resolve_department_id",
                AsyncMock(return_value="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            ),
        ):
            result = await mcp_server.save_weekly_plan(
                department_ref="Development",
                content_json='{"days": {}}',
                week_start="2026-07-20",
            )

        self.assertEqual(result["action"], "created")
        self.assertEqual(result["plan"]["start_date"], "2026-07-20")
        self.assertEqual(result["plan"]["end_date"], "2026-07-26")
        self.assertIn(("POST", "/api/planners/weekly-plans"), calls)

    async def test_save_weekly_plan_updates_existing_plan(self) -> None:
        async def fake_request(method: str, path: str, **kwargs):
            if method == "GET" and path == "/api/planners/weekly-plans":
                return [{"id": "plan-id"}]
            if method == "PATCH" and path == "/api/planners/weekly-plans/plan-id":
                return {"id": "plan-id", **kwargs["json"]}
            raise AssertionError((method, path))

        with (
            patch.object(mcp_server, "_request", side_effect=fake_request),
            patch.object(
                mcp_server,
                "_resolve_department_id",
                AsyncMock(return_value="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            ),
        ):
            result = await mcp_server.save_weekly_plan(
                department_ref="Development",
                content_json='{"days": {}}',
                week_start="2026-07-20",
                finalize=True,
            )

        self.assertEqual(result["action"], "updated")
        self.assertTrue(result["plan"]["is_finalized"])

    async def test_save_weekly_plan_rejects_non_object_content(self) -> None:
        with patch.object(
            mcp_server,
            "_resolve_department_id",
            AsyncMock(return_value="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        ):
            with self.assertRaises(ValueError):
                await mcp_server.save_weekly_plan(
                    department_ref="Development",
                    content_json='["not", "an", "object"]',
                )


class TestRealizationTools(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        mcp_server._lookup_cache.clear()

    async def test_get_weekly_realization_resolves_department_and_normalizes_week(self) -> None:
        request = AsyncMock(return_value={"period": {"id": "period-1"}, "people": []})
        with (
            patch.object(mcp_server, "_request", request),
            patch.object(
                mcp_server,
                "_resolve_department_id",
                AsyncMock(return_value="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            ),
        ):
            result = await mcp_server.get_weekly_realization(
                "Development", "2026-07-29"
            )

        self.assertEqual(result["period"]["id"], "period-1")
        self.assertEqual(request.await_args.args[:2], ("GET", "/api/realization/weekly"))
        self.assertEqual(request.await_args.kwargs["params"]["week_start"], "2026-07-27")

    async def test_review_accepts_suggestion_without_model_side_scoring(self) -> None:
        user_id = "11111111-1111-1111-1111-111111111111"
        weekly = {
            "period": {"id": "period-1"},
            "people": [{"id": "result-1", "user_id": user_id}],
        }
        request = AsyncMock(return_value={"id": "result-1", "final_level": "B"})
        with (
            patch.object(
                mcp_server,
                "_weekly_realization",
                AsyncMock(
                    return_value=(
                        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                        "2026-07-27",
                        weekly,
                    )
                ),
            ),
            patch.object(
                mcp_server,
                "_resolve_user_id",
                AsyncMock(return_value=user_id),
            ),
            patch.object(mcp_server, "_request", request),
        ):
            result = await mcp_server.review_weekly_realization_person(
                "Development",
                "Endi Hyseni",
                week_start="2026-07-27",
                manager_comment="Confirmed",
            )

        self.assertEqual(result["final_level"], "B")
        self.assertEqual(
            request.await_args.args[1],
            "/api/realization/periods/period-1/results/result-1/review",
        )
        payload = request.await_args.kwargs["json"]
        self.assertIsNone(payload["final_level"])
        self.assertNotIn("final_bonus", payload)
        self.assertEqual(payload["manager_comment"], "Confirmed")

    async def test_completed_extra_observation_forwards_verification_metadata(self) -> None:
        request = AsyncMock(return_value={"id": "observation-1"})
        weekly = {
            "period": {
                "id": "period-1",
                "department_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            }
        }
        with (
            patch.object(
                mcp_server,
                "_weekly_realization",
                AsyncMock(
                    return_value=(
                        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                        "2026-07-27",
                        weekly,
                    )
                ),
            ),
            patch.object(
                mcp_server,
                "_resolve_user_id",
                AsyncMock(return_value="11111111-1111-1111-1111-111111111111"),
            ),
            patch.object(mcp_server, "_request", request),
        ):
            await mcp_server.add_realization_observation(
                "Development",
                "Endi Hyseni",
                "EXTRA_TASK",
                "POSITIVE",
                "Completed verified extra work",
                task_id="22222222-2222-2222-2222-222222222222",
                observation_kind="COMPLETED_EXTRA_TASK",
                replaces_unfinished_planned_task=False,
                duplicate=False,
            )

        payload = request.await_args.kwargs["json"]
        self.assertEqual(payload["scope_type"], "TASK")
        self.assertFalse(payload["evidence_json"]["duplicate"])
        self.assertFalse(
            payload["evidence_json"]["replaces_unfinished_planned_task"]
        )


class TestPeopleAndStepsTools(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        mcp_server._lookup_cache.clear()

    async def test_get_task_people_maps_controls(self) -> None:
        users = [
            {"id": "11111111-1111-1111-1111-111111111111", "full_name": "Endi Hyseni"},
            {"id": "22222222-2222-2222-2222-222222222222", "full_name": "Laurent Hoxha"},
            {"id": "33333333-3333-3333-3333-333333333333", "full_name": "Elsa Ferati"},
        ]

        async def fake_request(method: str, path: str, **kwargs):
            if path == "/api/tasks/task-1":
                return {
                    "id": "task-1",
                    "title": "Task",
                    "status": "TODO",
                    "assigned_to": users[0]["id"],
                    "assignees": [users[0]],
                    "confirmation_assignee_id": users[1]["id"],
                    "alignment_user_ids": [users[2]["id"]],
                    "department_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                }
            if path == "/api/users":
                return users
            if path == "/api/departments":
                return [{"id": "dddddddd-dddd-dddd-dddd-dddddddddddd", "name": "Development"}]
            raise AssertionError(path)

        with patch.object(mcp_server, "_request", side_effect=fake_request):
            result = await mcp_server.get_task_people("task-1")

        self.assertEqual(result["control_1_confirmer"]["name"], "Laurent Hoxha")
        self.assertEqual(result["control_2_alignment_users"][0]["name"], "Elsa Ferati")
        self.assertEqual(result["department"]["name"], "Development")

    async def test_add_task_step_creates_checklist_when_missing(self) -> None:
        calls = []

        async def fake_request(method: str, path: str, **kwargs):
            calls.append((method, path))
            if method == "GET" and path == "/api/checklists":
                return []
            if method == "POST" and path == "/api/checklists":
                return {"id": "checklist-1"}
            if method == "POST" and path == "/api/checklist-items":
                self.assertEqual(kwargs["json"]["checklist_id"], "checklist-1")
                return {"id": "item-1", "title": kwargs["json"]["title"]}
            raise AssertionError((method, path))

        with patch.object(mcp_server, "_request", side_effect=fake_request):
            result = await mcp_server.add_task_step("task-1", "Step one")

        self.assertEqual(result["item"]["title"], "Step one")
        self.assertIn(("POST", "/api/checklists"), calls)

    async def test_schedule_task_validates_slot_and_requires_fields(self) -> None:
        with self.assertRaises(ValueError):
            await mcp_server.schedule_task("task-1", one_h_report_slot="09:00")
        with self.assertRaises(ValueError):
            await mcp_server.schedule_task("task-1")

    async def test_schedule_task_sets_1h_flag_with_slot(self) -> None:
        request = AsyncMock(return_value={"id": "task-1"})
        with patch.object(mcp_server, "_request", request):
            await mcp_server.schedule_task("task-1", due_date="2026-07-20", one_h_report_slot="10:00")

        payload = request.await_args.kwargs["json"]
        self.assertEqual(payload["due_date"], "2026-07-20")
        self.assertEqual(payload["one_h_report_slot"], "10:00")
        self.assertTrue(payload["is_1h_report"])


class TestNewToolsRegistered(unittest.IsolatedAsyncioTestCase):
    async def test_all_new_tools_are_registered(self) -> None:
        tools = {tool.name for tool in await mcp_server.mcp.list_tools()}
        expected = {
            "get_tasks_today",
            "get_tasks_this_week",
            "get_all_open_tasks_by_person",
            "get_overdue_tasks",
            "get_weekly_plan",
            "save_weekly_plan",
            "get_plan_vs_actual",
            "prepare_next_week_plan",
            "get_task_people",
            "get_person_workload",
            "get_department_overview",
            "get_task_steps",
            "add_task_step",
            "set_task_step_done",
            "schedule_task",
            "get_weekly_report",
            "export_report",
            "get_weekly_realization",
            "calculate_weekly_realization",
            "review_weekly_realization_person",
            "add_realization_observation",
            "verify_realization_observation",
            "void_realization_observation",
            "approve_weekly_realization",
            "lock_weekly_realization",
        }
        self.assertTrue(expected.issubset(tools), expected - tools)


class TestDeleteIsBlockedByDefault(unittest.IsolatedAsyncioTestCase):
    async def test_api_request_refuses_delete_unless_enabled(self) -> None:
        with patch.object(mcp_server, "ALLOW_DELETE", False), patch.object(mcp_server, "_headers", AsyncMock()) as headers:
            with self.assertRaisesRegex(ValueError, "DELETE is disabled"):
                await mcp_server.primeflow_api_request("DELETE", "/api/tasks/11111111-1111-1111-1111-111111111111")
            headers.assert_not_called()

    async def test_full_profile_does_not_expose_assistant_only_tools(self) -> None:
        tools = {tool.name for tool in await mcp_server.mcp.list_tools()}
        self.assertFalse(tools & mcp_server.ASSISTANT_ONLY_TOOLS)
        self.assertEqual(len(tools), 75)


if __name__ == "__main__":
    unittest.main()
