"""Create temporary Knowledge PX examples; remove only this batch with --cleanup."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy import create_engine, delete, insert, select
from sqlalchemy.engine import make_url

from app.config import settings
from app.models.ga_note import GaNote
from app.models.knowledge_prompt import KnowledgePrompt
from app.models.task import Task

MARKER = "[TEST KNOWLEDGE 2026-10-14]"
MANIFEST = BACKEND.parent / "tmp" / "knowledge-demo-2026-10-14.json"
EXAMPLES = {
    "DEFINITION": [
        ("REQUEST", "Definimi i prioritetit HIGH", "Kërkohet një definim i qartë për prioritetin HIGH dhe kur përdoret.", ["prioritet", "high"]),
        ("PENDING_TEST", "Çfarë është një projekt?", "Një projekt është një grup detyrash me një qëllim të përbashkët, përgjegjës dhe afat të përcaktuar.", ["projekt", "detyrë", "afat"]),
        ("PENDING_APPROVAL", "Çfarë është kontrolli i cilësisë?", "Kontrolli i cilësisë është shqyrtimi i rezultatit kundrejt kërkesës dhe kritereve të pranimit para dorëzimit.", ["cilësi", "kontroll", "dorëzim"]),
        ("APPROVED", "Çfarë është një procedurë?", "Një procedurë është një rend i përcaktuar hapash për të kryer një proces në mënyrë të njëtrajtshme.", ["procedurë", "proces", "hapa"]),
    ],
    "REGULATION": [
        ("REQUEST", "Rregullorja për emërtimin e skedarëve", "Kërkohet një rregullore për emërtimin dhe organizimin e skedarëve të projektit.", ["skedarë", "emërtim"]),
        ("PENDING_TEST", "Dorëzimi i detyrave", "1. Kontrollo kërkesën para dorëzimit.\n2. Bashkëngjit rezultatin dhe shëno çfarë është përfunduar.\n3. Kërko konfirmim kur kërkohet nga procesi.", ["detyrë", "dorëzim", "konfirmim"]),
        ("PENDING_APPROVAL", "Përgatitja për takime", "1. Përgatit agjendën dhe materialet.\n2. Shëno vendimet dhe personat përgjegjës.\n3. Regjistro afatet për veprimet e dakorduara.", ["takim", "agjendë", "afat"]),
        ("APPROVED", "Organizimi i dokumenteve", "1. Ruaj dokumentet në folderin përkatës të projektit.\n2. Përdor emra të kuptueshëm dhe versionin kur nevojitet.\n3. Kontrollo dokumentin përpara shpërndarjes.", ["dokument", "folder", "version"]),
    ],
}


def seed(engine):
    if MANIFEST.exists():
        raise SystemExit(f"Batch already recorded: {MANIFEST}. Use --verify to inspect it.")
    now = datetime.now(timezone.utc)
    batch = {"marker": MARKER, "created_at": now.isoformat(), "notes": [], "entries": []}
    notes, entries = [], []
    for kind, examples in EXAMPLES.items():
        for stage, title, content, keywords in examples:
            note_id = uuid.uuid4()
            batch["notes"].append(str(note_id))
            notes.append(dict(
                id=note_id, content=f"{MARKER} {title}\nShembull i përkohshëm për provë; do të fshihet pas shikimit.",
                knowledge_type=kind, status="CLOSED" if stage == "APPROVED" else "OPEN",
                note_type="GA", priority="NORMAL", is_converted_to_task=False,
                completed_at=now if stage == "APPROVED" else None,
            ))
            if stage == "REQUEST":
                continue
            entry_id = uuid.uuid4()
            batch["entries"].append(str(entry_id))
            entries.append(dict(
                id=entry_id, knowledge_type=kind, title=f"{MARKER} {title}",
                content=f"SHEMBULL TESTUES — vetëm për provë të pamjes, jo dokument zyrtar.\n\n{content}",
                keywords=["test", "demo", *keywords], source_note_id=note_id, status=stage,
                tested_at=now if stage in ("PENDING_APPROVAL", "APPROVED") else None,
                approved_at=now if stage == "APPROVED" else None,
                test_comment="Status i simuluar për shembull testues; nuk përfaqëson kontroll real." if stage in ("PENDING_APPROVAL", "APPROVED") else None,
            ))
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    # Record exact IDs before the transaction so cleanup remains possible if interrupted.
    MANIFEST.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
    with engine.begin() as conn:
        if conn.execute(select(KnowledgePrompt.id).where(KnowledgePrompt.title.startswith(MARKER))).first():
            raise SystemExit("Examples with this marker already exist; no rows inserted.")
        conn.execute(insert(GaNote.__table__), notes)
        conn.execute(insert(KnowledgePrompt.__table__), entries)
    print(f"Created {len(notes)} notes and {len(entries)} entries. Manifest: {MANIFEST}")


def cleanup(engine):
    batch = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if batch["marker"] != MARKER:
        raise SystemExit("Unexpected batch marker.")
    note_ids = [uuid.UUID(value) for value in batch["notes"]]
    entry_ids = [uuid.UUID(value) for value in batch["entries"]]
    with engine.begin() as conn:
        entries = conn.execute(select(KnowledgePrompt.id, KnowledgePrompt.title, KnowledgePrompt.test_task_id).where(KnowledgePrompt.id.in_(entry_ids))).all()
        notes = conn.execute(select(GaNote.id, GaNote.content).where(GaNote.id.in_(note_ids))).all()
        if any(not row.title.startswith(MARKER) or row.test_task_id for row in entries) or any(not row.content.startswith(MARKER) for row in notes):
            raise SystemExit("Examples were changed or linked to tasks; review those records before cleanup.")
        if conn.execute(select(Task.id).where(Task.ga_note_origin_id.in_(note_ids))).first():
            raise SystemExit("Tasks were created from these examples; review the tasks before cleanup.")
        if conn.execute(select(KnowledgePrompt.id).where(KnowledgePrompt.source_note_id.in_(note_ids), KnowledgePrompt.id.not_in(entry_ids))).first():
            raise SystemExit("Additional material was linked to these notes; review before cleanup.")
        conn.execute(delete(KnowledgePrompt.__table__).where(KnowledgePrompt.id.in_(entry_ids)))
        conn.execute(delete(GaNote.__table__).where(GaNote.id.in_(note_ids)))
    batch["deleted_at"] = datetime.now(timezone.utc).isoformat()
    MANIFEST.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Removed {len(entries)} entries and {len(notes)} notes from this test batch only.")


async def verify():
    from app.api.routers.knowledge import list_prompt_notes, list_prompts
    from app.db import SessionLocal, engine as async_engine

    batch = json.loads(MANIFEST.read_text(encoding="utf-8"))
    wanted_entries, wanted_notes = set(batch["entries"]), set(batch["notes"])
    async with SessionLocal() as db:
        for kind in EXAMPLES:
            entries = await list_prompts(knowledge_type=kind, status_filter=None, db=db, user=None)
            notes = await list_prompt_notes(knowledge_type=kind, db=db, user=None)
            demo_entries = [e for e in entries if str(e.id) in wanted_entries]
            demo_notes = [n for n in notes if str(n.id) in wanted_notes]
            assert len(demo_entries) == 3 and len(demo_notes) == 4
            assert {e.status for e in demo_entries} == {"PENDING_TEST", "PENDING_APPROVAL", "APPROVED"}
            assert all("test" in e.keywords and e.title.startswith(MARKER) for e in demo_entries)
            assert all(len(n.tasks) == 0 for n in demo_notes)
            print(f"{kind}: 4 notes, 3 searchable entries, control/approval/library statuses verified via API serializers.")
    await async_engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--seed", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()
    if args.verify:
        asyncio.run(verify())
    else:
        engine = create_engine(make_url(settings.DATABASE_URL).set(drivername="postgresql"))
        try:
            seed(engine) if args.seed else cleanup(engine)
        finally:
            engine.dispose()
