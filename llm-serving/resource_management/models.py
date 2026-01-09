"""
Data models for Resource Management.

Provides Pydantic models for GPU metrics, batching metrics,
cost tracking, and scaling recommendations.
"""

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class GPUMetrics(BaseModel):
    """GPU metrics snapshot from nvidia-smi."""

    gpu_id: int
    name: str

    # Memory metrics (bytes)
    memory_total: int
    memory_used: int
    memory_free: int
    memory_utilization_percent: float

    # Compute metrics
    gpu_utilization_percent: float
    temperature_celsius: float
    power_draw_watts: float
    power_limit_watts: float

    # Clock speeds (MHz)
    sm_clock: int
    memory_clock: int

    timestamp: datetime = Field(default_factory=datetime.utcnow)

    @property
    def memory_utilization(self) -> float:
        """Calculate memory utilization as a ratio."""
        return self.memory_used / self.memory_total if self.memory_total > 0 else 0.0


class ServiceResourceMetrics(BaseModel):
    """Resource metrics for a service."""

    service_name: str
    pod_name: str
    namespace: str = "llm-serving"

    # GPU metrics
    gpu_metrics: Optional[GPUMetrics] = None

    # CPU metrics
    cpu_usage_cores: float
    cpu_request_cores: float
    cpu_limit_cores: float

    # Memory metrics (bytes)
    memory_usage_bytes: int
    memory_request_bytes: int
    memory_limit_bytes: int

    # Request metrics
    pending_requests: int
    active_requests: int
    requests_per_second: float

    # Queue metrics
    queue_depth: int
    avg_queue_wait_ms: float

    timestamp: datetime = Field(default_factory=datetime.utcnow)


class BatchingMetrics(BaseModel):
    """Metrics for batch processing optimization."""

    service_name: str

    # Batch statistics
    avg_batch_size: float
    max_batch_size: int
    min_batch_size: int

    # Fill rate (actual vs max batch size)
    batch_fill_rate: float

    # Timing
    avg_batch_wait_ms: float
    avg_batch_processing_ms: float

    # Throughput
    items_per_second: float
    batches_per_second: float

    # Efficiency score (higher is better)
    efficiency_score: float

    timestamp: datetime = Field(default_factory=datetime.utcnow)


class CostRecord(BaseModel):
    """Cost record for a time period."""

    id: UUID
    service_name: str
    model_name: str

    # Time period
    start_time: datetime
    end_time: datetime

    # Usage metrics
    gpu_hours: float
    cpu_hours: float
    memory_gb_hours: float

    # Request counts
    total_requests: int
    total_tokens_processed: int

    # Costs (in USD or configured currency)
    gpu_cost: float
    cpu_cost: float
    memory_cost: float
    total_cost: float

    # Per-unit costs
    cost_per_request: float
    cost_per_1k_tokens: float


class ResourceRecommendation(BaseModel):
    """Resource scaling recommendation."""

    service_name: str
    recommendation_type: Literal["scale_up", "scale_down", "optimize", "maintain"]

    # Current state
    current_replicas: int
    current_gpu_utilization: float
    current_queue_depth: int

    # Recommended state
    recommended_replicas: int
    recommended_batch_size: Optional[int] = None

    # Reasoning
    reason: str
    confidence: float  # 0.0 to 1.0

    # Expected impact
    expected_cost_change_percent: float
    expected_latency_change_percent: float

    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ScalingPolicy(BaseModel):
    """Auto-scaling policy configuration."""

    service_name: str

    # Replica bounds
    min_replicas: int = 1
    max_replicas: int = 10

    # Scale-up thresholds
    scale_up_gpu_utilization: float = 80.0
    scale_up_queue_depth: int = 100
    scale_up_latency_p95_ms: float = 1000.0

    # Scale-down thresholds
    scale_down_gpu_utilization: float = 30.0
    scale_down_queue_depth: int = 10

    # Cooldown periods
    scale_up_cooldown_seconds: int = 60
    scale_down_cooldown_seconds: int = 300

    # Behavior
    scale_up_step: int = 1
    scale_down_step: int = 1

    # Cost constraints
    max_hourly_cost: Optional[float] = None
