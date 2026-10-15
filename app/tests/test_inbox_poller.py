import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.audit.models import Base, EmailMessage
from app.ingestion import inbox_poller
from app.ingestion.inbox_poller import _parse_iso


def test_parses_z_suffix():
    dt = _parse_iso("2026-09-15T09:12:00Z")
    assert dt.tzinfo is not None


def test_parses_explicit_utc_offset():
    dt = _parse_iso("2026-09-15T09:12:00+00:00")
    assert dt.tzinfo is not None


def test_z_and_explicit_offset_are_the_same_instant():
    # Regression: comparing these as raw strings (rather than parsed
    # datetimes) made an already-processed message look "newer" than the
    # poll cursor forever, since Postgres round-trips "Z" as "+00:00".
    assert _parse_iso("2026-09-15T09:12:00Z") == _parse_iso("2026-09-15T09:12:00+00:00")


# --- poll_and_process: per-message dedup instead of a received_at watermark ---

def _msg(msg_id: str, received_at: str) -> dict:
    return {
        "id": msg_id,
        "from": "a@example.com",
        "subject": msg_id,
        "body": "body",
        "received_at": received_at,
    }


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session


def _install(monkeypatch, messages, failing=frozenset()):
    async def fake_fetch(_url):
        return messages

    async def fake_process(db, _llm, _espo, _plane, _project, message):
        if message["id"] in failing:
            raise RuntimeError("transient")
        db.add(
            EmailMessage(
                source_message_id=message["id"],
                sender=message["from"],
                subject=message["subject"],
                body=message["body"],
                received_at=inbox_poller._parse_iso(message["received_at"]),
            )
        )

    monkeypatch.setattr(inbox_poller, "_fetch_messages", fake_fetch)
    monkeypatch.setattr(inbox_poller, "_process_one", fake_process)


async def _poll(db):
    return await inbox_poller.poll_and_process(db, None, None, None, "p", "http://x")


async def test_failed_message_is_retried_after_a_later_one_succeeds(db, monkeypatch):
    messages = [_msg("m1", "2026-09-15T09:00:00Z"), _msg("m2", "2026-09-15T10:00:00Z")]
    _install(monkeypatch, messages, failing={"m1"})
    assert await _poll(db) == 1  # m1 fails, m2 succeeds -> old watermark moved past m1

    _install(monkeypatch, messages)  # m1 recovers
    assert await _poll(db) == 1
    ids = set(db.scalars(select(EmailMessage.source_message_id)))
    assert ids == {"m1", "m2"}


async def test_already_processed_messages_are_not_reprocessed(db, monkeypatch):
    messages = [_msg("m1", "2026-09-15T09:00:00Z")]
    _install(monkeypatch, messages)
    assert await _poll(db) == 1
    assert await _poll(db) == 0
