"""Correlation context for distributed request tracing."""

from __future__ import annotations

import hashlib
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4

# Context variable for correlation data
_correlation_context: ContextVar[CorrelationContext | None] = ContextVar(
    "correlation_context", default=None
)


@dataclass
class CorrelationContext:
    """Correlation context for distributed tracing."""

    request_id: str
    trace_id: str
    tenant_id: str | None = None
    user_id_hash: str | None = None
    span_id: str | None = None

    @classmethod
    def generate(
        cls,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> CorrelationContext:
        """Generate new correlation context."""
        request_id = str(uuid4())
        return cls(
            request_id=request_id,
            trace_id=request_id,
            tenant_id=tenant_id,
            user_id_hash=cls._hash_user_id(user_id) if user_id else None,
        )

    @classmethod
    def from_headers(cls, headers: dict[str, str]) -> CorrelationContext:
        """Extract correlation context from HTTP headers."""
        normalized = {k.lower(): v for k, v in headers.items()}
        request_id = normalized.get("x-request-id") or str(uuid4())
        trace_id = normalized.get("x-trace-id") or request_id
        tenant_id = normalized.get("x-tenant-id")
        user_id_hash = normalized.get("x-user-id-hash")

        return cls(
            request_id=request_id,
            trace_id=trace_id,
            tenant_id=tenant_id,
            user_id_hash=user_id_hash,
        )

    def to_headers(self) -> dict[str, str]:
        """Convert to HTTP headers for propagation."""
        headers: dict[str, str] = {
            "X-Request-ID": self.request_id,
            "X-Trace-ID": self.trace_id,
        }
        if self.tenant_id:
            headers["X-Tenant-ID"] = self.tenant_id
        if self.user_id_hash:
            headers["X-User-ID-Hash"] = self.user_id_hash
        return headers

    @staticmethod
    def _hash_user_id(user_id: str) -> str:
        """Hash user ID for privacy in logs."""
        return hashlib.sha256(user_id.encode()).hexdigest()[:16]


def get_correlation_context() -> CorrelationContext | None:
    """Get current correlation context."""
    return _correlation_context.get()


def set_correlation_context(ctx: CorrelationContext) -> None:
    """Set correlation context for current async context."""
    _correlation_context.set(ctx)


def clear_correlation_context() -> None:
    """Clear the correlation context."""
    _correlation_context.set(None)
