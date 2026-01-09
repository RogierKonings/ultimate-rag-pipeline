"""Routes package for the ingestion API."""

from .documents import router as documents_router
from .ingest import router as ingest_router

# Migrations router is optional - depends on external modules
try:
    from .migrations import router as migrations_router
except ImportError:
    migrations_router = None

__all__ = ["ingest_router", "documents_router", "migrations_router"]

