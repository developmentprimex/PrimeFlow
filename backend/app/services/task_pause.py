from datetime import date, timedelta


def pause_until_on_day(periods: list[dict[str, str]] | None, day: date) -> date | None:
    day_key = day.isoformat()
    return next(
        (date.fromisoformat(period["until"]) for period in periods or []
         if period["from"] <= day_key <= period["until"]),
        None,
    )


def task_title_with_pause(title: str, periods: list[dict[str, str]] | None, day: date) -> str:
    return f"{title} [Pauzë]" if pause_until_on_day(periods, day) else title


def update_pause_periods(
    periods: list[dict[str, str]] | None, day: date, days: int | None,
) -> list[dict[str, str]]:
    day_key = day.isoformat()
    previous_day = (day - timedelta(days=1)).isoformat()
    history = [
        {"from": period["from"], "until": min(period["until"], previous_day)}
        for period in periods or [] if period["from"] < day_key
    ]
    if days is not None:
        history.append({"from": day_key, "until": (day + timedelta(days=days - 1)).isoformat()})
    return history
