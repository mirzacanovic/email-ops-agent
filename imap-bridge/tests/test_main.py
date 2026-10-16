import pytest
from fastapi.testclient import TestClient

from imap_bridge import main, mailbox
from imap_bridge.config import Config, load_config

PASSWORD = "hunter2-very-secret"


def make_cfg(**overrides) -> Config:
    base = dict(host="imap.example", port=993, use_ssl=True, user="u@x.example", password=PASSWORD)
    return Config(**{**base, **overrides})


MESSAGES = [
    {"id": "a@x", "from": "a@x.example", "to": "s@x.example", "subject": "One", "body": "b", "received_at": "2026-09-15T09:00:00Z"},
    {"id": "b@x", "from": "b@x.example", "to": "s@x.example", "subject": "Two", "body": "b", "received_at": "2026-09-16T09:00:00Z"},
]


@pytest.fixture
def client():
    app = main.app
    app.dependency_overrides[main.get_config] = lambda: make_cfg()
    app.dependency_overrides[main.get_fetcher] = lambda: (lambda cfg, since: list(MESSAGES))
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_messages_are_served_in_the_simulators_shape(client):
    r = client.get("/messages")
    assert r.status_code == 200
    assert r.json() == MESSAGES
    assert set(r.json()[0]) == {"id", "from", "to", "subject", "body", "received_at"}


def test_since_filters_like_the_simulator_does(client):
    r = client.get("/messages", params={"since": "2026-09-15T09:00:00Z"})
    assert [m["id"] for m in r.json()] == ["b@x"]  # strictly newer than `since`


def test_the_fetcher_is_asked_for_the_lookback_window():
    seen = {}

    def fetch(cfg, since):
        seen["since"] = since
        return []

    app = main.app
    app.dependency_overrides[main.get_config] = lambda: make_cfg(lookback_days=3)
    app.dependency_overrides[main.get_fetcher] = lambda: fetch
    try:
        TestClient(app).get("/messages")
    finally:
        app.dependency_overrides.clear()
    from datetime import datetime, timedelta, timezone

    age = datetime.now(timezone.utc) - seen["since"]
    assert timedelta(days=3) - timedelta(minutes=1) < age < timedelta(days=3) + timedelta(minutes=1)


def test_unconfigured_service_says_so_instead_of_returning_an_empty_inbox():
    app = main.app
    app.dependency_overrides[main.get_config] = lambda: make_cfg(host="", password="")
    try:
        c = TestClient(app)
        assert c.get("/messages").status_code == 503
        assert c.get("/health").json() == {"status": "ok", "configured": False}
        assert c.get("/ready").status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_a_mailbox_failure_is_a_502_with_a_safe_message():
    def broken(cfg, since):
        raise mailbox.MailboxError("IMAP login failed (check IMAP_USER and IMAP_PASSWORD)")

    app = main.app
    app.dependency_overrides[main.get_config] = lambda: make_cfg()
    app.dependency_overrides[main.get_fetcher] = lambda: broken
    try:
        r = TestClient(app).get("/messages")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 502
    assert "login failed" in r.json()["detail"] and PASSWORD not in r.text


def test_ready_reflects_whether_the_mailbox_can_be_opened(client, monkeypatch):
    monkeypatch.setattr(mailbox, "check_connection", lambda cfg: None)
    assert client.get("/ready").json() == {"ready": True, "folder": "INBOX"}

    def fail(cfg):
        raise mailbox.MailboxError("Cannot reach the IMAP server imap.example:993 (OSError)")

    monkeypatch.setattr(mailbox, "check_connection", fail)
    r = client.get("/ready")
    assert r.status_code == 503 and "Cannot reach" in r.json()["detail"]


def test_health_never_exposes_the_password(client):
    assert PASSWORD not in client.get("/health").text


# --- configuration ---


def test_config_defaults_to_tls_on_993_and_a_bounded_window():
    cfg = load_config({"IMAP_HOST": "h", "IMAP_USER": "u", "IMAP_PASSWORD": "p"})
    assert (cfg.port, cfg.use_ssl, cfg.folder, cfg.lookback_days, cfg.max_messages) == (993, True, "INBOX", 14, 200)
    assert cfg.configured


def test_plain_imap_defaults_to_port_143():
    assert load_config({"IMAP_SSL": "false"}).port == 143
    assert load_config({"IMAP_SSL": "0"}).use_ssl is False
    assert load_config({"IMAP_SSL": "no", "IMAP_PORT": "3143"}).port == 3143


def test_nothing_set_means_not_configured():
    assert not load_config({}).configured


@pytest.mark.parametrize("bad", [{"IMAP_PORT": "abc"}, {"IMAP_LOOKBACK_DAYS": "0"}, {"IMAP_MAX_MESSAGES": "-5"}])
def test_invalid_numbers_are_rejected_clearly(bad):
    with pytest.raises(ValueError, match="IMAP_"):
        load_config(bad)


def test_the_password_never_appears_in_repr_or_str():
    cfg = load_config({"IMAP_HOST": "h", "IMAP_USER": "u", "IMAP_PASSWORD": PASSWORD})
    assert PASSWORD not in repr(cfg) and PASSWORD not in str(cfg)
