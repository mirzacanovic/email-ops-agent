# Case study: an email-to-action agent with a human in the loop

> **Draft.** Everything below is something the repo's code, tests, rehearsal
> or notes in [roadmap.md](roadmap.md) support. The one remaining `[TODO]`
> is the recording link. Delete this note once it is filled in.

## The problem

Small and mid-sized companies run on shared inboxes. A customer writes in;
someone reads it, works out what it is, finds out whether the sender is
already in the CRM or already has an open ticket, and then types the same
information into one or more systems. It is slow, it is inconsistent, and
the classic failure is the duplicate: a follow-up that gets filed as a new
issue because nobody remembered the first one.

The obvious fix, an AI that "handles email", is also the one a careful
client won't accept: it writes to production systems on its own, it can't
explain itself, and it sends customer email content to a third party.

## What I built

An agent that reads an inbound email and **proposes** an action, which a
person approves before anything is written anywhere:

```
email → classify → extract → match existing records → propose
      → human approves / rejects → execute via API → audit log
```

- A sales inquiry becomes a **Lead in EspoCRM**; a support request becomes a
  **work item in Plane**.
- If the sender is already known, or the email is a follow-up to an
  existing issue, the proposal is an **update**, not a duplicate.
- Anything the model classifies as not a customer message is **escalated to
  a person** instead of acted on. (Whether the model classifies correctly is
  a separate question; see Results.)
- Every step (the raw email, the model's output, the proposed action, who
  decided, what the target system answered) is stored as an append-only
  audit trail.

## Design decisions that mattered

**A human approval step, enforced in code rather than by convention.**
The approve endpoint writes the decision row first and only then calls the
target system. A rejected or unreviewed proposal never reaches the
execution code at all. A failed API call is recorded as a failed result, so
the trail shows the failure instead of a crashed request.

**Open-weight model, on the client's own infrastructure, by default.**
Classification and extraction run on a self-hosted Mistral model, so
customer email content never leaves the stack. That matters for clients
with data-residency requirements. It is a product decision, not legal
advice, and the write-up says to confirm the data flow with the client's
counsel. The backend sits behind a one-method interface, so a client
without that constraint can switch to Claude by changing one environment
variable ([llm-backend.md](llm-backend.md)).

**Two small interfaces instead of one big agent loop.** The model backend
and the target systems each hide behind a narrow interface. Adding Zammad or
ERPNext, or pointing at a client's own Salesforce, means writing an
adapter, not changing the pipeline. Each pipeline stage is a separate
function whose input and output are logged, so "why did it propose that?"
always has an answer.

**Matching tuned to what each system can actually do.** EspoCRM is matched
on exact sender email first, then fuzzy company name. Plane has no
full-text search, so every issue the agent creates is tagged with the
sender's address, which lets a follow-up be matched against that sender's
own earlier issues only. A bug report from one customer can't be mistaken
for a similarly worded one from another.

**Updates append; they don't overwrite.** Matching a follow-up to an
existing Plane issue merges the new text into the description. A plain
overwrite would have silently destroyed the original bug report.

**Knowing when not to act.** The classifier has an explicit `other` intent,
which escalates instead of acting, and a confidence floor is wired in as a
second gate. Building the demo showed this was missing: the agent had no way
to say "this isn't a customer email", so the edge cases a client would ask
about couldn't actually occur. The mechanism now exists; the rehearsal
(below) showed that the 7B model doesn't use it reliably, which is why the
approval step stays the real safety net.

## What running it against real systems taught me

The most useful findings came from running against a real EspoCRM instance
and a real Plane workspace rather than mocks.

- **A single "last seen" cursor loses failed emails.** Progress was tracked
  as the newest successfully processed message, so one transient failure
  made that email permanently invisible once a later one succeeded. Now
  each message is tracked individually and failures retry on the next poll,
  with a regression test that fails against the old behaviour.
- **Overlapping runs duplicated work.** A slow poll was still running when a
  second started, and both processed the same emails. Fixed with a lock plus
  a database uniqueness constraint as a backstop.
- **A small local model is uneven on open-ended text.** It extracts anchored
  fields (the sender's address) reliably but mixes up free-text fields like
  descriptions. The honest answer is that the approval step is the safety
  net for those fields, and a larger local model is the next thing to try
  rather than more prompt tuning.

## Production-minded details

- Reviewer accounts with hashed passwords; the signed-in username is
  recorded on every decision.
- Schema changes go through Alembic migrations, with a test that fails when
  a model change has no migration. Existing databases are adopted
  automatically.
- A metrics page (approval rate, time to decision, action and confidence
  breakdowns) computed from the audit trail rather than separate counters.
- CI on every push: lint, type-check, tests, and image builds.

## What it deliberately doesn't do yet

Said plainly, because a client will ask:

- It reads from an email **simulator**, not a real inbox. A real inbox is the
  first step of a pilot, against a sandboxed domain.
- A reviewer can edit the proposed text before approving, but edits are plain
  text boxes (descriptions are raw HTML), and every reviewer can approve
  everything: no roles, no second approver.
- Authentication is HTTP Basic, which needs TLS in front of it outside
  localhost. There is no login throttling. Cross-site request forgery and
  framing are blocked by checking the browser's own origin headers, but that is
  a layer on top of a simple login, not a replacement for a proper identity
  provider.
- Extraction quality on free text is the main open risk (see above).
- Auto-execution without approval is out of scope until there is enough
  real-world accuracy data to set a threshold responsibly.

## Results

One scripted end-to-end rehearsal on 2026-10-05: six emails in three acts,
Mistral 7B on CPU, a real EspoCRM instance and a real Plane Cloud project,
a human (me) approving or rejecting each proposal. Small sample, one run:
read it as "what happened", not as a benchmark.

| | |
|---|---|
| Emails processed | 6 |
| Proposals approved / rejected | 5 / 1 |
| Approved actions that executed successfully | 5 of 5 |
| Follow-ups matched to the existing record instead of duplicated | **2 of 2** (Plane issue by sender-scoped title match; CRM Lead by exact email) |
| Records in each system after the run | 1 Plane work item, 1 Lead: no duplicates |
| Junk emails that reached the CRM | 0, because the one wrongly proposed was rejected at review |
| Emails correctly classified as not-a-customer-message | **1 of 2** |

What it showed, including the parts that don't flatter the model:

- **The workflow held up.** Creates, updates and the append-not-overwrite
  behaviour all worked against live systems, and the approval step did its
  job.
- **The model misclassified the recruiter spam** as a sales inquiry at 95%
  confidence and proposed creating a Lead for it. The human rejected it and
  nothing was written. The vague email was routed to a person as intended.
- **Self-reported confidence was uninformative.** All six emails came back at
  exactly 0.95, so the confidence floor never fired. It needs a better signal
  before it can be relied on.
- **Free-text extraction was weak**: the Plane issue was titled with the
  sender's name rather than the subject, and the Lead's description was the
  word `sales_inquiry`. A reviewer would fix these before approving. This is
  the case for a larger model, and the reason the review UI lets a person edit
  the proposal before approving it.
- **It is slow on CPU**: roughly 3 to 4 minutes per email, and the first
  model load took about 3 minutes with free memory (about 19 when the machine
  was nearly out of RAM). Fine for an approval-queue pilot, not for anything
  interactive.

**Second run, after a prompt change (2026-10-15).** I rewrote the
classification and extraction prompts to address those failures, fixed the
matching they exposed (a follow-up would otherwise have been filed as a
duplicate, so it now also matches on the email subject), and ran the same
six emails end to end again. Figures below are read from the audit trail.

| | First run (10-05) | Second run (10-15) |
|---|---|---|
| Emails processed | 6 | 6 |
| Proposals approved / rejected | 5 / 1 | 6 / 0 |
| Approved actions that executed | 5 of 5 | 6 of 6 |
| Follow-ups updated instead of duplicated | 2 of 2 | 2 of 2 (the Plane match now at title similarity 1.00) |
| Emails correctly treated as not-a-customer-message | 1 of 2 | 2 of 2 (spam and the vague email both escalated) |
| Junk reaching the CRM | 0 (rejected at review) | 0 (never proposed) |
| Issue title | the sender's name | the email's subject |
| Lead description | the word `sales_inquiry` | a summary of the request |

Read this carefully: it is one run, on the same six emails the fixes were
written against, so it shows the specific failures are fixed, not an accuracy
rate. As a separate check, five fresh emails the prompt had not been tuned on
(an SEO pitch, a newsletter, a login problem, an on-prem licensing question,
a vague "Hi") were all classified as expected, but that is five emails. Model
confidence is still a weak signal: clear emails come back at 0.9 to 0.95, so
the confidence floor never fired; the vague email escalated because it was
classified `other`, not because of the floor.

Recorded walkthrough: `[TODO: link]`

## Stack

Python, FastAPI, SQLAlchemy, Alembic, PostgreSQL, Jinja2; Ollama with
Mistral 7B (swappable for Claude); EspoCRM and Plane as target systems;
Docker Compose; GitHub Actions.

## If this were a client engagement

A pilot would swap the simulator for a sandboxed real inbox, add one or two
of the client's own systems as adapters, and run in approval-only mode for a
few weeks. That produces the accuracy data needed to decide, per action
type, whether anything can safely skip review.
