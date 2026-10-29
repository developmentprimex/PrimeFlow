import unittest
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.services.after_break_report import (
    DISPLAY_SECTION_TITLES,
    SECTION_TITLES,
    UNFINISHED_PRIORITY_COLUMNS,
    UNFINISHED_PRIORITY_TABLE_LABEL,
    _ascii_table,
    _blue_note_rows,
    _format_confirmation_questions,
    _done_am_task_rows,
    _new_system_task_rows,
    _unheld_meeting_section,
    _unfinished_priority_task_rows,
    _waiting_client_task_rows,
    _waiting_client_entry_dates,
    normalize_after_break_report_sections,
)
from app.services.meetings_report import _render_ascii_table_html, _table_tone_from_label
from app.services.meeting_point_manual_sync import section_group_label, with_section_keys


class AfterBreakConfirmationCategoryTests(unittest.TestCase):
    def test_edited_auto_title_keeps_its_original_m2_identity_and_position(self) -> None:
        saved = [{"title": title, "body": str(index)} for index, title in enumerate(SECTION_TITLES)]
        saved[4]["title"] = "DET TE PAKRYERA AM, 08:00/DEADLINE"

        sections = normalize_after_break_report_sections(with_section_keys("after_break", saved))
        affected = next(section for section in sections if section["section_key"] == SECTION_TITLES[4])

        self.assertEqual(affected["title"], "DET TE PAKRYERA AM, 08:00/DEADLINE")
        self.assertEqual(sections.index(affected), DISPLAY_SECTION_TITLES.index(SECTION_TITLES[4]))
        self.assertEqual(
            section_group_label("after_break", affected["title"], affected["section_key"]),
            "AUTO-FILLED FROM PRIMEFLOW",
        )

    def test_undiscussed_notes_are_first_in_the_auto_filled_group(self) -> None:
        sections = normalize_after_break_report_sections([])

        self.assertEqual(
            [section["title"] for section in sections],
            DISPLAY_SECTION_TITLES,
        )
        self.assertEqual(sections[4]["title"], "NOTES TE REJA ( NOT DISSCUSED)")
        self.assertEqual(sections[5]["title"], "TAK INT/EXT TE PAMBAJTURA")
        self.assertEqual(sections[6]["title"], "DET TE PAKRYERA, 08:00/DEADLINE")
        self.assertEqual(sections[7]["title"], "DT WFE")
        self.assertEqual(sections[8]["title"], "DET E KRYERA NE AM")
        self.assertEqual(sections[11]["title"], "GA MBYLLJA E DET")
        self.assertEqual(sections[12]["title"], "HV MBYLLJA E DET")

    def test_empty_confirmation_questions(self) -> None:
        lines = _format_confirmation_questions([])
        self.assertEqual(lines, ["PYETJE PER KONFIRMIM: 0"])

    def test_confirmation_table_includes_category_column(self) -> None:
        lines = _format_confirmation_questions(
            [
                ("PYETJE PËR BARAZIM", "Sa urgjente është?", "Sheno shkallen"),
                ("PYETJET PER 1H", "A eshte bere share detyra tek PX Notes?", ""),
            ]
        )
        joined = "\n".join(lines)
        self.assertIn("Kategoria", joined)
        self.assertIn("PYETJA", joined)
        self.assertIn("PYETJE PËR BARAZIM", joined)
        self.assertIn("PYETJET PER 1H", joined)
        self.assertIn("Sa urgjente është?", joined)
        self.assertIn("A eshte bere share detyra tek PX Notes?", joined)
        self.assertNotIn("LISTA", joined)


class NewSystemTaskRowsTests(unittest.IsolatedAsyncioTestCase):
    async def test_px_note_rows_include_all_and_only_undiscussed_notes(self) -> None:
        included = SimpleNamespace(
            id="included", content="Created before the former M2 window", is_discussed=False,
            created_by=None, created_at=datetime(2026, 8, 11, 9, 0), updated_at=None,
        )
        discussed = SimpleNamespace(
            id="discussed", content="Already discussed", is_discussed=True,
            created_by=None, created_at=datetime(2026, 8, 11, 12, 0), updated_at=None,
        )
        linked = SimpleNamespace(
            id="linked", content="Already linked to a task", is_discussed=False,
            created_by=None, created_at=datetime(2026, 8, 11, 14, 0), updated_at=None,
        )
        mira = SimpleNamespace(**{**included.__dict__, "id": "mira", "from_mira": True,
                                  "mira_shared_to_px": True})
        desktop = SimpleNamespace(**{**included.__dict__, "id": "desktop", "from_mira_desktop": True})

        class FakeResult:
            def __init__(self, values):
                self.values = values

            def scalars(self):
                return SimpleNamespace(all=lambda: self.values)

        class FakeDb:
            def __init__(self):
                self.results = iter([[included, discussed, linked, mira, desktop], [linked.id]])

            async def execute(self, _statement):
                return FakeResult(next(self.results))

        rows = await _blue_note_rows(FakeDb())

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "NO")
        self.assertIn("Created before the former M2 window", rows[0][2])

    async def test_new_system_tasks_include_department_and_finish_period(self) -> None:
        template = SimpleNamespace(
            title="New system task",
            department_id="development",
            finish_period="PM",
            assignee_ids=[],
            default_assignee_id=None,
            created_at=datetime(2026, 8, 11, 9, 0),
        )

        class FakeResult:
            def scalars(self):
                return SimpleNamespace(all=lambda: [template])

        class FakeDb:
            async def execute(self, _statement):
                return FakeResult()

        rows = await _new_system_task_rows(FakeDb(), {"development": "DEV"})

        self.assertEqual(rows, [["1", "-", "DEV", "PM", "New system task", "11.08.2026"]])


class UnfinishedPriorityTaskRowsTests(unittest.TestCase):
    def _task(self, title: str, due_hour: int, **overrides):
        values = {
            "id": title,
            "title": title,
            "due_date": datetime(2026, 8, 24, due_hour, 0, tzinfo=ZoneInfo("Europe/Tirane")),
            "created_at": datetime(2026, 8, 24, 7, 0, tzinfo=ZoneInfo("Europe/Tirane")),
            "completed_at": None,
            "status": "TODO",
            "is_deadline_important": False,
            "finish_period": "AM",
            "assigned_to": None,
            "fast_task_order": None,
            "department_id": None,
            "project_id": None,
            "system_template_origin_id": None,
            "system_task_slot_id": None,
            "is_bllok": False,
            "is_r1": False,
            "is_1h_report": False,
            "is_personal": False,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_includes_only_tasks_unfinished_at_m2_and_deduplicates_both_types(self) -> None:
        timezone = ZoneInfo("Europe/Tirane")
        cutoff = datetime(2026, 8, 24, 13, 20, tzinfo=timezone)
        tasks = [
            self._task("Open deadline", 15, is_deadline_important=True),
            self._task("Open AM/PM deadline", 15, is_deadline_important=True, finish_period="AM/PM"),
            self._task("Open 08:00 title", 2),
            self._task("Open EM title", 2),
            self._task("Both 08:00", 2, is_deadline_important=True),
            self._task("PM deadline", 15, is_deadline_important=True, finish_period="PM"),
            self._task("PM 08:00", 2, finish_period="PM"),
            self._task("No-period deadline", 15, is_deadline_important=True, finish_period=None),
            self._task("Done before 08:00", 2, completed_at=datetime(2026, 8, 24, 13, 19, tzinfo=timezone), status="DONE"),
            self._task("Done after 08:00", 2, completed_at=datetime(2026, 8, 24, 13, 21, tzinfo=timezone), status="DONE"),
            self._task("Due at eight without marker", 8),
            self._task("Not priority", 15),
            self._task("In progress due today", 15, status="IN_PROGRESS"),
            self._task("Waiting confirmation due today", 15, status="WAITING_CONFIRMATION"),
            self._task("Waiting client due today", 15, status="WAITING_CLIENT"),
            self._task("Wrong day 08:00", 2, due_date=datetime(2026, 8, 25, 2, 0, tzinfo=timezone)),
            self._task(
                "Future deadline",
                15,
                is_deadline_important=True,
                start_date=datetime(2026, 8, 24, 8, 0, tzinfo=timezone),
                due_date=datetime(2026, 8, 25, 15, 0, tzinfo=timezone),
            ),
            self._task("Created after 08:00", 2, created_at=datetime(2026, 8, 24, 13, 21, tzinfo=timezone)),
        ]

        rows = _unfinished_priority_task_rows(tasks, {}, {}, date(2026, 8, 24), cutoff, timezone)
        rows_by_title = {row[7]: row for row in rows}

        self.assertEqual(
            set(rows_by_title),
            {
                "Open deadline", "Open AM/PM deadline", "Open 08:00 title", "08:00 Open EM title",
                "Both 08:00", "Done after 08:00", "Due at eight without marker", "Not priority",
                "In progress due today",
            },
        )
        self.assertEqual(rows_by_title["Open deadline"][5], "DEADLINE")
        self.assertEqual(rows_by_title["Open 08:00 title"][5], "08:00")
        self.assertEqual(rows_by_title["08:00 Open EM title"][5], "08:00")
        self.assertEqual(rows_by_title["Both 08:00"][5], "DEADLINE / 08:00")
        self.assertEqual(rows_by_title["Due at eight without marker"][5], "DUE SOT")
        self.assertEqual(rows_by_title["In progress due today"][4], "IN_PROGRESS")
        self.assertEqual(rows_by_title["Done after 08:00"][4], "IN_PROGRESS")
        self.assertEqual(rows_by_title["Done after 08:00"][8], "SOT")
        self.assertEqual(
            [row[5] for row in rows],
            ["08:00", "08:00", "08:00", "DEADLINE / 08:00", "DEADLINE", "DEADLINE", "DUE SOT", "DUE SOT", "DUE SOT"],
        )

    def test_unfinished_rows_show_task_kind_separately_from_due_priority(self) -> None:
        timezone = ZoneInfo("Europe/Tirane")
        tasks = [
            self._task("System", 15, system_template_origin_id="template"),
            self._task("One hour", 15, is_1h_report=True),
            self._task("Blocked", 15, is_bllok=True),
            self._task("Personal", 15, is_personal=True),
            self._task("Project", 15, project_id="project"),
            self._task("Regular fast", 15),
        ]

        rows = _unfinished_priority_task_rows(
            tasks, {}, {}, date(2026, 8, 24),
            datetime(2026, 8, 24, 13, 20, tzinfo=timezone), timezone,
        )
        by_title = {row[7]: row for row in rows}

        self.assertEqual({title: row[6] for title, row in by_title.items()}, {
            "System": "SYS", "One hour": "1H", "Blocked": "BLL",
            "Personal": "P", "Project": "PRJK", "Regular fast": "FT",
        })
        self.assertTrue(all(row[5] == "DUE SOT" for row in rows))
        self.assertTrue(all(len(row) == len(UNFINISHED_PRIORITY_COLUMNS) for row in rows))

    def test_empty_unfinished_priority_section_keeps_the_full_table(self) -> None:
        rows = _ascii_table(
            UNFINISHED_PRIORITY_TABLE_LABEL,
            UNFINISHED_PRIORITY_COLUMNS,
            [],
            show_empty_table=True,
        )

        self.assertIn("DUE DATE", rows[2])
        self.assertIn("TIPI", rows[2])
        self.assertTrue(any("(Asnje detyre)" in row for row in rows))

    def test_08_rows_use_a_border_while_deadlines_keep_the_red_fill(self) -> None:
        html = _render_ascii_table_html(
            [
                "| NR | LLOJI | TITULLI |",
                "| 1 | DEADLINE | Deadline task |",
                "| 2 | DEADLINE / 08:00 | Both task |",
                "| 3 | 08:00 | Eight task |",
            ]
        )

        self.assertEqual(html.count('class="eight-am"'), 2)
        self.assertEqual(html.count('class="deadline"'), 1)
        self.assertLess(html.index("Eight task"), html.index("Both task"))
        self.assertLess(html.index("Both task"), html.index("Deadline task"))

    def test_due_today_rows_keep_status_color_while_priority_rows_keep_priority_style(self) -> None:
        lines = _ascii_table(
            UNFINISHED_PRIORITY_TABLE_LABEL,
            UNFINISHED_PRIORITY_COLUMNS,
            [
                ["1", "EF", "DEV", "AM", "TODO", "08:00", "1H", "Eight task", "SOT"],
                ["2", "RA", "DEV", "AM/PM", "IN_PROGRESS", "DEADLINE", "BLL", "Deadline task", "SOT"],
                ["3", "DV", "PCM", "AM", "TODO", "DUE SOT", "P", "Due task", "SOT"],
            ],
            show_empty_table=True,
        )

        html = _render_ascii_table_html(lines)

        self.assertEqual(html.count('class="eight-am"'), 1)
        self.assertEqual(html.count('class="deadline"'), 1)
        self.assertEqual(html.count('class="todo"'), 1)
        self.assertIn("DUE DATE", html)
        self.assertIn("SOT", html)


class DoneAmTaskRowsTests(unittest.TestCase):
    def _task(self, title: str, completed_at: datetime, **overrides):
        values = {
            "id": title,
            "title": title,
            "completed_at": completed_at,
            "status": "DONE",
            "assigned_to": "user-1",
            "fast_task_order": None,
            "is_deadline_important": False,
            "created_at": datetime(2026, 8, 24, 7, 0, tzinfo=ZoneInfo("Europe/Tirane")),
            "department_id": "development",
            "finish_period": "AM",
            "system_template_origin_id": None,
            "system_task_slot_id": None,
            "project_id": None,
            "is_bllok": False,
            "is_r1": False,
            "is_1h_report": False,
            "is_personal": False,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_includes_only_current_done_tasks_completed_before_noon_on_report_day(self) -> None:
        timezone = ZoneInfo("Europe/Tirane")
        tasks = [
            self._task("First done", datetime(2026, 8, 24, 8, 30, tzinfo=timezone)),
            self._task("Last done", datetime(2026, 8, 24, 11, 58, tzinfo=timezone), finish_period="PM"),
            self._task("System done", datetime(2026, 8, 24, 11, 59, tzinfo=timezone), system_template_origin_id="template-1"),
            self._task("Legacy system done", datetime(2026, 8, 24, 11, 57, tzinfo=timezone), system_task_slot_id="slot-1"),
            self._task("At noon", datetime(2026, 8, 24, 12, 0, tzinfo=timezone)),
            self._task("Afternoon", datetime(2026, 8, 24, 15, 0, tzinfo=timezone)),
            self._task("Wrong day", datetime(2026, 8, 23, 10, 0, tzinfo=timezone)),
            self._task("Reopened", datetime(2026, 8, 24, 9, 0, tzinfo=timezone), status="TODO"),
        ]

        rows = _done_am_task_rows(
            tasks,
            {"user-1": "Example User"},
            {},
            date(2026, 8, 24),
            timezone,
            {"development": "DEV"},
        )

        self.assertEqual([row[5] for row in rows], ["First done", "Last done"])
        self.assertEqual(rows[0], ["1", "EU", "DEV", "AM", "FT", "First done"])
        self.assertEqual(rows[1][3:5], ["PM", "FT"])

    def test_completed_am_table_uses_done_green_tone(self) -> None:
        self.assertEqual(_table_tone_from_label("DET E KRYERA NE AM:"), "done")

    def test_completed_am_table_prioritizes_shared_user_order_over_completion_time(self) -> None:
        timezone = ZoneInfo("Europe/Tirane")
        later_but_first_user = self._task(
            "First user",
            datetime(2026, 8, 24, 11, 30, tzinfo=timezone),
            _weekly_planner_report_sort=(0, "dev", 0, 0, "AT"),
        )
        earlier_but_second_user = self._task(
            "Second user",
            datetime(2026, 8, 24, 8, 15, tzinfo=timezone),
            _weekly_planner_report_sort=(0, "dev", 0, 1, "EF"),
        )

        rows = _done_am_task_rows(
            [earlier_but_second_user, later_but_first_user],
            {"user-1": "Example User"},
            {},
            date(2026, 8, 24),
            timezone,
            {"development": "DEV"},
        )

        self.assertEqual([row[5] for row in rows], ["First user", "Second user"])


class WaitingClientTaskRowsTests(unittest.TestCase):
    @staticmethod
    def _task(title: str, status: str, **overrides):
        values = {
            "id": title,
            "title": title,
            "status": status,
            "assigned_to": "user-1",
            "fast_task_order": None,
            "is_deadline_important": False,
            "created_at": datetime(2026, 8, 24, 7, 0),
            "department_id": "development",
            "finish_period": "AM",
            "system_template_origin_id": None,
            "project_id": None,
            "is_bllok": False,
            "is_r1": False,
            "is_1h_report": False,
            "is_personal": False,
            "start_date": datetime(2026, 8, 24, 7, 0),
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_dt_wfe_includes_only_waiting_client_tasks(self) -> None:
        rows = _waiting_client_task_rows(
            [
                self._task("Waiting task", "WAITING_CLIENT"),
                self._task("In progress task", "IN_PROGRESS"),
                self._task(
                    "Waiting task two",
                    " waiting_client ",
                    finish_period="PM",
                    created_at=datetime(2026, 8, 17, 7, 0),
                    start_date=datetime(2026, 8, 17, 7, 0),
                ),
            ],
            {"user-1": "Example User"},
            {},
            date(2026, 8, 24),
            {"development": "DEV"},
        )

        self.assertEqual([row[6] for row in rows], ["Waiting task", "Waiting task two"])
        self.assertEqual(rows[0], ["1", "EU", "DEV", "Pa date", "AM", "FT", "Waiting task"])
        self.assertEqual(rows[1][3], "Pa date")
        self.assertEqual(rows[1][4], "PM")

    def test_dt_wfe_age_cells_use_blue_and_yellow_tones(self) -> None:
        lines = [
            "DT WFE:",
            "+----+---------+----------+",
            "| NR | WFE NGA  | TITULLI  |",
            "+----+---------+----------+",
            "| 1  | Sot     | Current  |",
            "+----+---------+----------+",
            "| 2  | Dje     | Previous |",
            "+----+---------+----------+",
        ]

        rendered = _render_ascii_table_html(lines, "waiting-client")

        self.assertIn('class="created-this-week"', rendered)
        self.assertIn('bgcolor="#bae6fd"', rendered)
        self.assertIn('class="created-last-week"', rendered)
        self.assertIn('bgcolor="#fde68a"', rendered)

    def test_dt_wfe_age_uses_entry_date_and_local_calendar_day(self) -> None:
        rows = _waiting_client_task_rows(
            [
                self._task(
                    "Created earlier but starts this week",
                    "WAITING_CLIENT",
                    created_at=datetime(2026, 7, 1, 7, 0),
                    start_date=datetime(2026, 8, 25, 7, 0),
                ),
                self._task(
                    "Created this week but started last week",
                    "WAITING_CLIENT",
                    created_at=datetime(2026, 8, 24, 7, 0),
                    start_date=datetime(2026, 8, 20, 7, 0),
                ),
                self._task(
                    "Older start",
                    "WAITING_CLIENT",
                    start_date=datetime(2026, 8, 10, 7, 0),
                ),
                self._task("No start", "WAITING_CLIENT", start_date=None),
                self._task(
                    "Future start",
                    "WAITING_CLIENT",
                    start_date=datetime(2026, 8, 31, 7, 0),
                ),
            ],
            {"user-1": "Example User"},
            {},
            date(2026, 8, 24),
            {"development": "DEV"},
            entry_dates={
                "Created earlier but starts this week": datetime(2026, 8, 24, 8, 0),
                "Created this week but started last week": datetime(2026, 8, 23, 8, 0),
                "Older start": datetime(2026, 8, 22, 8, 0),
                # 22:30 UTC is already the next calendar day in Tirane.
                "Future start": datetime(2026, 8, 23, 22, 30, tzinfo=ZoneInfo("UTC")),
            },
        )

        buckets_by_title = {row[6]: row[3] for row in rows}
        self.assertEqual(buckets_by_title["Created earlier but starts this week"], "Sot")
        self.assertEqual(buckets_by_title["Created this week but started last week"], "Dje")
        self.assertEqual(buckets_by_title["Older start"], "22.08")
        self.assertEqual(buckets_by_title["No start"], "Pa date")
        self.assertEqual(buckets_by_title["Future start"], "Sot")

    def test_entry_after_report_day_is_unknown_instead_of_future(self) -> None:
        rows = _waiting_client_task_rows(
            [self._task("Later entry", "WAITING_CLIENT")], {}, {}, date(2026, 8, 24),
            entry_dates={"Later entry": datetime(2026, 8, 25, 8, 0)},
        )
        self.assertEqual(rows[0][3], "Pa date")

    def test_dt_wfe_sorts_departments_then_users_by_weekly_planner_order(self) -> None:
        tasks = [
            self._task("PCM second", "WAITING_CLIENT", _weekly_planner_report_sort=(2, "pcm", 0, 2, "dv")),
            self._task("DEV second", "WAITING_CLIENT", _weekly_planner_report_sort=(0, "dev", 0, 2, "ra")),
            self._task("GD first", "WAITING_CLIENT", _weekly_planner_report_sort=(1, "gd", 0, 1, "fg")),
            self._task("PCM first", "WAITING_CLIENT", _weekly_planner_report_sort=(2, "pcm", 0, 1, "oh")),
            self._task("DEV first", "WAITING_CLIENT", _weekly_planner_report_sort=(0, "dev", 0, 1, "eh")),
        ]

        rows = _waiting_client_task_rows(
            tasks,
            {"user-1": "Example User"},
            {},
            date(2026, 8, 24),
            {"development": "DEV"},
        )

        self.assertEqual(
            [row[6] for row in rows],
            ["DEV first", "DEV second", "GD first", "PCM first", "PCM second"],
        )

    def test_dt_wfe_uses_waiting_client_gold_tone(self) -> None:
        self.assertEqual(_table_tone_from_label("DT WFE:"), "waiting-client")

    def test_dt_wfe_sorts_by_full_entry_date_newest_first_unknown_last(self) -> None:
        entry_dates = {
            "Today": datetime(2026, 9, 18, 8, 0),
            "Yesterday": datetime(2026, 9, 17, 8, 0),
            "Previous month": datetime(2026, 8, 31, 8, 0),
            "Previous year": datetime(2025, 12, 31, 8, 0),
            "This month": datetime(2026, 9, 4, 8, 0),
        }
        tasks = [self._task(title, "WAITING_CLIENT") for title in ["Unknown", *entry_dates]]
        rows = _waiting_client_task_rows(
            tasks, {}, {}, date(2026, 9, 18), entry_dates=entry_dates,
        )
        self.assertEqual([row[6] for row in rows], [
            "Today", "Yesterday", "This month", "Previous month", "Previous year", "Unknown",
        ])
        self.assertEqual([row[0] for row in rows], ["1", "2", "3", "4", "5", "6"])


class WaitingClientEntryDatesTests(unittest.IsolatedAsyncioTestCase):
    async def test_latest_entry_ignores_edits_and_supports_both_audit_formats(self) -> None:
        def event(task_id, day, before, after, action="updated"):
            return SimpleNamespace(
                entity_id=task_id, created_at=datetime(2026, 8, day, 10, 0),
                before=before, after=after, action=action,
            )

        events = [
            event("reentered", 24, {"status": "WAITING_CLIENT"}, {"status": "WAITING_CLIENT"}),
            event("semantic", 24, {"field": "status", "value": "DONE"},
                  {"field": "status", "value": "WAITING_CLIENT"}, "task.reopened"),
            event("reentered", 23, {"status": "TODO"}, {"status": "WFE"}),
            event("created", 22, None, {"status": "WAITING_CLIENT"}, "created"),
            event("unknown", 22, {"status": "WFE"}, {"status": "WAITING_CLIENT"}),
            event("reentered", 21, {"status": "WAITING_CLIENT"}, {"status": "TODO"}),
            event("reentered", 20, {"status": "TODO"}, {"status": "WAITING_CLIENT"}),
        ]

        class FakeDb:
            async def execute(self, statement):
                return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: events))

        tasks = [SimpleNamespace(id=key, status="WAITING_CLIENT")
                 for key in ("reentered", "semantic", "created", "unknown")]
        dates = await _waiting_client_entry_dates(FakeDb(), tasks)
        self.assertEqual(dates, {
            "reentered": datetime(2026, 8, 23, 10, 0),
            "semantic": datetime(2026, 8, 24, 10, 0),
            "created": datetime(2026, 8, 22, 10, 0),
        })

    async def test_no_waiting_tasks_does_not_query_history(self) -> None:
        dates = await _waiting_client_entry_dates(None, [SimpleNamespace(id="done", status="DONE")])
        self.assertEqual(dates, {})


class UnheldMeetingRowsTests(unittest.TestCase):
    def test_includes_unmarked_and_canceled_internal_external_meetings(self) -> None:
        timezone = ZoneInfo("Europe/Tirane")
        meetings = [
            SimpleNamespace(id="held", title="Held", starts_at=datetime(2026, 8, 24, 9, 0, tzinfo=timezone), meeting_type="internal"),
            SimpleNamespace(id="unmarked", title="Unmarked", starts_at=datetime(2026, 8, 24, 10, 0, tzinfo=timezone), meeting_type="external"),
            SimpleNamespace(id="canceled", title="Canceled", starts_at=datetime(2026, 8, 24, 11, 0, tzinfo=timezone), meeting_type="internal"),
            SimpleNamespace(id="afternoon", title="Afternoon", starts_at=datetime(2026, 8, 24, 13, 15, tzinfo=timezone), meeting_type="internal"),
        ]

        lines, count = _unheld_meeting_section(
            meetings,
            {"held": "held", "canceled": "canceled"},
        )

        body = "\n".join(lines)
        self.assertEqual(count, 2)
        self.assertIn("TAK EXTERNE", body)
        self.assertIn("TAK INTERNE", body)
        self.assertIn("MBAJTUR?", body)
        self.assertIn("Unmarked", body)
        self.assertIn("Canceled", body)
        self.assertNotIn("Held", body)
        self.assertNotIn("Afternoon", body)

    def test_m2_linked_internal_meeting_inherits_external_color(self) -> None:
        timezone = ZoneInfo("Europe/Tirane")
        external = SimpleNamespace(
            id="external",
            title="External weekly",
            starts_at=datetime(2026, 8, 24, 10, 30, tzinfo=timezone),
            meeting_type="external",
            recurrence_type="weekly",
            calendar_categories=["Brown"],
            calendar_imported=True,
            microsoft_event_id="calendar-event",
            paired_external_meeting_id=None,
            pre_external_meeting_id=None,
        )
        linked_internal = SimpleNamespace(
            id="linked",
            title="Internal before external",
            starts_at=datetime(2026, 8, 24, 8, 15, tzinfo=timezone),
            meeting_type="internal",
            recurrence_type="weekly",
            calendar_categories=[],
            calendar_imported=False,
            microsoft_event_id=None,
            paired_external_meeting_id="external",
            pre_external_meeting_id=None,
        )
        manual_internal = SimpleNamespace(
            id="manual",
            title="Manual internal",
            starts_at=datetime(2026, 8, 24, 8, 30, tzinfo=timezone),
            meeting_type="internal",
            recurrence_type="weekly",
            calendar_categories=[],
            calendar_imported=False,
            microsoft_event_id=None,
            paired_external_meeting_id=None,
            pre_external_meeting_id=None,
        )

        lines, _ = _unheld_meeting_section(
            [external, linked_internal, manual_internal],
            {},
            [external, linked_internal, manual_internal],
        )

        body = "\n".join(lines)
        self.assertIn("[CAL] Internal before external [[mc:meeting-brown]]", body)
        self.assertIn("[MANUAL] Manual internal [[mc:meeting-manual]]", body)
        html = _render_ascii_table_html(lines)
        self.assertIn('bgcolor="#C9A98A"', html)
        self.assertIn('bgcolor="#FFF4CC"', html)


if __name__ == "__main__":
    unittest.main()
