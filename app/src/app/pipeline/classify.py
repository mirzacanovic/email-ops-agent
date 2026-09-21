from dataclasses import dataclass
from typing import Any

from app.llm.base import LLMClient

INTENTS = ["support_request", "sales_inquiry", "project_status_question"]

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": INTENTS},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["intent", "confidence"],
}

SYSTEM_PROMPT = (
    "You classify inbound business emails into exactly one of: "
    f"{', '.join(INTENTS)}. Respond only with the structured result."
)


@dataclass
class Classification:
    intent: str
    confidence: float
    raw: dict[str, Any]  # the model's unmodified response, for the audit trail


async def classify(llm: LLMClient, email_subject: str, email_body: str) -> Classification:
    """Classify the email's intent using whichever LLMClient is configured
    (Ollama-served open model by default, Claude if LLM_PROVIDER=claude).
    """
    user_prompt = f"Subject: {email_subject}\n\nBody:\n{email_body}"
    result = await llm.complete_json(SYSTEM_PROMPT, user_prompt, CLASSIFY_SCHEMA)
    return Classification(intent=result["intent"], confidence=result["confidence"], raw=result)
