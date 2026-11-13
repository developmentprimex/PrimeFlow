import io
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException
from openpyxl import load_workbook

from app.api.routers.exports import export_checklist_xlsx
from app.models.enums import UserRole


class TestChecklistExportAccess(unittest.IsolatedAsyncioTestCase):
    async def export_template(self, role, group_key):
        checklist = SimpleNamespace(
            id=uuid.uuid4(), project_id=None, task_id=None,
            group_key=group_key, title="Template", columns=None,
        )
        checklist_result = MagicMock()
        checklist_result.scalar_one_or_none.return_value = checklist
        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = []
        db = SimpleNamespace(execute=AsyncMock(side_effect=[checklist_result, items_result]))
        return await export_checklist_xlsx(
            checklist_id=checklist.id, format="mst", exclude_path=None, db=db,
            user=SimpleNamespace(role=role, full_name="Test User", username="test"),
        )

    async def test_admin_and_manager_download_valid_workbook(self):
        for role in (UserRole.ADMIN, UserRole.MANAGER):
            for group_key in (
                "MST_PRODUCT_CHECKLIST_TEMPLATE",
                "TT_PRODUCT_CHECKLIST_TEMPLATE",
                "MEETING_TEMPLATE",
            ):
                with self.subTest(role=role, group_key=group_key):
                    response = await self.export_template(role, group_key)
                    content = b"".join([chunk async for chunk in response.body_iterator])
                    workbook = load_workbook(io.BytesIO(content))
                    self.assertIn("DETYRAT", [cell.value for row in workbook.active for cell in row])
                    self.assertIn("attachment;", response.headers["content-disposition"])

    async def test_staff_cannot_export_global_templates(self):
        for group_key in (
            "MST_PRODUCT_CHECKLIST_TEMPLATE",
            "TT_PRODUCT_CHECKLIST_TEMPLATE",
            "MEETING_TEMPLATE",
        ):
            with self.subTest(group_key=group_key):
                with self.assertRaises(HTTPException) as raised:
                    await self.export_template(UserRole.STAFF, group_key)
                self.assertEqual(raised.exception.status_code, 403)
