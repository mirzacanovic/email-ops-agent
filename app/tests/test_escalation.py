from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.audit.models import Base, ProposedAction
from app.ingestion.inbox_poller import CLASSIFY_CONFIDENCE_FLOOR, _process_one
from app.llm.base import LLMClient
from app.pipeline.classify import INTENTS


class FakeLLM(LLMClient):
    """Returns a fixed classification; extract is never reached on the
    escalation paths under test (an extract call would raise)."""

    def __init__(self, intent: str, confidence: float) -> None:
        self._result = {"intent": intent, "confidence": confidence}

    async def complete_json(
        self, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]
    ) -> dict[str, Any]:
        if "intent" not in json_schema.get("properties", {}):
            raise AssertionError("extract must not run for an escalated email")
        return self._result


MESSAGE = {
    "id": "m1",
    "from": "someone@example.com",
    "subject": "hello",
    "body": "body",
    "received_at": "2026-09-20T09:00:00Z",
}


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session


async def _proposal(db, intent: str, confidence: float) -> ProposedAction:
    await _process_one(db, FakeLLM(intent, confidence), None, None, "p", MESSAGE)  # type: ignore[arg-type]
    db.commit()
    return db.scalars(select(ProposedAction)).one()


def test_other_is_a_valid_classifier_intent():
    assert "other" in INTENTS


async def test_other_intent_escalates(db):
    proposal = await _proposal(db, "other", 0.95)
    assert proposal.action_type == "escalate"
    assert "'other'" in proposal.rationale


async def test_low_confidence_routable_intent_escalates_with_the_reason(db):
    proposal = await _proposal(db, "sales_inquiry", CLASSIFY_CONFIDENCE_FLOOR - 0.1)
    assert proposal.action_type == "escalate"
    assert proposal.target_system == "none"
    assert "sure" in proposal.rationale and "sales_inquiry" in proposal.rationale
