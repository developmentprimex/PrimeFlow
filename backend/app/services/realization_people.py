from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.common_entry import CommonEntry
from app.models.enums import CommonCategory
from app.models.user import User
from app.services.common_leave import (
    is_common_view_full_day_absence,
    parse_common_view_annual_leave,
    parse_common_view_entry_day,
)


@dataclass(frozen=True)
class CommonLeaveCoverage:
    days: frozenset[date]
    entry_ids: tuple[uuid.UUID, ...]
    absence_days: frozenset[date] = frozenset()
    absence_entry_ids: tuple[uuid.UUID, ...] = ()
    full_day_absence_days: frozenset[date] = frozenset()
    delay_days: frozenset[date] = frozenset()
    delay_entry_ids: tuple[uuid.UUID, ...] = ()


def is_realization_excluded_user(user: User) -> bool:
    """People explicitly excluded from every Realization report and list."""
    full_name = " ".join((getattr(user, "full_name", "") or "").split()).casefold()
    username = (getattr(user, "username", "") or "").strip().casefold()
    email = (getattr(user, "email", "") or "").strip().casefold()
    return (
        full_name in {"gent arifaj", "genti arifaj"}
        or username == "gent.arifaj"
        or email == "g.arifaj@primexeu.com"
    )


def availability_status_on_day(
    coverage: CommonLeaveCoverage | None, day: date
) -> str | None:
    if coverage is None:
        return None
    if day in coverage.days:
        return "PV"
    if day in coverage.full_day_absence_days:
        return "MUNGESE"
    return None


def combine_availability_statuses(statuses: Iterable[str | None]) -> str | None:
    """One label for a stretch of days that were all spent away."""
    unique = {status for status in statuses if status}
    if not unique:
        return None
    if unique == {"PV"}:
        return "PV"
    if unique == {"MUNGESE"}:
        return "MUNGESE"
    if unique <= {"PV", "MUNGESE", "PV_MUNGESE"}:
        return "PV_MUNGESE"
    return None


def full_period_availability_statuses(
    coverage: dict[uuid.UUID, CommonLeaveCoverage],
    *,
    working_days: set[date],
) -> dict[uuid.UUID, str]:
    if not working_days:
        return {}
    statuses: dict[uuid.UUID, str] = {}
    for user_id, item in coverage.items():
        if working_days.issubset(item.days):
            statuses[user_id] = "PV"
        elif working_days.issubset(item.full_day_absence_days):
            statuses[user_id] = "MUNGESE"
        elif working_days.issubset(item.days | item.full_day_absence_days):
            statuses[user_id] = "PV_MUNGESE"
    return statuses


def availability_status_from_days(
    by_day: dict[date, str],
    *,
    working_days: set[date],
) -> str | None:
    """The week is PV only when every working day of it was spent away."""
    if not working_days or not working_days.issubset(by_day):
        return None
    return combine_availability_statuses(by_day[day] for day in working_days)


def build_common_leave_coverage(
    entries: Iterable[CommonEntry],
    *,
    user_ids: set[uuid.UUID],
    start_date: date,
    end_date: date,
) -> dict[uuid.UUID, CommonLeaveCoverage]:
    """Mirror Common View PV/FEST ranges for full-day realization exclusions."""
    days_by_user: dict[uuid.UUID, set[date]] = defaultdict(set)
    entries_by_user: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for entry in entries:
        leave_start, leave_end, full_day, _, _, _, is_all_users = (
            parse_common_view_annual_leave(entry)
        )
        if not full_day or leave_end < start_date or leave_start > end_date:
            continue
        impacted_users = (
            user_ids
            if is_all_users
            else {entry.assigned_to_user_id or entry.created_by_user_id} & user_ids
        )
        current = max(start_date, leave_start)
        last = min(end_date, leave_end)
        covered_days: set[date] = set()
        while current <= last:
            covered_days.add(current)
            current += timedelta(days=1)
        for user_id in impacted_users:
            days_by_user[user_id].update(covered_days)
            entries_by_user[user_id].add(entry.id)
    return {
        user_id: CommonLeaveCoverage(
            days=frozenset(days),
            entry_ids=tuple(sorted(entries_by_user[user_id], key=str)),
        )
        for user_id, days in days_by_user.items()
    }


async def load_active_users_and_common_leave(
    db: AsyncSession,
    *,
    department_id: uuid.UUID,
    start_date: date,
    end_date: date,
) -> tuple[list[User], dict[uuid.UUID, CommonLeaveCoverage]]:
    active_users = list((
        await db.execute(
            select(User).where(User.work_staff_filter())
            .where(
                User.department_id == department_id,
                User.is_active.is_(True),
            )
            .order_by(User.full_name.asc(), User.id.asc())
        )
    ).scalars().all())
    active_users = [user for user in active_users if not is_realization_excluded_user(user)]
    user_ids = {user.id for user in active_users}
    if not user_ids:
        return active_users, {}

    # Common View intentionally shows annual-leave entries regardless of approval
    # state, so realization uses the same source and interpretation.
    entries = list((
        await db.execute(
            select(CommonEntry).where(
                CommonEntry.category.in_({
                    CommonCategory.annual_leave,
                    CommonCategory.absences,
                    CommonCategory.delays,
                })
            )
        )
    ).scalars().all())
    leave_entries = [
        entry for entry in entries
        if getattr(entry, "category", CommonCategory.annual_leave) == CommonCategory.annual_leave
    ]
    coverage = build_common_leave_coverage(
        leave_entries,
        user_ids=user_ids,
        start_date=start_date,
        end_date=end_date,
    )
    absence_days_by_user: dict[uuid.UUID, set[date]] = defaultdict(set)
    full_day_absence_days_by_user: dict[uuid.UUID, set[date]] = defaultdict(set)
    absence_entries_by_user: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    delay_days_by_user: dict[uuid.UUID, set[date]] = defaultdict(set)
    delay_entries_by_user: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for entry in entries:
        category = getattr(entry, "category", None)
        if category not in {CommonCategory.absences, CommonCategory.delays}:
            continue
        event_day = parse_common_view_entry_day(entry)
        if event_day < start_date or event_day > end_date:
            continue
        impacted_user = entry.assigned_to_user_id or entry.created_by_user_id
        if impacted_user not in user_ids:
            continue
        if category == CommonCategory.absences:
            absence_days_by_user[impacted_user].add(event_day)
            absence_entries_by_user[impacted_user].add(entry.id)
            if is_common_view_full_day_absence(entry):
                full_day_absence_days_by_user[impacted_user].add(event_day)
        else:
            delay_days_by_user[impacted_user].add(event_day)
            delay_entries_by_user[impacted_user].add(entry.id)
    for user_id in set(absence_days_by_user) | set(delay_days_by_user):
        current = coverage.get(user_id, CommonLeaveCoverage(frozenset(), ()))
        coverage[user_id] = CommonLeaveCoverage(
            days=current.days,
            entry_ids=current.entry_ids,
            absence_days=frozenset(absence_days_by_user.get(user_id, set())),
            absence_entry_ids=tuple(sorted(absence_entries_by_user.get(user_id, set()), key=str)),
            full_day_absence_days=frozenset(full_day_absence_days_by_user.get(user_id, set())),
            delay_days=frozenset(delay_days_by_user.get(user_id, set())),
            delay_entry_ids=tuple(sorted(delay_entries_by_user.get(user_id, set()), key=str)),
        )
    return active_users, coverage


def full_period_leave_user_ids(
    coverage: dict[uuid.UUID, CommonLeaveCoverage],
    *,
    working_days: set[date],
) -> set[uuid.UUID]:
    if not working_days:
        return set()
    return {
        user_id
        for user_id, leave in coverage.items()
        if working_days.issubset(leave.days)
    }
