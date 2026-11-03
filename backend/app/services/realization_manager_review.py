from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    RealizationObservationCategory,
    RealizationObservationVisibility,
    RealizationScopeType,
)
from app.models.realization import RealizationObservation
from app.models.user import User

M3_MANAGER_REVIEW_SOURCE = "M3_MANAGER_REVIEW"
M3_MANAGER_REVIEW_DIMENSIONS = {"PLANNING", "REALIZATION"}
M3_MANAGER_REVIEW_MARKERS = {"POSITIVE", "NEGATIVE"}
M3_MANAGER_REVIEW_RATINGS = {"GOOD": "Mirë", "VERY_GOOD": "Shumë mirë", "ACTION_REQUIRED": "Kërkon veprim", "BAD": "Keq"}
M3_MANAGER_REVIEW_UNRATED_LABEL = "Pa vlerësim"


def is_m3_manager_review(observation: RealizationObservation | dict) -> bool:
    source_type = (
        observation.get("source_type")
        if isinstance(observation, dict)
        else observation.source_type
    )
    return source_type == M3_MANAGER_REVIEW_SOURCE


async def manager_review_rows(
    db: AsyncSession,
    *,
    period_id: uuid.UUID,
    user_id: uuid.UUID,
    for_update: bool = False,
) -> list[RealizationObservation]:
    statement = (
        select(RealizationObservation)
        .where(
            RealizationObservation.period_id == period_id,
            RealizationObservation.user_id == user_id,
            RealizationObservation.source_type == M3_MANAGER_REVIEW_SOURCE,
        )
        .order_by(RealizationObservation.created_at.asc(), RealizationObservation.id.asc())
    )
    if for_update:
        statement = statement.with_for_update()
    return list((await db.execute(statement)).scalars().all())


def review_dimension(row: RealizationObservation) -> str | None:
    value = (row.evidence_json or {}).get("review_dimension")
    return value if value in M3_MANAGER_REVIEW_DIMENSIONS else None


async def build_manager_review_response(
    db: AsyncSession,
    *,
    period_id: uuid.UUID,
    user_id: uuid.UUID,
    can_edit: bool,
    can_confirm_tasks: bool = False,
) -> dict:
    rows = await manager_review_rows(db, period_id=period_id, user_id=user_id)
    creator_ids = {row.created_by for row in rows if row.created_by}
    names = {
        row.id: row.full_name
        for row in (
            (
                await db.execute(select(User).where(User.id.in_(creator_ids)))
            ).scalars().all()
            if creator_ids
            else []
        )
    }

    def present(row: RealizationObservation) -> dict | None:
        dimension = review_dimension(row)
        if dimension is None or row.marker not in M3_MANAGER_REVIEW_MARKERS:
            return None
        evidence = row.evidence_json or {}
        if "review_rating" in evidence:
            # Written by the rating-aware flow: an absent rating means the manager
            # saved only a comment, so it must stay unrated.
            rating = evidence["review_rating"]
            if rating not in M3_MANAGER_REVIEW_RATINGS:
                rating = None
        else:
            rating = "GOOD" if row.marker == "POSITIVE" else "ACTION_REQUIRED"
        return {
            "level": evidence.get("review_level"),
            "rating": rating,
            "id": row.id,
            "dimension": dimension,
            "marker": row.marker,
            "label": M3_MANAGER_REVIEW_RATINGS[rating] if rating else M3_MANAGER_REVIEW_UNRATED_LABEL,
            "comment": row.comment or "",
            "created_by_user_id": row.created_by,
            "created_by_name": names.get(row.created_by, "Përdorues i panjohur"),
            "created_at": row.created_at,
            "active": row.voided_at is None,
            "voided_at": row.voided_at,
        }

    history = [item for row in rows if (item := present(row)) is not None]
    active = {
        item["dimension"]: item
        for item in history
        if item["active"]
    }
    return {
        "period_id": period_id,
        "user_id": user_id,
        "can_edit": can_edit,
        "can_confirm_tasks": can_confirm_tasks,
        "planning": active.get("PLANNING"),
        "realization": active.get("REALIZATION"),
        "history": list(reversed(history)),
    }


async def upsert_manager_review(
    db: AsyncSession,
    *,
    period_id: uuid.UUID,
    user_id: uuid.UUID,
    department_id: uuid.UUID,
    dimension: str,
    marker: str,
    comment: str | None,
    actor_id: uuid.UUID,
    rating: str | None = None,
    level: str | None = None,
    update_level: bool = False,
) -> RealizationObservation:
    if level is not None and level not in {"A+", "A", "B", "C", "M", "D", "E"}:
        raise ValueError("Invalid manager review level")
    if rating is not None:
        if rating not in M3_MANAGER_REVIEW_RATINGS:
            raise ValueError("Invalid manager review rating")
        marker = "POSITIVE" if rating in {"GOOD", "VERY_GOOD"} else "NEGATIVE"
    now = datetime.now(timezone.utc)
    rows = await manager_review_rows(
        db, period_id=period_id, user_id=user_id, for_update=True
    )
    previous: RealizationObservation | None = None
    for row in rows:
        if row.voided_at is None and review_dimension(row) == dimension:
            row.voided_at = now
            row.voided_by = actor_id
            row.void_reason = "SUPERSEDED_BY_M3_MANAGER_REVIEW"
            previous = row

    review = RealizationObservation(
        period_id=period_id,
        scope_type=RealizationScopeType.PERSON.value,
        user_id=user_id,
        department_id=department_id,
        marker=marker,
        category=RealizationObservationCategory.QUALITY.value,
        comment=(comment or "").strip(),
        evidence_json={
            "review_level": level if update_level else (previous.evidence_json or {}).get("review_level") if previous else None,
            "review_dimension": dimension,
            "review_rating": rating,
            "review_source": M3_MANAGER_REVIEW_SOURCE,
            **(
                {"supersedes_observation_id": str(previous.id)}
                if previous is not None
                else {}
            ),
        },
        source_type=M3_MANAGER_REVIEW_SOURCE,
        source_id=previous.id if previous is not None else None,
        is_system_generated=False,
        visibility=RealizationObservationVisibility.PERSON_AND_MANAGER.value,
        created_by=actor_id,
    )
    db.add(review)
    await db.flush()
    return review


async def clear_manager_review(
    db: AsyncSession,
    *,
    period_id: uuid.UUID,
    user_id: uuid.UUID,
    dimension: str,
    actor_id: uuid.UUID,
) -> list[RealizationObservation]:
    rows = await manager_review_rows(
        db, period_id=period_id, user_id=user_id, for_update=True
    )
    now = datetime.now(timezone.utc)
    cleared = []
    for row in rows:
        if row.voided_at is None and review_dimension(row) == dimension:
            row.voided_at = now
            row.voided_by = actor_id
            row.void_reason = "M3_MANAGER_REVIEW_CLEARED"
            cleared.append(row)
    return cleared
