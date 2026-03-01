"""Pydantic models for answer verification."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Claim(BaseModel):
    """A factual claim extracted from the answer."""

    text: str = Field(..., description="The claim text")
    claim_type: Literal["factual", "numerical", "temporal", "attribution"] = Field(
        default="factual", description="Type of claim"
    )


class VerificationStatus(StrEnum):
    """Status of claim verification against context."""

    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    UNVERIFIABLE = "unverifiable"


class ClaimVerificationResult(BaseModel):
    """Result of verifying a single claim against context."""

    claim_text: str = Field(..., description="The original claim text")
    status: VerificationStatus = Field(..., description="Verification status")
    supporting_evidence: str | None = Field(
        default=None, description="Quote from context supporting the claim"
    )


class ClaimExtractionResult(BaseModel):
    """Result of extracting claims from an answer."""

    claims: list[Claim] = Field(default_factory=list, description="Extracted claims")
    extraction_time_ms: float = Field(..., description="Time taken to extract claims")


class VerificationResult(BaseModel):
    """Overall verification result for the generated answer."""

    score: float = Field(..., ge=0.0, le=1.0, description="Verification score (0-1)")
    label: str = Field(
        ..., description="Verification label: supported, partial, unsupported, skipped"
    )
    claims_total: int = Field(default=0, description="Total claims verified")
    claims_supported: int = Field(default=0, description="Fully supported claims")
    claims_partial: int = Field(default=0, description="Partially supported claims")
    claims_unsupported: int = Field(default=0, description="Unsupported claims")
    verification_time_ms: float = Field(..., description="Total verification time")
    skipped: bool = Field(default=False, description="Whether verification was skipped")
    skip_reason: str | None = Field(default=None, description="Reason for skipping verification")
