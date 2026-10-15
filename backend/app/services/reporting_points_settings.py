from __future__ import annotations

from datetime import time
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import select, text

from app.models.after_break_report_settings import AfterBreakReportSettings
from app.models.meetings_report_settings import MeetingsReportSettings
from app.models.reporting_points_settings import ReportingPointsSettings
from app.services.audit import add_audit_log
from app.services.meetings_report_scheduler import normalize_recipients
from app.services.primeflow_report import report_timezone

DEFAULT_TIMES = {"M1": time(8, 30), "M2": time(12, 15), "M3": time(16, 20)}


class RecipientSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: list[EmailStr] = Field(min_length=1, max_length=100)
    cc: list[EmailStr] = Field(default_factory=list, max_length=100)
    bcc: list[EmailStr] = Field(default_factory=list, max_length=100)


class DeliverySettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_active: bool
    send_time: time
    weekdays: list[int] = Field(min_length=1, max_length=7)
    recipients: RecipientSettings
    manual_recipients: RecipientSettings

    @field_validator("weekdays")
    @classmethod
    def valid_days(cls, value):
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("Zgjidh ditët nga e hëna deri të dielën.")
        return sorted(set(value))

    @field_validator("send_time")
    @classmethod
    def valid_time(cls, value):
        if value.tzinfo is not None or value.second or value.microsecond:
            raise ValueError("Ora duhet të jetë lokale, në formatin HH:MM.")
        return value


def default_settings(report_type: str):
    return ReportingPointsSettings(
        report_type=report_type, is_active=True, send_time=DEFAULT_TIMES[report_type],
        weekdays=[0, 1, 2, 3, 4],
        recipients={"to": ["ga@primexeu.com", "info@primexeu.com"], "cc": [], "bcc": []},
        manual_recipients=None,
    )


async def settings_lock(db, report_type: str, *, wait: bool = True) -> bool:
    function = "pg_advisory_xact_lock" if wait else "pg_try_advisory_xact_lock"
    acquired = (await db.execute(text(f"SELECT {function}(hashtext(:key))"),
                                {"key": f"reporting_points_settings|{report_type}"})).scalar()
    return wait or bool(acquired)


async def get_delivery_settings(db, report_type: str, *, lock: bool = False, wait: bool = True):
    if lock and not await settings_lock(db, report_type, wait=wait):
        return None
    row = (await db.execute(select(ReportingPointsSettings).where(
        ReportingPointsSettings.report_type == report_type))).scalars().first()
    return row if row is not None else default_settings(report_type)


async def manual_recipients(db, report_type: str, settings) -> dict:
    if settings.manual_recipients is not None:
        return normalize_recipients(settings.manual_recipients)
    if report_type == "M1":
        return normalize_recipients(settings.recipients)
    legacy_model = AfterBreakReportSettings if report_type == "M2" else MeetingsReportSettings
    legacy = (await db.execute(select(legacy_model).order_by(legacy_model.created_at))).scalars().first()
    return normalize_recipients(legacy.recipients if legacy else settings.recipients)


def settings_payload(settings, manual: dict) -> dict:
    return {"report_type": settings.report_type, "is_active": settings.is_active,
            "send_time": settings.send_time.strftime("%H:%M"), "weekdays": settings.weekdays,
            "timezone": report_timezone().key, "recipients": normalize_recipients(settings.recipients),
            "manual_recipients": manual}


async def read_settings(db, report_type: str) -> dict:
    settings = await get_delivery_settings(db, report_type)
    return settings_payload(settings, await manual_recipients(db, report_type, settings))


async def save_settings(db, report_type: str, payload: DeliverySettingsPayload, user_id) -> dict:
    if report_type == "M1" and payload.send_time < time(8, 30):
        raise ValueError("Dërgimi automatik i M1 duhet të jetë në 08:30 ose më vonë.")
    if report_type == "M3" and payload.send_time < time(16, 15):
        raise ValueError("Dërgimi automatik i M3 duhet të jetë në 16:15 ose më vonë, pasi merret realizimi.")
    await settings_lock(db, report_type)
    row = (await db.execute(select(ReportingPointsSettings).where(
        ReportingPointsSettings.report_type == report_type))).scalars().first()
    if row is None:
        row = default_settings(report_type)
        db.add(row)
    before = settings_payload(row, await manual_recipients(db, report_type, row))
    row.is_active, row.send_time, row.weekdays = payload.is_active, payload.send_time, payload.weekdays
    row.recipients = normalize_recipients(payload.recipients.model_dump())
    row.manual_recipients = normalize_recipients(payload.manual_recipients.model_dump())
    row.updated_by = user_id
    after = settings_payload(row, row.manual_recipients)
    add_audit_log(db=db, actor_user_id=user_id, entity_type=f"{report_type.lower()}_reporting_points",
                  entity_id=uuid5(NAMESPACE_URL, f"primeflow:reporting-points-settings:{report_type}"),
                  action="UPDATE_DELIVERY_SETTINGS", before=before, after=after)
    await db.commit()
    return after
