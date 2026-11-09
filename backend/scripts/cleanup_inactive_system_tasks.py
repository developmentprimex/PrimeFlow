"""Preview or delete system tasks of inactive users, saving a backup before --apply."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run(args) -> None:
    from sqlalchemy import inspect, or_, select
    from sqlalchemy.engine import make_url
    from app.config import settings
    from app.db import Base, SessionLocal, engine
    from app.services.inactive_system_tasks import (
        apply_inactive_system_task_cleanup, plan_inactive_system_task_cleanup,
    )

    try:
        async with SessionLocal() as db:
            plan = await plan_inactive_system_task_cleanup(db)
            url = make_url(settings.DATABASE_URL)
            print(json.dumps({"host": url.host, "database": url.database, "apply": args.apply,
                "inactive_users": len(plan.inactive_user_ids), "tasks_to_delete": len(plan.task_ids),
                "occurrences_to_delete": len(plan.occurrence_ids),
                "shared_tasks_to_preserve": len(plan.shared_task_ids),
                "shared_tasks_to_reassign": len(plan.reassigned_tasks)}))
            if not args.apply:
                await db.rollback()
                return

            roots = {"tasks": [*plan.task_ids, *plan.shared_task_ids],
                     "system_task_occurrences": plan.occurrence_ids}
            backup = {}
            # Capture roots, incoming SET NULL references, and all cascading descendants.
            frontier = {}
            for name, ids in roots.items():
                if ids:
                    table = Base.metadata.tables[name]
                    rows = [dict(row) for row in (await db.execute(select(table).where(table.c.id.in_(ids)))).mappings()]
                    backup[name] = rows
                    frontier[name] = rows
            visited = set()
            existing_tables = set(await db.run_sync(lambda session: inspect(session.connection()).get_table_names()))
            while frontier:
                next_frontier = {}
                for table in Base.metadata.tables.values():
                    if table.name not in existing_tables:
                        continue
                    conditions = []
                    cascades = False
                    for fk in table.foreign_keys:
                        parent = fk.column.table.name
                        edge = (table.name, fk.parent.name, parent)
                        if parent not in frontier or edge in visited:
                            continue
                        visited.add(edge)
                        values = [row[fk.column.name] for row in frontier[parent] if row[fk.column.name] is not None]
                        if values:
                            conditions.append(fk.parent.in_(values))
                            cascades |= fk.ondelete == "CASCADE"
                    if conditions:
                        rows = [dict(row) for row in (await db.execute(select(table).where(or_(*conditions)))).mappings()]
                        if rows:
                            existing = backup.setdefault(table.name, [])
                            existing.extend(row for row in rows if row not in existing)
                            if cascades:
                                next_frontier[table.name] = rows
                frontier = next_frontier
            backup_path = None
            if backup:
                args.backup_dir.mkdir(parents=True, exist_ok=True)
                backup_path = args.backup_dir / ("inactive-system-tasks-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
                with backup_path.open("x", encoding="utf-8") as handle:
                    json.dump(backup, handle, default=str, ensure_ascii=False, indent=2)
            result = await apply_inactive_system_task_cleanup(db, plan)
            # Verify before committing; errors roll back the complete cleanup.
            remaining = await plan_inactive_system_task_cleanup(db)
            assert not remaining.task_ids and not remaining.occurrence_ids and not remaining.shared_task_ids, "Incomplete cleanup"
            await db.commit()
            print(json.dumps({**result, "backup": str(backup_path) if backup_path else None,
                              "remaining_inactive_system_tasks": 0}))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--database-host", help="Override a loopback host when connecting remotely.")
    parser.add_argument("--backup-dir", type=Path, default=Path("private-data/maintenance-backups"))
    args = parser.parse_args()
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=True)
    if args.database_host:
        from sqlalchemy.engine import make_url
        if "DATABASE_URL" not in os.environ:
            from dotenv import load_dotenv
            load_dotenv()
        url = make_url(os.environ["DATABASE_URL"])
        os.environ["DATABASE_URL"] = url.set(host=args.database_host).render_as_string(hide_password=False)
    asyncio.run(run(args))
