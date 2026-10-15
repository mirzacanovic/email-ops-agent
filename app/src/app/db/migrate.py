"""Runs Alembic migrations programmatically, so app startup (and tests) need
neither an alembic.ini nor a separate migration step.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, inspect

# The revision that matches what `Base.metadata.create_all` produced before
# Alembic existed. A database that has the tables but no alembic_version was
# created that way, so it is stamped here instead of re-running 0001 (which
# would fail on the tables already being there).
BASELINE_REVISION = "0001"


def _config(connection: Connection) -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent.parent / "migrations"))
    config.attributes["connection"] = connection
    return config


def run_migrations(engine: Engine) -> None:
    with engine.begin() as connection:
        config = _config(connection)
        tables = set(inspect(connection).get_table_names())
        if "email_messages" in tables and "alembic_version" not in tables:
            command.stamp(config, BASELINE_REVISION)
        command.upgrade(config, "head")
