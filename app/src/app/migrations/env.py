from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection

from app.audit.models import Base
from app.config import get_settings

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    # render_as_batch: SQLite (used in tests) can't ALTER constraints in
    # place; batch mode is a no-op on Postgres.
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # app.db.migrate passes its own connection (so tests and app startup
    # share one engine); the bare `alembic` CLI builds one from settings.
    connection = config.attributes.get("connection")
    if connection is None:
        engine = create_engine(get_settings().database_url)
        with engine.connect() as connection:
            _run(connection)
            connection.commit()
    else:
        _run(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
