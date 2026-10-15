# Demo script

A fixed, repeatable walkthrough (~10 minutes) instead of "whatever the
fixtures happen to do". Three acts: the golden path, the system recognising
what it has already seen, and the cases where it deliberately *doesn't* act.

> **Status: rehearsed end to end twice** (Mistral 7B on CPU, real EspoCRM and
> Plane). On 2026-10-05 Acts 1 and 2 matched the script and **Act 3 did not**
> (the model misclassified the spam). After the prompt and matching changes, a
> second full run on 2026-10-15 matched the script in all three acts (see the
> Act 3 note). Both are single runs on the same fixtures.

## Before you start

**Wait for the model to be loaded.** On the rehearsal machine the first load
of the 7B model took ~19 minutes. `docker compose up` now starts it loading
(the `ollama-warm` service) and keeps it resident for 24 hours, but you still
have to wait: `curl localhost:8000/ready` returns 503 until the model is
loaded and 200 when it is. Do this well before the audience arrives. (If the
warm-up service is not running, one long request does the same:
`curl -m 3000 localhost:11434/api/generate -d '{"model":"mistral:7b-instruct","prompt":"hi","stream":false,"keep_alive":"4h"}'`.)

Then expect **~3-4 minutes per email** (about 1 minute to classify, 1-3 to
extract). **Check inbox now** returns immediately and the page shows
"N of M emails done", refreshing itself every 10 seconds, so you can talk over
the wait or narrate the audit trail in Adminer. Don't run it in a hurry.

1. Start from a clean slate: empty audit tables, empty CRM and Plane project,
   only the act 1 emails live (`scripts/release_demo_emails.sh reset`). Do not
   use `scripts/reset_demo.sh` for this: it deletes the EspoCRM volume and its
   API key. The `demo-runbook` skill (`.claude/skills/`) has the checks and
   the exact commands.
2. Create your reviewer account:
   `docker compose exec app python -m app.cli create-user demo`
3. Open http://localhost:8000/approvals and sign in. Keep EspoCRM
   (:8080) and Plane open in other tabs so every approval can be shown
   landing in the real system.

## Act 1 — the golden path (2 emails)

Click **Check inbox now**. Two proposals appear.

| Email | What the agent does | Point to make |
|---|---|---|
| Jordan Lee, *"Export button throws an error"* | Classifies as a support request → proposes **create** in Plane | Extracted title/description, rationale, confidence are all visible before anything happens |
| Priya Raman, *"Pricing for 50-seat rollout"* | Classifies as a sales inquiry → proposes **create** Lead in EspoCRM | Same loop, different system, same approval step |

**Observed:** both proposals came out as expected (Plane create at 85%,
EspoCRM create at 90%), approved, and appeared as real records. Be ready for
two blemishes, which are worth owning rather than hiding: the Plane issue's
title was the sender's *name* ("Jordan Lee") rather than the subject, and the
Lead's description was the literal text `sales_inquiry`. (Both were fixed at the model level on 2026-10-09; re-check
end to end.) This is the
open-ended-extraction weakness (see the roadmap), and it is exactly what the
approval step exists to catch — a reviewer would fix these before approving.

**Approve both**, then show the new Plane work item and the EspoCRM Lead.
Nothing was written until the click; the audit trail (Adminer, :8082)
shows email → extraction → proposal → decision → execution.

## Act 2 — it remembers (2 emails)

`scripts/release_demo_emails.sh act2`, then **Check inbox now**.

| Email | Expected proposal | Point to make |
|---|---|---|
| Jordan again, *"Re: Export button…"* ("any update?") | **Update** the existing Plane issue, appending the follow-up | Matched back to the original instead of filing a duplicate |
| Priya again, *"Re: Pricing…"* (wants a 10-seat pilot) | **Update** the existing Lead via exact email match, high confidence | Same person, same record |

**Observed:** both were proposed as **updates, not duplicates** — Jordan's
follow-up matched the original Plane issue (75%) and Priya's matched her
Lead by exact email (100%); after approving, still exactly one work item and
one Lead. Caveats: the Plane match worked partly because both extractions
produced the same title ("Jordan Lee"), and the appended follow-up text was
just "Jordan Lee" rather than the actual question, so the *matching* is
solid but the *content* it carries is weak.

The updates only work because Act 1 was *approved first* — the matching
queries the live systems. This is also why the emails are released in acts.

## Act 3 — knowing when not to act (2 emails)

`scripts/release_demo_emails.sh act3`, then **Check inbox now**.

> **Update 2026-10-15: confirmed end to end.** After the prompt change, a full
> run (read from the audit trail) classified the spam as `other` and the vague
> email as `other` at 0.6; both escalated as originally intended, and all six
> approved actions executed. It is one run on the fixtures the prompt was
> tuned against, so keep the reject-the-spam beat below as the fallback in
> case the model does something different on the day.

**What the script originally expected:** both emails escalate. **What
happened in the first rehearsal (before the prompt change), with Mistral 7B:**

| Email | Observed proposal | What to say |
|---|---|---|
| TalentBridge recruiting spam | **Create a Lead** in EspoCRM — classified `sales_inquiry` at 95% | The model got this wrong. **Reject it** on camera: this is the human catching what the model can't, and nothing reached the CRM |
| "Quick question… resend the thing?" | **Escalate** — classified `other` at 95% | The system declining to guess; approving an escalation is a recorded no-op |

So the beat is not "the system is smart enough to ignore spam" — it isn't,
with this model — but **"a wrong proposal cost nothing because a person
had to approve it, and the vague one was routed to a human"**. That is a
more honest and, for a client, a more reassuring story.

Still **not true**, even after the prompt change:

- *Low-confidence escalation does not fire in practice.* Clear emails come
  back at 0.9-0.95 and the vague one at 0.6, all above the 50% floor
  (`CLASSIFY_CONFIDENCE_FLOOR`). The vague email escalates because it is
  classified `other`, not because of the floor. Don't demo the floor.
- *Spam classification is not proven robust.* Five unseen emails all landed
  correctly, but that is a small sample; don't promise it.

## Close: the numbers

Open http://localhost:8000/metrics: emails processed, approval rate,
median time to decision, how proposals split between create / update /
escalate, and the confidence distribution. After the rehearsal it read: 6 emails
processed, 83% approval (5 approved, 1 rejected — the spam), 5 of 5
executions succeeded. The "median time to decision" tile is only meaningful
with a real reviewer; scripted approvals make it near-instant, so don't
quote it from a rehearsal.

## Resetting

`scripts/release_demo_emails.sh reset` re-hides the act 2 and 3 emails; it does
not clear the database or the target systems (the `demo-runbook` skill covers
those). `scripts/reset_demo.sh` wipes every container volume, including the
EspoCRM API key, so only use it when you mean to rebuild everything from
scratch.
