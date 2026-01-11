"""
OTLP Exporter Validation.

Validates that all services export traces to the OTEL Collector.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class ServiceExportStatus:
    """Status of trace exports for a service."""

    service_name: str
    is_exporting: bool
    last_span_time: Optional[datetime] = None
    span_count_1h: int = 0
    error_rate: float = 0.0
    sample_rate: float = 0.0
    errors: list[str] = field(default_factory=list)


@dataclass
class OTLPValidationResult:
    """Result of OTLP validation."""

    is_valid: bool
    services: list[ServiceExportStatus]
    collector_healthy: bool
    total_services: int
    exporting_services: int
    validation_time: datetime = field(default_factory=datetime.utcnow)
    errors: list[str] = field(default_factory=list)


class OTLPValidator:
    """
    Validates OTLP trace exports from services.

    Checks:
    - OTEL Collector is healthy
    - All expected services are exporting traces
    - Trace context propagates across service calls
    - Export error rates are acceptable
    """

    def __init__(
        self,
        collector_url: str = "http://otel-collector:4318",
        jaeger_url: str = "http://jaeger:16686",
        prometheus_url: str = "http://prometheus:9090",
        expected_services: Optional[list[str]] = None,
    ):
        """
        Initialize OTLP validator.

        Args:
            collector_url: OTEL Collector HTTP endpoint
            jaeger_url: Jaeger query endpoint
            prometheus_url: Prometheus query endpoint
            expected_services: List of service names that should be exporting
        """
        self.collector_url = collector_url.rstrip("/")
        self.jaeger_url = jaeger_url.rstrip("/")
        self.prometheus_url = prometheus_url.rstrip("/")
        self.expected_services = expected_services or [
            "ingestion-service",
            "retrieval-service",
            "orchestrator-service",
            "llm-gateway",
        ]

    async def validate(self) -> OTLPValidationResult:
        """
        Run full OTLP validation.

        Returns:
            OTLPValidationResult with status of all checks
        """
        errors = []
        services = []

        # Check collector health
        collector_healthy = await self._check_collector_health()
        if not collector_healthy:
            errors.append("OTEL Collector is not healthy")

        # Check each service
        for service_name in self.expected_services:
            status = await self._check_service_exports(service_name)
            services.append(status)
            if not status.is_exporting:
                errors.append(f"Service {service_name} is not exporting traces")

        exporting_count = sum(1 for s in services if s.is_exporting)

        return OTLPValidationResult(
            is_valid=collector_healthy and exporting_count == len(self.expected_services),
            services=services,
            collector_healthy=collector_healthy,
            total_services=len(self.expected_services),
            exporting_services=exporting_count,
            errors=errors,
        )

    async def _check_collector_health(self) -> bool:
        """Check if OTEL Collector is healthy."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # OTEL Collector health endpoint
                response = await client.get(f"{self.collector_url.replace(':4318', ':13133')}/")
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"Collector health check failed: {e}")
            return False

    async def _check_service_exports(self, service_name: str) -> ServiceExportStatus:
        """Check if a service is exporting traces."""
        errors = []

        try:
            # Query Jaeger for recent traces from this service
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Jaeger API to get services
                response = await client.get(
                    f"{self.jaeger_url}/api/traces",
                    params={
                        "service": service_name,
                        "lookback": "1h",
                        "limit": 10,
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    traces = data.get("data", [])

                    if traces:
                        # Get most recent span time
                        latest_time = None
                        for trace in traces:
                            for span in trace.get("spans", []):
                                start_time = span.get("startTime", 0)
                                span_dt = datetime.fromtimestamp(start_time / 1_000_000)
                                if latest_time is None or span_dt > latest_time:
                                    latest_time = span_dt

                        return ServiceExportStatus(
                            service_name=service_name,
                            is_exporting=True,
                            last_span_time=latest_time,
                            span_count_1h=len(traces),
                        )

                    errors.append("No traces found in last hour")

        except Exception as e:
            errors.append(f"Failed to query traces: {str(e)}")

        # Try Prometheus metrics as fallback
        try:
            span_count = await self._get_span_count_from_prometheus(service_name)
            if span_count > 0:
                return ServiceExportStatus(
                    service_name=service_name,
                    is_exporting=True,
                    span_count_1h=span_count,
                )
        except Exception as e:
            errors.append(f"Prometheus query failed: {str(e)}")

        return ServiceExportStatus(
            service_name=service_name,
            is_exporting=False,
            errors=errors,
        )

    async def _get_span_count_from_prometheus(self, service_name: str) -> int:
        """Get span count from Prometheus metrics."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            query = f'sum(rate(otelcol_receiver_accepted_spans{{service_name="{service_name}"}}[1h]))'
            response = await client.get(
                f"{self.prometheus_url}/api/v1/query",
                params={"query": query},
            )

            if response.status_code == 200:
                data = response.json()
                results = data.get("data", {}).get("result", [])
                if results:
                    return int(float(results[0].get("value", [0, 0])[1]))

        return 0

    async def validate_trace_propagation(
        self,
        trace_id: str,
        expected_services: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """
        Validate that a trace propagates across expected services.

        Args:
            trace_id: The trace ID to check
            expected_services: Services that should have spans in this trace

        Returns:
            Validation result with service coverage
        """
        expected = expected_services or self.expected_services

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.jaeger_url}/api/traces/{trace_id}",
                )

                if response.status_code != 200:
                    return {
                        "valid": False,
                        "error": f"Trace not found: {trace_id}",
                        "services_found": [],
                        "services_missing": expected,
                    }

                data = response.json()
                traces = data.get("data", [])

                if not traces:
                    return {
                        "valid": False,
                        "error": "No trace data returned",
                        "services_found": [],
                        "services_missing": expected,
                    }

                # Extract services from spans
                services_found = set()
                for trace in traces:
                    for span in trace.get("spans", []):
                        process_id = span.get("processID")
                        processes = trace.get("processes", {})
                        if process_id and process_id in processes:
                            service_name = processes[process_id].get("serviceName")
                            if service_name:
                                services_found.add(service_name)

                services_missing = [s for s in expected if s not in services_found]

                return {
                    "valid": len(services_missing) == 0,
                    "trace_id": trace_id,
                    "services_found": list(services_found),
                    "services_missing": services_missing,
                    "span_count": sum(
                        len(t.get("spans", [])) for t in traces
                    ),
                }

        except Exception as e:
            return {
                "valid": False,
                "error": str(e),
                "services_found": [],
                "services_missing": expected,
            }

    async def get_export_metrics(self) -> dict[str, Any]:
        """
        Get OTLP export metrics from Prometheus.

        Returns:
            Dictionary with export statistics
        """
        metrics = {}

        queries = {
            "spans_exported_1h": 'sum(increase(otelcol_exporter_sent_spans[1h]))',
            "spans_failed_1h": 'sum(increase(otelcol_exporter_send_failed_spans[1h]))',
            "queue_size": 'otelcol_exporter_queue_size',
            "queue_capacity": 'otelcol_exporter_queue_capacity',
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                for metric_name, query in queries.items():
                    response = await client.get(
                        f"{self.prometheus_url}/api/v1/query",
                        params={"query": query},
                    )

                    if response.status_code == 200:
                        data = response.json()
                        results = data.get("data", {}).get("result", [])
                        if results:
                            metrics[metric_name] = float(results[0].get("value", [0, 0])[1])

        except Exception as e:
            logger.error(f"Failed to get export metrics: {e}")

        # Calculate derived metrics
        exported = metrics.get("spans_exported_1h", 0)
        failed = metrics.get("spans_failed_1h", 0)
        total = exported + failed

        if total > 0:
            metrics["success_rate"] = exported / total
        else:
            metrics["success_rate"] = 1.0

        return metrics
