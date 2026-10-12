"""CalDAV endpoints for GA's iPhone calendar account (read-only).

Mounted at the site root, not under ``/api``: CalDAV clients discover the
account through ``/.well-known/caldav`` and address resources by absolute path.
"""

from __future__ import annotations

import base64
import binascii
import hmac

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.ga_time_slots import _resolve_ga_user, load_ga_calendar_sources
from app.db import get_db
from app.services.ga_caldav import (
    ALLOWED_METHODS,
    CALDAV_PREFIX,
    CALDAV_USERNAME,
    DAV_HEADER,
    build_calendars,
    handle_caldav_request,
)
from app.services.ga_calendar_feed import caldav_password


router = APIRouter()

_METHODS = [
    "OPTIONS",
    "GET",
    "HEAD",
    "PROPFIND",
    "REPORT",
    "PROPPATCH",
    "PUT",
    "DELETE",
    "MKCALENDAR",
    "MKCOL",
    "MOVE",
    "COPY",
    "LOCK",
    "UNLOCK",
    "POST",
]
_MAX_BODY_BYTES = 256 * 1024


def _basic_credentials(request: Request) -> tuple[str, str] | None:
    scheme, _, encoded = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return None
    try:
        username, separator, password = base64.b64decode(encoded.strip(), validate=True).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return None
    return (username, password) if separator else None


def _unauthorized() -> Response:
    return Response(
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="PrimeFlow GA Calendar", charset="UTF-8"', "DAV": DAV_HEADER},
    )


async def _caldav(request: Request, db: AsyncSession, path: str) -> Response:
    if request.method == "OPTIONS":
        # Clients probe capabilities before they have credentials.
        return Response(status_code=200, headers={"DAV": DAV_HEADER, "Allow": ALLOWED_METHODS})

    credentials = _basic_credentials(request)
    if credentials is None:
        return _unauthorized()
    ga_user = await _resolve_ga_user(db)
    if ga_user is None:
        return _unauthorized()
    username, password = credentials
    # Compare both parts every time so a wrong username is not faster than a wrong password.
    username_ok = hmac.compare_digest(username.strip().lower().encode(), CALDAV_USERNAME.encode())
    password_ok = hmac.compare_digest(password.encode(), caldav_password(ga_user.id).encode())
    if not (username_ok and password_ok):
        return _unauthorized()

    body = await request.body()
    if len(body) > _MAX_BODY_BYTES:
        return Response(status_code=413)

    entries, meetings = await load_ga_calendar_sources(db, ga_user)
    result = handle_caldav_request(
        request.method,
        path,
        build_calendars(entries, meetings),
        depth=request.headers.get("Depth", "0"),
        body=body,
        prefer=request.headers.get("Prefer", ""),
    )
    headers = {"Cache-Control": "no-store", **result.headers}
    content = b"" if request.method == "HEAD" else result.body
    return Response(content=content, status_code=result.status, media_type=result.media_type, headers=headers)


@router.api_route("/.well-known/caldav", methods=_METHODS, include_in_schema=False)
async def caldav_well_known() -> Response:
    return Response(status_code=301, headers={"Location": f"{CALDAV_PREFIX}/"})


@router.api_route(CALDAV_PREFIX, methods=_METHODS, include_in_schema=False)
async def caldav_root(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    return await _caldav(request, db, "")


@router.api_route(CALDAV_PREFIX + "/{path:path}", methods=_METHODS, include_in_schema=False)
async def caldav_resource(path: str, request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    return await _caldav(request, db, path)


# iOS also asks the bare host for the principal when only a server name was typed.
@router.api_route("/", methods=["OPTIONS", "PROPFIND"], include_in_schema=False)
async def caldav_host_root(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    return await _caldav(request, db, "")
