import uuid
import hmac
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import get_db
from app.models.enums import UserRole
from app.models.ga_icloud_sync_connection import GaIcloudSyncConnection
from app.models.ga_time_slot_entry import GaTimeSlotEntry
from app.models.ga_time_table_row import GaTimeTableRow
from app.models.ga_time_slot_template import GaTimeSlotTemplate
from app.models.meeting import Meeting
from app.models.user import User
from app.schemas.ga_time_slot import (
    GaTimeSlotEntriesReorder,
    GaTimeSlotEntryIn,
    GaTimeSlotEntryOut,
    GaTimeSlotEntryUpdate,
    GaIcloudSyncConnectionCreate,
    GaIcloudSyncConnectionOut,
    GaIcloudSyncImport,
    GaIcloudSyncImportOut,
    GaIcloudSyncPairingOut,
    GaTimeTableCommentToSlotMove,
    GaTimeTableCrossCellMoveOut,
    GaTimeTableEntryToCommentMove,
    GaTimeTableRowComment,
    GaTimeTableRowCommentMove,
    GaTimeTableRowCommentUpdate,
    GaTimeTableRowCommentsUpdate,
    GaTimeTableRowIn,
    GaTimeTableRowOut,
    GaTimeTableRowsUpdate,
)
from app.services.ga_time_table import (
    DEFAULT_GA_TIME_TABLE_ROWS,
    GaTimeTableRowData,
    format_ga_time_label,
    get_ga_time_table_rows,
)
from app.services.ga_calendar_feed import build_ga_calendar, feed_token, is_valid_feed_token
from app.services.ga_icloud_sync import (
    TimeRow,
    connection_id_from_token,
    generate_connection_token,
    hash_connection_token,
    prepare_calendar_item,
    prepare_reminder_item,
    resolve_timezone,
)


router = APIRouter()

GA_USERNAME = "gane.arifaj"
GA_EMAIL = "ga@primexeu.com"


async def _resolve_ga_user(db: AsyncSession) -> User | None:
    stmt = select(User).where(
        func.lower(User.username) == GA_USERNAME,
    )
    ga_user = (await db.execute(stmt)).scalar_one_or_none()
    if ga_user:
        return ga_user
    stmt = select(User).where(func.lower(User.email) == GA_EMAIL)
    return (await db.execute(stmt)).scalar_one_or_none()


def _ensure_can_edit(current_user: User) -> None:
    if current_user.role == UserRole.ADMIN:
        return
    if (current_user.username or "").lower() == GA_USERNAME:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")


def _row_out(row: GaTimeTableRow | GaTimeTableRowData) -> GaTimeTableRowOut:
    comments: list[GaTimeTableRowComment] = []
    end_comments: list[GaTimeTableRowComment] = []
    for raw_comment in getattr(row, "comments", None) or []:
        try:
            parsed_comment = GaTimeTableRowComment.model_validate(raw_comment)
            if parsed_comment.column == "end":
                end_comments.append(parsed_comment)
            else:
                comments.append(parsed_comment)
        except (TypeError, ValueError):
            continue
    legacy_comment = (getattr(row, "comment", "") or "").strip()
    if not comments and legacy_comment:
        legacy_key = getattr(row, "id", None) or f"{row.start_time}-{row.end_time}"
        comments.append(
            GaTimeTableRowComment(
                id=f"legacy-{legacy_key}",
                content=legacy_comment,
                comment_background_color=getattr(row, "comment_background_color", "#FFFFFF") or "#FFFFFF",
                comment_text_color=getattr(row, "comment_text_color", "#0F172A") or "#0F172A",
                comment_is_bold=bool(getattr(row, "comment_is_bold", False)),
                comment_is_italic=bool(getattr(row, "comment_is_italic", False)),
            )
        )
    return GaTimeTableRowOut(
        id=getattr(row, "id", None),
        sort_order=row.sort_order,
        nr_label=row.nr_label,
        label=row.label,
        start_time=row.start_time,
        end_time=row.end_time,
        is_special=row.is_special,
        comment=getattr(row, "comment", "") or "",
        comment_background_color=getattr(row, "comment_background_color", "#FFFFFF") or "#FFFFFF",
        comment_text_color=getattr(row, "comment_text_color", "#0F172A") or "#0F172A",
        comment_is_bold=bool(getattr(row, "comment_is_bold", False)),
        comment_is_italic=bool(getattr(row, "comment_is_italic", False)),
        comments=comments,
        end_comments=end_comments,
    )


def _entry_out(entry: GaTimeSlotTemplate) -> GaTimeSlotEntryOut:
    return GaTimeSlotEntryOut(
        id=entry.id,
        user_id=entry.user_id,
        day_of_week=entry.day_of_week,
        start_time=entry.start_time,
        end_time=entry.end_time,
        content=entry.content,
        sort_order=entry.sort_order,
        background_color=entry.background_color,
        text_color=entry.text_color,
        is_bold=entry.is_bold,
        is_italic=entry.is_italic,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
        occurrence_date=None,
        source_type=None,
        source_name=None,
    )


def _dated_entry_out(entry: GaTimeSlotEntry) -> GaTimeSlotEntryOut:
    return GaTimeSlotEntryOut(
        id=entry.id,
        user_id=entry.user_id,
        day_of_week=entry.day_date.weekday(),
        start_time=entry.start_time,
        end_time=entry.end_time,
        content=entry.content,
        sort_order=0,
        background_color="#E0F2FE" if entry.source_type == "calendar" else "#FEF3C7",
        text_color="#0F172A",
        is_bold=False,
        is_italic=False,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
        occurrence_date=entry.day_date,
        source_type=entry.source_type,
        source_name=entry.source_name,
    )


def _connection_out(connection: GaIcloudSyncConnection) -> GaIcloudSyncConnectionOut:
    return GaIcloudSyncConnectionOut(
        id=connection.id,
        device_name=connection.device_name,
        calendar_name=connection.calendar_name,
        reminder_list_name=connection.reminder_list_name,
        last_synced_at=connection.last_synced_at,
        last_imported_count=connection.last_imported_count,
        created_at=connection.created_at,
    )


async def _connection_from_sync_token(
    db: AsyncSession,
    raw_token: str | None,
    *,
    lock: bool = False,
) -> GaIcloudSyncConnection:
    token = (raw_token or "").strip()
    connection_id = connection_id_from_token(token)
    if connection_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid sync token")

    statement = select(GaIcloudSyncConnection).where(
        GaIcloudSyncConnection.id == connection_id,
        GaIcloudSyncConnection.revoked_at.is_(None),
    )
    if lock:
        statement = statement.with_for_update()
    connection = (await db.execute(statement)).scalar_one_or_none()
    if connection is None or not hmac.compare_digest(connection.token_hash, hash_connection_token(token)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid sync token")
    return connection


def _replace_row_comments(
    row: GaTimeTableRow,
    start_comments: list[GaTimeTableRowComment],
    end_comments: list[GaTimeTableRowComment],
) -> None:
    row.comments = [
        *[{**comment.model_dump(mode="json"), "column": "start"} for comment in start_comments],
        *[{**comment.model_dump(mode="json"), "column": "end"} for comment in end_comments],
    ]
    row.comment = "\n".join(comment.content.strip() for comment in start_comments)
    if start_comments:
        first = start_comments[0]
        row.comment_background_color = first.comment_background_color
        row.comment_text_color = first.comment_text_color
        row.comment_is_bold = first.comment_is_bold
        row.comment_is_italic = first.comment_is_italic
    else:
        row.comment_background_color = "#FFFFFF"
        row.comment_text_color = "#0F172A"
        row.comment_is_bold = False
        row.comment_is_italic = False


@router.get("/rows", response_model=list[GaTimeTableRowOut])
async def list_ga_time_table_rows(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[GaTimeTableRowOut]:
    rows = await get_ga_time_table_rows(db)
    return [_row_out(row) for row in rows]


@router.put("/rows", response_model=list[GaTimeTableRowOut])
async def update_ga_time_table_rows(
    payload: GaTimeTableRowsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[GaTimeTableRowOut]:
    _ensure_can_edit(current_user)
    visible_rows = sorted(payload.rows, key=lambda row: row.start_time)
    if not visible_rows:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="At least one row is required")
    for idx, row in enumerate(visible_rows):
        if row.start_time >= row.end_time:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="End time must be after start time")
        if idx > 0 and visible_rows[idx - 1].end_time > row.start_time:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Rows cannot overlap")

    existing_rows = (
        await db.execute(select(GaTimeTableRow))
    ).scalars().all()
    existing_comments = {
        (row.start_time, row.end_time, row.is_special): {
            "comment": row.comment or "",
            "comment_background_color": row.comment_background_color or "#FFFFFF",
            "comment_text_color": row.comment_text_color or "#0F172A",
            "comment_is_bold": bool(row.comment_is_bold),
            "comment_is_italic": bool(row.comment_is_italic),
            "comments": list(row.comments or []),
        }
        for row in existing_rows
    }
    await db.execute(delete(GaTimeTableRow))
    rows: list[GaTimeTableRow] = [
        GaTimeTableRow(
            sort_order=0,
            nr_label="",
            label="",
            start_time=time(0, 0),
            end_time=time(0, 1),
            is_special=True,
            **existing_comments.get((time(0, 0), time(0, 1), True), {}),
        ),
        GaTimeTableRow(
            sort_order=1,
            nr_label="",
            label="",
            start_time=time(0, 1),
            end_time=time(0, 2),
            is_special=True,
            **existing_comments.get((time(0, 1), time(0, 2), True), {}),
        ),
    ]
    for idx, row in enumerate(visible_rows, start=1):
        rows.append(
            GaTimeTableRow(
                sort_order=idx + 1,
                nr_label=str(idx),
                label=format_ga_time_label(row.start_time, row.end_time),
                start_time=row.start_time,
                end_time=row.end_time,
                is_special=False,
                **existing_comments.get(
                    (row.start_time, row.end_time, False),
                    {
                        "comment": row.comment.strip(),
                        "comment_background_color": row.comment_background_color,
                        "comment_text_color": row.comment_text_color,
                        "comment_is_bold": row.comment_is_bold,
                        "comment_is_italic": row.comment_is_italic,
                    },
                ),
            )
        )
    db.add_all(rows)
    await db.commit()
    for row in rows:
        await db.refresh(row)
    return [_row_out(row) for row in rows]


@router.post("/rows", response_model=list[GaTimeTableRowOut], status_code=status.HTTP_201_CREATED)
async def create_ga_time_table_row(
    payload: GaTimeTableRowIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[GaTimeTableRowOut]:
    _ensure_can_edit(current_user)
    if payload.start_time >= payload.end_time:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="End time must be after start time",
        )

    stored_rows = (
        await db.execute(
            select(GaTimeTableRow)
            .order_by(GaTimeTableRow.sort_order, GaTimeTableRow.start_time)
            .with_for_update()
        )
    ).scalars().all()

    if not stored_rows:
        stored_rows = [
            GaTimeTableRow(
                sort_order=row.sort_order,
                nr_label=row.nr_label,
                label=row.label,
                start_time=row.start_time,
                end_time=row.end_time,
                is_special=row.is_special,
                comment=row.comment,
                comment_background_color=row.comment_background_color,
                comment_text_color=row.comment_text_color,
                comment_is_bold=row.comment_is_bold,
                comment_is_italic=row.comment_is_italic,
            )
            for row in DEFAULT_GA_TIME_TABLE_ROWS
        ]
        db.add_all(stored_rows)
        await db.flush()

    visible_rows = [row for row in stored_rows if not row.is_special]
    overlapping_rows = [
        existing
        for existing in visible_rows
        if existing.start_time < payload.end_time and payload.start_time < existing.end_time
    ]

    if overlapping_rows:
        containing_row = overlapping_rows[0] if len(overlapping_rows) == 1 else None
        if (
            containing_row is None
            or payload.start_time < containing_row.start_time
            or payload.end_time > containing_row.end_time
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Rows cannot partially overlap",
            )
        if (
            payload.start_time == containing_row.start_time
            and payload.end_time == containing_row.end_time
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This time row already exists",
            )

        original_start = containing_row.start_time
        original_end = containing_row.end_time
        containing_row.start_time = payload.start_time
        containing_row.end_time = payload.end_time

        split_rows: list[GaTimeTableRow] = []
        if original_start < payload.start_time:
            split_rows.append(
                GaTimeTableRow(
                    sort_order=0,
                    nr_label="",
                    label=format_ga_time_label(original_start, payload.start_time),
                    start_time=original_start,
                    end_time=payload.start_time,
                    is_special=False,
                )
            )
        if payload.end_time < original_end:
            split_rows.append(
                GaTimeTableRow(
                    sort_order=0,
                    nr_label="",
                    label=format_ga_time_label(payload.end_time, original_end),
                    start_time=payload.end_time,
                    end_time=original_end,
                    is_special=False,
                )
            )
        db.add_all(split_rows)
        visible_rows.extend(split_rows)

        # Entries previously attached to the larger row stay with the segment
        # explicitly selected by the user. The newly created remainder is empty.
        ga_user = await _resolve_ga_user(db)
        if ga_user is not None:
            await db.execute(
                update(GaTimeSlotTemplate)
                .where(
                    GaTimeSlotTemplate.user_id == ga_user.id,
                    GaTimeSlotTemplate.start_time == original_start,
                    GaTimeSlotTemplate.end_time == original_end,
                )
                .values(start_time=payload.start_time, end_time=payload.end_time)
            )
    else:
        new_row = GaTimeTableRow(
            sort_order=len(visible_rows) + 2,
            nr_label="",
            label=format_ga_time_label(payload.start_time, payload.end_time),
            start_time=payload.start_time,
            end_time=payload.end_time,
            is_special=False,
            comment=payload.comment.strip(),
            comment_background_color=payload.comment_background_color,
            comment_text_color=payload.comment_text_color,
            comment_is_bold=payload.comment_is_bold,
            comment_is_italic=payload.comment_is_italic,
        )
        db.add(new_row)
        visible_rows.append(new_row)
    visible_rows.sort(key=lambda row: (row.start_time, row.end_time))
    for idx, row in enumerate(visible_rows, start=1):
        row.sort_order = idx + 1
        row.nr_label = str(idx)
        row.label = format_ga_time_label(row.start_time, row.end_time)

    await db.commit()
    rows = await get_ga_time_table_rows(db)
    return [_row_out(row) for row in rows]


@router.patch("/rows/comment", response_model=GaTimeTableRowOut)
async def update_ga_time_table_row_comment(
    payload: GaTimeTableRowCommentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GaTimeTableRowOut:
    _ensure_can_edit(current_user)
    rows = (
        await db.execute(
            select(GaTimeTableRow)
            .order_by(GaTimeTableRow.sort_order, GaTimeTableRow.start_time)
            .with_for_update()
        )
    ).scalars().all()
    if not rows:
        rows = [
            GaTimeTableRow(
                sort_order=row.sort_order,
                nr_label=row.nr_label,
                label=row.label,
                start_time=row.start_time,
                end_time=row.end_time,
                is_special=row.is_special,
                comment=row.comment,
                comment_background_color=row.comment_background_color,
                comment_text_color=row.comment_text_color,
                comment_is_bold=row.comment_is_bold,
                comment_is_italic=row.comment_is_italic,
            )
            for row in DEFAULT_GA_TIME_TABLE_ROWS
        ]
        db.add_all(rows)
        await db.flush()

    target = next(
        (
            row for row in rows
            if row.start_time == payload.start_time and row.end_time == payload.end_time
        ),
        None,
    )
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Time row not found")
    target.comment = payload.comment.strip()
    target.comment_background_color = payload.comment_background_color
    target.comment_text_color = payload.comment_text_color
    target.comment_is_bold = payload.comment_is_bold
    target.comment_is_italic = payload.comment_is_italic
    end_comments = [
        raw_comment
        for raw_comment in (target.comments or [])
        if isinstance(raw_comment, dict) and raw_comment.get("column") == "end"
    ]
    start_comments = (
        [
            {
                "id": f"legacy-{target.id}",
                "content": target.comment,
                "column": "start",
                "comment_background_color": target.comment_background_color,
                "comment_text_color": target.comment_text_color,
                "comment_is_bold": target.comment_is_bold,
                "comment_is_italic": target.comment_is_italic,
            }
        ]
        if target.comment
        else []
    )
    target.comments = [*end_comments, *start_comments]
    await db.commit()
    await db.refresh(target)
    return _row_out(target)


@router.put("/rows/comments", response_model=GaTimeTableRowOut)
async def update_ga_time_table_row_comments(
    payload: GaTimeTableRowCommentsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GaTimeTableRowOut:
    _ensure_can_edit(current_user)
    rows = (
        await db.execute(
            select(GaTimeTableRow)
            .order_by(GaTimeTableRow.sort_order, GaTimeTableRow.start_time)
            .with_for_update()
        )
    ).scalars().all()
    if not rows:
        rows = [
            GaTimeTableRow(
                sort_order=row.sort_order,
                nr_label=row.nr_label,
                label=row.label,
                start_time=row.start_time,
                end_time=row.end_time,
                is_special=row.is_special,
                comment=row.comment,
                comment_background_color=row.comment_background_color,
                comment_text_color=row.comment_text_color,
                comment_is_bold=row.comment_is_bold,
                comment_is_italic=row.comment_is_italic,
            )
            for row in DEFAULT_GA_TIME_TABLE_ROWS
        ]
        db.add_all(rows)
        await db.flush()

    target = next(
        (
            row for row in rows
            if row.start_time == payload.start_time and row.end_time == payload.end_time
        ),
        None,
    )
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Time row not found")

    existing_other_column_comments = [
        raw_comment
        for raw_comment in (target.comments or [])
        if isinstance(raw_comment, dict)
        and raw_comment.get("column", "start") != payload.column
    ]
    serialized_comments = [
        {**comment.model_dump(mode="json"), "column": payload.column}
        for comment in payload.comments
    ]
    target.comments = [*existing_other_column_comments, *serialized_comments]
    if payload.column == "start":
        target.comment = "\n".join(comment.content.strip() for comment in payload.comments)
        if payload.comments:
            first = payload.comments[0]
            target.comment_background_color = first.comment_background_color
            target.comment_text_color = first.comment_text_color
            target.comment_is_bold = first.comment_is_bold
            target.comment_is_italic = first.comment_is_italic
        else:
            target.comment_background_color = "#FFFFFF"
            target.comment_text_color = "#0F172A"
            target.comment_is_bold = False
            target.comment_is_italic = False

    await db.commit()
    await db.refresh(target)
    return _row_out(target)


@router.put("/rows/comments/move", response_model=list[GaTimeTableRowOut])
async def move_ga_time_table_row_comment(
    payload: GaTimeTableRowCommentMove,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[GaTimeTableRowOut]:
    _ensure_can_edit(current_user)
    rows = (
        await db.execute(
            select(GaTimeTableRow)
            .order_by(GaTimeTableRow.sort_order, GaTimeTableRow.start_time)
            .with_for_update()
        )
    ).scalars().all()
    if not rows:
        rows = [
            GaTimeTableRow(
                sort_order=row.sort_order,
                nr_label=row.nr_label,
                label=row.label,
                start_time=row.start_time,
                end_time=row.end_time,
                is_special=row.is_special,
                comment=row.comment,
                comment_background_color=row.comment_background_color,
                comment_text_color=row.comment_text_color,
                comment_is_bold=row.comment_is_bold,
                comment_is_italic=row.comment_is_italic,
            )
            for row in DEFAULT_GA_TIME_TABLE_ROWS
        ]
        db.add_all(rows)
        await db.flush()

    source = next(
        (
            row for row in rows
            if row.start_time == payload.source_start_time
            and row.end_time == payload.source_end_time
        ),
        None,
    )
    target = next(
        (
            row for row in rows
            if row.start_time == payload.target_start_time
            and row.end_time == payload.target_end_time
        ),
        None,
    )
    if source is None or target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Time row not found")

    source_out = _row_out(source)
    source_state = {
        "start": list(source_out.comments),
        "end": list(source_out.end_comments),
    }
    if source is target:
        target_state = source_state
    else:
        target_out = _row_out(target)
        target_state = {
            "start": list(target_out.comments),
            "end": list(target_out.end_comments),
        }

    source_comments = source_state[payload.source_column]
    source_index = next(
        (index for index, comment in enumerate(source_comments) if comment.id == payload.comment_id),
        None,
    )
    if source_index is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    moved_comment = source_comments.pop(source_index)

    target_comments = target_state[payload.target_column]
    if source_comments is not target_comments and len(target_comments) >= 50:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The target comment cell is full",
        )
    before_index = next(
        (
            index for index, comment in enumerate(target_comments)
            if comment.id == payload.before_comment_id
        ),
        None,
    )
    target_comments.insert(before_index if before_index is not None else len(target_comments), moved_comment)

    _replace_row_comments(source, source_state["start"], source_state["end"])
    if target is not source:
        _replace_row_comments(target, target_state["start"], target_state["end"])

    await db.commit()
    touched_rows = [source] if source is target else sorted([source, target], key=lambda row: row.sort_order)
    for row in touched_rows:
        await db.refresh(row)
    return [_row_out(row) for row in touched_rows]


@router.put("/rows/comments/move-to-slot", response_model=GaTimeTableCrossCellMoveOut)
async def move_ga_time_table_comment_to_slot(
    payload: GaTimeTableCommentToSlotMove,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GaTimeTableCrossCellMoveOut:
    _ensure_can_edit(current_user)
    if payload.target_start_time >= payload.target_end_time:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="End time must be after start time",
        )
    ga_user = await _resolve_ga_user(db)
    if ga_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GA user not found")

    rows = (
        await db.execute(
            select(GaTimeTableRow)
            .order_by(GaTimeTableRow.sort_order, GaTimeTableRow.start_time)
            .with_for_update()
        )
    ).scalars().all()
    source = next(
        (
            row for row in rows
            if row.start_time == payload.source_start_time
            and row.end_time == payload.source_end_time
        ),
        None,
    )
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Time row not found")

    source_out = _row_out(source)
    source_state = {
        "start": list(source_out.comments),
        "end": list(source_out.end_comments),
    }
    source_comments = source_state[payload.source_column]
    source_index = next(
        (index for index, comment in enumerate(source_comments) if comment.id == payload.comment_id),
        None,
    )
    if source_index is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    moved_comment = source_comments.pop(source_index)

    target_entries = (
        await db.execute(
            select(GaTimeSlotTemplate)
            .where(
                GaTimeSlotTemplate.user_id == ga_user.id,
                GaTimeSlotTemplate.day_of_week == payload.target_day_of_week,
                GaTimeSlotTemplate.start_time == payload.target_start_time,
            )
            .order_by(GaTimeSlotTemplate.sort_order, GaTimeSlotTemplate.created_at)
            .with_for_update()
        )
    ).scalars().all()
    before_index = next(
        (
            index for index, entry in enumerate(target_entries)
            if entry.id == payload.before_entry_id
        ),
        None,
    )
    new_entry = GaTimeSlotTemplate(
        user_id=ga_user.id,
        day_of_week=payload.target_day_of_week,
        start_time=payload.target_start_time,
        end_time=payload.target_end_time,
        sort_order=0,
        content=moved_comment.content,
        background_color=moved_comment.comment_background_color,
        text_color=moved_comment.comment_text_color,
        is_bold=moved_comment.comment_is_bold,
        is_italic=moved_comment.comment_is_italic,
    )
    db.add(new_entry)
    target_entries.insert(before_index if before_index is not None else len(target_entries), new_entry)
    for sort_order, entry in enumerate(target_entries):
        entry.sort_order = sort_order
        entry.end_time = payload.target_end_time

    _replace_row_comments(source, source_state["start"], source_state["end"])
    await db.commit()
    await db.refresh(source)
    for entry in target_entries:
        await db.refresh(entry)
    return GaTimeTableCrossCellMoveOut(
        rows=[_row_out(source)],
        entries=[_entry_out(entry) for entry in target_entries],
    )


@router.put("/rows/comments/move-from-slot", response_model=GaTimeTableCrossCellMoveOut)
async def move_ga_time_table_entry_to_comment(
    payload: GaTimeTableEntryToCommentMove,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GaTimeTableCrossCellMoveOut:
    _ensure_can_edit(current_user)
    ga_user = await _resolve_ga_user(db)
    if ga_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GA user not found")

    entry = (
        await db.execute(
            select(GaTimeSlotTemplate)
            .where(
                GaTimeSlotTemplate.id == payload.entry_id,
                GaTimeSlotTemplate.user_id == ga_user.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")

    rows = (
        await db.execute(
            select(GaTimeTableRow)
            .order_by(GaTimeTableRow.sort_order, GaTimeTableRow.start_time)
            .with_for_update()
        )
    ).scalars().all()
    target = next(
        (
            row for row in rows
            if row.start_time == payload.target_start_time
            and row.end_time == payload.target_end_time
        ),
        None,
    )
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Time row not found")

    target_out = _row_out(target)
    target_state = {
        "start": list(target_out.comments),
        "end": list(target_out.end_comments),
    }
    target_comments = target_state[payload.target_column]
    if len(target_comments) >= 50:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The target comment cell is full",
        )
    before_index = next(
        (
            index for index, comment in enumerate(target_comments)
            if comment.id == payload.before_comment_id
        ),
        None,
    )
    target_comments.insert(
        before_index if before_index is not None else len(target_comments),
        GaTimeTableRowComment(
            id=f"slot-{entry.id}",
            content=entry.content,
            comment_background_color=entry.background_color,
            comment_text_color=entry.text_color,
            comment_is_bold=entry.is_bold,
            comment_is_italic=entry.is_italic,
            column=payload.target_column,
        ),
    )

    source_entries = (
        await db.execute(
            select(GaTimeSlotTemplate)
            .where(
                GaTimeSlotTemplate.user_id == ga_user.id,
                GaTimeSlotTemplate.day_of_week == entry.day_of_week,
                GaTimeSlotTemplate.start_time == entry.start_time,
                GaTimeSlotTemplate.id != entry.id,
            )
            .order_by(GaTimeSlotTemplate.sort_order, GaTimeSlotTemplate.created_at)
            .with_for_update()
        )
    ).scalars().all()
    for sort_order, source_entry in enumerate(source_entries):
        source_entry.sort_order = sort_order

    _replace_row_comments(target, target_state["start"], target_state["end"])
    await db.delete(entry)
    await db.commit()
    await db.refresh(target)
    for source_entry in source_entries:
        await db.refresh(source_entry)
    return GaTimeTableCrossCellMoveOut(
        rows=[_row_out(target)],
        entries=[_entry_out(source_entry) for source_entry in source_entries],
    )


@router.get("/icloud-sync", response_model=GaIcloudSyncConnectionOut | None)
async def get_icloud_sync_connection(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GaIcloudSyncConnectionOut | None:
    _ensure_can_edit(current_user)
    ga_user = await _resolve_ga_user(db)
    if ga_user is None:
        return None
    connection = (
        await db.execute(
            select(GaIcloudSyncConnection)
            .where(
                GaIcloudSyncConnection.ga_user_id == ga_user.id,
                GaIcloudSyncConnection.revoked_at.is_(None),
            )
            .order_by(GaIcloudSyncConnection.created_at.desc())
        )
    ).scalars().first()
    return _connection_out(connection) if connection else None


@router.post("/icloud-sync/pair", response_model=GaIcloudSyncPairingOut)
async def pair_icloud_sync_device(
    payload: GaIcloudSyncConnectionCreate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GaIcloudSyncPairingOut:
    _ensure_can_edit(current_user)
    ga_user = await _resolve_ga_user(db)
    if ga_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GA user not found")

    now = datetime.now(timezone.utc)
    active_connections = (
        await db.execute(
            select(GaIcloudSyncConnection).where(
                GaIcloudSyncConnection.ga_user_id == ga_user.id,
                GaIcloudSyncConnection.revoked_at.is_(None),
            )
        )
    ).scalars().all()
    for active in active_connections:
        active.revoked_at = now
    if active_connections:
        await db.execute(
            delete(GaTimeSlotEntry).where(
                GaTimeSlotEntry.sync_connection_id.in_([active.id for active in active_connections])
            )
        )

    connection_id = uuid.uuid4()
    pairing_token, token_hash = generate_connection_token(connection_id)
    connection = GaIcloudSyncConnection(
        id=connection_id,
        ga_user_id=ga_user.id,
        created_by_id=current_user.id,
        device_name=payload.device_name.strip(),
        calendar_name=payload.calendar_name.strip(),
        reminder_list_name=payload.reminder_list_name.strip(),
        token_hash=token_hash,
    )
    db.add(connection)
    await db.commit()
    await db.refresh(connection)
    response.headers["Cache-Control"] = "no-store"
    base_url = str(request.base_url).rstrip("/")
    return GaIcloudSyncPairingOut(
        **_connection_out(connection).model_dump(),
        import_url=f"{base_url}/api/ga-time-slots/icloud-sync/import",
        pairing_token=pairing_token,
    )


@router.delete("/icloud-sync/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_icloud_sync_connection(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    _ensure_can_edit(current_user)
    ga_user = await _resolve_ga_user(db)
    if ga_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GA user not found")
    connection = (
        await db.execute(
            select(GaIcloudSyncConnection).where(
                GaIcloudSyncConnection.id == connection_id,
                GaIcloudSyncConnection.ga_user_id == ga_user.id,
                GaIcloudSyncConnection.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync connection not found")
    connection.revoked_at = datetime.now(timezone.utc)
    await db.execute(delete(GaTimeSlotEntry).where(GaTimeSlotEntry.sync_connection_id == connection.id))
    await db.commit()


async def _ping_icloud_sync_connection(
    request: Request,
    x_primeflow_sync_token: str | None,
    db: AsyncSession,
) -> dict[str, bool | int | str]:
    await _connection_from_sync_token(db, x_primeflow_sync_token)
    body = await request.body()
    return {
        "ok": True,
        "method": request.method,
        "body_bytes": len(body),
    }


@router.get("/icloud-sync/ping")
async def ping_icloud_sync_connection_get(
    request: Request,
    x_primeflow_sync_token: str | None = Header(default=None, alias="X-PrimeFlow-Sync-Token"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool | int | str]:
    return await _ping_icloud_sync_connection(request, x_primeflow_sync_token, db)


@router.post("/icloud-sync/ping")
async def ping_icloud_sync_connection_post(
    request: Request,
    x_primeflow_sync_token: str | None = Header(default=None, alias="X-PrimeFlow-Sync-Token"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool | int | str]:
    return await _ping_icloud_sync_connection(request, x_primeflow_sync_token, db)


@router.post("/icloud-sync/import", response_model=GaIcloudSyncImportOut)
async def import_icloud_timetable_data(
    payload: GaIcloudSyncImport,
    x_primeflow_sync_token: str | None = Header(default=None, alias="X-PrimeFlow-Sync-Token"),
    db: AsyncSession = Depends(get_db),
) -> GaIcloudSyncImportOut:
    connection = await _connection_from_sync_token(db, x_primeflow_sync_token, lock=True)
    if payload.sync_window_end < payload.sync_window_start:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid sync window")
    if (payload.sync_window_end - payload.sync_window_start).days > 92:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Sync window is limited to 93 days")
    if payload.calendar_name.casefold() != connection.calendar_name.casefold():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Calendar name does not match pairing")
    if payload.reminder_list_name.casefold() != connection.reminder_list_name.casefold():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Reminder list does not match pairing")
    try:
        zone = resolve_timezone(payload.timezone)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    timetable_rows = await get_ga_time_table_rows(db)
    time_rows = [TimeRow(row.start_time, row.end_time) for row in timetable_rows]
    prepared = []
    skipped = 0
    for event in payload.events:
        source_name = (event.calendar_name or payload.calendar_name).strip()
        if source_name.casefold() != connection.calendar_name.casefold():
            skipped += 1
            continue
        item = prepare_calendar_item(
            external_id=event.id,
            title=event.title,
            starts_at=event.starts_at,
            ends_at=event.ends_at,
            is_all_day=event.is_all_day,
            calendar_name=source_name,
            location=event.location,
            zone=zone,
            rows=time_rows,
        )
        if not payload.sync_window_start <= item.day_date <= payload.sync_window_end or item.day_date.weekday() > 4:
            skipped += 1
            continue
        prepared.append(item)
    for reminder in payload.reminders:
        source_name = (reminder.reminder_list_name or payload.reminder_list_name).strip()
        if reminder.is_completed or source_name.casefold() != connection.reminder_list_name.casefold():
            skipped += 1
            continue
        item = prepare_reminder_item(
            external_id=reminder.id,
            title=reminder.title,
            due_at=reminder.due_at,
            due_date=reminder.due_date,
            reminder_list_name=source_name,
            notes=reminder.notes,
            fallback_date=payload.sync_window_start,
            zone=zone,
            rows=time_rows,
        )
        if not payload.sync_window_start <= item.day_date <= payload.sync_window_end or item.day_date.weekday() > 4:
            skipped += 1
            continue
        prepared.append(item)

    unique_items = {(item.source_type, item.source_external_id): item for item in prepared}
    skipped += len(prepared) - len(unique_items)
    await db.execute(
        delete(GaTimeSlotEntry).where(
            GaTimeSlotEntry.sync_connection_id == connection.id,
            GaTimeSlotEntry.day_date >= payload.sync_window_start,
            GaTimeSlotEntry.day_date <= payload.sync_window_end,
        )
    )
    entries = [
        GaTimeSlotEntry(
            user_id=connection.ga_user_id,
            day_date=item.day_date,
            start_time=item.start_time,
            end_time=item.end_time,
            content=item.content,
            sync_connection_id=connection.id,
            source_type=item.source_type,
            source_external_id=item.source_external_id,
            source_name=item.source_name,
        )
        for item in unique_items.values()
    ]
    db.add_all(entries)
    synced_at = datetime.now(timezone.utc)
    connection.last_synced_at = synced_at
    connection.last_imported_count = len(entries)
    await db.commit()
    calendar_count = sum(item.source_type == "calendar" for item in unique_items.values())
    reminder_count = sum(item.source_type == "reminder" for item in unique_items.values())
    return GaIcloudSyncImportOut(
        imported=len(entries),
        calendar_imported=calendar_count,
        reminders_imported=reminder_count,
        skipped=skipped,
        synced_at=synced_at,
    )


@router.get("/calendar-feed")
async def get_ga_calendar_feed_path(
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    _ensure_can_edit(current_user)
    ga_user = await _resolve_ga_user(db)
    if ga_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GA user not found")
    response.headers["Cache-Control"] = "no-store"
    # Relative to the API base; the frontend knows the public API host.
    return {"feed_path": f"/ga-time-slots/calendar/{feed_token(ga_user.id)}.ics"}


@router.get("/calendar/{token}.ics")
async def get_ga_calendar_feed(token: str, db: AsyncSession = Depends(get_db)) -> Response:
    # Public: Apple Calendar cannot send a login, so the secret token in the URL is the access check.
    ga_user = await _resolve_ga_user(db)
    if ga_user is None or not is_valid_feed_token(token, ga_user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    entries = (
        await db.execute(
            select(GaTimeSlotTemplate)
            .where(GaTimeSlotTemplate.user_id == ga_user.id)
            .order_by(GaTimeSlotTemplate.day_of_week, GaTimeSlotTemplate.start_time, GaTimeSlotTemplate.sort_order)
        )
    ).scalars().all()
    # The time table also shows the manual TAK INT meetings, so the phone gets them too.
    meetings = (
        await db.execute(
            select(Meeting)
            .where(
                Meeting.meeting_type == "internal",
                Meeting.paired_external_meeting_id.is_(None),
                Meeting.pre_external_meeting_id.is_(None),
                Meeting.starts_at.is_not(None),
            )
            .order_by(Meeting.starts_at)
        )
    ).scalars().all()
    return Response(
        content=build_ga_calendar(list(entries), list(meetings)),
        media_type="text/calendar; charset=utf-8",
        headers={"Cache-Control": "no-cache", "Content-Disposition": 'inline; filename="primeflow-ga.ics"'},
    )


@router.get("", response_model=list[GaTimeSlotEntryOut])
async def list_ga_time_slots(
    week_start: date,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[GaTimeSlotEntryOut]:
    ga_user = await _resolve_ga_user(db)
    if ga_user is None:
        return []
    template_rows = (
        await db.execute(
            select(GaTimeSlotTemplate)
            .where(GaTimeSlotTemplate.user_id == ga_user.id)
            .order_by(
                GaTimeSlotTemplate.day_of_week,
                GaTimeSlotTemplate.start_time,
                GaTimeSlotTemplate.sort_order,
                GaTimeSlotTemplate.created_at,
            )
        )
    ).scalars().all()
    week_end = week_start + timedelta(days=6)
    dated_rows = (
        await db.execute(
            select(GaTimeSlotEntry)
            .where(
                GaTimeSlotEntry.user_id == ga_user.id,
                GaTimeSlotEntry.sync_connection_id.is_not(None),
                GaTimeSlotEntry.day_date >= week_start,
                GaTimeSlotEntry.day_date <= week_end,
            )
            .order_by(GaTimeSlotEntry.day_date, GaTimeSlotEntry.start_time, GaTimeSlotEntry.created_at)
        )
    ).scalars().all()
    return [*[_entry_out(row) for row in template_rows], *[_dated_entry_out(row) for row in dated_rows]]


@router.post("", response_model=GaTimeSlotEntryOut)
async def create_ga_time_slot(
    payload: GaTimeSlotEntryIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GaTimeSlotEntryOut:
    _ensure_can_edit(current_user)
    ga_user = await _resolve_ga_user(db)
    if ga_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GA user not found")
    content = (payload.content or "").strip()
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Content is required")
    if payload.day_of_week < 0 or payload.day_of_week > 6:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid day_of_week")
    entry = GaTimeSlotTemplate(
        user_id=ga_user.id,
        day_of_week=payload.day_of_week,
        start_time=payload.start_time,
        end_time=payload.end_time,
        sort_order=payload.sort_order,
        content=content,
        background_color=payload.background_color,
        text_color=payload.text_color,
        is_bold=payload.is_bold,
        is_italic=payload.is_italic,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return _entry_out(entry)


@router.put("/reorder", response_model=list[GaTimeSlotEntryOut])
async def reorder_ga_time_slots(
    payload: GaTimeSlotEntriesReorder,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[GaTimeSlotEntryOut]:
    _ensure_can_edit(current_user)
    ga_user = await _resolve_ga_user(db)
    if ga_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GA user not found")

    entry_ids = [item.id for item in payload.entries]
    if len(entry_ids) != len(set(entry_ids)):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Duplicate entry ids")

    entries = (
        await db.execute(
            select(GaTimeSlotTemplate).where(
                GaTimeSlotTemplate.id.in_(entry_ids),
                GaTimeSlotTemplate.user_id == ga_user.id,
            )
        )
    ).scalars().all()
    entries_by_id = {entry.id: entry for entry in entries}
    if len(entries_by_id) != len(entry_ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="One or more entries were not found")

    for item in payload.entries:
        entry = entries_by_id[item.id]
        entry.day_of_week = item.day_of_week
        entry.start_time = item.start_time
        entry.end_time = item.end_time
        entry.sort_order = item.sort_order

    await db.commit()
    for entry in entries:
        await db.refresh(entry)
    return [_entry_out(entries_by_id[item.id]) for item in payload.entries]


@router.patch("/{entry_id}", response_model=GaTimeSlotEntryOut)
async def update_ga_time_slot(
    entry_id: uuid.UUID,
    payload: GaTimeSlotEntryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GaTimeSlotEntryOut:
    _ensure_can_edit(current_user)
    entry = (
        await db.execute(select(GaTimeSlotTemplate).where(GaTimeSlotTemplate.id == entry_id))
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")
    ga_user = await _resolve_ga_user(db)
    if ga_user is None or entry.user_id != ga_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    content = (payload.content or "").strip()
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Content is required")
    entry.content = content
    if payload.background_color is not None:
        entry.background_color = payload.background_color
    if payload.text_color is not None:
        entry.text_color = payload.text_color
    if payload.is_bold is not None:
        entry.is_bold = payload.is_bold
    if payload.is_italic is not None:
        entry.is_italic = payload.is_italic
    await db.commit()
    await db.refresh(entry)
    return _entry_out(entry)


@router.delete("/{entry_id}")
async def delete_ga_time_slot(
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    _ensure_can_edit(current_user)
    entry = (
        await db.execute(select(GaTimeSlotTemplate).where(GaTimeSlotTemplate.id == entry_id))
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")
    ga_user = await _resolve_ga_user(db)
    if ga_user is None or entry.user_id != ga_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    await db.delete(entry)
    await db.commit()
    return {"status": "ok"}
