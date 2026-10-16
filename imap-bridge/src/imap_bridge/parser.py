"""Turns a raw RFC 5322 email into the message shape the orchestrator expects:

    {"id", "from", "to", "subject", "body", "received_at"}

Real email is untrusted and messy, unlike the simulator's tidy fixtures, so this
is where that gets absorbed: encoded subjects (RFC 2047, e.g. German umlauts),
HTML-only bodies, odd charsets, attachments, missing headers and huge bodies.
Nothing here raises on a malformed message; it degrades to an empty field, so
one bad email cannot stop the rest of the inbox from being read.

Pure functions only (no network), so the whole module is unit-tested offline.
"""

import re
from datetime import datetime, timezone
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

MAX_BODY_CHARS = 20_000
TRUNCATION_MARK = "\n[... message truncated ...]"

_BLOCK_TAGS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}
_SKIPPED_TAGS = {"script", "style", "head", "title"}


class _TextExtractor(HTMLParser):
    """HTML to plain text: drops tags and script/style, keeps line breaks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - malformed HTML must not stop the inbox
        return re.sub(r"<[^>]+>", " ", html)
    return parser.text()


def _tidy(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)  # collapse runs of spaces, keep newlines
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _body(msg: EmailMessage, max_chars: int) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:  # e.g. only an attachment
        return ""
    try:
        content = part.get_content()
    except (LookupError, UnicodeError):  # unknown charset: decode leniently instead
        payload = part.get_payload(decode=True)
        content = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else ""
    if part.get_content_type() == "text/html":
        content = html_to_text(content)
    content = _tidy(content)
    if len(content) > max_chars:
        content = content[:max_chars].rstrip() + TRUNCATION_MARK
    return content


def _address(header_value: object) -> str:
    """First email address in an address header ("Priya <p@x.com>" -> "p@x.com")."""
    addresses = getattr(header_value, "addresses", None)
    if addresses:
        return str(addresses[0].addr_spec)
    return ""


def _received_at(msg: EmailMessage, fallback: datetime | None) -> datetime | None:
    raw = msg["date"]
    if raw is not None:
        try:
            parsed = parsedate_to_datetime(str(raw))
        except (TypeError, ValueError, IndexError):
            parsed = None
        if parsed is not None:
            # A date with no zone ("-0000") comes back naive: treat as UTC.
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return fallback


def parse_message(
    raw: bytes,
    fallback_id: str,
    fallback_received_at: datetime | None = None,
    max_body_chars: int = MAX_BODY_CHARS,
) -> dict[str, str] | None:
    """One raw email to the orchestrator's message dict.

    `fallback_id` is used when the email has no Message-ID header (the caller
    passes something stable like "uid-<uidvalidity>-<uid>"). Returns None only
    if no timestamp can be established at all, since the orchestrator needs one.
    """
    msg = message_from_bytes(raw, policy=policy.default)
    assert isinstance(msg, EmailMessage)

    received = _received_at(msg, fallback_received_at)
    if received is None:
        return None

    message_id = str(msg["message-id"] or "").strip().strip("<>").strip()
    subject = re.sub(r"\s+", " ", str(msg["subject"] or "")).strip()

    return {
        "id": message_id or fallback_id,
        "from": _address(msg["from"]) or "unknown@invalid",
        "to": _address(msg["to"]),
        "subject": subject,
        "body": _body(msg, max_body_chars),
        "received_at": received.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
