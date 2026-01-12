"""API routes for embedding model migrations.

Provides REST endpoints for managing the full migration lifecycle:
- Start migrations
- Monitor progress
- Validate quality
- Switch collections
- Rollback if needed
"""

import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from qdrant_client import AsyncQdrantClient

from services.ingestion.api.schemas import (
    MigrationListResponseSchema,
    MigrationRequestSchema,
    MigrationResponseSchema,
    StatusResponseSchema,
    SwitchRequestSchema,
    ValidationRequestSchema,
    ValidationResponseSchema,
)
from services.ingestion.migrations.embedding_migrator import EmbeddingMigrator
from services.ingestion.migrations.models import (
    MigrationRequest,
    MigrationStatus,
)
from services.ingestion.migrations.progress_tracker import (
    MigrationProgressStore,
    MigrationProgressStoreConfig,
)

router = APIRouter(tags=["Migrations"])


# Dependency injection


async def get_qdrant_client() -> AsyncQdrantClient:
    """Get Qdrant client instance."""
    url = os.getenv("QDRANT_URL", "http://localhost:6333")
    return AsyncQdrantClient(url=url)


async def get_progress_store() -> MigrationProgressStore:
    """Get migration progress store instance."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    store = MigrationProgressStore(
        config=MigrationProgressStoreConfig(redis_url=redis_url),
    )
    await store.connect()
    return store


async def get_migrator(
    qdrant: AsyncQdrantClient = Depends(get_qdrant_client),
    progress: MigrationProgressStore = Depends(get_progress_store),
) -> EmbeddingMigrator:
    """Get embedding migrator instance."""
    return EmbeddingMigrator(qdrant_client=qdrant, progress_store=progress)


def _migration_to_response(migration) -> MigrationResponseSchema:
    """Convert migration model to response schema."""
    return MigrationResponseSchema(
        migration_id=migration.migration_id,
        source_model=migration.source_model,
        target_model=migration.target_model,
        source_dimensions=migration.source_dimensions,
        target_dimensions=migration.target_dimensions,
        source_collection=migration.source_collection,
        target_collection=migration.target_collection,
        alias_name=migration.alias_name,
        status=migration.status,
        total_documents=migration.total_documents,
        processed_documents=migration.processed_documents,
        failed_documents=migration.failed_documents,
        progress_percentage=migration.progress_percentage,
        created_at=migration.created_at,
        started_at=migration.started_at,
        completed_at=migration.completed_at,
        validation_score=migration.validation_score,
        validation_passed=migration.validation_passed,
        validation_config=migration.validation_config,
        rollback_enabled=migration.rollback_enabled,
        last_error=migration.last_error,
    )


# Endpoints


@router.post("/embeddings", response_model=MigrationResponseSchema)
async def start_embedding_migration(
    request: MigrationRequestSchema,
    migrator: EmbeddingMigrator = Depends(get_migrator),
):
    """Start a new embedding model migration.

    This endpoint initiates a zero-downtime migration from the current
    embedding model to a new one. The migration:

    1. Creates a new collection with the target model dimensions
    2. Dispatches Celery tasks to re-embed all documents
    3. Tracks progress across distributed workers
    4. Requires explicit validation and switch steps

    The source collection remains active until you explicitly switch.

    You can optionally provide a validation_config to customize how the
    migration quality is validated before switching. If not provided,
    defaults will be used (sample_size=100, recall_threshold=0.95,
    latency_threshold_ms=100).
    """
    try:
        # Convert validation config to dict if provided
        validation_config_dict = None
        if request.validation_config:
            validation_config_dict = request.validation_config.model_dump()

        # Convert to internal request model
        migration_request = MigrationRequest(
            target_model=request.target_model,
            target_dimensions=request.target_dimensions,
            tenant_ids=request.tenant_ids,
            batch_size=request.batch_size,
            max_concurrent_batches=request.max_concurrent_batches,
            validate_before_switch=request.validate_before_switch,
            auto_switch=request.auto_switch,
            preserve_source=request.preserve_source,
            validation_config=validation_config_dict,
        )

        migration = await migrator.start_migration(migration_request)
        return _migration_to_response(migration)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Migration start failed: {str(e)}") from e


@router.get("/embeddings", response_model=MigrationListResponseSchema)
async def list_migrations(
    status: MigrationStatus | None = Query(None, description="Filter by status"),
    limit: int = Query(default=50, ge=1, le=200),
    progress: MigrationProgressStore = Depends(get_progress_store),
):
    """List all embedding migrations.

    Returns migrations sorted by creation date (newest first).
    Use the status filter to show only active or completed migrations.
    """
    try:
        migrations = await progress.get_all_migrations(
            limit=limit,
            status_filter=status,
        )

        active_count = sum(1 for m in migrations if m.is_active)

        return MigrationListResponseSchema(
            migrations=[_migration_to_response(m) for m in migrations],
            total=len(migrations),
            active_count=active_count,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list migrations: {str(e)}") from e


@router.get("/embeddings/active", response_model=list[MigrationResponseSchema])
async def get_active_migrations(
    progress: MigrationProgressStore = Depends(get_progress_store),
):
    """Get all currently active migrations.

    Active migrations are those in PENDING, IN_PROGRESS, VALIDATING,
    or SWITCHING status.
    """
    try:
        migrations = await progress.get_active_migrations()
        return [_migration_to_response(m) for m in migrations]

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get active migrations: {str(e)}",
        ) from e


@router.get("/embeddings/{migration_id}", response_model=MigrationResponseSchema)
async def get_migration_status(
    migration_id: UUID,
    progress: MigrationProgressStore = Depends(get_progress_store),
):
    """Get detailed status of a specific migration.

    Returns current progress, validation results, and any errors.
    """
    migration = await progress.get_migration(migration_id)
    if not migration:
        raise HTTPException(status_code=404, detail="Migration not found")

    return _migration_to_response(migration)


@router.post("/embeddings/{migration_id}/validate", response_model=ValidationResponseSchema)
async def validate_migration(
    migration_id: UUID,
    request: ValidationRequestSchema = ValidationRequestSchema(),
    migrator: EmbeddingMigrator = Depends(get_migrator),
):
    """Validate migration quality before switching.

    Compares retrieval results between the source and target collections
    using sample queries. Returns overlap scores to assess whether the
    new model produces comparable results.

    A high overlap score (>70%) indicates the new model finds similar
    results for the same queries, suggesting safe to switch.
    """
    try:
        result = await migrator.validate_migration(
            migration_id=migration_id,
            sample_size=request.sample_size,
            overlap_threshold=request.overlap_threshold,
        )

        return ValidationResponseSchema(
            total_queries=result.total_queries,
            avg_overlap=result.avg_overlap,
            min_overlap=result.min_overlap,
            max_overlap=result.max_overlap,
            validation_passed=result.validation_passed,
            queries_with_low_overlap=result.queries_with_low_overlap,
            overlap_threshold=result.overlap_threshold,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Validation failed: {str(e)}") from e


@router.post("/embeddings/{migration_id}/switch", response_model=StatusResponseSchema)
async def switch_collection(
    migration_id: UUID,
    request: SwitchRequestSchema = SwitchRequestSchema(),
    migrator: EmbeddingMigrator = Depends(get_migrator),
):
    """Switch the collection alias to the new collection.

    This is an atomic operation that instantly switches all traffic
    to the new collection with the target model embeddings.

    By default, requires validation to pass first. Use force=true
    to switch without passing validation (not recommended).
    """
    try:
        success = await migrator.switch_to_new_collection(
            migration_id=migration_id,
            force=request.force,
        )

        if success:
            return StatusResponseSchema(
                status="switched",
                message="Successfully switched to new collection",
                migration_id=migration_id,
            )
        raise HTTPException(status_code=500, detail="Switch operation failed")

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Switch failed: {str(e)}") from e


@router.post("/embeddings/{migration_id}/rollback", response_model=StatusResponseSchema)
async def rollback_migration(
    migration_id: UUID,
    migrator: EmbeddingMigrator = Depends(get_migrator),
):
    """Rollback to the previous collection.

    Switches the alias back to the source collection and deletes
    the target collection. Only available if:
    - preserve_source was enabled when starting the migration
    - The migration status allows rollback

    This is useful if issues are discovered after switching.
    """
    try:
        success = await migrator.rollback_migration(migration_id)

        if success:
            return StatusResponseSchema(
                status="rolled_back",
                message="Successfully rolled back to source collection",
                migration_id=migration_id,
            )
        raise HTTPException(status_code=500, detail="Rollback operation failed")

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rollback failed: {str(e)}") from e


@router.post("/embeddings/{migration_id}/cancel", response_model=StatusResponseSchema)
async def cancel_migration(
    migration_id: UUID,
    migrator: EmbeddingMigrator = Depends(get_migrator),
):
    """Cancel an in-progress migration.

    Stops the migration and cleans up the target collection.
    Does not affect the source collection.
    """
    try:
        success = await migrator.cancel_migration(migration_id)

        if success:
            return StatusResponseSchema(
                status="cancelled",
                message="Migration cancelled and cleaned up",
                migration_id=migration_id,
            )
        raise HTTPException(status_code=500, detail="Cancel operation failed")

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cancel failed: {str(e)}") from e


@router.post("/embeddings/{migration_id}/cleanup", response_model=StatusResponseSchema)
async def cleanup_old_collection(
    migration_id: UUID,
    migrator: EmbeddingMigrator = Depends(get_migrator),
):
    """Delete the old collection after successful migration.

    Only available after a successful migration to free up storage.
    This operation is irreversible and disables rollback.

    Warning: Only call this after confirming the new embeddings
    are working correctly in production.
    """
    try:
        success = await migrator.cleanup_old_collection(migration_id)

        if success:
            return StatusResponseSchema(
                status="cleaned",
                message="Source collection deleted, rollback disabled",
                migration_id=migration_id,
            )
        raise HTTPException(status_code=500, detail="Cleanup operation failed")

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}") from e


@router.delete("/embeddings/{migration_id}", response_model=StatusResponseSchema)
async def delete_migration_record(
    migration_id: UUID,
    progress: MigrationProgressStore = Depends(get_progress_store),
):
    """Delete a migration record from the tracking store.

    Does not affect the actual collections, only removes the
    migration tracking record. Useful for cleaning up old records.
    """
    migration = await progress.get_migration(migration_id)
    if not migration:
        raise HTTPException(status_code=404, detail="Migration not found")

    if migration.is_active:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete active migration. Cancel it first.",
        )

    success = await progress.delete_migration(migration_id)
    if success:
        return StatusResponseSchema(
            status="deleted",
            message="Migration record deleted",
            migration_id=migration_id,
        )
    raise HTTPException(status_code=500, detail="Delete operation failed")
