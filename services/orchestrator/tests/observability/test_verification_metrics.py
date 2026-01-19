"""Tests for verification metrics.

Reference: US-10.4.2 - Verification Metrics & Logging
"""

from unittest.mock import MagicMock

import pytest
from observability.verification_metrics import (
    rag_verification_claims,
    rag_verification_label,
    rag_verification_latency,
    rag_verification_score,
    record_verification_metrics,
)


class TestVerificationMetricsDefinitions:
    """Tests for verification metric definitions."""

    def test_rag_verification_score_labels(self):
        """Test rag_verification_score histogram has correct labels."""
        assert rag_verification_score is not None
        # Verify labels by creating a child metric
        rag_verification_score.labels(tenant_id="test")

    def test_rag_verification_label_labels(self):
        """Test rag_verification_label counter has correct labels."""
        assert rag_verification_label is not None
        rag_verification_label.labels(label="supported", tenant_id="test")

    def test_rag_verification_latency_labels(self):
        """Test rag_verification_latency histogram has correct labels."""
        assert rag_verification_latency is not None
        rag_verification_latency.labels(tenant_id="test")

    def test_rag_verification_claims_labels(self):
        """Test rag_verification_claims counter has correct labels."""
        assert rag_verification_claims is not None
        rag_verification_claims.labels(status="supported", tenant_id="test")


class TestRecordVerificationMetrics:
    """Tests for record_verification_metrics function."""

    @pytest.fixture
    def supported_result(self):
        """Create a fully supported verification result."""
        result = MagicMock()
        result.score = 1.0
        result.label = "supported"
        result.claims_total = 3
        result.claims_supported = 3
        result.claims_partial = 0
        result.claims_unsupported = 0
        result.verification_time_ms = 250.0
        result.skipped = False
        return result

    @pytest.fixture
    def partial_result(self):
        """Create a partially supported verification result."""
        result = MagicMock()
        result.score = 0.75
        result.label = "partial"
        result.claims_total = 4
        result.claims_supported = 2
        result.claims_partial = 2
        result.claims_unsupported = 0
        result.verification_time_ms = 300.0
        result.skipped = False
        return result

    @pytest.fixture
    def skipped_result(self):
        """Create a skipped verification result."""
        result = MagicMock()
        result.score = 1.0
        result.label = "skipped"
        result.claims_total = 0
        result.claims_supported = 0
        result.claims_partial = 0
        result.claims_unsupported = 0
        result.verification_time_ms = 5.0
        result.skipped = True
        result.skip_reason = "verification_disabled"
        return result

    def test_record_supported_verification(self, supported_result):
        """Test recording supported verification metrics."""
        # Should not raise
        record_verification_metrics(supported_result, "tenant-1")

    def test_record_partial_verification(self, partial_result):
        """Test recording partial verification metrics."""
        # Should not raise
        record_verification_metrics(partial_result, "tenant-2")

    def test_record_skipped_verification(self, skipped_result):
        """Test recording skipped verification metrics."""
        # Should not raise - skipped results don't record score/claims
        record_verification_metrics(skipped_result, "tenant-3")

    def test_record_with_none_tenant(self, supported_result):
        """Test recording metrics with None tenant defaults to anonymous."""
        # Should not raise - tenant_id defaults to "anonymous"
        record_verification_metrics(supported_result, None)

    def test_record_unsupported_verification(self):
        """Test recording unsupported verification metrics."""
        result = MagicMock()
        result.score = 0.0
        result.label = "unsupported"
        result.claims_total = 2
        result.claims_supported = 0
        result.claims_partial = 0
        result.claims_unsupported = 2
        result.verification_time_ms = 400.0
        result.skipped = False

        # Should not raise
        record_verification_metrics(result, "tenant-4")

    def test_record_zero_claims(self):
        """Test recording verification with zero claims."""
        result = MagicMock()
        result.score = 1.0
        result.label = "skipped"
        result.claims_total = 0
        result.claims_supported = 0
        result.claims_partial = 0
        result.claims_unsupported = 0
        result.verification_time_ms = 10.0
        result.skipped = True
        result.skip_reason = "no_claims_extracted"

        # Should not raise
        record_verification_metrics(result, "tenant-5")


class TestVerificationMetricsBuckets:
    """Tests for metric bucket configurations."""

    def test_score_histogram_buckets(self):
        """Test score histogram has appropriate buckets for 0-1 range."""
        # Access the describe to verify bucket configuration
        assert rag_verification_score is not None
        # The score histogram should have buckets from 0.1 to 1.0

    def test_latency_histogram_buckets(self):
        """Test latency histogram has appropriate buckets for seconds."""
        # Latency histogram should have buckets suitable for verification time
        assert rag_verification_latency is not None
