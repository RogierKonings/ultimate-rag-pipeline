"""Prometheus metrics for the Retrieval Service."""

import time
from functools import wraps
from typing import Any, Callable, Optional

# Try to import prometheus_client, provide stubs if not available
try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        Info,
        generate_latest,
    )

    HAS_PROMETHEUS = True
except ImportError:
    HAS_PROMETHEUS = False

    # Stub classes for when prometheus is not installed
    class StubMetric:
        def __init__(self, *args: Any, **kwargs: Any):
            self._labels: dict = {}
            self._value = 0

        def labels(self, **kwargs: Any) -> "StubMetric":
            return self

        def inc(self, amount: float = 1) -> None:
            self._value += amount

        def dec(self, amount: float = 1) -> None:
            self._value -= amount

        def set(self, value: float) -> None:
            self._value = value

        def observe(self, value: float) -> None:
            self._value = value

        def info(self, data: dict) -> None:
            pass

    Counter = StubMetric  # type: ignore
    Gauge = StubMetric  # type: ignore
    Histogram = StubMetric  # type: ignore
    Info = StubMetric  # type: ignore
    CONTENT_TYPE_LATEST = "text/plain"

    def generate_latest() -> bytes:
        return b"# Prometheus metrics not available"


class RetrievalMetrics:
    """
    Prometheus metrics for retrieval operations.

    Exposes metrics at /metrics endpoint for Prometheus scraping.
    """

    def __init__(self, service_name: str = "retrieval_service"):
        """
        Initialize Prometheus metrics.

        Args:
            service_name: Prefix for all metric names
        """
        self.service_name = service_name

        # Request counters
        self.requests_total = Counter(
            f"{service_name}_requests_total",
            "Total number of retrieval requests",
            ["mode", "status"],
        )

        # Result counters
        self.results_total = Counter(
            f"{service_name}_results_total",
            "Total number of results returned",
            ["mode"],
        )

        # Latency histograms
        self.request_duration = Histogram(
            f"{service_name}_request_duration_seconds",
            "Request duration in seconds",
            ["mode", "component"],
            buckets=[0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.5, 1.0],
        )

        self.preprocessing_duration = Histogram(
            f"{service_name}_preprocessing_duration_seconds",
            "Query preprocessing duration in seconds",
            buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.2],
        )

        self.search_duration = Histogram(
            f"{service_name}_search_duration_seconds",
            "Search execution duration in seconds",
            ["search_type"],  # semantic, keyword
            buckets=[0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.2],
        )

        self.rerank_duration = Histogram(
            f"{service_name}_rerank_duration_seconds",
            "Reranking duration in seconds",
            ["doc_count_bucket"],  # "1-10", "11-20", "21-50"
            buckets=[0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.2],
        )

        # Score histograms
        self.top_score = Histogram(
            f"{service_name}_top_score",
            "Top result score distribution",
            ["mode"],
            buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        )

        # Result count histogram
        self.result_count = Histogram(
            f"{service_name}_result_count",
            "Number of results per query",
            ["mode"],
            buckets=[0, 1, 2, 5, 10, 20, 50, 100],
        )

        # Cache metrics
        self.cache_hits = Counter(
            f"{service_name}_cache_hits_total",
            "Cache hit count",
            ["cache_type"],
        )

        self.cache_misses = Counter(
            f"{service_name}_cache_misses_total",
            "Cache miss count",
            ["cache_type"],
        )

        # Current state
        self.active_requests = Gauge(
            f"{service_name}_active_requests",
            "Number of currently active requests",
        )

        # Component health
        self.component_health = Gauge(
            f"{service_name}_component_health",
            "Component health status (1=healthy, 0=unhealthy)",
            ["component"],
        )

        # Service info
        self.service_info = Info(
            f"{service_name}_info",
            "Service information",
        )

    def record_request(
        self,
        mode: str,
        status: str,  # "success", "error"
        duration_seconds: float,
        result_count: int,
        top_score: Optional[float] = None,
    ) -> None:
        """
        Record a retrieval request.

        Args:
            mode: Search mode (hybrid, semantic, keyword)
            status: Request status (success or error)
            duration_seconds: Total request duration
            result_count: Number of results returned
            top_score: Score of top result
        """
        self.requests_total.labels(mode=mode, status=status).inc()
        self.request_duration.labels(mode=mode, component="total").observe(
            duration_seconds
        )
        self.result_count.labels(mode=mode).observe(result_count)
        self.results_total.labels(mode=mode).inc(result_count)

        if top_score is not None:
            self.top_score.labels(mode=mode).observe(top_score)

    def record_preprocessing(self, duration_seconds: float) -> None:
        """Record preprocessing duration."""
        self.preprocessing_duration.observe(duration_seconds)

    def record_search(self, search_type: str, duration_seconds: float) -> None:
        """
        Record search duration.

        Args:
            search_type: Type of search (semantic or keyword)
            duration_seconds: Search duration
        """
        self.search_duration.labels(search_type=search_type).observe(duration_seconds)

    def record_rerank(self, doc_count: int, duration_seconds: float) -> None:
        """
        Record reranking duration.

        Args:
            doc_count: Number of documents reranked
            duration_seconds: Reranking duration
        """
        if doc_count <= 10:
            bucket = "1-10"
        elif doc_count <= 20:
            bucket = "11-20"
        else:
            bucket = "21-50"

        self.rerank_duration.labels(doc_count_bucket=bucket).observe(duration_seconds)

    def record_cache(self, cache_type: str, hit: bool) -> None:
        """
        Record cache hit/miss.

        Args:
            cache_type: Type of cache (query, embedding, rerank)
            hit: Whether it was a cache hit
        """
        if hit:
            self.cache_hits.labels(cache_type=cache_type).inc()
        else:
            self.cache_misses.labels(cache_type=cache_type).inc()

    def set_component_health(self, component: str, healthy: bool) -> None:
        """
        Set component health status.

        Args:
            component: Component name (qdrant, opensearch, reranker)
            healthy: Whether component is healthy
        """
        self.component_health.labels(component=component).set(1 if healthy else 0)

    def set_service_info(self, version: str, **extra: Any) -> None:
        """
        Set service info.

        Args:
            version: Service version
            **extra: Additional info fields
        """
        self.service_info.info({"version": version, **extra})

    def request_tracking(self, mode: str = "hybrid") -> Callable:
        """
        Decorator for tracking request metrics.

        Args:
            mode: Search mode for labeling

        Returns:
            Decorator function
        """

        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                self.active_requests.inc()
                start_time = time.time()
                status = "success"

                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception:
                    status = "error"
                    raise
                finally:
                    duration = time.time() - start_time
                    self.active_requests.dec()
                    self.request_duration.labels(mode=mode, component="total").observe(
                        duration
                    )

            return wrapper

        return decorator


# Global metrics instance
metrics = RetrievalMetrics()


def get_metrics_output() -> tuple[bytes, str]:
    """
    Get Prometheus metrics output.

    Returns:
        Tuple of (metrics bytes, content type)
    """
    return generate_latest(), CONTENT_TYPE_LATEST
