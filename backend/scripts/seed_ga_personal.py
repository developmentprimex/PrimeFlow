"""Preview/import a reviewed JSON or ZIP seed; preserve live IDs and history."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.config import settings
from app.db import SessionLocal
from app.models.ga_personal import (
    GaPersonalSpace as Space, GaPersonalMember as Member, GaPersonalTemplate as Template,
    GaPersonalImport as ImportRun, GaPersonalOccurrence as Occurrence,
)
from app.models.user import User
from app.schemas.ga_personal import GenerateRequest
from app.services import ga_personal as service

USERNAMES = {"rrita": "rrita.canolli", "mrika": "mrika.canolli",
             "lirza": "lirza.canolli", "gane": "gane.arifaj"}


def read_archive(path):
    with zipfile.ZipFile(path) as archive:
        key = "mira-project/data/ga-personal.dataset.json"
        if archive.getinfo(key).file_size > 2 * 1024 * 1024:
            raise ValueError("Dataset is too large.")
        return json.loads(archive.read(key).decode("utf-8-sig"))


def read_dataset(path):
    path = Path(path)
    if path.suffix.lower() == ".zip":
        return read_archive(path)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Dataset is too large.")
    return json.loads(path.read_text(encoding="utf-8-sig"))


async def seed(db, dataset, mapping, *, admin_person="rrita", apply=False, day=None):
    day = day or datetime.now(service.TZ).date()
    parsed, rotation = service.validate_dataset(dataset)
    if set(mapping) != service.PEOPLE or len(set(mapping.values())) != 4:
        raise ValueError("Exactly four verified, distinct account UUIDs are required.")
    users = {u.id: u for u in (await db.execute(select(User).where(User.id.in_(mapping.values()), User.is_active.is_(True)))).scalars()}
    if len(users) != 4 or any(users[uid].username != USERNAMES[person] for person, uid in mapping.items()):
        raise ValueError("Verified account identity/active status differs from the mapping.")
    space = (await db.execute(select(Space).where(Space.key == "ga_personal").with_for_update())).scalar_one()
    members = {m.person_key: m for m in (await db.execute(select(Member).where(Member.space_id == space.id))).scalars()}
    if any(m.person_key not in mapping or m.user_id != mapping[m.person_key] or not m.active for m in members.values()):
        raise ValueError("Existing membership differs or is revoked; no membership was replaced.")
    admin = members.get(admin_person)
    if not admin or not admin.is_admin:
        raise ValueError("The selected module administrator must already be configured.")
    source_hash = service.document_hash(dataset)
    prior = (await db.execute(select(ImportRun).where(ImportRun.space_id == space.id, ImportRun.dataset_hash == source_hash))).scalar_one_or_none()
    templates = {t.source_id: t for t in (await db.execute(select(Template).where(Template.space_id == space.id, Template.source_id.is_not(None)))).scalars()}
    missing = [person for person in sorted(mapping) if person not in members]
    eligible = [key for key, data in parsed if data["frequency"] == "daily"
                and data["readiness"] == "ready_after_setup" and data["assignment"] in {"fixed", "rotation"}]
    summary = {"dataset_hash": source_hash, "templates": len(parsed),
        "steps": sum(len(d["steps"]) for _, d in parsed), "daily_candidates": len(eligible),
        "other_models_waiting_configuration": len(parsed) - len(eligible), "memberships_to_add": missing,
        "already_imported": bool(prior), "rotation_anchor": rotation.get("anchor_date"), "day": day.isoformat()}
    preview = await service.import_dataset(db, admin, dataset)
    summary.update({key: preview[key] for key in ("create", "update", "rename", "archive", "conflicts")})
    if not apply:
        return summary
    for person in missing:
        db.add(Member(space_id=space.id, user_id=mapping[person], person_key=person, is_admin=False, active=True))
    await db.flush()
    if not prior or any(key not in templates for key, _ in parsed):
        await service.import_dataset(db, admin, dataset, apply=True, expected_hash=source_hash, commit=False)
        templates = {t.source_id: t for t in (await db.execute(select(Template).where(Template.space_id == space.id, Template.source_id.is_not(None)))).scalars()}
    activated, preserved = [], []
    for key, original in parsed:
        row = templates[key]
        if key not in eligible or row.archived:
            continue
        normalized = {**row.definition, "enabled": False}
        # A local edit clears import_hash. Preserve all such edits/configuration.
        if row.import_hash != service.document_hash(original) or normalized != original:
            preserved.append(key)
            continue
        if not row.definition["enabled"]:
            row.definition = {**row.definition, "enabled": True}
            row.version += 1
        activated.append(key)
    previous = space.config.get("automatic_generation", {})
    space.config = {**space.config, "automatic_generation": {
        "enabled": True, "starts_on": previous.get("starts_on") or day.isoformat(),
        "policy": "reviewed_daily_seed_v" + str(dataset["format_version"]), "seed_source_ids": sorted(activated),
    }}
    await db.flush()
    result = await service.generate(db, admin, GenerateRequest(day=day), automatic=True, commit=False)
    await db.commit()
    return {**summary, "applied": True, "daily_models_active": len(activated),
        "preserved_local_edits": preserved, "created_occurrences": result["created"],
        "skipped_unconfigured_owners": len(result["skipped"]), "automatic_generation": True,
        "notifications_activated": False}


async def main(args):
    target = make_url(settings.DATABASE_URL)
    if args.apply and (target.host != args.expected_host or target.database != args.expected_database):
        raise SystemExit("Database target differs from the explicit host/database.")
    dataset = read_dataset(args.dataset or args.archive)
    async with SessionLocal() as db:
        if args.existing_memberships:
            rows = (await db.execute(select(Member).join(Space, Member.space_id == Space.id).where(
                Space.key == "ga_personal", Member.active.is_(True)))).scalars().all()
            mapping = {m.person_key: m.user_id for m in rows}
        else:
            mapping = {key: uuid.UUID(value) for key, value in json.loads(Path(args.mapping).read_text(encoding="utf-8-sig")).items()}
        if args.apply and args.backup:
            # Validate and acquire the space lock before taking a consistent
            # private backup. The subsequent seed shares this transaction.
            review = await seed(db, dataset, mapping, admin_person=args.admin_person)
            if review["conflicts"]:
                raise ValueError("Resolve preview conflicts before applying.")
            space = (await db.execute(select(Space).where(Space.key == "ga_personal"))).scalar_one()
            snapshot = {"created_at": service.utcnow().isoformat(), "space_id": str(space.id),
                        "config": space.config, "dataset_hash": review["dataset_hash"]}
            for label, model in (("templates", Template), ("occurrences", Occurrence), ("imports", ImportRun)):
                rows = (await db.execute(select(model).where(model.space_id == space.id))).scalars().all()
                snapshot[label] = [{column.key: getattr(row, column.key) for column in model.__table__.columns} for row in rows]
            with Path(args.backup).open("x", encoding="utf-8") as backup:
                json.dump(snapshot, backup, ensure_ascii=False, indent=2, default=str)
        result = await seed(db, dataset, mapping, admin_person=args.admin_person, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--archive")
    source.add_argument("--dataset")
    identities = parser.add_mutually_exclusive_group(required=True)
    identities.add_argument("--mapping")
    identities.add_argument("--existing-memberships", action="store_true")
    parser.add_argument("--admin-person", default="rrita", choices=sorted(USERNAMES))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-host")
    parser.add_argument("--expected-database")
    parser.add_argument("--backup", help="Private, new JSON file for the pre-apply config/templates/history snapshot.")
    args = parser.parse_args()
    if args.apply and (not args.expected_host or not args.expected_database):
        parser.error("--apply requires --expected-host and --expected-database")
    asyncio.run(main(args))
