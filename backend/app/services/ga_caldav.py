"""Read-only CalDAV view of the GA time table.

Apple Calendar can only colour a whole calendar, never a single event. To keep
the phone in the same colours as the time table, every colour is published as
its own calendar inside one CalDAV account, so GA adds the account once and
the calendars (with their colours) follow by themselves.

The server is stateless: resource names, ETags and collection tags are derived
from the current data, which is all a client needs to notice changes.
"""

from __future__ import annotations

import hashlib
import plistlib
import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import unquote, urlsplit

from app.models.ga_time_slot_template import GaTimeSlotTemplate
from app.models.meeting import Meeting
from app.services.ga_calendar_feed import (
    entry_event_lines,
    is_ga_time_table_meeting,
    meeting_event_lines,
    wrap_calendar,
)

CALDAV_PREFIX = "/caldav"
CALDAV_USERNAME = "ga"
ACCOUNT_NAME = "PrimeFlow GA"
ACCOUNT_EMAIL = "ga@primexeu.com"

DAV_HEADER = "1, 3, calendar-access"
ALLOWED_METHODS = "OPTIONS, GET, HEAD, PROPFIND, REPORT"
READ_ONLY_METHODS = {"PUT", "DELETE", "PROPPATCH", "MKCALENDAR", "MKCOL", "MOVE", "COPY", "LOCK", "UNLOCK", "POST"}

_NS = {
    "D": "DAV:",
    "C": "urn:ietf:params:xml:ns:caldav",
    "CS": "http://calendarserver.org/ns/",
    "A": "http://apple.com/ns/ical/",
}
for _prefix, _uri in _NS.items():
    ET.register_namespace(_prefix, _uri)


def _q(prefix: str, name: str) -> str:
    return f"{{{_NS[prefix]}}}{name}"


# The time table's background palette (GA_TIME_BACKGROUND_COLORS in the frontend).
_WHITE = "#FFFFFF"
_PALETTE: list[tuple[str, str, str]] = [
    ("yellow", "GA Yellow", "#FACC15"),
    ("purple", "GA Purple", "#A855F7"),
    ("red", "GA Red", "#EF4444"),
    ("green", "GA Green", "#22C55E"),
    ("blue", "GA Blue", "#3B82F6"),
]
_PALETTE_BY_COLOR = {color: (cal_id, name) for cal_id, name, color in _PALETTE}
# White rows have no colour of their own; a neutral grey stays readable in light and dark mode.
_DEFAULT_CALENDAR = ("default", "GA", "#64748B")
# Manual TAK INT rows are #fff4cc with a #d6b44c border; iOS lightens the calendar
# colour itself, so the border colour is the one that ends up looking the same.
_MEETING_CALENDAR = ("tak-int", "GA TAK INT", "#D6B44C")

# Older rows were saved with pale colours that the time table now shows as strong ones.
_STRONG_BACKGROUNDS = {
    "#FEF3C7": "#FACC15",
    "#FCE7F3": "#A855F7",
    "#F472B6": "#A855F7",
    "#FEE2E2": "#EF4444",
    "#DCFCE7": "#22C55E",
    "#DBEAFE": "#3B82F6",
}
_TEXT_COLOR_ALIASES = {
    "RED": "#EF4444",
    "#FF0000": "#EF4444",
    "RGB(255,0,0)": "#EF4444",
    "RGB(239,68,68)": "#EF4444",
    "YELLOW": "#FACC15",
    "RGB(250,204,21)": "#FACC15",
    "PURPLE": "#A855F7",
    "RGB(168,85,247)": "#A855F7",
    "GREEN": "#22C55E",
    "RGB(34,197,94)": "#22C55E",
    "BLUE": "#3B82F6",
    "RGB(59,130,246)": "#3B82F6",
}
_HEX_COLOR = re.compile(r"^#[0-9A-F]{6}$")
_STYLE_COLOR = re.compile(r"(?:^|;)\s*color\s*:\s*([^;]+)", re.IGNORECASE)


def _normalize_color(value: str | None) -> str:
    color = re.sub(r"\s+", "", value or "").upper()
    return _TEXT_COLOR_ALIASES.get(color, color)


class _LeadingColorParser(HTMLParser):
    """Find the inline colour of the first visible character of a rich-text row."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[tuple[str, str | None]] = []
        self.color: str | None = None
        self.done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.done or tag in {"br", "img", "hr"}:
            return
        values = {name: value or "" for name, value in attrs}
        color = values.get("data-ga-color") or values.get("color") or ""
        if not color:
            match = _STYLE_COLOR.search(values.get("style", ""))
            color = match.group(1) if match else ""
        self._stack.append((tag, _normalize_color(color) or None))

    def handle_endtag(self, tag: str) -> None:
        if self.done:
            return
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if self.done or not data.strip():
            return
        self.done = True
        for _, color in reversed(self._stack):
            if color:
                self.color = color
                break


def _leading_text_color(content: str | None) -> str | None:
    if not content or "<" not in content:
        return None
    parser = _LeadingColorParser()
    try:
        parser.feed(content)
    except Exception:
        return None
    return parser.color


def entry_calendar(entry: GaTimeSlotTemplate) -> tuple[str, str, str]:
    """Return (calendar id, name, colour) for a time table row."""
    background = _normalize_color(entry.background_color) or _WHITE
    background = _STRONG_BACKGROUNDS.get(background, background)
    if background in _PALETTE_BY_COLOR:
        cal_id, name = _PALETTE_BY_COLOR[background]
        return cal_id, name, background
    if background != _WHITE and _HEX_COLOR.match(background):
        # A colour outside the palette still gets its own calendar.
        return f"c-{background[1:].lower()}", f"GA {background}", background
    # White row: the visible colour is the text, so a coloured row title decides.
    for candidate in (_normalize_color(entry.text_color), _leading_text_color(entry.content)):
        if candidate in _PALETTE_BY_COLOR:
            cal_id, name = _PALETTE_BY_COLOR[candidate]
            return cal_id, name, candidate
    return _DEFAULT_CALENDAR


@dataclass
class DavEvent:
    name: str
    ics: str
    etag: str


@dataclass
class DavCalendar:
    id: str
    name: str
    color: str
    order: int
    events: list[DavEvent] = field(default_factory=list)

    @property
    def ctag(self) -> str:
        digest = hashlib.sha1()
        for event in sorted(self.events, key=lambda item: item.name):
            digest.update(f"{event.name}:{event.etag};".encode())
        return f"{self.id}-{digest.hexdigest()}"


def _event(name: str, event_lines: list[str]) -> DavEvent | None:
    if not event_lines:
        return None
    ics = wrap_calendar(event_lines)
    return DavEvent(name=f"{name}.ics", ics=ics, etag=f'"{hashlib.sha1(ics.encode()).hexdigest()}"')


def build_calendars(entries: list[GaTimeSlotTemplate], meetings: list[Meeting]) -> list[DavCalendar]:
    """Group the time table into one calendar per colour.

    The palette calendars always exist, so the phone's calendar list stays
    stable; a calendar for an unusual colour appears only while it is in use.
    TAK EXT is left out on purpose: the phone already has it from Outlook.
    """
    fixed = [_DEFAULT_CALENDAR, *_PALETTE, _MEETING_CALENDAR]
    calendars: dict[str, DavCalendar] = {
        cal_id: DavCalendar(id=cal_id, name=name, color=color, order=index + 1)
        for index, (cal_id, name, color) in enumerate(fixed)
    }
    for entry in entries:
        cal_id, name, color = entry_calendar(entry)
        calendar = calendars.get(cal_id)
        if calendar is None:
            calendar = calendars[cal_id] = DavCalendar(id=cal_id, name=name, color=color, order=len(calendars) + 1)
        # The calendar id is part of the UID: a row that changes colour leaves one
        # calendar and appears in another, and iOS mishandles one UID in two calendars.
        # The short domain keeps the UID line under the 75-octet folding limit.
        resource = f"ga-time-slot-{entry.id}-{cal_id}"
        event = _event(resource, entry_event_lines(entry, uid=f"{resource}@primeflow"))
        if event:
            calendar.events.append(event)
    meeting_calendar = calendars[_MEETING_CALENDAR[0]]
    for meeting in meetings:
        if not is_ga_time_table_meeting(meeting):
            continue
        resource = f"ga-m-{meeting.id}-{meeting_calendar.id}"
        event = _event(resource, meeting_event_lines(meeting, uid=f"{resource}@primeflow"))
        if event:
            meeting_calendar.events.append(event)
    return list(calendars.values())


# --- WebDAV resources -------------------------------------------------------

PropWriter = Callable[[ET.Element], None]


@dataclass
class _Resource:
    href: str
    props: dict[str, PropWriter]
    children: list["_Resource"] = field(default_factory=list)
    event: DavEvent | None = None
    calendar: DavCalendar | None = None


@dataclass
class DavResponse:
    status: int
    body: bytes = b""
    media_type: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


PRINCIPAL_HREF = f"{CALDAV_PREFIX}/principals/{CALDAV_USERNAME}/"
HOME_HREF = f"{CALDAV_PREFIX}/calendars/{CALDAV_USERNAME}/"


def _text(value: str) -> PropWriter:
    def write(element: ET.Element) -> None:
        element.text = value

    return write


def _hrefs(*values: str) -> PropWriter:
    def write(element: ET.Element) -> None:
        for value in values:
            ET.SubElement(element, _q("D", "href")).text = value

    return write


def _types(*names: str) -> PropWriter:
    def write(element: ET.Element) -> None:
        for name in names:
            ET.SubElement(element, name)

    return write


def _read_only_privileges(element: ET.Element) -> None:
    for name in ("read", "read-current-user-privilege-set"):
        ET.SubElement(ET.SubElement(element, _q("D", "privilege")), _q("D", name))


def _supported_reports(element: ET.Element) -> None:
    for name in ("calendar-multiget", "calendar-query"):
        report = ET.SubElement(ET.SubElement(element, _q("D", "supported-report")), _q("D", "report"))
        ET.SubElement(report, _q("C", name))


def _supported_components(element: ET.Element) -> None:
    ET.SubElement(element, _q("C", "comp"), {"name": "VEVENT"})


def _common_props(name: str, *resource_types: str) -> dict[str, PropWriter]:
    return {
        _q("D", "resourcetype"): _types(*resource_types),
        _q("D", "displayname"): _text(name),
        _q("D", "current-user-principal"): _hrefs(PRINCIPAL_HREF),
        _q("D", "owner"): _hrefs(PRINCIPAL_HREF),
        _q("D", "current-user-privilege-set"): _read_only_privileges,
    }


def _event_resource(calendar: DavCalendar, event: DavEvent) -> _Resource:
    return _Resource(
        href=f"{HOME_HREF}{calendar.id}/{event.name}",
        props={
            _q("D", "resourcetype"): _types(),
            _q("D", "getetag"): _text(event.etag),
            _q("D", "getcontenttype"): _text("text/calendar; charset=utf-8; component=vevent"),
            _q("D", "getcontentlength"): _text(str(len(event.ics.encode()))),
            _q("D", "current-user-privilege-set"): _read_only_privileges,
        },
        event=event,
    )


def _calendar_resource(calendar: DavCalendar) -> _Resource:
    props = _common_props(calendar.name, _q("D", "collection"), _q("C", "calendar"))
    props.update(
        {
            # Apple reads the colour as #RRGGBBAA.
            _q("A", "calendar-color"): _text(f"{calendar.color}FF"),
            _q("A", "calendar-order"): _text(str(calendar.order)),
            _q("CS", "getctag"): _text(calendar.ctag),
            _q("C", "supported-calendar-component-set"): _supported_components,
            _q("C", "calendar-description"): _text(f"{calendar.name} - PrimeFlow GA time table"),
            _q("D", "supported-report-set"): _supported_reports,
        }
    )
    return _Resource(
        href=f"{HOME_HREF}{calendar.id}/",
        props=props,
        children=[_event_resource(calendar, event) for event in calendar.events],
        calendar=calendar,
    )


def _principal_resource() -> _Resource:
    props = _common_props(ACCOUNT_NAME, _q("D", "collection"), _q("D", "principal"))
    props.update(
        {
            _q("D", "principal-URL"): _hrefs(PRINCIPAL_HREF),
            _q("D", "principal-collection-set"): _hrefs(f"{CALDAV_PREFIX}/principals/"),
            _q("C", "calendar-home-set"): _hrefs(HOME_HREF),
            _q("C", "calendar-user-address-set"): _hrefs(f"mailto:{ACCOUNT_EMAIL}", PRINCIPAL_HREF),
            _q("D", "supported-report-set"): _types(),
        }
    )
    return _Resource(href=PRINCIPAL_HREF, props=props)


def _resolve(path: str, calendars: list[DavCalendar]) -> _Resource | None:
    parts = [part for part in path.split("/") if part]
    if not parts:
        root = _common_props(ACCOUNT_NAME, _q("D", "collection"))
        root[_q("D", "principal-URL")] = _hrefs(PRINCIPAL_HREF)
        return _Resource(href=f"{CALDAV_PREFIX}/", props=root)
    if parts[0] == "principals":
        if len(parts) == 1:
            return _Resource(
                href=f"{CALDAV_PREFIX}/principals/",
                props=_common_props("Principals", _q("D", "collection")),
                children=[_principal_resource()],
            )
        if len(parts) == 2 and parts[1].lower() == CALDAV_USERNAME:
            return _principal_resource()
        return None
    if parts[0] != "calendars" or len(parts) < 2 or parts[1].lower() != CALDAV_USERNAME or len(parts) > 4:
        return None
    if len(parts) == 2:
        return _Resource(
            href=HOME_HREF,
            props=_common_props(ACCOUNT_NAME, _q("D", "collection")),
            children=[_calendar_resource(calendar) for calendar in calendars],
        )
    calendar = next((item for item in calendars if item.id == parts[2]), None)
    if calendar is None:
        return None
    resource = _calendar_resource(calendar)
    if len(parts) == 3:
        return resource
    return next((child for child in resource.children if child.event and child.event.name == parts[3]), None)


# --- Multi-status building --------------------------------------------------

_CALENDAR_DATA = _q("C", "calendar-data")


def _requested_props(body: bytes) -> list[str] | None:
    """Return the property names a request asks for, or None for "all"."""
    if not body.strip():
        return None
    root = ET.fromstring(body)
    prop = root.find(_q("D", "prop"))
    if prop is None:
        return None
    return [child.tag for child in prop]


def _append_response(
    multistatus: ET.Element, resource: _Resource, requested: list[str] | None, *, minimal: bool
) -> None:
    props = dict(resource.props)
    if resource.event is not None and requested and _CALENDAR_DATA in requested:
        props[_CALENDAR_DATA] = _text(resource.event.ics)
    names = list(props) if requested is None else requested

    response = ET.SubElement(multistatus, _q("D", "response"))
    ET.SubElement(response, _q("D", "href")).text = resource.href
    found = [name for name in names if name in props]
    missing = [name for name in names if name not in props]
    if found or not missing:
        propstat = ET.SubElement(response, _q("D", "propstat"))
        prop = ET.SubElement(propstat, _q("D", "prop"))
        for name in found:
            props[name](ET.SubElement(prop, name))
        ET.SubElement(propstat, _q("D", "status")).text = "HTTP/1.1 200 OK"
    if missing and not (minimal and found):
        propstat = ET.SubElement(response, _q("D", "propstat"))
        prop = ET.SubElement(propstat, _q("D", "prop"))
        for name in missing:
            ET.SubElement(prop, name)
        ET.SubElement(propstat, _q("D", "status")).text = "HTTP/1.1 404 Not Found"


def _multistatus(build: Callable[[ET.Element], None], *, minimal: bool) -> DavResponse:
    root = ET.Element(_q("D", "multistatus"))
    build(root)
    body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    headers = {"DAV": DAV_HEADER}
    if minimal:
        headers["Preference-Applied"] = "return=minimal"
    return DavResponse(207, body, 'application/xml; charset="utf-8"', headers)


def _error(status: int, *, precondition: str | None = None) -> DavResponse:
    if precondition is None:
        return DavResponse(status, headers={"DAV": DAV_HEADER})
    root = ET.Element(_q("D", "error"))
    ET.SubElement(root, precondition)
    return DavResponse(
        status,
        ET.tostring(root, encoding="utf-8", xml_declaration=True),
        'application/xml; charset="utf-8"',
        {"DAV": DAV_HEADER},
    )


def _href_path(href: str) -> str:
    path = unquote(urlsplit(href.strip()).path)
    if path.startswith(CALDAV_PREFIX):
        path = path[len(CALDAV_PREFIX) :]
    return path


def handle_caldav_request(
    method: str,
    path: str,
    calendars: list[DavCalendar],
    *,
    depth: str = "0",
    body: bytes = b"",
    prefer: str = "",
) -> DavResponse:
    """Answer one CalDAV request. ``path`` is relative to ``CALDAV_PREFIX``."""
    method = method.upper()
    minimal = "return=minimal" in prefer.replace(" ", "").lower()
    if method == "OPTIONS":
        return DavResponse(200, headers={"DAV": DAV_HEADER, "Allow": ALLOWED_METHODS})
    if method in READ_ONLY_METHODS:
        return _error(403)

    resource = _resolve(path, calendars)
    if resource is None:
        return _error(404)

    if method in {"GET", "HEAD"}:
        if resource.event is None:
            return DavResponse(200, b"PrimeFlow GA calendar\n", "text/plain; charset=utf-8", {"DAV": DAV_HEADER})
        return DavResponse(
            200,
            resource.event.ics.encode(),
            "text/calendar; charset=utf-8; component=vevent",
            {"ETag": resource.event.etag, "DAV": DAV_HEADER},
        )

    try:
        if method == "PROPFIND":
            requested = _requested_props(body)

            def build(root: ET.Element) -> None:
                _append_response(root, resource, requested, minimal=minimal)
                if depth.strip() != "0":
                    for child in resource.children:
                        _append_response(root, child, requested, minimal=minimal)

            return _multistatus(build, minimal=minimal)

        if method == "REPORT":
            if resource.calendar is None and resource.event is None:
                return _error(403, precondition=_q("D", "supported-report"))
            report = ET.fromstring(body)
            prop = report.find(_q("D", "prop"))
            requested = [child.tag for child in prop] if prop is not None else []
            events = resource.children if resource.calendar is not None else [resource]

            if report.tag == _q("C", "calendar-query"):

                def build(root: ET.Element) -> None:
                    for child in events:
                        _append_response(root, child, requested, minimal=minimal)

                return _multistatus(build, minimal=minimal)

            if report.tag == _q("C", "calendar-multiget"):
                by_path = {_href_path(child.href): child for child in events}

                def build(root: ET.Element) -> None:
                    for element in report.findall(_q("D", "href")):
                        child = by_path.get(_href_path(element.text or ""))
                        if child is not None:
                            _append_response(root, child, requested, minimal=minimal)
                            continue
                        response = ET.SubElement(root, _q("D", "response"))
                        ET.SubElement(response, _q("D", "href")).text = (element.text or "").strip()
                        ET.SubElement(response, _q("D", "status")).text = "HTTP/1.1 404 Not Found"

                return _multistatus(build, minimal=minimal)

            return _error(403, precondition=_q("D", "supported-report"))
    except ET.ParseError:
        return _error(400)

    return DavResponse(405, headers={"DAV": DAV_HEADER, "Allow": ALLOWED_METHODS})


def build_caldav_profile(*, host: str, port: int, use_ssl: bool, password: str) -> bytes:
    """An iOS configuration profile that adds the account without any typing."""
    namespace = uuid.uuid5(uuid.NAMESPACE_DNS, f"primeflow-ga-caldav.{host}")
    account = {
        "PayloadType": "com.apple.caldav.account",
        "PayloadVersion": 1,
        "PayloadIdentifier": "com.primexeu.primeflow.ga.caldav.account",
        "PayloadUUID": str(uuid.uuid5(namespace, "account")).upper(),
        "PayloadDisplayName": ACCOUNT_NAME,
        "CalDAVAccountDescription": ACCOUNT_NAME,
        "CalDAVHostName": host,
        "CalDAVPort": port,
        "CalDAVUseSSL": use_ssl,
        "CalDAVPrincipalURL": PRINCIPAL_HREF,
        "CalDAVUsername": CALDAV_USERNAME,
        "CalDAVPassword": password,
    }
    return plistlib.dumps(
        {
            "PayloadType": "Configuration",
            "PayloadVersion": 1,
            "PayloadIdentifier": "com.primexeu.primeflow.ga.caldav",
            "PayloadUUID": str(uuid.uuid5(namespace, "profile")).upper(),
            "PayloadDisplayName": f"{ACCOUNT_NAME} Calendar",
            "PayloadDescription": "Adds the PrimeFlow GA time table to Calendar, in the time table colours.",
            "PayloadOrganization": "PrimeFlow",
            "PayloadContent": [account],
        }
    )
