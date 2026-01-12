"""
Unit tests for Monitoring Models (US-5.6).

Tests Pydantic models for health, metrics, alerts, and anomaly detection config.
"""

from datetime import UTC, datetime

from monitoring.models import (
    Alert,
    AlertSeverity,
    AnomalyDetectionConfig,
    ComponentHealth,
    ErrorMetrics,
    HealthStatus,
    LatencyMetrics,
    ServiceHealth,
    ThroughputMetrics,
)


class TestHealthStatus:
    """Tests for HealthStatus enum."""

    def test_health_status_values(self):
        """Test health status enum values."""
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNKNOWN.value == "unknown"


class TestComponentHealth:
    """Tests for ComponentHealth model."""

    def test_component_health_creation(self):
        """Test creating component health."""
        health = ComponentHealth(
            name="model",
            status=HealthStatus.HEALTHY,
            message="Model loaded successfully",
            latency_ms=15.5,
        )

        assert health.name == "model"
        assert health.status == HealthStatus.HEALTHY
        assert health.message == "Model loaded successfully"
        assert health.latency_ms == 15.5
        assert health.last_check is not None

    def test_component_health_with_details(self):
        """Test component health with custom details."""
        health = ComponentHealth(
            name="gpu",
            status=HealthStatus.HEALTHY,
            details={
                "memory_used_mb": 16384,
                "memory_total_mb": 40960,
                "utilization_percent": 75.0,
            },
        )

        assert health.details is not None
        assert health.details["memory_used_mb"] == 16384

    def test_component_health_defaults(self):
        """Test component health default values."""
        health = ComponentHealth(
            name="test",
            status=HealthStatus.UNKNOWN,
        )

        assert health.message is None
        assert health.latency_ms is None
        assert health.details is None


class TestServiceHealth:
    """Tests for ServiceHealth model."""

    def test_service_health_creation(self):
        """Test creating service health."""
        health = ServiceHealth(
            service_name="vllm",
            status=HealthStatus.HEALTHY,
            model_loaded=True,
            model_name="qwen2.5-7b-instruct",
        )

        assert health.service_name == "vllm"
        assert health.status == HealthStatus.HEALTHY
        assert health.model_loaded is True
        assert health.model_name == "qwen2.5-7b-instruct"

    def test_service_health_with_components(self):
        """Test service health with component list."""
        components = [
            ComponentHealth(name="model", status=HealthStatus.HEALTHY),
            ComponentHealth(name="gpu", status=HealthStatus.HEALTHY),
        ]

        health = ServiceHealth(
            service_name="vllm",
            status=HealthStatus.HEALTHY,
            components=components,
        )

        assert len(health.components) == 2
        assert health.components[0].name == "model"

    def test_service_health_gpu_info(self):
        """Test service health with GPU information."""
        health = ServiceHealth(
            service_name="vllm",
            status=HealthStatus.HEALTHY,
            gpu_available=True,
            gpu_memory_used_mb=16384.0,
            gpu_memory_total_mb=40960.0,
            gpu_utilization_percent=75.0,
        )

        assert health.gpu_available is True
        assert health.gpu_memory_used_mb == 16384.0

    def test_is_ready_healthy_loaded(self):
        """Test is_ready when healthy and model loaded."""
        health = ServiceHealth(
            service_name="vllm",
            status=HealthStatus.HEALTHY,
            model_loaded=True,
        )

        assert health.is_ready() is True

    def test_is_ready_degraded_loaded(self):
        """Test is_ready when degraded but model loaded."""
        health = ServiceHealth(
            service_name="vllm",
            status=HealthStatus.DEGRADED,
            model_loaded=True,
        )

        assert health.is_ready() is True

    def test_is_ready_unhealthy(self):
        """Test is_ready when unhealthy."""
        health = ServiceHealth(
            service_name="vllm",
            status=HealthStatus.UNHEALTHY,
            model_loaded=True,
        )

        assert health.is_ready() is False

    def test_is_ready_model_not_loaded(self):
        """Test is_ready when model not loaded."""
        health = ServiceHealth(
            service_name="vllm",
            status=HealthStatus.HEALTHY,
            model_loaded=False,
        )

        assert health.is_ready() is False

    def test_service_health_defaults(self):
        """Test service health default values."""
        health = ServiceHealth(
            service_name="test",
            status=HealthStatus.UNKNOWN,
        )

        assert health.components == []
        assert health.model_loaded is False
        assert health.gpu_available is False
        assert health.active_requests == 0
        assert health.uptime_seconds == 0


class TestLatencyMetrics:
    """Tests for LatencyMetrics model."""

    def test_latency_metrics_creation(self):
        """Test creating latency metrics."""
        metrics = LatencyMetrics(
            service_name="vllm",
            endpoint="/v1/completions",
            p50_ms=100.0,
            p75_ms=150.0,
            p90_ms=200.0,
            p95_ms=250.0,
            p99_ms=400.0,
            min_ms=50.0,
            max_ms=500.0,
            avg_ms=120.0,
            count=1000,
        )

        assert metrics.service_name == "vllm"
        assert metrics.p50_ms == 100.0
        assert metrics.p99_ms == 400.0
        assert metrics.count == 1000

    def test_latency_metrics_defaults(self):
        """Test latency metrics default values."""
        metrics = LatencyMetrics(
            service_name="test",
            endpoint="/test",
            p50_ms=10.0,
            p75_ms=15.0,
            p90_ms=20.0,
            p95_ms=25.0,
            p99_ms=50.0,
            min_ms=5.0,
            max_ms=100.0,
            avg_ms=12.0,
            count=100,
        )

        assert metrics.window_seconds == 60
        assert metrics.timestamp is not None


class TestThroughputMetrics:
    """Tests for ThroughputMetrics model."""

    def test_throughput_metrics_creation(self):
        """Test creating throughput metrics."""
        metrics = ThroughputMetrics(
            service_name="vllm",
            requests_per_second=50.0,
            successful_requests=4500,
            failed_requests=50,
            tokens_per_second=5000.0,
            prompt_tokens=100000,
            completion_tokens=150000,
        )

        assert metrics.requests_per_second == 50.0
        assert metrics.tokens_per_second == 5000.0
        assert metrics.successful_requests == 4500

    def test_throughput_metrics_embedding(self):
        """Test throughput metrics for embedding service."""
        metrics = ThroughputMetrics(
            service_name="embedding",
            requests_per_second=100.0,
            successful_requests=9000,
            failed_requests=10,
            embeddings_per_second=3200.0,
        )

        assert metrics.embeddings_per_second == 3200.0

    def test_throughput_metrics_defaults(self):
        """Test throughput metrics default values."""
        metrics = ThroughputMetrics(
            service_name="test",
            requests_per_second=10.0,
            successful_requests=100,
            failed_requests=0,
        )

        assert metrics.tokens_per_second == 0
        assert metrics.embeddings_per_second == 0
        assert metrics.window_seconds == 60


class TestErrorMetrics:
    """Tests for ErrorMetrics model."""

    def test_error_metrics_creation(self):
        """Test creating error metrics."""
        metrics = ErrorMetrics(
            service_name="vllm",
            total_errors=50,
            timeout_errors=20,
            rate_limit_errors=15,
            model_errors=10,
            validation_errors=3,
            internal_errors=2,
            error_rate_percent=5.0,
        )

        assert metrics.total_errors == 50
        assert metrics.error_rate_percent == 5.0

    def test_error_metrics_defaults(self):
        """Test error metrics default values."""
        metrics = ErrorMetrics(
            service_name="test",
            total_errors=0,
            timeout_errors=0,
            rate_limit_errors=0,
            model_errors=0,
            validation_errors=0,
            internal_errors=0,
            error_rate_percent=0.0,
        )

        assert metrics.window_seconds == 60


class TestAlert:
    """Tests for Alert model."""

    def test_alert_creation(self):
        """Test creating an alert."""
        alert = Alert(
            name="HighLatency",
            severity=AlertSeverity.WARNING,
            service_name="vllm",
            firing=True,
            message="P95 latency exceeded 2s threshold",
        )

        assert alert.name == "HighLatency"
        assert alert.severity == AlertSeverity.WARNING
        assert alert.firing is True
        assert alert.id is not None

    def test_alert_with_labels(self):
        """Test alert with labels and annotations."""
        alert = Alert(
            name="HighErrorRate",
            severity=AlertSeverity.CRITICAL,
            service_name="vllm",
            firing=True,
            message="Error rate exceeded 15%",
            labels={
                "model": "qwen2.5-7b-instruct",
                "endpoint": "/v1/completions",
            },
            annotations={
                "runbook_url": "https://example.com/runbooks/high-error-rate",
                "dashboard_url": "https://grafana.example.com/d/llm-serving",
            },
        )

        assert alert.labels["model"] == "qwen2.5-7b-instruct"
        assert "runbook_url" in alert.annotations

    def test_alert_resolved(self):
        """Test resolved alert."""
        alert = Alert(
            name="HighLatency",
            severity=AlertSeverity.WARNING,
            service_name="vllm",
            firing=False,
            message="P95 latency returned to normal",
            started_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            resolved_at=datetime(2024, 1, 1, 12, 15, 0, tzinfo=UTC),
        )

        assert alert.firing is False
        assert alert.resolved_at is not None


class TestAlertSeverity:
    """Tests for AlertSeverity enum."""

    def test_alert_severity_values(self):
        """Test alert severity values."""
        assert AlertSeverity.CRITICAL.value == "critical"
        assert AlertSeverity.WARNING.value == "warning"
        assert AlertSeverity.INFO.value == "info"


class TestAnomalyDetectionConfig:
    """Tests for AnomalyDetectionConfig model."""

    def test_config_creation(self):
        """Test creating anomaly detection config."""
        config = AnomalyDetectionConfig(
            service_name="vllm",
            metric_name="request_latency",
        )

        assert config.service_name == "vllm"
        assert config.metric_name == "request_latency"

    def test_config_defaults(self):
        """Test anomaly detection config defaults."""
        config = AnomalyDetectionConfig(
            service_name="test",
            metric_name="test_metric",
        )

        assert config.window_size == 100
        assert config.warning_threshold == 2.0
        assert config.critical_threshold == 3.0
        assert config.min_samples == 10
        assert config.enabled is True

    def test_config_custom_thresholds(self):
        """Test custom threshold values."""
        config = AnomalyDetectionConfig(
            service_name="test",
            metric_name="test_metric",
            warning_threshold=1.5,
            critical_threshold=2.5,
            rate_warning_threshold=0.10,
            rate_critical_threshold=0.20,
        )

        assert config.warning_threshold == 1.5
        assert config.rate_warning_threshold == 0.10

    def test_config_disabled_checks(self):
        """Test disabling specific checks."""
        config = AnomalyDetectionConfig(
            service_name="test",
            metric_name="test_metric",
            check_latency=False,
            check_error_rate=True,
            check_memory_trend=False,
        )

        assert config.check_latency is False
        assert config.check_error_rate is True
