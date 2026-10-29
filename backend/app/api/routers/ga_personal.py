from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import select

from app.api.deps import get_current_user
from app.config import settings
from app.db import get_db
from app.models.ga_personal import (
    GaPersonalMember as Member, GaPersonalSpace as Space,
    GaPersonalTemplate as Template, GaPersonalOccurrence as Occurrence,
    GaPersonalEvent as Event,
)
from app.models.user import User
from app.schemas.ga_personal import (
    ActionRequest, ArchiveRequest, AutomationRequest, GenerateRequest, ImportRequest, OccurrenceUpdate, TemplateWrite,
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
                # Keep raw private input out of validation responses.
                response = JSONResponse({"detail": "Kontrollo fushat dhe provo përsëri."}, status_code=422)
            except HTTPException as exc:
                response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
            response.headers["Cache-Control"] = "private, no-store"
            return response

        return private_handler


router = APIRouter(route_class=PrivateRoute)


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


async def admin(member=Depends(membership)):
    if not member.is_admin:
        raise HTTPException(403, "Kërkohet administratori i modulit.")
    return member


@router.get("/access")
async def access(response: Response, user=Depends(get_current_user), db=Depends(get_db)):
    no_store(response)
    if not settings.GA_PERSONAL_ENABLED:
        return {"available": False, "unlocked": False}
    try:
        await membership(user, db)
    except HTTPException:
        return {"available": False, "unlocked": False}
    # Keep the access response compatible while using the normal PrimeFlow login.
    return {"available": True, "unlocked": True}


@router.get("/workspace")
async def workspace(response: Response, member=Depends(membership), db=Depends(get_db)):
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
async def templates(response: Response, member=Depends(membership), db=Depends(get_db)):
    no_store(response)
    rows = (await db.execute(select(Template).where(Template.space_id == member.space_id).order_by(Template.updated_at.desc()))).scalars().all()
    return [service.template_out(row, member) for row in rows]


@router.post("/templates")
async def create_template(payload: TemplateWrite, response: Response, member=Depends(membership), db=Depends(get_db)):
    no_store(response)
    return await service.save_template(db, member, payload)


@router.put("/templates/{template_id}")
async def edit_template(template_id: uuid.UUID, payload: TemplateWrite, response: Response, member=Depends(membership), db=Depends(get_db)):
    no_store(response)
    return await service.save_template(db, member, payload, template_id)


@router.post("/templates/{template_id}/archive")
async def archive(template_id: uuid.UUID, payload: ArchiveRequest, response: Response, member=Depends(membership), db=Depends(get_db)):
    no_store(response)
    return await service.archive_template(db, member, template_id, payload)


@router.get("/occurrences")
async def occurrences(response: Response, day: str | None = None, member=Depends(membership), db=Depends(get_db)):
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
                          member=Depends(membership), db=Depends(get_db)):
    no_store(response)
    return await service.edit_occurrence(db, member, occurrence_id, payload)


@router.post("/generate")
async def generate(payload: GenerateRequest, response: Response, member=Depends(admin), db=Depends(get_db)):
    no_store(response)
    return await service.generate(db, member, payload)


@router.post("/occurrences/{occurrence_id}/actions")
async def action(occurrence_id: uuid.UUID, payload: ActionRequest, response: Response, member=Depends(membership), db=Depends(get_db)):
    no_store(response)
    return await service.act(db, member, occurrence_id, payload)


@router.get("/history")
async def history(response: Response, member=Depends(membership), db=Depends(get_db)):
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
