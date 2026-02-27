"""Admin API routes for usage tracking and quota management.

Reference: US-10.5.4 - Token Usage Accounting
"""

import json as _json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from api.models.usage import (
    QuotaStatusResponse,
    QuotaUpdateRequest,
    QuotaUpdateResponse,
    UsageByModel,
    UsageStatsResponse,
)
from database.connection import get_db
from database.models.usage import TenantQuota, TokenUsage
from fastapi import APIRouter, Depends, HTTPException, Request, status
from shared.security.jwt.middleware import JWTAuthMiddleware, require_roles
from shared.security.jwt.models import TokenClaims
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Cache TTL for admin usage aggregation queries (seconds)
_USAGE_CACHE_TTL = 120

router = APIRouter(prefix="/admin", tags=["admin"])

DbSessionDep = Annotated[AsyncSession, Depends(get_db)]

_auth = JWTAuthMiddleware()


async def _require_admin(
    claims: Annotated[TokenClaims, Depends(_auth.get_current_user)],
) -> TokenClaims:
    """Require admin or service_account role for admin endpoints."""
    return await require_roles("admin", "service_account")(claims)

AdminAuthDep = Annotated[TokenClaims, Depends(_require_admin)]


def _get_redis(request: Request):
    """Extract the Redis client from app state (session manager), if available."""
    sm = getattr(request.app.state, "session_manager", None)
    if sm and hasattr(sm, "store") and hasattr(sm.store, "_redis"):
        return sm.store._redis
    return None


@router.get(
    "/usage/{tenant_id}",
    response_model=UsageStatsResponse,
    summary="Get usage statistics",
    description="Get token usage statistics for a tenant over a specified period.",
)
async def get_usage_stats(
    tenant_id: str,
    request: Request,
    period: Literal["day", "week", "month"] = "month",
    _: AdminAuthDep = None,
    db: DbSessionDep = None,
) -> UsageStatsResponse:
    """Get token usage statistics for a tenant.

    Args:
        tenant_id: The tenant identifier.
        period: Time period - day, week, or month (default: month).
        db: Database session.

    Returns:
        Usage statistics breakdown by model.
    """
    # Try Redis cache first
    redis = _get_redis(request)
    cache_key = f"admin:usage:{tenant_id}:{period}"
    if redis:
        try:
            cached = await redis.get(cache_key)
            if cached:
                return UsageStatsResponse(**_json.loads(cached))
        except Exception:
            pass  # Fall through to DB on cache errors

    end_date = datetime.now(UTC).date()

    if period == "day":
        start_date = end_date
    elif period == "week":
        start_date = end_date - timedelta(days=7)
    else:  # month
        start_date = end_date.replace(day=1)

    # Query aggregated usage by model
    result = await db.execute(
        select(
            TokenUsage.model,
            func.sum(TokenUsage.prompt_tokens).label("prompt_tokens"),
            func.sum(TokenUsage.completion_tokens).label("completion_tokens"),
            func.sum(TokenUsage.embedding_tokens).label("embedding_tokens"),
        )
        .where(
            TokenUsage.tenant_id == tenant_id,
            TokenUsage.date >= start_date,
            TokenUsage.date <= end_date,
        )
        .group_by(TokenUsage.model)
    )

    rows = result.all()

    usage_by_model = []
    total_prompt = 0
    total_completion = 0
    total_embedding = 0

    for row in rows:
        prompt = row.prompt_tokens or 0
        completion = row.completion_tokens or 0
        embedding = row.embedding_tokens or 0

        usage_by_model.append(
            UsageByModel(
                model=row.model,
                prompt_tokens=prompt,
                completion_tokens=completion,
                embedding_tokens=embedding,
                total_tokens=prompt + completion + embedding,
            )
        )

        total_prompt += prompt
        total_completion += completion
        total_embedding += embedding

    response = UsageStatsResponse(
        tenant_id=tenant_id,
        period=period,
        start_date=start_date,
        end_date=end_date,
        usage_by_model=usage_by_model,
        total_prompt_tokens=total_prompt,
        total_completion_tokens=total_completion,
        total_embedding_tokens=total_embedding,
        total_tokens=total_prompt + total_completion + total_embedding,
    )

    # Cache the result in Redis
    if redis:
        try:
            await redis.setex(cache_key, _USAGE_CACHE_TTL, response.model_dump_json())
        except Exception:
            pass  # Non-critical; DB result is still returned

    return response


@router.get(
    "/usage/{tenant_id}/quota",
    response_model=QuotaStatusResponse,
    summary="Get quota status",
    description="Get current quota status and usage for a tenant.",
)
async def get_quota_status(
    tenant_id: str,
    request: Request,
    _: AdminAuthDep = None,
    db: DbSessionDep = None,
) -> QuotaStatusResponse:
    """Get current quota status for a tenant.

    Args:
        tenant_id: The tenant identifier.
        db: Database session.

    Returns:
        Current quota configuration and usage status.
    """
    # Try Redis cache first
    redis = _get_redis(request)
    cache_key = f"admin:quota:{tenant_id}"
    if redis:
        try:
            cached = await redis.get(cache_key)
            if cached:
                return QuotaStatusResponse(**_json.loads(cached))
        except Exception:
            pass

    # Get quota configuration
    quota_result = await db.execute(select(TenantQuota).where(TenantQuota.tenant_id == tenant_id))
    quota_config = quota_result.scalar_one_or_none()

    # Get current month's usage
    today = datetime.now(UTC).date()
    first_of_month = today.replace(day=1)

    usage_result = await db.execute(
        select(
            func.coalesce(func.sum(TokenUsage.prompt_tokens), 0)
            + func.coalesce(func.sum(TokenUsage.completion_tokens), 0)
            + func.coalesce(func.sum(TokenUsage.embedding_tokens), 0)
        ).where(
            TokenUsage.tenant_id == tenant_id,
            TokenUsage.date >= first_of_month,
        )
    )
    current_usage = usage_result.scalar() or 0

    # Build response
    if quota_config is None:
        response = QuotaStatusResponse(
            tenant_id=tenant_id,
            quota_enabled=False,
            monthly_limit=None,
            current_usage=current_usage,
            remaining=None,
            usage_percent=None,
            alert_threshold_percent=80,
            is_over_limit=False,
        )
    else:
        remaining = None
        usage_percent = None
        is_over_limit = False

        if quota_config.quota_enabled and quota_config.monthly_token_limit is not None:
            remaining = max(0, quota_config.monthly_token_limit - current_usage)
            usage_percent = (current_usage / quota_config.monthly_token_limit) * 100
            is_over_limit = current_usage > quota_config.monthly_token_limit

        response = QuotaStatusResponse(
            tenant_id=tenant_id,
            quota_enabled=quota_config.quota_enabled,
            monthly_limit=quota_config.monthly_token_limit,
            current_usage=current_usage,
            remaining=remaining,
            usage_percent=round(usage_percent, 2) if usage_percent is not None else None,
            alert_threshold_percent=quota_config.alert_threshold_percent,
            is_over_limit=is_over_limit,
        )

    # Cache the result in Redis
    if redis:
        try:
            await redis.setex(cache_key, _USAGE_CACHE_TTL, response.model_dump_json())
        except Exception:
            pass

    return response


@router.put(
    "/usage/{tenant_id}/quota",
    response_model=QuotaUpdateResponse,
    summary="Set or update quota",
    description="Configure quota limits for a tenant.",
)
async def set_quota(
    tenant_id: str,
    request: QuotaUpdateRequest,
    _: AdminAuthDep = None,
    db: DbSessionDep = None,
) -> QuotaUpdateResponse:
    """Set or update quota configuration for a tenant.

    Args:
        tenant_id: The tenant identifier.
        request: Quota update request.
        db: Database session.

    Returns:
        Updated quota configuration.
    """
    # Check if quota config exists
    result = await db.execute(select(TenantQuota).where(TenantQuota.tenant_id == tenant_id))
    quota_config = result.scalar_one_or_none()

    if quota_config is None:
        # Create new quota config
        quota_config = TenantQuota(
            tenant_id=tenant_id,
            monthly_token_limit=request.monthly_token_limit,
            quota_enabled=request.quota_enabled,
            alert_threshold_percent=request.alert_threshold_percent,
        )
        db.add(quota_config)
    else:
        # Update existing config
        quota_config.monthly_token_limit = request.monthly_token_limit
        quota_config.quota_enabled = request.quota_enabled
        quota_config.alert_threshold_percent = request.alert_threshold_percent

    await db.commit()
    await db.refresh(quota_config)

    return QuotaUpdateResponse(
        tenant_id=tenant_id,
        monthly_token_limit=quota_config.monthly_token_limit,
        quota_enabled=quota_config.quota_enabled,
        alert_threshold_percent=quota_config.alert_threshold_percent,
        message="Quota updated successfully",
    )


@router.delete(
    "/usage/{tenant_id}/quota",
    summary="Delete quota configuration",
    description="Remove quota configuration for a tenant (reverts to unlimited).",
)
async def delete_quota(
    tenant_id: str,
    _: AdminAuthDep = None,
    db: DbSessionDep = None,
) -> dict:
    """Delete quota configuration for a tenant.

    Args:
        tenant_id: The tenant identifier.
        db: Database session.

    Returns:
        Confirmation message.
    """
    result = await db.execute(select(TenantQuota).where(TenantQuota.tenant_id == tenant_id))
    quota_config = result.scalar_one_or_none()

    if quota_config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No quota configuration found for tenant {tenant_id}",
        )

    await db.delete(quota_config)
    await db.commit()

    return {
        "message": f"Quota configuration deleted for tenant {tenant_id}",
        "tenant_id": tenant_id,
    }
