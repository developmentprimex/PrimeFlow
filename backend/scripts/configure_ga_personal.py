"""Explicit UUID provisioning. Password is read from the terminal, never argv."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, update
from app.auth.security import get_password_hash
from app.db import SessionLocal
from app.models.ga_personal import GaPersonalMember, GaPersonalSpace, GaPersonalUnlock
from app.models.user import User
from app.services.ga_personal import PEOPLE


async def configure(args):
    mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8-sig"))
    if set(mapping) != PEOPLE or args.admin not in PEOPLE:
        raise SystemExit("Mapping must contain exactly mrika, lirza, rrita, gane and an explicit administrator.")
    mapping = {key: uuid.UUID(value) for key, value in mapping.items()}
    if len(set(mapping.values())) != 4:
        raise SystemExit("Four distinct, verified PrimeFlow UUIDs are required.")
    async with SessionLocal() as db:
        users = {u.id: u for u in (await db.execute(select(User).where(User.id.in_(mapping.values()), User.is_active.is_(True)))).scalars()}
        if set(users) != set(mapping.values()):
            raise SystemExit("An explicitly mapped account is missing or inactive.")
        for person, user_id in mapping.items():
            print(f"{person}: {users[user_id].full_name} ({user_id})" + (" [module administrator]" if person == args.admin else ""))
        if not args.apply:
            print("Preview only. Review identities, then repeat with --apply; no password is needed for preview.")
            return
        password = getpass.getpass("Additional module password (12-72 UTF-8 bytes): ")
        if not 12 <= len(password.encode("utf-8")) <= 72 or password != getpass.getpass("Repeat module password: "):
            raise SystemExit("Password length or confirmation is invalid.")
        space = (await db.execute(select(GaPersonalSpace).where(GaPersonalSpace.key == "ga_personal").with_for_update())).scalar_one_or_none()
        if space is None:
            space = GaPersonalSpace(key="ga_personal", config={"reminders_enabled": False})
            db.add(space)
            await db.flush()
        space.password_hash = get_password_hash(password)
        space.password_version = (space.password_version or 0) + 1
        # Membership updates cannot inherit a previous user's unlock.
        await db.execute(update(GaPersonalUnlock).where(GaPersonalUnlock.space_id == space.id).values(revoked=True))
        existing = {m.person_key: m for m in (await db.execute(select(GaPersonalMember).where(GaPersonalMember.space_id == space.id))).scalars()}
        # Flush deletions before inserts, allowing an explicit UUID remapping.
        for member in existing.values():
            await db.delete(member)
        await db.flush()
        for person, user_id in mapping.items():
            db.add(GaPersonalMember(space_id=space.id, user_id=user_id, person_key=person,
                                    is_admin=person == args.admin, active=True))
        await db.commit()
        print("Configured. Enable GA_PERSONAL_ENABLED only after migration and isolation checks. No schedules or Discord messages activated.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", required=True, help="Private JSON file with four person keys mapped to verified UUIDs")
    parser.add_argument("--admin", required=True, choices=sorted(PEOPLE))
    parser.add_argument("--apply", action="store_true")
    asyncio.run(configure(parser.parse_args()))
