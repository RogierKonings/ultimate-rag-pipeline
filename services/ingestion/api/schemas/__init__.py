"""API schemas package."""

from .documents import (
    DocumentDeleteResponse,
    DocumentListResponse,
    DocumentResponse,
    ReindexRequest,
)
from .ingest import (
    ACLContext,
    ActiveJobsResponse,
    CancelJobResponse,
    ChunkingStrategy,
    IngestRequest,
    IngestResponse,
    JobProgress,
    JobStatus,
    JobStatusResponse,
    ProcessingOptions,
    ReembedRequest,
    ReembedResponse,
    ReembedTargetScope,
    SingleIngestRequest,
    SourceType,
    SyncRequest,
    SyncResponse,
    SyncSourceConfig,
)

# Migration schemas are optional - depend on external modules
try:
    from .migrations import (
        MigrationListResponseSchema,
        MigrationRequestSchema,
        MigrationResponseSchema,
        StatusResponseSchema,
        SwitchRequestSchema,
        ValidationConfigSchema,
        ValidationRequestSchema,
        ValidationResponseSchema,
    )

    _migration_schemas = [
        "MigrationRequestSchema",
        "MigrationResponseSchema",
        "MigrationListResponseSchema",
        "ValidationConfigSchema",
        "ValidationRequestSchema",
        "ValidationResponseSchema",
        "SwitchRequestSchema",
        "StatusResponseSchema",
    ]
except ImportError:
    MigrationRequestSchema = None
    MigrationResponseSchema = None
    MigrationListResponseSchema = None
    ValidationConfigSchema = None
    ValidationRequestSchema = None
    ValidationResponseSchema = None
    SwitchRequestSchema = None
    StatusResponseSchema = None
    _migration_schemas = []

__all__ = [
    # Ingest schemas
    "SourceType",
    "ChunkingStrategy",
    "ProcessingOptions",
    "ACLContext",
    "IngestRequest",
    "IngestResponse",
    "SingleIngestRequest",
    "JobProgress",
    "JobStatus",
    "JobStatusResponse",
    "ActiveJobsResponse",
    "CancelJobResponse",
    # Sync & Reembed schemas
    "SyncSourceConfig",
    "SyncRequest",
    "SyncResponse",
    "ReembedTargetScope",
    "ReembedRequest",
    "ReembedResponse",
    # Document schemas
    "DocumentResponse",
    "DocumentListResponse",
    "DocumentDeleteResponse",
    "ReindexRequest",
] + _migration_schemas
