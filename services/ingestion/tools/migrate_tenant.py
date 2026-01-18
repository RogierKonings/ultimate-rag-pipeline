"""Tool for migrating tenants between shared and dedicated indices.

Provides zero-downtime migration of tenant data from shared collection/index
to dedicated ones, with support for dry-run, progress tracking, and rollback.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue
from sqlalchemy import update

if TYPE_CHECKING:
    from opensearchpy import AsyncOpenSearch
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


@dataclass
class MigrationResult:
    """Result of tenant migration operation."""

    tenant_id: str
    source_collection: str
    target_collection: str
    source_index: str
    target_index: str
    qdrant_chunks_migrated: int
    opensearch_docs_migrated: int
    duration_seconds: float
    success: bool
    error: str | None = None
    dry_run: bool = False


@dataclass
class MigrationProgress:
    """Progress of ongoing migration."""

    tenant_id: str
    phase: str
    qdrant_copied: int = 0
    opensearch_copied: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class TenantMigrationTool:
    """Tool for migrating tenants between shared and dedicated indices.

    Supports:
    - Dry run mode for testing
    - Batch processing for large tenants
    - Progress tracking
    - Rollback capability

    Example:
        tool = TenantMigrationTool(
            qdrant_client=qdrant,
            opensearch_client=opensearch,
            session_factory=get_async_session,
        )

        # Dry run first
        result = await tool.migrate_to_dedicated(tenant_id, dry_run=True)
        print(f"Would migrate {result.qdrant_chunks_migrated} chunks")

        # Actual migration
        result = await tool.migrate_to_dedicated(tenant_id, dry_run=False)
    """

    def __init__(
        self,
        qdrant_client: AsyncQdrantClient,
        opensearch_client: AsyncOpenSearch,
        session_factory: Callable[[], AsyncSession],
        batch_size: int = 1000,
    ):
        """Initialize migration tool.

        Args:
            qdrant_client: Async Qdrant client.
            opensearch_client: Async OpenSearch client.
            session_factory: Factory for creating async database sessions.
            batch_size: Number of records to process per batch.
        """
        self.qdrant = qdrant_client
        self.opensearch = opensearch_client
        self.session_factory = session_factory
        self.batch_size = batch_size

        # Lazy-load managers
        self._collection_manager = None
        self._index_manager = None

        # Progress tracking
        self._progress: dict[str, MigrationProgress] = {}

    def _get_collection_manager(self):
        """Lazy-load CollectionManager."""
        if self._collection_manager is None:
            from vectorstore.collection_manager import CollectionManager
            self._collection_manager = CollectionManager(self.qdrant)
        return self._collection_manager

    def _get_index_manager(self):
        """Lazy-load OpenSearchIndexManager."""
        if self._index_manager is None:
            from search.index_manager import OpenSearchIndexManager
            self._index_manager = OpenSearchIndexManager(self.opensearch)
        return self._index_manager

    async def migrate_to_dedicated(
        self,
        tenant_id: UUID,
        dry_run: bool = True,
        qdrant_settings: dict | None = None,
        opensearch_settings: dict | None = None,
    ) -> MigrationResult:
        """Migrate tenant from shared to dedicated collection/index.

        Zero-downtime migration process:
        1. Create dedicated collection/index
        2. Copy all tenant's data to new collection/index
        3. Update tenant config to use dedicated
        4. (Data remains in shared for safety)

        Args:
            tenant_id: Tenant UUID to migrate.
            dry_run: If True, simulate without making changes.
            qdrant_settings: Custom settings for new collection.
            opensearch_settings: Custom settings for new index.

        Returns:
            MigrationResult with details and counts.
        """
        tenant_id_str = str(tenant_id)
        start_time = datetime.now(UTC)

        self._progress[tenant_id_str] = MigrationProgress(
            tenant_id=tenant_id_str,
            phase="initializing",
        )

        logger.info(
            "tenant_migration_started",
            tenant_id=tenant_id_str,
            dry_run=dry_run,
        )

        try:
            target_collection = f"documents_{tenant_id_str}"
            target_index = f"documents-{tenant_id_str}"

            # Phase 1: Create dedicated collection/index
            self._progress[tenant_id_str].phase = "creating_indices"

            if not dry_run:
                await self._get_collection_manager().ensure_collection_exists(
                    target_collection, qdrant_settings
                )
                await self._get_index_manager().ensure_index_exists(
                    target_index, opensearch_settings
                )

            # Phase 2: Copy Qdrant vectors
            self._progress[tenant_id_str].phase = "copying_qdrant"
            qdrant_count = await self._copy_qdrant_vectors(
                tenant_id_str,
                "documents",
                target_collection,
                dry_run,
            )

            # Phase 3: Copy OpenSearch documents
            self._progress[tenant_id_str].phase = "copying_opensearch"
            opensearch_count = await self._copy_opensearch_docs(
                tenant_id_str,
                "documents",
                target_index,
                dry_run,
            )

            # Phase 4: Update tenant config
            self._progress[tenant_id_str].phase = "updating_config"

            if not dry_run:
                await self._update_tenant_config(
                    tenant_id,
                    isolation_mode="dedicated",
                    qdrant_collection=target_collection,
                    opensearch_index=target_index,
                )

            duration = (datetime.now(UTC) - start_time).total_seconds()

            logger.info(
                "tenant_migration_complete",
                tenant_id=tenant_id_str,
                qdrant_chunks=qdrant_count,
                opensearch_docs=opensearch_count,
                duration_seconds=duration,
                dry_run=dry_run,
            )

            return MigrationResult(
                tenant_id=tenant_id_str,
                source_collection="documents",
                target_collection=target_collection,
                source_index="documents",
                target_index=target_index,
                qdrant_chunks_migrated=qdrant_count,
                opensearch_docs_migrated=opensearch_count,
                duration_seconds=duration,
                success=True,
                dry_run=dry_run,
            )

        except Exception as e:
            duration = (datetime.now(UTC) - start_time).total_seconds()
            logger.error(
                "tenant_migration_failed",
                tenant_id=tenant_id_str,
                error=str(e),
            )
            return MigrationResult(
                tenant_id=tenant_id_str,
                source_collection="documents",
                target_collection=f"documents_{tenant_id_str}",
                source_index="documents",
                target_index=f"documents-{tenant_id_str}",
                qdrant_chunks_migrated=0,
                opensearch_docs_migrated=0,
                duration_seconds=duration,
                success=False,
                error=str(e),
                dry_run=dry_run,
            )
        finally:
            self._progress.pop(tenant_id_str, None)

    async def _copy_qdrant_vectors(
        self,
        tenant_id: str,
        source_collection: str,
        target_collection: str,
        dry_run: bool,
    ) -> int:
        """Copy tenant's vectors from source to target collection."""
        total_copied = 0
        offset = None

        while True:
            points, offset = await self.qdrant.scroll(
                collection_name=source_collection,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="tenant_id",
                            match=MatchValue(value=tenant_id),
                        )
                    ]
                ),
                limit=self.batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )

            if not points:
                break

            if not dry_run:
                await self.qdrant.upsert(
                    collection_name=target_collection,
                    points=points,
                    wait=True,
                )

            total_copied += len(points)
            self._progress[tenant_id].qdrant_copied = total_copied

            logger.debug(
                "qdrant_batch_copied",
                tenant_id=tenant_id,
                batch_size=len(points),
                total=total_copied,
                dry_run=dry_run,
            )

            if offset is None:
                break

        return total_copied

    async def _copy_opensearch_docs(
        self,
        tenant_id: str,
        source_index: str,
        target_index: str,
        dry_run: bool,
    ) -> int:
        """Copy tenant's documents from source to target index."""
        total_copied = 0
        scroll_id = None

        # Initial search with scroll
        response = await self.opensearch.search(
            index=source_index,
            body={
                "query": {"term": {"tenant_id": tenant_id}},
                "size": self.batch_size,
            },
            scroll="5m",
        )

        while True:
            hits = response["hits"]["hits"]
            if not hits:
                break

            if not dry_run:
                # Bulk index to target
                actions = []
                for hit in hits:
                    actions.append(
                        {"index": {"_index": target_index, "_id": hit["_id"]}}
                    )
                    actions.append(hit["_source"])

                await self.opensearch.bulk(body=actions, refresh=True)

            total_copied += len(hits)
            self._progress[tenant_id].opensearch_copied = total_copied

            logger.debug(
                "opensearch_batch_copied",
                tenant_id=tenant_id,
                batch_size=len(hits),
                total=total_copied,
                dry_run=dry_run,
            )

            scroll_id = response.get("_scroll_id")
            if not scroll_id:
                break

            response = await self.opensearch.scroll(
                scroll_id=scroll_id,
                scroll="5m",
            )

        # Clear scroll
        if scroll_id:
            try:
                await self.opensearch.clear_scroll(scroll_id=scroll_id)
            except Exception as e:  # noqa: S110
                logger.debug("scroll_cleanup_failed", error=str(e))

        return total_copied

    async def _update_tenant_config(
        self,
        tenant_id: UUID,
        isolation_mode: str,
        qdrant_collection: str,
        opensearch_index: str,
    ) -> None:
        """Update tenant configuration in database."""
        from database.models import Tenant

        async with self.session_factory() as session:
            await session.execute(
                update(Tenant)
                .where(Tenant.id == tenant_id)
                .values(
                    isolation_mode=isolation_mode,
                    qdrant_collection_name=qdrant_collection,
                    opensearch_index_name=opensearch_index,
                )
            )
            await session.commit()

        # Invalidate cache
        from tenant.config_service import get_tenant_config_service
        get_tenant_config_service().invalidate_cache(tenant_id)

        logger.info(
            "tenant_config_updated",
            tenant_id=str(tenant_id),
            isolation_mode=isolation_mode,
        )

    async def rollback_to_shared(
        self,
        tenant_id: UUID,
    ) -> bool:
        """Rollback tenant from dedicated to shared.

        Only updates config - dedicated data remains for manual cleanup.

        Args:
            tenant_id: Tenant UUID.

        Returns:
            True if successful, False on error.
        """
        from database.models import Tenant

        try:
            async with self.session_factory() as session:
                await session.execute(
                    update(Tenant)
                    .where(Tenant.id == tenant_id)
                    .values(isolation_mode="shared")
                )
                await session.commit()

            # Invalidate cache
            from tenant.config_service import get_tenant_config_service
            get_tenant_config_service().invalidate_cache(tenant_id)

            logger.info("tenant_rollback_complete", tenant_id=str(tenant_id))
            return True
        except Exception as e:
            logger.error(
                "tenant_rollback_failed",
                tenant_id=str(tenant_id),
                error=str(e),
            )
            return False

    def get_progress(self, tenant_id: str) -> MigrationProgress | None:
        """Get current migration progress for tenant."""
        return self._progress.get(tenant_id)

    async def cleanup_dedicated_data(
        self,
        tenant_id: UUID,
        delete_collection: bool = True,
        delete_index: bool = True,
    ) -> dict[str, bool]:
        """Clean up dedicated collection/index after rollback.

        WARNING: This permanently deletes data.

        Args:
            tenant_id: Tenant UUID.
            delete_collection: Whether to delete Qdrant collection.
            delete_index: Whether to delete OpenSearch index.

        Returns:
            Dict with success status for each operation.
        """
        tenant_id_str = str(tenant_id)
        results = {}

        if delete_collection:
            results["qdrant"] = await self._get_collection_manager().delete_tenant_collection(
                tenant_id_str
            )

        if delete_index:
            results["opensearch"] = await self._get_index_manager().delete_tenant_index(
                tenant_id_str
            )

        return results

    async def get_tenant_stats(
        self,
        tenant_id: UUID,
    ) -> dict:
        """Get statistics about tenant's data in shared collection/index.

        Useful for estimating migration time and resources.

        Args:
            tenant_id: Tenant UUID.

        Returns:
            Dict with vector count and document count.
        """
        tenant_id_str = str(tenant_id)

        # Count vectors in Qdrant
        qdrant_count = 0
        offset = None
        while True:
            points, offset = await self.qdrant.scroll(
                collection_name="documents",
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="tenant_id",
                            match=MatchValue(value=tenant_id_str),
                        )
                    ]
                ),
                limit=1000,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            qdrant_count += len(points)
            if offset is None:
                break

        # Count documents in OpenSearch
        response = await self.opensearch.count(
            index="documents",
            body={"query": {"term": {"tenant_id": tenant_id_str}}},
        )
        opensearch_count = response.get("count", 0)

        return {
            "tenant_id": tenant_id_str,
            "qdrant_vector_count": qdrant_count,
            "opensearch_doc_count": opensearch_count,
        }
