"""
RAG-specific Semantic Attributes for OpenTelemetry.

Defines standard attribute names and enums for consistent
tracing across all RAG pipeline services.

These follow OpenTelemetry semantic conventions where applicable,
with RAG-specific extensions prefixed with "rag.".
"""

from enum import Enum
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span


class RAGOperation(str, Enum):
    """
    Enumeration of RAG pipeline operations.

    Used to categorize spans by operation type.
    """

    # Query operations
    QUERY = "query"
    QUERY_PREPROCESS = "query.preprocess"
    QUERY_EXPAND = "query.expand"

    # Embedding operations
    EMBEDDING = "embedding"
    EMBEDDING_BATCH = "embedding.batch"

    # Search operations
    VECTOR_SEARCH = "search.vector"
    KEYWORD_SEARCH = "search.keyword"
    HYBRID_SEARCH = "search.hybrid"

    # Fusion and reranking
    FUSION = "fusion"
    RERANK = "rerank"

    # LLM operations
    LLM_INFERENCE = "llm.inference"
    LLM_STREAMING = "llm.streaming"
    LLM_COMPLETION = "llm.completion"
    LLM_CHAT = "llm.chat"

    # Ingestion operations
    INGEST = "ingest"
    INGEST_PARSE = "ingest.parse"
    INGEST_CHUNK = "ingest.chunk"
    INGEST_EMBED = "ingest.embed"
    INGEST_INDEX = "ingest.index"

    # Orchestration
    ORCHESTRATE = "orchestrate"
    ROUTE = "route"
    PROMPT_BUILD = "prompt.build"
    GUARDRAIL = "guardrail"

    # Cache operations
    CACHE_READ = "cache.read"
    CACHE_WRITE = "cache.write"

    # Database operations
    DB_READ = "db.read"
    DB_WRITE = "db.write"


class RAGAttributes:
    """
    Standard attribute names for RAG tracing.

    All RAG-specific attributes are prefixed with "rag.".
    """

    # Operation metadata
    OPERATION = "rag.operation"
    TENANT_ID = "rag.tenant_id"
    USER_ID = "rag.user_id"
    REQUEST_ID = "rag.request_id"
    CONVERSATION_ID = "rag.conversation_id"

    # Query attributes
    QUERY_TEXT = "rag.query.text"
    QUERY_LENGTH = "rag.query.length"
    QUERY_TOKENS = "rag.query.tokens"
    QUERY_LANGUAGE = "rag.query.language"
    QUERY_INTENT = "rag.query.intent"

    # Search configuration
    SEARCH_MODE = "rag.search.mode"
    SEARCH_TOP_K = "rag.search.top_k"
    SEARCH_THRESHOLD = "rag.search.threshold"
    SEARCH_FILTERS = "rag.search.filters"

    # Retrieval results
    RETRIEVAL_COUNT = "rag.retrieval.count"
    RETRIEVAL_TOP_SCORE = "rag.retrieval.top_score"
    RETRIEVAL_AVG_SCORE = "rag.retrieval.avg_score"
    RETRIEVAL_MIN_SCORE = "rag.retrieval.min_score"
    RETRIEVAL_ZERO_RESULTS = "rag.retrieval.zero_results"

    # Vector search specific
    VECTOR_COLLECTION = "rag.vector.collection"
    VECTOR_DIMENSION = "rag.vector.dimension"
    VECTOR_METRIC = "rag.vector.metric"

    # Keyword search specific
    KEYWORD_INDEX = "rag.keyword.index"
    KEYWORD_ANALYZER = "rag.keyword.analyzer"

    # Fusion parameters
    FUSION_METHOD = "rag.fusion.method"
    FUSION_SEMANTIC_WEIGHT = "rag.fusion.semantic_weight"
    FUSION_KEYWORD_WEIGHT = "rag.fusion.keyword_weight"
    FUSION_RRF_K = "rag.fusion.rrf_k"

    # Reranking
    RERANK_MODEL = "rag.rerank.model"
    RERANK_INPUT_COUNT = "rag.rerank.input_count"
    RERANK_OUTPUT_COUNT = "rag.rerank.output_count"

    # Embedding
    EMBEDDING_MODEL = "rag.embedding.model"
    EMBEDDING_DIMENSION = "rag.embedding.dimension"
    EMBEDDING_BATCH_SIZE = "rag.embedding.batch_size"
    EMBEDDING_TOKENS = "rag.embedding.tokens"

    # LLM attributes
    LLM_MODEL = "rag.llm.model"
    LLM_PROVIDER = "rag.llm.provider"
    LLM_INPUT_TOKENS = "rag.llm.input_tokens"
    LLM_OUTPUT_TOKENS = "rag.llm.output_tokens"
    LLM_TOTAL_TOKENS = "rag.llm.total_tokens"
    LLM_TEMPERATURE = "rag.llm.temperature"
    LLM_MAX_TOKENS = "rag.llm.max_tokens"
    LLM_STOP_REASON = "rag.llm.stop_reason"
    LLM_TTFT_MS = "rag.llm.ttft_ms"  # Time to first token

    # Ingestion attributes
    INGEST_DOCUMENT_ID = "rag.ingest.document_id"
    INGEST_SOURCE_TYPE = "rag.ingest.source_type"
    INGEST_SOURCE_URI = "rag.ingest.source_uri"
    INGEST_CONTENT_TYPE = "rag.ingest.content_type"
    INGEST_CHUNK_COUNT = "rag.ingest.chunk_count"
    INGEST_CHUNK_STRATEGY = "rag.ingest.chunk_strategy"
    INGEST_CHUNK_SIZE = "rag.ingest.chunk_size"
    INGEST_CHUNK_OVERLAP = "rag.ingest.chunk_overlap"

    # Cache attributes
    CACHE_TYPE = "rag.cache.type"
    CACHE_HIT = "rag.cache.hit"
    CACHE_KEY = "rag.cache.key"
    CACHE_TTL = "rag.cache.ttl"

    # Error attributes
    ERROR_TYPE = "rag.error.type"
    ERROR_MESSAGE = "rag.error.message"
    ERROR_RETRY_COUNT = "rag.error.retry_count"

    # Performance
    DURATION_MS = "rag.duration_ms"
    QUEUE_TIME_MS = "rag.queue_time_ms"


def set_rag_attributes(
    span: Span | None = None,
    operation: RAGOperation | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
    request_id: str | None = None,
    **kwargs: Any,
) -> None:
    """
    Set RAG-specific attributes on a span.

    Args:
        span: Span to set attributes on (uses current span if None)
        operation: RAG operation type
        tenant_id: Tenant identifier
        user_id: User identifier
        request_id: Request identifier
        **kwargs: Additional attributes (keys should be RAGAttributes constants)
    """
    if span is None:
        span = trace.get_current_span()

    if span is None or not span.is_recording():
        return

    if operation is not None:
        span.set_attribute(RAGAttributes.OPERATION, operation.value)

    if tenant_id is not None:
        span.set_attribute(RAGAttributes.TENANT_ID, tenant_id)

    if user_id is not None:
        span.set_attribute(RAGAttributes.USER_ID, user_id)

    if request_id is not None:
        span.set_attribute(RAGAttributes.REQUEST_ID, request_id)

    # Set additional attributes
    for key, value in kwargs.items():
        if value is not None:
            # Convert complex types to strings
            if isinstance(value, (list, dict)):
                import json

                span.set_attribute(key, json.dumps(value))
            elif isinstance(value, Enum):
                span.set_attribute(key, value.value)
            else:
                span.set_attribute(key, value)


def set_retrieval_results(
    span: Span | None = None,
    count: int = 0,
    scores: list[float] | None = None,
) -> None:
    """
    Set retrieval result attributes on a span.

    Args:
        span: Span to set attributes on (uses current span if None)
        count: Number of results returned
        scores: List of result scores
    """
    if span is None:
        span = trace.get_current_span()

    if span is None or not span.is_recording():
        return

    span.set_attribute(RAGAttributes.RETRIEVAL_COUNT, count)
    span.set_attribute(RAGAttributes.RETRIEVAL_ZERO_RESULTS, count == 0)

    if scores and len(scores) > 0:
        span.set_attribute(RAGAttributes.RETRIEVAL_TOP_SCORE, max(scores))
        span.set_attribute(RAGAttributes.RETRIEVAL_AVG_SCORE, sum(scores) / len(scores))
        span.set_attribute(RAGAttributes.RETRIEVAL_MIN_SCORE, min(scores))


def set_llm_usage(
    span: Span | None = None,
    model: str | None = None,
    provider: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    ttft_ms: float | None = None,
    stop_reason: str | None = None,
) -> None:
    """
    Set LLM usage attributes on a span.

    Args:
        span: Span to set attributes on (uses current span if None)
        model: Model name/identifier
        provider: LLM provider name
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        ttft_ms: Time to first token in milliseconds
        stop_reason: Reason for completion stop
    """
    if span is None:
        span = trace.get_current_span()

    if span is None or not span.is_recording():
        return

    if model is not None:
        span.set_attribute(RAGAttributes.LLM_MODEL, model)

    if provider is not None:
        span.set_attribute(RAGAttributes.LLM_PROVIDER, provider)

    if input_tokens is not None:
        span.set_attribute(RAGAttributes.LLM_INPUT_TOKENS, input_tokens)

    if output_tokens is not None:
        span.set_attribute(RAGAttributes.LLM_OUTPUT_TOKENS, output_tokens)

    if input_tokens is not None and output_tokens is not None:
        span.set_attribute(RAGAttributes.LLM_TOTAL_TOKENS, input_tokens + output_tokens)

    if ttft_ms is not None:
        span.set_attribute(RAGAttributes.LLM_TTFT_MS, ttft_ms)

    if stop_reason is not None:
        span.set_attribute(RAGAttributes.LLM_STOP_REASON, stop_reason)


def set_embedding_attributes(
    span: Span | None = None,
    model: str | None = None,
    dimension: int | None = None,
    batch_size: int | None = None,
    tokens: int | None = None,
) -> None:
    """
    Set embedding operation attributes on a span.

    Args:
        span: Span to set attributes on (uses current span if None)
        model: Embedding model name
        dimension: Embedding dimension
        batch_size: Batch size
        tokens: Total tokens processed
    """
    if span is None:
        span = trace.get_current_span()

    if span is None or not span.is_recording():
        return

    if model is not None:
        span.set_attribute(RAGAttributes.EMBEDDING_MODEL, model)

    if dimension is not None:
        span.set_attribute(RAGAttributes.EMBEDDING_DIMENSION, dimension)

    if batch_size is not None:
        span.set_attribute(RAGAttributes.EMBEDDING_BATCH_SIZE, batch_size)

    if tokens is not None:
        span.set_attribute(RAGAttributes.EMBEDDING_TOKENS, tokens)


def set_cache_attributes(
    span: Span | None = None,
    cache_type: str | None = None,
    hit: bool | None = None,
    key: str | None = None,
    ttl: int | None = None,
) -> None:
    """
    Set cache operation attributes on a span.

    Args:
        span: Span to set attributes on (uses current span if None)
        cache_type: Type of cache (embedding, query, response)
        hit: Whether it was a cache hit
        key: Cache key (truncated for safety)
        ttl: Cache TTL in seconds
    """
    if span is None:
        span = trace.get_current_span()

    if span is None or not span.is_recording():
        return

    if cache_type is not None:
        span.set_attribute(RAGAttributes.CACHE_TYPE, cache_type)

    if hit is not None:
        span.set_attribute(RAGAttributes.CACHE_HIT, hit)

    if key is not None:
        # Truncate key for safety
        span.set_attribute(RAGAttributes.CACHE_KEY, key[:100])

    if ttl is not None:
        span.set_attribute(RAGAttributes.CACHE_TTL, ttl)
