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

    anthropic_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
