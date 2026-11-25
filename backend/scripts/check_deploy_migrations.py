"""Read the production revision and validate the deployment's upgrade path."""

import os
from pathlib import Path
import sys
import warnings

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from dotenv import dotenv_values
import sqlalchemy as sa


def planned_head(scripts: ScriptDirectory, current: tuple[str, ...]) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        head = scripts.get_current_head()
        if head is None:
            raise CommandError("The deployment commit has no Alembic head.")
        if not current:
            raise CommandError("The production database has no Alembic revision.")
        for revision in current:
            if scripts.get_revision(revision).revision != revision:
                raise CommandError(f"The deployment commit does not contain the exact revision {revision}.")
        scripts._upgrade_revs(head, current)
    return head


def main() -> int:
    backend = Path(__file__).resolve().parents[1]
    database_url = os.environ.get("DATABASE_URL") or dotenv_values(backend / ".env").get("DATABASE_URL")
    if not database_url:
        print("Migration preflight failed: DATABASE_URL is missing.", file=sys.stderr)
        return 1

    current: tuple[str, ...] = ()
    try:
        url = sa.make_url(database_url).set(drivername="postgresql+psycopg2")
        engine = sa.create_engine(url, connect_args={
            "connect_timeout": 5,
            "options": "-c default_transaction_read_only=on -c statement_timeout=5000",
        })
        try:
            with engine.connect() as connection:
                current = MigrationContext.configure(connection).get_current_heads()
        finally:
            engine.dispose()

        config = Config()
        config.set_main_option("script_location", str(backend / "alembic"))
        head = planned_head(ScriptDirectory.from_config(config), current)
    except (CommandError, UserWarning, KeyError) as error:
        revisions = ", ".join(current) or "(none)"
        print(f"Migration preflight failed (production revisions: {revisions}): {error}", file=sys.stderr)
        return 1
    except sa.exc.SQLAlchemyError as error:
        print(f"Migration preflight could not read the production database ({type(error).__name__}).", file=sys.stderr)
        return 1

    print(f"Migration preflight passed: {', '.join(current)} -> {head}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
