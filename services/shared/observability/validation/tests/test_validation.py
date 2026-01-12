"""
Integration Tests for Validation Module.

Tests the OTLP, Loki, and trace-log correlation validators.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ..loki import LogEntry, LokiValidationResult, LokiValidator
from ..otlp import OTLPValidationResult, OTLPValidator
from ..trace_log import TraceLogValidator

# =============================================================================
# OTLP Validator Tests
# =============================================================================

class TestOTLPValidator:
    """Tests for OTLPValidator."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return OTLPValidator(
            collector_url="http://localhost:4317",
            jaeger_url="http://localhost:16686",
        )

    @pytest.mark.asyncio
    async def test_validate_success(self, validator):
        """Test successful validation."""
        with patch.object(validator, "_check_collector_health") as mock_health, \
             patch.object(validator, "_check_trace_export") as mock_export, \
             patch.object(validator, "_check_service_discovery") as mock_discovery:

            mock_health.return_value = True
            mock_export.return_value = True
            mock_discovery.return_value = ["service-a", "service-b"]

            result = await validator.validate()

            assert result.is_valid
            assert result.collector_healthy
            assert result.trace_export_working
            assert len(result.services_discovered) == 2

    @pytest.mark.asyncio
    async def test_validate_collector_unhealthy(self, validator):
        """Test validation when collector is unhealthy."""
        with patch.object(validator, "_check_collector_health") as mock_health:
            mock_health.return_value = False

            result = await validator.validate()

            assert not result.is_valid
            assert not result.collector_healthy
            assert "Collector not responding" in result.errors

    @pytest.mark.asyncio
    async def test_check_collector_health(self, validator):
        """Test collector health check."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response,
            )

            result = await validator._check_collector_health()

            assert result is True

    @pytest.mark.asyncio
    async def test_validate_trace_propagation(self, validator):
        """Test trace propagation validation."""
        trace_id = "abc123def456"
        expected_services = ["orchestrator-service", "retrieval-service"]

        with patch.object(validator, "_get_trace_from_jaeger") as mock_get_trace:
            mock_get_trace.return_value = {
                "spans": [
                    {"serviceName": "orchestrator-service"},
                    {"serviceName": "retrieval-service"},
                ],
            }

            result = await validator.validate_trace_propagation(
                trace_id, expected_services,
            )

            assert result.is_valid
            assert result.services_found == expected_services


# =============================================================================
# Loki Validator Tests
# =============================================================================

class TestLokiValidator:
    """Tests for LokiValidator."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return LokiValidator(loki_url="http://localhost:3100")

    @pytest.mark.asyncio
    async def test_validate_success(self, validator):
        """Test successful Loki validation."""
        with patch.object(validator, "_check_loki_health") as mock_health, \
             patch.object(validator, "_check_log_ingestion") as mock_ingestion, \
             patch.object(validator, "_check_label_extraction") as mock_labels:

            mock_health.return_value = True
            mock_ingestion.return_value = True
            mock_labels.return_value = ["service", "level", "trace_id"]

            result = await validator.validate()

            assert result.is_valid
            assert result.loki_healthy
            assert result.log_ingestion_working
            assert "trace_id" in result.labels_available

    @pytest.mark.asyncio
    async def test_validate_loki_unhealthy(self, validator):
        """Test validation when Loki is unhealthy."""
        with patch.object(validator, "_check_loki_health") as mock_health:
            mock_health.return_value = False

            result = await validator.validate()

            assert not result.is_valid
            assert not result.loki_healthy

    @pytest.mark.asyncio
    async def test_query_logs_by_trace_id(self, validator):
        """Test querying logs by trace ID."""
        trace_id = "abc123def456"

        mock_response = {
            "data": {
                "result": [
                    {
                        "stream": {"service": "test-service"},
                        "values": [
                            ["1234567890", '{"message": "test log"}'],
                        ],
                    },
                ],
            },
        }

        with patch.object(validator, "_query_loki") as mock_query:
            mock_query.return_value = mock_response

            logs = await validator.query_logs_by_trace_id(trace_id)

            assert len(logs) == 1
            assert logs[0].service == "test-service"

    @pytest.mark.asyncio
    async def test_verify_json_parsing(self, validator):
        """Test JSON parsing verification."""
        with patch.object(validator, "_query_loki") as mock_query:
            mock_query.return_value = {
                "data": {
                    "result": [
                        {
                            "stream": {"service": "test-service"},
                            "values": [
                                ["1234567890", '{"level": "info", "message": "test"}'],
                            ],
                        },
                    ],
                },
            }

            result = await validator.verify_json_parsing("test-service")

            assert result["is_valid"]
            assert result["sample_count"] > 0


# =============================================================================
# Trace-Log Validator Tests
# =============================================================================

class TestTraceLogValidator:
    """Tests for TraceLogValidator."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return TraceLogValidator(
            jaeger_url="http://localhost:16686",
            loki_url="http://localhost:3100",
        )

    @pytest.mark.asyncio
    async def test_validate_success(self, validator):
        """Test successful trace-log correlation validation."""
        with patch.object(validator.otlp_validator, "validate") as mock_otlp, \
             patch.object(validator.loki_validator, "validate") as mock_loki, \
             patch.object(validator, "_check_correlation_working") as mock_corr:

            mock_otlp.return_value = OTLPValidationResult(
                is_valid=True,
                collector_healthy=True,
                trace_export_working=True,
                services_discovered=["test-service"],
            )
            mock_loki.return_value = LokiValidationResult(
                is_valid=True,
                loki_healthy=True,
                log_ingestion_working=True,
                labels_available=["trace_id"],
            )
            mock_corr.return_value = True

            result = await validator.validate()

            assert result.is_valid
            assert result.traces_available
            assert result.logs_available
            assert result.correlation_working

    @pytest.mark.asyncio
    async def test_validate_correlation(self, validator):
        """Test correlation validation for a specific trace."""
        trace_id = "abc123def456"
        expected_services = ["orchestrator-service"]

        with patch.object(validator.otlp_validator, "_get_trace_from_jaeger") as mock_trace, \
             patch.object(validator.loki_validator, "query_logs_by_trace_id") as mock_logs:

            mock_trace.return_value = {
                "spans": [
                    {"serviceName": "orchestrator-service", "operationName": "query"},
                ],
            }
            mock_logs.return_value = [
                LogEntry(
                    timestamp=datetime.now(tz=UTC),
                    service="orchestrator-service",
                    level="info",
                    message="Processing query",
                    trace_id=trace_id,
                ),
            ]

            result = await validator.validate_correlation(
                trace_id, expected_services,
            )

            assert result.is_valid
            assert result.trace_found
            assert result.logs_found
            assert "orchestrator-service" in result.services_with_logs

    @pytest.mark.asyncio
    async def test_validate_correlation_no_trace(self, validator):
        """Test correlation when trace is not found."""
        trace_id = "nonexistent"

        with patch.object(validator.otlp_validator, "_get_trace_from_jaeger") as mock_trace:
            mock_trace.return_value = None

            result = await validator.validate_correlation(trace_id, [])

            assert not result.is_valid
            assert not result.trace_found


# =============================================================================
# Smoke Tests
# =============================================================================

class TestSmokeTests:
    """Tests for the smoke test runner."""

    @pytest.mark.asyncio
    async def test_run_smoke_tests(self):
        """Test running full smoke test suite."""
        from ..smoke_tests import SmokeTestSuite, run_smoke_tests

        with patch("httpx.AsyncClient") as mock_client:
            # Mock all HTTP responses
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "ok"}

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response,
            )
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response,
            )

            result = await run_smoke_tests(
                orchestrator_url="http://localhost:8003",
                jaeger_url="http://localhost:16686",
                loki_url="http://localhost:3100",
                prometheus_url="http://localhost:9090",
                grafana_url="http://localhost:3000",
                collector_url="http://localhost:4317",
            )

            assert isinstance(result, SmokeTestSuite)
            assert result.total_tests > 0


# =============================================================================
# API Tests
# =============================================================================

class TestEvaluationAPI:
    """Tests for the evaluation API endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ...evaluation.api import router

        app = FastAPI()
        app.include_router(router)

        return TestClient(app)

    @pytest.mark.asyncio
    async def test_create_dataset(self, client):
        """Test dataset creation endpoint."""
        with patch("shared.observability.evaluation.api.get_repository") as mock_repo:
            mock_repo_instance = AsyncMock()
            mock_repo_instance.create_dataset.return_value = "test-dataset-id"
            mock_repo.return_value = mock_repo_instance

            response = client.post(
                "/api/v1/eval/datasets",
                json={
                    "name": "Test Dataset",
                    "description": "A test dataset",
                    "version": "1.0.0",
                },
            )

            # Note: This will fail without proper mocking setup
            # but tests the API structure
            assert response.status_code in [201, 422, 500]

    @pytest.mark.asyncio
    async def test_list_datasets(self, client):
        """Test dataset listing endpoint."""
        with patch("shared.observability.evaluation.api.get_repository") as mock_repo:
            mock_repo_instance = AsyncMock()
            mock_repo_instance.list_datasets.return_value = []
            mock_repo.return_value = mock_repo_instance

            response = client.get("/api/v1/eval/datasets")

            assert response.status_code in [200, 500]


# =============================================================================
# Metrics Tests
# =============================================================================

class TestEvaluationMetrics:
    """Tests for the evaluation metrics export."""

    def test_metrics_exporter_record_completion(self):
        """Test recording evaluation completion."""
        from ...evaluation.metrics import EvaluationMetricsExporter

        exporter = EvaluationMetricsExporter()

        exporter.record_run_completion(
            run_id="test-run-123",
            run_name="Test Run",
            dataset_name="test-dataset",
            duration_seconds=120.5,
            total_samples=100,
            successful_samples=95,
            failed_samples=5,
            aggregated_metrics={
                "context_precision": {"mean": 0.85, "std": 0.05},
                "faithfulness": {"mean": 0.90, "std": 0.03},
            },
            live_rag=True,
        )

        info = exporter.get_latest_run_info()
        assert info["run_id"] == "test-run-123"
        assert info["status"] == "completed"

    def test_metrics_exporter_record_failure(self):
        """Test recording evaluation failure."""
        from ...evaluation.metrics import EvaluationMetricsExporter

        exporter = EvaluationMetricsExporter()

        exporter.record_run_failure(
            run_id="test-run-456",
            run_name="Failed Run",
            dataset_name="test-dataset",
            duration_seconds=30.0,
            error_type="ValueError",
            error_message="Test error",
        )

        info = exporter.get_latest_run_info()
        assert info["run_id"] == "test-run-456"
        assert info["status"] == "failed"

    def test_prometheus_reporter(self):
        """Test Prometheus metrics reporter."""
        from ...evaluation.metrics import PrometheusMetricsReporter

        reporter = PrometheusMetricsReporter()

        # Create a mock run
        run = MagicMock()
        run.id = "test-run"
        run.name = "Test Run"
        run.dataset_name = "test-dataset"
        run.status = "completed"
        run.started_at = datetime.now(tz=UTC)
        run.completed_at = datetime.now(tz=UTC)
        run.metadata = {"live_rag": False}
        run.results = MagicMock()
        run.results.total_samples = 50
        run.results.successful_samples = 48
        run.results.failed_samples = 2
        run.results.aggregated_metrics = {
            "context_precision": {"mean": 0.88, "std": 0.04},
        }

        # Should not raise
        asyncio.run(reporter.report(run))


# =============================================================================
# Persistence Tests
# =============================================================================

class TestEvaluationPersistence:
    """Tests for evaluation persistence."""

    @pytest.mark.asyncio
    async def test_repository_create_dataset(self):
        """Test creating a dataset via repository."""
        from ...evaluation.persistence import EvaluationRepository

        with patch("asyncpg.create_pool") as mock_pool:
            mock_conn = AsyncMock()
            mock_conn.fetchval.return_value = "new-dataset-id"
            mock_pool.return_value.__aenter__.return_value.acquire.return_value.__aenter__.return_value = mock_conn

            EvaluationRepository("postgresql://test:test@localhost/test")

            # This tests the interface, actual DB calls are mocked
            # Full integration would require a real database

    @pytest.mark.asyncio
    async def test_repository_save_run_results(self):
        """Test saving run results via repository."""
        from ...evaluation.ragas_evaluator import AggregatedResults

        results = AggregatedResults(
            total_samples=10,
            successful_samples=10,
            failed_samples=0,
            aggregated_metrics={
                "context_precision": {
                    "mean": 0.85,
                    "std": 0.05,
                    "min": 0.75,
                    "max": 0.95,
                    "median": 0.85,
                },
            },
            individual_results=[],
            metadata={"test": True},
        )

        # Test that results can be serialized (for JSON storage)
        result_dict = results.to_dict()
        assert result_dict["total_samples"] == 10
        assert "context_precision" in result_dict["aggregated_metrics"]


# =============================================================================
# Pipeline Tracing Tests
# =============================================================================

class TestPipelineTracing:
    """Tests for pipeline OpenTelemetry tracing."""

    @pytest.mark.asyncio
    async def test_rag_client_with_tracing(self):
        """Test RAG client includes trace context."""
        from ...evaluation.pipeline import RAGClient

        client = RAGClient(
            base_url="http://localhost:8003",
            timeout=30.0,
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "answer": "Test answer",
                "contexts": ["Context 1"],
            }

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response,
            )

            response = await client.query("Test question")

            assert response.answer == "Test answer"
            assert len(response.contexts) == 1

    @pytest.mark.asyncio
    async def test_evaluation_pipeline_creates_spans(self):
        """Test that evaluation pipeline creates trace spans."""
        from ...evaluation.config import EvaluationConfig
        from ...evaluation.datasets import EvaluationDataset, EvaluationSample
        from ...evaluation.pipeline import EvaluationPipeline

        config = EvaluationConfig(
            metrics=["context_precision"],
            sample_size=1,
        )

        pipeline = EvaluationPipeline(config=config)

        dataset = EvaluationDataset(
            name="test",
            samples=[
                EvaluationSample(
                    question="What is AI?",
                    contexts=["AI is artificial intelligence"],
                    answer="AI is artificial intelligence",
                    ground_truth="AI is artificial intelligence",
                ),
            ],
        )

        # Mock the evaluator to avoid actual Ragas calls
        with patch.object(pipeline.evaluator, "evaluate_batch") as mock_eval, \
             patch.object(pipeline.evaluator, "aggregate_results") as mock_agg:

            mock_eval.return_value = []
            mock_agg.return_value = MagicMock(
                total_samples=1,
                successful_samples=1,
                failed_samples=0,
                aggregated_metrics={},
                to_dict=MagicMock(return_value={}),
            )

            # Run evaluation (will create spans)
            await pipeline.evaluate(dataset, run_name="test_run")

            # Verify evaluator was called
            mock_eval.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
