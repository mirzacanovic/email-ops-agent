# Roadmap

Where this project actually is, and what's left — kept current so a new
session (or a client walkthrough) doesn't have to reconstruct it from git
history.

## Done and verified

The Phase 1 loop runs end to end against real systems, not mocks:

- Email intake (simulator) → classify → extract → match → propose →
  human approval → execute → audit trail, all working
  ([docs/architecture.md](architecture.md)).
- Self-hosted LLM backend (Ollama/Mistral) for classify/extract,
  swappable for Claude via `LLM_PROVIDER`
  ([docs/llm-backend.md](llm-backend.md)).
- EspoCRM connector: verified end to end — a real Lead created and later
  updated via exact-email match.
- Plane connector: verified end to end — a real work item created, and a
  follow-up email correctly matched and updated it instead of filing a
  duplicate.
- CI: lint, type-check, unit tests, image builds, and compose validation
  on every push (`.github/workflows/ci.yml`).

## Near-term: hardening the current loop

Gaps found by actually running the pipeline against live systems, not
theoretical ones — this is what stands between "the demo works" and "I'd
trust this in front of a client."

- **Extraction accuracy on open-ended fields.** Fields with a clear
  anchor (the sender's email address) extract reliably; open-ended
  summarization (issue descriptions, lead descriptions) is still
  inconsistent on a 7B CPU model — see the `description`/
  `description_html` mix-ups found in testing. Two paths forward: try a
  stronger local model (Mistral Small, Mixtral), or treat the
  human-approval step as the actual safety net here rather than trying
  to prompt-engineer this away entirely.
- **The ingestion cursor doesn't handle failed messages.**
  `poll_and_process`'s `since` cursor is `max(received_at)` over
  *successfully* processed messages — an email that fails (transient
  error, timeout) becomes permanently unreachable once a *later* email
  succeeds, since the cursor has already moved past it. Needs
  per-message processed-state instead of a single watermark.
- **No real auth on the approval UI.** `DEMO_APPROVER` is hardcoded in
  `approval/routes.py`. Fine for a solo demo, not for anything with more
  than one reviewer.
- **`create_all` instead of Alembic.** Fine while the schema is still
  moving; switch before the audit trail holds anything real.
- **No way to trigger ingestion from the UI.** `/ingest/poll` is
  curl-only right now — a button on the approvals page would make the
  demo self-contained.

## Phase 2: demo polish

- 3–5 rehearsed golden-path scenarios plus 1–2 deliberate edge cases (no
  match found, ambiguous intent, low-confidence escalation) — a fixed
  script for walkthroughs rather than whatever the fixtures happen to do.
- A simple metrics view (time-to-resolution, approval rate, confidence
  distribution) — numbers land better than "look, it worked" in a pitch.
- Recorded walkthrough plus written case-study framing.

## Phase 3: expansion

- **More systems**: Zammad (helpdesk), ERPNext — same connector
  interface, new adapters, no pipeline changes.
- **Real inbox** instead of the simulator, once there's a pilot client —
  a sandboxed domain first.
- **Multi-step workflows**: one email triggering actions across more
  than one system (CRM update + project task + helpdesk ticket from a
  single message).
- **Confidence-gated auto-execution**: skip human approval below a
  configurable risk threshold for low-stakes actions, always require it
  above — once there's enough real-world accuracy data to set that
  threshold responsibly.
- **Observability/tracing** on the pipeline stages — useful for
  debugging, and as a client-facing "see what it's doing" feature.
- **Package the connector interface + approval UI as a starter
  template**, so a new client engagement is "write two adapters," not
  "rebuild the pipeline."
- **Revisit CI image publishing** (GHCR) once there's an actual
  deployment target this would serve.

## Explicitly out of scope for now

Noted so it doesn't get re-litigated every session:

- GPU inference or a cloud LLM as the *default* backend — the point is
  on-prem for EU data residency ([docs/llm-backend.md](llm-backend.md)).
- Vendoring Plane's own hosting into this repo's docker-compose
  ([docs/plane-setup.md](plane-setup.md)) — Plane Cloud or a separate
  self-host, not this repo's problem to run.
