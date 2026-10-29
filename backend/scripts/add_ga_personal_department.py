"""Add only the GA PERSONAL department, without running unrelated migrations/seed."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import make_url

from app.config import settings
from app.db import SessionLocal
from app.models.department import Department

DEPARTMENT_ID = uuid.UUID("b7f8125a-00d5-4d7a-962c-bfb495416eef")
NAME, CODE = "GA PERSONAL", "GAP"


async def main(args):
    url = make_url(settings.DATABASE_URL)
    if args.apply and (url.host != args.expected_host or url.database != args.expected_database):
        raise SystemExit("Database target differs from the explicitly expected host/database.")
    async with SessionLocal() as db:
        matches = (await db.execute(select(Department).where(or_(Department.code == CODE, Department.name == NAME)))).scalars().all()
        if any(d.code != CODE or d.name != NAME for d in matches) or len(matches) > 1:
            raise SystemExit("Conflicting department code/name; no changes applied.")
        if not matches and args.apply:
            await db.execute(insert(Department).values(id=DEPARTMENT_ID, name=NAME, code=CODE,
                             realization_mode="MANUAL").on_conflict_do_nothing(index_elements=[Department.code]))
            await db.commit()
            matches = (await db.execute(select(Department).where(Department.code == CODE))).scalars().all()
        if matches:
            row = matches[0]
            if row.name != NAME:
                raise SystemExit("Department code belongs to another name.")
            print(json.dumps({"status": "verified", "id": str(row.id), "name": row.name,
                              "code": row.code, "realization_mode": row.realization_mode}))
        else:
            print(json.dumps({"status": "preview", "name": NAME, "code": CODE,
                              "realization_mode": "MANUAL", "host": url.host, "database": url.database}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-host")
    parser.add_argument("--expected-database")
    args = parser.parse_args()
    if args.apply and (not args.expected_host or not args.expected_database):
        parser.error("--apply requires --expected-host and --expected-database")
    asyncio.run(main(args))
