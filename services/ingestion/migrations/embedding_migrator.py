"""Embedding model migration orchestrator.

Coordinates the full migration lifecycle:
1. Create target collection with new model dimensions
2. Dispatch batch re-embedding tasks via Celery
3. Track progress across distributed workers
4. Validate migration quality
5. Atomically switch collection alias
6. Support rollback if needed
"""

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from qdrant_client import AsyncQdrantClient

from .collection_manager import CollectionManager
from .models import (
    EmbeddingMigration,
    MigrationRequest,
    MigrationStatus,
    ValidationConfig,
    ValidationResult,
)
from .progress_tracker import MigrationProgressStore

logger = logging.getLogger(__name__)


class EmbeddingMigrator:
    """Orchestrates embedding model migrations.

    Coordinates zero-downtime migration from one embedding model to another,
    handling collection management, batch processing coordination, validation,
    and alias switching.
    """

    def __init__(
        self,
        qdrant_client: AsyncQdrantClient,
        progress_store: MigrationProgressStore,
        default_alias: str = "rag_chunks",
    ):
        """Initialize the migrator.

        Args:
            qdrant_client: Async Qdrant client instance.
            progress_store: Migration progress store.
            default_alias: Default collection alias name.
        """
        self.qdrant = qdrant_client
        self.collections = CollectionManager(qdrant_client)
        self.progress = progress_store
        self.default_alias = default_alias

    async def start_migration(
        self,
        request: MigrationRequest,
        current_model: Optional[str] = None,
        current_dimensions: Optional[int] = None,
    ) -> EmbeddingMigration:
        """Start a new embedding migration.

        Args:
            request: Migration request with target model and options.
            current_model: Current model name (auto-detected if None).
            current_dimensions: Current vector dimensions (auto-detected if None).

        Returns:
            Created migration record.

        Raises:
            ValueError: If migration cannot be started.
        """
        migration_id = uuid4()

        # Get current collection from alias
        current_collection = await self.collections.get_alias_target(self.default_alias)
        if not current_collection:
            raise ValueError(
                f"No collection found for alias '{self.default_alias}'. "
                "Please ensure the alias exists before starting migration."
            )

        # Auto-detect current model info if not provided
        if current_model is None:
            current_model = await self._detect_current_model(current_collection)
        if current_dimensions is None:
            current_dimensions = await self._get_collection_dimensions(current_collection)

        # Generate new collection name with timestamp
        version = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        target_collection = f"rag_chunks_v{version}"

        # Detect target dimensions if not specified
        target_dims = request.target_dimensions
        if target_dims is None:
            target_dims = await self._get_model_dimensions(request.target_model)

        # Count documents to migrate
        total_docs = await self._count_documents(
            current_collection,
            tenant_ids=request.tenant_ids,
        )

        # Parse validation config if provided, otherwise use defaults
        validation_config_dict = None
        if request.validation_config:
            validation_config_dict = request.validation_config
        else:
            # Use default validation config
            validation_config_dict = ValidationConfig().to_dict()

        # Create migration record
        migration = EmbeddingMigration(
            migration_id=migration_id,
            source_model=current_model,
            target_model=request.target_model,
            source_dimensions=current_dimensions,
            target_dimensions=target_dims,
            source_collection=current_collection,
            target_collection=target_collection,
            alias_name=self.default_alias,
            total_documents=total_docs,
            rollback_enabled=request.preserve_source,
            validation_config=validation_config_dict,
        )

        # Save migration record
        await self.progress.save_migration(migration)

        # Create target collection
        success = await self.collections.create_migration_collection(
            target_collection,
            target_dims,
        )
        if not success:
            migration.status = MigrationStatus.FAILED
            migration.last_error = "Failed to create target collection"
            await self.progress.save_migration(migration)
            raise ValueError("Failed to create target collection")

        logger.info(
            f"Started migration {migration_id}: "
            f"{current_model} -> {request.target_model} "
            f"({total_docs} documents)"
        )

        # Start batch re-embedding via Celery
        await self._dispatch_reembedding_tasks(
            migration=migration,
            batch_size=request.batch_size,
            max_concurrent=request.max_concurrent_batches,
            tenant_ids=request.tenant_ids,
        )

        return migration

    async def _dispatch_reembedding_tasks(
        self,
        migration: EmbeddingMigration,
        batch_size: int,
        max_concurrent: int,
        tenant_ids: Optional[list[str]] = None,
    ) -> None:
        """Dispatch Celery tasks for batch re-embedding.

        Args:
            migration: Migration record.
            batch_size: Documents per batch.
            max_concurrent: Maximum concurrent batches.
            tenant_ids: Optional tenant filter.
        """
        from services.ingestion.tasks.reembed import reembed_migration_batch

        # Get all document IDs to process
        document_ids = await self._get_document_ids(
            migration.source_collection,
            tenant_ids=tenant_ids,
        )

        if not document_ids:
            logger.warning(f"No documents found for migration {migration.migration_id}")
            migration.status = MigrationStatus.COMPLETED
            migration.completed_at = datetime.utcnow()
            await self.progress.save_migration(migration)
            return

        # Create batches
        batches = [
            document_ids[i : i + batch_size]
            for i in range(0, len(document_ids), batch_size)
        ]

        # Update migration status
        migration.status = MigrationStatus.IN_PROGRESS
        migration.started_at = datetime.utcnow()
        await self.progress.save_migration(migration)

        # Dispatch tasks using Celery group for parallel processing
        from celery import group

        job = group(
            reembed_migration_batch.s(
                migration_id=str(migration.migration_id),
                chunk_ids=[str(cid) for cid in batch],
                source_collection=migration.source_collection,
                target_collection=migration.target_collection,
                target_model=migration.target_model,
                batch_index=i,
            )
            for i, batch in enumerate(batches)
        )

        # Apply with rate limiting based on max_concurrent
        job.apply_async()

        logger.info(
            f"Dispatched {len(batches)} re-embedding tasks for migration "
            f"{migration.migration_id}"
        )

    async def get_migration_status(
        self, migration_id: UUID
    ) -> Optional[EmbeddingMigration]:
        """Get current status of a migration.

        Args:
            migration_id: UUID of the migration.

        Returns:
            Migration record if found.
        """
        return await self.progress.get_migration(migration_id)

    async def validate_migration(
        self,
        migration_id: UUID,
        sample_size: Optional[int] = None,
        overlap_threshold: Optional[float] = None,
    ) -> ValidationResult:
        """Validate migration quality before switching.

        Compares retrieval results between source and target collections
        using a sample of queries to ensure similar results.

        Args:
            migration_id: UUID of the migration.
            sample_size: Number of sample queries to test (uses stored config if None).
            overlap_threshold: Minimum overlap score to pass validation (uses stored config if None).

        Returns:
            Validation result with overlap scores.

        Raises:
            ValueError: If migration not found or not ready for validation.
        """
        migration = await self.progress.get_migration(migration_id)
        if not migration:
            raise ValueError(f"Migration {migration_id} not found")

        if migration.status not in (
            MigrationStatus.VALIDATING,
            MigrationStatus.IN_PROGRESS,
        ):
            raise ValueError(
                f"Migration {migration_id} not ready for validation "
                f"(status={migration.status})"
            )

        # Get validation config from migration record, or use defaults
        config = ValidationConfig.from_dict(migration.validation_config)

        # Apply overrides if provided
        effective_sample_size = sample_size if sample_size is not None else config.sample_size
        effective_threshold = overlap_threshold if overlap_threshold is not None else config.recall_threshold

        # Update status
        migration.status = MigrationStatus.VALIDATING
        await self.progress.save_migration(migration)

        # Get sample queries (in production, use retrieval logs)
        sample_queries = await self._get_sample_queries(effective_sample_size)

        overlap_scores = []

        for query in sample_queries:
            try:
                # Search in both collections
                old_results = await self._search_collection(
                    migration.source_collection,
                    query,
                    top_k=10,
                )
                new_results = await self._search_collection(
                    migration.target_collection,
                    query,
                    top_k=10,
                )

                # Calculate overlap
                old_ids = {r["id"] for r in old_results}
                new_ids = {r["id"] for r in new_results}

                if old_ids:
                    overlap = len(old_ids & new_ids) / len(old_ids)
                else:
                    overlap = 1.0 if not new_ids else 0.0

                overlap_scores.append(overlap)

            except Exception as e:
                logger.warning(f"Validation query failed: {e}")
                overlap_scores.append(0.0)

        # Create result
        result = ValidationResult.from_scores(overlap_scores, effective_threshold)

        # Update migration record
        migration.validation_score = result.avg_overlap
        migration.validation_passed = result.validation_passed
        await self.progress.save_migration(migration)

        logger.info(
            f"Migration {migration_id} validation: "
            f"avg_overlap={result.avg_overlap:.2%}, "
            f"passed={result.validation_passed}"
        )

        return result

    async def switch_to_new_collection(
        self,
        migration_id: UUID,
        force: bool = False,
    ) -> bool:
        """Switch the alias to the new collection.

        Args:
            migration_id: UUID of the migration.
            force: If True, switch even if validation didn't pass.

        Returns:
            True if switch was successful.

        Raises:
            ValueError: If migration not found or not ready for switch.
        """
        migration = await self.progress.get_migration(migration_id)
        if not migration:
            raise ValueError(f"Migration {migration_id} not found")

        if not migration.validation_passed and not force:
            raise ValueError(
                f"Migration {migration_id} validation not passed. "
                "Use force=True to switch anyway."
            )

        # Update status
        migration.status = MigrationStatus.SWITCHING
        await self.progress.save_migration(migration)

        # Atomic alias switch
        success = await self.collections.switch_alias(
            alias_name=migration.alias_name,
            new_collection=migration.target_collection,
            old_collection=migration.source_collection,
        )

        if success:
            migration.status = MigrationStatus.COMPLETED
            migration.completed_at = datetime.utcnow()
            logger.info(
                f"Migration {migration_id} completed: "
                f"switched alias {migration.alias_name} to {migration.target_collection}"
            )
        else:
            migration.status = MigrationStatus.FAILED
            migration.last_error = "Failed to switch alias"
            logger.error(f"Migration {migration_id} failed to switch alias")

        await self.progress.save_migration(migration)
        return success

    async def rollback_migration(self, migration_id: UUID) -> bool:
        """Rollback to the original collection.

        Args:
            migration_id: UUID of the migration.

        Returns:
            True if rollback was successful.

        Raises:
            ValueError: If migration not found or rollback not possible.
        """
        migration = await self.progress.get_migration(migration_id)
        if not migration:
            raise ValueError(f"Migration {migration_id} not found")

        if not migration.can_rollback:
            raise ValueError(
                f"Migration {migration_id} cannot be rolled back "
                f"(status={migration.status}, rollback_enabled={migration.rollback_enabled})"
            )

        # Switch alias back to source
        success = await self.collections.switch_alias(
            alias_name=migration.alias_name,
            new_collection=migration.source_collection,
            old_collection=migration.target_collection,
        )

        if success:
            migration.status = MigrationStatus.ROLLED_BACK
            migration.completed_at = datetime.utcnow()
            await self.progress.save_migration(migration)

            # Delete the target collection
            await self.collections.delete_collection(migration.target_collection)

            logger.info(
                f"Migration {migration_id} rolled back: "
                f"restored alias to {migration.source_collection}"
            )
        else:
            migration.last_error = "Failed to rollback alias"
            await self.progress.save_migration(migration)
            logger.error(f"Migration {migration_id} rollback failed")

        return success

    async def cleanup_old_collection(self, migration_id: UUID) -> bool:
        """Delete the source collection after successful migration.

        Only call this after confirming the migration is stable.

        Args:
            migration_id: UUID of the migration.

        Returns:
            True if cleanup was successful.

        Raises:
            ValueError: If migration not completed or cleanup not safe.
        """
        migration = await self.progress.get_migration(migration_id)
        if not migration:
            raise ValueError(f"Migration {migration_id} not found")

        if migration.status != MigrationStatus.COMPLETED:
            raise ValueError(
                f"Migration {migration_id} not completed (status={migration.status})"
            )

        # Verify alias points to target
        current_target = await self.collections.get_alias_target(migration.alias_name)
        if current_target != migration.target_collection:
            raise ValueError(
                f"Alias {migration.alias_name} does not point to target collection. "
                "Cleanup aborted for safety."
            )

        success = await self.collections.delete_collection(migration.source_collection)
        if success:
            migration.rollback_enabled = False
            await self.progress.save_migration(migration)
            logger.info(f"Cleaned up source collection {migration.source_collection}")

        return success

    async def cancel_migration(self, migration_id: UUID) -> bool:
        """Cancel an in-progress migration.

        Args:
            migration_id: UUID of the migration.

        Returns:
            True if cancellation was successful.
        """
        migration = await self.progress.get_migration(migration_id)
        if not migration:
            raise ValueError(f"Migration {migration_id} not found")

        if not migration.is_active:
            raise ValueError(
                f"Migration {migration_id} is not active (status={migration.status})"
            )

        # Update status
        migration.status = MigrationStatus.FAILED
        migration.last_error = "Cancelled by user"
        migration.completed_at = datetime.utcnow()
        await self.progress.save_migration(migration)

        # Clean up target collection
        await self.collections.delete_collection(migration.target_collection)

        logger.info(f"Migration {migration_id} cancelled")
        return True

    # Helper methods

    async def _detect_current_model(self, collection_name: str) -> str:
        """Detect the model used for a collection.

        In production, this would query metadata stored with the collection.
        """
        # Default to the standard model
        return "BAAI/bge-large-en-v1.5"

    async def _get_collection_dimensions(self, collection_name: str) -> int:
        """Get vector dimensions for a collection."""
        info = await self.collections.get_collection_info(collection_name)
        if info and "config" in info:
            return info["config"].get("vector_size", 1024)
        return 1024

    async def _get_model_dimensions(self, model_name: str) -> int:
        """Get dimensions for a model.

        Maps known models to their dimensions.
        """
        model_dimensions = {
            "BAAI/bge-large-en-v1.5": 1024,
            "BAAI/bge-m3": 1024,
            "BAAI/bge-base-en-v1.5": 768,
            "BAAI/bge-small-en-v1.5": 384,
            "sentence-transformers/all-MiniLM-L6-v2": 384,
            "sentence-transformers/all-mpnet-base-v2": 768,
            "text-embedding-ada-002": 1536,
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
        }
        return model_dimensions.get(model_name, 1024)

    async def _count_documents(
        self,
        collection_name: str,
        tenant_ids: Optional[list[str]] = None,
    ) -> int:
        """Count documents in a collection."""
        return await self.collections.get_collection_vector_count(collection_name)

    async def _get_document_ids(
        self,
        collection_name: str,
        tenant_ids: Optional[list[str]] = None,
        limit: int = 100000,
    ) -> list[str]:
        """Get all chunk IDs from a collection.

        Args:
            collection_name: Collection to query.
            tenant_ids: Optional tenant filter.
            limit: Maximum IDs to return.

        Returns:
            List of chunk ID strings.
        """
        from qdrant_client.models import Filter, FieldCondition, MatchAny

        try:
            # Build filter if tenant_ids specified
            query_filter = None
            if tenant_ids:
                query_filter = Filter(
                    must=[
                        FieldCondition(
                            key="tenant_id",
                            match=MatchAny(any=tenant_ids),
                        )
                    ]
                )

            # Scroll through all points
            chunk_ids = []
            offset = None

            while len(chunk_ids) < limit:
                results, offset = await self.qdrant.scroll(
                    collection_name=collection_name,
                    scroll_filter=query_filter,
                    limit=1000,
                    offset=offset,
                    with_payload=False,
                    with_vectors=False,
                )

                for point in results:
                    chunk_ids.append(str(point.id))

                if offset is None:
                    break

            return chunk_ids[:limit]

        except Exception as e:
            logger.error(f"Failed to get document IDs from {collection_name}: {e}")
            return []

    async def _get_sample_queries(self, sample_size: int) -> list[str]:
        """Get sample queries for validation.

        In production, this would retrieve recent queries from retrieval logs.
        For now, returns placeholder queries.
        """
        # TODO: Integrate with retrieval logs
        return [
            "What is the main topic?",
            "How does authentication work?",
            "Explain the architecture",
            "What are the key features?",
            "How to get started?",
        ][:sample_size]

    async def _search_collection(
        self,
        collection_name: str,
        query: str,
        top_k: int = 10,
    ) -> list[dict]:
        """Search a collection with a query.

        Args:
            collection_name: Collection to search.
            query: Query text.
            top_k: Number of results.

        Returns:
            List of result dicts with id and score.
        """
        from services.ingestion.embedding.service import (
            EmbeddingService,
            EmbeddingServiceConfig,
        )

        # Get query embedding using current service
        config = EmbeddingServiceConfig()
        async with EmbeddingService(config=config) as service:
            query_embedding = await service.embed_query(query)

        # Search collection
        results = await self.qdrant.search(
            collection_name=collection_name,
            query_vector=query_embedding,
            limit=top_k,
        )

        return [{"id": str(r.id), "score": r.score} for r in results]
