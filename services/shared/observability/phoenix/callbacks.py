"""
LLM Framework Callbacks.

Provides callbacks for LangChain and LlamaIndex to integrate with Phoenix tracing.
"""

import logging
import time
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from .tracer import PhoenixTracer, LLMSpan

logger = logging.getLogger(__name__)


class LangChainCallback:
    """
    LangChain callback handler for Phoenix tracing.

    Usage:
        tracer = PhoenixTracer()
        callback = LangChainCallback(tracer)
        llm = ChatOpenAI(callbacks=[callback])
    """

    def __init__(
        self,
        tracer: Optional[PhoenixTracer] = None,
        trace_id: Optional[str] = None,
    ):
        """
        Initialize LangChain callback.

        Args:
            tracer: Phoenix tracer instance
            trace_id: Optional trace ID to use for all spans
        """
        self.tracer = tracer or PhoenixTracer.get_instance()
        self.trace_id = trace_id or str(uuid4())
        self._spans: Dict[str, LLMSpan] = {}
        self._start_times: Dict[str, float] = {}

    def set_trace_id(self, trace_id: str) -> None:
        """Set the trace ID for subsequent spans."""
        self.trace_id = trace_id

    # LLM callbacks
    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Called when LLM starts running."""
        model = serialized.get("name", serialized.get("id", ["unknown"])[-1])
        provider = serialized.get("id", ["unknown"])[0] if serialized.get("id") else ""

        prompt = "\n".join(prompts)

        span = self.tracer.start_span(
            name=f"llm.{model}",
            trace_id=self.trace_id,
            span_type="llm",
            parent_id=parent_run_id,
            model=model,
            provider=provider,
            prompt=prompt,
            metadata=kwargs.get("metadata", {}),
        )

        self._spans[run_id] = span
        self._start_times[run_id] = time.time()

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Called when LLM ends running."""
        span = self._spans.pop(run_id, None)
        start_time = self._start_times.pop(run_id, None)

        if span:
            # Extract response data
            if hasattr(response, "generations") and response.generations:
                completions = []
                for gen_list in response.generations:
                    for gen in gen_list:
                        if hasattr(gen, "text"):
                            completions.append(gen.text)
                        elif hasattr(gen, "message"):
                            completions.append(str(gen.message.content))
                span.completion = "\n".join(completions)

            # Extract token usage
            if hasattr(response, "llm_output") and response.llm_output:
                token_usage = response.llm_output.get("token_usage", {})
                span.prompt_tokens = token_usage.get("prompt_tokens", 0)
                span.completion_tokens = token_usage.get("completion_tokens", 0)
                span.total_tokens = token_usage.get("total_tokens", 0)

            if start_time:
                span.latency_ms = (time.time() - start_time) * 1000

            self.tracer.end_span(span)

    def on_llm_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Called when LLM encounters an error."""
        span = self._spans.pop(run_id, None)
        self._start_times.pop(run_id, None)

        if span:
            self.tracer.end_span(span, error=str(error))

    # Chain callbacks
    def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Called when chain starts running."""
        name = serialized.get("name", serialized.get("id", ["chain"])[-1])

        span = self.tracer.start_span(
            name=f"chain.{name}",
            trace_id=self.trace_id,
            span_type="chain",
            parent_id=parent_run_id,
            metadata={"inputs": str(inputs)[:500]},
        )

        self._spans[run_id] = span
        self._start_times[run_id] = time.time()

    def on_chain_end(
        self,
        outputs: Dict[str, Any],
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Called when chain ends running."""
        span = self._spans.pop(run_id, None)
        start_time = self._start_times.pop(run_id, None)

        if span:
            span.metadata["outputs"] = str(outputs)[:500]
            if start_time:
                span.latency_ms = (time.time() - start_time) * 1000
            self.tracer.end_span(span)

    def on_chain_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Called when chain encounters an error."""
        span = self._spans.pop(run_id, None)
        self._start_times.pop(run_id, None)

        if span:
            self.tracer.end_span(span, error=str(error))

    # Retriever callbacks
    def on_retriever_start(
        self,
        serialized: Dict[str, Any],
        query: str,
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Called when retriever starts running."""
        span = self.tracer.start_span(
            name="retrieval",
            trace_id=self.trace_id,
            span_type="retrieval",
            parent_id=parent_run_id,
            query=query,
        )

        self._spans[run_id] = span
        self._start_times[run_id] = time.time()

    def on_retriever_end(
        self,
        documents: List[Any],
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Called when retriever ends running."""
        span = self._spans.pop(run_id, None)
        start_time = self._start_times.pop(run_id, None)

        if span:
            span.num_results = len(documents)
            if start_time:
                span.latency_ms = (time.time() - start_time) * 1000
            self.tracer.end_span(span)

    def on_retriever_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Called when retriever encounters an error."""
        span = self._spans.pop(run_id, None)
        self._start_times.pop(run_id, None)

        if span:
            self.tracer.end_span(span, error=str(error))

    # Tool callbacks
    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Called when tool starts running."""
        name = serialized.get("name", "tool")

        span = self.tracer.start_span(
            name=f"tool.{name}",
            trace_id=self.trace_id,
            span_type="chain",  # Tools are treated as chain spans
            parent_id=parent_run_id,
            metadata={"input": input_str[:500]},
        )

        self._spans[run_id] = span
        self._start_times[run_id] = time.time()

    def on_tool_end(
        self,
        output: str,
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Called when tool ends running."""
        span = self._spans.pop(run_id, None)
        start_time = self._start_times.pop(run_id, None)

        if span:
            span.metadata["output"] = output[:500]
            if start_time:
                span.latency_ms = (time.time() - start_time) * 1000
            self.tracer.end_span(span)

    def on_tool_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Called when tool encounters an error."""
        span = self._spans.pop(run_id, None)
        self._start_times.pop(run_id, None)

        if span:
            self.tracer.end_span(span, error=str(error))


class LlamaIndexCallback:
    """
    LlamaIndex callback handler for Phoenix tracing.

    Usage:
        tracer = PhoenixTracer()
        callback = LlamaIndexCallback(tracer)
        # Add to LlamaIndex callback manager
    """

    def __init__(
        self,
        tracer: Optional[PhoenixTracer] = None,
        trace_id: Optional[str] = None,
    ):
        """
        Initialize LlamaIndex callback.

        Args:
            tracer: Phoenix tracer instance
            trace_id: Optional trace ID to use for all spans
        """
        self.tracer = tracer or PhoenixTracer.get_instance()
        self.trace_id = trace_id or str(uuid4())
        self._spans: Dict[str, LLMSpan] = {}
        self._start_times: Dict[str, float] = {}

    def set_trace_id(self, trace_id: str) -> None:
        """Set the trace ID for subsequent spans."""
        self.trace_id = trace_id

    def on_event_start(
        self,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        event_id: str = "",
        parent_id: str = "",
        **kwargs: Any,
    ) -> str:
        """Handle event start."""
        event_id = event_id or str(uuid4())
        payload = payload or {}

        # Map event types to span types
        span_type = "chain"
        name = event_type

        if "LLM" in event_type:
            span_type = "llm"
            model = payload.get("model_name", "unknown")
            name = f"llm.{model}"

            span = self.tracer.start_span(
                name=name,
                trace_id=self.trace_id,
                span_type=span_type,
                parent_id=parent_id or None,
                model=model,
                prompt=payload.get("messages", payload.get("prompt", "")),
            )

        elif "EMBEDDING" in event_type:
            span_type = "embedding"
            model = payload.get("model_name", "unknown")
            name = f"embedding.{model}"

            span = self.tracer.start_span(
                name=name,
                trace_id=self.trace_id,
                span_type=span_type,
                parent_id=parent_id or None,
                embedding_model=model,
            )

        elif "RETRIEVE" in event_type or "QUERY" in event_type:
            span_type = "retrieval"
            name = "retrieval"

            span = self.tracer.start_span(
                name=name,
                trace_id=self.trace_id,
                span_type=span_type,
                parent_id=parent_id or None,
                query=str(payload.get("query", payload.get("query_str", ""))),
            )

        else:
            span = self.tracer.start_span(
                name=name,
                trace_id=self.trace_id,
                span_type=span_type,
                parent_id=parent_id or None,
                metadata=payload,
            )

        self._spans[event_id] = span
        self._start_times[event_id] = time.time()

        return event_id

    def on_event_end(
        self,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        event_id: str = "",
        **kwargs: Any,
    ) -> None:
        """Handle event end."""
        span = self._spans.pop(event_id, None)
        start_time = self._start_times.pop(event_id, None)
        payload = payload or {}

        if span:
            # Extract response data based on event type
            if "LLM" in event_type:
                response = payload.get("response", payload.get("completion", ""))
                if hasattr(response, "text"):
                    span.completion = response.text
                elif hasattr(response, "message"):
                    span.completion = str(response.message.content)
                else:
                    span.completion = str(response)

                # Token usage
                token_usage = payload.get("token_usage", {})
                if isinstance(token_usage, dict):
                    span.prompt_tokens = token_usage.get("prompt_tokens", 0)
                    span.completion_tokens = token_usage.get("completion_tokens", 0)
                    span.total_tokens = token_usage.get("total_tokens", 0)

            elif "EMBEDDING" in event_type:
                embeddings = payload.get("embeddings", [])
                span.num_embeddings = len(embeddings) if isinstance(embeddings, list) else 1

            elif "RETRIEVE" in event_type or "QUERY" in event_type:
                nodes = payload.get("nodes", payload.get("source_nodes", []))
                span.num_results = len(nodes) if isinstance(nodes, list) else 0

            if start_time:
                span.latency_ms = (time.time() - start_time) * 1000

            self.tracer.end_span(span)

    def start_trace(self, trace_id: Optional[str] = None) -> str:
        """Start a new trace."""
        self.trace_id = trace_id or str(uuid4())
        return self.trace_id

    def end_trace(
        self,
        trace_id: Optional[str] = None,
        trace_map: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        """End the current trace."""
        # Flush any remaining spans
        for event_id in list(self._spans.keys()):
            span = self._spans.pop(event_id, None)
            start_time = self._start_times.pop(event_id, None)
            if span:
                if start_time:
                    span.latency_ms = (time.time() - start_time) * 1000
                self.tracer.end_span(span)
