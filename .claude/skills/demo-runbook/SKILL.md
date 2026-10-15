---
name: demo-runbook
description: Gets the email-ops-agent stack into a clean, demo-ready state and checks it before anyone watches. Use this whenever the user says "prep the demo", "get ready to show this", "reset for the demo", "rehearse", "dry run", "record the walkthrough", "start from a clean slate", or asks why the demo starts with updates instead of creates, why the first poll hangs or times out, or whether the stack is ready. Also use it to clean up after a demo or rehearsal. Do NOT run scripts/reset_demo.sh yourself; this skill explains why and what to do instead.
---

# Demo runbook (email-ops-agent)

A demo of this project only behaves as scripted ([docs/demo-script.md](../../../docs/demo-script.md))
if the stack starts in a very particular state. Most of the ways it goes wrong
are quiet: nothing errors, the demo just shows the wrong thing (updates where
creates were expected, a 20-minute hang on the first email). So start with the
check, not with the fixes.

## 1. Run the preflight

```bash
python .claude/skills/demo-runbook/scripts/preflight.py
```

It is read-only. Add `--deep` to also time one tiny model request. It prints
`[ OK ]`, `[WARN]` or `[FAIL]` for each condition and a `fix:` line for
anything not OK. Work through the fixes in the order below, then run it again
until it says "Ready for a clean demo."

## 2. Fix what it reports

**Never run `scripts/reset_demo.sh` to get a clean slate.** It does
`docker compose down -v`, which deletes the EspoCRM volume, and the EspoCRM
API key lives in that volume, so afterwards the app can no longer talk to the
CRM until a new key is made and `scripts/seed_espocrm.py` is re-run. The
cleaning below is narrower and keeps the key.

In this order, because later steps depend on earlier ones:

1. **Stack down or unreachable.** Start Docker Desktop, then
   `docker compose up -d --build` from the project root. If you edited `.env`
   (for example `PLANE_*` or `LLM_PROVIDER`), recreate the app with
   `docker compose up -d app`. Do not `source .env` in the same shell first:
   Compose lets exported shell variables override the file, so the container
   silently keeps the old value.
2. **Model cold.** `docker compose up` now starts a warm-up (the
   `ollama-warm` service) and `GET /ready` on the app answers 503 until the
   model is loaded and 200 when it is. If the stack was already running without
   that service, run the warm-up command the preflight prints instead and wait
   for it to return. A cold load took 20-30 minutes on this machine, and Ollama
   only reports the model as loaded once it is fully ready, so the wait is
   the point. The app's own requests time out after 5 minutes and abort the
   load each time, so polling before the model is loaded makes things worse,
   not better. Run it in the background and tell the user it is a long wait.
3. **Audit DB not empty.** Already-processed emails are skipped by design, so
   old rows stop the acts from replaying. This deletes audit rows, so confirm
   with the user first, and take the data-only `pg_dump` backup before the
   `TRUNCATE` (both commands are in the preflight output). Keep the backup
   outside the repo.
4. **Wrong emails live.** `bash scripts/release_demo_emails.sh reset`. Act 2
   and 3 emails are released on cue during the demo; the follow-ups only match
   because the Act 1 records were approved first.
5. **No reviewer account.** The user creates it themselves
   (`docker compose exec app python -m app.cli create-user demo`); it prompts
   for the password. Do not pick or set a password for them.
6. **Leftover records in EspoCRM or Plane.** These are the user's real
   systems. List what the preflight found and ask before deleting anything;
   in past rehearsals the user cleared them by hand. Plane's own onboarding
   sample items are not the agent's and can stay.

## 3. Before showing someone

- Do one full dry run first, then clean up again (steps 3-6). Nothing in the
  prompt or matching changes has been verified end to end, and the dry run is
  where that gets found out, not in front of an audience.
- Expect about 3-4 minutes per email on CPU, so a full run is 25+ minutes
  of mostly waiting. "Check inbox now" starts a background job and returns at once; the page shows
  "N of M emails done" and refreshes itself, and `GET /ingest/status` has the same
  numbers. The older synchronous `POST /ingest/poll` still blocks for the whole
  batch, and a client-side timeout does not stop it, so use `/ingest/start`
  for anything scripted.
- Free RAM matters. With the host nearly out of memory the docker CLI hangs
  and model calls time out. The preflight warns about it; closing other apps
  is the fix.
- If the stack is flaky on the day, a screen recording of the dry run is the
  fallback (the roadmap still lists the recording as to-do).

## 4. After the demo

Repeat steps 3-6, so the next person starts clean.

## Shell gotchas on this machine

- In Git Bash, `docker exec`/`compose exec` arguments that look like Unix
  paths (`/tmp/x.py`) get rewritten into Windows paths. Prefix the command with
  `MSYS_NO_PATHCONV=1`.
- `docker compose` must run from the project root (the folder with
  `docker-compose.yml`), or it reports "no configuration file provided".
- If the docker CLI hangs but the HTTP health checks pass, the containers are
  fine; the host is short of memory.
