"""
Unit tests for configuration models (US-5.4).

Tests Pydantic models for validation and serialization.
"""

from datetime import datetime, timedelta

import pytest

from config.models import (
    ABTestConfig,
    ConfigVersion,
    EmbeddingConfig,
    LLMGenerationConfig,
    ModelConfigurationState,
    ModelEndpoint,
    ModelType,
    RerankerConfig,
    RoutingStrategy,
)


class TestLLMGenerationConfig:
    """Tests for LLMGenerationConfig model."""

    def test_default_values(self):
        """Test default configuration values."""
        config = LLMGenerationConfig()

        assert config.temperature == 0.7
        assert config.top_p == 1.0
        assert config.top_k == 50
        assert config.max_tokens == 1024
        assert config.frequency_penalty == 0.0
        assert config.presence_penalty == 0.0
        assert config.repetition_penalty == 1.0
        assert config.stop_sequences == []
        assert config.stream is True

    def test_valid_temperature(self):
        """Test valid temperature values."""
        config = LLMGenerationConfig(temperature=0.0)
        assert config.temperature == 0.0

        config = LLMGenerationConfig(temperature=2.0)
        assert config.temperature == 2.0

        config = LLMGenerationConfig(temperature=0.5)
        assert config.temperature == 0.5

    def test_invalid_temperature(self):
        """Test invalid temperature values."""
        with pytest.raises(ValueError):
            LLMGenerationConfig(temperature=-0.1)

        with pytest.raises(ValueError):
            LLMGenerationConfig(temperature=2.1)

    def test_invalid_top_p(self):
        """Test invalid top_p values."""
        with pytest.raises(ValueError):
            LLMGenerationConfig(top_p=-0.1)

        with pytest.raises(ValueError):
            LLMGenerationConfig(top_p=1.1)

    def test_to_vllm_params(self):
        """Test conversion to vLLM parameters."""
        config = LLMGenerationConfig(
            temperature=0.5,
            top_p=0.9,
            max_tokens=512,
            stop_sequences=["###", "END"],
        )

        params = config.to_vllm_params()

        assert params["temperature"] == 0.5
        assert params["top_p"] == 0.9
        assert params["max_tokens"] == 512
        assert params["stop"] == ["###", "END"]

    def test_to_vllm_params_empty_stop(self):
        """Test vLLM params with no stop sequences."""
        config = LLMGenerationConfig()
        params = config.to_vllm_params()

        assert params["stop"] is None


class TestEmbeddingConfig:
    """Tests for EmbeddingConfig model."""

    def test_default_values(self):
        """Test default configuration values."""
        config = EmbeddingConfig()

        assert config.normalize is True
        assert config.batch_size == 32
        assert config.max_sequence_length == 512
        assert config.use_fp16 is True
        assert config.prefix_query == "query: "
        assert config.prefix_passage == "passage: "

    def test_custom_values(self):
        """Test custom configuration values."""
        config = EmbeddingConfig(
            normalize=False,
            batch_size=64,
            max_sequence_length=1024,
            use_fp16=False,
        )

        assert config.normalize is False
        assert config.batch_size == 64
        assert config.max_sequence_length == 1024
        assert config.use_fp16 is False


class TestRerankerConfig:
    """Tests for RerankerConfig model."""

    def test_default_values(self):
        """Test default configuration values."""
        config = RerankerConfig()

        assert config.max_pairs_per_request == 100
        assert config.max_sequence_length == 512
        assert config.batch_size == 32
        assert config.normalize_scores is False
        assert config.use_fp16 is True


class TestModelEndpoint:
    """Tests for ModelEndpoint model."""

    def test_llm_endpoint(self):
        """Test LLM endpoint creation."""
        endpoint = ModelEndpoint(
            name="test-llm",
            type=ModelType.LLM,
            model_id="test-model",
            endpoint_url="http://localhost:8000",
            llm_config=LLMGenerationConfig(temperature=0.5),
        )

        assert endpoint.name == "test-llm"
        assert endpoint.type == ModelType.LLM
        assert endpoint.llm_config.temperature == 0.5
        assert endpoint.enabled is True
        assert endpoint.version == "1.0.0"

    def test_embedding_endpoint(self):
        """Test embedding endpoint creation."""
        endpoint = ModelEndpoint(
            name="test-embedding",
            type=ModelType.EMBEDDING,
            model_id="BAAI/bge-large-en-v1.5",
            endpoint_url="http://localhost:8001",
            embedding_config=EmbeddingConfig(batch_size=64),
        )

        assert endpoint.type == ModelType.EMBEDDING
        assert endpoint.embedding_config.batch_size == 64

    def test_endpoint_serialization(self):
        """Test endpoint serialization."""
        endpoint = ModelEndpoint(
            name="test",
            type=ModelType.LLM,
            model_id="test",
            endpoint_url="http://test",
            tags=["prod", "primary"],
        )

        data = endpoint.model_dump(mode="json")

        assert data["name"] == "test"
        assert data["type"] == "llm"
        assert data["tags"] == ["prod", "primary"]


class TestABTestConfig:
    """Tests for ABTestConfig model."""

    def test_default_values(self):
        """Test default A/B test values."""
        test = ABTestConfig(
            name="test-experiment",
            model_a="model-a",
            model_b="model-b",
        )

        assert test.traffic_split == 0.5
        assert test.strategy == RoutingStrategy.RANDOM
        assert test.active is True
        assert test.id is not None

    def test_is_active_default(self):
        """Test is_active with no time bounds."""
        test = ABTestConfig(
            name="test",
            model_a="a",
            model_b="b",
        )

        assert test.is_active() is True

    def test_is_active_inactive(self):
        """Test is_active when deactivated."""
        test = ABTestConfig(
            name="test",
            model_a="a",
            model_b="b",
            active=False,
        )

        assert test.is_active() is False

    def test_is_active_not_started(self):
        """Test is_active before start time."""
        test = ABTestConfig(
            name="test",
            model_a="a",
            model_b="b",
            start_time=datetime.utcnow() + timedelta(hours=1),
        )

        assert test.is_active() is False

    def test_is_active_ended(self):
        """Test is_active after end time."""
        test = ABTestConfig(
            name="test",
            model_a="a",
            model_b="b",
            end_time=datetime.utcnow() - timedelta(hours=1),
        )

        assert test.is_active() is False

    def test_is_active_in_window(self):
        """Test is_active within time window."""
        test = ABTestConfig(
            name="test",
            model_a="a",
            model_b="b",
            start_time=datetime.utcnow() - timedelta(hours=1),
            end_time=datetime.utcnow() + timedelta(hours=1),
        )

        assert test.is_active() is True


class TestModelConfigurationState:
    """Tests for ModelConfigurationState model."""

    def test_default_state(self):
        """Test default state values."""
        state = ModelConfigurationState()

        assert state.current_version == 1
        assert state.endpoints == {}
        assert state.ab_tests == []
        assert state.version_history == []

    def test_get_endpoint(self):
        """Test getting endpoint by name."""
        endpoint = ModelEndpoint(
            name="test",
            type=ModelType.LLM,
            model_id="test",
            endpoint_url="http://test",
        )
        state = ModelConfigurationState(endpoints={"test": endpoint})

        assert state.get_endpoint("test") == endpoint
        assert state.get_endpoint("nonexistent") is None

    def test_get_active_tests(self):
        """Test getting active A/B tests."""
        active_test = ABTestConfig(
            name="active",
            model_a="a",
            model_b="b",
            active=True,
        )
        inactive_test = ABTestConfig(
            name="inactive",
            model_a="a",
            model_b="b",
            active=False,
        )
        state = ModelConfigurationState(ab_tests=[active_test, inactive_test])

        active_tests = state.get_active_tests()

        assert len(active_tests) == 1
        assert active_tests[0].name == "active"


class TestConfigVersion:
    """Tests for ConfigVersion model."""

    def test_version_creation(self):
        """Test creating a config version."""
        endpoint = ModelEndpoint(
            name="test",
            type=ModelType.LLM,
            model_id="test",
            endpoint_url="http://test",
        )

        version = ConfigVersion(
            version=1,
            endpoints={"test": endpoint},
            description="Initial version",
        )

        assert version.version == 1
        assert version.id is not None
        assert version.timestamp is not None
        assert "test" in version.endpoints
        assert version.description == "Initial version"
