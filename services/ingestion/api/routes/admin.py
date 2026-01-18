"""Admin API routes for maintenance operations (US-10.1.2, US-10.2.3).

These endpoints require admin privileges and provide access to
maintenance operations like index reconciliation and rate limiting.
"""

import logging
from typing import Literal

from api.dependencies import get_current_user, get_rate_limiter
from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from rate_limiting.limiter import IngestionRateLimiter
from rate_limiting.models import TenantLimits

logger = logging.getLogger(__name__)

router = APIRouter()


class ReconcileRequest(BaseModel):
    """Request body for triggering reconciliation."""

    tenant_id: str = Field(..., description="Tenant ID to reconcile")
    document_id: str | None = Field(
        None, description="Specific document ID (optional, reconciles all if not provided)"
    )
    dry_run: bool = Field(
        True, description="If True, report issues without making changes (default: True for safety)"
    )


class ReconcileResponse(BaseModel):
    """Response from triggering reconciliation."""

    job_id: str = Field(..., description="Celery task ID for tracking")
    status: str = Field(..., description="Initial job status")
    message: str = Field(..., description="Human-readable message")


class ReconcileStatusResponse(BaseModel):
    """Response for reconciliation job status."""

    job_id: str
    status: str
    result: dict | None = None
    error: str | None = None


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Dependency that requires admin role.

    Args:
        current_user: Current authenticated user from get_current_user.

    Returns:
        The user dict if admin.

    Raises:
        HTTPException: If user is not an admin.
    """
    # Check if user has admin role
    roles = current_user.get("roles", [])
    is_admin = "admin" in roles or current_user.get("is_admin", False)

    if not is_admin:
        logger.warning(
            "Non-admin user attempted admin action",
            extra={"user_id": current_user.get("user_id")},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )

    return current_user


@router.post(
    "/reconcile",
    response_model=ReconcileResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger index reconciliation",
    description="""
    Trigger reconciliation between PostgreSQL and external stores (Qdrant, OpenSearch).

    **Requires admin privileges.**

    The reconciliation process:
    1. Finds chunks in PostgreSQL missing from Qdrant/OpenSearch and re-indexes them
    2. Finds orphaned entries in Qdrant/OpenSearch and removes them
    3. Updates document status fields

    **Safety:** Default is `dry_run=True` which reports issues without making changes.
    Set `dry_run=False` to actually repair issues.
    """,
)
async def trigger_reconciliation(
    request: ReconcileRequest,
    current_user: dict = Depends(require_admin),
) -> ReconcileResponse:
    """Trigger index reconciliation for a tenant.

    Args:
        request: Reconciliation request parameters.
        current_user: Authenticated admin user.

    Returns:
        Response with job ID for tracking.
    """
    from tasks.reconcile import reconcile_index

    logger.info(
        "Admin triggered reconciliation",
        extra={
            "admin_user_id": current_user.get("user_id"),
            "tenant_id": request.tenant_id,
            "document_id": request.document_id,
            "dry_run": request.dry_run,
        },
    )

    # Queue the reconciliation task
    task = reconcile_index.delay(
        tenant_id=request.tenant_id,
        document_id=request.document_id,
        dry_run=request.dry_run,
    )

    action = "dry-run " if request.dry_run else ""
    scope = f"document {request.document_id}" if request.document_id else "all documents"

    return ReconcileResponse(
        job_id=task.id,
        status="queued",
        message=f"Reconciliation {action}queued for tenant {request.tenant_id} ({scope})",
    )


@router.get(
    "/reconcile/{job_id}",
    response_model=ReconcileStatusResponse,
    summary="Get reconciliation job status",
    description="Get the status and result of a reconciliation job.",
)
async def get_reconciliation_status(
    job_id: str,
    current_user: dict = Depends(require_admin),
) -> ReconcileStatusResponse:
    """Get status of a reconciliation job.

    Args:
        job_id: Celery task ID.
        current_user: Authenticated admin user.

    Returns:
        Job status and result if completed.
    """
    result = AsyncResult(job_id)

    if result.state == "PENDING":
        return ReconcileStatusResponse(
            job_id=job_id,
            status="pending",
        )
    if result.state == "STARTED":
        return ReconcileStatusResponse(
            job_id=job_id,
            status="running",
        )
    if result.state == "SUCCESS":
        return ReconcileStatusResponse(
            job_id=job_id,
            status="completed",
            result=result.result,
        )
    if result.state == "FAILURE":
        return ReconcileStatusResponse(
            job_id=job_id,
            status="failed",
            error=str(result.result) if result.result else "Unknown error",
        )
    return ReconcileStatusResponse(
        job_id=job_id,
        status=result.state.lower(),
    )


@router.get(
    "/reconcile",
    response_model=list[ReconcileStatusResponse],
    summary="List recent reconciliation jobs",
    description="List recent reconciliation jobs for monitoring.",
)
async def list_reconciliation_jobs(
    tenant_id: str | None = None,
    limit: int = 10,
    current_user: dict = Depends(require_admin),
) -> list[ReconcileStatusResponse]:
    """List recent reconciliation jobs.

    Note: This is a simplified implementation that doesn't persist job history.
    In production, you'd want to store job metadata in a database.

    Args:
        tenant_id: Optional filter by tenant.
        limit: Maximum number of jobs to return.
        current_user: Authenticated admin user.

    Returns:
        List of recent job statuses.
    """
    # This is a placeholder - in production you'd query a job history table
    # For now, return empty list since we don't have persistent job tracking
    logger.info(
        "Admin listed reconciliation jobs",
        extra={
            "admin_user_id": current_user.get("user_id"),
            "tenant_id": tenant_id,
            "limit": limit,
        },
    )

    return []


# =============================================================================
# Rate Limiting Endpoints (US-10.2.3)
# =============================================================================


class TenantLimitsRequest(BaseModel):
    """Request body for updating tenant rate limits."""

    max_concurrent_jobs: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum concurrent ingestion jobs allowed",
    )
    priority: Literal["high", "normal", "low"] = Field(
        default="normal",
        description="Priority level for this tenant's jobs",
    )
    hard_limit: bool = Field(
        default=False,
        description="If True, reject jobs exceeding limit. If False, queue them.",
    )


class TenantJobStats(BaseModel):
    """Statistics about a tenant's ingestion jobs."""

    tenant_id: str = Field(..., description="Tenant ID")
    active_jobs: int = Field(..., description="Number of currently active jobs")
    queued_jobs: int = Field(..., description="Number of jobs waiting in queue")
    max_concurrent: int = Field(..., description="Maximum concurrent jobs allowed")
    priority: str = Field(..., description="Priority level")
    hard_limit: bool = Field(..., description="Whether hard limit is enabled")


class RateLimitsOverview(BaseModel):
    """Overview of all tenant rate limits."""

    total_active_tenants: int = Field(..., description="Number of tenants with active jobs")
    tenants: list[TenantJobStats] = Field(..., description="Per-tenant statistics")


class ClearQueueResponse(BaseModel):
    """Response from clearing a tenant's queue."""

    status: str = Field(..., description="Operation status")
    jobs_removed: int = Field(..., description="Number of jobs removed from queue")


@router.get(
    "/tenants/{tenant_id}/rate-limits",
    response_model=TenantJobStats,
    summary="Get tenant rate limits",
    description="Get rate limit configuration and current job counts for a tenant.",
)
async def get_tenant_rate_limits(
    tenant_id: str,
    current_user: dict = Depends(require_admin),
    rate_limiter: IngestionRateLimiter = Depends(get_rate_limiter),
) -> TenantJobStats:
    """Get rate limit configuration and job counts for a tenant.

    Args:
        tenant_id: The tenant ID.
        current_user: Authenticated admin user.
        rate_limiter: Rate limiter instance.

    Returns:
        Tenant job statistics.
    """
    limits = await rate_limiter.get_tenant_limits(tenant_id)
    active = await rate_limiter.get_active_count(tenant_id)
    queued = await rate_limiter.get_queued_count(tenant_id)

    return TenantJobStats(
        tenant_id=tenant_id,
        active_jobs=active,
        queued_jobs=queued,
        max_concurrent=limits.max_concurrent_jobs,
        priority=limits.priority,
        hard_limit=limits.hard_limit,
    )


@router.put(
    "/tenants/{tenant_id}/rate-limits",
    response_model=TenantJobStats,
    summary="Update tenant rate limits",
    description="Update rate limit configuration for a tenant.",
)
async def update_tenant_rate_limits(
    tenant_id: str,
    request: TenantLimitsRequest,
    current_user: dict = Depends(require_admin),
    rate_limiter: IngestionRateLimiter = Depends(get_rate_limiter),
) -> TenantJobStats:
    """Update rate limit configuration for a tenant.

    Args:
        tenant_id: The tenant ID.
        request: New limit configuration.
        current_user: Authenticated admin user.
        rate_limiter: Rate limiter instance.

    Returns:
        Updated tenant job statistics.
    """
    limits = TenantLimits(
        max_concurrent_jobs=request.max_concurrent_jobs,
        priority=request.priority,
        hard_limit=request.hard_limit,
    )
    await rate_limiter.set_tenant_limits(tenant_id, limits)

    logger.info(
        "Admin updated tenant rate limits",
        extra={
            "admin_user_id": current_user.get("user_id"),
            "tenant_id": tenant_id,
            "max_concurrent": limits.max_concurrent_jobs,
            "priority": limits.priority,
            "hard_limit": limits.hard_limit,
        },
    )

    active = await rate_limiter.get_active_count(tenant_id)
    queued = await rate_limiter.get_queued_count(tenant_id)

    return TenantJobStats(
        tenant_id=tenant_id,
        active_jobs=active,
        queued_jobs=queued,
        max_concurrent=limits.max_concurrent_jobs,
        priority=limits.priority,
        hard_limit=limits.hard_limit,
    )


@router.delete(
    "/tenants/{tenant_id}/rate-limits",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reset tenant rate limits",
    description="Reset tenant rate limits to defaults.",
)
async def reset_tenant_rate_limits(
    tenant_id: str,
    current_user: dict = Depends(require_admin),
    rate_limiter: IngestionRateLimiter = Depends(get_rate_limiter),
) -> None:
    """Reset tenant rate limits to defaults.

    Args:
        tenant_id: The tenant ID.
        current_user: Authenticated admin user.
        rate_limiter: Rate limiter instance.
    """
    await rate_limiter.delete_tenant_limits(tenant_id)

    logger.info(
        "Admin reset tenant rate limits to defaults",
        extra={
            "admin_user_id": current_user.get("user_id"),
            "tenant_id": tenant_id,
        },
    )


@router.get(
    "/rate-limits/overview",
    response_model=RateLimitsOverview,
    summary="Get rate limits overview",
    description="Get overview of all tenants with active jobs.",
)
async def get_rate_limits_overview(
    current_user: dict = Depends(require_admin),
    rate_limiter: IngestionRateLimiter = Depends(get_rate_limiter),
) -> RateLimitsOverview:
    """Get overview of all tenant job activity.

    Args:
        current_user: Authenticated admin user.
        rate_limiter: Rate limiter instance.

    Returns:
        Overview with all active tenants.
    """
    tenant_ids = await rate_limiter.get_all_active_tenants()

    tenants = []
    for tenant_id in tenant_ids:
        limits = await rate_limiter.get_tenant_limits(tenant_id)
        active = await rate_limiter.get_active_count(tenant_id)
        queued = await rate_limiter.get_queued_count(tenant_id)

        tenants.append(
            TenantJobStats(
                tenant_id=tenant_id,
                active_jobs=active,
                queued_jobs=queued,
                max_concurrent=limits.max_concurrent_jobs,
                priority=limits.priority,
                hard_limit=limits.hard_limit,
            )
        )

    return RateLimitsOverview(
        total_active_tenants=len(tenants),
        tenants=tenants,
    )


@router.post(
    "/tenants/{tenant_id}/clear-queue",
    response_model=ClearQueueResponse,
    summary="Clear tenant queue",
    description="Clear all queued jobs for a tenant. Use for emergency situations only.",
)
async def clear_tenant_queue(
    tenant_id: str,
    current_user: dict = Depends(require_admin),
    rate_limiter: IngestionRateLimiter = Depends(get_rate_limiter),
) -> ClearQueueResponse:
    """Clear all queued jobs for a tenant.

    This is an emergency operation that removes all waiting jobs.
    Jobs will not be processed and are not recoverable.

    Args:
        tenant_id: The tenant ID.
        current_user: Authenticated admin user.
        rate_limiter: Rate limiter instance.

    Returns:
        Response with number of jobs removed.
    """
    count = await rate_limiter.clear_queue(tenant_id)

    logger.warning(
        "Admin cleared tenant queue",
        extra={
            "admin_user_id": current_user.get("user_id"),
            "tenant_id": tenant_id,
            "jobs_cleared": count,
        },
    )

    return ClearQueueResponse(
        status="cleared",
        jobs_removed=count,
    )
