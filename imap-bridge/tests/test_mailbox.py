import imaplib
from datetime import date, datetime, timezone

import pytest

from imap_bridge import mailbox
from imap_bridge.config import Config
from imap_bridge.mailbox import MailboxError, fetch_recent, imap_date, parse_internaldate

PASSWORD = "hunter2-very-secret"
CFG = Config(host="imap.example", port=993, use_ssl=True, user="demo@demo-company.test", password=PASSWORD)
SINCE = datetime(2026, 9, 1, tzinfo=timezone.utc)


def raw_email(n: int, *, date_header: str | None = "Tue, 15 Sep 2026 11:47:00 +0000", message_id: str | None = None) -> bytes:
    lines = [f"From: Sender {n} <s{n}@example.com>", "To: sales@demo-company.test", f"Subject: Email number {n}"]
    if date_header:
        lines.append(f"Date: {date_header}")
    lines.append(f"Message-ID: <{message_id or f'm{n}@example.com'}>" if message_id != "" else "X-No-Id: 1")
    return ("\r\n".join(lines) + f"\r\n\r\nBody of {n}\r\n").encode()


class FakeImap:
    """Just enough of imaplib.IMAP4 to be driven by mailbox.py, recording every
    command so tests can assert what was (and was not) done to the mailbox."""

    def __init__(self, messages: dict[int, tuple[bytes, str]], *, login_error=None, select_status="OK"):
        self.messages = messages  # uid -> (raw bytes, INTERNALDATE text)
        self.login_error = login_error
        self.select_status = select_status
        self.log: list[tuple] = []
        self.logged_out = False

    def login(self, user, password):
        self.log.append(("LOGIN", user))
        if self.login_error:
            raise self.login_error
        return "OK", [b"logged in"]

    def select(self, folder, readonly=False):
        self.log.append(("SELECT", folder, readonly))
        return self.select_status, [b"1"]

    def response(self, name):
        return name, [b"4242"]

    def uid(self, command, *args):
        self.log.append((command, *args))
        if command == "SEARCH":
            return "OK", [b" ".join(str(u).encode() for u in sorted(self.messages))]
        if command == "FETCH":
            uid = int(args[0])
            raw, internal = self.messages[uid]
            header = f'{uid} (UID {uid} INTERNALDATE "{internal}" BODY[] {{{len(raw)}}}'.encode()
            return "OK", [(header, raw), b")"]
        raise AssertionError(f"unexpected IMAP command {command}")  # nothing else may ever be sent

    def logout(self):
        self.logged_out = True
        return "BYE", [b""]


def run(fake: FakeImap, cfg: Config = CFG, since: datetime = SINCE):
    return fetch_recent(cfg, since, connect=lambda _cfg: fake)


def internal(day="15-Sep-2026 11:47:00 +0000") -> str:
    return day


# --- what it returns ---


def test_returns_parsed_messages_oldest_first_whatever_the_uid_order():
    fake = FakeImap(
        {
            1: (raw_email(1, date_header="Wed, 16 Sep 2026 09:00:00 +0000"), internal()),
            2: (raw_email(2, date_header="Mon, 14 Sep 2026 09:00:00 +0000"), internal()),
        }
    )
    messages = run(fake)
    assert [m["id"] for m in messages] == ["m2@example.com", "m1@example.com"]
    assert messages[0]["subject"] == "Email number 2" and messages[0]["body"] == "Body of 2"


def test_only_the_newest_max_messages_are_read():
    fake = FakeImap({u: (raw_email(u), internal()) for u in range(1, 6)})
    cfg = Config(**{**CFG.__dict__, "max_messages": 2})
    messages = run(fake, cfg)
    assert sorted(m["id"] for m in messages) == ["m4@example.com", "m5@example.com"]  # highest UIDs = newest
    assert sum(1 for entry in fake.log if entry[0] == "FETCH") == 2  # and the rest were never downloaded


def test_the_search_uses_an_english_imap_date():
    fake = FakeImap({1: (raw_email(1), internal())})
    run(fake, since=datetime(2026, 3, 5, tzinfo=timezone.utc))
    assert ("SEARCH", None, "SINCE", "05-Mar-2026") in fake.log


# --- the read-only guarantee ---


def test_the_mailbox_is_opened_read_only_and_only_peeked_at():
    fake = FakeImap({1: (raw_email(1), internal()), 2: (raw_email(2), internal())})
    run(fake)
    assert ("SELECT", "INBOX", True) in fake.log  # EXAMINE: no flag can change
    fetches = [entry for entry in fake.log if entry[0] == "FETCH"]
    assert fetches and all("BODY.PEEK[]" in entry[2] for entry in fetches)  # PEEK: does not mark as read
    assert {entry[0] for entry in fake.log if entry[0] not in ("LOGIN", "SELECT")} == {"SEARCH", "FETCH"}
    # no STORE / COPY / EXPUNGE / APPEND ever: FakeImap.uid() raises on anything else


def test_the_connection_is_closed_afterwards():
    fake = FakeImap({1: (raw_email(1), internal())})
    run(fake)
    assert fake.logged_out


# --- ids and dates ---


def test_a_message_without_a_message_id_gets_a_stable_uid_based_id():
    fake = FakeImap({7: (raw_email(7, message_id=""), internal())})
    assert run(fake)[0]["id"] == "uid-4242-7"


def test_the_servers_internal_date_is_used_when_the_date_header_is_missing():
    fake = FakeImap({1: (raw_email(1, date_header=None), "15-Sep-2026 13:47:00 +0200")})
    assert run(fake)[0]["received_at"] == "2026-09-15T11:47:00Z"


# --- a bad message does not stop the rest ---


def test_an_unparseable_message_is_skipped_and_the_others_still_arrive(monkeypatch):
    real = mailbox.parse_message

    def flaky(raw, **kwargs):
        if b"Email number 2" in raw:
            raise RuntimeError("boom")
        return real(raw, **kwargs)

    monkeypatch.setattr(mailbox, "parse_message", flaky)
    fake = FakeImap({u: (raw_email(u), internal()) for u in (1, 2, 3)})
    assert [m["id"] for m in run(fake)] == ["m1@example.com", "m3@example.com"]


def test_a_message_with_no_timestamp_anywhere_is_skipped():
    fake = FakeImap({1: (raw_email(1, date_header=None), "garbage"), 2: (raw_email(2), internal())})
    assert [m["id"] for m in run(fake)] == ["m2@example.com"]


# --- failures are reported safely ---


def test_a_wrong_password_is_reported_without_echoing_secrets():
    fake = FakeImap({}, login_error=imaplib.IMAP4.error(f"[AUTHENTICATIONFAILED] bad login for {PASSWORD}"))
    with pytest.raises(MailboxError) as info:
        run(fake)
    assert "login failed" in str(info.value)
    assert PASSWORD not in str(info.value) and PASSWORD not in repr(info.value)
    assert fake.logged_out


def test_an_unreachable_server_is_reported_with_where_it_tried():
    def refuse(_cfg):
        raise ConnectionRefusedError("refused")

    with pytest.raises(MailboxError, match=r"Cannot reach the IMAP server imap\.example:993"):
        fetch_recent(CFG, SINCE, connect=refuse)


def test_an_unopenable_folder_is_reported_and_the_connection_still_closed():
    fake = FakeImap({}, select_status="NO")
    with pytest.raises(MailboxError, match="Cannot open the IMAP folder"):
        run(fake)
    assert fake.logged_out


def test_check_connection_succeeds_on_a_good_mailbox_and_fails_on_a_bad_one():
    mailbox.check_connection(CFG, connect=lambda _cfg: FakeImap({}))
    with pytest.raises(MailboxError):
        mailbox.check_connection(CFG, connect=lambda _cfg: FakeImap({}, login_error=imaplib.IMAP4.error("no")))


# --- small helpers ---


@pytest.mark.parametrize(
    ("day", "expected"),
    [(date(2026, 3, 5), "05-Mar-2026"), (date(2026, 12, 31), "31-Dec-2026"), (date(2026, 1, 1), "01-Jan-2026")],
)
def test_imap_date_is_zero_padded_and_english(day, expected):
    assert imap_date(day) == expected


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (b'1 (UID 1 INTERNALDATE "15-Sep-2026 13:47:00 +0200" BODY[] {5}', "2026-09-15T11:47:00"),
        (b'1 (UID 1 INTERNALDATE "15-Sep-2026 06:47:00 -0500" BODY[] {5}', "2026-09-15T11:47:00"),
        (b'1 (UID 1 INTERNALDATE " 5-Sep-2026 11:47:00 +0000" BODY[] {5}', "2026-09-05T11:47:00"),
    ],
)
def test_internaldate_is_converted_to_utc(header, expected):
    assert parse_internaldate(header).replace(tzinfo=None).isoformat() == expected


def test_a_garbled_internaldate_gives_none():
    assert parse_internaldate(b'1 (UID 1 INTERNALDATE "nonsense" BODY[] {5}') is None
