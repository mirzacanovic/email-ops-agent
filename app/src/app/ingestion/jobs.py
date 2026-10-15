"""In-process state for the background "check inbox" job.

A full poll takes about four minutes per email on a CPU-only model, which is
longer than a browser or curl will wait. So the UI starts the poll as a
background task, returns immediately, and reads progress from here.

State lives in memory and is lost on restart; that is fine because the
audit DB, not this object, is the record of what was processed. Like the
poll lock in routes.py, this assumes a single worker process; running
several would need the job state (and the lock) moved into the database.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

Progress = Callable[[int, int], None]  # (emails handled so far, emails to handle)
Run = Callable[[Progress], Awaitable[int]]  # returns the number processed successfully


@dataclass
class PollJob:
    state: str = "idle"  # idle | running | done | error
    started_at: datetime | None = None
    finished_at: datetime | None = None
    handled: int = 0  # emails attempted so far (successes and failures)
    total: int | None = None  # emails to attempt; None until the inbox has been read
    processed: int | None = None  # emails that succeeded, once finished
    error: str | None = None


job = PollJob()
_task: asyncio.Task[None] | None = None  # strong reference so the task isn't garbage collected


def status() -> dict[str, object]:
    return {
        "state": job.state,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "handled": job.handled,
        "total": job.total,
        "processed": job.processed,
        # Emails that were attempted but did not succeed; they have no audit row,
        # so the next poll retries them.
        "failed": (job.total - job.processed)
        if job.total is not None and job.processed is not None
        else None,
        "error": job.error,
    }


def is_running() -> bool:
    return job.state == "running"


def _progress(handled: int, total: int) -> None:
    job.handled, job.total = handled, total


async def _run(run: Run) -> None:
    try:
        job.processed = await run(_progress)
        job.state = "done"
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI, not swallowed
        logger.exception("Background poll failed")
        job.state, job.error = "error", f"{type(exc).__name__}: {exc}"[:300]
    finally:
        job.finished_at = datetime.now(timezone.utc)


def start(run: Run) -> bool:
    """Start `run` in the background. False (and nothing started) if a job is
    already running. Must be called from the event loop."""
    global _task
    if is_running():
        return False
    job.state, job.error = "running", None
    job.started_at, job.finished_at = datetime.now(timezone.utc), None
    job.handled, job.total, job.processed = 0, None, None
    _task = asyncio.get_running_loop().create_task(_run(run))
    return True
