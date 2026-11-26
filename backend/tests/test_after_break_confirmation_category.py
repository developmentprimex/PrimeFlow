import asyncio
import uuid
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from app.services.after_break_report import (
    DISPLAY_SECTION_TITLES,
    NEW_EMAILS_TITLE,
    PCM_PROJECTS_TITLE,
    SECTION_TITLES,
    UNFINISHED_PRIORITY_COLUMNS,
    UNFINISHED_PRIORITY_TABLE_LABEL,
    M2_PRIORITY_PROGRESS_TITLE,
    _ascii_table,
    _append_unfinished_priority_explanations,
    _new_emails_report_body,
    load_blue_notes,
    _format_confirmation_questions,
    _done_am_task_rows,
    _new_system_task_rows,
    _pcm_projects_summary,
    _unheld_meeting_section,
    _unfinished_priority_task_rows,
    _waiting_client_task_rows,
    _waiting_client_entry_dates,
    normalize_after_break_report_sections,
    render_html,
    render_plain_text,
)
from app.services.meetings_report import _render_ascii_table_html, _table_tone_from_label
from app.services.meeting_point_manual_sync import is_known_report_title, merge_common_view_manual_sections, section_group_label, with_section_keys
from app.services.discord_ga_replies import GA_REPLIES_SECTION_TITLE
from app.services.discord_ga_reactions import GA_REACTIONS_SECTION_TITLE


class AfterBreakConfirmationCategoryTests(unittest.TestCase):
    def test_hv_postponements_have_one_automatic_m2_section_and_show_each_date(self):
        from app.services.after_break_report import (
            HV_GA_POSTPONED_TITLE, _hv_ga_postponements_body,
        )
        from app.models.task import Task

        def event(task, field, before, after, **metadata):
            return task, SimpleNamespace(id=uuid.uuid4(), entity_id=task.id, action=f"task.{field}_changed",
                                         created_at=datetime(2026, 11, 26, 11),
                                         before={"value": before}, after={"value": after, **metadata})

        both = Task(id=uuid.uuid4(), title="Raporti | i stokut", status="TODO", assigned_to="hv")
        single = Task(id=uuid.uuid4(), title="Vetëm afati", status="IN_PROGRESS", assigned_to="hv")
        excluded = Task(id=uuid.uuid4(), title="Afati u afrua", status="TODO", assigned_to="hv")
        body, count = _hv_ga_postponements_body([
            event(both, "start_date", "2026-11-26", "2026-11-27"),
            event(both, "due_date", "2026-11-27", "2026-11-30", reason="Tjetër", comment="Biseduar | me GA"),
            event(single, "due_date", "2026-11-26", "2026-11-27"),
            event(excluded, "due_date", "2026-11-30", "2026-11-27"),
        ], names={"hv": "Haxhere Spahiu"})
        self.assertEqual(count, 2)
        first, second = body.split("SHTYER START OSE DUE DATE:")
        self.assertIn("SHTYER START DHE DUE DATE", first)
        self.assertIn("Raporti ¦ i stokut", first)
        self.assertIn("START: 26.11.2026 / DUE: 27.11.2026", first)
        self.assertIn("START: 27.11.2026 / DUE: 30.11.2026", first)
        self.assertIn("Vetëm afati", second)
        sections = normalize_after_break_report_sections([])
        point = [section for section in sections if section["section_key"] == HV_GA_POSTPONED_TITLE]
        self.assertEqual(len(point), 1)
        self.assertEqual(section_group_label("after_break", point[0]["title"]), "AUTO-FILLED FROM PRIMEFLOW")
        point[0]["body"] = body
        day = date(2026, 11, 26)
        for output in (render_html("M2", day, sections), render_plain_text("M2", day, sections)):
            self.assertIn("Raporti ¦ i stokut", output)
            self.assertIn("30.11.2026", output)
            self.assertIn("Biseduar ¦ me GA", output)
            self.assertNotIn("Afati u afrua", output)

    def test_m2_replaces_the_old_manual_email_point_in_saved_drafts(self) -> None:
        old_title = "DET NGA EMAIL/ PX INFO & ZHVILLIM"
        sections = normalize_after_break_report_sections([
            {"title": old_title, "body": "Old email answer"},
            {"title": "PIKAT TEK GR. PX RLZ DITOR & JAVOR", "body": "Keep this answer"},
        ])
        self.assertNotIn(old_title, [section["title"] for section in sections])
        self.assertEqual(sections[0]["body"], "Keep this answer")
        self.assertEqual(sections[1]["title"], "(GA) EMAILS TE REJA?")
        self.assertEqual(section_group_label("after_break", sections[1]["title"]), "AUTO-FILLED FROM PRIMEFLOW")

    def test_m2_email_window_uses_exact_received_timestamp(self) -> None:
        from app.services.after_break_report import load_new_email_mailboxes

        def message(subject, received):
            return {"subject": subject, "received_datetime": received}

        messages = [
            message("Before 08:00", "2026-11-24T06:59:59+00:00"),
            message("At 08:00", "2026-11-24T08:00:00+01:00"),
            message("At generation", "2026-11-24T10:23:45.123+01:00"),
            message("After generation", "2026-11-24T10:23:45.124+01:00"),
            message("Previous day", "2026-11-23T11:00:00+01:00"),
        ]
        with patch("app.services.after_break_report.read_report_inbox", AsyncMock(return_value={
            "configured": True, "connected": True, "messages": messages,
        })):
            mailboxes = asyncio.run(load_new_email_mailboxes(
                date(2026, 11, 24), datetime.fromisoformat("2026-11-24T09:23:45.123+00:00"),
            ))
        self.assertEqual(set(mailboxes), {"info-px", "it", "hf", "px-eu"})
        for mailbox in mailboxes.values():
            self.assertEqual([item["subject"] for item in mailbox["messages"]], ["At 08:00", "At generation"])

    def test_m2_email_table_is_preserved_in_report_outputs(self) -> None:
        generated = datetime.fromisoformat("2026-11-24T10:23:45+01:00")
        body = _new_emails_report_body({"info-px": {"configured": True, "connected": True, "messages": [
            {"subject": "New invoice", "sender": "Finance", "received_at": "09:15", "body": "Private message body"},
        ]}}, generated.date(), generated)
        sections = normalize_after_break_report_sections([{
            "title": NEW_EMAILS_TITLE, "section_key": NEW_EMAILS_TITLE, "body": body,
        }])
        for output in (render_html("M2", generated.date(), sections), render_plain_text("M2", generated.date(), sections)):
            self.assertIn(NEW_EMAILS_TITLE, output)
            self.assertIn("New invoice", output)
            self.assertIn("09:15", output)
            self.assertNotIn("Private message body", output)

    def test_dt_wfe_draft_duplicates_and_manual_keys_stay_in_one_automatic_section(self) -> None:
        saved = [
            {"title": "DT WFE", "body": "Original table"},
            {"title": "DT WFE", "body": "Duplicate generated table"},
            {"title": "3. DT WFE", "section_key": "manual:custom:3:legacy", "body": "Duplicate manual table"},
        ]
        sections = normalize_after_break_report_sections(saved)
        with patch("app.services.meeting_point_manual_sync.load_common_view_extra_titles",
                   new=AsyncMock(return_value=["3. DT WFE", "Other manual point"])):
            sections = asyncio.run(merge_common_view_manual_sections(None, sections, "after_break", saved))
        waiting = [section for section in sections if "DT WFE" in section["title"]]
        self.assertEqual(waiting, [{"title": "DT WFE", "section_key": "DT WFE", "body": "Original table"}])
        self.assertEqual(section_group_label("after_break", "DT WFE", "manual:DTWFE"), "AUTO-FILLED FROM PRIMEFLOW")
        self.assertEqual(sections[sections.index(waiting[0]) - 1]["title"], M2_PRIORITY_PROGRESS_TITLE)
        self.assertIn("Other manual point", [section["title"] for section in sections])

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
            [section["section_key"] for section in sections],
            DISPLAY_SECTION_TITLES,
        )
        automatic = [section["title"] for section in sections
                     if section_group_label("after_break", section["title"], section["section_key"]) == "AUTO-FILLED FROM PRIMEFLOW"]
        self.assertEqual(automatic[:4], [NEW_EMAILS_TITLE, GA_REPLIES_SECTION_TITLE, GA_REACTIONS_SECTION_TITLE, PCM_PROJECTS_TITLE])
        self.assertEqual(automatic[4:9], ["NOTES TE REJA ( NOT DISSCUSED)", "TAK INT/EXT TE PAMBAJTURA",
                                        M2_PRIORITY_PROGRESS_TITLE, "DT WFE", "DET E KRYERA NE AM"])
        self.assertEqual(automatic[-3:], ["GA MBYLLJA E DET", "HV MBYLLJA E DET", "DET TE SHTYERA TE HV ME GA"])

    def test_pcm_projects_use_title_codes_on_tasks_covering_the_report_day(self) -> None:
        def task(title, start, due, project_id=None):
            return SimpleNamespace(title=title, start_date=start, due_date=due, project_id=project_id)

        day = date(2026, 11, 18)
        tasks = [task("vs/vl/mst: Produkte", date(2026, 11, 17), day),
                 task("TT - Përditësim", day, date(2026, 11, 19)),
                 task("MST: Nesër", date(2026, 11, 19), date(2026, 11, 20), project_id="project"),
                 task("MSTUDIO", day, day, project_id="project"), task("MST pa afat", day, None, project_id="project")]
        self.assertEqual(_pcm_projects_summary(tasks, day), "VS - PO\nVL - PO\nMST - JO\nTT - JO")
        tasks.append(task("MST / TT - Përditësim", day, day, project_id="project"))
        self.assertEqual(_pcm_projects_summary(tasks, day), "VS - PO\nVL - PO\nMST - PO\nTT - PO")

        sections = normalize_after_break_report_sections([
            {"title": PCM_PROJECTS_TITLE, "section_key": PCM_PROJECTS_TITLE, "body": "(Ploteso manualisht)"},
        ])
        projects = [section for section in sections if section["section_key"] == PCM_PROJECTS_TITLE]
        self.assertEqual([section["body"] for section in projects], [""])
        self.assertEqual(section_group_label("after_break", PCM_PROJECTS_TITLE), "AUTO-FILLED FROM PRIMEFLOW")

    def test_m2_ga_reply_is_automatic_without_reimporting_the_manual_question(self) -> None:
        legacy = {"title": f"3. {GA_REPLIES_SECTION_TITLE}", "section_key": "manual:custom:3:ga", "body": "Old manual answer"}
        sections = normalize_after_break_report_sections([legacy])
        with patch("app.services.meeting_point_manual_sync.load_common_view_extra_titles",
                   AsyncMock(return_value=[GA_REPLIES_SECTION_TITLE])):
            merged = asyncio.run(merge_common_view_manual_sections(None, sections, "after_break", [legacy], [legacy]))
        point = [section for section in merged if section["title"] == GA_REPLIES_SECTION_TITLE]
        self.assertEqual(len(point), 1)
        self.assertEqual(section_group_label("after_break", point[0]["title"], point[0]["section_key"]), "AUTO-FILLED FROM PRIMEFLOW")
        self.assertNotIn("Old manual answer", render_html("M2", date(2026, 11, 18), merged))

    def test_retired_m2_questions_do_not_return_from_saved_drafts_or_common_view(self) -> None:
        plan_title, board_title = SECTION_TITLES[2:4]
        retired = [
            {"title": "Edited plan question", "section_key": plan_title, "body": "Old plan answer"},
            {"title": f"6. {board_title}", "section_key": "manual:custom:6:board", "body": "Old board answer"},
        ]
        sections = normalize_after_break_report_sections(retired)
        self.assertEqual([section["section_key"] for section in sections], DISPLAY_SECTION_TITLES)
        self.assertTrue(is_known_report_title("after_break", plan_title))
        self.assertTrue(is_known_report_title("after_break", board_title))
        self.assertFalse(is_known_report_title("morning", plan_title))
        with patch("app.services.meeting_point_manual_sync.load_common_view_extra_titles",
                   AsyncMock(return_value=[plan_title, board_title, "Another question"])):
            merged = asyncio.run(merge_common_view_manual_sections(None, sections, "after_break", retired, retired))
        expected_titles = [section["title"] for section in sections]
        self.assertEqual([section["title"] for section in merged], ["Another question", *expected_titles])
        html = render_html("M2", date(2026, 11, 18), merged)
        for removed in (plan_title, board_title, "Old plan answer", "Old board answer"):
            self.assertNotIn(removed, html)

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

        rows = [values for _, values in await load_blue_notes(FakeDb())]

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

    def test_m2_priority_progress_covers_the_planned_range_and_keeps_due_today_work(self) -> None:
        timezone = ZoneInfo("Europe/Tirane")
        day = date(2026, 8, 24)
        cutoff = datetime(2026, 8, 24, 13, 20, tzinfo=timezone)
        due = datetime(2026, 8, 26, 9, 0, tzinfo=timezone)
        start = datetime(2026, 8, 23, 9, 0, tzinfo=timezone)
        tasks = [
            self._task("08:00 Active", 9, start_date=start, due_date=due, status="IN_PROGRESS", progress_percentage=45),
            self._task("Important AM", 9, start_date=start, due_date=due, is_deadline_important=True),
            self._task("Important PM", 9, start_date=start, due_date=due, is_deadline_important=True, finish_period="PM"),
            self._task("08:00 Done", 9, start_date=start, status="DONE", completed_at=cutoff),
            self._task("08:00 Later", 9, start_date=due, due_date=due),
            self._task("Ordinary due today", 9),
        ]
        rows = _unfinished_priority_task_rows(tasks, {}, {}, day, cutoff, timezone, include_morning_progress=True)
        by_title = {row[7]: row for row in rows}
        self.assertEqual(set(by_title), {"08:00 Active", "Important AM", "08:00 Done", "Ordinary due today"})
        self.assertEqual(by_title["08:00 Active"][8:], ["26.08.2026", "IN PROGRESS"])
        self.assertEqual(by_title["08:00 Done"][9], "DONE")
        self.assertEqual(by_title["Ordinary due today"][8:], ["SOT", "TODO"])

    def test_m2_priority_table_renames_old_draft_labels_and_keeps_its_key(self) -> None:
        legacy = UNFINISHED_PRIORITY_TABLE_LABEL
        sections = normalize_after_break_report_sections([{"title": legacy, "body": f"{legacy}: 0"}])
        section = next(item for item in sections if item["section_key"] == legacy)
        self.assertEqual(section["title"], M2_PRIORITY_PROGRESS_TITLE)
        self.assertTrue(section["body"].startswith(f"{M2_PRIORITY_PROGRESS_TITLE}:"))
        self.assertIn(M2_PRIORITY_PROGRESS_TITLE, render_html("M2", date(2026, 8, 24), [section]))

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
        self.assertTrue(all(len(row) == len(UNFINISHED_PRIORITY_COLUMNS) - 2 for row in rows))

    def test_unfinished_priority_explanations_match_task_id_and_report_date(self) -> None:
        day = date(2026, 8, 24)
        first = SimpleNamespace(id="first")
        second = SimpleNamespace(id="second")
        columns = ["1", "EF", "DEV", "AM", "TODO", "DUE SOT", "FT", "Same title", "SOT"]
        rows = [[*columns, first.id], [*columns, second.id]]
        states = SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: [
                SimpleNamespace(task_id=second.id, user_id="ef", reason_code="OTHER", comment="Check | details"),
            ]),
        )
        notes = SimpleNamespace(all=lambda: [(first.id, "ef", {"comment": "Discord note"})])
        db = SimpleNamespace(execute=AsyncMock(side_effect=[states, notes]))
        result = asyncio.run(_append_unfinished_priority_explanations(
            db, rows, [first, second], day, {"ef": "Eva First"}, {},
            overrides={first.id: {"reason": "Manual reason"}},
        ))
        self.assertEqual(result[0], [*columns, "Manual reason", "EF: Discord note"])
        self.assertEqual(result[1], [*columns, "Tjetër", "Check ¦ details"])
        self.assertIn(day, db.execute.await_args_list[0].args[0].compile().params.values())
        self.assertIn(day.isoformat(), db.execute.await_args_list[1].args[0].compile().params.values())

    def test_m2_keeps_manual_and_discord_1h_comments_in_separate_cells(self) -> None:
        day = date(2026, 8, 24)
        first = SimpleNamespace(id="first")
        second = SimpleNamespace(id="second")
        columns = ["1", "EF", "DEV", "AM", "IN_PROGRESS", "08:00", "FT", "Same title", "SOT", "IN PROGRESS"]
        rows = [[*columns, first.id], [*columns, second.id]]
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [])))
        from app.services import after_break_report as service

        with patch.object(service, "_daily_rlz_values_by_task", AsyncMock(return_value={})), \
             patch.object(service, "load_follow_up_comments", AsyncMock(return_value={
                 "11:50": {first.id: "EF: Afati | mbetet hapur"},
                 "11:00": {first.id: "EF: Sot 45%"},
             })) as load_comments:
            result = asyncio.run(_append_unfinished_priority_explanations(
                db, rows, [first, second], day, {"ef": "Eva First"}, {},
                overrides={first.id: {"comment": "Manual M2"}}, include_morning_progress=True,
            ))
        self.assertEqual(result[0][-3:], ["-", "Manual M2", "11:00: EF: Sot 45% / 11:50: EF: Afati ¦ mbetet hapur"])
        self.assertEqual(result[1][-1], "-")
        load_comments.assert_awaited_once_with(db, day, service.FOLLOW_UP_BY_SLOT)
        body = "\n".join(service._ascii_table(
            service.UNFINISHED_PRIORITY_TABLE_LABEL, service.M2_PRIORITY_PROGRESS_COLUMNS, result,
        ))
        rendered = service.render_html("M2", day, [{"title": service.UNFINISHED_PRIORITY_TABLE_LABEL, "body": body}])
        for text in ("PROGRESI", "DISCORD 1H", "IN PROGRESS", "Manual M2", "EF: Sot 45%",
                     'bgcolor="#fef3c7"', "border-top:3px solid #dc2626", 'bgcolor="#DC2626"'):
            self.assertIn(text, rendered)

    def test_only_confirmed_continuations_without_another_m2_explanation_are_folded(self):
        from app.services import after_break_report as service

        day = date(2026, 8, 24)
        tasks = [SimpleNamespace(id=task_id) for task_id in ("continued", "blocked", "unconfirmed")]
        columns = ["1", "EF", "DEV", "AM", "IN_PROGRESS", "08:00", "FT", "Title", "SOT", "IN PROGRESS"]
        rows = [[*columns, task.id] for task in tasks]
        notes = SimpleNamespace(all=lambda: [
            ("continued", "ef", {"comment": "Ka vazhduar.", "continued": True}),
            ("blocked", "ef", {"comment": "Ka vazhduar.", "continued": True}),
            ("blocked", "ef", {"comment": "Pres QA."}),
        ])
        db = SimpleNamespace(execute=AsyncMock(return_value=notes))
        explanations = []
        with patch.object(service, "_daily_rlz_values_by_task", AsyncMock(return_value={})), \
             patch.object(service, "load_follow_up_comments", AsyncMock(return_value={})):
            result = asyncio.run(_append_unfinished_priority_explanations(
                db, rows, tasks, day, {"ef": "Eva First"}, {},
                explanation_rows=explanations, include_morning_progress=True,
            ))
        self.assertEqual([row["continued_only"] for row in explanations], [True, False, False])
        self.assertEqual(result[0][-2], "EF: Ka vazhduar.")
        self.assertIn("EF: Pres QA.", result[1][-2])

    def test_m2_manual_explanation_patch_preserves_other_saved_fields(self) -> None:
        from app.api.routers import after_break_report as api
        from app.services.after_break_report import UNFINISHED_EXPLANATION_OVERRIDES

        task_id = uuid.uuid4()
        row = SimpleNamespace(
            report_date=date(2026, 8, 24), status="DRAFT",
            generated_snapshot={"existing": True, UNFINISHED_EXPLANATION_OVERRIDES: {
                str(task_id): {"comment": "Saved comment"},
            }},
        )
        db = SimpleNamespace(get=AsyncMock(return_value=row), commit=AsyncMock(), refresh=AsyncMock())
        with patch.object(api, "build_unfinished_priority_task_rows", AsyncMock(return_value=[[str(task_id)]])), \
             patch.object(api, "_draft_with_questions", AsyncMock(return_value={})):
            asyncio.run(api.update_draft(
                uuid.uuid4(),
                api.DraftUpdate(unfinished_explanations={task_id: api.TaskExplanationUpdate(reason="Manual reason")}),
                db, SimpleNamespace(id=uuid.uuid4()),
            ))
        self.assertEqual(row.generated_snapshot, {
            "existing": True, UNFINISHED_EXPLANATION_OVERRIDES: {
                str(task_id): {"comment": "Saved comment", "reason": "Manual reason"},
            },
        })
        db.commit.assert_awaited_once()

    def test_empty_unfinished_priority_section_keeps_the_full_table(self) -> None:
        rows = _ascii_table(
            UNFINISHED_PRIORITY_TABLE_LABEL,
            UNFINISHED_PRIORITY_COLUMNS,
            [],
            show_empty_table=True,
        )

        self.assertIn("DUE DATE", rows[2])
        self.assertIn("TIPI", rows[2])
        self.assertIn("ARSYEJA", rows[2])
        self.assertIn("KOMENT", rows[2])
        self.assertEqual(rows[4].split("|")[8].strip(), "(Asnje detyre)")

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
