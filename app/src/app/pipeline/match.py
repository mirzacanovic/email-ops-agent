from typing import Any

from app.connectors.base import SystemConnector


async def find_candidate_matches(
    connector: SystemConnector,
    entity_type: str,
    extracted_fields: dict[str, Any],
) -> list[dict[str, Any]]:
    """Search `connector` for existing records that might already
    represent the sender/subject of this email.

    TODO(phase-1): start with an exact match on email address, then add
    fuzzy name matching for dedup (e.g. "Acme Inc" vs "Acme, Inc."). Log
    every candidate considered — not just the winner — to the audit
    trail, so a human reviewer can see what else was close.
    """
    raise NotImplementedError
