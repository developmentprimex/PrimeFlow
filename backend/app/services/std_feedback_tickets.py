from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.std_feedback_ticket import StdFeedbackSyncState, StdFeedbackTicket


logger = logging.getLogger(__name__)
_UNSET = object()


def _std_base_url() -> str:
    return (
        os.getenv("STD_FEEDBACK_API_BASE_URL")
        or os.getenv("STD_PRIMEFLOW_API_BASE_URL")
        or settings.STD_PRIMEFLOW_API_BASE_URL
        or settings.STD_FEEDBACK_API_BASE_URL
        or "https://std.primexeu.com/api/integrations/primeflow/v1"
    ).rstrip("/")


def _std_token() -> str:
    return (
        os.getenv("STD_FEEDBACK_API_TOKEN")
        or settings.STD_FEEDBACK_API_TOKEN
        or os.getenv("STD_PRIMEFLOW_API_TOKEN")
        or settings.STD_PRIMEFLOW_API_TOKEN
        or ""
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _person_label(value: Any) -> str | None:
    if isinstance(value, dict):
        return _stringify(value.get("full_name") or value.get("username") or value.get("email") or value.get("id"))
    return _stringify(value)


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _count(value: Any, fallback: Any) -> int:
    parsed = _int_or_none(value)
    if parsed is not None:
        return max(0, parsed)
    return len(fallback) if isinstance(fallback, list) else 0


def _extract_affected_fields(payload: dict[str, Any]) -> list[str]:
    candidate_keys = (
        "affected_fields",
        "affectedFields",
        "affected_field",
        "affectedField",
        "fields",
        "changed_fields",
        "changedFields",
    )
    containers: list[Any] = [payload]
    order_snapshot = payload.get("order_snapshot_json")
    if isinstance(order_snapshot, dict):
        containers.append(order_snapshot)

    values: list[str] = []
    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in candidate_keys:
            raw_value = container.get(key)
            if raw_value is None:
                continue
            if isinstance(raw_value, list):
                values.extend(str(item).strip() for item in raw_value if str(item).strip())
            elif isinstance(raw_value, dict):
                values.extend(str(item).strip() for item in raw_value.keys() if str(item).strip())
            elif str(raw_value).strip():
                values.append(str(raw_value).strip())

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(value)
    return deduped


def _tickets_payload(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("tickets", "data", "items", "results"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _ticket_payload(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    for key in ("ticket", "data", "item", "result"):
        nested = data.get(key)
        if isinstance(nested, dict):
            return nested
    return data


def _pagination_payload(data: Any) -> dict[str, Any]:
    if isinstance(data, dict) and isinstance(data.get("pagination"), dict):
        return data["pagination"]
    return {}


def is_external_ticket_payload(
    payload: dict[str, Any], domains: list[str] | None = None
) -> bool:
    creator = payload.get("creator") if isinstance(payload.get("creator"), dict) else {}
    email = str(creator.get("email") or payload.get("creator_email") or "").strip().casefold()
    allowed = domains if domains is not None else settings.std_feedback_external_domain_list
    return bool(email) and any(email.endswith(f"@{domain.casefold().lstrip('@')}") for domain in allowed)


def _needs_detail(existing: StdFeedbackTicket | None, summary: dict[str, Any]) -> bool:
    if existing is None:
        return True
    source_updated_at = _parse_datetime(summary.get("updated_at"))
    if source_updated_at is None:
        return False
    current = existing.source_updated_at
    if current is None:
        return True
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if source_updated_at.tzinfo is None:
        source_updated_at = source_updated_at.replace(tzinfo=timezone.utc)
    return source_updated_at != current


def _cursor_from_page(data: Any, rows: list[dict[str, Any]]) -> tuple[str, str] | None:
    pagination = _pagination_payload(data)
    cursor = pagination.get("next_cursor") if isinstance(pagination.get("next_cursor"), dict) else {}
    updated_at = _stringify(cursor.get("after_updated_at"))
    external_id = _stringify(cursor.get("after_id"))
    if updated_at and external_id:
        return updated_at, external_id

    candidates: list[tuple[datetime, str, str]] = []
    for row in rows:
        raw_updated = _stringify(row.get("updated_at"))
        row_id = _stringify(row.get("id"))
        parsed = _parse_datetime(raw_updated)
        if raw_updated and row_id and parsed:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            candidates.append((parsed, row_id, raw_updated))
    if not candidates:
        return None
    _, row_id, raw_updated = max(candidates, key=lambda item: (item[0], item[1]))
    return raw_updated, row_id


class StdFeedbackClient:
    """Small server-only STD client with bounded retries and no credential logging."""

    def __init__(
        self,
        *,
        token: str | None = None,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        resolved_token = token if token is not None else _std_token()
        self._client = httpx.AsyncClient(
            base_url=(base_url or _std_base_url()).rstrip("/"),
            headers={"Authorization": f"Bearer {resolved_token}"},
            timeout=httpx.Timeout(max(1, settings.STD_FEEDBACK_REQUEST_TIMEOUT_SECONDS)),
            transport=transport,
        )

    async def __aenter__(self) -> "StdFeedbackClient":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
        retries = max(1, settings.STD_FEEDBACK_REQUEST_RETRIES)
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                response = await self._client.get(path, params=params)
                response.raise_for_status()
                return response
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    raise
                if attempt + 1 < retries:
                    await asyncio.sleep(0.25 * (2**attempt))
        assert last_error is not None
        raise last_error

    async def health(self) -> dict[str, Any]:
        response = await self._get("/health")
        data = response.json()
        return data if isinstance(data, dict) else {"status": "unknown"}

    async def list_tickets(self, params: dict[str, Any]) -> dict[str, Any]:
        response = await self._get("/feedback-tickets", params=params)
        data = response.json()
        return data if isinstance(data, dict) else {"tickets": data}

    async def get_ticket(self, external_id: str) -> dict[str, Any]:
        response = await self._get(f"/feedback-tickets/{external_id}")
        return _ticket_payload(response.json())

    async def get_file(self, external_id: str, file_id: str) -> httpx.Response:
        return await self._get(f"/feedback-tickets/{external_id}/files/{file_id}")


async def _existing_by_external_ids(
    db: AsyncSession, external_ids: list[str]
) -> dict[str, StdFeedbackTicket]:
    if not external_ids:
        return {}
    rows = (
        await db.execute(select(StdFeedbackTicket).where(StdFeedbackTicket.external_id.in_(external_ids)))
    ).scalars().all()
    return {row.external_id: row for row in rows}


async def _get_sync_state(db: AsyncSession, *, lock: bool = False) -> StdFeedbackSyncState:
    stmt = select(StdFeedbackSyncState).where(StdFeedbackSyncState.key == "default")
    if lock:
        stmt = stmt.with_for_update()
    state = (await db.execute(stmt)).scalar_one_or_none()
    if state is None:
        state = StdFeedbackSyncState(key="default")
        db.add(state)
        await db.flush()
    return state


async def _upsert_std_ticket(
    db: AsyncSession,
    payload: dict[str, Any],
    *,
    existing: StdFeedbackTicket | None | object = _UNSET,
) -> StdFeedbackTicket | None:
    external_id = _stringify(payload.get("id"))
    if not external_id:
        return None
    if existing is _UNSET:
        ticket = (
            await db.execute(select(StdFeedbackTicket).where(StdFeedbackTicket.external_id == external_id))
        ).scalar_one_or_none()
    else:
        ticket = existing
    if ticket is None:
        ticket = StdFeedbackTicket(external_id=external_id)
        db.add(ticket)

    creator = payload.get("creator") if isinstance(payload.get("creator"), dict) else {}
    comments = payload.get("comments") if isinstance(payload.get("comments"), list) else []
    files_value = payload.get("files")
    if not isinstance(files_value, list):
        files_value = payload.get("attachments") if isinstance(payload.get("attachments"), list) else []
    order_snapshot = payload.get("order_snapshot_json")

    ticket.issue_number = _int_or_none(payload.get("issue_number"))
    ticket.order_ticket_number = _stringify(payload.get("related_ticket_number"))
    ticket.title = _stringify(payload.get("title"))
    ticket.description = _stringify(payload.get("description"))
    ticket.affected_fields = _extract_affected_fields(payload)
    ticket.category = _stringify(payload.get("category"))
    ticket.priority = _stringify(payload.get("priority"))
    ticket.status = _stringify(payload.get("status"))
    ticket.dashboard_area = _stringify(payload.get("dashboard_area"))
    ticket.creator_id = _stringify(creator.get("id"))
    ticket.reporter_username = _stringify(creator.get("username"))
    ticket.reporter_email = _stringify(creator.get("email"))
    ticket.assigned_admin = _person_label(payload.get("assigned_admin"))
    ticket.closed_by = _person_label(payload.get("closed_by"))
    ticket.related_order_id = _stringify(payload.get("related_order_id"))
    ticket.order_snapshot_json = order_snapshot if isinstance(order_snapshot, dict) else {}
    ticket.comment_count = _count(payload.get("comment_count"), comments)
    ticket.file_count = _count(payload.get("file_count"), files_value)
    ticket.is_external = is_external_ticket_payload(payload)
    ticket.reported_at = _parse_datetime(payload.get("created_at"))
    ticket.source_updated_at = _parse_datetime(payload.get("updated_at"))
    ticket.closed_at = _parse_datetime(payload.get("closed_at"))
    ticket.raw = payload
    ticket.synced_at = datetime.now(timezone.utc)
    return ticket


async def sync_std_feedback_tickets(
    db: AsyncSession,
    *,
    limit: int = 100,
    client: StdFeedbackClient | None = None,
) -> dict[str, Any]:
    if client is None and not _std_token():
        state = await _get_sync_state(db)
        state.last_sync_error = "STD feedback API token is not configured"
        await db.commit()
        return {"ok": False, "reason": "missing_token", "synced": 0, "pages": 0}

    state = await _get_sync_state(db, lock=True)
    initial_sync = not (state.after_updated_at and state.after_id)
    params: dict[str, Any] = {"limit": max(1, min(limit, 200))}
    if not initial_sync:
        params["after_updated_at"] = state.after_updated_at.isoformat()
        params["after_id"] = state.after_id

    owns_client = client is None
    active_client = client or StdFeedbackClient()
    synced = 0
    pages = 0
    seen_cursors: set[tuple[str, str]] = set()
    try:
        while True:
            data = await active_client.list_tickets(params)
            rows = _tickets_payload(data)
            external_ids = [value for row in rows if (value := _stringify(row.get("id")))]
            existing_by_id = await _existing_by_external_ids(db, external_ids)

            for summary in rows:
                external_id = _stringify(summary.get("id"))
                if not external_id:
                    continue
                existing = existing_by_id.get(external_id)
                payload = summary
                if _needs_detail(existing, summary):
                    detail = await active_client.get_ticket(external_id)
                    payload = {**summary, **detail}
                if is_external_ticket_payload(payload) or existing is not None:
                    await _upsert_std_ticket(db, payload, existing=existing)
                    if is_external_ticket_payload(payload):
                        synced += 1

            pagination = _pagination_payload(data)
            cursor = _cursor_from_page(data, rows)
            if cursor:
                parsed_cursor = _parse_datetime(cursor[0])
                if parsed_cursor is None:
                    raise ValueError("STD returned an invalid updated_at cursor")
                state.after_updated_at = parsed_cursor
                state.after_id = cursor[1]
            state.last_sync_error = None
            await db.commit()
            pages += 1

            if not pagination.get("has_more"):
                break
            if cursor is None:
                raise ValueError("STD pagination has_more=true without a usable cursor")
            if cursor in seen_cursors:
                raise ValueError("STD pagination repeated the same cursor")
            seen_cursors.add(cursor)
            params["after_updated_at"], params["after_id"] = cursor

        state.last_successful_sync_at = datetime.now(timezone.utc)
        state.last_sync_error = None
        await db.commit()
        return {"ok": True, "synced": synced, "pages": pages, "initial_sync": initial_sync}
    except Exception as exc:
        await db.rollback()
        failure_state = await _get_sync_state(db)
        failure_state.last_sync_error = f"{type(exc).__name__}: {exc}"[:2000]
        await db.commit()
        logger.error("std_feedback_ticket_sync_failed: %s", type(exc).__name__)
        return {"ok": False, "reason": "sync_failed", "synced": synced, "pages": pages}
    finally:
        if owns_client:
            await active_client.close()


async def refresh_std_ticket_detail(
    db: AsyncSession,
    ticket: StdFeedbackTicket,
    *,
    client: StdFeedbackClient | None = None,
) -> StdFeedbackTicket:
    if client is None and not _std_token():
        return ticket
    owns_client = client is None
    active_client = client or StdFeedbackClient()
    try:
        detail = await active_client.get_ticket(ticket.external_id)
        merged = {**(ticket.raw or {}), **detail}
        await _upsert_std_ticket(db, merged, existing=ticket)
        await db.commit()
        await db.refresh(ticket)
    except Exception:
        await db.rollback()
        logger.warning("std_feedback_ticket_detail_refresh_failed")
    finally:
        if owns_client:
            await active_client.close()
    return ticket


def ticket_comments(ticket: StdFeedbackTicket) -> list[dict[str, Any]]:
    value = (ticket.raw or {}).get("comments")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def ticket_files(ticket: StdFeedbackTicket) -> list[dict[str, Any]]:
    raw = ticket.raw or {}
    value = raw.get("files") if isinstance(raw.get("files"), list) else raw.get("attachments")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


async def run_std_feedback_ticket_sync_forever() -> None:
    from app.db import SessionLocal

    while True:
        interval_seconds = max(1, settings.STD_FEEDBACK_SYNC_INTERVAL_MINUTES) * 60
        if settings.STD_FEEDBACK_SYNC_ENABLED:
            try:
                async with SessionLocal() as db:
                    await sync_std_feedback_tickets(db)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("std_feedback_ticket_scheduler_failed")
        await asyncio.sleep(interval_seconds if settings.STD_FEEDBACK_SYNC_ENABLED else 60)
