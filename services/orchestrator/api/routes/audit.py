"""Audit API routes for querying, exporting, and validating audit logs.

Reference: US-10.7.5 - Comprehensive Audit Logging
"""

import csv
import io
from datetime import datetime
from typing import Annotated
from uuid import UUID

from database.connection import get_db
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.security.audit import (
    AuditAction,
    AuditLogEntry,
    AuditOutcome,
    AuditQuery,
    AuditSeverity,
    AuditStats,
)
from shared.security.audit.repository import AuditRepository

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])

DbSessionDep = Annotated[AsyncSession, Depends(get_db)]

# Constants
MAX_EXPORT_DAYS = 90


# Response models
class AuditLogResponse(BaseModel):
    """Response model for audit log queries."""

    events: list[AuditLogEntry] = Field(description="List of audit log entries")
    total: int = Field(description="Total number of matching entries")
    limit: int = Field(description="Number of entries returned")
    offset: int = Field(description="Offset from start of results")


class AuditExportResponse(BaseModel):
    """Response model for audit log export."""

    total_entries: int = Field(description="Total entries exported")
    format: str = Field(description="Export format (json or csv)")
    start_time: datetime = Field(description="Start of export time range")
    end_time: datetime = Field(description="End of export time range")
    entries: list[dict] = Field(description="Exported entries")


class HashChainValidationResponse(BaseModel):
    """Response model for hash chain validation."""

    valid: bool = Field(description="Whether the hash chain is valid")
    error: str | None = Field(description="Error message if validation failed")
    entries_checked: int = Field(description="Number of entries checked")


@router.get(
    "/logs",
    response_model=AuditLogResponse,
    summary="Query audit logs",
    description="Query audit logs with various filters and pagination support.",
)
async def query_audit_logs(
    tenant_id: Annotated[UUID, Query(description="Tenant ID to filter logs")],
    db: DbSessionDep,
    start_time: Annotated[datetime | None, Query(description="Start of time range")] = None,
    end_time: Annotated[datetime | None, Query(description="End of time range")] = None,
    user_id: Annotated[UUID | None, Query(description="Filter by user ID")] = None,
    action: Annotated[AuditAction | None, Query(description="Filter by action type")] = None,
    outcome: Annotated[AuditOutcome | None, Query(description="Filter by outcome")] = None,
    severity: Annotated[AuditSeverity | None, Query(description="Filter by severity")] = None,
    resource_type: Annotated[str | None, Query(description="Filter by resource type")] = None,
    resource_id: Annotated[str | None, Query(description="Filter by resource ID")] = None,
    search_text: Annotated[str | None, Query(description="Full-text search")] = None,
    limit: Annotated[int, Query(ge=1, le=1000, description="Max results to return")] = 100,
    offset: Annotated[int, Query(ge=0, description="Offset for pagination")] = 0,
    order_by: Annotated[str, Query(description="Field to order by")] = "timestamp",
    order_desc: Annotated[bool, Query(description="Order descending")] = True,
) -> AuditLogResponse:
    """Query audit logs with filters.

    Args:
        tenant_id: Required tenant ID to filter logs.
        db: Database session.
        start_time: Optional start of time range.
        end_time: Optional end of time range.
        user_id: Optional user ID filter.
        action: Optional action type filter.
        outcome: Optional outcome filter.
        severity: Optional severity filter.
        resource_type: Optional resource type filter.
        resource_id: Optional resource ID filter.
        search_text: Optional full-text search.
        limit: Maximum number of results (1-1000).
        offset: Offset for pagination.
        order_by: Field to order by.
        order_desc: Whether to order descending.

    Returns:
        AuditLogResponse with matching events.
    """
    # Build query with filters
    actions = [action] if action else None
    outcomes = [outcome] if outcome else None
    severities = [severity] if severity else None

    query = AuditQuery(
        tenant_id=tenant_id,
        start_time=start_time,
        end_time=end_time,
        user_id=user_id,
        actions=actions,
        outcomes=outcomes,
        severities=severities,
        resource_type=resource_type,
        resource_id=resource_id,
        search_text=search_text,
        limit=limit,
        offset=offset,
        order_by=order_by,
        order_desc=order_desc,
    )

    repo = AuditRepository(db)
    entries = await repo.search(query)

    return AuditLogResponse(
        events=entries,
        total=len(entries),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/logs/{entry_id}",
    response_model=AuditLogEntry,
    summary="Get single audit log entry",
    description="Retrieve a single audit log entry by ID.",
    responses={404: {"description": "Entry not found"}},
)
async def get_audit_log_entry(
    entry_id: UUID,
    tenant_id: Annotated[UUID, Query(description="Tenant ID for authorization")],
    db: DbSessionDep,
) -> AuditLogEntry:
    """Get a single audit log entry by ID.

    Args:
        entry_id: The audit entry ID.
        tenant_id: Required tenant ID for authorization check.
        db: Database session.

    Returns:
        The audit log entry.

    Raises:
        HTTPException: If entry not found or tenant mismatch.
    """
    repo = AuditRepository(db)
    entry = await repo.get_by_id(entry_id)

    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit log entry {entry_id} not found",
        )

    # Verify tenant access
    if entry.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit log entry {entry_id} not found",
        )

    return entry


@router.get(
    "/stats",
    response_model=AuditStats,
    summary="Get audit statistics",
    description="Get aggregated statistics for audit logs.",
)
async def get_audit_stats(
    tenant_id: Annotated[UUID, Query(description="Tenant ID to filter stats")],
    db: DbSessionDep,
    start_time: Annotated[datetime | None, Query(description="Start of time range")] = None,
    end_time: Annotated[datetime | None, Query(description="End of time range")] = None,
) -> AuditStats:
    """Get audit statistics.

    Args:
        tenant_id: Required tenant ID to filter stats.
        db: Database session.
        start_time: Optional start of time range.
        end_time: Optional end of time range.

    Returns:
        AuditStats with aggregated data.
    """
    repo = AuditRepository(db)
    return await repo.get_stats(
        tenant_id=tenant_id,
        start_time=start_time,
        end_time=end_time,
    )


@router.get(
    "/export",
    summary="Export audit logs",
    description="Export audit logs in JSON or CSV format.",
    responses={
        200: {
            "description": "Export successful",
            "content": {
                "application/json": {},
                "text/csv": {},
            },
        },
        400: {"description": "Invalid request or time range too large"},
    },
)
async def export_audit_logs(
    tenant_id: Annotated[UUID, Query(description="Tenant ID to filter logs")],
    start_time: Annotated[datetime, Query(description="Start of time range")],
    end_time: Annotated[datetime, Query(description="End of time range")],
    db: DbSessionDep,
    output_format: Annotated[str, Query(description="Export format: json or csv", alias="format")] = "json",
    include_details: Annotated[bool, Query(description="Include full details field")] = False,
):
    """Export audit logs.

    Args:
        tenant_id: Required tenant ID to filter logs.
        start_time: Required start of time range.
        end_time: Required end of time range.
        db: Database session.
        output_format: Export format (json or csv). Default: json.
        include_details: Whether to include full details field.

    Returns:
        JSON response or CSV streaming response.

    Raises:
        HTTPException: If time range exceeds 90 days or invalid format.
    """
    # Validate time range
    time_diff = end_time - start_time
    if time_diff.days > MAX_EXPORT_DAYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Export time range cannot exceed {MAX_EXPORT_DAYS} days",
        )

    if output_format not in ("json", "csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Format must be 'json' or 'csv'",
        )

    # Query all entries in the time range
    query = AuditQuery(
        tenant_id=tenant_id,
        start_time=start_time,
        end_time=end_time,
        limit=1000,  # Max for export
        offset=0,
        order_by="timestamp",
        order_desc=False,
    )

    repo = AuditRepository(db)
    entries = await repo.search(query)

    if output_format == "csv":
        return _generate_csv_response(entries, include_details)

    # JSON format
    export_data = []
    for entry in entries:
        if include_details:
            export_data.append(entry.model_dump(mode="json"))
        else:
            export_data.append(entry.to_safe_dict())

    return AuditExportResponse(
        total_entries=len(entries),
        format="json",
        start_time=start_time,
        end_time=end_time,
        entries=export_data,
    )


def _generate_csv_response(entries: list[AuditLogEntry], include_details: bool) -> StreamingResponse:
    """Generate a CSV streaming response for audit entries.

    Args:
        entries: List of audit log entries.
        include_details: Whether to include details column.

    Returns:
        StreamingResponse with CSV content.
    """
    # Define CSV columns
    columns = [
        "id",
        "timestamp",
        "user_id",
        "username",
        "tenant_id",
        "action",
        "outcome",
        "severity",
        "resource_type",
        "resource_id",
        "client_ip",
        "request_method",
        "request_path",
        "status_code",
        "error_message",
        "entry_hash",
    ]

    if include_details:
        columns.append("details")

    def generate():
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=columns)

        # Write header
        writer.writeheader()
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        # Write rows
        for entry in entries:
            row = {
                "id": str(entry.id),
                "timestamp": entry.timestamp.isoformat(),
                "user_id": str(entry.user_id) if entry.user_id else "",
                "username": entry.username or "",
                "tenant_id": str(entry.tenant_id) if entry.tenant_id else "",
                "action": entry.action.value,
                "outcome": entry.outcome.value,
                "severity": entry.severity.value,
                "resource_type": entry.resource_type or "",
                "resource_id": entry.resource_id or "",
                "client_ip": entry.client_ip or "",
                "request_method": entry.request_method or "",
                "request_path": entry.request_path or "",
                "status_code": entry.status_code or "",
                "error_message": entry.error_message or "",
                "entry_hash": entry.entry_hash or "",
            }

            if include_details:
                import json
                row["details"] = json.dumps(entry.details) if entry.details else ""

            writer.writerow(row)
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=audit_logs.csv",
        },
    )


@router.get(
    "/validate-chain",
    response_model=HashChainValidationResponse,
    summary="Validate hash chain",
    description="Verify the integrity of the audit log hash chain for tamper detection.",
)
async def validate_hash_chain(
    tenant_id: Annotated[UUID, Query(description="Tenant ID for the hash chain")],
    db: DbSessionDep,
    limit: Annotated[int, Query(ge=1, le=10000, description="Max entries to validate")] = 1000,
) -> HashChainValidationResponse:
    """Validate the audit log hash chain.

    The hash chain provides tamper evidence by linking each entry to the
    previous entry via cryptographic hashes.

    Args:
        tenant_id: Required tenant ID for validation scope.
        db: Database session.
        limit: Maximum number of entries to validate (1-10000).

    Returns:
        HashChainValidationResponse with validation result.
    """
    repo = AuditRepository(db)

    # First, get entries filtered by tenant_id
    query = AuditQuery(
        tenant_id=tenant_id,
        limit=limit,
        offset=0,
        order_by="timestamp",
        order_desc=False,
    )

    entries = await repo.search(query)

    if not entries:
        return HashChainValidationResponse(
            valid=True,
            error=None,
            entries_checked=0,
        )

    # Validate the hash chain for tenant-scoped entries
    previous_hash = None
    entries_checked = 0

    for entry in entries:
        entries_checked += 1

        # Check if previous hash matches (for tenant-scoped chain)
        if entry.previous_hash != previous_hash:
            return HashChainValidationResponse(
                valid=False,
                error=f"Hash chain broken at entry {entry.id}",
                entries_checked=entries_checked,
            )

        # Verify entry hash
        computed = entry.compute_hash(previous_hash)
        if entry.entry_hash != computed:
            return HashChainValidationResponse(
                valid=False,
                error=f"Entry hash mismatch at {entry.id}",
                entries_checked=entries_checked,
            )

        previous_hash = entry.entry_hash

    return HashChainValidationResponse(
        valid=True,
        error=None,
        entries_checked=entries_checked,
    )
