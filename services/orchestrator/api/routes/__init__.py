"""API routes for the Orchestrator Service."""

from .admin import router as admin_router
from .audit import router as audit_router
from .capabilities import router as capabilities_router
from .health import router as health_router
from .query import router as query_router
from .sessions import router as sessions_router

__all__ = [
    "admin_router",
    "audit_router",
    "capabilities_router",
    "health_router",
    "query_router",
    "sessions_router",
]
