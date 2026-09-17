from dataclasses import dataclass


@dataclass
class Classification:
    intent: str  # e.g. "support_request" | "sales_inquiry" | "project_status_question"
    confidence: float


async def classify(email_subject: str, email_body: str) -> Classification:
    """Classify the email's intent.

    TODO(phase-1): call Claude with a fixed set of intent labels (start
    with the 2-3 from the roadmap) and return its label + confidence.
    Log the raw model response to the audit trail alongside the result.
    """
    raise NotImplementedError
