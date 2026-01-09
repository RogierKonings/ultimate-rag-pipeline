"""Qdrant collection management for embedding migrations.

This module handles collection lifecycle operations needed for zero-downtime
embedding model migrations, including collection creation, alias management,
and atomic switching.
"""

import logging
from typing import Optional

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    HnswConfigDiff,
    OptimizersConfigDiff,
    PayloadSchemaType,
    AliasOperations,
    CreateAliasOperation,
    DeleteAliasOperation,
)

logger = logging.getLogger(__name__)


class CollectionManager:
    """Manage Qdrant collections for embedding migrations.

    Provides operations for:
    - Creating new collections with specific vector configurations
    - Managing collection aliases for zero-downtime switching
    - Atomic alias updates for instant migration cutover
    - Collection cleanup after successful migrations
    """

    def __init__(
        self,
        client: AsyncQdrantClient,
        hnsw_m: int = 16,
        hnsw_ef_construct: int = 100,
    ):
        """Initialize CollectionManager.

        Args:
            client: Async Qdrant client instance.
            hnsw_m: HNSW M parameter for vector index.
            hnsw_ef_construct: HNSW ef_construct parameter.
        """
        self.client = client
        self.hnsw_m = hnsw_m
        self.hnsw_ef_construct = hnsw_ef_construct

    async def create_migration_collection(
        self,
        collection_name: str,
        dimensions: int,
        distance: Distance = Distance.COSINE,
    ) -> bool:
        """Create a new collection for migration target.

        Args:
            collection_name: Name for the new collection.
            dimensions: Vector dimensionality.
            distance: Distance metric (default: Cosine).

        Returns:
            True if collection was created successfully.
        """
        try:
            # Check if collection already exists
            collections = await self.client.get_collections()
            existing_names = [c.name for c in collections.collections]

            if collection_name in existing_names:
                logger.warning(f"Collection {collection_name} already exists")
                return True

            await self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=dimensions,
                    distance=distance,
                ),
                hnsw_config=HnswConfigDiff(
                    m=self.hnsw_m,
                    ef_construct=self.hnsw_ef_construct,
                ),
                optimizers_config=OptimizersConfigDiff(
                    indexing_threshold=20000,
                ),
            )

            # Create payload indices for filtering
            await self._create_payload_indices(collection_name)

            logger.info(
                f"Created migration collection: {collection_name} "
                f"(dims={dimensions}, distance={distance})"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to create collection {collection_name}: {e}")
            return False

    async def _create_payload_indices(self, collection_name: str) -> None:
        """Create indices on filterable fields for the new collection.

        Args:
            collection_name: Name of the collection.
        """
        filterable_fields = [
            "document_id",
            "tenant_id",
            "visibility",
            "allowed_groups",
            "allowed_users",
            "source_type",
        ]

        for field in filterable_fields:
            try:
                await self.client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field,
                    field_schema=PayloadSchemaType.KEYWORD,
                )
            except Exception as e:
                logger.warning(
                    f"Failed to create index on {field} for {collection_name}: {e}"
                )

    async def get_alias_target(self, alias_name: str) -> Optional[str]:
        """Get the collection currently pointed to by an alias.

        Args:
            alias_name: Name of the alias to look up.

        Returns:
            Collection name if alias exists, None otherwise.
        """
        try:
            aliases = await self.client.get_aliases()
            for alias in aliases.aliases:
                if alias.alias_name == alias_name:
                    return alias.collection_name
            return None
        except Exception as e:
            logger.error(f"Failed to get alias {alias_name}: {e}")
            return None

    async def list_collection_aliases(self, collection_name: str) -> list[str]:
        """List all aliases pointing to a collection.

        Args:
            collection_name: Name of the collection.

        Returns:
            List of alias names.
        """
        try:
            aliases = await self.client.get_aliases()
            return [
                alias.alias_name
                for alias in aliases.aliases
                if alias.collection_name == collection_name
            ]
        except Exception as e:
            logger.error(f"Failed to list aliases for {collection_name}: {e}")
            return []

    async def switch_alias(
        self,
        alias_name: str,
        new_collection: str,
        old_collection: Optional[str] = None,
    ) -> bool:
        """Atomically switch alias to new collection.

        This operation is atomic - the alias points to exactly one collection
        at any given time, ensuring zero-downtime migration.

        Args:
            alias_name: Name of the alias to update.
            new_collection: New collection to point to.
            old_collection: Optional old collection (for logging).

        Returns:
            True if switch was successful.
        """
        try:
            # Build alias operations
            operations: list[AliasOperations] = []

            # Delete existing alias if it exists
            current_target = await self.get_alias_target(alias_name)
            if current_target:
                operations.append(
                    AliasOperations(
                        delete_alias=DeleteAliasOperation(alias_name=alias_name)
                    )
                )

            # Create new alias
            operations.append(
                AliasOperations(
                    create_alias=CreateAliasOperation(
                        alias_name=alias_name,
                        collection_name=new_collection,
                    )
                )
            )

            # Execute atomically
            await self.client.update_collection_aliases(change_aliases_operations=operations)

            logger.info(
                f"Switched alias {alias_name}: "
                f"{current_target or 'none'} -> {new_collection}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to switch alias {alias_name} to {new_collection}: {e}")
            return False

    async def create_alias(self, alias_name: str, collection_name: str) -> bool:
        """Create a new alias for a collection.

        Args:
            alias_name: Name for the new alias.
            collection_name: Collection to point to.

        Returns:
            True if alias was created successfully.
        """
        try:
            await self.client.update_collection_aliases(
                change_aliases_operations=[
                    AliasOperations(
                        create_alias=CreateAliasOperation(
                            alias_name=alias_name,
                            collection_name=collection_name,
                        )
                    )
                ]
            )
            logger.info(f"Created alias {alias_name} -> {collection_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to create alias {alias_name}: {e}")
            return False

    async def delete_alias(self, alias_name: str) -> bool:
        """Delete an alias.

        Args:
            alias_name: Name of the alias to delete.

        Returns:
            True if alias was deleted successfully.
        """
        try:
            await self.client.update_collection_aliases(
                change_aliases_operations=[
                    AliasOperations(
                        delete_alias=DeleteAliasOperation(alias_name=alias_name)
                    )
                ]
            )
            logger.info(f"Deleted alias {alias_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete alias {alias_name}: {e}")
            return False

    async def delete_collection(self, collection_name: str) -> bool:
        """Delete a collection (after successful migration).

        Warning: This operation is irreversible. Only delete after confirming
        the migration was successful.

        Args:
            collection_name: Name of the collection to delete.

        Returns:
            True if collection was deleted successfully.
        """
        try:
            # Safety check: don't delete if any aliases point to it
            aliases = await self.list_collection_aliases(collection_name)
            if aliases:
                logger.error(
                    f"Cannot delete collection {collection_name}: "
                    f"has active aliases: {aliases}"
                )
                return False

            await self.client.delete_collection(collection_name)
            logger.info(f"Deleted collection: {collection_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete collection {collection_name}: {e}")
            return False

    async def get_collection_info(self, collection_name: str) -> Optional[dict]:
        """Get information about a collection.

        Args:
            collection_name: Name of the collection.

        Returns:
            Collection info dict or None if not found.
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
            logger.error(f"Failed to get collection info for {collection_name}: {e}")
            return None

    async def get_collection_vector_count(self, collection_name: str) -> int:
        """Get the number of vectors in a collection.

        Args:
            collection_name: Name of the collection.

        Returns:
            Number of vectors, or 0 if collection not found.
        """
        info = await self.get_collection_info(collection_name)
        if info:
            return info.get("vectors_count", 0) or 0
        return 0
