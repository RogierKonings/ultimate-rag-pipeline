"""
Phoenix Tracer.

Provides LLM call tracing with Phoenix integration.
"""

import logging
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Optional
from uuid import uuid4

from .config import PhoenixConfig

logger = logging.getLogger(__name__)


@dataclass
class LLMSpan:
    """Represents a single LLM call span."""

    id: str = field(default_factory=lambda: str(uuid4()))
    trace_id: str = ""
    parent_id: str | None = None
    name: str = ""
    span_type: str = "llm"  # llm, embedding, retrieval, chain

    # Timing
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: datetime | None = None
    latency_ms: float = 0.0

    # LLM specific
    model: str = ""
    provider: str = ""
    prompt: str = ""
    completion: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    # Embeddings
    embedding_model: str = ""
    embedding_dimensions: int = 0
    num_embeddings: int = 0

    # Retrieval
    query: str = ""
    num_results: int = 0
    retrieval_strategy: str = ""

    # Status
    status: str = "ok"  # ok, error
    error_message: str | None = None

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    def finish(self, error: str | None = None) -> None:
        """Mark span as finished."""
        self.end_time = datetime.now(tz=UTC)
        self.latency_ms = (self.end_time - self.start_time).total_seconds() * 1000
        if error:
            self.status = "error"
            self.error_message = error

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "span_type": self.span_type,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "latency_ms": self.latency_ms,
            "model": self.model,
            "provider": self.provider,
            "prompt": self.prompt,
            "completion": self.completion,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "embedding_model": self.embedding_model,
            "embedding_dimensions": self.embedding_dimensions,
            "num_embeddings": self.num_embeddings,
            "query": self.query,
            "num_results": self.num_results,
            "retrieval_strategy": self.retrieval_strategy,
            "status": self.status,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }


class PhoenixTracer:
    """
    Tracer for LLM calls with Phoenix integration.

    Collects and exports LLM call traces to Phoenix for analysis.
    """

    _instance: Optional["PhoenixTracer"] = None

    def __init__(self, config: PhoenixConfig | None = None):
        """
        Initialize Phoenix tracer.

        Args:
            config: Phoenix configuration
        """
        self.config = config or PhoenixConfig.from_env()
        self._queue: deque[LLMSpan] = deque(maxlen=self.config.max_queue_size)
        self._lock = threading.Lock()
        self._flush_thread: threading.Thread | None = None
        self._running = False
        self._tokenizer = None

        if self.config.enabled:
            self._start_flush_thread()

    @classmethod
    def get_instance(cls, config: PhoenixConfig | None = None) -> "PhoenixTracer":
        """Get or create singleton instance."""
        if cls._instance is None:
            cls._instance = cls(config)
        return cls._instance

    def _start_flush_thread(self) -> None:
        """Start background flush thread."""
        self._running = True
        self._flush_thread = threading.Thread(
            target=self._flush_loop,
            daemon=True,
            name="phoenix-flush",
        )
        self._flush_thread.start()

    def _flush_loop(self) -> None:
        """Background loop to flush spans."""
        while self._running:
            time.sleep(self.config.flush_interval)
            try:
                self._flush()
            except Exception as e:
                logger.error(f"Error flushing spans: {e}")

    def _flush(self) -> None:
        """Flush queued spans to Phoenix."""
        with self._lock:
            if not self._queue:
                return

            spans = list(self._queue)
            self._queue.clear()

        if spans:
            self._send_spans(spans)

    def _send_spans(self, spans: list[LLMSpan]) -> None:
        """Send spans to Phoenix server."""
        try:
            import httpx

            # Convert spans to Phoenix format
            payload = {
                "project": self.config.project_name,
                "spans": [self._to_phoenix_format(s) for s in spans],
            }

            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    f"{self.config.phoenix_url}/v1/spans",
                    json=payload,
                )
                response.raise_for_status()

            logger.debug(f"Sent {len(spans)} spans to Phoenix")

        except Exception as e:
            logger.error(f"Failed to send spans to Phoenix: {e}")

    def _to_phoenix_format(self, span: LLMSpan) -> dict[str, Any]:
        """Convert span to Phoenix-compatible format."""
        phoenix_span = {
            "context": {
                "trace_id": span.trace_id,
                "span_id": span.id,
            },
            "name": span.name,
            "kind": self._get_span_kind(span.span_type),
            "start_time": span.start_time.isoformat(),
            "end_time": span.end_time.isoformat() if span.end_time else None,
            "status": {"status_code": "OK" if span.status == "ok" else "ERROR"},
            "attributes": {},
        }

        # Add type-specific attributes
        if span.span_type == "llm":
            phoenix_span["attributes"].update(
                {
                    "llm.model_name": span.model,
                    "llm.provider": span.provider,
                    "llm.token_count.prompt": span.prompt_tokens,
                    "llm.token_count.completion": span.completion_tokens,
                    "llm.token_count.total": span.total_tokens,
                },
            )
            if self.config.log_prompts:
                phoenix_span["attributes"]["llm.prompts"] = [span.prompt]
            if self.config.log_responses:
                phoenix_span["attributes"]["llm.completions"] = [span.completion]

        elif span.span_type == "embedding":
            phoenix_span["attributes"].update(
                {
                    "embedding.model_name": span.embedding_model,
                    "embedding.embeddings": span.num_embeddings,
                },
            )

        elif span.span_type == "retrieval":
            phoenix_span["attributes"].update(
                {
                    "retrieval.strategy": span.retrieval_strategy,
                    "retrieval.documents": span.num_results,
                },
            )

        # Add metadata
        for key, value in span.metadata.items():
            phoenix_span["attributes"][f"metadata.{key}"] = value

        if span.error_message:
            phoenix_span["status"]["message"] = span.error_message

        return phoenix_span

    def _get_span_kind(self, span_type: str) -> str:
        """Map span type to Phoenix span kind."""
        mapping = {
            "llm": "LLM",
            "embedding": "EMBEDDING",
            "retrieval": "RETRIEVER",
            "chain": "CHAIN",
        }
        return mapping.get(span_type, "UNKNOWN")

    def _should_sample(self) -> bool:
        """Determine if this trace should be sampled."""
        return random.random() < self.config.sample_rate  # noqa: S311

    def _count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        if not self.config.count_tokens:
            return 0

        try:
            if self._tokenizer is None:
                import tiktoken

                self._tokenizer = tiktoken.get_encoding(self.config.tokenizer_model)
            return len(self._tokenizer.encode(text))
        except Exception:
            # Fallback: rough estimate
            return len(text) // 4

    def start_trace(self, name: str = "rag_query") -> str:
        """
        Start a new trace.

        Args:
            name: Name for the trace

        Returns:
            Trace ID
        """
        return str(uuid4())

    def start_span(
        self,
        name: str,
        trace_id: str,
        span_type: str = "llm",
        parent_id: str | None = None,
        **kwargs: Any,
    ) -> LLMSpan:
        """
        Start a new span.

        Args:
            name: Span name
            trace_id: Parent trace ID
            span_type: Type of span (llm, embedding, retrieval, chain)
            parent_id: Parent span ID
            **kwargs: Additional span attributes

        Returns:
            LLMSpan instance
        """
        return LLMSpan(
            trace_id=trace_id,
            parent_id=parent_id,
            name=name,
            span_type=span_type,
            **kwargs,
        )

    def end_span(self, span: LLMSpan, error: str | None = None) -> None:
        """
        End a span and queue for export.

        Args:
            span: The span to end
            error: Optional error message
        """
        if not self.config.enabled:
            return

        if not self._should_sample():
            return

        span.finish(error)

        # Count tokens if not already set
        if span.span_type == "llm":
            if span.prompt_tokens == 0 and span.prompt:
                span.prompt_tokens = self._count_tokens(span.prompt)
            if span.completion_tokens == 0 and span.completion:
                span.completion_tokens = self._count_tokens(span.completion)
            span.total_tokens = span.prompt_tokens + span.completion_tokens

        with self._lock:
            self._queue.append(span)

    def record_llm_call(
        self,
        trace_id: str,
        model: str,
        prompt: str,
        completion: str,
        provider: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: float = 0.0,
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> LLMSpan:
        """
        Record a complete LLM call.

        Args:
            trace_id: Trace ID
            model: Model name
            prompt: Input prompt
            completion: Model completion
            provider: LLM provider (openai, anthropic, etc.)
            prompt_tokens: Number of prompt tokens
            completion_tokens: Number of completion tokens
            latency_ms: Call latency in milliseconds
            parent_id: Parent span ID
            metadata: Additional metadata
            error: Error message if call failed

        Returns:
            The recorded span
        """
        span = self.start_span(
            name=f"llm.{model}",
            trace_id=trace_id,
            span_type="llm",
            parent_id=parent_id,
            model=model,
            provider=provider,
            prompt=prompt,
            completion=completion,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            metadata=metadata or {},
        )

        if latency_ms > 0:
            span.latency_ms = latency_ms

        self.end_span(span, error)
        return span

    def record_embedding(
        self,
        trace_id: str,
        model: str,
        num_embeddings: int,
        dimensions: int = 0,
        latency_ms: float = 0.0,
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LLMSpan:
        """
        Record an embedding call.

        Args:
            trace_id: Trace ID
            model: Embedding model name
            num_embeddings: Number of embeddings generated
            dimensions: Embedding dimensions
            latency_ms: Call latency
            parent_id: Parent span ID
            metadata: Additional metadata

        Returns:
            The recorded span
        """
        span = self.start_span(
            name=f"embedding.{model}",
            trace_id=trace_id,
            span_type="embedding",
            parent_id=parent_id,
            embedding_model=model,
            num_embeddings=num_embeddings,
            embedding_dimensions=dimensions,
            metadata=metadata or {},
        )

        if latency_ms > 0:
            span.latency_ms = latency_ms

        self.end_span(span)
        return span

    def record_retrieval(
        self,
        trace_id: str,
        query: str,
        num_results: int,
        strategy: str = "",
        latency_ms: float = 0.0,
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LLMSpan:
        """
        Record a retrieval operation.

        Args:
            trace_id: Trace ID
            query: Search query
            num_results: Number of results returned
            strategy: Retrieval strategy used
            latency_ms: Call latency
            parent_id: Parent span ID
            metadata: Additional metadata

        Returns:
            The recorded span
        """
        span = self.start_span(
            name="retrieval",
            trace_id=trace_id,
            span_type="retrieval",
            parent_id=parent_id,
            query=query,
            num_results=num_results,
            retrieval_strategy=strategy,
            metadata=metadata or {},
        )

        if latency_ms > 0:
            span.latency_ms = latency_ms

        self.end_span(span)
        return span

    def shutdown(self) -> None:
        """Shutdown tracer and flush remaining spans."""
        self._running = False
        if self._flush_thread:
            self._flush_thread.join(timeout=5.0)
        self._flush()
