"""Data models for metadata enrichment."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class PIIType(str, Enum):
    """Types of PII entities that can be detected."""

    EMAIL = "EMAIL_ADDRESS"
    PHONE = "PHONE_NUMBER"
    PERSON = "PERSON"
    LOCATION = "LOCATION"
    CREDIT_CARD = "CREDIT_CARD"
    SSN = "US_SSN"
    IP_ADDRESS = "IP_ADDRESS"
    DATE_TIME = "DATE_TIME"
    NRP = "NRP"  # Nationality, Religion, Political group
    MEDICAL = "MEDICAL_LICENSE"
    ORGANIZATION = "ORGANIZATION"


class PIIEntity(BaseModel):
    """A single detected PII entity."""

    entity_type: PIIType
    text: str
    start: int
    end: int
    score: float  # Confidence score 0-1


class PIIResult(BaseModel):
    """Result of PII detection on a document."""

    entities: list[PIIEntity]
    entity_counts: dict[str, int]
    has_pii: bool
    high_sensitivity: bool  # True if SSN, credit card, etc.


class LanguageResult(BaseModel):
    """Result of language detection."""

    language_code: str  # ISO 639-1 (e.g., "en", "es", "de")
    language_name: str
    confidence: float


class EnrichmentContext(BaseModel):
    """Context passed through the enrichment pipeline."""

    tenant_id: str
    visibility: str = "private"
    allowed_groups: list[str] = Field(default_factory=list)
    allowed_users: list[str] = Field(default_factory=list)
    custom_metadata: dict[str, Any] = Field(default_factory=dict)


class EnrichmentConfig(BaseModel):
    """Configuration for the enrichment pipeline."""

    enable_language_detection: bool = True
    enable_pii_detection: bool = True
    pii_languages: list[str] = Field(default_factory=lambda: ["en"])
    pii_score_threshold: float = 0.7
    high_sensitivity_types: list[PIIType] = Field(
        default_factory=lambda: [
            PIIType.SSN,
            PIIType.CREDIT_CARD,
            PIIType.MEDICAL,
        ]
    )


class DocumentMetadataEnriched(BaseModel):
    """Enriched document metadata."""

    # Extracted from document
    title: Optional[str] = None
    author: Optional[str] = None
    created_date: Optional[datetime] = None
    modified_date: Optional[datetime] = None

    # Detected
    language: Optional[LanguageResult] = None
    pii: Optional[PIIResult] = None

    # Injected (from request/config)
    tenant_id: str
    visibility: str = "private"
    allowed_groups: list[str] = Field(default_factory=list)
    allowed_users: list[str] = Field(default_factory=list)

    # Custom fields
    custom: dict[str, Any] = Field(default_factory=dict)

    # Processing info
    enriched_at: datetime = Field(default_factory=datetime.utcnow)
