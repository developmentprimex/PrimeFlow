"""Kujtesa e Mira-s: every signed-in staff member reads and corrects the register."""
import uuid
from typing import Literal
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user
from app.db import get_db
from app.schemas.mira_memory import MemoryEdit, MemoryStatusChange
from app.services import mira_memory

router = APIRouter()


@router.get('/items')
async def list_items(status: Literal['open', 'closed', 'all'] = 'open', db: AsyncSession = Depends(get_db),
        user=Depends(get_current_user)):
    return await mira_memory.list_items(db, status)


@router.get('/items/{item_id}')
async def get_item(item_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return await mira_memory.get_item(db, item_id)


@router.patch('/items/{item_id}')
async def edit_item(item_id: uuid.UUID, payload: MemoryEdit, db: AsyncSession = Depends(get_db),
        user=Depends(get_current_user)):
    return await mira_memory.edit_item(db, user, item_id, payload)


@router.post('/items/{item_id}/status')
async def set_status(item_id: uuid.UUID, payload: MemoryStatusChange, db: AsyncSession = Depends(get_db),
        user=Depends(get_current_user)):
    return await mira_memory.set_status(db, user, item_id, payload)


@router.post('/retry-failed')
async def retry_failed(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return await mira_memory.retry_failed(db, user)
