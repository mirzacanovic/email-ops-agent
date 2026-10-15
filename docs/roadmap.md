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
- Editable fields in the review UI ("Edit before approving"): a reviewer can
  correct the proposed text before it is sent; the decision is stored as
  `edited` with only the changed fields, the original proposal is untouched,
  and `/metrics` shows how often approvals needed an edit. Also fixed on the
  way: a proposal could be approved or rejected twice (a double click would
  execute twice and create a duplicate). Verified with unit tests, deliberate
  breakage of the two key protections, and a live check of the validation path
  and page rendering; **not** yet run live through an approved edit (that
  would write a real record to Plane or EspoCRM).
- Known limits: `description_html` is edited as raw HTML (the reviewer sees
  `<br>` tags); a field can't be blanked out, only changed.
- CSRF and clickjacking protection (`app/security.py`). Basic auth means the
  browser sends credentials with any request to the host, including one fired
  from another site, so a middleware refuses state-changing requests whose
  `Sec-Fetch-Site` is not `same-origin` (or whose `Origin` is not this host)
  and sets `frame-ancestors 'none'`. It is stateless (no session or token to
  add), leaves curl and scripts alone, and also refuses other ports on the
  same host, which count as "same-site" on localhost. A test walks every route
  the app registers, so a new state-changing route is checked automatically.
  Verified with unit tests, three deliberate breakages, and requests against
  the running container; not yet exercised by a real browser clicking the
  app's own forms (they should send `Sec-Fetch-Site: same-origin`). Limits: it
  relies on the browser sending those headers (every current browser does), and
  it does not stop an attacker who can already run script on the app's own
  origin (that would be an XSS problem; values are escaped in the templates).

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

**Fixed (robustness pass):**

- *Cold start*: the first load of the 7B model took ~19 minutes, and the
  app's 5-minute timeout aborted it every time, so a cold stack never recovered.
  `docker-compose.yml` now sets `OLLAMA_KEEP_ALIVE` (24 h by default) and has a
  one-shot `ollama-warm` service that loads the model during `docker compose
  up`. `GET /ready` reports 503 until the database is up and the model is
  actually loaded, so there is something to wait on.
- *EspoCRM's 30 s timeout* was too tight while Ollama saturated the CPU. The
  connector timeouts (EspoCRM 60 s, Plane 30 s, Ollama 300 s) are now settings
  (`ESPOCRM_TIMEOUT_SECONDS` etc.).
- *`/ingest/poll` blocked for the whole batch* (~4 min per email). "Check
  inbox now" now starts a background job (`POST /ingest/start`) and the page
  shows "N of M emails done", refreshing itself; `GET /ingest/status` has the
  same numbers. The synchronous `/ingest/poll` is kept. Job state is
  in-memory and single-process, like the poll lock.

Not yet confirmed on a cold start: the warm-up service itself (a cold load takes
~20 minutes, and recreating the Ollama container would trigger one), so that
part is verified by config validation and reading, not by a run.

**Still open:**

- **Confidence is still a weak signal** (see above); the floor needs a better
  signal or a higher value before it can be demoed.
- **Prompt fit to the fixtures**: the classify examples were written after
  seeing the failures, so the six fixtures overstate accuracy. Grow the
  held-out set before trusting any accuracy number.

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
