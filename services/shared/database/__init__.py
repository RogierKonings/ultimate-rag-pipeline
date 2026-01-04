"""
Database package for the RAG Pipeline.

This package provides async SQLAlchemy database connectivity and ORM models
for storing document metadata, chunks, and audit logs.
"""

from database.connection import (
    create_async_engine,
    get_session,
    get_db,
    check_database_health,
)
from database.models.base import Base
from database.models.document import Document, Chunk
from database.models.audit import AuditLog

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
]
