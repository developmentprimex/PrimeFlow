"""Project work that justifies missing 1H slots in PCM and Graphic Design."""

PROJECT_COVERAGE_DEPARTMENTS = {
    "PCM", "GD", "GDS", "GRAPHIC DESIGN", "PRODUCT CONTENT",
    "PROJECT CONTENT", "PROJECT CONTENT MANAGER",
}


def is_project_coverage_department(code: str | None, name: str | None = None) -> bool:
    return any((value or "").strip().upper() in PROJECT_COVERAGE_DEPARTMENTS for value in (code, name))


def project_task_periods(finish_period: str | None) -> tuple[str, ...]:
    period = (finish_period or "").strip().upper()
    return (period,) if period in {"AM", "PM"} else ("AM", "PM")
