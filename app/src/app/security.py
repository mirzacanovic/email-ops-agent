"""Cross-site request protection for the whole app.

Why this is needed: the app authenticates with HTTP Basic, and a browser that
has logged in sends those credentials automatically with *every* request to
this host, including one fired by a form on some other website. Without a
check, a page the reviewer happens to visit could post to
/approvals/<id>/approve or /ingest/start and the app would treat it as the
reviewer's own click.

The classic fix, a per-session secret token in each form, needs a session, and
this app deliberately has none. Instead we check what the browser itself says
about where the request came from. Those headers are set by the browser and
cannot be set or changed by JavaScript on another site:

  * Sec-Fetch-Site: only "same-origin" (or "none", a direct user action such as
    a bookmark) is accepted. "same-site" is refused too: on localhost every
    port counts as same-site, so a compromised page on EspoCRM or Adminer
    (other ports on the same host) must not be able to approve things here.
  * Origin, for browsers that do not send Sec-Fetch-Site: must be this host.
  * Neither header: not a browser (curl, scripts, tests). Such a client sends
    its credentials on purpose, so there is no ambient authority to abuse, and
    refusing it would break every scripted use of the API.

Safe methods (GET/HEAD/OPTIONS) are never refused; no GET in this app changes
state, and keeping it that way is what makes this check sufficient.

Also sets frame-ancestors 'none': otherwise another site could embed this page
in an invisible frame and trick the reviewer into clicking Approve ("clickjacking"),
which is the same attack by a different route.

Behind a reverse proxy this assumes the proxy forwards the original Host header
(the default for nginx/Traefik with `proxy_set_header Host $host`).
"""

from collections.abc import Mapping
from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

SECURITY_HEADERS = [
    (b"content-security-policy", b"frame-ancestors 'none'"),
    (b"x-frame-options", b"DENY"),  # older browsers that ignore frame-ancestors
    (b"x-content-type-options", b"nosniff"),
]


def blocked_reason(method: str, headers: Mapping[str, str]) -> str | None:
    """Why this request looks cross-site, or None if it may proceed.

    `headers` must be case-insensitive (Starlette's Headers) or already lowercase.
    """
    if method.upper() in SAFE_METHODS:
        return None

    site = headers.get("sec-fetch-site")
    if site is not None:
        return None if site in ("same-origin", "none") else f"Sec-Fetch-Site: {site}"

    origin = headers.get("origin")
    if origin is not None:
        # "null" is what browsers send from sandboxed frames and some redirects.
        if origin == "null" or urlsplit(origin).netloc.lower() != headers.get("host", "").lower():
            return f"Origin: {origin}"

    return None


class SecurityMiddleware:
    """Pure ASGI (not BaseHTTPMiddleware) so it adds no per-request overhead
    and cannot interfere with the background poll task."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        reason = blocked_reason(scope["method"], headers)

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), *SECURITY_HEADERS]}
            await send(message)

        if reason is not None:
            response = JSONResponse(
                {"detail": f"Cross-site request refused ({reason})"}, status_code=403
            )
            await response(scope, receive, send_with_security_headers)
            return
        await self.app(scope, receive, send_with_security_headers)
