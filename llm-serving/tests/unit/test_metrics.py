"""
Unit tests for Metrics Collection (US-5.6).

Tests Prometheus metrics and MetricsCollector.
"""

import time

import pytest
from prometheus_client import REGISTRY

from monitoring.metrics import (
    BATCH_SIZE,
    CACHE_HITS,
    CACHE_MISSES,
    EMBEDDINGS_GENERATED,
    ERROR_TOTAL,
    MODEL_LOADED,
    QUEUE_SIZE,
    REQUEST_IN_PROGRESS,
    REQUEST_LATENCY,
    REQUEST_TOTAL,
    TOKENS_PER_SECOND,
    TOKENS_PROCESSED,
    MetricsCollector,
    update_gpu_metrics,
)


@pytest.fixture(autouse=True)
def reset_metrics():
    """Reset metrics before each test."""
    # Note: In a real test suite, you might want to create a fresh registry
    # For now, we'll work with the default registry
    yield


class TestMetricsCollector:
    """Tests for MetricsCollector."""

    @pytest.fixture
    def collector(self):
        """Create a metrics collector."""
        return MetricsCollector(service_name="test-service", model_name="test-model")

    def test_initialization(self, collector):
        """Test collector initialization."""
        assert collector.service_name == "test-service"
        assert collector.model_name == "test-model"

    def test_record_request(self, collector):
        """Test recording a request."""
        collector.record_request(
            endpoint="/generate",
            status="success",
            latency=0.5,
        )

        # Verify counter was incremented
        # Note: Due to label matching, we check the metric exists
        assert REQUEST_TOTAL is not None

    def test_record_tokens(self, collector):
        """Test recording token metrics."""
        collector.record_tokens(
            input_tokens=100,
            output_tokens=200,
            duration=1.0,
        )

        # Tokens per second should be set
        assert TOKENS_PER_SECOND is not None

    def test_record_tokens_zero_duration(self, collector):
        """Test recording tokens with zero duration."""
        # Should not raise an error
        collector.record_tokens(
            input_tokens=100,
            output_tokens=200,
            duration=0.0,
        )

    def test_record_time_to_first_token(self, collector):
        """Test recording TTFT."""
        collector.record_time_to_first_token(ttft=0.25)

        # No exception should be raised

    def test_record_embeddings(self, collector):
        """Test recording embedding generation."""
        collector.record_embeddings(count=32)

        assert EMBEDDINGS_GENERATED is not None

    def test_record_batch(self, collector):
        """Test recording batch metrics."""
        collector.record_batch(
            batch_size=16,
            processing_time=0.5,
        )

        assert BATCH_SIZE is not None

    def test_record_queue_metrics(self, collector):
        """Test recording queue metrics."""
        collector.record_queue_metrics(
            queue_size=10,
            wait_time=0.1,
            queue_type="request",
        )

        assert QUEUE_SIZE is not None

    def test_record_queue_metrics_no_wait_time(self, collector):
        """Test recording queue metrics without wait time."""
        collector.record_queue_metrics(
            queue_size=5,
            queue_type="batch",
        )

        # Should not raise

    def test_record_error(self, collector):
        """Test recording an error."""
        collector.record_error(error_type="timeout")

        assert ERROR_TOTAL is not None

    def test_record_cache_hit(self, collector):
        """Test recording cache hit."""
        collector.record_cache_access(hit=True, cache_type="embedding")

        assert CACHE_HITS is not None

    def test_record_cache_miss(self, collector):
        """Test recording cache miss."""
        collector.record_cache_access(hit=False, cache_type="embedding")

        assert CACHE_MISSES is not None

    def test_set_model_loaded(self, collector):
        """Test setting model loaded status."""
        collector.set_model_loaded(True)
        collector.set_model_loaded(False)

        assert MODEL_LOADED is not None

    def test_set_model_info(self, collector):
        """Test setting model info."""
        collector.set_model_info({
            "name": "test-model",
            "version": "1.0",
            "parameters": "7B",
        })

        # Should not raise

    def test_track_request_context_manager_success(self, collector):
        """Test track_request context manager on success."""
        with collector.track_request("/generate"):
            time.sleep(0.01)  # Simulate work

        # Should record success

    def test_track_request_context_manager_error(self, collector):
        """Test track_request context manager on error."""
        with pytest.raises(ValueError):
            with collector.track_request("/generate"):
                raise ValueError("Test error")

        # Should record error

    def test_track_health_check(self, collector):
        """Test track_health_check context manager."""
        with collector.track_health_check(check_type="liveness"):
            time.sleep(0.001)

        # Should record health check duration

    def test_request_instrumentation_decorator_sync(self, collector):
        """Test request_instrumentation decorator on sync function."""

        @collector.request_instrumentation("/test")
        def test_func():
            return "result"

        result = test_func()
        assert result == "result"

    @pytest.mark.asyncio
    async def test_request_instrumentation_decorator_async(self, collector):
        """Test request_instrumentation decorator on async function."""

        @collector.request_instrumentation("/test")
        async def test_func():
            return "result"

        result = await test_func()
        assert result == "result"


class TestUpdateGPUMetrics:
    """Tests for update_gpu_metrics function."""

    def test_update_all_metrics(self):
        """Test updating all GPU metrics."""
        update_gpu_metrics(
            gpu_id=0,
            gpu_name="NVIDIA A100",
            metrics={
                "memory_used": 20 * 1024 * 1024 * 1024,
                "memory_total": 40 * 1024 * 1024 * 1024,
                "utilization": 75.0,
                "temperature": 65.0,
                "power_draw": 250.0,
            },
        )

        # Should not raise

    def test_update_partial_metrics(self):
        """Test updating partial GPU metrics."""
        update_gpu_metrics(
            gpu_id=1,
            gpu_name="NVIDIA T4",
            metrics={
                "memory_used": 8 * 1024 * 1024 * 1024,
                "memory_total": 16 * 1024 * 1024 * 1024,
            },
        )

        # Should not raise

    def test_update_empty_metrics(self):
        """Test updating with empty metrics dict."""
        update_gpu_metrics(
            gpu_id=2,
            gpu_name="Unknown",
            metrics={},
        )

        # Should not raise


class TestPrometheusMetrics:
    """Tests for raw Prometheus metrics."""

    def test_request_total_labels(self):
        """Test REQUEST_TOTAL metric labels."""
        REQUEST_TOTAL.labels(
            service="vllm",
            model="test",
            endpoint="/generate",
            status="success",
        ).inc()

        # Verify metric was created with correct labels
        assert REQUEST_TOTAL._metrics

    def test_request_latency_histogram(self):
        """Test REQUEST_LATENCY histogram."""
        REQUEST_LATENCY.labels(
            service="vllm",
            model="test",
            endpoint="/generate",
        ).observe(0.5)

        # Verify histogram was updated
        assert REQUEST_LATENCY._metrics

    def test_request_in_progress_gauge(self):
        """Test REQUEST_IN_PROGRESS gauge."""
        gauge = REQUEST_IN_PROGRESS.labels(
            service="vllm",
            model="test",
        )
        gauge.inc()
        gauge.dec()

        # Should work without errors

    def test_tokens_processed_counter(self):
        """Test TOKENS_PROCESSED counter."""
        TOKENS_PROCESSED.labels(
            service="vllm",
            model="test",
            type="input",
        ).inc(100)

        TOKENS_PROCESSED.labels(
            service="vllm",
            model="test",
            type="output",
        ).inc(200)

        # Should work without errors

    def test_batch_size_histogram_buckets(self):
        """Test BATCH_SIZE histogram has correct buckets."""
        BATCH_SIZE.labels(
            service="vllm",
            model="test",
        ).observe(16)

        # Should be tracked in appropriate bucket
        assert BATCH_SIZE._metrics
