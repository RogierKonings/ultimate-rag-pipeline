"""
Unit tests for Resource Management (US-5.5).

Tests GPU monitoring, batch optimization, and cost tracking.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from resource_management.batch_optimizer import BatchOptimizer
from resource_management.cost_tracker import CostConfig, CostTracker
from resource_management.gpu_monitor import GPUMonitor
from resource_management.models import (
    BatchingMetrics,
    CostRecord,
    GPUMetrics,
    ResourceRecommendation,
    ScalingPolicy,
)


class TestGPUMetrics:
    """Tests for GPUMetrics model."""

    def test_gpu_metrics_creation(self):
        """Test creating GPUMetrics."""
        metrics = GPUMetrics(
            gpu_id=0,
            name="NVIDIA A100",
            memory_total=40 * 1024 * 1024 * 1024,  # 40GB
            memory_used=20 * 1024 * 1024 * 1024,  # 20GB
            memory_free=20 * 1024 * 1024 * 1024,
            memory_utilization_percent=50.0,
            gpu_utilization_percent=75.0,
            temperature_celsius=65.0,
            power_draw_watts=250.0,
            power_limit_watts=400.0,
            sm_clock=1530,
            memory_clock=1215,
        )

        assert metrics.gpu_id == 0
        assert metrics.name == "NVIDIA A100"
        assert metrics.gpu_utilization_percent == 75.0

    def test_memory_utilization_property(self):
        """Test memory utilization calculation."""
        metrics = GPUMetrics(
            gpu_id=0,
            name="Test GPU",
            memory_total=40 * 1024 * 1024 * 1024,
            memory_used=20 * 1024 * 1024 * 1024,
            memory_free=20 * 1024 * 1024 * 1024,
            memory_utilization_percent=50.0,
            gpu_utilization_percent=75.0,
            temperature_celsius=65.0,
            power_draw_watts=250.0,
            power_limit_watts=400.0,
            sm_clock=1530,
            memory_clock=1215,
        )

        assert metrics.memory_utilization == 0.5


class TestGPUMonitor:
    """Tests for GPUMonitor."""

    @pytest.fixture
    def gpu_monitor(self):
        """Create a GPU monitor."""
        return GPUMonitor(poll_interval=1.0)

    @pytest.mark.asyncio
    async def test_start_stop(self, gpu_monitor):
        """Test GPU monitor lifecycle."""
        await gpu_monitor.start()
        assert gpu_monitor.is_running()

        await gpu_monitor.stop()
        assert not gpu_monitor.is_running()

    def test_get_metrics_empty(self, gpu_monitor):
        """Test getting metrics when none collected."""
        metrics = gpu_monitor.get_metrics()
        assert metrics == []

    def test_get_avg_utilization_empty(self, gpu_monitor):
        """Test average utilization with no data."""
        assert gpu_monitor.get_avg_utilization() == 0.0

    def test_parse_memory(self, gpu_monitor):
        """Test memory string parsing."""
        assert gpu_monitor._parse_memory("16384 MiB") == 16384 * 1024 * 1024
        assert gpu_monitor._parse_memory("40 GiB") == 40 * 1024 * 1024 * 1024

    def test_parse_percent(self, gpu_monitor):
        """Test percentage string parsing."""
        assert gpu_monitor._parse_percent("45 %") == 45.0
        assert gpu_monitor._parse_percent("100%") == 100.0

    def test_parse_power(self, gpu_monitor):
        """Test power string parsing."""
        assert gpu_monitor._parse_power("125.00 W") == 125.0
        assert gpu_monitor._parse_power("250W") == 250.0

    def test_parse_clock(self, gpu_monitor):
        """Test clock string parsing."""
        assert gpu_monitor._parse_clock("1530 MHz") == 1530
        assert gpu_monitor._parse_clock("1215MHz") == 1215

    def test_register_callback(self, gpu_monitor):
        """Test registering a callback."""
        callback = lambda x: None
        gpu_monitor.register_callback(callback)
        assert callback in gpu_monitor._callbacks

    def test_unregister_callback(self, gpu_monitor):
        """Test unregistering a callback."""
        callback = lambda x: None
        gpu_monitor.register_callback(callback)
        gpu_monitor.unregister_callback(callback)
        assert callback not in gpu_monitor._callbacks


class TestBatchOptimizer:
    """Tests for BatchOptimizer."""

    @pytest.fixture
    def batch_optimizer(self):
        """Create a batch optimizer."""
        return BatchOptimizer(
            service_name="test-service",
            initial_batch_size=32,
            initial_timeout_ms=50.0,
        )

    def test_initialization(self, batch_optimizer):
        """Test batch optimizer initialization."""
        assert batch_optimizer.service_name == "test-service"
        assert batch_optimizer.current_batch_size == 32
        assert batch_optimizer.current_timeout_ms == 50.0

    def test_record_batch(self, batch_optimizer):
        """Test recording batch events."""
        batch_optimizer.record_batch(
            batch_size=16, processing_time_ms=50.0, wait_time_ms=25.0
        )

        metrics = batch_optimizer.get_metrics()
        assert metrics.avg_batch_size == 16
        assert metrics.avg_batch_processing_ms == 50.0
        assert metrics.avg_batch_wait_ms == 25.0

    def test_metrics_empty(self, batch_optimizer):
        """Test metrics with no data."""
        metrics = batch_optimizer.get_metrics()

        assert metrics.avg_batch_size == 0
        assert metrics.efficiency_score == 0

    def test_recommend_insufficient_data(self, batch_optimizer):
        """Test recommendations with insufficient data."""
        for _ in range(5):
            batch_optimizer.record_batch(16, 50.0, 25.0)

        recommendation = batch_optimizer.recommend_parameters()

        assert recommendation["confidence"] == 0.0
        assert "Insufficient" in recommendation["reason"]

    def test_recommend_low_fill_rate(self, batch_optimizer):
        """Test recommendations for low fill rate."""
        # Record low fill rate batches (8 out of 32 = 25%)
        for _ in range(20):
            batch_optimizer.record_batch(
                batch_size=8,  # 25% of 32
                processing_time_ms=50.0,
                wait_time_ms=50.0,  # Full timeout
            )

        recommendation = batch_optimizer.recommend_parameters()

        # Should recommend smaller batch size
        assert recommendation["batch_size"] < 32 or recommendation["timeout_ms"] > 50.0

    def test_recommend_high_efficiency(self, batch_optimizer):
        """Test recommendations for high efficiency."""
        # Record high fill rate batches with fast processing
        for _ in range(20):
            batch_optimizer.record_batch(
                batch_size=30,  # 94% of 32
                processing_time_ms=30.0,  # Fast processing
                wait_time_ms=10.0,
            )

        recommendation = batch_optimizer.recommend_parameters()

        # Should recommend increasing batch size or maintaining
        assert recommendation["batch_size"] >= 32
        assert recommendation["confidence"] > 0.5

    def test_apply_recommendation(self, batch_optimizer):
        """Test applying recommendations."""
        recommendation = {
            "batch_size": 64,
            "timeout_ms": 100.0,
            "confidence": 0.8,
            "reason": "Test",
        }

        batch_optimizer.apply_recommendation(recommendation)

        assert batch_optimizer.current_batch_size == 64
        assert batch_optimizer.current_timeout_ms == 100.0

    def test_reset_stats(self, batch_optimizer):
        """Test resetting statistics."""
        for _ in range(10):
            batch_optimizer.record_batch(16, 50.0, 25.0)

        batch_optimizer.reset_stats()

        assert batch_optimizer.get_metrics().avg_batch_size == 0


class TestCostTracker:
    """Tests for CostTracker."""

    @pytest.fixture
    def cost_tracker(self):
        """Create a cost tracker with short aggregation interval."""
        return CostTracker(aggregation_interval=timedelta(seconds=1))

    def test_initialization(self, cost_tracker):
        """Test cost tracker initialization."""
        assert cost_tracker.config is not None
        assert cost_tracker.aggregation_interval == timedelta(seconds=1)

    def test_record_usage(self, cost_tracker):
        """Test recording usage."""
        cost_tracker.record_usage(
            service_name="vllm",
            model_name="llama-8b",
            gpu_name="NVIDIA-A100-SXM4-40GB",
            gpu_utilization=80.0,
            cpu_cores=4.0,
            memory_gb=24.0,
            requests=100,
            tokens=10000,
            duration_seconds=1.0,
        )

        # Should have accumulated data
        assert "vllm:llama-8b" in cost_tracker._usage_accumulator

    def test_force_finalize(self, cost_tracker):
        """Test force finalizing period."""
        cost_tracker.record_usage(
            service_name="vllm",
            model_name="llama-8b",
            gpu_name="NVIDIA-A100-SXM4-40GB",
            gpu_utilization=80.0,
            cpu_cores=4.0,
            memory_gb=24.0,
            requests=100,
            tokens=10000,
        )

        cost_tracker.force_finalize()

        assert len(cost_tracker._cost_records) > 0

    def test_get_cost_summary(self, cost_tracker):
        """Test getting cost summary."""
        cost_tracker.record_usage(
            service_name="vllm",
            model_name="llama-8b",
            gpu_name="NVIDIA-A100-SXM4-40GB",
            gpu_utilization=80.0,
            cpu_cores=4.0,
            memory_gb=24.0,
            requests=100,
            tokens=10000,
        )
        cost_tracker.force_finalize()

        summary = cost_tracker.get_cost_summary()

        assert summary["total_requests"] >= 100
        assert summary["total_cost"] >= 0

    def test_get_cost_by_model(self, cost_tracker):
        """Test cost breakdown by model."""
        cost_tracker.record_usage(
            service_name="vllm",
            model_name="llama-8b",
            gpu_name="NVIDIA-A100-SXM4-40GB",
            gpu_utilization=80.0,
            cpu_cores=4.0,
            memory_gb=24.0,
            requests=50,
            tokens=5000,
        )

        cost_tracker.record_usage(
            service_name="embedding",
            model_name="bge-large",
            gpu_name="NVIDIA-T4",
            gpu_utilization=60.0,
            cpu_cores=2.0,
            memory_gb=4.0,
            requests=200,
            tokens=20000,
        )

        cost_tracker.force_finalize()

        by_model = cost_tracker.get_cost_by_model()

        assert "llama-8b" in by_model or "bge-large" in by_model

    def test_estimate_monthly_cost(self, cost_tracker):
        """Test monthly cost estimation."""
        # With no recent data, should be 0
        estimate = cost_tracker.estimate_monthly_cost()
        assert estimate == 0.0

    def test_clear_records(self, cost_tracker):
        """Test clearing records."""
        cost_tracker.record_usage(
            service_name="test",
            model_name="test",
            gpu_name="test",
            gpu_utilization=50.0,
            cpu_cores=1.0,
            memory_gb=1.0,
        )
        cost_tracker.force_finalize()

        cleared = cost_tracker.clear_records()

        assert cleared > 0
        assert len(cost_tracker._cost_records) == 0


class TestCostConfig:
    """Tests for CostConfig."""

    def test_default_gpu_costs(self):
        """Test default GPU cost configuration."""
        config = CostConfig()

        assert config.get_gpu_cost("NVIDIA-A100-SXM4-40GB") == 4.00
        assert config.get_gpu_cost("NVIDIA-T4") == 0.75

    def test_unknown_gpu_cost(self):
        """Test cost for unknown GPU."""
        config = CostConfig()

        # Should return default cost
        cost = config.get_gpu_cost("Unknown-GPU")
        assert cost == config.gpu_cost_per_hour["default"]


class TestScalingPolicy:
    """Tests for ScalingPolicy model."""

    def test_default_values(self):
        """Test default scaling policy values."""
        policy = ScalingPolicy(service_name="vllm")

        assert policy.min_replicas == 1
        assert policy.max_replicas == 10
        assert policy.scale_up_gpu_utilization == 80.0
        assert policy.scale_down_gpu_utilization == 30.0

    def test_custom_values(self):
        """Test custom scaling policy."""
        policy = ScalingPolicy(
            service_name="vllm",
            min_replicas=2,
            max_replicas=8,
            scale_up_gpu_utilization=90.0,
            max_hourly_cost=100.0,
        )

        assert policy.min_replicas == 2
        assert policy.max_replicas == 8
        assert policy.max_hourly_cost == 100.0


class TestResourceRecommendation:
    """Tests for ResourceRecommendation model."""

    def test_scale_up_recommendation(self):
        """Test creating a scale up recommendation."""
        rec = ResourceRecommendation(
            service_name="vllm",
            recommendation_type="scale_up",
            current_replicas=1,
            current_gpu_utilization=90.0,
            current_queue_depth=150,
            recommended_replicas=2,
            reason="High GPU utilization and queue depth",
            confidence=0.85,
            expected_cost_change_percent=100.0,
            expected_latency_change_percent=-40.0,
        )

        assert rec.recommendation_type == "scale_up"
        assert rec.recommended_replicas == 2
        assert rec.confidence == 0.85
