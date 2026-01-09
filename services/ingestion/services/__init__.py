"""Services package for the ingestion service."""

from .documents import DeleteResult, DocumentListResult, DocumentService
from .deduplication import (
    CHUNK_SCHEMA_VERSION,
    DeduplicationCheckResult,
    DeduplicationResult,
    DeduplicationService,
    VersionInfo,
    create_deduplication_service,
)
from .ingestion_logs import (
    IngestionLogEntry,
    IngestionLogWriter,
    get_ingestion_log_writer,
    reset_ingestion_log_writer,
)

__all__ = [
    "DocumentService",
    "DocumentListResult",
    "DeleteResult",
    "DeduplicationService",
    "DeduplicationResult",
    "DeduplicationCheckResult",
    "VersionInfo",
    "CHUNK_SCHEMA_VERSION",
    "create_deduplication_service",
    # Ingestion logging (US-2.12)
    "IngestionLogEntry",
    "IngestionLogWriter",
    "get_ingestion_log_writer",
    "reset_ingestion_log_writer",
]
