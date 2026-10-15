import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.deps import require_user
from app.config import Settings, get_settings
from app.connectors.espocrm import EspoCRMConnector
from app.connectors.plane import PlaneConnector
from app.db.session import get_db
from app.dependencies import get_espocrm_connector, get_llm, get_plane_connector
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


@router.post("/poll")
async def poll(
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_llm),
    espocrm: EspoCRMConnector = Depends(get_espocrm_connector),
    plane: PlaneConnector = Depends(get_plane_connector),
    settings: Settings = Depends(get_settings),
) -> dict[str, int]:
    """Trigger a pipeline run against the email simulator now, rather
    than waiting on a background loop — simpler to demo (click, see the
    result) and there's no real inbox pushing events yet anyway.
    """
    processed = await _locked_poll(db, llm, espocrm, plane, settings)
    if processed is None:
        raise HTTPException(status_code=409, detail="A poll is already in progress")
    return {"processed": processed}


@router.post("/poll-form")
async def poll_form(
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_llm),
    espocrm: EspoCRMConnector = Depends(get_espocrm_connector),
    plane: PlaneConnector = Depends(get_plane_connector),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Same poll as /ingest/poll, for the approvals page's button: redirects
    back to the page with the outcome instead of returning JSON."""
    try:
        processed = await _locked_poll(db, llm, espocrm, plane, settings)
    except Exception:
        return RedirectResponse(url="/approvals?poll=error", status_code=303)
    if processed is None:
        return RedirectResponse(url="/approvals?poll=busy", status_code=303)
    return RedirectResponse(url=f"/approvals?poll=ok&processed={processed}", status_code=303)
