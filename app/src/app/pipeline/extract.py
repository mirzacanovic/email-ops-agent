from typing import Any

from app.llm.base import LLMClient

SYSTEM_PROMPT = (
    "Extract structured fields from this business email, constrained to "
    "the JSON schema you're given. Rules:\n"
    "1. Copy names, email addresses, phone numbers, and other identifying "
    "details exactly as they appear in the email or in the sender address "
    "given below — never invent, reformat, or guess a value.\n"
    "2. If a field's value isn't clearly present in the email, omit that "
    "field entirely rather than filling in a plausible-sounding guess.\n"
    "3. Match each field to its description precisely — do not put one "
    "kind of information (e.g. a company name) into a field meant for "
    "another (e.g. a problem description).\n\n"
    "Example: given a body \"Hi, I'm Alex Chen from Acme Corp, we'd like a "
    "demo\" and sender address \"alex@acme.com\", a lead-like schema "
    "should extract {\"firstName\": \"Alex\", \"lastName\": \"Chen\", "
    "\"emailAddress\": \"alex@acme.com\", \"accountName\": \"Acme Corp\"} — "
    "not a reformatted or invented email, and no fields the email didn't "
    "mention."
)


async def extract(
    llm: LLMClient,
    email_subject: str,
    email_body: str,
    sender_email: str,
    intent: str,
    target_schema: dict[str, Any],
) -> dict[str, Any]:
    """Extract structured fields from the email, constrained to
    `target_schema` — a JSON Schema object, as returned by
    `SystemConnector.get_schema(entity_type)`.

    `sender_email` is passed as ground truth rather than left for the
    model to infer from the signature in the body: in testing, leaving
    it out produced a hallucinated address (a "praman@..." address
    invented from "Priya Raman" in the signature, when the real sender
    was "priya.raman@...") — the model was guessing a plausible corporate
    email format instead of using the real one, which it simply didn't
    have.
    """
    user_prompt = (
        f"Sender address: {sender_email}\n"
        f"Intent: {intent}\n"
        f"Subject: {email_subject}\n\n"
        f"Body:\n{email_body}"
    )
    return await llm.complete_json(SYSTEM_PROMPT, user_prompt, target_schema)
