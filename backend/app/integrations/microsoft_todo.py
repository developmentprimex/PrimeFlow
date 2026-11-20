"""Microsoft To Do (Graph) for the shared organizer mailbox (MS_ORGANIZER_EMAIL).

The mailbox's To Do lists sync with the GA's iPhone Reminders through Exchange.
Field mapping used here:

* ``title``                       -> reminder title
* ``dueDateTime``                 -> reminder date (To Do keeps only the date)
* ``reminderDateTime`` + ``isReminderOn`` -> reminder time ("with time" on iPhone)
* ``status`` = ``completed``      -> ticked on iPhone
* ``body`` (text)                 -> notes; steps are stored as ``☐``/``☑`` lines
  because ``checklistItems`` do not sync to iPhone Reminders over Exchange.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.integrations.microsoft import GRAPH_BASE_URL

TODO_SCOPE = "Tasks.ReadWrite"
STEP_OPEN = "☐"
STEP_DONE = "☑"


class TodoScopeMissing(RuntimeError):
    """The stored organizer token was granted before Tasks.ReadWrite was added."""


def ensure_todo_scope(scope: str | None) -> None:
    granted = {item.rsplit("/", 1)[-1].casefold() for item in (scope or "").split()}
    if TODO_SCOPE.casefold() not in granted:
        raise TodoScopeMissing(
            "The Microsoft connection of the organizer mailbox has no Tasks.ReadWrite permission. "
            "Re-authorize it in PrimeFlow (Settings -> Microsoft) after the app registration has the permission."
        )


@dataclass
class Step:
    text: str
    done: bool = False


def split_body(content: str | None) -> tuple[str, list[Step]]:
    """Split a To Do text body into free notes and ☐/☑ step lines."""
    notes: list[str] = []
    steps: list[Step] = []
    for line in (content or "").replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if stripped.startswith(STEP_OPEN):
            steps.append(Step(stripped[len(STEP_OPEN):].strip(), False))
        elif stripped.startswith(STEP_DONE):
            steps.append(Step(stripped[len(STEP_DONE):].strip(), True))
        else:
            notes.append(line)
    return "\n".join(notes).strip(), steps


def join_body(notes: str | None, steps: list[Step]) -> str:
    lines = [(notes or "").strip()] if (notes or "").strip() else []
    if steps:
        if lines:
            lines.append("")
        lines.extend(f"{STEP_DONE if step.done else STEP_OPEN} {step.text.strip()}" for step in steps if step.text.strip())
    return "\n".join(lines)


def graph_datetime(day: date, at: time, tz: ZoneInfo) -> dict[str, str]:
    """A dateTimeTimeZone in UTC, which Graph accepts for every To Do field."""
    local = datetime.combine(day, at, tzinfo=tz)
    return {"dateTime": local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"}


def due_payload(day: date | None) -> dict[str, str] | None:
    # To Do stores only the calendar date of dueDateTime; send that date at midnight
    # in UTC so the date never shifts with the conversion.
    if day is None:
        return None
    return {"dateTime": f"{day.isoformat()}T00:00:00", "timeZone": "UTC"}


# Exchange/iPhone reminders often carry Windows zone names. ZoneInfo knows only IANA
# names, so the common ones are mapped here; anything unknown is treated as UTC.
WINDOWS_ZONES = {
    "utc": "UTC",
    "coordinated universal time": "UTC",
    "tzone://microsoft/utc": "UTC",
    "gmt standard time": "Europe/London",
    "greenwich standard time": "Atlantic/Reykjavik",
    "w. europe standard time": "Europe/Berlin",
    "central europe standard time": "Europe/Budapest",
    "central european standard time": "Europe/Warsaw",
    "romance standard time": "Europe/Paris",
    "gtb standard time": "Europe/Bucharest",
    "e. europe standard time": "Europe/Chisinau",
    "fle standard time": "Europe/Kiev",
    "turkey standard time": "Europe/Istanbul",
    "russian standard time": "Europe/Moscow",
    "eastern standard time": "America/New_York",
    "central standard time": "America/Chicago",
    "mountain standard time": "America/Denver",
    "pacific standard time": "America/Los_Angeles",
}


def resolve_zone(name: str | None):
    """IANA zone for a Graph ``timeZone`` value (IANA or Windows name); UTC when unknown."""
    raw = (name or "UTC").strip()
    mapped = WINDOWS_ZONES.get(raw.casefold(), raw)
    if mapped.upper() in {"UTC", "GMT", "ETC/UTC"}:
        return timezone.utc
    try:
        return ZoneInfo(mapped)
    except Exception:
        return timezone.utc


def _naive(value: dict[str, Any]) -> datetime | None:
    raw = str(value["dateTime"]).split(".")[0]
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def parse_graph_dt(value: dict[str, Any] | None, tz: ZoneInfo) -> datetime | None:
    if not value or not value.get("dateTime"):
        return None
    parsed = _naive(value)
    if parsed is None:
        return None
    return parsed.replace(tzinfo=resolve_zone(value.get("timeZone"))).astimezone(tz)


def parse_due_date(value: dict[str, Any] | None, tz: ZoneInfo | None = None) -> date | None:
    """Calendar date of a To Do ``dueDateTime`` in the GA's timezone.

    iPhone/Exchange reminders store the due day as local midnight, which Graph often
    returns in UTC (``2026-11-19T23:00:00`` UTC = 20 Nov in Belgrade). Taking the raw
    date part would move such reminders one day back, so the value is converted to
    ``tz`` first. Without ``tz`` the raw date part is used (legacy behaviour).
    """
    if not value or not value.get("dateTime"):
        return None
    if tz is None:
        try:
            return date.fromisoformat(str(value["dateTime"])[:10])
        except ValueError:
            return None
    local = parse_graph_dt(value, tz)
    return local.date() if local is not None else None


class TodoClient:
    def __init__(self, access_token: str, *, timeout: float = 15.0):
        self._headers = {"Authorization": f"Bearer {access_token}"}
        self._timeout = timeout

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = path if path.startswith("https://") else f"{GRAPH_BASE_URL}{path}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            res = await client.request(method, url, headers=self._headers, **kwargs)
        res.raise_for_status()
        return res.json() if res.content else {}

    async def _paged(self, path: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        url: str | None = path
        next_params = params
        while url:
            data = await self._request("GET", url, params=next_params)
            items.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
            next_params = None
        return items

    async def lists(self) -> list[dict[str, Any]]:
        return await self._paged("/me/todo/lists")

    async def resolve_list(self, list_name: str | None) -> dict[str, Any]:
        lists = await self.lists()
        if list_name:
            wanted = list_name.strip().casefold()
            for item in lists:
                if str(item.get("displayName") or "").strip().casefold() == wanted:
                    return item
            raise ValueError(f"To Do list '{list_name}' was not found.")
        for item in lists:
            if item.get("wellknownListName") == "defaultList":
                return item
        if not lists:
            raise ValueError("The organizer mailbox has no To Do lists.")
        return lists[0]

    async def tasks(self, list_id: str, *, include_completed: bool) -> list[dict[str, Any]]:
        params = {"$top": "100"}
        if not include_completed:
            params["$filter"] = "status ne 'completed'"
        return await self._paged(f"/me/todo/lists/{list_id}/tasks", params)

    async def get(self, list_id: str, task_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/me/todo/lists/{list_id}/tasks/{task_id}")

    async def create(self, list_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/me/todo/lists/{list_id}/tasks", json=payload)

    async def update(self, list_id: str, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PATCH", f"/me/todo/lists/{list_id}/tasks/{task_id}", json=payload)
