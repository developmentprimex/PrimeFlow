import os
import asyncio
import base64
import json
import re
import time
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
import asyncpg
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from app.services.ga_note_task import ga_note_default_task_description, ga_note_task_title


ENV_FILE = Path(__file__).resolve().with_name(".env")
load_dotenv(ENV_FILE, override=False)

API_BASE_URL = os.getenv("PRIMEFLOW_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
WEB_BASE_URL = os.getenv("PRIMEFLOW_WEB_BASE_URL", "http://127.0.0.1:3000").rstrip("/")
ACCESS_TOKEN = os.getenv("PRIMEFLOW_ACCESS_TOKEN")
READONLY_DATABASE_URL = os.getenv("PRIMEFLOW_READONLY_DATABASE_URL")
REQUEST_TIMEOUT = float(os.getenv("PRIMEFLOW_MCP_TIMEOUT", "30"))
MCP_HOST = os.getenv("PRIMEFLOW_MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.getenv("PRIMEFLOW_MCP_PORT", "8010"))
APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Europe/Budapest")
_token_cache: dict[str, Any] = {"access_token": ACCESS_TOKEN, "expires_at": 0}
_lookup_cache: dict[str, dict[str, Any]] = {}
LOOKUP_CACHE_SECONDS = 60

PRIMEFLOW_GUIDE = """
Primeflow is an internal task, project, planning, reporting, and operations system.

Use the specific MCP tools first for common work. Use primeflow_api_request only when a specific tool does not cover the request.
All API calls go through the existing Primeflow FastAPI backend and use the configured service account, so backend permissions still apply.

Core language and business rules:
- "1H" means a Primeflow 1H report task. It is not a request to set the deadline one hour from now. Set is_1h_report=true.
- 1H slots, when requested, use one_h_report_slot values: 10:00, 11:00, 11:50, 14:20, 16:00.
- After the app's slot rollover time, Primeflow may apply 1H slot work to the next effective workday. Let the backend enforce this.
- Initials such as LH should be resolved to users before assignment. LH normally means Laurent Hoxha if that is the unique matching user.
- For task assignment, prefer assignee_name or assignee_ids in MCP tools. The MCP server resolves names/initials and sends assignees=[user_id] plus assigned_to.
- Status values commonly include TODO, IN_PROGRESS, PAUSED, WAITING_CONFIRMATION, DONE, and related backend enum values.
- Priority values commonly include NORMAL and HIGH.
- Dates should be ISO strings. For day filters, use local-day bounds such as 2026-07-09T00:00:00+02:00 to 2026-07-10T00:00:00+02:00.
- Albanian time words: sot=today, neser/nesër=tomorrow, dje=yesterday, kete jave/këtë javë=current week, and javen tjeter/javën tjetër=next week.
- Task type codes (badges): BLL=blocked task (is_bllok), R1 (is_r1), 1H=1H report task (is_1h_report), GA=created from a GA/KA note (ga_note_origin_id), P=personal task (is_personal). "Detyrat 1H" means tasks with is_1h_report=true, "detyrat P" means personal tasks.
- Control persons on a task: control 1 = the confirmer (confirmation_assignee_id), control 2 = the alignment users (alignment_user_ids). In VS/VL project workflows these correspond to the KO1/KO2 control steps.
- Task steps live in checklists attached to the task; per-day scheduling uses start_date/due_date, finish_period (AM/PM), and the 1H slot.

Major modules:
- Auth: login, refresh, logout, and /api/auth/me. MCP handles login internally with the configured service account.
- Users: list users, lookup users, create/update/deactivate users where permitted. Use list_users or resolve_user before assigning by name.
- Departments and boards: departments group work areas such as Development, Graphic Design, Finance, HR, PCM, GA/KA. Boards support department kanban views.
- Tasks: primary work item. Tasks have title, description, internal_notes, project_id, department_id, assigned_to, assignees, status, priority, phase, progress, start_date, due_date, completed_at, is_1h_report, one_h_report_slot, is_bllok, is_r1, is_personal, and related planner fields.
- Projects: grouped work with current_phase, status, manager, department, project_type, total_products, templates, workflow items, phase advancement, close/remove-from-day operations.
- Common View: operational cross-department view built from common entries and task/project signals. It includes common entries, approval/rejection, assignment, leave/block rows, bllok tasks, personal/R1/1H/common orderable tasks, and consolidated planning visibility.
- Weekly Planner: weekly and weekly-table endpoints show planned work by user/day/slot, support save-day, user ordering, user visibility, snapshots, plan-vs-actual, plan-vs-final, comparison, latest snapshot, overview, and legend rows.
- Realization: deterministic weekly PLANNED-vs-FINAL evidence, policy-based suggestions, observations, manager review, admin approval, and locking. Use Realization tools instead of calculating grades in the model.
- Monthly Planner: monthly planning endpoint for larger time windows.
- System Tasks: recurring/system templates, approvals, rejections, occurrence generation, occurrence date changes, and generated task visibility.
- GA notes and Plan notes: notes with attachments, discussed/done fields, task conversion, task deadlines, waiting confirmation handling, and public GA notes.
- GA time slots/table: GA time table rows, slot entries, and time-based reporting.
- Meetings: meetings, external/internal meeting flows, triggered system tasks, meeting templates/exports.
- Internal notes and internal meeting sessions: internal note creation, grouped updates, done state, cleanup/session handling.
- Checklists and checklist items: reusable checklists, project phase checklist items, checklist item editing/deletion, import/export support.
- Reports and exports: daily reports, GA daily table, XLSX/CSV/PDF exports for tasks, weekly planner, common view, snapshots, system tasks, GA notes, meetings, checklists, and daily reports.
- File access: maps users, lists folders/access, creates/approves/rejects file access requests, removes access where permitted.
- Microsoft integration: authorization URL, callback, status, disconnect, calendar events.
- Notifications and audit logs: user notifications, read/delete operations, audit history.
- External platform links and project prompts: platform references and prompt/config records for project workflows.

Endpoint guidance:
- Use /openapi.json or list_api_endpoints to discover exact routes and schemas.
- Use GET endpoints for lookup/reporting before mutating.
- Use POST/PATCH/PUT only when the user clearly asks to create, update, approve, reject, save, or generate.
- Use DELETE only when the user explicitly asks to delete/deactivate/remove and the target ID is clear.
- Never invent UUIDs. Resolve names with list_users, resolve_user, list_projects, or relevant lookup endpoints.
- For "what tasks does X have today / unfinished today", use get_user_tasks_for_day or get_user_unfinished_tasks_today. Do not manually filter by assignee name.
- When the user supplies names instead of IDs, pass those names to the dedicated *_ref or *_name arguments. The MCP server resolves them. Do not call list_users/list_departments first unless resolution is ambiguous.
- For meetings in a week, use get_common_view_meetings_for_week. Set week=current or week=next instead of calculating dates yourself.
- For GA/KA note creation, use create_ga_note. note_type must be GA or KA. priority, when provided, must be NORMAL or HIGH.
- To create a task from an existing GA/KA note, always use create_task_from_ga_note instead of create_task. It keeps ga_note_origin_id linked to the source note, uses the note title/content, and marks the note as converted only after task creation succeeds.
- Use create_meeting, create_plan_note, create_internal_note, and create_common_entry for those actions instead of primeflow_api_request.
- After a successful write tool call, report the returned object and ID. Do not repeat a create call merely because a later read does not immediately show it.
- Tool selection map for common questions:
  - "detyrat per sot / detyrat 1H per sot per te gjithe" -> get_tasks_today (task_type="1H" for 1H tasks only).
  - "detyrat e kesaj jave / javes tjeter" -> get_tasks_this_week with week=current or next.
  - "te gjitha detyrat e hapura per secilin person" -> get_all_open_tasks_by_person.
  - "detyrat me vonese / te pakryera" -> get_overdue_tasks.
  - Weekly plan: get_weekly_plan to read, save_weekly_plan to draft/save, get_plan_vs_actual to compare plan with reality.
  - "me ndihmo te bej planin e javes tjeter" -> call prepare_next_week_plan first, draft the plan from its data, then save with save_weekly_plan.
  - "kush e ka kontrollin / kush e konfirmon" -> get_task_people (control 1 and control 2).
  - Workload of one person -> get_person_workload. Whole department -> get_department_overview.
  - Task steps -> get_task_steps, add_task_step, set_task_step_done. Scheduling a task to days/slots -> schedule_task.
  - Weekly summary report -> get_weekly_report. Excel/PDF downloads -> export_report.
  - Weekly Realization -> get_weekly_realization first; calculate_weekly_realization only on explicit request; review/approve/lock with the dedicated workflow tools.
- Database read-only tools are for schema understanding, relationship discovery, debugging, and simple analytics only. Use API tools for writes and Primeflow business logic.
- run_readonly_sql allows only SELECT/WITH statements and runs in a read-only transaction. Never use database tools for create/update/delete actions.
"""

# ---------------------------------------------------------------- profiles
#
# "full" (default): the historical server used by the primeflow-mcp process on
#   8010 - every tool, SSE, one shared service account. Unchanged.
# "assistant": the remote GA assistant connector - Streamable HTTP on /mcp, OAuth
#   bearer tokens per user, only ASSISTANT_TOOLS, and every API call is made as
#   the token's user (created_by / audit_logs record that user).
MCP_PROFILE = os.getenv("PRIMEFLOW_MCP_PROFILE", "full").strip().lower() or "full"
if MCP_PROFILE not in {"full", "assistant"}:
    raise RuntimeError("PRIMEFLOW_MCP_PROFILE must be 'full' or 'assistant'")
IS_ASSISTANT = MCP_PROFILE == "assistant"
ALLOW_DELETE = os.getenv("PRIMEFLOW_MCP_ALLOW_DELETE", "false").strip().lower() in {"1", "true", "yes"}
MCP_INTERNAL_SECRET = os.getenv("MCP_ASSISTANT_INTERNAL_SECRET", "")
MCP_RESOURCE_URL = os.getenv("MCP_ASSISTANT_RESOURCE_URL", "https://mcp-flow.primexeu.com/mcp")
OAUTH_ISSUER_URL = os.getenv("OAUTH_ISSUER_URL", "https://api-flow.primexeu.com")

# Tools exposed by the assistant profile (existing tools + the GA assistant tools).
ASSISTANT_TOOLS = frozenset({
    "primeflow_me", "primeflow_context", "health_check", "list_users", "resolve_user", "list_projects",
    "get_project", "resolve_project", "list_tasks", "get_task", "get_task_people", "get_task_steps",
    "get_tasks_today", "get_overdue_tasks", "get_user_tasks_for_day", "get_user_unfinished_tasks_today",
    "list_meetings", "get_common_view_meetings_for_week", "get_daily_ga_table", "list_ga_notes",
    "create_ga_note", "update_ga_note", "create_task", "update_task", "schedule_task", "add_task_step",
    "set_task_step_done", "search_primeflow", "search", "fetch",
    "ga_agenda", "ga_leftovers", "ga_untimed_today", "ga_item_done", "ga_item_postpone", "ga_item_set_time",
    "ga_item_remove_from_day", "ga_add_comment",
    "todo_list", "todo_create", "todo_update", "todo_complete", "todo_set_steps",
    "ga_time_table", "ga_discord_mentions", "ga_discord_mark",
})
# Tools that exist only in the assistant profile; the full profile stays as it was.
ASSISTANT_ONLY_TOOLS = frozenset({
    "ga_agenda", "ga_leftovers", "ga_untimed_today", "ga_item_done", "ga_item_postpone", "ga_item_set_time",
    "ga_item_remove_from_day", "ga_add_comment",
    "todo_list", "todo_create", "todo_update", "todo_complete", "todo_set_steps",
    "ga_time_table", "ga_discord_mentions", "ga_discord_mark",
})
# Existing allowlisted tools that change data (everything else allowlisted only reads).
ASSISTANT_WRITE_TOOLS = frozenset({
    "create_ga_note", "update_ga_note", "create_task", "update_task", "schedule_task", "add_task_step", "set_task_step_done",
})


def _assistant_auth_kwargs() -> dict[str, Any]:
    """FastMCP kwargs that turn the server into an OAuth-protected resource server."""
    try:
        from mcp.server.auth.provider import AccessToken
        from mcp.server.auth.settings import AuthSettings
        from mcp.server.transport_security import TransportSecuritySettings
    except ImportError as exc:  # pragma: no cover - depends on the installed SDK
        raise RuntimeError(
            "The assistant profile needs the newer MCP SDK from requirements-mcp-assistant.txt."
        ) from exc
    if "subject" not in AccessToken.model_fields:  # pragma: no cover - SDK guard
        raise RuntimeError(
            "The assistant profile needs the newer MCP SDK from requirements-mcp-assistant.txt "
            "(run it with backend/.venv-mcp-assistant)."
        )
    import hashlib
    from urllib.parse import urlsplit

    class PrimeflowAccessToken(AccessToken):
        api_token: str = ""
        api_token_expires_at: float = 0.0
        email: str | None = None

    class PrimeflowTokenVerifier:
        """Validates assistant tokens with the PrimeFlow OAuth server (internal endpoint)."""

        def __init__(self) -> None:
            self._cache: dict[str, PrimeflowAccessToken] = {}

        def invalidate(self, token: str) -> None:
            self._cache.pop(hashlib.sha256(token.encode("utf-8")).hexdigest(), None)

        async def verify_token(self, token: str) -> AccessToken | None:
            key = hashlib.sha256(token.encode("utf-8")).hexdigest()
            cached = self._cache.get(key)
            now = time.time()
            # Re-validate well before the 15-minute PrimeFlow JWT expires, so a tool call
            # never starts with a JWT that can lapse while it runs.
            if cached is not None and cached.api_token_expires_at - 120 > now and (cached.expires_at or 0) > now:
                return cached
            if not MCP_INTERNAL_SECRET:
                print("MCP assistant: MCP_ASSISTANT_INTERNAL_SECRET is not set; rejecting tokens")
                return None
            try:
                async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=REQUEST_TIMEOUT) as client:
                    response = await client.post(
                        "/api/oauth/internal/session",
                        json={"token": token},
                        headers={"X-MCP-Internal-Secret": MCP_INTERNAL_SECRET},
                    )
            except httpx.HTTPError as exc:
                print(f"MCP assistant: token validation unreachable: {type(exc).__name__}")
                return None
            if response.status_code != 200:
                print(f"MCP assistant: token validation returned HTTP {response.status_code}")
                return None
            data = response.json()
            if not data.get("active"):
                self._cache.pop(key, None)
                return None
            verified = PrimeflowAccessToken(
                token=token,
                client_id=str(data.get("client_id") or ""),
                scopes=str(data.get("scope") or "").split(),
                expires_at=int(data.get("exp") or 0),
                resource=data.get("resource"),
                subject=str(data.get("sub") or ""),
                api_token=str(data.get("primeflow_access_token") or ""),
                api_token_expires_at=now + float(data.get("primeflow_access_token_expires_in") or 0),
                email=data.get("email"),
            )
            if len(self._cache) > 500:
                self._cache.clear()
            self._cache[key] = verified
            return verified

    global ASSISTANT_VERIFIER
    ASSISTANT_VERIFIER = PrimeflowTokenVerifier()
    public_host = urlsplit(MCP_RESOURCE_URL).netloc
    allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"] + ([public_host] if public_host else [])
    allowed_origins = ["http://127.0.0.1:*", "http://localhost:*", "https://claude.ai"]
    return {
        "token_verifier": ASSISTANT_VERIFIER,
        "auth": AuthSettings(
            issuer_url=OAUTH_ISSUER_URL,
            resource_server_url=MCP_RESOURCE_URL,
            required_scopes=["primeflow"],
        ),
        "transport_security": TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        ),
        "streamable_http_path": "/mcp",
    }


ASSISTANT_VERIFIER: Any = None

if IS_ASSISTANT:
    mcp = FastMCP("primeflow-assistant", instructions=PRIMEFLOW_GUIDE, host=MCP_HOST, port=MCP_PORT, **_assistant_auth_kwargs())
else:
    mcp = FastMCP("primeflow", instructions=PRIMEFLOW_GUIDE, host=MCP_HOST, port=MCP_PORT)


def _tool(name: str | None = None, *, read_only: bool | None = None, destructive: bool | None = None, idempotent: bool | None = None):
    """Register a tool for the active profile.

    full profile: identical to ``@mcp.tool(name=...)`` for every pre-existing tool;
    assistant-only tools are skipped. assistant profile: only ASSISTANT_TOOLS, with
    MCP tool annotations (readOnlyHint / destructiveHint).
    """

    def decorator(fn):
        tool_name = name or fn.__name__
        if not IS_ASSISTANT:
            if tool_name in ASSISTANT_ONLY_TOOLS:
                return fn
            return mcp.tool(name=name)(fn) if name else mcp.tool()(fn)
        if tool_name not in ASSISTANT_TOOLS:
            return fn
        from mcp.types import ToolAnnotations

        is_read_only = read_only if read_only is not None else tool_name not in ASSISTANT_WRITE_TOOLS
        annotations = ToolAnnotations(
            readOnlyHint=is_read_only,
            destructiveHint=bool(destructive) if not is_read_only else None,
            idempotentHint=idempotent,
            openWorldHint=False,
        )
        return mcp.tool(name=name, annotations=annotations)(fn)

    return decorator

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
FORBIDDEN_SQL_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|copy|execute|call|merge|"
    r"refresh|vacuum|analyze|reindex|cluster|comment|security|set|reset|listen|notify)\b",
    re.IGNORECASE,
)


def _jwt_exp(token: str) -> int:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return int(json.loads(base64.urlsafe_b64decode(payload.encode("ascii"))).get("exp", 0))
    except Exception:
        return 0


def _caller_access() -> Any:
    """The verified OAuth token the assistant session was opened with (identity only).

    With Streamable HTTP the tool handlers run inside the session task, so this
    context value belongs to the request that *opened* the session. It identifies the
    user, but its PrimeFlow JWT may be stale: API calls use _current_access() instead.
    """
    from mcp.server.auth.middleware.auth_context import get_access_token

    access = get_access_token()
    if access is None or not getattr(access, "api_token", ""):
        raise RuntimeError("This assistant request is not authenticated.")
    return access


def _current_bearer() -> str | None:
    """Bearer token of the HTTP request that carried the current MCP message."""
    try:
        request = mcp._mcp_server.request_context.request  # noqa: SLF001 - per-message HTTP request
    except (LookupError, AttributeError):
        return None
    header = str(getattr(request, "headers", {}).get("authorization") or "")
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


async def _current_access(*, force: bool = False) -> Any:
    """Verified access for *this* message, with a PrimeFlow JWT that is still valid.

    Uses the current request's OAuth token (Claude refreshes it over time) and asks the
    verifier, which mints a fresh 15-minute PrimeFlow JWT whenever the cached one is
    close to expiry. force=True drops the cache first (after an API 401).
    """
    token = _current_bearer()
    if token is None:
        context_access = _caller_access()
        # No HTTP request for this message (e.g. in-process calls): the context token is
        # fine while its JWT is still valid; otherwise re-validate it below.
        if not force and float(getattr(context_access, "api_token_expires_at", 0) or 0) - 120 > time.time():
            return context_access
        token = getattr(context_access, "token", None)
    if not token or ASSISTANT_VERIFIER is None:
        return _caller_access()
    if force:
        ASSISTANT_VERIFIER.invalidate(token)
    access = await ASSISTANT_VERIFIER.verify_token(token)
    if access is None or not getattr(access, "api_token", ""):
        raise RuntimeError("The PrimeFlow sign-in of this connector has expired; reconnect PrimeFlow in Claude.")
    return access


def _cache_scope() -> str:
    """Lookup caches are per user in the assistant profile (visibility differs by role)."""
    if not IS_ASSISTANT:
        return ""
    try:
        return f"{_caller_access().subject}:"
    except RuntimeError:
        return "anonymous:"


async def _access_token(*, force_refresh: bool = False) -> str:
    if IS_ASSISTANT:
        # Never the shared service account: act as the user who authorized the connector,
        # with a JWT that is fresh for this message (see _current_access). force_refresh is
        # per call (after a 401), so parallel tool calls never consume each other's retry.
        return str((await _current_access(force=force_refresh)).api_token)
    cached_token = str(_token_cache.get("access_token") or "")
    cached_exp = int(_token_cache.get("expires_at") or 0)
    if cached_token and cached_exp > int(time.time()) + 30:
        return cached_token

    primeflow_email = os.getenv("PRIMEFLOW_EMAIL")
    primeflow_password = os.getenv("PRIMEFLOW_PASSWORD")
    if primeflow_email and primeflow_password:
        async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=REQUEST_TIMEOUT) as client:
            response = await client.post(
                "/api/auth/login",
                json={"email": primeflow_email, "password": primeflow_password},
            )
        response.raise_for_status()
        token = response.json()["access_token"]
        _token_cache["access_token"] = token
        _token_cache["expires_at"] = _jwt_exp(token)
        return token

    if ACCESS_TOKEN:
        _token_cache["access_token"] = ACCESS_TOKEN
        _token_cache["expires_at"] = _jwt_exp(ACCESS_TOKEN)
        return ACCESS_TOKEN

    raise RuntimeError(
        "Set PRIMEFLOW_EMAIL and PRIMEFLOW_PASSWORD, or set PRIMEFLOW_ACCESS_TOKEN for short local tests."
    )


async def _headers(*, force_refresh: bool = False) -> dict[str, str]:
    token = await _access_token(force_refresh=force_refresh)
    if not token:
        raise RuntimeError(
            "PRIMEFLOW_ACCESS_TOKEN is not set. Log in to Primeflow and provide a valid API access token."
        )
    return {"Authorization": f"Bearer {token}"}


def _api_error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
        if isinstance(body, dict):
            detail = body.get("detail") or body.get("message") or body.get("error")
            if detail:
                return json.dumps(detail, ensure_ascii=False) if not isinstance(detail, str) else detail
        return json.dumps(body, ensure_ascii=False)[:2000]
    except Exception:
        return response.text.strip()[:2000] or response.reason_phrase


async def _request(method: str, path: str, *, params: dict[str, Any] | None = None, json: Any = None) -> Any:
    clean_params = {key: value for key, value in (params or {}).items() if value is not None}
    response: httpx.Response | None = None
    transient = {429, 500, 502, 503, 504}
    delays = (0, 2, 5)
    refreshed = False
    force_refresh = False
    last_error: Exception | None = None
    for attempt, delay in enumerate(delays, 1):
        if delay and not force_refresh:
            await asyncio.sleep(delay)
        try:
            headers = await _headers(force_refresh=force_refresh)
            force_refresh = False
            async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=REQUEST_TIMEOUT, headers=headers) as client:
                response = await client.request(method, path, params=clean_params, json=json)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
            last_error = exc
            print(f"Primeflow API transient failure method={method.upper()} path={path} attempt={attempt}")
            continue
        if response.status_code == 401 and not refreshed:
            refreshed = True
            _token_cache["access_token"] = None
            _token_cache["expires_at"] = 0
            if IS_ASSISTANT:
                # Mint a new PrimeFlow JWT for this user and retry at once.
                print(f"MCP assistant: API 401 on {method.upper()} {path}; re-validating the connector token and retrying")
                force_refresh = True
            continue
        if response.status_code not in transient:
            break
        print(f"Primeflow API transient HTTP status={response.status_code} method={method.upper()} path={path} attempt={attempt}")
    if response is None:
        raise RuntimeError(f"Primeflow API is unreachable for {method.upper()} {path} after 3 attempts: {type(last_error).__name__}") from last_error
    assert response is not None
    if response.is_error:
        detail = _api_error_detail(response)
        raise RuntimeError(f"Primeflow API {method.upper()} {path} failed ({response.status_code}): {detail}")
    if response.status_code == 204 or not response.content:
        return {"status": "ok"}
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"Primeflow API {method.upper()} {path} returned non-JSON content ({response.headers.get('content-type', 'unknown')})."
        ) from exc


def _validate_startup_configuration() -> None:
    missing = []
    if not API_BASE_URL:
        missing.append("PRIMEFLOW_API_BASE_URL")
    if IS_ASSISTANT:
        # The assistant never uses the shared service account; it needs the OAuth wiring instead.
        if not MCP_INTERNAL_SECRET:
            missing.append("MCP_ASSISTANT_INTERNAL_SECRET")
        if not MCP_RESOURCE_URL:
            missing.append("MCP_ASSISTANT_RESOURCE_URL")
    elif not (ACCESS_TOKEN or (os.getenv("PRIMEFLOW_EMAIL") and os.getenv("PRIMEFLOW_PASSWORD"))):
        missing.append("PRIMEFLOW_EMAIL/PRIMEFLOW_PASSWORD or PRIMEFLOW_ACCESS_TOKEN")
    if not MCP_HOST:
        missing.append("PRIMEFLOW_MCP_HOST")
    if not MCP_PORT:
        missing.append("PRIMEFLOW_MCP_PORT")
    if missing:
        raise RuntimeError("Missing MCP configuration: " + ", ".join(missing))


def _db_url() -> str:
    if not READONLY_DATABASE_URL:
        raise RuntimeError(
            "PRIMEFLOW_READONLY_DATABASE_URL is not set. Configure a PostgreSQL read-only user before using DB tools."
        )
    return READONLY_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)


def _validate_readonly_sql(sql: str) -> str:
    statement = sql.strip()
    if not statement:
        raise ValueError("SQL query is required.")
    if ";" in statement.rstrip(";"):
        raise ValueError("Only one SQL statement is allowed.")
    statement = statement.rstrip(";").strip()
    lowered = statement.lower()
    if not (lowered.startswith("select ") or lowered.startswith("with ")):
        raise ValueError("Only SELECT or WITH read-only queries are allowed.")
    if FORBIDDEN_SQL_RE.search(statement):
        raise ValueError("This SQL contains a forbidden non-read-only keyword.")
    return statement


def _quote_ident(value: str) -> str:
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", value):
        raise ValueError(f"Invalid SQL identifier: {value}")
    return f'"{value}"'


async def _db_fetch(sql: str, *args: Any) -> list[dict[str, Any]]:
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction(readonly=True):
            rows = await conn.fetch(sql, *args)
            return [dict(row) for row in rows]
    finally:
        await conn.close()


def _parse_json_arg(value: str | None, *, default: Any) -> Any:
    if value is None or value.strip() == "":
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Expected valid JSON, got: {value}") from exc


def _normalize_api_path(path: str) -> str:
    value = path.strip()
    if not value:
        raise ValueError("API path is required.")
    if value.startswith("http://") or value.startswith("https://"):
        raise ValueError("Use a relative Primeflow path, not a full URL.")
    if value in {"/health", "health", "/openapi.json", "openapi.json"}:
        return value if value.startswith("/") else f"/{value}"
    if value.startswith("/api/"):
        return value
    if value.startswith("api/"):
        return f"/{value}"
    return f"/api/{value.lstrip('/')}"


def _frontend_url(path: str) -> str:
    return urljoin(f"{WEB_BASE_URL}/", path.lstrip("/"))


def _local_tz() -> ZoneInfo | timezone:
    try:
        return ZoneInfo(APP_TIMEZONE)
    except Exception:
        return timezone.utc


def _parse_day(value: str | None) -> date:
    today = datetime.now(_local_tz()).date()
    if not value:
        return today
    normalized = value.strip().lower()
    relative_days = {
        "today": 0,
        "sot": 0,
        "tomorrow": 1,
        "neser": 1,
        "nesër": 1,
        "yesterday": -1,
        "dje": -1,
    }
    if normalized in relative_days:
        return today + timedelta(days=relative_days[normalized])
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("day_date must be YYYY-MM-DD, today/sot, tomorrow/neser, or yesterday/dje") from exc


def _day_bounds(value: str | None) -> tuple[str, str, str]:
    day = _parse_day(value)
    tz = _local_tz()
    start = datetime.combine(day, datetime_time.min, tzinfo=tz)
    # Primeflow's task window filters compare local dates inclusively. Keep the
    # upper bound inside the requested day so tomorrow's tasks are not included.
    end = start + timedelta(days=1) - timedelta(microseconds=1)
    return day.isoformat(), start.isoformat(), end.isoformat()


def _week_start(value: str | None = None, week: str = "current") -> str:
    if value:
        requested = _parse_day(value)
        return (requested - timedelta(days=requested.weekday())).isoformat()
    today = datetime.now(_local_tz()).date()
    monday = today - timedelta(days=today.weekday())
    normalized = week.strip().lower()
    if normalized in {"next", "next_week", "javen tjeter", "javën tjetër"}:
        monday += timedelta(days=7)
    elif normalized not in {"current", "this", "this_week", "kete jave", "këtë javë"}:
        raise ValueError("week must be current or next, or provide week_start as YYYY-MM-DD")
    return monday.isoformat()


async def _cached_lookup(key: str, path: str) -> list[dict[str, Any]]:
    key = f"{_cache_scope()}{key}"
    now = time.monotonic()
    cached = _lookup_cache.get(key)
    if cached and float(cached.get("expires_at") or 0) > now:
        return cached["value"]
    value = await _request("GET", path)
    if not isinstance(value, list):
        raise RuntimeError(f"Primeflow lookup {path} returned an unexpected response.")
    _lookup_cache[key] = {"value": value, "expires_at": now + LOOKUP_CACHE_SECONDS}
    return value


def _user_initials(user: dict[str, Any]) -> str:
    full_name = str(user.get("full_name") or "").strip()
    if full_name:
        parts = [part for part in re.split(r"\s+", full_name) if part]
        return "".join(part[0] for part in parts).upper()
    username = str(user.get("username") or "").strip()
    return "".join(part[0] for part in re.split(r"[\s._-]+", username) if part).upper()


def _user_search_text(user: dict[str, Any]) -> str:
    return " ".join(
        str(user.get(key) or "").lower()
        for key in ("full_name", "username", "email")
    )


async def _resolve_user_id(user_ref: str | None, department_ref: str | None = None) -> str | None:
    if not user_ref:
        return None
    value = user_ref.strip()
    if not value:
        return None
    if UUID_RE.match(value):
        return value

    users = await _cached_lookup("users", "/api/users")
    if department_ref:
        department_id = await _resolve_department_id(department_ref)
        users = [user for user in users if str(user.get("department_id")) == department_id]
    query = value.lower()
    query_initials = value.replace(".", "").replace(" ", "").upper()

    exact_matches = [
        user for user in users
        if query in {
            str(user.get("full_name") or "").lower(),
            str(user.get("username") or "").lower(),
            str(user.get("email") or "").lower(),
        }
    ]
    if len(exact_matches) == 1:
        return str(exact_matches[0]["id"])

    initials_matches = [user for user in users if _user_initials(user) == query_initials]
    if len(initials_matches) == 1:
        return str(initials_matches[0]["id"])

    contains_matches = [user for user in users if query in _user_search_text(user)]
    if len(contains_matches) == 1:
        return str(contains_matches[0]["id"])

    if not exact_matches and not initials_matches and not contains_matches:
        raise ValueError(f"No Primeflow user matched '{user_ref}'. Use list_users to inspect users.")

    candidates = exact_matches or initials_matches or contains_matches
    names = ", ".join(
        f"{user.get('full_name') or user.get('username')} ({user.get('id')})"
        for user in candidates[:10]
    )
    raise ValueError(f"Ambiguous Primeflow user '{user_ref}'. Matching candidates: {names}")


async def _resolve_department_id(department_ref: str | None) -> str | None:
    if not department_ref:
        return None
    value = department_ref.strip()
    if not value:
        return None
    if UUID_RE.match(value):
        return value

    departments = await _cached_lookup("departments", "/api/departments")
    query = value.lower()
    exact_matches = [
        dept for dept in departments
        if query in {
            str(dept.get("name") or "").lower(),
            str(dept.get("code") or "").lower(),
            str(dept.get("slug") or "").lower(),
        }
    ]
    if len(exact_matches) == 1:
        return str(exact_matches[0]["id"])

    contains_matches = [
        dept for dept in departments
        if query in " ".join(str(dept.get(key) or "").lower() for key in ("name", "code", "slug"))
    ]
    if len(contains_matches) == 1:
        return str(contains_matches[0]["id"])

    candidates = exact_matches or contains_matches
    if not candidates:
        raise ValueError(f"No Primeflow department matched '{department_ref}'. Use list_departments to inspect departments.")
    names = ", ".join(
        f"{dept.get('name') or dept.get('code')} ({dept.get('id')})"
        for dept in candidates[:10]
    )
    raise ValueError(f"Ambiguous Primeflow department '{department_ref}'. Matching candidates: {names}")


async def _resolve_project_id(project_ref: str | None, department_ref: str | None = None) -> str | None:
    if not project_ref:
        return None
    value = project_ref.strip()
    if not value:
        return None
    if UUID_RE.match(value):
        return value

    projects = await _cached_lookup("projects", "/api/projects")
    if department_ref:
        department_id = await _resolve_department_id(department_ref)
        projects = [project for project in projects if str(project.get("department_id")) == department_id]
    query = value.casefold()

    def titles(project: dict[str, Any]) -> set[str]:
        return {
            str(project.get("title") or "").strip().casefold(),
            str(project.get("display_title") or "").strip().casefold(),
        }

    exact = [project for project in projects if query in titles(project)]
    if len(exact) == 1:
        return str(exact[0]["id"])
    contains = [project for project in projects if any(query in title for title in titles(project) if title)]
    if len(contains) == 1:
        return str(contains[0]["id"])
    candidates = exact or contains
    if not candidates:
        raise ValueError(f"No Primeflow project matched '{project_ref}'. Use list_projects to inspect projects.")
    names = ", ".join(
        f"{project.get('display_title') or project.get('title')} ({project.get('id')})"
        for project in candidates[:10]
    )
    raise ValueError(f"Ambiguous Primeflow project '{project_ref}'. Matching candidates: {names}")


ONE_H_SLOTS = {"10:00", "11:00", "11:50", "14:20", "16:00"}
TASK_TYPE_ALIASES = {
    "1H": "1H",
    "P": "P",
    "P:": "P",
    "PERSONAL": "P",
    "BLL": "BLL",
    "BLLOK": "BLL",
    "R1": "R1",
    "GA": "GA",
}


def _normalize_task_type(task_type: str | None) -> str | None:
    if not task_type:
        return None
    value = task_type.strip().upper().rstrip(":") or None
    if value in {None, "ALL"}:
        return None
    normalized = TASK_TYPE_ALIASES.get(value) or TASK_TYPE_ALIASES.get(f"{value}:")
    if not normalized:
        raise ValueError("task_type must be one of 1H, P, BLL, R1, GA, or ALL")
    return normalized


def _task_type_code(task: dict[str, Any]) -> str | None:
    # Mirrors get_fast_task_type in app/api/routers/planners.py.
    if task.get("is_bllok"):
        return "BLL"
    if task.get("is_r1"):
        return "R1"
    if task.get("is_1h_report"):
        return "1H"
    if task.get("ga_note_origin_id"):
        return "GA"
    if task.get("is_personal"):
        return "P"
    return None


def _task_matches_type(task: dict[str, Any], task_type: str | None) -> bool:
    if not task_type:
        return True
    if task_type == "BLL":
        return bool(task.get("is_bllok"))
    if task_type == "R1":
        return bool(task.get("is_r1"))
    if task_type == "1H":
        return bool(task.get("is_1h_report"))
    if task_type == "GA":
        return bool(task.get("ga_note_origin_id"))
    if task_type == "P":
        return bool(task.get("is_personal"))
    return True


def _task_is_open(task: dict[str, Any]) -> bool:
    return (
        str(task.get("status") or "").upper() not in {"DONE", "COMPLETED"}
        and not task.get("completed_at")
    )


def _iso_date_part(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _task_overdue_days(task: dict[str, Any], today: date) -> int | None:
    if not _task_is_open(task):
        return None
    due = _iso_date_part(task.get("due_date"))
    if due and due < today:
        return (today - due).days
    return None


def _effective_task_date(task: dict[str, Any]) -> date | None:
    # Same precedence the backend uses for planner-window filtering.
    for key in ("planned_date", "due_date", "start_date", "created_at"):
        parsed = _iso_date_part(task.get(key))
        if parsed:
            return parsed
    return None


def _user_label(user: dict[str, Any] | None) -> str:
    if not user:
        return "Unassigned"
    return str(user.get("full_name") or user.get("username") or user.get("email") or user.get("id"))


async def _users_by_id() -> dict[str, dict[str, Any]]:
    users = await _cached_lookup("users", "/api/users")
    return {str(user.get("id")): user for user in users}


def _compact_task(task: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    today = today or datetime.now(_local_tz()).date()
    compact = {
        "id": task.get("id"),
        "title": task.get("title"),
        "type": _task_type_code(task),
        "status": task.get("status"),
        "priority": task.get("priority") if task.get("priority") != "NORMAL" else None,
        "one_h_report_slot": task.get("one_h_report_slot"),
        "finish_period": task.get("finish_period"),
        "start_date": task.get("start_date"),
        "due_date": task.get("due_date"),
        "original_due_date": task.get("original_due_date"),
        "days_late": _task_overdue_days(task, today),
        "progress_percentage": task.get("progress_percentage") or None,
        "assignees": [_user_label(assignee) for assignee in task.get("assignees") or []] or None,
        "project_id": task.get("project_id"),
        "is_deadline_important": task.get("is_deadline_important") or None,
    }
    return {key: value for key, value in compact.items() if value is not None}


def _group_tasks_by_person(
    tasks: list[dict[str, Any]],
    users_by_id: dict[str, dict[str, Any]],
    today: date | None = None,
) -> list[dict[str, Any]]:
    today = today or datetime.now(_local_tz()).date()
    groups: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        keys = [str(assignee.get("id")) for assignee in task.get("assignees") or []]
        if not keys and task.get("assigned_to"):
            keys = [str(task["assigned_to"])]
        for key in keys or ["unassigned"]:
            groups.setdefault(key, []).append(task)
    people: list[dict[str, Any]] = []
    for key, person_tasks in groups.items():
        user = users_by_id.get(key)
        people.append(
            {
                "user_id": None if key == "unassigned" else key,
                "name": _user_label(user) if user or key == "unassigned" else key,
                "count": len(person_tasks),
                "overdue_count": sum(1 for task in person_tasks if _task_overdue_days(task, today)),
                "tasks": [_compact_task(task, today) for task in person_tasks],
            }
        )
    people.sort(key=lambda person: (person["user_id"] is None, person["name"].lower()))
    return people


def _week_bounds(week_start_iso: str) -> tuple[date, date, str, str]:
    monday = date.fromisoformat(week_start_iso)
    sunday = monday + timedelta(days=6)
    tz = _local_tz()
    window_from = datetime.combine(monday, datetime_time.min, tzinfo=tz)
    window_to = datetime.combine(sunday, datetime_time.min, tzinfo=tz) + timedelta(days=1) - timedelta(microseconds=1)
    return monday, sunday, window_from.isoformat(), window_to.isoformat()


def _parse_date_arg(value: str | None) -> str | None:
    """Accept ISO datetimes as-is; convert plain dates and sot/neser/dje words to ISO dates."""
    if not value:
        return None
    if "T" in value:
        return value
    return _parse_day(value).isoformat()


@_tool()
async def primeflow_me() -> Any:
    """Return the Primeflow user connected to this MCP server."""
    return await _request("GET", "/api/auth/me")


@_tool()
async def primeflow_guide() -> str:
    """Return a broad guide explaining Primeflow modules, terminology, and MCP/API usage rules."""
    return PRIMEFLOW_GUIDE


@_tool()
async def primeflow_context() -> Any:
    """Return current Primeflow time, timezone, connected user, and departments. Use when a request depends on 'today' or access scope."""
    now = datetime.now(_local_tz())
    user, departments = await asyncio.gather(
        _request("GET", "/api/auth/me"),
        _cached_lookup("departments", "/api/departments"),
    )
    return {
        "now": now.isoformat(),
        "today": now.date().isoformat(),
        "timezone": APP_TIMEZONE,
        "connected_user": user,
        "departments": departments,
    }


@_tool()
async def list_api_endpoints(tag: str | None = None, query: str | None = None) -> Any:
    """List Primeflow API endpoints from FastAPI OpenAPI. Optional tag/query filters narrow the result."""
    spec = await _request("GET", "/openapi.json")
    results: list[dict[str, Any]] = []
    tag_filter = tag.lower() if tag else None
    query_filter = query.lower() if query else None
    for path, methods in spec.get("paths", {}).items():
        for method, details in methods.items():
            if method.lower() not in {"get", "post", "patch", "put", "delete"}:
                continue
            tags = details.get("tags") or []
            haystack = " ".join(
                [
                    path,
                    method,
                    str(details.get("summary") or ""),
                    str(details.get("description") or ""),
                    " ".join(str(item) for item in tags),
                ]
            ).lower()
            if tag_filter and tag_filter not in [str(item).lower() for item in tags]:
                continue
            if query_filter and query_filter not in haystack:
                continue
            results.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "tags": tags,
                    "summary": details.get("summary"),
                    "operation_id": details.get("operationId"),
                }
            )
    return results


@_tool()
async def list_departments() -> Any:
    """List Primeflow departments. Use this before department-specific reports if the department ID is unknown."""
    return await _cached_lookup("departments", "/api/departments")


@_tool()
async def resolve_department(department_ref: str) -> Any:
    """Resolve a Primeflow department name/code/slug/UUID such as Development, DEV, GA, PCM to a department record."""
    department_id = await _resolve_department_id(department_ref)
    departments = await _cached_lookup("departments", "/api/departments")
    for department in departments:
        if str(department.get("id")) == department_id:
            return department
    return {"id": department_id}


@_tool()
async def primeflow_api_request(
    method: str,
    path: str,
    params_json: str | None = None,
    body_json: str | None = None,
) -> Any:
    """
    Call any Primeflow API endpoint through the existing backend.

    method: GET, POST, PATCH, PUT, or DELETE.
    path: relative path such as /api/tasks, /api/planners/weekly-table, /api/common-view, or /openapi.json.
    params_json: JSON object for query params, for example {"include_done": false}.
    body_json: JSON body for POST/PATCH/PUT, for example {"title": "Task"}.

    DELETE is disabled unless the server sets PRIMEFLOW_MCP_ALLOW_DELETE=true.
    """
    method_upper = method.strip().upper()
    if method_upper not in {"GET", "POST", "PATCH", "PUT", "DELETE"}:
        raise ValueError("method must be GET, POST, PATCH, PUT, or DELETE.")
    if method_upper == "DELETE" and not ALLOW_DELETE:
        raise ValueError(
            "DELETE is disabled on this MCP server (PRIMEFLOW_MCP_ALLOW_DELETE=false). "
            "Ask an administrator to delete the item in PrimeFlow."
        )
    normalized_path = _normalize_api_path(path)
    params = _parse_json_arg(params_json, default={})
    body = _parse_json_arg(body_json, default=None)
    if not isinstance(params, dict):
        raise ValueError("params_json must be a JSON object.")

    response: httpx.Response | None = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=REQUEST_TIMEOUT, headers=await _headers()) as client:
                response = await client.request(method_upper, normalized_path, params=params, json=body)
        except httpx.RequestError as exc:
            raise RuntimeError(f"Primeflow API is unreachable for {method_upper} {normalized_path}: {exc}") from exc
        if response.status_code != 401 or attempt == 1:
            break
        _token_cache["access_token"] = None
        _token_cache["expires_at"] = 0
    assert response is not None
    if response.is_error:
        raise RuntimeError(
            f"Primeflow API {method_upper} {normalized_path} failed ({response.status_code}): {_api_error_detail(response)}"
        )
    content_type = response.headers.get("content-type", "")
    if response.status_code == 204 or not response.content:
        return {"status": "ok", "status_code": response.status_code}
    if "application/json" in content_type:
        return response.json()
    text = response.text
    return {
        "status_code": response.status_code,
        "content_type": content_type,
        "content_length": len(response.content),
        "text_preview": text[:2000],
    }


@_tool()
async def list_database_tables(schema_name: str = "public") -> Any:
    """List database tables/views in a schema using the read-only DB connection."""
    return await _db_fetch(
        """
        select table_schema, table_name, table_type
        from information_schema.tables
        where table_schema = $1
        order by table_type, table_name
        """,
        schema_name,
    )


@_tool()
async def describe_database_table(table_name: str, schema_name: str = "public") -> Any:
    """Describe columns, types, nullability, defaults, and primary key status for a database table."""
    columns = await _db_fetch(
        """
        select
            c.ordinal_position,
            c.column_name,
            c.data_type,
            c.udt_name,
            c.is_nullable,
            c.column_default,
            case when pk.column_name is not null then true else false end as is_primary_key
        from information_schema.columns c
        left join (
            select ku.table_schema, ku.table_name, ku.column_name
            from information_schema.table_constraints tc
            join information_schema.key_column_usage ku
              on tc.constraint_name = ku.constraint_name
             and tc.table_schema = ku.table_schema
            where tc.constraint_type = 'PRIMARY KEY'
        ) pk
          on pk.table_schema = c.table_schema
         and pk.table_name = c.table_name
         and pk.column_name = c.column_name
        where c.table_schema = $1 and c.table_name = $2
        order by c.ordinal_position
        """,
        schema_name,
        table_name,
    )
    if not columns:
        raise ValueError(f"Table not found: {schema_name}.{table_name}")
    return columns


@_tool()
async def list_database_relationships(table_name: str | None = None, schema_name: str = "public") -> Any:
    """List foreign-key relationships, optionally filtered to one table."""
    return await _db_fetch(
        """
        select
            tc.constraint_name,
            kcu.table_schema,
            kcu.table_name,
            kcu.column_name,
            ccu.table_schema as foreign_table_schema,
            ccu.table_name as foreign_table_name,
            ccu.column_name as foreign_column_name
        from information_schema.table_constraints tc
        join information_schema.key_column_usage kcu
          on tc.constraint_name = kcu.constraint_name
         and tc.table_schema = kcu.table_schema
        join information_schema.constraint_column_usage ccu
          on ccu.constraint_name = tc.constraint_name
         and ccu.table_schema = tc.table_schema
        where tc.constraint_type = 'FOREIGN KEY'
          and kcu.table_schema = $1
          and ($2::text is null or kcu.table_name = $2 or ccu.table_name = $2)
        order by kcu.table_name, kcu.column_name
        """,
        schema_name,
        table_name,
    )


@_tool()
async def run_readonly_sql(sql: str, max_rows: int = 100) -> Any:
    """
    Run a read-only SQL query against Primeflow DB.

    Only SELECT/WITH are allowed. The query runs in a read-only transaction.
    Results are capped to max_rows, default 100, hard max 500.
    Use this for understanding data and relationships, not for app writes.
    """
    statement = _validate_readonly_sql(sql)
    row_limit = min(max(max_rows, 1), 500)
    wrapped = f"select * from ({statement}) as mcp_readonly_result limit {row_limit}"
    rows = await _db_fetch(wrapped)
    return {"row_count": len(rows), "max_rows": row_limit, "rows": rows}


@_tool()
async def search_primeflow(query: str) -> Any:
    """Search Primeflow tasks and projects by text."""
    return await _request("GET", "/api/search", params={"q": query})


@_tool(name="search")
async def search_for_chatgpt(query: str) -> dict[str, list[dict[str, str]]]:
    """Search Primeflow and return ChatGPT-compatible citation results."""
    data = await search_primeflow(query)
    results: list[dict[str, str]] = []
    for task in data.get("tasks", []):
        task_id = str(task["id"])
        results.append(
            {
                "id": f"task:{task_id}",
                "title": task.get("title") or f"Task {task_id}",
                "url": _frontend_url(f"/tasks/{task_id}"),
            }
        )
    for project in data.get("projects", []):
        project_id = str(project["id"])
        title = project.get("title") or project.get("name") or f"Project {project_id}"
        results.append(
            {
                "id": f"project:{project_id}",
                "title": title,
                "url": _frontend_url(f"/projects/{project_id}"),
            }
        )
    return {"results": results}


@_tool(name="fetch")
async def fetch_for_chatgpt(id: str) -> dict[str, Any]:
    """Fetch a Primeflow search result by ID. IDs are returned by the search tool."""
    kind, _, item_id = id.partition(":")
    if kind == "task" and item_id:
        task = await get_task(item_id)
        return {
            "id": id,
            "title": task.get("title") or f"Task {item_id}",
            "text": "\n".join(
                part
                for part in [
                    f"Status: {task.get('status')}",
                    f"Priority: {task.get('priority')}",
                    f"Due date: {task.get('due_date')}",
                    task.get("description") or "",
                    task.get("internal_notes") or "",
                ]
                if part
            ),
            "url": _frontend_url(f"/tasks/{item_id}"),
            "metadata": {"type": "task", "primeflow_id": item_id},
        }
    if kind == "project" and item_id:
        project = await get_project(item_id)
        return {
            "id": id,
            "title": project.get("display_title") or project.get("title") or f"Project {item_id}",
            "text": "\n".join(
                part
                for part in [
                    f"Status: {project.get('status')}",
                    f"Current phase: {project.get('current_phase')}",
                    f"Progress: {project.get('progress_percentage')}%",
                    project.get("description") or "",
                ]
                if part
            ),
            "url": _frontend_url(f"/projects/{item_id}"),
            "metadata": {"type": "project", "primeflow_id": item_id},
        }
    raise ValueError("Expected a search result ID like task:<uuid> or project:<uuid>.")


@_tool()
async def list_tasks(
    department_id: str | None = None,
    department_ref: str | None = None,
    project_id: str | None = None,
    project_ref: str | None = None,
    status: str | None = None,
    assigned_to: str | None = None,
    assignee_name: str | None = None,
    due_from: str | None = None,
    due_to: str | None = None,
    window_from: str | None = None,
    window_to: str | None = None,
    include_done: bool = True,
    include_inactive: bool = False,
) -> Any:
    """
    List Primeflow tasks with optional filters.

    Use assignee_name for names/initials like "Endi Hyseni" or "EH"; the MCP server resolves it to assigned_to UUID.
    Date filters should be ISO datetime strings. window_from/window_to is better for "tasks for this day" because it considers due/start/created planner windows.
    """
    resolved_department = department_id or await _resolve_department_id(department_ref)
    resolved_project = project_id or await _resolve_project_id(project_ref, department_ref)
    resolved_assignee = await _resolve_user_id(assignee_name or assigned_to, department_ref)
    return await _request(
        "GET",
        "/api/tasks",
        params={
            "department_id": resolved_department,
            "project_id": resolved_project,
            "status": status,
            "assigned_to": resolved_assignee,
            "due_from": due_from,
            "due_to": due_to,
            "window_from": window_from,
            "window_to": window_to,
            "include_done": include_done,
            "include_inactive": include_inactive,
        },
    )


@_tool()
async def get_user_tasks_for_day(
    user_ref: str,
    day_date: str | None = None,
    unfinished_only: bool = False,
    include_inactive: bool = False,
    department_ref: str | None = None,
    include_overdue: bool = False,
) -> Any:
    """
    Get one user's Primeflow tasks for a specific local day.

    Use this for questions like "what does Endi Hyseni need to finish today?"
    user_ref can be a full name, username, email, UUID, or initials.
    day_date is YYYY-MM-DD; omitted means today in APP_TIMEZONE.
    unfinished_only=true excludes DONE/completed tasks. include_overdue=true
    also includes unfinished tasks due before the requested day.
    """
    user_id = await _resolve_user_id(user_ref, department_ref)
    day, start, end = _day_bounds(day_date)
    tasks = await _request(
        "GET",
        "/api/tasks",
        params={
            "assigned_to": user_id,
            "window_from": start,
            "window_to": end,
            "include_done": not unfinished_only,
            "include_inactive": include_inactive,
        },
    )
    overdue_count = 0
    if include_overdue:
        overdue_before = datetime.fromisoformat(start) - timedelta(microseconds=1)
        overdue_tasks = await _request(
            "GET",
            "/api/tasks",
            params={
                "assigned_to": user_id,
                "due_to": overdue_before.isoformat(),
                "include_done": False,
                "include_inactive": include_inactive,
            },
        )
        existing_ids = {str(task.get("id")) for task in tasks}
        new_overdue = [task for task in overdue_tasks if str(task.get("id")) not in existing_ids]
        overdue_count = len(new_overdue)
        tasks = new_overdue + tasks
    if unfinished_only:
        tasks = [
            task for task in tasks
            if str(task.get("status") or "").upper() not in {"DONE", "COMPLETED"}
            and not task.get("completed_at")
        ]
    users = await _cached_lookup("users", "/api/users")
    user = next((candidate for candidate in users if str(candidate.get("id")) == user_id), {"id": user_id})
    return {
        "user": user,
        "user_id": user_id,
        "day": day,
        "unfinished_only": unfinished_only,
        "include_overdue": include_overdue,
        "overdue_count": overdue_count,
        "count": len(tasks),
        "tasks": tasks,
    }


@_tool()
async def get_user_unfinished_tasks_today(user_ref: str, department_ref: str | None = None) -> Any:
    """Get unfinished Primeflow tasks for a user today. Use this for 'left unfinished today' questions."""
    return await get_user_tasks_for_day(
        user_ref=user_ref,
        day_date=None,
        unfinished_only=True,
        department_ref=department_ref,
    )


@_tool()
async def get_open_tasks_by_department(
    department_ref: str,
    include_done: bool = False,
    include_inactive: bool = False,
) -> Any:
    """Get open/unfinished tasks for a Primeflow department by name/code/UUID."""
    department_id = await _resolve_department_id(department_ref)
    return await list_tasks(
        department_id=department_id,
        include_done=include_done,
        include_inactive=include_inactive,
    )


@_tool()
async def get_common_view(
    week_start: str | None = None,
    include: str | None = "users,departments,entries,meetings,system_tasks,tasks",
    department_id: str | None = None,
    include_all_departments: bool = True,
    max_items_per_bucket: int | None = None,
) -> Any:
    """
    Get Primeflow Common View.

    Use this for Common View, internal/external meetings, 1H, blocked, personal, R1, priority, feedback,
    absent/leave, external holidays, system-task BZ rows, and weekly operational overview.
    For meetings, Common View returns them in items.internal and items.external.
    week_start should be the Monday date in YYYY-MM-DD format; omitted means current week.
    """
    return await _request(
        "GET",
        "/api/common-view",
        params={
            "week_start": week_start,
            "include": include,
            "department_id": department_id,
            "include_all_departments": include_all_departments,
            "max_items_per_bucket": max_items_per_bucket,
        },
    )


@_tool()
async def get_common_view_meetings_for_week(
    week_start: str | None = None,
    department_ref: str | None = None,
    include_all_departments: bool = True,
    week: Literal["current", "next"] = "current",
) -> Any:
    """
    Get internal and external meetings from Common View for a week.

    Use this for "takime interne/eksterne kete jave/javen tjeter".
    week_start should be Monday YYYY-MM-DD. The result contains internal and external lists.
    """
    department_id = await _resolve_department_id(department_ref)
    resolved_week_start = _week_start(week_start, week)
    data = await get_common_view(
        week_start=resolved_week_start,
        include="users,departments,meetings",
        department_id=department_id,
        include_all_departments=include_all_departments,
    )
    items = data.get("items") or {}
    return {
        "week_start": data.get("week_start"),
        "week_end": data.get("week_end"),
        "counts": {
            "internal": len(items.get("internal") or []),
            "external": len(items.get("external") or []),
        },
        "internal": items.get("internal") or [],
        "external": items.get("external") or [],
    }


@_tool()
async def list_meetings(
    department_id: str | None = None,
    department_ref: str | None = None,
    project_id: str | None = None,
    project_ref: str | None = None,
    include_all_departments: bool = True,
    meeting_type: str | None = None,
) -> Any:
    """
    List Primeflow meetings.

    meeting_type can be "internal" or "external".
    For week-based internal/external meeting summaries, prefer get_common_view because it expands recurring meetings by week.
    """
    resolved_department = department_id or await _resolve_department_id(department_ref)
    resolved_project = project_id or await _resolve_project_id(project_ref, department_ref)
    return await _request(
        "GET",
        "/api/meetings",
        params={
            "department_id": resolved_department,
            "project_id": resolved_project,
            "include_all_departments": include_all_departments,
            "meeting_type": meeting_type,
        },
    )


@_tool()
async def create_meeting(
    title: str,
    department_ref: str,
    starts_at: str | None = None,
    meeting_type: Literal["internal", "external"] = "external",
    platform: str | None = None,
    meeting_url: str | None = None,
    project_ref: str | None = None,
    participant_names: list[str] | None = None,
    participant_ids: list[str] | None = None,
    recurrence_type: Literal["none", "weekly", "monthly", "yearly"] = "none",
    recurrence_days_of_week: list[int] | None = None,
    recurrence_days_of_month: list[int] | None = None,
) -> Any:
    """
    Create an internal or external Primeflow meeting.

    starts_at is an ISO datetime. Weekly recurrence uses Monday=0 through
    Sunday=6. Monthly recurrence uses day numbers 1-31. Participant names and
    initials are resolved automatically.
    """
    department_id = await _resolve_department_id(department_ref)
    project_id = await _resolve_project_id(project_ref, department_ref)
    resolved_participants = list(dict.fromkeys(participant_ids or []))
    for participant_name in participant_names or []:
        participant_id = await _resolve_user_id(participant_name)
        if participant_id and participant_id not in resolved_participants:
            resolved_participants.append(participant_id)
    if recurrence_days_of_week and any(day < 0 or day > 6 for day in recurrence_days_of_week):
        raise ValueError("recurrence_days_of_week values must be between 0 (Monday) and 6 (Sunday)")
    if recurrence_days_of_month and any(day < 1 or day > 31 for day in recurrence_days_of_month):
        raise ValueError("recurrence_days_of_month values must be between 1 and 31")
    return await _request(
        "POST",
        "/api/meetings",
        json={
            "title": title,
            "platform": platform,
            "starts_at": starts_at,
            "meeting_url": meeting_url,
            "meeting_type": meeting_type,
            "recurrence_type": None if recurrence_type == "none" else recurrence_type,
            "recurrence_days_of_week": recurrence_days_of_week,
            "recurrence_days_of_month": recurrence_days_of_month,
            "department_id": department_id,
            "project_id": project_id,
            "participant_ids": resolved_participants,
        },
    )


@_tool()
async def get_weekly_planner(
    week_start: str | None = None,
    department_ref: str | None = None,
    user_ref: str | None = None,
) -> Any:
    """Get Primeflow weekly planner data. Use for weekly plan/project/task planning views."""
    department_id = await _resolve_department_id(department_ref)
    user_id = await _resolve_user_id(user_ref)
    return await _request(
        "GET",
        "/api/planners/weekly",
        params={"week_start": week_start, "department_id": department_id, "user_id": user_id},
    )


@_tool()
async def get_weekly_table(
    week_start: str | None = None,
    department_ref: str | None = None,
    is_this_week: bool = False,
) -> Any:
    """Get Primeflow weekly table planner, organized by departments/users/days/AM/PM."""
    department_id = await _resolve_department_id(department_ref)
    return await _request(
        "GET",
        "/api/planners/weekly-table",
        params={"week_start": week_start, "department_id": department_id, "is_this_week": is_this_week},
    )


@_tool()
async def get_monthly_planner(
    year: int,
    month: int,
    department_ref: str | None = None,
    user_ref: str | None = None,
) -> Any:
    """Get Primeflow monthly planner for a year/month, optionally scoped to department or user."""
    department_id = await _resolve_department_id(department_ref)
    user_id = await _resolve_user_id(user_ref)
    return await _request(
        "GET",
        "/api/planners/monthly",
        params={"year": year, "month": month, "department_id": department_id, "user_id": user_id},
    )


@_tool()
async def get_daily_report(
    day: str | None = None,
    department_ref: str | None = None,
    user_ref: str | None = None,
) -> Any:
    """Get Primeflow daily report for execution/accountability, late items, daily tasks, and system occurrences."""
    day_value = _parse_day(day).isoformat()
    department_id = await _resolve_department_id(department_ref)
    user_id = await _resolve_user_id(user_ref)
    return await _request(
        "GET",
        "/api/reports/daily",
        params={"day": day_value, "department_id": department_id, "user_id": user_id},
    )


@_tool()
async def get_daily_ga_table(
    day: str | None = None,
    department_ref: str | None = None,
    user_ref: str | None = None,
) -> Any:
    """Get Primeflow daily GA table/report data for a day."""
    day_value = _parse_day(day).isoformat()
    department_id = await _resolve_department_id(department_ref)
    user_id = await _resolve_user_id(user_ref)
    return await _request(
        "GET",
        "/api/reports/daily-ga-table",
        params={"day": day_value, "department_id": department_id, "user_id": user_id},
    )


@_tool()
async def list_common_entries(from_date: str | None = None, to_date: str | None = None) -> Any:
    """List Common entries, optionally by date range. Use for complaints, requests, proposals, problems, leave/PV, holidays, feedback."""
    return await _request("GET", "/api/common-entries", params={"from": from_date, "to": to_date})


@_tool()
async def create_common_entry(
    category: Literal[
        "Delays",
        "Absences",
        "Annual Leave",
        "Blocks",
        "External Tasks",
        "External Holiday",
        "Problems",
        "Complaints",
        "Requests",
        "Proposals",
    ],
    title: str,
    description: str | None = None,
    entry_date: str | None = None,
    assigned_to_name: str | None = None,
) -> Any:
    """Create a Common View entry such as a delay, absence, block, problem, complaint, request, or proposal."""
    assigned_to_user_id = await _resolve_user_id(assigned_to_name)
    resolved_entry_date = _parse_day(entry_date).isoformat() if entry_date else None
    return await _request(
        "POST",
        "/api/common-entries",
        json={
            "category": category,
            "title": title,
            "description": description,
            "entry_date": resolved_entry_date,
            "assigned_to_user_id": assigned_to_user_id,
        },
    )


@_tool()
async def list_leave_blocks(
    block_type: str = "PV_FEST",
    start: str | None = None,
    end: str | None = None,
    department_ref: str | None = None,
) -> Any:
    """List Common View leave/holiday blocks. block_type defaults to PV_FEST."""
    department_id = await _resolve_department_id(department_ref)
    return await _request(
        "GET",
        "/api/common-entries/blocks",
        params={"type": block_type, "start": start, "end": end, "department_id": department_id},
    )


@_tool()
async def list_ga_notes(project_id: str | None = None, department_ref: str | None = None) -> Any:
    """List GA/KA notes, optionally for a project or department."""
    department_id = await _resolve_department_id(department_ref)
    return await _request("GET", "/api/ga-notes", params={"project_id": project_id, "department_id": department_id})


@_tool()
async def create_ga_note(
    content: str,
    note_type: Literal["GA", "KA"] = "GA",
    department_ref: str | None = None,
    project_id: str | None = None,
    project_ref: str | None = None,
    priority: Literal["NORMAL", "HIGH"] | None = None,
    status: Literal["OPEN", "CLOSED"] | None = None,
    start_date: str | None = None,
    due_date: str | None = None,
    is_discussed: bool | None = None,
) -> Any:
    """
    Create a GA/KA note in Primeflow.

    Use this for requests like "krijo GA note" or "shto KA note".
    note_type must be GA or KA. priority can be NORMAL or HIGH. department_ref
    can be a department name such as "Development" or "GA/KA".
    """
    department_id = await _resolve_department_id(department_ref)
    resolved_project_id = project_id or await _resolve_project_id(project_ref, department_ref)
    return await _request(
        "POST",
        "/api/ga-notes",
        json={
            "content": content,
            "note_type": note_type,
            "department_id": department_id,
            "project_id": resolved_project_id,
            "priority": priority,
            "status": status,
            "start_date": start_date,
            "due_date": due_date,
            "is_discussed": is_discussed,
        },
    )


@_tool()
async def update_ga_note(
    note_id: str,
    content: str | None = None,
    status: Literal["OPEN", "CLOSED"] | None = None,
    priority: Literal["NORMAL", "HIGH"] | None = None,
    is_discussed: bool | None = None,
    is_converted_to_task: bool | None = None,
) -> Any:
    """Update the content, status, priority, discussed state, or conversion state of an existing GA/KA note."""
    payload = {
        "content": content,
        "status": status,
        "priority": priority,
        "is_discussed": is_discussed,
        "is_converted_to_task": is_converted_to_task,
    }
    return await _request(
        "PATCH",
        f"/api/ga-notes/{note_id}",
        json={key: value for key, value in payload.items() if value is not None},
    )


@_tool()
async def create_task_from_ga_note(
    note_id: str,
    assignee_name: str | None = None,
    assignee_names: list[str] | None = None,
    assignee_ids: list[str] | None = None,
    department_ref: str | None = None,
    project_id: str | None = None,
    start_date: str | None = None,
    due_date: str | None = None,
    priority: str = "NORMAL",
    is_1h_report: bool = False,
    one_h_report_slot: str | None = None,
    is_deadline_important: bool = False,
) -> Any:
    """
    Create a task from an existing GA/KA note and keep it linked to that note.

    The task title and description are always taken from the note. Assign at
    least one person through assignee_name/assignee_names or exact assignee_ids.
    Dates must be ISO strings. Use this instead of create_task for any existing
    GA/KA note; it prevents a second conversion of the same note.
    """
    note = await _request("GET", f"/api/ga-notes/{note_id}")
    if note.get("is_converted_to_task"):
        raise ValueError(f"GA/KA note {note_id} is already converted to a task.")

    resolved_assignees = list(dict.fromkeys(assignee_ids or []))
    name_refs = list(assignee_names or [])
    if assignee_name:
        name_refs.insert(0, assignee_name)
    for name_ref in name_refs:
        resolved_user_id = await _resolve_user_id(name_ref)
        if resolved_user_id and resolved_user_id not in resolved_assignees:
            resolved_assignees.append(resolved_user_id)
    if not resolved_assignees:
        raise ValueError("Provide at least one assignee_name, assignee_names, or assignee_ids value.")

    note_project_id = note.get("project_id")
    if project_id and note_project_id and project_id != note_project_id:
        raise ValueError("project_id must match the source GA/KA note project.")
    effective_project_id = project_id or note_project_id
    department_id = await _resolve_department_id(department_ref)
    department_id = department_id or note.get("department_id")
    if effective_project_id and not department_id:
        project = await _request("GET", f"/api/projects/{effective_project_id}")
        department_id = project.get("department_id")
    if not department_id:
        raise ValueError(
            "The source note has no department. Provide department_ref so the task can be created."
        )

    normalized_priority = priority.upper()
    if normalized_priority not in {"NORMAL", "HIGH"}:
        raise ValueError("priority must be NORMAL or HIGH")
    if one_h_report_slot and one_h_report_slot not in {"10:00", "11:00", "11:50", "14:20", "16:00"}:
        raise ValueError("one_h_report_slot must be 10:00, 11:00, 11:50, 14:20, or 16:00")

    content = note.get("content")
    task = await _request(
        "POST",
        "/api/tasks",
        json={
            "title": ga_note_task_title(content),
            "description": ga_note_default_task_description(content),
            "project_id": effective_project_id,
            "department_id": department_id,
            "assigned_to": resolved_assignees[0],
            "assignees": resolved_assignees,
            "ga_note_origin_id": note_id,
            "status": "TODO",
            "priority": normalized_priority,
            "start_date": start_date,
            "due_date": due_date,
            "is_deadline_important": is_deadline_important,
            "is_1h_report": is_1h_report or bool(one_h_report_slot),
            "one_h_report_slot": one_h_report_slot,
        },
    )
    updated_note = await _request(
        "PATCH",
        f"/api/ga-notes/{note_id}",
        json={"is_converted_to_task": True},
    )
    return {
        "task": task,
        "ga_note": updated_note,
        "message": "Task created from GA/KA note and linked to its source note.",
    }


@_tool()
async def list_plan_notes(project_id: str | None = None, department_ref: str | None = None) -> Any:
    """List plan notes, optionally for a project or department."""
    department_id = await _resolve_department_id(department_ref)
    return await _request("GET", "/api/plan-notes", params={"project_id": project_id, "department_id": department_id})


@_tool()
async def create_plan_note(
    content: str,
    department_ref: str | None = None,
    project_ref: str | None = None,
    project_id: str | None = None,
    comment: str | None = None,
    note_type: Literal["GA", "KA"] = "GA",
    priority: Literal["NORMAL", "HIGH"] | None = None,
    start_date: str | None = None,
    due_date: str | None = None,
    planned_for_date: str | None = None,
    next_week: bool = False,
) -> Any:
    """Create a Primeflow Plan Note for a department or project."""
    department_id = await _resolve_department_id(department_ref)
    resolved_project_id = project_id or await _resolve_project_id(project_ref, department_ref)
    return await _request(
        "POST",
        "/api/plan-notes",
        json={
            "content": content,
            "comment": comment,
            "note_type": note_type,
            "priority": priority,
            "start_date": start_date,
            "due_date": due_date,
            "planned_for_date": _parse_day(planned_for_date).isoformat() if planned_for_date else None,
            "next_week": next_week,
            "project_id": resolved_project_id,
            "department_id": department_id,
        },
    )


@_tool()
async def list_internal_notes(department_ref: str, to_user_ref: str | None = None) -> Any:
    """List internal notes for a department, optionally targeted to a user."""
    department_id = await _resolve_department_id(department_ref)
    to_user_id = await _resolve_user_id(to_user_ref)
    return await _request(
        "GET",
        "/api/internal-notes",
        params={"department_id": department_id, "to_user_id": to_user_id},
    )


@_tool()
async def create_internal_note(
    title: str,
    to_user_names: list[str],
    description: str | None = None,
    project_ref: str | None = None,
    department_ref: str | None = None,
) -> Any:
    """Create an Internal Note for one or more Primeflow users. Names and initials are resolved automatically."""
    if not to_user_names:
        raise ValueError("Provide at least one to_user_names value")
    to_user_ids: list[str] = []
    for user_name in to_user_names:
        user_id = await _resolve_user_id(user_name)
        if user_id and user_id not in to_user_ids:
            to_user_ids.append(user_id)
    department_id = await _resolve_department_id(department_ref)
    project_id = await _resolve_project_id(project_ref, department_ref)
    return await _request(
        "POST",
        "/api/internal-notes",
        json={
            "title": title,
            "description": description,
            "department_id": department_id,
            "project_id": project_id,
            "to_user_ids": to_user_ids,
        },
    )


@_tool()
async def list_system_tasks(
    department_ref: str | None = None,
    only_active: bool = False,
    assigned_to: str | None = None,
    occurrence_date: str | None = None,
    include_overdue: bool = False,
) -> Any:
    """List system tasks/occurrences. assigned_to can be name/initials/UUID."""
    department_id = await _resolve_department_id(department_ref)
    assigned_to_id = await _resolve_user_id(assigned_to)
    return await _request(
        "GET",
        "/api/system-tasks",
        params={
            "department_id": department_id,
            "only_active": only_active,
            "assigned_to": assigned_to_id,
            "occurrence_date": occurrence_date,
            "include_overdue": include_overdue,
        },
    )


@_tool()
async def list_system_task_templates() -> Any:
    """List Primeflow system task templates including recurring task definitions where visible."""
    return await _request("GET", "/api/system-tasks/templates")


@_tool()
async def get_task(task_id: str) -> Any:
    """Get a Primeflow task by ID."""
    return await _request("GET", f"/api/tasks/{task_id}")


@_tool()
async def create_task(
    title: str,
    description: str | None = None,
    project_id: str | None = None,
    project_ref: str | None = None,
    department_id: str | None = None,
    department_ref: str | None = None,
    assigned_to: str | None = None,
    assignee_name: str | None = None,
    assignee_names: list[str] | None = None,
    assignee_ids: list[str] | None = None,
    start_date: str | None = None,
    due_date: str | None = None,
    priority: str | None = None,
    status: str | None = None,
    internal_notes: str | None = None,
    progress_percentage: int | None = None,
    is_deadline_important: bool | None = None,
    is_1h_report: bool | None = None,
    one_h_report_slot: str | None = None,
) -> Any:
    """
    Create a Primeflow task.

    Primeflow rules:
    - Use assignee_name for names or initials such as "Laurent Hoxha" or "LH"; the MCP server resolves it to a user ID.
    - Use assignee_ids only when exact Primeflow user UUIDs are already known.
    - "1H" means set is_1h_report=true, not "due in one hour".
    - one_h_report_slot, when known, must be one of 10:00, 11:00, 11:50, 14:20, 16:00.
    - due_date should be an ISO datetime string.
    """
    if len(title.strip()) < 2:
        raise ValueError("title must contain at least 2 characters")
    resolved_department = department_id or await _resolve_department_id(department_ref)
    resolved_project = project_id or await _resolve_project_id(project_ref, department_ref)
    if resolved_project and not resolved_department:
        project = await _request("GET", f"/api/projects/{resolved_project}")
        resolved_department = project.get("department_id")

    resolved_assignees = list(dict.fromkeys(assignee_ids or []))
    name_refs = list(assignee_names or [])
    if assignee_name or assigned_to:
        name_refs.insert(0, assignee_name or assigned_to or "")
    for name_ref in name_refs:
        resolved_assignee = await _resolve_user_id(name_ref, department_ref)
        if resolved_assignee and resolved_assignee not in resolved_assignees:
            resolved_assignees.append(resolved_assignee)

    normalized_priority = priority.upper() if priority else None
    if normalized_priority and normalized_priority not in {"NORMAL", "HIGH"}:
        raise ValueError("priority must be NORMAL or HIGH")
    normalized_status = status.upper() if status else None
    if normalized_status and normalized_status not in {"TODO", "IN_PROGRESS", "PAUSED", "WAITING_CONFIRMATION", "DONE"}:
        raise ValueError("status must be TODO, IN_PROGRESS, PAUSED, WAITING_CONFIRMATION, or DONE")
    if progress_percentage is not None and not 0 <= progress_percentage <= 100:
        raise ValueError("progress_percentage must be between 0 and 100")
    if one_h_report_slot and one_h_report_slot not in {"10:00", "11:00", "11:50", "14:20", "16:00"}:
        raise ValueError("one_h_report_slot must be 10:00, 11:00, 11:50, 14:20, or 16:00")

    return await _request(
        "POST",
        "/api/tasks",
        json={
            "title": title,
            "description": description,
            "project_id": resolved_project,
            "department_id": resolved_department,
            "assigned_to": resolved_assignees[0] if resolved_assignees else None,
            "assignees": resolved_assignees or None,
            "start_date": start_date,
            "due_date": due_date,
            "priority": normalized_priority,
            "status": normalized_status,
            "internal_notes": internal_notes,
            "progress_percentage": progress_percentage,
            "is_deadline_important": is_deadline_important,
            "is_1h_report": is_1h_report,
            "one_h_report_slot": one_h_report_slot,
        },
    )


@_tool()
async def create_1h_task(
    title: str,
    assignee_name: str,
    description: str | None = None,
    department_ref: str | None = None,
    due_date: str | None = None,
    one_h_report_slot: str | None = None,
    priority: str | None = None,
) -> Any:
    """
    Create a Primeflow 1H task for a user.

    Use this when the user says "krijo task 1H per LH/filan person".
    1H means is_1h_report=true. assignee_name can be initials or full name.
    """
    department_id = await _resolve_department_id(department_ref)
    return await create_task(
        title=title,
        description=description,
        department_id=department_id,
        assignee_name=assignee_name,
        due_date=due_date,
        priority=priority,
        is_1h_report=True,
        one_h_report_slot=one_h_report_slot,
    )


@_tool()
async def update_task(
    task_id: str,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    assigned_to: str | None = None,
    assignee_name: str | None = None,
    assignee_ids: list[str] | None = None,
    due_date: str | None = None,
    progress_percentage: int | None = None,
    is_1h_report: bool | None = None,
    one_h_report_slot: str | None = None,
    start_date: str | None = None,
    internal_notes: str | None = None,
    is_deadline_important: bool | None = None,
) -> Any:
    """Update selected fields on a Primeflow task. Use assignee_name for names/initials such as LH."""
    resolved_assignees = list(assignee_ids or [])
    resolved_assignee = await _resolve_user_id(assignee_name or assigned_to)
    if resolved_assignee and resolved_assignee not in resolved_assignees:
        resolved_assignees.insert(0, resolved_assignee)
    payload = {
        "title": title,
        "description": description,
        "status": status,
        "priority": priority,
        "assigned_to": resolved_assignees[0] if resolved_assignees else None,
        "assignees": resolved_assignees or None,
        "due_date": due_date,
        "start_date": start_date,
        "internal_notes": internal_notes,
        "progress_percentage": progress_percentage,
        "is_deadline_important": is_deadline_important,
        "is_1h_report": is_1h_report,
        "one_h_report_slot": one_h_report_slot,
    }
    return await _request("PATCH", f"/api/tasks/{task_id}", json={key: value for key, value in payload.items() if value is not None})


@_tool()
async def list_projects(
    department_id: str | None = None,
    department_ref: str | None = None,
    include_templates: bool = False,
) -> Any:
    """List Primeflow projects with optional department filtering."""
    resolved_department = department_id or await _resolve_department_id(department_ref)
    if resolved_department is None and not include_templates:
        return await _cached_lookup("projects", "/api/projects")
    return await _request(
        "GET",
        "/api/projects",
        params={"department_id": resolved_department, "include_templates": include_templates},
    )


@_tool()
async def get_project(project_id: str) -> Any:
    """Get a Primeflow project by ID."""
    return await _request("GET", f"/api/projects/{project_id}")


@_tool()
async def resolve_project(project_ref: str, department_ref: str | None = None) -> Any:
    """Resolve a Primeflow project title/display title/UUID, optionally inside a department, to its project record."""
    project_id = await _resolve_project_id(project_ref, department_ref)
    return await _request("GET", f"/api/projects/{project_id}")


@_tool()
async def list_users() -> Any:
    """List active Primeflow users visible to the connected account."""
    return await _cached_lookup("users", "/api/users")


@_tool()
async def resolve_user(user_ref: str, department_ref: str | None = None) -> Any:
    """Resolve a Primeflow user name, email, username, UUID, or initials like LH to a user record."""
    user_id = await _resolve_user_id(user_ref, department_ref)
    users = await _cached_lookup("users", "/api/users")
    for user in users:
        if str(user.get("id")) == user_id:
            return user
    return {"id": user_id}


@_tool()
async def get_tasks_today(
    user_ref: str | None = None,
    department_ref: str | None = None,
    task_type: str | None = None,
    unfinished_only: bool = True,
    include_overdue: bool = False,
    day_date: str | None = None,
) -> Any:
    """
    Get tasks for one local day, grouped by person.

    Use this for "detyrat per sot", "detyrat 1H per sot per te gjithe personat", etc.
    task_type filters by badge: 1H, P (personal), BLL (blocked), R1, GA, or ALL.
    Omit user_ref to include every person. day_date accepts YYYY-MM-DD, sot, neser, dje.
    include_overdue=true also lists unfinished tasks due before the day.
    """
    normalized_type = _normalize_task_type(task_type)
    user_id = await _resolve_user_id(user_ref, department_ref)
    department_id = await _resolve_department_id(department_ref)
    day, start, end = _day_bounds(day_date)
    tasks = await _request(
        "GET",
        "/api/tasks",
        params={
            "assigned_to": user_id,
            "department_id": department_id,
            "window_from": start,
            "window_to": end,
            "include_done": not unfinished_only,
        },
    )
    if include_overdue:
        overdue_before = datetime.fromisoformat(start) - timedelta(microseconds=1)
        overdue_tasks = await _request(
            "GET",
            "/api/tasks",
            params={
                "assigned_to": user_id,
                "department_id": department_id,
                "due_to": overdue_before.isoformat(),
                "include_done": False,
            },
        )
        existing_ids = {str(task.get("id")) for task in tasks}
        tasks = [task for task in overdue_tasks if str(task.get("id")) not in existing_ids] + tasks
    if unfinished_only:
        tasks = [task for task in tasks if _task_is_open(task)]
    tasks = [task for task in tasks if _task_matches_type(task, normalized_type)]
    people = _group_tasks_by_person(tasks, await _users_by_id(), _parse_day(day_date))
    return {
        "day": day,
        "task_type": normalized_type or "ALL",
        "unfinished_only": unfinished_only,
        "total_tasks": len(tasks),
        "people": people,
    }


@_tool()
async def get_tasks_this_week(
    week: str = "current",
    week_start: str | None = None,
    user_ref: str | None = None,
    department_ref: str | None = None,
    task_type: str | None = None,
    unfinished_only: bool = False,
) -> Any:
    """
    Get tasks for a whole week, grouped by day and then by person.

    Use this for "detyrat e kesaj jave" or "detyrat e javes tjeter". week is current or next,
    or pass week_start as YYYY-MM-DD. task_type filters by badge: 1H, P, BLL, R1, GA, ALL.
    """
    normalized_type = _normalize_task_type(task_type)
    user_id = await _resolve_user_id(user_ref, department_ref)
    department_id = await _resolve_department_id(department_ref)
    monday, sunday, window_from, window_to = _week_bounds(_week_start(week_start, week))
    tasks = await _request(
        "GET",
        "/api/tasks",
        params={
            "assigned_to": user_id,
            "department_id": department_id,
            "window_from": window_from,
            "window_to": window_to,
            "include_done": not unfinished_only,
        },
    )
    if unfinished_only:
        tasks = [task for task in tasks if _task_is_open(task)]
    tasks = [task for task in tasks if _task_matches_type(task, normalized_type)]
    users_by_id = await _users_by_id()
    today = datetime.now(_local_tz()).date()
    days: list[dict[str, Any]] = []
    for offset in range(7):
        day = monday + timedelta(days=offset)
        day_tasks = [task for task in tasks if _effective_task_date(task) == day]
        if not day_tasks and offset >= 5:
            continue
        days.append(
            {
                "date": day.isoformat(),
                "weekday": day.strftime("%A"),
                "total_tasks": len(day_tasks),
                "people": _group_tasks_by_person(day_tasks, users_by_id, today),
            }
        )
    return {
        "week_start": monday.isoformat(),
        "week_end": sunday.isoformat(),
        "task_type": normalized_type or "ALL",
        "total_tasks": len(tasks),
        "days": days,
    }


@_tool()
async def get_all_open_tasks_by_person(
    department_ref: str | None = None,
    task_type: str | None = None,
    max_tasks_per_person: int = 50,
) -> Any:
    """
    Get every open (not DONE) task for every person, grouped by person.

    Use this for "te gjitha detyrat e hapura per secilin person". Optionally scope to a
    department or a task_type badge (1H, P, BLL, R1, GA). Overdue tasks include days_late.
    """
    normalized_type = _normalize_task_type(task_type)
    department_id = await _resolve_department_id(department_ref)
    tasks = await _request(
        "GET",
        "/api/tasks",
        params={"department_id": department_id, "include_done": False},
    )
    tasks = [task for task in tasks if _task_matches_type(task, normalized_type)]
    people = _group_tasks_by_person(tasks, await _users_by_id())
    for person in people:
        person["tasks"] = person["tasks"][: max(1, max_tasks_per_person)]
    return {
        "task_type": normalized_type or "ALL",
        "total_open_tasks": len(tasks),
        "people_count": len(people),
        "people": people,
    }


@_tool()
async def get_overdue_tasks(
    user_ref: str | None = None,
    department_ref: str | None = None,
) -> Any:
    """Get unfinished tasks whose due date has passed, grouped by person, with days_late and the original due date."""
    user_id = await _resolve_user_id(user_ref, department_ref)
    department_id = await _resolve_department_id(department_ref)
    today = datetime.now(_local_tz()).date()
    tz = _local_tz()
    due_before = datetime.combine(today, datetime_time.min, tzinfo=tz) - timedelta(microseconds=1)
    tasks = await _request(
        "GET",
        "/api/tasks",
        params={
            "assigned_to": user_id,
            "department_id": department_id,
            "due_to": due_before.isoformat(),
            "include_done": False,
        },
    )
    tasks = [task for task in tasks if _task_overdue_days(task, today)]
    return {
        "as_of": today.isoformat(),
        "total_overdue": len(tasks),
        "people": _group_tasks_by_person(tasks, await _users_by_id(), today),
    }


@_tool()
async def get_weekly_plan(
    week: str = "current",
    week_start: str | None = None,
    department_ref: str | None = None,
) -> Any:
    """
    Get the stored weekly plan for a week (and department). Falls back to the computed
    weekly table grid when no stored plan exists yet.

    Use this for "plani i javes / plani i javes tjeter".
    """
    department_id = await _resolve_department_id(department_ref)
    monday = _week_start(week_start, week)
    plans = await _request(
        "GET",
        "/api/planners/weekly-plans",
        params={"department_id": department_id, "week_start": monday},
    )
    if plans:
        return {"week_start": monday, "source": "stored_plan", "plans": plans}
    table = await _request(
        "GET",
        "/api/planners/weekly-table",
        params={"week_start": monday, "department_id": department_id},
    )
    return {"week_start": monday, "source": "weekly_table", "plans": [], "weekly_table": table}


@_tool()
async def save_weekly_plan(
    department_ref: str,
    content_json: str,
    week: str = "next",
    week_start: str | None = None,
    finalize: bool | None = None,
) -> Any:
    """
    Create or update the stored weekly plan for a department and week.

    content_json is the plan payload as a JSON object string. If a plan already exists
    for that week it is updated, otherwise a new one is created. week defaults to next.
    Set finalize=true only when the user says the plan is final.
    """
    department_id = await _resolve_department_id(department_ref)
    content = _parse_json_arg(content_json, default=None)
    if not isinstance(content, dict):
        raise ValueError("content_json must be a JSON object.")
    monday_iso = _week_start(week_start, week)
    monday, sunday, _, _ = _week_bounds(monday_iso)
    existing = await _request(
        "GET",
        "/api/planners/weekly-plans",
        params={"department_id": department_id, "week_start": monday_iso},
    )
    if existing:
        plan_id = existing[0]["id"]
        payload = {"content": content}
        if finalize is not None:
            payload["is_finalized"] = finalize
        plan = await _request("PATCH", f"/api/planners/weekly-plans/{plan_id}", json=payload)
        return {"action": "updated", "plan": plan}
    plan = await _request(
        "POST",
        "/api/planners/weekly-plans",
        json={
            "department_id": department_id,
            "start_date": monday.isoformat(),
            "end_date": sunday.isoformat(),
            "content": content,
            "is_finalized": finalize,
        },
    )
    return {"action": "created", "plan": plan}


@_tool()
async def get_plan_vs_actual(
    department_ref: str,
    week: str = "current",
    week_start: str | None = None,
    compare_to: Literal["actual", "final"] = "actual",
) -> Any:
    """
    Compare the planned week (snapshot) with what actually happened.

    compare_to=actual compares against the live state; compare_to=final compares against
    the end-of-week snapshot. Requires a department.
    """
    department_id = await _resolve_department_id(department_ref)
    monday = _week_start(week_start, week)
    return await _request(
        "GET",
        f"/api/planners/weekly-snapshots/plan-vs-{compare_to}",
        params={"department_id": department_id, "week_start": monday},
    )


async def _weekly_realization(
    department_ref: str,
    week_start: str | None,
) -> tuple[str, str, dict[str, Any]]:
    department_id = await _resolve_department_id(department_ref)
    if not department_id:
        raise ValueError("department_ref is required.")
    monday = _week_start(week_start)
    result = await _request(
        "GET",
        "/api/realization/weekly",
        params={"department_id": department_id, "week_start": monday},
    )
    if not isinstance(result, dict):
        raise RuntimeError("Primeflow returned an invalid weekly Realization response.")
    return department_id, monday, result


@_tool()
async def get_weekly_realization(
    department_ref: str,
    week_start: str | None = None,
) -> Any:
    """
    Read the official weekly Realization workflow for a department.

    Returns PLANNED/FINAL availability, period status, deterministic person results,
    evidence, questions, and department totals. It does not calculate grades in MCP.
    """
    _, _, result = await _weekly_realization(department_ref, week_start)
    return result


@_tool()
async def calculate_weekly_realization(
    department_ref: str,
    week_start: str | None = None,
) -> Any:
    """
    Explicitly calculate or recalculate an unlocked weekly Realization period.

    Call only when the user asks to calculate. Primeflow requires official PLANNED
    and FINAL snapshots and enforces manager/admin permissions and review locks.
    """
    department_id = await _resolve_department_id(department_ref)
    if not department_id:
        raise ValueError("department_ref is required.")
    monday = _week_start(week_start)
    return await _request(
        "POST",
        "/api/realization/weekly/calculate",
        params={"department_id": department_id, "week_start": monday},
    )


@_tool()
async def review_weekly_realization_person(
    department_ref: str,
    user_ref: str,
    week_start: str | None = None,
    final_level: Literal["A+", "A", "B", "C", "M", "D", "E"] | None = None,
    final_symbol: Literal["+", "+/-", "-"] | None = None,
    manager_comment: str | None = None,
    override_reason: str | None = None,
    question_values_json: str | None = None,
) -> Any:
    """
    Review one calculated employee result using Primeflow's manager workflow.

    Omit final fields to accept the suggestion. Supply level and symbol together;
    an override_reason is mandatory when either final value differs.
    question_values_json may contain manager-confirmed answers keyed by stable
    Realization question keys.
    """
    department_id, _, weekly = await _weekly_realization(department_ref, week_start)
    user_id = await _resolve_user_id(user_ref, department_ref)
    if not user_id:
        raise ValueError("user_ref is required.")
    people = weekly.get("people") or []
    matches = [person for person in people if str(person.get("user_id")) == user_id]
    if len(matches) != 1:
        raise ValueError(
            f"No calculated Realization result exists for user {user_ref} in department {department_id}."
        )
    question_values = _parse_json_arg(question_values_json, default={})
    if not isinstance(question_values, dict):
        raise ValueError("question_values_json must be a JSON object.")
    result = matches[0]
    return await _request(
        "POST",
        f"/api/realization/periods/{weekly['period']['id']}/results/{result['id']}/review",
        json={
            "final_level": final_level,
            "final_symbol": final_symbol,
            "manager_comment": manager_comment,
            "override_reason": override_reason,
            "question_values": question_values,
        },
    )


@_tool()
async def add_realization_observation(
    department_ref: str,
    user_ref: str,
    category: Literal[
        "EXTRA_TASK",
        "HELPED_COLLEAGUE",
        "PROPOSAL",
        "TIME_SAVED",
        "QUALITY",
        "DELAY",
        "ABSENCE",
        "MISSED_MEETING",
        "BLOCKER",
        "REPEATED_PROBLEM",
        "PRIORITY_CHANGE",
        "OTHER",
    ],
    marker: Literal["POSITIVE", "NEUTRAL", "NEGATIVE", "DIAMOND"],
    comment: str,
    week_start: str | None = None,
    task_id: str | None = None,
    observation_kind: Literal["REQUESTED_EXTRA_TASK", "COMPLETED_EXTRA_TASK"] | None = None,
    helped_user_ref: str | None = None,
    affected_user_ref: str | None = None,
    impact_level: Literal["MINOR", "MAJOR", "MULTIPLE_PEOPLE"] | None = None,
    impact_minutes: int | None = None,
    repeat_key: str | None = None,
    high_impact: bool | None = None,
    replaces_unfinished_planned_task: bool | None = None,
    duplicate: bool | None = None,
    visibility: Literal[
        "PRIVATE_MANAGER", "PERSON_AND_MANAGER", "TEAM_AGGREGATE"
    ] = "PERSON_AND_MANAGER",
) -> Any:
    """
    Append a Realization observation without changing task/planner data.

    Staff submissions remain unverified. A completed additional task can affect
    A/A+ only after verification and explicit duplicate=false and
    replaces_unfinished_planned_task=false evidence.
    """
    _, _, weekly = await _weekly_realization(department_ref, week_start)
    user_id = await _resolve_user_id(user_ref, department_ref)
    if not user_id:
        raise ValueError("user_ref is required.")
    helped_user_id = await _resolve_user_id(helped_user_ref, department_ref)
    affected_user_id = await _resolve_user_id(affected_user_ref, department_ref)
    evidence = {
        key: value
        for key, value in {
            "kind": observation_kind,
            "helped_user_id": helped_user_id,
            "affected_user_id": affected_user_id,
            "impact_level": impact_level,
            "high_impact": high_impact,
            "replaces_unfinished_planned_task": replaces_unfinished_planned_task,
            "duplicate": duplicate,
        }.items()
        if value is not None
    }
    return await _request(
        "POST",
        "/api/realization/observations",
        json={
            "period_id": weekly["period"]["id"],
            "scope_type": "TASK" if task_id else "PERSON",
            "task_id": task_id,
            "user_id": user_id,
            "department_id": weekly["period"]["department_id"],
            "marker": marker,
            "category": category,
            "impact_minutes": impact_minutes,
            "repeat_key": repeat_key,
            "comment": comment,
            "evidence_json": evidence,
            "visibility": visibility,
        },
    )


@_tool()
async def verify_realization_observation(
    observation_id: str,
    comment: str | None = None,
) -> Any:
    """Verify one active Realization observation as a manager/admin append-only event."""
    return await _request(
        "POST",
        f"/api/realization/observations/{observation_id}/verify",
        json={"comment": comment},
    )


@_tool()
async def void_realization_observation(observation_id: str, reason: str) -> Any:
    """Void an observation with a required reason; Primeflow retains its audit history."""
    if not reason.strip():
        raise ValueError("reason is required.")
    return await _request(
        "POST",
        f"/api/realization/observations/{observation_id}/void",
        json={"reason": reason},
    )


@_tool()
async def approve_weekly_realization(
    department_ref: str,
    week_start: str | None = None,
) -> Any:
    """Approve a fully reviewed weekly Realization period. Admin permission is required."""
    _, _, weekly = await _weekly_realization(department_ref, week_start)
    return await _request(
        "POST", f"/api/realization/periods/{weekly['period']['id']}/approve"
    )


@_tool()
async def lock_weekly_realization(
    department_ref: str,
    week_start: str | None = None,
) -> Any:
    """
    Permanently lock an approved weekly Realization period.

    Call only on an explicit lock request. Locked periods reject recalculation,
    review changes, observation mutations, and result changes.
    """
    _, _, weekly = await _weekly_realization(department_ref, week_start)
    return await _request(
        "POST", f"/api/realization/periods/{weekly['period']['id']}/lock"
    )


@_tool()
async def prepare_next_week_plan(department_ref: str | None = None) -> Any:
    """
    Collect everything needed to draft next week's plan in one call.

    Returns: this week's planner table with completion state, all open/overdue tasks per
    person (carryover candidates), leave/holiday blocks and meetings for next week, any
    already-stored next-week plan, and the projects list. Draft the plan from this data,
    then persist it with save_weekly_plan.
    """
    department_id = await _resolve_department_id(department_ref)
    this_monday = _week_start(None, "current")
    next_monday = _week_start(None, "next")
    _, next_sunday, _, _ = _week_bounds(next_monday)

    async def _safe(coro: Any) -> Any:
        try:
            return await coro
        except Exception as exc:
            return {"error": str(exc)}

    (
        current_week_table,
        open_tasks,
        leave_blocks,
        meetings,
        stored_next_plans,
        projects,
    ) = await asyncio.gather(
        _safe(_request(
            "GET",
            "/api/planners/weekly-table",
            params={"week_start": this_monday, "department_id": department_id, "is_this_week": True},
        )),
        _safe(_request(
            "GET",
            "/api/tasks",
            params={"department_id": department_id, "include_done": False},
        )),
        _safe(_request(
            "GET",
            "/api/common-entries/blocks",
            params={
                "type": "PV_FEST",
                "start": next_monday,
                "end": next_sunday.isoformat(),
                "department_id": department_id,
            },
        )),
        _safe(get_common_view_meetings_for_week(week_start=next_monday)),
        _safe(_request(
            "GET",
            "/api/planners/weekly-plans",
            params={"department_id": department_id, "week_start": next_monday},
        )),
        _safe(_request("GET", "/api/projects", params={"department_id": department_id})),
    )
    open_by_person: Any = open_tasks
    if isinstance(open_tasks, list):
        open_by_person = _group_tasks_by_person(open_tasks, await _users_by_id())
    return {
        "this_week_start": this_monday,
        "next_week_start": next_monday,
        "next_week_end": next_sunday.isoformat(),
        "current_week_table": current_week_table,
        "open_tasks_by_person": open_by_person,
        "leave_blocks_next_week": leave_blocks,
        "meetings_next_week": meetings,
        "stored_next_week_plans": stored_next_plans,
        "projects": projects,
        "hint": (
            "Draft next week's plan per person and day (AM/PM), carrying over overdue and open tasks, "
            "avoiding people on leave, keeping meeting times free, then call save_weekly_plan."
        ),
    }


@_tool()
async def get_task_people(task_id: str) -> Any:
    """
    Get everyone involved in a task: assignees, control 1 (the confirmer), control 2
    (alignment users), creator, and department. Use for "kush e ka kontrollin e taskut".
    """
    task = await _request("GET", f"/api/tasks/{task_id}")
    users_by_id = await _users_by_id()
    departments = await _cached_lookup("departments", "/api/departments")

    def _person(user_id: Any) -> dict[str, Any] | None:
        if not user_id:
            return None
        user = users_by_id.get(str(user_id))
        return {"id": str(user_id), "name": _user_label(user) if user else str(user_id)}

    department = next(
        (dept for dept in departments if str(dept.get("id")) == str(task.get("department_id"))),
        None,
    )
    return {
        "task": _compact_task(task),
        "assignees": [
            {"id": str(assignee.get("id")), "name": _user_label(assignee)}
            for assignee in task.get("assignees") or []
        ],
        "primary_assignee": _person(task.get("assigned_to")),
        "control_1_confirmer": _person(task.get("confirmation_assignee_id")),
        "control_2_alignment_users": [
            person for person in (_person(user_id) for user_id in task.get("alignment_user_ids") or []) if person
        ],
        "created_by": _person(task.get("created_by")),
        "department": department,
    }


@_tool()
async def get_person_workload(
    user_ref: str,
    week: str = "current",
    week_start: str | None = None,
) -> Any:
    """
    Get one person's full workload: open tasks, this week's tasks, overdue tasks,
    1H slots, and the projects they are involved in.
    """
    user_id = await _resolve_user_id(user_ref)
    monday, sunday, window_from, window_to = _week_bounds(_week_start(week_start, week))
    today = datetime.now(_local_tz()).date()
    open_tasks, week_tasks = await asyncio.gather(
        _request("GET", "/api/tasks", params={"assigned_to": user_id, "include_done": False}),
        _request(
            "GET",
            "/api/tasks",
            params={"assigned_to": user_id, "window_from": window_from, "window_to": window_to},
        ),
    )
    overdue = [task for task in open_tasks if _task_overdue_days(task, today)]
    one_h = [task for task in open_tasks if task.get("is_1h_report")]
    projects = await _cached_lookup("projects", "/api/projects")
    project_titles = {
        str(project.get("id")): project.get("display_title") or project.get("title")
        for project in projects
    }
    involved_projects = sorted(
        {
            project_titles.get(str(task.get("project_id")), str(task.get("project_id")))
            for task in open_tasks
            if task.get("project_id")
        }
    )
    users_by_id = await _users_by_id()
    return {
        "user": {"id": user_id, "name": _user_label(users_by_id.get(user_id))},
        "week_start": monday.isoformat(),
        "week_end": sunday.isoformat(),
        "counts": {
            "open": len(open_tasks),
            "overdue": len(overdue),
            "one_h": len(one_h),
            "blocked": sum(1 for task in open_tasks if task.get("is_bllok")),
            "personal": sum(1 for task in open_tasks if task.get("is_personal")),
            "this_week": len(week_tasks),
        },
        "open_tasks": [_compact_task(task, today) for task in open_tasks],
        "this_week_tasks": [_compact_task(task, today) for task in week_tasks],
        "projects_involved": involved_projects,
    }


@_tool()
async def get_department_overview(
    department_ref: str,
    week: str = "current",
    week_start: str | None = None,
) -> Any:
    """
    Get a department overview: members with open/overdue/1H/blocked task counts,
    and the department's projects with phase/status.
    """
    department_id = await _resolve_department_id(department_ref)
    monday = _week_start(week_start, week)
    users, open_tasks, projects = await asyncio.gather(
        _cached_lookup("users", "/api/users"),
        _request("GET", "/api/tasks", params={"department_id": department_id, "include_done": False}),
        _request("GET", "/api/projects", params={"department_id": department_id}),
    )
    members = [user for user in users if str(user.get("department_id")) == department_id]
    users_by_id = {str(user.get("id")): user for user in users}
    people = _group_tasks_by_person(open_tasks, users_by_id)
    by_user = {person["user_id"]: person for person in people}
    today = datetime.now(_local_tz()).date()
    member_rows = []
    for member in members:
        member_id = str(member.get("id"))
        person = by_user.get(member_id)
        person_tasks = person["tasks"] if person else []
        member_rows.append(
            {
                "id": member_id,
                "name": _user_label(member),
                "role": member.get("role"),
                "open": len(person_tasks),
                "overdue": person["overdue_count"] if person else 0,
                "one_h": sum(1 for task in person_tasks if task.get("type") == "1H"),
                "blocked": sum(1 for task in person_tasks if task.get("type") == "BLL"),
            }
        )
    return {
        "department_id": department_id,
        "week_start": monday,
        "as_of": today.isoformat(),
        "members": member_rows,
        "total_open_tasks": len(open_tasks),
        "projects": [
            {
                "id": project.get("id"),
                "title": project.get("display_title") or project.get("title"),
                "current_phase": project.get("current_phase"),
                "status": project.get("status"),
                "progress_percentage": project.get("progress_percentage"),
            }
            for project in (projects if isinstance(projects, list) else [])
        ],
    }


@_tool()
async def get_task_steps(task_id: str) -> Any:
    """Get a task with its step checklists and items. Use for "detyra me hapat/steps"."""
    task, checklists = await asyncio.gather(
        _request("GET", f"/api/tasks/{task_id}"),
        _request("GET", "/api/checklists", params={"task_id": task_id}),
    )
    return {"task": _compact_task(task), "checklists": checklists}


@_tool()
async def add_task_step(
    task_id: str,
    title: str,
    comment: str | None = None,
    checklist_title: str = "Steps",
) -> Any:
    """Add a step (checklist item) to a task. Creates the task's checklist first if it has none."""
    checklists = await _request("GET", "/api/checklists", params={"task_id": task_id})
    if checklists:
        checklist_id = checklists[0]["id"]
    else:
        checklist = await _request(
            "POST",
            "/api/checklists",
            json={"task_id": task_id, "title": checklist_title},
        )
        checklist_id = checklist["id"]
    item = await _request(
        "POST",
        "/api/checklist-items",
        json={"checklist_id": checklist_id, "title": title, "comment": comment},
    )
    return {"checklist_id": checklist_id, "item": item}


@_tool()
async def set_task_step_done(item_id: str, done: bool = True) -> Any:
    """Mark a task step (checklist item) as done or not done."""
    return await _request("PATCH", f"/api/checklist-items/{item_id}", json={"is_checked": done})


@_tool()
async def schedule_task(
    task_id: str,
    start_date: str | None = None,
    due_date: str | None = None,
    finish_period: Literal["AM", "PM"] | None = None,
    one_h_report_slot: str | None = None,
) -> Any:
    """
    Schedule a task onto days and slots: start/due dates (YYYY-MM-DD, sot, neser, or ISO
    datetime), AM/PM finish period, and the 1H slot (10:00, 11:00, 11:50, 14:20, 16:00).
    """
    if one_h_report_slot and one_h_report_slot not in ONE_H_SLOTS:
        raise ValueError("one_h_report_slot must be 10:00, 11:00, 11:50, 14:20, or 16:00")
    payload = {
        "start_date": _parse_date_arg(start_date),
        "due_date": _parse_date_arg(due_date),
        "finish_period": finish_period,
        "one_h_report_slot": one_h_report_slot,
        "is_1h_report": True if one_h_report_slot else None,
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    if not payload:
        raise ValueError("Provide at least one of start_date, due_date, finish_period, or one_h_report_slot.")
    return await _request("PATCH", f"/api/tasks/{task_id}", json=payload)


@_tool()
async def get_weekly_report(
    week: str = "current",
    week_start: str | None = None,
    department_ref: str | None = None,
    user_ref: str | None = None,
) -> Any:
    """
    Get a weekly execution report: for each workday, the planned tasks, what was done,
    and what is late, plus per-person totals for the week.
    """
    department_id = await _resolve_department_id(department_ref)
    user_id = await _resolve_user_id(user_ref, department_ref)
    monday, sunday, _, _ = _week_bounds(_week_start(week_start, week))
    weekdays = [monday + timedelta(days=offset) for offset in range(5)]
    reports = await asyncio.gather(
        *(
            _request(
                "GET",
                "/api/reports/daily",
                params={"day": day.isoformat(), "department_id": department_id, "user_id": user_id},
            )
            for day in weekdays
        )
    )
    users_by_id = await _users_by_id()
    per_person: dict[str, dict[str, int]] = {}
    days_out = []
    for day, report in zip(weekdays, reports):
        items = list(report.get("tasks_today") or [])
        overdue_items = list(report.get("tasks_overdue") or [])
        done = 0
        for item in items:
            task = item.get("task") or {}
            if not _task_is_open(task):
                done += 1
            for assignee in task.get("assignees") or [{"id": task.get("assigned_to")}]:
                if not assignee.get("id"):
                    continue
                stats = per_person.setdefault(
                    _user_label(users_by_id.get(str(assignee["id"]))),
                    {"planned": 0, "done": 0, "overdue": 0},
                )
                stats["planned"] += 1
                if not _task_is_open(task):
                    stats["done"] += 1
        for item in overdue_items:
            task = item.get("task") or {}
            for assignee in task.get("assignees") or [{"id": task.get("assigned_to")}]:
                if not assignee.get("id"):
                    continue
                stats = per_person.setdefault(
                    _user_label(users_by_id.get(str(assignee["id"]))),
                    {"planned": 0, "done": 0, "overdue": 0},
                )
                stats["overdue"] += 1
        days_out.append(
            {
                "date": day.isoformat(),
                "weekday": day.strftime("%A"),
                "planned": len(items),
                "done": done,
                "overdue_carried": len(overdue_items),
                "system_overdue": len(report.get("system_overdue") or []),
            }
        )
    return {
        "week_start": monday.isoformat(),
        "week_end": sunday.isoformat(),
        "days": days_out,
        "per_person": [
            {"name": name, **stats}
            for name, stats in sorted(per_person.items(), key=lambda entry: entry[0].lower())
        ],
    }


@_tool()
async def export_report(
    kind: Literal[
        "tasks",
        "open_tasks",
        "weekly_planner",
        "daily_report",
        "plan_vs_actual",
        "plan_vs_final",
        "common_view",
    ],
    week_start: str | None = None,
    day: str | None = None,
    department_ref: str | None = None,
    user_ref: str | None = None,
) -> Any:
    """
    Build a download URL for a Primeflow XLSX export (tasks, open tasks, weekly planner,
    daily report, plan-vs-actual/final, common view). The link requires a logged-in
    Primeflow session, so share it for the user to open in their browser.
    """
    department_id = await _resolve_department_id(department_ref)
    user_id = await _resolve_user_id(user_ref, department_ref)
    paths = {
        "tasks": "/api/exports/tasks.xlsx",
        "open_tasks": "/api/exports/open-tasks.xlsx",
        "weekly_planner": "/api/exports/weekly-planner.xlsx",
        "daily_report": "/api/exports/daily-report.xlsx",
        "plan_vs_actual": "/api/exports/weekly-plan-vs-actual.xlsx",
        "plan_vs_final": "/api/exports/weekly-plan-vs-final.xlsx",
        "common_view": "/api/exports/common.xlsx",
    }
    params: dict[str, Any] = {"department_id": department_id, "user_id": user_id}
    if kind in {"weekly_planner", "plan_vs_actual", "plan_vs_final", "common_view"}:
        params["week_start"] = _week_start(week_start, "current")
    if kind == "daily_report":
        params["day"] = _parse_day(day).isoformat()
    if kind in {"plan_vs_actual", "plan_vs_final"} and not department_id:
        raise ValueError("plan_vs_actual/plan_vs_final exports require a department_ref.")
    query = "&".join(
        f"{key}={value}" for key, value in params.items() if value is not None
    )
    url = f"{API_BASE_URL}{paths[kind]}" + (f"?{query}" if query else "")
    return {
        "kind": kind,
        "url": url,
        "note": "Open this link while logged in to Primeflow; the export endpoint requires authentication.",
    }


@_tool()
async def health_check() -> dict[str, Any]:
    """Read-only functional health check for MCP, authentication, and Common View."""
    result: dict[str, Any] = {
        "status": "degraded",
        "mcp_server_time": datetime.now(timezone.utc).isoformat(),
        "api_host": API_BASE_URL,
        "authentication_status": "failed",
        "primeflow_api_health": "failed",
        "common_view_reachable": False,
        "build_sha": os.getenv("APP_BUILD_SHA", "unknown"),
        "application_timezone": APP_TIMEZONE,
        "report_timezone": os.getenv("PRIMEFLOW_REPORT_TIMEZONE", "Europe/Tirane"),
    }
    try:
        await _access_token()
        result["authentication_status"] = "ok"
        health = await _request("GET", "/health")
        result["primeflow_api_health"] = "ok" if health else "failed"
        view = await _request("GET", "/api/common-view", params={"include": "tasks", "max_items_per_bucket": 1})
        result["common_view_reachable"] = isinstance(view, dict)
        result["status"] = "ok" if result["common_view_reachable"] else "degraded"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    return result


# ---------------------------------------------------------------- GA assistant tools (assistant profile)
#
# Item ids carry their source: pf_task:<uuid>, pf_meeting:<uuid>@YYYY-MM-DD,
# ms_event:<id>, todo:<list_id>::<task_id>. Times are GA_TIMEZONE (default
# Europe/Belgrade); dates and datetimes are ISO 8601.


@_tool(read_only=True)
async def ga_agenda(start: str, end: str, include_untimed: bool = False) -> Any:
    """
    GA's agenda for the window [start, end): GA TASKS, BZ ME GA TASKS (koha_bz, bz_with),
    tasks with the F symbol, PrimeFlow meetings (TAK INT/EXT), Outlook events and
    Microsoft To Do reminders of info@ (not "Flagged Emails"), GA's iPhone reminders from the
    GA Time Table "R:" rows (source iphone_sync, id tt:..., read-only) and Discord messages
    that mention GA (kind DISCORD, id dc:..., untimed on the day written), each with a
    source-prefixed id. A reminder in both To Do and iPhone Sync is listed once (the To Do
    item, with the tt: id in linked_ids). To Do/iPhone reminders without a date are untimed
    items of today until done.

    start/end: ISO 8601 (e.g. 2026-11-19T08:00:00+01:00). Items without a time are left
    out unless include_untimed=true (then the untimed open items of the covered days are added).
    Use this for the scheduled reports (08:00, 09:00, 11:50, 14:20, 16:00).
    """
    return await _request("GET", "/api/ga-assistant/agenda", params={"start": start, "end": end, "include_untimed": include_untimed})


@_tool(read_only=True)
async def ga_leftovers(as_of: str | None = None) -> Any:
    """
    Every unfinished item due before as_of (ISO 8601, default now): earlier days and
    earlier today, oldest first, with source and days late. Unmarked meetings count
    only on their own day; iPhone "R:" reminders still open on the phone and Discord
    mentions not yet marked seen/done are included.
    """
    return await _request("GET", "/api/ga-assistant/leftovers", params={"as_of": as_of})


@_tool(read_only=True)
async def ga_untimed_today(date: str | None = None) -> Any:
    """
    Open items without a time for a day (YYYY-MM-DD, default today): GA TASKS without koha_bz,
    To Do and iPhone reminders without a time ("R: 00:00", or no date at all: shown every day
    until done) and open Discord mentions of that day.
    """
    return await _request("GET", "/api/ga-assistant/untimed", params={"day": _parse_date_arg(date) if date else None})


@_tool(read_only=False, destructive=False, idempotent=True)
async def ga_item_done(item_id: str, comment: str | None = None, override_reason: str | None = None) -> Any:
    """
    Mark an agenda item as done ("4 kryer").
    PrimeFlow task -> DONE (like the Done/Confirm button). Normal tasks (not 1H/special ones)
    need GA's own result comment before closing: pass it as comment (saved together with the
    close). If PrimeFlow answers that a comment is required, ask GA for one; override_reason
    is only for an explicit exception.
    BZ where GA is not an assignee -> records "BZ u mbajt" (comment + audit) without closing
    the colleague's task. Meeting -> "Mbajtur". To Do -> completed. Discord mention (dc:) -> done.
    Outlook events and iPhone reminders (tt:, can_complete=false: the iPhone Sync is one-way)
    are read-only: GA completes those on the iPhone.
    """
    return await _request(
        "POST",
        "/api/ga-assistant/items/done",
        json={"item_id": item_id, "comment": comment, "override_reason": override_reason},
    )


@_tool(read_only=False, destructive=False)
async def ga_item_postpone(
    item_id: str,
    new_date: str,
    new_time: str | None = None,
    reason_code: str | None = None,
    reason_comment: str | None = None,
) -> Any:
    """
    Postpone an item ("5 shtyje"). new_date: YYYY-MM-DD or sot/neser; new_time: HH:MM (optional).
    PrimeFlow tasks change due_date (original_due_date is kept); tasks not assigned to GA may
    require reason_code + reason_comment (the backend says so). To Do changes its date/reminder.
    BZ items and meetings cannot be postponed from here.
    """
    return await _request(
        "POST",
        "/api/ga-assistant/items/postpone",
        json={
            "item_id": item_id,
            "new_date": _parse_date_arg(new_date),
            "new_time": new_time,
            "reason_code": reason_code,
            "reason_comment": reason_comment,
        },
    )


@_tool(read_only=False, destructive=False, idempotent=True)
async def ga_item_set_time(item_id: str, time: str | None = None, date: str | None = None) -> Any:
    """
    Set, change or clear (time=null) an item's time ("2 në 11:00").
    PrimeFlow tasks/BZ: a per-day time for GA's agenda only (due date and BZ template stay
    unchanged); date defaults to the item's day or today. To Do: sets/clears the reminder time.
    """
    return await _request(
        "POST",
        "/api/ga-assistant/items/set-time",
        json={"item_id": item_id, "time": time, "day": _parse_date_arg(date) if date else None},
    )


@_tool(read_only=False, destructive=True, idempotent=True)
async def ga_item_remove_from_day(item_id: str, reason: str, date: str | None = None) -> Any:
    """Soft-remove an item from GA's agenda for one day (default today; meetings use their own day). Nothing is deleted."""
    return await _request(
        "POST",
        "/api/ga-assistant/items/remove-from-day",
        json={"item_id": item_id, "reason": reason, "day": _parse_date_arg(date) if date else None},
    )


@_tool(read_only=False, destructive=False)
async def ga_add_comment(item_id: str, text: str) -> Any:
    """Add a comment: PrimeFlow task -> appended to GA's task comment; To Do -> appended to its notes."""
    return await _request("POST", "/api/ga-assistant/items/comment", json={"item_id": item_id, "text": text})


@_tool(read_only=True)
async def todo_list(
    list_name: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    include_completed: bool = False,
) -> Any:
    """List Microsoft To Do items of info@ (synced with GA's iPhone Reminders), optionally by list and due-date range."""
    return await _request(
        "GET",
        "/api/ga-assistant/todo",
        params={
            "list_name": list_name,
            "from": _parse_date_arg(from_date) if from_date else None,
            "to": _parse_date_arg(to_date) if to_date else None,
            "include_completed": include_completed,
        },
    )


@_tool(read_only=False, destructive=False)
async def todo_create(
    title: str,
    due_date: str | None = None,
    time: str | None = None,
    notes: str | None = None,
    list_name: str | None = None,
) -> Any:
    """Create a To Do item (iPhone reminder). due_date YYYY-MM-DD/sot/neser; time HH:MM needs due_date. Without list_name it goes to the list iPhone Reminders syncs into."""
    return await _request(
        "POST",
        "/api/ga-assistant/todo",
        json={
            "title": title,
            "due_date": _parse_date_arg(due_date) if due_date else None,
            "time": time,
            "notes": notes,
            "list_name": list_name,
        },
    )


@_tool(read_only=False, destructive=False, idempotent=True)
async def todo_update(
    id: str,
    title: str | None = None,
    due_date: str | None = None,
    time: str | None = None,
    clear_time: bool = False,
    notes: str | None = None,
) -> Any:
    """Update a To Do item (id from todo_list/ga_agenda). clear_time=true removes the reminder time; notes replaces the notes but keeps the steps."""
    return await _request(
        "PATCH",
        f"/api/ga-assistant/todo/{_todo_path(id)}",
        json={
            "title": title,
            "due_date": _parse_date_arg(due_date) if due_date else None,
            "time": time,
            "clear_time": clear_time,
            "notes": notes,
        },
    )


@_tool(read_only=False, destructive=False, idempotent=True)
async def todo_complete(id: str) -> Any:
    """Mark a To Do item as completed (ticked on iPhone)."""
    return await _request("POST", f"/api/ga-assistant/todo/{_todo_path(id)}/complete")


@_tool(read_only=False, destructive=False, idempotent=True)
async def todo_set_steps(id: str, steps: list[dict[str, Any]]) -> Any:
    """
    Replace the steps of a To Do item: steps=[{"text": "...", "done": false}, ...].
    Steps are stored as checkbox lines in the notes, because iPhone Reminders does not sync To Do checklist items.
    """
    return await _request("PUT", f"/api/ga-assistant/todo/{_todo_path(id)}/steps", json={"steps": steps})


@_tool(read_only=True)
async def ga_time_table(week_start: str | None = None) -> Any:
    """
    The GA Time Table of /admin-tasks for one work week, as GA sees it: the time rows (with
    their notes) and, per day Monday-Friday, the entries in each row - weekly template
    entries plus the iPhone Sync rows ("R: HH:MM: ..." reminders, "CALENDAR ..." events).
    week_start: any date of the week (YYYY-MM-DD or sot/neser; default this week).
    Meetings and tasks are not part of this grid; use ga_agenda for those.
    """
    day = _parse_day(week_start) if week_start else datetime.now(_local_tz()).date()
    monday = day - timedelta(days=day.weekday())
    rows, entries = await asyncio.gather(
        _request("GET", "/api/ga-time-slots/rows"),
        _request("GET", "/api/ga-time-slots", params={"week_start": monday.isoformat()}),
    )

    def plain(value: str | None) -> str:
        text = re.sub(r"<br\s*/?>", "\n", value or "", flags=re.IGNORECASE)
        text = re.sub(r"<[^>]*>", "", text)
        return re.sub(r"[ \t]+", " ", text).strip()

    def display(entry: dict[str, Any]) -> str:
        text = plain(entry.get("content"))
        if entry.get("source_type") == "reminder":
            text = re.sub(r"^\s*REMINDER\s*:?\s*", "R: ", text, flags=re.IGNORECASE)
        return text

    days = [monday + timedelta(days=offset) for offset in range(5)]
    names = ["H", "M", "MR", "E", "P"]
    grid = []
    for row in sorted(rows or [], key=lambda item: item.get("sort_order") or 0):
        start, end = str(row.get("start_time") or "")[:5], str(row.get("end_time") or "")[:5]
        cells = {}
        for index, current in enumerate(days):
            cell = [
                {
                    "text": display(entry),
                    "source": "iphone_sync" if entry.get("source_type") else "template",
                    "kind": entry.get("source_type") or "entry",
                }
                for entry in entries or []
                if str(entry.get("start_time") or "")[:5] == start
                and str(entry.get("end_time") or "")[:5] == end
                and (entry.get("occurrence_date") == current.isoformat()
                     if entry.get("occurrence_date") else entry.get("day_of_week") == index)
            ]
            if cell:
                cells[f"{names[index]} {current.isoformat()}"] = cell
        notes = [plain(comment.get("content")) for comment in (row.get("comments") or []) if plain(comment.get("content"))]
        grid.append({
            "row": row.get("nr_label") or row.get("label") or "",
            "label": row.get("label") or "",
            "time": "pa orë" if start == "00:00" and end == "00:01" else f"{start}-{end}",
            "notes": notes,
            "days": cells,
        })
    return {"week_start": monday.isoformat(), "days": [f"{n} {d.isoformat()}" for n, d in zip(names, days)], "rows": grid}


@_tool(read_only=True)
async def ga_discord_mentions(
    since: str | None = None, until: str | None = None, only_open: bool = True, only_ready: bool = False
) -> Any:
    """
    Discord messages in PrimEx server channels that mention GA (@GA or a role she has) or
    reply to one of her messages, oldest first: who (name + initials, e.g. LH), channel,
    time (Europe/Belgrade), text, message link, attachments and status (new/seen/done).
    reactions: [{emoji, count, users:[{name, initials}]}]. reviewed_by: initials of colleagues
    who approved with ✅ 👍 ✔️ ☑️ (not the author, not GA); ready_for_ga = reviewed_by not empty.
    since/until: ISO 8601 (default: today 00:00 until now). only_open=true hides done ones;
    only_ready=true returns only ready_for_ga messages.
    DMs are never read. Use in the hourly report: "since" = the previous report time.
    """
    return await _request(
        "GET",
        "/api/ga-assistant/discord/mentions",
        params={"since": since, "until": until, "only_open": only_open, "only_ready": only_ready},
    )


@_tool(read_only=False, destructive=False, idempotent=True)
async def ga_discord_mark(id: str, status: str) -> Any:
    """Mark a Discord mention (id dc:<message id>) as "seen" or "done" ("new" undoes it). Nothing changes in Discord."""
    if status not in {"new", "seen", "done"}:
        raise ValueError('status must be "seen", "done" or "new"')
    return await _request("POST", f"/api/ga-assistant/discord/mentions/{id.strip()}/status", json={"status": status})


def _todo_path(item_id: str) -> str:
    from urllib.parse import quote

    value = item_id.strip()
    if not value.startswith("todo:"):
        raise ValueError("To Do ids look like todo:<list_id>::<task_id> (from todo_list or ga_agenda).")
    return quote(value, safe=":")


if __name__ == "__main__":
    _validate_startup_configuration()
    transport = os.getenv("PRIMEFLOW_MCP_TRANSPORT", "stdio")
    if IS_ASSISTANT:
        # The remote connector speaks Streamable HTTP on /mcp behind the HTTPS tunnel.
        mcp.run(transport="streamable-http")
    elif transport == "sse":
        mcp.run(transport="sse")
    else:
        mcp.run()
