"""Tests for embedding migrator orchestrator."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from migrations.embedding_migrator import EmbeddingMigrator
from migrations.models import (
    EmbeddingMigration,
    MigrationRequest,
    MigrationStatus,
    ValidationConfig,
    ValidationResult,
)


@pytest.mark.asyncio
class TestEmbeddingMigrator:
    """Tests for EmbeddingMigrator."""

    async def test_start_migration_no_alias(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test starting migration when no alias exists."""
        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        request = MigrationRequest(target_model="BAAI/bge-m3")

        with pytest.raises(ValueError, match="No collection found for alias"):
            await migrator.start_migration(request)

    async def test_start_migration_success(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test successful migration start."""
        # Setup alias to return existing collection
        alias = MagicMock()
        alias.alias_name = "rag_chunks"
        alias.collection_name = "rag_chunks_v1"
        aliases_response = MagicMock()
        aliases_response.aliases = [alias]
        mock_qdrant_client.get_aliases.return_value = aliases_response

        # Mock scroll to return some document IDs
        point = MagicMock()
        point.id = str(uuid4())
        mock_qdrant_client.scroll.return_value = ([point], None)

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        request = MigrationRequest(
            target_model="BAAI/bge-m3",
            batch_size=100,
        )

        # Mock the task dispatch
        with patch(
            "migrations.embedding_migrator.EmbeddingMigrator._dispatch_reembedding_tasks"
        ) as mock_dispatch:
            mock_dispatch.return_value = None

            migration = await migrator.start_migration(
                request,
                current_model="BAAI/bge-large-en-v1.5",
                current_dimensions=1024,
            )

            assert migration is not None
            assert migration.source_model == "BAAI/bge-large-en-v1.5"
            assert migration.target_model == "BAAI/bge-m3"
            assert migration.source_collection == "rag_chunks_v1"
            assert "rag_chunks_v" in migration.target_collection
            # Default validation config should be stored
            assert migration.validation_config is not None
            assert migration.validation_config["sample_size"] == 100
            assert migration.validation_config["recall_threshold"] == 0.95
            assert migration.validation_config["latency_threshold_ms"] == 100

    async def test_start_migration_with_custom_validation_config(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test migration start with custom validation config."""
        # Setup alias to return existing collection
        alias = MagicMock()
        alias.alias_name = "rag_chunks"
        alias.collection_name = "rag_chunks_v1"
        aliases_response = MagicMock()
        aliases_response.aliases = [alias]
        mock_qdrant_client.get_aliases.return_value = aliases_response

        # Mock scroll to return some document IDs
        point = MagicMock()
        point.id = str(uuid4())
        mock_qdrant_client.scroll.return_value = ([point], None)

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        # Custom validation config
        custom_validation_config = {
            "sample_size": 200,
            "recall_threshold": 0.90,
            "latency_threshold_ms": 150,
        }

        request = MigrationRequest(
            target_model="BAAI/bge-m3",
            batch_size=100,
            validation_config=custom_validation_config,
        )

        # Mock the task dispatch
        with patch(
            "migrations.embedding_migrator.EmbeddingMigrator._dispatch_reembedding_tasks"
        ) as mock_dispatch:
            mock_dispatch.return_value = None

            migration = await migrator.start_migration(
                request,
                current_model="BAAI/bge-large-en-v1.5",
                current_dimensions=1024,
            )

            assert migration is not None
            # Custom validation config should be stored
            assert migration.validation_config is not None
            assert migration.validation_config["sample_size"] == 200
            assert migration.validation_config["recall_threshold"] == 0.90
            assert migration.validation_config["latency_threshold_ms"] == 150

    async def test_get_migration_status(self, mock_qdrant_client, mock_progress_store):
        """Test getting migration status."""
        migration_id = uuid4()
        expected_migration = EmbeddingMigration(
            migration_id=migration_id,
            source_model="model-a",
            target_model="model-b",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="col_v1",
            target_collection="col_v2",
            status=MigrationStatus.IN_PROGRESS,
            total_documents=1000,
            processed_documents=500,
        )
        mock_progress_store.get_migration.return_value = expected_migration

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        result = await migrator.get_migration_status(migration_id)

        assert result is not None
        assert result.migration_id == migration_id
        assert result.status == MigrationStatus.IN_PROGRESS
        assert result.progress_percentage == 50.0

    async def test_validate_migration_not_found(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test validation when migration not found."""
        mock_progress_store.get_migration.return_value = None

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        with pytest.raises(ValueError, match="not found"):
            await migrator.validate_migration(uuid4())

    async def test_validate_migration_wrong_status(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test validation when migration in wrong status."""
        migration = EmbeddingMigration(
            migration_id=uuid4(),
            source_model="model-a",
            target_model="model-b",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="col_v1",
            target_collection="col_v2",
            status=MigrationStatus.COMPLETED,  # Wrong status
        )
        mock_progress_store.get_migration.return_value = migration

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        with pytest.raises(ValueError, match="not ready for validation"):
            await migrator.validate_migration(migration.migration_id)

    async def test_validate_migration_uses_stored_config(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test validation uses stored validation config from migration."""
        # Create migration with custom validation config
        custom_config = {
            "sample_size": 50,
            "recall_threshold": 0.80,
            "latency_threshold_ms": 200,
        }
        migration = EmbeddingMigration(
            migration_id=uuid4(),
            source_model="model-a",
            target_model="model-b",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="col_v1",
            target_collection="col_v2",
            status=MigrationStatus.IN_PROGRESS,
            validation_config=custom_config,
        )
        mock_progress_store.get_migration.return_value = migration

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        # Mock the internal methods to return controlled results
        with patch.object(
            migrator, "_get_sample_queries", new_callable=AsyncMock
        ) as mock_queries, patch.object(
            migrator, "_search_collection", new_callable=AsyncMock
        ) as mock_search:
            # Return test queries
            mock_queries.return_value = ["query1", "query2"]
            # Return matching results (100% overlap)
            mock_search.return_value = [{"id": "1", "score": 0.9}]

            result = await migrator.validate_migration(migration.migration_id)

            # Should have called _get_sample_queries with stored config sample_size
            mock_queries.assert_called_once_with(50)
            # Result should use stored recall_threshold (0.80)
            assert result.overlap_threshold == 0.80

    async def test_validate_migration_overrides_stored_config(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test validation can override stored config with explicit params."""
        # Create migration with custom validation config
        stored_config = {
            "sample_size": 50,
            "recall_threshold": 0.80,
            "latency_threshold_ms": 200,
        }
        migration = EmbeddingMigration(
            migration_id=uuid4(),
            source_model="model-a",
            target_model="model-b",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="col_v1",
            target_collection="col_v2",
            status=MigrationStatus.IN_PROGRESS,
            validation_config=stored_config,
        )
        mock_progress_store.get_migration.return_value = migration

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        # Mock the internal methods
        with patch.object(
            migrator, "_get_sample_queries", new_callable=AsyncMock
        ) as mock_queries, patch.object(
            migrator, "_search_collection", new_callable=AsyncMock
        ) as mock_search:
            mock_queries.return_value = ["query1"]
            mock_search.return_value = [{"id": "1", "score": 0.9}]

            # Override with explicit params
            result = await migrator.validate_migration(
                migration.migration_id,
                sample_size=200,  # Override stored 50
                overlap_threshold=0.95,  # Override stored 0.80
            )

            # Should have called _get_sample_queries with overridden sample_size
            mock_queries.assert_called_once_with(200)
            # Result should use overridden threshold
            assert result.overlap_threshold == 0.95

    async def test_validate_migration_uses_defaults_without_config(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test validation uses defaults when no config stored."""
        # Create migration without validation config
        migration = EmbeddingMigration(
            migration_id=uuid4(),
            source_model="model-a",
            target_model="model-b",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="col_v1",
            target_collection="col_v2",
            status=MigrationStatus.IN_PROGRESS,
            validation_config=None,  # No config stored
        )
        mock_progress_store.get_migration.return_value = migration

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        # Mock the internal methods
        with patch.object(
            migrator, "_get_sample_queries", new_callable=AsyncMock
        ) as mock_queries, patch.object(
            migrator, "_search_collection", new_callable=AsyncMock
        ) as mock_search:
            mock_queries.return_value = ["query1"]
            mock_search.return_value = [{"id": "1", "score": 0.9}]

            result = await migrator.validate_migration(migration.migration_id)

            # Should use default sample_size (100)
            mock_queries.assert_called_once_with(100)
            # Should use default recall_threshold (0.95)
            assert result.overlap_threshold == 0.95

    async def test_switch_to_new_collection_success(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test successful collection switch."""
        migration = EmbeddingMigration(
            migration_id=uuid4(),
            source_model="model-a",
            target_model="model-b",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="col_v1",
            target_collection="col_v2",
            validation_passed=True,
        )
        mock_progress_store.get_migration.return_value = migration

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        # Patch the switch_alias method to avoid Pydantic validation issues
        with patch.object(
            migrator.collections, "switch_alias", new_callable=AsyncMock
        ) as mock_switch:
            mock_switch.return_value = True

            result = await migrator.switch_to_new_collection(migration.migration_id)

            assert result is True
            mock_switch.assert_called_once()

    async def test_switch_without_validation_requires_force(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test switch fails without validation unless forced."""
        migration = EmbeddingMigration(
            migration_id=uuid4(),
            source_model="model-a",
            target_model="model-b",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="col_v1",
            target_collection="col_v2",
            validation_passed=False,  # Not validated
        )
        mock_progress_store.get_migration.return_value = migration

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        with pytest.raises(ValueError, match="validation not passed"):
            await migrator.switch_to_new_collection(migration.migration_id)

    async def test_switch_with_force(self, mock_qdrant_client, mock_progress_store):
        """Test switch with force flag."""
        migration = EmbeddingMigration(
            migration_id=uuid4(),
            source_model="model-a",
            target_model="model-b",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="col_v1",
            target_collection="col_v2",
            validation_passed=False,
        )
        mock_progress_store.get_migration.return_value = migration

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        # Patch the switch_alias method to avoid Pydantic validation issues
        with patch.object(
            migrator.collections, "switch_alias", new_callable=AsyncMock
        ) as mock_switch:
            mock_switch.return_value = True

            result = await migrator.switch_to_new_collection(
                migration.migration_id, force=True
            )

            assert result is True

    async def test_rollback_migration_success(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test successful rollback."""
        migration = EmbeddingMigration(
            migration_id=uuid4(),
            source_model="model-a",
            target_model="model-b",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="col_v1",
            target_collection="col_v2",
            status=MigrationStatus.COMPLETED,
            rollback_enabled=True,
        )
        mock_progress_store.get_migration.return_value = migration

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        # Patch the switch_alias method to avoid Pydantic validation issues
        with patch.object(
            migrator.collections, "switch_alias", new_callable=AsyncMock
        ) as mock_switch:
            mock_switch.return_value = True

            result = await migrator.rollback_migration(migration.migration_id)

            assert result is True
            # Verify alias was switched back
            mock_switch.assert_called_once()
            # Verify target collection was deleted
            mock_qdrant_client.delete_collection.assert_called_with("col_v2")

    async def test_rollback_not_possible(self, mock_qdrant_client, mock_progress_store):
        """Test rollback when not possible."""
        migration = EmbeddingMigration(
            migration_id=uuid4(),
            source_model="model-a",
            target_model="model-b",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="col_v1",
            target_collection="col_v2",
            status=MigrationStatus.IN_PROGRESS,  # Can't rollback in progress
            rollback_enabled=True,
        )
        mock_progress_store.get_migration.return_value = migration

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        with pytest.raises(ValueError, match="cannot be rolled back"):
            await migrator.rollback_migration(migration.migration_id)

    async def test_cancel_migration_success(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test cancelling an active migration."""
        migration = EmbeddingMigration(
            migration_id=uuid4(),
            source_model="model-a",
            target_model="model-b",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="col_v1",
            target_collection="col_v2",
            status=MigrationStatus.IN_PROGRESS,
        )
        mock_progress_store.get_migration.return_value = migration

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        result = await migrator.cancel_migration(migration.migration_id)

        assert result is True
        mock_qdrant_client.delete_collection.assert_called_with("col_v2")

    async def test_cancel_completed_migration_fails(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test cancelling a completed migration fails."""
        migration = EmbeddingMigration(
            migration_id=uuid4(),
            source_model="model-a",
            target_model="model-b",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="col_v1",
            target_collection="col_v2",
            status=MigrationStatus.COMPLETED,
        )
        mock_progress_store.get_migration.return_value = migration

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        with pytest.raises(ValueError, match="is not active"):
            await migrator.cancel_migration(migration.migration_id)

    async def test_cleanup_old_collection_success(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test cleaning up old collection after migration."""
        migration = EmbeddingMigration(
            migration_id=uuid4(),
            source_model="model-a",
            target_model="model-b",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="col_v1",
            target_collection="col_v2",
            status=MigrationStatus.COMPLETED,
            rollback_enabled=True,
        )
        mock_progress_store.get_migration.return_value = migration

        # Setup alias pointing to target
        alias = MagicMock()
        alias.alias_name = "rag_chunks"
        alias.collection_name = "col_v2"
        aliases_response = MagicMock()
        aliases_response.aliases = [alias]
        mock_qdrant_client.get_aliases.return_value = aliases_response

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        result = await migrator.cleanup_old_collection(migration.migration_id)

        assert result is True
        mock_qdrant_client.delete_collection.assert_called_with("col_v1")

    async def test_cleanup_not_completed(self, mock_qdrant_client, mock_progress_store):
        """Test cleanup fails when migration not completed."""
        migration = EmbeddingMigration(
            migration_id=uuid4(),
            source_model="model-a",
            target_model="model-b",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="col_v1",
            target_collection="col_v2",
            status=MigrationStatus.IN_PROGRESS,
        )
        mock_progress_store.get_migration.return_value = migration

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        with pytest.raises(ValueError, match="not completed"):
            await migrator.cleanup_old_collection(migration.migration_id)


@pytest.mark.asyncio
class TestRollbackScenarios:
    """Comprehensive tests for rollback functionality in various failure scenarios."""

    async def test_rollback_after_partial_migration_completes_successfully(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test rollback correctly restores state after partial migration.

        Scenario: Migration was started and 50% of documents were processed,
        then user decides to rollback.
        """
        migration_id = uuid4()
        migration = EmbeddingMigration(
            migration_id=migration_id,
            source_model="BAAI/bge-large-en-v1.5",
            target_model="BAAI/bge-m3",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="rag_chunks_v1",
            target_collection="rag_chunks_v2",
            alias_name="rag_chunks",
            status=MigrationStatus.FAILED,  # Failed mid-migration
            rollback_enabled=True,
            total_documents=100,
            processed_documents=50,  # Only 50% processed
            failed_documents=0,
            last_error="Migration interrupted",
        )
        mock_progress_store.get_migration.return_value = migration

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        # Patch the switch_alias method to avoid Pydantic validation issues with qdrant models
        with patch.object(
            migrator.collections, "switch_alias", new_callable=AsyncMock
        ) as mock_switch:
            mock_switch.return_value = True

            result = await migrator.rollback_migration(migration_id)

            assert result is True
            # Verify switch_alias was called with correct args (rollback to source)
            mock_switch.assert_called_once_with(
                alias_name="rag_chunks",
                new_collection="rag_chunks_v1",
                old_collection="rag_chunks_v2",
            )
            # Verify migration status was updated to ROLLED_BACK
            saved_migration = mock_progress_store.save_migration.call_args[0][0]
            assert saved_migration.status == MigrationStatus.ROLLED_BACK
            # Verify target collection was deleted
            mock_qdrant_client.delete_collection.assert_called_with("rag_chunks_v2")

    async def test_rollback_after_validation_failure(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test rollback when validation detects quality regression.

        Scenario: Migration completed re-embedding but validation showed
        quality regression, so rollback is triggered.
        """
        migration_id = uuid4()
        migration = EmbeddingMigration(
            migration_id=migration_id,
            source_model="BAAI/bge-large-en-v1.5",
            target_model="BAAI/bge-m3",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="rag_chunks_v1",
            target_collection="rag_chunks_v2",
            alias_name="rag_chunks",
            status=MigrationStatus.VALIDATING,  # In validation phase
            rollback_enabled=True,
            total_documents=100,
            processed_documents=100,  # All processed
            validation_score=0.55,  # Below threshold
            validation_passed=False,
        )
        mock_progress_store.get_migration.return_value = migration

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        # Patch the switch_alias method to avoid Pydantic validation issues
        with patch.object(
            migrator.collections, "switch_alias", new_callable=AsyncMock
        ) as mock_switch:
            mock_switch.return_value = True

            result = await migrator.rollback_migration(migration_id)

            assert result is True
            # Verify status updated
            saved_migration = mock_progress_store.save_migration.call_args[0][0]
            assert saved_migration.status == MigrationStatus.ROLLED_BACK
            # Verify cleanup happened
            mock_qdrant_client.delete_collection.assert_called_with("rag_chunks_v2")

    async def test_rollback_preserves_original_collection_untouched(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test that rollback preserves original collection data.

        Scenario: Verify that during rollback, only the target collection
        is deleted and the source collection remains intact.
        """
        migration_id = uuid4()
        migration = EmbeddingMigration(
            migration_id=migration_id,
            source_model="BAAI/bge-large-en-v1.5",
            target_model="BAAI/bge-m3",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="rag_chunks_v1",
            target_collection="rag_chunks_v2",
            alias_name="rag_chunks",
            status=MigrationStatus.COMPLETED,
            rollback_enabled=True,
            total_documents=1000,
            processed_documents=1000,
        )
        mock_progress_store.get_migration.return_value = migration

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        # Patch the switch_alias method to avoid Pydantic validation issues
        with patch.object(
            migrator.collections, "switch_alias", new_callable=AsyncMock
        ) as mock_switch:
            mock_switch.return_value = True

            result = await migrator.rollback_migration(migration_id)

            assert result is True
            # Verify only target collection was deleted, not source
            mock_qdrant_client.delete_collection.assert_called_once_with("rag_chunks_v2")
            # Source collection should NOT be deleted
            delete_calls = mock_qdrant_client.delete_collection.call_args_list
            assert len(delete_calls) == 1
            assert delete_calls[0][0][0] == "rag_chunks_v2"

    async def test_rollback_alias_switches_back_to_source(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test that alias correctly switches back during rollback.

        Scenario: After a completed migration where alias was switched to
        the new collection, rollback should restore alias to source.
        """
        migration_id = uuid4()
        migration = EmbeddingMigration(
            migration_id=migration_id,
            source_model="BAAI/bge-large-en-v1.5",
            target_model="BAAI/bge-m3",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="rag_chunks_v1",
            target_collection="rag_chunks_v2",
            alias_name="rag_chunks",
            status=MigrationStatus.COMPLETED,
            rollback_enabled=True,
        )
        mock_progress_store.get_migration.return_value = migration

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        # Patch the switch_alias method to capture the call and verify args
        with patch.object(
            migrator.collections, "switch_alias", new_callable=AsyncMock
        ) as mock_switch:
            mock_switch.return_value = True

            result = await migrator.rollback_migration(migration_id)

            assert result is True
            # Verify switch_alias was called with correct arguments
            # Rollback should switch alias from target back to source
            mock_switch.assert_called_once_with(
                alias_name="rag_chunks",
                new_collection="rag_chunks_v1",  # Back to source
                old_collection="rag_chunks_v2",  # From target
            )

    async def test_rollback_is_idempotent(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test that calling rollback multiple times is safe.

        Scenario: After first rollback succeeds, calling rollback again
        should not cause errors or duplicate operations.
        """
        from datetime import timezone

        migration_id = uuid4()

        # First call - migration in COMPLETED state
        migration_completed = EmbeddingMigration(
            migration_id=migration_id,
            source_model="BAAI/bge-large-en-v1.5",
            target_model="BAAI/bge-m3",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="rag_chunks_v1",
            target_collection="rag_chunks_v2",
            alias_name="rag_chunks",
            status=MigrationStatus.COMPLETED,
            rollback_enabled=True,
        )

        # Second call - migration already in ROLLED_BACK state
        migration_rolled_back = EmbeddingMigration(
            migration_id=migration_id,
            source_model="BAAI/bge-large-en-v1.5",
            target_model="BAAI/bge-m3",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="rag_chunks_v1",
            target_collection="rag_chunks_v2",
            alias_name="rag_chunks",
            status=MigrationStatus.ROLLED_BACK,
            rollback_enabled=True,
            completed_at=datetime.now(timezone.utc),
        )

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        # Patch the switch_alias method
        with patch.object(
            migrator.collections, "switch_alias", new_callable=AsyncMock
        ) as mock_switch:
            mock_switch.return_value = True

            # First rollback
            mock_progress_store.get_migration.return_value = migration_completed
            result1 = await migrator.rollback_migration(migration_id)
            assert result1 is True

        # Second rollback - should fail since status is ROLLED_BACK (not in can_rollback)
        mock_progress_store.get_migration.return_value = migration_rolled_back
        with pytest.raises(ValueError, match="cannot be rolled back"):
            await migrator.rollback_migration(migration_id)

    async def test_rollback_when_rollback_disabled(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test that rollback fails when explicitly disabled.

        Scenario: Migration was started with preserve_source=False,
        meaning source collection was deleted after switch.
        """
        migration_id = uuid4()
        migration = EmbeddingMigration(
            migration_id=migration_id,
            source_model="BAAI/bge-large-en-v1.5",
            target_model="BAAI/bge-m3",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="rag_chunks_v1",
            target_collection="rag_chunks_v2",
            alias_name="rag_chunks",
            status=MigrationStatus.COMPLETED,
            rollback_enabled=False,  # Disabled
        )
        mock_progress_store.get_migration.return_value = migration

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        with pytest.raises(ValueError, match="cannot be rolled back"):
            await migrator.rollback_migration(migration_id)

    async def test_rollback_handles_alias_switch_failure(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test rollback behavior when alias switch fails.

        Scenario: During rollback, the alias switch operation fails
        (e.g., Qdrant is unavailable).
        """
        migration_id = uuid4()
        migration = EmbeddingMigration(
            migration_id=migration_id,
            source_model="BAAI/bge-large-en-v1.5",
            target_model="BAAI/bge-m3",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="rag_chunks_v1",
            target_collection="rag_chunks_v2",
            alias_name="rag_chunks",
            status=MigrationStatus.COMPLETED,
            rollback_enabled=True,
        )
        mock_progress_store.get_migration.return_value = migration

        # Setup alias pointing to target
        alias = MagicMock()
        alias.alias_name = "rag_chunks"
        alias.collection_name = "rag_chunks_v2"
        aliases_response = MagicMock()
        aliases_response.aliases = [alias]
        mock_qdrant_client.get_aliases.return_value = aliases_response

        # Make alias update fail
        mock_qdrant_client.update_collection_aliases.side_effect = Exception(
            "Qdrant unavailable"
        )

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        result = await migrator.rollback_migration(migration_id)

        assert result is False
        # Verify error was recorded
        saved_migration = mock_progress_store.save_migration.call_args[0][0]
        assert saved_migration.last_error == "Failed to rollback alias"

    async def test_rollback_migration_not_found(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test rollback fails gracefully when migration not found."""
        mock_progress_store.get_migration.return_value = None

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        with pytest.raises(ValueError, match="not found"):
            await migrator.rollback_migration(uuid4())

    async def test_rollback_from_failed_status(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test rollback works from FAILED status.

        Scenario: Migration failed during re-embedding, rollback should
        clean up the partially-filled target collection.
        """
        migration_id = uuid4()
        migration = EmbeddingMigration(
            migration_id=migration_id,
            source_model="BAAI/bge-large-en-v1.5",
            target_model="BAAI/bge-m3",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="rag_chunks_v1",
            target_collection="rag_chunks_v2",
            alias_name="rag_chunks",
            status=MigrationStatus.FAILED,
            rollback_enabled=True,
            total_documents=1000,
            processed_documents=250,
            failed_documents=50,
            last_error="Embedding service unavailable",
        )
        mock_progress_store.get_migration.return_value = migration

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        # Patch the switch_alias method
        with patch.object(
            migrator.collections, "switch_alias", new_callable=AsyncMock
        ) as mock_switch:
            mock_switch.return_value = True

            result = await migrator.rollback_migration(migration_id)

            assert result is True
            # Verify cleanup
            saved_migration = mock_progress_store.save_migration.call_args[0][0]
            assert saved_migration.status == MigrationStatus.ROLLED_BACK
            mock_qdrant_client.delete_collection.assert_called_with("rag_chunks_v2")

    async def test_concurrent_rollback_requests(
        self, mock_qdrant_client, mock_progress_store
    ):
        """Test behavior when concurrent rollback requests are made.

        Scenario: Multiple rollback requests come in simultaneously.
        Only the first should succeed, subsequent ones should fail
        gracefully due to status check.
        """
        migration_id = uuid4()

        # Track how many times migration is fetched and status changes
        call_count = 0

        async def get_migration_side_effect(mid):
            nonlocal call_count
            call_count += 1
            # First call returns COMPLETED, subsequent return ROLLED_BACK
            if call_count == 1:
                return EmbeddingMigration(
                    migration_id=migration_id,
                    source_model="BAAI/bge-large-en-v1.5",
                    target_model="BAAI/bge-m3",
                    source_dimensions=1024,
                    target_dimensions=1024,
                    source_collection="rag_chunks_v1",
                    target_collection="rag_chunks_v2",
                    alias_name="rag_chunks",
                    status=MigrationStatus.COMPLETED,
                    rollback_enabled=True,
                )
            else:
                return EmbeddingMigration(
                    migration_id=migration_id,
                    source_model="BAAI/bge-large-en-v1.5",
                    target_model="BAAI/bge-m3",
                    source_dimensions=1024,
                    target_dimensions=1024,
                    source_collection="rag_chunks_v1",
                    target_collection="rag_chunks_v2",
                    alias_name="rag_chunks",
                    status=MigrationStatus.ROLLED_BACK,
                    rollback_enabled=True,
                )

        mock_progress_store.get_migration.side_effect = get_migration_side_effect

        migrator = EmbeddingMigrator(
            qdrant_client=mock_qdrant_client,
            progress_store=mock_progress_store,
        )

        # Patch the switch_alias method
        with patch.object(
            migrator.collections, "switch_alias", new_callable=AsyncMock
        ) as mock_switch:
            mock_switch.return_value = True

            # First rollback succeeds
            result1 = await migrator.rollback_migration(migration_id)
            assert result1 is True

        # Second rollback fails due to status
        with pytest.raises(ValueError, match="cannot be rolled back"):
            await migrator.rollback_migration(migration_id)


class TestEmbeddingMigratorHelpers:
    """Tests for helper methods."""

    def test_model_dimensions_mapping(self):
        """Test model dimensions lookup."""
        # Known models should return correct dimensions
        migrator = EmbeddingMigrator.__new__(EmbeddingMigrator)

        import asyncio

        dims = asyncio.run(migrator._get_model_dimensions("BAAI/bge-large-en-v1.5"))
        assert dims == 1024

        dims = asyncio.run(migrator._get_model_dimensions("BAAI/bge-base-en-v1.5"))
        assert dims == 768

        dims = asyncio.run(migrator._get_model_dimensions("text-embedding-3-large"))
        assert dims == 3072

        # Unknown model should return default
        dims = asyncio.run(migrator._get_model_dimensions("unknown-model"))
        assert dims == 1024
