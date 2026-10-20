import os
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@127.0.0.1/primeflow_test')
os.environ.setdefault('JWT_SECRET', 'voice-tests-not-a-production-secret')
from fastapi import HTTPException
from app.models.enums import UserRole
from app.schemas.ga_note import GaNoteCreate
from app.services.ga_note_creation import build_ga_note

class NoteCreationTests(unittest.IsolatedAsyncioTestCase):
    async def test_staff_cannot_create_unscoped_or_other_department_note(self):
        user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.STAFF, department_id=uuid.uuid4(), email='test@example.test')
        db = SimpleNamespace(add=Mock(), get=AsyncMock())
        for department in [None, uuid.uuid4()]:
            with self.assertRaises(HTTPException):
                await build_ga_note(db, user, GaNoteCreate(content='Meeting', department_id=department))
        db.add.assert_not_called()

    async def test_builder_uses_existing_owner_and_does_not_commit(self):
        user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.STAFF, department_id=uuid.uuid4(), email='test@example.test')
        db = SimpleNamespace(add=Mock(), get=AsyncMock(), commit=AsyncMock())
        note = await build_ga_note(db, user, GaNoteCreate(content='Meeting', department_id=user.department_id))
        self.assertEqual(note.created_by, user.id)
        self.assertEqual(note.department_id, user.department_id)
        db.commit.assert_not_called()

    async def test_normal_project_note_keeps_project_and_department(self):
        user=SimpleNamespace(id=uuid.uuid4(),role=UserRole.STAFF,department_id=uuid.uuid4(),email='test@example.test')
        project=SimpleNamespace(id=uuid.uuid4(),department_id=user.department_id)
        db=SimpleNamespace(add=Mock(),execute=AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=project))))
        note=await build_ga_note(db,user,GaNoteCreate(content='Project note',project_id=project.id))
        self.assertEqual(note.project_id,project.id);self.assertEqual(note.department_id,user.department_id)
