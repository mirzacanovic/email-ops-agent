import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.audit.models import Base
from app.db.migrate import BASELINE_REVISION, run_migrations


@pytest.fixture
def engine(tmp_path) -> Engine:
    return create_engine(f"sqlite:///{tmp_path / 'test.db'}")


def _version(engine: Engine) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _insert_email(conn, row_id: str, source_id: str) -> None:
    conn.execute(
        text(
            "INSERT INTO email_messages "
            "(id, source_message_id, sender, subject, body, received_at, created_at) "
            "VALUES (:id, :src, 's', 's', 'b', '2026-09-15', '2026-09-15')"
        ),
        {"id": row_id, "src": source_id},
    )


def test_fresh_database_migrates_to_head(engine):
    run_migrations(engine)
    assert _version(engine) == "0003"
    assert set(Base.metadata.tables) <= set(inspect(engine).get_table_names())


def test_migrations_match_the_models(engine):
    # Catches a model change that forgot its migration.
    run_migrations(engine)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_running_migrations_twice_is_a_noop(engine):
    run_migrations(engine)
    run_migrations(engine)
    assert _version(engine) == "0003"


def _downgrade_to_pre_alembic(engine: Engine) -> None:
    """Make the database look like one created by the old create_all-on-startup:
    tables present, no alembic_version, no unique constraint, no users."""
    run_migrations(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE alembic_version"))
        conn.execute(text("DROP TABLE users"))  # added after the create_all era
        conn.execute(text("ALTER TABLE email_messages RENAME TO old"))
        conn.execute(
            text(
                "CREATE TABLE email_messages (id VARCHAR NOT NULL PRIMARY KEY, "
                "source_message_id VARCHAR NOT NULL, sender VARCHAR NOT NULL, "
                "subject VARCHAR NOT NULL, body TEXT NOT NULL, "
                "received_at DATETIME NOT NULL, created_at DATETIME NOT NULL)"
            )
        )
        conn.execute(text("DROP TABLE old"))


def test_pre_alembic_database_is_stamped_then_upgraded(engine):
    _downgrade_to_pre_alembic(engine)
    with engine.begin() as conn:
        _insert_email(conn, "1", "m1")  # existing data must survive

    run_migrations(engine)

    assert _version(engine) == "0003"
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM email_messages")).scalar_one() == 1


def test_unique_constraint_rejects_a_second_row_for_the_same_message(engine):
    run_migrations(engine)
    with pytest.raises(IntegrityError), engine.begin() as conn:
        _insert_email(conn, "1", "m1")
        _insert_email(conn, "2", "m1")


def test_upgrade_refuses_when_duplicates_already_exist(engine):
    # A pre-Alembic database that already holds the duplicate rows from the
    # old overlapping-poll race: the constraint can't be added silently.
    _downgrade_to_pre_alembic(engine)
    with engine.begin() as conn:
        _insert_email(conn, "1", "m1")
        _insert_email(conn, "2", "m1")

    with pytest.raises(RuntimeError, match="duplicate source_message_id"):
        run_migrations(engine)


def test_baseline_revision_is_the_first_migration():
    assert BASELINE_REVISION == "0001"
