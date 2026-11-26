from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.api.deps import get_current_user
from app.db import get_db
from app.models.department import Department
from app.models.enums import UserRole
from app.schemas.department import DepartmentOut, DepartmentRealizationModeUpdate
from app.services.audit import add_audit_log
from app.services.development_m1 import build_development_m1
from app.services.development_m2 import build_development_m2
from app.services.development_m3 import build_development_m3


router = APIRouter()


@router.get("/development/m1")
async def get_development_m1(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    report = await build_development_m1(db, user)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Development department not found")
    return report


@router.get("/development/m2")
async def get_development_m2(response: Response, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    report = await build_development_m2(db, user)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Development department not found")
    response.headers["Cache-Control"] = "no-store"
    return report


@router.get("/development/m3")
async def get_development_m3(response: Response, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    report = await build_development_m3(db, user)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Development department not found")
    response.headers["Cache-Control"] = "no-store"
    return report


def _clients_path_for_department(department: Department) -> Path | None:
    lookup_key = re.sub(r"[^A-Z0-9]+", "_", (department.code or department.name or "").upper()).strip("_")
    configured_path = os.getenv(f"CLIENTS_PATH_{lookup_key}")
    identity = f"{department.code or ''} {department.name or ''}".upper()
    if not configured_path and "DEVELOP" in identity:
        configured_path = os.getenv(
            "DEVELOPMENT_CLIENTS_PATH",
            r"\\192.168.10.8\Files\10_ZHVILLIM\05_CLIENTS",
        )
    uses_shared_client_files = any(
        marker in identity
        for marker in ("PRODUCT", "PROJECT CONTENT", "PCM", "GRAPHIC DESIGN")
    )
    if not configured_path and uses_shared_client_files:
        configured_path = os.getenv(
            "PRODUCT_CLIENTS_PATH",
            r"\\192.168.10.8\Klientat\05_CLIENTS",
        )
    return Path(configured_path) if configured_path else None


@router.get("", response_model=list[DepartmentOut])
async def list_departments(db: AsyncSession = Depends(get_db), _=Depends(get_current_user)) -> list[DepartmentOut]:
    departments = (
        await db.execute(
            select(Department)
            .options(load_only(Department.id, Department.name, Department.code, Department.realization_mode))
            .order_by(Department.name)
        )
    ).scalars().all()
    return [
        DepartmentOut(
            id=d.id, name=d.name, code=d.code, realization_mode=d.realization_mode
        )
        for d in departments
    ]


@router.patch("/{department_id}/realization-mode", response_model=DepartmentOut)
async def update_department_realization_mode(
    department_id: uuid.UUID,
    payload: DepartmentRealizationModeUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> DepartmentOut:
    if user.role is not UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    department = await db.get(Department, department_id)
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")
    before = department.realization_mode
    department.realization_mode = payload.realization_mode.value
    add_audit_log(
        db=db,
        actor_user_id=user.id,
        entity_type="department",
        entity_id=department.id,
        action="realization_mode_changed",
        before={"realization_mode": before},
        after={"realization_mode": department.realization_mode},
    )
    await db.commit()
    return DepartmentOut(
        id=department.id,
        name=department.name,
        code=department.code,
        realization_mode=department.realization_mode,
    )


@router.get("/{department_id}/file-clients", response_model=list[str])
async def list_department_file_clients(
    department_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
) -> list[str]:
    department = (
        await db.execute(select(Department).where(Department.id == department_id))
    ).scalar_one_or_none()
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")

    clients_path = _clients_path_for_department(department)
    if clients_path is None:
        return []
    try:
        return sorted(
            [entry.name for entry in clients_path.iterdir() if entry.is_dir() and not entry.name.startswith(".")],
            key=str.casefold,
        )
    except (OSError, PermissionError):
        return []


@router.get("/{department_id}/file-clients/{client_name}/platforms", response_model=list[str])
async def list_department_file_client_platforms(
    department_id: uuid.UUID,
    client_name: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
) -> list[str]:
    department = (
        await db.execute(select(Department).where(Department.id == department_id))
    ).scalar_one_or_none()
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")
    if client_name != Path(client_name).name or client_name in {".", ".."}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid client name")

    clients_path = _clients_path_for_department(department)
    if clients_path is None:
        return []
    try:
        known_clients = {entry.name for entry in clients_path.iterdir() if entry.is_dir() and not entry.name.startswith(".")}
        if client_name not in known_clients:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
        platforms_path = clients_path / client_name / "03_PLATFORMS"
        return sorted(
            [entry.name for entry in platforms_path.iterdir() if entry.is_dir() and not entry.name.startswith(".")],
            key=str.casefold,
        )
    except HTTPException:
        raise
    except (OSError, PermissionError):
        return []

