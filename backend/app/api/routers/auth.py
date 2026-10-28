from __future__ import annotations

import uuid

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import (
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
    decode_token,
    require_token_type,
    verify_password,
)
from app.api.deps import get_current_user
from app.config import settings
from app.db import get_db
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.user import UserOut


router = APIRouter()

REFRESH_COOKIE_NAME = "primex_refresh"


def _refresh_cookie_options(*, max_age: int | None = None) -> dict[str, object]:
    options: dict[str, object] = {
        "httponly": True,
        "secure": settings.auth_cookie_secure,
        "samesite": settings.auth_cookie_samesite,
        "path": "/api/auth",
    }
    if settings.AUTH_COOKIE_DOMAIN:
        options["domain"] = settings.AUTH_COOKIE_DOMAIN
    if max_age is not None:
        options["max_age"] = max_age
    return options


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    now = datetime.now(timezone.utc)
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")

    jti = uuid.uuid4().hex
    access_token = create_access_token(user_id=user.id, role=user.role.value, department_id=user.department_id, session_id=jti)
    refresh_token, expires_at = create_refresh_token(user_id=user.id, jti=jti)

    db.add(RefreshToken(user_id=user.id, jti=jti, expires_at=expires_at))
    await db.commit()

    response.set_cookie(
        REFRESH_COOKIE_NAME,
        refresh_token,
        **_refresh_cookie_options(max_age=int((expires_at - now).total_seconds())),
    )

    return TokenResponse(access_token=access_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    refresh_cookie: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    if not refresh_cookie:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")

    try:
        payload = decode_token(refresh_cookie)
        require_token_type(payload, REFRESH_TOKEN_TYPE)
        user_id = uuid.UUID(str(payload.get("sub")))
        jti = str(payload.get("jti"))
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    now = datetime.now(timezone.utc)
    token_row = (
        await db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id, RefreshToken.jti == jti, RefreshToken.revoked_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if token_row is None or token_row.expires_at <= now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")

    # The refresh token is deliberately not rotated here. Rotation logged users
    # out whenever two tabs refreshed together, or when a slow response was
    # dropped by the browser after the old token had already been revoked.
    # It stays valid until logout or its own expiry.
    #
    # A session that is still in use must not hit that expiry, so once less
    # than half the lifetime remains a fresh token is issued alongside it. The
    # old one is left to expire on its own, which keeps a second tab or a
    # dropped response from ending the session.
    if token_row.expires_at - now < timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS / 2):
        new_jti = uuid.uuid4().hex
        new_refresh_token, new_expires_at = create_refresh_token(user_id=user.id, jti=new_jti, session_id=str(payload.get("sid") or jti))
        db.add(RefreshToken(user_id=user.id, jti=new_jti, expires_at=new_expires_at))
        await db.commit()
        response.set_cookie(
            REFRESH_COOKIE_NAME,
            new_refresh_token,
            **_refresh_cookie_options(max_age=int((new_expires_at - now).total_seconds())),
        )

    access_token = create_access_token(user_id=user.id, role=user.role.value, department_id=user.department_id, session_id=str(payload.get("sid") or jti))
    return TokenResponse(access_token=access_token)


@router.post("/logout")
async def logout(
    response: Response,
    refresh_cookie: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if refresh_cookie:
        try:
            payload = decode_token(refresh_cookie)
            require_token_type(payload, REFRESH_TOKEN_TYPE)
            user_id = uuid.UUID(str(payload.get("sub")))
            jti = str(payload.get("jti"))
            now = datetime.now(timezone.utc)
            token_row = (
                await db.execute(select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.jti == jti))
            ).scalar_one_or_none()
            if token_row and token_row.revoked_at is None:
                token_row.revoked_at = now
                if settings.GA_PERSONAL_ENABLED:
                    from app.models.ga_personal import GaPersonalUnlock
                    await db.execute(update(GaPersonalUnlock).where(GaPersonalUnlock.user_id == user_id).values(revoked=True))
                    # Invalidate the original session identity even after a refresh renewal.
                    await db.execute(update(RefreshToken).where(
                        RefreshToken.user_id == user_id,
                        RefreshToken.jti == str(payload.get("sid") or jti),
                    ).values(revoked_at=now))
                await db.commit()
        except Exception:
            pass

    response.delete_cookie(
        REFRESH_COOKIE_NAME,
        path="/api/auth",
        domain=settings.AUTH_COOKIE_DOMAIN,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
    )
    return {"status": "ok"}


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        department_id=user.department_id,
        is_active=user.is_active,
    )

