"""
Anomaly detection for LLM Serving Layer.

Provides statistical and ML-based anomaly detection for latency,
throughput, and error rates.
"""

import logging
import math
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class AnomalyType(str, Enum):
    """Types of anomalies that can be detected."""

    LATENCY_SPIKE = "latency_spike"
    LATENCY_DEGRADATION = "latency_degradation"
    ERROR_RATE_SPIKE = "error_rate_spike"
    THROUGHPUT_DROP = "throughput_drop"
    MEMORY_LEAK = "memory_leak"
    GPU_THERMAL = "gpu_thermal"
    QUEUE_BUILDUP = "queue_buildup"


class AnomalySeverity(str, Enum):
    """Severity levels for anomalies."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Anomaly:
    """Represents a detected anomaly."""

    type: AnomalyType
    severity: AnomalySeverity
    metric_name: str
    current_value: float
    expected_value: float
    threshold: float
    deviation: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    service_name: str | None = None
    model_name: str | None = None
    message: str | None = None
    context: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "type": self.type.value,
            "severity": self.severity.value,
            "metric_name": self.metric_name,
            "current_value": self.current_value,
            "expected_value": self.expected_value,
            "threshold": self.threshold,
            "deviation": self.deviation,
            "timestamp": self.timestamp.isoformat(),
            "service_name": self.service_name,
            "model_name": self.model_name,
            "message": self.message,
            "context": self.context,
        }


class BaseAnomalyDetector(ABC):
    """Base class for anomaly detectors."""

    @abstractmethod
    def add_value(self, value: float) -> Anomaly | None:
        """Add a new value and check for anomalies."""

    @abstractmethod
    def reset(self) -> None:
        """Reset the detector state."""


class ZScoreDetector(BaseAnomalyDetector):
    """
    Anomaly detector using Z-score statistical method.

    Detects values that deviate significantly from the running mean.
    """

    def __init__(
        self,
        metric_name: str,
        window_size: int = 100,
        warning_threshold: float = 2.0,
        critical_threshold: float = 3.0,
        min_samples: int = 10,
        service_name: str | None = None,
        model_name: str | None = None,
        anomaly_type: AnomalyType = AnomalyType.LATENCY_SPIKE,
    ):
        """
        Initialize Z-score detector.

        Args:
            metric_name: Name of the metric being monitored
            window_size: Number of samples to keep for statistics
            warning_threshold: Z-score threshold for warning
            critical_threshold: Z-score threshold for critical
            min_samples: Minimum samples before detection starts
            service_name: Service name for context
            model_name: Model name for context
            anomaly_type: Type of anomaly this detector finds
        """
        self.metric_name = metric_name
        self.window_size = window_size
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.min_samples = min_samples
        self.service_name = service_name
        self.model_name = model_name
        self.anomaly_type = anomaly_type

        self._values: deque[float] = deque(maxlen=window_size)
        self._sum = 0.0
        self._sum_sq = 0.0

    def add_value(self, value: float) -> Anomaly | None:
        """
        Add a value and check for anomalies.

        Args:
            value: The metric value to check

        Returns:
            Anomaly if detected, None otherwise
        """
        # Update running statistics
        if len(self._values) == self.window_size:
            old_value = self._values[0]
            self._sum -= old_value
            self._sum_sq -= old_value * old_value

        self._values.append(value)
        self._sum += value
        self._sum_sq += value * value

        # Need minimum samples
        if len(self._values) < self.min_samples:
            return None

        # Calculate statistics
        n = len(self._values)
        mean = self._sum / n
        variance = (self._sum_sq / n) - (mean * mean)
        std_dev = math.sqrt(max(0, variance))

        # Avoid division by zero
        if std_dev < 1e-10:
            return None

        # Calculate z-score
        z_score = abs(value - mean) / std_dev

        # Check thresholds
        if z_score >= self.critical_threshold:
            severity = AnomalySeverity.CRITICAL
        elif z_score >= self.warning_threshold:
            severity = AnomalySeverity.WARNING
        else:
            return None

        return Anomaly(
            type=self.anomaly_type,
            severity=severity,
            metric_name=self.metric_name,
            current_value=value,
            expected_value=mean,
            threshold=self.warning_threshold
            if severity == AnomalySeverity.WARNING
            else self.critical_threshold,
            deviation=z_score,
            service_name=self.service_name,
            model_name=self.model_name,
            message=f"{self.metric_name} is {z_score:.2f} standard deviations from mean",
            context={
                "mean": mean,
                "std_dev": std_dev,
                "z_score": z_score,
                "sample_count": n,
            },
        )

    def reset(self) -> None:
        """Reset detector state."""
        self._values.clear()
        self._sum = 0.0
        self._sum_sq = 0.0


class RateDetector(BaseAnomalyDetector):
    """
    Anomaly detector for rate metrics (e.g., error rate, throughput).

    Tracks rate over time windows and detects sudden changes.
    """

    def __init__(
        self,
        metric_name: str,
        window_seconds: float = 60.0,
        warning_threshold: float = 0.1,  # 10% error rate
        critical_threshold: float = 0.25,  # 25% error rate
        min_events: int = 10,
        service_name: str | None = None,
        model_name: str | None = None,
        anomaly_type: AnomalyType = AnomalyType.ERROR_RATE_SPIKE,
    ):
        """
        Initialize rate detector.

        Args:
            metric_name: Name of the metric
            window_seconds: Time window in seconds
            warning_threshold: Rate threshold for warning
            critical_threshold: Rate threshold for critical
            min_events: Minimum events before detection
            service_name: Service name
            model_name: Model name
            anomaly_type: Type of anomaly
        """
        self.metric_name = metric_name
        self.window_seconds = window_seconds
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.min_events = min_events
        self.service_name = service_name
        self.model_name = model_name
        self.anomaly_type = anomaly_type

        self._events: deque[tuple[float, float]] = deque()  # (timestamp, value)

    def add_value(self, value: float) -> Anomaly | None:
        """
        Add a value (0 for success, 1 for error/event).

        Args:
            value: 0 or 1 indicating event occurrence

        Returns:
            Anomaly if rate exceeds threshold
        """
        now = time.time()

        # Add new event
        self._events.append((now, value))

        # Remove old events
        cutoff = now - self.window_seconds
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

        # Need minimum events
        if len(self._events) < self.min_events:
            return None

        # Calculate rate
        total_events = len(self._events)
        error_events = sum(1 for _, v in self._events if v > 0)
        rate = error_events / total_events

        # Check thresholds
        if rate >= self.critical_threshold:
            severity = AnomalySeverity.CRITICAL
        elif rate >= self.warning_threshold:
            severity = AnomalySeverity.WARNING
        else:
            return None

        return Anomaly(
            type=self.anomaly_type,
            severity=severity,
            metric_name=self.metric_name,
            current_value=rate,
            expected_value=0.0,  # Ideal rate
            threshold=self.warning_threshold
            if severity == AnomalySeverity.WARNING
            else self.critical_threshold,
            deviation=rate / self.warning_threshold,
            service_name=self.service_name,
            model_name=self.model_name,
            message=f"{self.metric_name} rate is {rate * 100:.1f}%",
            context={
                "rate": rate,
                "total_events": total_events,
                "error_events": error_events,
                "window_seconds": self.window_seconds,
            },
        )

    def reset(self) -> None:
        """Reset detector state."""
        self._events.clear()


class TrendDetector(BaseAnomalyDetector):
    """
    Anomaly detector for trending metrics (e.g., memory usage).

    Detects continuous increases that might indicate leaks.
    """

    def __init__(
        self,
        metric_name: str,
        window_size: int = 30,
        trend_threshold: float = 0.8,  # 80% of values increasing
        min_samples: int = 10,
        absolute_threshold: float | None = None,
        service_name: str | None = None,
        model_name: str | None = None,
        anomaly_type: AnomalyType = AnomalyType.MEMORY_LEAK,
    ):
        """
        Initialize trend detector.

        Args:
            metric_name: Name of the metric
            window_size: Number of samples for trend analysis
            trend_threshold: Fraction of increasing values to trigger
            min_samples: Minimum samples before detection
            absolute_threshold: Optional absolute value threshold
            service_name: Service name
            model_name: Model name
            anomaly_type: Type of anomaly
        """
        self.metric_name = metric_name
        self.window_size = window_size
        self.trend_threshold = trend_threshold
        self.min_samples = min_samples
        self.absolute_threshold = absolute_threshold
        self.service_name = service_name
        self.model_name = model_name
        self.anomaly_type = anomaly_type

        self._values: deque[float] = deque(maxlen=window_size)

    def add_value(self, value: float) -> Anomaly | None:
        """
        Add a value and check for trends.

        Args:
            value: The metric value

        Returns:
            Anomaly if trend detected
        """
        self._values.append(value)

        # Check absolute threshold first
        if self.absolute_threshold is not None and value >= self.absolute_threshold:
            return Anomaly(
                type=self.anomaly_type,
                severity=AnomalySeverity.CRITICAL,
                metric_name=self.metric_name,
                current_value=value,
                expected_value=self.absolute_threshold,
                threshold=self.absolute_threshold,
                deviation=value / self.absolute_threshold,
                service_name=self.service_name,
                model_name=self.model_name,
                message=f"{self.metric_name} exceeded absolute threshold",
                context={"threshold_type": "absolute"},
            )

        # Need minimum samples for trend detection
        if len(self._values) < self.min_samples:
            return None

        # Calculate trend
        values = list(self._values)
        increasing = sum(1 for i in range(1, len(values)) if values[i] > values[i - 1])
        trend_ratio = increasing / (len(values) - 1)

        if trend_ratio >= self.trend_threshold:
            # Calculate slope
            first_half_avg = sum(values[: len(values) // 2]) / (len(values) // 2)
            second_half_avg = sum(values[len(values) // 2 :]) / (len(values) - len(values) // 2)
            slope = second_half_avg - first_half_avg

            severity = AnomalySeverity.CRITICAL if trend_ratio > 0.9 else AnomalySeverity.WARNING

            return Anomaly(
                type=self.anomaly_type,
                severity=severity,
                metric_name=self.metric_name,
                current_value=value,
                expected_value=values[0],  # First value
                threshold=self.trend_threshold,
                deviation=trend_ratio,
                service_name=self.service_name,
                model_name=self.model_name,
                message=f"{self.metric_name} showing {trend_ratio * 100:.0f}% increasing trend",
                context={
                    "trend_ratio": trend_ratio,
                    "slope": slope,
                    "start_value": values[0],
                    "end_value": values[-1],
                    "sample_count": len(values),
                },
            )

        return None

    def reset(self) -> None:
        """Reset detector state."""
        self._values.clear()


class ThresholdDetector(BaseAnomalyDetector):
    """
    Simple threshold-based anomaly detector.

    Detects values exceeding static thresholds.
    """

    def __init__(
        self,
        metric_name: str,
        warning_threshold: float,
        critical_threshold: float,
        direction: str = "above",  # "above" or "below"
        service_name: str | None = None,
        model_name: str | None = None,
        anomaly_type: AnomalyType = AnomalyType.GPU_THERMAL,
    ):
        """
        Initialize threshold detector.

        Args:
            metric_name: Name of the metric
            warning_threshold: Warning threshold
            critical_threshold: Critical threshold
            direction: "above" or "below" - which direction triggers
            service_name: Service name
            model_name: Model name
            anomaly_type: Type of anomaly
        """
        self.metric_name = metric_name
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.direction = direction
        self.service_name = service_name
        self.model_name = model_name
        self.anomaly_type = anomaly_type

    def add_value(self, value: float) -> Anomaly | None:
        """
        Check value against thresholds.

        Args:
            value: The metric value

        Returns:
            Anomaly if threshold exceeded
        """
        if self.direction == "above":
            if value >= self.critical_threshold:
                severity = AnomalySeverity.CRITICAL
            elif value >= self.warning_threshold:
                severity = AnomalySeverity.WARNING
            else:
                return None
        else:  # below
            if value <= self.critical_threshold:
                severity = AnomalySeverity.CRITICAL
            elif value <= self.warning_threshold:
                severity = AnomalySeverity.WARNING
            else:
                return None

        threshold = (
            self.warning_threshold
            if severity == AnomalySeverity.WARNING
            else self.critical_threshold
        )

        return Anomaly(
            type=self.anomaly_type,
            severity=severity,
            metric_name=self.metric_name,
            current_value=value,
            expected_value=threshold,
            threshold=threshold,
            deviation=abs(value - threshold) / max(threshold, 1e-10),
            service_name=self.service_name,
            model_name=self.model_name,
            message=f"{self.metric_name} is {self.direction} threshold: {value}",
            context={
                "direction": self.direction,
                "warning_threshold": self.warning_threshold,
                "critical_threshold": self.critical_threshold,
            },
        )

    def reset(self) -> None:
        """Reset detector state (no-op for threshold detector)."""


class AnomalyDetectorManager:
    """
    Manages multiple anomaly detectors for a service.

    Provides centralized anomaly detection across multiple metrics.
    """

    def __init__(
        self,
        service_name: str,
        model_name: str | None = None,
        on_anomaly: callable | None = None,
    ):
        """
        Initialize detector manager.

        Args:
            service_name: Name of the service
            model_name: Name of the model
            on_anomaly: Callback function when anomaly detected
        """
        self.service_name = service_name
        self.model_name = model_name
        self.on_anomaly = on_anomaly

        self._detectors: dict[str, BaseAnomalyDetector] = {}
        self._recent_anomalies: deque[Anomaly] = deque(maxlen=100)

        # Set up default detectors
        self._setup_default_detectors()

    def _setup_default_detectors(self) -> None:
        """Set up default detectors for common metrics."""
        # Latency detector
        self.register_detector(
            "request_latency",
            ZScoreDetector(
                metric_name="request_latency",
                window_size=100,
                warning_threshold=2.0,
                critical_threshold=3.0,
                service_name=self.service_name,
                model_name=self.model_name,
                anomaly_type=AnomalyType.LATENCY_SPIKE,
            ),
        )

        # Error rate detector
        self.register_detector(
            "error_rate",
            RateDetector(
                metric_name="error_rate",
                window_seconds=60.0,
                warning_threshold=0.05,
                critical_threshold=0.15,
                service_name=self.service_name,
                model_name=self.model_name,
                anomaly_type=AnomalyType.ERROR_RATE_SPIKE,
            ),
        )

        # Queue depth detector
        self.register_detector(
            "queue_depth",
            ThresholdDetector(
                metric_name="queue_depth",
                warning_threshold=50,
                critical_threshold=100,
                direction="above",
                service_name=self.service_name,
                model_name=self.model_name,
                anomaly_type=AnomalyType.QUEUE_BUILDUP,
            ),
        )

        # GPU temperature detector
        self.register_detector(
            "gpu_temperature",
            ThresholdDetector(
                metric_name="gpu_temperature",
                warning_threshold=80,  # 80°C warning
                critical_threshold=90,  # 90°C critical
                direction="above",
                service_name=self.service_name,
                model_name=self.model_name,
                anomaly_type=AnomalyType.GPU_THERMAL,
            ),
        )

        # Memory trend detector
        self.register_detector(
            "memory_usage",
            TrendDetector(
                metric_name="memory_usage",
                window_size=30,
                trend_threshold=0.8,
                absolute_threshold=0.95,  # 95% memory usage
                service_name=self.service_name,
                model_name=self.model_name,
                anomaly_type=AnomalyType.MEMORY_LEAK,
            ),
        )

    def register_detector(self, name: str, detector: BaseAnomalyDetector) -> None:
        """
        Register a detector.

        Args:
            name: Unique name for the detector
            detector: The detector instance
        """
        self._detectors[name] = detector
        logger.debug(f"Registered anomaly detector: {name}")

    def unregister_detector(self, name: str) -> None:
        """Unregister a detector."""
        if name in self._detectors:
            del self._detectors[name]

    def check(self, metric_name: str, value: float) -> Anomaly | None:
        """
        Check a metric value for anomalies.

        Args:
            metric_name: Name of the metric (should match a registered detector)
            value: The metric value

        Returns:
            Anomaly if detected, None otherwise
        """
        detector = self._detectors.get(metric_name)
        if detector is None:
            return None

        anomaly = detector.add_value(value)
        if anomaly:
            self._recent_anomalies.append(anomaly)
            logger.warning(
                f"Anomaly detected: {anomaly.type.value} - {anomaly.message}",
            )

            if self.on_anomaly:
                try:
                    self.on_anomaly(anomaly)
                except Exception as e:
                    logger.error(f"Error in anomaly callback: {e}")

        return anomaly

    def get_recent_anomalies(
        self,
        limit: int = 10,
        severity: AnomalySeverity | None = None,
    ) -> list[Anomaly]:
        """
        Get recent anomalies.

        Args:
            limit: Maximum number to return
            severity: Filter by severity

        Returns:
            List of recent anomalies
        """
        anomalies = list(self._recent_anomalies)
        anomalies.reverse()  # Most recent first

        if severity:
            anomalies = [a for a in anomalies if a.severity == severity]

        return anomalies[:limit]

    def reset_all(self) -> None:
        """Reset all detectors."""
        for detector in self._detectors.values():
            detector.reset()
        self._recent_anomalies.clear()

    def get_detector_names(self) -> list[str]:
        """Get names of all registered detectors."""
        return list(self._detectors.keys())
