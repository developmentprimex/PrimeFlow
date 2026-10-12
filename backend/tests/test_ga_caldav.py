from __future__ import annotations

import base64
import plistlib
import unittest
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, time, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import ga_caldav as caldav_router
from app.db import get_db
from app.services.ga_caldav import build_caldav_profile, build_calendars, entry_calendar
from app.services.ga_calendar_feed import caldav_password


D = "{DAV:}"
C = "{urn:ietf:params:xml:ns:caldav}"
CS = "{http://calendarserver.org/ns/}"
A = "{http://apple.com/ns/ical/}"

GA_USER = SimpleNamespace(id=uuid.UUID("11111111-1111-1111-1111-111111111111"))


def _entry(content: str, background: str = "#FFFFFF", text: str = "#0F172A", **overrides):
    values = {
        "id": uuid.uuid4(),
        "day_of_week": 0,
        "start_time": time(15, 30),
        "end_time": time(16, 0),
        "content": content,
        "background_color": background,
        "text_color": text,
        "created_at": datetime(2026, 10, 5, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 10, 6, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _meeting(title: str = "BZ TAK INT FINC"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        title=title,
        platform=None,
        meeting_url=None,
        meeting_type="internal",
        starts_at=datetime(2026, 10, 14, 9, 15, tzinfo=timezone.utc),
        ends_at=None,
        recurrence_type="none",
        recurrence_days_of_week=None,
        recurrence_days_of_month=None,
        paired_external_meeting_id=None,
        pre_external_meeting_id=None,
        calendar_imported=False,
        microsoft_event_id=None,
        calendar_sync_status=None,
        calendar_categories=None,
        reminder_minutes_before=15,
        updated_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )


class TestEntryColours(unittest.TestCase):
    def test_background_colour_decides_the_calendar(self) -> None:
        self.assertEqual(entry_calendar(_entry("LC HW", "#A855F7")), ("purple", "GA Purple", "#A855F7"))
        self.assertEqual(entry_calendar(_entry("x", "#facc15"))[0], "yellow")
        # Pale colours from older rows are shown as the strong colour in the time table.
        self.assertEqual(entry_calendar(_entry("x", "#FEE2E2"))[2], "#EF4444")

    def test_white_row_follows_its_text_colour(self) -> None:
        self.assertEqual(entry_calendar(_entry("x", text="#3B82F6"))[0], "blue")
        self.assertEqual(
            entry_calendar(_entry('<span data-ga-color="#A855F7" style="color: rgb(168, 85, 247);">RRC</span> / MC'))[0],
            "purple",
        )
        self.assertEqual(entry_calendar(_entry('<strong><font color="red">DNSPG</font></strong>'))[0], "red")
        # Only the start of the row counts: a red question mark at the end does not recolour it.
        self.assertEqual(entry_calendar(_entry('MC <span style="color:#EF4444">?</span>'))[0], "default")
        self.assertEqual(entry_calendar(_entry("MC MSM"))[0], "default")

    def test_unusual_colour_gets_its_own_calendar(self) -> None:
        self.assertEqual(entry_calendar(_entry("x", "#123abc")), ("c-123abc", "GA #123ABC", "#123ABC"))


class TestCalDavFlow(unittest.TestCase):
    """Walks the same requests the iPhone sends when the account is added."""

    def setUp(self) -> None:
        self.purple = _entry("LC HW", "#A855F7")
        self.plain = _entry("MC MSM")
        self.meeting = _meeting()
        self.entries = [self.purple, self.plain]
        self.meetings = [self.meeting]

        app = FastAPI()
        app.include_router(caldav_router.router)

        async def _no_db():
            yield None

        app.dependency_overrides[get_db] = _no_db

        async def _ga_user(_db):
            return GA_USER

        async def _sources(_db, _user):
            return self.entries, self.meetings

        for target, replacement in (("_resolve_ga_user", _ga_user), ("load_ga_calendar_sources", _sources)):
            patcher = patch.object(caldav_router, target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.client = TestClient(app)
        token = base64.b64encode(f"ga:{caldav_password(GA_USER.id)}".encode()).decode()
        self.auth = {"Authorization": f"Basic {token}"}

    def _propfind(self, path: str, props: str, depth: str = "0") -> ET.Element:
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<A:propfind xmlns:A="DAV:" xmlns:B="urn:ietf:params:xml:ns:caldav" '
            'xmlns:C="http://calendarserver.org/ns/" xmlns:D="http://apple.com/ns/ical/">'
            f"<A:prop>{props}</A:prop></A:propfind>"
        )
        response = self.client.request(
            "PROPFIND", path, content=body, headers={**self.auth, "Depth": depth, "Content-Type": "text/xml"}
        )
        self.assertEqual(response.status_code, 207, response.text)
        return ET.fromstring(response.content)

    @staticmethod
    def _ok_prop(response: ET.Element, tag: str) -> ET.Element | None:
        for propstat in response.findall(f"{D}propstat"):
            if "200" in (propstat.findtext(f"{D}status") or ""):
                return propstat.find(f"{D}prop/{tag}")
        return None

    def test_discovery_and_authentication(self) -> None:
        redirect = self.client.request("PROPFIND", "/.well-known/caldav", follow_redirects=False)
        self.assertEqual(redirect.status_code, 301)
        self.assertEqual(redirect.headers["location"], "/caldav/")

        options = self.client.request("OPTIONS", "/caldav/")
        self.assertEqual(options.status_code, 200)
        self.assertIn("calendar-access", options.headers["dav"])

        anonymous = self.client.request("PROPFIND", "/caldav/")
        self.assertEqual(anonymous.status_code, 401)
        self.assertTrue(anonymous.headers["www-authenticate"].startswith("Basic "))

        wrong = base64.b64encode(b"ga:wrong-password").decode()
        denied = self.client.request("PROPFIND", "/caldav/", headers={"Authorization": f"Basic {wrong}"})
        self.assertEqual(denied.status_code, 401)

        for path in ("/caldav/", "/caldav", "/"):
            root = self._propfind(path, "<A:current-user-principal/><A:resourcetype/>")
            principal = self._ok_prop(root.find(f"{D}response"), f"{D}current-user-principal")
            self.assertEqual(principal.findtext(f"{D}href"), "/caldav/principals/ga/")

        principal = self._propfind(
            "/caldav/principals/ga/", "<B:calendar-home-set/><B:schedule-inbox-URL/><A:displayname/>"
        ).find(f"{D}response")
        home = self._ok_prop(principal, f"{C}calendar-home-set")
        self.assertEqual(home.findtext(f"{D}href"), "/caldav/calendars/ga/")
        # Unknown properties are reported as missing, not dropped.
        statuses = [propstat.findtext(f"{D}status") for propstat in principal.findall(f"{D}propstat")]
        self.assertIn("HTTP/1.1 404 Not Found", statuses)

    def test_calendar_list_carries_the_time_table_colours(self) -> None:
        home = self._propfind(
            "/caldav/calendars/ga/",
            "<A:resourcetype/><A:displayname/><D:calendar-color/><C:getctag/>"
            "<B:supported-calendar-component-set/><A:current-user-privilege-set/>",
            depth="1",
        )
        calendars = {}
        for response in home.findall(f"{D}response"):
            if self._ok_prop(response, f"{D}resourcetype").find(f"{C}calendar") is None:
                continue
            calendars[response.findtext(f"{D}href")] = response
        self.assertEqual(
            set(calendars),
            {f"/caldav/calendars/ga/{name}/" for name in ("default", "yellow", "purple", "red", "green", "blue", "tak-int")},
        )
        purple = calendars["/caldav/calendars/ga/purple/"]
        self.assertEqual(self._ok_prop(purple, f"{A}calendar-color").text, "#A855F7FF")
        self.assertEqual(self._ok_prop(purple, f"{D}displayname").text, "GA Purple")
        self.assertEqual(
            self._ok_prop(purple, f"{C}supported-calendar-component-set").find(f"{C}comp").get("name"), "VEVENT"
        )
        privileges = self._ok_prop(purple, f"{D}current-user-privilege-set")
        self.assertIsNone(privileges.find(f"{D}privilege/{D}write"))
        self.assertIsNotNone(privileges.find(f"{D}privilege/{D}read"))

    def test_events_are_listed_fetched_and_read_only(self) -> None:
        listing = self._propfind("/caldav/calendars/ga/purple/", "<A:getetag/><A:getcontenttype/>", depth="1")
        events = [r for r in listing.findall(f"{D}response") if r.findtext(f"{D}href").endswith(".ics")]
        self.assertEqual(len(events), 1)
        href = events[0].findtext(f"{D}href")
        etag = self._ok_prop(events[0], f"{D}getetag").text
        self.assertEqual(href, f"/caldav/calendars/ga/purple/ga-time-slot-{self.purple.id}-purple.ics")

        report = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<B:calendar-multiget xmlns:A="DAV:" xmlns:B="urn:ietf:params:xml:ns:caldav">'
            "<A:prop><A:getetag/><B:calendar-data/></A:prop>"
            f"<A:href>{href}</A:href><A:href>/caldav/calendars/ga/purple/missing.ics</A:href>"
            "</B:calendar-multiget>"
        )
        response = self.client.request(
            "REPORT", "/caldav/calendars/ga/purple/", content=report, headers={**self.auth, "Depth": "1"}
        )
        self.assertEqual(response.status_code, 207, response.text)
        found, missing = ET.fromstring(response.content).findall(f"{D}response")
        data = self._ok_prop(found, f"{C}calendar-data").text
        self.assertIn("SUMMARY:LC HW", data)
        self.assertIn(f"UID:ga-time-slot-{self.purple.id}-purple@primeflow", data)
        self.assertIn("RRULE:FREQ=WEEKLY;BYDAY=MO", data)
        self.assertEqual(self._ok_prop(found, f"{D}getetag").text, etag)
        self.assertIn("404", missing.findtext(f"{D}status"))

        query = (
            '<B:calendar-query xmlns:A="DAV:" xmlns:B="urn:ietf:params:xml:ns:caldav">'
            '<A:prop><A:getetag/></A:prop><B:filter><B:comp-filter name="VCALENDAR"/></B:filter></B:calendar-query>'
        )
        response = self.client.request("REPORT", "/caldav/calendars/ga/tak-int/", content=query, headers=self.auth)
        self.assertEqual(response.status_code, 207)
        self.assertEqual(len(ET.fromstring(response.content).findall(f"{D}response")), 1)

        fetched = self.client.get(href, headers=self.auth)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.headers["etag"], etag)
        self.assertTrue(fetched.headers["content-type"].startswith("text/calendar"))

        for method in ("PUT", "DELETE", "PROPPATCH", "MKCALENDAR"):
            self.assertEqual(self.client.request(method, href, headers=self.auth).status_code, 403, method)
        self.assertEqual(self.client.get("/caldav/calendars/ga/nope/", headers=self.auth).status_code, 404)

    def test_colour_change_moves_the_event_and_updates_both_ctags(self) -> None:
        before = {calendar.id: calendar.ctag for calendar in build_calendars(self.entries, self.meetings)}
        unchanged = {calendar.id: calendar.ctag for calendar in build_calendars(self.entries, self.meetings)}
        self.assertEqual(before, unchanged)

        self.purple.background_color = "#EF4444"
        after = {calendar.id: calendar for calendar in build_calendars(self.entries, self.meetings)}
        self.assertNotEqual(before["purple"], after["purple"].ctag)
        self.assertNotEqual(before["red"], after["red"].ctag)
        self.assertEqual(before["default"], after["default"].ctag)
        self.assertEqual(after["purple"].events, [])
        self.assertEqual(after["red"].events[0].name, f"ga-time-slot-{self.purple.id}-red.ics")

    def test_profile_points_the_phone_at_the_account(self) -> None:
        profile = plistlib.loads(
            build_caldav_profile(host="api-flow.primexeu.com", port=443, use_ssl=True, password="secret")
        )
        account = profile["PayloadContent"][0]
        self.assertEqual(account["PayloadType"], "com.apple.caldav.account")
        self.assertEqual(account["CalDAVHostName"], "api-flow.primexeu.com")
        self.assertEqual(account["CalDAVPrincipalURL"], "/caldav/principals/ga/")
        self.assertEqual((account["CalDAVUsername"], account["CalDAVPassword"]), ("ga", "secret"))
        self.assertIs(account["CalDAVUseSSL"], True)


if __name__ == "__main__":
    unittest.main()
