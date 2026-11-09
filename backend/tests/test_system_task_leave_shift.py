from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from app.services.system_task_instances import (
    _assignee_on_full_day_leave,
    _build_annual_leave_snapshot,
    _parse_annual_leave_entry,
    _replacement_user_for_occurrence,
    generate_system_task_instances,
    reconcile_system_task_assignments_for_day,
    reconcile_system_task_assignments_in_range,
)


class TestSystemTaskLeaveShift(TestCase):
    @staticmethod
    def _leave_snapshot(*user_ids: uuid.UUID):
        return ({user_id: [(date(2026, 5, 1), date(2026, 5, 1))] for user_id in user_ids}, [])

    def test_parse_annual_leave_entry_detects_all_users_marker(self) -> None:
        entry = SimpleNamespace(
            description="[ALL_USERS] Date: 2026-05-01 (Full day) Labour Day",
            entry_date=date(2026, 5, 1),
            created_at=datetime(2026, 4, 30, 8, 0, tzinfo=timezone.utc),
        )

        start_date, end_date, full_day, _, _, note, is_all_users = _parse_annual_leave_entry(entry)

        self.assertEqual(start_date, date(2026, 5, 1))
        self.assertEqual(end_date, date(2026, 5, 1))
        self.assertTrue(full_day)
        self.assertTrue(is_all_users)
        self.assertEqual(note, "Labour Day")

    def test_all_users_leave_blocks_date(self) -> None:
        user_id = uuid.uuid4()
        snapshot = _build_annual_leave_snapshot(
            [
                SimpleNamespace(
                    description="[ALL_USERS] Date: 2026-05-01 (Full day)",
                    entry_date=date(2026, 5, 1),
                    created_at=datetime(2026, 4, 30, 8, 0, tzinfo=timezone.utc),
                    assigned_to_user_id=None,
                    created_by_user_id=user_id,
                )
            ]
        )

        leave_by_user, all_users_ranges = snapshot
        self.assertTrue(
            _assignee_on_full_day_leave(user_id, date(2026, 5, 1), leave_by_user, all_users_ranges)
        )

    def test_only_individual_assignee_on_leave_is_blocked(self) -> None:
        first_user_id = uuid.uuid4()
        second_user_id = uuid.uuid4()
        working_user_id = uuid.uuid4()
        leave_by_user, all_users_ranges = _build_annual_leave_snapshot(
            [
                SimpleNamespace(
                    description="Date: 2026-05-01 (Full day)",
                    entry_date=date(2026, 5, 1),
                    created_at=datetime(2026, 4, 30, 8, 0, tzinfo=timezone.utc),
                    assigned_to_user_id=first_user_id,
                    created_by_user_id=first_user_id,
                ),
                SimpleNamespace(
                    description="Date: 2026-05-01 (Full day)",
                    entry_date=date(2026, 5, 1),
                    created_at=datetime(2026, 4, 30, 8, 0, tzinfo=timezone.utc),
                    assigned_to_user_id=second_user_id,
                    created_by_user_id=second_user_id,
                ),
            ]
        )

        self.assertTrue(
            _assignee_on_full_day_leave(
                first_user_id,
                date(2026, 5, 1),
                leave_by_user,
                all_users_ranges,
            )
        )
        self.assertTrue(
            _assignee_on_full_day_leave(
                second_user_id,
                date(2026, 5, 1),
                leave_by_user,
                all_users_ranges,
            )
        )
        self.assertFalse(
            _assignee_on_full_day_leave(
                working_user_id,
                date(2026, 5, 1),
                leave_by_user,
                all_users_ranges,
            )
        )

    def test_partial_day_leave_does_not_block_assignee(self) -> None:
        user_id = uuid.uuid4()
        leave_by_user, all_users_ranges = _build_annual_leave_snapshot(
            [
                SimpleNamespace(
                    description="Date: 2026-05-01 (08:00 - 12:00)",
                    entry_date=date(2026, 5, 1),
                    created_at=datetime(2026, 4, 30, 8, 0, tzinfo=timezone.utc),
                    assigned_to_user_id=user_id,
                    created_by_user_id=user_id,
                )
            ]
        )

        self.assertFalse(
            _assignee_on_full_day_leave(user_id, date(2026, 5, 1), leave_by_user, all_users_ranges)
        )

    def test_single_absent_assignee_uses_zv1_then_zv2(self) -> None:
        primary_id, zv1_id, zv2_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        slot = SimpleNamespace(primary_user_id=primary_id)
        template = SimpleNamespace(zv1_user_id=zv1_id, zv2_user_id=zv2_id)

        leave_by_user, all_users_ranges = self._leave_snapshot(primary_id)
        replacement_id, source_slot = _replacement_user_for_occurrence(
            template=template,
            slots=[slot],
            occurrence_day=date(2026, 5, 1),
            leave_by_user=leave_by_user,
            all_users_ranges=all_users_ranges,
            user_email_map={},
        )
        self.assertEqual(replacement_id, zv1_id)
        self.assertIs(source_slot, slot)

        leave_by_user, all_users_ranges = self._leave_snapshot(primary_id, zv1_id)
        replacement_id, _ = _replacement_user_for_occurrence(
            template=template,
            slots=[slot],
            occurrence_day=date(2026, 5, 1),
            leave_by_user=leave_by_user,
            all_users_ranges=all_users_ranges,
            user_email_map={},
        )
        self.assertEqual(replacement_id, zv2_id)

    def test_no_replacement_when_zv1_and_zv2_are_absent(self) -> None:
        primary_id, zv1_id, zv2_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        leave_by_user, all_users_ranges = self._leave_snapshot(primary_id, zv1_id, zv2_id)
        replacement_id, source_slot = _replacement_user_for_occurrence(
            template=SimpleNamespace(zv1_user_id=zv1_id, zv2_user_id=zv2_id),
            slots=[SimpleNamespace(primary_user_id=primary_id)],
            occurrence_day=date(2026, 5, 1),
            leave_by_user=leave_by_user,
            all_users_ranges=all_users_ranges,
            user_email_map={},
        )
        self.assertIsNone(replacement_id)
        self.assertIsNone(source_slot)

    def test_multi_assignee_without_gane_requires_everyone_to_be_absent(self) -> None:
        first_id, second_id, zv1_id, zv2_id = (uuid.uuid4() for _ in range(4))
        slots = [SimpleNamespace(primary_user_id=first_id), SimpleNamespace(primary_user_id=second_id)]
        template = SimpleNamespace(zv1_user_id=zv1_id, zv2_user_id=zv2_id)

        leave_by_user, all_users_ranges = self._leave_snapshot(first_id)
        replacement_id, _ = _replacement_user_for_occurrence(
            template=template,
            slots=slots,
            occurrence_day=date(2026, 5, 1),
            leave_by_user=leave_by_user,
            all_users_ranges=all_users_ranges,
            user_email_map={},
        )
        self.assertIsNone(replacement_id)

        leave_by_user, all_users_ranges = self._leave_snapshot(first_id, second_id)
        replacement_id, source_slot = _replacement_user_for_occurrence(
            template=template,
            slots=slots,
            occurrence_day=date(2026, 5, 1),
            leave_by_user=leave_by_user,
            all_users_ranges=all_users_ranges,
            user_email_map={},
        )
        self.assertEqual(replacement_id, zv1_id)
        self.assertIs(source_slot, slots[0])

    def test_gane_is_identified_by_email_case_insensitively(self) -> None:
        gane_id, first_id, second_id, zv1_id, zv2_id = (uuid.uuid4() for _ in range(5))
        slots = [
            SimpleNamespace(primary_user_id=gane_id),
            SimpleNamespace(primary_user_id=first_id),
            SimpleNamespace(primary_user_id=second_id),
        ]
        template = SimpleNamespace(zv1_user_id=zv1_id, zv2_user_id=zv2_id)
        email_map = {gane_id: "GA@PRIMEXEU.COM".lower()}

        leave_by_user, all_users_ranges = self._leave_snapshot(first_id)
        replacement_id, _ = _replacement_user_for_occurrence(
            template=template,
            slots=slots,
            occurrence_day=date(2026, 5, 1),
            leave_by_user=leave_by_user,
            all_users_ranges=all_users_ranges,
            user_email_map=email_map,
        )
        self.assertIsNone(replacement_id)

        leave_by_user, all_users_ranges = self._leave_snapshot(first_id, second_id)
        replacement_id, source_slot = _replacement_user_for_occurrence(
            template=template,
            slots=slots,
            occurrence_day=date(2026, 5, 1),
            leave_by_user=leave_by_user,
            all_users_ranges=all_users_ranges,
            user_email_map=email_map,
        )
        self.assertEqual(replacement_id, zv1_id)
        self.assertIs(source_slot, slots[1])


class TestSystemTaskLeaveGeneration(IsolatedAsyncioTestCase):
    async def test_range_reconciliation_covers_future_days_and_aggregates_results(self) -> None:
        db = AsyncMock()
        start = date(2026, 5, 1)
        now_utc = datetime(2026, 5, 1, 4, 0, tzinfo=timezone.utc)

        with patch(
            "app.services.system_task_instances.reconcile_system_task_assignments_for_day",
            new=AsyncMock(
                side_effect=[
                    {"reassigned": 1, "deactivated": 0, "reactivated": 0, "created": 0, "skipped": 0},
                    {"reassigned": 0, "deactivated": 1, "reactivated": 0, "created": 0, "skipped": 2},
                    {"reassigned": 2, "deactivated": 0, "reactivated": 1, "created": 0, "skipped": 0},
                ]
            ),
        ) as reconcile_day:
            result = await reconcile_system_task_assignments_in_range(
                db=db,
                start=start,
                end=date(2026, 5, 3),
                now_utc=now_utc,
            )

        self.assertEqual(
            result,
            {"reassigned": 3, "deactivated": 1, "reactivated": 1, "created": 0, "skipped": 2},
        )
        self.assertEqual(
            [call.kwargs["target_day"] for call in reconcile_day.await_args_list],
            [date(2026, 5, 1), date(2026, 5, 2), date(2026, 5, 3)],
        )
        self.assertTrue(all(call.kwargs["template_ids"] is None for call in reconcile_day.await_args_list))

    async def test_daily_reconciliation_reassigns_single_absent_user_to_zv1(self) -> None:
        primary_id, zv1_id, zv2_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        occurrence = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
        template = SimpleNamespace(
            id=uuid.uuid4(),
            timezone="UTC",
            department_id=None,
            zv1_user_id=zv1_id,
            zv2_user_id=zv2_id,
        )
        slot = SimpleNamespace(
            id=uuid.uuid4(),
            primary_user_id=primary_id,
            created_at=occurrence,
        )
        task = SimpleNamespace(
            id=uuid.uuid4(),
            origin_run_at=occurrence,
            assigned_to=primary_id,
            status="TODO",
            completed_at=None,
            progress_percentage=0,
            is_active=True,
        )
        leave_entry = SimpleNamespace(
            description="Date: 2026-05-01 (Full day)",
            entry_date=date(2026, 5, 1),
            created_at=occurrence,
            assigned_to_user_id=primary_id,
            created_by_user_id=primary_id,
        )
        rows_result = SimpleNamespace(all=lambda: [(task, template, slot)])
        leave_result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [leave_entry]))
        db = SimpleNamespace(execute=AsyncMock(side_effect=[rows_result, leave_result]))

        with (
            patch(
                "app.services.system_task_instances._system_task_user_maps",
                new=AsyncMock(return_value=({primary_id: None, zv1_id: uuid.uuid4(), zv2_id: None}, {})),
            ),
            patch(
                "app.services.system_task_instances._replace_generated_task_assignee",
                new=AsyncMock(),
            ) as replace_assignee,
        ):
            result = await reconcile_system_task_assignments_for_day(
                db=db,
                target_day=date(2026, 5, 1),
                now_utc=occurrence,
            )

        self.assertEqual(result["reassigned"], 1)
        replace_assignee.assert_awaited_once()
        self.assertEqual(replace_assignee.await_args.kwargs["user_id"], zv1_id)

    async def test_weekly_generator_keeps_full_original_plan_despite_leave(self) -> None:
        leave_user_id = uuid.uuid4()
        working_user_id = uuid.uuid4()
        occurrence = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
        template = SimpleNamespace(id=uuid.uuid4(), duration_days=1, department_id=None)
        leave_slot = SimpleNamespace(
            id=uuid.uuid4(),
            primary_user_id=leave_user_id,
            next_run_at=occurrence,
        )
        working_slot = SimpleNamespace(
            id=uuid.uuid4(),
            primary_user_id=working_user_id,
            next_run_at=occurrence,
        )
        slots_result = SimpleNamespace(all=lambda: [(leave_slot, template), (working_slot, template)])
        db = SimpleNamespace(execute=AsyncMock(return_value=slots_result))

        with (
            patch("app.services.system_task_instances.ensure_slots_initialized", new=AsyncMock()),
            patch(
                "app.services.system_task_instances._system_task_user_maps",
                new=AsyncMock(return_value=({leave_user_id: None, working_user_id: None}, {})),
            ),
            patch("app.services.system_task_instances.template_tz", return_value=timezone.utc),
            patch("app.services.system_task_instances.template_due_time", return_value=occurrence.time()),
            patch(
                "app.services.system_task_instances.next_occurrence",
                side_effect=lambda _template, current: current.replace(day=current.day + 7),
            ),
            patch(
                "app.services.system_task_instances._insert_system_task_instance",
                new=AsyncMock(return_value=True),
            ) as insert_instance,
        ):
            created = await generate_system_task_instances(
                db=db,
                now_utc=occurrence,
                start=occurrence.date(),
                end=occurrence.date(),
            )

        self.assertEqual(created, 2)
        self.assertEqual(insert_instance.await_count, 2)
        generated_slots = [call.kwargs["slot"] for call in insert_instance.await_args_list]
        self.assertEqual(generated_slots, [leave_slot, working_slot])

    async def test_weekly_generator_does_not_assign_replacements_early(self) -> None:
        first_id, second_id, zv1_id, zv2_id = (uuid.uuid4() for _ in range(4))
        occurrence = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
        template = SimpleNamespace(
            id=uuid.uuid4(),
            duration_days=1,
            department_id=None,
            zv1_user_id=zv1_id,
            zv2_user_id=zv2_id,
        )
        first_slot = SimpleNamespace(id=uuid.uuid4(), primary_user_id=first_id, next_run_at=occurrence)
        second_slot = SimpleNamespace(id=uuid.uuid4(), primary_user_id=second_id, next_run_at=occurrence)
        slots_result = SimpleNamespace(all=lambda: [(first_slot, template), (second_slot, template)])
        db = SimpleNamespace(execute=AsyncMock(return_value=slots_result))

        with (
            patch("app.services.system_task_instances.ensure_slots_initialized", new=AsyncMock()),
            patch(
                "app.services.system_task_instances._system_task_user_maps",
                new=AsyncMock(return_value=({first_id: None, second_id: None, zv1_id: uuid.uuid4()}, {})),
            ),
            patch("app.services.system_task_instances.template_tz", return_value=timezone.utc),
            patch("app.services.system_task_instances.template_due_time", return_value=occurrence.time()),
            patch(
                "app.services.system_task_instances.next_occurrence",
                side_effect=lambda _template, current: current.replace(day=current.day + 7),
            ),
            patch(
                "app.services.system_task_instances._insert_system_task_instance",
                new=AsyncMock(return_value=True),
            ) as insert_instance,
        ):
            created = await generate_system_task_instances(
                db=db,
                now_utc=occurrence,
                start=occurrence.date(),
                end=occurrence.date(),
            )

        self.assertEqual(created, 2)
        self.assertEqual(insert_instance.await_count, 2)
        assigned_ids = [call.kwargs["assignee_id"] for call in insert_instance.await_args_list]
        self.assertEqual(assigned_ids, [first_id, second_id])
