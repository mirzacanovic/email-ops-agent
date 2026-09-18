from abc import ABC, abstractmethod
from typing import Any


class SystemConnector(ABC):
    """Common interface every integrated SaaS system implements.

    The pipeline (match/propose/execute) only ever calls these four
    methods. Keeping the interface identical across Plane, EspoCRM, and
    any future system (Zammad, ERPNext, a client's real Salesforce) is
    what lets a new integration be a new adapter instead of a pipeline
    rewrite.
    """

    @abstractmethod
    async def search_records(
        self, entity_type: str, query: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Return records of `entity_type` matching `query`.

        `query` keys are equals-filters on that field (adapters translate
        them into whatever filter syntax the underlying API needs). The
        reserved key `_fulltext` is a hint to use the system's own
        full-text/keyword search instead of an exact match, when it has
        one — used for fuzzy matching (e.g. a company name spelled
        slightly differently than what's on file) without pulling every
        record client-side. Adapters that don't support it may ignore it.
        """

    @abstractmethod
    async def create_record(
        self, entity_type: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a record of `entity_type` and return it as created."""

    @abstractmethod
    async def update_record(
        self, entity_type: str, record_id: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        """Patch an existing record and return it as updated."""

    @abstractmethod
    async def get_schema(self, entity_type: str) -> dict[str, Any]:
        """Return the field schema for `entity_type`, used to constrain
        what the extraction/propose stages are allowed to fill in."""
