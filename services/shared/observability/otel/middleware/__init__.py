"""
OTEL Middleware for web frameworks and task queues.
"""

from .celery import CeleryTraceMiddleware, instrument_celery
from .fastapi import OTELMiddleware, get_trace_context_dependency

__all__ = [
    "OTELMiddleware",
    "get_trace_context_dependency",
    "instrument_celery",
    "CeleryTraceMiddleware",
]
