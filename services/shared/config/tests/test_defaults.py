"""Tests for shared configuration defaults."""

import os
from unittest.mock import patch

import pytest

from shared.config.defaults import (
    ChunkingConfig,
    EmbeddingConfig,
    RetrievalConfig,
    get_chunking_config,
    get_embedding_config,
    get_retrieval_config,
    validate_all_configs,
)


class TestChunkingConfig:
    """Test ChunkingConfig class."""

    def test_default_values(self):
        """Test default configuration values match architecture spec."""
        config = ChunkingConfig()

        assert config.target_tokens == 300
        assert config.max_tokens == 512
        assert config.chunk_overlap == 50
        assert config.min_chunk_size == 50
        assert config.tokenizer == "cl100k_base"
        assert config.preserve_sentences is True
        assert config.preserve_paragraphs is False

    def test_chunk_size_alias(self):
        """Test chunk_size property alias."""
        config = ChunkingConfig(target_tokens=400)
        assert config.chunk_size == 400

    def test_overlap_tokens_alias(self):
        """Test overlap_tokens property alias."""
        config = ChunkingConfig(chunk_overlap=75)
        assert config.overlap_tokens == 75

    def test_separators_default(self):
        """Test default separators for recursive splitting."""
        config = ChunkingConfig()
        assert config.separators == ["\n\n", "\n", ". ", " "]


class TestEmbeddingConfig:
    """Test EmbeddingConfig class."""

    def test_default_values(self):
        """Test default configuration values match architecture spec."""
        config = EmbeddingConfig()

        assert config.model_name == "BAAI/bge-large-en-v1.5"
        assert config.dimensions == 1024
        assert config.batch_size == 32
        assert config.normalize is True
        assert config.max_sequence_length == 512
        assert "Represent this sentence" in config.query_prefix

    def test_batch_size_constraints(self):
        """Test batch_size field constraints."""
        # Valid values
        config = EmbeddingConfig(batch_size=1)
        assert config.batch_size == 1

        config = EmbeddingConfig(batch_size=256)
        assert config.batch_size == 256

        # Invalid values
        with pytest.raises(ValueError):
            EmbeddingConfig(batch_size=0)

        with pytest.raises(ValueError):
            EmbeddingConfig(batch_size=257)


class TestRetrievalConfig:
    """Test RetrievalConfig class."""

    def test_default_values(self):
        """Test default configuration values match architecture spec."""
        config = RetrievalConfig()

        assert config.semantic_top_k == 50
        assert config.keyword_top_k == 50
        assert config.rrf_k == 60
        assert config.semantic_weight == 0.7
        assert config.keyword_weight == 0.3
        assert config.rerank_top_k == 10
        assert config.reranker_model == "BAAI/bge-reranker-v2-m3"

    def test_weight_constraints(self):
        """Test weight field constraints."""
        # Valid weights
        config = RetrievalConfig(semantic_weight=0.0, keyword_weight=1.0)
        assert config.semantic_weight == 0.0

        # Invalid weights
        with pytest.raises(ValueError):
            RetrievalConfig(semantic_weight=1.5)

        with pytest.raises(ValueError):
            RetrievalConfig(keyword_weight=-0.1)


class TestGetChunkingConfig:
    """Test get_chunking_config factory function."""

    def test_returns_defaults(self):
        """Test factory returns default values."""
        config = get_chunking_config()

        assert config.target_tokens == 300
        assert config.max_tokens == 512
        assert config.chunk_overlap == 50

    def test_env_var_override(self):
        """Test environment variables override defaults."""
        with patch.dict(
            os.environ,
            {
                "CHUNKING_TARGET_TOKENS": "400",
                "CHUNKING_MAX_TOKENS": "600",
                "CHUNKING_CHUNK_OVERLAP": "75",
            },
        ):
            config = get_chunking_config()

            assert config.target_tokens == 400
            assert config.max_tokens == 600
            assert config.chunk_overlap == 75

    def test_explicit_override_beats_env_var(self):
        """Test explicit overrides take precedence over env vars."""
        with patch.dict(os.environ, {"CHUNKING_TARGET_TOKENS": "400"}):
            config = get_chunking_config(target_tokens=500)

            assert config.target_tokens == 500


class TestGetEmbeddingConfig:
    """Test get_embedding_config factory function."""

    def test_returns_defaults(self):
        """Test factory returns default values."""
        config = get_embedding_config()

        assert config.model_name == "BAAI/bge-large-en-v1.5"
        assert config.dimensions == 1024

    def test_env_var_override(self):
        """Test environment variables override defaults."""
        with patch.dict(
            os.environ,
            {
                "EMBEDDING_MODEL": "sentence-transformers/all-MiniLM-L6-v2",
                "EMBEDDING_DIMENSIONS": "384",
                "EMBEDDING_BATCH_SIZE": "64",
                "EMBEDDING_NORMALIZE": "false",
            },
        ):
            config = get_embedding_config()

            assert config.model_name == "sentence-transformers/all-MiniLM-L6-v2"
            assert config.dimensions == 384
            assert config.batch_size == 64
            assert config.normalize is False


class TestGetRetrievalConfig:
    """Test get_retrieval_config factory function."""

    def test_returns_defaults(self):
        """Test factory returns default values."""
        config = get_retrieval_config()

        assert config.semantic_top_k == 50
        assert config.rrf_k == 60

    def test_env_var_override(self):
        """Test environment variables override defaults."""
        with patch.dict(
            os.environ,
            {
                "RETRIEVAL_SEMANTIC_TOP_K": "100",
                "RETRIEVAL_KEYWORD_TOP_K": "100",
                "RETRIEVAL_RRF_K": "40",
                "RETRIEVAL_SEMANTIC_WEIGHT": "0.6",
                "RETRIEVAL_KEYWORD_WEIGHT": "0.4",
            },
        ):
            config = get_retrieval_config()

            assert config.semantic_top_k == 100
            assert config.keyword_top_k == 100
            assert config.rrf_k == 40
            assert config.semantic_weight == 0.6
            assert config.keyword_weight == 0.4


class TestValidateAllConfigs:
    """Test validate_all_configs function."""

    def test_valid_defaults(self):
        """Test that default configuration is valid."""
        errors = validate_all_configs()
        assert errors == []

    def test_invalid_chunk_overlap(self):
        """Test validation catches overlap >= target."""
        with patch.dict(
            os.environ,
            {
                "CHUNKING_TARGET_TOKENS": "100",
                "CHUNKING_CHUNK_OVERLAP": "150",
            },
        ):
            errors = validate_all_configs()

            assert len(errors) >= 1
            assert any("chunk_overlap" in e for e in errors)

    def test_invalid_target_exceeds_max(self):
        """Test validation catches target > max."""
        with patch.dict(
            os.environ,
            {
                "CHUNKING_TARGET_TOKENS": "600",
                "CHUNKING_MAX_TOKENS": "512",
            },
        ):
            errors = validate_all_configs()

            assert len(errors) >= 1
            assert any("target_tokens" in e and "exceeds" in e for e in errors)

    def test_invalid_weights_sum(self):
        """Test validation catches weights not summing to 1.0."""
        with patch.dict(
            os.environ,
            {
                "RETRIEVAL_SEMANTIC_WEIGHT": "0.6",
                "RETRIEVAL_KEYWORD_WEIGHT": "0.6",
            },
        ):
            errors = validate_all_configs()

            assert len(errors) >= 1
            assert any("weight" in e.lower() for e in errors)

    def test_unusual_embedding_dimensions(self):
        """Test validation warns about unusual dimensions."""
        with patch.dict(os.environ, {"EMBEDDING_DIMENSIONS": "512"}):
            errors = validate_all_configs()

            assert len(errors) >= 1
            assert any("dimensions" in e for e in errors)

    def test_rerank_exceeds_semantic(self):
        """Test validation catches rerank_top_k > semantic_top_k."""
        with patch.dict(
            os.environ,
            {
                "RETRIEVAL_RERANK_TOP_K": "100",
                "RETRIEVAL_SEMANTIC_TOP_K": "50",
            },
        ):
            errors = validate_all_configs()

            assert len(errors) >= 1
            assert any("rerank_top_k" in e for e in errors)
