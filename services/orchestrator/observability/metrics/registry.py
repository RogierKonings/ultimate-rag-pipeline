"""
RAG Metrics Registry.

Centralized Prometheus metrics for all RAG pipeline operations.
Follows naming convention: rag_<subsystem>_<metric>_<unit>
"""

import os
from typing import Optional

import structlog
from prometheus_client import (
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Info,
    multiprocess,
)

logger = structlog.get_logger(__name__)

# Global metrics instance
_metrics: Optional["RAGMetrics"] = None
_initialized: bool = False

# Histogram buckets for different latency ranges
LATENCY_BUCKETS_FAST = (0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.2, 0.25, 0.3)
LATENCY_BUCKETS_MEDIUM = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0)
LATENCY_BUCKETS_SLOW = (0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.5, 10.0, 15.0)
LATENCY_BUCKETS_LLM = (0.1, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 20.0, 30.0, 60.0)

# Token count buckets
TOKEN_BUCKETS = (10, 50, 100, 250, 500, 1000, 2000, 4000, 8000, 16000)

# Result count buckets
RESULT_BUCKETS = (0, 1, 2, 5, 10, 20, 50, 100)


class RAGMetrics:
    """
    Centralized Prometheus metrics for RAG pipeline.

    All metrics follow the naming convention: rag_<subsystem>_<metric>_<unit>

    Subsystems:
    - query: End-to-end query metrics
    - retrieval: Search and retrieval metrics
    - embedding: Embedding generation metrics
    - llm: LLM inference metrics
    - ingest: Document ingestion metrics
    - cache: Caching metrics
    - system: System-level metrics
    """

    def __init__(
        self,
        service_name: str = "rag_service",
        registry: CollectorRegistry | None = None,
    ):
        """
        Initialize RAG metrics.

        Args:
            service_name: Service name for metric labels
            registry: Custom registry (uses default if None)
        """
        self.service_name = service_name
        self.registry = registry or REGISTRY

        # Initialize all metric groups
        self._init_query_metrics()
        self._init_retrieval_metrics()
        self._init_embedding_metrics()
        self._init_llm_metrics()
        self._init_ingest_metrics()
        self._init_cache_metrics()
        self._init_system_metrics()

    def _init_query_metrics(self) -> None:
        """Initialize query-related metrics."""
        # Query counters
        self.query_total = Counter(
            "rag_query_total",
            "Total number of queries processed",
            ["service", "mode", "status"],
            registry=self.registry,
        )

        # Query latency
        self.query_duration_seconds = Histogram(
            "rag_query_duration_seconds",
            "Query processing duration in seconds",
            ["service", "mode"],
            buckets=LATENCY_BUCKETS_SLOW,
            registry=self.registry,
        )

        # Active queries gauge
        self.query_active = Gauge(
            "rag_query_active",
            "Number of currently active queries",
            ["service"],
            registry=self.registry,
        )

    def _init_retrieval_metrics(self) -> None:
        """Initialize retrieval-related metrics."""
        # Retrieval latency by search type
        self.retrieval_duration_seconds = Histogram(
            "rag_retrieval_duration_seconds",
            "Retrieval duration by search type",
            ["service", "search_type"],  # semantic, keyword, hybrid
            buckets=LATENCY_BUCKETS_MEDIUM,
            registry=self.registry,
        )

        # Result counts
        self.retrieval_result_count = Histogram(
            "rag_retrieval_result_count",
            "Number of results returned per query",
            ["service", "search_type"],
            buckets=RESULT_BUCKETS,
            registry=self.registry,
        )

        # Zero results counter
        self.retrieval_zero_results_total = Counter(
            "rag_retrieval_zero_results_total",
            "Number of queries returning zero results",
            ["service", "search_type"],
            registry=self.registry,
        )

        # Reranking metrics
        self.rerank_duration_seconds = Histogram(
            "rag_rerank_duration_seconds",
            "Reranking duration in seconds",
            ["service", "model"],
            buckets=LATENCY_BUCKETS_MEDIUM,
            registry=self.registry,
        )

        self.rerank_input_count = Histogram(
            "rag_rerank_input_count",
            "Number of documents sent to reranker",
            ["service"],
            buckets=RESULT_BUCKETS,
            registry=self.registry,
        )

        # Score distribution
        self.retrieval_top_score = Histogram(
            "rag_retrieval_top_score",
            "Top result score distribution",
            ["service", "search_type"],
            buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
            registry=self.registry,
        )

    def _init_embedding_metrics(self) -> None:
        """Initialize embedding-related metrics."""
        # Embedding latency
        self.embedding_duration_seconds = Histogram(
            "rag_embedding_duration_seconds",
            "Embedding generation duration",
            ["service", "model"],
            buckets=LATENCY_BUCKETS_FAST,
            registry=self.registry,
        )

        # Token counts
        self.embedding_tokens_total = Counter(
            "rag_embedding_tokens_total",
            "Total tokens embedded",
            ["service", "model"],
            registry=self.registry,
        )

        # Batch sizes
        self.embedding_batch_size = Histogram(
            "rag_embedding_batch_size",
            "Embedding batch size distribution",
            ["service"],
            buckets=(1, 2, 4, 8, 16, 32, 64, 128),
            registry=self.registry,
        )

        # Embeddings generated
        self.embedding_generated_total = Counter(
            "rag_embedding_generated_total",
            "Total embeddings generated",
            ["service", "model"],
            registry=self.registry,
        )

    def _init_llm_metrics(self) -> None:
        """Initialize LLM-related metrics."""
        # LLM request counter
        self.llm_requests_total = Counter(
            "rag_llm_requests_total",
            "Total LLM requests",
            ["service", "model", "provider", "status"],
            registry=self.registry,
        )

        # LLM latency
        self.llm_duration_seconds = Histogram(
            "rag_llm_duration_seconds",
            "LLM inference duration",
            ["service", "model"],
            buckets=LATENCY_BUCKETS_LLM,
            registry=self.registry,
        )

        # Time to first token
        self.llm_ttft_seconds = Histogram(
            "rag_llm_ttft_seconds",
            "Time to first token for streaming",
            ["service", "model"],
            buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
            registry=self.registry,
        )

        # Token throughput
        self.llm_tokens_total = Counter(
            "rag_llm_tokens_total",
            "Total LLM tokens processed",
            ["service", "model", "type"],  # type: input, output
            registry=self.registry,
        )

        # Tokens per second gauge
        self.llm_tokens_per_second = Gauge(
            "rag_llm_tokens_per_second",
            "Current LLM token throughput",
            ["service", "model"],
            registry=self.registry,
        )

        # Context length distribution
        self.llm_context_tokens = Histogram(
            "rag_llm_context_tokens",
            "LLM context length in tokens",
            ["service", "model"],
            buckets=TOKEN_BUCKETS,
            registry=self.registry,
        )

    def _init_ingest_metrics(self) -> None:
        """Initialize ingestion-related metrics."""
        # Documents ingested
        self.ingest_documents_total = Counter(
            "rag_ingest_documents_total",
            "Total documents ingested",
            ["service", "source_type", "status"],
            registry=self.registry,
        )

        # Chunks created
        self.ingest_chunks_total = Counter(
            "rag_ingest_chunks_total",
            "Total chunks created",
            ["service", "strategy"],
            registry=self.registry,
        )

        # Ingestion latency by stage
        self.ingest_duration_seconds = Histogram(
            "rag_ingest_duration_seconds",
            "Ingestion duration by stage",
            ["service", "stage"],  # parse, chunk, embed, index
            buckets=LATENCY_BUCKETS_SLOW,
            registry=self.registry,
        )

        # Queue metrics
        self.ingest_queue_size = Gauge(
            "rag_ingest_queue_size",
            "Current ingestion queue size",
            ["service", "queue"],
            registry=self.registry,
        )

        # Data throughput
        self.ingest_bytes_total = Counter(
            "rag_ingest_bytes_total",
            "Total bytes ingested",
            ["service", "source_type"],
            registry=self.registry,
        )

    def _init_cache_metrics(self) -> None:
        """Initialize cache-related metrics."""
        # Cache hits/misses
        self.cache_hits_total = Counter(
            "rag_cache_hits_total",
            "Total cache hits",
            ["service", "cache_type"],  # embedding, query, response
            registry=self.registry,
        )

        self.cache_misses_total = Counter(
            "rag_cache_misses_total",
            "Total cache misses",
            ["service", "cache_type"],
            registry=self.registry,
        )

        # Cache size
        self.cache_size_bytes = Gauge(
            "rag_cache_size_bytes",
            "Current cache size in bytes",
            ["service", "cache_type"],
            registry=self.registry,
        )

        # Cache operations
        self.cache_operations_total = Counter(
            "rag_cache_operations_total",
            "Total cache operations",
            ["service", "cache_type", "operation"],  # get, set, delete
            registry=self.registry,
        )

    def _init_system_metrics(self) -> None:
        """Initialize system-level metrics."""
        # Service info
        self.service_info = Info(
            "rag_service",
            "RAG service information",
            registry=self.registry,
        )

        # Component health
        self.component_health = Gauge(
            "rag_component_health",
            "Component health status (1=healthy, 0=unhealthy)",
            ["service", "component"],
            registry=self.registry,
        )

        # Error counter
        self.errors_total = Counter(
            "rag_errors_total",
            "Total errors by type",
            ["service", "error_type", "component"],
            registry=self.registry,
        )

    # =========================================================================
    # Recording methods
    # =========================================================================

    def record_query(
        self,
        mode: str,
        duration: float,
        result_count: int,
        status: str = "success",
        top_score: float | None = None,
    ) -> None:
        """
        Record a query execution.

        Args:
            mode: Search mode (hybrid, semantic, keyword)
            duration: Query duration in seconds
            result_count: Number of results returned
            status: Query status (success, error)
            top_score: Score of top result
        """
        self.query_total.labels(
            service=self.service_name,
            mode=mode,
            status=status,
        ).inc()

        self.query_duration_seconds.labels(
            service=self.service_name,
            mode=mode,
        ).observe(duration)

        self.retrieval_result_count.labels(
            service=self.service_name,
            search_type=mode,
        ).observe(result_count)

        if result_count == 0:
            self.retrieval_zero_results_total.labels(
                service=self.service_name,
                search_type=mode,
            ).inc()

        if top_score is not None:
            self.retrieval_top_score.labels(
                service=self.service_name,
                search_type=mode,
            ).observe(top_score)

    def record_retrieval(
        self,
        search_type: str,
        duration: float,
        result_count: int,
    ) -> None:
        """
        Record a retrieval operation.

        Args:
            search_type: Type of search (semantic, keyword, hybrid)
            duration: Search duration in seconds
            result_count: Number of results
        """
        self.retrieval_duration_seconds.labels(
            service=self.service_name,
            search_type=search_type,
        ).observe(duration)

        self.retrieval_result_count.labels(
            service=self.service_name,
            search_type=search_type,
        ).observe(result_count)

    def record_rerank(
        self,
        duration: float,
        input_count: int,
        model: str = "default",
    ) -> None:
        """
        Record a reranking operation.

        Args:
            duration: Reranking duration in seconds
            input_count: Number of documents reranked
            model: Reranker model name
        """
        self.rerank_duration_seconds.labels(
            service=self.service_name,
            model=model,
        ).observe(duration)

        self.rerank_input_count.labels(
            service=self.service_name,
        ).observe(input_count)

    def record_embedding(
        self,
        duration: float,
        token_count: int,
        batch_size: int = 1,
        model: str = "default",
    ) -> None:
        """
        Record an embedding operation.

        Args:
            duration: Embedding duration in seconds
            token_count: Number of tokens embedded
            batch_size: Batch size
            model: Embedding model name
        """
        self.embedding_duration_seconds.labels(
            service=self.service_name,
            model=model,
        ).observe(duration)

        self.embedding_tokens_total.labels(
            service=self.service_name,
            model=model,
        ).inc(token_count)

        self.embedding_batch_size.labels(
            service=self.service_name,
        ).observe(batch_size)

        self.embedding_generated_total.labels(
            service=self.service_name,
            model=model,
        ).inc(batch_size)

    def record_llm(
        self,
        model: str,
        duration: float,
        input_tokens: int,
        output_tokens: int,
        status: str = "success",
        provider: str = "default",
        ttft: float | None = None,
    ) -> None:
        """
        Record an LLM inference.

        Args:
            model: Model name
            duration: Inference duration in seconds
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            status: Request status
            provider: LLM provider
            ttft: Time to first token (for streaming)
        """
        self.llm_requests_total.labels(
            service=self.service_name,
            model=model,
            provider=provider,
            status=status,
        ).inc()

        self.llm_duration_seconds.labels(
            service=self.service_name,
            model=model,
        ).observe(duration)

        self.llm_tokens_total.labels(
            service=self.service_name,
            model=model,
            type="input",
        ).inc(input_tokens)

        self.llm_tokens_total.labels(
            service=self.service_name,
            model=model,
            type="output",
        ).inc(output_tokens)

        self.llm_context_tokens.labels(
            service=self.service_name,
            model=model,
        ).observe(input_tokens)

        if ttft is not None:
            self.llm_ttft_seconds.labels(
                service=self.service_name,
                model=model,
            ).observe(ttft)

        # Calculate and record throughput
        if duration > 0:
            tokens_per_sec = output_tokens / duration
            self.llm_tokens_per_second.labels(
                service=self.service_name,
                model=model,
            ).set(tokens_per_sec)

    def record_ingest(
        self,
        source_type: str,
        duration: float,
        chunk_count: int,
        status: str = "success",
        stage: str = "total",
        bytes_processed: int = 0,
        strategy: str = "recursive",
    ) -> None:
        """
        Record a document ingestion.

        Args:
            source_type: Source type (file, web, api, database)
            duration: Ingestion duration in seconds
            chunk_count: Number of chunks created
            status: Ingestion status
            stage: Ingestion stage (parse, chunk, embed, index, total)
            bytes_processed: Bytes processed
            strategy: Chunking strategy
        """
        self.ingest_documents_total.labels(
            service=self.service_name,
            source_type=source_type,
            status=status,
        ).inc()

        self.ingest_duration_seconds.labels(
            service=self.service_name,
            stage=stage,
        ).observe(duration)

        if chunk_count > 0:
            self.ingest_chunks_total.labels(
                service=self.service_name,
                strategy=strategy,
            ).inc(chunk_count)

        if bytes_processed > 0:
            self.ingest_bytes_total.labels(
                service=self.service_name,
                source_type=source_type,
            ).inc(bytes_processed)

    def record_cache(
        self,
        cache_type: str,
        hit: bool,
        operation: str = "get",
    ) -> None:
        """
        Record a cache operation.

        Args:
            cache_type: Type of cache (embedding, query, response)
            hit: Whether it was a cache hit
            operation: Operation type (get, set, delete)
        """
        if operation == "get":
            if hit:
                self.cache_hits_total.labels(
                    service=self.service_name,
                    cache_type=cache_type,
                ).inc()
            else:
                self.cache_misses_total.labels(
                    service=self.service_name,
                    cache_type=cache_type,
                ).inc()

        self.cache_operations_total.labels(
            service=self.service_name,
            cache_type=cache_type,
            operation=operation,
        ).inc()

    def record_error(
        self,
        error_type: str,
        component: str,
    ) -> None:
        """
        Record an error.

        Args:
            error_type: Type of error
            component: Component where error occurred
        """
        self.errors_total.labels(
            service=self.service_name,
            error_type=error_type,
            component=component,
        ).inc()

    def set_component_health(
        self,
        component: str,
        healthy: bool,
    ) -> None:
        """
        Set component health status.

        Args:
            component: Component name
            healthy: Whether component is healthy
        """
        self.component_health.labels(
            service=self.service_name,
            component=component,
        ).set(1 if healthy else 0)

    def set_service_info(
        self,
        version: str,
        environment: str = "development",
        **extra: str,
    ) -> None:
        """
        Set service info.

        Args:
            version: Service version
            environment: Deployment environment
            **extra: Additional info fields
        """
        self.service_info.info(
            {
                "service": self.service_name,
                "version": version,
                "environment": environment,
                **extra,
            },
        )

    def inc_active_queries(self) -> None:
        """Increment active queries gauge."""
        self.query_active.labels(service=self.service_name).inc()

    def dec_active_queries(self) -> None:
        """Decrement active queries gauge."""
        self.query_active.labels(service=self.service_name).dec()

    def set_queue_size(self, queue: str, size: int) -> None:
        """Set ingestion queue size."""
        self.ingest_queue_size.labels(
            service=self.service_name,
            queue=queue,
        ).set(size)


def setup_metrics(
    service_name: str,
    service_version: str = "1.0.0",
    multiprocess_mode: bool = False,
) -> RAGMetrics:
    """
    Initialize metrics collection.

    Args:
        service_name: Name of the service
        service_version: Version of the service
        multiprocess_mode: Enable multiprocess mode for gunicorn

    Returns:
        RAGMetrics instance
    """
    global _metrics, _initialized

    if _initialized and _metrics is not None:
        logger.debug("Metrics already initialized")
        return _metrics

    # Handle multiprocess mode (for gunicorn)
    registry = REGISTRY
    if multiprocess_mode:
        prometheus_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
        if prometheus_dir:
            registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(registry)
            logger.info(f"Multiprocess metrics enabled: {prometheus_dir}")

    _metrics = RAGMetrics(service_name=service_name, registry=registry)
    _metrics.set_service_info(version=service_version)
    _initialized = True

    logger.info(f"Metrics initialized for {service_name}")
    return _metrics


def get_metrics() -> RAGMetrics:
    """
    Get the global metrics instance.

    Returns:
        RAGMetrics instance

    Raises:
        RuntimeError: If metrics not initialized
    """
    global _metrics

    if _metrics is None:
        # Create default instance
        _metrics = RAGMetrics()

    return _metrics


def get_metrics_registry() -> CollectorRegistry:
    """
    Get the Prometheus registry.

    Returns:
        CollectorRegistry
    """
    return REGISTRY
