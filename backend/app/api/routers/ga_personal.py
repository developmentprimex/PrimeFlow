from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import select, update

from app.api.deps import get_current_user, http_bearer
from app.auth.security import decode_token, get_password_hash, verify_password
from app.config import settings
from app.db import get_db
from app.models.ga_personal import (
    GaPersonalMember as Member, GaPersonalSpace as Space, GaPersonalUnlock as Unlock,
    GaPersonalThrottle as Throttle, GaPersonalTemplate as Template, GaPersonalOccurrence as Occurrence,
    GaPersonalEvent as Event,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.ga_personal import (
    ActionRequest, ArchiveRequest, AutomationRequest, GenerateRequest, ImportRequest, OccurrenceUpdate, PasswordRequest, TemplateWrite, UnlockRequest,
)
from app.services import ga_personal as service
from app.services import ga_personal_discord as discord_service

class PrivateRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private_handler(request: Request):
            try:
                if request.method in {"POST", "PUT"}:
                    length = request.headers.get("content-length", "0")
                    if not length.isdigit():
                        raise HTTPException(400, "Kërkesë e pavlefshme.")
                    if int(length) > 2 * 1024 * 1024 or len(await request.body()) > 2 * 1024 * 1024:
                        raise HTTPException(413, "Kërkesa duhet të jetë deri në 2 MB.")
                response = await handler(request)
            except RequestValidationError:
                # FastAPI's default validation details include raw input. Never
                # echo module passwords (including malformed secret fields).
                response = JSONResponse({"detail": "Kontrollo fushat dhe provo përsëri."}, status_code=422)
            except HTTPException as exc:
                response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
            response.headers["Cache-Control"] = "private, no-store"
            return response

        return private_handler


router = APIRouter(route_class=PrivateRoute)
COOKIE = "primeflow_ga_personal"
COOKIE_PATH = "/api/ga-personal"


def no_store(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


async def membership(user=Depends(get_current_user), db=Depends(get_db)):
    if not settings.GA_PERSONAL_ENABLED:
        raise HTTPException(404, "Moduli nuk është aktivizuar.")
    member = (await db.execute(select(Member).join(Space, Space.id == Member.space_id).where(
        Member.user_id == user.id, Member.active.is_(True), Space.key == "ga_personal",
    ))).scalar_one_or_none()
    if member is None:
        raise HTTPException(403, "Nuk ke qasje në këtë modul.")
    return member


async def login_session(credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
                        user=Depends(get_current_user), db=Depends(get_db)):
    try:
        sid = decode_token(credentials.credentials).get("sid")
        if not sid or len(sid) > 64:
            raise ValueError()
    except (AttributeError, ValueError):
        raise HTTPException(409, "Hyr përsëri në PrimeFlow për ta hapur këtë modul.")
    session = (await db.execute(select(RefreshToken).where(
        RefreshToken.user_id == user.id, RefreshToken.jti == sid, RefreshToken.revoked_at.is_(None),
    ))).scalar_one_or_none()
    if not session or service.aware(session.expires_at) <= service.utcnow():
        raise HTTPException(409, "Sesioni përfundoi. Hyr përsëri në PrimeFlow.")
    return sid


async def unlocked(request: Request, member=Depends(membership), sid=Depends(login_session), db=Depends(get_db)):
    raw = request.cookies.get(COOKIE, "")
    session = await db.get(Unlock, service.digest(raw)) if raw and len(raw) <= 100 else None
    space = await db.get(Space, member.space_id)
    if (not session or session.user_id != member.user_id or session.space_id != member.space_id
        or session.login_session_id != sid or session.revoked
        or service.aware(session.expires_at) <= service.utcnow() or session.password_version != space.password_version):
        raise HTTPException(423, "Hape modulin me fjalëkalimin shtesë.")
    db.info["ga_personal_unlock_hash"] = session.token_hash
    return member


async def admin(member=Depends(unlocked)):
    if not member.is_admin:
        raise HTTPException(403, "Kërkohet administratori i modulit.")
    return member


@router.get("/access")
async def access(request: Request, response: Response, user=Depends(get_current_user), db=Depends(get_db)):
    no_store(response)
    if not settings.GA_PERSONAL_ENABLED:
        return {"available": False, "unlocked": False}
    try:
        member = await membership(user, db)
    except HTTPException:
        return {"available": False, "unlocked": False}
    space = await db.get(Space, member.space_id)
    requires_login = False
    try:
        credentials = await http_bearer(request)
        sid = await login_session(credentials, user, db)
    except HTTPException:
        requires_login = True
    is_unlocked = False
    if not requires_login:
        try:
            await unlocked(request, member, sid, db)
            is_unlocked = True
        except HTTPException:
            pass
    session = await db.get(Unlock, service.digest(request.cookies.get(COOKIE, ""))) if is_unlocked else None
    return {"available": True, "unlocked": is_unlocked, "configured": bool(space.password_hash),
            "expires_at": service.aware(session.expires_at).isoformat() if session else None,
            "requires_login": requires_login,
            "setup_allowed": member.is_admin and not space.password_hash and not requires_login}


@router.post("/password/setup")
async def setup_password(payload: PasswordRequest, response: Response, member=Depends(membership),
                         sid=Depends(login_session), db=Depends(get_db)):
    """The verified module administrator can initialize an unset gate once."""
    no_store(response)
    if not member.is_admin:
        raise HTTPException(403, "Vetëm administratori i modulit mund ta vendosë fjalëkalimin e parë.")
    value = payload.password.get_secret_value()
    if not 12 <= len(value.encode("utf-8")) <= 72:
        raise HTTPException(422, "Fjalëkalimi duhet të ketë 12–72 byte.")
    space = await service.lock_member_space(db, member, need_admin=True)
    if space.password_hash:
        raise HTTPException(409, "Fjalëkalimi është vendosur. Hape modulin për ta ndryshuar.")
    space.password_hash = get_password_hash(value)
    space.password_version += 1
    await db.execute(update(Unlock).where(Unlock.space_id == space.id).values(revoked=True))
    await db.commit()
    return {"configured": True, "unlocked": False}


@router.post("/unlock")
async def unlock(payload: UnlockRequest, request: Request, response: Response,
                 member=Depends(membership), sid=Depends(login_session), db=Depends(get_db)):
    no_store(response)
    space = await service.lock_member_space(db, member)
    if not space.password_hash:
        raise HTTPException(409, "Fjalëkalimi i modulit ende nuk është konfiguruar.")
    now = service.utcnow()
    if not 1 <= len(payload.password.get_secret_value().encode("utf-8")) <= 72:
        raise HTTPException(422, "Fjalëkalimi duhet të ketë 1–72 byte.")
    buckets = []
    for key in (str(member.user_id), "ip:" + (request.client.host if request.client else "unknown")):
        hashed = service.digest(key)
        bucket = await db.get(Throttle, hashed)
        if bucket is None:
            bucket = Throttle(key=hashed, failures=0, window_start=now)
            db.add(bucket)
        if service.aware(bucket.window_start) + timedelta(minutes=15) <= now:
            bucket.failures, bucket.window_start = 0, now
        buckets.append(bucket)
    if any(b.failures >= 5 for b in buckets):
        raise HTTPException(429, "Shumë tentime. Provo pas 15 minutash.", headers={"Retry-After": "900"})
    if not verify_password(payload.password.get_secret_value(), space.password_hash):
        for bucket in buckets:
            bucket.failures += 1
        await db.commit()  # Persist failed attempts, including across API instances.
        raise HTTPException(403, "Fjalëkalimi nuk është i saktë.")
    for bucket in buckets:
        bucket.failures = 0
    # Rotate this browser's old token, without invalidating another browser.
    old = request.cookies.get(COOKIE)
    if old:
        await db.execute(update(Unlock).where(Unlock.token_hash == service.digest(old), Unlock.user_id == member.user_id).values(revoked=True))
    raw = secrets.token_urlsafe(32)
    minutes = max(1, min(settings.GA_PERSONAL_UNLOCK_MINUTES, 480))
    parent = (await db.execute(select(RefreshToken).where(RefreshToken.user_id == member.user_id, RefreshToken.jti == sid))).scalar_one()
    expiry = min(now + timedelta(minutes=minutes), service.aware(parent.expires_at))
    db.add(Unlock(token_hash=service.digest(raw), user_id=member.user_id, space_id=member.space_id,
                  login_session_id=sid, password_version=space.password_version, expires_at=expiry))
    await db.commit()
    response.set_cookie(COOKIE, raw, httponly=True, secure=settings.auth_cookie_secure,
                        samesite=settings.auth_cookie_samesite, path=COOKIE_PATH, max_age=max(0, int((expiry - now).total_seconds())))
    return {"unlocked": True, "expires_at": expiry.isoformat()}


@router.post("/lock")
async def lock(request: Request, response: Response, member=Depends(membership), db=Depends(get_db)):
    no_store(response)
    raw = request.cookies.get(COOKIE)
    if raw:
        await db.execute(update(Unlock).where(Unlock.token_hash == service.digest(raw), Unlock.user_id == member.user_id).values(revoked=True))
        await db.commit()
    response.delete_cookie(COOKIE, path=COOKIE_PATH, secure=settings.auth_cookie_secure, samesite=settings.auth_cookie_samesite)
    return {"unlocked": False}


@router.get("/workspace")
async def workspace(response: Response, member=Depends(unlocked), db=Depends(get_db)):
    no_store(response)
    space = await db.get(Space, member.space_id)
    rows = (await db.execute(select(Member, User.full_name).join(User, User.id == Member.user_id).where(
        Member.space_id == member.space_id, Member.active.is_(True), User.is_active.is_(True),
    ))).all()
    return {"person_key": member.person_key, "is_admin": member.is_admin, "timezone": "Europe/Belgrade",
        "members": [{"person_key": m.person_key, "name": name} for m, name in rows],
        "config": {k: v for k, v in space.config.items() if k != "discord"},
        "discord": {**discord_service.public_status(space), "messages_enabled": await discord_service.granted(db, space)}}


@router.get("/templates")
async def templates(response: Response, member=Depends(unlocked), db=Depends(get_db)):
    no_store(response)
    rows = (await db.execute(select(Template).where(Template.space_id == member.space_id).order_by(Template.updated_at.desc()))).scalars().all()
    return [service.template_out(row, member) for row in rows]


@router.post("/templates")
async def create_template(payload: TemplateWrite, response: Response, member=Depends(unlocked), db=Depends(get_db)):
    no_store(response)
    return await service.save_template(db, member, payload)


@router.put("/templates/{template_id}")
async def edit_template(template_id: uuid.UUID, payload: TemplateWrite, response: Response, member=Depends(unlocked), db=Depends(get_db)):
    no_store(response)
    return await service.save_template(db, member, payload, template_id)


@router.post("/templates/{template_id}/archive")
async def archive(template_id: uuid.UUID, payload: ArchiveRequest, response: Response, member=Depends(unlocked), db=Depends(get_db)):
    no_store(response)
    return await service.archive_template(db, member, template_id, payload)


@router.get("/occurrences")
async def occurrences(response: Response, day: str | None = None, member=Depends(unlocked), db=Depends(get_db)):
    no_store(response)
    stmt = select(Occurrence, Template).join(Template, Template.id == Occurrence.template_id).where(
        Occurrence.space_id == member.space_id, Template.space_id == member.space_id)
    if day:
        try:
            service.date.fromisoformat(day)
        except ValueError:
            raise HTTPException(422, "Data nuk është e vlefshme.")
        # Keep unfinished weekend duties visible throughout their period.
        weekend = "weekend:" + (service.date.fromisoformat(day) - timedelta(days=service.date.fromisoformat(day).weekday())).isoformat()
        from sqlalchemy import or_
        stmt = stmt.where(or_(Occurrence.local_date == day, Occurrence.period_key == weekend)
                          if service.date.fromisoformat(day).weekday() in (5, 6) else Occurrence.local_date == day)
    rows = (await db.execute(stmt.order_by(Occurrence.local_date.desc(), Occurrence.due_at, Occurrence.id).limit(500))).all()
    return [service.occurrence_out(row, can_edit=service.may_edit_occurrence(member, template, row))
            for row, template in rows]


@router.patch("/occurrences/{occurrence_id}")
async def edit_occurrence(occurrence_id: uuid.UUID, payload: OccurrenceUpdate, response: Response,
                          member=Depends(unlocked), db=Depends(get_db)):
    no_store(response)
    return await service.edit_occurrence(db, member, occurrence_id, payload)


@router.post("/generate")
async def generate(payload: GenerateRequest, response: Response, member=Depends(admin), db=Depends(get_db)):
    no_store(response)
    return await service.generate(db, member, payload)


@router.post("/occurrences/{occurrence_id}/actions")
async def action(occurrence_id: uuid.UUID, payload: ActionRequest, response: Response, member=Depends(unlocked), db=Depends(get_db)):
    no_store(response)
    return await service.act(db, member, occurrence_id, payload)


@router.get("/history")
async def history(response: Response, member=Depends(unlocked), db=Depends(get_db)):
    no_store(response)
    rows = (await db.execute(select(Event).where(Event.space_id == member.space_id).order_by(Event.created_at.desc()).limit(200))).scalars().all()
    return [{"id": str(e.id), "occurrence_id": str(e.occurrence_id) if e.occurrence_id else None,
             "actor_id": str(e.actor_id), "kind": e.kind, "payload": e.payload,
             "created_at": service.aware(e.created_at).isoformat()} for e in rows]


@router.post("/import/preview")
async def preview(payload: ImportRequest, response: Response, member=Depends(admin), db=Depends(get_db)):
    no_store(response)
    return await service.import_dataset(db, member, payload.dataset)


@router.post("/import/apply")
async def apply_import(payload: ImportRequest, response: Response, member=Depends(admin), db=Depends(get_db)):
    no_store(response)
    return await service.import_dataset(db, member, payload.dataset, apply=True, expected_hash=payload.expected_hash)


@router.put("/password")
async def password(payload: PasswordRequest, response: Response, member=Depends(admin), db=Depends(get_db)):
    no_store(response)
    if not 12 <= len(payload.password.get_secret_value().encode("utf-8")) <= 72:
        raise HTTPException(422, "Fjalëkalimi duhet të ketë 12–72 byte.")
    space = await service.lock_member_space(db, member, need_admin=True)
    space.password_hash = get_password_hash(payload.password.get_secret_value())
    space.password_version += 1
    await db.execute(update(Unlock).where(Unlock.space_id == space.id).values(revoked=True))
    await db.commit()
    response.delete_cookie(COOKIE, path=COOKIE_PATH)
    return {"unlocked": False}


@router.put("/automation")
async def automation(payload: AutomationRequest, response: Response, member=Depends(admin), db=Depends(get_db)):
    no_store(response)
    space = await service.lock_member_space(db, member, need_admin=True)
    previous = space.config.get("automatic_generation", {})
    space.config = {**space.config, "automatic_generation": {
        **previous, "enabled": payload.enabled,
        "starts_on": previous.get("starts_on") or service.utcnow().astimezone(service.TZ).date().isoformat(),
    }}
    db.add(Event(space_id=space.id, actor_id=member.user_id, request_id=str(uuid.uuid4()),
                 kind="automation_enabled" if payload.enabled else "automation_disabled", payload={}))
    await db.commit()
    return {"enabled": payload.enabled}


# Registered after the shared dependencies above to keep browser and bridge
# authorization separate while using the same private-response handling.
from app.api.routers.ga_personal_discord import router as discord_router
router.include_router(discord_router)
