import unittest
import uuid
import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit
from pathlib import Path

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI, HTTPException, Response
from fastapi.testclient import TestClient
from jose import jwt

from app.api.deps import get_current_user
from app.api.routers import mailbox
from app.auth.security import ALGORITHM
from app.db import get_db
from app.integrations import microsoft_mail as graph
from app.models.enums import UserRole
from app.models.mailbox_connection import MailboxConnection
from app.models.user import User


SCOPE = "User.Read Mail.Read MailboxSettings.Read"


class MailboxConnectionTests(unittest.TestCase):
    def setUp(self):
        self.key_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.key_dir.cleanup)
        self.key_path = Path(self.key_dir.name) / 'token.key'
        self.key_path.write_bytes(Fernet.generate_key())
        self.user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN, is_active=True)
        self.db = AsyncMock()
        self.db.add = lambda row: self.added.append(row)
        self.added = []
        self.db.get.return_value = None
        app = FastAPI()
        app.include_router(mailbox.router, prefix="/api/mailbox")
        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        for key, value in {
            "MS_CLIENT_ID": "mailbox-test", "MS_CLIENT_SECRET": "test-secret",
            "MS_TENANT_ID": "test-tenant", "MS_MAILBOX_EMAIL": "info@primexeu.com",
            "MS_MAIL_REDIRECT_URI": "http://testserver/api/mailbox/callback",
            "FRONTEND_URL": "http://frontend.test",
            "MS_MAIL_TOKEN_KEY_FILE": str(self.key_path),
        }.items():
            p = patch.object(mailbox.settings, key, value)
            p.start()
            self.addCleanup(p.stop)
        purpose = patch.object(mailbox, 'fetch_mailbox_type', new=AsyncMock(return_value='user'))
        purpose.start()
        self.addCleanup(purpose.stop)

    def authorize(self):
        response = self.client.post("/api/mailbox/authorize-url")
        self.assertEqual(response.status_code, 200)
        return parse_qs(urlsplit(response.json()["url"]).query)["state"][0]

    def token_data(self):
        return {"access_token": "access", "refresh_token": "refresh", "scope": SCOPE, "expires_in": 3600}

    def callback(self, state):
        return self.client.get("/api/mailbox/callback", params={"state": state, "code": "code"}, follow_redirects=False)

    def test_admin_only_and_no_database_access_for_other_roles(self):
        for role in (UserRole.MANAGER, UserRole.STAFF):
            self.user.role = role
            for method, path in (("get", "status"), ("post", "authorize-url"), ("post", "test"), ("delete", "connection")):
                self.assertEqual(getattr(self.client, method)(f"/api/mailbox/{path}").status_code, 403)
        self.db.get.assert_not_awaited()
        self.db.execute.assert_not_awaited()

    def test_authorization_requests_only_mail_read_scopes_and_sets_browser_cookie(self):
        state = self.authorize()
        payload = jwt.decode(state, mailbox.settings.JWT_SECRET, algorithms=[ALGORITHM])
        self.assertEqual(payload["type"], "mailbox_oauth")
        self.assertEqual(payload["sub"], str(self.user.id))
        self.assertEqual(self.client.cookies.get(mailbox.STATE_COOKIE), state)
        self.assertTrue(graph.has_mail_permissions("https://graph.microsoft.com/Mail.Read User.Read MailboxSettings.Read"))
        self.assertFalse(graph.has_mail_permissions("User.Read Calendars.ReadWrite"))
        self.assertFalse(any("write" in scope.lower() or "send" in scope.lower() for scope in graph.MAIL_SCOPES))

    def test_callback_without_matching_cookie_or_with_expired_state_is_rejected(self):
        with patch.object(mailbox, "mail_token_request", new=AsyncMock()) as exchange:
            self.assertIn("invalid_state", self.callback("forged").headers["location"])
            state = jwt.encode({"type": "mailbox_oauth", "sub": str(self.user.id), "mailbox": "info@primexeu.com", "exp": 1}, mailbox.settings.JWT_SECRET, algorithm=ALGORITHM)
            self.client.cookies.set(mailbox.STATE_COOKIE, state)
            self.assertIn("invalid_state", self.callback(state).headers["location"])
            exchange.assert_not_awaited()

    def test_wrong_account_does_not_replace_connection(self):
        state = self.authorize()
        self.db.get.return_value = self.user
        with patch.object(mailbox, "mail_token_request", new=AsyncMock(return_value=self.token_data())), patch.object(mailbox, "fetch_user_profile", new=AsyncMock(return_value={"mail": "other@example.com"})):
            response = self.callback(state)
        self.assertIn("wrong_account", response.headers["location"])
        self.db.commit.assert_not_awaited()
        self.assertEqual(self.added, [])

    def test_successful_callback_stores_encrypted_tokens_in_separate_table(self):
        state = self.authorize()
        self.db.get.side_effect = lambda model, key: self.user if model is User else None
        with patch.object(mailbox, "mail_token_request", new=AsyncMock(return_value=self.token_data())), patch.object(mailbox, "fetch_user_profile", new=AsyncMock(return_value={"mail": "INFO@PRIMEXEU.COM"})):
            response = self.callback(state)
        self.assertIn("mailbox=authorized", response.headers["location"])
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        row = self.added[0]
        self.assertIsInstance(row, MailboxConnection)
        self.assertNotEqual(row.access_token_encrypted, "access")
        self.assertEqual(graph.decrypt_token(row.refresh_token_encrypted), "refresh")
        self.assertEqual(row.mailbox_email, "info@primexeu.com")
        self.assertEqual(row.mailbox_type, "user")
        self.assertIsNone(self.client.cookies.get(mailbox.STATE_COOKIE))
        self.db.commit.assert_awaited_once()

    def test_missing_permissions_or_disabled_admin_cannot_connect(self):
        self.db.get.return_value = self.user
        state = self.authorize()
        data = self.token_data()
        data["scope"] = "User.Read Calendars.ReadWrite"
        with patch.object(mailbox, "mail_token_request", new=AsyncMock(return_value=data)):
            self.assertIn("missing_permissions", self.callback(state).headers["location"])
        self.user.is_active = False
        state = self.authorize()
        with patch.object(mailbox, "mail_token_request", new=AsyncMock()) as exchange:
            self.assertIn("denied", self.callback(state).headers["location"])
            exchange.assert_not_awaited()
        self.db.commit.assert_not_awaited()

    def test_status_has_no_tokens_and_does_not_claim_a_live_test(self):
        self.db.get.return_value = SimpleNamespace(scope=SCOPE, mailbox_type='user', connected_at=datetime.now(timezone.utc), last_checked_at=None)
        response = self.client.get("/api/mailbox/status")
        self.assertTrue(response.json()["authorized"])
        self.assertFalse(response.json()["connected"])
        self.assertTrue(response.json()["encryption_ready"])
        self.assertIsNone(response.json()["last_checked_at"])
        self.assertNotIn("token", response.text)
        self.assertEqual(response.headers["cache-control"], "private, no-store")

    def test_missing_key_blocks_authorization_and_reading(self):
        self.key_path.unlink()
        self.assertEqual(self.client.post('/api/mailbox/authorize-url').status_code, 503)
        self.assertEqual(self.client.post('/api/mailbox/test').status_code, 503)
        self.db.commit.assert_not_awaited()

    def test_shared_or_unknown_mailbox_is_not_stored(self):
        self.db.get.return_value = self.user
        for purpose in ('shared', 'unknown', 'room'):
            state = self.authorize()
            with patch.object(mailbox, 'mail_token_request', new=AsyncMock(return_value=self.token_data())), patch.object(mailbox, 'fetch_user_profile', new=AsyncMock(return_value={'mail': 'info@primexeu.com'})), patch.object(mailbox, 'fetch_mailbox_type', new=AsyncMock(return_value=purpose)):
                self.assertIn('unsupported_mailbox_type', self.callback(state).headers['location'])
        self.db.commit.assert_not_awaited()

    def test_encryption_is_independent_of_jwt_secret_and_needs_original_mailbox_key(self):
        encrypted = graph.encrypt_token('secret')
        with patch.object(mailbox.settings, 'JWT_SECRET', 'changed-jwt-secret'):
            self.assertEqual(graph.decrypt_token(encrypted), 'secret')
        self.key_path.write_bytes(Fernet.generate_key())
        with self.assertRaises(InvalidToken):
            graph.decrypt_token(encrypted)

    def test_disconnect_deletes_mailbox_only(self):
        response = self.client.delete("/api/mailbox/connection")
        self.assertEqual(response.json(), {"connected": False})
        statement = str(self.db.execute.await_args.args[0])
        self.assertIn("mailbox_connections", statement)
        self.assertNotIn("microsoft_tokens", statement)


class MailboxReadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'token.key'
        path.write_bytes(Fernet.generate_key())
        patched = patch.object(mailbox.settings, 'MS_MAIL_TOKEN_KEY_FILE', str(path))
        patched.start()
        self.addCleanup(patched.stop)

    async def test_graph_preview_only_reads_inbox_and_categories_with_pagination(self):
        requests = []
        def handle(request):
            requests.append(request)
            self.assertEqual(request.method, "GET")
            if request.url.path.endswith("/messages"):
                self.assertIn("/inbox/", request.url.path)
                self.assertEqual(request.url.params["$top"], "10")
                return httpx.Response(200, json={"value": [{"id": "m1", "subject": "TT", "categories": ["TT", "Pagesa"], "bodyPreview": "<script>bad()</script>", "isRead": False, "from": {"emailAddress": {"address": "client@example.com"}}}]})
            if "page=2" in str(request.url):
                return httpx.Response(200, json={"value": [{"id": "c2", "displayName": "Pagesa"}]})
            return httpx.Response(200, json={"value": [{"id": "c1", "displayName": "TT"}], "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/outlook/masterCategories?page=2"})
        real_client = httpx.AsyncClient
        with patch.object(graph.httpx, "AsyncClient", side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw)):
            result = await graph.fetch_mail_preview("secret")
        self.assertEqual(len(requests), 3)
        self.assertEqual([c["name"] for c in result["categories"]], ["TT", "Pagesa"])
        self.assertFalse(result["messages"][0]["is_read"])
        self.assertEqual(result["messages"][0]["categories"], ["TT", "Pagesa"])

    async def test_refresh_retains_read_scopes_and_encrypts_rotated_tokens(self):
        db = AsyncMock()
        row = SimpleNamespace(scope=SCOPE, refresh_token_encrypted=graph.encrypt_token("old-refresh"))
        with patch.object(mailbox, "mail_token_request", new=AsyncMock(return_value={"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600})) as exchange:
            await mailbox.refresh_mailbox(db, row, "https://primeflow.test/api/mailbox/callback")
        self.assertEqual(graph.decrypt_token(row.access_token_encrypted), "new-access")
        self.assertEqual(graph.decrypt_token(row.refresh_token_encrypted), "new-refresh")
        self.assertEqual(row.scope, SCOPE)
        self.assertEqual(exchange.await_args.kwargs["refresh_token"], "old-refresh")
        db.commit.assert_awaited_once()

    async def test_read_test_refreshes_once_on_401_and_records_success(self):
        db = AsyncMock()
        row = SimpleNamespace(scope=SCOPE, expires_at=datetime.now(timezone.utc) + timedelta(hours=1), access_token_encrypted=graph.encrypt_token("access"))
        db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: row)
        error = httpx.HTTPStatusError("expired", request=httpx.Request("GET", "https://graph.microsoft.com"), response=httpx.Response(401))
        with patch.object(mailbox, "fetch_mail_preview", new=AsyncMock(side_effect=[error, {"messages": [], "categories": []}])) as read, patch.object(mailbox, "refresh_mailbox", new=AsyncMock()) as refresh:
            request = SimpleNamespace(base_url="https://primeflow.test/")
            result = await mailbox.test_connection(request, Response(), user=None, db=db)
        self.assertEqual(result["messages"], [])
        self.assertEqual(read.await_count, 2)
        refresh.assert_awaited_once()
        self.assertIsNotNone(row.last_checked_at)

    async def test_failed_graph_read_does_not_record_verified_connection(self):
        db = AsyncMock()
        row = SimpleNamespace(scope=SCOPE, expires_at=datetime.now(timezone.utc) + timedelta(hours=1), access_token_encrypted=graph.encrypt_token('access'), last_checked_at=None)
        db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: row)
        denied = httpx.HTTPStatusError('denied', request=httpx.Request('GET', 'https://graph.microsoft.com'), response=httpx.Response(403))
        with patch.object(mailbox, 'fetch_mail_preview', new=AsyncMock(side_effect=denied)):
            with self.assertRaises(HTTPException) as error:
                await mailbox.test_connection(SimpleNamespace(base_url='https://primeflow.test/'), Response(), user=None, db=db)
        self.assertEqual(error.exception.status_code, 409)
        self.assertIsNone(row.last_checked_at)
        db.commit.assert_not_awaited()

    async def test_untrusted_pagination_never_receives_access_token(self):
        requests = []
        def handle(request):
            requests.append(str(request.url))
            return httpx.Response(200, json={"value": [], "@odata.nextLink": "https://evil.example/categories"})
        real_client = httpx.AsyncClient
        with patch.object(graph.httpx, "AsyncClient", side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw)):
            with self.assertRaises(ValueError):
                await graph.fetch_mail_preview("secret")
        self.assertTrue(all(url.startswith("https://graph.microsoft.com/") for url in requests))


class MailboxKeyProvisionTests(unittest.TestCase):
    def test_provisioning_never_replaces_an_existing_key(self):
        from scripts.init_mailbox_token_key import provision_key
        with tempfile.TemporaryDirectory() as directory, patch('scripts.init_mailbox_token_key.subprocess.run'):
            path = Path(directory) / 'mailbox' / 'token.key'
            self.assertTrue(provision_key(path))
            original = path.read_bytes()
            self.assertFalse(provision_key(path))
            self.assertEqual(path.read_bytes(), original)
            Fernet(original.strip())
