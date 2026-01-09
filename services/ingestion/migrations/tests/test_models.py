"""Tests for migration data models."""

from datetime import datetime
from uuid import uuid4

import pytest

from services.ingestion.migrations.models import (
    EmbeddingMigration,
    MigrationProgress,
    MigrationRequest,
    MigrationStatus,
    ValidationConfig,
    ValidationResult,
)


class TestValidationConfig:
    """Tests for ValidationConfig dataclass."""

    def test_default_values(self):
        """Test default values match architecture specification."""
        config = ValidationConfig()
        assert config.sample_size == 100
        assert config.recall_threshold == 0.95
        assert config.latency_threshold_ms == 100

    def test_custom_values(self):
        """Test custom configuration values."""
        config = ValidationConfig(
            sample_size=200,
            recall_threshold=0.90,
            latency_threshold_ms=150,
        )
        assert config.sample_size == 200
        assert config.recall_threshold == 0.90
        assert config.latency_threshold_ms == 150

    def test_to_dict(self):
        """Test converting config to dictionary."""
        config = ValidationConfig(
            sample_size=50,
            recall_threshold=0.85,
            latency_threshold_ms=200,
        )
        config_dict = config.to_dict()
        assert config_dict == {
            "sample_size": 50,
            "recall_threshold": 0.85,
            "latency_threshold_ms": 200,
        }

    def test_from_dict(self):
        """Test creating config from dictionary."""
        data = {
            "sample_size": 150,
            "recall_threshold": 0.80,
            "latency_threshold_ms": 250,
        }
        config = ValidationConfig.from_dict(data)
        assert config.sample_size == 150
        assert config.recall_threshold == 0.80
        assert config.latency_threshold_ms == 250

    def test_from_dict_none(self):
        """Test creating config from None returns defaults."""
        config = ValidationConfig.from_dict(None)
        assert config.sample_size == 100
        assert config.recall_threshold == 0.95
        assert config.latency_threshold_ms == 100

    def test_from_dict_partial(self):
        """Test creating config from partial dictionary uses defaults."""
        data = {"sample_size": 200}
        config = ValidationConfig.from_dict(data)
        assert config.sample_size == 200
        assert config.recall_threshold == 0.95  # default
        assert config.latency_threshold_ms == 100  # default

    def test_from_dict_empty(self):
        """Test creating config from empty dictionary uses defaults."""
        config = ValidationConfig.from_dict({})
        assert config.sample_size == 100
        assert config.recall_threshold == 0.95
        assert config.latency_threshold_ms == 100


class TestMigrationStatus:
    """Tests for MigrationStatus enum."""

    def test_all_statuses_exist(self):
        """Test all expected statuses are defined."""
        assert MigrationStatus.PENDING == "pending"
        assert MigrationStatus.IN_PROGRESS == "in_progress"
        assert MigrationStatus.VALIDATING == "validating"
        assert MigrationStatus.SWITCHING == "switching"
        assert MigrationStatus.COMPLETED == "completed"
        assert MigrationStatus.FAILED == "failed"
        assert MigrationStatus.ROLLED_BACK == "rolled_back"


class TestEmbeddingMigration:
    """Tests for EmbeddingMigration model."""

    def test_progress_percentage_zero_documents(self):
        """Test progress is 0% when no documents."""
        migration = EmbeddingMigration(
            migration_id=uuid4(),
            source_model="model-a",
            target_model="model-b",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="col_v1",
            target_collection="col_v2",
            total_documents=0,
            processed_documents=0,
        )
        assert migration.progress_percentage == 0.0

    def test_progress_percentage_partial(self):
        """Test progress calculation with partial completion."""
        migration = EmbeddingMigration(
            migration_id=uuid4(),
            source_model="model-a",
            target_model="model-b",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="col_v1",
            target_collection="col_v2",
            total_documents=1000,
            processed_documents=500,
        )
        assert migration.progress_percentage == 50.0

    def test_progress_percentage_complete(self):
        """Test progress is 100% when all documents processed."""
        migration = EmbeddingMigration(
            migration_id=uuid4(),
            source_model="model-a",
            target_model="model-b",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="col_v1",
            target_collection="col_v2",
            total_documents=1000,
            processed_documents=1000,
        )
        assert migration.progress_percentage == 100.0

    def test_is_active_pending(self):
        """Test is_active for pending status."""
        migration = EmbeddingMigration(
            migration_id=uuid4(),
            source_model="model-a",
            target_model="model-b",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="col_v1",
            target_collection="col_v2",
            status=MigrationStatus.PENDING,
        )
        assert migration.is_active is True

    def test_is_active_in_progress(self):
        """Test is_active for in_progress status."""
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
        assert migration.is_active is True

    def test_is_active_completed(self):
        """Test is_active for completed status."""
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
        assert migration.is_active is False

    def test_can_rollback_completed_with_preserve(self):
        """Test rollback is possible when completed with preserve_source."""
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
        assert migration.can_rollback is True

    def test_cannot_rollback_without_preserve(self):
        """Test rollback is not possible without preserve_source."""
        migration = EmbeddingMigration(
            migration_id=uuid4(),
            source_model="model-a",
            target_model="model-b",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="col_v1",
            target_collection="col_v2",
            status=MigrationStatus.COMPLETED,
            rollback_enabled=False,
        )
        assert migration.can_rollback is False

    def test_json_serialization(self):
        """Test migration can be serialized to JSON."""
        migration = EmbeddingMigration(
            migration_id=uuid4(),
            source_model="model-a",
            target_model="model-b",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="col_v1",
            target_collection="col_v2",
        )
        json_str = migration.model_dump_json()
        assert "source_model" in json_str
        assert "target_model" in json_str

    def test_validation_config_stored(self):
        """Test validation config is stored in migration."""
        validation_config = {
            "sample_size": 200,
            "recall_threshold": 0.90,
            "latency_threshold_ms": 150,
        }
        migration = EmbeddingMigration(
            migration_id=uuid4(),
            source_model="model-a",
            target_model="model-b",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="col_v1",
            target_collection="col_v2",
            validation_config=validation_config,
        )
        assert migration.validation_config == validation_config
        assert migration.validation_config["sample_size"] == 200
        assert migration.validation_config["recall_threshold"] == 0.90

    def test_validation_config_default_none(self):
        """Test validation config defaults to None."""
        migration = EmbeddingMigration(
            migration_id=uuid4(),
            source_model="model-a",
            target_model="model-b",
            source_dimensions=1024,
            target_dimensions=1024,
            source_collection="col_v1",
            target_collection="col_v2",
        )
        assert migration.validation_config is None


class TestMigrationRequest:
    """Tests for MigrationRequest model."""

    def test_default_values(self):
        """Test default values are set correctly."""
        request = MigrationRequest(target_model="BAAI/bge-m3")
        assert request.batch_size == 100
        assert request.max_concurrent_batches == 4
        assert request.validate_before_switch is True
        assert request.auto_switch is False
        assert request.preserve_source is True
        assert request.validation_config is None

    def test_batch_size_validation(self):
        """Test batch size validation."""
        # Valid batch size
        request = MigrationRequest(target_model="model", batch_size=500)
        assert request.batch_size == 500

        # Invalid batch size (too small)
        with pytest.raises(ValueError):
            MigrationRequest(target_model="model", batch_size=5)

        # Invalid batch size (too large)
        with pytest.raises(ValueError):
            MigrationRequest(target_model="model", batch_size=2000)

    def test_max_concurrent_validation(self):
        """Test max concurrent batches validation."""
        # Valid value
        request = MigrationRequest(target_model="model", max_concurrent_batches=8)
        assert request.max_concurrent_batches == 8

        # Invalid value (too small)
        with pytest.raises(ValueError):
            MigrationRequest(target_model="model", max_concurrent_batches=0)

    def test_with_validation_config(self):
        """Test request with custom validation config."""
        validation_config = {
            "sample_size": 200,
            "recall_threshold": 0.90,
            "latency_threshold_ms": 150,
        }
        request = MigrationRequest(
            target_model="BAAI/bge-m3",
            validation_config=validation_config,
        )
        assert request.validation_config == validation_config
        assert request.validation_config["sample_size"] == 200
        assert request.validation_config["recall_threshold"] == 0.90
        assert request.validation_config["latency_threshold_ms"] == 150


class TestValidationResult:
    """Tests for ValidationResult model."""

    def test_from_scores_empty(self):
        """Test validation result with empty scores."""
        result = ValidationResult.from_scores([])
        assert result.total_queries == 0
        assert result.avg_overlap == 0.0
        assert result.validation_passed is False

    def test_from_scores_all_high(self):
        """Test validation result with all high scores."""
        scores = [0.9, 0.85, 0.95, 0.88]
        result = ValidationResult.from_scores(scores, threshold=0.7)
        assert result.total_queries == 4
        assert result.avg_overlap == pytest.approx(0.895, rel=0.01)
        assert result.validation_passed is True
        assert result.queries_with_low_overlap == 0

    def test_from_scores_mixed(self):
        """Test validation result with mixed scores."""
        scores = [0.9, 0.5, 0.8, 0.6]  # avg = 0.7
        result = ValidationResult.from_scores(scores, threshold=0.7)
        assert result.total_queries == 4
        assert result.avg_overlap == pytest.approx(0.7, rel=0.01)
        assert result.validation_passed is True
        assert result.queries_with_low_overlap == 2

    def test_from_scores_below_threshold(self):
        """Test validation result below threshold."""
        scores = [0.5, 0.4, 0.6, 0.5]  # avg = 0.5
        result = ValidationResult.from_scores(scores, threshold=0.7)
        assert result.validation_passed is False
        assert result.queries_with_low_overlap == 4

    def test_min_max_overlap(self):
        """Test min and max overlap calculation."""
        scores = [0.5, 0.9, 0.7]
        result = ValidationResult.from_scores(scores)
        assert result.min_overlap == 0.5
        assert result.max_overlap == 0.9


class TestMigrationProgress:
    """Tests for MigrationProgress model."""

    def test_basic_progress(self):
        """Test basic progress model."""
        progress = MigrationProgress(
            migration_id=uuid4(),
            batch_index=5,
            documents_processed=100,
            documents_failed=2,
            batch_duration_ms=1500.5,
        )
        assert progress.documents_processed == 100
        assert progress.documents_failed == 2
        assert progress.batch_index == 5

    def test_progress_with_errors(self):
        """Test progress model with error messages."""
        progress = MigrationProgress(
            migration_id=uuid4(),
            batch_index=0,
            documents_processed=98,
            documents_failed=2,
            batch_duration_ms=2000.0,
            error_messages=["Error 1", "Error 2"],
        )
        assert len(progress.error_messages) == 2
