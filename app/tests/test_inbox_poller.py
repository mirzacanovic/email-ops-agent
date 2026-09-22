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
