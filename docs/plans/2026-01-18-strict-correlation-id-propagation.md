# Strict Correlation ID Propagation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable complete request tracing across all services by propagating consistent correlation IDs through HTTP headers and Celery tasks.

**Architecture:** Build a unified `CorrelationContext` that flows through all service boundaries via HTTP headers (`X-Request-ID`, `X-Trace-ID`, `X-Tenant-ID`, `X-User-ID-Hash`) and Celery task headers. Leverage existing `RequestContext` and `RequestLoggingMiddleware` patterns, extending them for correlation propagation.

**Tech Stack:** Python 3.11+, FastAPI, httpx, Celery, structlog, OpenTelemetry, Redis

---

## Task 1: Create Correlation Context Module

**Files:**
- Create: `services/shared/observability/correlation/__init__.py`
- Create: `services/shared/observability/correlation/context.py`
- Test: `services/shared/observability/correlation/tests/__init__.py`
- Test: `services/shared/observability/correlation/tests/test_context.py`

**Step 1: Write the failing test for CorrelationContext**

```python
# services/shared/observability/correlation/tests/test_context.py
"""Tests for CorrelationContext."""

import pytest
from correlation.context import (
    CorrelationContext,
    get_correlation_context,
    set_correlation_context,
    clear_correlation_context,
)


class TestCorrelationContext:
    """Tests for CorrelationContext dataclass."""

    def test_generate_creates_valid_context(self):
        """Should generate context with valid UUIDs."""
        ctx = CorrelationContext.generate(tenant_id="tenant-123")

        assert ctx.request_id is not None
        assert len(ctx.request_id) == 36  # UUID format
        assert ctx.trace_id == ctx.request_id  # Default: trace_id equals request_id
        assert ctx.tenant_id == "tenant-123"
        assert ctx.user_id_hash is None

    def test_generate_with_user_id_hashes_it(self):
        """Should hash user ID for privacy."""
        ctx = CorrelationContext.generate(
            tenant_id="tenant-123",
            user_id="user-456"
        )

        assert ctx.user_id_hash is not None
        assert ctx.user_id_hash != "user-456"
        assert len(ctx.user_id_hash) == 16  # Truncated SHA256

    def test_from_headers_extracts_all_fields(self):
        """Should extract context from HTTP headers."""
        headers = {
            "x-request-id": "req-123",
            "x-trace-id": "trace-456",
            "x-tenant-id": "tenant-789",
            "x-user-id-hash": "abc123",
        }

        ctx = CorrelationContext.from_headers(headers)

        assert ctx.request_id == "req-123"
        assert ctx.trace_id == "trace-456"
        assert ctx.tenant_id == "tenant-789"
        assert ctx.user_id_hash == "abc123"

    def test_from_headers_generates_missing_request_id(self):
        """Should generate request_id if not provided."""
        headers = {}

        ctx = CorrelationContext.from_headers(headers)

        assert ctx.request_id is not None
        assert len(ctx.request_id) == 36
        assert ctx.trace_id == ctx.request_id

    def test_from_headers_uses_request_id_as_trace_id_if_missing(self):
        """Should use request_id as trace_id if trace_id not provided."""
        headers = {"x-request-id": "req-123"}

        ctx = CorrelationContext.from_headers(headers)

        assert ctx.trace_id == "req-123"

    def test_to_headers_produces_correct_format(self):
        """Should convert to HTTP headers for propagation."""
        ctx = CorrelationContext(
            request_id="req-123",
            trace_id="trace-456",
            tenant_id="tenant-789",
            user_id_hash="abc123",
        )

        headers = ctx.to_headers()

        assert headers["X-Request-ID"] == "req-123"
        assert headers["X-Trace-ID"] == "trace-456"
        assert headers["X-Tenant-ID"] == "tenant-789"
        assert headers["X-User-ID-Hash"] == "abc123"

    def test_to_headers_omits_none_values(self):
        """Should not include None values in headers."""
        ctx = CorrelationContext(
            request_id="req-123",
            trace_id="trace-456",
        )

        headers = ctx.to_headers()

        assert "X-Tenant-ID" not in headers
        assert "X-User-ID-Hash" not in headers


class TestCorrelationContextVar:
    """Tests for context variable management."""

    def test_set_and_get_correlation_context(self):
        """Should store and retrieve context."""
        ctx = CorrelationContext(
            request_id="req-123",
            trace_id="trace-456",
        )

        set_correlation_context(ctx)
        retrieved = get_correlation_context()

        assert retrieved is not None
        assert retrieved.request_id == "req-123"

        # Cleanup
        clear_correlation_context()

    def test_get_returns_none_when_not_set(self):
        """Should return None when context not set."""
        clear_correlation_context()

        result = get_correlation_context()

        assert result is None

    def test_clear_removes_context(self):
        """Should clear the context."""
        ctx = CorrelationContext(request_id="req-123", trace_id="trace-456")
        set_correlation_context(ctx)

        clear_correlation_context()

        assert get_correlation_context() is None
```

**Step 2: Run test to verify it fails**

Run: `cd services/shared/observability && python -m pytest correlation/tests/test_context.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'correlation'"

**Step 3: Write minimal implementation**

```python
# services/shared/observability/correlation/__init__.py
"""Correlation ID propagation for distributed tracing."""

from .context import (
    CorrelationContext,
    get_correlation_context,
    set_correlation_context,
    clear_correlation_context,
)

__all__ = [
    "CorrelationContext",
    "get_correlation_context",
    "set_correlation_context",
    "clear_correlation_context",
]
```

```python
# services/shared/observability/correlation/context.py
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
    """
    Correlation context for distributed tracing.

    This context is propagated across service boundaries via HTTP headers
    and made available to logging and tracing systems.

    Attributes:
        request_id: Unique identifier for the user request.
        trace_id: OTEL trace ID (may equal request_id).
        tenant_id: Tenant context for multi-tenancy.
        user_id_hash: Hashed user ID for privacy in logs.
        span_id: Current span ID (optional).
    """

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
        """
        Generate new correlation context.

        Args:
            tenant_id: Optional tenant identifier.
            user_id: Optional user identifier (will be hashed).

        Returns:
            New CorrelationContext with generated IDs.
        """
        request_id = str(uuid4())
        return cls(
            request_id=request_id,
            trace_id=request_id,  # Use request_id as trace_id by default
            tenant_id=tenant_id,
            user_id_hash=cls._hash_user_id(user_id) if user_id else None,
        )

    @classmethod
    def from_headers(cls, headers: dict[str, str]) -> CorrelationContext:
        """
        Extract correlation context from HTTP headers.

        Headers are matched case-insensitively.

        Args:
            headers: HTTP headers dict.

        Returns:
            CorrelationContext extracted from headers.
        """
        # Normalize header keys to lowercase
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
        """
        Convert to HTTP headers for propagation.

        Returns:
            Dict of HTTP headers with correlation context.
        """
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
        """
        Hash user ID for privacy in logs.

        Args:
            user_id: The user identifier to hash.

        Returns:
            First 16 characters of SHA256 hash.
        """
        return hashlib.sha256(user_id.encode()).hexdigest()[:16]


def get_correlation_context() -> CorrelationContext | None:
    """
    Get current correlation context.

    Returns:
        Current CorrelationContext or None if not set.
    """
    return _correlation_context.get()


def set_correlation_context(ctx: CorrelationContext) -> None:
    """
    Set correlation context for current async context.

    Args:
        ctx: The CorrelationContext to set.
    """
    _correlation_context.set(ctx)


def clear_correlation_context() -> None:
    """Clear the correlation context."""
    _correlation_context.set(None)
```

```python
# services/shared/observability/correlation/tests/__init__.py
"""Tests for correlation module."""
```

**Step 4: Run test to verify it passes**

Run: `cd services/shared/observability && python -m pytest correlation/tests/test_context.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add services/shared/observability/correlation/
git commit -m "$(cat <<'EOF'
feat(observability): add CorrelationContext for distributed tracing

Implements US-10.3.1 AC-1, AC-2: Standardized correlation headers and ID generation.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Create Correlation Middleware

**Files:**
- Create: `services/shared/observability/correlation/middleware.py`
- Test: `services/shared/observability/correlation/tests/test_middleware.py`

**Step 1: Write the failing test for CorrelationMiddleware**

```python
# services/shared/observability/correlation/tests/test_middleware.py
"""Tests for CorrelationMiddleware."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.testclient import TestClient as StarletteTestClient

from correlation.middleware import CorrelationMiddleware
from correlation.context import get_correlation_context, clear_correlation_context


@pytest.fixture
def app():
    """Create test FastAPI app with CorrelationMiddleware."""
    app = FastAPI()
    app.add_middleware(CorrelationMiddleware, service_name="test-service")

    @app.get("/test")
    async def test_endpoint():
        ctx = get_correlation_context()
        return {
            "request_id": ctx.request_id if ctx else None,
            "tenant_id": ctx.tenant_id if ctx else None,
        }

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


class TestCorrelationMiddleware:
    """Tests for CorrelationMiddleware."""

    def test_generates_request_id_if_not_provided(self, client):
        """Should generate request_id when not in headers."""
        response = client.get("/test")

        assert response.status_code == 200
        assert "X-Request-ID" in response.headers
        assert len(response.headers["X-Request-ID"]) == 36

    def test_preserves_existing_request_id(self, client):
        """Should preserve request_id from incoming headers."""
        response = client.get(
            "/test",
            headers={"X-Request-ID": "existing-req-123"}
        )

        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == "existing-req-123"
        data = response.json()
        assert data["request_id"] == "existing-req-123"

    def test_extracts_tenant_id_from_headers(self, client):
        """Should extract tenant_id from headers."""
        response = client.get(
            "/test",
            headers={
                "X-Request-ID": "req-123",
                "X-Tenant-ID": "tenant-456"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["tenant_id"] == "tenant-456"

    def test_adds_trace_id_to_response(self, client):
        """Should add X-Trace-ID to response headers."""
        response = client.get(
            "/test",
            headers={"X-Request-ID": "req-123"}
        )

        assert "X-Trace-ID" in response.headers

    def test_clears_context_after_request(self, client):
        """Should clear context after request completes."""
        clear_correlation_context()

        response = client.get("/test")
        assert response.status_code == 200

        # Context should be cleared after request
        # Note: TestClient runs synchronously, so context is isolated
        ctx = get_correlation_context()
        assert ctx is None

    def test_skips_excluded_paths(self, client):
        """Should not process excluded paths like /health."""
        # Health endpoint should still work but with minimal processing
        response = client.get("/health")

        assert response.status_code == 200


class TestCorrelationMiddlewareStructlog:
    """Tests for structlog integration."""

    @patch("correlation.middleware.structlog")
    def test_binds_context_to_structlog(self, mock_structlog, client):
        """Should bind correlation context to structlog."""
        mock_contextvars = MagicMock()
        mock_structlog.contextvars = mock_contextvars

        response = client.get(
            "/test",
            headers={
                "X-Request-ID": "req-123",
                "X-Tenant-ID": "tenant-456"
            }
        )

        # Verify structlog was bound with context
        mock_contextvars.bind_contextvars.assert_called()
        call_kwargs = mock_contextvars.bind_contextvars.call_args[1]
        assert call_kwargs["request_id"] == "req-123"
        assert call_kwargs["tenant_id"] == "tenant-456"
```

**Step 2: Run test to verify it fails**

Run: `cd services/shared/observability && python -m pytest correlation/tests/test_middleware.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'correlation.middleware'"

**Step 3: Write minimal implementation**

```python
# services/shared/observability/correlation/middleware.py
"""FastAPI middleware for correlation ID propagation."""

from __future__ import annotations

import time
from typing import Callable

import structlog
from fastapi import Request, Response
from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from .context import (
    CorrelationContext,
    clear_correlation_context,
    get_correlation_context,
    set_correlation_context,
)

logger = structlog.get_logger(__name__)


class CorrelationMiddleware(BaseHTTPMiddleware):
    """
    Middleware for correlation ID propagation.

    Extracts correlation headers from incoming requests,
    binds them to logging and tracing context,
    and ensures they're included in responses.

    Args:
        app: ASGI application.
        service_name: Name of the service for logging.
        excluded_paths: Paths to exclude from processing.
    """

    def __init__(
        self,
        app: ASGIApp,
        service_name: str = "unknown",
        excluded_paths: list[str] | None = None,
    ) -> None:
        """Initialize the middleware."""
        super().__init__(app)
        self.service_name = service_name
        self.excluded_paths = excluded_paths or [
            "/health",
            "/healthz",
            "/ready",
            "/readyz",
            "/live",
            "/livez",
            "/metrics",
        ]

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Process the request and propagate correlation context."""
        # Skip excluded paths
        if self._should_exclude(request.url.path):
            return await call_next(request)

        # Extract or generate correlation context
        headers = {k.lower(): v for k, v in request.headers.items()}
        ctx = CorrelationContext.from_headers(headers)

        # Set in context variable
        set_correlation_context(ctx)

        # Bind to structlog context
        structlog.contextvars.bind_contextvars(
            request_id=ctx.request_id,
            trace_id=ctx.trace_id,
            tenant_id=ctx.tenant_id or "unknown",
            service=self.service_name,
        )

        # Add to OTEL span
        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_attribute("request_id", ctx.request_id)
            span.set_attribute("trace_id", ctx.trace_id)
            if ctx.tenant_id:
                span.set_attribute("tenant_id", ctx.tenant_id)

        # Log request start
        start_time = time.perf_counter()
        logger.info(
            "request_started",
            method=request.method,
            path=request.url.path,
        )

        try:
            response = await call_next(request)

            # Add correlation headers to response
            response.headers["X-Request-ID"] = ctx.request_id
            response.headers["X-Trace-ID"] = ctx.trace_id

            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
            )

            return response

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "request_failed",
                method=request.method,
                path=request.url.path,
                error=str(e),
                duration_ms=round(duration_ms, 2),
            )
            raise

        finally:
            # Clear context
            structlog.contextvars.unbind_contextvars(
                "request_id", "trace_id", "tenant_id", "service"
            )
            clear_correlation_context()

    def _should_exclude(self, path: str) -> bool:
        """Check if path should be excluded from processing."""
        return any(path.startswith(excluded) for excluded in self.excluded_paths)
```

**Step 4: Update __init__.py**

```python
# services/shared/observability/correlation/__init__.py
"""Correlation ID propagation for distributed tracing."""

from .context import (
    CorrelationContext,
    get_correlation_context,
    set_correlation_context,
    clear_correlation_context,
)
from .middleware import CorrelationMiddleware

__all__ = [
    "CorrelationContext",
    "get_correlation_context",
    "set_correlation_context",
    "clear_correlation_context",
    "CorrelationMiddleware",
]
```

**Step 5: Run test to verify it passes**

Run: `cd services/shared/observability && python -m pytest correlation/tests/test_middleware.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add services/shared/observability/correlation/
git commit -m "$(cat <<'EOF'
feat(observability): add CorrelationMiddleware for FastAPI

Implements US-10.3.1 AC-3: Middleware extracts headers into context,
binds to OTEL spans and structlog.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Create Correlated HTTP Client

**Files:**
- Create: `services/shared/observability/correlation/http_client.py`
- Test: `services/shared/observability/correlation/tests/test_http_client.py`

**Step 1: Write the failing test for CorrelatedHttpClient**

```python
# services/shared/observability/correlation/tests/test_http_client.py
"""Tests for CorrelatedHttpClient."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from correlation.http_client import CorrelatedHttpClient, create_service_client
from correlation.context import (
    CorrelationContext,
    set_correlation_context,
    clear_correlation_context,
)


@pytest.fixture
def correlation_context():
    """Set up correlation context for tests."""
    ctx = CorrelationContext(
        request_id="req-123",
        trace_id="trace-456",
        tenant_id="tenant-789",
        user_id_hash="abc123",
    )
    set_correlation_context(ctx)
    yield ctx
    clear_correlation_context()


class TestCorrelatedHttpClient:
    """Tests for CorrelatedHttpClient."""

    @pytest.mark.asyncio
    async def test_get_includes_correlation_headers(self, correlation_context):
        """Should include correlation headers in GET requests."""
        client = CorrelatedHttpClient(base_url="http://test.local")

        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response

            async with client:
                await client.get("/test")

            # Check headers were passed
            call_kwargs = mock_get.call_args[1]
            headers = call_kwargs.get("headers", {})
            assert headers["X-Request-ID"] == "req-123"
            assert headers["X-Trace-ID"] == "trace-456"
            assert headers["X-Tenant-ID"] == "tenant-789"
            assert headers["X-User-ID-Hash"] == "abc123"

    @pytest.mark.asyncio
    async def test_post_includes_correlation_headers(self, correlation_context):
        """Should include correlation headers in POST requests."""
        client = CorrelatedHttpClient(base_url="http://test.local")

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            async with client:
                await client.post("/test", json={"data": "value"})

            call_kwargs = mock_post.call_args[1]
            headers = call_kwargs.get("headers", {})
            assert headers["X-Request-ID"] == "req-123"

    @pytest.mark.asyncio
    async def test_merges_extra_headers(self, correlation_context):
        """Should merge extra headers with correlation headers."""
        client = CorrelatedHttpClient(base_url="http://test.local")

        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_response = MagicMock()
            mock_get.return_value = mock_response

            async with client:
                await client.get("/test", headers={"Authorization": "Bearer token"})

            call_kwargs = mock_get.call_args[1]
            headers = call_kwargs.get("headers", {})
            assert headers["Authorization"] == "Bearer token"
            assert headers["X-Request-ID"] == "req-123"

    @pytest.mark.asyncio
    async def test_works_without_correlation_context(self):
        """Should work when no correlation context is set."""
        clear_correlation_context()
        client = CorrelatedHttpClient(base_url="http://test.local")

        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_response = MagicMock()
            mock_get.return_value = mock_response

            async with client:
                await client.get("/test")

            # Should not raise, headers may be empty
            call_kwargs = mock_get.call_args[1]
            headers = call_kwargs.get("headers", {})
            # Correlation headers should not be present
            assert "X-Request-ID" not in headers or headers.get("X-Request-ID") is None


class TestCreateServiceClient:
    """Tests for create_service_client factory."""

    def test_creates_client_with_service_name(self):
        """Should create client with correct base URL."""
        client = create_service_client(
            service_name="retrieval",
            base_url="http://retrieval:8002"
        )

        assert client.base_url == "http://retrieval:8002"
        assert client.timeout == 30.0

    def test_creates_client_with_custom_timeout(self):
        """Should allow custom timeout."""
        client = create_service_client(
            service_name="retrieval",
            base_url="http://retrieval:8002",
            timeout=60.0
        )

        assert client.timeout == 60.0
```

**Step 2: Run test to verify it fails**

Run: `cd services/shared/observability && python -m pytest correlation/tests/test_http_client.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'correlation.http_client'"

**Step 3: Write minimal implementation**

```python
# services/shared/observability/correlation/http_client.py
"""HTTP client that automatically propagates correlation headers."""

from __future__ import annotations

from typing import Any

import httpx

from .context import get_correlation_context


class CorrelatedHttpClient:
    """
    HTTP client that automatically propagates correlation headers.

    Use this client for all inter-service communication to ensure
    request tracing works across service boundaries.

    Example:
        ```python
        client = CorrelatedHttpClient(base_url="http://retrieval:8002")
        async with client:
            response = await client.get("/api/v1/retrieve")
        ```
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> None:
        """
        Initialize the correlated HTTP client.

        Args:
            base_url: Base URL for requests.
            timeout: Request timeout in seconds.
            **kwargs: Additional arguments passed to httpx.AsyncClient.
        """
        self.base_url = base_url
        self.timeout = timeout
        self._client_kwargs = kwargs
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "CorrelatedHttpClient":
        """Enter async context."""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            **self._client_kwargs,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Exit async context."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_headers(self, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
        """
        Build headers including correlation context.

        Args:
            extra_headers: Additional headers to include.

        Returns:
            Combined headers dict.
        """
        headers = dict(extra_headers) if extra_headers else {}

        # Add correlation headers from context
        ctx = get_correlation_context()
        if ctx:
            headers.update(ctx.to_headers())

        return headers

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        GET request with correlation headers.

        Args:
            path: Request path.
            params: Query parameters.
            headers: Additional headers.
            **kwargs: Additional arguments for httpx.

        Returns:
            HTTP response.
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context.")
        return await self._client.get(
            path,
            params=params,
            headers=self._get_headers(headers),
            **kwargs,
        )

    async def post(
        self,
        path: str,
        json: Any = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        POST request with correlation headers.

        Args:
            path: Request path.
            json: JSON body.
            data: Form data.
            headers: Additional headers.
            **kwargs: Additional arguments for httpx.

        Returns:
            HTTP response.
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context.")
        return await self._client.post(
            path,
            json=json,
            data=data,
            headers=self._get_headers(headers),
            **kwargs,
        )

    async def put(
        self,
        path: str,
        json: Any = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        PUT request with correlation headers.

        Args:
            path: Request path.
            json: JSON body.
            data: Form data.
            headers: Additional headers.
            **kwargs: Additional arguments for httpx.

        Returns:
            HTTP response.
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context.")
        return await self._client.put(
            path,
            json=json,
            data=data,
            headers=self._get_headers(headers),
            **kwargs,
        )

    async def delete(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        DELETE request with correlation headers.

        Args:
            path: Request path.
            headers: Additional headers.
            **kwargs: Additional arguments for httpx.

        Returns:
            HTTP response.
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context.")
        return await self._client.delete(
            path,
            headers=self._get_headers(headers),
            **kwargs,
        )


def create_service_client(
    service_name: str,
    base_url: str,
    timeout: float = 30.0,
    **kwargs: Any,
) -> CorrelatedHttpClient:
    """
    Create HTTP client for inter-service communication.

    Args:
        service_name: Name of the target service (for logging).
        base_url: Base URL of the service.
        timeout: Request timeout in seconds.
        **kwargs: Additional arguments for the client.

    Returns:
        Configured CorrelatedHttpClient.
    """
    return CorrelatedHttpClient(
        base_url=base_url,
        timeout=timeout,
        **kwargs,
    )
```

**Step 4: Update __init__.py**

```python
# services/shared/observability/correlation/__init__.py
"""Correlation ID propagation for distributed tracing."""

from .context import (
    CorrelationContext,
    get_correlation_context,
    set_correlation_context,
    clear_correlation_context,
)
from .middleware import CorrelationMiddleware
from .http_client import CorrelatedHttpClient, create_service_client

__all__ = [
    "CorrelationContext",
    "get_correlation_context",
    "set_correlation_context",
    "clear_correlation_context",
    "CorrelationMiddleware",
    "CorrelatedHttpClient",
    "create_service_client",
]
```

**Step 5: Run test to verify it passes**

Run: `cd services/shared/observability && python -m pytest correlation/tests/test_http_client.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add services/shared/observability/correlation/
git commit -m "$(cat <<'EOF'
feat(observability): add CorrelatedHttpClient for header propagation

Implements US-10.3.1 AC-4: HTTP clients automatically inject correlation headers.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Create Celery Correlation Integration

**Files:**
- Create: `services/shared/observability/correlation/celery.py`
- Test: `services/shared/observability/correlation/tests/test_celery.py`

**Step 1: Write the failing test for Celery integration**

```python
# services/shared/observability/correlation/tests/test_celery.py
"""Tests for Celery correlation integration."""

import pytest
from unittest.mock import MagicMock, patch

from correlation.celery import (
    inject_correlation_to_task,
    extract_correlation_from_task,
    setup_celery_correlation_signals,
)
from correlation.context import (
    CorrelationContext,
    get_correlation_context,
    set_correlation_context,
    clear_correlation_context,
)


@pytest.fixture
def correlation_context():
    """Set up correlation context."""
    ctx = CorrelationContext(
        request_id="req-123",
        trace_id="trace-456",
        tenant_id="tenant-789",
        user_id_hash="abc123",
    )
    set_correlation_context(ctx)
    yield ctx
    clear_correlation_context()


class TestInjectCorrelationToTask:
    """Tests for inject_correlation_to_task."""

    def test_injects_correlation_into_headers(self, correlation_context):
        """Should inject correlation context into task headers."""
        headers = {}

        inject_correlation_to_task(headers)

        assert "correlation_context" in headers
        data = headers["correlation_context"]
        assert data["request_id"] == "req-123"
        assert data["trace_id"] == "trace-456"
        assert data["tenant_id"] == "tenant-789"
        assert data["user_id_hash"] == "abc123"

    def test_handles_no_correlation_context(self):
        """Should handle case when no correlation context is set."""
        clear_correlation_context()
        headers = {}

        inject_correlation_to_task(headers)

        assert "correlation_context" not in headers

    def test_preserves_existing_headers(self, correlation_context):
        """Should preserve existing headers."""
        headers = {"existing": "value"}

        inject_correlation_to_task(headers)

        assert headers["existing"] == "value"
        assert "correlation_context" in headers


class TestExtractCorrelationFromTask:
    """Tests for extract_correlation_from_task."""

    def test_extracts_correlation_from_headers(self):
        """Should extract and set correlation context from headers."""
        clear_correlation_context()
        headers = {
            "correlation_context": {
                "request_id": "req-123",
                "trace_id": "trace-456",
                "tenant_id": "tenant-789",
                "user_id_hash": "abc123",
            }
        }

        extract_correlation_from_task(headers, task_id="task-001")

        ctx = get_correlation_context()
        assert ctx is not None
        assert ctx.request_id == "req-123"
        assert ctx.trace_id == "trace-456"
        assert ctx.tenant_id == "tenant-789"

        clear_correlation_context()

    def test_generates_context_from_task_id_when_no_headers(self):
        """Should generate context using task_id when no correlation headers."""
        clear_correlation_context()
        headers = {}

        extract_correlation_from_task(headers, task_id="task-001")

        ctx = get_correlation_context()
        assert ctx is not None
        assert ctx.request_id == "task-001"
        assert ctx.trace_id == "task-001"

        clear_correlation_context()

    def test_uses_tenant_id_from_kwargs_as_fallback(self):
        """Should use tenant_id from kwargs if not in headers."""
        clear_correlation_context()
        headers = {}

        extract_correlation_from_task(
            headers,
            task_id="task-001",
            tenant_id="fallback-tenant"
        )

        ctx = get_correlation_context()
        assert ctx.tenant_id == "fallback-tenant"

        clear_correlation_context()
```

**Step 2: Run test to verify it fails**

Run: `cd services/shared/observability && python -m pytest correlation/tests/test_celery.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'correlation.celery'"

**Step 3: Write minimal implementation**

```python
# services/shared/observability/correlation/celery.py
"""Celery integration for correlation context propagation."""

from __future__ import annotations

from typing import Any

import structlog

from .context import (
    CorrelationContext,
    clear_correlation_context,
    get_correlation_context,
    set_correlation_context,
)

logger = structlog.get_logger(__name__)

# Key for storing correlation context in Celery task headers
CORRELATION_HEADER_KEY = "correlation_context"


def inject_correlation_to_task(headers: dict[str, Any]) -> None:
    """
    Inject correlation context into Celery task headers.

    Call this before publishing a task to propagate context.

    Args:
        headers: Celery task headers dict to inject into.
    """
    ctx = get_correlation_context()
    if ctx is None:
        return

    headers[CORRELATION_HEADER_KEY] = {
        "request_id": ctx.request_id,
        "trace_id": ctx.trace_id,
        "tenant_id": ctx.tenant_id,
        "user_id_hash": ctx.user_id_hash,
    }


def extract_correlation_from_task(
    headers: dict[str, Any],
    task_id: str,
    tenant_id: str | None = None,
) -> None:
    """
    Extract correlation context from Celery task headers.

    Call this at the start of task execution.

    Args:
        headers: Celery task headers.
        task_id: The Celery task ID (used as fallback request_id).
        tenant_id: Optional tenant_id from task kwargs (fallback).
    """
    correlation_data = headers.get(CORRELATION_HEADER_KEY)

    if correlation_data:
        ctx = CorrelationContext(
            request_id=correlation_data.get("request_id", task_id),
            trace_id=correlation_data.get("trace_id", task_id),
            tenant_id=correlation_data.get("tenant_id", tenant_id),
            user_id_hash=correlation_data.get("user_id_hash"),
        )
    else:
        # Generate new context for task without parent context
        ctx = CorrelationContext(
            request_id=task_id,
            trace_id=task_id,
            tenant_id=tenant_id,
        )

    set_correlation_context(ctx)

    # Bind to structlog
    structlog.contextvars.bind_contextvars(
        request_id=ctx.request_id,
        trace_id=ctx.trace_id,
        tenant_id=ctx.tenant_id or "unknown",
        task_id=task_id,
    )


def cleanup_correlation_for_task() -> None:
    """
    Clean up correlation context after task completion.

    Call this when the task finishes.
    """
    structlog.contextvars.unbind_contextvars(
        "request_id", "trace_id", "tenant_id", "task_id"
    )
    clear_correlation_context()


def setup_celery_correlation_signals(celery_app: Any) -> None:
    """
    Set up Celery signals for automatic correlation propagation.

    This connects signal handlers that automatically inject correlation
    context when publishing tasks and extract it when executing tasks.

    Args:
        celery_app: The Celery application instance.
    """
    from celery.signals import before_task_publish, task_postrun, task_prerun

    @before_task_publish.connect
    def propagate_correlation_to_task(
        headers: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Propagate correlation context to Celery task headers."""
        if headers is not None:
            inject_correlation_to_task(headers)

    @task_prerun.connect
    def setup_correlation_for_task(
        task_id: str,
        task: Any,
        args: tuple,
        kwargs: dict,
        **signal_kwargs: Any,
    ) -> None:
        """Set up correlation context at start of Celery task."""
        # Check for correlation in task headers
        request = task.request
        headers = getattr(request, "headers", {}) or {}

        # Get tenant_id from kwargs as fallback
        tenant_id = kwargs.get("tenant_id")

        extract_correlation_from_task(headers, task_id, tenant_id)

    @task_postrun.connect
    def cleanup_correlation_after_task(**kwargs: Any) -> None:
        """Clean up correlation context after task."""
        cleanup_correlation_for_task()

    logger.info("Celery correlation signals configured")
```

**Step 4: Update __init__.py**

```python
# services/shared/observability/correlation/__init__.py
"""Correlation ID propagation for distributed tracing."""

from .context import (
    CorrelationContext,
    get_correlation_context,
    set_correlation_context,
    clear_correlation_context,
)
from .middleware import CorrelationMiddleware
from .http_client import CorrelatedHttpClient, create_service_client
from .celery import (
    inject_correlation_to_task,
    extract_correlation_from_task,
    cleanup_correlation_for_task,
    setup_celery_correlation_signals,
)

__all__ = [
    "CorrelationContext",
    "get_correlation_context",
    "set_correlation_context",
    "clear_correlation_context",
    "CorrelationMiddleware",
    "CorrelatedHttpClient",
    "create_service_client",
    "inject_correlation_to_task",
    "extract_correlation_from_task",
    "cleanup_correlation_for_task",
    "setup_celery_correlation_signals",
]
```

**Step 5: Run test to verify it passes**

Run: `cd services/shared/observability && python -m pytest correlation/tests/test_celery.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add services/shared/observability/correlation/
git commit -m "$(cat <<'EOF'
feat(observability): add Celery correlation integration

Implements US-10.3.1 AC-4: Celery tasks receive and propagate correlation context.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Integrate Correlation into Ingestion Service

**Files:**
- Modify: `services/ingestion/api/main.py`
- Modify: `services/ingestion/tasks/celery_app.py`

**Step 1: Read current files**

Review: `services/ingestion/api/main.py` and `services/ingestion/tasks/celery_app.py`

**Step 2: Update ingestion service main.py**

In `services/ingestion/api/main.py`, add the CorrelationMiddleware after imports and before other middleware:

Find the middleware setup section and add:

```python
from shared.observability.correlation import CorrelationMiddleware

# In create_app function, add before other middleware:
app.add_middleware(
    CorrelationMiddleware,
    service_name="ingestion-service",
)
```

Note: `CorrelationMiddleware` should be added BEFORE `RequestLoggingMiddleware` since middleware is executed in reverse order (first added = outermost).

**Step 3: Update ingestion Celery app**

In `services/ingestion/tasks/celery_app.py`, add correlation signal setup:

```python
from shared.observability.correlation import setup_celery_correlation_signals

# After celery app creation:
setup_celery_correlation_signals(app)
```

**Step 4: Run existing tests to verify no regressions**

Run: `cd services/ingestion && python -m pytest tests/ -v --tb=short`
Expected: PASS (all existing tests should still pass)

**Step 5: Commit**

```bash
git add services/ingestion/api/main.py services/ingestion/tasks/celery_app.py
git commit -m "$(cat <<'EOF'
feat(ingestion): integrate correlation middleware and Celery signals

Implements US-10.3.1 AC-3: Adds CorrelationMiddleware to ingestion service
and configures Celery for correlation propagation.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Integrate Correlation into Retrieval Service

**Files:**
- Modify: `services/retrieval/api/main.py`

**Step 1: Read current file**

Review: `services/retrieval/api/main.py`

**Step 2: Update retrieval service main.py**

Add the CorrelationMiddleware in the create_app function:

```python
from shared.observability.correlation import CorrelationMiddleware

# In create_app function:
app.add_middleware(
    CorrelationMiddleware,
    service_name="retrieval-service",
)
```

**Step 3: Run existing tests to verify no regressions**

Run: `cd services/retrieval && python -m pytest tests/ -v --tb=short`
Expected: PASS

**Step 4: Commit**

```bash
git add services/retrieval/api/main.py
git commit -m "$(cat <<'EOF'
feat(retrieval): integrate correlation middleware

Implements US-10.3.1 AC-3: Adds CorrelationMiddleware to retrieval service.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Integrate Correlation into Orchestrator Service

**Files:**
- Modify: `services/orchestrator/api/app.py`
- Modify: `services/orchestrator/gateway/client.py` (to use CorrelatedHttpClient)

**Step 1: Read current files**

Review: `services/orchestrator/api/app.py` and `services/orchestrator/gateway/client.py`

**Step 2: Update orchestrator app.py**

Replace the inline middleware with CorrelationMiddleware:

```python
from shared.observability.correlation import CorrelationMiddleware

# In create_app function, replace the inline @app.middleware("http") with:
app.add_middleware(
    CorrelationMiddleware,
    service_name="orchestrator-service",
)
```

Remove the inline `log_requests` middleware since `CorrelationMiddleware` provides similar functionality.

**Step 3: Update orchestrator gateway client to propagate headers**

In `services/orchestrator/gateway/client.py`, modify the httpx client to include correlation headers:

Add import and modify request methods:

```python
from shared.observability.correlation import get_correlation_context

# In request methods, get headers:
def _get_correlation_headers(self) -> dict[str, str]:
    """Get correlation headers from current context."""
    ctx = get_correlation_context()
    if ctx:
        return ctx.to_headers()
    return {}

# In chat_completion and other methods, merge headers:
headers = self._get_correlation_headers()
# Pass headers to httpx requests
```

**Step 4: Run existing tests to verify no regressions**

Run: `cd services/orchestrator && python -m pytest tests/ -v --tb=short`
Expected: PASS

**Step 5: Commit**

```bash
git add services/orchestrator/api/app.py services/orchestrator/gateway/client.py
git commit -m "$(cat <<'EOF'
feat(orchestrator): integrate correlation middleware and propagate headers

Implements US-10.3.1 AC-3, AC-4: Adds CorrelationMiddleware and propagates
correlation headers to LLM gateway calls.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Write Integration Tests

**Files:**
- Create: `services/shared/observability/correlation/tests/test_integration.py`

**Step 1: Write integration tests for cross-service correlation**

```python
# services/shared/observability/correlation/tests/test_integration.py
"""Integration tests for correlation propagation."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx

from correlation.middleware import CorrelationMiddleware
from correlation.http_client import CorrelatedHttpClient
from correlation.context import (
    CorrelationContext,
    get_correlation_context,
    set_correlation_context,
    clear_correlation_context,
)
from correlation.celery import (
    inject_correlation_to_task,
    extract_correlation_from_task,
    cleanup_correlation_for_task,
)


class TestMiddlewareToHttpClientPropagation:
    """Tests for correlation propagation from middleware to HTTP client."""

    @pytest.fixture
    def downstream_app(self):
        """Create a downstream service that captures headers."""
        app = FastAPI()
        captured_headers = {}

        @app.post("/api/search")
        async def search(request):
            # Capture correlation headers
            captured_headers.update({
                "x-request-id": request.headers.get("x-request-id"),
                "x-trace-id": request.headers.get("x-trace-id"),
                "x-tenant-id": request.headers.get("x-tenant-id"),
            })
            return {"results": []}

        return app, captured_headers

    @pytest.mark.asyncio
    async def test_correlation_propagates_through_http_client(self):
        """Correlation from middleware should propagate via HTTP client."""
        # Simulate middleware setting context
        ctx = CorrelationContext(
            request_id="test-req-123",
            trace_id="test-trace-456",
            tenant_id="tenant-789",
        )
        set_correlation_context(ctx)

        captured_headers = {}

        async def mock_post(*args, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = {"results": []}
            return response

        with patch.object(httpx.AsyncClient, "post", side_effect=mock_post):
            client = CorrelatedHttpClient(base_url="http://downstream:8000")
            async with client:
                await client.post("/api/search", json={"query": "test"})

        assert captured_headers.get("X-Request-ID") == "test-req-123"
        assert captured_headers.get("X-Trace-ID") == "test-trace-456"
        assert captured_headers.get("X-Tenant-ID") == "tenant-789"

        clear_correlation_context()


class TestCeleryCorrelationPropagation:
    """Tests for correlation propagation through Celery tasks."""

    def test_full_celery_propagation_cycle(self):
        """Should propagate correlation through Celery task lifecycle."""
        # Set up parent context (e.g., from HTTP request)
        parent_ctx = CorrelationContext(
            request_id="http-req-123",
            trace_id="http-trace-456",
            tenant_id="tenant-789",
            user_id_hash="user-hash-abc",
        )
        set_correlation_context(parent_ctx)

        # Simulate before_task_publish signal
        task_headers = {}
        inject_correlation_to_task(task_headers)

        # Clear context (simulating different process/worker)
        clear_correlation_context()
        assert get_correlation_context() is None

        # Simulate task_prerun signal (worker receiving task)
        extract_correlation_from_task(task_headers, task_id="celery-task-001")

        # Verify context is restored
        restored_ctx = get_correlation_context()
        assert restored_ctx is not None
        assert restored_ctx.request_id == "http-req-123"
        assert restored_ctx.trace_id == "http-trace-456"
        assert restored_ctx.tenant_id == "tenant-789"

        # Simulate task_postrun signal
        cleanup_correlation_for_task()

        # Verify cleanup
        assert get_correlation_context() is None


class TestLogJoinability:
    """Tests to verify logs are joinable by request_id."""

    @patch("correlation.middleware.structlog")
    def test_logs_include_request_id(self, mock_structlog):
        """All logs should include request_id for joinability."""
        mock_contextvars = MagicMock()
        mock_structlog.contextvars = mock_contextvars
        mock_structlog.get_logger.return_value = MagicMock()

        app = FastAPI()
        app.add_middleware(CorrelationMiddleware, service_name="test-service")

        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get(
            "/test",
            headers={"X-Request-ID": "joinable-req-123"}
        )

        assert response.status_code == 200

        # Verify structlog was bound with request_id
        bind_calls = mock_contextvars.bind_contextvars.call_args_list
        assert len(bind_calls) > 0

        bound_kwargs = bind_calls[0][1]
        assert bound_kwargs.get("request_id") == "joinable-req-123"
```

**Step 2: Run integration tests**

Run: `cd services/shared/observability && python -m pytest correlation/tests/test_integration.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add services/shared/observability/correlation/tests/test_integration.py
git commit -m "$(cat <<'EOF'
test(observability): add correlation integration tests

Implements US-10.3.1 AC-5: Tests verify log joinability by request_id
and cross-service/Celery correlation propagation.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Run Full Test Suite and Update User Story

**Files:**
- Modify: `workflow/refined/10-architectural-improvements/US-10.3.1-strict-correlation-id-propagation.md`

**Step 1: Run all correlation tests**

Run: `cd services/shared/observability && python -m pytest correlation/tests/ -v`
Expected: All tests PASS

**Step 2: Run service tests to verify no regressions**

Run: `make test`
Expected: All tests PASS

**Step 3: Update user story status**

Move the user story to done and update status:

```bash
mv workflow/refined/10-architectural-improvements/US-10.3.1-strict-correlation-id-propagation.md \
   workflow/done/10-architectural-improvements/US-10.3.1-strict-correlation-id-propagation.md
```

Update the status in the file from `Draft` to `Done`.

**Step 4: Commit**

```bash
git add workflow/
git commit -m "$(cat <<'EOF'
docs: mark US-10.3.1 strict correlation ID propagation as done

All acceptance criteria completed:
- AC-1: Standardized headers (X-Request-ID, X-Trace-ID, X-Tenant-ID, X-User-ID-Hash)
- AC-2: ID generation with UUID v4, preserving existing valid IDs
- AC-3: CorrelationMiddleware for all services
- AC-4: HTTP client and Celery integration
- AC-5: Logs joinable by request_id

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Summary

This plan implements US-10.3.1 in 9 tasks:

| Task | Description | Files |
|------|-------------|-------|
| 1 | Create CorrelationContext module | `correlation/context.py`, tests |
| 2 | Create CorrelationMiddleware | `correlation/middleware.py`, tests |
| 3 | Create CorrelatedHttpClient | `correlation/http_client.py`, tests |
| 4 | Create Celery integration | `correlation/celery.py`, tests |
| 5 | Integrate into Ingestion Service | `ingestion/api/main.py`, `tasks/celery_app.py` |
| 6 | Integrate into Retrieval Service | `retrieval/api/main.py` |
| 7 | Integrate into Orchestrator Service | `orchestrator/api/app.py`, `gateway/client.py` |
| 8 | Write integration tests | `correlation/tests/test_integration.py` |
| 9 | Run full test suite and update docs | `workflow/` |

Each task follows TDD: write failing test, implement, verify, commit.
