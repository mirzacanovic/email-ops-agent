#!/usr/bin/env python3
"""Checks the classify/extract prompts (and the matching that depends on them)
against the demo fixtures and a held-out set. Read-only.

    python .claude/skills/prompt-change-check/scripts/run_check.py [options]

  --rebuild        rebuild the app image first (REQUIRED after editing a prompt:
                   the container bakes in src/ at build time)
  --only ID [ID..] check only these email ids (e.g. to retry ones that timed out)
  --results FILE   skip the model run and grade an existing results file (JSONL
                   from a previous run); useful to re-read results or to test
                   the checker itself
  --out FILE       where to save this run's raw results (default: temp dir)

The model run is slow (about 4 minutes per email on CPU, so ~45 minutes for
all eleven), so run it in the background. Exit code 1 if any check fails.
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]  # <root>/.claude/skills/prompt-change-check/scripts/
SKILL = Path(__file__).resolve().parents[1]
INTENT_LABELS = ("sales_inquiry", "support_request", "project_status_question")

sys.path.insert(0, str(ROOT / "app" / "src"))
from app.pipeline.match import normalize_subject  # noqa: E402  (pure function, no deps)


def similarity(a: str, b: str) -> float:
    # Same measure as app.pipeline.match._name_similarity
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def match_threshold() -> float:
    source = (ROOT / "app/src/app/pipeline/propose.py").read_text(encoding="utf-8")
    found = re.search(r"SIMILAR_ISSUE_THRESHOLD\s*=\s*([0-9.]+)", source)
    return float(found.group(1)) if found else 0.55


def load_emails() -> tuple[list[dict], dict[str, str], dict[str, str], list[dict]]:
    """Returns (emails, expected intent by id, group by id, thread pairs)."""
    fixtures_meta = json.loads((SKILL / "assets/fixture_expectations.json").read_text(encoding="utf-8"))
    heldout = json.loads((SKILL / "assets/heldout.json").read_text(encoding="utf-8"))["emails"]
    dirs = [ROOT / "email-simulator/src/email_simulator/fixtures"]
    dirs += sorted((ROOT / "email-simulator/demo-scenarios").glob("act*"))
    emails, expected, group = [], dict(fixtures_meta["intents"]), {}
    for d in dirs:
        for path in sorted(d.glob("*.json")):
            email = json.loads(path.read_text(encoding="utf-8"))
            emails.append(email)
            group[email["id"]] = "fixture"
    for email in heldout:
        emails.append({k: v for k, v in email.items() if k not in ("expected_intent", "burned")})
        expected[email["id"]] = email["expected_intent"]
        group[email["id"]] = "burned" if email.get("burned") else "held-out"
    return emails, expected, group, fixtures_meta.get("threads", [])


def run_model(emails: list[dict], out_path: Path, rebuild: bool) -> None:
    def docker(*args: str, **kw):
        return subprocess.run(["docker", "compose", *args], cwd=ROOT, **kw)

    if rebuild:
        print("Rebuilding the app image so it has the current prompts...", file=sys.stderr)
        docker("up", "-d", "--build", "app", check=True)
        for _ in range(30):
            try:
                urllib.request.urlopen("http://localhost:8000/health", timeout=3)
                break
            except Exception:
                time.sleep(2)
    with tempfile.TemporaryDirectory() as tmp:
        messages = Path(tmp) / "pcc_messages.json"
        messages.write_text(json.dumps(emails), encoding="utf-8")
        docker("cp", str(messages), "app:/tmp/pcc_messages.json", check=True, capture_output=True)
    docker("cp", str(SKILL / "scripts/probe.py"), "app:/tmp/pcc_probe.py", check=True, capture_output=True)

    proc = subprocess.Popen(
        ["docker", "compose", "exec", "-T", "app", "python", "/tmp/pcc_probe.py", "/tmp/pcc_messages.json"],
        cwd=ROOT, stdout=subprocess.PIPE, text=True, encoding="utf-8",
    )
    assert proc.stdout is not None
    with out_path.open("w", encoding="utf-8") as sink:
        for line in proc.stdout:
            if line.startswith("{"):
                sink.write(line)
                sink.flush()
                row = json.loads(line)
                print(f"  ran {row['id']}: {row.get('intent') or row.get('error')}", file=sys.stderr)
    proc.wait()


def evaluate(rows: list[dict], expected: dict[str, str], group: dict[str, str], threads: list[dict]):
    """Returns (checks, scoreboard). A check is (email id, name, status, detail)."""
    checks: list[tuple[str, str, str, str]] = []
    by_id = {r["id"]: r for r in rows}
    board: dict[str, list[int]] = {}  # group -> [passed, total] for the classification check

    for row in rows:
        eid, g = row["id"], group.get(row["id"], "fixture")
        if "error" in row:
            checks.append((eid, "model call", "FAIL", row["error"]))
            board.setdefault(g, [0, 0])[1] += 1
            continue
        want = expected.get(eid)
        ok = row["intent"] == want
        board.setdefault(g, [0, 0])[0] += ok
        board[g][1] += 1
        checks.append((eid, "intent", "PASS" if ok else "FAIL",
                       f"got {row['intent']} ({row['confidence']}), expected {want}"))

        extracted = row.get("extracted") or {}
        leaked = [k for k, v in extracted.items()
                  if isinstance(v, str) and any(re.search(rf"\b{label}\b", v) for label in INTENT_LABELS)]
        if extracted:
            checks.append((eid, "no intent label in fields", "FAIL" if leaked else "PASS",
                           f"field(s) {leaked} contain an intent label" if leaked else ""))
        # A first-contact issue's title should echo its subject. A follow-up
        # ("Re: ...") is exempt: its title only matters if the match to the
        # original survives, which the thread check below covers.
        is_followup = normalize_subject(row["subject"]) != row["subject"].strip()
        if "name" in extracted and not is_followup:
            s = similarity(extracted["name"], normalize_subject(row["subject"]))
            checks.append((eid, "title tracks subject", "PASS" if s >= 0.5 else "FAIL",
                           f"{extracted['name']!r} vs subject: {s:.2f} (want >= 0.50)"))

    threshold = match_threshold()
    for pair in threads:
        orig, follow = by_id.get(pair["original"]), by_id.get(pair["followup"])
        label = f"{pair['followup']} matches {pair['original']}'s issue"
        if not (orig and follow and (orig.get("extracted") or {}).get("name")
                and (follow.get("extracted") or {}).get("name")):
            checks.append((pair["followup"], label, "SKIP", "needs both emails extracted"))
            continue
        original_title = orig["extracted"]["name"]
        by_title = similarity(follow["extracted"]["name"], original_title)
        by_subject = similarity(normalize_subject(follow["subject"]), original_title)
        best = max(by_title, by_subject)
        status = "FAIL" if best < threshold else ("WARN" if by_title < threshold else "PASS")
        note = "" if status == "PASS" else (
            " - only the subject fallback rescues it" if status == "WARN" else " - would file a duplicate")
        checks.append((pair["followup"], label, status,
                       f"model title {by_title:.2f}, subject {by_subject:.2f}, threshold {threshold}{note}"))
    return checks, board


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--only", nargs="+", metavar="ID")
    parser.add_argument("--results", metavar="FILE")
    parser.add_argument("--out", metavar="FILE")
    args = parser.parse_args()

    emails, expected, group, threads = load_emails()
    if args.only:
        emails = [e for e in emails if e["id"] in args.only]
    if args.results:
        results_path = Path(args.results)
    else:
        results_path = Path(args.out) if args.out else Path(tempfile.gettempdir()) / "pcc_results.jsonl"
        print(f"Running {len(emails)} emails through the model (slow); raw results -> {results_path}",
              file=sys.stderr)
        run_model(emails, results_path, args.rebuild)

    rows = [json.loads(line) for line in results_path.read_text(encoding="utf-8").splitlines() if line.startswith("{")]
    if args.only:
        rows = [r for r in rows if r["id"] in args.only]
    checks, board = evaluate(sorted(rows, key=lambda r: r["id"]), expected, group, threads)

    for eid, name, status, detail in checks:
        print(f"[{status:<4}] {eid:<8} {name}" + (f"  - {detail}" if detail else ""))
    print("\nClassification by group:")
    notes = {"fixture": "the known failures; passing shows they are fixed, not that it generalises",
             "held-out": "the number that means something",
             "burned": "tuned against or resembling a prompt example; regression only"}
    for g in ("held-out", "fixture", "burned"):
        if g in board:
            print(f"  {g:<9} {board[g][0]} of {board[g][1]}   ({notes[g]})")
    if "held-out" not in board:
        print("  (no held-out emails in this run: nothing here measures generalisation)")
    failed = sum(1 for c in checks if c[2] == "FAIL")
    print(f"\n{failed} failing check(s)." if failed else "\nAll checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
