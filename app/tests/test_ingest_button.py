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
from app.ingestion import jobs
from app.ingestion import routes as ingestion_routes


@pytest.fixture(autouse=True)
def fresh_job_state():
    jobs.job.__dict__.update(jobs.PollJob().__dict__)
    yield
    jobs.job.__dict__.update(jobs.PollJob().__dict__)


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
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
    assert "disabled" not in html.split("<button", 1)[1].split(">", 1)[0]  # idle: clickable


def test_synchronous_poll_still_returns_the_processed_count(client, monkeypatch):
    _stub_poll(monkeypatch, 3)
    r = client.post("/ingest/poll")
    assert (r.status_code, r.json()) == (200, {"processed": 3})


async def test_synchronous_poll_reports_busy_when_a_poll_is_running(client, monkeypatch):
    _stub_poll(monkeypatch, 1)
    async with ingestion_routes._poll_lock:
        r = client.post("/ingest/poll")
    assert r.status_code == 409
