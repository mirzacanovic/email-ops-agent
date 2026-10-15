from typing import Any

import pytest

from app.connectors.base import SystemConnector
from app.pipeline.match import (
    _name_similarity,
    find_candidate_matches,
    find_similar_issues,
    normalize_subject,
)


class FakeConnector(SystemConnector):
    """In-memory test double. Returns one canned response per
    `search_records` call, in call order, and records every call made —
    so match.py's control flow (which query goes out first, how many
    calls happen) is testable without real HTTP.
    """

    def __init__(self, responses: list[list[dict[str, Any]]]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def search_records(
        self, entity_type: str, query: dict[str, Any]
    ) -> list[dict[str, Any]]:
        self.calls.append((entity_type, dict(query)))
        return self._responses.pop(0)

    async def create_record(self, entity_type: str, fields: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    async def update_record(
        self, entity_type: str, record_id: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        raise NotImplementedError

    async def get_schema(self, entity_type: str) -> dict[str, Any]:
        raise NotImplementedError


def test_name_similarity_identical_strings():
    assert _name_similarity("Acme Inc", "Acme Inc") == 1.0


def test_name_similarity_ignores_case_and_surrounding_whitespace():
    assert _name_similarity("  Acme Inc  ", "acme inc") == 1.0


async def test_exact_email_match_short_circuits_the_fuzzy_pass():
    connector = FakeConnector(responses=[[{"id": "c1", "emailAddress": "a@b.com"}]])
    matches = await find_candidate_matches(
        connector, "Contact", extracted_fields={"accountName": "Acme"}, sender_email="a@b.com"
    )
    assert len(matches) == 1
    assert matches[0].match_reason == "exact_email"
    assert matches[0].score == 1.0
    assert len(connector.calls) == 1  # the fuzzy pass never ran


async def test_falls_back_to_fuzzy_account_name_when_no_exact_email_match():
    connector = FakeConnector(
        responses=[
            [],  # exact-email pass: nothing
            [{"id": "c2", "accountName": "Acme Incorporated"}],  # fuzzy pass
        ]
    )
    matches = await find_candidate_matches(
        connector,
        "Contact",
        extracted_fields={"accountName": "Acme Inc"},
        sender_email="new@b.com",
    )
    assert len(matches) == 1
    assert matches[0].match_reason == "fuzzy_name"
    assert 0 < matches[0].score < 1
    assert connector.calls[1] == ("Contact", {"_fulltext": "Acme Inc"})


async def test_find_similar_issues_scores_and_ranks_by_title_similarity():
    connector = FakeConnector(
        responses=[
            [
                {"id": "i1", "name": "Totally different issue"},
                {"id": "i2", "name": "Export button throws an error"},
            ]
        ]
    )
    matches = await find_similar_issues(
        connector,
        "issues:proj-1",
        candidate_title="Export button throws an error",
        sender_email="jordan@x.com",
    )
    assert matches[0].record["id"] == "i2"
    assert matches[0].score == 1.0
    assert matches[0].match_reason == "fuzzy_title"
    # scoped to this sender via external_id alone -- not external_source
    # too, which triggers a 404-on-no-match lookup mode on Plane's real
    # API instead of a normal filtered list (see match.py's docstring).
    assert connector.calls == [("issues:proj-1", {"external_id": "jordan@x.com"})]


# --- follow-up matching on the email's own subject (found in the rehearsal) ---

@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("Re: Export button throws an error", "Export button throws an error"),
        ("RE: re: Fwd: Export button", "Export button"),
        ("AW: Exportproblem", "Exportproblem"),
        ("WG: AW: Exportproblem", "Exportproblem"),
        ("Export button", "Export button"),
        ("Regarding exports", "Regarding exports"),  # "Re" inside a word is not a prefix
    ],
)
def test_normalize_subject(subject, expected):
    assert normalize_subject(subject) == expected


async def test_followup_matches_original_via_subject_even_when_model_title_differs():
    # Real values from the rehearsal: the model titled the follow-up
    # "CSV export issue", which scores only ~0.28 against the original issue
    # (threshold 0.55) -- the follow-up's own subject must rescue the match.
    original = {"id": "i1", "name": "Export button throws an error on the reports page"}
    connector = FakeConnector([[original]])

    without_subject = await find_similar_issues(
        FakeConnector([[original]]), "issues:p", "CSV export issue", sender_email="j@x.com"
    )
    assert without_subject[0].score < 0.55

    with_subject = await find_similar_issues(
        connector,
        "issues:p",
        "CSV export issue",
        sender_email="j@x.com",
        alt_titles=[normalize_subject("Re: Export button throws an error on the reports page")],
    )
    assert with_subject[0].score == pytest.approx(1.0)
