"""HTTP front for an IMAP mailbox, speaking the same contract as the email
simulator (GET /messages), so the orchestrator can read a real inbox without
any change to the pipeline: point EMAIL_SIMULATOR_URL at this service.

There is deliberately no login on these endpoints: they expose mail content, so
this service must only be reachable from the orchestrator (docker network) or
from localhost; docker-compose publishes its port on 127.0.0.1 only.
"""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from imap_bridge import mailbox
from imap_bridge.config import Config, load_config

app = FastAPI(title="IMAP Bridge")

Fetcher = Callable[[Config, datetime], list[dict[str, str]]]


@lru_cache
def get_config() -> Config:
    return load_config()


def get_fetcher() -> Fetcher:
    return mailbox.fetch_recent


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@app.get("/health")
def health(cfg: Config = Depends(get_config)) -> dict[str, object]:
    """The process is up. Says whether it is configured, not whether the
    mailbox is reachable (that is /ready)."""
    return {"status": "ok", "configured": cfg.configured}


@app.get("/ready")
def ready(cfg: Config = Depends(get_config)) -> JSONResponse:
    if not cfg.configured:
        return JSONResponse(status_code=503, content={"ready": False, "detail": "IMAP_HOST, IMAP_USER and IMAP_PASSWORD are not all set"})
    try:
        mailbox.check_connection(cfg)
    except mailbox.MailboxError as exc:
        return JSONResponse(status_code=503, content={"ready": False, "detail": str(exc)})
    return JSONResponse(content={"ready": True, "folder": cfg.folder})


@app.get("/messages")
def list_messages(
    since: str | None = Query(default=None),
    cfg: Config = Depends(get_config),
    fetch: Fetcher = Depends(get_fetcher),
) -> list[dict[str, str]]:
    """Recent mail from the configured folder, oldest first.

    Only the last IMAP_LOOKBACK_DAYS days and at most IMAP_MAX_MESSAGES of the
    newest, because the orchestrator asks again on every check (it skips what it
    already processed by id). Mail older than the window is never seen.
    `since` (ISO 8601) is accepted for compatibility with the simulator.
    """
    if not cfg.configured:
        raise HTTPException(status_code=503, detail="IMAP_HOST, IMAP_USER and IMAP_PASSWORD must be set")
    window_start = datetime.now(timezone.utc) - timedelta(days=cfg.lookback_days)
    try:
        messages = fetch(cfg, window_start)
    except mailbox.MailboxError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    if since:
        cutoff = _parse_iso(since)
        messages = [m for m in messages if _parse_iso(m["received_at"]) > cutoff]
    return messages
