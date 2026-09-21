from dataclasses import dataclass
from typing import Any

from app.pipeline.match import CandidateMatch

EXACT_MATCH_THRESHOLD = 0.95
AMBIGUOUS_MATCH_THRESHOLD = 0.6


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
) -> ProposedActionDraft:
    """Decide what action to propose, given where the caller has already
    routed this intent (`target_system`/`entity_type` — see
    `ingestion.inbox_poller.INTENT_ROUTES`, the single place intents are
    mapped to systems) and what `match.find_candidate_matches` found.

    `target_system` is None when the intent has no route yet (e.g.
    "project_status_question" — Phase 1 has no Plane issue-matching, see
    match.py's TODO) — that always escalates rather than guessing.
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

    # target_system == "plane": Phase 1 has no issue-matching, so this
    # always proposes creating a new issue. Confidence is capped below
    # the CRM no-match case to reflect the real risk of filing a
    # duplicate against an issue that already exists.
    return ProposedActionDraft(
        action_type="create_record",
        target_system=target_system,
        entity_type=entity_type,
        record_id=None,
        fields=extracted_fields,
        rationale=(
            "Support request — creating a Plane issue "
            "(no dedup against existing issues implemented yet)."
        ),
        confidence=0.7,
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
