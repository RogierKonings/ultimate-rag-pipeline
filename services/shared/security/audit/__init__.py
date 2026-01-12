"""
Audit logging module.

This module provides comprehensive audit logging for security-relevant
events including authentication, authorization, data access, and
administrative actions.

Features:
- Structured JSON logging for log aggregation
- Hash chaining for tamper evidence
- Database persistence with efficient querying
- FastAPI middleware for automatic request logging
- Convenience methods for common audit events

Example:
    ```python
    from services.shared.security.audit import (
        AuditLogger,
        AuditAction,
        AuditMiddleware,
        get_audit_logger,
    )

    # Get global logger
    logger = get_audit_logger("my-service")

    # Log events
    await logger.log_login(
        user_id=user_id,
        username="john@example.com",
        success=True,
        client_ip="192.168.1.1",
    )

    await logger.log_document_access(
        user_id=user_id,
        document_id=doc_id,
        action=AuditAction.DOCUMENT_READ,
    )

    await logger.log_access_denied(
        user_id=user_id,
        resource_type="document",
        resource_id=str(doc_id),
        action=AuditAction.DOCUMENT_READ,
        reason="Insufficient permissions",
    )

    # Use middleware for automatic logging
    from fastapi import FastAPI

    app = FastAPI()
    app.add_middleware(
        AuditMiddleware,
        service_name="ingestion-service",
        exclude_paths=["/health", "/metrics"],
    )
    ```
"""

from .logger import (
    AuditLogger,
    AuditLogHandler,
    get_audit_logger,
    set_audit_logger,
)
from .middleware import (
    AuditMiddleware,
    create_audit_middleware,
)
from .models import (
    AuditAction,
    AuditExportRequest,
    AuditExportResponse,
    AuditLogEntry,
    AuditOutcome,
    AuditQuery,
    AuditSeverity,
    AuditStats,
)
from .repository import (
    AuditRepository,
)

__all__ = [
    # Models
    "AuditAction",
    "AuditOutcome",
    "AuditSeverity",
    "AuditLogEntry",
    "AuditQuery",
    "AuditStats",
    "AuditExportRequest",
    "AuditExportResponse",
    # Logger
    "AuditLogger",
    "AuditLogHandler",
    "get_audit_logger",
    "set_audit_logger",
    # Middleware
    "AuditMiddleware",
    "create_audit_middleware",
    # Repository
    "AuditRepository",
]
