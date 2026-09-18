import json
from typing import Any

import httpx

from app.llm.base import LLMClient


class OllamaClient(LLMClient):
    """Talks to a self-hosted Ollama server.

    Uses Ollama's native `/api/chat` rather than its OpenAI-compatible
    `/v1/chat/completions` endpoint, because `/api/chat` accepts a JSON
    Schema directly in `format` and constrains generation to it —
    important for classify/extract, where the caller needs a dict back,
    not free text to re-parse.
    """

    def __init__(self, base_url: str, model: str) -> None:
        self._model = model
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=60.0)

    async def complete_json(
        self, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]
    ) -> dict[str, Any]:
        response = await self._client.post(
            "/api/chat",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "format": json_schema,
                "stream": False,
            },
        )
        response.raise_for_status()
        content = response.json()["message"]["content"]
        return json.loads(content)
