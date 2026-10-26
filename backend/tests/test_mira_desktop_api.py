import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@127.0.0.1/primeflow_test')
os.environ.setdefault('JWT_SECRET', 'desktop-test-secret')
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.routers.mira_desktop import router
from app.api.deps import get_current_user
from app.db import get_db
from app.services import mira_desktop as service


def client():
    app = FastAPI()
    app.include_router(router, prefix='/api/mira-desktop')
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.UUID(int=1))
    app.dependency_overrides[get_db] = lambda: None
    return TestClient(app)


def test_capabilities_independent_of_discord_flag():
    with patch.object(service.settings, 'OPENAI_API_KEY', 'fake'), patch.object(
            service.settings, 'DISCORD_MEETING_NOTES_ENABLED', False):
        response = client().get('/api/mira-desktop/capabilities')
    assert response.status_code == 200
    assert response.json() == dict(enabled=True, user_id=str(uuid.UUID(int=1)),
        max_segment_seconds=10, max_duration_seconds=14400, frontend_url=service.settings.FRONTEND_URL)


def test_consent_and_input_bounds_reject_before_service():
    with patch.object(service, 'create_session', AsyncMock()) as create:
        for body in [dict(id=str(uuid.uuid4()), title='Call', consent_acknowledged=False),
                     dict(id=str(uuid.uuid4()), title=' ', consent_acknowledged=True),
                     dict(id=str(uuid.uuid4()), title='x'*201, consent_acknowledged=True)]:
            assert client().post('/api/mira-desktop/sessions', json=body).status_code == 422
        create.assert_not_awaited()


def test_upload_rejects_wrong_content_type_and_oversized_stream():
    url = f'/api/mira-desktop/sessions/{uuid.uuid4()}/segments/0?start_ms=0&end_ms=10'
    with patch.object(service, 'upload_segment', AsyncMock()) as upload:
        assert client().post(url, content=b'abc').status_code == 415
        assert client().post(url, content=b'x'*(service.MAX_AUDIO_BYTES+1),
            headers={'Content-Type': 'audio/wav'}).status_code == 413
        upload.assert_not_awaited()


def test_every_route_requires_normal_user_authentication():
    app = FastAPI()
    app.include_router(router, prefix='/api/mira-desktop')
    app.dependency_overrides[get_db] = lambda: None
    api = TestClient(app)
    session = str(uuid.uuid4())
    for method, path, kwargs in [
        ('get', '/capabilities', {}),
        ('get', f'/sessions/{session}', {}),
        ('post', '/sessions', {'json': dict(id=session, title='Call', consent_acknowledged=True)}),
        ('post', f'/sessions/{session}/finish', {'json': dict(segment_count=0)}),
        ('post', f'/sessions/{session}/segments/0?start_ms=0&end_ms=10',
            {'content': b'abc', 'headers': {'Content-Type': 'audio/wav'}}),
    ]:
        assert getattr(api, method)('/api/mira-desktop'+path, **kwargs).status_code == 401
