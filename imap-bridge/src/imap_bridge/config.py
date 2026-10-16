"""Settings, read from environment variables only.

The mailbox password is deliberately never written to a file in the repo, never
logged and never shown by repr(); it only ever comes from the environment (the
project's git-ignored .env via docker compose).
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

_FALSE = {"0", "false", "no", "off", ""}


def _flag(value: str) -> bool:
    return value.strip().lower() not in _FALSE


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {raw!r}") from None
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero, got {value}")
    return value


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    use_ssl: bool
    user: str
    password: str = field(repr=False)  # repr=False: never show up in a log line or traceback
    folder: str = "INBOX"
    # The orchestrator re-reads the mailbox on every check, so bound how much it
    # sees: only recent mail, and never more than max_messages of it.
    lookback_days: int = 14
    max_messages: int = 200
    max_body_chars: int = 20_000
    timeout_seconds: int = 30

    @property
    def configured(self) -> bool:
        return bool(self.host and self.user and self.password)


def load_config(env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    use_ssl = _flag(env.get("IMAP_SSL", "true"))
    return Config(
        host=env.get("IMAP_HOST", "").strip(),
        port=_int(env, "IMAP_PORT", 993 if use_ssl else 143),
        use_ssl=use_ssl,
        user=env.get("IMAP_USER", "").strip(),
        password=env.get("IMAP_PASSWORD", ""),
        folder=env.get("IMAP_FOLDER", "INBOX").strip() or "INBOX",
        lookback_days=_int(env, "IMAP_LOOKBACK_DAYS", 14),
        max_messages=_int(env, "IMAP_MAX_MESSAGES", 200),
        max_body_chars=_int(env, "IMAP_MAX_BODY_CHARS", 20_000),
        timeout_seconds=_int(env, "IMAP_TIMEOUT_SECONDS", 30),
    )
