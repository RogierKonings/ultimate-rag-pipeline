"""Tests for migration progress tracker."""

from uuid import uuid4

import pytest

from services.ingestion.migrations.models import (
    EmbeddingMigration,
    MigrationProgress,
    MigrationStatus,
)
from services.ingestion.migrations.progress_tracker import (
    MigrationProgressStore,
    MigrationProgressStoreConfig,
)


@pytest.mark.asyncio
class TestMigrationProgressStore:
    """Tests for MigrationProgressStore.

    Note: These tests require a running Redis instance.
    Run with: pytest -m "asyncio" --ignore=services/ingestion/migrations/tests/test_progress_tracker.py
    to skip these tests if Redis is not available.
    """

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return MigrationProgressStoreConfig(
            redis_url="redis://localhost:6379",
            key_prefix="test_migration:",
            ttl_seconds=300,  # Short TTL for tests
        )

    @pytest.fixture
    def sample_migration(self):
        """Create a sample migration."""
        return EmbeddingMigration(
            migration_id=uuid4(),
            source_model="model-a",
            target_model="model-b",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="col_v1",
            target_collection="col_v2",
            total_documents=1000,
        )

    @pytest.mark.skip(reason="Requires running Redis instance")
    async def test_save_and_get_migration(self, config, sample_migration):
        """Test saving and retrieving a migration."""
        async with MigrationProgressStore(config=config) as store:
            # Save
            result = await store.save_migration(sample_migration)
            assert result is True

            # Get
            retrieved = await store.get_migration(sample_migration.migration_id)
            assert retrieved is not None
            assert retrieved.migration_id == sample_migration.migration_id
            assert retrieved.source_model == sample_migration.source_model

            # Cleanup
            await store.delete_migration(sample_migration.migration_id)

    @pytest.mark.skip(reason="Requires running Redis instance")
    async def test_get_nonexistent_migration(self, config):
        """Test getting a migration that doesn't exist."""
        async with MigrationProgressStore(config=config) as store:
            result = await store.get_migration(uuid4())
            assert result is None

    @pytest.mark.skip(reason="Requires running Redis instance")
    async def test_delete_migration(self, config, sample_migration):
        """Test deleting a migration."""
        async with MigrationProgressStore(config=config) as store:
            # Save
            await store.save_migration(sample_migration)

            # Delete
            result = await store.delete_migration(sample_migration.migration_id)
            assert result is True

            # Verify deleted
            retrieved = await store.get_migration(sample_migration.migration_id)
            assert retrieved is None

    @pytest.mark.skip(reason="Requires running Redis instance")
    async def test_get_active_migrations(self, config):
        """Test getting active migrations."""
        async with MigrationProgressStore(config=config) as store:
            # Create active migration
            active = EmbeddingMigration(
                migration_id=uuid4(),
                source_model="model-a",
                target_model="model-b",
                source_dimensions=1024,
                target_dimensions=1024,
                source_collection="col_v1",
                target_collection="col_v2",
                status=MigrationStatus.IN_PROGRESS,
            )
            await store.save_migration(active)

            # Create completed migration
            completed = EmbeddingMigration(
                migration_id=uuid4(),
                source_model="model-a",
                target_model="model-b",
                source_dimensions=1024,
                target_dimensions=1024,
                source_collection="col_v3",
                target_collection="col_v4",
                status=MigrationStatus.COMPLETED,
            )
            await store.save_migration(completed)

            # Get active
            actives = await store.get_active_migrations()
            assert len(actives) >= 1
            assert any(m.migration_id == active.migration_id for m in actives)
            assert not any(m.migration_id == completed.migration_id for m in actives)

            # Cleanup
            await store.delete_migration(active.migration_id)
            await store.delete_migration(completed.migration_id)

    @pytest.mark.skip(reason="Requires running Redis instance")
    async def test_update_progress(self, config, sample_migration):
        """Test updating migration progress."""
        async with MigrationProgressStore(config=config) as store:
            # Save initial
            sample_migration.status = MigrationStatus.IN_PROGRESS
            await store.save_migration(sample_migration)

            # Update progress
            updated = await store.update_progress(
                migration_id=sample_migration.migration_id,
                processed_increment=100,
                failed_increment=5,
            )

            assert updated is not None
            assert updated.processed_documents == 100
            assert updated.failed_documents == 5

            # Update again
            updated = await store.update_progress(
                migration_id=sample_migration.migration_id,
                processed_increment=100,
            )

            assert updated.processed_documents == 200
            assert updated.failed_documents == 5

            # Cleanup
            await store.delete_migration(sample_migration.migration_id)

    @pytest.mark.skip(reason="Requires running Redis instance")
    async def test_update_status(self, config, sample_migration):
        """Test updating migration status."""
        async with MigrationProgressStore(config=config) as store:
            # Save initial
            await store.save_migration(sample_migration)

            # Update status
            updated = await store.update_status(
                migration_id=sample_migration.migration_id,
                status=MigrationStatus.IN_PROGRESS,
            )

            assert updated is not None
            assert updated.status == MigrationStatus.IN_PROGRESS
            assert updated.started_at is not None

            # Update to completed
            updated = await store.update_status(
                migration_id=sample_migration.migration_id,
                status=MigrationStatus.COMPLETED,
            )

            assert updated.status == MigrationStatus.COMPLETED
            assert updated.completed_at is not None

            # Cleanup
            await store.delete_migration(sample_migration.migration_id)

    @pytest.mark.skip(reason="Requires running Redis instance")
    async def test_record_batch_progress(self, config, sample_migration):
        """Test recording batch progress."""
        async with MigrationProgressStore(config=config) as store:
            # Save initial
            sample_migration.status = MigrationStatus.IN_PROGRESS
            await store.save_migration(sample_migration)

            # Record batch
            progress = MigrationProgress(
                migration_id=sample_migration.migration_id,
                batch_index=0,
                documents_processed=100,
                documents_failed=2,
                batch_duration_ms=1500.0,
            )
            result = await store.record_batch_progress(progress)
            assert result is True

            # Verify update
            updated = await store.get_migration(sample_migration.migration_id)
            assert updated.processed_documents == 100
            assert updated.failed_documents == 2

            # Cleanup
            await store.delete_migration(sample_migration.migration_id)

    @pytest.mark.skip(reason="Requires running Redis instance")
    async def test_progress_auto_completes_to_validating(self, config):
        """Test that migration auto-transitions to validating when complete."""
        async with MigrationProgressStore(config=config) as store:
            # Create migration with 200 total documents
            migration = EmbeddingMigration(
                migration_id=uuid4(),
                source_model="model-a",
                target_model="model-b",
                source_dimensions=1024,
                target_dimensions=1024,
                source_collection="col_v1",
                target_collection="col_v2",
                status=MigrationStatus.IN_PROGRESS,
                total_documents=200,
            )
            await store.save_migration(migration)

            # Process all documents
            updated = await store.update_progress(
                migration_id=migration.migration_id,
                processed_increment=200,
            )

            # Should auto-transition to validating
            assert updated.status == MigrationStatus.VALIDATING

            # Cleanup
            await store.delete_migration(migration.migration_id)


class TestMigrationProgressStoreUnit:
    """Unit tests that don't require Redis."""

    def test_config_defaults(self):
        """Test default configuration values."""
        config = MigrationProgressStoreConfig()
        assert config.redis_url == "redis://localhost:6379"
        assert config.key_prefix == "migration:"
        assert config.ttl_seconds == 86400 * 30

    def test_store_initialization(self):
        """Test store initialization."""
        config = MigrationProgressStoreConfig(key_prefix="custom:")
        store = MigrationProgressStore(config=config)
        assert store.config.key_prefix == "custom:"
        assert store._client is None

    def test_migration_key_format(self):
        """Test migration key generation."""
        store = MigrationProgressStore()
        migration_id = uuid4()
        key = store._migration_key(migration_id)
        assert key == f"migration:{migration_id}"

    def test_active_migrations_key_format(self):
        """Test active migrations key."""
        store = MigrationProgressStore()
        key = store._active_migrations_key()
        assert key == "migration:active"
