"""Reads recent mail from an IMAP mailbox, read-only.

Design points that matter for a real inbox (as opposed to the simulator):

  * Read-only. The folder is opened with EXAMINE (readonly=True) and messages
    are fetched with BODY.PEEK[], so reading never marks a client's mail as
    read, moves it, or deletes it.
  * Bounded. Only mail from the last `lookback_days`, at most `max_messages` of
    it (the newest), because the orchestrator asks again on every check.
  * Isolated failures. One message that cannot be parsed is skipped and logged
    (without its content); it does not stop the rest.
  * Safe errors. MailboxError messages never contain the password.

The network layer is injected (`connect`), so tests run against a fake.
"""

import imaplib
import logging
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

from imap_bridge.config import Config
from imap_bridge.parser import parse_message

logger = logging.getLogger(__name__)

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_INTERNALDATE = re.compile(
    rb'INTERNALDATE "\s*(\d{1,2})-([A-Za-z]{3})-(\d{4}) (\d\d):(\d\d):(\d\d) ([+-])(\d\d)(\d\d)"'
)
_UID = re.compile(rb"UID (\d+)")


class MailboxError(Exception):
    """Something went wrong talking to the mailbox. The message is safe to show."""


def imap_date(day: date) -> str:
    # strftime("%b") follows the machine's locale; IMAP requires English month names.
    return f"{day.day:02d}-{_MONTHS[day.month - 1]}-{day.year}"


def parse_internaldate(header: bytes) -> datetime | None:
    """The server's own receive time, from a FETCH response header. Used only
    when the email has no usable Date header."""
    match = _INTERNALDATE.search(header)
    if not match:
        return None
    day, month, year, hh, mm, ss, sign, off_h, off_m = match.groups()
    try:
        month_number = _MONTHS.index(month.decode().capitalize()) + 1
        local = datetime(int(year), month_number, int(day), int(hh), int(mm), int(ss))
    except ValueError:
        return None
    offset_minutes = int(off_h) * 60 + int(off_m)
    if sign == b"-":
        offset_minutes = -offset_minutes
    return (local - timedelta(minutes=offset_minutes)).replace(tzinfo=timezone.utc)


def default_connect(cfg: Config) -> imaplib.IMAP4:
    if cfg.use_ssl:
        return imaplib.IMAP4_SSL(cfg.host, cfg.port, timeout=cfg.timeout_seconds)
    return imaplib.IMAP4(cfg.host, cfg.port, timeout=cfg.timeout_seconds)


class ImapLike(Protocol):
    """The five IMAP calls this module makes. Typed here (instead of as
    imaplib.IMAP4) because the stdlib stubs are narrower than the real library
    (e.g. uid() takes a None charset and bytes UIDs), and so tests can pass a fake."""

    def login(self, user: str, password: str, /) -> tuple[str, list[Any]]: ...

    def select(self, mailbox: str, /, readonly: bool = ...) -> tuple[str, list[Any]]: ...

    def response(self, code: str, /) -> tuple[str, list[Any]]: ...

    def uid(self, command: str, /, *args: Any) -> tuple[str, list[Any]]: ...

    def logout(self) -> tuple[str, list[Any]]: ...


Connect = Callable[[Config], ImapLike]


def _open(cfg: Config, connect: Connect) -> ImapLike:
    """A connected, logged-in connection with the folder open read-only."""
    try:
        conn = connect(cfg)
    except (OSError, EOFError) as exc:
        raise MailboxError(
            f"Cannot reach the IMAP server {cfg.host}:{cfg.port} ({type(exc).__name__})"
        ) from None
    try:
        try:
            conn.login(cfg.user, cfg.password)
        except imaplib.IMAP4.error:
            raise MailboxError("IMAP login failed (check IMAP_USER and IMAP_PASSWORD)") from None
        status, _ = conn.select(cfg.folder, readonly=True)
        if status != "OK":
            raise MailboxError(f"Cannot open the IMAP folder {cfg.folder!r}")
    except Exception:
        _close(conn)
        raise
    return conn


def _close(conn: ImapLike) -> None:
    try:
        conn.logout()
    except Exception:  # noqa: BLE001 - closing is best effort
        pass


def _uidvalidity(conn: ImapLike) -> str:
    try:
        _, data = conn.response("UIDVALIDITY")
        return data[0].decode() if data and data[0] else "0"
    except Exception:  # noqa: BLE001
        return "0"


def check_connection(cfg: Config, connect: Connect = default_connect) -> None:
    """Raises MailboxError unless the mailbox can be logged in to and opened."""
    try:
        conn = _open(cfg, connect)
    except imaplib.IMAP4.error:
        raise MailboxError("IMAP error while opening the mailbox") from None
    _close(conn)


def fetch_recent(cfg: Config, since: datetime, connect: Connect = default_connect) -> list[dict[str, str]]:
    """Messages received on or after `since` (day granularity from the server),
    newest `max_messages` of them, oldest first."""
    try:
        conn = _open(cfg, connect)
    except imaplib.IMAP4.error:
        raise MailboxError("IMAP error while opening the mailbox") from None

    messages: list[dict[str, str]] = []
    try:
        uidvalidity = _uidvalidity(conn)
        status, data = conn.uid("SEARCH", None, "SINCE", imap_date(since.date()))
        if status != "OK":
            raise MailboxError("The IMAP search failed")
        uids = data[0].split() if data and data[0] else []
        for uid in uids[-cfg.max_messages:]:  # UIDs only grow, so the tail is the newest
            parsed = _fetch_one(conn, uid, uidvalidity, cfg)
            if parsed is not None:
                messages.append(parsed)
    except (imaplib.IMAP4.error, OSError, EOFError) as exc:
        raise MailboxError(f"Reading the mailbox failed ({type(exc).__name__})") from None
    finally:
        _close(conn)

    messages.sort(key=lambda m: (m["received_at"], m["id"]))
    return messages


def _fetch_one(conn: ImapLike, uid: bytes, uidvalidity: str, cfg: Config) -> dict[str, str] | None:
    try:
        # BODY.PEEK[] leaves the \Seen flag alone; plain BODY[] would mark it read.
        status, resp = conn.uid("FETCH", uid, "(INTERNALDATE BODY.PEEK[])")
        if status != "OK":
            return None
        for item in resp:
            if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
                header, raw = item[0], item[1]
                return parse_message(
                    raw,
                    fallback_id=f"uid-{uidvalidity}-{uid.decode()}",
                    fallback_received_at=parse_internaldate(header),
                    max_body_chars=cfg.max_body_chars,
                )
    except (imaplib.IMAP4.error, OSError, EOFError):
        raise
    except Exception:  # noqa: BLE001 - one bad message must not stop the rest
        logger.warning("Skipping message uid=%s: could not be parsed", uid.decode(errors="replace"))
    return None
