"""Integration tests for retrieval resilience."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from resilience import (
    CircuitBreakerConfig,
    CircuitState,
    DegradationMode,
    ResilienceConfig,
    RetrievalDegradationManager,
)
from search.fusion import HybridSearchConfig, HybridSearchResponse
from search.hybrid import HybridSearcher
from search.resilient_hybrid import ResilientHybridSearcher


class TestResilientHybridSearcherIntegration:
    """Integration tests for ResilientHybridSearcher."""

    @pytest.fixture
    def mock_hybrid_searcher(self) -> MagicMock:
        """Create mock hybrid searcher."""
        mock = MagicMock(spec=HybridSearcher)
        mock.config = HybridSearchConfig()
        mock.semantic = MagicMock()
        mock.keyword = MagicMock()
        mock._fusion = MagicMock()
        return mock

    @pytest.fixture
    def degradation_manager(self) -> RetrievalDegradationManager:
        """Create degradation manager with fast circuit breakers."""
        config = ResilienceConfig(
            qdrant_circuit=CircuitBreakerConfig(failure_threshold=2, recovery_timeout=0.1),
            opensearch_circuit=CircuitBreakerConfig(failure_threshold=2, recovery_timeout=0.1),
            reranker_circuit=CircuitBreakerConfig(failure_threshold=2, recovery_timeout=0.1),
        )
        return RetrievalDegradationManager(config)

    @pytest.fixture
    def resilient_searcher(
        self,
        mock_hybrid_searcher: MagicMock,
        degradation_manager: RetrievalDegradationManager,
    ) -> ResilientHybridSearcher:
        """Create resilient searcher with mocks."""
        return ResilientHybridSearcher(mock_hybrid_searcher, degradation_manager)

    @pytest.mark.asyncio
    async def test_search_hybrid_full_mode(
        self,
        resilient_searcher: ResilientHybridSearcher,
        mock_hybrid_searcher: MagicMock,
    ) -> None:
        """Search should use both backends in HYBRID_FULL mode."""
        # Setup mocks
        mock_hybrid_searcher.semantic.search = AsyncMock(
            return_value=MagicMock(results=[], total_found=0)
        )
        mock_hybrid_searcher.keyword.search = AsyncMock(
            return_value=MagicMock(results=[], total_found=0)
        )
        mock_hybrid_searcher._fusion.fuse = MagicMock(return_value=[])

        response = await resilient_searcher.search(
            query="test",
            query_embedding=[0.1] * 768,
            top_k=10,
        )

        assert response.degradation_mode == DegradationMode.HYBRID_FULL.value
        mock_hybrid_searcher.semantic.search.assert_called_once()
        mock_hybrid_searcher.keyword.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_degrades_to_keyword_only(
        self,
        resilient_searcher: ResilientHybridSearcher,
        degradation_manager: RetrievalDegradationManager,
        mock_hybrid_searcher: MagicMock,
    ) -> None:
        """Search should use keyword-only when Qdrant circuit opens."""
        # Force Qdrant circuit open
        degradation_manager.qdrant_breaker._state = CircuitState.OPEN

        mock_hybrid_searcher.search_keyword_only = AsyncMock(
            return_value=HybridSearchResponse(
                results=[],
                total_semantic=0,
                total_keyword=5,
                search_time_ms=10,
                fusion_method=mock_hybrid_searcher.config.fusion_method,
            )
        )

        response = await resilient_searcher.search(
            query="test",
            query_embedding=[0.1] * 768,
        )

        assert response.degradation_mode == DegradationMode.KEYWORD_ONLY.value
        assert "qdrant" in response.components_skipped

    @pytest.mark.asyncio
    async def test_search_degrades_to_semantic_only(
        self,
        resilient_searcher: ResilientHybridSearcher,
        degradation_manager: RetrievalDegradationManager,
        mock_hybrid_searcher: MagicMock,
    ) -> None:
        """Search should use semantic-only when OpenSearch circuit opens."""
        # Force OpenSearch circuit open
        degradation_manager.opensearch_breaker._state = CircuitState.OPEN

        mock_hybrid_searcher.search_semantic_only = AsyncMock(
            return_value=HybridSearchResponse(
                results=[],
                total_semantic=5,
                total_keyword=0,
                search_time_ms=10,
                fusion_method=mock_hybrid_searcher.config.fusion_method,
            )
        )

        response = await resilient_searcher.search(
            query="test",
            query_embedding=[0.1] * 768,
        )

        assert response.degradation_mode == DegradationMode.SEMANTIC_ONLY.value
        assert "opensearch" in response.components_skipped

    @pytest.mark.asyncio
    async def test_search_returns_empty_in_minimal_mode(
        self,
        resilient_searcher: ResilientHybridSearcher,
        degradation_manager: RetrievalDegradationManager,
    ) -> None:
        """Search should return empty results in MINIMAL mode."""
        # Force both circuits open
        degradation_manager.qdrant_breaker._state = CircuitState.OPEN
        degradation_manager.opensearch_breaker._state = CircuitState.OPEN

        response = await resilient_searcher.search(
            query="test",
            query_embedding=[0.1] * 768,
        )

        assert response.degradation_mode == DegradationMode.MINIMAL.value
        assert len(response.results) == 0
        assert "qdrant" in response.components_skipped
        assert "opensearch" in response.components_skipped

    @pytest.mark.asyncio
    async def test_circuit_opens_after_failures(
        self,
        resilient_searcher: ResilientHybridSearcher,
        degradation_manager: RetrievalDegradationManager,
        mock_hybrid_searcher: MagicMock,
    ) -> None:
        """Circuit should open after threshold failures."""
        # Make semantic search fail
        mock_hybrid_searcher.semantic.search = AsyncMock(
            side_effect=ConnectionError("Qdrant unavailable")
        )
        mock_hybrid_searcher.keyword.search = AsyncMock(
            return_value=MagicMock(results=[], total_found=0)
        )
        mock_hybrid_searcher._fusion.fuse = MagicMock(return_value=[])

        # Trigger failures (threshold is 2)
        for _ in range(2):
            await resilient_searcher.search(
                query="test",
                query_embedding=[0.1] * 768,
            )

        # Circuit should now be open
        assert degradation_manager.qdrant_breaker.state == CircuitState.OPEN
        assert degradation_manager.get_current_mode() == DegradationMode.KEYWORD_ONLY

    @pytest.mark.asyncio
    async def test_response_includes_components_used(
        self,
        resilient_searcher: ResilientHybridSearcher,
        mock_hybrid_searcher: MagicMock,
    ) -> None:
        """Response should include components_used list."""
        mock_hybrid_searcher.semantic.search = AsyncMock(
            return_value=MagicMock(results=[], total_found=0)
        )
        mock_hybrid_searcher.keyword.search = AsyncMock(
            return_value=MagicMock(results=[], total_found=0)
        )
        mock_hybrid_searcher._fusion.fuse = MagicMock(return_value=[])

        response = await resilient_searcher.search(
            query="test",
            query_embedding=[0.1] * 768,
        )

        assert "qdrant" in response.components_used
        assert "opensearch" in response.components_used
        assert "reranker" in response.components_used

    @pytest.mark.asyncio
    async def test_hybrid_no_rerank_mode(
        self,
        resilient_searcher: ResilientHybridSearcher,
        degradation_manager: RetrievalDegradationManager,
        mock_hybrid_searcher: MagicMock,
    ) -> None:
        """Search should work in HYBRID_NO_RERANK when reranker is down."""
        # Force reranker circuit open
        degradation_manager.reranker_breaker._state = CircuitState.OPEN

        mock_hybrid_searcher.semantic.search = AsyncMock(
            return_value=MagicMock(results=[], total_found=0)
        )
        mock_hybrid_searcher.keyword.search = AsyncMock(
            return_value=MagicMock(results=[], total_found=0)
        )
        mock_hybrid_searcher._fusion.fuse = MagicMock(return_value=[])

        response = await resilient_searcher.search(
            query="test",
            query_embedding=[0.1] * 768,
        )

        assert response.degradation_mode == DegradationMode.HYBRID_NO_RERANK.value
        assert "reranker" in response.components_skipped
        # Both search backends should still be used
        mock_hybrid_searcher.semantic.search.assert_called_once()
        mock_hybrid_searcher.keyword.search.assert_called_once()
