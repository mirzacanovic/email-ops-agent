"""Seed EspoCRM with a couple of contacts/accounts so the match stage in
Phase 1 has something to find (or deliberately miss).

TODO(phase-1):
  - Use app.connectors.espocrm.EspoCRMConnector directly (same code path
    the pipeline uses) rather than a separate ad-hoc client, so this
    script also doubles as a smoke test of the connector.
  - Seed one contact that DOES match a fixture email's sender
    (jordan.lee@northwind-supply.com / Northwind Supply Co.) and leave
    Bluecrest Logistics absent, so the demo shows both the "found an
    existing record" and "no match, propose create" paths.

Run with: python scripts/seed_espocrm.py (from the repo root, with the
app's venv active and .env loaded).
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app" / "src"))

from app.connectors.espocrm import EspoCRMConnector  # noqa: E402

SEED_CONTACTS = [
    {
        "firstName": "Jordan",
        "lastName": "Lee",
        "emailAddress": "jordan.lee@northwind-supply.com",
        "accountName": "Northwind Supply Co.",
    },
]


async def main() -> None:
    connector = EspoCRMConnector(
        base_url=os.environ.get("ESPOCRM_BASE_URL", "http://localhost:8080"),
        api_key=os.environ["ESPOCRM_API_KEY"],
    )
    for contact in SEED_CONTACTS:
        created = await connector.create_record("Contact", contact)
        print(f"Created contact: {created.get('id')} {contact['emailAddress']}")


if __name__ == "__main__":
    asyncio.run(main())
