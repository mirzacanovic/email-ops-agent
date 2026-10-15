from fastapi import FastAPI

from app.approval.routes import router as approval_router
from app.db.migrate import run_migrations
from app.db.session import engine
from app.ingestion.routes import router as ingestion_router
from app.metrics.routes import router as metrics_router
from app.readiness import router as readiness_router
from app.security import SecurityMiddleware

app = FastAPI(title="Email Ops Agent")
# Refuses cross-site state-changing requests and sets anti-framing headers;
# see app/security.py for why Basic auth makes this necessary.
app.add_middleware(SecurityMiddleware)
app.include_router(approval_router)
app.include_router(ingestion_router)
app.include_router(metrics_router)
app.include_router(readiness_router)


@app.on_event("startup")
def migrate_database() -> None:
    # Brings a fresh or pre-Alembic database up to date; see app/db/migrate.py.
    run_migrations(engine)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
