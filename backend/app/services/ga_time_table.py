from dataclasses import dataclass
from datetime import date, datetime, time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ga_time_table_row import GaTimeTableRow
from app.models.user import User
from app.services import ga_assistant
from app.services.ga_icloud_sync import TimeRow, resolve_row


@dataclass(frozen=True)
class GaTimeTableRowData:
    sort_order: int
    nr_label: str
    label: str
    start_time: time
    end_time: time
    is_special: bool = False
    comment: str = ""
    comment_background_color: str = "#FFFFFF"
    comment_text_color: str = "#0F172A"
    comment_is_bold: bool = False
    comment_is_italic: bool = False


@dataclass(frozen=True)
class GaTimeTableTask:
    task_id: UUID
    day: date
    row_start: time
    scheduled_time: time | None
    text: str


def _time(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


DEFAULT_GA_TIME_TABLE_ROWS: tuple[GaTimeTableRowData, ...] = (
    GaTimeTableRowData(0, "", "", _time("00:00"), _time("00:01"), True),
    GaTimeTableRowData(1, "", "", _time("00:01"), _time("00:02"), True),
    GaTimeTableRowData(2, "1", "07:30 - 08:00", _time("07:30"), _time("08:00")),
    GaTimeTableRowData(3, "2", "08:00 - 09:00", _time("08:00"), _time("09:00")),
    GaTimeTableRowData(4, "3", "09:00 - 10:00", _time("09:00"), _time("10:00")),
    GaTimeTableRowData(5, "4", "10:00 - 11:00", _time("10:00"), _time("11:00")),
    GaTimeTableRowData(6, "5", "11:00 - 12:00", _time("11:00"), _time("12:00")),
    GaTimeTableRowData(7, "6", "12:00 - 13:00", _time("12:00"), _time("13:00")),
    GaTimeTableRowData(8, "7", "13:00 - 13:30", _time("13:00"), _time("13:30")),
    GaTimeTableRowData(9, "8", "13:30 - 14:00", _time("13:30"), _time("14:00")),
    GaTimeTableRowData(10, "9", "14:00 - 14:30", _time("14:00"), _time("14:30")),
    GaTimeTableRowData(11, "10", "14:30 - 15:30", _time("14:30"), _time("15:30")),
    GaTimeTableRowData(12, "11", "15:30 - 16:00", _time("15:30"), _time("16:00")),
    GaTimeTableRowData(13, "12", "16:00 - 16:30", _time("16:00"), _time("16:30")),
    GaTimeTableRowData(14, "13", "16:30 - 17:00", _time("16:30"), _time("17:00")),
    GaTimeTableRowData(15, "14", "17:00 - 18:00", _time("17:00"), _time("18:00")),
    GaTimeTableRowData(16, "15", "18:00 - 19:00", _time("18:00"), _time("19:00")),
    GaTimeTableRowData(17, "16", "19:00 - 20:00", _time("19:00"), _time("20:00")),
    GaTimeTableRowData(18, "17", "20:00 - 21:00", _time("20:00"), _time("21:00")),
    GaTimeTableRowData(19, "18", "21:00 - 22:00", _time("21:00"), _time("22:00")),
)


def format_ga_time_label(start_time: time, end_time: time) -> str:
    return f"{start_time.hour:02d}:{start_time.minute:02d} - {end_time.hour:02d}:{end_time.minute:02d}"


async def get_ga_time_table_rows(db: AsyncSession) -> list[GaTimeTableRow | GaTimeTableRowData]:
    rows = (
        await db.execute(
            select(GaTimeTableRow)
            .order_by(GaTimeTableRow.sort_order, GaTimeTableRow.start_time)
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    return list(rows) if rows else list(DEFAULT_GA_TIME_TABLE_ROWS)


async def get_ga_time_table_tasks(
    db: AsyncSession,
    owner: User,
    day_from: date,
    day_to: date,
    rows: list[GaTimeTableRow | GaTimeTableRowData],
) -> list[GaTimeTableTask]:
    tz = ga_assistant.ga_tz()
    items = await ga_assistant.collect_task_items(db, owner, day_from, day_to, today=datetime.now(tz).date(), tz=tz)
    tasks = [
        item for item in items
        if item.kind == ga_assistant.KIND_GA_TASK and item.day is not None and day_from <= item.day <= day_to
    ]
    if not tasks:
        return []

    states = await ga_assistant.load_day_states(db, owner.id, day_from, day_to)
    tasks = ga_assistant.apply_day_states(tasks, states, tz)
    timed_rows = [TimeRow(row.start_time, row.end_time) for row in rows if not row.is_special]
    untimed_start = next((row.start_time for row in rows if row.is_special), rows[0].start_time)
    result = []
    for item in sorted(tasks, key=ga_assistant.sort_key):
        clock = item.start.time() if item.start else None
        row = resolve_row(clock, timed_rows) if clock is not None else None
        prefix = f"{clock:%H:%M} " if clock is not None else ""
        status = "✓ Done " if not item.is_open else ""
        result.append(GaTimeTableTask(
            task_id=UUID(item.id.removeprefix(ga_assistant.PREFIX_TASK)),
            day=item.day,
            row_start=row.start if row else untimed_start,
            scheduled_time=clock,
            text=f"{status}{prefix}{item.title}",
        ))
    return result
