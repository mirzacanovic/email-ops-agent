import pytest

from app.pipeline.match import CandidateMatch
from app.pipeline.propose import propose_action


async def test_escalates_when_intent_has_no_route():
    result = await propose_action(
        intent="project_status_question",
        target_system=None,
        entity_type=None,
        extracted_fields={},
        candidate_matches=[],
        sender_email="someone@example.com",
    )
    assert result.action_type == "escalate"
    assert result.target_system == "none"
    assert result.confidence == 0.0


async def test_espocrm_creates_when_no_match():
    result = await propose_action(
        intent="sales_inquiry",
        target_system="espocrm",
        entity_type="Lead",
        extracted_fields={"firstName": "Alex"},
        candidate_matches=[],
        sender_email="alex@example.com",
    )
    assert result.action_type == "create_record"
    assert result.record_id is None
    assert result.confidence == 0.9


async def test_espocrm_updates_on_exact_email_match():
    match = CandidateMatch(record={"id": "lead-123"}, match_reason="exact_email", score=1.0)
    result = await propose_action(
        intent="sales_inquiry",
        target_system="espocrm",
        entity_type="Lead",
        extracted_fields={"firstName": "Alex"},
        candidate_matches=[match],
        sender_email="alex@example.com",
    )
    assert result.action_type == "update_record"
    assert result.record_id == "lead-123"
    assert result.confidence == 1.0


async def test_espocrm_ambiguous_match_creates_but_flags_low_confidence():
    match = CandidateMatch(
        record={"id": "lead-999", "accountName": "Acme Inc"},
        match_reason="fuzzy_name",
        score=0.7,
    )
    result = await propose_action(
        intent="sales_inquiry",
        target_system="espocrm",
        entity_type="Lead",
        extracted_fields={"accountName": "Acme, Inc."},
        candidate_matches=[match],
        sender_email="new@example.com",
    )
    assert result.action_type == "create_record"
    assert result.record_id is None
    assert result.confidence == pytest.approx(0.3)
    assert "Acme Inc" in result.rationale


async def test_plane_creates_new_issue_and_tags_external_id():
    result = await propose_action(
        intent="support_request",
        target_system="plane",
        entity_type="issues:proj-1",
        extracted_fields={"name": "Bug title", "description_html": "details"},
        candidate_matches=[],
        sender_email="reporter@example.com",
    )
    assert result.action_type == "create_record"
    assert result.fields["name"] == "Bug title"
    assert result.fields["external_id"] == "reporter@example.com"
    assert result.fields["external_source"] == "email-ops-agent"


async def test_plane_appends_followup_to_matched_issue_instead_of_overwriting():
    match = CandidateMatch(
        record={"id": "issue-1", "name": "Bug title", "description_html": "original text"},
        match_reason="fuzzy_title",
        score=0.8,
    )
    result = await propose_action(
        intent="project_status_question",
        target_system="plane",
        entity_type="issues:proj-1",
        extracted_fields={"description_html": "any update?"},
        candidate_matches=[match],
        sender_email="reporter@example.com",
    )
    assert result.action_type == "update_record"
    assert result.record_id == "issue-1"
    assert "original text" in result.fields["description_html"]
    assert "any update?" in result.fields["description_html"]
    # The title is deliberately left alone -- only description_html updates.
    assert "name" not in result.fields
