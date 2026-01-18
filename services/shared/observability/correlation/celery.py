"""Celery integration for correlation context propagation."""

from __future__ import annotations

from typing import Any

import structlog

from .context import (
    CorrelationContext,
    clear_correlation_context,
    get_correlation_context,
    set_correlation_context,
)

logger = structlog.get_logger(__name__)

CORRELATION_HEADER_KEY = "correlation_context"


def inject_correlation_to_task(headers: dict[str, Any]) -> None:
    """Inject correlation context into Celery task headers.

    This function should be called before publishing a task to ensure
    correlation context is propagated to the worker.

    Args:
        headers: The Celery task headers dictionary to inject into.
    """
    ctx = get_correlation_context()
    if ctx is None:
        return

    headers[CORRELATION_HEADER_KEY] = {
        "request_id": ctx.request_id,
        "trace_id": ctx.trace_id,
        "tenant_id": ctx.tenant_id,
        "user_id_hash": ctx.user_id_hash,
    }


def extract_correlation_from_task(
    headers: dict[str, Any],
    task_id: str,
    tenant_id: str | None = None,
) -> None:
    """Extract correlation context from Celery task headers.

    This function should be called at the start of task execution to
    restore the correlation context from the originating request.

    Args:
        headers: The Celery task headers dictionary.
        task_id: The Celery task ID (used as fallback for request/trace IDs).
        tenant_id: Optional tenant_id fallback from task kwargs.
    """
    correlation_data = headers.get(CORRELATION_HEADER_KEY)

    if correlation_data:
        ctx = CorrelationContext(
            request_id=correlation_data.get("request_id", task_id),
            trace_id=correlation_data.get("trace_id", task_id),
            tenant_id=correlation_data.get("tenant_id", tenant_id),
            user_id_hash=correlation_data.get("user_id_hash"),
        )
    else:
        ctx = CorrelationContext(
            request_id=task_id,
            trace_id=task_id,
            tenant_id=tenant_id,
        )

    set_correlation_context(ctx)

    # Bind to structlog context for logging
    structlog.contextvars.bind_contextvars(
        request_id=ctx.request_id,
        trace_id=ctx.trace_id,
        tenant_id=ctx.tenant_id or "unknown",
        task_id=task_id,
    )


def cleanup_correlation_for_task() -> None:
    """Clean up correlation context after task completion.

    This function should be called after task execution to clear the
    correlation context and prevent context leakage between tasks.
    """
    structlog.contextvars.unbind_contextvars(
        "request_id", "trace_id", "tenant_id", "task_id"
    )
    clear_correlation_context()


def setup_celery_correlation_signals(celery_app: Any) -> None:
    """Set up Celery signals for automatic correlation propagation.

    This registers signal handlers that automatically:
    - Inject correlation context when publishing tasks
    - Extract correlation context when starting task execution
    - Clean up correlation context after task completion

    Args:
        celery_app: The Celery application instance.
    """
    from celery.signals import before_task_publish, task_postrun, task_prerun

    @before_task_publish.connect
    def propagate_correlation_to_task(
        headers: dict[str, Any] | None = None, **kwargs: Any
    ) -> None:
        """Signal handler to inject correlation context before task publish."""
        if headers is not None:
            inject_correlation_to_task(headers)

    @task_prerun.connect
    def setup_correlation_for_task(
        task_id: str, task: Any, args: tuple, kwargs: dict, **signal_kwargs: Any
    ) -> None:
        """Signal handler to extract correlation context at task start."""
        request = task.request
        headers = getattr(request, "headers", {}) or {}
        tenant_id_kwarg = kwargs.get("tenant_id")
        extract_correlation_from_task(headers, task_id, tenant_id_kwarg)

    @task_postrun.connect
    def cleanup_correlation_after_task(**kwargs: Any) -> None:
        """Signal handler to clean up correlation context after task."""
        cleanup_correlation_for_task()

    logger.info("Celery correlation signals configured")
