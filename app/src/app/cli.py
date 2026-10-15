"""Reviewer account management:

    python -m app.cli create-user <username>
    python -m app.cli set-password <username>

The password is always prompted for (never a CLI argument or env var), so it
doesn't land in shell history or process listings.
"""

import argparse
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.models import User
from app.auth.passwords import hash_password
from app.db.migrate import run_migrations
from app.db.session import SessionLocal, engine

MIN_PASSWORD_LENGTH = 8


def _prompt_password() -> str:
    password = getpass.getpass("Password: ")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if getpass.getpass("Repeat password: ") != password:
        raise SystemExit("Passwords did not match.")
    return password


def create_user(db: Session, username: str, password: str) -> None:
    if db.scalar(select(User).where(User.username == username)):
        raise SystemExit(f"User {username!r} already exists (use set-password to change it).")
    db.add(User(username=username, password_hash=hash_password(password)))
    db.commit()


def set_password(db: Session, username: str, password: str) -> None:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise SystemExit(f"No such user: {username!r}.")
    user.password_hash = hash_password(password)
    db.commit()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("create-user", "set-password"):
        sub.add_parser(name).add_argument("username")
    args = parser.parse_args(argv)

    run_migrations(engine)  # so the users table exists even before the app has started
    password = _prompt_password()
    with SessionLocal() as db:
        if args.command == "create-user":
            create_user(db, args.username, password)
            print(f"Created user {args.username!r}.")
        else:
            set_password(db, args.username, password)
            print(f"Updated password for {args.username!r}.")


if __name__ == "__main__":
    main(sys.argv[1:])
