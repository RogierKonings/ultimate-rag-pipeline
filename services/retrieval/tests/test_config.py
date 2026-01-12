"""Tests for configuration."""

import os
from unittest.mock import patch

from config import RetrievalConfig


class TestRetrievalConfig:
    """Tests for RetrievalConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = RetrievalConfig()

        assert config.service_name == "retrieval-service"
        assert config.service_port == 8002
        assert config.debug is False
        assert config.qdrant_url == "http://localhost:6333"
        assert config.opensearch_url == "http://localhost:9200"
        assert config.semantic_weight == 0.7
        assert config.keyword_weight == 0.3

    def test_config_from_env(self):
        """Test configuration from environment variables."""
        env_vars = {
            "RETRIEVAL_SERVICE_PORT": "8003",
            "RETRIEVAL_DEBUG": "true",
            "RETRIEVAL_QDRANT_URL": "http://qdrant:6333",
            "RETRIEVAL_SEMANTIC_WEIGHT": "0.8",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            config = RetrievalConfig()

            assert config.service_port == 8003
            assert config.debug is True
            assert config.qdrant_url == "http://qdrant:6333"
            assert config.semantic_weight == 0.8

    def test_weight_validation(self):
        """Test weight range validation."""
        # Valid weights
        config = RetrievalConfig(semantic_weight=0.0, keyword_weight=1.0)
        assert config.semantic_weight == 0.0

        config = RetrievalConfig(semantic_weight=1.0, keyword_weight=0.0)
        assert config.semantic_weight == 1.0

    def test_jwt_config(self):
        """Test JWT configuration."""
        config = RetrievalConfig(
            jwt_secret="my-secret",
            jwt_algorithm="HS512",
        )

        assert config.jwt_secret == "my-secret"
        assert config.jwt_algorithm == "HS512"

    def test_cache_config(self):
        """Test cache configuration."""
        config = RetrievalConfig(
            redis_url="redis://redis:6379",
            cache_enabled=True,
            cache_ttl_seconds=7200,
        )

        assert config.redis_url == "redis://redis:6379"
        assert config.cache_enabled is True
        assert config.cache_ttl_seconds == 7200

    def test_timeout_config(self):
        """Test timeout configuration."""
        config = RetrievalConfig(
            search_timeout_seconds=60.0,
            rerank_timeout_seconds=45.0,
        )

        assert config.search_timeout_seconds == 60.0
        assert config.rerank_timeout_seconds == 45.0

    def test_logging_config(self):
        """Test logging configuration."""
        config = RetrievalConfig(
            log_level="DEBUG",
            log_format="text",
        )

        assert config.log_level == "DEBUG"
        assert config.log_format == "text"

    def test_metrics_config(self):
        """Test metrics configuration."""
        config = RetrievalConfig(
            metrics_enabled=True,
            metrics_port=9091,
        )

        assert config.metrics_enabled is True
        assert config.metrics_port == 9091
