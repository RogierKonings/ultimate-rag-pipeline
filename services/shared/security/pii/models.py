"""
PII detection data models.

This module defines the data structures for PII detection results,
entities, and processing outcomes.
"""

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from .config import PIIEntityType, PIIHandlingMode, PIISensitivity


class PIIEntity(BaseModel):
    """
    A single detected PII entity.

    Represents one occurrence of PII found in text,
    with its type, location, and confidence score.
    """

    entity_type: str = Field(
        ...,
        description="Type of PII entity (e.g., EMAIL_ADDRESS, PERSON)",
    )
    text: str = Field(
        ...,
        description="The actual PII text found",
    )
    start: int = Field(
        ...,
        description="Start character offset in original text",
    )
    end: int = Field(
        ...,
        description="End character offset in original text",
    )
    score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score (0-1)",
    )
    sensitivity: Optional[PIISensitivity] = Field(
        default=None,
        description="Sensitivity level of this entity",
    )

    def to_safe_dict(self) -> dict[str, Any]:
        """
        Convert to dict without actual PII text.

        For logging/auditing without exposing PII values.
        """
        return {
            "entity_type": self.entity_type,
            "start": self.start,
            "end": self.end,
            "score": self.score,
            "length": self.end - self.start,
            "sensitivity": self.sensitivity.value if self.sensitivity else None,
        }


class PIIResult(BaseModel):
    """
    Result of PII detection on text.

    Contains all detected entities and summary statistics.
    """

    entities: list[PIIEntity] = Field(
        default_factory=list,
        description="List of detected PII entities",
    )
    entity_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Count of each entity type detected",
    )
    has_pii: bool = Field(
        default=False,
        description="Whether any PII was detected",
    )
    has_high_sensitivity: bool = Field(
        default=False,
        description="Whether high-sensitivity PII was detected",
    )
    processed_length: int = Field(
        default=0,
        description="Length of text processed",
    )
    processing_time_ms: float = Field(
        default=0.0,
        description="Time taken to process in milliseconds",
    )

    def to_safe_dict(self) -> dict[str, Any]:
        """
        Convert to dict for logging without PII values.
        """
        return {
            "entity_counts": self.entity_counts,
            "has_pii": self.has_pii,
            "has_high_sensitivity": self.has_high_sensitivity,
            "total_entities": len(self.entities),
            "processed_length": self.processed_length,
            "processing_time_ms": self.processing_time_ms,
        }


class PIIProcessedText(BaseModel):
    """
    Text after PII processing (redaction, masking, etc.).

    Contains the processed text and details of transformations.
    """

    original_length: int = Field(
        ...,
        description="Length of original text",
    )
    processed_text: str = Field(
        ...,
        description="Text after PII processing",
    )
    handling_mode: PIIHandlingMode = Field(
        ...,
        description="How PII was handled",
    )
    entities_processed: int = Field(
        default=0,
        description="Number of PII entities processed",
    )
    transformations: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Details of each transformation applied",
    )


class PIIChunkResult(BaseModel):
    """
    PII processing result for a document chunk.

    Used during ingestion pipeline processing.
    """

    chunk_id: str = Field(
        ...,
        description="ID of the processed chunk",
    )
    detection_result: PIIResult = Field(
        ...,
        description="PII detection results",
    )
    processed: Optional[PIIProcessedText] = Field(
        default=None,
        description="Processed text if transformation was applied",
    )
    rejected: bool = Field(
        default=False,
        description="Whether chunk was rejected due to PII",
    )
    rejection_reason: Optional[str] = Field(
        default=None,
        description="Reason for rejection if applicable",
    )


class PIIDocumentResult(BaseModel):
    """
    Aggregated PII results for an entire document.

    Summarizes PII findings across all chunks.
    """

    document_id: UUID = Field(
        ...,
        description="ID of the document",
    )
    total_chunks: int = Field(
        default=0,
        description="Total chunks processed",
    )
    chunks_with_pii: int = Field(
        default=0,
        description="Chunks containing PII",
    )
    chunks_rejected: int = Field(
        default=0,
        description="Chunks rejected due to PII",
    )
    total_entities: int = Field(
        default=0,
        description="Total PII entities found",
    )
    entity_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Aggregated entity counts",
    )
    has_high_sensitivity: bool = Field(
        default=False,
        description="Whether high-sensitivity PII was found",
    )
    high_sensitivity_types: list[str] = Field(
        default_factory=list,
        description="Types of high-sensitivity PII found",
    )
    processing_time_ms: float = Field(
        default=0.0,
        description="Total processing time",
    )
    processed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When processing completed",
    )

    @classmethod
    def from_chunk_results(
        cls,
        document_id: UUID,
        chunk_results: list[PIIChunkResult],
    ) -> "PIIDocumentResult":
        """
        Create document result from chunk results.

        Args:
            document_id: Document ID.
            chunk_results: List of chunk processing results.

        Returns:
            Aggregated document result.
        """
        entity_counts: dict[str, int] = {}
        total_entities = 0
        chunks_with_pii = 0
        chunks_rejected = 0
        has_high_sensitivity = False
        high_sensitivity_types: set[str] = set()
        total_time = 0.0

        for chunk_result in chunk_results:
            result = chunk_result.detection_result

            if result.has_pii:
                chunks_with_pii += 1

            if chunk_result.rejected:
                chunks_rejected += 1

            if result.has_high_sensitivity:
                has_high_sensitivity = True
                # Track which high-sensitivity types were found
                for entity in result.entities:
                    if entity.sensitivity and entity.sensitivity in (
                        PIISensitivity.HIGH,
                        PIISensitivity.CRITICAL,
                    ):
                        high_sensitivity_types.add(entity.entity_type)

            total_entities += len(result.entities)
            total_time += result.processing_time_ms

            for entity_type, count in result.entity_counts.items():
                entity_counts[entity_type] = entity_counts.get(entity_type, 0) + count

        return cls(
            document_id=document_id,
            total_chunks=len(chunk_results),
            chunks_with_pii=chunks_with_pii,
            chunks_rejected=chunks_rejected,
            total_entities=total_entities,
            entity_counts=entity_counts,
            has_high_sensitivity=has_high_sensitivity,
            high_sensitivity_types=sorted(high_sensitivity_types),
            processing_time_ms=total_time,
        )


class PIIAnalysisRequest(BaseModel):
    """Request model for PII analysis API endpoint."""

    text: str = Field(
        ...,
        min_length=1,
        description="Text to analyze for PII",
    )
    language: str = Field(
        default="en",
        description="Language of the text (ISO 639-1)",
    )
    entities: Optional[list[str]] = Field(
        default=None,
        description="Specific entity types to detect (None = all configured)",
    )
    score_threshold: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum confidence score (None = use default)",
    )
    return_text: bool = Field(
        default=False,
        description="Whether to include detected text in response",
    )


class PIIAnalysisResponse(BaseModel):
    """Response model for PII analysis API endpoint."""

    entities: list[PIIEntity] = Field(
        default_factory=list,
        description="Detected PII entities",
    )
    entity_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Count of each entity type",
    )
    has_pii: bool = Field(
        default=False,
        description="Whether any PII was detected",
    )
    has_high_sensitivity: bool = Field(
        default=False,
        description="Whether high-sensitivity PII was detected",
    )
    redacted_text: Optional[str] = Field(
        default=None,
        description="Text with PII redacted (if requested)",
    )
    processing_time_ms: float = Field(
        default=0.0,
        description="Processing time in milliseconds",
    )
