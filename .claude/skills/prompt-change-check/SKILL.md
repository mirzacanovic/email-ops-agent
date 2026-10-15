---
name: prompt-change-check
description: Verifies a change to how email-ops-agent's model classifies or extracts emails, and that follow-up matching still works afterwards. Use this whenever the user edits or asks you to edit SYSTEM_PROMPT in app/src/app/pipeline/classify.py or extract.py, the intent list or CLASSIFY_CONFIDENCE_FLOOR, the field descriptions in the Plane/EspoCRM connectors' schemas, switches OLLAMA_MODEL or LLM_PROVIDER, or asks "did the prompt change help", "is the classifier still right", "test the spam case", or "why did the follow-up create a duplicate". Run it before claiming any prompt or model change works, and before putting accuracy claims in the README, roadmap or case study.
---

# Prompt-change check (email-ops-agent)

Changing a prompt here has two failure modes that are easy to miss and have
both happened:

1. **Tuning on the test.** Few-shot examples were written to match the demo
   fixtures that had failed (a recruiter pitch, "resend the thing"), so the
   fixtures then passed and looked like proof. They are proof the known
   failures are fixed, nothing more. Generalisation can only be measured on
   emails the prompt has not seen.
2. **Fixing one thing breaks the next stage.** Making the model's Plane
   titles faithful ("Export button throws an error...") made the follow-up's
   title ("CSV export issue") score 0.28 against the original, below the 0.55
   match threshold, so the follow-up would have been filed as a duplicate. The
   old match only worked because both titles were the sender's name. A change
   that improves extraction can silently break matching.

The bundled script runs the real `classify` and `extract` (read-only) over the
six demo fixtures and a held-out set, grades the results, and checks that the
follow-up thread still matches. It writes nothing to the database, Plane or
EspoCRM.

## Procedure

1. **Write expected answers before looking at the model's.** For any email
   you add to test the change, put it in `assets/heldout.json` with
   `expected_intent` set first. Labels written after seeing the output
   quietly become whatever the model said.
2. **Get the stack ready.** The model must be warm and the container must
   have the new code. If unsure, use the `demo-runbook` skill (warm-up, health).
   Then run with `--rebuild`: the container copies `src/` at image build time,
   so without it you would be testing the old prompt and see no change.
3. **Run it, in the background.** About 4 minutes per email on CPU, so all
   eleven take ~45 minutes. A shorter loop while iterating is fine
   (`--only h-1 msg-005`), but run everything before concluding anything.

   ```bash
   python .claude/skills/prompt-change-check/scripts/run_check.py --rebuild
   ```

   `--results FILE` re-grades a saved run without calling the model. A
   `ReadTimeout` on an email means the call took over the app's 5-minute
   limit, usually the model queued behind a warm-up or the host is out of
   memory; fix that and retry just those ids with `--only`, rather than
   reading it as a prompt problem.
4. **Read the results by group, not as one number.**
   - *held-out* is the only number that says anything about unseen mail.
   - *fixture* shows the known failures stay fixed.
   - *burned* are regression cases that no longer measure generalisation.
   Also read the WARN lines. "Only the subject fallback rescues it" means the
   model title and the original have drifted apart and the match depends on
   `normalize_subject` in `pipeline/match.py`; that is fine, but it is the
   thing to look at if matching ever regresses.
5. **Keep the held-out set honest.** If you add a few-shot example that
   resembles a held-out email, set that email's `"burned": true` and write a
   fresh unseen one to replace it. Do not tune a prompt until a held-out
   email passes; if one fails, that is information, not a bug in the test.
6. **Report what the run supports and no more.** Say "5 of 5 held-out
   emails" rather than "100% accurate"; five emails cannot support a rate. Note
   that this checks the model stage, not the full pipeline: an end-to-end
   run through approvals (see `demo-runbook`) is still what confirms a change
   works in the demo. Update `docs/roadmap.md` and `docs/case-study.md` with
   the same caveats.

## Writing the prompt changes themselves

What has worked, and why, so you can apply it to cases not seen yet:

- **Define categories from the company's point of view.** The recruiter pitch
  was a "sales inquiry" because "sales" read as "someone is selling". The
  definition has to say who is buying from whom.
- **Name the escape hatch and what belongs in it.** `other` only gets used
  if the prompt says what goes there (pitches aimed at us, newsletters,
  too-vague messages).
- **Show the output you want, not just the rule.** A worked example of an
  issue-style extraction fixed titles better than "do not use a person's name".
- **Do not pass labels the model might copy.** The intent was passed as a bare
  `Intent: sales_inquiry` line and ended up as the Lead's description.
- **Self-reported confidence is weak.** The model said 0.95 for everything
  until it was told when to go lower, and even then the 0.5 floor never fired.
  Do not build demo claims on `CLASSIFY_CONFIDENCE_FLOOR` without evidence.
