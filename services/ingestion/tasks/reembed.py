"""Re-embedding tasks for model migration.

This module provides Celery tasks for re-embedding documents when
changing embedding models, including support for zero-downtime
migration batches.
"""

import asyncio
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from .celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="tasks.reembed.reembed_collection",
    max_retries=3,
    queue="reembed",
)
def reembed_collection(
    self,
    collection_name: str,
    new_model: str,
    batch_size: int = 100,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Re-embed all documents in a collection with a new model.

    Use case: Upgrading embedding model while preserving documents.

    Args:
        collection_name: Name of the collection to re-embed.
        new_model: New embedding model identifier.
        batch_size: Number of chunks to process per batch.
        tenant_id: Optional tenant filter.

    Returns:
        Summary of re-embedding results.
    """
    try:
        return asyncio.run(
            _reembed_collection_async(
                task=self,
                collection_name=collection_name,
                new_model=new_model,
                batch_size=batch_size,
                tenant_id=tenant_id,
            ),
        )

    except Exception as e:
        logger.error(f"Re-embedding failed: {e}")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e) from e
        raise


async def _reembed_collection_async(
    task,
    collection_name: str,
    new_model: str,
    batch_size: int,
    tenant_id: str | None,
) -> dict[str, Any]:
    """Async implementation of re-embedding.

    Args:
        task: Celery task instance for state updates.
        collection_name: Collection to re-embed.
        new_model: New model identifier.
        batch_size: Batch size for processing.
        tenant_id: Optional tenant filter.

    Returns:
        Results dict.
    """
    from sqlalchemy import select

    from embedding.service import (
        EmbeddingService,
        EmbeddingServiceConfig,
    )
    from shared.database.connection import get_session
    from shared.database.models import Chunk

    start_time = datetime.now(tz=UTC)

    # Get all chunks from PostgreSQL
    task.update_state(
        state="PROGRESS",
        meta={"stage": "loading", "message": "Loading chunks from database..."},
    )

    async with get_session() as session:
        query = select(Chunk).where(Chunk.collection_name == collection_name)
        if tenant_id:
            query = query.where(Chunk.tenant_id == tenant_id)

        result = await session.execute(query)
        chunks = result.scalars().all()

    total = len(chunks)
    if total == 0:
        return {
            "collection": collection_name,
            "new_model": new_model,
            "chunks_reembedded": 0,
            "duration_seconds": 0,
        }

    task.update_state(
        state="PROGRESS",
        meta={
            "stage": "re-embedding",
            "total": total,
            "processed": 0,
            "message": f"Re-embedding {total} chunks with {new_model}...",
        },
    )

    # Configure embedding service with new model
    config = EmbeddingServiceConfig(model=new_model)
    async with EmbeddingService(config=config) as embedding_service:
        processed = 0

        # Process in batches
        for i in range(0, total, batch_size):
            batch = chunks[i : i + batch_size]

            # Generate new embeddings
            new_embeddings = await embedding_service.embed_texts(
                texts=[c.content for c in batch],
                chunk_ids=[c.chunk_id for c in batch],
            )

            # Update vector store
            await _update_embeddings_in_qdrant(
                collection_name=collection_name,
                chunks=batch,
                embeddings=new_embeddings,
            )

            processed += len(batch)
            task.update_state(
                state="PROGRESS",
                meta={
                    "stage": "re-embedding",
                    "total": total,
                    "processed": processed,
                    "message": f"Processed {processed}/{total} chunks",
                },
            )

    end_time = datetime.now(tz=UTC)
    duration = (end_time - start_time).total_seconds()

    return {
        "collection": collection_name,
        "new_model": new_model,
        "chunks_reembedded": processed,
        "duration_seconds": duration,
    }


async def _update_embeddings_in_qdrant(
    collection_name: str,
    chunks: list,
    embeddings,
) -> None:
    """Update embeddings in Qdrant vector store.

    Args:
        collection_name: Qdrant collection name.
        chunks: List of chunk records.
        embeddings: New embeddings result.
    """
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.models import PointStruct

    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    client = AsyncQdrantClient(url=qdrant_url)

    try:
        points = []
        for chunk, emb_result in zip(chunks, embeddings.results, strict=True):
            points.append(
                PointStruct(
                    id=str(chunk.chunk_id),
                    vector=emb_result.embedding,
                    payload={
                        "document_id": str(chunk.document_id),
                        "content": chunk.content,
                        "tenant_id": chunk.tenant_id,
                    },
                ),
            )

        if points:
            await client.upsert(collection_name=collection_name, points=points, wait=True)
    finally:
        await client.close()


# Migration batch task for zero-downtime migrations


@celery_app.task(
    bind=True,
    name="tasks.reembed.reembed_migration_batch",
    max_retries=3,
    default_retry_delay=60,
    rate_limit="10/m",  # Prevent overwhelming embedding service
    queue="reembed",
)
def reembed_migration_batch(
    self,
    migration_id: str,
    chunk_ids: list[str],
    source_collection: str,
    target_collection: str,
    target_model: str,
    batch_index: int = 0,
) -> dict[str, Any]:
    """Re-embed a batch of chunks for a migration.

    This task is designed for zero-downtime migrations where embeddings
    are written to a new collection while the old one remains active.

    Args:
        migration_id: UUID of the migration job.
        chunk_ids: List of chunk ID strings to process.
        source_collection: Source collection to read from.
        target_collection: Target collection to write to.
        target_model: Target embedding model name.
        batch_index: Index of this batch (for logging/tracking).

    Returns:
        Batch processing results.
    """
    try:
        return asyncio.run(
            _reembed_migration_batch_async(
                task=self,
                migration_id=migration_id,
                chunk_ids=chunk_ids,
                source_collection=source_collection,
                target_collection=target_collection,
                target_model=target_model,
                batch_index=batch_index,
            ),
        )

    except Exception as e:
        logger.error(f"Migration batch {batch_index} failed: {e}")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e) from e
        # Record failure in progress tracker
        asyncio.run(
            _record_batch_failure(
                migration_id=migration_id,
                batch_index=batch_index,
                failed_count=len(chunk_ids),
                error=str(e),
            ),
        )
        raise


async def _reembed_migration_batch_async(
    task,
    migration_id: str,
    chunk_ids: list[str],
    source_collection: str,
    target_collection: str,
    target_model: str,
    batch_index: int,
) -> dict[str, Any]:
    """Async implementation of migration batch re-embedding.

    Args:
        task: Celery task instance.
        migration_id: Migration UUID string.
        chunk_ids: Chunk IDs to process.
        source_collection: Source Qdrant collection.
        target_collection: Target Qdrant collection.
        target_model: Target model name.
        batch_index: Batch index for tracking.

    Returns:
        Results dict with processed/failed counts.
    """
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.models import PointStruct

    from embedding.service import (
        EmbeddingService,
        EmbeddingServiceConfig,
    )
    from migrations.models import MigrationProgress
    from migrations.progress_tracker import (
        MigrationProgressStore,
        MigrationProgressStoreConfig,
    )

    start_time = time.time()
    processed = 0
    failed = 0
    error_messages: list[str] = []

    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

    qdrant = AsyncQdrantClient(url=qdrant_url)
    progress_store = MigrationProgressStore(
        config=MigrationProgressStoreConfig(redis_url=redis_url),
    )

    try:
        await progress_store.connect()

        # Update task state
        task.update_state(
            state="PROGRESS",
            meta={
                "stage": "re-embedding",
                "batch": batch_index,
                "total_in_batch": len(chunk_ids),
                "processed": 0,
            },
        )

        # Fetch source points with their payloads
        source_points = await qdrant.retrieve(
            collection_name=source_collection,
            ids=chunk_ids,
            with_payload=True,
            with_vectors=False,
        )

        if not source_points:
            logger.warning(f"No points found for batch {batch_index}")
            return {
                "migration_id": migration_id,
                "batch_index": batch_index,
                "processed": 0,
                "failed": 0,
                "duration_ms": 0,
            }

        # Extract content for re-embedding
        contents = []
        point_map = {}
        for point in source_points:
            content = point.payload.get("content", "")
            if content:
                contents.append(content)
                point_map[str(point.id)] = point

        # Generate new embeddings with target model
        config = EmbeddingServiceConfig(model=target_model)
        async with EmbeddingService(config=config) as embedding_service:
            # Create dummy UUIDs for embedding service
            dummy_ids = [UUID(int=i) for i in range(len(contents))]
            embeddings_result = await embedding_service.embed_texts(
                texts=contents,
                chunk_ids=dummy_ids,
                prefix="passage: ",  # BGE document prefix
            )

        # Build points for target collection
        new_points = []
        for (point_id, source_point), emb_result in zip(
            point_map.items(),
            embeddings_result.results,
            strict=False,
        ):
            try:
                new_points.append(
                    PointStruct(
                        id=point_id,
                        vector=emb_result.embedding,
                        payload=source_point.payload,
                    ),
                )
                processed += 1
            except Exception as e:
                logger.error(f"Failed to create point for {point_id}: {e}")
                error_messages.append(f"Point {point_id}: {str(e)}")
                failed += 1

        # Upsert to target collection
        if new_points:
            await qdrant.upsert(
                collection_name=target_collection,
                points=new_points,
                wait=True,
            )

        # Update progress tracker
        duration_ms = (time.time() - start_time) * 1000

        progress = MigrationProgress(
            migration_id=UUID(migration_id),
            batch_index=batch_index,
            documents_processed=processed,
            documents_failed=failed,
            batch_duration_ms=duration_ms,
            error_messages=error_messages,
        )

        await progress_store.record_batch_progress(progress)

        logger.info(
            f"Migration {migration_id} batch {batch_index}: "
            f"processed={processed}, failed={failed}, duration={duration_ms:.0f}ms",
        )

        return {
            "migration_id": migration_id,
            "batch_index": batch_index,
            "processed": processed,
            "failed": failed,
            "duration_ms": duration_ms,
        }

    finally:
        await qdrant.close()
        await progress_store.disconnect()


async def _record_batch_failure(
    migration_id: str,
    batch_index: int,
    failed_count: int,
    error: str,
) -> None:
    """Record a batch failure in the progress tracker.

    Args:
        migration_id: Migration UUID string.
        batch_index: Index of the failed batch.
        failed_count: Number of documents that failed.
        error: Error message.
    """
    from migrations.models import MigrationProgress
    from migrations.progress_tracker import (
        MigrationProgressStore,
        MigrationProgressStoreConfig,
    )

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

    try:
        async with MigrationProgressStore(
            config=MigrationProgressStoreConfig(redis_url=redis_url),
        ) as store:
            progress = MigrationProgress(
                migration_id=UUID(migration_id),
                batch_index=batch_index,
                documents_processed=0,
                documents_failed=failed_count,
                batch_duration_ms=0,
                error_messages=[error],
            )
            await store.record_batch_progress(progress)
    except Exception as e:
        logger.error(f"Failed to record batch failure: {e}")
