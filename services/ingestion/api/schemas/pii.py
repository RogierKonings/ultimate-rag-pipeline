"""Pydantic schemas for PII admin API endpoints.

These schemas define the request/response models for managing
per-tenant PII configuration.
"""

from pydantic import BaseModel, ConfigDict, Field


class IngestionPIIConfig(BaseModel):
    """PII configuration for document ingestion."""

    enabled: bool = Field(
        default=True,
        description="Whether PII detection is enabled during ingestion",
    )
    handling_mode: str | None = Field(
        default=None,
        description="Handling mode override (redact, mask, flag, passthrough). None uses default.",
    )
    reject_on_high_sensitivity: bool = Field(
        default=False,
        description="Reject documents containing high-sensitivity PII (SSN, credit card, etc.)",
    )
    store_pii_metadata: bool = Field(
        default=True,
        description="Store PII detection metadata with documents",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "enabled": True,
                    "handling_mode": "redact",
                    "reject_on_high_sensitivity": True,
                    "store_pii_metadata": True,
                },
            ],
        },
    )


class QueryPIIConfig(BaseModel):
    """PII configuration for query sanitization."""

    enabled: bool = Field(
        default=True,
        description="Whether PII detection is enabled for queries",
    )
    handling_mode: str | None = Field(
        default=None,
        description="Handling mode override. None uses default.",
    )
    redact_in_logs: bool = Field(
        default=True,
        description="Redact PII before logging queries",
    )
    reject_queries_with_pii: bool = Field(
        default=False,
        description="Reject queries that contain PII",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "enabled": True,
                    "handling_mode": "redact",
                    "redact_in_logs": True,
                    "reject_queries_with_pii": False,
                },
            ],
        },
    )


class ResponsePIIConfig(BaseModel):
    """PII configuration for response filtering."""

    enabled: bool = Field(
        default=True,
        description="Whether PII detection is enabled for responses",
    )
    handling_mode: str | None = Field(
        default=None,
        description="Handling mode override. None uses default.",
    )
    block_on_high_sensitivity: bool = Field(
        default=False,
        description="Block responses containing high-sensitivity PII",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "enabled": True,
                    "handling_mode": "redact",
                    "block_on_high_sensitivity": False,
                },
            ],
        },
    )


class PIIEntityConfigSchema(BaseModel):
    """Per-entity PII configuration override."""

    enabled: bool = Field(
        default=True,
        description="Whether detection is enabled for this entity type",
    )
    handling_mode: str | None = Field(
        default=None,
        description="Handling mode override for this entity type",
    )
    min_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum confidence score (0-1) for this entity type",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "enabled": True,
                    "handling_mode": "reject",
                    "min_score": 0.9,
                },
            ],
        },
    )


class CustomPatternSchema(BaseModel):
    """Custom regex pattern for tenant-specific PII detection."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique name for the pattern",
    )
    pattern: str = Field(
        ...,
        min_length=1,
        description="Regex pattern to match",
    )
    entity_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Entity type name for matches (e.g., EMPLOYEE_ID)",
    )
    score: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Confidence score to assign to matches",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "employee_id",
                    "pattern": "EMP-\\d{6}",
                    "entity_type": "EMPLOYEE_ID",
                    "score": 0.85,
                },
            ],
        },
    )


class TenantPIISettingsResponse(BaseModel):
    """Full PII configuration for a tenant."""

    tenant_id: str = Field(..., description="Tenant UUID")
    enabled: bool = Field(..., description="Global PII detection enabled")
    default_handling_mode: str = Field(
        ...,
        description="Default handling mode (redact, mask, flag, passthrough)",
    )
    confidence_threshold: float = Field(
        ...,
        description="Default minimum confidence score",
    )
    ingestion: IngestionPIIConfig = Field(
        ...,
        description="Ingestion-specific PII settings",
    )
    query: QueryPIIConfig = Field(
        ...,
        description="Query-specific PII settings",
    )
    response: ResponsePIIConfig = Field(
        ...,
        description="Response-specific PII settings",
    )
    entity_configs: dict[str, PIIEntityConfigSchema] = Field(
        default_factory=dict,
        description="Per-entity configuration overrides",
    )
    custom_patterns: list[CustomPatternSchema] = Field(
        default_factory=list,
        description="Tenant-specific custom patterns",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                    "enabled": True,
                    "default_handling_mode": "redact",
                    "confidence_threshold": 0.7,
                    "ingestion": {
                        "enabled": True,
                        "handling_mode": "redact",
                        "reject_on_high_sensitivity": False,
                        "store_pii_metadata": True,
                    },
                    "query": {
                        "enabled": True,
                        "handling_mode": None,
                        "redact_in_logs": True,
                        "reject_queries_with_pii": False,
                    },
                    "response": {
                        "enabled": True,
                        "handling_mode": None,
                        "block_on_high_sensitivity": False,
                    },
                    "entity_configs": {
                        "US_SSN": {
                            "enabled": True,
                            "handling_mode": "reject",
                            "min_score": 0.9,
                        },
                    },
                    "custom_patterns": [
                        {
                            "name": "employee_id",
                            "pattern": "EMP-\\d{6}",
                            "entity_type": "EMPLOYEE_ID",
                            "score": 0.85,
                        },
                    ],
                },
            ],
        },
    )


class TenantPIISettingsUpdate(BaseModel):
    """Partial update for tenant PII settings.

    All fields are optional. Only provided fields will be updated.
    """

    enabled: bool | None = Field(
        default=None,
        description="Global PII detection enabled",
    )
    default_handling_mode: str | None = Field(
        default=None,
        description="Default handling mode",
    )
    confidence_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Default minimum confidence score",
    )
    ingestion: IngestionPIIConfig | None = Field(
        default=None,
        description="Ingestion-specific PII settings",
    )
    query: QueryPIIConfig | None = Field(
        default=None,
        description="Query-specific PII settings",
    )
    response: ResponsePIIConfig | None = Field(
        default=None,
        description="Response-specific PII settings",
    )
    entity_configs: dict[str, PIIEntityConfigSchema] | None = Field(
        default=None,
        description="Per-entity configuration overrides",
    )


class PIITestRequest(BaseModel):
    """Request to test PII detection on sample text."""

    text: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="Sample text to test PII detection on",
    )
    handling_mode: str | None = Field(
        default=None,
        description="Handling mode to preview (redact, mask, flag). None uses tenant default.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "text": "Contact John Smith at john.smith@example.com or call 555-123-4567.",
                    "handling_mode": "redact",
                },
            ],
        },
    )


class PIIEntityDetected(BaseModel):
    """A detected PII entity (with text redacted for safety)."""

    entity_type: str = Field(..., description="Type of PII detected")
    start: int = Field(..., description="Start position in text")
    end: int = Field(..., description="End position in text")
    score: float = Field(..., description="Confidence score")
    length: int = Field(..., description="Length of detected text")


class PIITestResponse(BaseModel):
    """Response from PII detection test."""

    has_pii: bool = Field(..., description="Whether any PII was detected")
    entity_counts: dict[str, int] = Field(
        ...,
        description="Count of each entity type detected",
    )
    entities: list[PIIEntityDetected] = Field(
        ...,
        description="Detected entities (text values redacted)",
    )
    redacted_text: str = Field(
        ...,
        description="Preview of text after applying handling mode",
    )
    processing_time_ms: float = Field(
        ...,
        description="Time taken to process in milliseconds",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "has_pii": True,
                    "entity_counts": {"EMAIL_ADDRESS": 1, "PHONE_NUMBER": 1, "PERSON": 1},
                    "entities": [
                        {"entity_type": "PERSON", "start": 8, "end": 18, "score": 0.85, "length": 10},
                        {"entity_type": "EMAIL_ADDRESS", "start": 22, "end": 44, "score": 0.99, "length": 22},
                        {"entity_type": "PHONE_NUMBER", "start": 53, "end": 65, "score": 0.95, "length": 12},
                    ],
                    "redacted_text": "Contact [PERSON] at [EMAIL_ADDRESS] or call [PHONE_NUMBER].",
                    "processing_time_ms": 45.2,
                },
            ],
        },
    )


class AddCustomPatternRequest(BaseModel):
    """Request to add a custom pattern."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique name for the pattern",
    )
    pattern: str = Field(
        ...,
        min_length=1,
        description="Regex pattern to match",
    )
    entity_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Entity type name for matches",
    )
    score: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Confidence score to assign",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "employee_id",
                    "pattern": "EMP-\\d{6}",
                    "entity_type": "EMPLOYEE_ID",
                    "score": 0.85,
                },
            ],
        },
    )


class CustomPatternResponse(BaseModel):
    """Response after adding/removing a custom pattern."""

    tenant_id: str
    action: str  # "added" or "removed"
    pattern_name: str
    total_patterns: int
