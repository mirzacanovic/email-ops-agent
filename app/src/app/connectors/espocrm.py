from typing import Any

import httpx

from app.connectors.base import SystemConnector


class EspoCRMConnector(SystemConnector):
    """Adapter for EspoCRM's REST API (https://docs.espocrm.com/development/api/).

    Auth: header `X-Api-Key: <key>` from an EspoCRM API User.
    """

    def __init__(self, base_url: str, api_key: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=f"{base_url.rstrip('/')}/api/v1",
            headers={"X-Api-Key": api_key},
            timeout=10.0,
        )

    async def search_records(
        self, entity_type: str, query: dict[str, Any]
    ) -> list[dict[str, Any]]:
        # TODO(phase-1): translate `query` into EspoCRM's `where[]` array
        # syntax instead of passing raw params through.
        response = await self._client.get(f"/{entity_type}", params=query)
        response.raise_for_status()
        return response.json().get("list", [])

    async def create_record(
        self, entity_type: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        response = await self._client.post(f"/{entity_type}", json=fields)
        response.raise_for_status()
        return response.json()

    async def update_record(
        self, entity_type: str, record_id: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        response = await self._client.put(f"/{entity_type}/{record_id}", json=fields)
        response.raise_for_status()
        return response.json()

    async def get_schema(self, entity_type: str) -> dict[str, Any]:
        response = await self._client.get("/Metadata")
        response.raise_for_status()
        return response.json().get("entityDefs", {}).get(entity_type, {})
