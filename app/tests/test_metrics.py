from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.audit.models import (
    ApprovalDecision,
    Base,
    EmailMessage,
    ExecutionResult,
    ExtractionResult,
    ProposedAction,
    User,
)
from app.auth.deps import require_user
from app.db.session import get_db
from app.metrics.queries import compute_metrics
from app.metrics.routes import router

T0 = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _add_proposal(db, n: int, intent: str, action_type: str, confidence: float) -> ProposedAction:
    email = EmailMessage(
        source_message_id=f"m{n}", sender="s@x.com", subject="s", body="b", received_at=T0
    )
    db.add(email)
    db.flush()
    db.add(
        ExtractionResult(
            email_message_id=email.id,
            intent=intent,
            intent_confidence=0.9,
            extracted_fields={},
            model_raw_response={},
        )
    )
    action = ProposedAction(
        email_message_id=email.id,
        action_type=action_type,
        target_system="plane",
        entity_type="x",
        fields={},
        candidate_matches=[],
        rationale="r",
        confidence=confidence,
        created_at=T0,
    )
    db.add(action)
    db.flush()
    return action


def _decide(db, action, decision: str, after_seconds: int, success: bool | None = None) -> None:
    d = ApprovalDecision(
        proposed_action_id=action.id,
        decision=decision,
        approver="alice",
        decided_at=T0 + timedelta(seconds=after_seconds),
    )
    db.add(d)
    db.flush()
    if success is not None:
        db.add(
            ExecutionResult(approval_decision_id=d.id, success=success, response_payload={})
        )


def test_empty_database_gives_zeroes_not_errors(session_factory):
    with session_factory() as db:
        m = compute_metrics(db)
    assert (m.proposals, m.pending, m.approval_rate, m.median_seconds_to_decision) == (
        0,
        0,
        None,
        None,
    )


def test_metrics_reflect_the_audit_trail(session_factory):
    with session_factory() as db:
        a = _add_proposal(db, 1, "sales_inquiry", "create_record", 0.9)
        b = _add_proposal(db, 2, "support_request", "update_record", 0.7)
        c = _add_proposal(db, 3, "other", "escalate", 0.0)
        _add_proposal(db, 4, "support_request", "create_record", 0.9)  # still pending
        _decide(db, a, "approved", 30, success=True)
        _decide(db, b, "approved", 90, success=False)
        _decide(db, c, "rejected", 60)
        db.commit()

        m = compute_metrics(db)

    assert (m.emails_processed, m.proposals, m.decided, m.pending) == (4, 4, 3, 1)
    assert (m.approved, m.rejected) == (2, 1)
    assert m.approval_rate == pytest.approx(2 / 3)
    assert m.median_seconds_to_decision == 60
    assert (m.executed, m.execution_failures) == (1, 1)
    assert m.by_action_type == {"create_record": 2, "update_record": 1, "escalate": 1}
    assert m.by_intent == {"sales_inquiry": 1, "support_request": 2, "other": 1}
    assert m.confidence_distribution == {"0–50%": 1, "50–80%": 1, "80–100%": 2}


def test_metrics_page_renders_and_requires_login(session_factory):
    with session_factory() as db:
        a = _add_proposal(db, 1, "sales_inquiry", "create_record", 0.9)
        _decide(db, a, "approved", 45, success=True)
        db.commit()

    def override_db():
        with session_factory() as session:
            yield session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    assert client.get("/metrics").status_code == 401

    app.dependency_overrides[require_user] = lambda: User(username="t", password_hash="x")
    page = client.get("/metrics")
    assert page.status_code == 200
    assert "100%" in page.text and "45s" in page.text


def test_edited_approvals_are_counted_as_approved_and_measured_separately(session_factory):
    with session_factory() as db:
        for n, decision in enumerate(["approved", "edited", "edited", "rejected"], start=1):
            _decide(db, _add_proposal(db, n, "support_request", "create_record", 0.9), decision, 30)
        db.commit()
        m = compute_metrics(db)

    assert (m.approved, m.edited, m.rejected) == (3, 2, 1)  # an edited approval is still approved
    assert m.edit_rate == pytest.approx(2 / 3)
    assert m.approval_rate == pytest.approx(3 / 4)


def test_edit_rate_is_empty_until_something_is_approved(session_factory):
    with session_factory() as db:
        _decide(db, _add_proposal(db, 1, "other", "create_record", 0.9), "rejected", 30)
        db.commit()
        assert compute_metrics(db).edit_rate is None
