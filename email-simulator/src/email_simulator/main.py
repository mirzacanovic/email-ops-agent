import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query

FIXTURES_DIR = Path("/app/fixtures")

app = FastAPI(title="Email Simulator")


def _load_fixtures() -> list[dict[str, Any]]:
    messages = [json.loads(p.read_text()) for p in sorted(FIXTURES_DIR.glob("*.json"))]
    return sorted(messages, key=lambda m: m["received_at"])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/messages")
def list_messages(since: str | None = Query(default=None)) -> list[dict[str, Any]]:
    """Return fixture emails, optionally only those received after `since`
    (ISO 8601). The orchestrator's inbox poller uses this to fetch only
    new messages on each poll — see app/src/app/ingestion/inbox_poller.py.
    """
    messages = _load_fixtures()
    if since:
        messages = [m for m in messages if m["received_at"] > since]
    return messages


@app.get("/messages/{message_id}")
def get_message(message_id: str) -> dict[str, Any] | None:
    for message in _load_fixtures():
        if message["id"] == message_id:
            return message
    return None
