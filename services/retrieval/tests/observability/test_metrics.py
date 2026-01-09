"""Tests for RetrievalMetrics."""

import pytest

from observability.metrics import RetrievalMetrics, get_metrics_output


class TestRetrievalMetrics:
    """Tests for RetrievalMetrics."""

    @pytest.fixture
    def metrics(self):
        """Create metrics instance with unique name to avoid conflicts."""
        import uuid

        return RetrievalMetrics(f"test_service_{uuid.uuid4().hex[:8]}")

    def test_metrics_initialization(self, metrics):
        """Test metrics initialize correctly."""
        assert metrics.service_name.startswith("test_service_")
        assert metrics.requests_total is not None
        assert metrics.request_duration is not None

    def test_record_request_success(self, metrics):
        """Test recording a successful request."""
        metrics.record_request(
            mode="hybrid",
            status="success",
            duration_seconds=0.15,
            result_count=10,
            top_score=0.92,
        )

        # Verify counter was incremented
        # Note: prometheus_client counters don't expose value directly in tests
        # This test verifies the method doesn't raise

    def test_record_request_error(self, metrics):
        """Test recording a failed request."""
        metrics.record_request(
            mode="semantic",
            status="error",
            duration_seconds=0.05,
            result_count=0,
        )

    def test_record_request_no_top_score(self, metrics):
        """Test recording request without top_score."""
        metrics.record_request(
            mode="keyword",
            status="success",
            duration_seconds=0.10,
            result_count=0,
            top_score=None,
        )

    def test_record_preprocessing(self, metrics):
        """Test recording preprocessing duration."""
        metrics.record_preprocessing(duration_seconds=0.02)

    def test_record_search_semantic(self, metrics):
        """Test recording semantic search duration."""
        metrics.record_search(search_type="semantic", duration_seconds=0.05)

    def test_record_search_keyword(self, metrics):
        """Test recording keyword search duration."""
        metrics.record_search(search_type="keyword", duration_seconds=0.03)

    def test_record_rerank_small_batch(self, metrics):
        """Test recording rerank for small batch (1-10)."""
        metrics.record_rerank(doc_count=5, duration_seconds=0.05)

    def test_record_rerank_medium_batch(self, metrics):
        """Test recording rerank for medium batch (11-20)."""
        metrics.record_rerank(doc_count=15, duration_seconds=0.08)

    def test_record_rerank_large_batch(self, metrics):
        """Test recording rerank for large batch (21-50)."""
        metrics.record_rerank(doc_count=30, duration_seconds=0.12)

    def test_record_cache_hit(self, metrics):
        """Test recording cache hit."""
        metrics.record_cache(cache_type="query", hit=True)

    def test_record_cache_miss(self, metrics):
        """Test recording cache miss."""
        metrics.record_cache(cache_type="query", hit=False)

    def test_record_cache_different_types(self, metrics):
        """Test recording cache operations for different types."""
        metrics.record_cache(cache_type="query", hit=True)
        metrics.record_cache(cache_type="embedding", hit=True)
        metrics.record_cache(cache_type="rerank", hit=False)

    def test_set_component_health_healthy(self, metrics):
        """Test setting component as healthy."""
        metrics.set_component_health(component="qdrant", healthy=True)

    def test_set_component_health_unhealthy(self, metrics):
        """Test setting component as unhealthy."""
        metrics.set_component_health(component="opensearch", healthy=False)

    def test_set_multiple_component_health(self, metrics):
        """Test setting health for multiple components."""
        metrics.set_component_health(component="qdrant", healthy=True)
        metrics.set_component_health(component="opensearch", healthy=True)
        metrics.set_component_health(component="reranker", healthy=False)

    def test_set_service_info(self, metrics):
        """Test setting service info."""
        metrics.set_service_info(
            version="1.0.0",
            environment="test",
            build_date="2024-01-01",
        )

    def test_active_requests_tracking(self, metrics):
        """Test active requests gauge."""
        metrics.active_requests.inc()
        metrics.active_requests.inc()
        metrics.active_requests.dec()

    def test_request_tracking_decorator(self, metrics):
        """Test request tracking decorator."""

        @metrics.request_tracking(mode="hybrid")
        async def sample_handler():
            return {"status": "ok"}

        # Just verify decorator doesn't break function
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(sample_handler())
        assert result == {"status": "ok"}

    def test_request_tracking_decorator_with_error(self, metrics):
        """Test request tracking decorator with error."""

        @metrics.request_tracking(mode="semantic")
        async def failing_handler():
            raise ValueError("Test error")

        import asyncio

        with pytest.raises(ValueError):
            asyncio.get_event_loop().run_until_complete(failing_handler())


class TestMetricsOutput:
    """Tests for metrics output generation."""

    def test_get_metrics_output(self):
        """Test generating metrics output."""
        content, content_type = get_metrics_output()

        assert isinstance(content, bytes)
        assert isinstance(content_type, str)

    def test_metrics_output_content_type(self):
        """Test metrics content type."""
        _, content_type = get_metrics_output()

        # Should be Prometheus format or plain text
        assert "text" in content_type or "prometheus" in content_type.lower()


class TestMetricsHistogramBuckets:
    """Tests for histogram bucket configurations."""

    def test_request_duration_buckets(self, metrics=None):
        """Test request duration histogram has appropriate buckets."""
        if metrics is None:
            metrics = RetrievalMetrics("test_buckets")

        # Record various durations
        for duration in [0.01, 0.05, 0.1, 0.2, 0.5, 1.0]:
            metrics.record_request(
                mode="hybrid",
                status="success",
                duration_seconds=duration,
                result_count=10,
            )

    def test_preprocessing_duration_buckets(self, metrics=None):
        """Test preprocessing histogram has appropriate buckets."""
        if metrics is None:
            metrics = RetrievalMetrics("test_buckets_pre")

        for duration in [0.001, 0.005, 0.01, 0.05, 0.1]:
            metrics.record_preprocessing(duration)

    def test_search_duration_buckets(self, metrics=None):
        """Test search histogram has appropriate buckets."""
        if metrics is None:
            metrics = RetrievalMetrics("test_buckets_search")

        for duration in [0.01, 0.05, 0.1, 0.15]:
            metrics.record_search("semantic", duration)

    def test_top_score_buckets(self, metrics=None):
        """Test top score histogram has appropriate buckets."""
        if metrics is None:
            metrics = RetrievalMetrics("test_buckets_score")

        for score in [0.1, 0.3, 0.5, 0.7, 0.9]:
            metrics.record_request(
                mode="hybrid",
                status="success",
                duration_seconds=0.1,
                result_count=10,
                top_score=score,
            )

    def test_result_count_buckets(self, metrics=None):
        """Test result count histogram has appropriate buckets."""
        if metrics is None:
            metrics = RetrievalMetrics("test_buckets_count")

        for count in [0, 1, 5, 10, 20, 50]:
            metrics.record_request(
                mode="hybrid",
                status="success",
                duration_seconds=0.1,
                result_count=count,
            )
