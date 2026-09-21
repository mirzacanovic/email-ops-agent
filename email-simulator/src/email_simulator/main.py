import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query

FIXTURES_DIR = Path("/app/fixtures")

app = FastAPI(title="Email Simulator")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _load_fixtures() -> list[dict[str, Any]]:
    messages = [json.loads(p.read_text()) for p in sorted(FIXTURES_DIR.glob("*.json"))]
    return sorted(messages, key=lambda m: _parse_iso(m["received_at"]))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/messages")
def list_messages(since: str | None = Query(default=None)) -> list[dict[str, Any]]:
    """Return fixture emails, optionally only those received after `since`
    (any ISO 8601 datetime string). Compared as parsed datetimes rather
    than raw strings, so differing UTC-offset spellings — fixtures use
    "Z", a caller might round-trip one through Python as "+00:00" — still
    compare correctly instead of every message looking "newer" forever.

    The orchestrator's inbox poller uses this to fetch only new messages
    on each poll — see app/src/app/ingestion/inbox_poller.py.
    """
    messages = _load_fixtures()
    if since:
        since_dt = _parse_iso(since)
        messages = [m for m in messages if _parse_iso(m["received_at"]) > since_dt]
    return messages


@app.get("/messages/{message_id}")
def get_message(message_id: str) -> dict[str, Any] | None:
    for message in _load_fixtures():
        if message["id"] == message_id:
            return message
    return None
