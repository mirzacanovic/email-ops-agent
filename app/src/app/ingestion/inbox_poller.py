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
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.models import EmailMessage, ExtractionResult, ProposedAction
from app.connectors.base import SystemConnector
from app.llm.base import LLMClient
from app.pipeline.classify import classify
from app.pipeline.extract import extract
from app.pipeline.match import (
    CandidateMatch,
    find_candidate_matches,
    find_similar_issues,
    normalize_subject,
)
from app.pipeline.propose import propose_action

logger = logging.getLogger(__name__)

# The single place an intent is mapped to the system it acts on. An
# intent with no entry here falls through to propose.py's escalation
# path instead of guessing. "project_status_question" routes to Plane
# too, not just "support_request" -- a "any update on this?" follow-up
# is exactly what find_similar_issues (see pipeline/match.py) exists to
# match back to the original issue instead of filing a duplicate.
INTENT_ROUTES: dict[str, str] = {
    "sales_inquiry": "espocrm",
    "support_request": "plane",
    "project_status_question": "plane",
}


# Below this classifier confidence the email is escalated to a human rather
# than acted on, even if its intent has a route. Deliberately conservative:
# a wrongly-routed CRM/Plane action costs more than one extra manual review.
CLASSIFY_CONFIDENCE_FLOOR = 0.5


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _fetch_messages(email_simulator_url: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(base_url=email_simulator_url, timeout=10.0) as client:
        response = await client.get("/messages")
        response.raise_for_status()
        return response.json()


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

    "Already processed" is decided per message (by `source_message_id`),
    not by a received_at watermark: a failed message is rolled back and
    leaves no row, so it is simply fetched and retried on the next poll
    even after a later message has succeeded.
    """
    messages = await _fetch_messages(email_simulator_url)
    already_processed = set(db.scalars(select(EmailMessage.source_message_id)))
    messages = [m for m in messages if m["id"] not in already_processed]

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
    escalation_reason: str | None = None
    if target_system is not None and classification.confidence < CLASSIFY_CONFIDENCE_FLOOR:
        escalation_reason = (
            f"Classifier was only {classification.confidence:.0%} sure this is a "
            f"{classification.intent!r} (floor is {CLASSIFY_CONFIDENCE_FLOOR:.0%}) — "
            "flagging for manual handling rather than guessing."
        )
        target_system = None

    entity_type: str | None = None
    extracted_fields: dict[str, Any] = {}
    candidate_matches: list[CandidateMatch] = []

    if target_system == "espocrm":
        entity_type = "Lead"
        schema = await espocrm.get_schema(entity_type)
        extracted_fields = await extract(
            llm, email.subject, email.body, email.sender, classification.intent, schema
        )
        candidate_matches = await find_candidate_matches(
            espocrm, entity_type, extracted_fields, sender_email=email.sender
        )
    elif target_system == "plane":
        entity_type = f"issues:{plane_project_id}"
        schema = await plane.get_schema(entity_type)
        extracted_fields = await extract(
            llm, email.subject, email.body, email.sender, classification.intent, schema
        )
        candidate_matches = await find_similar_issues(
            plane,
            entity_type,
            extracted_fields.get("name", email.subject),
            sender_email=email.sender,
            alt_titles=[normalize_subject(email.subject)],
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
        classification.intent,
        target_system,
        entity_type,
        extracted_fields,
        candidate_matches,
        sender_email=email.sender,
        escalation_reason=escalation_reason,
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
