"""
Trace Context Propagation.

Provides utilities for propagating trace context across:
- HTTP requests (W3C Trace Context)
- Async message queues (Celery, Kafka)
- Inter-service calls

Uses W3C Trace Context format by default for maximum compatibility.
"""

import logging
from typing import Any, Callable, Dict, Optional, Mapping

from opentelemetry import trace
from opentelemetry.context import Context, get_current, attach, detach
from opentelemetry.propagate import extract, inject
from opentelemetry.propagators.textmap import Getter, Setter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

logger = logging.getLogger(__name__)

# Default propagator (W3C Trace Context)
_propagator = TraceContextTextMapPropagator()


class DictGetter(Getter):
    """Getter for extracting context from dictionaries."""

    def get(self, carrier: Mapping[str, str], key: str) -> Optional[list[str]]:
        value = carrier.get(key)
        if value is not None:
            return [value]
        # Try case-insensitive lookup
        for k, v in carrier.items():
            if k.lower() == key.lower():
                return [v]
        return None

    def keys(self, carrier: Mapping[str, str]) -> list[str]:
        return list(carrier.keys())


class DictSetter(Setter):
    """Setter for injecting context into dictionaries."""

    def set(self, carrier: Dict[str, str], key: str, value: str) -> None:
        carrier[key] = value


# Singleton instances
_dict_getter = DictGetter()
_dict_setter = DictSetter()


class TraceContextPropagator:
    """
    Helper class for trace context propagation.

    Provides methods for injecting and extracting trace context
    from various carrier types.
    """

    def __init__(self):
        """Initialize the propagator."""
        self.propagator = _propagator

    def inject_into_headers(
        self,
        headers: Optional[Dict[str, str]] = None,
        context: Optional[Context] = None,
    ) -> Dict[str, str]:
        """
        Inject trace context into HTTP headers.

        Args:
            headers: Existing headers dict to inject into (creates new if None)
            context: Context to inject (uses current if None)

        Returns:
            Headers dict with trace context

        Example:
            headers = propagator.inject_into_headers()
            response = await client.get(url, headers=headers)
        """
        if headers is None:
            headers = {}

        inject(headers, context=context, setter=_dict_setter)
        return headers

    def extract_from_headers(
        self,
        headers: Mapping[str, str],
    ) -> Context:
        """
        Extract trace context from HTTP headers.

        Args:
            headers: HTTP headers containing trace context

        Returns:
            Extracted context

        Example:
            context = propagator.extract_from_headers(request.headers)
            with tracer.start_as_current_span("handler", context=context):
                ...
        """
        return extract(headers, getter=_dict_getter)

    def inject_into_carrier(
        self,
        carrier: Dict[str, Any],
        context: Optional[Context] = None,
        key_prefix: str = "",
    ) -> Dict[str, Any]:
        """
        Inject trace context into a generic carrier (e.g., message headers).

        Args:
            carrier: Carrier dict to inject into
            context: Context to inject (uses current if None)
            key_prefix: Optional prefix for context keys

        Returns:
            Carrier with trace context
        """
        trace_headers: Dict[str, str] = {}
        inject(trace_headers, context=context, setter=_dict_setter)

        for key, value in trace_headers.items():
            carrier[f"{key_prefix}{key}"] = value

        return carrier

    def extract_from_carrier(
        self,
        carrier: Mapping[str, Any],
        key_prefix: str = "",
    ) -> Context:
        """
        Extract trace context from a generic carrier.

        Args:
            carrier: Carrier containing trace context
            key_prefix: Prefix used for context keys

        Returns:
            Extracted context
        """
        # Extract headers with prefix if specified
        headers = {}
        for key, value in carrier.items():
            if key_prefix and key.startswith(key_prefix):
                headers[key[len(key_prefix) :]] = str(value)
            elif not key_prefix:
                headers[key] = str(value)

        return extract(headers, getter=_dict_getter)


# Singleton instance
_context_propagator = TraceContextPropagator()


def inject_trace_context(
    carrier: Optional[Dict[str, str]] = None,
    context: Optional[Context] = None,
) -> Dict[str, str]:
    """
    Inject current trace context into a carrier.

    Convenience function for injecting W3C Trace Context headers.

    Args:
        carrier: Dict to inject into (creates new if None)
        context: Context to inject (uses current if None)

    Returns:
        Carrier dict with trace context headers

    Example:
        # For HTTP requests
        headers = inject_trace_context()
        response = await httpx_client.get(url, headers=headers)

        # For Celery tasks
        task_headers = inject_trace_context()
        my_task.apply_async(args=[...], headers=task_headers)
    """
    return _context_propagator.inject_into_headers(carrier, context)


def extract_trace_context(
    carrier: Mapping[str, str],
) -> Context:
    """
    Extract trace context from a carrier.

    Convenience function for extracting W3C Trace Context.

    Args:
        carrier: Headers/dict containing trace context

    Returns:
        Extracted context for use with span creation

    Example:
        # In FastAPI endpoint
        context = extract_trace_context(dict(request.headers))
        with tracer.start_as_current_span("handler", context=context):
            ...
    """
    return _context_propagator.extract_from_headers(carrier)


def get_current_trace_id() -> Optional[str]:
    """
    Get the current trace ID as a hex string.

    Returns:
        32-character hex trace ID or None if not in a trace
    """
    span = trace.get_current_span()
    if span is None:
        return None

    ctx = span.get_span_context()
    if ctx is None or not ctx.is_valid:
        return None

    return format(ctx.trace_id, "032x")


def get_current_span_id() -> Optional[str]:
    """
    Get the current span ID as a hex string.

    Returns:
        16-character hex span ID or None if not in a span
    """
    span = trace.get_current_span()
    if span is None:
        return None

    ctx = span.get_span_context()
    if ctx is None or not ctx.is_valid:
        return None

    return format(ctx.span_id, "016x")


def get_trace_context_dict() -> Dict[str, Optional[str]]:
    """
    Get current trace context as a dictionary.

    Useful for including in logs and other contexts.

    Returns:
        Dict with trace_id and span_id (may be None)
    """
    return {
        "trace_id": get_current_trace_id(),
        "span_id": get_current_span_id(),
    }


def with_trace_context(context: Context) -> Callable:
    """
    Decorator to run a function with a specific trace context.

    Args:
        context: Context to use

    Returns:
        Decorated function

    Example:
        context = extract_trace_context(headers)

        @with_trace_context(context)
        async def process_message():
            # Runs within the extracted context
            ...
    """

    def decorator(func: Callable) -> Callable:
        import asyncio
        from functools import wraps

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            token = attach(context)
            try:
                return await func(*args, **kwargs)
            finally:
                detach(token)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            token = attach(context)
            try:
                return func(*args, **kwargs)
            finally:
                detach(token)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


class CeleryTracePropagator:
    """
    Helper for propagating trace context through Celery tasks.

    Injects context into task headers and extracts it in the worker.
    """

    HEADER_PREFIX = "otel_"

    @classmethod
    def inject_task_headers(
        cls,
        headers: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Inject trace context into Celery task headers.

        Args:
            headers: Existing task headers (creates new if None)

        Returns:
            Headers with trace context
        """
        if headers is None:
            headers = {}

        return _context_propagator.inject_into_carrier(
            headers, key_prefix=cls.HEADER_PREFIX
        )

    @classmethod
    def extract_task_context(
        cls,
        headers: Mapping[str, Any],
    ) -> Context:
        """
        Extract trace context from Celery task headers.

        Args:
            headers: Task headers containing trace context

        Returns:
            Extracted context
        """
        return _context_propagator.extract_from_carrier(
            headers, key_prefix=cls.HEADER_PREFIX
        )


class KafkaTracePropagator:
    """
    Helper for propagating trace context through Kafka messages.

    Compatible with confluent-kafka and aiokafka.
    """

    @classmethod
    def inject_message_headers(
        cls,
        headers: Optional[list[tuple[str, bytes]]] = None,
    ) -> list[tuple[str, bytes]]:
        """
        Inject trace context into Kafka message headers.

        Args:
            headers: Existing message headers

        Returns:
            Headers with trace context
        """
        if headers is None:
            headers = []

        # Inject into dict first
        trace_dict: Dict[str, str] = {}
        inject(trace_dict, setter=_dict_setter)

        # Convert to Kafka header format
        for key, value in trace_dict.items():
            headers.append((key, value.encode("utf-8")))

        return headers

    @classmethod
    def extract_message_context(
        cls,
        headers: Optional[list[tuple[str, bytes]]],
    ) -> Context:
        """
        Extract trace context from Kafka message headers.

        Args:
            headers: Kafka message headers

        Returns:
            Extracted context
        """
        if headers is None:
            return get_current()

        # Convert to dict
        header_dict = {}
        for key, value in headers:
            if isinstance(value, bytes):
                header_dict[key] = value.decode("utf-8")
            else:
                header_dict[key] = str(value)

        return extract(header_dict, getter=_dict_getter)
