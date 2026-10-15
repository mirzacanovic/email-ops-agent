from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.approval.edits import EDIT_PREFIX, EditError, editable_fields, parse_edits
from app.audit.models import ApprovalDecision, ExecutionResult, ProposedAction, User
from app.auth.deps import require_user
from app.connectors.espocrm import EspoCRMConnector
from app.connectors.plane import PlaneConnector
from app.db.session import get_db
from app.dependencies import get_espocrm_connector, get_plane_connector
from app.ingestion import jobs
from app.pipeline.execute import execute_action
from app.pipeline.propose import ProposedActionDraft

router = APIRouter(prefix="/approvals", tags=["approvals"], dependencies=[Depends(require_user)])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _render_pending(
    request: Request,
    db: Session,
    error: str | None = None,
    error_for: str | None = None,
    submitted: dict[str, str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    already_decided = select(ApprovalDecision.proposed_action_id)
    pending = db.scalars(
        select(ProposedAction)
        .where(ProposedAction.id.not_in(already_decided))
        .order_by(ProposedAction.created_at.desc())
    ).all()
    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "pending": pending,
            "job": jobs.status(),
            "editable": {a.id: editable_fields(a.fields) for a in pending},
            "error": error,
            "error_for": error_for,
            # What the reviewer typed, so a rejected edit isn't lost.
            "submitted": submitted or {},
        },
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
def list_pending_approvals(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return _render_pending(request, db)


async def _read_form(request: Request) -> dict[str, str]:
    """The posted form as {name: value}. Parsed by hand so the app does not need
    python-multipart; the approve button posts no body at all, and curl callers
    may post none or something else, which all mean "no edits"."""
    if not request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
        return {}
    body = (await request.body()).decode("utf-8", errors="replace")
    return {key: values[0] for key, values in parse_qs(body, keep_blank_values=True).items()}


def _require_undecided(db: Session, proposed: ProposedAction) -> None:
    # Without this, a double click or a retry after a slow response records two
    # decisions and executes twice, i.e. creates a duplicate issue or Lead.
    if db.scalar(
        select(ApprovalDecision.id).where(ApprovalDecision.proposed_action_id == proposed.id)
    ):
        raise HTTPException(status_code=409, detail="This proposal has already been decided")


@router.post("/{proposed_action_id}/approve", response_model=None)
async def approve(
    proposed_action_id: str,
    request: Request,
    db: Session = Depends(get_db),
    espocrm: EspoCRMConnector = Depends(get_espocrm_connector),
    plane: PlaneConnector = Depends(get_plane_connector),
    user: User = Depends(require_user),
) -> RedirectResponse | HTMLResponse:
    proposed = db.get(ProposedAction, proposed_action_id)
    if proposed is None:
        raise HTTPException(status_code=404, detail="Proposed action not found")
    _require_undecided(db, proposed)

    form = await _read_form(request)
    try:
        edits = parse_edits(form, proposed.fields)
    except EditError as exc:
        submitted = {k[len(EDIT_PREFIX):]: v for k, v in form.items() if k.startswith(EDIT_PREFIX)}
        return _render_pending(
            request, db, error=str(exc), error_for=proposed.id, submitted=submitted, status_code=422
        )

    # The proposal row is never modified: the audit trail keeps what the model
    # proposed (ProposedAction.fields) and what the human changed
    # (ApprovalDecision.edited_fields) side by side.
    decision = ApprovalDecision(
        proposed_action_id=proposed.id,
        decision="edited" if edits else "approved",
        edited_fields=edits or None,
        approver=user.username,
    )
    db.add(decision)
    db.flush()  # populate decision.id for the ExecutionResult FK below

    connector = {"espocrm": espocrm, "plane": plane}.get(proposed.target_system)
    draft = ProposedActionDraft(
        action_type=proposed.action_type,
        target_system=proposed.target_system,
        entity_type=proposed.entity_type,
        record_id=proposed.record_id,
        fields={**proposed.fields, **edits},
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
def reject(
    proposed_action_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> RedirectResponse:
    proposed = db.get(ProposedAction, proposed_action_id)
    if proposed is None:
        raise HTTPException(status_code=404, detail="Proposed action not found")
    _require_undecided(db, proposed)

    db.add(
        ApprovalDecision(
            proposed_action_id=proposed.id, decision="rejected", approver=user.username
        )
    )
    db.commit()
    return RedirectResponse(url="/approvals", status_code=303)
