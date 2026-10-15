from app.config import Settings
from app.llm.base import LLMClient
from app.llm.claude_client import ClaudeClient
from app.llm.ollama_client import OllamaClient


def get_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "ollama":
        return OllamaClient(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout=settings.ollama_timeout_seconds,
        )
    if settings.llm_provider == "claude":
        return ClaudeClient(api_key=settings.anthropic_api_key, model=settings.anthropic_model)
    raise ValueError(f"Unknown LLM_PROVIDER: {settings.llm_provider!r}")
