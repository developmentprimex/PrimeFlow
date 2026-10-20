from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.daily_planner_snapshot import DailyPlannerSnapshot
from app.models.department import Department
from app.models.project import Project
from app.models.task import Task
from app.services.after_break_report import _blue_note_rows
from app.services.daily_report_logic import daily_report_tyo_label, planned_range_for_daily_report
from app.services.meetings_report import (
    _all_participant_user_ids,
    _assignee_names,
    _clean_task_title,
    _daily_baseline_task_ids,
    _daily_rlz_values_by_task,
    _effective_task_assignee_ids,
    _is_open,
    _is_system_task,
    _is_without_progress_for_m3_day,
    _m3_am_pm_label,
    _m3_department_label,
    _m3_task_type_label,
    _normalize_report_status,
    _postponed_tasks_for_m3_day,
    _task_day,
    _task_owners,
    apply_weekly_planner_task_order,
    common_view_task_sort_key,
)


@dataclass(slots=True)
class ClosingTableRow:
    values: list[str]
    status: str = ""
    is_deadline: bool = False
    is_eight_am: bool = False


@dataclass(slots=True)
class ClosingTable:
    label: str
    columns: list[str]
    rows: list[ClosingTableRow] = field(default_factory=list)
    tone: str = ""


@dataclass(slots=True)
class ClosingSection:
    title: str
    tables: list[ClosingTable]


def _stack_start_due(value: str) -> str:
    return re.sub(r"\s+/\s+(?=DUE:)", "\n", str(value), count=1)


def _task_row(
    task: Task,
    values: list[str],
    *,
    status: str | None = None,
) -> ClosingTableRow:
    title = _clean_task_title(task.title)
    return ClosingTableRow(
        values=[*values, title],
        status=status or _normalize_report_status(task.status),
        is_deadline=bool(task.is_deadline_important),
        is_eight_am="08:00" in title or _m3_task_type_label(task) == "08:00",
    )


def _system_task_tyo_label(task: Task, report_day: date) -> str:
    """Use the Daily Report due-date/business-day rules for unfinished system tasks."""
    _, due_day = planned_range_for_daily_report(task, None)
    return daily_report_tyo_label(
        report_day=report_day,
        start_day=None,
        due_day=due_day,
        mode="dueOnly",
    )


def _include_unfinished_system_task(
    task: Task,
    report_day: date,
    baseline_ids: set[Any],
) -> bool:
    if not _is_system_task(task) or not _is_open(task):
        return False
    if task.id in baseline_ids:
        return True

    _, due_day = planned_range_for_daily_report(task, None)
    if due_day is not None and due_day <= report_day:
        return True

    # Preserve the existing fallback for system tasks without a due date that
    # are scheduled specifically for the report day.
    return _task_day(task) == report_day


async def build_tomorrow_closing_sections(
    db: AsyncSession,
    report_day: date,
) -> list[ClosingSection]:
    """Build the delivery-day closing tables shown before Tomorrow's task grid.

    The selectors intentionally reuse M2/M3 helpers so the same task membership,
    Weekly Planner ordering, postponement audit rules, and undiscussed-note rule
    are used in every report surface.
    """
    tasks = (
        await db.execute(select(Task).where(Task.is_active.is_(True)))
    ).scalars().all()
    project_ids = {
        task.project_id
        for task in tasks
        if getattr(task, "project_id", None) is not None
    }
    project_titles_by_id = (
        {
            project_id: title
            for project_id, title in (
                await db.execute(
                    select(Project.id, Project.title).where(Project.id.in_(project_ids))
                )
            ).all()
        }
        if project_ids
        else {}
    )
    names = await _assignee_names(db, tasks)
    assignee_ids_by_task = await _effective_task_assignee_ids(db, tasks)
    all_participant_ids = await _all_participant_user_ids(db)
    department_codes = {
        department_id: code
        for department_id, code in (
            await db.execute(select(Department.id, Department.code))
        ).all()
    }
    await apply_weekly_planner_task_order(
        db, tasks, assignee_ids_by_task, department_codes
    )

    def ordered(values: list[Task]) -> list[Task]:
        return sorted(
            values,
            key=lambda task: (
                1
                if task.completed_at
                or _normalize_report_status(task.status) == "DONE"
                else 0,
                *common_view_task_sort_key(
                    task,
                    names,
                    assignee_ids_by_task,
                    all_participant_ids=all_participant_ids,
                ),
            ),
        )

    def common_values(task: Task) -> list[str]:
        return [
            _task_owners(
                task,
                names,
                assignee_ids_by_task,
                all_participant_ids=all_participant_ids,
            ),
            _m3_department_label(task, department_codes),
            _m3_am_pm_label(task),
        ]

    def project_title(task: Task) -> str:
        return str(project_titles_by_id.get(getattr(task, "project_id", None), "-") or "-")

    def common_values_with_project(task: Task) -> list[str]:
        owner, department, am_pm = common_values(task)
        return [owner, department, project_title(task), am_pm]

    no_progress = ordered(
        [task for task in tasks if _is_without_progress_for_m3_day(task, report_day)]
    )
    daily_rlz = await _daily_rlz_values_by_task(
        db, no_progress, report_day, names, assignee_ids_by_task
    )
    no_progress_rows: list[ClosingTableRow] = []
    for index, task in enumerate(no_progress, 1):
        reason, comment = daily_rlz.get(task.id, ("-", "-"))
        row = _task_row(
            task,
            [str(index), *common_values_with_project(task)],
            status="TODO",
        )
        row.values.extend([reason or "-", comment or "-"])
        no_progress_rows.append(row)

    snapshots = (
        await db.execute(
            select(DailyPlannerSnapshot).where(
                DailyPlannerSnapshot.day_date == report_day
            )
        )
    ).scalars().all()
    baseline_ids = _daily_baseline_task_ids(list(snapshots))
    system_unfinished = ordered(
        [
            task
            for task in tasks
            if _include_unfinished_system_task(task, report_day, baseline_ids)
        ]
    )
    system_daily_rlz = await _daily_rlz_values_by_task(
        db, system_unfinished, report_day, names, assignee_ids_by_task
    )
    system_rows: list[ClosingTableRow] = []
    for index, task in enumerate(system_unfinished, 1):
        row = _task_row(
            task,
            [str(index), *common_values(task)],
        )
        row.values.insert(-1, _system_task_tyo_label(task, report_day))
        reason, comment = system_daily_rlz.get(task.id, ("-", "-"))
        row.values.extend([reason or "-", comment or "-"])
        system_rows.append(row)

    postponed, postponed_ranges, postponed_both, postponed_both_ranges = (
        await _postponed_tasks_for_m3_day(db, report_day, tasks)
    )

    def postponed_rows(
        values: list[Task], ranges: dict[Any, tuple[str, str]]
    ) -> list[ClosingTableRow]:
        result: list[ClosingTableRow] = []
        for index, task in enumerate(ordered(values), 1):
            date_from, date_to = ranges.get(task.id, ("-", "-"))
            row = _task_row(
                task,
                [
                    str(index),
                    *common_values_with_project(task),
                    _m3_task_type_label(task),
                    _stack_start_due(date_from),
                    _stack_start_due(date_to),
                ],
            )
            row.values.extend(getattr(task, "_report_postponement_explanation", ("-", "-")))
            result.append(row)
        return result

    note_rows = [ClosingTableRow(values=row) for row in await _blue_note_rows(db)]

    return [
        ClosingSection(
            title="DET PA PROGRESS",
            tables=[
                ClosingTable(
                    label="TODO",
                    columns=[
                        "NR", "KUSH", "DEP", "PRJK", "AM/PM", "TITULLI", "ARSYEJA", "KOMENT"
                    ],
                    rows=no_progress_rows,
                    tone="todo",
                )
            ],
        ),
        ClosingSection(
            title="DET SYS PA KRY",
            tables=[
                ClosingTable(
                    label="DET SYS PA KRY",
                    columns=[
                        "NR", "KUSH", "DEP", "AM/PM", "T/Y/O", "TITULLI",
                        "ARSYEJA", "KOMENT",
                    ],
                    rows=system_rows,
                )
            ],
        ),
        ClosingSection(
            title="DET E SHTYERA",
            tables=[
                ClosingTable(
                    label="SHTYER START DHE DUE DATE",
                    columns=[
                        "NR", "KUSH", "DEP", "PRJK", "AM/PM", "LLOJI", "NGA", "NE", "TITULLI", "ARSYEJA", "KOMENT"
                    ],
                    rows=postponed_rows(postponed_both, postponed_both_ranges),
                ),
                ClosingTable(
                    label="SHTYER START OSE DUE DATE",
                    columns=[
                        "NR", "KUSH", "DEP", "PRJK", "AM/PM", "LLOJI", "NGA", "NE", "TITULLI", "ARSYEJA", "KOMENT"
                    ],
                    rows=postponed_rows(postponed, postponed_ranges),
                ),
            ],
        ),
        ClosingSection(
            title="NOTES PA DISK",
            tables=[
                ClosingTable(
                    label="NOTES",
                    columns=["NR", "DISK", "NOTE", "FROM", "TIME"],
                    rows=note_rows,
                    tone="notes",
                )
            ],
        ),
    ]
