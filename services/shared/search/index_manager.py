"""Manager for per-tenant OpenSearch indices.

Provides utilities for creating, configuring, and managing tenant-specific
OpenSearch indices for index isolation.
"""

from __future__ import annotations

import structlog
from opensearchpy import AsyncOpenSearch

logger = structlog.get_logger(__name__)

# Default index settings matching the ingestion service configuration
DEFAULT_INDEX_SETTINGS = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 1,
        "analysis": {
            "analyzer": {
                "default": {
                    "type": "standard",
                    "stopwords": "_english_",
                }
            }
        },
    },
    "mappings": {
        "properties": {
            "chunk_id": {"type": "keyword"},
            "document_id": {"type": "keyword"},
            "tenant_id": {"type": "keyword"},
            "status": {"type": "keyword"},
            "content": {"type": "text", "analyzer": "default"},
            "chunk_index": {"type": "integer"},
            "token_count": {"type": "integer"},
            "visibility": {"type": "keyword"},
            "allowed_groups": {"type": "keyword"},
            "allowed_users": {"type": "keyword"},
            "owner_id": {"type": "keyword"},
            "source": {"type": "keyword"},
            "source_uri": {"type": "keyword"},
            "source_type": {"type": "keyword"},
            "source_page": {"type": "integer"},
            "source_section": {"type": "keyword"},
            "parent_chunk_id": {"type": "keyword"},
            "created_at": {"type": "date"},
        }
    },
}


class OpenSearchIndexManager:
    """Manages OpenSearch indices for multi-tenant isolation.

    Provides methods to create, delete, and inspect per-tenant indices.
    Each tenant can have a dedicated index with custom settings.

    Example:
        manager = OpenSearchIndexManager(opensearch_client)
        index = await manager.create_tenant_index(
            tenant_id="550e8400-e29b-41d4-a716-446655440000",
            settings={"settings": {"number_of_shards": 2}}
        )
    """

    def __init__(self, client: AsyncOpenSearch):
        """Initialize the index manager.

        Args:
            client: Async OpenSearch client instance.
        """
        self.client = client

    async def ensure_index_exists(
        self,
        index_name: str,
        settings: dict | None = None,
    ) -> bool:
        """Ensure index exists, creating if necessary.

        Args:
            index_name: Name of the index.
            settings: Optional custom settings (deep merged with defaults).

        Returns:
            True if index was created, False if already existed.
        """
        exists = await self.client.indices.exists(index=index_name)
        if exists:
            logger.info("index_exists", index_name=index_name)
            return False

        # Merge settings with defaults
        effective_settings = self._deep_merge(
            DEFAULT_INDEX_SETTINGS,
            settings or {},
        )

        await self.client.indices.create(
            index=index_name,
            body=effective_settings,
        )

        logger.info("index_created", index_name=index_name)
        return True

    async def create_tenant_index(
        self,
        tenant_id: str,
        settings: dict | None = None,
    ) -> str:
        """Create dedicated index for tenant.

        Args:
            tenant_id: Tenant identifier (UUID as string).
            settings: Optional custom index settings.

        Returns:
            Index name that was created.
        """
        index_name = f"documents-{tenant_id}"
        await self.ensure_index_exists(index_name, settings)
        return index_name

    async def delete_tenant_index(
        self,
        tenant_id: str,
    ) -> bool:
        """Delete tenant's dedicated index.

        Args:
            tenant_id: Tenant identifier (UUID as string).

        Returns:
            True if deleted successfully, False on error.
        """
        index_name = f"documents-{tenant_id}"
        try:
            await self.client.indices.delete(index=index_name)
            logger.info("index_deleted", index_name=index_name)
            return True
        except Exception as e:
            logger.error(
                "index_delete_failed",
                index_name=index_name,
                error=str(e),
            )
            return False

    async def get_index_stats(
        self,
        index_name: str,
    ) -> dict:
        """Get index statistics.

        Args:
            index_name: Name of the index.

        Returns:
            Dictionary with index statistics.
        """
        try:
            stats = await self.client.indices.stats(index=index_name)
            index_stats = stats["indices"].get(index_name, {})
            primaries = index_stats.get("primaries", {})
            return {
                "name": index_name,
                "docs_count": primaries.get("docs", {}).get("count", 0),
                "deleted_docs": primaries.get("docs", {}).get("deleted", 0),
                "store_size_bytes": primaries.get("store", {}).get(
                    "size_in_bytes", 0
                ),
            }
        except Exception as e:
            logger.error(
                "get_index_stats_failed",
                index_name=index_name,
                error=str(e),
            )
            return {"name": index_name, "error": str(e)}

    async def list_tenant_indices(self) -> list[str]:
        """List all tenant-specific indices.

        Returns:
            List of index names matching the documents-* pattern.
        """
        try:
            # Use cat API to list indices matching pattern
            indices = await self.client.cat.indices(
                index="documents-*",
                format="json",
            )
            return [idx["index"] for idx in indices]
        except Exception as e:
            logger.warning(
                "list_tenant_indices_failed",
                error=str(e),
            )
            return []

    async def index_exists(self, index_name: str) -> bool:
        """Check if an index exists.

        Args:
            index_name: Name of the index.

        Returns:
            True if index exists, False otherwise.
        """
        return await self.client.indices.exists(index=index_name)

    def _deep_merge(self, base: dict, override: dict) -> dict:
        """Deep merge dictionaries.

        Args:
            base: Base dictionary.
            override: Dictionary with values to override.

        Returns:
            Merged dictionary.
        """
        result = base.copy()
        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result
