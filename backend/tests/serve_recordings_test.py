"""Dedicated test API; never run this module as a production server."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recording_test_support import configure_test_environment, prepare_database

configure_test_environment()
fixture_path = Path(__file__).resolve().parents[2] / "tmp/recorder-fixture.json"
if "--prepare" in sys.argv:
    fixture_path.write_text(json.dumps(prepare_database(full_schema=True)), encoding="utf-8")
    print("Isolated recorder browser fixture prepared")
    raise SystemExit(0)

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
import uvicorn
from app.api.deps import get_current_user
from app.api.routers.meeting_recordings import router
from app.api.routers.recording_analysis import router as analysis_router
from app.db import get_db
from app.models.meeting import Meeting, MeetingParticipant

if not fixture_path.is_file():
    raise RuntimeError("Prepare the isolated browser fixture first")
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:3100"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(router, prefix="/api/meeting-recordings")
app.include_router(analysis_router, prefix="/api/meeting-recordings")


@app.get("/api/auth/me")
async def me(user=Depends(get_current_user)):
    return {key: getattr(user, key) for key in ["id", "email", "username", "full_name", "role", "department_id", "is_active"]}


@app.get("/api/meetings")
async def meetings(db=Depends(get_db), user=Depends(get_current_user)):
    rows = (await db.execute(select(Meeting))).scalars().all()
    result = []
    for row in rows:
        participant_ids = (await db.execute(select(MeetingParticipant.user_id).where(MeetingParticipant.meeting_id == row.id))).scalars().all()
        result.append({"id": row.id, "title": row.title, "created_by": row.created_by, "participant_ids": participant_ids})
    return result


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8012, access_log=False, log_level="warning")
