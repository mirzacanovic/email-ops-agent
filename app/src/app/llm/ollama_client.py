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

    def __init__(self, base_url: str, model: str, timeout: float = 300.0) -> None:
        self._model = model
        # CPU-only cold loads of a 7B model can take minutes, and Ollama
        # aborts an in-progress load the moment the client disconnects
        # (confirmed from its own logs: "client connection closed before
        # llama-server finished loading, aborting load"). A timeout that
        # fires before the load finishes doesn't just fail that request —
        # it forces every subsequent request to restart the cold load
        # from scratch too, so this needs real headroom rather than a
        # typical HTTP client timeout.
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

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
                # temperature=0 for reproducibility: classify/extract feed
                # an audit trail and an approval decision, and the same
                # email classifying differently across runs (confirmed in
                # testing — one run called a message "support_request",
                # another called it "project_status_question") undermines
                # the whole point of having an auditable, explainable
                # pipeline. Deterministic sampling doesn't fix accuracy,
                # but at least the same input reliably gives the same
                # answer.
                "options": {"temperature": 0},
            },
        )
        response.raise_for_status()
        content = response.json()["message"]["content"]
        return json.loads(content)
