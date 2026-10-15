import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from app.main import app
from app.security import SAFE_METHODS, blocked_reason

HOST = "localhost:8000"


def check(method: str, **headers: str) -> str | None:
    return blocked_reason(method, Headers({"host": HOST, **{k.replace("_", "-"): v for k, v in headers.items()}}))


# --- the decision, in isolation ---


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_safe_methods_are_never_refused_even_cross_site(method):
    assert check(method, sec_fetch_site="cross-site", origin="https://evil.example") is None


def test_a_client_that_sends_no_browser_headers_is_allowed():
    # curl, scripts, tests: they send credentials on purpose, nothing ambient to abuse.
    assert check("POST") is None


@pytest.mark.parametrize("site", ["same-origin", "none"])
def test_same_origin_and_direct_user_actions_are_allowed(site):
    assert check("POST", sec_fetch_site=site) is None


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_other_sites_are_refused_including_same_site(site):
    # same-site matters: on localhost every port is "same-site", so a page served
    # by EspoCRM (:8080) or Adminer (:8082) must not be able to approve here.
    assert "Sec-Fetch-Site" in (check("POST", sec_fetch_site=site) or "")


def test_origin_must_be_this_host_when_sec_fetch_site_is_absent():
    assert check("POST", origin=f"http://{HOST}") is None
    assert check("POST", origin="HTTP://LOCALHOST:8000") is None  # host comparison ignores case
    assert check("POST", origin="https://evil.example")
    assert check("POST", origin="http://localhost:8080")  # same host, different port
    assert check("POST", origin="null")  # sandboxed frames and some redirects


def test_sec_fetch_site_is_trusted_over_origin():
    # The browser sets Sec-Fetch-Site itself; when it says same-origin there is nothing to second-guess.
    assert check("POST", sec_fetch_site="same-origin", origin="https://evil.example") is None


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_every_unsafe_method_is_covered(method):
    assert check(method, sec_fetch_site="cross-site")


# --- wired into the real app ---

client = TestClient(app)  # no `with`: startup (migrations) is not run


def unsafe_routes() -> list[tuple[str, str]]:
    found = []
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        for method in methods - SAFE_METHODS:
            found.append((method, route.path))  # type: ignore[attr-defined]
    return sorted(found)


def test_the_app_has_state_changing_routes_to_protect():
    # Guards the test below against silently checking nothing.
    assert len(unsafe_routes()) >= 5


@pytest.mark.parametrize(("method", "path"), unsafe_routes())
def test_every_state_changing_route_refuses_cross_site_requests(method, path):
    url = path.replace("{proposed_action_id}", "x")
    r = client.request(method, url, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403, f"{method} {path} accepted a cross-site request"
    assert "Cross-site request refused" in r.text


@pytest.mark.parametrize(("method", "path"), unsafe_routes())
def test_same_origin_requests_still_reach_authentication(method, path):
    url = path.replace("{proposed_action_id}", "x")
    r = client.request(method, url, headers={"Origin": "http://testserver"})
    assert r.status_code == 401  # got past the CSRF check; the login still guards it


def test_a_cross_site_get_still_works():
    r = client.get("/health", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 200


@pytest.mark.parametrize("path", ["/health", "/approvals"])
def test_pages_cannot_be_framed(path):
    r = client.get(path)  # /approvals answers 401 here; the headers must be on it too
    assert r.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_the_refusal_itself_also_carries_the_headers():
    r = client.post("/ingest/start", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403 and r.headers["x-frame-options"] == "DENY"
