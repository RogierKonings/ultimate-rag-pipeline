"""Tests for timeout configuration module."""

import os
from unittest import mock

import pytest

from shared.config.timeouts import (
    ALL_TIMEOUTS,
    ORCHESTRATOR_LLM_TIMEOUT,
    RETRIEVAL_EMBEDDING_TIMEOUT,
    RETRIEVAL_QDRANT_TIMEOUT,
    TimeoutConfig,
    get_timeout,
    get_timeout_ms,
    get_timeout_seconds,
)


class TestTimeoutConfig:
    """Tests for TimeoutConfig dataclass."""

    def test_default_values(self) -> None:
        """TimeoutConfig should have sensible defaults."""
        config = TimeoutConfig(timeout_ms=1000, retries=2)

        assert config.timeout_ms == 1000
        assert config.retries == 2
        assert config.backoff_base_ms == 100
        assert config.backoff_max_ms == 5000
        assert config.idempotent is True

    def test_immutable(self) -> None:
        """TimeoutConfig should be immutable (frozen)."""
        config = TimeoutConfig(timeout_ms=1000, retries=2)

        with pytest.raises(AttributeError):
            config.timeout_ms = 2000  # type: ignore

    def test_custom_values(self) -> None:
        """TimeoutConfig should accept custom values."""
        config = TimeoutConfig(
            timeout_ms=5000,
            retries=3,
            backoff_base_ms=200,
            backoff_max_ms=10000,
            idempotent=False,
        )

        assert config.timeout_ms == 5000
        assert config.retries == 3
        assert config.backoff_base_ms == 200
        assert config.backoff_max_ms == 10000
        assert config.idempotent is False

    def test_timeout_seconds_property(self) -> None:
        """timeout_seconds property should convert ms to seconds."""
        config = TimeoutConfig(timeout_ms=5000, retries=1)

        assert config.timeout_seconds == 5.0

    def test_timeout_seconds_fractional(self) -> None:
        """timeout_seconds should handle fractional seconds."""
        config = TimeoutConfig(timeout_ms=1500, retries=1)

        assert config.timeout_seconds == 1.5

    def test_backoff_base_seconds_property(self) -> None:
        """backoff_base_seconds property should convert ms to seconds."""
        config = TimeoutConfig(timeout_ms=1000, retries=1, backoff_base_ms=250)

        assert config.backoff_base_seconds == 0.25

    def test_backoff_max_seconds_property(self) -> None:
        """backoff_max_seconds property should convert ms to seconds."""
        config = TimeoutConfig(timeout_ms=1000, retries=1, backoff_max_ms=10000)

        assert config.backoff_max_seconds == 10.0


class TestGetTimeout:
    """Tests for get_timeout function."""

    def test_get_known_timeout(self) -> None:
        """get_timeout should return config for known names."""
        config = get_timeout("RETRIEVAL_QDRANT")

        assert config == RETRIEVAL_QDRANT_TIMEOUT
        assert config.timeout_ms == 3000

    def test_get_unknown_timeout_raises(self) -> None:
        """get_timeout should raise KeyError for unknown names."""
        with pytest.raises(KeyError) as exc_info:
            get_timeout("UNKNOWN_TIMEOUT")

        assert "Unknown timeout: UNKNOWN_TIMEOUT" in str(exc_info.value)
        assert "Available timeouts:" in str(exc_info.value)

    def test_get_timeout_seconds(self) -> None:
        """get_timeout_seconds should return timeout in seconds."""
        seconds = get_timeout_seconds("RETRIEVAL_QDRANT")

        assert seconds == 3.0

    def test_get_timeout_ms(self) -> None:
        """get_timeout_ms should return timeout in milliseconds."""
        milliseconds = get_timeout_ms("RETRIEVAL_QDRANT")

        assert milliseconds == 3000

    def test_get_timeout_embedding(self) -> None:
        """get_timeout should return embedding timeout config."""
        config = get_timeout("RETRIEVAL_EMBEDDING")

        assert config == RETRIEVAL_EMBEDDING_TIMEOUT
        assert config.timeout_ms == 5000
        assert config.retries == 2


class TestAllTimeoutsRegistry:
    """Tests for ALL_TIMEOUTS registry."""

    def test_all_timeouts_has_expected_keys(self) -> None:
        """ALL_TIMEOUTS should have all expected timeout names."""
        expected_keys = [
            # Retrieval
            "RETRIEVAL_EMBEDDING",
            "RETRIEVAL_QDRANT",
            "RETRIEVAL_OPENSEARCH",
            "RETRIEVAL_RERANKER",
            "RETRIEVAL_TOTAL",
            # Orchestrator
            "ORCHESTRATOR_RETRIEVAL",
            "ORCHESTRATOR_LLM",
            "ORCHESTRATOR_TOTAL",
            # Ingestion
            "INGESTION_PARSING",
            "INGESTION_EMBEDDING",
            "INGESTION_QDRANT_UPSERT",
            "INGESTION_OPENSEARCH_INDEX",
            "INGESTION_DOCUMENT",
            # Infrastructure
            "REDIS_OPERATION",
            "POSTGRES_QUERY",
            "HTTP_CONNECTION",
        ]

        for key in expected_keys:
            assert key in ALL_TIMEOUTS, f"Missing timeout: {key}"

    def test_all_values_are_timeout_config(self) -> None:
        """All values in ALL_TIMEOUTS should be TimeoutConfig instances."""
        for name, config in ALL_TIMEOUTS.items():
            assert isinstance(config, TimeoutConfig), f"{name} is not TimeoutConfig"

    def test_all_timeout_ms_positive(self) -> None:
        """All timeout_ms values should be positive."""
        for name, config in ALL_TIMEOUTS.items():
            assert config.timeout_ms > 0, f"{name} has non-positive timeout_ms"

    def test_all_retries_non_negative(self) -> None:
        """All retry values should be non-negative."""
        for name, config in ALL_TIMEOUTS.items():
            assert config.retries >= 0, f"{name} has negative retries"

    def test_all_backoff_base_positive(self) -> None:
        """All backoff_base_ms values should be positive."""
        for name, config in ALL_TIMEOUTS.items():
            assert config.backoff_base_ms > 0, f"{name} has non-positive backoff_base_ms"

    def test_all_backoff_max_gte_base(self) -> None:
        """All backoff_max_ms should be >= backoff_base_ms."""
        for name, config in ALL_TIMEOUTS.items():
            assert config.backoff_max_ms >= config.backoff_base_ms, (
                f"{name} has backoff_max_ms < backoff_base_ms"
            )


class TestTimeoutDefaultValues:
    """Tests for default timeout values."""

    def test_retrieval_qdrant_defaults(self) -> None:
        """RETRIEVAL_QDRANT_TIMEOUT should have correct defaults."""
        assert RETRIEVAL_QDRANT_TIMEOUT.timeout_ms == 3000
        assert RETRIEVAL_QDRANT_TIMEOUT.retries == 1
        assert RETRIEVAL_QDRANT_TIMEOUT.idempotent is True

    def test_retrieval_embedding_defaults(self) -> None:
        """RETRIEVAL_EMBEDDING_TIMEOUT should have correct defaults."""
        assert RETRIEVAL_EMBEDDING_TIMEOUT.timeout_ms == 5000
        assert RETRIEVAL_EMBEDDING_TIMEOUT.retries == 2
        assert RETRIEVAL_EMBEDDING_TIMEOUT.idempotent is True

    def test_orchestrator_llm_not_idempotent(self) -> None:
        """ORCHESTRATOR_LLM_TIMEOUT should not be idempotent."""
        assert ORCHESTRATOR_LLM_TIMEOUT.timeout_ms == 25000
        assert ORCHESTRATOR_LLM_TIMEOUT.retries == 0
        assert ORCHESTRATOR_LLM_TIMEOUT.idempotent is False

    def test_retrieval_total_timeout(self) -> None:
        """RETRIEVAL_TOTAL timeout should be 15 seconds."""
        config = get_timeout("RETRIEVAL_TOTAL")
        assert config.timeout_ms == 15000
        assert config.retries == 0

    def test_orchestrator_total_timeout(self) -> None:
        """ORCHESTRATOR_TOTAL timeout should be 30 seconds."""
        config = get_timeout("ORCHESTRATOR_TOTAL")
        assert config.timeout_ms == 30000
        assert config.retries == 0
        assert config.idempotent is False

    def test_ingestion_document_timeout(self) -> None:
        """INGESTION_DOCUMENT timeout should be 5 minutes."""
        config = get_timeout("INGESTION_DOCUMENT")
        assert config.timeout_ms == 300000  # 5 minutes in ms
        assert config.timeout_seconds == 300.0  # 5 minutes
        assert config.retries == 3


class TestEnvironmentVariableOverrides:
    """Tests for environment variable override functionality."""

    def test_timeout_env_override(self) -> None:
        """Timeout should be overridable via environment variable."""
        # We need to reimport the module to pick up env var changes
        # This tests the _get_env_int and _create_timeout_config functions
        with mock.patch.dict(
            os.environ,
            {"RETRIEVAL_QDRANT_TIMEOUT_MS": "6000"},
        ):
            # Reimport to pick up the env var
            from importlib import reload

            import shared.config.timeouts as timeouts_module

            reloaded = reload(timeouts_module)

            assert reloaded.RETRIEVAL_QDRANT_TIMEOUT.timeout_ms == 6000

            # Reload again to restore original values
            with mock.patch.dict(os.environ, {}, clear=False):
                # Remove our override
                os.environ.pop("RETRIEVAL_QDRANT_TIMEOUT_MS", None)
                reload(timeouts_module)

    def test_retries_env_override(self) -> None:
        """Retries should be overridable via environment variable."""
        with mock.patch.dict(
            os.environ,
            {"RETRIEVAL_QDRANT_RETRIES": "5"},
        ):
            from importlib import reload

            import shared.config.timeouts as timeouts_module

            reloaded = reload(timeouts_module)

            assert reloaded.RETRIEVAL_QDRANT_TIMEOUT.retries == 5

            # Clean up
            os.environ.pop("RETRIEVAL_QDRANT_RETRIES", None)
            reload(timeouts_module)

    def test_idempotent_env_override(self) -> None:
        """Idempotent flag should be overridable via environment variable."""
        with mock.patch.dict(
            os.environ,
            {"RETRIEVAL_QDRANT_IDEMPOTENT": "false"},
        ):
            from importlib import reload

            import shared.config.timeouts as timeouts_module

            reloaded = reload(timeouts_module)

            assert reloaded.RETRIEVAL_QDRANT_TIMEOUT.idempotent is False

            # Clean up
            os.environ.pop("RETRIEVAL_QDRANT_IDEMPOTENT", None)
            reload(timeouts_module)

    def test_invalid_env_int_uses_default(self) -> None:
        """Invalid integer env var should fall back to default."""
        with mock.patch.dict(
            os.environ,
            {"RETRIEVAL_QDRANT_TIMEOUT_MS": "not_a_number"},
        ):
            from importlib import reload

            import shared.config.timeouts as timeouts_module

            reloaded = reload(timeouts_module)

            # Should use default value when parsing fails
            assert reloaded.RETRIEVAL_QDRANT_TIMEOUT.timeout_ms == 3000

            # Clean up
            os.environ.pop("RETRIEVAL_QDRANT_TIMEOUT_MS", None)
            reload(timeouts_module)
