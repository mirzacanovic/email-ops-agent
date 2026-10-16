from datetime import datetime, timezone
from email.message import EmailMessage

from imap_bridge.parser import MAX_BODY_CHARS, TRUNCATION_MARK, html_to_text, parse_message

FALLBACK_TIME = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def build(
    *,
    subject="Pricing for 50-seat rollout",
    sender='"Priya Raman" <priya.raman@bluecrestlogistics.com>',
    to="sales@demo-company.test",
    date="Tue, 15 Sep 2026 11:47:00 +0000",
    message_id="<abc123@mail.bluecrestlogistics.com>",
    body="Hello,\r\n\r\nWe'd like pricing.\r\n\r\nPriya",
) -> EmailMessage:
    msg = EmailMessage()
    if subject is not None:
        msg["Subject"] = subject
    if sender is not None:
        msg["From"] = sender
    if to is not None:
        msg["To"] = to
    if date is not None:
        msg["Date"] = date
    if message_id is not None:
        msg["Message-ID"] = message_id
    msg.set_content(body)
    return msg


def parse(msg_or_bytes, **kwargs):
    raw = msg_or_bytes if isinstance(msg_or_bytes, bytes) else msg_or_bytes.as_bytes()
    return parse_message(raw, fallback_id="uid-1-7", **kwargs)


def test_a_plain_email_maps_to_the_orchestrators_shape():
    assert parse(build()) == {
        "id": "abc123@mail.bluecrestlogistics.com",
        "from": "priya.raman@bluecrestlogistics.com",  # address only, not the display name
        "to": "sales@demo-company.test",
        "subject": "Pricing for 50-seat rollout",
        "body": "Hello,\n\nWe'd like pricing.\n\nPriya",
        "received_at": "2026-09-15T11:47:00Z",
    }


def test_encoded_subject_with_umlauts_is_decoded():
    raw = (
        b"From: Anna <anna@firma.example>\r\nTo: s@x.example\r\n"
        b"Subject: =?utf-8?B?QW5mcmFnZSDDvGJlciBMaXplbnplbiBmw7xyIDUwIE51dHplcg==?=\r\n"
        b"Date: Tue, 15 Sep 2026 11:47:00 +0000\r\nMessage-ID: <m1@x>\r\n\r\nHallo\r\n"
    )
    assert parse(raw)["subject"] == "Anfrage über Lizenzen für 50 Nutzer"


def test_a_folded_multiline_subject_becomes_one_line():
    # Mail servers fold long headers across lines; the builder above refuses to,
    # so write the raw bytes the way they arrive.
    raw = (
        b"From: a@b.example\r\nDate: Tue, 15 Sep 2026 11:47:00 +0000\r\nMessage-ID: <f@x>\r\n"
        b"Subject: Export button\r\n throws an error\r\n\r\nbody\r\n"
    )
    assert parse(raw)["subject"] == "Export button throws an error"


def test_multipart_alternative_prefers_the_plain_text_part():
    msg = build(body="plain version")
    msg.add_alternative("<html><body><p>html <b>version</b></p></body></html>", subtype="html")
    assert parse(msg)["body"] == "plain version"


def test_an_html_only_email_is_converted_to_readable_text():
    msg = EmailMessage()
    msg["From"], msg["Date"], msg["Message-ID"] = "a@b.example", "Tue, 15 Sep 2026 11:47:00 +0000", "<h@x>"
    msg.set_content(
        "<html><head><style>p{color:red}</style></head><body>"
        "<p>Hi team,</p><p>The export is <b>broken</b>.<br>Please help.</p>"
        "<script>alert(1)</script></body></html>",
        subtype="html",
    )
    body = parse(msg)["body"]
    assert body == "Hi team,\n\nThe export is broken.\nPlease help."
    assert "alert" not in body and "color" not in body  # script and style never leak into the text


def test_a_latin1_body_is_decoded_not_mangled():
    raw = (
        b"From: a@b.example\r\nDate: Tue, 15 Sep 2026 11:47:00 +0000\r\nMessage-ID: <l@x>\r\n"
        b"Content-Type: text/plain; charset=iso-8859-1\r\nContent-Transfer-Encoding: 8bit\r\n\r\n"
        b"Gr\xfc\xdfe aus M\xfcnchen\r\n"
    )
    assert parse(raw)["body"] == "Grüße aus München"


def test_an_unknown_charset_falls_back_instead_of_raising():
    raw = (
        b"From: a@b.example\r\nDate: Tue, 15 Sep 2026 11:47:00 +0000\r\nMessage-ID: <u@x>\r\n"
        b"Content-Type: text/plain; charset=x-nonexistent\r\n\r\nstill readable\r\n"
    )
    assert "still readable" in parse(raw)["body"]


def test_attachments_are_ignored_and_the_text_part_is_kept():
    msg = build(body="See the attached screenshot.")
    msg.add_attachment(b"\x89PNG fake bytes", maintype="image", subtype="png", filename="screen.png")
    assert parse(msg)["body"] == "See the attached screenshot."


def test_an_email_with_only_an_attachment_has_an_empty_body():
    msg = EmailMessage()
    msg["From"], msg["Date"], msg["Message-ID"] = "a@b.example", "Tue, 15 Sep 2026 11:47:00 +0000", "<o@x>"
    msg.add_attachment(b"data", maintype="application", subtype="pdf", filename="x.pdf")
    assert parse(msg)["body"] == ""


def test_a_huge_body_is_truncated_with_a_marker():
    body = parse(build(body="word " * 30_000))["body"]
    assert len(body) <= MAX_BODY_CHARS + len(TRUNCATION_MARK)
    assert body.endswith(TRUNCATION_MARK.strip())


def test_missing_message_id_uses_the_stable_fallback():
    assert parse(build(message_id=None))["id"] == "uid-1-7"


def test_message_id_is_stripped_of_angle_brackets():
    assert parse(build(message_id="  <Xyz@host>  "))["id"] == "Xyz@host"


def test_a_date_with_a_timezone_offset_is_converted_to_utc():
    assert parse(build(date="Tue, 15 Sep 2026 13:47:00 +0200"))["received_at"] == "2026-09-15T11:47:00Z"


def test_a_date_without_a_zone_is_treated_as_utc():
    assert parse(build(date="Tue, 15 Sep 2026 11:47:00 -0000"))["received_at"] == "2026-09-15T11:47:00Z"


def test_missing_or_garbage_date_uses_the_servers_internal_date():
    assert parse(build(date=None), fallback_received_at=FALLBACK_TIME)["received_at"] == "2026-09-01T12:00:00Z"
    assert parse(build(date="not a date"), fallback_received_at=FALLBACK_TIME)["received_at"] == "2026-09-01T12:00:00Z"


def test_no_usable_timestamp_at_all_skips_the_message():
    assert parse(build(date=None)) is None


def test_missing_from_does_not_crash_and_is_clearly_marked():
    assert parse(build(sender=None))["from"] == "unknown@invalid"


def test_the_first_recipient_is_used_when_there_are_several():
    assert parse(build(to="a@x.example, b@x.example"))["to"] == "a@x.example"


def test_crlf_and_runs_of_blank_lines_are_normalised():
    assert parse(build(body="a\r\n\r\n\r\n\r\n\r\nb   c"))["body"] == "a\n\nb c"


def test_html_to_text_survives_broken_markup():
    assert "hello" in html_to_text("<p>hello <b>unclosed <i>tags")
