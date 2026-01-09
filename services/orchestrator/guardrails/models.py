"""Pydantic models for guardrails."""

from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ViolationType(str, Enum):
    """Types of guardrail violations."""

    PII_DETECTED = "pii_detected"
    INJECTION_ATTEMPT = "injection_attempt"
    CONTENT_TOO_LONG = "content_too_long"
    HARMFUL_CONTENT = "harmful_content"
    PROFANITY = "profanity"


class PIIType(str, Enum):
    """Types of PII that can be detected."""

    EMAIL = "email"
    PHONE = "phone"
    SSN = "ssn"
    CREDIT_CARD = "credit_card"
    IP_ADDRESS = "ip_address"


class Violation(BaseModel):
    """A guardrail violation."""

    type: ViolationType
    severity: str  # "low", "medium", "high"
    description: str
    location: Optional[str] = None  # Where in the text


class GuardrailResult(BaseModel):
    """Result of a guardrail check."""

    passed: bool
    violations: List[Violation] = Field(default_factory=list)
    sanitized_content: Optional[str] = None
    processing_time_ms: float = 0.0


class GuardrailConfig(BaseModel):
    """Configuration for guardrails."""

    # Input guardrails
    max_input_length: int = Field(default=4000, description="Maximum input text length")
    enable_pii_detection: bool = Field(default=True, description="Enable PII detection")
    enable_injection_detection: bool = Field(
        default=True, description="Enable prompt injection detection"
    )

    # Output guardrails
    max_output_length: int = Field(default=8000, description="Maximum output text length")
    enable_harmful_content_filter: bool = Field(
        default=True, description="Enable harmful content filtering"
    )
    enable_hallucination_check: bool = Field(
        default=True, description="Enable hallucination checking"
    )

    # Behavior configuration
    block_on_pii: bool = Field(
        default=False, description="Block request on PII detection vs just warn"
    )
    block_on_injection: bool = Field(
        default=True, description="Block request on injection detection"
    )
    block_on_harmful_content: bool = Field(
        default=True, description="Block response on harmful content"
    )

    # Severity thresholds
    pii_severity: Literal["low", "medium", "high", "critical"] = Field(
        default="medium", description="Default severity for PII violations"
    )
    injection_severity: Literal["low", "medium", "high", "critical"] = Field(
        default="critical", description="Default severity for injection violations"
    )
    harmful_content_severity: Literal["low", "medium", "high", "critical"] = Field(
        default="high", description="Default severity for harmful content violations"
    )
    length_severity: Literal["low", "medium", "high", "critical"] = Field(
        default="low", description="Default severity for length violations"
    )

    # Hallucination detection
    hallucination_threshold: float = Field(
        default=0.5,
        description="Threshold for hallucination detection (0-1, lower = more strict)",
    )
