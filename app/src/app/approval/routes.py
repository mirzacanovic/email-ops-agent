from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.models import ApprovalDecision, ExecutionResult, ProposedAction
from app.connectors.espocrm import EspoCRMConnector
from app.connectors.plane import PlaneConnector
from app.db.session import get_db
from app.dependencies import get_espocrm_connector, get_plane_connector
from app.pipeline.execute import execute_action
from app.pipeline.propose import ProposedActionDraft

router = APIRouter(prefix="/approvals", tags=["approvals"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# demo has no real auth/identity yet -- see TODO(phase-2) below.
DEMO_APPROVER = "demo-user"


@router.get("", response_class=HTMLResponse)
def list_pending_approvals(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    already_decided = select(ApprovalDecision.proposed_action_id)
    pending = db.scalars(
        select(ProposedAction)
        .where(ProposedAction.id.not_in(already_decided))
        .order_by(ProposedAction.created_at.desc())
    ).all()
    return templates.TemplateResponse(request, "review.html", {"pending": pending})


@router.post("/{proposed_action_id}/approve")
async def approve(
    proposed_action_id: str,
    db: Session = Depends(get_db),
    espocrm: EspoCRMConnector = Depends(get_espocrm_connector),
    plane: PlaneConnector = Depends(get_plane_connector),
) -> RedirectResponse:
    proposed = db.get(ProposedAction, proposed_action_id)
    if proposed is None:
        raise HTTPException(status_code=404, detail="Proposed action not found")

    # TODO(phase-2): real auth — approver is hardcoded until there's a
    # login system for the review UI.
    decision = ApprovalDecision(
        proposed_action_id=proposed.id, decision="approved", approver=DEMO_APPROVER
    )
    db.add(decision)
    db.flush()  # populate decision.id for the ExecutionResult FK below

    connector = {"espocrm": espocrm, "plane": plane}.get(proposed.target_system)
    draft = ProposedActionDraft(
        action_type=proposed.action_type,
        target_system=proposed.target_system,
        entity_type=proposed.entity_type,
        record_id=proposed.record_id,
        fields=proposed.fields,
        rationale=proposed.rationale,
        confidence=proposed.confidence,
    )
    try:
        result = await execute_action(connector, draft)
        db.add(
            ExecutionResult(
                approval_decision_id=decision.id, success=True, response_payload=result
            )
        )
    except Exception as exc:
        db.add(
            ExecutionResult(
                approval_decision_id=decision.id,
                success=False,
                response_payload={},
                error_message=str(exc),
            )
        )
    db.commit()
    return RedirectResponse(url="/approvals", status_code=303)


@router.post("/{proposed_action_id}/reject")
def reject(proposed_action_id: str, db: Session = Depends(get_db)) -> RedirectResponse:
    proposed = db.get(ProposedAction, proposed_action_id)
    if proposed is None:
        raise HTTPException(status_code=404, detail="Proposed action not found")

    db.add(
        ApprovalDecision(
            proposed_action_id=proposed.id, decision="rejected", approver=DEMO_APPROVER
        )
    )
    db.commit()
    return RedirectResponse(url="/approvals", status_code=303)
