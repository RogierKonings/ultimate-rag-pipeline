"""Degradation manager for retrieval service.

Manages degradation modes based on circuit breaker states, enabling
graceful degradation when backends become unhealthy.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum

from .circuit_breaker import CircuitBreaker, CircuitState
from .config import ResilienceConfig

logger = logging.getLogger(__name__)


class DegradationMode(str, Enum):
    """Retrieval service degradation modes."""

    HYBRID_FULL = "hybrid_full"  # All components healthy
    SEMANTIC_ONLY = "semantic_only"  # OpenSearch down, use Qdrant only
    KEYWORD_ONLY = "keyword_only"  # Qdrant down, use OpenSearch only
    HYBRID_NO_RERANK = "hybrid_no_rerank"  # Reranker down, skip reranking
    MINIMAL = "minimal"  # Multiple failures, best effort


@dataclass
class DegradationStatus:
    """Current degradation status with details."""

    mode: DegradationMode
    qdrant_healthy: bool
    opensearch_healthy: bool
    reranker_healthy: bool
    components_available: list[str] = field(default_factory=list)
    components_unavailable: list[str] = field(default_factory=list)


class RetrievalDegradationManager:
    """Manages degradation modes based on circuit breaker states.

    Determines which retrieval mode to use based on health of
    backend components (Qdrant, OpenSearch, Reranker).
    """

    def __init__(self, config: ResilienceConfig | None = None):
        """Initialize degradation manager.

        Args:
            config: Resilience configuration for circuit breakers
        """
        self.config = config or ResilienceConfig()

        # Create circuit breakers for each backend
        self.qdrant_breaker = CircuitBreaker("qdrant", self.config.qdrant_circuit)
        self.opensearch_breaker = CircuitBreaker(
            "opensearch", self.config.opensearch_circuit
        )
        self.reranker_breaker = CircuitBreaker("reranker", self.config.reranker_circuit)

    def get_current_mode(self) -> DegradationMode:
        """Determine current degradation mode from circuit states."""
        qdrant_ok = self.qdrant_breaker.state != CircuitState.OPEN
        opensearch_ok = self.opensearch_breaker.state != CircuitState.OPEN
        reranker_ok = self.reranker_breaker.state != CircuitState.OPEN

        if qdrant_ok and opensearch_ok and reranker_ok:
            return DegradationMode.HYBRID_FULL

        if not qdrant_ok and not opensearch_ok:
            return DegradationMode.MINIMAL

        if not qdrant_ok:
            return DegradationMode.KEYWORD_ONLY

        if not opensearch_ok:
            return DegradationMode.SEMANTIC_ONLY

        if not reranker_ok:
            return DegradationMode.HYBRID_NO_RERANK

        return DegradationMode.HYBRID_FULL

    def get_status(self) -> DegradationStatus:
        """Get detailed degradation status."""
        mode = self.get_current_mode()

        qdrant_healthy = self.qdrant_breaker.state != CircuitState.OPEN
        opensearch_healthy = self.opensearch_breaker.state != CircuitState.OPEN
        reranker_healthy = self.reranker_breaker.state != CircuitState.OPEN

        available = []
        unavailable = []

        if qdrant_healthy:
            available.append("qdrant")
        else:
            unavailable.append("qdrant")

        if opensearch_healthy:
            available.append("opensearch")
        else:
            unavailable.append("opensearch")

        if reranker_healthy:
            available.append("reranker")
        else:
            unavailable.append("reranker")

        return DegradationStatus(
            mode=mode,
            qdrant_healthy=qdrant_healthy,
            opensearch_healthy=opensearch_healthy,
            reranker_healthy=reranker_healthy,
            components_available=available,
            components_unavailable=unavailable,
        )

    def should_use_semantic(self) -> bool:
        """Check if semantic search should be used."""
        mode = self.get_current_mode()
        return mode in (
            DegradationMode.HYBRID_FULL,
            DegradationMode.SEMANTIC_ONLY,
            DegradationMode.HYBRID_NO_RERANK,
        )

    def should_use_keyword(self) -> bool:
        """Check if keyword search should be used."""
        mode = self.get_current_mode()
        return mode in (
            DegradationMode.HYBRID_FULL,
            DegradationMode.KEYWORD_ONLY,
            DegradationMode.HYBRID_NO_RERANK,
        )

    def should_use_reranker(self) -> bool:
        """Check if reranker should be used."""
        mode = self.get_current_mode()
        return mode in (
            DegradationMode.HYBRID_FULL,
            DegradationMode.SEMANTIC_ONLY,
            DegradationMode.KEYWORD_ONLY,
        )

    def get_circuit_statuses(self) -> dict:
        """Get status of all circuit breakers."""
        return {
            "qdrant": self.qdrant_breaker.get_metrics(),
            "opensearch": self.opensearch_breaker.get_metrics(),
            "reranker": self.reranker_breaker.get_metrics(),
        }

    def reset_all(self) -> None:
        """Reset all circuit breakers to closed state."""
        self.qdrant_breaker.reset()
        self.opensearch_breaker.reset()
        self.reranker_breaker.reset()
        logger.info("All circuit breakers reset")


# Module-level singleton
_manager: RetrievalDegradationManager | None = None


def get_degradation_manager() -> RetrievalDegradationManager:
    """Get or create the singleton degradation manager."""
    global _manager
    if _manager is None:
        _manager = RetrievalDegradationManager()
    return _manager


def reset_degradation_manager() -> None:
    """Reset the singleton degradation manager (for testing)."""
    global _manager
    _manager = None
