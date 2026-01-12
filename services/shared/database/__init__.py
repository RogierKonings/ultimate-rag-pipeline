"""
Database package for the RAG Pipeline.

This package provides async SQLAlchemy database connectivity and ORM models
for storing document metadata, chunks, and audit logs.
"""

from database.connection import (
    check_database_health,
    create_async_engine,
    get_db,
    get_session,
)
from database.models.audit import AuditLog
from database.models.base import Base
from database.models.document import Chunk, Document

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
