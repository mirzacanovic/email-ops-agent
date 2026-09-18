from typing import Any

from anthropic import AsyncAnthropic

from app.llm.base import LLMClient


class ClaudeClient(LLMClient):
    """Fast-POC backend — not for deployments with a data-residency
    constraint. Kept alongside OllamaClient to demonstrate that the
    pipeline is backend-agnostic, and useful for prototyping before a
    client's on-prem model is stood up.
    """

    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        self._client = AsyncAnthropic(api_key=api_key)

    async def complete_json(
        self, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]
    ) -> dict[str, Any]:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[
                {
                    "name": "respond",
                    "description": "Return the structured result.",
                    "input_schema": json_schema,
                }
            ],
            tool_choice={"type": "tool", "name": "respond"},
        )
        for block in response.content:
            if block.type == "tool_use":
                return block.input
        raise RuntimeError("Claude did not return a tool_use block")
