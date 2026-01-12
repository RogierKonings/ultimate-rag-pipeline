"""
Data models for Health & Monitoring.

Provides Pydantic models for health status, metrics, alerts, and anomaly detection.
"""

from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class HealthStatus(str, Enum):
    """Health status enum."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class ComponentHealth(BaseModel):
    """Health status of a single component."""

    name: str
    status: HealthStatus
    message: str | None = None
    last_check: datetime = Field(default_factory=datetime.utcnow)
    latency_ms: float | None = None

    # Component-specific details
    details: dict | None = None


class ServiceHealth(BaseModel):
    """Overall health of a service."""

    service_name: str
    status: HealthStatus

    # Component health checks
    components: list[ComponentHealth] = Field(default_factory=list)

    # Model status
    model_loaded: bool = False
    model_name: str | None = None

    # Resource status
    gpu_available: bool = False
    gpu_memory_used_mb: float | None = None
    gpu_memory_total_mb: float | None = None
    gpu_utilization_percent: float | None = None

    # Request status
    active_requests: int = 0
    pending_requests: int = 0

    # Timing
    uptime_seconds: float = 0
    last_request_time: datetime | None = None

    def is_ready(self) -> bool:
        """Check if service is ready to accept requests."""
        return (
            self.status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED]
            and self.model_loaded
        )


class LatencyMetrics(BaseModel):
    """Latency metrics with percentiles."""

    service_name: str
    endpoint: str

    # Latency percentiles (milliseconds)
    p50_ms: float
    p75_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float

    # Min/max/avg
    min_ms: float
    max_ms: float
    avg_ms: float

    # Sample count
    count: int

    # Time window
    window_seconds: int = 60
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ThroughputMetrics(BaseModel):
    """Throughput metrics."""

    service_name: str

    # Request throughput
    requests_per_second: float
    successful_requests: int
    failed_requests: int

    # Token throughput (for LLM)
    tokens_per_second: float = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    # Embedding throughput
    embeddings_per_second: float = 0

    # Time window
    window_seconds: int = 60
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ErrorMetrics(BaseModel):
    """Error rate metrics."""

    service_name: str

    # Error counts by type
    total_errors: int
    timeout_errors: int
    rate_limit_errors: int
    model_errors: int
    validation_errors: int
    internal_errors: int

    # Error rate
    error_rate_percent: float

    # Time window
    window_seconds: int = 60
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AlertSeverity(str, Enum):
    """Alert severity levels."""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class Alert(BaseModel):
    """Alert definition."""

    id: UUID = Field(default_factory=uuid4)
    name: str
    severity: AlertSeverity
    service_name: str

    # Alert state
    firing: bool
    message: str

    # Timing
    started_at: datetime | None = None
    resolved_at: datetime | None = None

    # Context
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)


class AnomalyDetectionConfig(BaseModel):
    """Configuration for anomaly detection."""

    service_name: str
    metric_name: str

    # Z-score based detection settings
    window_size: int = 100
    warning_threshold: float = 2.0  # Standard deviations
    critical_threshold: float = 3.0  # Standard deviations
    min_samples: int = 10

    # Rate-based detection settings (for error rates)
    rate_window_seconds: float = 60.0
    rate_warning_threshold: float = 0.05  # 5%
    rate_critical_threshold: float = 0.15  # 15%

    # Trend detection settings
    trend_window_size: int = 30
    trend_threshold: float = 0.8  # 80% increasing

    # Enabled checks
    enabled: bool = True
    check_latency: bool = True
    check_error_rate: bool = True
    check_memory_trend: bool = True
