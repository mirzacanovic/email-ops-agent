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

- **One connector interface, one adapter per system**
  (`app/src/app/connectors/base.py`). `search_records` / `create_record` /
  `update_record` / `get_schema` are the only methods the pipeline calls.
  Adding Zammad or ERPNext later — or swapping EspoCRM for a client's real
  Salesforce — means writing a new adapter, not touching the pipeline.

- **Every pipeline stage is a separate, inspectable function**
  (`app/src/app/pipeline/*.py`) rather than one opaque agent loop. Each
  stage's input/output is logged to the audit trail, so a demo (or a real
  client) can see exactly why the agent proposed what it proposed.

- **Nothing touches Plane or EspoCRM without a human approval row.**
  The `execute` stage only runs against a `ProposedAction` that has an
  `approved` status in the audit DB (see `app/src/app/audit/models.py`).

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
