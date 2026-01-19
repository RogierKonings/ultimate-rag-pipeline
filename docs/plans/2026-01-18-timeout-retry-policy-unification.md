# Timeout & Retry Policy Unification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Standardize timeout and retry policies across all services with a shared configuration module and unified patterns.

**Architecture:** Create a shared timeout configuration module in `services/shared/config/timeouts.py` with all timeout values centralized and environment-variable-overridable. Create a shared retry utility in `services/shared/resilience/retry.py` using asyncio patterns. Update all services to import from shared config and use the retry utility.

**Tech Stack:** Python 3.11+, asyncio, Pydantic, structlog

**Reference Spec:** `workflow/refined/10-architectural-improvements/US-10.2.4-timeout-retry-policy-unification.md`

---

## Task 1: Create Shared Timeout Configuration Module

**Files:**
- Create: `services/shared/config/__init__.py`
- Create: `services/shared/config/timeouts.py`

**Step 1: Create the config directory**

```bash
mkdir -p services/shared/config
```

**Step 2: Create timeouts.py with all timeout values**

Create `services/shared/config/timeouts.py`:

```python
"""Standardized timeout and retry configuration.

All timeouts are in milliseconds.
All services should import from this module for consistency.

IMPORTANT: Inner timeouts must be shorter than outer timeouts
to allow proper error handling and graceful degradation.

Cascade hierarchy (outer -> inner):
  RAG E2E (30000ms)
    ├── Retrieval Total (15000ms)
    │   ├── Embedding Request (5000ms)
    │   ├── Qdrant Query (3000ms)
    │   ├── OpenSearch Query (3000ms)
    │   └── Reranker Batch (8000ms)
    └── LLM Generation (25000ms)
        └── LLM Gateway Request (20000ms)

  Ingestion Document (300000ms = 5min)
    ├── Parsing (60000ms)
    ├── Embedding Batch (30000ms)
    ├── Qdrant Upsert (10000ms)
    └── OpenSearch Index (10000ms)
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class TimeoutConfig:
    """Configuration for a single operation timeout.

    Attributes:
        timeout_ms: Timeout in milliseconds
        retries: Number of retry attempts (0 = no retries)
        backoff_base_ms: Base delay for exponential backoff
        backoff_max_ms: Maximum delay for exponential backoff
        idempotent: Whether the operation is safe to retry
    """

    timeout_ms: int
    retries: int
    backoff_base_ms: int = 100
    backoff_max_ms: int = 5000
    idempotent: bool = True


# =============================================================================
# Retrieval Service Timeouts
# =============================================================================

RETRIEVAL_EMBEDDING_TIMEOUT = TimeoutConfig(
    timeout_ms=int(os.getenv("RETRIEVAL_EMBEDDING_TIMEOUT_MS", "5000")),
    retries=int(os.getenv("RETRIEVAL_EMBEDDING_RETRIES", "2")),
    idempotent=True,
)

RETRIEVAL_QDRANT_TIMEOUT = TimeoutConfig(
    timeout_ms=int(os.getenv("RETRIEVAL_QDRANT_TIMEOUT_MS", "3000")),
    retries=int(os.getenv("RETRIEVAL_QDRANT_RETRIES", "1")),
    idempotent=True,
)

RETRIEVAL_OPENSEARCH_TIMEOUT = TimeoutConfig(
    timeout_ms=int(os.getenv("RETRIEVAL_OPENSEARCH_TIMEOUT_MS", "3000")),
    retries=int(os.getenv("RETRIEVAL_OPENSEARCH_RETRIES", "1")),
    idempotent=True,
)

RETRIEVAL_RERANKER_TIMEOUT = TimeoutConfig(
    timeout_ms=int(os.getenv("RETRIEVAL_RERANKER_TIMEOUT_MS", "8000")),
    retries=int(os.getenv("RETRIEVAL_RERANKER_RETRIES", "1")),
    idempotent=True,
)

RETRIEVAL_TOTAL_TIMEOUT = TimeoutConfig(
    timeout_ms=int(os.getenv("RETRIEVAL_TOTAL_TIMEOUT_MS", "15000")),
    retries=0,  # No retry at this level
    idempotent=True,
)

# =============================================================================
# Orchestrator Service Timeouts
# =============================================================================

ORCHESTRATOR_RETRIEVAL_TIMEOUT = TimeoutConfig(
    timeout_ms=int(os.getenv("ORCHESTRATOR_RETRIEVAL_TIMEOUT_MS", "20000")),
    retries=int(os.getenv("ORCHESTRATOR_RETRIEVAL_RETRIES", "1")),
    idempotent=True,
)

ORCHESTRATOR_LLM_TIMEOUT = TimeoutConfig(
    timeout_ms=int(os.getenv("ORCHESTRATOR_LLM_TIMEOUT_MS", "25000")),
    retries=0,  # LLM calls are not retried (expensive)
    idempotent=False,
)

ORCHESTRATOR_TOTAL_TIMEOUT = TimeoutConfig(
    timeout_ms=int(os.getenv("ORCHESTRATOR_TOTAL_TIMEOUT_MS", "30000")),
    retries=0,
    idempotent=False,
)

# =============================================================================
# Ingestion Service Timeouts
# =============================================================================

INGESTION_PARSING_TIMEOUT = TimeoutConfig(
    timeout_ms=int(os.getenv("INGESTION_PARSING_TIMEOUT_MS", "60000")),
    retries=0,  # Parsing is idempotent but not retried (deterministic)
    idempotent=True,
)

INGESTION_EMBEDDING_TIMEOUT = TimeoutConfig(
    timeout_ms=int(os.getenv("INGESTION_EMBEDDING_TIMEOUT_MS", "30000")),
    retries=int(os.getenv("INGESTION_EMBEDDING_RETRIES", "2")),
    idempotent=True,
)

INGESTION_QDRANT_UPSERT_TIMEOUT = TimeoutConfig(
    timeout_ms=int(os.getenv("INGESTION_QDRANT_UPSERT_TIMEOUT_MS", "10000")),
    retries=int(os.getenv("INGESTION_QDRANT_UPSERT_RETRIES", "2")),
    idempotent=True,  # Upsert is idempotent
)

INGESTION_OPENSEARCH_INDEX_TIMEOUT = TimeoutConfig(
    timeout_ms=int(os.getenv("INGESTION_OPENSEARCH_INDEX_TIMEOUT_MS", "10000")),
    retries=int(os.getenv("INGESTION_OPENSEARCH_INDEX_RETRIES", "2")),
    idempotent=True,
)

INGESTION_DOCUMENT_TIMEOUT = TimeoutConfig(
    timeout_ms=int(os.getenv("INGESTION_DOCUMENT_TIMEOUT_MS", "300000")),  # 5 min
    retries=int(os.getenv("INGESTION_DOCUMENT_RETRIES", "3")),
    idempotent=True,
)

# =============================================================================
# Shared/Infrastructure Timeouts
# =============================================================================

REDIS_OPERATION_TIMEOUT = TimeoutConfig(
    timeout_ms=int(os.getenv("REDIS_OPERATION_TIMEOUT_MS", "1000")),
    retries=int(os.getenv("REDIS_OPERATION_RETRIES", "1")),
    idempotent=True,
)

POSTGRES_QUERY_TIMEOUT = TimeoutConfig(
    timeout_ms=int(os.getenv("POSTGRES_QUERY_TIMEOUT_MS", "5000")),
    retries=int(os.getenv("POSTGRES_QUERY_RETRIES", "1")),
    idempotent=True,  # For SELECT queries
)

HTTP_CONNECTION_TIMEOUT = TimeoutConfig(
    timeout_ms=int(os.getenv("HTTP_CONNECTION_TIMEOUT_MS", "5000")),
    retries=0,  # Connection timeouts don't retry
    idempotent=True,
)

# =============================================================================
# Timeout Registry
# =============================================================================

ALL_TIMEOUTS: dict[str, TimeoutConfig] = {
    # Retrieval
    "retrieval_embedding": RETRIEVAL_EMBEDDING_TIMEOUT,
    "retrieval_qdrant": RETRIEVAL_QDRANT_TIMEOUT,
    "retrieval_opensearch": RETRIEVAL_OPENSEARCH_TIMEOUT,
    "retrieval_reranker": RETRIEVAL_RERANKER_TIMEOUT,
    "retrieval_total": RETRIEVAL_TOTAL_TIMEOUT,
    # Orchestrator
    "orchestrator_retrieval": ORCHESTRATOR_RETRIEVAL_TIMEOUT,
    "orchestrator_llm": ORCHESTRATOR_LLM_TIMEOUT,
    "orchestrator_total": ORCHESTRATOR_TOTAL_TIMEOUT,
    # Ingestion
    "ingestion_parsing": INGESTION_PARSING_TIMEOUT,
    "ingestion_embedding": INGESTION_EMBEDDING_TIMEOUT,
    "ingestion_qdrant_upsert": INGESTION_QDRANT_UPSERT_TIMEOUT,
    "ingestion_opensearch_index": INGESTION_OPENSEARCH_INDEX_TIMEOUT,
    "ingestion_document": INGESTION_DOCUMENT_TIMEOUT,
    # Infrastructure
    "redis_operation": REDIS_OPERATION_TIMEOUT,
    "postgres_query": POSTGRES_QUERY_TIMEOUT,
    "http_connection": HTTP_CONNECTION_TIMEOUT,
}


def get_timeout(name: str) -> TimeoutConfig:
    """Get timeout configuration by name.

    Args:
        name: Timeout configuration name from ALL_TIMEOUTS

    Returns:
        TimeoutConfig for the specified operation

    Raises:
        ValueError: If timeout name is not found
    """
    if name not in ALL_TIMEOUTS:
        raise ValueError(f"Unknown timeout: {name}. Available: {list(ALL_TIMEOUTS.keys())}")
    return ALL_TIMEOUTS[name]


def get_timeout_seconds(name: str) -> float:
    """Get timeout value in seconds (convenience method).

    Args:
        name: Timeout configuration name from ALL_TIMEOUTS

    Returns:
        Timeout value in seconds as float
    """
    return get_timeout(name).timeout_ms / 1000.0
```

**Step 3: Create __init__.py**

Create `services/shared/config/__init__.py`:

```python
"""Shared configuration module.

This module provides centralized configuration for:
- Timeouts and retry policies
- Configuration validation
"""

from .timeouts import (
    ALL_TIMEOUTS,
    HTTP_CONNECTION_TIMEOUT,
    INGESTION_DOCUMENT_TIMEOUT,
    INGESTION_EMBEDDING_TIMEOUT,
    INGESTION_OPENSEARCH_INDEX_TIMEOUT,
    INGESTION_PARSING_TIMEOUT,
    INGESTION_QDRANT_UPSERT_TIMEOUT,
    ORCHESTRATOR_LLM_TIMEOUT,
    ORCHESTRATOR_RETRIEVAL_TIMEOUT,
    ORCHESTRATOR_TOTAL_TIMEOUT,
    POSTGRES_QUERY_TIMEOUT,
    REDIS_OPERATION_TIMEOUT,
    RETRIEVAL_EMBEDDING_TIMEOUT,
    RETRIEVAL_OPENSEARCH_TIMEOUT,
    RETRIEVAL_QDRANT_TIMEOUT,
    RETRIEVAL_RERANKER_TIMEOUT,
    RETRIEVAL_TOTAL_TIMEOUT,
    TimeoutConfig,
    get_timeout,
    get_timeout_seconds,
)

__all__ = [
    # Core types
    "TimeoutConfig",
    # Retrieval timeouts
    "RETRIEVAL_EMBEDDING_TIMEOUT",
    "RETRIEVAL_QDRANT_TIMEOUT",
    "RETRIEVAL_OPENSEARCH_TIMEOUT",
    "RETRIEVAL_RERANKER_TIMEOUT",
    "RETRIEVAL_TOTAL_TIMEOUT",
    # Orchestrator timeouts
    "ORCHESTRATOR_RETRIEVAL_TIMEOUT",
    "ORCHESTRATOR_LLM_TIMEOUT",
    "ORCHESTRATOR_TOTAL_TIMEOUT",
    # Ingestion timeouts
    "INGESTION_PARSING_TIMEOUT",
    "INGESTION_EMBEDDING_TIMEOUT",
    "INGESTION_QDRANT_UPSERT_TIMEOUT",
    "INGESTION_OPENSEARCH_INDEX_TIMEOUT",
    "INGESTION_DOCUMENT_TIMEOUT",
    # Infrastructure timeouts
    "REDIS_OPERATION_TIMEOUT",
    "POSTGRES_QUERY_TIMEOUT",
    "HTTP_CONNECTION_TIMEOUT",
    # Utilities
    "ALL_TIMEOUTS",
    "get_timeout",
    "get_timeout_seconds",
]
```

**Step 4: Commit**

```bash
git add services/shared/config/
git commit -m "feat(shared): add centralized timeout configuration module

Introduces services/shared/config/timeouts.py with:
- TimeoutConfig dataclass for timeout + retry settings
- Standardized timeout values for all services
- Environment variable overrides for all values
- Cascade hierarchy documentation
- Registry for programmatic access"
```

---

## Task 2: Create Shared Retry Utility

**Files:**
- Create: `services/shared/resilience/__init__.py`
- Create: `services/shared/resilience/retry.py`

**Step 1: Create the resilience directory**

```bash
mkdir -p services/shared/resilience
```

**Step 2: Create retry.py**

Create `services/shared/resilience/retry.py`:

```python
"""Retry utilities with exponential backoff.

Provides standardized retry behavior across all services with:
- Exponential backoff with jitter
- Configurable via TimeoutConfig
- Structured logging
- Async-first design
"""

import asyncio
import random
import structlog
from functools import wraps
from typing import Any, Callable, TypeVar

from shared.config.timeouts import TimeoutConfig

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class RetryExhausted(Exception):
    """Raised when all retry attempts have been exhausted.

    Attributes:
        operation: Name of the operation that failed
        attempts: Total number of attempts made
        last_error: The final exception that caused failure
    """

    def __init__(self, operation: str, attempts: int, last_error: Exception):
        self.operation = operation
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"{operation} failed after {attempts} attempts: {last_error}")


class TimeoutExceeded(Exception):
    """Raised when operation timeout is exceeded.

    Attributes:
        operation: Name of the operation that timed out
        timeout_ms: The timeout value in milliseconds
    """

    def __init__(self, operation: str, timeout_ms: int):
        self.operation = operation
        self.timeout_ms = timeout_ms
        super().__init__(f"{operation} timed out after {timeout_ms}ms")


async def with_retry(
    func: Callable[..., T],
    config: TimeoutConfig,
    operation_name: str,
    *args: Any,
    **kwargs: Any,
) -> T:
    """Execute async function with timeout and retry.

    Applies timeout to each attempt and retries with exponential backoff
    on failure. Respects the idempotent flag - non-idempotent operations
    are not retried.

    Args:
        func: Async function to call
        config: Timeout configuration with retry settings
        operation_name: Name for logging and error messages
        *args: Positional arguments to pass to func
        **kwargs: Keyword arguments to pass to func

    Returns:
        Result from func

    Raises:
        RetryExhausted: If all retries fail
        TimeoutExceeded: If timeout exceeded and no retries configured
        Exception: Original exception if non-idempotent operation fails
    """
    last_error: Exception | None = None
    attempts = config.retries + 1 if config.idempotent else 1

    for attempt in range(attempts):
        try:
            result = await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=config.timeout_ms / 1000.0,
            )

            if attempt > 0:
                logger.info(
                    "retry_succeeded",
                    operation=operation_name,
                    attempt=attempt + 1,
                    total_attempts=attempts,
                )

            return result

        except asyncio.TimeoutError as e:
            last_error = TimeoutExceeded(operation_name, config.timeout_ms)
            logger.warning(
                "operation_timeout",
                operation=operation_name,
                attempt=attempt + 1,
                total_attempts=attempts,
                timeout_ms=config.timeout_ms,
            )

        except Exception as e:
            last_error = e
            logger.warning(
                "operation_failed",
                operation=operation_name,
                attempt=attempt + 1,
                total_attempts=attempts,
                error=str(e),
                error_type=type(e).__name__,
            )

        # Calculate backoff if retrying
        if attempt < attempts - 1:
            backoff = _calculate_backoff(
                attempt=attempt,
                base_ms=config.backoff_base_ms,
                max_ms=config.backoff_max_ms,
            )
            logger.debug(
                "retry_backoff",
                operation=operation_name,
                backoff_ms=backoff,
                next_attempt=attempt + 2,
            )
            await asyncio.sleep(backoff / 1000.0)

    if last_error is None:
        last_error = RuntimeError(f"{operation_name} failed with no error recorded")

    raise RetryExhausted(operation_name, attempts, last_error)


def _calculate_backoff(attempt: int, base_ms: int, max_ms: int) -> int:
    """Calculate exponential backoff with jitter.

    Uses exponential backoff (base * 2^attempt) with ±25% jitter
    to prevent thundering herd problems.

    Args:
        attempt: Current attempt number (0-indexed)
        base_ms: Base delay in milliseconds
        max_ms: Maximum delay cap in milliseconds

    Returns:
        Backoff delay in milliseconds
    """
    # Exponential backoff: base * 2^attempt
    backoff = base_ms * (2**attempt)
    # Cap at max
    backoff = min(backoff, max_ms)
    # Add jitter (±25%)
    jitter = backoff * 0.25 * (random.random() * 2 - 1)
    return int(backoff + jitter)


def retry_on_timeout(config: TimeoutConfig, operation_name: str) -> Callable:
    """Decorator for retry with timeout.

    Wraps an async function with timeout and retry logic.
    Non-idempotent operations (config.idempotent=False) are not retried.

    Usage:
        @retry_on_timeout(RETRIEVAL_QDRANT_TIMEOUT, "qdrant_search")
        async def search_qdrant(query):
            ...

    Args:
        config: Timeout configuration
        operation_name: Name for logging

    Returns:
        Decorator function
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await with_retry(func, config, operation_name, *args, **kwargs)

        return wrapper

    return decorator


async def with_timeout(
    func: Callable[..., T],
    timeout_ms: int,
    operation_name: str,
    *args: Any,
    **kwargs: Any,
) -> T:
    """Execute async function with timeout only (no retry).

    Simpler version for operations that should not be retried.

    Args:
        func: Async function to call
        timeout_ms: Timeout in milliseconds
        operation_name: Name for error messages
        *args: Positional arguments to pass to func
        **kwargs: Keyword arguments to pass to func

    Returns:
        Result from func

    Raises:
        TimeoutExceeded: If timeout exceeded
    """
    try:
        return await asyncio.wait_for(
            func(*args, **kwargs),
            timeout=timeout_ms / 1000.0,
        )
    except asyncio.TimeoutError:
        raise TimeoutExceeded(operation_name, timeout_ms)
```

**Step 3: Create __init__.py**

Create `services/shared/resilience/__init__.py`:

```python
"""Shared resilience utilities.

This module provides:
- Retry utilities with exponential backoff
- Timeout handling
- Structured error types
"""

from .retry import (
    RetryExhausted,
    TimeoutExceeded,
    retry_on_timeout,
    with_retry,
    with_timeout,
)

__all__ = [
    "RetryExhausted",
    "TimeoutExceeded",
    "retry_on_timeout",
    "with_retry",
    "with_timeout",
]
```

**Step 4: Commit**

```bash
git add services/shared/resilience/
git commit -m "feat(shared): add retry utility with exponential backoff

Introduces services/shared/resilience/retry.py with:
- with_retry() for async functions with timeout + retry
- retry_on_timeout() decorator for declarative retry
- with_timeout() for timeout-only operations
- Exponential backoff with jitter
- Structured logging via structlog
- RetryExhausted and TimeoutExceeded exceptions"
```

---

## Task 3: Add Timeout Cascade Validation

**Files:**
- Create: `services/shared/config/validation.py`
- Modify: `services/shared/config/__init__.py`

**Step 1: Create validation.py**

Create `services/shared/config/validation.py`:

```python
"""Configuration validation utilities.

Validates that timeout cascade relationships are properly configured
to prevent inner timeouts being longer than outer timeouts.
"""

import structlog

from .timeouts import ALL_TIMEOUTS

logger = structlog.get_logger(__name__)


class ConfigurationError(Exception):
    """Raised when configuration validation fails."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"Configuration validation failed: {errors}")


def validate_timeout_cascade() -> list[str]:
    """Validate that timeout cascade is properly configured.

    Ensures inner timeouts are shorter than outer timeouts to allow
    for proper error handling and graceful degradation.

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []

    # Retrieval cascade: inner operations < total
    retrieval_inner = max(
        ALL_TIMEOUTS["retrieval_embedding"].timeout_ms,
        ALL_TIMEOUTS["retrieval_qdrant"].timeout_ms,
        ALL_TIMEOUTS["retrieval_opensearch"].timeout_ms,
        ALL_TIMEOUTS["retrieval_reranker"].timeout_ms,
    )
    retrieval_total = ALL_TIMEOUTS["retrieval_total"].timeout_ms

    if retrieval_inner >= retrieval_total:
        errors.append(
            f"Retrieval inner timeout ({retrieval_inner}ms) >= "
            f"total timeout ({retrieval_total}ms)"
        )

    # Orchestrator cascade: retrieval call < total
    orch_retrieval = ALL_TIMEOUTS["orchestrator_retrieval"].timeout_ms
    orch_total = ALL_TIMEOUTS["orchestrator_total"].timeout_ms

    if orch_retrieval >= orch_total:
        errors.append(
            f"Orchestrator retrieval timeout ({orch_retrieval}ms) >= "
            f"total timeout ({orch_total}ms)"
        )

    # Cross-service: retrieval total < orchestrator retrieval
    retrieval_total_ms = ALL_TIMEOUTS["retrieval_total"].timeout_ms
    if retrieval_total_ms >= orch_retrieval:
        errors.append(
            f"Retrieval total ({retrieval_total_ms}ms) >= "
            f"orchestrator retrieval timeout ({orch_retrieval}ms)"
        )

    # Ingestion cascade: inner operations < document total
    ingestion_inner = max(
        ALL_TIMEOUTS["ingestion_parsing"].timeout_ms,
        ALL_TIMEOUTS["ingestion_embedding"].timeout_ms,
        ALL_TIMEOUTS["ingestion_qdrant_upsert"].timeout_ms,
        ALL_TIMEOUTS["ingestion_opensearch_index"].timeout_ms,
    )
    ingestion_total = ALL_TIMEOUTS["ingestion_document"].timeout_ms

    if ingestion_inner >= ingestion_total:
        errors.append(
            f"Ingestion inner timeout ({ingestion_inner}ms) >= "
            f"document timeout ({ingestion_total}ms)"
        )

    if errors:
        for error in errors:
            logger.error("timeout_cascade_invalid", error=error)
    else:
        logger.info("timeout_cascade_valid")

    return errors


def validate_on_startup(fail_fast: bool = True) -> list[str]:
    """Run all configuration validations at startup.

    Args:
        fail_fast: If True, raise exception on validation failure

    Returns:
        List of validation errors

    Raises:
        ConfigurationError: If fail_fast=True and validation fails
    """
    errors = validate_timeout_cascade()

    if errors and fail_fast:
        raise ConfigurationError(errors)

    return errors
```

**Step 2: Update __init__.py to export validation**

Add to `services/shared/config/__init__.py`:

```python
from .validation import (
    ConfigurationError,
    validate_on_startup,
    validate_timeout_cascade,
)
```

And add to `__all__`:

```python
    # Validation
    "ConfigurationError",
    "validate_timeout_cascade",
    "validate_on_startup",
```

**Step 3: Commit**

```bash
git add services/shared/config/
git commit -m "feat(shared): add timeout cascade validation

Adds validation to ensure inner timeouts < outer timeouts:
- validate_timeout_cascade() checks all cascade relationships
- validate_on_startup() runs at service startup
- ConfigurationError for validation failures
- Logs validation results via structlog"
```

---

## Task 4: Write Unit Tests for Timeout Config

**Files:**
- Create: `services/shared/config/tests/__init__.py`
- Create: `services/shared/config/tests/test_timeouts.py`

**Step 1: Create test directory**

```bash
mkdir -p services/shared/config/tests
touch services/shared/config/tests/__init__.py
```

**Step 2: Write timeout tests**

Create `services/shared/config/tests/test_timeouts.py`:

```python
"""Tests for timeout configuration module."""

import os
from unittest import mock

import pytest

from shared.config.timeouts import (
    ALL_TIMEOUTS,
    RETRIEVAL_QDRANT_TIMEOUT,
    TimeoutConfig,
    get_timeout,
    get_timeout_seconds,
)


class TestTimeoutConfig:
    """Tests for TimeoutConfig dataclass."""

    def test_default_values(self) -> None:
        """TimeoutConfig should have sensible defaults."""
        config = TimeoutConfig(timeout_ms=1000, retries=2)

        assert config.timeout_ms == 1000
        assert config.retries == 2
        assert config.backoff_base_ms == 100
        assert config.backoff_max_ms == 5000
        assert config.idempotent is True

    def test_immutable(self) -> None:
        """TimeoutConfig should be immutable (frozen)."""
        config = TimeoutConfig(timeout_ms=1000, retries=2)

        with pytest.raises(AttributeError):
            config.timeout_ms = 2000  # type: ignore

    def test_custom_values(self) -> None:
        """TimeoutConfig should accept custom values."""
        config = TimeoutConfig(
            timeout_ms=5000,
            retries=3,
            backoff_base_ms=200,
            backoff_max_ms=10000,
            idempotent=False,
        )

        assert config.timeout_ms == 5000
        assert config.retries == 3
        assert config.backoff_base_ms == 200
        assert config.backoff_max_ms == 10000
        assert config.idempotent is False


class TestGetTimeout:
    """Tests for get_timeout function."""

    def test_get_known_timeout(self) -> None:
        """get_timeout should return config for known names."""
        config = get_timeout("retrieval_qdrant")

        assert config == RETRIEVAL_QDRANT_TIMEOUT
        assert config.timeout_ms == 3000

    def test_get_unknown_timeout_raises(self) -> None:
        """get_timeout should raise for unknown names."""
        with pytest.raises(ValueError) as exc_info:
            get_timeout("unknown_timeout")

        assert "Unknown timeout" in str(exc_info.value)
        assert "unknown_timeout" in str(exc_info.value)

    def test_get_timeout_seconds(self) -> None:
        """get_timeout_seconds should return timeout in seconds."""
        seconds = get_timeout_seconds("retrieval_qdrant")

        assert seconds == 3.0


class TestEnvironmentOverrides:
    """Tests for environment variable overrides."""

    def test_env_var_overrides_default(self) -> None:
        """Environment variables should override defaults."""
        with mock.patch.dict(os.environ, {"RETRIEVAL_QDRANT_TIMEOUT_MS": "9999"}):
            # Need to reimport to pick up env var
            from importlib import reload

            from shared.config import timeouts

            reload(timeouts)

            assert timeouts.RETRIEVAL_QDRANT_TIMEOUT.timeout_ms == 9999

            # Restore
            reload(timeouts)

    def test_retry_env_var_override(self) -> None:
        """Retry count should be overridable via env var."""
        with mock.patch.dict(os.environ, {"RETRIEVAL_QDRANT_RETRIES": "5"}):
            from importlib import reload

            from shared.config import timeouts

            reload(timeouts)

            assert timeouts.RETRIEVAL_QDRANT_TIMEOUT.retries == 5

            # Restore
            reload(timeouts)


class TestAllTimeoutsRegistry:
    """Tests for ALL_TIMEOUTS registry."""

    def test_all_timeouts_has_expected_keys(self) -> None:
        """ALL_TIMEOUTS should have all expected timeout names."""
        expected_keys = [
            "retrieval_embedding",
            "retrieval_qdrant",
            "retrieval_opensearch",
            "retrieval_reranker",
            "retrieval_total",
            "orchestrator_retrieval",
            "orchestrator_llm",
            "orchestrator_total",
            "ingestion_parsing",
            "ingestion_embedding",
            "ingestion_qdrant_upsert",
            "ingestion_opensearch_index",
            "ingestion_document",
            "redis_operation",
            "postgres_query",
            "http_connection",
        ]

        for key in expected_keys:
            assert key in ALL_TIMEOUTS, f"Missing timeout: {key}"

    def test_all_values_are_timeout_config(self) -> None:
        """All values in ALL_TIMEOUTS should be TimeoutConfig."""
        for name, config in ALL_TIMEOUTS.items():
            assert isinstance(config, TimeoutConfig), f"{name} is not TimeoutConfig"
```

**Step 3: Run tests**

```bash
cd services/shared && pytest config/tests/test_timeouts.py -v
```

Expected: All tests PASS

**Step 4: Commit**

```bash
git add services/shared/config/tests/
git commit -m "test(shared): add timeout configuration unit tests

Test coverage for:
- TimeoutConfig dataclass behavior
- get_timeout() function
- Environment variable overrides
- ALL_TIMEOUTS registry completeness"
```

---

## Task 5: Write Unit Tests for Retry Utility

**Files:**
- Create: `services/shared/resilience/tests/__init__.py`
- Create: `services/shared/resilience/tests/test_retry.py`

**Step 1: Create test directory**

```bash
mkdir -p services/shared/resilience/tests
touch services/shared/resilience/tests/__init__.py
```

**Step 2: Write retry tests**

Create `services/shared/resilience/tests/test_retry.py`:

```python
"""Tests for retry utility."""

import asyncio

import pytest

from shared.config.timeouts import TimeoutConfig
from shared.resilience.retry import (
    RetryExhausted,
    TimeoutExceeded,
    retry_on_timeout,
    with_retry,
    with_timeout,
)


class TestWithRetry:
    """Tests for with_retry function."""

    @pytest.fixture
    def config(self) -> TimeoutConfig:
        """Create test timeout config."""
        return TimeoutConfig(
            timeout_ms=100,
            retries=2,
            backoff_base_ms=10,
            backoff_max_ms=50,
            idempotent=True,
        )

    async def test_successful_call(self, config: TimeoutConfig) -> None:
        """Successful call should return result immediately."""
        call_count = 0

        async def success() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await with_retry(success, config, "test_op")

        assert result == "ok"
        assert call_count == 1

    async def test_retries_on_failure(self, config: TimeoutConfig) -> None:
        """Should retry on failure until success."""
        call_count = 0

        async def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("failed")
            return "success"

        result = await with_retry(flaky, config, "test_op")

        assert result == "success"
        assert call_count == 3

    async def test_raises_after_retries_exhausted(self, config: TimeoutConfig) -> None:
        """Should raise RetryExhausted after all attempts fail."""

        async def always_fails() -> str:
            raise ConnectionError("always fails")

        with pytest.raises(RetryExhausted) as exc_info:
            await with_retry(always_fails, config, "test_op")

        assert exc_info.value.operation == "test_op"
        assert exc_info.value.attempts == 3  # 1 initial + 2 retries
        assert "always fails" in str(exc_info.value.last_error)

    async def test_timeout_triggers_retry(self, config: TimeoutConfig) -> None:
        """Timeout should trigger retry."""
        call_count = 0

        async def slow_then_fast() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                await asyncio.sleep(1)  # Longer than 100ms timeout
            return "success"

        result = await with_retry(slow_then_fast, config, "test_op")

        assert result == "success"
        assert call_count == 2

    async def test_non_idempotent_not_retried(self) -> None:
        """Non-idempotent operations should not be retried."""
        config = TimeoutConfig(
            timeout_ms=100,
            retries=2,
            idempotent=False,
        )
        call_count = 0

        async def fails() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        with pytest.raises(RetryExhausted) as exc_info:
            await with_retry(fails, config, "test_op")

        assert call_count == 1  # No retries for non-idempotent
        assert exc_info.value.attempts == 1


class TestRetryOnTimeoutDecorator:
    """Tests for retry_on_timeout decorator."""

    async def test_decorator_applies_retry(self) -> None:
        """Decorator should apply retry logic."""
        config = TimeoutConfig(timeout_ms=100, retries=1)
        call_count = 0

        @retry_on_timeout(config, "decorated_op")
        async def decorated() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("fail")
            return "success"

        result = await decorated()

        assert result == "success"
        assert call_count == 2


class TestWithTimeout:
    """Tests for with_timeout function."""

    async def test_successful_call(self) -> None:
        """Successful call within timeout should return result."""

        async def fast() -> str:
            return "ok"

        result = await with_timeout(fast, 1000, "test_op")

        assert result == "ok"

    async def test_timeout_raises(self) -> None:
        """Slow call should raise TimeoutExceeded."""

        async def slow() -> str:
            await asyncio.sleep(1)
            return "ok"

        with pytest.raises(TimeoutExceeded) as exc_info:
            await with_timeout(slow, 50, "test_op")

        assert exc_info.value.operation == "test_op"
        assert exc_info.value.timeout_ms == 50


class TestBackoffCalculation:
    """Tests for backoff calculation."""

    async def test_backoff_increases_exponentially(self) -> None:
        """Backoff should increase with each attempt."""
        config = TimeoutConfig(
            timeout_ms=10,  # Very short to trigger timeout
            retries=3,
            backoff_base_ms=100,
            backoff_max_ms=1000,
        )
        delays: list[float] = []

        async def track_and_fail() -> str:
            delays.append(asyncio.get_event_loop().time())
            raise ConnectionError("fail")

        try:
            await with_retry(track_and_fail, config, "test_op")
        except RetryExhausted:
            pass

        # Should have 4 calls (1 initial + 3 retries)
        assert len(delays) == 4

        # Calculate actual delays between calls
        actual_delays = [delays[i + 1] - delays[i] for i in range(len(delays) - 1)]

        # Each delay should be roughly exponentially increasing
        # (with some tolerance for jitter and timing)
        assert actual_delays[0] < actual_delays[1] < actual_delays[2]
```

**Step 3: Run tests**

```bash
cd services/shared && pytest resilience/tests/test_retry.py -v
```

Expected: All tests PASS

**Step 4: Commit**

```bash
git add services/shared/resilience/tests/
git commit -m "test(shared): add retry utility unit tests

Test coverage for:
- with_retry() successful calls and retries
- Retry exhaustion and error propagation
- Timeout triggering retry
- Non-idempotent operation behavior
- retry_on_timeout() decorator
- with_timeout() function
- Exponential backoff behavior"
```

---

## Task 6: Write Validation Tests

**Files:**
- Create: `services/shared/config/tests/test_validation.py`

**Step 1: Write validation tests**

Create `services/shared/config/tests/test_validation.py`:

```python
"""Tests for configuration validation."""

import os
from unittest import mock

import pytest

from shared.config.validation import (
    ConfigurationError,
    validate_on_startup,
    validate_timeout_cascade,
)


class TestValidateTimeoutCascade:
    """Tests for validate_timeout_cascade function."""

    def test_default_config_is_valid(self) -> None:
        """Default timeout configuration should be valid."""
        errors = validate_timeout_cascade()

        assert len(errors) == 0

    def test_detects_retrieval_cascade_violation(self) -> None:
        """Should detect when retrieval inner > total."""
        # Set reranker timeout higher than total
        with mock.patch.dict(
            os.environ,
            {
                "RETRIEVAL_RERANKER_TIMEOUT_MS": "20000",
                "RETRIEVAL_TOTAL_TIMEOUT_MS": "15000",
            },
        ):
            from importlib import reload

            from shared.config import timeouts, validation

            reload(timeouts)
            reload(validation)

            errors = validation.validate_timeout_cascade()

            assert len(errors) > 0
            assert any("Retrieval inner timeout" in e for e in errors)

            # Restore
            reload(timeouts)
            reload(validation)

    def test_detects_orchestrator_cascade_violation(self) -> None:
        """Should detect when orchestrator retrieval >= total."""
        with mock.patch.dict(
            os.environ,
            {
                "ORCHESTRATOR_RETRIEVAL_TIMEOUT_MS": "35000",
                "ORCHESTRATOR_TOTAL_TIMEOUT_MS": "30000",
            },
        ):
            from importlib import reload

            from shared.config import timeouts, validation

            reload(timeouts)
            reload(validation)

            errors = validation.validate_timeout_cascade()

            assert len(errors) > 0
            assert any("Orchestrator retrieval timeout" in e for e in errors)

            # Restore
            reload(timeouts)
            reload(validation)


class TestValidateOnStartup:
    """Tests for validate_on_startup function."""

    def test_returns_empty_on_valid_config(self) -> None:
        """Should return empty list for valid config."""
        errors = validate_on_startup(fail_fast=False)

        assert errors == []

    def test_raises_on_invalid_with_fail_fast(self) -> None:
        """Should raise ConfigurationError with fail_fast=True."""
        with mock.patch.dict(
            os.environ,
            {
                "RETRIEVAL_RERANKER_TIMEOUT_MS": "20000",
                "RETRIEVAL_TOTAL_TIMEOUT_MS": "15000",
            },
        ):
            from importlib import reload

            from shared.config import timeouts, validation

            reload(timeouts)
            reload(validation)

            with pytest.raises(ConfigurationError) as exc_info:
                validation.validate_on_startup(fail_fast=True)

            assert len(exc_info.value.errors) > 0

            # Restore
            reload(timeouts)
            reload(validation)

    def test_returns_errors_without_fail_fast(self) -> None:
        """Should return errors without raising when fail_fast=False."""
        with mock.patch.dict(
            os.environ,
            {
                "RETRIEVAL_RERANKER_TIMEOUT_MS": "20000",
                "RETRIEVAL_TOTAL_TIMEOUT_MS": "15000",
            },
        ):
            from importlib import reload

            from shared.config import timeouts, validation

            reload(timeouts)
            reload(validation)

            errors = validation.validate_on_startup(fail_fast=False)

            assert len(errors) > 0

            # Restore
            reload(timeouts)
            reload(validation)
```

**Step 2: Run tests**

```bash
cd services/shared && pytest config/tests/test_validation.py -v
```

Expected: All tests PASS

**Step 3: Commit**

```bash
git add services/shared/config/tests/
git commit -m "test(shared): add timeout validation tests

Test coverage for:
- Default configuration validity
- Cascade violation detection
- fail_fast behavior
- ConfigurationError exception"
```

---

## Task 7: Update Retrieval Service to Use Shared Config

**Files:**
- Modify: `services/retrieval/config.py`
- Modify: `services/retrieval/search/semantic.py` (or equivalent)
- Modify: `services/retrieval/search/keyword.py` (or equivalent)
- Modify: `services/retrieval/reranking/reranker.py`

**Step 1: Update retrieval config.py to reference shared timeouts**

Update `services/retrieval/config.py` to import from shared config:

```python
# Add at top of file
from shared.config import (
    RETRIEVAL_EMBEDDING_TIMEOUT,
    RETRIEVAL_OPENSEARCH_TIMEOUT,
    RETRIEVAL_QDRANT_TIMEOUT,
    RETRIEVAL_RERANKER_TIMEOUT,
    RETRIEVAL_TOTAL_TIMEOUT,
    get_timeout_seconds,
)

# Update timeout fields to use shared defaults
class RetrievalConfig(BaseSettings):
    # ... existing fields ...

    # Timeout settings (override from shared config if needed)
    search_timeout_seconds: float = get_timeout_seconds("retrieval_total")
    rerank_timeout_seconds: float = get_timeout_seconds("retrieval_reranker")
    qdrant_timeout_seconds: float = get_timeout_seconds("retrieval_qdrant")
    opensearch_timeout_seconds: float = get_timeout_seconds("retrieval_opensearch")
```

**Step 2: Update semantic search to use retry utility**

Update `services/retrieval/search/semantic.py` (or equivalent file with Qdrant search):

```python
from shared.config import RETRIEVAL_QDRANT_TIMEOUT
from shared.resilience import retry_on_timeout

class SemanticSearcher:
    @retry_on_timeout(RETRIEVAL_QDRANT_TIMEOUT, "qdrant_query")
    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 50,
        filters: dict | None = None,
    ) -> SearchResponse:
        """Search Qdrant with standardized timeout and retry."""
        # Existing implementation...
```

**Step 3: Update keyword search to use retry utility**

Update `services/retrieval/search/keyword.py` (or equivalent file with OpenSearch search):

```python
from shared.config import RETRIEVAL_OPENSEARCH_TIMEOUT
from shared.resilience import retry_on_timeout

class KeywordSearcher:
    @retry_on_timeout(RETRIEVAL_OPENSEARCH_TIMEOUT, "opensearch_query")
    async def search(
        self,
        query: str,
        top_k: int = 50,
        filters: dict | None = None,
    ) -> SearchResponse:
        """Search OpenSearch with standardized timeout and retry."""
        # Existing implementation...
```

**Step 4: Update reranker to use shared config**

Update `services/retrieval/reranking/reranker.py`:

```python
from shared.config import RETRIEVAL_RERANKER_TIMEOUT
from shared.resilience import retry_on_timeout

class Reranker:
    @retry_on_timeout(RETRIEVAL_RERANKER_TIMEOUT, "rerank_batch")
    async def rerank(
        self,
        query: str,
        documents: list[Document],
    ) -> list[RankedDocument]:
        """Rerank documents with standardized timeout and retry."""
        # Existing implementation...
```

**Step 5: Commit**

```bash
git add services/retrieval/
git commit -m "refactor(retrieval): use shared timeout and retry config

- Import timeout constants from shared.config
- Replace hardcoded timeouts with shared values
- Use retry_on_timeout decorator for Qdrant, OpenSearch, Reranker
- Enables environment variable override of all timeouts"
```

---

## Task 8: Update Orchestrator Service to Use Shared Config

**Files:**
- Modify: `services/orchestrator/config.py`
- Modify: `services/orchestrator/workflow/nodes/retrieval.py`
- Modify: `services/orchestrator/gateway/client.py`

**Step 1: Update orchestrator config.py**

Update `services/orchestrator/config.py`:

```python
from shared.config import (
    ORCHESTRATOR_LLM_TIMEOUT,
    ORCHESTRATOR_RETRIEVAL_TIMEOUT,
    ORCHESTRATOR_TOTAL_TIMEOUT,
    get_timeout_seconds,
)

class OrchestratorConfig(BaseSettings):
    # ... existing fields ...

    # Timeout settings from shared config
    retrieval_timeout: float = get_timeout_seconds("orchestrator_retrieval")
    stream_timeout: float = get_timeout_seconds("orchestrator_llm")
    total_timeout: float = get_timeout_seconds("orchestrator_total")
```

**Step 2: Update retrieval node to use retry utility**

Update `services/orchestrator/workflow/nodes/retrieval.py`:

```python
from shared.config import ORCHESTRATOR_RETRIEVAL_TIMEOUT
from shared.resilience import RetryExhausted, with_retry

async def retrieval_node(state: RAGState) -> RAGState:
    """Retrieval with standardized timeout and retry."""
    try:
        response = await with_retry(
            retrieval_client.search,
            ORCHESTRATOR_RETRIEVAL_TIMEOUT,
            "orchestrator_retrieval",
            query=state["query"],
            user_context=state["user_context"],
        )
        state["documents"] = response["results"]
    except RetryExhausted as e:
        logger.error("retrieval_exhausted", error=str(e))
        state["documents"] = []
        state["fallbacks_used"].append("retrieval_timeout")

    return state
```

**Step 3: Update gateway client to use shared config**

Update `services/orchestrator/gateway/client.py`:

```python
from shared.config import ORCHESTRATOR_LLM_TIMEOUT
from shared.resilience import with_timeout, TimeoutExceeded

class GatewayClient:
    async def generate(self, prompt: str, **kwargs) -> str:
        """Generate with standardized timeout (no retry for LLM)."""
        try:
            return await with_timeout(
                self._call_llm,
                ORCHESTRATOR_LLM_TIMEOUT.timeout_ms,
                "llm_generation",
                prompt=prompt,
                **kwargs,
            )
        except TimeoutExceeded:
            logger.error("llm_timeout", timeout_ms=ORCHESTRATOR_LLM_TIMEOUT.timeout_ms)
            raise
```

**Step 4: Commit**

```bash
git add services/orchestrator/
git commit -m "refactor(orchestrator): use shared timeout and retry config

- Import timeout constants from shared.config
- Use with_retry for retrieval calls
- Use with_timeout for LLM calls (no retry)
- Enables environment variable override of all timeouts"
```

---

## Task 9: Update Ingestion Service to Use Shared Config

**Files:**
- Modify: `services/ingestion/config.py`
- Modify: `services/ingestion/embedding/client.py`
- Modify: `services/ingestion/tasks/ingest.py`

**Step 1: Update ingestion config.py**

Update `services/ingestion/config.py`:

```python
from shared.config import (
    INGESTION_DOCUMENT_TIMEOUT,
    INGESTION_EMBEDDING_TIMEOUT,
    INGESTION_OPENSEARCH_INDEX_TIMEOUT,
    INGESTION_PARSING_TIMEOUT,
    INGESTION_QDRANT_UPSERT_TIMEOUT,
    get_timeout_seconds,
)

class IngestionConfig(BaseSettings):
    # ... existing fields ...

    # Timeout settings from shared config
    parsing_timeout_seconds: float = get_timeout_seconds("ingestion_parsing")
    embedding_timeout_seconds: float = get_timeout_seconds("ingestion_embedding")
    qdrant_upsert_timeout_seconds: float = get_timeout_seconds("ingestion_qdrant_upsert")
    opensearch_index_timeout_seconds: float = get_timeout_seconds("ingestion_opensearch_index")
```

**Step 2: Update embedding client to use retry utility**

Update `services/ingestion/embedding/client.py`:

```python
from shared.config import INGESTION_EMBEDDING_TIMEOUT
from shared.resilience import retry_on_timeout

class EmbeddingClient:
    @retry_on_timeout(INGESTION_EMBEDDING_TIMEOUT, "embedding_batch")
    async def embed_batch(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        """Generate embeddings with standardized timeout and retry."""
        # Existing implementation...
```

**Step 3: Update ingest task to use shared config for Celery time limits**

Update `services/ingestion/tasks/ingest.py`:

```python
from shared.config import INGESTION_DOCUMENT_TIMEOUT

# Use shared config for Celery task time limits
@celery_app.task(
    bind=True,
    max_retries=INGESTION_DOCUMENT_TIMEOUT.retries,
    soft_time_limit=INGESTION_DOCUMENT_TIMEOUT.timeout_ms // 1000 - 30,  # Buffer
    time_limit=INGESTION_DOCUMENT_TIMEOUT.timeout_ms // 1000,
)
def ingest_document(self, document_id: str, tenant_id: str) -> dict:
    """Ingest document with standardized time limits."""
    # Existing implementation...
```

**Step 4: Commit**

```bash
git add services/ingestion/
git commit -m "refactor(ingestion): use shared timeout and retry config

- Import timeout constants from shared.config
- Use retry_on_timeout for embedding client
- Use shared config for Celery task time limits
- Enables environment variable override of all timeouts"
```

---

## Task 10: Add Startup Validation to All Services

**Files:**
- Modify: `services/retrieval/api/main.py`
- Modify: `services/orchestrator/api/main.py`
- Modify: `services/ingestion/api/main.py`

**Step 1: Add validation to retrieval service startup**

Update `services/retrieval/api/main.py` lifespan function:

```python
from shared.config import validate_on_startup

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate configuration at startup
    validate_on_startup(fail_fast=True)

    # ... rest of startup logic ...
```

**Step 2: Add validation to orchestrator service startup**

Update `services/orchestrator/api/main.py` lifespan function:

```python
from shared.config import validate_on_startup

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate configuration at startup
    validate_on_startup(fail_fast=True)

    # ... rest of startup logic ...
```

**Step 3: Add validation to ingestion service startup**

Update `services/ingestion/api/main.py` lifespan function:

```python
from shared.config import validate_on_startup

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate configuration at startup
    validate_on_startup(fail_fast=True)

    # ... rest of startup logic ...
```

**Step 4: Commit**

```bash
git add services/retrieval/api/main.py services/orchestrator/api/main.py services/ingestion/api/main.py
git commit -m "feat: add timeout cascade validation at service startup

All services now validate timeout cascade configuration on startup.
Invalid configurations (inner timeout >= outer timeout) will prevent
service from starting, failing fast with clear error messages."
```

---

## Task 11: Update CLAUDE.md with Timeout Documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add timeout reference section to CLAUDE.md**

Add the following section to `CLAUDE.md` after the "Retrieval Pipeline Tuning" section:

```markdown
### Timeout Reference

All timeouts are centralized in `services/shared/config/timeouts.py` and can be overridden via environment variables.

#### Standard Timeout Values

| Operation | Timeout | Retries | Env Var |
|-----------|---------|---------|---------|
| **Retrieval Service** |
| Embedding request | 5000ms | 2 | `RETRIEVAL_EMBEDDING_TIMEOUT_MS` |
| Qdrant query | 3000ms | 1 | `RETRIEVAL_QDRANT_TIMEOUT_MS` |
| OpenSearch query | 3000ms | 1 | `RETRIEVAL_OPENSEARCH_TIMEOUT_MS` |
| Reranker batch | 8000ms | 1 | `RETRIEVAL_RERANKER_TIMEOUT_MS` |
| Retrieval total | 15000ms | 0 | `RETRIEVAL_TOTAL_TIMEOUT_MS` |
| **Orchestrator Service** |
| Retrieval call | 20000ms | 1 | `ORCHESTRATOR_RETRIEVAL_TIMEOUT_MS` |
| LLM generation | 25000ms | 0 | `ORCHESTRATOR_LLM_TIMEOUT_MS` |
| RAG total | 30000ms | 0 | `ORCHESTRATOR_TOTAL_TIMEOUT_MS` |
| **Ingestion Service** |
| Document parsing | 60000ms | 0 | `INGESTION_PARSING_TIMEOUT_MS` |
| Embedding batch | 30000ms | 2 | `INGESTION_EMBEDDING_TIMEOUT_MS` |
| Qdrant upsert | 10000ms | 2 | `INGESTION_QDRANT_UPSERT_TIMEOUT_MS` |
| OpenSearch index | 10000ms | 2 | `INGESTION_OPENSEARCH_INDEX_TIMEOUT_MS` |
| Document total | 300000ms | 3 | `INGESTION_DOCUMENT_TIMEOUT_MS` |

#### Timeout Cascade

```
RAG E2E (30s)
├── Retrieval Total (15s)
│   ├── Embedding (5s)
│   ├── Qdrant (3s) ──┐
│   ├── OpenSearch (3s)├── Parallel
│   └── Reranker (8s)
└── LLM (25s)
```

**Rule:** Inner timeouts must always be shorter than outer timeouts. This is validated at service startup.

#### Retry Policy

- **Idempotent operations** (search, embedding): Retry with exponential backoff
- **Non-idempotent operations** (LLM generation): No retry
- **Backoff formula:** `min(base_ms * 2^attempt, max_ms)` with ±25% jitter
```

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add timeout reference table to CLAUDE.md

Documents all standardized timeouts with:
- Default values and retry counts
- Environment variable names for overrides
- Timeout cascade diagram
- Retry policy explanation"
```

---

## Task 12: Update .env.example with Timeout Variables

**Files:**
- Modify: `.env.example`

**Step 1: Add timeout environment variables to .env.example**

Add the following section to `.env.example`:

```bash
# =============================================================================
# Timeout Configuration (all values in milliseconds)
# =============================================================================

# Retrieval Service
RETRIEVAL_EMBEDDING_TIMEOUT_MS=5000
RETRIEVAL_EMBEDDING_RETRIES=2
RETRIEVAL_QDRANT_TIMEOUT_MS=3000
RETRIEVAL_QDRANT_RETRIES=1
RETRIEVAL_OPENSEARCH_TIMEOUT_MS=3000
RETRIEVAL_OPENSEARCH_RETRIES=1
RETRIEVAL_RERANKER_TIMEOUT_MS=8000
RETRIEVAL_RERANKER_RETRIES=1
RETRIEVAL_TOTAL_TIMEOUT_MS=15000

# Orchestrator Service
ORCHESTRATOR_RETRIEVAL_TIMEOUT_MS=20000
ORCHESTRATOR_RETRIEVAL_RETRIES=1
ORCHESTRATOR_LLM_TIMEOUT_MS=25000
ORCHESTRATOR_TOTAL_TIMEOUT_MS=30000

# Ingestion Service
INGESTION_PARSING_TIMEOUT_MS=60000
INGESTION_EMBEDDING_TIMEOUT_MS=30000
INGESTION_EMBEDDING_RETRIES=2
INGESTION_QDRANT_UPSERT_TIMEOUT_MS=10000
INGESTION_QDRANT_UPSERT_RETRIES=2
INGESTION_OPENSEARCH_INDEX_TIMEOUT_MS=10000
INGESTION_OPENSEARCH_INDEX_RETRIES=2
INGESTION_DOCUMENT_TIMEOUT_MS=300000
INGESTION_DOCUMENT_RETRIES=3

# Infrastructure
REDIS_OPERATION_TIMEOUT_MS=1000
REDIS_OPERATION_RETRIES=1
POSTGRES_QUERY_TIMEOUT_MS=5000
POSTGRES_QUERY_RETRIES=1
HTTP_CONNECTION_TIMEOUT_MS=5000
```

**Step 2: Commit**

```bash
git add .env.example
git commit -m "docs: add timeout environment variables to .env.example

All timeout and retry values can now be configured via environment
variables, enabling runtime tuning without code changes."
```

---

## Task 13: Final Verification

**Step 1: Run all shared module tests**

```bash
cd services/shared && pytest config/tests/ resilience/tests/ -v
```

Expected: All tests PASS

**Step 2: Run all service tests**

```bash
make test
```

Expected: All tests PASS

**Step 3: Run linting**

```bash
make lint
```

Expected: No errors

**Step 4: Verify services start with validation**

```bash
make up-all
make health
```

Expected: All services start and report healthy

**Step 5: Move user story to done**

```bash
mv workflow/refined/10-architectural-improvements/US-10.2.4-timeout-retry-policy-unification.md \
   workflow/done/10-architectural-improvements/
```

**Step 6: Final commit**

```bash
git add workflow/
git commit -m "docs: mark US-10.2.4 timeout/retry unification as done

Timeout & Retry Policy Unification implementation complete:
- [x] AC-1: Standardized configuration in shared module
- [x] AC-2: Timeout values documented in CLAUDE.md
- [x] AC-3: Retry policies standardized with exponential backoff
- [x] AC-4: Cascade behavior validated at startup
- [x] AC-5: Integration testing via service tests"
```

---

## Summary

This plan implements US-10.2.4 by:

1. **Creating shared timeout config** (`services/shared/config/timeouts.py`) with all values centralized and environment-variable-overridable
2. **Creating retry utility** (`services/shared/resilience/retry.py`) with exponential backoff and jitter
3. **Adding cascade validation** to ensure inner timeouts < outer timeouts
4. **Updating all services** to import from shared config
5. **Adding startup validation** to fail fast on misconfiguration
6. **Documenting in CLAUDE.md** with timeout table and cascade diagram
7. **Adding env vars to .env.example** for runtime configuration

All code follows existing patterns in the codebase and uses structlog for consistent logging.
