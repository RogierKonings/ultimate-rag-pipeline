"""Pydantic schemas for ingestion API endpoints."""

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SourceType(str, Enum):
    """Supported source types for document ingestion."""

    FILESYSTEM = "filesystem"
    DATABASE = "database"
    WEB = "web"
    API = "api"


class ChunkingStrategy(str, Enum):
    """Available chunking strategies."""

    RECURSIVE = "recursive"
    SEMANTIC = "semantic"
    HIERARCHICAL = "hierarchical"


# --- Source Configuration Models ---


class FilesystemSourceConfig(BaseModel):
    """Configuration for filesystem source."""

    path: str
    storage_type: Literal["local", "s3"] = "local"
    s3_endpoint: str | None = None
    s3_bucket: str | None = None
    recursive: bool = True
    file_extensions: list[str] | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "path": "/data/documents",
                    "storage_type": "local",
                    "recursive": True,
                    "file_extensions": [".pdf", ".docx", ".md"],
                },
                {
                    "path": "documents/",
                    "storage_type": "s3",
                    "s3_endpoint": "http://minio:9000",
                    "s3_bucket": "rag-documents",
                    "recursive": True,
                },
            ],
        },
    )


class DatabaseSourceConfig(BaseModel):
    """Configuration for database source."""

    connection_string: str
    db_type: Literal["postgresql", "mysql"]
    query: str
    content_column: str
    id_column: str
    metadata_columns: list[str] = []

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "connection_string": "postgresql://user:pass@localhost:5432/articles",
                    "db_type": "postgresql",
                    "query": "SELECT id, content, title, author FROM articles WHERE updated_at > :since",
                    "content_column": "content",
                    "id_column": "id",
                    "metadata_columns": ["title", "author"],
                },
            ],
        },
    )


class WebSourceConfig(BaseModel):
    """Configuration for web crawler source."""

    start_urls: list[str]
    allowed_domains: list[str] | None = None
    max_depth: int = 2
    max_pages: int = 100

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "start_urls": ["https://docs.example.com/"],
                    "allowed_domains": ["docs.example.com"],
                    "max_depth": 3,
                    "max_pages": 500,
                },
            ],
        },
    )


class APISourceConfig(BaseModel):
    """Configuration for API source."""

    base_url: str
    list_endpoint: str
    fetch_endpoint: str
    auth_type: Literal["none", "bearer", "api_key", "basic"] = "none"
    auth_token: str | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "base_url": "https://api.example.com/v1",
                    "list_endpoint": "/documents",
                    "fetch_endpoint": "/documents/{id}",
                    "auth_type": "bearer",
                    "auth_token": "your-api-token",
                },
            ],
        },
    )


# --- Processing Options ---


class ProcessingOptions(BaseModel):
    """Options for document processing pipeline."""

    chunking_strategy: ChunkingStrategy = ChunkingStrategy.SEMANTIC
    chunk_size: int = Field(default=512, ge=100, le=4096)
    chunk_overlap: int = Field(default=50, ge=0, le=500)
    enable_pii_detection: bool = True
    custom_metadata: dict[str, Any] = {}

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "chunking_strategy": "recursive",
                    "chunk_size": 300,
                    "chunk_overlap": 50,
                    "enable_pii_detection": True,
                    "custom_metadata": {"department": "Engineering"},
                },
            ],
        },
    )


class ACLContext(BaseModel):
    """Access control context for ingested documents."""

    tenant_id: str
    visibility: Literal["public", "private", "group"] = "private"
    allowed_groups: list[str] = []
    allowed_users: list[str] = []

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                    "visibility": "group",
                    "allowed_groups": [
                        "550e8400-e29b-41d4-a716-446655440001",
                        "550e8400-e29b-41d4-a716-446655440002",
                    ],
                    "allowed_users": [],
                },
            ],
        },
    )


# --- Ingestion Request/Response ---


class IngestRequest(BaseModel):
    """Request to start an ingestion job.

    Per architecture.md POST /api/v1/ingest contract.
    """

    source_type: SourceType
    source_config: dict[str, Any]  # Validated based on source_type
    processing: ProcessingOptions = ProcessingOptions()
    acl: ACLContext

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "source_type": "filesystem",
                    "source_config": {
                        "path": "s3://bucket/path/document.pdf",
                        "storage_type": "s3",
                        "s3_bucket": "bucket",
                    },
                    "processing": {
                        "chunking_strategy": "recursive",
                        "chunk_size": 300,
                        "chunk_overlap": 50,
                    },
                    "acl": {
                        "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                        "visibility": "private",
                        "allowed_groups": [
                            "550e8400-e29b-41d4-a716-446655440001",
                            "550e8400-e29b-41d4-a716-446655440002",
                        ],
                    },
                },
            ],
        },
    )

    @field_validator("source_config")
    @classmethod
    def validate_source_config(cls, v: dict[str, Any], info) -> dict[str, Any]:
        """Validate source_config matches source_type schema."""
        source_type = info.data.get("source_type")
        if source_type == SourceType.FILESYSTEM:
            FilesystemSourceConfig(**v)
        elif source_type == SourceType.DATABASE:
            DatabaseSourceConfig(**v)
        elif source_type == SourceType.WEB:
            WebSourceConfig(**v)
        elif source_type == SourceType.API:
            APISourceConfig(**v)
        return v


class IngestResponse(BaseModel):
    """Response after starting an ingestion job.

    Per architecture.md POST /api/v1/ingest response contract.
    """

    job_id: UUID
    status: str
    message: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job_id": "550e8400-e29b-41d4-a716-446655440000",
                    "status": "queued",
                    "message": "Ingestion job started",
                    "created_at": "2025-12-18T12:00:00Z",
                },
            ],
        },
    )


class SingleIngestRequest(BaseModel):
    """Request to ingest a single document."""

    source_type: str
    source_id: str
    source_config: dict[str, Any]
    processing: ProcessingOptions = ProcessingOptions()
    acl: ACLContext

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "source_type": "filesystem",
                    "source_id": "doc-001",
                    "source_config": {
                        "path": "/data/documents/report.pdf",
                        "storage_type": "local",
                    },
                    "processing": {
                        "chunking_strategy": "recursive",
                        "chunk_size": 300,
                    },
                    "acl": {
                        "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                        "visibility": "private",
                    },
                },
            ],
        },
    )


# --- Job Status ---


class JobProgress(BaseModel):
    """Progress information for a running job."""

    current: int = 0
    total: int = 0
    stage: str = ""
    percentage: float = 0.0

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "current": 75,
                    "total": 150,
                    "stage": "embedding",
                    "percentage": 50.0,
                },
            ],
        },
    )


class JobStatus(str, Enum):
    """Job status values."""

    PENDING = "pending"
    STARTED = "started"
    PROGRESS = "progress"
    SUCCESS = "success"
    FAILURE = "failure"
    REVOKED = "revoked"


class JobStatusResponse(BaseModel):
    """Response for job status query."""

    job_id: UUID
    status: JobStatus
    progress: JobProgress | None = None
    documents_processed: int = 0
    chunks_created: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    error_message: str | None = None
    errors: list[str] = []

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job_id": "550e8400-e29b-41d4-a716-446655440000",
                    "status": "progress",
                    "progress": {
                        "current": 75,
                        "total": 150,
                        "stage": "embedding",
                        "percentage": 50.0,
                    },
                    "documents_processed": 75,
                    "chunks_created": 450,
                    "started_at": "2025-12-18T12:00:00Z",
                    "completed_at": None,
                    "duration_seconds": 120.5,
                    "error_message": None,
                    "errors": [],
                },
                {
                    "job_id": "550e8400-e29b-41d4-a716-446655440001",
                    "status": "success",
                    "progress": {
                        "current": 150,
                        "total": 150,
                        "stage": "completed",
                        "percentage": 100.0,
                    },
                    "documents_processed": 150,
                    "chunks_created": 900,
                    "started_at": "2025-12-18T12:00:00Z",
                    "completed_at": "2025-12-18T12:04:30Z",
                    "duration_seconds": 270.0,
                    "error_message": None,
                    "errors": [],
                },
            ],
        },
    )


class ActiveJobsResponse(BaseModel):
    """Response for listing active jobs."""

    jobs: list[JobStatusResponse]
    total: int

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "jobs": [
                        {
                            "job_id": "550e8400-e29b-41d4-a716-446655440000",
                            "status": "progress",
                            "documents_processed": 75,
                            "chunks_created": 450,
                        },
                    ],
                    "total": 1,
                },
            ],
        },
    )


class CancelJobResponse(BaseModel):
    """Response for job cancellation."""

    job_id: UUID
    cancelled: bool

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job_id": "550e8400-e29b-41d4-a716-446655440000",
                    "cancelled": True,
                },
            ],
        },
    )


# --- Sync & Re-embed Schemas ---


class SyncSourceConfig(BaseModel):
    """Configuration for incremental sync source."""

    connection_string: str | None = Field(
        None,
        description="Database connection string for DATABASE source",
    )
    table: str | None = Field(None, description="Table to sync for DATABASE source")
    updated_since: datetime | None = Field(
        None,
        description="Sync documents updated since this timestamp",
    )
    path: str | None = Field(None, description="Path for FILESYSTEM source")
    start_urls: list[str] | None = Field(None, description="URLs for WEB source")
    base_url: str | None = Field(None, description="Base URL for API source")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "connection_string": "postgresql://user:pass@localhost:5432/mydb",
                    "table": "articles",
                    "updated_since": "2025-12-01T00:00:00Z",
                },
                {
                    "path": "/data/documents",
                    "updated_since": "2025-12-01T00:00:00Z",
                },
            ],
        },
    )


class SyncRequest(BaseModel):
    """Request to trigger incremental sync for a source.

    Per architecture.md POST /api/v1/ingest/sync contract.
    """

    tenant_id: str = Field(..., description="Tenant identifier")
    source_type: SourceType = Field(..., description="Type of source to sync")
    source_config: SyncSourceConfig = Field(..., description="Source configuration")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                    "source_type": "database",
                    "source_config": {
                        "connection_string": "postgresql://user:pass@localhost:5432/mydb",
                        "table": "articles",
                        "updated_since": "2025-12-01T00:00:00Z",
                    },
                },
                {
                    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                    "source_type": "filesystem",
                    "source_config": {
                        "path": "/data/documents",
                        "updated_since": "2025-12-01T00:00:00Z",
                    },
                },
            ],
        },
    )

    @field_validator("source_config")
    @classmethod
    def validate_source_config(
        cls,
        v: SyncSourceConfig,
        info,
    ) -> SyncSourceConfig:
        """Validate that required fields are present for source type."""
        source_type = info.data.get("source_type")
        if source_type == SourceType.DATABASE and (not v.connection_string or not v.table):
            raise ValueError(
                "DATABASE source requires connection_string and table",
            )
        return v


class SyncResponse(BaseModel):
    """Response after starting an incremental sync job."""

    job_id: UUID = Field(..., description="Job identifier for tracking")
    status: str = Field(default="queued", description="Initial job status")
    estimated_completion: datetime | None = Field(
        None,
        description="Estimated completion time",
    )
    message: str = Field(default="Sync job started", description="Status message")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job_id": "550e8400-e29b-41d4-a716-446655440000",
                    "status": "queued",
                    "estimated_completion": "2025-12-18T12:05:00Z",
                    "message": "Sync job started",
                },
            ],
        },
    )


class ReembedTargetScope(BaseModel):
    """Target scope for re-embedding job.

    Filters which documents to re-embed with new model.
    """

    tenant_id: str | None = Field(None, description="Limit to specific tenant")
    source_types: list[SourceType] | None = Field(
        None,
        description="Limit to specific source types",
    )
    document_ids: list[UUID] | None = Field(
        None,
        description="Limit to specific document IDs",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                    "source_types": ["filesystem", "web"],
                },
                {
                    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                    "document_ids": [
                        "550e8400-e29b-41d4-a716-446655440001",
                        "550e8400-e29b-41d4-a716-446655440002",
                    ],
                },
            ],
        },
    )


class ReembedRequest(BaseModel):
    """Request to start re-embedding job with new model.

    Per architecture.md POST /api/v1/ingest/reembed contract.
    """

    embedding_model: str = Field(
        ...,
        description="New embedding model name (e.g., BAAI/bge-m3)",
    )
    target_scope: ReembedTargetScope = Field(
        ...,
        description="Scope filter for documents to re-embed",
    )
    batch_size: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Batch size for processing",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "embedding_model": "BAAI/bge-m3",
                    "target_scope": {
                        "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                        "source_types": ["filesystem", "web"],
                    },
                    "batch_size": 100,
                },
            ],
        },
    )


class ReembedResponse(BaseModel):
    """Response after starting a re-embedding job."""

    job_id: UUID = Field(..., description="Celery job ID for task tracking")
    embedding_job_id: UUID = Field(
        ...,
        description="Embedding job record ID in database",
    )
    status: str = Field(default="pending", description="Initial job status")
    estimated_completion: datetime | None = Field(
        None,
        description="Estimated completion time",
    )
    message: str = Field(
        default="Re-embedding job started",
        description="Status message",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job_id": "550e8400-e29b-41d4-a716-446655440000",
                    "embedding_job_id": "550e8400-e29b-41d4-a716-446655440001",
                    "status": "pending",
                    "estimated_completion": "2025-12-18T14:00:00Z",
                    "message": "Re-embedding job started",
                },
            ],
        },
    )
