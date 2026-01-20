"""Admin API routes for tenant PII configuration (US-10.7.4).

Provides endpoints for managing per-tenant PII detection settings,
custom patterns, and testing PII detection.
"""

import logging
import re
from uuid import UUID

from api.dependencies import get_async_session
from api.routes.admin import require_admin
from api.schemas.pii import (
    AddCustomPatternRequest,
    CustomPatternResponse,
    IngestionPIIConfig,
    PIIEntityConfigSchema,
    PIIEntityDetected,
    PIITestRequest,
    PIITestResponse,
    QueryPIIConfig,
    ResponsePIIConfig,
    TenantPIISettingsResponse,
    TenantPIISettingsUpdate,
)
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from shared.security.pii import (
    PIIHandlingMode,
    get_tenant_pii_config_service,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# Helper functions


async def get_tenant_or_404(tenant_id: str, session: AsyncSession):
    """Load tenant from database or raise 404."""
    from database.models import Tenant
    from sqlalchemy import select

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


def validate_handling_mode(mode: str | None) -> None:
    """Validate handling mode value."""
    if mode is not None:
        valid_modes = {m.value for m in PIIHandlingMode}
        if mode not in valid_modes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid handling_mode '{mode}'. Must be one of: {', '.join(valid_modes)}",
            )


def validate_regex_pattern(pattern: str) -> None:
    """Validate that a string is a valid regex pattern."""
    try:
        re.compile(pattern)
    except re.error as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid regex pattern: {e}",
        ) from e


def config_to_response(tenant_id: str, config: dict) -> TenantPIISettingsResponse:
    """Convert raw config dict to response model."""
    return TenantPIISettingsResponse(
        tenant_id=tenant_id,
        enabled=config.get("enabled", True),
        default_handling_mode=config.get("default_handling_mode", "flag"),
        confidence_threshold=config.get("confidence_threshold", 0.7),
        ingestion=IngestionPIIConfig(**config.get("ingestion", {})),
        query=QueryPIIConfig(**config.get("query", {})),
        response=ResponsePIIConfig(**config.get("response", {})),
        entity_configs={
            k: PIIEntityConfigSchema(**v)
            for k, v in config.get("entity_configs", {}).items()
        },
        custom_patterns=config.get("custom_patterns", []),
    )


# Endpoints


@router.get(
    "/tenants/{tenant_id}/pii-settings",
    response_model=TenantPIISettingsResponse,
    summary="Get tenant PII settings",
    description="Get the current PII configuration for a tenant.",
)
async def get_pii_settings(
    tenant_id: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(require_admin),
) -> TenantPIISettingsResponse:
    """Get current PII configuration for a tenant.

    Args:
        tenant_id: Tenant UUID.
        session: Database session.
        current_user: Authenticated admin user.

    Returns:
        Current PII configuration merged with defaults.
    """
    await get_tenant_or_404(tenant_id, session)

    service = get_tenant_pii_config_service()
    config = await service.get_raw_config(UUID(tenant_id), session)

    logger.info(
        "Admin retrieved PII settings",
        extra={
            "admin_user_id": current_user.get("sub"),
            "tenant_id": tenant_id,
        },
    )

    return config_to_response(tenant_id, config)


@router.put(
    "/tenants/{tenant_id}/pii-settings",
    response_model=TenantPIISettingsResponse,
    summary="Replace tenant PII settings",
    description="Replace the entire PII configuration for a tenant.",
)
async def replace_pii_settings(
    tenant_id: str,
    settings: TenantPIISettingsUpdate,
    session: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(require_admin),
) -> TenantPIISettingsResponse:
    """Replace entire PII configuration for a tenant.

    Args:
        tenant_id: Tenant UUID.
        settings: New PII configuration.
        session: Database session.
        current_user: Authenticated admin user.

    Returns:
        Updated PII configuration.
    """
    await get_tenant_or_404(tenant_id, session)

    # Validate handling modes
    validate_handling_mode(settings.default_handling_mode)
    if settings.ingestion:
        validate_handling_mode(settings.ingestion.handling_mode)
    if settings.query:
        validate_handling_mode(settings.query.handling_mode)
    if settings.response:
        validate_handling_mode(settings.response.handling_mode)

    # Build update dict (only include provided fields)
    updates = settings.model_dump(exclude_unset=True)

    service = get_tenant_pii_config_service()
    config = await service.update_tenant_config(
        UUID(tenant_id),
        session,
        updates,
        merge=False,  # PUT replaces entirely
    )

    await session.commit()

    logger.info(
        "Admin replaced PII settings",
        extra={
            "admin_user_id": current_user.get("sub"),
            "tenant_id": tenant_id,
        },
    )

    return config_to_response(tenant_id, config)


@router.patch(
    "/tenants/{tenant_id}/pii-settings",
    response_model=TenantPIISettingsResponse,
    summary="Update tenant PII settings",
    description="Partially update the PII configuration for a tenant (merge with existing).",
)
async def update_pii_settings(
    tenant_id: str,
    settings: TenantPIISettingsUpdate,
    session: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(require_admin),
) -> TenantPIISettingsResponse:
    """Partially update PII configuration for a tenant.

    Only provided fields will be updated; others remain unchanged.

    Args:
        tenant_id: Tenant UUID.
        settings: PII configuration updates.
        session: Database session.
        current_user: Authenticated admin user.

    Returns:
        Updated PII configuration.
    """
    await get_tenant_or_404(tenant_id, session)

    # Validate handling modes
    validate_handling_mode(settings.default_handling_mode)
    if settings.ingestion:
        validate_handling_mode(settings.ingestion.handling_mode)
    if settings.query:
        validate_handling_mode(settings.query.handling_mode)
    if settings.response:
        validate_handling_mode(settings.response.handling_mode)

    # Build update dict (only include provided fields)
    updates = settings.model_dump(exclude_unset=True)

    service = get_tenant_pii_config_service()
    config = await service.update_tenant_config(
        UUID(tenant_id),
        session,
        updates,
        merge=True,  # PATCH merges with existing
    )

    await session.commit()

    logger.info(
        "Admin updated PII settings",
        extra={
            "admin_user_id": current_user.get("sub"),
            "tenant_id": tenant_id,
            "updated_fields": list(updates.keys()),
        },
    )

    return config_to_response(tenant_id, config)


@router.post(
    "/tenants/{tenant_id}/pii-settings/custom-patterns",
    response_model=CustomPatternResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add custom PII pattern",
    description="Add a custom regex pattern for tenant-specific PII detection.",
)
async def add_custom_pattern(
    tenant_id: str,
    request: AddCustomPatternRequest,
    session: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(require_admin),
) -> CustomPatternResponse:
    """Add a custom PII pattern for a tenant.

    Args:
        tenant_id: Tenant UUID.
        request: Pattern details.
        session: Database session.
        current_user: Authenticated admin user.

    Returns:
        Confirmation with updated pattern count.
    """
    await get_tenant_or_404(tenant_id, session)

    # Validate regex pattern
    validate_regex_pattern(request.pattern)

    service = get_tenant_pii_config_service()

    try:
        config = await service.add_custom_pattern(
            UUID(tenant_id),
            session,
            name=request.name,
            pattern=request.pattern,
            entity_type=request.entity_type,
            score=request.score,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e

    await session.commit()

    logger.info(
        "Admin added custom PII pattern",
        extra={
            "admin_user_id": current_user.get("sub"),
            "tenant_id": tenant_id,
            "pattern_name": request.name,
            "entity_type": request.entity_type,
        },
    )

    return CustomPatternResponse(
        tenant_id=tenant_id,
        action="added",
        pattern_name=request.name,
        total_patterns=len(config.get("custom_patterns", [])),
    )


@router.delete(
    "/tenants/{tenant_id}/pii-settings/custom-patterns/{pattern_name}",
    response_model=CustomPatternResponse,
    summary="Remove custom PII pattern",
    description="Remove a custom regex pattern from tenant configuration.",
)
async def remove_custom_pattern(
    tenant_id: str,
    pattern_name: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(require_admin),
) -> CustomPatternResponse:
    """Remove a custom PII pattern for a tenant.

    Args:
        tenant_id: Tenant UUID.
        pattern_name: Name of pattern to remove.
        session: Database session.
        current_user: Authenticated admin user.

    Returns:
        Confirmation with updated pattern count.
    """
    await get_tenant_or_404(tenant_id, session)

    service = get_tenant_pii_config_service()

    try:
        config = await service.remove_custom_pattern(
            UUID(tenant_id),
            session,
            pattern_name,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e

    await session.commit()

    logger.info(
        "Admin removed custom PII pattern",
        extra={
            "admin_user_id": current_user.get("sub"),
            "tenant_id": tenant_id,
            "pattern_name": pattern_name,
        },
    )

    return CustomPatternResponse(
        tenant_id=tenant_id,
        action="removed",
        pattern_name=pattern_name,
        total_patterns=len(config.get("custom_patterns", [])),
    )


@router.post(
    "/tenants/{tenant_id}/pii-settings/test",
    response_model=PIITestResponse,
    summary="Test PII detection",
    description="Test PII detection on sample text using tenant's configuration.",
)
async def test_pii_detection(
    tenant_id: str,
    request: PIITestRequest,
    session: AsyncSession = Depends(get_async_session),  # noqa: PT028
    current_user: dict = Depends(require_admin),  # noqa: PT028
) -> PIITestResponse:
    """Test PII detection on sample text.

    Useful for validating configuration before saving.

    Args:
        tenant_id: Tenant UUID.
        request: Text to test and optional handling mode.
        session: Database session.
        current_user: Authenticated admin user.

    Returns:
        Detection results including redacted preview.
    """
    await get_tenant_or_404(tenant_id, session)

    # Validate handling mode if provided
    validate_handling_mode(request.handling_mode)

    service = get_tenant_pii_config_service()
    detector = await service.get_detector(UUID(tenant_id), session)

    # Detect PII
    result = await detector.detect(request.text)

    # Get handling mode
    handling_mode = PIIHandlingMode.REDACT  # Default for test
    if request.handling_mode:
        handling_mode = PIIHandlingMode(request.handling_mode)

    # Generate redacted preview
    if handling_mode == PIIHandlingMode.REDACT:
        redacted_text = await detector.redact(request.text)
    elif handling_mode == PIIHandlingMode.MASK:
        redacted_text = await detector.mask(request.text)
    else:
        redacted_text = request.text

    # Build response (don't include actual PII text)
    entities = [
        PIIEntityDetected(
            entity_type=e.entity_type,
            start=e.start,
            end=e.end,
            score=e.score,
            length=len(e.text),
        )
        for e in result.entities
    ]

    logger.info(
        "Admin tested PII detection",
        extra={
            "admin_user_id": current_user.get("sub"),
            "tenant_id": tenant_id,
            "text_length": len(request.text),
            "pii_found": result.has_pii,
            "entity_count": len(result.entities),
        },
    )

    return PIITestResponse(
        has_pii=result.has_pii,
        entity_counts=result.entity_counts,
        entities=entities,
        redacted_text=redacted_text,
        processing_time_ms=result.processing_time_ms,
    )
