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
        """Plane has no field-schema endpoint like EspoCRM's Metadata API,
        and `entity_type` (a project) doesn't change what fields an issue
        has, so this is a static schema rather than a lookup.

        Deliberately excludes state and assignee: both are IDs scoped to
        this workspace/project (from `/projects/{id}/states/` and
        `/members/`), not something extraction should invent from email
        text — the propose stage resolves those from business rules
        (e.g. "new issues start in the backlog state") instead.
        """
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "A concise title summarizing the problem, e.g. "
                        "'CSV export fails on reports page' — not the "
                        "sender's name or company."
                    ),
                },
                "description_html": {
                    "type": "string",
                    "description": (
                        "A description of the issue itself — what's wrong, "
                        "steps to reproduce, impact — in the sender's own "
                        "words. Not the sender's name or company."
                    ),
                },
                "priority": {
                    "type": "string",
                    "enum": ["urgent", "high", "medium", "low", "none"],
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        }

    @staticmethod
    def _project_id(entity_type: str) -> str:
        # entity_type is expected as "issues:<project_id>"
        _, _, project_id = entity_type.partition(":")
        if not project_id:
            raise ValueError(
                f"PlaneConnector expects entity_type like 'issues:<project_id>', got {entity_type!r}"
            )
        return project_id
