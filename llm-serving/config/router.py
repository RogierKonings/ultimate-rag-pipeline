"""
A/B test router for LLM Serving Layer.

Routes requests to different models based on A/B test configuration.
Supports multiple routing strategies including random, user-based,
header-based, and round-robin.
"""

import hashlib
import logging
import random
import time

from .manager import ConfigurationManager
from .models import ABTestConfig, ModelType, RoutingStrategy

logger = logging.getLogger(__name__)


class ABRouter:
    """
    Routes requests to different models based on A/B test configuration.

    Supports multiple strategies:
    - SINGLE: Always use primary model
    - RANDOM: Random selection with weights
    - ROUND_ROBIN: Alternate between models
    - HEADER_BASED: Based on request header
    - USER_BASED: Consistent routing based on user ID hash
    """

    def __init__(self, config_manager: ConfigurationManager):
        """
        Initialize router with configuration manager.

        Args:
            config_manager: Configuration manager instance
        """
        self.config_manager = config_manager

    def route(
        self,
        model_type: ModelType,
        request_headers: dict[str, str] | None = None,
        user_id: str | None = None,
    ) -> str:
        """
        Determine which model endpoint to use.

        Args:
            model_type: Type of model (LLM, embedding, reranker)
            request_headers: Optional request headers for header-based routing
            user_id: Optional user ID for user-based routing

        Returns:
            Name of the model endpoint to use
        """
        # Get active tests for this model type
        active_tests = self._get_tests_for_type(model_type)

        if not active_tests:
            # No active tests, return default endpoint
            return self._get_default_endpoint(model_type)

        # Use first active test (could be extended to support multiple)
        test = active_tests[0]

        return self._select_model(test, request_headers, user_id)

    def _get_tests_for_type(self, model_type: ModelType) -> list[ABTestConfig]:
        """Get active A/B tests that apply to the given model type."""
        tests = []

        for test in self.config_manager.get_active_ab_tests():
            endpoint_a = self.config_manager.get_endpoint(test.model_a)
            endpoint_b = self.config_manager.get_endpoint(test.model_b)

            if (
                endpoint_a
                and endpoint_a.type == model_type
                or endpoint_b
                and endpoint_b.type == model_type
            ):
                tests.append(test)

        return tests

    def _get_default_endpoint(self, model_type: ModelType) -> str:
        """Get default endpoint for a model type."""
        endpoints = self.config_manager.get_all_endpoints(model_type)
        enabled_endpoints = [e for e in endpoints if e.enabled]

        if not enabled_endpoints:
            raise ValueError(f"No enabled {model_type.value} endpoints found")

        return enabled_endpoints[0].name

    def _select_model(
        self,
        test: ABTestConfig,
        request_headers: dict[str, str] | None,
        user_id: str | None,
    ) -> str:
        """Select model based on test strategy."""

        if test.strategy == RoutingStrategy.SINGLE:
            return test.model_a

        if test.strategy == RoutingStrategy.RANDOM:
            return test.model_a if random.random() < test.traffic_split else test.model_b

        if test.strategy == RoutingStrategy.ROUND_ROBIN:
            # Simple implementation using timestamp
            return test.model_a if int(time.time()) % 2 == 0 else test.model_b

        if test.strategy == RoutingStrategy.HEADER_BASED:
            if request_headers:
                header_value = request_headers.get(test.routing_header, "a")
                return test.model_a if header_value.lower() == "a" else test.model_b
            return test.model_a

        if test.strategy == RoutingStrategy.USER_BASED:
            if user_id:
                # Hash user ID for consistent routing
                user_hash = int(hashlib.md5(user_id.encode()).hexdigest(), 16)
                return (
                    test.model_a if (user_hash % 100) < (test.traffic_split * 100) else test.model_b
                )

            # No user ID, fall back to model_a
            return test.model_a

        return test.model_a

    def get_selected_model_info(
        self,
        model_type: ModelType,
        request_headers: dict[str, str] | None = None,
        user_id: str | None = None,
    ) -> dict:
        """
        Get information about which model was selected and why.

        Args:
            model_type: Type of model
            request_headers: Optional request headers
            user_id: Optional user ID

        Returns:
            Dict with model selection details
        """
        model_name = self.route(model_type, request_headers, user_id)
        endpoint = self.config_manager.get_endpoint(model_name)

        # Find applicable test
        active_tests = self._get_tests_for_type(model_type)
        test_info = None
        if active_tests:
            test = active_tests[0]
            test_info = {
                "test_id": str(test.id),
                "test_name": test.name,
                "strategy": test.strategy.value,
                "traffic_split": test.traffic_split,
            }

        return {
            "model_name": model_name,
            "model_id": endpoint.model_id if endpoint else None,
            "endpoint_url": endpoint.endpoint_url if endpoint else None,
            "ab_test": test_info,
        }


class RoutingMetrics:
    """Tracks routing decisions for observability."""

    def __init__(self):
        """Initialize routing metrics."""
        self._routing_counts: dict[str, dict[str, int]] = {}
        self._test_routing_counts: dict[str, dict[str, int]] = {}

    def record_routing(
        self,
        model_type: ModelType,
        selected_model: str,
        test_id: str | None = None,
    ) -> None:
        """
        Record a routing decision.

        Args:
            model_type: Type of model
            selected_model: Name of selected model
            test_id: Optional A/B test ID
        """
        type_key = model_type.value

        if type_key not in self._routing_counts:
            self._routing_counts[type_key] = {}

        if selected_model not in self._routing_counts[type_key]:
            self._routing_counts[type_key][selected_model] = 0

        self._routing_counts[type_key][selected_model] += 1

        if test_id:
            if test_id not in self._test_routing_counts:
                self._test_routing_counts[test_id] = {}

            if selected_model not in self._test_routing_counts[test_id]:
                self._test_routing_counts[test_id][selected_model] = 0

            self._test_routing_counts[test_id][selected_model] += 1

    def get_routing_stats(self) -> dict:
        """Get routing statistics."""
        return {
            "by_model_type": self._routing_counts,
            "by_test": self._test_routing_counts,
        }

    def get_test_distribution(self, test_id: str) -> dict:
        """Get traffic distribution for a specific A/B test."""
        if test_id not in self._test_routing_counts:
            return {}

        counts = self._test_routing_counts[test_id]
        total = sum(counts.values())

        if total == 0:
            return {}

        return {model: count / total for model, count in counts.items()}
