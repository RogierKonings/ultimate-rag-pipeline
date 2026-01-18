"""Tests for degradation manager."""

import pytest

from resilience import (
    CircuitState,
    DegradationMode,
    RetrievalDegradationManager,
    ResilienceConfig,
    reset_degradation_manager,
)


class TestRetrievalDegradationManager:
    """Tests for RetrievalDegradationManager class."""

    @pytest.fixture
    def manager(self) -> RetrievalDegradationManager:
        """Create a fresh degradation manager."""
        reset_degradation_manager()
        return RetrievalDegradationManager()

    def test_all_healthy_returns_hybrid_full(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """All circuits closed should return HYBRID_FULL mode."""
        assert manager.get_current_mode() == DegradationMode.HYBRID_FULL

    def test_qdrant_down_returns_keyword_only(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """Qdrant circuit open should return KEYWORD_ONLY mode."""
        manager.qdrant_breaker._state = CircuitState.OPEN

        assert manager.get_current_mode() == DegradationMode.KEYWORD_ONLY

    def test_opensearch_down_returns_semantic_only(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """OpenSearch circuit open should return SEMANTIC_ONLY mode."""
        manager.opensearch_breaker._state = CircuitState.OPEN

        assert manager.get_current_mode() == DegradationMode.SEMANTIC_ONLY

    def test_reranker_down_returns_hybrid_no_rerank(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """Reranker circuit open should return HYBRID_NO_RERANK mode."""
        manager.reranker_breaker._state = CircuitState.OPEN

        assert manager.get_current_mode() == DegradationMode.HYBRID_NO_RERANK

    def test_both_search_backends_down_returns_minimal(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """Both Qdrant and OpenSearch down should return MINIMAL mode."""
        manager.qdrant_breaker._state = CircuitState.OPEN
        manager.opensearch_breaker._state = CircuitState.OPEN

        assert manager.get_current_mode() == DegradationMode.MINIMAL

    def test_should_use_semantic_in_hybrid_full(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """Should use semantic search in HYBRID_FULL mode."""
        assert manager.should_use_semantic() is True

    def test_should_not_use_semantic_when_qdrant_down(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """Should not use semantic search when Qdrant is down."""
        manager.qdrant_breaker._state = CircuitState.OPEN

        assert manager.should_use_semantic() is False

    def test_should_use_keyword_in_hybrid_full(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """Should use keyword search in HYBRID_FULL mode."""
        assert manager.should_use_keyword() is True

    def test_should_not_use_keyword_when_opensearch_down(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """Should not use keyword search when OpenSearch is down."""
        manager.opensearch_breaker._state = CircuitState.OPEN

        assert manager.should_use_keyword() is False

    def test_should_use_reranker_in_hybrid_full(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """Should use reranker in HYBRID_FULL mode."""
        assert manager.should_use_reranker() is True

    def test_should_not_use_reranker_when_reranker_down(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """Should not use reranker when reranker is down."""
        manager.reranker_breaker._state = CircuitState.OPEN

        assert manager.should_use_reranker() is False

    def test_get_status_returns_complete_info(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """get_status should return complete degradation info."""
        status = manager.get_status()

        assert status.mode == DegradationMode.HYBRID_FULL
        assert status.qdrant_healthy is True
        assert status.opensearch_healthy is True
        assert status.reranker_healthy is True
        assert "qdrant" in status.components_available
        assert len(status.components_unavailable) == 0

    def test_get_status_with_failure(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """get_status should reflect component failures."""
        manager.qdrant_breaker._state = CircuitState.OPEN

        status = manager.get_status()

        assert status.mode == DegradationMode.KEYWORD_ONLY
        assert status.qdrant_healthy is False
        assert "qdrant" in status.components_unavailable
        assert "opensearch" in status.components_available

    def test_reset_all_clears_circuits(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """reset_all should reset all circuit breakers."""
        manager.qdrant_breaker._state = CircuitState.OPEN
        manager.opensearch_breaker._state = CircuitState.OPEN

        manager.reset_all()

        assert manager.qdrant_breaker.state == CircuitState.CLOSED
        assert manager.opensearch_breaker.state == CircuitState.CLOSED
        assert manager.get_current_mode() == DegradationMode.HYBRID_FULL

    def test_get_circuit_statuses(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """get_circuit_statuses should return all circuit metrics."""
        statuses = manager.get_circuit_statuses()

        assert "qdrant" in statuses
        assert "opensearch" in statuses
        assert "reranker" in statuses
        assert statuses["qdrant"]["state"] == "closed"

    def test_custom_config(self) -> None:
        """Manager should use custom config when provided."""
        from resilience import CircuitBreakerConfig

        config = ResilienceConfig(
            qdrant_circuit=CircuitBreakerConfig(failure_threshold=10),
        )
        manager = RetrievalDegradationManager(config)

        assert manager.qdrant_breaker.config.failure_threshold == 10
