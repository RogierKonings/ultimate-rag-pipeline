"""Degradation manager for system-wide resilience coordination.

This module provides centralized management of circuit breakers and
calculates overall system degradation level based on service health.

Degradation Levels:
- NORMAL: All services healthy, full functionality
- DEGRADED: Some services failing, reduced functionality
- MINIMAL: Critical services failing, minimal functionality
"""

import logging
from enum import Enum
from typing import Dict, List, Optional

from .circuit_breaker import CircuitBreaker, CircuitState
from .config import CircuitBreakerConfig, ResilienceConfig


logger = logging.getLogger(__name__)


class DegradationLevel(str, Enum):
    """System degradation levels."""

    NORMAL = "normal"  # All services healthy
    DEGRADED = "degraded"  # Some services failing
    MINIMAL = "minimal"  # Critical services failing


class DegradationManager:
    """Manages system-wide circuit breakers and degradation state.

    The DegradationManager provides:
    - Centralized circuit breaker registration and access
    - Overall system health calculation
    - Degradation level determination
    - Status reporting for observability

    Usage:
        manager = DegradationManager()

        # Register circuits for services
        manager.register_circuit("llm_gateway", critical=True)
        manager.register_circuit("retrieval", critical=True)
        manager.register_circuit("guardrails", critical=False)

        # Get circuit for use
        llm_circuit = manager.get_circuit("llm_gateway")

        # Check system status
        level = manager.degradation_level
        status = manager.get_status()
    """

    def __init__(self, config: Optional[ResilienceConfig] = None):
        """Initialize degradation manager.

        Args:
            config: Resilience configuration, uses defaults if not provided
        """
        self.config = config or ResilienceConfig()
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._critical_circuits: List[str] = []

    def register_circuit(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
        critical: bool = False,
    ) -> CircuitBreaker:
        """Register a circuit breaker for a service.

        Args:
            name: Unique identifier for the circuit (e.g., "llm_gateway")
            config: Optional circuit-specific configuration
            critical: Whether this circuit is critical for system operation

        Returns:
            The registered CircuitBreaker instance

        Raises:
            ValueError: If a circuit with this name already exists
        """
        if name in self._circuit_breakers:
            raise ValueError(f"Circuit '{name}' already registered")

        circuit_config = config or self.config.circuit_breaker
        circuit = CircuitBreaker(name, circuit_config)
        self._circuit_breakers[name] = circuit

        if critical:
            self._critical_circuits.append(name)

        logger.info(
            "Registered circuit breaker '%s' (critical=%s)",
            name,
            critical,
            extra={"circuit_name": name, "critical": critical},
        )

        return circuit

    def get_circuit(self, name: str) -> CircuitBreaker:
        """Get a circuit breaker by name.

        Args:
            name: Circuit identifier

        Returns:
            CircuitBreaker instance

        Raises:
            KeyError: If circuit is not registered
        """
        if name not in self._circuit_breakers:
            raise KeyError(f"Circuit '{name}' not registered")
        return self._circuit_breakers[name]

    def has_circuit(self, name: str) -> bool:
        """Check if a circuit is registered.

        Args:
            name: Circuit identifier

        Returns:
            True if circuit exists
        """
        return name in self._circuit_breakers

    def unregister_circuit(self, name: str) -> None:
        """Remove a circuit breaker.

        Args:
            name: Circuit identifier

        Raises:
            KeyError: If circuit is not registered
        """
        if name not in self._circuit_breakers:
            raise KeyError(f"Circuit '{name}' not registered")

        del self._circuit_breakers[name]
        if name in self._critical_circuits:
            self._critical_circuits.remove(name)

        logger.info(
            "Unregistered circuit breaker '%s'",
            name,
            extra={"circuit_name": name},
        )

    @property
    def degradation_level(self) -> DegradationLevel:
        """Calculate overall system degradation level.

        Logic:
        - MINIMAL: Any critical circuit is OPEN
        - DEGRADED: Any non-critical circuit is OPEN or any circuit is HALF_OPEN
        - NORMAL: All circuits are CLOSED

        Returns:
            Current degradation level
        """
        if not self._circuit_breakers:
            return DegradationLevel.NORMAL

        # Check critical circuits first
        for name in self._critical_circuits:
            circuit = self._circuit_breakers[name]
            if circuit.state == CircuitState.OPEN:
                return DegradationLevel.MINIMAL

        # Check all circuits for degraded state
        has_open = False
        has_half_open = False

        for circuit in self._circuit_breakers.values():
            state = circuit.state
            if state == CircuitState.OPEN:
                has_open = True
            elif state == CircuitState.HALF_OPEN:
                has_half_open = True

        if has_open or has_half_open:
            return DegradationLevel.DEGRADED

        return DegradationLevel.NORMAL

    @property
    def healthy_circuits(self) -> List[str]:
        """Get list of healthy (CLOSED) circuits.

        Returns:
            List of circuit names in CLOSED state
        """
        return [
            name
            for name, circuit in self._circuit_breakers.items()
            if circuit.state == CircuitState.CLOSED
        ]

    @property
    def unhealthy_circuits(self) -> List[str]:
        """Get list of unhealthy (OPEN or HALF_OPEN) circuits.

        Returns:
            List of circuit names not in CLOSED state
        """
        return [
            name
            for name, circuit in self._circuit_breakers.items()
            if circuit.state != CircuitState.CLOSED
        ]

    def get_status(self) -> Dict:
        """Get comprehensive status of all circuits.

        Returns:
            Dictionary with system status including:
            - degradation_level: Current overall level
            - circuits: Status of each registered circuit
            - summary: Quick health summary
        """
        circuits_status = {}
        healthy_count = 0
        degraded_count = 0
        failing_count = 0

        for name, circuit in self._circuit_breakers.items():
            state = circuit.state
            is_critical = name in self._critical_circuits

            circuits_status[name] = {
                "state": state.value,
                "critical": is_critical,
                "failure_count": circuit.failure_count,
                "metrics": circuit.get_metrics(),
            }

            if state == CircuitState.CLOSED:
                healthy_count += 1
            elif state == CircuitState.HALF_OPEN:
                degraded_count += 1
            else:  # OPEN
                failing_count += 1

        return {
            "degradation_level": self.degradation_level.value,
            "circuits": circuits_status,
            "summary": {
                "total": len(self._circuit_breakers),
                "healthy": healthy_count,
                "degraded": degraded_count,
                "failing": failing_count,
                "critical_circuits": self._critical_circuits,
            },
        }

    def reset_circuit(self, name: str) -> None:
        """Reset a specific circuit to CLOSED state.

        Args:
            name: Circuit identifier

        Raises:
            KeyError: If circuit is not registered
        """
        circuit = self.get_circuit(name)
        circuit.reset()
        logger.info(
            "Reset circuit '%s' via DegradationManager",
            name,
            extra={"circuit_name": name},
        )

    def reset_all_circuits(self) -> None:
        """Reset all circuits to CLOSED state."""
        for name, circuit in self._circuit_breakers.items():
            circuit.reset()
        logger.info(
            "Reset all %d circuits",
            len(self._circuit_breakers),
            extra={"circuit_count": len(self._circuit_breakers)},
        )

    def get_available_features(self) -> Dict[str, bool]:
        """Get map of features to availability based on circuit states.

        Returns:
            Dictionary mapping feature names to availability
        """
        # Map circuit names to features
        feature_map = {
            "llm_gateway": "llm_generation",
            "retrieval": "document_retrieval",
            "embedding": "query_embedding",
            "guardrails": "content_filtering",
        }

        features = {}
        for circuit_name, feature_name in feature_map.items():
            if circuit_name in self._circuit_breakers:
                circuit = self._circuit_breakers[circuit_name]
                features[feature_name] = circuit.state == CircuitState.CLOSED
            else:
                # Circuit not registered, assume available
                features[feature_name] = True

        return features


# Global degradation manager instance
_manager: Optional[DegradationManager] = None


def get_degradation_manager() -> DegradationManager:
    """Get or create the global degradation manager.

    Returns:
        Global DegradationManager instance
    """
    global _manager
    if _manager is None:
        _manager = DegradationManager()
    return _manager


def reset_degradation_manager() -> None:
    """Reset the global degradation manager.

    Useful for testing.
    """
    global _manager
    _manager = None
