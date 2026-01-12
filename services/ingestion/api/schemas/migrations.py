"""Pydantic schemas for migration API endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from services.ingestion.migrations.models import MigrationStatus


class ValidationConfigSchema(BaseModel):
    """Schema for validation configuration.

    These settings control how migration quality is validated before switching
    to the new collection.
    """

    sample_size: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Number of sample queries for validation",
    )
    recall_threshold: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="Minimum acceptable recall@10 (overlap score)",
    )
    latency_threshold_ms: int = Field(
        default=100,
        ge=10,
        le=10000,
        description="Maximum acceptable p95 latency in milliseconds",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "sample_size": 100,
                    "recall_threshold": 0.95,
                    "latency_threshold_ms": 100,
                },
            ],
        },
    }


class MigrationRequestSchema(BaseModel):
    """Request schema for starting an embedding migration."""

    target_model: str = Field(..., description="Target embedding model name")
    target_dimensions: int | None = Field(
        None,
        description="Target dimensions (auto-detected if not specified)",
    )

    # Scope
    tenant_ids: list[str] | None = Field(
        None,
        description="Limit migration to specific tenants",
    )

    # Options
    batch_size: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Documents per batch",
    )
    max_concurrent_batches: int = Field(
        default=4,
        ge=1,
        le=16,
        description="Max concurrent batches",
    )
    validate_before_switch: bool = Field(
        default=True,
        description="Run validation before switching",
    )
    auto_switch: bool = Field(
        default=False,
        description="Auto-switch on validation pass",
    )
    preserve_source: bool = Field(
        default=True,
        description="Keep source collection for rollback",
    )

    # Validation configuration
    validation_config: ValidationConfigSchema | None = Field(
        None,
        description="Configuration for migration validation (sample_size, recall_threshold, latency_threshold_ms)",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "target_model": "BAAI/bge-m3",
                    "batch_size": 100,
                    "max_concurrent_batches": 4,
                    "validate_before_switch": True,
                    "auto_switch": False,
                    "preserve_source": True,
                    "validation_config": {
                        "sample_size": 100,
                        "recall_threshold": 0.95,
                        "latency_threshold_ms": 100,
                    },
                },
            ],
        },
    }


class MigrationResponseSchema(BaseModel):
    """Response schema for migration status."""

    migration_id: UUID
    source_model: str
    target_model: str
    source_dimensions: int
    target_dimensions: int
    source_collection: str
    target_collection: str
    alias_name: str

    status: MigrationStatus
    total_documents: int
    processed_documents: int
    failed_documents: int
    progress_percentage: float

    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    validation_score: float | None = None
    validation_passed: bool = False
    validation_config: dict | None = Field(
        None,
        description="Stored validation configuration",
    )
    rollback_enabled: bool = True
    last_error: str | None = None


class ValidationRequestSchema(BaseModel):
    """Request schema for migration validation.

    All fields are optional. If not provided, the values from the stored
    validation config (set when starting the migration) will be used.
    """

    sample_size: int | None = Field(
        default=None,
        ge=10,
        le=1000,
        description="Number of queries to sample (overrides stored config if provided)",
    )
    overlap_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum overlap score to pass (overrides stored config if provided)",
    )


class ValidationResponseSchema(BaseModel):
    """Response schema for validation results."""

    total_queries: int
    avg_overlap: float
    min_overlap: float
    max_overlap: float
    validation_passed: bool
    queries_with_low_overlap: int
    overlap_threshold: float


class SwitchRequestSchema(BaseModel):
    """Request schema for switching collections."""

    force: bool = Field(
        default=False,
        description="Force switch even if validation failed",
    )


class MigrationListResponseSchema(BaseModel):
    """Response schema for listing migrations."""

    migrations: list[MigrationResponseSchema]
    total: int
    active_count: int


class StatusResponseSchema(BaseModel):
    """Generic status response."""

    status: str
    message: str
    migration_id: UUID | None = None
