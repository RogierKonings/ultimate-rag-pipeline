"""
Prometheus metrics for LLM Serving Layer.

Provides comprehensive metrics for request tracking, latency monitoring,
token throughput, and resource utilization.
"""

import functools
import logging
import time
from contextlib import contextmanager
from typing import Any, Callable, Optional

from prometheus_client import Counter, Gauge, Histogram, Info

logger = logging.getLogger(__name__)

# Request metrics
REQUEST_TOTAL = Counter(
    "llm_requests_total",
    "Total number of requests",
    ["service", "model", "endpoint", "status"],
)

REQUEST_LATENCY = Histogram(
    "llm_request_latency_seconds",
    "Request latency in seconds",
    ["service", "model", "endpoint"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

REQUEST_IN_PROGRESS = Gauge(
    "llm_requests_in_progress",
    "Number of requests currently being processed",
    ["service", "model"],
)

# Token metrics (for LLM services)
TOKENS_PROCESSED = Counter(
    "llm_tokens_processed_total",
    "Total tokens processed",
    ["service", "model", "type"],  # type: input/output
)

TOKENS_PER_SECOND = Gauge(
    "llm_tokens_per_second",
    "Current token processing rate",
    ["service", "model"],
)

TIME_TO_FIRST_TOKEN = Histogram(
    "llm_time_to_first_token_seconds",
    "Time to first token for streaming responses",
    ["service", "model"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
)

# Embedding metrics
EMBEDDING_DIMENSION = Gauge(
    "llm_embedding_dimension",
    "Embedding vector dimension",
    ["service", "model"],
)

EMBEDDINGS_GENERATED = Counter(
    "llm_embeddings_generated_total",
    "Total embeddings generated",
    ["service", "model"],
)

# Queue metrics
QUEUE_SIZE = Gauge(
    "llm_queue_size",
    "Current queue size",
    ["service", "queue_type"],  # queue_type: request/batch
)

QUEUE_WAIT_TIME = Histogram(
    "llm_queue_wait_seconds",
    "Time spent waiting in queue",
    ["service", "queue_type"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5),
)

# Batch metrics
BATCH_SIZE = Histogram(
    "llm_batch_size",
    "Batch size distribution",
    ["service", "model"],
    buckets=(1, 2, 4, 8, 16, 32, 64, 128),
)

BATCH_PROCESSING_TIME = Histogram(
    "llm_batch_processing_seconds",
    "Batch processing time",
    ["service", "model"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# GPU metrics
GPU_MEMORY_USED = Gauge(
    "llm_gpu_memory_used_bytes",
    "GPU memory currently in use",
    ["gpu_id", "gpu_name"],
)

GPU_MEMORY_TOTAL = Gauge(
    "llm_gpu_memory_total_bytes",
    "Total GPU memory",
    ["gpu_id", "gpu_name"],
)

GPU_UTILIZATION = Gauge(
    "llm_gpu_utilization_percent",
    "GPU compute utilization percentage",
    ["gpu_id", "gpu_name"],
)

GPU_TEMPERATURE = Gauge(
    "llm_gpu_temperature_celsius",
    "GPU temperature in Celsius",
    ["gpu_id", "gpu_name"],
)

GPU_POWER_DRAW = Gauge(
    "llm_gpu_power_watts",
    "GPU power draw in watts",
    ["gpu_id", "gpu_name"],
)

# Model info
MODEL_INFO = Info(
    "llm_model",
    "Model information",
)

# Error metrics
ERROR_TOTAL = Counter(
    "llm_errors_total",
    "Total number of errors",
    ["service", "model", "error_type"],
)

# Cache metrics
CACHE_HITS = Counter(
    "llm_cache_hits_total",
    "Total cache hits",
    ["service", "cache_type"],
)

CACHE_MISSES = Counter(
    "llm_cache_misses_total",
    "Total cache misses",
    ["service", "cache_type"],
)

# Health metrics
HEALTH_CHECK_DURATION = Histogram(
    "llm_health_check_duration_seconds",
    "Health check duration",
    ["service", "check_type"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1),
)

MODEL_LOADED = Gauge(
    "llm_model_loaded",
    "Whether the model is loaded (1) or not (0)",
    ["service", "model"],
)


class MetricsCollector:
    """
    Centralized metrics collection for LLM services.

    Provides convenient methods and decorators for instrumenting code.
    """

    def __init__(self, service_name: str, model_name: Optional[str] = None):
        """
        Initialize metrics collector.

        Args:
            service_name: Name of the service (vllm, embedding, reranker)
            model_name: Name of the model being served
        """
        self.service_name = service_name
        self.model_name = model_name or "unknown"

        # Track in-flight requests
        self._request_start_times: dict[str, float] = {}

    def record_request(
        self,
        endpoint: str,
        status: str,
        latency: float,
        model: Optional[str] = None,
    ) -> None:
        """
        Record a completed request.

        Args:
            endpoint: The endpoint that was called
            status: Request status (success, error, timeout)
            latency: Request latency in seconds
            model: Model name (uses default if not specified)
        """
        model = model or self.model_name

        REQUEST_TOTAL.labels(
            service=self.service_name,
            model=model,
            endpoint=endpoint,
            status=status,
        ).inc()

        REQUEST_LATENCY.labels(
            service=self.service_name,
            model=model,
            endpoint=endpoint,
        ).observe(latency)

    def record_tokens(
        self,
        input_tokens: int,
        output_tokens: int,
        duration: float,
        model: Optional[str] = None,
    ) -> None:
        """
        Record token processing metrics.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            duration: Processing duration in seconds
            model: Model name
        """
        model = model or self.model_name

        TOKENS_PROCESSED.labels(
            service=self.service_name,
            model=model,
            type="input",
        ).inc(input_tokens)

        TOKENS_PROCESSED.labels(
            service=self.service_name,
            model=model,
            type="output",
        ).inc(output_tokens)

        if duration > 0:
            tokens_per_sec = output_tokens / duration
            TOKENS_PER_SECOND.labels(
                service=self.service_name,
                model=model,
            ).set(tokens_per_sec)

    def record_time_to_first_token(
        self,
        ttft: float,
        model: Optional[str] = None,
    ) -> None:
        """
        Record time to first token for streaming.

        Args:
            ttft: Time to first token in seconds
            model: Model name
        """
        model = model or self.model_name

        TIME_TO_FIRST_TOKEN.labels(
            service=self.service_name,
            model=model,
        ).observe(ttft)

    def record_embeddings(
        self,
        count: int,
        model: Optional[str] = None,
    ) -> None:
        """
        Record embedding generation.

        Args:
            count: Number of embeddings generated
            model: Model name
        """
        model = model or self.model_name

        EMBEDDINGS_GENERATED.labels(
            service=self.service_name,
            model=model,
        ).inc(count)

    def record_batch(
        self,
        batch_size: int,
        processing_time: float,
        model: Optional[str] = None,
    ) -> None:
        """
        Record batch processing metrics.

        Args:
            batch_size: Number of items in batch
            processing_time: Batch processing time in seconds
            model: Model name
        """
        model = model or self.model_name

        BATCH_SIZE.labels(
            service=self.service_name,
            model=model,
        ).observe(batch_size)

        BATCH_PROCESSING_TIME.labels(
            service=self.service_name,
            model=model,
        ).observe(processing_time)

    def record_queue_metrics(
        self,
        queue_size: int,
        wait_time: Optional[float] = None,
        queue_type: str = "request",
    ) -> None:
        """
        Record queue metrics.

        Args:
            queue_size: Current queue size
            wait_time: Time spent waiting in queue (optional)
            queue_type: Type of queue (request, batch)
        """
        QUEUE_SIZE.labels(
            service=self.service_name,
            queue_type=queue_type,
        ).set(queue_size)

        if wait_time is not None:
            QUEUE_WAIT_TIME.labels(
                service=self.service_name,
                queue_type=queue_type,
            ).observe(wait_time)

    def record_error(
        self,
        error_type: str,
        model: Optional[str] = None,
    ) -> None:
        """
        Record an error.

        Args:
            error_type: Type of error
            model: Model name
        """
        model = model or self.model_name

        ERROR_TOTAL.labels(
            service=self.service_name,
            model=model,
            error_type=error_type,
        ).inc()

    def record_cache_access(
        self,
        hit: bool,
        cache_type: str = "embedding",
    ) -> None:
        """
        Record cache access.

        Args:
            hit: Whether it was a cache hit
            cache_type: Type of cache
        """
        if hit:
            CACHE_HITS.labels(
                service=self.service_name,
                cache_type=cache_type,
            ).inc()
        else:
            CACHE_MISSES.labels(
                service=self.service_name,
                cache_type=cache_type,
            ).inc()

    def set_model_loaded(self, loaded: bool, model: Optional[str] = None) -> None:
        """
        Update model loaded status.

        Args:
            loaded: Whether model is loaded
            model: Model name
        """
        model = model or self.model_name

        MODEL_LOADED.labels(
            service=self.service_name,
            model=model,
        ).set(1 if loaded else 0)

    def set_model_info(self, info: dict[str, str]) -> None:
        """
        Set model information.

        Args:
            info: Dictionary of model information
        """
        MODEL_INFO.info(info)

    @contextmanager
    def track_request(self, endpoint: str, model: Optional[str] = None):
        """
        Context manager to track request metrics.

        Args:
            endpoint: Endpoint being called
            model: Model name

        Yields:
            None

        Example:
            with collector.track_request("/generate"):
                result = await generate()
        """
        model = model or self.model_name
        start = time.time()

        REQUEST_IN_PROGRESS.labels(
            service=self.service_name,
            model=model,
        ).inc()

        try:
            yield
            status = "success"
        except Exception as e:
            status = "error"
            self.record_error(type(e).__name__, model)
            raise
        finally:
            latency = time.time() - start

            REQUEST_IN_PROGRESS.labels(
                service=self.service_name,
                model=model,
            ).dec()

            self.record_request(endpoint, status, latency, model)

    @contextmanager
    def track_health_check(self, check_type: str = "full"):
        """
        Context manager to track health check duration.

        Args:
            check_type: Type of health check (liveness, readiness, full)

        Yields:
            None
        """
        start = time.time()

        try:
            yield
        finally:
            duration = time.time() - start
            HEALTH_CHECK_DURATION.labels(
                service=self.service_name,
                check_type=check_type,
            ).observe(duration)

    def request_instrumentation(
        self,
        endpoint: str,
        model: Optional[str] = None,
    ) -> Callable:
        """
        Decorator for request instrumentation.

        Args:
            endpoint: Endpoint name
            model: Model name

        Returns:
            Decorated function

        Example:
            @collector.request_instrumentation("/generate")
            async def generate(request):
                ...
        """

        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with self.track_request(endpoint, model):
                    return await func(*args, **kwargs)

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                with self.track_request(endpoint, model):
                    return func(*args, **kwargs)

            import asyncio

            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            return sync_wrapper

        return decorator


def update_gpu_metrics(gpu_id: int, gpu_name: str, metrics: dict) -> None:
    """
    Update GPU metrics from monitoring data.

    Args:
        gpu_id: GPU device ID
        gpu_name: GPU name
        metrics: Dictionary with GPU metrics
    """
    labels = {"gpu_id": str(gpu_id), "gpu_name": gpu_name}

    if "memory_used" in metrics:
        GPU_MEMORY_USED.labels(**labels).set(metrics["memory_used"])

    if "memory_total" in metrics:
        GPU_MEMORY_TOTAL.labels(**labels).set(metrics["memory_total"])

    if "utilization" in metrics:
        GPU_UTILIZATION.labels(**labels).set(metrics["utilization"])

    if "temperature" in metrics:
        GPU_TEMPERATURE.labels(**labels).set(metrics["temperature"])

    if "power_draw" in metrics:
        GPU_POWER_DRAW.labels(**labels).set(metrics["power_draw"])
