"""The background "check inbox" job: starts instantly, reports progress, and
survives the request that started it. These tests use an async client so the
job's task keeps running on the test's event loop between requests."""

import asyncio

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.approval.routes import router as approval_router
from app.audit.models import Base, User
from app.auth.deps import require_user
from app.db.session import get_db
from app.ingestion import jobs
from app.ingestion import routes as ingestion_routes


@pytest.fixture(autouse=True)
def fresh_job_state():
    jobs.job.__dict__.update(jobs.PollJob().__dict__)
    yield
    jobs.job.__dict__.update(jobs.PollJob().__dict__)


@pytest.fixture
async def client():
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
    app.dependency_overrides[require_user] = lambda: User(username="tester", password_hash="x")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


class FakePoll:
    """Stands in for poll_and_process: reports 3 emails, then waits to be released."""

    def __init__(self, processed: int = 3, total: int = 3, error: Exception | None = None):
        self.release = asyncio.Event()
        self.processed, self.total, self.error = processed, total, error

    async def __call__(self, **kwargs):
        progress = kwargs["progress"]
        progress(0, self.total)
        progress(1, self.total)
        await self.release.wait()
        if self.error:
            raise self.error
        progress(self.total, self.total)
        return self.processed


async def settled(client, state: str, attempts: int = 200) -> dict:
    for _ in range(attempts):
        body = (await client.get("/ingest/status")).json()
        if body["state"] == state:
            return body
        await asyncio.sleep(0.01)
    raise AssertionError(f"job never reached {state!r}: {body}")


async def test_status_is_idle_before_any_job(client):
    body = (await client.get("/ingest/status")).json()
    assert body["state"] == "idle"
    assert body["failed"] is None


async def test_start_returns_immediately_while_the_job_keeps_running(client, monkeypatch):
    poll = FakePoll()
    monkeypatch.setattr(ingestion_routes, "poll_and_process", poll)

    started = await client.post("/ingest/start")
    assert started.status_code == 202  # returned without waiting for the poll

    running = await settled(client, "running")
    assert (running["handled"], running["total"]) == (1, 3)  # progress is visible mid-run

    poll.release.set()
    done = await settled(client, "done")
    assert (done["processed"], done["failed"], done["handled"]) == (3, 0, 3)
    assert done["finished_at"] is not None


async def test_second_start_while_running_is_refused(client, monkeypatch):
    poll = FakePoll()
    monkeypatch.setattr(ingestion_routes, "poll_and_process", poll)
    assert (await client.post("/ingest/start")).status_code == 202

    again = await client.post("/ingest/start")
    assert again.status_code == 409
    assert again.json()["state"] == "running"

    poll.release.set()
    await settled(client, "done")


async def test_synchronous_poll_is_refused_while_a_job_holds_the_lock(client, monkeypatch):
    poll = FakePoll()
    monkeypatch.setattr(ingestion_routes, "poll_and_process", poll)
    await client.post("/ingest/start")
    await settled(client, "running")
    await asyncio.sleep(0.02)  # let the job reach and take the poll lock

    assert (await client.post("/ingest/poll")).status_code == 409

    poll.release.set()
    await settled(client, "done")


async def test_emails_that_fail_are_reported_not_hidden(client, monkeypatch):
    poll = FakePoll(processed=2, total=3)
    monkeypatch.setattr(ingestion_routes, "poll_and_process", poll)
    await client.post("/ingest/start")
    poll.release.set()

    done = await settled(client, "done")
    assert (done["processed"], done["failed"]) == (2, 1)


async def test_a_crashing_job_is_reported_and_a_new_one_can_start(client, monkeypatch):
    poll = FakePoll(error=RuntimeError("simulator down"))
    monkeypatch.setattr(ingestion_routes, "poll_and_process", poll)
    await client.post("/ingest/start")
    poll.release.set()

    failed = await settled(client, "error")
    assert "simulator down" in failed["error"]

    retry = FakePoll()
    monkeypatch.setattr(ingestion_routes, "poll_and_process", retry)
    assert (await client.post("/ingest/start")).status_code == 202
    retry.release.set()
    await settled(client, "done")


async def test_button_redirects_at_once_and_page_shows_progress_then_result(client, monkeypatch):
    poll = FakePoll()
    monkeypatch.setattr(ingestion_routes, "poll_and_process", poll)

    redirect = await client.post("/ingest/poll-form")
    assert (redirect.status_code, redirect.headers["location"]) == (303, "/approvals")

    await settled(client, "running")
    page = (await client.get("/approvals")).text
    assert "1 of 3 emails done" in page
    assert 'http-equiv="refresh"' in page  # keeps itself current while running
    assert "disabled" in page.split("<button", 1)[1].split(">", 1)[0]

    poll.release.set()
    await settled(client, "done")
    page = (await client.get("/approvals")).text
    assert "3 new messages processed" in page
    assert 'http-equiv="refresh"' not in page  # stops refreshing once finished


async def test_page_reports_a_failed_job(client, monkeypatch):
    poll = FakePoll(error=RuntimeError("simulator down"))
    monkeypatch.setattr(ingestion_routes, "poll_and_process", poll)
    await client.post("/ingest/poll-form")
    poll.release.set()
    await settled(client, "error")

    assert "simulator down" in (await client.get("/approvals")).text
