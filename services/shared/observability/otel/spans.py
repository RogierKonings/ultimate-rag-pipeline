"""
Span Decorators and Helpers.

Provides convenient decorators and context managers for creating
OpenTelemetry spans with RAG-specific attributes.
"""

import asyncio
import time
import logging
from contextlib import contextmanager, asynccontextmanager
from functools import wraps
from typing import Any, Callable, Optional, TypeVar, Union, ParamSpec

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode, SpanKind

from .tracer import get_tracer
from .attributes import RAGOperation, RAGAttributes, set_rag_attributes

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


def get_current_span() -> Optional[Span]:
    """
    Get the current active span.

    Returns:
        Current span or None if no span is active
    """
    span = trace.get_current_span()
    if span and span.is_recording():
        return span
    return None


def add_span_event(
    name: str,
    attributes: Optional[dict[str, Any]] = None,
    span: Optional[Span] = None,
) -> None:
    """
    Add an event to the current or specified span.

    Args:
        name: Event name
        attributes: Optional event attributes
        span: Optional span (uses current if None)
    """
    if span is None:
        span = get_current_span()

    if span is not None:
        span.add_event(name, attributes=attributes or {})


def set_span_error(
    exception: Exception,
    message: Optional[str] = None,
    span: Optional[Span] = None,
) -> None:
    """
    Mark a span as errored and record the exception.

    Args:
        exception: The exception that occurred
        message: Optional error message
        span: Optional span (uses current if None)
    """
    if span is None:
        span = get_current_span()

    if span is not None:
        span.set_status(Status(StatusCode.ERROR, message or str(exception)))
        span.record_exception(exception)
        span.set_attribute(RAGAttributes.ERROR_TYPE, type(exception).__name__)
        span.set_attribute(RAGAttributes.ERROR_MESSAGE, str(exception)[:500])


@contextmanager
def rag_span(
    name: str,
    operation: Optional[RAGOperation] = None,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: Optional[dict[str, Any]] = None,
    record_exception: bool = True,
    set_status_on_exception: bool = True,
):
    """
    Context manager for creating a RAG span.

    Automatically handles:
    - Span creation with proper kind
    - RAG operation attribute setting
    - Duration tracking
    - Exception recording
    - Status setting

    Args:
        name: Span name
        operation: RAG operation type
        kind: Span kind (default: INTERNAL)
        attributes: Additional span attributes
        record_exception: Whether to record exceptions
        set_status_on_exception: Whether to set error status on exception

    Yields:
        The created span

    Example:
        with rag_span("vector_search", RAGOperation.VECTOR_SEARCH) as span:
            span.set_attribute("rag.search.top_k", 10)
            results = await search(query)
    """
    tracer = get_tracer()
    start_time = time.perf_counter()

    with tracer.start_as_current_span(name, kind=kind) as span:
        try:
            # Set operation attribute
            if operation is not None:
                span.set_attribute(RAGAttributes.OPERATION, operation.value)

            # Set additional attributes
            if attributes:
                for key, value in attributes.items():
                    if value is not None:
                        span.set_attribute(key, value)

            yield span

            # Set success status
            span.set_status(Status(StatusCode.OK))

        except Exception as e:
            if record_exception:
                span.record_exception(e)

            if set_status_on_exception:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.set_attribute(RAGAttributes.ERROR_TYPE, type(e).__name__)

            raise

        finally:
            # Record duration
            duration_ms = (time.perf_counter() - start_time) * 1000
            span.set_attribute(RAGAttributes.DURATION_MS, duration_ms)


@asynccontextmanager
async def async_rag_span(
    name: str,
    operation: Optional[RAGOperation] = None,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: Optional[dict[str, Any]] = None,
    record_exception: bool = True,
    set_status_on_exception: bool = True,
):
    """
    Async context manager for creating a RAG span.

    Same as rag_span but for async contexts.

    Args:
        name: Span name
        operation: RAG operation type
        kind: Span kind (default: INTERNAL)
        attributes: Additional span attributes
        record_exception: Whether to record exceptions
        set_status_on_exception: Whether to set error status on exception

    Yields:
        The created span
    """
    tracer = get_tracer()
    start_time = time.perf_counter()

    with tracer.start_as_current_span(name, kind=kind) as span:
        try:
            if operation is not None:
                span.set_attribute(RAGAttributes.OPERATION, operation.value)

            if attributes:
                for key, value in attributes.items():
                    if value is not None:
                        span.set_attribute(key, value)

            yield span

            span.set_status(Status(StatusCode.OK))

        except Exception as e:
            if record_exception:
                span.record_exception(e)

            if set_status_on_exception:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.set_attribute(RAGAttributes.ERROR_TYPE, type(e).__name__)

            raise

        finally:
            duration_ms = (time.perf_counter() - start_time) * 1000
            span.set_attribute(RAGAttributes.DURATION_MS, duration_ms)


def traced(
    name: Optional[str] = None,
    operation: Optional[RAGOperation] = None,
    kind: SpanKind = SpanKind.INTERNAL,
    record_args: bool = False,
    record_result: bool = False,
    attributes: Optional[dict[str, Any]] = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    Decorator for tracing functions.

    Automatically creates a span for the decorated function,
    handling both sync and async functions.

    Args:
        name: Span name (defaults to function name)
        operation: RAG operation type
        kind: Span kind
        record_args: Whether to record function arguments as attributes
        record_result: Whether to record function result as attribute
        attributes: Additional static attributes

    Returns:
        Decorated function

    Example:
        @traced("process_query", RAGOperation.QUERY)
        async def process_query(query: str, top_k: int = 10):
            ...

        @traced(record_args=True)
        def compute_embedding(text: str):
            ...
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        span_name = name or func.__name__
        tracer = get_tracer()

        @wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            start_time = time.perf_counter()

            with tracer.start_as_current_span(span_name, kind=kind) as span:
                try:
                    # Set operation
                    if operation is not None:
                        span.set_attribute(RAGAttributes.OPERATION, operation.value)

                    # Set static attributes
                    if attributes:
                        for key, value in attributes.items():
                            if value is not None:
                                span.set_attribute(key, value)

                    # Record arguments
                    if record_args:
                        _record_function_args(span, func, args, kwargs)

                    # Execute function
                    result = await func(*args, **kwargs)

                    # Record result
                    if record_result and result is not None:
                        _record_function_result(span, result)

                    span.set_status(Status(StatusCode.OK))
                    return result

                except Exception as e:
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.set_attribute(RAGAttributes.ERROR_TYPE, type(e).__name__)
                    raise

                finally:
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    span.set_attribute(RAGAttributes.DURATION_MS, duration_ms)

        @wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            start_time = time.perf_counter()

            with tracer.start_as_current_span(span_name, kind=kind) as span:
                try:
                    if operation is not None:
                        span.set_attribute(RAGAttributes.OPERATION, operation.value)

                    if attributes:
                        for key, value in attributes.items():
                            if value is not None:
                                span.set_attribute(key, value)

                    if record_args:
                        _record_function_args(span, func, args, kwargs)

                    result = func(*args, **kwargs)

                    if record_result and result is not None:
                        _record_function_result(span, result)

                    span.set_status(Status(StatusCode.OK))
                    return result

                except Exception as e:
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.set_attribute(RAGAttributes.ERROR_TYPE, type(e).__name__)
                    raise

                finally:
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    span.set_attribute(RAGAttributes.DURATION_MS, duration_ms)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        return sync_wrapper  # type: ignore

    return decorator


def _record_function_args(
    span: Span,
    func: Callable,
    args: tuple,
    kwargs: dict,
) -> None:
    """Record function arguments as span attributes."""
    import inspect

    try:
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())

        # Record positional args
        for i, (param_name, value) in enumerate(zip(params, args)):
            if param_name == "self":
                continue
            _set_safe_attribute(span, f"arg.{param_name}", value)

        # Record keyword args
        for key, value in kwargs.items():
            _set_safe_attribute(span, f"arg.{key}", value)

    except Exception:
        # Don't fail if we can't record args
        pass


def _record_function_result(span: Span, result: Any) -> None:
    """Record function result as span attribute."""
    try:
        if isinstance(result, (str, int, float, bool)):
            span.set_attribute("result", result)
        elif isinstance(result, (list, tuple)):
            span.set_attribute("result.length", len(result))
        elif isinstance(result, dict):
            span.set_attribute("result.keys", str(list(result.keys())[:10]))
        elif hasattr(result, "__len__"):
            span.set_attribute("result.length", len(result))
    except Exception:
        pass


def _set_safe_attribute(span: Span, key: str, value: Any) -> None:
    """Set an attribute on a span, handling various types safely."""
    try:
        if value is None:
            return

        if isinstance(value, (str, int, float, bool)):
            # Truncate long strings
            if isinstance(value, str) and len(value) > 500:
                value = value[:500] + "..."
            span.set_attribute(key, value)

        elif isinstance(value, (list, tuple)):
            span.set_attribute(f"{key}.length", len(value))

        elif isinstance(value, dict):
            span.set_attribute(f"{key}.keys", str(list(value.keys())[:10]))

        elif hasattr(value, "__str__"):
            str_value = str(value)[:500]
            span.set_attribute(key, str_value)

    except Exception:
        # Don't fail on attribute setting
        pass
