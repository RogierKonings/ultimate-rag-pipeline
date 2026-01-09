"""
Unit tests for ConfigurationManager (US-5.4).

Tests configuration loading, updates, versioning, and rollback.
"""

import tempfile
from pathlib import Path

import pytest
import yaml

from config.manager import ConfigurationManager
from config.models import ABTestConfig, ModelType


@pytest.fixture
def config_manager():
    """Create a fresh configuration manager."""
    return ConfigurationManager()


@pytest.fixture
def sample_config():
    """Sample configuration data."""
    return {
        "endpoints": {
            "test-llm": {
                "type": "llm",
                "model_id": "test-model",
                "endpoint_url": "http://localhost:8000",
                "llm_config": {"temperature": 0.5, "max_tokens": 512},
            },
            "test-embedding": {
                "type": "embedding",
                "model_id": "test-embedding",
                "endpoint_url": "http://localhost:8001",
            },
        }
    }


@pytest.fixture
def two_model_config():
    """Configuration with two models for A/B testing."""
    return {
        "endpoints": {
            "model-a": {
                "type": "llm",
                "model_id": "model-a",
                "endpoint_url": "http://a",
            },
            "model-b": {
                "type": "llm",
                "model_id": "model-b",
                "endpoint_url": "http://b",
            },
        }
    }


class TestConfigurationLoading:
    """Tests for configuration loading."""

    @pytest.mark.asyncio
    async def test_load_from_dict(self, config_manager, sample_config):
        """Test loading configuration from dictionary."""
        await config_manager.load_from_dict(sample_config)

        state = config_manager.get_state()
        assert "test-llm" in state.endpoints
        assert state.endpoints["test-llm"].llm_config.temperature == 0.5

    @pytest.mark.asyncio
    async def test_load_from_file(self, config_manager, sample_config):
        """Test loading configuration from YAML file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump(sample_config, f)
            path = Path(f.name)

        try:
            await config_manager.load_from_file(path)

            assert "test-llm" in config_manager.get_state().endpoints
        finally:
            path.unlink()

    @pytest.mark.asyncio
    async def test_load_increments_version(self, config_manager, sample_config):
        """Test that loading configuration increments version."""
        await config_manager.load_from_dict(sample_config)
        v1 = config_manager.get_state().current_version

        await config_manager.load_from_dict(sample_config)
        v2 = config_manager.get_state().current_version

        assert v2 == v1 + 1


class TestEndpointOperations:
    """Tests for endpoint operations."""

    @pytest.mark.asyncio
    async def test_get_endpoint(self, config_manager, sample_config):
        """Test getting a specific endpoint."""
        await config_manager.load_from_dict(sample_config)

        endpoint = config_manager.get_endpoint("test-llm")

        assert endpoint is not None
        assert endpoint.model_id == "test-model"

    @pytest.mark.asyncio
    async def test_get_nonexistent_endpoint(self, config_manager, sample_config):
        """Test getting a nonexistent endpoint."""
        await config_manager.load_from_dict(sample_config)

        endpoint = config_manager.get_endpoint("nonexistent")

        assert endpoint is None

    @pytest.mark.asyncio
    async def test_get_all_endpoints(self, config_manager, sample_config):
        """Test getting all endpoints."""
        await config_manager.load_from_dict(sample_config)

        endpoints = config_manager.get_all_endpoints()

        assert len(endpoints) == 2

    @pytest.mark.asyncio
    async def test_get_endpoints_by_type(self, config_manager, sample_config):
        """Test filtering endpoints by type."""
        await config_manager.load_from_dict(sample_config)

        llm_endpoints = config_manager.get_all_endpoints(ModelType.LLM)
        embedding_endpoints = config_manager.get_all_endpoints(ModelType.EMBEDDING)

        assert len(llm_endpoints) == 1
        assert len(embedding_endpoints) == 1

    @pytest.mark.asyncio
    async def test_update_endpoint(self, config_manager, sample_config):
        """Test updating endpoint configuration."""
        await config_manager.load_from_dict(sample_config)

        await config_manager.update_endpoint("test-llm", {"enabled": False})

        endpoint = config_manager.get_endpoint("test-llm")
        assert endpoint.enabled is False

    @pytest.mark.asyncio
    async def test_update_nonexistent_endpoint(self, config_manager, sample_config):
        """Test updating a nonexistent endpoint raises error."""
        await config_manager.load_from_dict(sample_config)

        with pytest.raises(ValueError, match="not found"):
            await config_manager.update_endpoint("nonexistent", {"enabled": False})


class TestGenerationParams:
    """Tests for LLM generation parameter updates."""

    @pytest.mark.asyncio
    async def test_update_generation_params(self, config_manager, sample_config):
        """Test updating generation parameters."""
        await config_manager.load_from_dict(sample_config)

        await config_manager.update_generation_params(
            "test-llm", temperature=0.9, max_tokens=2048
        )

        endpoint = config_manager.get_endpoint("test-llm")
        assert endpoint.llm_config.temperature == 0.9
        assert endpoint.llm_config.max_tokens == 2048

    @pytest.mark.asyncio
    async def test_update_params_nonllm_endpoint(self, config_manager, sample_config):
        """Test updating generation params on non-LLM endpoint."""
        await config_manager.load_from_dict(sample_config)

        with pytest.raises(ValueError, match="not an LLM"):
            await config_manager.update_generation_params(
                "test-embedding", temperature=0.5
            )


class TestABTests:
    """Tests for A/B test management."""

    @pytest.mark.asyncio
    async def test_create_ab_test(self, config_manager, two_model_config):
        """Test creating an A/B test."""
        await config_manager.load_from_dict(two_model_config)

        test = ABTestConfig(
            name="test-experiment",
            model_a="model-a",
            model_b="model-b",
            traffic_split=0.5,
        )
        await config_manager.create_ab_test(test)

        tests = config_manager.get_active_ab_tests()
        assert len(tests) == 1
        assert tests[0].name == "test-experiment"

    @pytest.mark.asyncio
    async def test_create_ab_test_invalid_model(self, config_manager, two_model_config):
        """Test creating A/B test with invalid model raises error."""
        await config_manager.load_from_dict(two_model_config)

        test = ABTestConfig(
            name="test",
            model_a="model-a",
            model_b="nonexistent",
        )

        with pytest.raises(ValueError, match="not found"):
            await config_manager.create_ab_test(test)

    @pytest.mark.asyncio
    async def test_update_ab_test(self, config_manager, two_model_config):
        """Test updating an A/B test."""
        await config_manager.load_from_dict(two_model_config)

        test = ABTestConfig(
            name="test",
            model_a="model-a",
            model_b="model-b",
        )
        await config_manager.create_ab_test(test)

        await config_manager.update_ab_test(test.id, {"traffic_split": 0.7})

        tests = config_manager.get_active_ab_tests()
        assert tests[0].traffic_split == 0.7

    @pytest.mark.asyncio
    async def test_deactivate_ab_test(self, config_manager, two_model_config):
        """Test deactivating an A/B test."""
        await config_manager.load_from_dict(two_model_config)

        test = ABTestConfig(
            name="test",
            model_a="model-a",
            model_b="model-b",
        )
        await config_manager.create_ab_test(test)

        await config_manager.deactivate_ab_test(test.id)

        tests = config_manager.get_active_ab_tests()
        assert len(tests) == 0


class TestVersioning:
    """Tests for configuration versioning."""

    @pytest.mark.asyncio
    async def test_version_history(self, config_manager, sample_config):
        """Test version history is maintained."""
        # ConfigurationManager starts at version 1 (empty state)
        # Each load_from_dict increments the version
        await config_manager.load_from_dict(sample_config)  # version 2
        await config_manager.load_from_dict(sample_config)  # version 3
        await config_manager.load_from_dict(sample_config)  # version 4

        state = config_manager.get_state()

        # Version history contains entries for versions 2, 3, 4
        assert len(state.version_history) == 3
        assert state.current_version == 4

    @pytest.mark.asyncio
    async def test_version_history_limit(self, config_manager, sample_config):
        """Test version history is limited."""
        # Load more configs than the history limit
        for _ in range(15):
            await config_manager.load_from_dict(sample_config)

        state = config_manager.get_state()

        assert len(state.version_history) <= state.max_history_versions

    @pytest.mark.asyncio
    async def test_rollback(self, config_manager):
        """Test configuration rollback."""
        # Load initial config
        await config_manager.load_from_dict(
            {
                "endpoints": {
                    "v1": {
                        "type": "llm",
                        "model_id": "v1",
                        "endpoint_url": "http://v1",
                    }
                }
            }
        )

        # Load updated config
        await config_manager.load_from_dict(
            {
                "endpoints": {
                    "v2": {
                        "type": "llm",
                        "model_id": "v2",
                        "endpoint_url": "http://v2",
                    }
                }
            }
        )

        assert "v2" in config_manager.get_state().endpoints
        assert "v1" not in config_manager.get_state().endpoints

        # Rollback
        await config_manager.rollback()

        assert "v1" in config_manager.get_state().endpoints

    @pytest.mark.asyncio
    async def test_rollback_no_history(self, config_manager):
        """Test rollback with no history raises error."""
        with pytest.raises(ValueError, match="No version history"):
            await config_manager.rollback()


class TestCallbacks:
    """Tests for configuration change callbacks."""

    @pytest.mark.asyncio
    async def test_callback_on_load(self, config_manager, sample_config):
        """Test callback is called on configuration load."""
        callback_called = []

        def callback(state):
            callback_called.append(state.current_version)

        config_manager.register_callback(callback)
        await config_manager.load_from_dict(sample_config)

        assert len(callback_called) == 1

    @pytest.mark.asyncio
    async def test_async_callback(self, config_manager, sample_config):
        """Test async callback works."""
        callback_called = []

        async def callback(state):
            callback_called.append(state.current_version)

        config_manager.register_callback(callback)
        await config_manager.load_from_dict(sample_config)

        assert len(callback_called) == 1


class TestExport:
    """Tests for configuration export."""

    @pytest.mark.asyncio
    async def test_export_yaml(self, config_manager, sample_config):
        """Test YAML export."""
        await config_manager.load_from_dict(sample_config)

        yaml_content = config_manager.export_yaml()

        # Should be valid YAML
        parsed = yaml.safe_load(yaml_content)
        assert "endpoints" in parsed
        assert "test-llm" in parsed["endpoints"]
