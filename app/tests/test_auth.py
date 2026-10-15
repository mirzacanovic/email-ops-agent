from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import cli
from app.approval.routes import router as approval_router
from app.audit.models import ApprovalDecision, Base, EmailMessage, ProposedAction, User
from app.auth.passwords import hash_password, verify_password
from app.db.session import get_db
from app.dependencies import get_espocrm_connector, get_llm, get_plane_connector
from app.ingestion.routes import router as ingestion_router


def test_hash_verifies_and_is_salted():
    h1, h2 = hash_password("correct horse"), hash_password("correct horse")
    assert h1 != h2
    assert verify_password("correct horse", h1)
    assert not verify_password("wrong", h1)


def test_malformed_hash_never_verifies():
    assert not verify_password("x", "not-a-hash")
    assert not verify_password("x", "bcrypt$1$2$3$aa$bb")


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def client(session_factory):
    def override_db():
        with session_factory() as session:
            yield session

    app = FastAPI()
    app.include_router(approval_router)
    app.include_router(ingestion_router)
    app.dependency_overrides[get_db] = override_db
    for dep in (get_llm, get_espocrm_connector, get_plane_connector):
        app.dependency_overrides[dep] = lambda: None
    with session_factory() as db:
        cli.create_user(db, "alice", "alice-password")
    return TestClient(app)


def _seed_proposal(session_factory) -> str:
    with session_factory() as db:
        email = EmailMessage(
            source_message_id="m1",
            sender="s@example.com",
            subject="s",
            body="b",
            received_at=datetime.now(timezone.utc),
        )
        db.add(email)
        db.flush()
        action = ProposedAction(
            email_message_id=email.id,
            action_type="create_record",
            target_system="unknown",
            entity_type="x",
            fields={},
            candidate_matches=[],
            rationale="r",
            confidence=0.5,
        )
        db.add(action)
        db.commit()
        return action.id


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/approvals"),
        ("post", "/approvals/abc/approve"),
        ("post", "/approvals/abc/reject"),
        ("post", "/ingest/poll"),
        ("post", "/ingest/poll-form"),
    ],
)
def test_protected_routes_require_credentials(client, method, path):
    r = getattr(client, method)(path)
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Basic")


def test_wrong_password_and_unknown_user_are_both_rejected(client):
    assert client.get("/approvals", auth=("alice", "nope")).status_code == 401
    assert client.get("/approvals", auth=("mallory", "alice-password")).status_code == 401


def test_valid_credentials_are_accepted(client):
    assert client.get("/approvals", auth=("alice", "alice-password")).status_code == 200


def test_no_users_means_nobody_gets_in(session_factory):
    app = FastAPI()
    app.include_router(approval_router)
    app.dependency_overrides[get_db] = lambda: session_factory()
    assert TestClient(app).get("/approvals", auth=("alice", "x")).status_code == 401


def test_decision_records_the_authenticated_user_as_approver(client, session_factory):
    action_id = _seed_proposal(session_factory)
    r = client.post(
        f"/approvals/{action_id}/reject", auth=("alice", "alice-password"), follow_redirects=False
    )
    assert r.status_code == 303
    with session_factory() as db:
        decision = db.scalars(select(ApprovalDecision)).one()
        assert (decision.decision, decision.approver) == ("rejected", "alice")


def test_cli_create_user_rejects_duplicates_and_set_password_requires_user(session_factory):
    with session_factory() as db:
        cli.create_user(db, "bob", "bob-password")
        with pytest.raises(SystemExit, match="already exists"):
            cli.create_user(db, "bob", "other-password")
        with pytest.raises(SystemExit, match="No such user"):
            cli.set_password(db, "nobody", "whatever-pw")
        cli.set_password(db, "bob", "new-password")
        stored = _get(db, "bob")
        assert verify_password("new-password", stored.password_hash)
        assert not verify_password("bob-password", stored.password_hash)


def _get(db: Session, username: str) -> User:
    return db.scalars(select(User).where(User.username == username)).one()
