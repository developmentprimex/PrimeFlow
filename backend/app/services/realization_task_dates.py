from __future__ import annotations

from datetime import date

from app.services.daily_realization_events import semantic_local_day


def start_dates_for_day(*, events, day: date, current_start: date | None) -> dict:
    """Recover start dates around the selected day's changes, including old days."""
    ordered = sorted(events, key=lambda event: (event.created_at, str(event.id)))
    today = [event for event in ordered if semantic_local_day(event.created_at) == day]
    earlier = [event for event in ordered if semantic_local_day(event.created_at) < day]
    later = [event for event in ordered if semantic_local_day(event.created_at) > day]
    if today:
        original = semantic_local_day((today[0].before or {}).get("value"))
        final = semantic_local_day((today[-1].after or {}).get("value"))
    elif earlier:
        original = final = semantic_local_day((earlier[-1].after or {}).get("value"))
    elif later:
        original = final = semantic_local_day((later[0].before or {}).get("value"))
    else:
        original = final = current_start
    return {
        "original_start_date": original.isoformat() if original else None,
        "start_date_on_day": final.isoformat() if final else None,
    }
