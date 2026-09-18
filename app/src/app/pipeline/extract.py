from typing import Any

from app.llm.base import LLMClient

SYSTEM_PROMPT = (
    "Extract structured fields from this business email for the given "
    "intent. Only fill fields present in the provided schema; leave "
    "fields out rather than guessing a value that isn't in the email."
)


async def extract(
    llm: LLMClient,
    email_subject: str,
    email_body: str,
    intent: str,
    target_schema: dict[str, Any],
) -> dict[str, Any]:
    """Extract structured fields from the email, constrained to
    `target_schema` — a JSON Schema object, as returned by
    `SystemConnector.get_schema(entity_type)`.
    """
    user_prompt = f"Intent: {intent}\nSubject: {email_subject}\n\nBody:\n{email_body}"
    return await llm.complete_json(SYSTEM_PROMPT, user_prompt, target_schema)
