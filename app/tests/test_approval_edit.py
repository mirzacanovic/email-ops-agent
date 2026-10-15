from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.approval.edits import EditError, editable_fields, parse_edits
from app.approval.routes import router
from app.audit.models import (
    ApprovalDecision,
    Base,
    EmailMessage,
    ExecutionResult,
    ProposedAction,
    User,
)
from app.auth.deps import require_user
from app.connectors.base import SystemConnector
from app.db.session import get_db
from app.dependencies import get_espocrm_connector, get_plane_connector

PLANE_FIELDS: dict[str, Any] = {
    "name": "Export button throws an error",
    "description_html": "Hi team,<br>The export is broken.",
    "priority": "high",
    "external_id": "jordan@example.com",
    "external_source": "email-ops-agent",
}


# --- validation (pure) ---


def test_only_unprotected_text_fields_are_editable():
    names = [f.name for f in editable_fields({**PLANE_FIELDS, "count": 3})]
    assert names == ["name", "description_html", "priority"]  # not external_*, not the int


def test_priority_is_a_choice_and_description_is_multiline():
    by_name = {f.name: f for f in editable_fields(PLANE_FIELDS)}
    assert by_name["priority"].choices == ["urgent", "high", "medium", "low", "none"]
    assert by_name["description_html"].multiline and not by_name["name"].multiline


def test_parse_edits_returns_only_what_changed():
    form = {"edit__name": "A better title", "edit__priority": "high", "unrelated": "x"}
    assert parse_edits(form, PLANE_FIELDS) == {"name": "A better title"}


def test_untouched_form_is_not_an_edit_even_with_browser_line_endings():
    proposed = {"description": "line one\nline two"}
    assert parse_edits({"edit__description": "line one\r\nline two"}, proposed) == {}


@pytest.mark.parametrize(
    ("form", "message"),
    [
        ({"edit__name": "   "}, "cannot be empty"),
        ({"edit__external_id": "x@y.com"}, "cannot be edited"),
        ({"edit__external_source": "other"}, "cannot be edited"),
        ({"edit__not_a_field": "x"}, "cannot be edited"),
        ({"edit__priority": "yesterday"}, "must be one of"),
        ({"edit__name": "x" * 10_001}, "too long"),
    ],
)
def test_bad_edits_are_rejected(form, message):
    with pytest.raises(EditError, match=message):
        parse_edits(form, PLANE_FIELDS)


# --- routes ---


class FakeConnector(SystemConnector):
    def __init__(self) -> None:
        self.created: list[tuple[str, dict[str, Any]]] = []
        self.updated: list[tuple[str, str, dict[str, Any]]] = []

    async def search_records(self, entity_type, query):
        return []

    async def create_record(self, entity_type, fields):
        self.created.append((entity_type, dict(fields)))
        return {"id": "new-1"}

    async def update_record(self, entity_type, record_id, fields):
        self.updated.append((entity_type, record_id, dict(fields)))
        return {"id": record_id}

    async def get_schema(self, entity_type):
        return {}


@pytest.fixture
def env():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    plane = FakeConnector()

    def override_db():
        with Session() as session:
            yield session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_user] = lambda: User(username="alice", password_hash="x")
    app.dependency_overrides[get_plane_connector] = lambda: plane
    app.dependency_overrides[get_espocrm_connector] = lambda: FakeConnector()

    def seed(fields=None, action_type="create_record", record_id=None) -> str:
        with Session() as db:
            email = EmailMessage(
                source_message_id=f"m{db.query(EmailMessage).count()}",
                sender="s@x.com",
                subject="s",
                body="b",
                received_at=datetime.now(timezone.utc),
            )
            db.add(email)
            db.flush()
            action = ProposedAction(
                email_message_id=email.id,
                action_type=action_type,
                target_system="plane" if action_type != "escalate" else "none",
                entity_type="issues:p" if action_type != "escalate" else "n/a",
                record_id=record_id,
                fields=PLANE_FIELDS if fields is None else fields,
                candidate_matches=[],
                rationale="r",
                confidence=0.8,
            )
            db.add(action)
            db.commit()
            return action.id

    class Env:
        client = TestClient(app)
        connector = plane

        @staticmethod
        def decisions():
            with Session() as db:
                return list(db.scalars(select(ApprovalDecision)))

        @staticmethod
        def executions():
            with Session() as db:
                return list(db.scalars(select(ExecutionResult)))

        @staticmethod
        def stored_fields(action_id):
            with Session() as db:
                return db.get(ProposedAction, action_id).fields

    Env.seed = staticmethod(seed)  # type: ignore[attr-defined]
    return Env


def test_plain_approve_sends_the_proposal_unchanged(env):
    action_id = env.seed()
    r = env.client.post(f"/approvals/{action_id}/approve", follow_redirects=False)
    assert r.status_code == 303
    (decision,) = env.decisions()
    assert (decision.decision, decision.edited_fields, decision.approver) == ("approved", None, "alice")
    assert env.connector.created == [("issues:p", PLANE_FIELDS)]


def test_edits_are_sent_recorded_and_the_original_proposal_is_kept(env):
    action_id = env.seed()
    r = env.client.post(
        f"/approvals/{action_id}/approve",
        data={"edit__name": "CSV export fails on reports page", "edit__priority": "urgent"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    (decision,) = env.decisions()
    assert decision.decision == "edited"
    assert decision.edited_fields == {"name": "CSV export fails on reports page", "priority": "urgent"}

    ((_, sent),) = env.connector.created
    assert sent["name"] == "CSV export fails on reports page" and sent["priority"] == "urgent"
    assert sent["description_html"] == PLANE_FIELDS["description_html"]  # untouched stays
    assert sent["external_id"] == "jordan@example.com"  # pipeline bookkeeping preserved
    assert env.stored_fields(action_id) == PLANE_FIELDS  # audit: what the model proposed
    assert [e.success for e in env.executions()] == [True]


def test_submitting_the_form_without_changes_is_a_plain_approval(env):
    action_id = env.seed()
    data = {f"edit__{k}": v for k, v in PLANE_FIELDS.items() if not k.startswith("external")}
    data["edit__description_html"] = data["edit__description_html"].replace("\n", "\r\n")
    env.client.post(f"/approvals/{action_id}/approve", data=data, follow_redirects=False)
    (decision,) = env.decisions()
    assert (decision.decision, decision.edited_fields) == ("approved", None)


def test_editing_an_update_sends_the_edited_text_to_the_existing_record(env):
    action_id = env.seed(
        fields={"description_html": "original<br>--- Follow-up ---<br>Jordan"},
        action_type="update_record",
        record_id="issue-42",
    )
    env.client.post(
        f"/approvals/{action_id}/approve",
        data={"edit__description_html": "original<br>--- Follow-up ---<br>Any update on the CSV export?"},
        follow_redirects=False,
    )
    assert env.connector.updated == [
        ("issues:p", "issue-42",
         {"description_html": "original<br>--- Follow-up ---<br>Any update on the CSV export?"})
    ]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"edit__name": ""}, "cannot be empty"),
        ({"edit__external_id": "attacker@example.com"}, "cannot be edited"),
        ({"edit__priority": "whenever"}, "must be one of"),
    ],
)
def test_rejected_edit_writes_nothing_and_explains_why(env, data, message):
    action_id = env.seed()
    r = env.client.post(f"/approvals/{action_id}/approve", data=data, follow_redirects=False)
    assert r.status_code == 422
    assert message in r.text
    assert env.decisions() == [] and env.connector.created == []


def test_rejected_edit_keeps_what_the_reviewer_typed(env):
    action_id = env.seed()
    r = env.client.post(
        f"/approvals/{action_id}/approve",
        data={"edit__name": "", "edit__description_html": "My careful rewrite of the description"},
    )
    assert r.status_code == 422
    assert "My careful rewrite of the description" in r.text


def test_deciding_twice_is_refused_so_nothing_executes_twice(env):
    action_id = env.seed()
    assert env.client.post(f"/approvals/{action_id}/approve", follow_redirects=False).status_code == 303
    assert env.client.post(f"/approvals/{action_id}/approve", follow_redirects=False).status_code == 409
    assert env.client.post(f"/approvals/{action_id}/reject", follow_redirects=False).status_code == 409
    assert len(env.connector.created) == 1 and len(env.decisions()) == 1


def test_rejecting_then_approving_is_refused(env):
    action_id = env.seed()
    assert env.client.post(f"/approvals/{action_id}/reject", follow_redirects=False).status_code == 303
    assert env.client.post(f"/approvals/{action_id}/approve", follow_redirects=False).status_code == 409
    assert env.connector.created == []


def test_page_offers_prefilled_editing_for_text_fields_only(env):
    env.seed()
    env.seed(fields={}, action_type="escalate")
    html = env.client.get("/approvals").text
    assert html.count("Edit before approving") == 1  # the escalation has nothing to edit
    assert 'name="edit__name" value="Export button throws an error"' in html
    assert '<option value="high" selected>' in html
    assert "edit__external_id" not in html and "edit__external_source" not in html


def test_field_values_are_escaped_in_the_edit_form(env):
    env.seed(fields={"name": '"><script>alert(1)</script>'})
    html = env.client.get("/approvals").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
