import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth.deps import require_user
from app.config import Settings, get_settings
from app.connectors.espocrm import EspoCRMConnector
from app.connectors.plane import PlaneConnector
from app.db.session import SessionLocal, get_db
from app.dependencies import get_espocrm_connector, get_llm, get_plane_connector
from app.ingestion import jobs
from app.ingestion.inbox_poller import poll_and_process
from app.llm.base import LLMClient

router = APIRouter(prefix="/ingest", tags=["ingestion"], dependencies=[Depends(require_user)])

# Dedup is per message (source_message_id), but it only sees rows already
# committed -- two overlapping calls both see the same unprocessed
# messages and both process them, producing duplicate rows (confirmed in
# testing: a slow first call was still running server-side, past its
# caller's own client-side timeout, when a second call started). A single
# process-wide lock is enough for this single-worker demo deployment; a
# real deployment with multiple workers would need a DB-level lock instead.
_poll_lock = asyncio.Lock()


async def _locked_poll(
    db: Session,
    llm: LLMClient,
    espocrm: EspoCRMConnector,
    plane: PlaneConnector,
    settings: Settings,
) -> int | None:
    """Runs one poll under the process-wide lock; None if one is already running."""
    if _poll_lock.locked():
        return None
    async with _poll_lock:
        return await poll_and_process(
            db=db,
            llm=llm,
            espocrm=espocrm,
            plane=plane,
            plane_project_id=settings.plane_default_project_id,
            email_simulator_url=settings.email_simulator_url,
        )


def _start_background_poll() -> bool:
    """Starts a poll as a background job. False if one is already running
    (either another background job or a synchronous /ingest/poll call)."""
    if _poll_lock.locked() or jobs.is_running():
        return False

    async def run(progress: jobs.Progress) -> int:
        # The request that started this has long since returned and closed its
        # DB session, so the job opens its own and builds its own clients.
        settings = get_settings()
        with SessionLocal() as db:
            async with _poll_lock:
                return await poll_and_process(
                    db=db,
                    llm=get_llm(),
                    espocrm=get_espocrm_connector(),
                    plane=get_plane_connector(),
                    plane_project_id=settings.plane_default_project_id,
                    email_simulator_url=settings.email_simulator_url,
                    progress=progress,
                )

    return jobs.start(run)


@router.post("/poll")
async def poll(
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_llm),
    espocrm: EspoCRMConnector = Depends(get_espocrm_connector),
    plane: PlaneConnector = Depends(get_plane_connector),
    settings: Settings = Depends(get_settings),
) -> dict[str, int]:
    """Run the pipeline against the email simulator now and wait for it.

    Blocks for the whole batch (minutes on a CPU-only model), so a client
    or proxy timeout is likely; the server keeps going regardless. Prefer
    POST /ingest/start plus GET /ingest/status for anything interactive.
    """
    processed = await _locked_poll(db, llm, espocrm, plane, settings)
    if processed is None:
        raise HTTPException(status_code=409, detail="A poll is already in progress")
    return {"processed": processed}


@router.post("/start", status_code=202)
async def start() -> JSONResponse:
    """Start a poll in the background and return immediately; follow it with
    GET /ingest/status."""
    if not _start_background_poll():
        return JSONResponse(
            status_code=409, content={"detail": "A poll is already in progress", **jobs.status()}
        )
    return JSONResponse(status_code=202, content=jobs.status())


@router.get("/status")
async def status() -> dict[str, object]:
    """State of the most recent background poll (idle until one has been started)."""
    return jobs.status()


@router.post("/poll-form")
async def poll_form() -> RedirectResponse:
    """The approvals page's button: starts a background poll and goes straight
    back to the page, which shows progress and refreshes itself while it runs.
    Starting while one is already running is harmless; the page shows that one."""
    _start_background_poll()
    return RedirectResponse(url="/approvals", status_code=303)
