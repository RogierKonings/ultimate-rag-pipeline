"""
Database package for the RAG Pipeline.

This package provides async SQLAlchemy database connectivity and ORM models
for storing document metadata, chunks, and audit logs.
"""

from .connection import (
    check_database_health,
    create_async_engine,
    get_db,
    get_session,
)
from .events import ensure_events_registered
from .models.audit import AuditLog
from .models.base import Base
from .models.document import Chunk, Document

__all__ = [
    # Connection
    "create_async_engine",
    "get_session",
    "get_db",
    "check_database_health",
    # Models
    "Base",
    "Document",
    "Chunk",
    "AuditLog",
    # Events
    "ensure_events_registered",
]
