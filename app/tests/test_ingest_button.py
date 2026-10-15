import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.approval.routes import router as approval_router
from app.audit.models import Base, User
from app.auth.deps import require_user
from app.db.session import get_db
from app.dependencies import get_espocrm_connector, get_llm, get_plane_connector
from app.ingestion import routes as ingestion_routes


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def override_db():
        with Session() as session:
            yield session

    app = FastAPI()
    app.include_router(approval_router)
    app.include_router(ingestion_routes.router)
    app.dependency_overrides[get_db] = override_db
    # Auth itself is covered in test_auth.py; here every request is a logged-in user.
    app.dependency_overrides[require_user] = lambda: User(username="tester", password_hash="x")
    app.dependency_overrides[get_llm] = lambda: None
    app.dependency_overrides[get_espocrm_connector] = lambda: None
    app.dependency_overrides[get_plane_connector] = lambda: None
    return TestClient(app)


def _stub_poll(monkeypatch, result):
    async def fake(**_kwargs):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(ingestion_routes, "poll_and_process", fake)


def test_button_is_rendered_on_approvals_page(client):
    html = client.get("/approvals").text
    assert 'action="/ingest/poll-form"' in html


def test_poll_form_redirects_with_processed_count(client, monkeypatch):
    _stub_poll(monkeypatch, 3)
    r = client.post("/ingest/poll-form", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/approvals?poll=ok&processed=3"
    assert "3 new messages processed" in client.get(r.headers["location"]).text


def test_poll_form_redirects_with_error_when_poll_raises(client, monkeypatch):
    _stub_poll(monkeypatch, RuntimeError("simulator down"))
    r = client.post("/ingest/poll-form", follow_redirects=False)
    assert r.headers["location"] == "/approvals?poll=error"


async def test_poll_form_reports_busy_when_a_poll_is_running(client, monkeypatch):
    _stub_poll(monkeypatch, 1)
    async with ingestion_routes._poll_lock:
        r = client.post("/ingest/poll-form", follow_redirects=False)
    assert r.headers["location"] == "/approvals?poll=busy"
