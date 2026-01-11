"""
Celery OpenTelemetry Instrumentation.

Provides tracing for Celery tasks with:
- Automatic span creation for task execution
- Trace context propagation through task headers
- Task-specific attributes (name, id, retries)
- Error tracking and recording
"""

import logging
from typing import Any, Callable, Optional

from celery import Celery, Task
from celery.signals import (
    before_task_publish,
    after_task_publish,
    task_prerun,
    task_postrun,
    task_failure,
    task_retry,
)

from opentelemetry import trace, context as otel_context
from opentelemetry.trace import SpanKind, Status, StatusCode

from ..tracer import get_tracer
from ..context import (
    CeleryTracePropagator,
    inject_trace_context,
    get_current_trace_id,
)
from ..attributes import RAGAttributes, RAGOperation

logger = logging.getLogger(__name__)


class CeleryTraceMiddleware:
    """
    Middleware for tracing Celery tasks.

    This class manages trace context propagation and span creation
    for Celery tasks. It should be used in conjunction with the
    signal handlers.
    """

    def __init__(self, service_name: str = "celery-worker"):
        """
        Initialize the middleware.

        Args:
            service_name: Service name for worker spans
        """
        self.service_name = service_name
        self.tracer = get_tracer(service_name)
        self._task_spans: dict[str, Any] = {}
        self._task_tokens: dict[str, Any] = {}

    def on_task_prerun(
        self,
        task_id: str,
        task: Task,
        args: tuple,
        kwargs: dict,
        **signal_kwargs: Any,
    ) -> None:
        """
        Called before a task starts execution.

        Creates a span for the task and restores trace context from headers.
        """
        # Extract trace context from task headers
        headers = getattr(task.request, "headers", {}) or {}
        parent_context = CeleryTracePropagator.extract_task_context(headers)

        # Create span for task execution
        span = self.tracer.start_span(
            f"celery.task.{task.name}",
            context=parent_context,
            kind=SpanKind.CONSUMER,
        )

        # Set task attributes
        span.set_attribute("celery.task.id", task_id)
        span.set_attribute("celery.task.name", task.name)
        span.set_attribute("celery.task.retries", task.request.retries or 0)
        span.set_attribute(RAGAttributes.OPERATION, "celery.task")

        # Set queue info if available
        if hasattr(task.request, "delivery_info"):
            delivery_info = task.request.delivery_info or {}
            if "routing_key" in delivery_info:
                span.set_attribute("celery.routing_key", delivery_info["routing_key"])
            if "exchange" in delivery_info:
                span.set_attribute("celery.exchange", delivery_info["exchange"])

        # Store span and activate context
        token = otel_context.attach(trace.set_span_in_context(span))
        self._task_spans[task_id] = span
        self._task_tokens[task_id] = token

    def on_task_postrun(
        self,
        task_id: str,
        task: Task,
        args: tuple,
        kwargs: dict,
        retval: Any,
        state: str,
        **signal_kwargs: Any,
    ) -> None:
        """
        Called after a task completes.

        Ends the span and records the result state.
        """
        span = self._task_spans.pop(task_id, None)
        token = self._task_tokens.pop(task_id, None)

        if span is None:
            return

        try:
            span.set_attribute("celery.task.state", state)

            if state == "SUCCESS":
                span.set_status(Status(StatusCode.OK))
            elif state == "FAILURE":
                span.set_status(Status(StatusCode.ERROR, "Task failed"))
            elif state == "REVOKED":
                span.set_status(Status(StatusCode.ERROR, "Task revoked"))

            span.end()

        finally:
            if token is not None:
                otel_context.detach(token)

    def on_task_failure(
        self,
        task_id: str,
        exception: Exception,
        args: tuple,
        kwargs: dict,
        traceback: Any,
        einfo: Any,
        **signal_kwargs: Any,
    ) -> None:
        """
        Called when a task fails.

        Records the exception on the span.
        """
        span = self._task_spans.get(task_id)
        if span is None:
            return

        span.record_exception(exception)
        span.set_attribute(RAGAttributes.ERROR_TYPE, type(exception).__name__)
        span.set_attribute(RAGAttributes.ERROR_MESSAGE, str(exception)[:500])

    def on_task_retry(
        self,
        task_id: str,
        exception: Exception,
        einfo: Any,
        **signal_kwargs: Any,
    ) -> None:
        """
        Called when a task is retried.

        Adds a retry event to the span.
        """
        span = self._task_spans.get(task_id)
        if span is None:
            return

        span.add_event(
            "task.retry",
            attributes={
                "exception.type": type(exception).__name__,
                "exception.message": str(exception)[:200],
            },
        )


# Global middleware instance
_middleware: Optional[CeleryTraceMiddleware] = None


def instrument_celery(
    app: Optional[Celery] = None,
    service_name: str = "celery-worker",
) -> CeleryTraceMiddleware:
    """
    Instrument Celery for distributed tracing.

    This function sets up signal handlers to trace Celery tasks.
    Call this once during application startup.

    Args:
        app: Celery application (optional, signals are global)
        service_name: Service name for worker spans

    Returns:
        CeleryTraceMiddleware instance

    Example:
        from celery import Celery
        from shared.observability.otel.middleware import instrument_celery

        app = Celery("tasks")
        middleware = instrument_celery(app, "ingestion-worker")
    """
    global _middleware

    if _middleware is not None:
        logger.warning("Celery already instrumented, returning existing middleware")
        return _middleware

    _middleware = CeleryTraceMiddleware(service_name)

    # Connect signal handlers
    task_prerun.connect(_middleware.on_task_prerun)
    task_postrun.connect(_middleware.on_task_postrun)
    task_failure.connect(_middleware.on_task_failure)
    task_retry.connect(_middleware.on_task_retry)

    # Connect publish handlers for context propagation
    before_task_publish.connect(_on_before_task_publish)
    after_task_publish.connect(_on_after_task_publish)

    logger.info(f"Celery instrumentation enabled for {service_name}")

    return _middleware


def _on_before_task_publish(
    sender: str,
    headers: dict,
    body: Any,
    **kwargs: Any,
) -> None:
    """
    Inject trace context into task headers before publishing.
    """
    CeleryTracePropagator.inject_task_headers(headers)


def _on_after_task_publish(
    sender: str,
    headers: dict,
    body: Any,
    **kwargs: Any,
) -> None:
    """
    Called after a task is published.
    """
    # Could add span event here if needed
    pass


def traced_task(
    name: Optional[str] = None,
    operation: RAGOperation = RAGOperation.INGEST,
) -> Callable:
    """
    Decorator for adding extra tracing to Celery tasks.

    Use this in addition to instrument_celery() for more control
    over task-specific attributes.

    Args:
        name: Custom span name (defaults to task name)
        operation: RAG operation type for the task

    Returns:
        Decorated task function

    Example:
        @app.task
        @traced_task(operation=RAGOperation.INGEST_EMBED)
        def embed_documents(document_ids: list[str]):
            ...
    """

    def decorator(func: Callable) -> Callable:
        from functools import wraps

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            span_name = name or func.__name__

            with tracer.start_as_current_span(span_name) as span:
                span.set_attribute(RAGAttributes.OPERATION, operation.value)

                # Record argument info
                if args:
                    span.set_attribute("task.args_count", len(args))
                if kwargs:
                    span.set_attribute("task.kwargs_keys", str(list(kwargs.keys())))

                try:
                    result = func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    raise

        return wrapper

    return decorator


def get_task_trace_headers() -> dict[str, Any]:
    """
    Get trace context headers for passing to a Celery task.

    Use this when calling tasks with .apply_async() to propagate context.

    Returns:
        Dict of headers with trace context

    Example:
        from shared.observability.otel.middleware.celery import get_task_trace_headers

        my_task.apply_async(
            args=[document_id],
            headers=get_task_trace_headers(),
        )
    """
    return CeleryTracePropagator.inject_task_headers({})
