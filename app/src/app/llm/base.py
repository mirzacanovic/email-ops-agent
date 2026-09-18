from abc import ABC, abstractmethod
from typing import Any


class LLMClient(ABC):
    """Common interface for whichever model backs classify/extract.

    One method covers both stages: give it a system prompt, a user
    prompt, and a JSON schema, get back a dict conforming to that
    schema. Swapping the backend — Ollama-served Mistral for a
    data-residency-constrained client, Claude for a fast POC — never
    touches app/pipeline/*, the same way SystemConnector keeps Plane
    and EspoCRM interchangeable from the pipeline's point of view.
    """

    @abstractmethod
    async def complete_json(
        self, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Return a dict conforming to `json_schema`."""
