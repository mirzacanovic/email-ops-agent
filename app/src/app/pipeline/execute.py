from typing import Any

from app.connectors.base import SystemConnector
from app.pipeline.propose import ProposedActionDraft


async def execute_action(
    connector: SystemConnector, action: ProposedActionDraft
) -> dict[str, Any]:
    """Execute an approved action through `connector`.

    Must only ever be called with an action that has a corresponding
    approved `ApprovalDecision` row — the caller (approval routes) is
    responsible for enforcing that, this function assumes it's already
    true. TODO(phase-1): wrap in a try/except that writes a failed
    ExecutionResult row instead of raising, so failures show up in the
    audit trail rather than crashing the request.
    """
    if action.action_type == "create_record":
        return await connector.create_record(action.entity_type, action.fields)
    if action.action_type == "update_record":
        if action.record_id is None:
            raise ValueError("update_record action requires record_id")
        return await connector.update_record(
            action.entity_type, action.record_id, action.fields
        )
    raise ValueError(f"Unknown action_type: {action.action_type}")
