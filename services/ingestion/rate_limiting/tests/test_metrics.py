"""Unit tests for rate limiting metrics."""

from unittest.mock import AsyncMock

import pytest
from rate_limiting.metrics import (
    ingestion_active_jobs,
    ingestion_queued_jobs,
    ingestion_rate_limited_total,
    record_rate_limit_hit,
    update_all_metrics,
    update_tenant_gauges,
)


class TestMetrics:
    """Tests for Prometheus metrics."""

    def test_record_rate_limit_hit_queued(self):
        """Test recording a queued rate limit hit."""
        # Get initial value
        initial = ingestion_rate_limited_total.labels(
            tenant_id="test-tenant",
            action="queued",
        )._value.get()

        record_rate_limit_hit("test-tenant", "queued")

        # Verify counter incremented
        new_value = ingestion_rate_limited_total.labels(
            tenant_id="test-tenant",
            action="queued",
        )._value.get()

        assert new_value == initial + 1

    def test_record_rate_limit_hit_rejected(self):
        """Test recording a rejected rate limit hit."""
        initial = ingestion_rate_limited_total.labels(
            tenant_id="test-tenant",
            action="rejected",
        )._value.get()

        record_rate_limit_hit("test-tenant", "rejected")

        new_value = ingestion_rate_limited_total.labels(
            tenant_id="test-tenant",
            action="rejected",
        )._value.get()

        assert new_value == initial + 1

    def test_update_tenant_gauges(self):
        """Test updating gauge metrics for a tenant."""
        update_tenant_gauges("gauge-tenant", active=5, queued=3)

        active_value = ingestion_active_jobs.labels(tenant_id="gauge-tenant")._value.get()
        queued_value = ingestion_queued_jobs.labels(tenant_id="gauge-tenant")._value.get()

        assert active_value == 5
        assert queued_value == 3

    @pytest.mark.asyncio
    async def test_update_all_metrics(self):
        """Test updating metrics from rate limiter state."""
        mock_limiter = AsyncMock()
        mock_limiter.get_all_active_tenants.return_value = ["tenant-a", "tenant-b"]
        mock_limiter.get_active_count.side_effect = [2, 4]
        mock_limiter.get_queued_count.side_effect = [1, 0]

        await update_all_metrics(mock_limiter)

        # Verify get_active_count was called for each tenant
        assert mock_limiter.get_active_count.call_count == 2
        assert mock_limiter.get_queued_count.call_count == 2

        # Verify gauges were updated
        assert ingestion_active_jobs.labels(tenant_id="tenant-a")._value.get() == 2
        assert ingestion_active_jobs.labels(tenant_id="tenant-b")._value.get() == 4
        assert ingestion_queued_jobs.labels(tenant_id="tenant-a")._value.get() == 1
        assert ingestion_queued_jobs.labels(tenant_id="tenant-b")._value.get() == 0
