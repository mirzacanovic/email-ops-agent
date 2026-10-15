"""Guards the prompt wording that fixed failures seen in the live rehearsal
(see docs/roadmap.md, "Found in the rehearsal"). They can't prove the model
behaves, only that the instructions don't silently regress."""

from app.pipeline.classify import INTENTS, SYSTEM_PROMPT as CLASSIFY_PROMPT
from app.pipeline.extract import SYSTEM_PROMPT as EXTRACT_PROMPT


def test_classify_prompt_defines_every_intent():
    for intent in INTENTS:
        assert f"- {intent}:" in CLASSIFY_PROMPT


def test_classify_prompt_sends_inbound_sales_pitches_to_other():
    assert "sell something TO us" in CLASSIFY_PROMPT
    assert "recruiters" in CLASSIFY_PROMPT


def test_classify_prompt_asks_for_calibrated_confidence():
    assert "below 0.6" in CLASSIFY_PROMPT


def test_extract_prompt_ties_titles_to_the_subject_not_a_person():
    assert "subject line" in EXTRACT_PROMPT
    assert "never a person's name" in EXTRACT_PROMPT


def test_extract_prompt_forbids_copying_the_intent_label():
    assert "sales_inquiry" in EXTRACT_PROMPT  # named as the thing not to copy
    assert "Never put the intent" in EXTRACT_PROMPT
