from __future__ import annotations

import hashlib
import json
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.api.deps import get_current_user
from app.config import settings
from app.db import get_db
from app.services import voice_assistant as voice

router = APIRouter()


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sdp: str = Field(min_length=10, max_length=100000)
    mode: Literal["tasks", "px_notes"] = "tasks"


@router.post("/session")
async def create_session(payload: SessionRequest, user=Depends(get_current_user)):
    if not settings.OPENAI_API_KEY:
        raise HTTPException(503, "Asistentja zanore nuk është konfiguruar. Vendos OPENAI_API_KEY në backend.")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            result = await client.post(
                "https://api.openai.com/v1/realtime/calls",
                headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                         "OpenAI-Safety-Identifier": hashlib.sha256(str(user.id).encode()).hexdigest()},
                files={"sdp": (None, payload.sdp), "session": (None, json.dumps(voice.session_config(user, mode=payload.mode)))},
            )
    except httpx.RequestError:
        raise HTTPException(502, "Nuk u lidhëm me shërbimin zanor. Provo përsëri.")
    if result.is_error:
        # Never forward provider bodies, credentials or session configuration.
        raise HTTPException(502, "OpenAI refuzoi lidhjen zanore. Kontrollo modelin, API key dhe kreditin e llogarisë.")
    return Response(result.text, media_type="application/sdp", headers={"Cache-Control": "no-store"})


@router.post("/tools/{name}")
async def run_tool(name: str, payload: dict, user=Depends(get_current_user), db=Depends(get_db)):
    try:
        return await voice.execute_tool(user, name, payload, db=db)
    except (ValidationError, ValueError):
        raise HTTPException(422, "Argumentet e veprimit nuk janë të vlefshme. Lexo detyrën dhe kërko sqarim.")
