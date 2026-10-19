import io
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.api.deps import get_current_user
from app.api.routers import private_profile_photo as photos


class PrivateProfilePhotoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        storage = patch.object(photos, 'PHOTO_DIR', Path(self.tmp.name))
        storage.start()
        self.addCleanup(storage.stop)
        self.user = SimpleNamespace(id=uuid.uuid4(), email='42primex.eu@gmail.com', role='STAFF')
        app = FastAPI()
        app.include_router(photos.router, prefix='/profile-photo')
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def upload(self):
        image = io.BytesIO()
        Image.new('RGB', (32, 32), 'blue').save(image, 'PNG')
        return self.client.put('/profile-photo', files={'file': ('photo.png', image.getvalue(), 'image/png')})

    def test_owner_can_upload_read_replace_and_remove(self):
        self.assertEqual(self.client.get('/profile-photo').status_code, 404)
        self.assertEqual(self.upload().status_code, 204)
        response = self.client.get('/profile-photo')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'private, no-store')
        self.assertEqual(response.headers['content-type'], 'image/jpeg')
        self.assertEqual(Image.open(io.BytesIO(response.content)).size, (32, 32))
        self.assertEqual(self.upload().status_code, 204)
        self.assertEqual(self.client.delete('/profile-photo').status_code, 204)
        self.assertEqual(self.client.get('/profile-photo').status_code, 404)

    def test_other_accounts_including_admin_cannot_read_upload_or_delete(self):
        self.upload()
        for role in ('STAFF', 'ADMIN'):
            self.user = SimpleNamespace(id=uuid.uuid4(), email='other@example.com', role=role)
            self.assertEqual(self.client.get('/profile-photo').status_code, 403)
            self.assertEqual(self.upload().status_code, 403)
            self.assertEqual(self.client.delete('/profile-photo').status_code, 403)

    def test_same_name_does_not_grant_access(self):
        self.user = SimpleNamespace(id=uuid.uuid4(), email='fake@example.com', full_name='Eris Reqica')
        self.assertEqual(self.client.get('/profile-photo').status_code, 403)

    def test_invalid_and_oversized_files_rejected(self):
        response = self.client.put('/profile-photo', files={'file': ('fake.png', b'not an image', 'image/png')})
        self.assertEqual(response.status_code, 400)
        response = self.client.put('/profile-photo', files={'file': ('large.png', b'x' * (photos.MAX_PHOTO_BYTES + 1), 'image/png')})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.client.get('/profile-photo').status_code, 404)

    def test_anonymous_requests_require_login(self):
        app = FastAPI()
        app.include_router(photos.router, prefix='/profile-photo')
        with TestClient(app) as client:
            self.assertEqual(client.get('/profile-photo').status_code, 401)
