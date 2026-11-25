from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import get_db
from app.models.user import User
from app.services.discord_task_deliveries import build_report, save_comment
from app.services.primeflow_report import report_timezone

router = APIRouter()


class DeliveryCommentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    comment: str = Field(max_length=2000)


@router.get("")
async def get_report(
    response: Response,
    report_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    today = datetime.now(report_timezone()).date()
    if report_date and report_date > today:
        raise HTTPException(422, "Data e raportit duhet të jetë sot ose më herët.")
    response.headers["Cache-Control"] = "private, no-store"
    return await build_report(db, report_date or today)


@router.put("/{report_date}/comments/{row_id}")
async def put_comment(
    report_date: date,
    payload: DeliveryCommentPayload,
    row_id: str = Path(max_length=73),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    if report_date > datetime.now(report_timezone()).date():
        raise HTTPException(422, "Data e raportit duhet të jetë sot ose më herët.")
    return {"comment": await save_comment(db, report_date, row_id, payload.comment)}
