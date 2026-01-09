"""Data models for job management and tracking.

This module defines Pydantic models for:
- Job status enumeration
- Progress tracking
- Job results and requests
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Status of an async job."""

    PENDING = "pending"
    STARTED = "started"
    PROGRESS = "progress"
    SUCCESS = "success"
    FAILURE = "failure"
    RETRY = "retry"
    REVOKED = "revoked"


class JobProgress(BaseModel):
    """Progress information for a running job."""

    current: int = Field(default=0, ge=0, description="Current item number")
    total: int = Field(default=0, ge=0, description="Total items to process")
    stage: str = Field(default="", description="Current processing stage")
    message: str = Field(default="", description="Human-readable status message")

    @property
    def percentage(self) -> float:
        """Calculate progress percentage."""
        if self.total == 0:
            return 0.0
        return (self.current / self.total) * 100


class IngestJobResult(BaseModel):
    """Result of an ingestion job."""

    job_id: str = Field(..., description="Unique job identifier")
    status: JobStatus = Field(..., description="Current job status")
    progress: Optional[JobProgress] = Field(
        default=None, description="Progress info if in progress"
    )

    # Results
    documents_processed: int = Field(default=0, ge=0)
    chunks_created: int = Field(default=0, ge=0)
    errors: list[str] = Field(default_factory=list)

    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None

    # Error info
    error_message: Optional[str] = None
    traceback: Optional[str] = None


class IngestJobRequest(BaseModel):
    """Request parameters for an ingestion job."""

    job_id: UUID = Field(default_factory=uuid4, description="Unique job identifier")

    # Source configuration
    source_type: str = Field(
        ..., description="Source type: filesystem, database, web, api"
    )
    source_config: dict[str, Any] = Field(
        ..., description="Source-specific configuration"
    )

    # Processing options
    chunking_strategy: str = Field(
        default="recursive", description="Chunking strategy to use"
    )
    chunk_size: int = Field(default=300, ge=50, le=2048, description="Target chunk size in tokens")
    chunk_overlap: int = Field(default=50, ge=0, le=500, description="Chunk overlap in tokens")

    # ACL context
    tenant_id: str = Field(..., description="Tenant identifier")
    visibility: str = Field(default="private", description="Document visibility")
    allowed_groups: list[str] = Field(default_factory=list)
    allowed_users: list[str] = Field(default_factory=list)

    # Options
    enable_pii_detection: bool = Field(default=True)
    custom_metadata: dict[str, Any] = Field(default_factory=dict)


class ReembedJobRequest(BaseModel):
    """Request parameters for a re-embedding job."""

    job_id: UUID = Field(default_factory=uuid4)
    collection_name: str = Field(..., description="Collection to re-embed")
    new_model: str = Field(..., description="New embedding model to use")
    batch_size: int = Field(
        default=100, ge=1, le=1000, description="Batch size for processing"
    )
    tenant_id: Optional[str] = Field(
        default=None, description="Optional tenant filter"
    )


class DLQEntry(BaseModel):
    """Entry in the dead letter queue."""

    task_name: str = Field(..., description="Name of the failed task")
    args: list[Any] = Field(default_factory=list, description="Task arguments")
    kwargs: dict[str, Any] = Field(default_factory=dict, description="Task keyword arguments")
    error: str = Field(..., description="Error message")
    traceback: Optional[str] = Field(default=None, description="Full traceback")
    retries: int = Field(default=0, ge=0, description="Number of retries attempted")
    failed_at: datetime = Field(default_factory=datetime.utcnow)
    job_id: Optional[str] = Field(default=None, description="Associated job ID")
