"""Routes package for the ingestion API."""

from .admin import router as admin_router
from .documents import router as documents_router
from .ingest import router as ingest_router
from .video import router as video_router
from .video_management import router as video_management_router

# Migrations router is optional - depends on external modules
try:
    from .migrations import router as migrations_router
except ImportError:
    migrations_router = None

__all__ = [
    "admin_router",
    "ingest_router",
    "documents_router",
    "migrations_router",
    "video_router",
    "video_management_router",
]
