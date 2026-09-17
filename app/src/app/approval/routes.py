from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.models import ProposedAction
from app.db.session import get_db

router = APIRouter(prefix="/approvals", tags=["approvals"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@router.get("", response_class=HTMLResponse)
def list_pending_approvals(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    # TODO(phase-1): exclude actions that already have an ApprovalDecision
    # row once that join is needed; for now this just lists everything
    # proposed so the empty-state page has something to render against.
    pending = db.scalars(select(ProposedAction).order_by(ProposedAction.created_at.desc())).all()
    return templates.TemplateResponse(
        request, "review.html", {"pending": pending}
    )


@router.post("/{proposed_action_id}/approve")
def approve(proposed_action_id: str) -> dict[str, str]:
    # TODO(phase-1): write an ApprovalDecision row, then call
    # pipeline.execute.execute_action and write an ExecutionResult row.
    raise NotImplementedError


@router.post("/{proposed_action_id}/reject")
def reject(proposed_action_id: str) -> dict[str, str]:
    # TODO(phase-1): write an ApprovalDecision row with decision="rejected".
    raise NotImplementedError
