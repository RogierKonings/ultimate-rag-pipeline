"""
Cost Tracker for LLM Serving Layer.

Tracks and allocates costs for LLM serving infrastructure.
Monitors GPU, CPU, and memory usage per service/model
and calculates associated costs.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from prometheus_client import Counter, Gauge

from .models import CostRecord

logger = logging.getLogger(__name__)

# Prometheus metrics for cost tracking
COST_TOTAL = Gauge(
    "cost_tracker_total_cost",
    "Total accumulated cost in USD",
    ["service_name", "model_name"],
)

COST_GPU_HOURS = Counter(
    "cost_tracker_gpu_hours_total",
    "Total GPU hours consumed",
    ["service_name", "model_name", "gpu_type"],
)

COST_PER_REQUEST = Gauge(
    "cost_tracker_cost_per_request",
    "Average cost per request in USD",
    ["service_name", "model_name"],
)

COST_PER_1K_TOKENS = Gauge(
    "cost_tracker_cost_per_1k_tokens",
    "Cost per 1000 tokens in USD",
    ["service_name", "model_name"],
)


@dataclass
class CostConfig:
    """Cost configuration per resource type."""

    # GPU costs (per hour) - common GPU types
    gpu_cost_per_hour: dict[str, float] = field(
        default_factory=lambda: {
            "NVIDIA-A100-SXM4-40GB": 4.00,
            "NVIDIA-A100-SXM4-80GB": 6.00,
            "NVIDIA-A100-PCIe-40GB": 3.50,
            "NVIDIA-A100-PCIe-80GB": 5.50,
            "NVIDIA-H100-SXM5-80GB": 10.00,
            "NVIDIA-A10": 1.50,
            "NVIDIA-A10G": 1.20,
            "NVIDIA-L4": 0.80,
            "NVIDIA-T4": 0.75,
            "NVIDIA-V100-SXM2-16GB": 2.50,
            "NVIDIA-V100-SXM2-32GB": 3.00,
            "NVIDIA-RTX-4090": 1.00,
            "NVIDIA-RTX-A6000": 1.25,
            "default": 2.00,  # Default rate for unknown GPUs
        },
    )

    # CPU cost per core-hour
    cpu_cost_per_core_hour: float = 0.05

    # Memory cost per GB-hour
    memory_cost_per_gb_hour: float = 0.01

    def get_gpu_cost(self, gpu_name: str) -> float:
        """Get GPU cost per hour, falling back to default if unknown."""
        return self.gpu_cost_per_hour.get(gpu_name, self.gpu_cost_per_hour["default"])


class CostTracker:
    """
    Track and allocate costs for LLM serving infrastructure.

    Monitors GPU, CPU, and memory usage per service/model
    and calculates associated costs.
    """

    def __init__(
        self,
        config: CostConfig | None = None,
        aggregation_interval: timedelta = timedelta(hours=1),
    ):
        """
        Initialize cost tracker.

        Args:
            config: Cost configuration
            aggregation_interval: Time period for aggregating costs
        """
        self.config = config or CostConfig()
        self.aggregation_interval = aggregation_interval

        self._current_period_start = datetime.now(tz=UTC)
        self._usage_accumulator: dict[str, dict] = {}
        self._cost_records: list[CostRecord] = []

    def record_usage(
        self,
        service_name: str,
        model_name: str,
        gpu_name: str,
        gpu_utilization: float,
        cpu_cores: float,
        memory_gb: float,
        requests: int = 0,
        tokens: int = 0,
        duration_seconds: float = 1.0,
    ) -> None:
        """
        Record resource usage for cost tracking.

        Args:
            service_name: Name of the service
            model_name: Name of the model
            gpu_name: Name/type of the GPU
            gpu_utilization: GPU utilization percentage (0-100)
            cpu_cores: Number of CPU cores used
            memory_gb: Memory used in GB
            requests: Number of requests processed
            tokens: Number of tokens processed
            duration_seconds: Duration of this usage sample
        """
        key = f"{service_name}:{model_name}"

        if key not in self._usage_accumulator:
            self._usage_accumulator[key] = {
                "service_name": service_name,
                "model_name": model_name,
                "gpu_name": gpu_name,
                "gpu_seconds": 0.0,
                "cpu_core_seconds": 0.0,
                "memory_gb_seconds": 0.0,
                "requests": 0,
                "tokens": 0,
            }

        acc = self._usage_accumulator[key]
        # Weight GPU seconds by utilization
        acc["gpu_seconds"] += duration_seconds * (gpu_utilization / 100.0)
        acc["cpu_core_seconds"] += cpu_cores * duration_seconds
        acc["memory_gb_seconds"] += memory_gb * duration_seconds
        acc["requests"] += requests
        acc["tokens"] += tokens

        # Check if we should finalize the period
        if datetime.now(tz=UTC) - self._current_period_start > self.aggregation_interval:
            self._finalize_period()

    def _finalize_period(self) -> None:
        """Finalize the current period and create cost records."""
        period_end = datetime.now(tz=UTC)

        for _key, acc in self._usage_accumulator.items():
            gpu_hours = acc["gpu_seconds"] / 3600
            cpu_hours = acc["cpu_core_seconds"] / 3600
            memory_gb_hours = acc["memory_gb_seconds"] / 3600

            # Calculate costs
            gpu_cost = gpu_hours * self.config.get_gpu_cost(acc["gpu_name"])
            cpu_cost = cpu_hours * self.config.cpu_cost_per_core_hour
            memory_cost = memory_gb_hours * self.config.memory_cost_per_gb_hour
            total_cost = gpu_cost + cpu_cost + memory_cost

            # Calculate per-unit costs
            cost_per_request = total_cost / acc["requests"] if acc["requests"] > 0 else 0
            cost_per_1k_tokens = total_cost / (acc["tokens"] / 1000) if acc["tokens"] > 0 else 0

            record = CostRecord(
                id=uuid4(),
                service_name=acc["service_name"],
                model_name=acc["model_name"],
                start_time=self._current_period_start,
                end_time=period_end,
                gpu_hours=gpu_hours,
                cpu_hours=cpu_hours,
                memory_gb_hours=memory_gb_hours,
                total_requests=acc["requests"],
                total_tokens_processed=acc["tokens"],
                gpu_cost=gpu_cost,
                cpu_cost=cpu_cost,
                memory_cost=memory_cost,
                total_cost=total_cost,
                cost_per_request=cost_per_request,
                cost_per_1k_tokens=cost_per_1k_tokens,
            )

            self._cost_records.append(record)

            # Update Prometheus metrics
            labels = {
                "service_name": acc["service_name"],
                "model_name": acc["model_name"],
            }
            COST_TOTAL.labels(**labels).set(total_cost)
            COST_PER_REQUEST.labels(**labels).set(cost_per_request)
            COST_PER_1K_TOKENS.labels(**labels).set(cost_per_1k_tokens)

            COST_GPU_HOURS.labels(
                service_name=acc["service_name"],
                model_name=acc["model_name"],
                gpu_type=acc["gpu_name"],
            ).inc(gpu_hours)

            logger.info(
                f"Cost record for {acc['service_name']}/{acc['model_name']}: "
                f"${total_cost:.4f} ({acc['requests']} requests, {acc['tokens']} tokens)",
            )

        # Reset accumulator
        self._usage_accumulator = {}
        self._current_period_start = period_end

    def force_finalize(self) -> None:
        """Force finalization of current period."""
        if self._usage_accumulator:
            self._finalize_period()

    def get_cost_summary(
        self,
        service_name: str | None = None,
        model_name: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> dict:
        """
        Get cost summary for a time period.

        Args:
            service_name: Filter by service name
            model_name: Filter by model name
            start_time: Filter by start time
            end_time: Filter by end time

        Returns:
            Dict with cost summary
        """
        records = self._cost_records

        if service_name:
            records = [r for r in records if r.service_name == service_name]

        if model_name:
            records = [r for r in records if r.model_name == model_name]

        if start_time:
            records = [r for r in records if r.start_time >= start_time]

        if end_time:
            records = [r for r in records if r.end_time <= end_time]

        if not records:
            return {
                "total_cost": 0,
                "gpu_cost": 0,
                "cpu_cost": 0,
                "memory_cost": 0,
                "total_requests": 0,
                "total_tokens": 0,
                "cost_per_request": 0,
                "cost_per_1k_tokens": 0,
                "records_count": 0,
            }

        total_cost = sum(r.total_cost for r in records)
        total_requests = sum(r.total_requests for r in records)
        total_tokens = sum(r.total_tokens_processed for r in records)

        return {
            "total_cost": total_cost,
            "gpu_cost": sum(r.gpu_cost for r in records),
            "cpu_cost": sum(r.cpu_cost for r in records),
            "memory_cost": sum(r.memory_cost for r in records),
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "cost_per_request": (total_cost / total_requests if total_requests > 0 else 0),
            "cost_per_1k_tokens": (total_cost / (total_tokens / 1000) if total_tokens > 0 else 0),
            "records_count": len(records),
        }

    def get_cost_by_model(self) -> dict[str, dict]:
        """
        Get cost breakdown by model.

        Returns:
            Dict mapping model names to cost summaries
        """
        model_costs: dict[str, dict] = {}

        for record in self._cost_records:
            if record.model_name not in model_costs:
                model_costs[record.model_name] = {
                    "total_cost": 0,
                    "gpu_cost": 0,
                    "cpu_cost": 0,
                    "memory_cost": 0,
                    "total_requests": 0,
                    "total_tokens": 0,
                }

            model_costs[record.model_name]["total_cost"] += record.total_cost
            model_costs[record.model_name]["gpu_cost"] += record.gpu_cost
            model_costs[record.model_name]["cpu_cost"] += record.cpu_cost
            model_costs[record.model_name]["memory_cost"] += record.memory_cost
            model_costs[record.model_name]["total_requests"] += record.total_requests
            model_costs[record.model_name]["total_tokens"] += record.total_tokens_processed

        return model_costs

    def get_cost_by_service(self) -> dict[str, dict]:
        """
        Get cost breakdown by service.

        Returns:
            Dict mapping service names to cost summaries
        """
        service_costs: dict[str, dict] = {}

        for record in self._cost_records:
            if record.service_name not in service_costs:
                service_costs[record.service_name] = {
                    "total_cost": 0,
                    "gpu_cost": 0,
                    "cpu_cost": 0,
                    "memory_cost": 0,
                    "total_requests": 0,
                    "total_tokens": 0,
                }

            service_costs[record.service_name]["total_cost"] += record.total_cost
            service_costs[record.service_name]["gpu_cost"] += record.gpu_cost
            service_costs[record.service_name]["cpu_cost"] += record.cpu_cost
            service_costs[record.service_name]["memory_cost"] += record.memory_cost
            service_costs[record.service_name]["total_requests"] += record.total_requests
            service_costs[record.service_name]["total_tokens"] += record.total_tokens_processed

        return service_costs

    def estimate_monthly_cost(self) -> float:
        """
        Estimate monthly cost based on recent usage.

        Returns:
            Estimated monthly cost in USD
        """
        now = datetime.now(tz=UTC)
        day_ago = now - timedelta(days=1)

        recent_records = [r for r in self._cost_records if r.start_time >= day_ago]

        if not recent_records:
            return 0.0

        daily_cost = sum(r.total_cost for r in recent_records)
        return daily_cost * 30

    def estimate_annual_cost(self) -> float:
        """
        Estimate annual cost based on recent usage.

        Returns:
            Estimated annual cost in USD
        """
        return self.estimate_monthly_cost() * 12

    def get_all_records(
        self,
        limit: int | None = None,
    ) -> list[CostRecord]:
        """
        Get all cost records.

        Args:
            limit: Maximum number of records to return (most recent)

        Returns:
            List of cost records
        """
        records = self._cost_records
        if limit:
            records = records[-limit:]
        return records

    def clear_records(self, before: datetime | None = None) -> int:
        """
        Clear cost records.

        Args:
            before: Only clear records before this time

        Returns:
            Number of records cleared
        """
        if before is None:
            count = len(self._cost_records)
            self._cost_records = []
            return count

        original_count = len(self._cost_records)
        self._cost_records = [r for r in self._cost_records if r.end_time >= before]
        return original_count - len(self._cost_records)
