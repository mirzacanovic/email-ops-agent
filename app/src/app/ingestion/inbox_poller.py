"""Fetches new messages from the email simulator and runs each through
classify -> extract -> match -> propose, persisting an audit row at
every stage. Exposed via POST /ingest/poll (app/src/app/ingestion/routes.py)
rather than a background loop, so a demo can trigger it on cue.
"""

import logging
from dataclasses import asdict
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.models import EmailMessage, ExtractionResult, ProposedAction
from app.connectors.base import SystemConnector
from app.llm.base import LLMClient
from app.pipeline.classify import classify
from app.pipeline.extract import extract
from app.pipeline.match import CandidateMatch, find_candidate_matches
from app.pipeline.propose import propose_action

logger = logging.getLogger(__name__)

# The single place an intent is mapped to the system it acts on. An
# intent with no entry here (e.g. "project_status_question" — Phase 1
# has no Plane issue-matching yet, see match.py's TODO) falls through to
# propose.py's escalation path instead of guessing.
INTENT_ROUTES: dict[str, str] = {
    "sales_inquiry": "espocrm",
    "support_request": "plane",
}


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def poll_and_process(
    db: Session,
    llm: LLMClient,
    espocrm: SystemConnector,
    plane: SystemConnector,
    plane_project_id: str,
    email_simulator_url: str,
) -> int:
    """Returns the number of messages successfully processed.

    Each message is committed independently, so one failure (a malformed
    email, a transient connector error) is logged and skipped rather
    than losing progress on — or blocking — the rest of the batch.
    """
    since = db.scalar(select(func.max(EmailMessage.received_at)))

    async with httpx.AsyncClient(base_url=email_simulator_url, timeout=10.0) as client:
        params = {"since": since.isoformat()} if since else {}
        response = await client.get("/messages", params=params)
        response.raise_for_status()
        messages = response.json()

    processed = 0
    for message in messages:
        try:
            await _process_one(db, llm, espocrm, plane, plane_project_id, message)
            db.commit()
            processed += 1
        except Exception:
            db.rollback()
            logger.exception("Failed to process message %s", message.get("id"))

    return processed


async def _process_one(
    db: Session,
    llm: LLMClient,
    espocrm: SystemConnector,
    plane: SystemConnector,
    plane_project_id: str,
    message: dict[str, Any],
) -> None:
    email = EmailMessage(
        source_message_id=message["id"],
        sender=message["from"],
        subject=message["subject"],
        body=message["body"],
        received_at=_parse_iso(message["received_at"]),
    )
    db.add(email)
    db.flush()  # populate email.id for the FK rows below

    classification = await classify(llm, email.subject, email.body)
    target_system = INTENT_ROUTES.get(classification.intent)

    entity_type: str | None = None
    extracted_fields: dict[str, Any] = {}
    candidate_matches: list[CandidateMatch] = []

    if target_system == "espocrm":
        entity_type = "Lead"
        schema = await espocrm.get_schema(entity_type)
        extracted_fields = await extract(
            llm, email.subject, email.body, classification.intent, schema
        )
        candidate_matches = await find_candidate_matches(
            espocrm, entity_type, extracted_fields, sender_email=email.sender
        )
    elif target_system == "plane":
        entity_type = f"issues:{plane_project_id}"
        schema = await plane.get_schema(entity_type)
        extracted_fields = await extract(
            llm, email.subject, email.body, classification.intent, schema
        )

    db.add(
        ExtractionResult(
            email_message_id=email.id,
            intent=classification.intent,
            intent_confidence=classification.confidence,
            extracted_fields=extracted_fields,
            model_raw_response={"classify": classification.raw, "extract": extracted_fields},
        )
    )

    proposed = await propose_action(
        classification.intent, target_system, entity_type, extracted_fields, candidate_matches
    )
    db.add(
        ProposedAction(
            email_message_id=email.id,
            action_type=proposed.action_type,
            target_system=proposed.target_system,
            entity_type=proposed.entity_type,
            record_id=proposed.record_id,
            fields=proposed.fields,
            candidate_matches=[asdict(m) for m in candidate_matches],
            rationale=proposed.rationale,
            confidence=proposed.confidence,
        )
    )
