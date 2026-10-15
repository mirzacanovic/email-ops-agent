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

## Phase 2: demo polish

Done, and rehearsed once end to end on the live stack (2026-10-05; see
[demo-script.md](demo-script.md) for what actually happened):

- Scripted three-act walkthrough with release script
  ([docs/demo-script.md](demo-script.md)). Writing it exposed that the
  classifier had no way to say "not a customer email" and that confidence
  never gated anything, so the edge cases couldn't actually occur; both are
  now real (`other` intent, `CLASSIFY_CONFIDENCE_FLOOR`).
- Metrics page at `/metrics` (approval rate, time to decision, action and
  confidence breakdowns), computed from the audit trail.

Still to do:

- Recorded walkthrough (the one remaining `[TODO]` in
  [case-study.md](case-study.md), whose results are filled in from the rehearsal).

## Found in the rehearsal

**Fixed by the prompt change (2026-10-09), then confirmed end to end on
2026-10-15** — a full three-act run through approvals (6 emails, 6 executed;
spam and the vague email escalated; both follow-ups updated rather than
duplicated). Separately, classify + extract were run read-only on the six
fixtures and on five unseen emails (5 of 5 as expected). Both are single runs:

- *Spam classified `sales_inquiry`* -> now `other` (the fixture, plus held-out
  SEO-agency and newsletter emails; 5 of 5 held-out emails classified as
  expected). Caveat: `other`'s definition names agencies and newsletters, so
  those two held-out cases are not a wholly unseen category.
- *Plane title was the sender's name / Lead description was the literal
  intent* -> titles now come from the subject, descriptions summarise the
  request (including the follow-up's pilot request).
- *Confidence always 0.95* -> partly: vague emails now come back at 0.6
  (clear ones still 0.95, spam at 0.9), so the 0.5 floor still would not have
  fired on any of them. Revisit the floor value or the signal.
- Side effect found and fixed: better titles broke the follow-up match (the
  model's "CSV export issue" scores 0.28 against the original, threshold
  0.55; the old match only worked because both titles were "Jordan Lee").
  `find_similar_issues` now also scores the normalized email subject
  (`Re:`/`Fwd:`/`AW:` stripped), which matches at about 1.0.

**Still open:**

- **Confidence is still a weak signal** (see above); the floor needs a better
  signal or a higher value before it can be demoed.
- **Prompt fit to the fixtures**: the classify examples were written after
  seeing the failures, so the six fixtures overstate accuracy. Grow the
  held-out set before trusting any accuracy number.
- **Cold start**: first load of the 7B model took ~19 minutes, and the app's
  300 s Ollama timeout aborts the load, so a cold stack never recovers on
  its own. Consider `OLLAMA_KEEP_ALIVE` set high in `docker-compose.yml`, a
  warm-up step in `ollama-pull`, and a readiness check.
- **EspoCRM's 30 s timeout is too tight** while Ollama saturates the CPU
  (one search timed out mid-rehearsal; the per-message retry recovered it).
- **`/ingest/poll` blocks for the whole batch** (~4 min per email), so a
  client or browser timeout is likely. Fine for the demo with a long timeout;
  would want a background job with a status endpoint for anything else.

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
