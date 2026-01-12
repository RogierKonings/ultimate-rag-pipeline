"""Tests for degradation manager."""

import pytest
from resilience.circuit_breaker import CircuitState
from resilience.config import CircuitBreakerConfig, ResilienceConfig
from resilience.degradation import (
    DegradationLevel,
    DegradationManager,
    get_degradation_manager,
    reset_degradation_manager,
)


class TestDegradationManagerInitialization:
    """Tests for DegradationManager initialization."""

    def test_default_initialization(self):
        """Test manager initializes with defaults."""
        manager = DegradationManager()

        assert manager.config is not None
        assert len(manager._circuit_breakers) == 0
        assert len(manager._critical_circuits) == 0

    def test_custom_config_initialization(self):
        """Test manager initializes with custom config."""
        config = ResilienceConfig(
            circuit_breaker=CircuitBreakerConfig(failure_threshold=10),
        )
        manager = DegradationManager(config)

        assert manager.config.circuit_breaker.failure_threshold == 10


class TestCircuitRegistration:
    """Tests for circuit breaker registration."""

    @pytest.fixture
    def manager(self):
        """Create a fresh DegradationManager."""
        return DegradationManager()

    def test_register_circuit(self, manager):
        """Test registering a circuit breaker."""
        circuit = manager.register_circuit("test_service")

        assert circuit is not None
        assert circuit.name == "test_service"
        assert manager.has_circuit("test_service")

    def test_register_circuit_with_custom_config(self, manager):
        """Test registering circuit with custom config."""
        config = CircuitBreakerConfig(failure_threshold=10)
        circuit = manager.register_circuit("test_service", config=config)

        assert circuit.config.failure_threshold == 10

    def test_register_critical_circuit(self, manager):
        """Test registering a critical circuit."""
        manager.register_circuit("critical_service", critical=True)

        assert "critical_service" in manager._critical_circuits

    def test_register_duplicate_circuit_raises(self, manager):
        """Test registering duplicate circuit raises error."""
        manager.register_circuit("test_service")

        with pytest.raises(ValueError, match="already registered"):
            manager.register_circuit("test_service")

    def test_get_circuit(self, manager):
        """Test getting a registered circuit."""
        manager.register_circuit("test_service")

        circuit = manager.get_circuit("test_service")

        assert circuit is not None
        assert circuit.name == "test_service"

    def test_get_unregistered_circuit_raises(self, manager):
        """Test getting unregistered circuit raises error."""
        with pytest.raises(KeyError, match="not registered"):
            manager.get_circuit("nonexistent")

    def test_has_circuit(self, manager):
        """Test has_circuit method."""
        manager.register_circuit("test_service")

        assert manager.has_circuit("test_service") is True
        assert manager.has_circuit("nonexistent") is False

    def test_unregister_circuit(self, manager):
        """Test unregistering a circuit."""
        manager.register_circuit("test_service", critical=True)

        manager.unregister_circuit("test_service")

        assert manager.has_circuit("test_service") is False
        assert "test_service" not in manager._critical_circuits

    def test_unregister_nonexistent_circuit_raises(self, manager):
        """Test unregistering nonexistent circuit raises error."""
        with pytest.raises(KeyError, match="not registered"):
            manager.unregister_circuit("nonexistent")


class TestDegradationLevel:
    """Tests for degradation level calculation."""

    @pytest.fixture
    def manager(self):
        """Create a DegradationManager with test circuits."""
        mgr = DegradationManager()
        mgr.register_circuit("llm_gateway", critical=True)
        mgr.register_circuit("retrieval", critical=True)
        mgr.register_circuit("guardrails", critical=False)
        return mgr

    def test_normal_when_all_closed(self, manager):
        """Test NORMAL level when all circuits are CLOSED."""
        level = manager.degradation_level

        assert level == DegradationLevel.NORMAL

    def test_normal_with_no_circuits(self):
        """Test NORMAL level with no registered circuits."""
        manager = DegradationManager()

        assert manager.degradation_level == DegradationLevel.NORMAL

    def test_minimal_when_critical_circuit_open(self, manager):
        """Test MINIMAL level when critical circuit is OPEN."""
        # Open the critical LLM circuit
        llm_circuit = manager.get_circuit("llm_gateway")
        error = Exception("test error")
        for _ in range(5):  # Default threshold is 5
            llm_circuit.record_failure(error)

        assert llm_circuit.state == CircuitState.OPEN
        assert manager.degradation_level == DegradationLevel.MINIMAL

    def test_degraded_when_non_critical_circuit_open(self, manager):
        """Test DEGRADED level when non-critical circuit is OPEN."""
        # Open the non-critical guardrails circuit
        guardrails_circuit = manager.get_circuit("guardrails")
        error = Exception("test error")
        for _ in range(5):
            guardrails_circuit.record_failure(error)

        assert guardrails_circuit.state == CircuitState.OPEN
        assert manager.degradation_level == DegradationLevel.DEGRADED

    def test_degraded_when_circuit_half_open(self, manager):
        """Test DEGRADED level when any circuit is HALF_OPEN."""
        llm_circuit = manager.get_circuit("llm_gateway")
        llm_circuit._state = CircuitState.HALF_OPEN

        assert manager.degradation_level == DegradationLevel.DEGRADED

    def test_minimal_takes_precedence(self, manager):
        """Test MINIMAL takes precedence over DEGRADED."""
        # Open critical circuit
        llm_circuit = manager.get_circuit("llm_gateway")
        error = Exception("test error")
        for _ in range(5):
            llm_circuit.record_failure(error)

        # Also open non-critical circuit
        guardrails_circuit = manager.get_circuit("guardrails")
        for _ in range(5):
            guardrails_circuit.record_failure(error)

        assert manager.degradation_level == DegradationLevel.MINIMAL


class TestHealthyUnhealthyCircuits:
    """Tests for healthy/unhealthy circuit tracking."""

    @pytest.fixture
    def manager(self):
        """Create a DegradationManager with test circuits."""
        mgr = DegradationManager()
        mgr.register_circuit("circuit1")
        mgr.register_circuit("circuit2")
        mgr.register_circuit("circuit3")
        return mgr

    def test_all_healthy_initially(self, manager):
        """Test all circuits are healthy initially."""
        assert len(manager.healthy_circuits) == 3
        assert len(manager.unhealthy_circuits) == 0

    def test_unhealthy_circuits_tracked(self, manager):
        """Test unhealthy circuits are tracked."""
        circuit1 = manager.get_circuit("circuit1")
        error = Exception("test error")
        for _ in range(5):
            circuit1.record_failure(error)

        assert "circuit1" not in manager.healthy_circuits
        assert "circuit1" in manager.unhealthy_circuits
        assert "circuit2" in manager.healthy_circuits
        assert "circuit3" in manager.healthy_circuits


class TestDegradationManagerStatus:
    """Tests for status reporting."""

    @pytest.fixture
    def manager(self):
        """Create a DegradationManager with test circuits."""
        mgr = DegradationManager()
        mgr.register_circuit("llm_gateway", critical=True)
        mgr.register_circuit("retrieval", critical=False)
        return mgr

    def test_get_status_structure(self, manager):
        """Test status response structure."""
        status = manager.get_status()

        assert "degradation_level" in status
        assert "circuits" in status
        assert "summary" in status

        assert "llm_gateway" in status["circuits"]
        assert "retrieval" in status["circuits"]

        assert status["summary"]["total"] == 2
        assert "critical_circuits" in status["summary"]

    def test_status_reflects_circuit_states(self, manager):
        """Test status reflects actual circuit states."""
        # Open one circuit
        llm_circuit = manager.get_circuit("llm_gateway")
        error = Exception("test error")
        for _ in range(5):
            llm_circuit.record_failure(error)

        status = manager.get_status()

        assert status["degradation_level"] == "minimal"
        assert status["circuits"]["llm_gateway"]["state"] == "open"
        assert status["circuits"]["retrieval"]["state"] == "closed"
        assert status["summary"]["healthy"] == 1
        assert status["summary"]["failing"] == 1

    def test_status_includes_critical_flag(self, manager):
        """Test status includes critical flag for circuits."""
        status = manager.get_status()

        assert status["circuits"]["llm_gateway"]["critical"] is True
        assert status["circuits"]["retrieval"]["critical"] is False


class TestCircuitReset:
    """Tests for circuit reset operations."""

    @pytest.fixture
    def manager(self):
        """Create a DegradationManager with failing circuits."""
        mgr = DegradationManager()
        mgr.register_circuit("circuit1")
        mgr.register_circuit("circuit2")

        # Open both circuits
        error = Exception("test error")
        for circuit_name in ["circuit1", "circuit2"]:
            circuit = mgr.get_circuit(circuit_name)
            for _ in range(5):
                circuit.record_failure(error)

        return mgr

    def test_reset_single_circuit(self, manager):
        """Test resetting a single circuit."""
        assert manager.get_circuit("circuit1").state == CircuitState.OPEN

        manager.reset_circuit("circuit1")

        assert manager.get_circuit("circuit1").state == CircuitState.CLOSED
        assert manager.get_circuit("circuit2").state == CircuitState.OPEN

    def test_reset_all_circuits(self, manager):
        """Test resetting all circuits."""
        manager.reset_all_circuits()

        assert manager.get_circuit("circuit1").state == CircuitState.CLOSED
        assert manager.get_circuit("circuit2").state == CircuitState.CLOSED
        assert manager.degradation_level == DegradationLevel.NORMAL


class TestAvailableFeatures:
    """Tests for feature availability mapping."""

    def test_all_features_available_by_default(self):
        """Test all features available when no circuits registered."""
        manager = DegradationManager()

        features = manager.get_available_features()

        assert features["llm_generation"] is True
        assert features["document_retrieval"] is True
        assert features["query_embedding"] is True
        assert features["content_filtering"] is True

    def test_feature_unavailable_when_circuit_open(self):
        """Test feature unavailable when corresponding circuit is OPEN."""
        manager = DegradationManager()
        manager.register_circuit("llm_gateway", critical=True)

        # Open the circuit
        circuit = manager.get_circuit("llm_gateway")
        error = Exception("test error")
        for _ in range(5):
            circuit.record_failure(error)

        features = manager.get_available_features()

        assert features["llm_generation"] is False


class TestGlobalDegradationManager:
    """Tests for global degradation manager singleton."""

    def setup_method(self):
        """Reset global manager before each test."""
        reset_degradation_manager()

    def test_get_degradation_manager_creates_singleton(self):
        """Test get_degradation_manager creates singleton."""
        manager1 = get_degradation_manager()
        manager2 = get_degradation_manager()

        assert manager1 is manager2

    def test_reset_degradation_manager(self):
        """Test resetting the global manager."""
        manager1 = get_degradation_manager()
        manager1.register_circuit("test_circuit")

        reset_degradation_manager()
        manager2 = get_degradation_manager()

        assert manager1 is not manager2
        assert manager2.has_circuit("test_circuit") is False
