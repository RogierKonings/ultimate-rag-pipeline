"""
Audit middleware for FastAPI.

This module provides middleware for automatic audit logging
of API requests and responses.
"""

import re
import time
from typing import Any
from uuid import UUID

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from .logger import AuditLogger, get_audit_logger
from .models import AuditAction, AuditOutcome, AuditSeverity


class AuditMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for automatic audit logging.

    Logs all API requests with user identity, action type,
    resource information, and response status.

    Example:
        ```python
        from fastapi import FastAPI
        from services.shared.security.audit import AuditMiddleware

        app = FastAPI()
        app.add_middleware(
            AuditMiddleware,
            service_name="ingestion-service",
            exclude_paths=["/health", "/metrics"],
        )
        ```
    """

    def __init__(
        self,
        app,
        service_name: str = "rag-pipeline",
        logger: AuditLogger | None = None,
        exclude_paths: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        log_request_body: bool = False,
        log_response_body: bool = False,
    ):
        """
        Initialize audit middleware.

        Args:
            app: FastAPI application.
            service_name: Name of the service.
            logger: Custom audit logger (uses global if None).
            exclude_paths: Exact paths to exclude from logging.
            exclude_patterns: Regex patterns for paths to exclude.
            log_request_body: Whether to log request body (careful with PII).
            log_response_body: Whether to log response body.
        """
        super().__init__(app)
        self.service_name = service_name
        self._logger = logger
        self.exclude_paths = set(exclude_paths or [
            "/health",
            "/healthz",
            "/ready",
            "/readiness",
            "/metrics",
            "/openapi.json",
            "/docs",
            "/redoc",
        ])
        self.exclude_patterns = [
            re.compile(p) for p in (exclude_patterns or [])
        ]
        self.log_request_body = log_request_body
        self.log_response_body = log_response_body

    @property
    def logger(self) -> AuditLogger:
        """Get audit logger."""
        if self._logger is None:
            self._logger = get_audit_logger(self.service_name)
        return self._logger

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Process request and log audit event."""
        # Check if path should be excluded
        if self._should_exclude(request.url.path):
            return await call_next(request)

        # Start timing
        start_time = time.perf_counter()

        # Extract request info
        client_ip = self._get_client_ip(request)
        user_agent = request.headers.get("user-agent")
        request_id = request.headers.get("x-request-id")
        trace_id = request.headers.get("x-trace-id") or request.headers.get(
            "traceparent", "",
        ).split("-")[1] if "-" in request.headers.get("traceparent", "") else None

        # Extract user info from request state (set by auth middleware)
        user_id = getattr(request.state, "user_id", None)
        username = getattr(request.state, "username", None)
        tenant_id = getattr(request.state, "tenant_id", None)

        # Determine action and resource from request
        action = self._determine_action(request.method, request.url.path)
        resource_type, resource_id = self._extract_resource(request.url.path)

        # Process request
        response: Response | None = None
        error_message: str | None = None
        outcome = AuditOutcome.SUCCESS
        severity = AuditSeverity.INFO

        try:
            response = await call_next(request)

            # Determine outcome from status code
            if response.status_code >= 500:
                outcome = AuditOutcome.ERROR
                severity = AuditSeverity.ERROR
            elif response.status_code == 403:
                outcome = AuditOutcome.DENIED
                severity = AuditSeverity.WARNING
            elif response.status_code == 401:
                outcome = AuditOutcome.UNAUTHORIZED
                severity = AuditSeverity.WARNING
            elif response.status_code >= 400:
                outcome = AuditOutcome.FAILURE
                severity = AuditSeverity.WARNING

        except Exception as e:
            outcome = AuditOutcome.ERROR
            severity = AuditSeverity.ERROR
            error_message = str(e)
            raise

        finally:
            # Calculate duration
            duration_ms = (time.perf_counter() - start_time) * 1000

            # Build details
            details: dict[str, Any] = {}

            # Log audit event
            try:
                await self.logger.log(
                    action=action,
                    outcome=outcome,
                    severity=severity,
                    user_id=UUID(user_id) if user_id else None,
                    username=username,
                    tenant_id=UUID(tenant_id) if tenant_id else None,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    client_ip=client_ip,
                    user_agent=user_agent,
                    request_method=request.method,
                    request_path=str(request.url.path),
                    request_id=request_id,
                    trace_id=trace_id,
                    status_code=response.status_code if response else 500,
                    duration_ms=duration_ms,
                    error_message=error_message,
                    details=details if details else None,
                )
            except Exception:
                # Don't fail request if audit logging fails
                pass

        return response

    def _should_exclude(self, path: str) -> bool:
        """Check if path should be excluded from logging."""
        # Check exact matches
        if path in self.exclude_paths:
            return True

        # Check patterns
        return any(pattern.match(path) for pattern in self.exclude_patterns)

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP, handling proxies."""
        # Check X-Forwarded-For header (set by reverse proxies)
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # Get the first IP (original client)
            return forwarded_for.split(",")[0].strip()

        # Check X-Real-IP header
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip

        # Fall back to direct connection IP
        if request.client:
            return request.client.host

        return "unknown"

    def _determine_action(self, method: str, path: str) -> AuditAction:
        """Determine audit action from HTTP method and path."""
        # Map path patterns to actions
        path_lower = path.lower()

        # Authentication endpoints
        if "/auth/" in path_lower or "/login" in path_lower:
            if "login" in path_lower:
                return AuditAction.AUTH_LOGIN
            if "logout" in path_lower:
                return AuditAction.AUTH_LOGOUT
            if "refresh" in path_lower:
                return AuditAction.AUTH_TOKEN_REFRESH

        # Document endpoints
        if "/document" in path_lower or "/ingest" in path_lower:
            if method == "POST":
                return AuditAction.DOCUMENT_CREATE
            if method == "GET":
                return AuditAction.DOCUMENT_READ
            if method in ("PUT", "PATCH"):
                return AuditAction.DOCUMENT_UPDATE
            if method == "DELETE":
                return AuditAction.DOCUMENT_DELETE

        # Query/search endpoints
        if "/search" in path_lower or "/query" in path_lower or "/retrieve" in path_lower:
            return AuditAction.QUERY_SEARCH

        if "/chat" in path_lower:
            return AuditAction.QUERY_CHAT

        # ACL endpoints
        if "/acl" in path_lower or "/share" in path_lower:
            if method == "POST":
                return AuditAction.ACL_GRANT
            if method == "DELETE":
                return AuditAction.ACL_REVOKE
            if method in ("PUT", "PATCH"):
                return AuditAction.ACL_UPDATE

        # Admin endpoints
        if "/admin/" in path_lower or "/users" in path_lower:
            if "/user" in path_lower:
                if method == "POST":
                    return AuditAction.ADMIN_USER_CREATE
                if method in ("PUT", "PATCH"):
                    return AuditAction.ADMIN_USER_UPDATE
                if method == "DELETE":
                    return AuditAction.ADMIN_USER_DELETE
            if "/role" in path_lower:
                if method == "POST":
                    return AuditAction.ADMIN_ROLE_ASSIGN
                if method == "DELETE":
                    return AuditAction.ADMIN_ROLE_REVOKE

        # Data operations
        if "/export" in path_lower:
            return AuditAction.DATA_EXPORT
        if "/import" in path_lower:
            return AuditAction.DATA_IMPORT

        # Generic fallback based on method
        if method == "GET":
            return AuditAction.GENERIC_READ
        if method in ("POST", "PUT", "PATCH"):
            return AuditAction.GENERIC_WRITE
        if method == "DELETE":
            return AuditAction.GENERIC_DELETE

        return AuditAction.GENERIC_READ

    def _extract_resource(self, path: str) -> tuple[str | None, str | None]:
        """Extract resource type and ID from path."""
        # Common patterns: /api/v1/documents/{id}, /api/v1/users/{id}
        parts = path.strip("/").split("/")

        resource_type = None
        resource_id = None

        # Look for resource type and ID
        for _i, part in enumerate(parts):
            # Skip version prefixes
            if part in ("api", "v1", "v2"):
                continue

            # Found a resource type
            if not resource_type and part.isalpha():
                resource_type = part.rstrip("s")  # documents -> document

            # Found an ID (UUID-like or numeric)
            if resource_type and not resource_id:
                if self._looks_like_id(part):
                    resource_id = part
                    break

        return resource_type, resource_id

    def _looks_like_id(self, value: str) -> bool:
        """Check if value looks like an ID."""
        # UUID format
        if len(value) == 36 and value.count("-") == 4:
            return True

        # Numeric ID
        if value.isdigit():
            return True

        # Short UUID or hash
        return bool(len(value) >= 8 and all(c in "0123456789abcdef-" for c in value.lower()))


def create_audit_middleware(
    service_name: str = "rag-pipeline",
    **kwargs,
) -> type:
    """
    Create configured audit middleware class.

    Args:
        service_name: Service name.
        **kwargs: Additional middleware arguments.

    Returns:
        Configured middleware class.
    """

    class ConfiguredAuditMiddleware(AuditMiddleware):
        def __init__(self, app):
            super().__init__(
                app,
                service_name=service_name,
                **kwargs,
            )

    return ConfiguredAuditMiddleware
