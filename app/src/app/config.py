from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://appuser:apppassword@localhost:5432/email_ops"
    )
    email_simulator_url: str = "http://localhost:8001"

    espocrm_base_url: str = "http://localhost:8080"
    espocrm_api_key: str = ""

    plane_api_base_url: str = "https://api.plane.so"
    plane_api_key: str = ""
    plane_workspace_slug: str = ""
    # Which project new support-request issues get filed into (from the
    # project's URL/settings in the Plane UI). A real multi-project setup
    # would derive this from the email rather than hardcoding one project.
    plane_default_project_id: str = ""

    # "ollama" (default) keeps email content on-prem; "claude" is a
    # fast-POC fallback for clients without a data-residency constraint.
    # See app/src/app/llm/ — pipeline code depends only on LLMClient,
    # never on either backend directly.
    llm_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "mistral:7b-instruct"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"


@lru_cache
def get_settings() -> Settings:
    return Settings()
