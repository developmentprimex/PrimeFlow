from datetime import date
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.services.tomorrow_print_report import _excel_table_attachment, _html_table, _task_rows


@pytest.mark.parametrize("period_field", ["finishPeriod", "finish_period"])
@pytest.mark.parametrize("all_day_period", [None, "AM/PM"])
def test_blocked_tasks_group_by_period_before_existing_person_order(period_field, all_day_period):
    report_date = date(2026, 10, 19)
    tasks = []
    for period in ("PM", all_day_period, " am "):
        for person_order in (2, 1):
            label = period.strip().upper() if period and period != "AM/PM" else "ALL-DAY"
            tasks.append({
                "task_id": f"{label}-{person_order}",
                "title": f"Work {label} person {person_order}",
                "date": report_date.isoformat(),
                period_field: period,
                "weeklyPlannerSort": [0, person_order],
                "isDeadlineImportant": period == "PM",
                "oneHReportSlot": "10:00",
            })

    rows = _task_rows({"blocked": tasks, "oneH": tasks}, report_date)
    blocked = next(items for label, items, _ in rows if label.startswith("BLL"))
    expected = [
        "Work ALL-DAY person 1", "Work AM person 1",
        "Work ALL-DAY person 2", "Work AM person 2",
        "Work PM person 1", "Work PM person 2",
    ]
    assert [item["title"] for item in blocked] == expected

    # Other task rows retain person-first ordering, including priority within a person.
    one_h = next(items for label, items, _ in rows if label == "1H 10:00")
    assert [item["title"] for item in one_h] == [
        "Work PM person 1", "Work ALL-DAY person 1", "Work AM person 1",
        "Work PM person 2", "Work ALL-DAY person 2", "Work AM person 2",
    ]

    blocked_rows = [("BLL", blocked, False)]
    html = _html_table(blocked_rows, report_date=report_date)
    assert [html.index(title) for title in expected] == sorted(html.index(title) for title in expected)

    _, content, _ = _excel_table_attachment(blocked_rows, [], report_date)
    sheet = load_workbook(BytesIO(content)).active
    exported = "\n".join(str(cell.value or "") for row in sheet for cell in row)
    assert [exported.index(title) for title in expected] == sorted(exported.index(title) for title in expected)
