#!/usr/bin/env python3
"""Read-only pre-demo checks for email-ops-agent.

Reports whether the stack is in a state where the three-act demo
(docs/demo-script.md) will behave as scripted, and prints the fix for
everything that is not. It never changes anything: no deletes, no
truncates, no container restarts. The fixes are for a human (or Claude, after
asking) to run.

    python .claude/skills/demo-runbook/scripts/preflight.py [--deep]

--deep also sends one tiny request to the model and times it (up to 2 min).
Exit code: 0 = clean, 1 = at least one FAIL.
"""

import argparse
import ctypes
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]  # <root>/.claude/skills/demo-runbook/scripts/
ACT1_MESSAGE_IDS = {"msg-001", "msg-002"}
AGENT_SOURCE = "email-ops-agent"  # external_source the Plane connector stamps on issues

results: list[tuple[str, str, str, str]] = []  # (level, title, detail, fix)


def record(level: str, title: str, detail: str = "", fix: str = "") -> None:
    results.append((level, title, detail, fix))


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def http_json(url: str, headers: dict[str, str] | None = None, timeout: float = 8.0):
    """Returns (status, parsed JSON or None). status 0 = unreachable."""
    # Plane Cloud sits behind a bot filter that answers 403 to urllib's default
    # "Python-urllib" User-Agent (curl works), so always send our own.
    request = urllib.request.Request(
        url, headers={"User-Agent": "email-ops-agent-preflight/1.0", **(headers or {})}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            try:
                return response.status, json.loads(body)
            except ValueError:
                return response.status, None
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception:
        return 0, None


def check_services(env: dict[str, str]) -> bool:
    ports = {
        "app": env.get("APP_PORT", "8000"),
        "email simulator": env.get("EMAIL_SIM_PORT", "8001"),
        "Ollama": env.get("OLLAMA_PORT", "11434"),
        "EspoCRM": env.get("ESPOCRM_PORT", "8080"),
    }
    paths = {"app": "/health", "email simulator": "/health", "Ollama": "/api/tags", "EspoCRM": "/"}
    down = [n for n, p in ports.items() if http_json(f"http://localhost:{p}{paths[n]}")[0] == 0]
    if down:
        record(
            "FAIL",
            "Services not reachable: " + ", ".join(down),
            fix="Start Docker Desktop, then from the project root: docker compose up -d --build"
            "  (NOT scripts/reset_demo.sh, which wipes the EspoCRM volume and its API key)",
        )
        return False
    record("OK", "App, simulator, EspoCRM and Ollama all respond")
    return True


def check_llm_provider(env: dict[str, str]) -> None:
    provider = env.get("LLM_PROVIDER", "ollama")
    if provider != "ollama":
        record(
            "WARN",
            f"LLM_PROVIDER={provider} in .env",
            "The demo story (email content stays on-prem) assumes ollama.",
            "Set LLM_PROVIDER=ollama in .env and run: docker compose up -d app",
        )
    else:
        record("OK", "LLM_PROVIDER=ollama")


def parse_ollama_time(value: str) -> datetime | None:
    # Ollama prints nanosecond fractions; fromisoformat accepts at most 6 digits.
    value = re.sub(r"(\.\d{6})\d+", r"\1", value.replace("Z", "+00:00"))
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def check_model(env: dict[str, str], deep: bool) -> None:
    port = env.get("OLLAMA_PORT", "11434")
    model = env.get("OLLAMA_MODEL", "mistral:7b-instruct")
    status, data = http_json(f"http://localhost:{port}/api/ps")
    loaded = (data or {}).get("models") or []
    warm_cmd = (
        'curl -m 3600 localhost:11434/api/generate -d '
        f"'{{\"model\":\"{model}\",\"prompt\":\"hi\",\"stream\":false,\"keep_alive\":\"4h\"}}'"
    )
    if not loaded:
        record(
            "FAIL",
            "Model is not loaded (cold)",
            "A cold 7B load took ~3 minutes with free RAM but ~20 when the host was short of memory, "
            "and the app's 300 s timeout aborts a slow one, so a poll on a cold model can fail.",
            f"Run once and wait for it to return (Git Bash): {warm_cmd}",
        )
        return
    expires = parse_ollama_time(loaded[0].get("expires_at", ""))
    if expires is not None:
        minutes_left = (expires - datetime.now(timezone.utc)).total_seconds() / 60
        if minutes_left < 45:
            record(
                "WARN",
                f"Model is loaded but unloads in ~{max(minutes_left, 0):.0f} min",
                "If it unloads mid-demo the next email pays the full cold-start cost.",
                f"Re-run the warm-up to extend keep_alive: {warm_cmd}",
            )
        else:
            record("OK", f"Model loaded, stays resident ~{minutes_left / 60:.1f} h")
    else:
        record("OK", "Model loaded")

    if deep:
        body = json.dumps(
            {"model": model, "prompt": "Reply with one word.", "stream": False,
             "options": {"num_predict": 4}}
        ).encode()
        request = urllib.request.Request(
            f"http://localhost:{port}/api/generate", data=body,
            headers={"Content-Type": "application/json"},
        )
        started = time.time()
        try:
            urllib.request.urlopen(request, timeout=120).read()
            seconds = time.time() - started
            level = "OK" if seconds < 30 else "WARN"
            record(level, f"Tiny model request took {seconds:.0f}s",
                   "" if level == "OK" else "Slow: memory pressure or CPU contention?",
                   "" if level == "OK" else "Close other apps; check free RAM above.")
        except Exception as exc:
            record("FAIL", "Tiny model request failed or took >120 s", str(exc)[:120],
                   "Check: docker compose logs ollama --tail 30")


def check_host_memory() -> None:
    if sys.platform != "win32":
        return

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
            ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))  # type: ignore[attr-defined]
    free_gb = status.ullAvailPhys / 1024**3
    total_gb = status.ullTotalPhys / 1024**3
    if free_gb < 1.5:
        record(
            "WARN",
            f"Only {free_gb:.1f} GB of {total_gb:.0f} GB host RAM is free",
            "Under this much pressure the docker CLI hangs and model calls time out.",
            "Close browsers/IDEs and other heavy apps before the demo.",
        )
    else:
        record("OK", f"{free_gb:.1f} GB of {total_gb:.0f} GB host RAM free")


def docker_psql(env: dict[str, str], sql: str) -> str | None:
    user, db = env.get("APP_DB_USER", "appuser"), env.get("APP_DB_NAME", "email_ops")
    try:
        done = subprocess.run(
            ["docker", "compose", "exec", "-T", "app-db", "psql", "-U", user, "-d", db, "-tAc", sql],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        record("WARN", "docker CLI did not answer within 30 s",
               "Usually host memory pressure, not a stack problem; the HTTP checks above still hold.",
               "Free RAM or restart Docker Desktop, then re-run.")
        return None
    except FileNotFoundError:
        record("WARN", "docker CLI not found on PATH")
        return None
    if done.returncode != 0:
        record("WARN", "Could not query the audit database", done.stderr.strip()[:160],
               "Is the app-db container running? docker compose ps")
        return None
    return done.stdout.strip()


def check_database(env: dict[str, str]) -> None:
    out = docker_psql(
        env,
        "select (select count(*) from email_messages), (select count(*) from proposed_actions), "
        "(select count(*) from approval_decisions), (select count(*) from users)",
    )
    if out is None:
        return
    emails, proposals, decisions, users = (int(n) for n in out.split("|"))
    if emails or proposals or decisions:
        record(
            "FAIL",
            f"Audit DB is not empty ({emails} emails, {proposals} proposals, {decisions} decisions)",
            "Already-processed emails are skipped, so the acts would not replay.",
            "Back up, then truncate (ask the user first; this deletes audit rows):\n"
            "         docker compose exec -T app-db pg_dump -U <APP_DB_USER> -d <APP_DB_NAME> --data-only "
            "-t email_messages -t extraction_results -t proposed_actions -t approval_decisions "
            "-t execution_results > <backup>.sql\n"
            "         docker compose exec -T app-db psql -U <APP_DB_USER> -d <APP_DB_NAME> -c "
            '"TRUNCATE execution_results, approval_decisions, proposed_actions, '
            'extraction_results, email_messages"',
        )
    else:
        record("OK", "Audit DB is empty")
    if users == 0:
        record("FAIL", "No reviewer account exists (every page answers 401)",
               fix="The user runs this (it prompts for a password): "
               "docker compose exec app python -m app.cli create-user demo")
    else:
        record("OK", f"{users} reviewer account(s) exist")


def check_live_emails(env: dict[str, str]) -> None:
    port = env.get("EMAIL_SIM_PORT", "8001")
    status, data = http_json(f"http://localhost:{port}/messages")
    if not isinstance(data, list):
        return
    live = {m.get("id") for m in data}
    if live != ACT1_MESSAGE_IDS:
        record(
            "FAIL",
            f"Simulator is serving {sorted(live)}; Act 1 expects only {sorted(ACT1_MESSAGE_IDS)}",
            "Later acts are released on cue; leaving them live processes everything at once, "
            "before the earlier records exist to match against.",
            "bash scripts/release_demo_emails.sh reset",
        )
    else:
        record("OK", "Only the Act 1 emails are live")


def check_espocrm(env: dict[str, str]) -> None:
    key = env.get("ESPOCRM_API_KEY", "")
    if not key:
        record("FAIL", "ESPOCRM_API_KEY is empty in .env",
               fix="Create an API user in EspoCRM and put its key in .env")
        return
    port = env.get("ESPOCRM_PORT", "8080")
    status, data = http_json(
        f"http://localhost:{port}/api/v1/Lead?maxSize=1&select=emailAddress",
        {"X-Api-Key": key},
    )
    if status != 200 or not isinstance(data, dict):
        record("FAIL", f"EspoCRM API rejected the key (HTTP {status})",
               fix="Recreate the API user/key in EspoCRM and update .env")
        return
    total = data.get("total", 0)
    if total:
        record("FAIL", f"EspoCRM already has {total} Lead(s)",
               "Act 1 would propose an update instead of a create.",
               "Delete them in EspoCRM (Leads > select > Remove). Ask the user before doing it for them.")
    else:
        record("OK", "EspoCRM has no Leads")


def check_plane(env: dict[str, str]) -> None:
    key, slug, project = (env.get(k, "") for k in
                          ("PLANE_API_KEY", "PLANE_WORKSPACE_SLUG", "PLANE_DEFAULT_PROJECT_ID"))
    if not (key and slug and project):
        record("FAIL", "PLANE_API_KEY / PLANE_WORKSPACE_SLUG / PLANE_DEFAULT_PROJECT_ID missing in .env")
        return
    base = env.get("PLANE_API_BASE_URL", "https://api.plane.so").rstrip("/")
    status, data = http_json(
        f"{base}/api/v1/workspaces/{slug}/projects/{project}/work-items/",
        {"X-API-Key": key}, timeout=20,
    )
    if status != 200 or not isinstance(data, dict):
        record("FAIL", f"Plane API call failed (HTTP {status})",
               "Wrong slug/project ID, bad key, or no network.",
               "Check the PLANE_* values in .env against the project URL in Plane")
        return
    ours = [i for i in data.get("results", []) if i.get("external_source") == AGENT_SOURCE]
    if ours:
        titles = "; ".join(f"#{i.get('sequence_id')} {i.get('name')!r}" for i in ours[:4])
        record("FAIL", f"Plane project already has {len(ours)} agent-created work item(s): {titles}",
               "Act 1 would propose an update instead of a create.",
               "Delete them in Plane (they carry external_source=email-ops-agent). "
               "Plane's own onboarding sample items can stay. Ask the user first.")
    else:
        record("OK", "Plane project has no agent-created work items")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--deep", action="store_true", help="also time one tiny model request")
    args = parser.parse_args()

    env = load_env()
    if not env:
        print(f"No .env found at {ROOT / '.env'}", file=sys.stderr)
        return 1

    check_host_memory()
    if check_services(env):
        check_llm_provider(env)
        check_model(env, args.deep)
        check_live_emails(env)
        check_database(env)
        check_espocrm(env)
        check_plane(env)

    marks = {"OK": "[ OK ]", "WARN": "[WARN]", "FAIL": "[FAIL]"}
    for level, title, detail, fix in results:
        print(f"{marks[level]} {title}")
        if detail:
            print(f"       {detail}")
        if fix:
            print(f"       fix: {fix}")
    fails = sum(1 for r in results if r[0] == "FAIL")
    warns = sum(1 for r in results if r[0] == "WARN")
    print()
    print("Ready for a clean demo." if not (fails or warns)
          else f"{fails} problem(s) and {warns} warning(s) to resolve before the demo.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
