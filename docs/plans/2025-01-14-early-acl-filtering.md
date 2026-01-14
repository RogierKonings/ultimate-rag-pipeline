# US-10.1.4: Early ACL Filtering Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement defense-in-depth ACL safety net with metrics and comprehensive tests, verifying early filtering already works.

**Architecture:** The codebase already applies ACL filters at query level (before reranking). This plan adds a post-rerank safety net filter as defense-in-depth, adds Prometheus metrics to track if the safety net ever catches anything, and implements comprehensive integration tests for all visibility scenarios.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, prometheus_client, pytest, structlog

---

## Summary of Current State

Based on codebase exploration:
- **AC-1 (Query-Level Filtering):** ALREADY IMPLEMENTED
  - ACL filters applied in `acl/filter.py` via `ACLFilter.build_filter()`
  - Filters passed to both Qdrant and OpenSearch at query level
  - Applied BEFORE fusion/reranking in `api/routes/retrieve.py:64`
- **AC-2 (Safety Net):** NOT IMPLEMENTED - needs new module
- **AC-3 (Performance):** Need to document that early filtering is working
- **AC-4 (Tests):** Partial - needs comprehensive integration tests

---

## Task 1: Add Safety Net Module

**Files:**
- Create: `services/retrieval/acl/safety_net.py`
- Test: `services/retrieval/tests/acl/test_safety_net.py`

**Step 1: Write the failing test for ACLSafetyNet**

Create `services/retrieval/tests/acl/test_safety_net.py`:

```python
"""Tests for ACL safety net filter."""

from uuid import uuid4

import pytest
from acl.models import UserContext, Visibility
from acl.safety_net import ACLSafetyNet
from search.fusion import FusedResult


@pytest.fixture
def user_context():
    """Create a regular user context."""
    return UserContext(
        user_id=uuid4(),
        tenant_id=uuid4(),
        groups=["engineering"],
        roles=["user"],
        permissions=["read:documents"],
    )


@pytest.fixture
def safety_net():
    """Create safety net instance."""
    return ACLSafetyNet()


def make_fused_result(
    tenant_id,
    visibility: str = "public",
    owner_id=None,
    allowed_groups=None,
    allowed_users=None,
    status: str = "active",
) -> FusedResult:
    """Helper to create FusedResult with ACL metadata."""
    return FusedResult(
        chunk_id=uuid4(),
        document_id=uuid4(),
        content="Test content",
        fused_score=0.9,
        metadata={
            "tenant_id": str(tenant_id),
            "visibility": visibility,
            "owner_id": str(owner_id) if owner_id else None,
            "allowed_groups": allowed_groups or [],
            "allowed_users": [str(u) for u in (allowed_users or [])],
            "status": status,
        },
    )


class TestACLSafetyNetFilter:
    """Tests for safety net filtering logic."""

    def test_passes_authorized_public_document(self, safety_net, user_context):
        """Public docs in same tenant should pass."""
        result = make_fused_result(
            tenant_id=user_context.tenant_id,
            visibility="public",
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 1
        assert filtered[0].chunk_id == result.chunk_id

    def test_blocks_wrong_tenant(self, safety_net, user_context):
        """Docs from different tenant should be blocked."""
        wrong_tenant = uuid4()
        result = make_fused_result(
            tenant_id=wrong_tenant,
            visibility="public",
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 0

    def test_blocks_inactive_document(self, safety_net, user_context):
        """Soft-deleted docs should be blocked."""
        result = make_fused_result(
            tenant_id=user_context.tenant_id,
            visibility="public",
            status="deleted",
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 0

    def test_allows_group_member_access(self, safety_net, user_context):
        """Group docs accessible to group members."""
        result = make_fused_result(
            tenant_id=user_context.tenant_id,
            visibility="group",
            allowed_groups=["engineering"],
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 1

    def test_blocks_non_group_member(self, safety_net, user_context):
        """Group docs not accessible to non-members."""
        result = make_fused_result(
            tenant_id=user_context.tenant_id,
            visibility="group",
            allowed_groups=["finance"],  # user is in engineering
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 0

    def test_allows_private_to_owner(self, safety_net, user_context):
        """Private docs accessible to owner."""
        result = make_fused_result(
            tenant_id=user_context.tenant_id,
            visibility="private",
            owner_id=user_context.user_id,
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 1

    def test_blocks_private_from_non_owner(self, safety_net, user_context):
        """Private docs not accessible to non-owner."""
        other_user = uuid4()
        result = make_fused_result(
            tenant_id=user_context.tenant_id,
            visibility="private",
            owner_id=other_user,
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 0

    def test_allows_explicit_user_access(self, safety_net, user_context):
        """Docs with explicit user allowlist."""
        result = make_fused_result(
            tenant_id=user_context.tenant_id,
            visibility="private",
            allowed_users=[user_context.user_id],
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 1

    def test_allows_tenant_visibility(self, safety_net, user_context):
        """Tenant-visible docs accessible to all in tenant."""
        result = make_fused_result(
            tenant_id=user_context.tenant_id,
            visibility="tenant",
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 1
```

**Step 2: Run test to verify it fails**

Run: `cd services/retrieval && python -m pytest tests/acl/test_safety_net.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'acl.safety_net'`

**Step 3: Write minimal implementation**

Create `services/retrieval/acl/safety_net.py`:

```python
"""ACL Safety Net - Defense in depth filter applied after reranking.

This module provides a safety net that filters results AFTER reranking
as a defense-in-depth measure. If query-level ACL filtering is working
correctly, this safety net should NEVER filter anything.

Any filtering at this stage indicates a bug and is logged as a warning.
"""

import structlog

from acl.models import UserContext
from search.fusion import FusedResult

logger = structlog.get_logger(__name__)


class ACLSafetyNet:
    """
    Defense-in-depth ACL filter applied after reranking.

    This should NEVER filter anything if query-level ACL is working.
    Any filtering here indicates a bug and is logged as a warning.
    """

    def filter(
        self,
        results: list[FusedResult],
        user_context: UserContext,
    ) -> list[FusedResult]:
        """
        Apply safety net ACL filter.

        Args:
            results: Fused results after reranking
            user_context: Current user's context

        Returns:
            Filtered results (should be identical to input if ACL working)
        """
        filtered = []
        for result in results:
            if self._is_accessible(result, user_context):
                filtered.append(result)
            else:
                # This should NEVER happen - log warning
                logger.warning(
                    "acl_safety_net_filtered",
                    chunk_id=str(result.chunk_id),
                    document_id=str(result.document_id),
                    tenant_id=str(user_context.tenant_id),
                    result_tenant=result.metadata.get("tenant_id"),
                    visibility=result.metadata.get("visibility"),
                    reason="safety_net_catch",
                )

        return filtered

    def _is_accessible(
        self,
        result: FusedResult,
        user_context: UserContext,
    ) -> bool:
        """
        Check if result is accessible to user.

        Args:
            result: The search result to check
            user_context: Current user's context

        Returns:
            True if accessible, False otherwise
        """
        metadata = result.metadata

        # Tenant check - MANDATORY
        result_tenant = metadata.get("tenant_id")
        if result_tenant != str(user_context.tenant_id):
            return False

        # Status check - only active documents
        status = metadata.get("status", "active")
        if status != "active":
            return False

        # Visibility checks
        visibility = metadata.get("visibility", "private")

        if visibility == "public":
            return True

        if visibility == "tenant":
            return True  # Already passed tenant check

        if visibility == "group":
            allowed_groups = set(metadata.get("allowed_groups", []))
            user_groups = set(user_context.groups)
            return bool(allowed_groups & user_groups)

        if visibility == "private":
            # Check owner
            owner_id = metadata.get("owner_id")
            if owner_id == str(user_context.user_id):
                return True

            # Check explicit user allowlist
            allowed_users = metadata.get("allowed_users", [])
            if str(user_context.user_id) in allowed_users:
                return True

            return False

        # Unknown visibility - deny by default
        return False
```

**Step 4: Run test to verify it passes**

Run: `cd services/retrieval && python -m pytest tests/acl/test_safety_net.py -v`

Expected: All tests PASS

**Step 5: Commit**

```bash
git add services/retrieval/acl/safety_net.py services/retrieval/tests/acl/test_safety_net.py
git commit -m "feat(acl): add ACL safety net for defense-in-depth filtering

Implements post-rerank ACL filter as safety net (AC-2).
This should never filter anything if query-level ACL works correctly.
Any filtering is logged as warning indicating a bug.

Part of US-10.1.4"
```

---

## Task 2: Add Prometheus Metrics for Safety Net

**Files:**
- Modify: `services/retrieval/observability/metrics.py`
- Modify: `services/retrieval/acl/safety_net.py`
- Test: `services/retrieval/tests/acl/test_safety_net.py` (add metric tests)

**Step 1: Write the failing test for metrics**

Add to `services/retrieval/tests/acl/test_safety_net.py`:

```python
class TestACLSafetyNetMetrics:
    """Tests for safety net Prometheus metrics."""

    def test_metric_incremented_on_filter(self, safety_net, user_context):
        """Metric should increment when safety net filters a result."""
        # Reset metric
        from observability.metrics import metrics

        # Get initial value (may not exist yet)
        initial = 0
        try:
            initial = metrics.acl_safety_net_filtered._value._value
        except AttributeError:
            pass

        # Create unauthorized result
        wrong_tenant = uuid4()
        result = make_fused_result(
            tenant_id=wrong_tenant,
            visibility="public",
        )

        safety_net.filter([result], user_context)

        # Check metric incremented
        new_value = metrics.acl_safety_net_filtered._value._value
        assert new_value > initial

    def test_metric_not_incremented_for_authorized(self, safety_net, user_context):
        """Metric should NOT increment for authorized results."""
        from observability.metrics import metrics

        initial = 0
        try:
            initial = metrics.acl_safety_net_filtered._value._value
        except AttributeError:
            pass

        result = make_fused_result(
            tenant_id=user_context.tenant_id,
            visibility="public",
        )

        safety_net.filter([result], user_context)

        # Metric should not change
        try:
            new_value = metrics.acl_safety_net_filtered._value._value
            assert new_value == initial
        except AttributeError:
            pass  # Metric not created means no increment
```

**Step 2: Run test to verify it fails**

Run: `cd services/retrieval && python -m pytest tests/acl/test_safety_net.py::TestACLSafetyNetMetrics -v`

Expected: FAIL with `AttributeError: 'RetrievalMetrics' object has no attribute 'acl_safety_net_filtered'`

**Step 3: Add metric to metrics.py**

In `services/retrieval/observability/metrics.py`, add after `self.service_info` definition (around line 161):

```python
        # ACL Safety Net metrics
        self.acl_safety_net_filtered = Counter(
            f"{service_name}_acl_safety_net_filtered_total",
            "Documents filtered by ACL safety net (should be zero in normal operation)",
            ["tenant_id", "reason"],
        )
```

**Step 4: Update safety_net.py to use metric**

Update `services/retrieval/acl/safety_net.py`:

```python
"""ACL Safety Net - Defense in depth filter applied after reranking.

This module provides a safety net that filters results AFTER reranking
as a defense-in-depth measure. If query-level ACL filtering is working
correctly, this safety net should NEVER filter anything.

Any filtering at this stage indicates a bug and is logged as a warning.
"""

import structlog

from acl.models import UserContext
from observability.metrics import metrics
from search.fusion import FusedResult

logger = structlog.get_logger(__name__)


class ACLSafetyNet:
    """
    Defense-in-depth ACL filter applied after reranking.

    This should NEVER filter anything if query-level ACL is working.
    Any filtering here indicates a bug and is logged as a warning.
    """

    def filter(
        self,
        results: list[FusedResult],
        user_context: UserContext,
    ) -> list[FusedResult]:
        """
        Apply safety net ACL filter.

        Args:
            results: Fused results after reranking
            user_context: Current user's context

        Returns:
            Filtered results (should be identical to input if ACL working)
        """
        filtered = []
        for result in results:
            if self._is_accessible(result, user_context):
                filtered.append(result)
            else:
                # This should NEVER happen - log warning and increment metric
                reason = self._get_denial_reason(result, user_context)
                logger.warning(
                    "acl_safety_net_filtered",
                    chunk_id=str(result.chunk_id),
                    document_id=str(result.document_id),
                    tenant_id=str(user_context.tenant_id),
                    result_tenant=result.metadata.get("tenant_id"),
                    visibility=result.metadata.get("visibility"),
                    reason=reason,
                )
                metrics.acl_safety_net_filtered.labels(
                    tenant_id=str(user_context.tenant_id),
                    reason=reason,
                ).inc()

        return filtered

    def _get_denial_reason(
        self,
        result: FusedResult,
        user_context: UserContext,
    ) -> str:
        """Determine why access was denied for logging."""
        metadata = result.metadata

        if metadata.get("tenant_id") != str(user_context.tenant_id):
            return "wrong_tenant"
        if metadata.get("status") != "active":
            return "inactive_document"

        visibility = metadata.get("visibility", "private")
        if visibility == "group":
            return "group_mismatch"
        if visibility == "private":
            return "private_unauthorized"

        return "unknown"

    def _is_accessible(
        self,
        result: FusedResult,
        user_context: UserContext,
    ) -> bool:
        """
        Check if result is accessible to user.

        Args:
            result: The search result to check
            user_context: Current user's context

        Returns:
            True if accessible, False otherwise
        """
        metadata = result.metadata

        # Tenant check - MANDATORY
        result_tenant = metadata.get("tenant_id")
        if result_tenant != str(user_context.tenant_id):
            return False

        # Status check - only active documents
        status = metadata.get("status", "active")
        if status != "active":
            return False

        # Visibility checks
        visibility = metadata.get("visibility", "private")

        if visibility == "public":
            return True

        if visibility == "tenant":
            return True  # Already passed tenant check

        if visibility == "group":
            allowed_groups = set(metadata.get("allowed_groups", []))
            user_groups = set(user_context.groups)
            return bool(allowed_groups & user_groups)

        if visibility == "private":
            # Check owner
            owner_id = metadata.get("owner_id")
            if owner_id == str(user_context.user_id):
                return True

            # Check explicit user allowlist
            allowed_users = metadata.get("allowed_users", [])
            if str(user_context.user_id) in allowed_users:
                return True

            return False

        # Unknown visibility - deny by default
        return False
```

**Step 5: Run test to verify it passes**

Run: `cd services/retrieval && python -m pytest tests/acl/test_safety_net.py -v`

Expected: All tests PASS

**Step 6: Commit**

```bash
git add services/retrieval/observability/metrics.py services/retrieval/acl/safety_net.py services/retrieval/tests/acl/test_safety_net.py
git commit -m "feat(metrics): add acl_safety_net_filtered_total Prometheus metric

Adds Counter metric to track when safety net filters results.
This metric should always be zero in normal operation.
Non-zero values indicate query-level ACL is not working correctly.

Part of US-10.1.4 AC-2.3"
```

---

## Task 3: Integrate Safety Net into Retrieve Endpoint

**Files:**
- Modify: `services/retrieval/api/routes/retrieve.py`
- Modify: `services/retrieval/acl/__init__.py`
- Test: `services/retrieval/tests/api/test_retrieve_safety_net.py`

**Step 1: Write the failing test**

Create `services/retrieval/tests/api/test_retrieve_safety_net.py`:

```python
"""Tests for safety net integration in retrieve endpoint."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from acl.models import UserContext
from acl.safety_net import ACLSafetyNet
from api.routes.retrieve import router
from search.fusion import FusedResult, HybridSearchResponse, FusionMethod


@pytest.fixture
def app():
    """Create test FastAPI app."""
    app = FastAPI()
    app.include_router(router)

    # Mock dependencies
    app.state.preprocessor = MagicMock()
    app.state.preprocessor.process = AsyncMock(return_value=MagicMock(
        embedding=[0.1] * 1024,
        processing_time_ms=10.0,
    ))

    app.state.hybrid = MagicMock()
    app.state.reranker = MagicMock()
    app.state.acl_filter = MagicMock()
    app.state.acl_filter.build_filter = MagicMock(return_value={})

    # Add safety net
    app.state.safety_net = ACLSafetyNet()

    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def user_context():
    """Create user context for tests."""
    return UserContext(
        user_id=uuid4(),
        tenant_id=uuid4(),
        groups=["engineering"],
        roles=["user"],
        permissions=["read:documents"],
    )


class TestSafetyNetIntegration:
    """Tests for safety net in retrieve endpoint."""

    def test_safety_net_applied_after_rerank(self, app, client, user_context):
        """Safety net should filter results after reranking."""
        tenant_id = user_context.tenant_id
        wrong_tenant = uuid4()

        # Create results where one has wrong tenant (shouldn't happen)
        results = [
            FusedResult(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="Authorized content",
                fused_score=0.9,
                metadata={
                    "tenant_id": str(tenant_id),
                    "visibility": "public",
                    "status": "active",
                },
            ),
            FusedResult(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="Unauthorized content",
                fused_score=0.8,
                metadata={
                    "tenant_id": str(wrong_tenant),  # Wrong tenant!
                    "visibility": "public",
                    "status": "active",
                },
            ),
        ]

        app.state.hybrid.search = AsyncMock(return_value=HybridSearchResponse(
            results=results,
            total_semantic=2,
            total_keyword=2,
            search_time_ms=50.0,
            fusion_method=FusionMethod.RRF,
        ))

        # Patch the user context dependency
        with patch("api.routes.retrieve.UserContextDep", return_value=user_context):
            response = client.post(
                "/retrieve",
                json={"query": "test query"},
                headers={"Authorization": "Bearer test-token"},
            )

        # Only authorized result should be returned
        assert response.status_code == 200
        data = response.json()
        assert data["total_results"] == 1
```

**Step 2: Run test to verify it fails**

Run: `cd services/retrieval && python -m pytest tests/api/test_retrieve_safety_net.py -v`

Expected: FAIL (safety net not yet integrated)

**Step 3: Update acl/__init__.py to export safety_net**

Update `services/retrieval/acl/__init__.py`:

```python
"""ACL (Access Control List) module for retrieval service."""

from acl.context import get_user_context
from acl.filter import ACLFilter, AnonymousAccessFilter
from acl.middleware import UserContextDep
from acl.models import ACLFilterConfig, DocumentACL, UserContext, Visibility
from acl.safety_net import ACLSafetyNet

__all__ = [
    "ACLFilter",
    "ACLFilterConfig",
    "ACLSafetyNet",
    "AnonymousAccessFilter",
    "DocumentACL",
    "get_user_context",
    "UserContext",
    "UserContextDep",
    "Visibility",
]
```

**Step 4: Integrate safety net into retrieve.py**

In `services/retrieval/api/routes/retrieve.py`:

1. Add import at top:
```python
from acl.safety_net import ACLSafetyNet
```

2. After reranking (around line 140), add safety net filter:

Find this section:
```python
    # Rerank if enabled
    rerank_time = None
    results = search_response.results

    if body.rerank and results:
        rerank_start = time.time()
        results = await reranker.rerank_fused_results(
            query=body.query,
            fused_results=results,
            top_k=body.top_k,
        )
        rerank_time = (time.time() - rerank_start) * 1000
```

Add after it:
```python
    # Apply ACL safety net (defense in depth)
    safety_net: ACLSafetyNet = request.app.state.safety_net
    pre_safety_count = len(results)
    results = safety_net.filter(results, user)
    safety_net_filtered = pre_safety_count - len(results)
```

3. Update the metrics in the response to include safety_net_filtered:

In the `SearchMetrics` response (around line 165), ensure we track:
```python
        metrics=SearchMetrics(
            # ... existing metrics ...
            final_results_count=len(response_results),
        ),
```

**Step 5: Update app initialization to include safety_net**

Check `services/retrieval/main.py` or wherever the app is initialized, ensure `safety_net` is set:

```python
app.state.safety_net = ACLSafetyNet()
```

**Step 6: Run test to verify it passes**

Run: `cd services/retrieval && python -m pytest tests/api/test_retrieve_safety_net.py -v`

Expected: PASS

**Step 7: Commit**

```bash
git add services/retrieval/acl/__init__.py services/retrieval/api/routes/retrieve.py services/retrieval/main.py services/retrieval/tests/api/test_retrieve_safety_net.py
git commit -m "feat(retrieve): integrate ACL safety net into retrieve endpoint

Safety net filter is now applied after reranking as defense-in-depth.
If query-level ACL is working correctly, this should be a no-op.
Any filtering is logged and metrics incremented.

Part of US-10.1.4 AC-2.1"
```

---

## Task 4: Add Comprehensive Integration Tests for ACL Scenarios

**Files:**
- Create: `services/retrieval/tests/acl/test_acl_integration.py`

**Step 1: Write integration tests for all visibility scenarios**

Create `services/retrieval/tests/acl/test_acl_integration.py`:

```python
"""Integration tests for ACL filtering across all visibility scenarios.

These tests verify that ACL filtering works correctly at both:
1. Query level (in Qdrant/OpenSearch)
2. Safety net level (post-rerank)

AC-4: Security Validation
"""

from uuid import uuid4

import pytest
from acl.filter import ACLFilter, AnonymousAccessFilter
from acl.models import ACLFilterConfig, UserContext, Visibility
from acl.safety_net import ACLSafetyNet
from search.fusion import FusedResult


class TestAllVisibilityLevels:
    """AC-4.2: Test all visibility levels."""

    @pytest.fixture
    def acl_filter(self):
        return ACLFilter()

    @pytest.fixture
    def safety_net(self):
        return ACLSafetyNet()

    @pytest.fixture
    def tenant_id(self):
        return uuid4()

    @pytest.fixture
    def user_in_engineering(self, tenant_id):
        return UserContext(
            user_id=uuid4(),
            tenant_id=tenant_id,
            groups=["engineering"],
            roles=["user"],
            permissions=["read:documents"],
        )

    @pytest.fixture
    def user_in_marketing(self, tenant_id):
        return UserContext(
            user_id=uuid4(),
            tenant_id=tenant_id,
            groups=["marketing"],
            roles=["user"],
            permissions=["read:documents"],
        )

    @pytest.fixture
    def user_no_groups(self, tenant_id):
        """AC-4.3: User with no group memberships."""
        return UserContext(
            user_id=uuid4(),
            tenant_id=tenant_id,
            groups=[],
            roles=["user"],
            permissions=["read:documents"],
        )

    @pytest.fixture
    def admin_user(self, tenant_id):
        """AC-4.4: Admin user for bypass testing."""
        return UserContext(
            user_id=uuid4(),
            tenant_id=tenant_id,
            groups=["admins"],
            roles=["admin"],
            permissions=["read:documents", "write:documents"],
        )

    # PUBLIC visibility tests
    def test_public_visible_to_all_in_tenant(
        self, acl_filter, user_in_engineering, user_in_marketing, user_no_groups, tenant_id
    ):
        """Public documents visible to all users in same tenant."""
        for user in [user_in_engineering, user_in_marketing, user_no_groups]:
            filter_dict = acl_filter.build_filter(user)

            # Should have public in should clauses
            should = filter_dict.get("should", [])
            public_clause = next(
                (c for c in should if c["key"] == "visibility" and c["match"]["value"] == "public"),
                None,
            )
            assert public_clause is not None, f"Public visibility missing for user {user}"

    def test_public_not_visible_to_other_tenant(self, acl_filter, tenant_id):
        """Public documents NOT visible to users in different tenant."""
        other_tenant = uuid4()
        user = UserContext(
            user_id=uuid4(),
            tenant_id=other_tenant,
            groups=[],
            roles=["user"],
        )

        filter_dict = acl_filter.build_filter(user)

        # Must clause should require different tenant
        must = filter_dict.get("must", [])
        tenant_clause = next(
            (c for c in must if c["key"] == "tenant_id"),
            None,
        )
        assert tenant_clause is not None
        assert tenant_clause["match"]["value"] == str(other_tenant)

    # PRIVATE visibility tests
    def test_private_visible_to_owner_only(self, acl_filter, safety_net, tenant_id):
        """Private documents only visible to owner."""
        owner_id = uuid4()
        owner = UserContext(
            user_id=owner_id,
            tenant_id=tenant_id,
            groups=[],
            roles=["user"],
        )
        other_user = UserContext(
            user_id=uuid4(),
            tenant_id=tenant_id,
            groups=[],
            roles=["user"],
        )

        # Owner filter should include owner_id
        owner_filter = acl_filter.build_filter(owner)
        should = owner_filter.get("should", [])
        owner_clause = next(
            (c for c in should if c["key"] == "owner_id"),
            None,
        )
        assert owner_clause is not None
        assert owner_clause["match"]["value"] == str(owner_id)

        # Safety net should also enforce owner-only
        private_result = FusedResult(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="Private content",
            fused_score=0.9,
            metadata={
                "tenant_id": str(tenant_id),
                "visibility": "private",
                "owner_id": str(owner_id),
                "status": "active",
            },
        )

        # Owner can access
        assert len(safety_net.filter([private_result], owner)) == 1
        # Other user cannot
        assert len(safety_net.filter([private_result], other_user)) == 0

    # GROUP visibility tests
    def test_group_visible_to_members_only(
        self, acl_filter, safety_net, user_in_engineering, user_in_marketing, tenant_id
    ):
        """Group documents only visible to group members."""
        # Engineering user filter should include engineering group
        eng_filter = acl_filter.build_filter(user_in_engineering)
        should = eng_filter.get("should", [])
        group_clause = next(
            (c for c in should if c["key"] == "allowed_groups"),
            None,
        )
        assert group_clause is not None
        assert "engineering" in group_clause["match"]["any"]

        # Safety net enforcement
        eng_doc = FusedResult(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="Engineering doc",
            fused_score=0.9,
            metadata={
                "tenant_id": str(tenant_id),
                "visibility": "group",
                "allowed_groups": ["engineering"],
                "status": "active",
            },
        )

        # Engineering user can access
        assert len(safety_net.filter([eng_doc], user_in_engineering)) == 1
        # Marketing user cannot
        assert len(safety_net.filter([eng_doc], user_in_marketing)) == 0

    # TENANT visibility tests
    def test_tenant_visible_to_all_in_same_tenant(
        self, acl_filter, user_in_engineering, user_in_marketing, user_no_groups
    ):
        """Tenant documents visible to all users in same tenant."""
        for user in [user_in_engineering, user_in_marketing, user_no_groups]:
            filter_dict = acl_filter.build_filter(user)

            should = filter_dict.get("should", [])
            tenant_clause = next(
                (c for c in should if c["key"] == "visibility" and c["match"]["value"] == "tenant"),
                None,
            )
            assert tenant_clause is not None


class TestEdgeCases:
    """AC-4.3: Edge case tests."""

    @pytest.fixture
    def tenant_id(self):
        return uuid4()

    def test_user_with_no_group_memberships(self, tenant_id):
        """User with no groups should still see public/tenant docs."""
        user = UserContext(
            user_id=uuid4(),
            tenant_id=tenant_id,
            groups=[],
            roles=["user"],
        )

        acl_filter = ACLFilter()
        filter_dict = acl_filter.build_filter(user)

        should = filter_dict.get("should", [])

        # Should see public
        public = next(
            (c for c in should if c["key"] == "visibility" and c["match"]["value"] == "public"),
            None,
        )
        assert public is not None

        # Should see tenant
        tenant = next(
            (c for c in should if c["key"] == "visibility" and c["match"]["value"] == "tenant"),
            None,
        )
        assert tenant is not None

        # Should NOT have group clause (no groups)
        group = next(
            (c for c in should if c["key"] == "allowed_groups"),
            None,
        )
        assert group is None

    def test_user_with_empty_groups_list(self, tenant_id):
        """Empty groups list should not cause group filter clause."""
        user = UserContext(
            user_id=uuid4(),
            tenant_id=tenant_id,
            groups=[],  # Empty list
            roles=["user"],
        )

        acl_filter = ACLFilter()
        filter_dict = acl_filter.build_filter(user)

        # No group clause
        should = filter_dict.get("should", [])
        group = next(
            (c for c in should if c["key"] == "allowed_groups"),
            None,
        )
        assert group is None

        # No denied_groups in must_not
        must_not = filter_dict.get("must_not", [])
        denied = next(
            (c for c in must_not if c["key"] == "denied_groups"),
            None,
        )
        assert denied is None


class TestAdminBypass:
    """AC-4.4: Admin bypass tests."""

    @pytest.fixture
    def tenant_id(self):
        return uuid4()

    @pytest.fixture
    def admin_user(self, tenant_id):
        return UserContext(
            user_id=uuid4(),
            tenant_id=tenant_id,
            groups=["admins"],
            roles=["admin"],
            permissions=["read:documents", "write:documents"],
        )

    def test_admin_bypass_when_enabled(self, admin_user):
        """Admin should bypass ACL when admin_bypass=True."""
        config = ACLFilterConfig(admin_bypass=True)
        acl_filter = ACLFilter(config)

        filter_dict = acl_filter.build_filter(admin_user)

        # Should return empty filter (no restrictions)
        assert filter_dict == {}

    def test_admin_no_bypass_when_disabled(self, admin_user):
        """Admin should NOT bypass when admin_bypass=False."""
        config = ACLFilterConfig(admin_bypass=False)
        acl_filter = ACLFilter(config)

        filter_dict = acl_filter.build_filter(admin_user)

        # Should have normal ACL filters
        assert "must" in filter_dict or "should" in filter_dict

    def test_admin_qdrant_filter_none_when_bypass(self, admin_user):
        """Qdrant filter should be None for admin bypass."""
        config = ACLFilterConfig(admin_bypass=True)
        acl_filter = ACLFilter(config)

        qdrant_filter = acl_filter.build_qdrant_filter(admin_user)

        assert qdrant_filter is None

    def test_admin_opensearch_filter_empty_when_bypass(self, admin_user):
        """OpenSearch filter should be empty list for admin bypass."""
        config = ACLFilterConfig(admin_bypass=True)
        acl_filter = ACLFilter(config)

        os_filter = acl_filter.build_opensearch_filter(admin_user)

        assert os_filter == []


class TestTenantIsolation:
    """Test that tenant isolation is always enforced."""

    def test_tenant_always_in_must_clause(self):
        """Tenant filter should always be in must clause."""
        tenant_id = uuid4()
        user = UserContext(
            user_id=uuid4(),
            tenant_id=tenant_id,
            groups=["any"],
            roles=["user"],
        )

        acl_filter = ACLFilter()
        filter_dict = acl_filter.build_filter(user)

        must = filter_dict.get("must", [])
        tenant_clause = next(
            (c for c in must if c["key"] == "tenant_id"),
            None,
        )

        assert tenant_clause is not None
        assert tenant_clause["match"]["value"] == str(tenant_id)

    def test_cross_tenant_access_blocked_in_safety_net(self):
        """Safety net should block cross-tenant access."""
        tenant_a = uuid4()
        tenant_b = uuid4()

        user_a = UserContext(
            user_id=uuid4(),
            tenant_id=tenant_a,
            groups=[],
            roles=["user"],
        )

        # Document from tenant B
        doc_from_b = FusedResult(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="Tenant B content",
            fused_score=0.9,
            metadata={
                "tenant_id": str(tenant_b),
                "visibility": "public",
                "status": "active",
            },
        )

        safety_net = ACLSafetyNet()
        filtered = safety_net.filter([doc_from_b], user_a)

        assert len(filtered) == 0


class TestAnonymousAccess:
    """Test anonymous user access restrictions."""

    def test_anonymous_sees_public_only(self):
        """Anonymous users should only see public documents."""
        anon_filter = AnonymousAccessFilter()
        anon_context = UserContext.anonymous()

        filter_dict = anon_filter.build_filter(anon_context)

        must = filter_dict.get("must", [])

        # Should require public visibility
        visibility_clause = next(
            (c for c in must if c["key"] == "visibility"),
            None,
        )
        assert visibility_clause is not None
        assert visibility_clause["match"]["value"] == "public"

    def test_anonymous_no_group_or_private_access(self):
        """Anonymous users should have no should clauses for groups/private."""
        anon_filter = AnonymousAccessFilter()
        anon_context = UserContext.anonymous()

        filter_dict = anon_filter.build_filter(anon_context)

        # Should have no "should" clauses
        assert "should" not in filter_dict
```

**Step 2: Run tests**

Run: `cd services/retrieval && python -m pytest tests/acl/test_acl_integration.py -v`

Expected: All tests PASS (tests existing functionality)

**Step 3: Commit**

```bash
git add services/retrieval/tests/acl/test_acl_integration.py
git commit -m "test(acl): add comprehensive integration tests for all ACL scenarios

Tests cover:
- AC-4.2: All visibility levels (public, private, group, tenant)
- AC-4.3: Edge cases (user with no groups)
- AC-4.4: Admin bypass functionality
- Tenant isolation enforcement
- Anonymous user restrictions

Part of US-10.1.4"
```

---

## Task 5: Document Early Filtering Performance

**Files:**
- Update: `workflow/refined/10-architectural-improvements/US-10.1.4-early-acl-filtering.md`

**Step 1: Update user story with verification**

Update the acceptance criteria in the user story to mark completed items:

```markdown
### AC-1: Query-Level ACL Filtering
- [x] Qdrant queries ALWAYS include `tenant_id`, `visibility`, `allowed_groups` filters
- [x] OpenSearch queries include equivalent filter clauses
- [x] Filters applied before results returned from stores
- [x] ACL filter construction extracted to reusable utility

### AC-2: Safety Net Filter (Defense in Depth)
- [x] Post-rerank ACL filter retained as safety net only
- [x] Safety net logs warning if it filters anything (indicates bug)
- [x] Metric: `acl_safety_net_filtered_total` (should be zero)

### AC-3: Performance Validation
- [x] Measure retrieval latency before and after - N/A (early filtering already in place)
- [x] Fewer documents processed by reranker (measure reduction) - N/A
- [x] P95 latency improvement documented - N/A (no change needed)

### AC-4: Security Validation
- [x] Integration test: unauthorized docs never appear at any stage
- [x] Test all visibility levels: public, private, group, tenant
- [x] Test edge case: user with no group memberships
- [x] Test edge case: admin bypass
```

**Step 2: Move to done**

```bash
mv workflow/refined/10-architectural-improvements/US-10.1.4-early-acl-filtering.md workflow/done/10-architectural-improvements/
git add workflow/
git commit -m "docs: mark US-10.1.4 early ACL filtering as complete

ACL filters were already applied at query level (early filtering).
Added defense-in-depth safety net with logging and metrics.
Comprehensive integration tests added for all visibility scenarios."
```

---

## Summary

| Task | Description | Status |
|------|-------------|--------|
| 1 | Add Safety Net Module | New file |
| 2 | Add Prometheus Metrics | Modify existing |
| 3 | Integrate into Retrieve Endpoint | Modify existing |
| 4 | Add Integration Tests | New file |
| 5 | Document Completion | Update docs |

**Key Findings:**
- Early ACL filtering was ALREADY implemented at query level
- Main work is adding defense-in-depth safety net and comprehensive tests
- No performance changes needed (filters already applied early)
