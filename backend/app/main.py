from __future__ import annotations

import asyncio
import os
import uuid

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from starlette.middleware.gzip import GZipMiddleware

from app.auth.security import ACCESS_TOKEN_TYPE, decode_token, require_token_type
from app.api.routers import api_router
from app.api.routers.ga_caldav import router as ga_caldav_router
from app.config import settings
from app.jobs.recording_files_archive import run_recording_files_archive_forever
from app.services.meetings_report_scheduler import run_meetings_report_scheduler_forever
from app.services.m3_reporting_points_scheduler import run_m3_reporting_points_scheduler_forever
from app.services.reporting_points_auto_scheduler import run_reporting_points_auto_scheduler_forever
from app.services.meeting_reminder_scheduler import run_meeting_reminder_scheduler_forever
from app.services.microsoft_calendar_sync_scheduler import run_microsoft_calendar_sync_forever
from app.services.after_break_report_scheduler import run_after_break_report_scheduler_forever
from app.services.end_week_bz_report_scheduler import run_end_week_bz_report_scheduler_forever
from app.services.morning_report_scheduler import run_morning_report_scheduler_forever
from app.services.tomorrow_print_report_scheduler import run_tomorrow_print_report_scheduler_forever
from app.services.today_print_report_scheduler import run_today_print_report_scheduler_forever
from app.services.today_print_report_freeze import run_today_print_report_freeze_scheduler_forever
from app.services.std_feedback_tickets import run_std_feedback_ticket_sync_forever
from app.services.system_task_scheduler import (
    run_system_task_daily_reconciliation_forever,
    run_system_task_scheduler_forever,
)
from app.websocket.redis_listener import start_notification_listener
from app.websocket.manager import manager


app = FastAPI(title="Primex Nexus", default_response_class=ORJSONResponse)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)
# Level 3 retains nearly all JSON compression while spending materially less
# CPU on the large planner, task and report payloads.
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=3)

app.include_router(api_router, prefix="/api")
# CalDAV clients address the account by absolute path, so it lives at the site root.
app.include_router(ga_caldav_router)

listener_task: asyncio.Task | None = None
recording_files_archive_task: asyncio.Task | None = None
scheduler_task: asyncio.Task | None = None
system_task_daily_reconciliation_task: asyncio.Task | None = None
meetings_report_scheduler_task: asyncio.Task | None = None
m3_reporting_points_scheduler_task: asyncio.Task | None = None
reporting_points_auto_scheduler_task: asyncio.Task | None = None
after_break_report_scheduler_task: asyncio.Task | None = None
end_week_bz_report_scheduler_task: asyncio.Task | None = None
morning_report_scheduler_task: asyncio.Task | None = None
tomorrow_print_report_scheduler_task: asyncio.Task | None = None
today_print_report_scheduler_task: asyncio.Task | None = None
today_print_report_freeze_scheduler_task: asyncio.Task | None = None
std_feedback_sync_task: asyncio.Task | None = None
microsoft_calendar_sync_task: asyncio.Task | None = None
meeting_reminder_scheduler_task: asyncio.Task | None = None

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "build": os.getenv("APP_BUILD_SHA", "unknown")}


@app.on_event("startup")
async def _startup() -> None:
    global recording_files_archive_task
    recording_files_archive_task = asyncio.create_task(run_recording_files_archive_forever())
    global m3_reporting_points_scheduler_task
    global reporting_points_auto_scheduler_task
    global today_print_report_freeze_scheduler_task
    global listener_task, scheduler_task, system_task_daily_reconciliation_task, meetings_report_scheduler_task, after_break_report_scheduler_task, end_week_bz_report_scheduler_task, morning_report_scheduler_task, tomorrow_print_report_scheduler_task, today_print_report_scheduler_task, std_feedback_sync_task, microsoft_calendar_sync_task, meeting_reminder_scheduler_task
    if settings.REDIS_ENABLED:
        listener_task = asyncio.create_task(start_notification_listener())
    if settings.SYSTEM_TASK_SCHEDULER_ENABLED:
        scheduler_task = asyncio.create_task(run_system_task_scheduler_forever())
        system_task_daily_reconciliation_task = asyncio.create_task(
            run_system_task_daily_reconciliation_forever()
        )
    if settings.REPORT_SCHEDULERS_ENABLED:
        today_print_report_freeze_scheduler_task = asyncio.create_task(run_today_print_report_freeze_scheduler_forever())
        m3_reporting_points_scheduler_task = asyncio.create_task(run_m3_reporting_points_scheduler_forever())
        reporting_points_auto_scheduler_task = asyncio.create_task(run_reporting_points_auto_scheduler_forever())
        meetings_report_scheduler_task = asyncio.create_task(run_meetings_report_scheduler_forever())
        after_break_report_scheduler_task = asyncio.create_task(run_after_break_report_scheduler_forever())
        end_week_bz_report_scheduler_task = asyncio.create_task(run_end_week_bz_report_scheduler_forever())
        morning_report_scheduler_task = asyncio.create_task(run_morning_report_scheduler_forever())
        if settings.TOMORROW_PRINT_REPORT_SCHEDULER_ENABLED:
            tomorrow_print_report_scheduler_task = asyncio.create_task(run_tomorrow_print_report_scheduler_forever())
        if settings.TODAY_PRINT_REPORT_SCHEDULER_ENABLED:
            today_print_report_scheduler_task = asyncio.create_task(run_today_print_report_scheduler_forever())
    if settings.STD_FEEDBACK_SYNC_ENABLED:
        std_feedback_sync_task = asyncio.create_task(run_std_feedback_ticket_sync_forever())
    if settings.MS_CALENDAR_SYNC_ENABLED:
        microsoft_calendar_sync_task = asyncio.create_task(run_microsoft_calendar_sync_forever())
    if settings.MEETING_REMINDER_SCHEDULER_ENABLED:
        meeting_reminder_scheduler_task = asyncio.create_task(run_meeting_reminder_scheduler_forever())


@app.on_event("shutdown")
async def _shutdown() -> None:
    global recording_files_archive_task
    if recording_files_archive_task is not None:
        recording_files_archive_task.cancel()
        try:
            await recording_files_archive_task
        except asyncio.CancelledError:
            pass
        recording_files_archive_task = None
    global m3_reporting_points_scheduler_task
    global reporting_points_auto_scheduler_task
    global today_print_report_freeze_scheduler_task
    global listener_task, scheduler_task, system_task_daily_reconciliation_task, meetings_report_scheduler_task, after_break_report_scheduler_task, end_week_bz_report_scheduler_task, morning_report_scheduler_task, tomorrow_print_report_scheduler_task, today_print_report_scheduler_task, std_feedback_sync_task, microsoft_calendar_sync_task, meeting_reminder_scheduler_task
    if reporting_points_auto_scheduler_task is not None:
        reporting_points_auto_scheduler_task.cancel()
        try:
            await reporting_points_auto_scheduler_task
        except asyncio.CancelledError:
            pass
        reporting_points_auto_scheduler_task = None
    if today_print_report_freeze_scheduler_task is not None:
        today_print_report_freeze_scheduler_task.cancel()
        try:
            await today_print_report_freeze_scheduler_task
        except asyncio.CancelledError:
            pass
        today_print_report_freeze_scheduler_task = None
    if m3_reporting_points_scheduler_task is not None:
        m3_reporting_points_scheduler_task.cancel()
        try:
            await m3_reporting_points_scheduler_task
        except asyncio.CancelledError:
            pass
        m3_reporting_points_scheduler_task = None
    if listener_task is not None:
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass
        listener_task = None
    if scheduler_task is not None:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
        scheduler_task = None
    if system_task_daily_reconciliation_task is not None:
        system_task_daily_reconciliation_task.cancel()
        try:
            await system_task_daily_reconciliation_task
        except asyncio.CancelledError:
            pass
        system_task_daily_reconciliation_task = None
    if meetings_report_scheduler_task is not None:
        meetings_report_scheduler_task.cancel()
        try:
            await meetings_report_scheduler_task
        except asyncio.CancelledError:
            pass
        meetings_report_scheduler_task = None
    if after_break_report_scheduler_task is not None:
        after_break_report_scheduler_task.cancel()
        try:
            await after_break_report_scheduler_task
        except asyncio.CancelledError:
            pass
        after_break_report_scheduler_task = None
    if end_week_bz_report_scheduler_task is not None:
        end_week_bz_report_scheduler_task.cancel()
        try:
            await end_week_bz_report_scheduler_task
        except asyncio.CancelledError:
            pass
        end_week_bz_report_scheduler_task = None
    if morning_report_scheduler_task is not None:
        morning_report_scheduler_task.cancel()
        try:
            await morning_report_scheduler_task
        except asyncio.CancelledError:
            pass
        morning_report_scheduler_task = None
    if tomorrow_print_report_scheduler_task is not None:
        tomorrow_print_report_scheduler_task.cancel()
        try:
            await tomorrow_print_report_scheduler_task
        except asyncio.CancelledError:
            pass
        tomorrow_print_report_scheduler_task = None
    if today_print_report_scheduler_task is not None:
        today_print_report_scheduler_task.cancel()
        try:
            await today_print_report_scheduler_task
        except asyncio.CancelledError:
            pass
        today_print_report_scheduler_task = None
    if std_feedback_sync_task is not None:
        std_feedback_sync_task.cancel()
        try:
            await std_feedback_sync_task
        except asyncio.CancelledError:
            pass
        std_feedback_sync_task = None
    if microsoft_calendar_sync_task is not None:
        microsoft_calendar_sync_task.cancel()
        try:
            await microsoft_calendar_sync_task
        except asyncio.CancelledError:
            pass
        microsoft_calendar_sync_task = None
    if meeting_reminder_scheduler_task is not None:
        meeting_reminder_scheduler_task.cancel()
        try:
            await meeting_reminder_scheduler_task
        except asyncio.CancelledError:
            pass
        meeting_reminder_scheduler_task = None


@app.websocket("/ws/notifications")
async def ws_notifications(websocket: WebSocket, token: str = Query(...)) -> None:
    try:
        payload = decode_token(token)
        require_token_type(payload, ACCESS_TOKEN_TYPE)
        user_id = uuid.UUID(str(payload.get("sub")))
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    await manager.connect(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(user_id, websocket)

