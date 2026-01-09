"""Migration progress tracking with Redis persistence.

Stores and retrieves migration state using Redis for reliability across
worker restarts and distributed processing.
"""

import json
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

import redis.asyncio as redis
from pydantic import BaseModel

from .models import EmbeddingMigration, MigrationStatus, MigrationProgress

logger = logging.getLogger(__name__)


class MigrationProgressStoreConfig(BaseModel):
    """Configuration for the migration progress store."""

    redis_url: str = "redis://localhost:6379"
    key_prefix: str = "migration:"
    ttl_seconds: int = 86400 * 30  # 30 days


class MigrationProgressStore:
    """Store and track migration progress in Redis.

    Provides atomic updates for progress tracking across distributed
    Celery workers processing migration batches.
    """

    def __init__(self, config: Optional[MigrationProgressStoreConfig] = None):
        """Initialize the progress store.

        Args:
            config: Store configuration. Uses defaults if not provided.
        """
        self.config = config or MigrationProgressStoreConfig()
        self._client: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Connect to Redis."""
        self._client = redis.from_url(self.config.redis_url, decode_responses=True)

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._client:
            await self._client.close()
            self._client = None

    async def __aenter__(self) -> "MigrationProgressStore":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()

    def _migration_key(self, migration_id: UUID) -> str:
        """Get Redis key for a migration."""
        return f"{self.config.key_prefix}{migration_id}"

    def _active_migrations_key(self) -> str:
        """Get Redis key for active migrations set."""
        return f"{self.config.key_prefix}active"

    def _tenant_migrations_key(self, tenant_id: str) -> str:
        """Get Redis key for tenant migrations list."""
        return f"{self.config.key_prefix}tenant:{tenant_id}"

    async def save_migration(self, migration: EmbeddingMigration) -> bool:
        """Save or update a migration record.

        Args:
            migration: Migration record to save.

        Returns:
            True if save was successful.
        """
        if not self._client:
            raise RuntimeError("Not connected to Redis")

        try:
            key = self._migration_key(migration.migration_id)
            data = migration.model_dump_json()

            # Use pipeline for atomic operations
            pipe = self._client.pipeline()

            # Save migration data
            pipe.set(key, data, ex=self.config.ttl_seconds)

            # Track in active migrations if applicable
            if migration.is_active:
                pipe.sadd(self._active_migrations_key(), str(migration.migration_id))
            else:
                pipe.srem(self._active_migrations_key(), str(migration.migration_id))

            await pipe.execute()

            logger.debug(
                f"Saved migration {migration.migration_id} "
                f"(status={migration.status}, progress={migration.progress_percentage}%)"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to save migration {migration.migration_id}: {e}")
            return False

    async def get_migration(self, migration_id: UUID) -> Optional[EmbeddingMigration]:
        """Get a migration record by ID.

        Args:
            migration_id: UUID of the migration.

        Returns:
            Migration record if found, None otherwise.
        """
        if not self._client:
            raise RuntimeError("Not connected to Redis")

        try:
            key = self._migration_key(migration_id)
            data = await self._client.get(key)

            if data:
                return EmbeddingMigration.model_validate_json(data)
            return None

        except Exception as e:
            logger.error(f"Failed to get migration {migration_id}: {e}")
            return None

    async def delete_migration(self, migration_id: UUID) -> bool:
        """Delete a migration record.

        Args:
            migration_id: UUID of the migration to delete.

        Returns:
            True if deletion was successful.
        """
        if not self._client:
            raise RuntimeError("Not connected to Redis")

        try:
            key = self._migration_key(migration_id)

            pipe = self._client.pipeline()
            pipe.delete(key)
            pipe.srem(self._active_migrations_key(), str(migration_id))
            await pipe.execute()

            return True

        except Exception as e:
            logger.error(f"Failed to delete migration {migration_id}: {e}")
            return False

    async def get_active_migrations(self) -> list[EmbeddingMigration]:
        """Get all active migrations.

        Returns:
            List of active migration records.
        """
        if not self._client:
            raise RuntimeError("Not connected to Redis")

        try:
            active_ids = await self._client.smembers(self._active_migrations_key())
            migrations = []

            for migration_id in active_ids:
                migration = await self.get_migration(UUID(migration_id))
                if migration:
                    migrations.append(migration)

            return migrations

        except Exception as e:
            logger.error(f"Failed to get active migrations: {e}")
            return []

    async def update_progress(
        self,
        migration_id: UUID,
        processed_increment: int = 0,
        failed_increment: int = 0,
    ) -> Optional[EmbeddingMigration]:
        """Atomically update migration progress.

        Uses Redis WATCH for optimistic locking to ensure atomic updates
        across distributed workers.

        Args:
            migration_id: UUID of the migration.
            processed_increment: Number of documents processed to add.
            failed_increment: Number of failed documents to add.

        Returns:
            Updated migration record, or None if update failed.
        """
        if not self._client:
            raise RuntimeError("Not connected to Redis")

        key = self._migration_key(migration_id)

        # Use optimistic locking with WATCH
        try:
            async with self._client.pipeline(transaction=True) as pipe:
                while True:
                    try:
                        await pipe.watch(key)

                        # Get current state
                        data = await pipe.get(key)
                        if not data:
                            await pipe.unwatch()
                            return None

                        migration = EmbeddingMigration.model_validate_json(data)

                        # Update progress
                        migration.processed_documents += processed_increment
                        migration.failed_documents += failed_increment

                        # Check if complete
                        if (
                            migration.processed_documents + migration.failed_documents
                            >= migration.total_documents
                        ):
                            if migration.status == MigrationStatus.IN_PROGRESS:
                                migration.status = MigrationStatus.VALIDATING

                        # Start transaction
                        pipe.multi()
                        pipe.set(key, migration.model_dump_json(), ex=self.config.ttl_seconds)
                        await pipe.execute()

                        return migration

                    except redis.WatchError:
                        # Retry on concurrent modification
                        continue

        except Exception as e:
            logger.error(f"Failed to update progress for {migration_id}: {e}")
            return None

    async def update_status(
        self,
        migration_id: UUID,
        status: MigrationStatus,
        error: Optional[str] = None,
    ) -> Optional[EmbeddingMigration]:
        """Update migration status.

        Args:
            migration_id: UUID of the migration.
            status: New status.
            error: Optional error message.

        Returns:
            Updated migration record, or None if update failed.
        """
        if not self._client:
            raise RuntimeError("Not connected to Redis")

        migration = await self.get_migration(migration_id)
        if not migration:
            return None

        migration.status = status
        if error:
            migration.last_error = error

        # Set timestamps based on status
        now = datetime.utcnow()
        if status == MigrationStatus.IN_PROGRESS and not migration.started_at:
            migration.started_at = now
        elif status in (
            MigrationStatus.COMPLETED,
            MigrationStatus.FAILED,
            MigrationStatus.ROLLED_BACK,
        ):
            migration.completed_at = now

        await self.save_migration(migration)
        return migration

    async def record_batch_progress(self, progress: MigrationProgress) -> bool:
        """Record progress from a completed batch.

        Args:
            progress: Batch progress update.

        Returns:
            True if progress was recorded successfully.
        """
        migration = await self.update_progress(
            migration_id=progress.migration_id,
            processed_increment=progress.documents_processed,
            failed_increment=progress.documents_failed,
        )
        return migration is not None

    async def get_all_migrations(
        self,
        limit: int = 100,
        status_filter: Optional[MigrationStatus] = None,
    ) -> list[EmbeddingMigration]:
        """Get all migrations with optional filtering.

        Note: This scans all migration keys, which may be slow with many migrations.
        Consider adding a sorted set index for production use.

        Args:
            limit: Maximum number of migrations to return.
            status_filter: Optional status to filter by.

        Returns:
            List of migration records.
        """
        if not self._client:
            raise RuntimeError("Not connected to Redis")

        try:
            pattern = f"{self.config.key_prefix}????????-????-????-????-????????????"
            migrations = []

            async for key in self._client.scan_iter(match=pattern, count=100):
                if len(migrations) >= limit:
                    break

                data = await self._client.get(key)
                if data:
                    migration = EmbeddingMigration.model_validate_json(data)
                    if status_filter is None or migration.status == status_filter:
                        migrations.append(migration)

            # Sort by created_at descending
            migrations.sort(key=lambda m: m.created_at, reverse=True)
            return migrations[:limit]

        except Exception as e:
            logger.error(f"Failed to get all migrations: {e}")
            return []
