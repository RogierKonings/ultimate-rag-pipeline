"""Request and response models for usage tracking API.

Reference: US-10.5.4 - Token Usage Accounting
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class UsageByModel(BaseModel):
    """Token usage breakdown by model.

    Attributes:
        model: The model identifier.
        prompt_tokens: Total prompt tokens consumed.
        completion_tokens: Total completion tokens generated.
        embedding_tokens: Total embedding tokens processed.
        total_tokens: Sum of all token types.
    """

    model: str = Field(..., description="Model identifier")
    prompt_tokens: int = Field(default=0, description="Prompt tokens consumed")
    completion_tokens: int = Field(default=0, description="Completion tokens generated")
    embedding_tokens: int = Field(default=0, description="Embedding tokens processed")
    total_tokens: int = Field(default=0, description="Total tokens")


class UsageStatsResponse(BaseModel):
    """Response model for usage statistics.

    Attributes:
        tenant_id: The tenant identifier.
        period: The time period (day, week, month).
        start_date: Start date of the period.
        end_date: End date of the period.
        usage_by_model: Breakdown of usage per model.
        total_prompt_tokens: Total prompt tokens across all models.
        total_completion_tokens: Total completion tokens across all models.
        total_embedding_tokens: Total embedding tokens across all models.
        total_tokens: Grand total of all tokens.
    """

    tenant_id: str = Field(..., description="Tenant identifier")
    period: str = Field(..., description="Time period")
    start_date: date = Field(..., description="Period start date")
    end_date: date = Field(..., description="Period end date")
    usage_by_model: list[UsageByModel] = Field(default_factory=list, description="Usage per model")
    total_prompt_tokens: int = Field(default=0, description="Total prompt tokens")
    total_completion_tokens: int = Field(default=0, description="Total completion tokens")
    total_embedding_tokens: int = Field(default=0, description="Total embedding tokens")
    total_tokens: int = Field(default=0, description="Grand total tokens")


class QuotaStatusResponse(BaseModel):
    """Response model for quota status.

    Attributes:
        tenant_id: The tenant identifier.
        quota_enabled: Whether quota enforcement is enabled.
        monthly_limit: Monthly token limit (None if unlimited).
        current_usage: Current month's token usage.
        remaining: Tokens remaining (None if unlimited).
        usage_percent: Percentage of quota used (None if unlimited).
        alert_threshold_percent: Alert threshold percentage.
        is_over_limit: Whether usage exceeds the limit.
    """

    tenant_id: str = Field(..., description="Tenant identifier")
    quota_enabled: bool = Field(default=False, description="Quota enforcement enabled")
    monthly_limit: int | None = Field(default=None, description="Monthly token limit")
    current_usage: int = Field(default=0, description="Current month usage")
    remaining: int | None = Field(default=None, description="Tokens remaining")
    usage_percent: float | None = Field(default=None, description="Usage percentage")
    alert_threshold_percent: int = Field(default=80, description="Alert threshold")
    is_over_limit: bool = Field(default=False, description="Usage exceeds limit")


class QuotaUpdateRequest(BaseModel):
    """Request model for updating quota configuration.

    Attributes:
        monthly_token_limit: New monthly token limit (None for unlimited).
        quota_enabled: Whether to enable quota enforcement.
        alert_threshold_percent: Alert threshold percentage.
    """

    monthly_token_limit: int | None = Field(
        default=None,
        ge=0,
        description="Monthly token limit (null for unlimited)",
    )
    quota_enabled: bool = Field(default=False, description="Enable quota enforcement")
    alert_threshold_percent: int = Field(
        default=80,
        ge=0,
        le=100,
        description="Alert threshold percentage",
    )


class QuotaUpdateResponse(BaseModel):
    """Response model for quota update.

    Attributes:
        tenant_id: The tenant identifier.
        monthly_token_limit: Updated monthly token limit.
        quota_enabled: Updated quota enforcement status.
        alert_threshold_percent: Updated alert threshold.
        updated_at: Timestamp of the update.
    """

    tenant_id: str = Field(..., description="Tenant identifier")
    monthly_token_limit: int | None = Field(default=None, description="Monthly limit")
    quota_enabled: bool = Field(default=False, description="Quota enabled")
    alert_threshold_percent: int = Field(default=80, description="Alert threshold")
    message: str = Field(default="Quota updated successfully", description="Status message")
