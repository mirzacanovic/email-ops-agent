from dataclasses import dataclass
from typing import Any

from app.pipeline.match import CandidateMatch


@dataclass
class ProposedActionDraft:
    action_type: str  # e.g. "create_record" | "update_record"
    target_system: str  # "espocrm" | "plane"
    entity_type: str
    record_id: str | None  # set only for update_record
    fields: dict[str, Any]
    rationale: str
    confidence: float


async def propose_action(
    intent: str,
    extracted_fields: dict[str, Any],
    candidate_matches: list[CandidateMatch],
) -> ProposedActionDraft:
    """Decide what action to propose given the extraction + search results.

    TODO(phase-1): simple rule first (no match -> create, exact match ->
    update, ambiguous matches -> low confidence + flag for escalation),
    then consider letting Claude choose among a fixed action menu with
    the rationale as part of its output. This draft is what gets shown
    to the human approver, unexecuted, until they approve it.
    """
    raise NotImplementedError
