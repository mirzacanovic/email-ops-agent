from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from app.connectors.base import SystemConnector


@dataclass
class CandidateMatch:
    record: dict[str, Any]
    match_reason: str  # "exact_email" | "fuzzy_name"
    score: float  # 0..1, 1.0 = exact


async def find_candidate_matches(
    connector: SystemConnector,
    entity_type: str,
    extracted_fields: dict[str, Any],
    sender_email: str,
) -> list[CandidateMatch]:
    """Search `connector` for existing records that might already
    represent the sender of this email.

    Two passes, most-confident first:
      1. Exact match on the sender's email address — the reliable case.
      2. Fuzzy match on company/account name, in case the sender used a
         different address than what's on file (a colleague, an alias,
         a personal address) — narrowed server-side via `_fulltext`
         where the connector supports it, then scored locally so the
         caller can see *how* close each hit was.

    Every candidate from both passes is returned, not just the top hit,
    so the audit trail (and a human reviewer) can see what else was
    close before the propose stage picks one.

    TODO(phase-1/2): this exact-email + fuzzy-account-name scheme fits
    CRM-style entities (EspoCRM Contact/Lead). Matching Plane issues
    (e.g. "is this the same bug already reported") needs a different
    scheme — keyword search against issue titles — reusing the same
    CandidateMatch shape.
    """
    candidates: list[CandidateMatch] = []

    exact_matches = await connector.search_records(entity_type, {"emailAddress": sender_email})
    candidates.extend(
        CandidateMatch(record=record, match_reason="exact_email", score=1.0)
        for record in exact_matches
    )

    account_name = extracted_fields.get("accountName")
    if account_name and not exact_matches:
        fuzzy_matches = await connector.search_records(entity_type, {"_fulltext": account_name})
        for record in fuzzy_matches:
            candidate_name = record.get("accountName") or record.get("name", "")
            score = _name_similarity(account_name, candidate_name)
            candidates.append(
                CandidateMatch(record=record, match_reason="fuzzy_name", score=score)
            )

    return sorted(candidates, key=lambda c: c.score, reverse=True)


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()
