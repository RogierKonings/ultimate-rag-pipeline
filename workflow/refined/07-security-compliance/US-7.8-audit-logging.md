# US-7.8: Audit Logging

> **Epic:** Security & Compliance  
> **Priority:** High  
> **Estimated Effort:** 2 days  
> **Dependencies:** US-7.1 (JWT Authentication)

## User Story

**As a** compliance officer  
**I want** comprehensive audit logs  
**So that** all access and actions are traceable for security and compliance requirements

## Objective

Implement structured audit logging for all API operations including user identity, action type, resources accessed, timestamps, IP addresses, and outcomes. Store logs in tamper-evident storage with configurable retention policies.

## Architecture Reference

- **Format:** Structured JSON logs
- **Transport:** Stdout → Log aggregator (Loki, ELK, CloudWatch)
- **Storage:** PostgreSQL for queryable audit + Object storage for long-term
- **Retention:** Configurable (default 1 year)
- **Compliance:** SOC 2, GDPR, HIPAA compatible

## Implementation Tasks

### 1. Create Audit Log Models

`services/shared/security/audit/models.py`:

```python
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID, uuid4


class AuditAction(str, Enum):
    """Standard audit actions."""
    # Authentication
    LOGIN = "auth.login"
    LOGOUT = "auth.logout"
    LOGIN_FAILED = "auth.login_failed"
    TOKEN_REFRESH = "auth.token_refresh"
    PASSWORD_CHANGE = "auth.password_change"
    
    # Document operations
    DOCUMENT_CREATE = "document.create"
    DOCUMENT_READ = "document.read"
    DOCUMENT_UPDATE = "document.update"
    DOCUMENT_DELETE = "document.delete"
    DOCUMENT_SHARE = "document.share"
    
    # Query operations
    QUERY_EXECUTE = "query.execute"
    QUERY_RESULT_VIEW = "query.result_view"
    
    # Ingestion
    INGESTION_START = "ingestion.start"
    INGESTION_COMPLETE = "ingestion.complete"
    INGESTION_FAILED = "ingestion.failed"
    
    # ACL changes
    ACL_UPDATE = "acl.update"
    ACL_SHARE = "acl.share"
    ACL_REVOKE = "acl.revoke"
    
    # Admin operations
    USER_CREATE = "admin.user_create"
    USER_UPDATE = "admin.user_update"
    USER_DELETE = "admin.user_delete"
    ROLE_ASSIGN = "admin.role_assign"
    ROLE_REVOKE = "admin.role_revoke"
    
    # Configuration
    CONFIG_UPDATE = "config.update"
    SECRET_ACCESS = "secret.access"
    
    # Data export
    DATA_EXPORT = "data.export"
    AUDIT_EXPORT = "audit.export"


class AuditOutcome(str, Enum):
    """Outcome of audited action."""
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"
    ERROR = "error"


class AuditSeverity(str, Enum):
    """Severity level for audit events."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AuditLogEntry(BaseModel):
    """Structured audit log entry."""
    
    # Identity
    id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # Actor
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    tenant_id: Optional[UUID] = None
    session_id: Optional[str] = None
    
    # Request context
    request_id: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    
    # Action
    action: AuditAction
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    
    # Details
    outcome: AuditOutcome
    severity: AuditSeverity = AuditSeverity.INFO
    details: Dict[str, Any] = Field(default_factory=dict)
    
    # Error tracking
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    
    # Compliance
    data_classification: Optional[str] = None  # public, internal, confidential, restricted
    pii_accessed: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "timestamp": self.timestamp.isoformat(),
            "user_id": self.user_id,
            "user_email": self.user_email,
            "tenant_id": str(self.tenant_id) if self.tenant_id else None,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "action": self.action.value,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "outcome": self.outcome.value,
            "severity": self.severity.value,
            "details": self.details,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "data_classification": self.data_classification,
            "pii_accessed": self.pii_accessed,
        }
    
    def to_log_line(self) -> str:
        """Format for structured logging output."""
        import json
        return json.dumps(self.to_dict())


class AuditQuery(BaseModel):
    """Query parameters for audit log search."""
    user_id: Optional[str] = None
    tenant_id: Optional[UUID] = None
    action: Optional[AuditAction] = None
    actions: Optional[List[AuditAction]] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    outcome: Optional[AuditOutcome] = None
    severity: Optional[AuditSeverity] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    ip_address: Optional[str] = None
    limit: int = Field(default=100, le=1000)
    offset: int = 0
```

### 2. Create Audit Logger

`services/shared/security/audit/logger.py`:

```python
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID
import structlog
import json
import asyncio

from .models import (
    AuditLogEntry,
    AuditAction,
    AuditOutcome,
    AuditSeverity,
)

logger = structlog.get_logger("audit")


class AuditLogger:
    """Centralized audit logging service."""
    
    def __init__(
        self,
        repository=None,  # AuditRepository for DB storage
        queue=None,       # Optional async queue for buffering
    ):
        self.repository = repository
        self.queue = queue
        self._buffer = []
        self._buffer_size = 100
    
    async def log(
        self,
        action: AuditAction,
        outcome: AuditOutcome,
        request_id: str,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        tenant_id: Optional[UUID] = None,
        session_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        severity: AuditSeverity = AuditSeverity.INFO,
        details: Optional[Dict[str, Any]] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        data_classification: Optional[str] = None,
        pii_accessed: bool = False,
    ) -> AuditLogEntry:
        """Log an audit event."""
        
        entry = AuditLogEntry(
            timestamp=datetime.utcnow(),
            user_id=user_id,
            user_email=user_email,
            tenant_id=tenant_id,
            session_id=session_id,
            request_id=request_id,
            ip_address=ip_address,
            user_agent=user_agent,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            severity=severity,
            details=details or {},
            error_code=error_code,
            error_message=error_message,
            data_classification=data_classification,
            pii_accessed=pii_accessed,
        )
        
        # Log to stdout (for log aggregation)
        self._log_to_stdout(entry)
        
        # Store in database
        if self.repository:
            await self._store_entry(entry)
        
        return entry
    
    def _log_to_stdout(self, entry: AuditLogEntry):
        """Output structured log for aggregation."""
        log_func = logger.info
        if entry.severity == AuditSeverity.WARNING:
            log_func = logger.warning
        elif entry.severity == AuditSeverity.ERROR:
            log_func = logger.error
        elif entry.severity == AuditSeverity.CRITICAL:
            log_func = logger.critical
        
        log_func(
            "audit_event",
            audit_id=str(entry.id),
            action=entry.action.value,
            outcome=entry.outcome.value,
            user_id=entry.user_id,
            tenant_id=str(entry.tenant_id) if entry.tenant_id else None,
            resource_type=entry.resource_type,
            resource_id=entry.resource_id,
            ip_address=entry.ip_address,
            request_id=entry.request_id,
            pii_accessed=entry.pii_accessed,
            **entry.details,
        )
    
    async def _store_entry(self, entry: AuditLogEntry):
        """Store entry in database."""
        try:
            await self.repository.create(entry)
        except Exception as e:
            logger.error("audit_storage_error", error=str(e), entry_id=str(entry.id))
    
    # Convenience methods for common actions
    async def log_login(
        self,
        request_id: str,
        user_id: str,
        user_email: str,
        tenant_id: UUID,
        ip_address: str,
        success: bool,
        failure_reason: str = None,
    ):
        """Log authentication attempt."""
        return await self.log(
            action=AuditAction.LOGIN if success else AuditAction.LOGIN_FAILED,
            outcome=AuditOutcome.SUCCESS if success else AuditOutcome.FAILURE,
            request_id=request_id,
            user_id=user_id,
            user_email=user_email,
            tenant_id=tenant_id,
            ip_address=ip_address,
            severity=AuditSeverity.INFO if success else AuditSeverity.WARNING,
            error_message=failure_reason,
        )
    
    async def log_document_access(
        self,
        request_id: str,
        user_id: str,
        tenant_id: UUID,
        document_id: str,
        action: AuditAction,
        success: bool,
        ip_address: str = None,
        details: Dict[str, Any] = None,
    ):
        """Log document operation."""
        return await self.log(
            action=action,
            outcome=AuditOutcome.SUCCESS if success else AuditOutcome.FAILURE,
            request_id=request_id,
            user_id=user_id,
            tenant_id=tenant_id,
            ip_address=ip_address,
            resource_type="document",
            resource_id=document_id,
            details=details,
        )
    
    async def log_query(
        self,
        request_id: str,
        user_id: str,
        tenant_id: UUID,
        query_text: str,
        result_count: int,
        duration_ms: float,
        ip_address: str = None,
    ):
        """Log query execution."""
        # Redact query if it might contain PII
        safe_query = query_text[:100] + "..." if len(query_text) > 100 else query_text
        
        return await self.log(
            action=AuditAction.QUERY_EXECUTE,
            outcome=AuditOutcome.SUCCESS,
            request_id=request_id,
            user_id=user_id,
            tenant_id=tenant_id,
            ip_address=ip_address,
            resource_type="query",
            details={
                "query_preview": safe_query,
                "result_count": result_count,
                "duration_ms": duration_ms,
            },
        )
    
    async def log_access_denied(
        self,
        request_id: str,
        user_id: str,
        tenant_id: UUID,
        resource_type: str,
        resource_id: str,
        required_permission: str,
        ip_address: str = None,
    ):
        """Log authorization failure."""
        return await self.log(
            action=AuditAction.DOCUMENT_READ,
            outcome=AuditOutcome.DENIED,
            request_id=request_id,
            user_id=user_id,
            tenant_id=tenant_id,
            ip_address=ip_address,
            resource_type=resource_type,
            resource_id=resource_id,
            severity=AuditSeverity.WARNING,
            details={"required_permission": required_permission},
        )


# Singleton instance
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
```

### 3. Create Audit Middleware

`services/shared/security/audit/middleware.py`:

```python
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Callable
import time
import uuid
import structlog

from .logger import get_audit_logger, AuditLogger
from .models import AuditAction, AuditOutcome, AuditSeverity
from ..jwt.models import TokenClaims

logger = structlog.get_logger(__name__)


class AuditMiddleware(BaseHTTPMiddleware):
    """Middleware to automatically audit all API requests."""
    
    # Endpoints to exclude from auditing
    EXCLUDED_PATHS = [
        "/health",
        "/ready",
        "/metrics",
        "/docs",
        "/openapi.json",
        "/favicon.ico",
    ]
    
    # Map HTTP methods to audit actions
    METHOD_TO_ACTION = {
        "GET": "read",
        "POST": "create",
        "PUT": "update",
        "PATCH": "update",
        "DELETE": "delete",
    }
    
    def __init__(self, app, audit_logger: AuditLogger = None):
        super().__init__(app)
        self.audit_logger = audit_logger or get_audit_logger()
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip excluded paths
        if any(request.url.path.startswith(p) for p in self.EXCLUDED_PATHS):
            return await call_next(request)
        
        # Generate request ID
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        
        # Extract request metadata
        ip_address = self._get_client_ip(request)
        user_agent = request.headers.get("User-Agent")
        
        # Extract user from request state (set by auth middleware)
        user: TokenClaims = getattr(request.state, "user", None)
        
        # Track timing
        start_time = time.time()
        
        # Process request
        response = await call_next(request)
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000
        
        # Determine outcome
        outcome = self._determine_outcome(response.status_code)
        severity = self._determine_severity(response.status_code)
        
        # Determine action
        action = self._determine_action(request)
        resource_type, resource_id = self._extract_resource(request)
        
        # Log audit event
        try:
            await self.audit_logger.log(
                action=action,
                outcome=outcome,
                request_id=request_id,
                user_id=user.user_id if user else None,
                user_email=user.email if user else None,
                tenant_id=user.tenant_id if user else None,
                ip_address=ip_address,
                user_agent=user_agent,
                resource_type=resource_type,
                resource_id=resource_id,
                severity=severity,
                details={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                },
            )
        except Exception as e:
            logger.error("audit_middleware_error", error=str(e))
        
        return response
    
    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP, handling proxies."""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        return request.client.host if request.client else "unknown"
    
    def _determine_outcome(self, status_code: int) -> AuditOutcome:
        if 200 <= status_code < 300:
            return AuditOutcome.SUCCESS
        elif status_code == 401:
            return AuditOutcome.FAILURE
        elif status_code == 403:
            return AuditOutcome.DENIED
        else:
            return AuditOutcome.ERROR
    
    def _determine_severity(self, status_code: int) -> AuditSeverity:
        if 200 <= status_code < 300:
            return AuditSeverity.INFO
        elif status_code in (401, 403):
            return AuditSeverity.WARNING
        elif status_code >= 500:
            return AuditSeverity.ERROR
        else:
            return AuditSeverity.INFO
    
    def _determine_action(self, request: Request) -> AuditAction:
        """Map request to audit action."""
        path = request.url.path
        method = request.method
        
        # Auth endpoints
        if "/auth/token" in path:
            return AuditAction.LOGIN
        if "/auth/refresh" in path:
            return AuditAction.TOKEN_REFRESH
        if "/auth/logout" in path:
            return AuditAction.LOGOUT
        
        # Document endpoints
        if "/documents" in path:
            if method == "GET":
                return AuditAction.DOCUMENT_READ
            elif method == "POST":
                return AuditAction.DOCUMENT_CREATE
            elif method in ("PUT", "PATCH"):
                return AuditAction.DOCUMENT_UPDATE
            elif method == "DELETE":
                return AuditAction.DOCUMENT_DELETE
        
        # Query endpoints
        if "/query" in path:
            return AuditAction.QUERY_EXECUTE
        
        # ACL endpoints
        if "/acl" in path:
            if "share" in path:
                return AuditAction.ACL_SHARE
            return AuditAction.ACL_UPDATE
        
        # Ingestion endpoints
        if "/ingestion" in path or "/ingest" in path:
            return AuditAction.INGESTION_START
        
        # Default based on method
        action_map = {
            "GET": AuditAction.DOCUMENT_READ,
            "POST": AuditAction.DOCUMENT_CREATE,
            "PUT": AuditAction.DOCUMENT_UPDATE,
            "PATCH": AuditAction.DOCUMENT_UPDATE,
            "DELETE": AuditAction.DOCUMENT_DELETE,
        }
        return action_map.get(method, AuditAction.DOCUMENT_READ)
    
    def _extract_resource(self, request: Request) -> tuple[str, str]:
        """Extract resource type and ID from path."""
        path_parts = request.url.path.strip("/").split("/")
        
        resource_type = None
        resource_id = None
        
        for i, part in enumerate(path_parts):
            if part in ("documents", "collections", "users", "queries"):
                resource_type = part.rstrip("s")
                if i + 1 < len(path_parts):
                    resource_id = path_parts[i + 1]
                break
        
        return resource_type, resource_id
```

### 4. Create Audit Database Model

`services/shared/database/models/audit_log.py`:

```python
from sqlalchemy import Column, String, DateTime, JSON, Boolean, Index, Enum
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
import enum

from .base import Base


class AuditActionEnum(str, enum.Enum):
    LOGIN = "auth.login"
    LOGOUT = "auth.logout"
    LOGIN_FAILED = "auth.login_failed"
    TOKEN_REFRESH = "auth.token_refresh"
    DOCUMENT_CREATE = "document.create"
    DOCUMENT_READ = "document.read"
    DOCUMENT_UPDATE = "document.update"
    DOCUMENT_DELETE = "document.delete"
    QUERY_EXECUTE = "query.execute"
    ACL_UPDATE = "acl.update"
    # ... add more as needed


class AuditOutcomeEnum(str, enum.Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"
    ERROR = "error"


class AuditLog(Base):
    """Audit log database model."""
    __tablename__ = "audit_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # Actor
    user_id = Column(String(255), index=True)
    user_email = Column(String(255))
    tenant_id = Column(UUID(as_uuid=True), index=True)
    session_id = Column(String(255))
    
    # Request context
    request_id = Column(String(255), nullable=False, index=True)
    ip_address = Column(String(45))  # IPv6 max length
    user_agent = Column(String(500))
    
    # Action
    action = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(100), index=True)
    resource_id = Column(String(255), index=True)
    
    # Outcome
    outcome = Column(String(20), nullable=False, index=True)
    severity = Column(String(20), default="info")
    
    # Details
    details = Column(JSON, default={})
    
    # Error
    error_code = Column(String(100))
    error_message = Column(String(1000))
    
    # Compliance
    data_classification = Column(String(50))
    pii_accessed = Column(Boolean, default=False)
    
    __table_args__ = (
        Index("ix_audit_logs_tenant_timestamp", "tenant_id", "timestamp"),
        Index("ix_audit_logs_user_action", "user_id", "action"),
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
    )
```

### 5. Create Audit Repository

`services/shared/database/repositories/audit.py`:

```python
from typing import List, Optional
from datetime import datetime
from uuid import UUID
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.audit_log import AuditLog
from shared.security.audit.models import AuditLogEntry, AuditQuery


class AuditRepository:
    """Repository for audit log persistence."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, entry: AuditLogEntry) -> AuditLog:
        """Store audit log entry."""
        log = AuditLog(
            id=entry.id,
            timestamp=entry.timestamp,
            user_id=entry.user_id,
            user_email=entry.user_email,
            tenant_id=entry.tenant_id,
            session_id=entry.session_id,
            request_id=entry.request_id,
            ip_address=entry.ip_address,
            user_agent=entry.user_agent,
            action=entry.action.value,
            resource_type=entry.resource_type,
            resource_id=entry.resource_id,
            outcome=entry.outcome.value,
            severity=entry.severity.value,
            details=entry.details,
            error_code=entry.error_code,
            error_message=entry.error_message,
            data_classification=entry.data_classification,
            pii_accessed=entry.pii_accessed,
        )
        
        self.session.add(log)
        await self.session.commit()
        return log
    
    async def search(self, query: AuditQuery) -> List[AuditLog]:
        """Search audit logs with filters."""
        stmt = select(AuditLog)
        conditions = []
        
        if query.user_id:
            conditions.append(AuditLog.user_id == query.user_id)
        
        if query.tenant_id:
            conditions.append(AuditLog.tenant_id == query.tenant_id)
        
        if query.action:
            conditions.append(AuditLog.action == query.action.value)
        
        if query.actions:
            conditions.append(AuditLog.action.in_([a.value for a in query.actions]))
        
        if query.resource_type:
            conditions.append(AuditLog.resource_type == query.resource_type)
        
        if query.resource_id:
            conditions.append(AuditLog.resource_id == query.resource_id)
        
        if query.outcome:
            conditions.append(AuditLog.outcome == query.outcome.value)
        
        if query.severity:
            conditions.append(AuditLog.severity == query.severity.value)
        
        if query.start_time:
            conditions.append(AuditLog.timestamp >= query.start_time)
        
        if query.end_time:
            conditions.append(AuditLog.timestamp <= query.end_time)
        
        if query.ip_address:
            conditions.append(AuditLog.ip_address == query.ip_address)
        
        if conditions:
            stmt = stmt.where(and_(*conditions))
        
        stmt = stmt.order_by(AuditLog.timestamp.desc())
        stmt = stmt.limit(query.limit).offset(query.offset)
        
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def get_by_request_id(self, request_id: str) -> Optional[AuditLog]:
        """Get audit log by request ID."""
        stmt = select(AuditLog).where(AuditLog.request_id == request_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_user_activity(
        self,
        user_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> List[AuditLog]:
        """Get all activity for a user in a time range."""
        stmt = select(AuditLog).where(
            and_(
                AuditLog.user_id == user_id,
                AuditLog.timestamp >= start_time,
                AuditLog.timestamp <= end_time,
            )
        ).order_by(AuditLog.timestamp.desc())
        
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def get_resource_history(
        self,
        resource_type: str,
        resource_id: str,
    ) -> List[AuditLog]:
        """Get all audit events for a resource."""
        stmt = select(AuditLog).where(
            and_(
                AuditLog.resource_type == resource_type,
                AuditLog.resource_id == resource_id,
            )
        ).order_by(AuditLog.timestamp.desc())
        
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def count_by_action(
        self,
        tenant_id: UUID,
        start_time: datetime,
        end_time: datetime,
    ) -> dict:
        """Count events by action type."""
        from sqlalchemy import func
        
        stmt = select(
            AuditLog.action,
            func.count(AuditLog.id).label("count")
        ).where(
            and_(
                AuditLog.tenant_id == tenant_id,
                AuditLog.timestamp >= start_time,
                AuditLog.timestamp <= end_time,
            )
        ).group_by(AuditLog.action)
        
        result = await self.session.execute(stmt)
        return {row.action: row.count for row in result}
```

### 6. Create Audit API Endpoints

`services/api-gateway/routers/audit.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from datetime import datetime, timedelta
from uuid import UUID

from shared.security.jwt.models import TokenClaims
from shared.security.jwt.middleware import get_current_user
from shared.security.rbac.middleware import require_permission
from shared.security.rbac.permissions import Permission
from shared.security.audit.models import AuditQuery, AuditAction, AuditOutcome
from shared.database.repositories.audit import AuditRepository

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/logs")
async def search_audit_logs(
    user_id: Optional[str] = None,
    action: Optional[AuditAction] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    outcome: Optional[AuditOutcome] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    limit: int = Query(100, le=1000),
    offset: int = 0,
    user: TokenClaims = Depends(require_permission(Permission.AUDIT_READ)),
    audit_repo: AuditRepository = Depends(),
):
    """Search audit logs with filters."""
    query = AuditQuery(
        user_id=user_id,
        tenant_id=user.tenant_id,  # Always filter by tenant
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )
    
    logs = await audit_repo.search(query)
    return {"logs": logs, "count": len(logs)}


@router.get("/logs/user/{target_user_id}")
async def get_user_activity(
    target_user_id: str,
    days: int = Query(7, le=90),
    user: TokenClaims = Depends(require_permission(Permission.AUDIT_READ)),
    audit_repo: AuditRepository = Depends(),
):
    """Get all activity for a specific user."""
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=days)
    
    logs = await audit_repo.get_user_activity(
        user_id=target_user_id,
        start_time=start_time,
        end_time=end_time,
    )
    
    return {"user_id": target_user_id, "logs": logs}


@router.get("/logs/resource/{resource_type}/{resource_id}")
async def get_resource_history(
    resource_type: str,
    resource_id: str,
    user: TokenClaims = Depends(require_permission(Permission.AUDIT_READ)),
    audit_repo: AuditRepository = Depends(),
):
    """Get audit history for a specific resource."""
    logs = await audit_repo.get_resource_history(
        resource_type=resource_type,
        resource_id=resource_id,
    )
    
    return {
        "resource_type": resource_type,
        "resource_id": resource_id,
        "logs": logs,
    }


@router.get("/stats")
async def get_audit_stats(
    days: int = Query(7, le=90),
    user: TokenClaims = Depends(require_permission(Permission.AUDIT_READ)),
    audit_repo: AuditRepository = Depends(),
):
    """Get audit statistics."""
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=days)
    
    action_counts = await audit_repo.count_by_action(
        tenant_id=user.tenant_id,
        start_time=start_time,
        end_time=end_time,
    )
    
    return {
        "period_days": days,
        "action_counts": action_counts,
    }


@router.post("/export")
async def export_audit_logs(
    start_time: datetime,
    end_time: datetime,
    format: str = Query("json", pattern="^(json|csv)$"),
    user: TokenClaims = Depends(require_permission(Permission.AUDIT_EXPORT)),
    audit_repo: AuditRepository = Depends(),
):
    """Export audit logs for compliance."""
    query = AuditQuery(
        tenant_id=user.tenant_id,
        start_time=start_time,
        end_time=end_time,
        limit=10000,  # Allow larger exports
    )
    
    logs = await audit_repo.search(query)
    
    # This would be an async job in production
    return {
        "status": "completed",
        "count": len(logs),
        "format": format,
        "data": logs if format == "json" else None,
    }
```

### 7. Create Tests

`tests/security/test_audit_logging.py`:

```python
import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from shared.security.audit.models import (
    AuditLogEntry,
    AuditAction,
    AuditOutcome,
    AuditSeverity,
    AuditQuery,
)
from shared.security.audit.logger import AuditLogger


@pytest.fixture
def audit_logger():
    return AuditLogger()


class TestAuditLogEntry:
    def test_create_entry(self):
        entry = AuditLogEntry(
            request_id="req-123",
            user_id="user-456",
            tenant_id=uuid4(),
            action=AuditAction.DOCUMENT_READ,
            outcome=AuditOutcome.SUCCESS,
            resource_type="document",
            resource_id="doc-789",
        )
        
        assert entry.id is not None
        assert entry.timestamp is not None
        assert entry.action == AuditAction.DOCUMENT_READ
    
    def test_to_dict(self):
        entry = AuditLogEntry(
            request_id="req-123",
            action=AuditAction.LOGIN,
            outcome=AuditOutcome.SUCCESS,
        )
        
        data = entry.to_dict()
        
        assert "id" in data
        assert data["action"] == "auth.login"
        assert data["outcome"] == "success"
    
    def test_severity_defaults(self):
        entry = AuditLogEntry(
            request_id="req-123",
            action=AuditAction.DOCUMENT_READ,
            outcome=AuditOutcome.SUCCESS,
        )
        
        assert entry.severity == AuditSeverity.INFO


class TestAuditLogger:
    @pytest.mark.asyncio
    async def test_log_event(self, audit_logger):
        entry = await audit_logger.log(
            action=AuditAction.DOCUMENT_CREATE,
            outcome=AuditOutcome.SUCCESS,
            request_id="req-123",
            user_id="user-456",
            tenant_id=uuid4(),
            resource_type="document",
            resource_id="doc-789",
        )
        
        assert entry.action == AuditAction.DOCUMENT_CREATE
        assert entry.outcome == AuditOutcome.SUCCESS
    
    @pytest.mark.asyncio
    async def test_log_login(self, audit_logger):
        entry = await audit_logger.log_login(
            request_id="req-123",
            user_id="user-456",
            user_email="user@example.com",
            tenant_id=uuid4(),
            ip_address="192.168.1.1",
            success=True,
        )
        
        assert entry.action == AuditAction.LOGIN
        assert entry.ip_address == "192.168.1.1"
    
    @pytest.mark.asyncio
    async def test_log_login_failure(self, audit_logger):
        entry = await audit_logger.log_login(
            request_id="req-123",
            user_id="user-456",
            user_email="user@example.com",
            tenant_id=uuid4(),
            ip_address="192.168.1.1",
            success=False,
            failure_reason="Invalid password",
        )
        
        assert entry.action == AuditAction.LOGIN_FAILED
        assert entry.severity == AuditSeverity.WARNING
    
    @pytest.mark.asyncio
    async def test_log_query(self, audit_logger):
        entry = await audit_logger.log_query(
            request_id="req-123",
            user_id="user-456",
            tenant_id=uuid4(),
            query_text="How do I configure the system?",
            result_count=5,
            duration_ms=150.5,
        )
        
        assert entry.action == AuditAction.QUERY_EXECUTE
        assert entry.details["result_count"] == 5


class TestAuditQuery:
    def test_default_values(self):
        query = AuditQuery()
        
        assert query.limit == 100
        assert query.offset == 0
    
    def test_with_filters(self):
        query = AuditQuery(
            user_id="user-123",
            action=AuditAction.DOCUMENT_READ,
            start_time=datetime.utcnow() - timedelta(days=7),
            limit=50,
        )
        
        assert query.user_id == "user-123"
        assert query.limit == 50
```

## Acceptance Criteria

- [ ] All API calls logged with user identity
- [ ] Action and resource type/ID logged
- [ ] Timestamp and IP address logged
- [ ] Structured JSON log format for aggregation
- [ ] Database persistence for audit queries
- [ ] Audit log search API implemented
- [ ] Export functionality for compliance
- [ ] Retention policy configurable
- [ ] Tests passing

## Verification Commands

```bash
# Check audit logs in stdout
kubectl logs -n rag-pipeline deploy/api-gateway | grep audit_event

# Run audit tests
pytest tests/security/test_audit_logging.py -v

# Query audit logs via API
curl -X GET "http://localhost:8000/audit/logs?action=auth.login&limit=10" \
  -H "Authorization: Bearer $TOKEN"

# Get user activity
curl -X GET "http://localhost:8000/audit/logs/user/user-123?days=7" \
  -H "Authorization: Bearer $TOKEN"

# Export audit logs
curl -X POST "http://localhost:8000/audit/export" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"start_time": "2024-01-01T00:00:00Z", "end_time": "2024-01-31T23:59:59Z"}'
```

## Environment Variables

```bash
# Audit configuration
AUDIT_LOG_LEVEL=INFO
AUDIT_RETENTION_DAYS=365
AUDIT_STORAGE_BACKEND=postgresql

# Log aggregation
LOG_FORMAT=json
LOG_OUTPUT=stdout
```

## Files to Create

1. `services/shared/security/audit/__init__.py`
2. `services/shared/security/audit/models.py`
3. `services/shared/security/audit/logger.py`
4. `services/shared/security/audit/middleware.py`
5. `services/shared/database/models/audit_log.py`
6. `services/shared/database/repositories/audit.py`
7. `services/api-gateway/routers/audit.py`
8. `services/shared/database/migrations/versions/xxx_add_audit_logs.py`
9. `tests/security/test_audit_logging.py`

## Security Considerations

- **Never log sensitive data** - Redact passwords, tokens, PII
- **Tamper-evident storage** - Consider append-only or blockchain
- **Access control** - Only authorized users can view/export
- **Integrity checks** - Hash chain or signatures
- **Separate storage** - Audit logs separate from application data
- **Retention compliance** - Meet regulatory requirements
