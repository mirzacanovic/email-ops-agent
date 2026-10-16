#!/usr/bin/env python3
"""Puts the demo emails into the sandbox IMAP server (greenmail), the IMAP
equivalent of scripts/release_demo_emails.sh.

    python scripts/send_demo_emails.py act1        # the two first emails
    python scripts/send_demo_emails.py act2        # the two follow-ups
    python scripts/send_demo_emails.py act3        # spam + the vague email
    python scripts/send_demo_emails.py all
    python scripts/send_demo_emails.py --status    # how many messages, how many unread
    python scripts/send_demo_emails.py --purge     # empty the sandbox mailbox

Needs `docker compose --profile imap up -d` first. Emails are sent with the
CURRENT date, as real incoming mail would be: the fixtures' own September dates
fall outside the bridge's lookback window. Each keeps a stable Message-ID
(<msg-001@demo-company.test>), so sending an act twice is harmless: the
orchestrator skips ids it has already processed.

--purge refuses to run against anything but localhost: it deletes every message
in the mailbox.
"""

import argparse
import imaplib
import json
import smtplib
import sys
import time
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTS = {
    "act1": ["msg-001", "msg-002"],
    "act2": ["msg-003", "msg-004"],
    "act3": ["msg-005", "msg-006"],
}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def find_fixtures() -> dict[str, dict]:
    """Every demo email by id, wherever it currently lives (the live fixtures
    folder and the staged demo-scenarios folders both hold some)."""
    found: dict[str, dict] = {}
    base = ROOT / "email-simulator"
    folders = [base / "src/email_simulator/fixtures", *sorted((base / "demo-scenarios").glob("act*"))]
    for folder in folders:
        for path in sorted(folder.glob("*.json")):
            message = json.loads(path.read_text(encoding="utf-8"))
            found.setdefault(message["id"], message)
    return found


def build(fixture: dict, mailbox_address: str, seconds_ago: int) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = fixture["from"]
    msg["To"] = fixture["to"]
    msg["Subject"] = fixture["subject"]
    msg["Date"] = formatdate(time.time() - seconds_ago, usegmt=True)
    msg["Message-ID"] = f"<{fixture['id']}@demo-company.test>"
    msg.set_content(fixture["body"])
    return msg


def send(ids: list[str], env: dict[str, str]) -> None:
    fixtures = find_fixtures()
    missing = [i for i in ids if i not in fixtures]
    if missing:
        sys.exit(f"Demo email(s) not found: {', '.join(missing)}")
    host = "localhost"
    port = int(env.get("GREENMAIL_SMTP_PORT", "3025"))
    mailbox = f"{env.get('IMAP_USER', 'demo')}@demo-company.test"
    try:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            for position, email_id in enumerate(ids):
                # Staggered a few seconds apart so the order within an act is kept.
                msg = build(fixtures[email_id], mailbox, seconds_ago=(len(ids) - position) * 5)
                # The envelope recipient is the sandbox user's mailbox; the To: header
                # keeps the fixture's original address (sales@, support@, ...).
                smtp.send_message(msg, from_addr=fixtures[email_id]["from"], to_addrs=[mailbox])
                print(f"sent {email_id}: {fixtures[email_id]['subject']}")
    except OSError as exc:
        sys.exit(f"Could not reach the sandbox mail server at {host}:{port} ({exc}).\n"
                 "Start it with: docker compose --profile imap up -d")


def imap_connection(env: dict[str, str]) -> imaplib.IMAP4:
    port = int(env.get("GREENMAIL_IMAP_PORT", "3143"))
    password = env.get("IMAP_PASSWORD", "")
    if not password:
        sys.exit("IMAP_PASSWORD is not set in .env (see .env.example)")
    try:
        conn = imaplib.IMAP4("localhost", port, timeout=15)
        conn.login(env.get("IMAP_USER", "demo"), password)
    except (OSError, imaplib.IMAP4.error) as exc:
        sys.exit(f"Could not log in to the sandbox mailbox on localhost:{port} ({type(exc).__name__})")
    return conn


def status(env: dict[str, str]) -> None:
    conn = imap_connection(env)
    conn.select("INBOX", readonly=True)
    total = len(conn.search(None, "ALL")[1][0].split())
    unseen = len(conn.search(None, "UNSEEN")[1][0].split())
    conn.logout()
    print(f"INBOX: {total} message(s), {unseen} unread")


def purge(env: dict[str, str]) -> None:
    host = env.get("IMAP_HOST_FOR_PURGE", "localhost")
    if host not in LOCAL_HOSTS:
        sys.exit("--purge only runs against localhost: it deletes every message in the mailbox.")
    conn = imap_connection(env)
    conn.select("INBOX")
    uids = conn.search(None, "ALL")[1][0].split()
    for uid in uids:
        conn.store(uid, "+FLAGS", "\\Deleted")
    conn.expunge()
    conn.logout()
    print(f"deleted {len(uids)} message(s) from the sandbox INBOX")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("act", nargs="?", choices=[*ACTS, "all"])
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--purge", action="store_true")
    args = parser.parse_args()
    env = load_env()

    if args.purge:
        purge(env)
    elif args.status:
        status(env)
    elif args.act:
        send([i for act in (ACTS if args.act == "all" else [args.act]) for i in ACTS[act]], env)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
