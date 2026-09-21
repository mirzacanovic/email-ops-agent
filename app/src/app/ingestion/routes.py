from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.connectors.espocrm import EspoCRMConnector
from app.connectors.plane import PlaneConnector
from app.db.session import get_db
from app.dependencies import get_espocrm_connector, get_llm, get_plane_connector
from app.ingestion.inbox_poller import poll_and_process
from app.llm.base import LLMClient

router = APIRouter(prefix="/ingest", tags=["ingestion"])


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
    processed = await poll_and_process(
        db=db,
        llm=llm,
        espocrm=espocrm,
        plane=plane,
        plane_project_id=settings.plane_default_project_id,
        email_simulator_url=settings.email_simulator_url,
    )
    return {"processed": processed}
