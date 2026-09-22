# Email Ops Agent

[![CI](https://github.com/mirzacanovic/email-ops-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/mirzacanovic/email-ops-agent/actions/workflows/ci.yml)

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
- **Ollama** — self-hosted, open-weight model (Mistral by default) for
  classify/extract, so email content never leaves the stack. See
  [docs/llm-backend.md](docs/llm-backend.md).
- **app** — the orchestrator: classification/extraction, record matching,
  action proposal, approval UI, execution, audit log.

See [docs/architecture.md](docs/architecture.md) for how the pieces fit
together, [docs/plane-setup.md](docs/plane-setup.md) for why Plane isn't
in `docker-compose.yml`, [docs/llm-backend.md](docs/llm-backend.md) for
the LLM backend choice, and [docs/roadmap.md](docs/roadmap.md) for what's
done, what's next, and what's deliberately out of scope for now.

## Repo layout

```
email-ops-agent/
├── .github/workflows/ci.yml  # lint, type-check, unit tests, image builds, compose validation
├── docker-compose.yml        # app-db, adminer, email-simulator, app, EspoCRM(+db+daemon)
├── .env.example
├── requirements-dev.txt      # CI tooling (ruff, mypy, pytest) -- not in either runtime image
├── app/                      # orchestrator: FastAPI service
│   ├── pytest.ini
│   ├── tests/                # propose.py decision rules, match.py scoring, schema translation
│   └── src/app/
│       ├── connectors/       # one interface, one adapter per SaaS system
│       ├── llm/              # one interface, one adapter per model backend (Ollama/Claude)
│       ├── pipeline/         # classify -> extract -> match -> propose -> execute
│       ├── approval/         # human-in-the-loop review UI
│       ├── audit/            # audit-log models
│       └── db/               # SQLAlchemy session (create_all for now; Alembic later)
├── email-simulator/          # serves fixture emails over HTTP
│   ├── pytest.ini
│   ├── tests/
│   └── src/email_simulator/fixtures/
├── scripts/                  # seed data, demo reset
└── docs/
```

## Quickstart

1. Copy `.env.example` to `.env` (defaults use the self-hosted Ollama
   backend, so `ANTHROPIC_API_KEY` is only needed if you set
   `LLM_PROVIDER=claude`; fill in `PLANE_*` once you've stood up Plane —
   see docs/plane-setup.md).
2. `docker compose up --build` — first run also pulls the Ollama model
   (a few GB), which takes a few minutes; `ollama-pull` exits when done.
3. EspoCRM: http://localhost:8080 (admin / value of `ESPOCRM_ADMIN_PASSWORD`)
   — generate an API key under Administration → API Users and set
   `ESPOCRM_API_KEY`, then run `python scripts/seed_espocrm.py`.
4. Email simulator: http://localhost:8001/docs
5. Orchestrator API: http://localhost:8000/docs
6. Ollama: http://localhost:11434 (`GET /api/tags` to confirm the model pulled)
7. Adminer (DB browser, for watching the audit trail fill up live):
   http://localhost:8082 — system: PostgreSQL, server: `app-db`
8. Run the pipeline: `curl -X POST http://localhost:8000/ingest/poll` pulls
   whatever's new from the email simulator through
   classify → extract → match → propose.
9. Review proposals: http://localhost:8000/approvals — approve calls the
   target system's API for real (EspoCRM if `ESPOCRM_API_KEY` is set;
   Plane if `PLANE_*` is configured), reject just records the decision.

## Development

CI (`.github/workflows/ci.yml`) runs lint, type-check, unit tests, and a
build of both images on every push/PR. To run the same checks locally:

```bash
pip install -r requirements-dev.txt -r app/requirements.txt -r email-simulator/requirements.txt

ruff check app email-simulator

cd app && MYPYPATH=src mypy src/app tests --explicit-package-bases && pytest && cd ..
cd email-simulator && MYPYPATH=src mypy src/email_simulator tests --explicit-package-bases && pytest && cd ..
```

Unit tests cover the pure-logic pieces — `propose.py`'s decision rules,
`match.py`'s fuzzy scoring, EspoCRM's schema-translation — not the
connectors' actual HTTP calls (those need a real EspoCRM/Plane, which is
what `docker compose up` + a manual `/ingest/poll` run is for).

## Status

Phase 1 — the full loop runs end to end against live systems (a real
EspoCRM instance and a real Plane Cloud workspace), not mocks. See
[docs/roadmap.md](docs/roadmap.md) for the current gap list and what's
next.
