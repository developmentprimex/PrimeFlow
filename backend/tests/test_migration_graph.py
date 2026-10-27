from pathlib import Path
from io import StringIO
import unittest
from unittest.mock import patch
import warnings

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import sqlalchemy as sa


def migration_scripts() -> ScriptDirectory:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    return ScriptDirectory.from_config(config)


class MigrationGraphTests(unittest.TestCase):
    def test_mira_desktop_deployed_stamp_upgrades_without_recreating_its_tables(self) -> None:
        scripts = migration_scripts()
        desktop = scripts.get_revision("0165_mira_desktop")
        repetitive = scripts.get_revision("0165_system_task_is_repetitive")
        merge = scripts.get_revision("0166_merge_mira_repetitive")
        self.assertEqual(desktop.down_revision, "0164_project_is_active")
        self.assertEqual(set(merge.down_revision), {desktop.revision, repetitive.revision})
        for deployed, required, already_applied in (
            (desktop.revision, repetitive.revision, {desktop.revision}),
            (repetitive.revision, desktop.revision, {repetitive.revision}),
            ((desktop.revision, repetitive.revision), merge.revision, {desktop.revision, repetitive.revision}),
            ("0164_project_is_active", desktop.revision, set()),
        ):
            with self.subTest(deployed=deployed):
                revisions = [step.revision.revision for step in scripts._upgrade_revs(merge.revision, deployed)]
                self.assertIn(required, revisions)
                self.assertTrue(already_applied.isdisjoint(revisions))
                self.assertEqual(revisions[-1], merge.revision)
        self.assertEqual(scripts._upgrade_revs(merge.revision, merge.revision), [])

    def test_restored_mira_desktop_migration_creates_capture_tables(self) -> None:
        migration = migration_scripts().get_revision("0165_mira_desktop").module
        output = StringIO()
        operations = Operations(MigrationContext.configure(
            dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output},
        ))
        with patch.object(migration, "op", operations):
            migration.upgrade()
        sql = output.getvalue()
        self.assertIn("CREATE TABLE mira_desktop_sessions", sql)
        self.assertIn("CREATE TABLE mira_desktop_segments", sql)
        self.assertIn("CONSTRAINT uq_mira_desktop_segment_sequence UNIQUE (session_id, sequence)", sql)
        self.assertIn("FOREIGN KEY(session_id) REFERENCES mira_desktop_sessions (id) ON DELETE CASCADE", sql)
        self.assertIn("CREATE INDEX ix_mira_desktop_sessions_user_id", sql)
        self.assertIn("CREATE INDEX ix_mira_desktop_segments_session_id", sql)

    def test_recording_deletion_recognizes_the_deployed_stamp_without_reapplying_it(self) -> None:
        scripts = migration_scripts()
        revision = scripts.get_revision("0161_recording_deletion")
        self.assertEqual(revision.down_revision, "0160_mira_host_px_notes")
        self.assertEqual(scripts._upgrade_revs(revision.revision, revision.revision), [])
        self.assertNotIn(revision.revision, [
            step.revision.revision for step in scripts._upgrade_revs("heads", revision.revision)
        ])
        self.assertEqual(
            [step.revision.revision for step in scripts._upgrade_revs(revision.revision, revision.down_revision)],
            [revision.revision],
        )

    def test_recording_deletion_upgrade_and_downgrade_preserve_existing_recordings(self) -> None:
        migration = migration_scripts().get_revision("0161_recording_deletion").module
        engine = sa.create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                connection.execute(sa.text("CREATE TABLE meeting_recordings (id TEXT PRIMARY KEY, title TEXT NOT NULL)"))
                connection.execute(sa.text("INSERT INTO meeting_recordings VALUES ('existing', 'Keep this recording')"))
                operations = Operations(MigrationContext.configure(connection))
                with patch.object(migration, "op", operations):
                    migration.upgrade()
                    columns = {column["name"]: column for column in sa.inspect(connection).get_columns("meeting_recordings")}
                    self.assertTrue(columns["deleted_at"]["nullable"])
                    self.assertTrue(columns["files_purged_at"]["nullable"])
                    indexes = sa.inspect(connection).get_indexes("meeting_recordings")
                    self.assertEqual([(index["name"], index["column_names"], index["unique"]) for index in indexes],
                                     [("ix_deleted_at", ["deleted_at"], 0)])
                    self.assertEqual(connection.execute(sa.text("SELECT id, title, deleted_at, files_purged_at FROM meeting_recordings")).one(),
                                     ("existing", "Keep this recording", None, None))
                    migration.downgrade()
                self.assertEqual(connection.execute(sa.text("SELECT id, title FROM meeting_recordings")).one(),
                                 ("existing", "Keep this recording"))
                self.assertNotIn("deleted_at", {column["name"] for column in sa.inspect(connection).get_columns("meeting_recordings")})
        finally:
            engine.dispose()

    def test_recording_deletion_migration_emits_the_observed_postgresql_schema(self) -> None:
        migration = migration_scripts().get_revision("0161_recording_deletion").module
        output = StringIO()
        operations = Operations(MigrationContext.configure(
            dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output},
        ))
        with patch.object(migration, "op", operations):
            migration.upgrade()
        sql = output.getvalue()
        self.assertIn("ADD COLUMN deleted_at TIMESTAMP WITH TIME ZONE", sql)
        self.assertIn("ADD COLUMN files_purged_at TIMESTAMP WITH TIME ZONE", sql)
        self.assertNotIn("deleted_at TIMESTAMP WITH TIME ZONE NOT NULL", sql)
        self.assertIn("CREATE INDEX ix_deleted_at ON meeting_recordings (deleted_at)", sql)

    def test_revisions_are_unique_and_have_one_head(self) -> None:
        # Alembic only warns about duplicate IDs, so a zero exit code alone
        # does not establish that the migration graph is valid.
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            scripts = migration_scripts()
            self.assertEqual(len(scripts.get_heads()), 1)
            revisions = list(scripts.walk_revisions())
        self.assertEqual(len({item.revision for item in revisions}), len(revisions))

    def test_deployed_marker_remains_an_ancestor_of_person_comments(self) -> None:
        scripts = migration_scripts()
        marker = scripts.get_revision("0135_realization_daily_comments")
        successor = scripts.get_revision("0136_person_comments")
        self.assertEqual(Path(marker.path).name, "0135_realization_daily_comments.py")
        self.assertEqual(successor.down_revision, marker.revision)
        path = list(scripts.iterate_revisions("heads", marker.revision))
        self.assertIn(successor.revision, [item.revision for item in path])

    def test_upgrade_accepts_both_deployed_person_comment_ids(self) -> None:
        scripts = migration_scripts()
        for deployed in (
            "0136_person_comments",
            "0136_daily_person_comments",
            "0140_report_manual_questions",
        ):
            with self.subTest(deployed=deployed):
                # Exercise Alembic's upgrade planner with the actual deployed
                # stamps, without connecting to or modifying a server database.
                steps = scripts._upgrade_revs("heads", deployed)
                revisions = [step.revision.revision for step in steps]
                self.assertEqual(revisions[-1], scripts.get_current_head())
                self.assertIn("0141_merge_person_comment_ids", revisions)
                self.assertNotIn("0136_person_comments", revisions)
                self.assertNotIn("20260811_add_realization_review_answers", revisions)

    def test_alternate_marker_has_no_schema_operations(self) -> None:
        scripts = migration_scripts()
        marker = scripts.get_revision("0136_daily_person_comments")
        self.assertEqual(marker.down_revision, "0136_person_comments")
        with patch.object(scripts.get_revision("0136_person_comments").module, "op") as operations:
            marker.module.upgrade()
            marker.module.downgrade()
        self.assertEqual(operations.mock_calls, [])

    def test_missing_table_emits_postgresql_schema_with_unique_person_comments(self) -> None:
        migration = migration_scripts().get_revision("0136_person_comments").module
        output = StringIO()
        operations = Operations(MigrationContext.configure(
            dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output},
        ))
        with patch.object(migration, "op", operations), patch.object(migration.sa, "inspect") as inspect:
            inspect.return_value.has_table.return_value = False
            migration.upgrade()
        sql = output.getvalue()
        self.assertIn("CREATE TABLE realization_daily_person_comments", sql)
        self.assertIn("UNIQUE (period_id, user_id)", sql)
        self.assertIn("FOREIGN KEY(period_id) REFERENCES realization_periods (id) ON DELETE CASCADE", sql)
        self.assertIn("CREATE INDEX ix_realization_daily_person_comments_period_id", sql)
        self.assertIn("CREATE INDEX ix_realization_daily_person_comments_user_id", sql)

    def test_person_comment_upgrade_preserves_rows_and_repairs_missing_index(self) -> None:
        migration = migration_scripts().get_revision("0136_person_comments").module
        # An isolated in-memory database exercises the actual DDL and row
        # preservation without connecting to the configured server database.
        engine = sa.create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                operations = Operations(MigrationContext.configure(connection))
                # Seed the schema that an earlier deployment of the colliding
                # revision would have left behind. TEXT IDs avoid relying on
                # PostgreSQL's gen_random_uuid() inside this SQLite fixture.
                connection.execute(sa.text(
                    "CREATE TABLE realization_daily_person_comments ("
                    "id TEXT PRIMARY KEY, period_id TEXT NOT NULL, user_id TEXT NOT NULL, "
                    "comment TEXT, updated_by TEXT, "
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, "
                    "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, "
                    "CONSTRAINT uq_realization_daily_person_comment UNIQUE (period_id, user_id))"
                ))
                with patch.object(migration, "op", operations):
                    connection.execute(sa.text(
                        "INSERT INTO realization_daily_person_comments (id, period_id, user_id, comment) "
                        "VALUES ('row-id', 'period-id', 'user-id', 'Existing comment')"
                    ))
                    # The colliding 0135 may have already created this table.
                    migration.upgrade()
                    connection.execute(sa.text("DROP INDEX ix_realization_daily_person_comments_user_id"))
                    migration.upgrade()
                self.assertEqual(
                    connection.execute(sa.text("SELECT comment FROM realization_daily_person_comments")).scalars().all(),
                    ["Existing comment"],
                )
                indexes = {item["name"] for item in sa.inspect(connection).get_indexes("realization_daily_person_comments")}
                self.assertTrue({
                    "ix_realization_daily_person_comments_period_id",
                    "ix_realization_daily_person_comments_user_id",
                }.issubset(indexes))
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
