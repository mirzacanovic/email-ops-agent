# Email Ops Agent

Portfolio project: an AI agent that reads an inbound email, extracts structured
information, searches existing records across a company's SaaS stack, proposes
an action, waits for human approval, executes it via API, and records an
audit trail for every step.

Demo stack (Phase 1):

- **Email simulator** — serves fixture emails instead of a real inbox, so
  scenarios are deterministic and replayable.
- **EspoCRM** — CRM (contacts, leads, accounts).
- **Plane** — project management (issues) — run separately, see
  [docs/plane-setup.md](docs/plane-setup.md).
- **app** — the orchestrator: classification/extraction, record matching,
  action proposal, approval UI, execution, audit log.

See [docs/architecture.md](docs/architecture.md) for how the pieces fit
together and [docs/plane-setup.md](docs/plane-setup.md) for why Plane isn't
in `docker-compose.yml`.

## Repo layout

```
email-ops-agent/
├── docker-compose.yml        # app-db, adminer, email-simulator, app, EspoCRM(+db+daemon)
├── .env.example
├── app/                      # orchestrator: FastAPI service
│   └── src/app/
│       ├── connectors/       # one interface, one adapter per SaaS system
│       ├── pipeline/         # classify -> extract -> match -> propose -> execute
│       ├── approval/         # human-in-the-loop review UI
│       ├── audit/            # audit-log models
│       └── db/               # SQLAlchemy session (create_all for now; Alembic later)
├── email-simulator/          # serves fixture emails over HTTP
│   └── src/email_simulator/fixtures/
├── scripts/                  # seed data, demo reset
└── docs/
```

## Quickstart

1. Copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY` (and
   `PLANE_*` once you've stood up Plane — see docs/plane-setup.md).
2. `docker compose up --build`
3. EspoCRM: http://localhost:8080 (admin / value of `ESPOCRM_ADMIN_PASSWORD`)
4. Email simulator: http://localhost:8001/docs
5. Orchestrator API: http://localhost:8000/docs
6. Adminer (DB browser, for watching the audit trail fill up live):
   http://localhost:8082 — system: PostgreSQL, server: `app-db`

## Status

Phase 0 scaffold — services boot and health-check, connector interface and
audit schema are in place, but the classify/extract/match/propose/execute
pipeline steps are stubs. See inline `TODO(phase-1)` markers.
