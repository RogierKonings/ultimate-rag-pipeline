"""Admin API routes for maintenance operations (US-10.1.2).

These endpoints require admin privileges and provide access to
maintenance operations like index reconciliation.
"""

import logging

from api.dependencies import get_current_user
from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

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
