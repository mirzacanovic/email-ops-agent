from typing import Any

from app.connectors.base import SystemConnector
from app.pipeline.propose import ProposedActionDraft


async def execute_action(
    connector: SystemConnector | None, action: ProposedActionDraft
) -> dict[str, Any]:
    """Execute an approved action.

    Must only ever be called with an action that has a corresponding
    approved `ApprovalDecision` row — the caller (approval routes) is
    responsible for enforcing that and for turning a raised exception
    into a failed `ExecutionResult` row rather than a crashed request.

    `connector` is None only for `escalate` actions, which never call an
    API — approval just acknowledges that a human will handle it outside
    this system.
    """
    if action.action_type == "escalate":
        return {"note": "no API call made — escalated for manual handling"}

    if connector is None:
        raise ValueError(f"No connector configured for target_system {action.target_system!r}")

    if action.action_type == "create_record":
        return await connector.create_record(action.entity_type, action.fields)
    if action.action_type == "update_record":
        if action.record_id is None:
            raise ValueError("update_record action requires record_id")
        return await connector.update_record(
            action.entity_type, action.record_id, action.fields
        )
    raise ValueError(f"Unknown action_type: {action.action_type}")
