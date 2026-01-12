"""
Batch Optimizer for LLM Serving Layer.

Optimizes batch processing parameters based on observed metrics.
Monitors batch fill rates, processing times, and throughput
to recommend optimal batch sizes and timeouts.
"""

import logging
import statistics
from dataclasses import dataclass, field

from prometheus_client import Gauge, Histogram

from .models import BatchingMetrics

logger = logging.getLogger(__name__)

# Prometheus metrics for batch optimization
BATCH_SIZE = Gauge(
    "batch_optimizer_batch_size",
    "Current configured batch size",
    ["service_name"],
)

BATCH_TIMEOUT = Gauge(
    "batch_optimizer_timeout_ms",
    "Current configured batch timeout in milliseconds",
    ["service_name"],
)

BATCH_FILL_RATE = Gauge(
    "batch_optimizer_fill_rate",
    "Current batch fill rate (0-1)",
    ["service_name"],
)

BATCH_EFFICIENCY = Gauge(
    "batch_optimizer_efficiency",
    "Current batch efficiency score (0-1)",
    ["service_name"],
)

BATCH_PROCESSING_TIME = Histogram(
    "batch_processing_time_ms",
    "Batch processing time in milliseconds",
    ["service_name"],
    buckets=[10, 25, 50, 100, 250, 500, 1000, 2500, 5000],
)


@dataclass
class BatchStats:
    """Statistics for batch processing."""

    batch_sizes: list[int] = field(default_factory=list)
    processing_times_ms: list[float] = field(default_factory=list)
    wait_times_ms: list[float] = field(default_factory=list)


class BatchOptimizer:
    """
    Optimizes batch processing parameters based on observed metrics.

    Monitors batch fill rates, processing times, and throughput
    to recommend optimal batch sizes and timeouts.
    """

    def __init__(
        self,
        service_name: str,
        initial_batch_size: int = 32,
        initial_timeout_ms: float = 50.0,
        window_size: int = 100,
        min_batch_size: int = 4,
        max_batch_size: int = 128,
        min_timeout_ms: float = 10.0,
        max_timeout_ms: float = 500.0,
    ):
        """
        Initialize batch optimizer.

        Args:
            service_name: Name of the service being optimized
            initial_batch_size: Starting batch size
            initial_timeout_ms: Starting batch timeout
            window_size: Number of samples to keep for analysis
            min_batch_size: Minimum allowed batch size
            max_batch_size: Maximum allowed batch size
            min_timeout_ms: Minimum allowed timeout
            max_timeout_ms: Maximum allowed timeout
        """
        self.service_name = service_name
        self.current_batch_size = initial_batch_size
        self.current_timeout_ms = initial_timeout_ms
        self.window_size = window_size
        self.min_batch_size = min_batch_size
        self.max_batch_size = max_batch_size
        self.min_timeout_ms = min_timeout_ms
        self.max_timeout_ms = max_timeout_ms

        self._batch_sizes: list[int] = []
        self._processing_times: list[float] = []
        self._wait_times: list[float] = []
        self._throughputs: list[float] = []

        # Update Prometheus metrics
        BATCH_SIZE.labels(service_name=service_name).set(initial_batch_size)
        BATCH_TIMEOUT.labels(service_name=service_name).set(initial_timeout_ms)

    def record_batch(
        self,
        batch_size: int,
        processing_time_ms: float,
        wait_time_ms: float,
    ) -> None:
        """
        Record a batch processing event.

        Args:
            batch_size: Number of items in the batch
            processing_time_ms: Time to process the batch in ms
            wait_time_ms: Time spent waiting for batch to fill in ms
        """
        self._batch_sizes.append(batch_size)
        self._processing_times.append(processing_time_ms)
        self._wait_times.append(wait_time_ms)

        # Calculate throughput (items per second)
        total_time_s = (processing_time_ms + wait_time_ms) / 1000
        if total_time_s > 0:
            self._throughputs.append(batch_size / total_time_s)

        # Trim to window size
        if len(self._batch_sizes) > self.window_size:
            self._batch_sizes = self._batch_sizes[-self.window_size :]
            self._processing_times = self._processing_times[-self.window_size :]
            self._wait_times = self._wait_times[-self.window_size :]
            self._throughputs = self._throughputs[-self.window_size :]

        # Record Prometheus metrics
        BATCH_PROCESSING_TIME.labels(service_name=self.service_name).observe(
            processing_time_ms,
        )

        # Update efficiency metrics
        metrics = self.get_metrics()
        BATCH_FILL_RATE.labels(service_name=self.service_name).set(
            metrics.batch_fill_rate,
        )
        BATCH_EFFICIENCY.labels(service_name=self.service_name).set(
            metrics.efficiency_score,
        )

    def get_metrics(self) -> BatchingMetrics:
        """
        Get current batching metrics.

        Returns:
            BatchingMetrics with current statistics
        """
        if not self._batch_sizes:
            return BatchingMetrics(
                service_name=self.service_name,
                avg_batch_size=0,
                max_batch_size=0,
                min_batch_size=0,
                batch_fill_rate=0,
                avg_batch_wait_ms=0,
                avg_batch_processing_ms=0,
                items_per_second=0,
                batches_per_second=0,
                efficiency_score=0,
            )

        avg_batch = statistics.mean(self._batch_sizes)
        fill_rate = (
            avg_batch / self.current_batch_size if self.current_batch_size > 0 else 0
        )

        return BatchingMetrics(
            service_name=self.service_name,
            avg_batch_size=avg_batch,
            max_batch_size=max(self._batch_sizes),
            min_batch_size=min(self._batch_sizes),
            batch_fill_rate=fill_rate,
            avg_batch_wait_ms=(
                statistics.mean(self._wait_times) if self._wait_times else 0
            ),
            avg_batch_processing_ms=(
                statistics.mean(self._processing_times) if self._processing_times else 0
            ),
            items_per_second=(
                statistics.mean(self._throughputs) if self._throughputs else 0
            ),
            batches_per_second=len(self._batch_sizes) / self.window_size,
            efficiency_score=self._calculate_efficiency(),
        )

    def _calculate_efficiency(self) -> float:
        """
        Calculate efficiency score (0-1).

        Higher is better. Considers:
        - Batch fill rate (want high)
        - Wait time relative to processing (want low)
        - Throughput stability
        """
        if not self._batch_sizes or not self._processing_times:
            return 0.0

        # Fill rate component (0-0.4)
        avg_fill = statistics.mean(self._batch_sizes) / self.current_batch_size
        fill_score = min(avg_fill, 1.0) * 0.4

        # Wait efficiency component (0-0.3)
        # Lower wait-to-processing ratio is better
        if self._processing_times:
            avg_wait = statistics.mean(self._wait_times) if self._wait_times else 0
            avg_proc = statistics.mean(self._processing_times)
            wait_ratio = (
                avg_wait / (avg_wait + avg_proc) if (avg_wait + avg_proc) > 0 else 0
            )
            wait_score = (1 - wait_ratio) * 0.3
        else:
            wait_score = 0

        # Throughput stability component (0-0.3)
        if len(self._throughputs) > 1:
            try:
                cv = statistics.stdev(self._throughputs) / statistics.mean(
                    self._throughputs,
                )
                stability_score = max(0, 1 - cv) * 0.3
            except (ZeroDivisionError, statistics.StatisticsError):
                stability_score = 0
        else:
            stability_score = 0.15

        return fill_score + wait_score + stability_score

    def recommend_parameters(self) -> dict:
        """
        Recommend optimal batch parameters based on observed data.

        Returns:
            Dict with recommended batch_size, timeout_ms, confidence, and reason
        """
        if len(self._batch_sizes) < 10:
            return {
                "batch_size": self.current_batch_size,
                "timeout_ms": self.current_timeout_ms,
                "confidence": 0.0,
                "reason": "Insufficient data for recommendations",
            }

        metrics = self.get_metrics()

        # Low fill rate: decrease batch size or increase timeout
        if metrics.batch_fill_rate < 0.5:
            if metrics.avg_batch_wait_ms < self.current_timeout_ms * 0.8:
                # Timeout rarely reached, increase it
                new_timeout = min(self.current_timeout_ms * 1.5, self.max_timeout_ms)
                return {
                    "batch_size": self.current_batch_size,
                    "timeout_ms": new_timeout,
                    "confidence": 0.7,
                    "reason": f"Low fill rate ({metrics.batch_fill_rate:.2f}), increasing timeout",
                }
            # Decrease batch size
            new_batch_size = max(
                int(self.current_batch_size * 0.75), self.min_batch_size,
            )
            return {
                "batch_size": new_batch_size,
                "timeout_ms": self.current_timeout_ms,
                "confidence": 0.8,
                "reason": f"Low fill rate ({metrics.batch_fill_rate:.2f}), decreasing batch size",
            }

        # High fill rate and quick processing: increase batch size
        if metrics.batch_fill_rate > 0.9 and metrics.avg_batch_processing_ms < 100:
            new_batch_size = min(
                int(self.current_batch_size * 1.25), self.max_batch_size,
            )
            return {
                "batch_size": new_batch_size,
                "timeout_ms": self.current_timeout_ms,
                "confidence": 0.7,
                "reason": f"High fill rate ({metrics.batch_fill_rate:.2f}) with fast processing, increasing batch size",
            }

        # Very high wait times: decrease timeout
        if (
            metrics.avg_batch_wait_ms > self.current_timeout_ms * 0.9
            and metrics.batch_fill_rate < 0.7
        ):
            new_timeout = max(self.current_timeout_ms * 0.7, self.min_timeout_ms)
            return {
                "batch_size": self.current_batch_size,
                "timeout_ms": new_timeout,
                "confidence": 0.6,
                "reason": "High wait times with low fill rate, decreasing timeout",
            }

        # Good efficiency, maintain current settings
        return {
            "batch_size": self.current_batch_size,
            "timeout_ms": self.current_timeout_ms,
            "confidence": 0.9,
            "reason": f"Current settings optimal (efficiency: {metrics.efficiency_score:.2f})",
        }

    def apply_recommendation(self, recommendation: dict) -> None:
        """
        Apply recommended parameters.

        Args:
            recommendation: Dict from recommend_parameters()
        """
        self.current_batch_size = recommendation["batch_size"]
        self.current_timeout_ms = recommendation["timeout_ms"]

        # Update Prometheus metrics
        BATCH_SIZE.labels(service_name=self.service_name).set(self.current_batch_size)
        BATCH_TIMEOUT.labels(service_name=self.service_name).set(self.current_timeout_ms)

        logger.info(
            f"Applied batch optimization for {self.service_name}: "
            f"batch_size={self.current_batch_size}, timeout={self.current_timeout_ms}ms "
            f"(reason: {recommendation['reason']})",
        )

    def auto_tune(self) -> dict | None:
        """
        Automatically tune parameters if confidence is high enough.

        Returns:
            Applied recommendation if auto-tuned, None otherwise
        """
        recommendation = self.recommend_parameters()

        # Only auto-apply if confidence is high and there's a change
        if recommendation["confidence"] >= 0.7 and (
            recommendation["batch_size"] != self.current_batch_size
            or recommendation["timeout_ms"] != self.current_timeout_ms
        ):
            self.apply_recommendation(recommendation)
            return recommendation

        return None

    def reset_stats(self) -> None:
        """Reset collected statistics."""
        self._batch_sizes = []
        self._processing_times = []
        self._wait_times = []
        self._throughputs = []
        logger.info(f"Reset batch statistics for {self.service_name}")

    def get_stats(self) -> BatchStats:
        """
        Get raw batch statistics.

        Returns:
            BatchStats with raw data
        """
        return BatchStats(
            batch_sizes=self._batch_sizes.copy(),
            processing_times_ms=self._processing_times.copy(),
            wait_times_ms=self._wait_times.copy(),
        )
