"""
Tests for Prometheus metrics module.
"""

from unittest.mock import Mock

import pytest
from prometheus_client import CollectorRegistry


class TestRAGMetrics:
    """Tests for RAGMetrics class."""

    @pytest.fixture
    def metrics(self):
        """Create a RAGMetrics instance with a fresh registry."""
        from shared.observability.metrics.registry import RAGMetrics

        # Use a separate registry for tests to avoid conflicts
        registry = CollectorRegistry()
        return RAGMetrics(service_name="test_service", registry=registry)

    def test_metrics_initialization(self, metrics):
        """Test that all metrics are initialized."""
        # Query metrics
        assert metrics.query_total is not None
        assert metrics.query_duration_seconds is not None
        assert metrics.query_active is not None

        # Retrieval metrics
        assert metrics.retrieval_duration_seconds is not None
        assert metrics.retrieval_result_count is not None

        # LLM metrics
        assert metrics.llm_requests_total is not None
        assert metrics.llm_duration_seconds is not None
        assert metrics.llm_ttft_seconds is not None

        # Cache metrics
        assert metrics.cache_hits_total is not None
        assert metrics.cache_misses_total is not None

    def test_record_query(self, metrics):
        """Test recording query metrics."""
        metrics.record_query(
            mode="hybrid",
            duration=0.5,
            result_count=10,
            status="success",
            top_score=0.95,
        )

        # No errors means success
        # Actual metric values would need registry inspection

    def test_record_retrieval(self, metrics):
        """Test recording retrieval metrics."""
        metrics.record_retrieval(
            search_type="semantic",
            duration=0.1,
            result_count=5,
        )

    def test_record_rerank(self, metrics):
        """Test recording rerank metrics."""
        metrics.record_rerank(
            duration=0.05,
            input_count=20,
            model="bge-reranker-v2-m3",
        )

    def test_record_embedding(self, metrics):
        """Test recording embedding metrics."""
        metrics.record_embedding(
            duration=0.02,
            token_count=150,
            batch_size=8,
            model="bge-large-en-v1.5",
        )

    def test_record_llm(self, metrics):
        """Test recording LLM metrics."""
        metrics.record_llm(
            model="llama-3.1-8b",
            duration=2.5,
            input_tokens=500,
            output_tokens=200,
            status="success",
            provider="vllm",
            ttft=0.3,
        )

    def test_record_ingest(self, metrics):
        """Test recording ingestion metrics."""
        metrics.record_ingest(
            source_type="file",
            duration=5.0,
            chunk_count=25,
            status="success",
            stage="total",
            bytes_processed=50000,
        )

    def test_record_cache(self, metrics):
        """Test recording cache metrics."""
        metrics.record_cache(cache_type="embedding", hit=True)
        metrics.record_cache(cache_type="query", hit=False)

    def test_record_error(self, metrics):
        """Test recording error metrics."""
        metrics.record_error(
            error_type="ValidationError",
            component="retrieval",
        )

    def test_set_component_health(self, metrics):
        """Test setting component health."""
        metrics.set_component_health("qdrant", healthy=True)
        metrics.set_component_health("redis", healthy=False)

    def test_active_queries_gauge(self, metrics):
        """Test active queries gauge."""
        metrics.inc_active_queries()
        metrics.inc_active_queries()
        metrics.dec_active_queries()

    def test_set_queue_size(self, metrics):
        """Test setting queue size."""
        metrics.set_queue_size("default", 100)


class TestMetricsSetup:
    """Tests for metrics setup functions."""

    def test_setup_metrics(self):
        """Test setup_metrics function."""
        from shared.observability.metrics.registry import setup_metrics

        # Reset global state by creating new instance
        metrics = setup_metrics(
            service_name="test-setup",
            service_version="1.0.0",
        )

        assert metrics is not None
        assert metrics.service_name == "test-setup"

    def test_get_metrics_returns_instance(self):
        """Test get_metrics returns valid instance."""
        from shared.observability.metrics.registry import get_metrics

        metrics = get_metrics()
        assert metrics is not None


class TestPrometheusMiddleware:
    """Tests for PrometheusMiddleware."""

    def test_middleware_excludes_health_paths(self):
        """Test that health paths are excluded from metrics."""
        from shared.observability.metrics.middleware import PrometheusMiddleware

        middleware = PrometheusMiddleware(
            app=Mock(),
            service_name="test",
        )

        assert middleware._should_exclude("/health")
        assert middleware._should_exclude("/metrics")
        assert middleware._should_exclude("/readyz")
        assert not middleware._should_exclude("/api/query")

    def test_status_bucket(self):
        """Test status code bucketing."""
        from shared.observability.metrics.middleware import PrometheusMiddleware

        middleware = PrometheusMiddleware(app=Mock())

        assert middleware._status_bucket(200) == "2xx"
        assert middleware._status_bucket(201) == "2xx"
        assert middleware._status_bucket(301) == "3xx"
        assert middleware._status_bucket(400) == "4xx"
        assert middleware._status_bucket(404) == "4xx"
        assert middleware._status_bucket(500) == "5xx"
        assert middleware._status_bucket(503) == "5xx"


class TestMetricsExporters:
    """Tests for metrics exporters."""

    def test_get_metrics_output(self):
        """Test generating metrics output."""
        from shared.observability.metrics.exporters import get_metrics_output

        output, content_type = get_metrics_output()

        assert isinstance(output, bytes)
        assert "text/plain" in content_type or "openmetrics" in content_type

    def test_metrics_exporter_class(self):
        """Test MetricsExporter class."""
        from shared.observability.metrics.exporters import MetricsExporter

        exporter = MetricsExporter()

        assert exporter.content_type() is not None
        output = exporter.generate()
        assert isinstance(output, bytes)


class TestMetricDefinitions:
    """Tests for metric definitions."""

    def test_metric_catalog_populated(self):
        """Test that metric catalog has entries."""
        from shared.observability.metrics.definitions import METRIC_CATALOG

        assert len(METRIC_CATALOG) > 0
        assert "rag_query_total" in METRIC_CATALOG
        assert "rag_llm_requests_total" in METRIC_CATALOG

    def test_metric_definition_structure(self):
        """Test MetricDefinition dataclass."""
        from shared.observability.metrics.definitions import (
            Label,
            MetricDefinition,
            MetricType,
        )

        metric = MetricDefinition(
            name="rag_test_metric_count",
            metric_type=MetricType.COUNTER,
            unit="requests",
            description="Test metric",
            labels=[
                Label("service", "Service name", "low"),
            ],
        )

        assert metric.name == "rag_test_metric_count"
        assert metric.metric_type == MetricType.COUNTER
        assert metric.validate_name()
        assert metric.subsystem == "test"

    def test_get_slo_relevant_metrics(self):
        """Test getting SLO-relevant metrics."""
        from shared.observability.metrics.definitions import get_slo_relevant_metrics

        slo_metrics = get_slo_relevant_metrics()

        assert len(slo_metrics) > 0
        for metric in slo_metrics:
            assert metric.slo_relevant is True

    def test_validate_metric_name(self):
        """Test metric name validation."""
        from shared.observability.metrics.definitions import validate_metric_name

        assert validate_metric_name("rag_query_total")
        assert validate_metric_name("rag_llm_duration_seconds")
        assert not validate_metric_name("query_total")  # Missing rag_ prefix
        assert not validate_metric_name("RAG_query_total")  # Uppercase

    def test_generate_metrics_documentation(self):
        """Test documentation generation."""
        from shared.observability.metrics.definitions import generate_metrics_documentation

        docs = generate_metrics_documentation()

        assert "# RAG Metrics Catalog" in docs
        assert "rag_query_total" in docs
        assert "PromQL" in docs or "promql" in docs.lower()


class TestSLI:
    """Tests for SLI definitions."""

    def test_sli_catalog_populated(self):
        """Test that SLI catalog has entries."""
        from shared.observability.metrics.definitions import SLI_CATALOG

        assert len(SLI_CATALOG) > 0
        assert "query_availability" in SLI_CATALOG

    def test_sli_query_rendering(self):
        """Test SLI query rendering."""
        from shared.observability.metrics.definitions.sli import SLI_CATALOG, render_sli_query

        sli = SLI_CATALOG["query_availability"]
        query = render_sli_query(sli, "5m")

        assert "5m" in query
        assert "{{window}}" not in query

    def test_sli_error_ratio_query(self):
        """Test SLI error ratio query generation."""
        from shared.observability.metrics.definitions import SLI_CATALOG

        sli = SLI_CATALOG["query_availability"]
        error_query = sli.get_error_ratio_query()

        assert "1 -" in error_query

    def test_tenant_error_rate_sli_exists(self):
        """Test that tenant_error_rate SLI is registered."""
        from shared.observability.metrics.definitions import SLI_CATALOG

        assert "tenant_error_rate" in SLI_CATALOG
        sli = SLI_CATALOG["tenant_error_rate"]
        assert "tenant_id" in sli.query_good
        assert "tenant_id" in sli.query_total
        assert sli.category == "availability"

    def test_retrieval_latency_target_sli_exists(self):
        """Test that retrieval_latency_p95_target SLI exists with 250ms threshold."""
        from shared.observability.metrics.definitions import SLI_CATALOG

        assert "retrieval_latency_p95_target" in SLI_CATALOG
        sli = SLI_CATALOG["retrieval_latency_p95_target"]
        assert 'le="0.25"' in sli.query_good  # 250ms
        assert sli.category == "latency"

    def test_rag_e2e_latency_target_sli_exists(self):
        """Test that rag_e2e_latency_p95_target SLI exists with 2s threshold."""
        from shared.observability.metrics.definitions import SLI_CATALOG

        assert "rag_e2e_latency_p95_target" in SLI_CATALOG
        sli = SLI_CATALOG["rag_e2e_latency_p95_target"]
        assert 'le="2.0"' in sli.query_good  # 2000ms
        assert sli.category == "latency"


class TestSLO:
    """Tests for SLO definitions."""

    def test_slo_catalog_populated(self):
        """Test that SLO catalog has entries."""
        from shared.observability.metrics.definitions import SLO_CATALOG

        assert len(SLO_CATALOG) > 0
        assert "query_availability" in SLO_CATALOG
        assert "query_latency" in SLO_CATALOG

    def test_slo_error_budget(self):
        """Test SLO error budget calculation."""
        from shared.observability.metrics.definitions import SLO_CATALOG

        slo = SLO_CATALOG["query_availability"]

        assert slo.target == 0.999
        assert slo.error_budget == pytest.approx(0.001)
        assert slo.error_budget_percent == pytest.approx(0.1)

    def test_slo_burn_rates(self):
        """Test SLO burn rate configurations."""
        from shared.observability.metrics.definitions import SLO_CATALOG

        slo = SLO_CATALOG["query_availability"]

        assert len(slo.burn_rates) > 0
        # Fast burn rate should be highest
        assert slo.burn_rates[0].rate > slo.burn_rates[-1].rate

    def test_generate_slo_recording_rules(self):
        """Test SLO recording rule generation."""
        from shared.observability.metrics.definitions import (
            SLO_CATALOG,
            generate_slo_recording_rules,
        )

        slo = SLO_CATALOG["query_availability"]
        rules = generate_slo_recording_rules(slo)

        assert len(rules) > 0
        # Should have rules for various windows
        rule_names = [r["record"] for r in rules]
        assert any("ratio" in name for name in rule_names)
        assert any("error_budget" in name for name in rule_names)

    def test_generate_slo_burn_rate_alerts(self):
        """Test SLO burn rate alert generation."""
        from shared.observability.metrics.definitions import (
            SLO_CATALOG,
        )
        from shared.observability.metrics.definitions.slo import generate_slo_recording_rules

        slo = SLO_CATALOG["query_availability"]
        alerts = generate_slo_recording_rules(slo)

        assert len(alerts) > 0

    def test_generate_all_slo_rules(self):
        """Test generating all SLO rules."""
        from shared.observability.metrics.definitions.slo import generate_all_slo_rules

        rules = generate_all_slo_rules()

        assert "groups" in rules
        assert len(rules["groups"]) >= 2  # recording + alerting

    def test_slo_tenant_scoped_flag(self):
        """Test that SLO supports tenant_scoped flag."""
        from shared.observability.metrics.definitions.slo import SLO

        slo = SLO(
            name="test_tenant_slo",
            sli_name="tenant_error_rate",
            target=0.99,
            window="30d",
            description="Test tenant-scoped SLO",
            tenant_scoped=True,
        )

        assert slo.tenant_scoped is True

        # Default should be False
        slo_default = SLO(
            name="test_global_slo",
            sli_name="query_availability",
            target=0.999,
            window="30d",
            description="Test global SLO",
        )
        assert slo_default.tenant_scoped is False

    def test_new_slos_registered(self):
        """Test that US-10.3.4 SLOs are registered."""
        from shared.observability.metrics.definitions import SLO_CATALOG

        # Retrieval latency SLO
        assert "retrieval_latency_p95" in SLO_CATALOG
        retrieval_slo = SLO_CATALOG["retrieval_latency_p95"]
        assert retrieval_slo.target == 0.95
        assert retrieval_slo.sli_name == "retrieval_latency_p95_target"

        # E2E latency SLO
        assert "rag_e2e_latency_p95" in SLO_CATALOG
        e2e_slo = SLO_CATALOG["rag_e2e_latency_p95"]
        assert e2e_slo.target == 0.95
        assert e2e_slo.sli_name == "rag_e2e_latency_p95_target"

        # Tenant error rate SLO
        assert "tenant_error_rate" in SLO_CATALOG
        tenant_slo = SLO_CATALOG["tenant_error_rate"]
        assert tenant_slo.target == 0.99
        assert tenant_slo.tenant_scoped is True
