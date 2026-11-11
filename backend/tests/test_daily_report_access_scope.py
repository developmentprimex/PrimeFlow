import unittest
import uuid
from types import SimpleNamespace

from fastapi import HTTPException

from app.api.routers.reports import (
    _enforce_daily_report_target_scope,
    _resolve_effective_department_id,
    _resolve_target_user_id,
)
from app.models.enums import UserRole


class TestDailyReportAccessScope(unittest.TestCase):
    def test_staff_can_access_own_report_in_department(self) -> None:
        department_id = uuid.uuid4()
        user_id = uuid.uuid4()
        current_user = SimpleNamespace(id=user_id, role=UserRole.STAFF, department_id=department_id)
        target_user = SimpleNamespace(id=user_id, department_id=department_id)

        effective_department = _resolve_effective_department_id(
            current_user=current_user,
            requested_department_id=department_id,
        )
        self.assertEqual(effective_department, department_id)
        _enforce_daily_report_target_scope(
            current_user=current_user,
            effective_department_id=effective_department,
            target_user=target_user,
        )

    def test_staff_can_access_other_user_same_department(self) -> None:
        department_id = uuid.uuid4()
        current_user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.STAFF, department_id=department_id)
        target_user = SimpleNamespace(id=uuid.uuid4(), department_id=department_id)

        effective_department = _resolve_effective_department_id(
            current_user=current_user,
            requested_department_id=None,
        )
        self.assertEqual(effective_department, department_id)
        _enforce_daily_report_target_scope(
            current_user=current_user,
            effective_department_id=effective_department,
            target_user=target_user,
        )

    def test_staff_cannot_access_user_from_other_department(self) -> None:
        current_user_department_id = uuid.uuid4()
        other_department_id = uuid.uuid4()
        current_user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.STAFF, department_id=current_user_department_id)
        target_user = SimpleNamespace(id=uuid.uuid4(), department_id=other_department_id)

        with self.assertRaises(HTTPException) as err:
            _enforce_daily_report_target_scope(
                current_user=current_user,
                effective_department_id=current_user_department_id,
                target_user=target_user,
            )
        self.assertEqual(err.exception.status_code, 403)

    def test_manager_admin_behavior_with_department_scope(self) -> None:
        department_id = uuid.uuid4()
        manager = SimpleNamespace(id=uuid.uuid4(), role=UserRole.MANAGER, department_id=department_id)
        admin = SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN, department_id=None)
        target_other_department = SimpleNamespace(id=uuid.uuid4(), department_id=uuid.uuid4())

        with self.assertRaises(HTTPException):
            _enforce_daily_report_target_scope(
                current_user=manager,
                effective_department_id=department_id,
                target_user=target_other_department,
            )

        # Admin with no effective department can target any user.
        _enforce_daily_report_target_scope(
            current_user=admin,
            effective_department_id=None,
            target_user=target_other_department,
        )

    def test_omitted_user_id_defaults_to_current_user(self) -> None:
        current_user_id = uuid.uuid4()
        self.assertEqual(
            _resolve_target_user_id(requested_user_id=None, current_user_id=current_user_id),
            current_user_id,
        )


if __name__ == "__main__":
    unittest.main()


from tests.report_attendance_fixtures import present_report_population
