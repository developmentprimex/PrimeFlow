"""Check columns required by the application and restored deployed revisions."""

import asyncio

from sqlalchemy import text

from app.db import engine


EXPECTED_COLUMNS = {
    ("meeting_recordings", "deleted_at"),
    ("meeting_recordings", "files_purged_at"),
    *(("reporting_points_settings", column) for column in (
        "report_type", "is_active", "send_time", "weekdays", "recipients", "manual_recipients", "updated_by", "updated_at",
    )),
    *(("m3_reporting_points_reports", column) for column in (
        "id", "report_date", "manual_answers", "data", "realization",
        "realization_captured_at", "generated_at", "status", "sent_at", "auto_sent_at",
        "gmail_message_id", "last_error", "updated_by", "created_at", "updated_at",
    )),
    ("m2_reporting_points_reports", "auto_sent_at"),
    ("ga_notes", "knowledge_tester_id"),
    ("knowledge_prompts", "tester_id"),
    ("knowledge_prompts", "test_task_id"),
    ("realization_daily_close_events", "daily_comment"),
    *(("realization_daily_person_comments", column) for column in (
        "id", "period_id", "user_id", "comment", "updated_by", "created_at", "updated_at",
    )),
}


async def main() -> None:
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema()"
                )
            )
            present = {(row.table_name, row.column_name) for row in rows}
        missing = sorted(EXPECTED_COLUMNS - present)
        if missing:
            raise RuntimeError(f"Missing migration columns: {missing}")
        print("Required migration columns: OK")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
