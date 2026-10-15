import re
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from app.connectors.base import SystemConnector


@dataclass
class CandidateMatch:
    record: dict[str, Any]
    match_reason: str  # "exact_email" | "fuzzy_name" | "fuzzy_title"
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

    This exact-email + fuzzy-account-name scheme fits CRM-style entities
    (EspoCRM Contact/Lead). See `find_similar_issues` below for Plane's
    different matching scheme.
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


_SUBJECT_PREFIX = re.compile(r"^\s*((re|fwd?|aw|wg)\s*:\s*)+", re.IGNORECASE)


def normalize_subject(subject: str) -> str:
    """Strip reply/forward prefixes ("Re:", "Fwd:", German "AW:"/"WG:") so a
    follow-up's subject compares equal to the original email's subject."""
    return _SUBJECT_PREFIX.sub("", subject).strip()


async def find_similar_issues(
    connector: SystemConnector,
    entity_type: str,
    candidate_title: str,
    sender_email: str,
    alt_titles: Sequence[str] = (),
) -> list[CandidateMatch]:
    """Search for existing Plane issues that might already cover the same
    problem as a new support request, so a follow-up ("any update on the
    CSV export bug?") updates the existing issue instead of filing a
    duplicate.

    Plane's work-items list endpoint has no full-text search (no
    `_fulltext`-equivalent — PlaneConnector doesn't support that
    convention), so this narrows to a small candidate set a different
    way: every issue this pipeline previously created is tagged with
    `external_id=<sender email>` (see propose.py's use of
    `connectors.plane.EXTERNAL_SOURCE`) at creation time, and Plane's
    list endpoint documents `external_id` as a real, indexed filter — so
    this fetches only *this sender's* prior issues, then scores each
    one's title against `candidate_title` locally. Restricting to the
    same sender first avoids matching one customer's bug report against
    a different customer's similarly-worded one.

    Filters on `external_id` alone, not `external_id` + `external_source`
    together: confirmed empirically against the live API that combining
    both switches the endpoint from list/filter semantics (200, possibly
    empty) to single-resource lookup semantics (404 when nothing matches)
    — undocumented, but reproducible. `external_source` is still set at
    creation time as informational tagging, just not used as a filter.

    Each issue is scored against `candidate_title` and every entry in
    `alt_titles`, keeping the best score. Callers pass the email's
    normalized subject as an alternative: the model-written title is a
    paraphrase that can differ a lot from the original issue's title
    ("CSV export issue" vs "Export button throws an error..." scores 0.28),
    while the follow-up's own subject usually matches it almost exactly.
    """
    prior_issues = await connector.search_records(entity_type, {"external_id": sender_email})
    candidates = [
        CandidateMatch(
            record=issue,
            match_reason="fuzzy_title",
            score=max(
                _name_similarity(title, issue.get("name", ""))
                for title in (candidate_title, *alt_titles)
            ),
        )
        for issue in prior_issues
    ]
    return sorted(candidates, key=lambda c: c.score, reverse=True)


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()
