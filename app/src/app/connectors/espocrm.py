from typing import Any

import httpx

from app.connectors.base import SystemConnector

# EspoCRM's Metadata API returns dozens of fields per entity (id,
# createdAt, modifiedById, versionNumber, ...) that extraction must never
# be allowed to invent values for. This is the allowlist of fields
# extraction is allowed to fill in per entity type; get_schema() only
# ever exposes these.
EXTRACTABLE_FIELDS: dict[str, list[str]] = {
    "Contact": [
        "firstName",
        "lastName",
        "emailAddress",
        "phoneNumber",
        "accountName",
        "description",
    ],
    "Lead": [
        "firstName",
        "lastName",
        "emailAddress",
        "phoneNumber",
        "accountName",
        "description",
        "source",
    ],
}

# EspoCRM field type -> JSON Schema fragment. Unlisted types (e.g. link
# fields other than the denormalized *Name ones) fall back to "string".
ESPOCRM_TYPE_MAP: dict[str, dict[str, Any]] = {
    "varchar": {"type": "string"},
    "text": {"type": "string"},
    "wysiwyg": {"type": "string"},
    "url": {"type": "string"},
    "email": {"type": "string"},
    "phone": {"type": "string"},
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "currency": {"type": "number"},
    "bool": {"type": "boolean"},
    "date": {"type": "string", "format": "date"},
    "datetime": {"type": "string", "format": "date-time"},
}

# Grounds the extraction model on what each field actually means, so it
# stops confusing e.g. "the sender's company" with "what the sender is
# asking for" (msg-001 in testing extracted a company name into a field
# meant for a problem description).
FIELD_DESCRIPTIONS: dict[str, str] = {
    "firstName": "The sender's first name.",
    "lastName": "The sender's last name.",
    "emailAddress": (
        "The sender's email address, copied exactly from the sender "
        "address given in the prompt — never reformatted or guessed."
    ),
    "phoneNumber": "A phone number explicitly written in the email, if any.",
    "accountName": (
        "The name of the sender's company/organization, if mentioned — "
        "not the sender's own name."
    ),
    "description": (
        "A concise summary, in the sender's own words, of what they are "
        "asking for or reporting — not the company name or sender name."
    ),
    "source": (
        "How this lead reached us (e.g. 'Website', 'Referral'), only if "
        "explicitly stated in the email — omit if not stated."
    ),
}


def build_schema_from_field_defs(entity_type: str, field_defs: dict[str, Any]) -> dict[str, Any]:
    """Translate EspoCRM's raw metadata field defs into JSON Schema,
    narrowed to EXTRACTABLE_FIELDS. Split out from get_schema as a pure
    function so the translation logic (allowlisting, type mapping, field
    descriptions) is unit-testable without mocking HTTP.
    """
    allowed_fields = EXTRACTABLE_FIELDS.get(entity_type, list(field_defs.keys()))

    properties: dict[str, Any] = {}
    for field_name in allowed_fields:
        field_def = field_defs.get(field_name)
        if field_def is None:
            continue
        if field_def.get("type") == "enum" and field_def.get("options"):
            prop = {"type": "string", "enum": field_def["options"]}
        else:
            # Copy rather than reuse the shared ESPOCRM_TYPE_MAP dict —
            # every "varchar" field would otherwise point at the same
            # object, so adding a per-field "description" below would
            # leak across all fields of that type.
            prop = dict(ESPOCRM_TYPE_MAP.get(field_def.get("type", ""), {"type": "string"}))
        if field_name in FIELD_DESCRIPTIONS:
            prop["description"] = FIELD_DESCRIPTIONS[field_name]
        properties[field_name] = prop

    return {"type": "object", "properties": properties, "additionalProperties": False}


class EspoCRMConnector(SystemConnector):
    """Adapter for EspoCRM's REST API (https://docs.espocrm.com/development/api/).

    Auth: header `X-Api-Key: <key>` from an EspoCRM API User.
    """

    def __init__(self, base_url: str, api_key: str) -> None:
        # 10s was too tight in practice: a request timed out here while
        # running alongside Ollama inference under load, failing a
        # message that would otherwise have succeeded (same class of
        # problem OllamaClient's own timeout hit — see its comment).
        self._client = httpx.AsyncClient(
            base_url=f"{base_url.rstrip('/')}/api/v1",
            headers={"X-Api-Key": api_key},
            timeout=30.0,
        )

    async def search_records(
        self, entity_type: str, query: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """`query` keys are translated into EspoCRM's `where[]` equals-filter
        array, e.g. `{"emailAddress": "x@y.com"}` becomes
        `where[0][type]=equals&where[0][attribute]=emailAddress&where[0][value]=x@y.com`.

        The reserved key `_fulltext` maps instead to EspoCRM's server-side
        `textFilter`, which matches across the entity's configured
        name/search fields — used for the fuzzy-name pass in
        `pipeline.match`, since scanning every record client-side wouldn't
        scale past demo-sized data.
        """
        # httpx's `params` accepts list[tuple[str, str | int | float | bool
        # | None]] specifically -- list[tuple[str, str]], though every
        # value here is in fact a str, isn't accepted due to list
        # invariance, so the annotation has to match httpx's shape exactly.
        params: list[tuple[str, str | int | float | bool | None]] = [("maxSize", "50")]
        where_index = 0
        for attribute, value in query.items():
            if attribute == "_fulltext":
                continue
            params.append((f"where[{where_index}][type]", "equals"))
            params.append((f"where[{where_index}][attribute]", attribute))
            params.append((f"where[{where_index}][value]", str(value)))
            where_index += 1
        if "_fulltext" in query:
            params.append(("textFilter", str(query["_fulltext"])))

        response = await self._client.get(f"/{entity_type}", params=params)
        response.raise_for_status()
        return response.json().get("list", [])

    async def create_record(
        self, entity_type: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        response = await self._client.post(f"/{entity_type}", json=fields)
        response.raise_for_status()
        return response.json()

    async def update_record(
        self, entity_type: str, record_id: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        response = await self._client.put(f"/{entity_type}/{record_id}", json=fields)
        response.raise_for_status()
        return response.json()

    async def get_schema(self, entity_type: str) -> dict[str, Any]:
        """Return a JSON Schema built from EspoCRM's own metadata, narrowed
        to EXTRACTABLE_FIELDS so the extraction stage can only ever
        produce fields this entity actually has and that are safe to
        fill from email content.
        """
        response = await self._client.get("/Metadata")
        response.raise_for_status()
        field_defs: dict[str, Any] = (
            response.json().get("entityDefs", {}).get(entity_type, {}).get("fields", {})
        )
        return build_schema_from_field_defs(entity_type, field_defs)
