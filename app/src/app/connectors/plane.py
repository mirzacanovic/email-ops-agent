from typing import Any

import httpx

from app.connectors.base import SystemConnector


class PlaneConnector(SystemConnector):
    """Adapter for Plane's REST API (https://developers.plane.so/api-reference).

    Auth: header `x-api-key: <key>`. Most endpoints are scoped under
    `/api/v1/workspaces/{workspace_slug}/...`, and issue operations are
    further scoped to a project, so `entity_type` here is treated as
    `"issues:<project_id>"` — see TODO below for a cleaner scheme once
    the extraction stage knows how to pick a project.
    """

    def __init__(self, base_url: str, api_key: str, workspace_slug: str) -> None:
        self._workspace_slug = workspace_slug
        self._client = httpx.AsyncClient(
            base_url=f"{base_url.rstrip('/')}/api/v1/workspaces/{workspace_slug}",
            headers={"x-api-key": api_key},
            timeout=10.0,
        )

    async def search_records(
        self, entity_type: str, query: dict[str, Any]
    ) -> list[dict[str, Any]]:
        project_id = self._project_id(entity_type)
        response = await self._client.get(f"/projects/{project_id}/issues/", params=query)
        response.raise_for_status()
        return response.json().get("results", [])

    async def create_record(
        self, entity_type: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        project_id = self._project_id(entity_type)
        response = await self._client.post(f"/projects/{project_id}/issues/", json=fields)
        response.raise_for_status()
        return response.json()

    async def update_record(
        self, entity_type: str, record_id: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        project_id = self._project_id(entity_type)
        response = await self._client.patch(
            f"/projects/{project_id}/issues/{record_id}/", json=fields
        )
        response.raise_for_status()
        return response.json()

    async def get_schema(self, entity_type: str) -> dict[str, Any]:
        # TODO(phase-1): Plane doesn't expose a field-schema endpoint the
        # way EspoCRM does; derive the allowed fields (state, priority,
        # labels) from `/projects/{project_id}/` and its states/labels
        # sub-resources instead.
        return {}

    @staticmethod
    def _project_id(entity_type: str) -> str:
        # entity_type is expected as "issues:<project_id>"
        _, _, project_id = entity_type.partition(":")
        if not project_id:
            raise ValueError(
                f"PlaneConnector expects entity_type like 'issues:<project_id>', got {entity_type!r}"
            )
        return project_id
