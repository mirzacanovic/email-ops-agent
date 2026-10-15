import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import readiness
from app.config import Settings
from app.connectors.espocrm import EspoCRMConnector
from app.connectors.plane import PlaneConnector
from app.llm.factory import get_llm_client
from app.llm.ollama_client import OllamaClient


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(readiness.router)
    return TestClient(app)


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def _ollama_says(monkeypatch, models: list[str] | Exception):
    def fake_get(url, timeout):
        if isinstance(models, Exception):
            raise models
        return httpx.Response(
            200, json={"models": [{"name": m} for m in models]}, request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(readiness.httpx, "get", fake_get)


def test_ready_when_database_up_and_model_loaded(client, monkeypatch):
    monkeypatch.setattr(readiness, "get_settings", lambda: _settings(ollama_model="m:7b"))
    monkeypatch.setattr(readiness, "_database", lambda: {"ready": True})
    _ollama_says(monkeypatch, ["m:7b"])

    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json()["llm"] == {"provider": "ollama", "ready": True, "model": "m:7b"}


def test_not_ready_while_the_model_is_still_loading(client, monkeypatch):
    monkeypatch.setattr(readiness, "get_settings", lambda: _settings(ollama_model="m:7b"))
    monkeypatch.setattr(readiness, "_database", lambda: {"ready": True})
    _ollama_says(monkeypatch, [])  # Ollama only lists a model once it is fully loaded

    r = client.get("/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["ready"] is False and body["llm"]["ready"] is False
    assert "not loaded" in body["llm"]["detail"]


def test_not_ready_when_ollama_is_unreachable(client, monkeypatch):
    monkeypatch.setattr(readiness, "get_settings", lambda: _settings())
    monkeypatch.setattr(readiness, "_database", lambda: {"ready": True})
    _ollama_says(monkeypatch, httpx.ConnectError("refused"))

    r = client.get("/ready")
    assert r.status_code == 503
    assert "unreachable" in r.json()["llm"]["detail"]


def test_not_ready_when_the_database_is_down(client, monkeypatch):
    monkeypatch.setattr(readiness, "get_settings", lambda: _settings(ollama_model="m:7b"))
    monkeypatch.setattr(readiness, "_database", lambda: {"ready": False, "detail": "OperationalError"})
    _ollama_says(monkeypatch, ["m:7b"])

    r = client.get("/ready")
    assert r.status_code == 503
    assert r.json()["database"]["ready"] is False


def test_claude_provider_needs_an_api_key(client, monkeypatch):
    monkeypatch.setattr(readiness, "_database", lambda: {"ready": True})
    monkeypatch.setattr(readiness, "get_settings", lambda: _settings(llm_provider="claude"))
    assert client.get("/ready").status_code == 503

    monkeypatch.setattr(
        readiness, "get_settings", lambda: _settings(llm_provider="claude", anthropic_api_key="k")
    )
    assert client.get("/ready").status_code == 200


def test_ready_is_open_like_health(client, monkeypatch):
    monkeypatch.setattr(readiness, "get_settings", lambda: _settings())
    monkeypatch.setattr(readiness, "_database", lambda: {"ready": True})
    _ollama_says(monkeypatch, [])
    assert client.get("/ready").status_code != 401  # no login needed to ask


# --- timeouts are settings now, not hard-coded numbers ---


def test_timeouts_default_to_the_values_the_rehearsal_needed():
    s = _settings()
    assert (s.espocrm_timeout_seconds, s.plane_timeout_seconds, s.ollama_timeout_seconds) == (
        60.0,
        30.0,
        300.0,
    )


def test_timeout_settings_reach_the_clients():
    s = _settings(espocrm_timeout_seconds=61, plane_timeout_seconds=32, ollama_timeout_seconds=303)
    espo = EspoCRMConnector("http://x", "k", timeout=s.espocrm_timeout_seconds)
    plane = PlaneConnector("http://x", "k", "ws", timeout=s.plane_timeout_seconds)
    llm = get_llm_client(s)
    assert isinstance(llm, OllamaClient)
    assert espo._client.timeout.read == 61
    assert plane._client.timeout.read == 32
    assert llm._client.timeout.read == 303
