"""GET /ready: can this stack process an email right now?

Separate from /health on purpose. /health only says the app process is up,
which is true minutes before the model is: a cold load of the 7B model took
~3 minutes on CPU with free memory and ~20 when the host was short of it, and
polling during it can fail and restart the load. /ready is the one to wait on before a demo or a first poll.

Open (no login) like /health; it returns only booleans and short reasons.
"""

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.db.session import engine

router = APIRouter(tags=["health"])


def _database() -> dict[str, object]:
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        return {"ready": True}
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return {"ready": False, "detail": f"{type(exc).__name__}"}


def _llm() -> dict[str, object]:
    settings = get_settings()
    if settings.llm_provider != "ollama":
        configured = bool(settings.anthropic_api_key)
        return {
            "provider": settings.llm_provider,
            "ready": configured,
            **({} if configured else {"detail": "ANTHROPIC_API_KEY is empty"}),
        }
    try:
        response = httpx.get(f"{settings.ollama_base_url.rstrip('/')}/api/ps", timeout=3.0)
        response.raise_for_status()
        loaded = [m.get("name") for m in response.json().get("models", [])]
    except Exception as exc:  # noqa: BLE001
        return {"provider": "ollama", "ready": False, "detail": f"Ollama unreachable ({type(exc).__name__})"}
    if settings.ollama_model in loaded:
        return {"provider": "ollama", "ready": True, "model": settings.ollama_model}
    return {
        "provider": "ollama",
        "ready": False,
        "model": settings.ollama_model,
        "detail": "model not loaded yet (a cold load takes a few minutes, longer if memory is short); see docker compose logs ollama",
    }


@router.get("/ready")
def ready() -> JSONResponse:
    checks = {"database": _database(), "llm": _llm()}
    ok = all(c["ready"] for c in checks.values())
    return JSONResponse(status_code=200 if ok else 503, content={"ready": ok, **checks})
