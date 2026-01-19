"""Tests for business metrics and metrics collector.

Reference: US-10.3.3 - Business & Quality Metrics
"""

import uuid

import pytest
from observability.business_metrics import (
    rag_citations_per_response,
    rag_component_latency,
    rag_context_relevance,
    rag_degraded_queries,
    rag_e2e_latency,
    rag_fallback_usage,
    rag_feedback_total,
    rag_queries_total,
)
from observability.metrics_collector import QueryMetrics, RAGMetricsCollector


class TestQueryMetrics:
    """Tests for QueryMetrics dataclass."""

    def test_query_metrics_defaults(self):
        """Test QueryMetrics has sensible defaults."""
        metrics = QueryMetrics(
            request_id="test-123",
            tenant_id=None,
        )

        assert metrics.request_id == "test-123"
        assert metrics.tenant_id is None
        assert metrics.tenant_tier == "standard"
        assert metrics.strategy == "direct"
        assert metrics.rag_used is False
        assert metrics.degraded is False
        assert metrics.degradation_mode is None
        assert metrics.fallbacks_used == []
        assert metrics.e2e_latency_ms == 0.0
        assert metrics.component_timings == {}
        assert metrics.context_relevance_score is None
        assert metrics.citation_count == 0
        assert metrics.status == "success"

    def test_query_metrics_full_values(self):
        """Test QueryMetrics with all values populated."""
        metrics = QueryMetrics(
            request_id="test-456",
            tenant_id="tenant-abc",
            tenant_tier="premium",
            strategy="hybrid",
            rag_used=True,
            degraded=True,
            degradation_mode="semantic_only",
            fallbacks_used=["semantic_fallback"],
            e2e_latency_ms=1500.0,
            component_timings={"retrieval": 300, "generation": 1000},
            context_relevance_score=0.85,
            citation_count=5,
            status="success",
        )

        assert metrics.request_id == "test-456"
        assert metrics.tenant_id == "tenant-abc"
        assert metrics.tenant_tier == "premium"
        assert metrics.strategy == "hybrid"
        assert metrics.rag_used is True
        assert metrics.degraded is True
        assert metrics.degradation_mode == "semantic_only"
        assert metrics.fallbacks_used == ["semantic_fallback"]
        assert metrics.e2e_latency_ms == 1500.0
        assert metrics.component_timings == {"retrieval": 300, "generation": 1000}
        assert metrics.context_relevance_score == 0.85
        assert metrics.citation_count == 5
        assert metrics.status == "success"


class TestRAGMetricsCollector:
    """Tests for RAGMetricsCollector."""

    @pytest.fixture
    def collector(self):
        """Create a metrics collector instance."""
        return RAGMetricsCollector()

    def test_record_query_success(self, collector):
        """Test recording a successful query."""
        metrics = QueryMetrics(
            request_id=str(uuid.uuid4()),
            tenant_id="tenant-1",
            tenant_tier="standard",
            strategy="hybrid",
            rag_used=True,
            degraded=False,
            degradation_mode=None,
            fallbacks_used=[],
            e2e_latency_ms=1200.0,
            component_timings={},
            context_relevance_score=0.9,
            citation_count=3,
            status="success",
        )

        # Should not raise
        collector.record_query(metrics)

    def test_record_query_with_degradation(self, collector):
        """Test recording a degraded query."""
        metrics = QueryMetrics(
            request_id=str(uuid.uuid4()),
            tenant_id="tenant-2",
            tenant_tier="premium",
            strategy="hybrid",
            rag_used=True,
            degraded=True,
            degradation_mode="semantic_only",
            fallbacks_used=["semantic_fallback"],
            e2e_latency_ms=800.0,
            component_timings={"retrieval": 200, "generation": 500},
            context_relevance_score=0.75,
            citation_count=2,
            status="success",
        )

        # Should not raise
        collector.record_query(metrics)

    def test_record_query_error_status(self, collector):
        """Test recording a failed query."""
        metrics = QueryMetrics(
            request_id=str(uuid.uuid4()),
            tenant_id="tenant-3",
            strategy="direct",
            rag_used=False,
            e2e_latency_ms=50.0,
            status="error",
        )

        # Should not raise
        collector.record_query(metrics)

    def test_record_query_anonymous_tenant(self, collector):
        """Test recording a query without tenant ID."""
        metrics = QueryMetrics(
            request_id=str(uuid.uuid4()),
            tenant_id=None,
            strategy="hybrid",
            rag_used=True,
            e2e_latency_ms=1000.0,
            citation_count=5,
            status="success",
        )

        # Should not raise - tenant_id should default to "anonymous"
        collector.record_query(metrics)

    def test_record_query_with_component_timings(self, collector):
        """Test recording query with component-level timings."""
        metrics = QueryMetrics(
            request_id=str(uuid.uuid4()),
            tenant_id="tenant-4",
            strategy="hybrid",
            rag_used=True,
            e2e_latency_ms=2000.0,
            component_timings={
                "routing": 10,
                "retrieval": 300,
                "prompt": 50,
                "generation": 1500,
                "validation": 100,
            },
            status="success",
        )

        # Should not raise
        collector.record_query(metrics)

    def test_record_query_multiple_fallbacks(self, collector):
        """Test recording query with multiple fallbacks used."""
        metrics = QueryMetrics(
            request_id=str(uuid.uuid4()),
            tenant_id="tenant-5",
            strategy="hybrid",
            rag_used=True,
            degraded=True,
            degradation_mode="minimal",
            fallbacks_used=["semantic_fallback", "no_rerank_fallback", "cache_fallback"],
            e2e_latency_ms=500.0,
            status="success",
        )

        # Should not raise
        collector.record_query(metrics)

    def test_record_query_no_relevance_score(self, collector):
        """Test recording query without relevance score."""
        metrics = QueryMetrics(
            request_id=str(uuid.uuid4()),
            tenant_id="tenant-6",
            strategy="direct",
            rag_used=False,
            e2e_latency_ms=200.0,
            context_relevance_score=None,
            status="success",
        )

        # Should not raise - relevance score is optional
        collector.record_query(metrics)


class TestBusinessMetricsDefinitions:
    """Tests for business metric definitions."""

    def test_rag_queries_total_labels(self):
        """Test rag_queries_total counter has correct labels."""
        # Access metric to verify it's properly defined
        assert rag_queries_total is not None
        # Verify labels by creating a child metric
        rag_queries_total.labels(
            strategy="hybrid",
            rag_used="true",
            degraded="false",
            tenant_id="test",
            status="success",
        )

    def test_rag_e2e_latency_labels(self):
        """Test rag_e2e_latency histogram has correct labels."""
        assert rag_e2e_latency is not None
        rag_e2e_latency.labels(
            strategy="hybrid",
            tenant_tier="standard",
            degraded="false",
        )

    def test_rag_component_latency_labels(self):
        """Test rag_component_latency histogram has correct labels."""
        assert rag_component_latency is not None
        rag_component_latency.labels(component="retrieval")

    def test_rag_feedback_total_labels(self):
        """Test rag_feedback_total counter has correct labels."""
        assert rag_feedback_total is not None
        rag_feedback_total.labels(rating="positive", tenant_id="test")

    def test_rag_fallback_usage_labels(self):
        """Test rag_fallback_usage counter has correct labels."""
        assert rag_fallback_usage is not None
        rag_fallback_usage.labels(fallback_type="cache_hit", tenant_id="test")

    def test_rag_degraded_queries_labels(self):
        """Test rag_degraded_queries counter has correct labels."""
        assert rag_degraded_queries is not None
        rag_degraded_queries.labels(degradation_mode="semantic_only", tenant_id="test")

    def test_rag_context_relevance_labels(self):
        """Test rag_context_relevance histogram has correct labels."""
        assert rag_context_relevance is not None
        rag_context_relevance.labels(tenant_id="test")

    def test_rag_citations_per_response_labels(self):
        """Test rag_citations_per_response histogram has correct labels."""
        assert rag_citations_per_response is not None
        rag_citations_per_response.labels(tenant_id="test")


class TestRatingToLabel:
    """Tests for rating to label conversion."""

    def test_rating_5_is_positive(self):
        """Test rating 5 converts to positive."""
        from api.routes.query import _rating_to_label

        assert _rating_to_label(5) == "positive"

    def test_rating_4_is_positive(self):
        """Test rating 4 converts to positive."""
        from api.routes.query import _rating_to_label

        assert _rating_to_label(4) == "positive"

    def test_rating_3_is_neutral(self):
        """Test rating 3 converts to neutral."""
        from api.routes.query import _rating_to_label

        assert _rating_to_label(3) == "neutral"

    def test_rating_2_is_negative(self):
        """Test rating 2 converts to negative."""
        from api.routes.query import _rating_to_label

        assert _rating_to_label(2) == "negative"

    def test_rating_1_is_negative(self):
        """Test rating 1 converts to negative."""
        from api.routes.query import _rating_to_label

        assert _rating_to_label(1) == "negative"
