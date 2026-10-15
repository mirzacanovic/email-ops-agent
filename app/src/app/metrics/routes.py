from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth.deps import require_user
from app.db.session import get_db
from app.metrics.queries import compute_metrics

router = APIRouter(prefix="/metrics", tags=["metrics"], dependencies=[Depends(require_user)])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 90 * 60:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"


@router.get("", response_class=HTMLResponse)
def metrics_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    metrics = compute_metrics(db)
    return templates.TemplateResponse(
        request,
        "metrics.html",
        {"m": metrics, "time_to_decision": _duration(metrics.median_seconds_to_decision)},
    )
