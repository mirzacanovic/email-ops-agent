from fastapi import FastAPI

from app.approval.routes import router as approval_router
from app.audit.models import Base
from app.db.session import engine
from app.ingestion.routes import router as ingestion_router

app = FastAPI(title="Email Ops Agent")
app.include_router(approval_router)
app.include_router(ingestion_router)


@app.on_event("startup")
def create_audit_tables() -> None:
    # TODO(phase-2): replace with Alembic migrations once the schema
    # needs to evolve without dropping data.
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
