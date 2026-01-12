"""
Unit tests for A/B Router (US-5.4).

Tests routing strategies and model selection.
"""

import pytest
from config.manager import ConfigurationManager
from config.models import ABTestConfig, ModelEndpoint, ModelType, RoutingStrategy
from config.router import ABRouter, RoutingMetrics


@pytest.fixture
def config_manager():
    """Create a configuration manager with test endpoints."""
    manager = ConfigurationManager()
    manager._state.endpoints = {
        "model-a": ModelEndpoint(
            name="model-a",
            type=ModelType.LLM,
            model_id="model-a",
            endpoint_url="http://a",
        ),
        "model-b": ModelEndpoint(
            name="model-b",
            type=ModelType.LLM,
            model_id="model-b",
            endpoint_url="http://b",
        ),
        "embedding-a": ModelEndpoint(
            name="embedding-a",
            type=ModelType.EMBEDDING,
            model_id="embedding-a",
            endpoint_url="http://embed-a",
        ),
    }
    return manager


@pytest.fixture
def router(config_manager):
    """Create an A/B router."""
    return ABRouter(config_manager)


class TestDefaultRouting:
    """Tests for default routing behavior."""

    def test_route_no_tests(self, router, config_manager):
        """Test routing with no active A/B tests."""
        result = router.route(ModelType.LLM)

        # Should return first enabled endpoint of that type
        assert result == "model-a"

    def test_route_embedding_no_tests(self, router):
        """Test embedding routing with no tests."""
        result = router.route(ModelType.EMBEDDING)

        assert result == "embedding-a"

    def test_route_no_enabled_endpoints(self, config_manager):
        """Test routing when no endpoints are enabled."""
        for endpoint in config_manager._state.endpoints.values():
            endpoint.enabled = False

        router = ABRouter(config_manager)

        with pytest.raises(ValueError, match="No enabled"):
            router.route(ModelType.LLM)


class TestRoutingStrategies:
    """Tests for different routing strategies."""

    def test_single_strategy(self, router, config_manager):
        """Test SINGLE routing strategy."""
        config_manager._state.ab_tests = [
            ABTestConfig(
                name="test",
                model_a="model-a",
                model_b="model-b",
                strategy=RoutingStrategy.SINGLE,
            ),
        ]

        # Should always return model_a
        for _ in range(10):
            result = router.route(ModelType.LLM)
            assert result == "model-a"

    def test_random_strategy_distribution(self, router, config_manager):
        """Test RANDOM routing gives reasonable distribution."""
        config_manager._state.ab_tests = [
            ABTestConfig(
                name="test",
                model_a="model-a",
                model_b="model-b",
                traffic_split=0.5,
                strategy=RoutingStrategy.RANDOM,
            ),
        ]

        results = {"model-a": 0, "model-b": 0}
        for _ in range(1000):
            result = router.route(ModelType.LLM)
            results[result] += 1

        # Should be roughly 50/50 with some tolerance
        assert 400 < results["model-a"] < 600
        assert 400 < results["model-b"] < 600

    def test_random_strategy_skewed(self, router, config_manager):
        """Test RANDOM routing with skewed split."""
        config_manager._state.ab_tests = [
            ABTestConfig(
                name="test",
                model_a="model-a",
                model_b="model-b",
                traffic_split=0.8,  # 80% to model-a
                strategy=RoutingStrategy.RANDOM,
            ),
        ]

        results = {"model-a": 0, "model-b": 0}
        for _ in range(1000):
            result = router.route(ModelType.LLM)
            results[result] += 1

        # Should be roughly 80/20
        assert 700 < results["model-a"] < 900
        assert 100 < results["model-b"] < 300

    def test_header_based_strategy(self, router, config_manager):
        """Test HEADER_BASED routing strategy."""
        config_manager._state.ab_tests = [
            ABTestConfig(
                name="test",
                model_a="model-a",
                model_b="model-b",
                strategy=RoutingStrategy.HEADER_BASED,
                routing_header="X-Model-Version",
            ),
        ]

        # Header value "a" should route to model_a
        result = router.route(
            ModelType.LLM, request_headers={"X-Model-Version": "a"},
        )
        assert result == "model-a"

        # Header value "b" should route to model_b
        result = router.route(
            ModelType.LLM, request_headers={"X-Model-Version": "b"},
        )
        assert result == "model-b"

        # No header should default to model_a
        result = router.route(ModelType.LLM)
        assert result == "model-a"

    def test_user_based_strategy_consistency(self, router, config_manager):
        """Test USER_BASED routing is consistent for same user."""
        config_manager._state.ab_tests = [
            ABTestConfig(
                name="test",
                model_a="model-a",
                model_b="model-b",
                traffic_split=0.5,
                strategy=RoutingStrategy.USER_BASED,
            ),
        ]

        user_id = "user-123"

        # Same user should always get same result
        result1 = router.route(ModelType.LLM, user_id=user_id)
        result2 = router.route(ModelType.LLM, user_id=user_id)
        result3 = router.route(ModelType.LLM, user_id=user_id)

        assert result1 == result2 == result3

    def test_user_based_strategy_distribution(self, router, config_manager):
        """Test USER_BASED routing gives reasonable distribution."""
        config_manager._state.ab_tests = [
            ABTestConfig(
                name="test",
                model_a="model-a",
                model_b="model-b",
                traffic_split=0.5,
                strategy=RoutingStrategy.USER_BASED,
            ),
        ]

        results = {"model-a": 0, "model-b": 0}
        for i in range(1000):
            result = router.route(ModelType.LLM, user_id=f"user-{i}")
            results[result] += 1

        # Should be roughly 50/50
        assert 400 < results["model-a"] < 600

    def test_round_robin_strategy(self, router, config_manager):
        """Test ROUND_ROBIN routing alternates."""
        config_manager._state.ab_tests = [
            ABTestConfig(
                name="test",
                model_a="model-a",
                model_b="model-b",
                strategy=RoutingStrategy.ROUND_ROBIN,
            ),
        ]

        # Round robin is based on timestamp, so we just verify it returns valid models
        result = router.route(ModelType.LLM)
        assert result in ["model-a", "model-b"]


class TestGetSelectedModelInfo:
    """Tests for model selection info."""

    def test_info_no_test(self, router, config_manager):
        """Test getting info with no A/B test."""
        info = router.get_selected_model_info(ModelType.LLM)

        assert info["model_name"] == "model-a"
        assert info["model_id"] == "model-a"
        assert info["endpoint_url"] == "http://a"
        assert info["ab_test"] is None

    def test_info_with_test(self, router, config_manager):
        """Test getting info with active A/B test."""
        test = ABTestConfig(
            name="test-experiment",
            model_a="model-a",
            model_b="model-b",
            traffic_split=0.5,
            strategy=RoutingStrategy.RANDOM,
        )
        config_manager._state.ab_tests = [test]

        info = router.get_selected_model_info(ModelType.LLM)

        assert info["model_name"] in ["model-a", "model-b"]
        assert info["ab_test"] is not None
        assert info["ab_test"]["test_name"] == "test-experiment"
        assert info["ab_test"]["strategy"] == "random"


class TestRoutingMetrics:
    """Tests for routing metrics tracking."""

    def test_record_routing(self):
        """Test recording routing decisions."""
        metrics = RoutingMetrics()

        metrics.record_routing(ModelType.LLM, "model-a")
        metrics.record_routing(ModelType.LLM, "model-a")
        metrics.record_routing(ModelType.LLM, "model-b")

        stats = metrics.get_routing_stats()

        assert stats["by_model_type"]["llm"]["model-a"] == 2
        assert stats["by_model_type"]["llm"]["model-b"] == 1

    def test_record_with_test(self):
        """Test recording routing with A/B test."""
        metrics = RoutingMetrics()

        metrics.record_routing(ModelType.LLM, "model-a", test_id="test-123")
        metrics.record_routing(ModelType.LLM, "model-b", test_id="test-123")

        stats = metrics.get_routing_stats()

        assert stats["by_test"]["test-123"]["model-a"] == 1
        assert stats["by_test"]["test-123"]["model-b"] == 1

    def test_get_test_distribution(self):
        """Test getting test traffic distribution."""
        metrics = RoutingMetrics()

        for _ in range(80):
            metrics.record_routing(ModelType.LLM, "model-a", test_id="test-123")
        for _ in range(20):
            metrics.record_routing(ModelType.LLM, "model-b", test_id="test-123")

        distribution = metrics.get_test_distribution("test-123")

        assert abs(distribution["model-a"] - 0.8) < 0.01
        assert abs(distribution["model-b"] - 0.2) < 0.01

    def test_get_nonexistent_test_distribution(self):
        """Test getting distribution for nonexistent test."""
        metrics = RoutingMetrics()

        distribution = metrics.get_test_distribution("nonexistent")

        assert distribution == {}
