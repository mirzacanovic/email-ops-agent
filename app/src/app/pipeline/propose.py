from dataclasses import dataclass
from typing import Any

from app.connectors.plane import EXTERNAL_SOURCE
from app.pipeline.match import CandidateMatch

EXACT_MATCH_THRESHOLD = 0.95
AMBIGUOUS_MATCH_THRESHOLD = 0.6
SIMILAR_ISSUE_THRESHOLD = 0.55


@dataclass
class ProposedActionDraft:
    action_type: str  # "create_record" | "update_record" | "escalate"
    target_system: str  # "espocrm" | "plane" | "none"
    entity_type: str
    record_id: str | None  # set only for update_record
    fields: dict[str, Any]
    rationale: str
    confidence: float


async def propose_action(
    intent: str,
    target_system: str | None,
    entity_type: str | None,
    extracted_fields: dict[str, Any],
    candidate_matches: list[CandidateMatch],
    sender_email: str,
) -> ProposedActionDraft:
    """Decide what action to propose, given where the caller has already
    routed this intent (`target_system`/`entity_type` — see
    `ingestion.inbox_poller.INTENT_ROUTES`, the single place intents are
    mapped to systems) and what `match.find_candidate_matches` /
    `match.find_similar_issues` found.

    `target_system` is None when the intent has no route yet (e.g.
    "project_status_question", which would need its own handling) — that
    always escalates rather than guessing.
    """
    if target_system is None or entity_type is None:
        return ProposedActionDraft(
            action_type="escalate",
            target_system="none",
            entity_type="n/a",
            record_id=None,
            fields=extracted_fields,
            rationale=(
                f"Intent {intent!r} has no automated action defined yet — "
                "flagging for manual handling rather than guessing."
            ),
            confidence=0.0,
        )

    if target_system == "espocrm":
        return _propose_crm_action(target_system, entity_type, extracted_fields, candidate_matches)

    return _propose_plane_action(
        target_system, entity_type, extracted_fields, candidate_matches, sender_email
    )


def _propose_crm_action(
    target_system: str,
    entity_type: str,
    extracted_fields: dict[str, Any],
    candidate_matches: list[CandidateMatch],
) -> ProposedActionDraft:
    best = candidate_matches[0] if candidate_matches else None

    if best is not None and best.score >= EXACT_MATCH_THRESHOLD:
        return ProposedActionDraft(
            action_type="update_record",
            target_system=target_system,
            entity_type=entity_type,
            record_id=best.record.get("id"),
            fields=extracted_fields,
            rationale=(
                f"Matched an existing {entity_type} via {best.match_reason} "
                f"(score {best.score:.2f}); updating it with this email's details."
            ),
            confidence=best.score,
        )

    if best is not None and best.score >= AMBIGUOUS_MATCH_THRESHOLD:
        candidate_name = best.record.get("accountName", "?")
        return ProposedActionDraft(
            action_type="create_record",
            target_system=target_system,
            entity_type=entity_type,
            record_id=None,
            fields=extracted_fields,
            rationale=(
                f"No exact match, but a {entity_type} with {best.score:.2f} name "
                f"similarity exists ({candidate_name}) — proposing create, "
                "flagged low-confidence in case this is the same account "
                "under a different name."
            ),
            confidence=1 - best.score,
        )

    return ProposedActionDraft(
        action_type="create_record",
        target_system=target_system,
        entity_type=entity_type,
        record_id=None,
        fields=extracted_fields,
        rationale=f"No existing {entity_type} matched the sender's email or account name.",
        confidence=0.9,
    )


def _propose_plane_action(
    target_system: str,
    entity_type: str,
    extracted_fields: dict[str, Any],
    candidate_matches: list[CandidateMatch],
    sender_email: str,
) -> ProposedActionDraft:
    best = candidate_matches[0] if candidate_matches else None

    if best is not None and best.score >= SIMILAR_ISSUE_THRESHOLD:
        # Append rather than overwrite: a naive PATCH of description_html
        # with just the follow-up's content would destroy the original
        # bug report. candidate_matches is already scoped to this sender's
        # own prior issues (see find_similar_issues), so a title match
        # here is a real signal, not a coincidence across customers.
        existing_description = best.record.get("description_html") or ""
        follow_up = extracted_fields.get("description_html", "")
        merged_description = (
            f"{existing_description}<br><br>--- Follow-up email ---<br>{follow_up}"
            if follow_up
            else existing_description
        )
        return ProposedActionDraft(
            action_type="update_record",
            target_system=target_system,
            entity_type=entity_type,
            record_id=best.record.get("id"),
            fields={"description_html": merged_description},
            rationale=(
                f"Matched an existing issue from this sender "
                f"({best.record.get('name')!r}, title similarity {best.score:.2f}); "
                "appending this email as a follow-up instead of filing a duplicate."
            ),
            confidence=best.score,
        )

    # No close-enough prior issue from this sender: create a new one,
    # tagged so a later follow-up can find it the same way this one did.
    fields = dict(extracted_fields)
    fields["external_id"] = sender_email
    fields["external_source"] = EXTERNAL_SOURCE
    return ProposedActionDraft(
        action_type="create_record",
        target_system=target_system,
        entity_type=entity_type,
        record_id=None,
        fields=fields,
        rationale="No existing issue from this sender matched closely enough — creating a new one.",
        confidence=0.85,
    )
