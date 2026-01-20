"""Admin API routes for tenant isolation management (US-10.1.5).

Provides endpoints for managing per-tenant index/collection isolation,
including migration between shared and dedicated modes.
"""

import logging
from uuid import UUID

from api.dependencies import get_async_session
from api.routes.admin import require_admin
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter()


# Request/Response Models


class IsolationStatusResponse(BaseModel):
    """Response for tenant isolation status."""

    tenant_id: str = Field(..., description="Tenant UUID")
    isolation_mode: str = Field(..., description="Current isolation mode: shared or dedicated")
    qdrant_collection: str = Field(..., description="Active Qdrant collection name")
    opensearch_index: str = Field(..., description="Active OpenSearch index name")
    qdrant_settings: dict | None = Field(None, description="Custom Qdrant settings if any")
    opensearch_settings: dict | None = Field(None, description="Custom OpenSearch settings if any")


class MigrationRequest(BaseModel):
    """Request body for migration operations."""

    qdrant_settings: dict | None = Field(
        None,
        description="Custom HNSW/optimizer settings for the new Qdrant collection",
    )
    opensearch_settings: dict | None = Field(
        None,
        description="Custom settings for the new OpenSearch index",
    )


class MigrationResponse(BaseModel):
    """Response for migration operations."""

    tenant_id: str
    dry_run: bool
    status: str
    message: str
    stats: dict | None = None


class MigrationProgressResponse(BaseModel):
    """Response for migration progress."""

    tenant_id: str
    phase: str
    total_vectors: int
    migrated_vectors: int
    total_documents: int
    migrated_documents: int
    started_at: str | None
    completed_at: str | None
    error: str | None = None


class RollbackResponse(BaseModel):
    """Response for rollback operation."""

    tenant_id: str
    status: str
    message: str
    previous_mode: str
    new_mode: str


class CleanupRequest(BaseModel):
    """Request body for cleanup operations."""

    delete_collection: bool = Field(True, description="Delete Qdrant collection")
    delete_index: bool = Field(True, description="Delete OpenSearch index")


class CleanupResponse(BaseModel):
    """Response for cleanup operation."""

    tenant_id: str
    status: str
    deleted: dict


class TenantStatsResponse(BaseModel):
    """Response for tenant statistics."""

    tenant_id: str
    shared_vectors: int
    shared_documents: int
    dedicated_vectors: int | None = None
    dedicated_documents: int | None = None


# Helper function to get tenant


async def get_tenant_or_404(tenant_id: str, session: AsyncSession):
    """Load tenant from database or raise 404."""
    from sqlalchemy import select

    from shared.database.models import Tenant

    try:
        tenant_uuid = UUID(tenant_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid tenant ID format: {tenant_id}",
        ) from e

    result = await session.execute(select(Tenant).where(Tenant.id == tenant_uuid))
    tenant = result.scalar_one_or_none()

    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant not found: {tenant_id}",
        )

    return tenant


# Endpoints


@router.get(
    "/tenants/{tenant_id}/isolation-status",
    response_model=IsolationStatusResponse,
    summary="Get tenant isolation status",
    description="Get the current isolation configuration for a tenant.",
)
async def get_isolation_status(
    tenant_id: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(require_admin),
) -> IsolationStatusResponse:
    """Get current isolation configuration for a tenant.

    Args:
        tenant_id: Tenant UUID.
        session: Database session.
        current_user: Authenticated admin user.

    Returns:
        Current isolation configuration.
    """
    tenant = await get_tenant_or_404(tenant_id, session)

    logger.info(
        "Admin queried isolation status",
        extra={
            "admin_user_id": current_user.get("user_id"),
            "tenant_id": tenant_id,
            "isolation_mode": tenant.isolation_mode,
        },
    )

    return IsolationStatusResponse(
        tenant_id=str(tenant.id),
        isolation_mode=tenant.isolation_mode,
        qdrant_collection=tenant.get_qdrant_collection(),
        opensearch_index=tenant.get_opensearch_index(),
        qdrant_settings=tenant.qdrant_settings,
        opensearch_settings=tenant.opensearch_settings,
    )


@router.post(
    "/tenants/{tenant_id}/migrate-to-dedicated",
    response_model=MigrationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Migrate tenant to dedicated indices",
    description="""
    Migrate a tenant from shared to dedicated Qdrant collection and OpenSearch index.

    **Requires admin privileges.**

    The migration process:
    1. Creates dedicated collection/index for the tenant
    2. Copies all tenant data from shared to dedicated stores
    3. Updates tenant configuration to use dedicated mode
    4. Data remains in shared stores for safety (use cleanup endpoint to remove)

    **Safety:** Default is `dry_run=True` which calculates migration scope without making changes.
    Set `dry_run=False` to actually perform the migration.
    """,
)
async def migrate_to_dedicated(
    tenant_id: str,
    dry_run: bool = Query(True, description="If True, report scope without migrating"),
    request: MigrationRequest | None = None,
    session: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(require_admin),
) -> MigrationResponse:
    """Migrate tenant to dedicated indices.

    Args:
        tenant_id: Tenant UUID.
        dry_run: If True, only calculate migration scope.
        request: Optional custom settings for new indices.
        session: Database session.
        current_user: Authenticated admin user.

    Returns:
        Migration status and statistics.
    """
    from tools.migrate_tenant import TenantMigrationTool

    tenant = await get_tenant_or_404(tenant_id, session)

    if tenant.isolation_mode == "dedicated" and not dry_run:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant is already using dedicated indices",
        )

    logger.info(
        "Admin initiated tenant migration",
        extra={
            "admin_user_id": current_user.get("user_id"),
            "tenant_id": tenant_id,
            "dry_run": dry_run,
        },
    )

    # Get settings from config
    from config import get_settings

    settings = get_settings()

    tool = TenantMigrationTool(
        qdrant_url=settings.qdrant_url,
        opensearch_url=settings.opensearch_url,
        session_factory=lambda: session,
    )

    try:
        await tool.connect()

        qdrant_settings = request.qdrant_settings if request else None
        opensearch_settings = request.opensearch_settings if request else None

        result = await tool.migrate_to_dedicated(
            tenant_id=UUID(tenant_id),
            dry_run=dry_run,
            qdrant_settings=qdrant_settings,
            opensearch_settings=opensearch_settings,
        )

        return MigrationResponse(
            tenant_id=tenant_id,
            dry_run=dry_run,
            status="success" if result.success else "failed",
            message=result.message,
            stats={
                "vectors_migrated": result.vectors_migrated,
                "documents_migrated": result.documents_migrated,
                "errors": result.errors,
            },
        )

    finally:
        await tool.close()


@router.get(
    "/tenants/{tenant_id}/migration-status",
    response_model=MigrationProgressResponse,
    summary="Get migration progress",
    description="Check the progress of an ongoing migration.",
)
async def get_migration_status(
    tenant_id: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(require_admin),
) -> MigrationProgressResponse:
    """Get progress of an ongoing migration.

    Args:
        tenant_id: Tenant UUID.
        session: Database session.
        current_user: Authenticated admin user.

    Returns:
        Migration progress information.
    """
    from tools.migrate_tenant import TenantMigrationTool

    # Verify tenant exists
    await get_tenant_or_404(tenant_id, session)

    from config import get_settings

    settings = get_settings()

    tool = TenantMigrationTool(
        qdrant_url=settings.qdrant_url,
        opensearch_url=settings.opensearch_url,
        session_factory=lambda: session,
    )

    progress = tool.get_progress(UUID(tenant_id))

    if progress is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No migration in progress for tenant: {tenant_id}",
        )

    return MigrationProgressResponse(
        tenant_id=tenant_id,
        phase=progress.phase,
        total_vectors=progress.total_vectors,
        migrated_vectors=progress.migrated_vectors,
        total_documents=progress.total_documents,
        migrated_documents=progress.migrated_documents,
        started_at=progress.started_at.isoformat() if progress.started_at else None,
        completed_at=progress.completed_at.isoformat() if progress.completed_at else None,
        error=progress.error,
    )


@router.post(
    "/tenants/{tenant_id}/rollback-to-shared",
    response_model=RollbackResponse,
    summary="Rollback tenant to shared indices",
    description="""
    Rollback a tenant from dedicated to shared mode.

    **Requires admin privileges.**

    This operation:
    1. Updates tenant configuration to use shared indices
    2. Does NOT delete dedicated collection/index (use cleanup endpoint)
    3. Does NOT move data from dedicated back to shared

    **Note:** Data must already exist in shared indices for tenant to function
    after rollback. Use this for emergency rollback or when shared data was
    never deleted.
    """,
)
async def rollback_to_shared(
    tenant_id: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(require_admin),
) -> RollbackResponse:
    """Rollback tenant to shared indices.

    Args:
        tenant_id: Tenant UUID.
        session: Database session.
        current_user: Authenticated admin user.

    Returns:
        Rollback status.
    """
    from tools.migrate_tenant import TenantMigrationTool

    tenant = await get_tenant_or_404(tenant_id, session)

    if tenant.isolation_mode == "shared":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant is already using shared indices",
        )

    logger.info(
        "Admin initiated tenant rollback",
        extra={
            "admin_user_id": current_user.get("user_id"),
            "tenant_id": tenant_id,
        },
    )

    from config import get_settings

    settings = get_settings()

    tool = TenantMigrationTool(
        qdrant_url=settings.qdrant_url,
        opensearch_url=settings.opensearch_url,
        session_factory=lambda: session,
    )

    try:
        await tool.connect()
        success = await tool.rollback_to_shared(UUID(tenant_id))

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Rollback failed - check logs for details",
            )

        return RollbackResponse(
            tenant_id=tenant_id,
            status="success",
            message="Tenant rolled back to shared indices",
            previous_mode="dedicated",
            new_mode="shared",
        )

    finally:
        await tool.close()


@router.delete(
    "/tenants/{tenant_id}/dedicated-data",
    response_model=CleanupResponse,
    summary="Cleanup dedicated tenant data",
    description="""
    Delete dedicated Qdrant collection and/or OpenSearch index for a tenant.

    **Requires admin privileges.**

    **WARNING:** This permanently deletes data. Only use after:
    - Successfully migrating back to shared indices, OR
    - Confirming the data is no longer needed

    Use request body to control what gets deleted.
    """,
)
async def cleanup_dedicated_data(
    tenant_id: str,
    request: CleanupRequest | None = None,
    session: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(require_admin),
) -> CleanupResponse:
    """Cleanup dedicated indices for a tenant.

    Args:
        tenant_id: Tenant UUID.
        request: Control what to delete.
        session: Database session.
        current_user: Authenticated admin user.

    Returns:
        Cleanup status.
    """
    from tools.migrate_tenant import TenantMigrationTool

    # Verify tenant exists
    await get_tenant_or_404(tenant_id, session)

    delete_collection = request.delete_collection if request else True
    delete_index = request.delete_index if request else True

    logger.warning(
        "Admin initiated dedicated data cleanup",
        extra={
            "admin_user_id": current_user.get("user_id"),
            "tenant_id": tenant_id,
            "delete_collection": delete_collection,
            "delete_index": delete_index,
        },
    )

    from config import get_settings

    settings = get_settings()

    tool = TenantMigrationTool(
        qdrant_url=settings.qdrant_url,
        opensearch_url=settings.opensearch_url,
        session_factory=lambda: session,
    )

    try:
        await tool.connect()
        result = await tool.cleanup_dedicated_data(
            tenant_id=UUID(tenant_id),
            delete_collection=delete_collection,
            delete_index=delete_index,
        )

        return CleanupResponse(
            tenant_id=tenant_id,
            status="success",
            deleted=result,
        )

    finally:
        await tool.close()


@router.get(
    "/tenants/{tenant_id}/stats",
    response_model=TenantStatsResponse,
    summary="Get tenant data statistics",
    description="Get statistics about tenant data in shared and dedicated stores.",
)
async def get_tenant_stats(
    tenant_id: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(require_admin),
) -> TenantStatsResponse:
    """Get statistics about tenant data distribution.

    Args:
        tenant_id: Tenant UUID.
        session: Database session.
        current_user: Authenticated admin user.

    Returns:
        Statistics about tenant data.
    """
    from tools.migrate_tenant import TenantMigrationTool

    # Verify tenant exists
    await get_tenant_or_404(tenant_id, session)

    from config import get_settings

    settings = get_settings()

    tool = TenantMigrationTool(
        qdrant_url=settings.qdrant_url,
        opensearch_url=settings.opensearch_url,
        session_factory=lambda: session,
    )

    try:
        await tool.connect()
        stats = await tool.get_tenant_stats(UUID(tenant_id))

        return TenantStatsResponse(
            tenant_id=tenant_id,
            shared_vectors=stats.get("shared_vectors", 0),
            shared_documents=stats.get("shared_documents", 0),
            dedicated_vectors=stats.get("dedicated_vectors"),
            dedicated_documents=stats.get("dedicated_documents"),
        )

    finally:
        await tool.close()
