from dataclasses import dataclass
from typing import Any

from app.llm.base import LLMClient

# "other" is the model's way out: spam, recruiters, vendor pitches, anything
# that isn't a customer message. It has no entry in INTENT_ROUTES, so it
# escalates to a human instead of being forced into a customer workflow.
INTENTS = ["support_request", "sales_inquiry", "project_status_question", "other"]

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": INTENTS},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["intent", "confidence"],
}

# The definitions are written from the company's point of view on purpose:
# in the live rehearsal an unsolicited recruiting pitch was classified as a
# sales_inquiry at 95% because "sales" read as "someone is selling", when it
# means "someone wants to buy from us".
SYSTEM_PROMPT = (
    "You classify inbound business emails for a software company into "
    f"exactly one of: {', '.join(INTENTS)}. Judge from the company's point "
    "of view:\n"
    "- support_request: an existing customer reports a problem with our "
    "product and wants help.\n"
    "- sales_inquiry: a prospective customer wants to buy OUR product "
    "(pricing, a demo, a pilot).\n"
    "- project_status_question: someone asks for an update on something "
    "they already raised with us.\n"
    "- other: everything else, including (a) unsolicited pitches where the "
    "sender is trying to sell something TO us (recruiters, staffing and "
    "marketing agencies, vendors, partnership offers), (b) newsletters and "
    "automated notifications, and (c) messages too vague to tell what the "
    "sender wants.\n\n"
    "Examples:\n"
    "\"We'd like pricing for 50 seats\" -> sales_inquiry.\n"
    "\"Our export button is broken\" -> support_request.\n"
    "\"Any update on the export bug?\" -> project_status_question.\n"
    "\"We place engineers 30% below market rates, book a call\" -> other "
    "(they are selling to us, not buying from us).\n"
    "\"Can you resend the thing we talked about?\" -> other (too vague).\n\n"
    "Set confidence honestly: use 0.9 or higher only when the email clearly "
    "fits one category, and below 0.6 when it is ambiguous or could fit "
    "more than one. Respond only with the structured result."
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
