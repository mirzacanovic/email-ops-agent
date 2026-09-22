import json
from pathlib import Path

import email_simulator.main as main
from email_simulator.main import _parse_iso


def test_parses_z_suffix():
    dt = _parse_iso("2026-09-15T09:12:00Z")
    assert dt.tzinfo is not None


def test_z_and_explicit_offset_are_the_same_instant():
    # Regression: raw-string comparison of these two equal instants made
    # every already-processed message look new again on the next poll.
    assert _parse_iso("2026-09-17T08:30:00Z") == _parse_iso("2026-09-17T08:30:00+00:00")


def _write_fixture(directory: Path, filename: str, message_id: str, received_at: str) -> None:
    (directory / filename).write_text(
        json.dumps(
            {
                "id": message_id,
                "from": "sender@example.com",
                "to": "support@example.com",
                "subject": "Subject",
                "body": "Body",
                "received_at": received_at,
            }
        )
    )


def test_list_messages_since_filters_by_parsed_datetime_not_raw_string(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "FIXTURES_DIR", tmp_path)
    _write_fixture(tmp_path, "a.json", "msg-a", "2026-09-15T09:12:00Z")
    _write_fixture(tmp_path, "b.json", "msg-b", "2026-09-17T08:30:00Z")

    # "since" spelled with an explicit offset (as a datetime round-tripped
    # through Postgres would come back) rather than "Z" -- msg-a's
    # timestamp is the exact same instant as this cursor, so it must be
    # excluded (not "newer"), and only msg-b should come back.
    result = main.list_messages(since="2026-09-15T09:12:00+00:00")

    assert [m["id"] for m in result] == ["msg-b"]


def test_list_messages_with_no_since_returns_everything_sorted(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "FIXTURES_DIR", tmp_path)
    _write_fixture(tmp_path, "b.json", "msg-b", "2026-09-17T08:30:00Z")
    _write_fixture(tmp_path, "a.json", "msg-a", "2026-09-15T09:12:00Z")

    result = main.list_messages(since=None)

    assert [m["id"] for m in result] == ["msg-a", "msg-b"]
