from functools import lru_cache

from app.config import get_settings
from app.connectors.espocrm import EspoCRMConnector
from app.connectors.plane import PlaneConnector
from app.llm.base import LLMClient
from app.llm.factory import get_llm_client

# lru_cache gives one long-lived client per process (connection pooling)
# rather than a new httpx/Anthropic client per request.


@lru_cache
def get_espocrm_connector() -> EspoCRMConnector:
    settings = get_settings()
    return EspoCRMConnector(base_url=settings.espocrm_base_url, api_key=settings.espocrm_api_key)


@lru_cache
def get_plane_connector() -> PlaneConnector:
    settings = get_settings()
    return PlaneConnector(
        base_url=settings.plane_api_base_url,
        api_key=settings.plane_api_key,
        workspace_slug=settings.plane_workspace_slug,
    )


@lru_cache
def get_llm() -> LLMClient:
    return get_llm_client(get_settings())
