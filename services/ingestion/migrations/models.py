"""Data models for embedding model migration.

These models track migration state, progress, and validation results.
"""

from dataclasses import dataclass, asdict, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


@dataclass
class ValidationConfig:
    """Configuration for migration validation.

    Attributes:
        sample_size: Number of sample queries to use for validation.
        recall_threshold: Minimum acceptable recall@10 (overlap score).
        latency_threshold_ms: Maximum acceptable p95 latency in milliseconds.
    """

    sample_size: int = 100
    recall_threshold: float = 0.95  # Min acceptable recall@10
    latency_threshold_ms: int = 100  # Max acceptable p95 latency

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ValidationConfig":
        """Create from dictionary."""
        if data is None:
            return cls()
        return cls(
            sample_size=data.get("sample_size", 100),
            recall_threshold=data.get("recall_threshold", 0.95),
            latency_threshold_ms=data.get("latency_threshold_ms", 100),
        )


class MigrationStatus(str, Enum):
    """Status of an embedding model migration."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    VALIDATING = "validating"
    SWITCHING = "switching"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class EmbeddingMigration(BaseModel):
    """Tracks an embedding model migration.

    This model captures the full state of a migration, including:
    - Source and target model information
    - Collection mapping for zero-downtime switching
    - Progress tracking for re-embedding
    - Validation results and timestamps
    """

    migration_id: UUID

    # Model info
    source_model: str
    target_model: str
    source_dimensions: int
    target_dimensions: int

    # Collection info
    source_collection: str
    target_collection: str
    alias_name: str = "rag_chunks"

    # Progress
    status: MigrationStatus = MigrationStatus.PENDING
    total_documents: int = 0
    processed_documents: int = 0
    failed_documents: int = 0

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Validation
    validation_score: Optional[float] = None
    validation_passed: bool = False

    # Rollback info
    rollback_enabled: bool = True

    # Validation configuration
    validation_config: Optional[dict] = None

    # Error tracking
    last_error: Optional[str] = None

    @property
    def progress_percentage(self) -> float:
        """Calculate progress as a percentage."""
        if self.total_documents == 0:
            return 0.0
        return round(self.processed_documents / self.total_documents * 100, 2)

    @property
    def is_active(self) -> bool:
        """Check if migration is currently active."""
        return self.status in (
            MigrationStatus.PENDING,
            MigrationStatus.IN_PROGRESS,
            MigrationStatus.VALIDATING,
            MigrationStatus.SWITCHING,
        )

    @property
    def can_rollback(self) -> bool:
        """Check if rollback is possible."""
        return (
            self.rollback_enabled
            and self.status
            in (
                MigrationStatus.COMPLETED,
                MigrationStatus.FAILED,
                MigrationStatus.VALIDATING,
            )
        )

    model_config = {"json_encoders": {datetime: lambda v: v.isoformat()}}


class MigrationRequest(BaseModel):
    """Request to start an embedding migration."""

    target_model: str = Field(..., description="New embedding model name")
    target_dimensions: Optional[int] = Field(
        None, description="Dimensions (auto-detected if None)"
    )

    # Scope
    tenant_ids: Optional[list[str]] = Field(
        None, description="Limit to specific tenants"
    )
    document_filters: Optional[dict] = Field(
        None, description="Filter documents to migrate"
    )

    # Options
    batch_size: int = Field(default=100, ge=10, le=1000)
    max_concurrent_batches: int = Field(default=4, ge=1, le=16)
    validate_before_switch: bool = True
    auto_switch: bool = False  # Require manual switch confirmation
    preserve_source: bool = True  # Keep old collection for rollback

    # Validation configuration
    validation_config: Optional[dict] = Field(
        None,
        description="Validation configuration with sample_size, recall_threshold, latency_threshold_ms",
    )


class ValidationResult(BaseModel):
    """Results from migration validation."""

    total_queries: int
    overlap_scores: list[float]
    avg_overlap: float
    validation_passed: bool
    min_overlap: float = 0.0
    max_overlap: float = 0.0

    # Detailed metrics
    queries_with_low_overlap: int = 0
    overlap_threshold: float = 0.7

    @classmethod
    def from_scores(
        cls, scores: list[float], threshold: float = 0.7
    ) -> "ValidationResult":
        """Create a validation result from overlap scores."""
        if not scores:
            return cls(
                total_queries=0,
                overlap_scores=[],
                avg_overlap=0.0,
                validation_passed=False,
                overlap_threshold=threshold,
            )

        avg = sum(scores) / len(scores)
        return cls(
            total_queries=len(scores),
            overlap_scores=scores,
            avg_overlap=avg,
            validation_passed=avg >= threshold,
            min_overlap=min(scores),
            max_overlap=max(scores),
            queries_with_low_overlap=sum(1 for s in scores if s < threshold),
            overlap_threshold=threshold,
        )


class MigrationProgress(BaseModel):
    """Progress update for a migration batch."""

    migration_id: UUID
    batch_index: int
    documents_processed: int
    documents_failed: int
    batch_duration_ms: float
    error_messages: list[str] = Field(default_factory=list)
