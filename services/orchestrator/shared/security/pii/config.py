"""
PII detection configuration.

This module defines configuration settings for PII detection
including handling modes, entity types, and thresholds.
"""

from enum import Enum

from pydantic import BaseModel, Field


class PIIHandlingMode(str, Enum):
    """How to handle detected PII."""

    PASSTHROUGH = "passthrough"  # Do nothing, just flag
    REDACT = "redact"  # Replace with [ENTITY_TYPE]
    MASK = "mask"  # Partially mask (e.g., ***@email.com)
    FLAG = "flag"  # Add metadata flag but keep content
    REJECT = "reject"  # Reject document entirely
    ENCRYPT = "encrypt"  # Encrypt the PII values


class PIIEntityType(str, Enum):
    """Types of PII entities that can be detected."""

    # Standard Presidio entities
    EMAIL_ADDRESS = "EMAIL_ADDRESS"
    PHONE_NUMBER = "PHONE_NUMBER"
    PERSON = "PERSON"
    LOCATION = "LOCATION"
    CREDIT_CARD = "CREDIT_CARD"
    US_SSN = "US_SSN"
    US_ITIN = "US_ITIN"
    US_PASSPORT = "US_PASSPORT"
    US_DRIVER_LICENSE = "US_DRIVER_LICENSE"
    US_BANK_NUMBER = "US_BANK_NUMBER"
    IP_ADDRESS = "IP_ADDRESS"
    DATE_TIME = "DATE_TIME"
    NRP = "NRP"  # Nationality, Religion, Political group
    MEDICAL_LICENSE = "MEDICAL_LICENSE"
    ORGANIZATION = "ORGANIZATION"
    URL = "URL"
    IBAN_CODE = "IBAN_CODE"
    CRYPTO = "CRYPTO"

    # Custom entities
    EMPLOYEE_ID = "EMPLOYEE_ID"
    PROJECT_CODE = "PROJECT_CODE"
    API_KEY = "API_KEY"
    AWS_ACCESS_KEY = "AWS_ACCESS_KEY"
    PRIVATE_KEY = "PRIVATE_KEY"
    JWT_TOKEN = "JWT_TOKEN"
    CONNECTION_STRING = "CONNECTION_STRING"


class PIISensitivity(str, Enum):
    """Sensitivity levels for PII."""

    LOW = "low"  # Names, organizations
    MEDIUM = "medium"  # Emails, phone numbers
    HIGH = "high"  # SSN, credit cards, financial data
    CRITICAL = "critical"  # Credentials, keys


# Default sensitivity mappings
DEFAULT_SENSITIVITY_MAP: dict[str, PIISensitivity] = {
    PIIEntityType.PERSON.value: PIISensitivity.LOW,
    PIIEntityType.ORGANIZATION.value: PIISensitivity.LOW,
    PIIEntityType.LOCATION.value: PIISensitivity.LOW,
    PIIEntityType.DATE_TIME.value: PIISensitivity.LOW,
    PIIEntityType.URL.value: PIISensitivity.LOW,
    PIIEntityType.EMAIL_ADDRESS.value: PIISensitivity.MEDIUM,
    PIIEntityType.PHONE_NUMBER.value: PIISensitivity.MEDIUM,
    PIIEntityType.IP_ADDRESS.value: PIISensitivity.MEDIUM,
    PIIEntityType.NRP.value: PIISensitivity.MEDIUM,
    PIIEntityType.CREDIT_CARD.value: PIISensitivity.HIGH,
    PIIEntityType.US_SSN.value: PIISensitivity.HIGH,
    PIIEntityType.US_ITIN.value: PIISensitivity.HIGH,
    PIIEntityType.US_PASSPORT.value: PIISensitivity.HIGH,
    PIIEntityType.US_DRIVER_LICENSE.value: PIISensitivity.HIGH,
    PIIEntityType.US_BANK_NUMBER.value: PIISensitivity.HIGH,
    PIIEntityType.IBAN_CODE.value: PIISensitivity.HIGH,
    PIIEntityType.MEDICAL_LICENSE.value: PIISensitivity.HIGH,
    PIIEntityType.CRYPTO.value: PIISensitivity.HIGH,
    PIIEntityType.EMPLOYEE_ID.value: PIISensitivity.MEDIUM,
    PIIEntityType.PROJECT_CODE.value: PIISensitivity.LOW,
    PIIEntityType.API_KEY.value: PIISensitivity.CRITICAL,
    PIIEntityType.AWS_ACCESS_KEY.value: PIISensitivity.CRITICAL,
    PIIEntityType.PRIVATE_KEY.value: PIISensitivity.CRITICAL,
    PIIEntityType.JWT_TOKEN.value: PIISensitivity.CRITICAL,
    PIIEntityType.CONNECTION_STRING.value: PIISensitivity.CRITICAL,
}


class PIIEntityConfig(BaseModel):
    """Configuration for a specific PII entity type."""

    enabled: bool = True
    handling_mode: PIIHandlingMode | None = None  # Override default
    min_score: float | None = None  # Override default threshold
    sensitivity: PIISensitivity | None = None  # Override default


class PIISettings(BaseModel):
    """
    Configuration settings for PII detection.

    Example:
        ```python
        settings = PIISettings(
            enabled=True,
            default_handling_mode=PIIHandlingMode.REDACT,
            confidence_threshold=0.7,
            languages=["en"],
            entity_configs={
                PIIEntityType.EMAIL_ADDRESS: PIIEntityConfig(
                    handling_mode=PIIHandlingMode.MASK,
                ),
                PIIEntityType.US_SSN: PIIEntityConfig(
                    handling_mode=PIIHandlingMode.REJECT,
                ),
            },
        )
        ```
    """

    # Global settings
    enabled: bool = Field(
        default=True,
        description="Whether PII detection is enabled",
    )
    default_handling_mode: PIIHandlingMode = Field(
        default=PIIHandlingMode.FLAG,
        description="Default handling mode for detected PII",
    )
    confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence score (0-1) to consider a detection valid",
    )
    languages: list[str] = Field(
        default_factory=lambda: ["en"],
        description="Languages to support (ISO 639-1 codes)",
    )

    # Entity types to detect
    entities_to_detect: list[str] = Field(
        default_factory=lambda: [
            PIIEntityType.EMAIL_ADDRESS.value,
            PIIEntityType.PHONE_NUMBER.value,
            PIIEntityType.PERSON.value,
            PIIEntityType.LOCATION.value,
            PIIEntityType.CREDIT_CARD.value,
            PIIEntityType.US_SSN.value,
            PIIEntityType.IP_ADDRESS.value,
            PIIEntityType.ORGANIZATION.value,
            PIIEntityType.API_KEY.value,
            PIIEntityType.AWS_ACCESS_KEY.value,
            PIIEntityType.PRIVATE_KEY.value,
        ],
        description="Entity types to detect",
    )

    # Per-entity configuration overrides
    entity_configs: dict[str, PIIEntityConfig] = Field(
        default_factory=dict,
        description="Per-entity configuration overrides",
    )

    # Sensitivity-based handling
    high_sensitivity_entities: list[str] = Field(
        default_factory=lambda: [
            PIIEntityType.US_SSN.value,
            PIIEntityType.CREDIT_CARD.value,
            PIIEntityType.US_BANK_NUMBER.value,
            PIIEntityType.MEDICAL_LICENSE.value,
            PIIEntityType.API_KEY.value,
            PIIEntityType.AWS_ACCESS_KEY.value,
            PIIEntityType.PRIVATE_KEY.value,
            PIIEntityType.JWT_TOKEN.value,
            PIIEntityType.CONNECTION_STRING.value,
        ],
        description="Entities considered high sensitivity",
    )

    # Behavior settings
    reject_on_high_sensitivity: bool = Field(
        default=False,
        description="Reject documents containing high-sensitivity PII",
    )
    store_pii_metadata: bool = Field(
        default=True,
        description="Store PII detection results in metadata",
    )
    log_detections: bool = Field(
        default=True,
        description="Log PII detections (without actual values)",
    )

    # Custom recognizers
    custom_recognizers_path: str | None = Field(
        default=None,
        description="Path to custom recognizers YAML file",
    )

    def get_handling_mode(self, entity_type: str) -> PIIHandlingMode:
        """Get handling mode for a specific entity type."""
        if entity_type in self.entity_configs:
            config = self.entity_configs[entity_type]
            if config.handling_mode is not None:
                return config.handling_mode
        return self.default_handling_mode

    def get_min_score(self, entity_type: str) -> float:
        """Get minimum confidence score for a specific entity type."""
        if entity_type in self.entity_configs:
            config = self.entity_configs[entity_type]
            if config.min_score is not None:
                return config.min_score
        return self.confidence_threshold

    def get_sensitivity(self, entity_type: str) -> PIISensitivity:
        """Get sensitivity level for a specific entity type."""
        if entity_type in self.entity_configs:
            config = self.entity_configs[entity_type]
            if config.sensitivity is not None:
                return config.sensitivity
        return DEFAULT_SENSITIVITY_MAP.get(entity_type, PIISensitivity.MEDIUM)

    def is_entity_enabled(self, entity_type: str) -> bool:
        """Check if detection is enabled for a specific entity type."""
        if entity_type not in self.entities_to_detect:
            return False
        if entity_type in self.entity_configs:
            return self.entity_configs[entity_type].enabled
        return True


def create_pii_settings_from_env() -> PIISettings:
    """
    Create PII settings from environment variables.

    Environment variables:
        PII_ENABLED: Enable/disable PII detection
        PII_DEFAULT_MODE: Default handling mode
        PII_THRESHOLD: Confidence threshold
        PII_LANGUAGES: Comma-separated language codes
        PII_REJECT_HIGH_SENSITIVITY: Reject on high-sensitivity PII
    """
    import os

    enabled = os.getenv("PII_ENABLED", "true").lower() == "true"
    mode = os.getenv("PII_DEFAULT_MODE", "flag")
    threshold = float(os.getenv("PII_THRESHOLD", "0.7"))
    languages = os.getenv("PII_LANGUAGES", "en").split(",")
    reject_high = os.getenv("PII_REJECT_HIGH_SENSITIVITY", "false").lower() == "true"

    return PIISettings(
        enabled=enabled,
        default_handling_mode=PIIHandlingMode(mode),
        confidence_threshold=threshold,
        languages=languages,
        reject_on_high_sensitivity=reject_high,
    )
