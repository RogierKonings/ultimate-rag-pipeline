"""Schema alignment tests for US-2.12.

These tests validate that:
1. ORM models match the architecture-defined schemas
2. Migrations produce the expected database structure
3. Embedding dimensions and chunking defaults match architecture spec

Run with: pytest tests/ingest/test_schema_alignment.py
"""


import pytest
from sqlalchemy import inspect

# Architecture-defined constants from docs/architecture.md
ARCHITECTURE_EMBEDDING_DIMENSIONS = 1024
ARCHITECTURE_CHUNKING_TARGET_TOKENS = 300
ARCHITECTURE_CHUNKING_MAX_TOKENS = 512
ARCHITECTURE_CHUNKING_OVERLAP_TOKENS = 50


class TestArchitectureSchemaAlignment:
    """Tests that ORM models match architecture.md schema definitions."""

    def test_documents_table_columns(self):
        """Verify documents table has all architecture-defined columns."""
        from database.models import Document

        mapper = inspect(Document)
        column_names = {col.key for col in mapper.columns}

        # Required columns per architecture.md source_documents table
        required_columns = {
            "id",
            "tenant_id",
            "source_type",
            "source_uri",  # Renamed from source_id in migration 002
            "title",
            "content_hash",
            "version",
            "visibility",
            "allowed_groups",
            "created_at",
            "updated_at",
        }

        missing = required_columns - column_names
        assert not missing, f"Documents table missing columns: {missing}"

    def test_chunks_table_columns(self):
        """Verify chunks table has all architecture-defined columns."""
        from database.models import Chunk

        mapper = inspect(Chunk)
        column_names = {col.key for col in mapper.columns}

        # Required columns per architecture.md chunks table
        required_columns = {
            "id",
            "document_id",
            "chunk_index",
            "content",
            "token_count",
            "embedding_model",
            "embedding_version",
            "created_at",
            "tenant_id",  # Denormalized for query performance
            "schema_version",  # Added in migration 002
        }

        missing = required_columns - column_names
        assert not missing, f"Chunks table missing columns: {missing}"

    def test_embedding_jobs_table_columns(self):
        """Verify embedding_jobs table has all architecture-defined columns."""
        from database.models import EmbeddingJob

        mapper = inspect(EmbeddingJob)
        column_names = {col.key for col in mapper.columns}

        # Required columns per architecture.md embedding_jobs table
        required_columns = {
            "id",
            "status",
            "embedding_model",
            "target_scope",
            "started_at",
            "completed_at",
            "error_message",
            "stats",
        }

        missing = required_columns - column_names
        assert not missing, f"EmbeddingJob table missing columns: {missing}"

    def test_retrieval_logs_table_columns(self):
        """Verify retrieval_logs table has all architecture-defined columns."""
        from database.models import RetrievalLog

        mapper = inspect(RetrievalLog)
        column_names = {col.key for col in mapper.columns}

        # Required columns per architecture.md retrieval_logs table
        required_columns = {
            "id",
            "tenant_id",
            "user_id",
            "query",
            "effective_query",
            "retrieved_chunk_ids",
            "scores",
            "filters_applied",
            "latency_ms",
            "created_at",
            # US-2.12 additions for ingestion logging
            "trace_id",
            "span_id",
            "document_id",
            "job_id",
            "event_type",
        }

        missing = required_columns - column_names
        assert not missing, f"RetrievalLog table missing columns: {missing}"


class TestEmbeddingConfigAlignment:
    """Tests that embedding configuration matches architecture defaults."""

    def test_embedding_dimensions_default(self):
        """Verify embedding dimensions match architecture spec (1024)."""
        from config import (
            ARCHITECTURE_EMBEDDING_DIMENSIONS,
            get_settings,
        )

        settings = get_settings()
        assert settings.embedding_dimensions == ARCHITECTURE_EMBEDDING_DIMENSIONS
        assert settings.embedding_dimensions == 1024

    def test_embedding_service_config_dimensions(self):
        """Verify EmbeddingServiceConfig uses correct dimensions."""
        from embedding.models import EmbeddingServiceConfig

        config = EmbeddingServiceConfig()
        assert config.dimensions == ARCHITECTURE_EMBEDDING_DIMENSIONS

    def test_embedding_dimensions_validation_rejects_wrong_value(self):
        """Verify config validation rejects non-1024 dimensions."""
        from pydantic import ValidationError

        from config import Settings

        with pytest.raises(ValidationError) as exc_info:
            Settings(embedding_dimensions=768)

        assert "embedding_dimensions" in str(exc_info.value)
        assert "1024" in str(exc_info.value)


class TestChunkingConfigAlignment:
    """Tests that chunking configuration matches architecture defaults."""

    def test_chunking_target_tokens_default(self):
        """Verify chunking target tokens match architecture spec (300)."""
        from config import (
            ARCHITECTURE_CHUNKING_TARGET_TOKENS,
            get_settings,
        )

        settings = get_settings()
        assert settings.chunking_target_tokens == ARCHITECTURE_CHUNKING_TARGET_TOKENS
        assert settings.chunking_target_tokens == 300

    def test_chunking_max_tokens_default(self):
        """Verify chunking max tokens match architecture spec (512)."""
        from config import (
            ARCHITECTURE_CHUNKING_MAX_TOKENS,
            get_settings,
        )

        settings = get_settings()
        assert settings.chunking_max_tokens == ARCHITECTURE_CHUNKING_MAX_TOKENS
        assert settings.chunking_max_tokens == 512

    def test_chunking_overlap_tokens_default(self):
        """Verify chunking overlap tokens match architecture spec (50)."""
        from config import (
            ARCHITECTURE_CHUNKING_OVERLAP_TOKENS,
            get_settings,
        )

        settings = get_settings()
        assert settings.chunking_overlap_tokens == ARCHITECTURE_CHUNKING_OVERLAP_TOKENS
        assert settings.chunking_overlap_tokens == 50

    def test_chunking_config_defaults(self):
        """Verify ChunkingConfig class uses architecture defaults."""
        from processors.chunking import ChunkingConfig

        config = ChunkingConfig()
        assert config.target_tokens == ARCHITECTURE_CHUNKING_TARGET_TOKENS
        assert config.max_tokens == ARCHITECTURE_CHUNKING_MAX_TOKENS
        assert config.chunk_overlap == ARCHITECTURE_CHUNKING_OVERLAP_TOKENS

    def test_chunking_target_validation_rejects_wrong_value(self):
        """Verify config validation rejects non-300 target tokens."""
        from pydantic import ValidationError

        from config import Settings

        with pytest.raises(ValidationError) as exc_info:
            Settings(chunking_target_tokens=200)

        assert "chunking_target_tokens" in str(exc_info.value)
        assert "300" in str(exc_info.value)

    def test_chunking_max_validation_rejects_wrong_value(self):
        """Verify config validation rejects non-512 max tokens."""
        from pydantic import ValidationError

        from config import Settings

        with pytest.raises(ValidationError) as exc_info:
            Settings(chunking_max_tokens=1024)

        assert "chunking_max_tokens" in str(exc_info.value)
        assert "512" in str(exc_info.value)

    def test_chunking_overlap_validation_rejects_wrong_value(self):
        """Verify config validation rejects non-50 overlap tokens."""
        from pydantic import ValidationError

        from config import Settings

        with pytest.raises(ValidationError) as exc_info:
            Settings(chunking_overlap_tokens=100)

        assert "chunking_overlap_tokens" in str(exc_info.value)
        assert "50" in str(exc_info.value)


class TestConfigValidationFunction:
    """Tests for the validate_architecture_config helper function."""

    def test_validate_architecture_config_returns_all_validations(self):
        """Verify validate_architecture_config returns complete results."""
        from config import validate_architecture_config

        results = validate_architecture_config()

        assert "embedding_dimensions" in results
        assert "chunking_target_tokens" in results
        assert "chunking_max_tokens" in results
        assert "chunking_overlap_tokens" in results

        # All should be valid with default config
        for key, value in results.items():
            assert value["valid"], f"{key} validation failed"
            assert value["expected"] == value["actual"]


class TestTelemetryConfiguration:
    """Tests for telemetry configuration (US-2.12)."""

    def test_otel_configuration_present(self):
        """Verify OpenTelemetry configuration is present in settings."""
        from config import get_settings

        settings = get_settings()
        assert hasattr(settings, "otel_enabled")
        assert hasattr(settings, "otel_service_name")
        assert hasattr(settings, "otel_exporter_otlp_endpoint")

    def test_metrics_configuration_present(self):
        """Verify Prometheus metrics configuration is present in settings."""
        from config import get_settings

        settings = get_settings()
        assert hasattr(settings, "metrics_enabled")
        assert hasattr(settings, "metrics_port")

    def test_default_service_name(self):
        """Verify default OTEL service name is ingestion-service."""
        from config import get_settings

        settings = get_settings()
        assert settings.otel_service_name == "ingestion-service"


class TestDocumentModelConstraints:
    """Tests for document model constraints matching architecture."""

    def test_document_unique_constraint(self):
        """Verify documents have unique constraint on (tenant_id, source_uri, content_hash)."""
        from database.models import Document

        mapper = inspect(Document)
        table = mapper.persist_selectable

        # Check for unique index
        unique_indexes = [
            idx for idx in table.indexes if idx.unique
        ]

        unique_column_sets = [
            frozenset(col.name for col in idx.columns)
            for idx in unique_indexes
        ]

        expected_columns = frozenset(["tenant_id", "source_uri", "content_hash"])
        assert expected_columns in unique_column_sets, (
            f"Missing unique constraint on (tenant_id, source_uri, content_hash). "
            f"Found: {unique_column_sets}"
        )

    def test_chunk_document_relationship(self):
        """Verify chunks have foreign key to documents with cascade delete."""
        from database.models import Chunk

        mapper = inspect(Chunk)
        relationships = mapper.relationships

        # Should have document relationship
        assert "document" in relationships

        # Get the document_id column and check foreign key
        doc_id_col = mapper.columns.get("document_id")
        assert doc_id_col is not None
        assert len(doc_id_col.foreign_keys) > 0

        # Check cascade behavior via the foreign key
        fk = list(doc_id_col.foreign_keys)[0]
        assert fk.ondelete == "CASCADE"
