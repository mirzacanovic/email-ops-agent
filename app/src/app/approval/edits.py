"""What a reviewer may change before approving, and how an edit is validated.

The model proposes `fields`; a human can correct the text before it is sent to
Plane or EspoCRM. Edits are checked here, on the server, against the proposal
itself rather than trusting whatever the browser posts: only fields the
pipeline proposed as text can be changed, and fields the pipeline sets for its
own bookkeeping cannot.
"""

from dataclasses import dataclass

EDIT_PREFIX = "edit__"  # form field name = EDIT_PREFIX + proposal field name
MAX_LENGTH = 10_000

# Set by the pipeline (e.g. the sender's address, used to match later follow-ups
# to this issue), so a reviewer editing them would silently break matching.
PROTECTED_FIELDS = frozenset({"external_id", "external_source"})

# Fields with a fixed set of values; anything else is rejected.
FIELD_CHOICES: dict[str, list[str]] = {
    "priority": ["urgent", "high", "medium", "low", "none"],
}

MULTILINE_FIELDS = frozenset({"description", "description_html"})


class EditError(ValueError):
    """The submitted edits are not acceptable; the message is shown to the reviewer."""


@dataclass(frozen=True)
class EditableField:
    name: str
    value: str
    choices: list[str] | None = None
    multiline: bool = False


def _normalize(text: str) -> str:
    # Browsers submit textarea line breaks as CRLF; compare and store LF.
    return text.replace("\r\n", "\n")


def editable_fields(fields: dict[str, object]) -> list[EditableField]:
    """The proposed fields a reviewer can change, in proposal order."""
    result = []
    for name, value in fields.items():
        if name in PROTECTED_FIELDS or not isinstance(value, str):
            continue
        result.append(
            EditableField(
                name=name,
                value=value,
                choices=FIELD_CHOICES.get(name),
                multiline=name in MULTILINE_FIELDS or "\n" in value or len(value) > 80,
            )
        )
    return result


def parse_edits(form: dict[str, str], proposed: dict[str, object]) -> dict[str, str]:
    """Returns only the fields whose value actually changed (so submitting an
    untouched form is a plain approval, not an "edit"). Raises EditError."""
    allowed = {f.name: f for f in editable_fields(proposed)}
    edits: dict[str, str] = {}
    for key, raw in form.items():
        if not key.startswith(EDIT_PREFIX):
            continue
        name = key[len(EDIT_PREFIX):]
        if name not in allowed:
            raise EditError(f"'{name}' cannot be edited")
        value = _normalize(raw)
        if not value.strip():
            raise EditError(f"'{name}' cannot be empty")
        if len(value) > MAX_LENGTH:
            raise EditError(f"'{name}' is too long (limit {MAX_LENGTH} characters)")
        choices = allowed[name].choices
        if choices is not None and value not in choices:
            raise EditError(f"'{name}' must be one of: {', '.join(choices)}")
        if value != _normalize(allowed[name].value):
            edits[name] = value
    return edits
