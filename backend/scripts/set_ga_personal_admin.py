"""Assign a verified existing account as module admin, preserving its work role."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text, update
from sqlalchemy.engine import make_url

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models.ga_personal import (
    SCHEMA, GaPersonalSpace, GaPersonalMember, GaPersonalUnlock,
)
from app.models.user import User

ACCOUNTS = {"rrita": "rrita.canolli", "mrika": "mrika.canolli",
            "lirza": "lirza.canolli", "gane": "gane.arifaj"}


async def assign_admin(db, person, user_id):
    user = (await db.execute(select(User).where(User.id == user_id).with_for_update())).scalar_one_or_none()
    if not user or user.username != ACCOUNTS[person] or not user.is_active:
        raise ValueError("The exact verified account must exist and be active.")
    work_role = user.role
    space = (await db.execute(select(GaPersonalSpace).where(GaPersonalSpace.key == "ga_personal").with_for_update())).scalar_one_or_none()
    if space is None:
        # No generated/default password and no implicit activation.
        space = GaPersonalSpace(key="ga_personal", config={"reminders_enabled": False})
        db.add(space)
        await db.flush()
    members = (await db.execute(select(GaPersonalMember).where(
        GaPersonalMember.space_id == space.id,
        (GaPersonalMember.person_key == person) | (GaPersonalMember.user_id == user_id),
    ))).scalars().all()
    if any(m.user_id != user_id or m.person_key != person for m in members) or len(members) > 1:
        raise ValueError("Existing person/account mapping conflicts; no identities were changed.")
    member = members[0] if members else GaPersonalMember(
        space_id=space.id, user_id=user_id, person_key=person,
    )
    member.is_admin, member.active = True, True
    db.add(member)
    await db.execute(update(GaPersonalUnlock).where(
        GaPersonalUnlock.space_id == space.id, GaPersonalUnlock.user_id == user_id,
    ).values(revoked=True))
    await db.flush()
    await db.refresh(user)
    if user.role != work_role:
        raise ValueError("The work role must not change.")
    return {"username": user.username, "user_id": str(user.id), "person_key": person,
            "module_admin": member.is_admin, "membership_active": member.active,
            "primeflow_role": user.role.value, "password_configured": bool(space.password_hash)}


async def main(args):
    target = make_url(settings.DATABASE_URL)
    if args.apply and (target.host != args.expected_host or target.database != args.expected_database):
        raise SystemExit("Database target differs from the explicitly expected host/database.")
    async with engine.begin() as conn:
        # Provision just this isolated module, not unrelated pending migrations.
        # Leave the deployed Alembic stamp unchanged; its module migration is
        # idempotent so a later normal deployment can adopt these same tables.
        await conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('primeflow:ga_personal:provision'))"))
        account = (await conn.execute(select(User.id, User.username, User.is_active).where(User.id == args.user_id))).one_or_none()
        if not account or account.username != ACCOUNTS[args.person] or not account.is_active:
            raise SystemExit("Account identity/active status differs from the requested member.")
        if not args.apply:
            print(json.dumps({"status": "preview", "username": account.username, "module_admin": True,
                              "host": target.host, "database": target.database}))
            return
        before = (await conn.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num"))).scalars().all()
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS ga_personal"))
        await conn.execute(text("REVOKE ALL ON SCHEMA ga_personal FROM PUBLIC"))
        tables = [t for t in Base.metadata.tables.values() if t.schema == SCHEMA]
        await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
        after = (await conn.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num"))).scalars().all()
        if before != after:
            raise SystemExit("Unexpected migration stamp change.")
    async with SessionLocal() as db:
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('primeflow:ga_personal:provision'))"))
        result = await assign_admin(db, args.person, args.user_id)
        await db.commit()
    async with SessionLocal() as db:
        member = (await db.execute(select(GaPersonalMember).join(GaPersonalSpace, GaPersonalSpace.id == GaPersonalMember.space_id).where(
            GaPersonalMember.user_id == args.user_id, GaPersonalMember.person_key == args.person,
            GaPersonalSpace.key == "ga_personal",
        ))).scalar_one()
        if not member.is_admin or not member.active:
            raise SystemExit("Persisted module administrator verification failed.")
    print(json.dumps({"status": "verified", **result, "api_module_enabled_in_this_environment": settings.GA_PERSONAL_ENABLED}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--person", required=True, choices=sorted(ACCOUNTS))
    parser.add_argument("--user-id", required=True, type=uuid.UUID)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-host")
    parser.add_argument("--expected-database")
    args = parser.parse_args()
    if args.apply and (not args.expected_host or not args.expected_database):
        parser.error("--apply requires --expected-host and --expected-database")
    asyncio.run(main(args))
