"""Runs INSIDE the app container (run_check.py copies it in). Read-only.

Runs the real classify + extract on each email in a JSON file and prints one
JSON line per email. Writes nothing to the database, Plane or EspoCRM (the
EspoCRM connector is only asked for its field schema).

A failure on one email (e.g. a model timeout) is reported on that email's line
instead of killing the run, so the remaining emails still get checked.
"""

import asyncio
import json
import sys

from app.config import get_settings
from app.dependencies import get_espocrm_connector, get_llm, get_plane_connector
from app.ingestion.inbox_poller import INTENT_ROUTES
from app.pipeline.classify import classify
from app.pipeline.extract import extract


async def main(path: str) -> None:
    messages = json.load(open(path, encoding="utf-8"))
    llm, espocrm, plane = get_llm(), get_espocrm_connector(), get_plane_connector()
    project = get_settings().plane_default_project_id
    for m in sorted(messages, key=lambda m: m["id"]):
        out: dict = {"id": m["id"], "subject": m["subject"]}
        try:
            c = await classify(llm, m["subject"], m["body"])
            out.update(intent=c.intent, confidence=c.confidence)
            target = INTENT_ROUTES.get(c.intent)
            if target:
                if target == "espocrm":
                    schema = await espocrm.get_schema("Lead")
                else:
                    schema = await plane.get_schema(f"issues:{project}")
                out["extracted"] = await extract(
                    llm, m["subject"], m["body"], m["from"], c.intent, schema
                )
        except Exception as exc:  # noqa: BLE001 - report, keep going
            out["error"] = f"{type(exc).__name__}: {exc}"[:200]
        print(json.dumps(out, ensure_ascii=False), flush=True)


asyncio.run(main(sys.argv[1]))
