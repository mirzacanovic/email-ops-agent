# Architecture

```
Email simulator ──▶ ingestion ──▶ classify ──▶ extract ──▶ match ──▶ propose
                                                                        │
                                                                        ▼
                                                                    approval
                                                                (human approve/
                                                                 edit/reject)
                                                                        │
                                                                        ▼
                                                                     execute ──▶ Plane / EspoCRM
                                                                        │
                                                                        ▼
                                                                   audit log
```

## Design decisions

- **One LLM interface, one adapter per backend**
  (`app/src/app/llm/base.py`). classify/extract depend only on
  `LLMClient.complete_json`, never on Ollama or Claude directly — see
  [docs/llm-backend.md](llm-backend.md) for why the default backend is a
  self-hosted open-weight model rather than a cloud API.

- **One connector interface, one adapter per system**
  (`app/src/app/connectors/base.py`). `search_records` / `create_record` /
  `update_record` / `get_schema` are the only methods the pipeline calls.
  Adding Zammad or ERPNext later — or swapping EspoCRM for a client's real
  Salesforce — means writing a new adapter, not touching the pipeline.
  `get_schema` always returns real JSON Schema, narrowed to a
  per-entity allowlist of fields (see `EXTRACTABLE_FIELDS` in
  `connectors/espocrm.py`) — extraction is never exposed to a system's
  full internal field set, only the ones it's safe to fill from email
  content.

- **Matching is two passes, both logged** (`app/src/app/pipeline/match.py`):
  exact match on sender email first, then a fuzzy pass on account/company
  name via the connector's `_fulltext` search convention, scored locally
  with `difflib`. Every candidate considered is kept, not just the best
  one, so a human reviewer can see what else was close.

- **Every pipeline stage is a separate, inspectable function**
  (`app/src/app/pipeline/*.py`) rather than one opaque agent loop. Each
  stage's input/output is logged to the audit trail, so a demo (or a real
  client) can see exactly why the agent proposed what it proposed.

- **Nothing touches Plane or EspoCRM without a human approval row.**
  `POST /approvals/{id}/approve` writes the `ApprovalDecision` row first,
  then calls `execute_action` — a rejection or an unreviewed proposal
  never reaches `execute.py` at all. A failed execution is caught and
  recorded as a failed `ExecutionResult` rather than raising, so the
  audit trail shows the failure instead of a crashed request.

- **Some intents deliberately produce no action.** `propose_action`
  returns `action_type="escalate"` for any intent with no route in
  `ingestion.inbox_poller.INTENT_ROUTES` (e.g.
  `project_status_question`, which would need Plane issue-matching that
  isn't built yet) rather than guessing. `execute_action` treats
  `escalate` as a no-op — approving it just records that a human will
  handle it outside this system.

- **The email simulator is a separate service, not a module**, so it can
  later be swapped for a real IMAP/webhook listener without touching the
  orchestrator's ingestion contract (just the URL it polls).

## Data flow through the audit DB

`EmailMessage` (raw input) → `ExtractionResult` (structured fields) →
`ProposedAction` (candidate action + confidence + matched record refs) →
`ApprovalDecision` (who / when / approve|edit|reject) → `ExecutionResult`
(API call outcome). All rows are append-only and keyed back to the
originating `EmailMessage.id`, so any action can be traced back to the
email that caused it.
