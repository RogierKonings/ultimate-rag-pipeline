"""Manager for per-tenant Qdrant collections.

Provides utilities for creating, configuring, and managing tenant-specific
Qdrant collections for index isolation.
"""

from __future__ import annotations

import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    HnswConfigDiff,
    OptimizersConfigDiff,
    PayloadSchemaType,
    VectorParams,
)

logger = structlog.get_logger(__name__)

# Default settings matching the ingestion service configuration
DEFAULT_QDRANT_SETTINGS = {
    "vector_size": 1024,  # BGE-large dimensions
    "distance": "Cosine",
    "hnsw_m": 16,
    "hnsw_ef_construct": 100,
    "memmap_threshold": 20000,
}

# Fields to index for efficient filtering
PAYLOAD_INDICES = [
    ("document_id", PayloadSchemaType.KEYWORD),
    ("tenant_id", PayloadSchemaType.KEYWORD),
    ("status", PayloadSchemaType.KEYWORD),
    ("visibility", PayloadSchemaType.KEYWORD),
    ("allowed_groups", PayloadSchemaType.KEYWORD),
    ("allowed_users", PayloadSchemaType.KEYWORD),
    ("source_type", PayloadSchemaType.KEYWORD),
]


class CollectionManager:
    """Manages Qdrant collections for multi-tenant isolation.

    Provides methods to create, delete, and inspect per-tenant collections.
    Each tenant can have a dedicated collection with custom settings for
    HNSW parameters and optimizers.

    Example:
        manager = CollectionManager(qdrant_client)
        collection = await manager.create_tenant_collection(
            tenant_id="550e8400-e29b-41d4-a716-446655440000",
            settings={"hnsw_m": 32}  # Custom HNSW settings
        )
    """

    def __init__(self, client: AsyncQdrantClient):
        """Initialize the collection manager.

        Args:
            client: Async Qdrant client instance.
        """
        self.client = client

    async def ensure_collection_exists(
        self,
        collection_name: str,
        settings: dict | None = None,
    ) -> bool:
        """Ensure collection exists, creating if necessary.

        Args:
            collection_name: Name of the collection.
            settings: Optional custom settings (merged with defaults).

        Returns:
            True if collection was created, False if already existed.
        """
        collections = await self.client.get_collections()
        if any(c.name == collection_name for c in collections.collections):
            logger.info("collection_exists", collection_name=collection_name)
            return False

        # Merge settings with defaults
        effective = {**DEFAULT_QDRANT_SETTINGS, **(settings or {})}

        # Map distance string to enum
        distance = Distance[effective["distance"].upper()]

        # Create collection
        await self.client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=effective["vector_size"],
                distance=distance,
            ),
            hnsw_config=HnswConfigDiff(
                m=effective["hnsw_m"],
                ef_construct=effective["hnsw_ef_construct"],
            ),
            optimizers_config=OptimizersConfigDiff(
                memmap_threshold=effective.get("memmap_threshold", 20000),
            ),
        )

        # Create payload indices
        await self._create_payload_indices(collection_name)

        logger.info(
            "collection_created",
            collection_name=collection_name,
            settings=effective,
        )
        return True

    async def _create_payload_indices(self, collection_name: str) -> None:
        """Create payload field indices for filtering.

        Args:
            collection_name: Collection to create indices on.
        """
        for field_name, field_type in PAYLOAD_INDICES:
            try:
                await self.client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field_name,
                    field_schema=field_type,
                )
            except Exception as e:
                # Log but don't fail - index may already exist
                logger.warning(
                    "payload_index_creation_failed",
                    collection_name=collection_name,
                    field_name=field_name,
                    error=str(e),
                )

    async def create_tenant_collection(
        self,
        tenant_id: str,
        settings: dict | None = None,
    ) -> str:
        """Create dedicated collection for tenant.

        Args:
            tenant_id: Tenant identifier (UUID as string).
            settings: Optional custom HNSW/optimizer settings.

        Returns:
            Collection name that was created.
        """
        collection_name = f"documents_{tenant_id}"
        await self.ensure_collection_exists(collection_name, settings)
        return collection_name

    async def delete_tenant_collection(
        self,
        tenant_id: str,
    ) -> bool:
        """Delete tenant's dedicated collection.

        Args:
            tenant_id: Tenant identifier (UUID as string).

        Returns:
            True if deleted successfully, False on error.
        """
        collection_name = f"documents_{tenant_id}"
        try:
            await self.client.delete_collection(collection_name)
            logger.info("collection_deleted", collection_name=collection_name)
            return True
        except Exception as e:
            logger.error(
                "collection_delete_failed",
                collection_name=collection_name,
                error=str(e),
            )
            return False

    async def get_collection_stats(
        self,
        collection_name: str,
    ) -> dict:
        """Get collection statistics.

        Args:
            collection_name: Name of the collection.

        Returns:
            Dictionary with collection statistics.
        """
        try:
            info = await self.client.get_collection(collection_name)
            return {
                "name": collection_name,
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
                "status": info.status.value,
                "config": {
                    "vector_size": info.config.params.vectors.size,
                    "distance": info.config.params.vectors.distance.value,
                },
            }
        except Exception as e:
            logger.error(
                "get_collection_stats_failed",
                collection_name=collection_name,
                error=str(e),
            )
            return {"name": collection_name, "error": str(e)}

    async def list_tenant_collections(self) -> list[str]:
        """List all tenant-specific collections.

        Returns:
            List of collection names matching the documents_* pattern.
        """
        collections = await self.client.get_collections()
        return [
            c.name
            for c in collections.collections
            if c.name.startswith("documents_")
        ]

    async def collection_exists(self, collection_name: str) -> bool:
        """Check if a collection exists.

        Args:
            collection_name: Name of the collection.

        Returns:
            True if collection exists, False otherwise.
        """
        collections = await self.client.get_collections()
        return any(c.name == collection_name for c in collections.collections)
