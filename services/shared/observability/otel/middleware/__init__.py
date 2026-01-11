"""
OTEL Middleware for web frameworks and task queues.
"""

from .fastapi import OTELMiddleware, get_trace_context_dependency
from .celery import instrument_celery, CeleryTraceMiddleware

__all__ = [
    "OTELMiddleware",
    "get_trace_context_dependency",
    "instrument_celery",
    "CeleryTraceMiddleware",
]
