from typing import Any


async def extract(
    email_subject: str, email_body: str, intent: str, target_schema: dict[str, Any]
) -> dict[str, Any]:
    """Extract structured fields from the email, constrained to `target_schema`.

    TODO(phase-1): call Claude with tool use / a JSON schema derived from
    `target_schema` (e.g. an EspoCRM entity's field defs, or Plane's issue
    fields) so extraction only ever produces fields the target system
    understands. Log input/output to the audit trail.
    """
    raise NotImplementedError
