"""
Observability Smoke Tests.

End-to-end smoke tests for the observability stack.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import structlog

from .trace_log import TraceLogValidator

logger = structlog.get_logger(__name__)


@dataclass
class SmokeTestResult:
    """Result of a single smoke test."""

    name: str
    passed: bool
    duration_ms: float
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class SmokeTestSuite:
    """Results from a full smoke test suite."""

    passed: bool
    total_tests: int
    passed_tests: int
    failed_tests: int
    results: list[SmokeTestResult]
    duration_ms: float
    run_time: datetime = field(default_factory=datetime.utcnow)


async def run_smoke_tests(
    orchestrator_url: str = "http://orchestrator:8003",
    jaeger_url: str = "http://jaeger:16686",
    loki_url: str = "http://loki:3100",
    prometheus_url: str = "http://prometheus:9090",
    grafana_url: str = "http://grafana:3000",
    collector_url: str = "http://otel-collector:4318",
) -> SmokeTestSuite:
    """
    Run the full observability smoke test suite.

    Args:
        orchestrator_url: Orchestrator service URL
        jaeger_url: Jaeger query URL
        loki_url: Loki query URL
        prometheus_url: Prometheus URL
        grafana_url: Grafana URL
        collector_url: OTEL Collector URL

    Returns:
        SmokeTestSuite with all results
    """
    start_time = datetime.now(tz=UTC)
    results = []

    # Test 1: OTEL Collector health
    result = await _test_otel_collector_health(collector_url)
    results.append(result)

    # Test 2: Jaeger/Tempo health
    result = await _test_trace_backend_health(jaeger_url)
    results.append(result)

    # Test 3: Loki health
    result = await _test_loki_health(loki_url)
    results.append(result)

    # Test 4: Prometheus health
    result = await _test_prometheus_health(prometheus_url)
    results.append(result)

    # Test 5: Grafana health
    result = await _test_grafana_health(grafana_url)
    results.append(result)

    # Test 6: Send test request and verify trace
    result = await _test_request_creates_trace(orchestrator_url, jaeger_url)
    results.append(result)

    # Test 7: Verify logs appear in Loki
    result = await _test_logs_in_loki(loki_url)
    results.append(result)

    # Test 8: Verify trace-log correlation
    result = await _test_trace_log_correlation(jaeger_url, loki_url)
    results.append(result)

    # Test 9: Verify Prometheus scrapes
    result = await _test_prometheus_scrapes(prometheus_url)
    results.append(result)

    # Test 10: Verify Grafana datasources
    result = await _test_grafana_datasources(grafana_url)
    results.append(result)

    # Calculate summary
    end_time = datetime.now(tz=UTC)
    duration_ms = (end_time - start_time).total_seconds() * 1000

    passed_tests = sum(1 for r in results if r.passed)
    failed_tests = len(results) - passed_tests

    return SmokeTestSuite(
        passed=failed_tests == 0,
        total_tests=len(results),
        passed_tests=passed_tests,
        failed_tests=failed_tests,
        results=results,
        duration_ms=duration_ms,
    )


async def _test_otel_collector_health(collector_url: str) -> SmokeTestResult:
    """Test OTEL Collector is healthy."""
    start = datetime.now(tz=UTC)
    name = "OTEL Collector Health"

    try:
        health_url = collector_url.replace(":4318", ":13133")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{health_url}/")

            duration_ms = (datetime.now(tz=UTC) - start).total_seconds() * 1000

            if response.status_code == 200:
                return SmokeTestResult(
                    name=name,
                    passed=True,
                    duration_ms=duration_ms,
                    message="OTEL Collector is healthy",
                )
            return SmokeTestResult(
                name=name,
                passed=False,
                duration_ms=duration_ms,
                message=f"Collector returned status {response.status_code}",
            )

    except Exception as e:
        duration_ms = (datetime.now(tz=UTC) - start).total_seconds() * 1000
        return SmokeTestResult(
            name=name,
            passed=False,
            duration_ms=duration_ms,
            error=str(e),
        )


async def _test_trace_backend_health(jaeger_url: str) -> SmokeTestResult:
    """Test Jaeger/Tempo is healthy."""
    start = datetime.now(tz=UTC)
    name = "Trace Backend Health"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{jaeger_url}/api/services")

            duration_ms = (datetime.now(tz=UTC) - start).total_seconds() * 1000

            if response.status_code == 200:
                data = response.json()
                services = data.get("data", [])
                return SmokeTestResult(
                    name=name,
                    passed=True,
                    duration_ms=duration_ms,
                    message=f"Jaeger healthy, {len(services)} services found",
                    details={"services": services},
                )
            return SmokeTestResult(
                name=name,
                passed=False,
                duration_ms=duration_ms,
                message=f"Jaeger returned status {response.status_code}",
            )

    except Exception as e:
        duration_ms = (datetime.now(tz=UTC) - start).total_seconds() * 1000
        return SmokeTestResult(
            name=name,
            passed=False,
            duration_ms=duration_ms,
            error=str(e),
        )


async def _test_loki_health(loki_url: str) -> SmokeTestResult:
    """Test Loki is healthy."""
    start = datetime.now(tz=UTC)
    name = "Loki Health"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{loki_url}/ready")

            duration_ms = (datetime.now(tz=UTC) - start).total_seconds() * 1000

            if response.status_code == 200:
                return SmokeTestResult(
                    name=name,
                    passed=True,
                    duration_ms=duration_ms,
                    message="Loki is ready",
                )
            return SmokeTestResult(
                name=name,
                passed=False,
                duration_ms=duration_ms,
                message=f"Loki returned status {response.status_code}",
            )

    except Exception as e:
        duration_ms = (datetime.now(tz=UTC) - start).total_seconds() * 1000
        return SmokeTestResult(
            name=name,
            passed=False,
            duration_ms=duration_ms,
            error=str(e),
        )


async def _test_prometheus_health(prometheus_url: str) -> SmokeTestResult:
    """Test Prometheus is healthy."""
    start = datetime.now(tz=UTC)
    name = "Prometheus Health"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{prometheus_url}/-/healthy")

            duration_ms = (datetime.now(tz=UTC) - start).total_seconds() * 1000

            if response.status_code == 200:
                return SmokeTestResult(
                    name=name,
                    passed=True,
                    duration_ms=duration_ms,
                    message="Prometheus is healthy",
                )
            return SmokeTestResult(
                name=name,
                passed=False,
                duration_ms=duration_ms,
                message=f"Prometheus returned status {response.status_code}",
            )

    except Exception as e:
        duration_ms = (datetime.now(tz=UTC) - start).total_seconds() * 1000
        return SmokeTestResult(
            name=name,
            passed=False,
            duration_ms=duration_ms,
            error=str(e),
        )


async def _test_grafana_health(grafana_url: str) -> SmokeTestResult:
    """Test Grafana is healthy."""
    start = datetime.now(tz=UTC)
    name = "Grafana Health"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{grafana_url}/api/health")

            duration_ms = (datetime.now(tz=UTC) - start).total_seconds() * 1000

            if response.status_code == 200:
                data = response.json()
                return SmokeTestResult(
                    name=name,
                    passed=True,
                    duration_ms=duration_ms,
                    message=f"Grafana healthy: {data.get('database', 'ok')}",
                    details=data,
                )
            return SmokeTestResult(
                name=name,
                passed=False,
                duration_ms=duration_ms,
                message=f"Grafana returned status {response.status_code}",
            )

    except Exception as e:
        duration_ms = (datetime.now(tz=UTC) - start).total_seconds() * 1000
        return SmokeTestResult(
            name=name,
            passed=False,
            duration_ms=duration_ms,
            error=str(e),
        )


async def _test_request_creates_trace(
    orchestrator_url: str,
    jaeger_url: str,
) -> SmokeTestResult:
    """Test that a request creates a trace in Jaeger."""
    start = datetime.now(tz=UTC)
    name = "Request Creates Trace"

    try:
        # Generate unique request ID
        request_id = str(uuid4())

        # Send a test request
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{orchestrator_url}/api/v1/orchestrate/query",
                json={
                    "query": f"Smoke test query {request_id}",
                    "tenant_id": "smoke-test",
                },
                headers={
                    "X-Request-ID": request_id,
                },
            )

            if response.status_code not in [200, 201]:
                duration_ms = (datetime.now(tz=UTC) - start).total_seconds() * 1000
                return SmokeTestResult(
                    name=name,
                    passed=False,
                    duration_ms=duration_ms,
                    message=f"Request failed with status {response.status_code}",
                )

            # Wait for trace to be indexed
            await asyncio.sleep(2)

            # Search for the trace
            search_response = await client.get(
                f"{jaeger_url}/api/traces",
                params={
                    "service": "orchestrator-service",
                    "tags": f'{{"request_id":"{request_id}"}}',
                    "lookback": "5m",
                    "limit": 1,
                },
            )

            duration_ms = (datetime.now(tz=UTC) - start).total_seconds() * 1000

            if search_response.status_code == 200:
                data = search_response.json()
                traces = data.get("data", [])

                if traces:
                    trace_id = traces[0].get("traceID")
                    span_count = len(traces[0].get("spans", []))
                    return SmokeTestResult(
                        name=name,
                        passed=True,
                        duration_ms=duration_ms,
                        message=f"Trace created with {span_count} spans",
                        details={
                            "trace_id": trace_id,
                            "span_count": span_count,
                            "request_id": request_id,
                        },
                    )
                return SmokeTestResult(
                    name=name,
                    passed=False,
                    duration_ms=duration_ms,
                    message="No trace found after request",
                    details={"request_id": request_id},
                )
            return SmokeTestResult(
                name=name,
                passed=False,
                duration_ms=duration_ms,
                message=f"Jaeger search failed: {search_response.status_code}",
            )

    except Exception as e:
        duration_ms = (datetime.now(tz=UTC) - start).total_seconds() * 1000
        return SmokeTestResult(
            name=name,
            passed=False,
            duration_ms=duration_ms,
            error=str(e),
        )


async def _test_logs_in_loki(loki_url: str) -> SmokeTestResult:
    """Test that logs are being ingested in Loki."""
    start = datetime.now(tz=UTC)
    name = "Logs in Loki"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Query recent logs
            response = await client.get(
                f"{loki_url}/loki/api/v1/query",
                params={
                    "query": '{service=~".+"}',
                    "limit": 10,
                },
            )

            duration_ms = (datetime.now(tz=UTC) - start).total_seconds() * 1000

            if response.status_code == 200:
                data = response.json()
                results = data.get("data", {}).get("result", [])

                if results:
                    services = set()
                    for stream in results:
                        service = stream.get("stream", {}).get("service")
                        if service:
                            services.add(service)

                    return SmokeTestResult(
                        name=name,
                        passed=True,
                        duration_ms=duration_ms,
                        message=f"Found logs from {len(services)} services",
                        details={"services": list(services)},
                    )
                return SmokeTestResult(
                    name=name,
                    passed=False,
                    duration_ms=duration_ms,
                    message="No logs found in Loki",
                )
            return SmokeTestResult(
                name=name,
                passed=False,
                duration_ms=duration_ms,
                message=f"Loki query failed: {response.status_code}",
            )

    except Exception as e:
        duration_ms = (datetime.now(tz=UTC) - start).total_seconds() * 1000
        return SmokeTestResult(
            name=name,
            passed=False,
            duration_ms=duration_ms,
            error=str(e),
        )


async def _test_trace_log_correlation(
    jaeger_url: str,
    loki_url: str,
) -> SmokeTestResult:
    """Test trace-log correlation works."""
    start = datetime.now(tz=UTC)
    name = "Trace-Log Correlation"

    try:
        validator = TraceLogValidator(jaeger_url=jaeger_url, loki_url=loki_url)
        result = await validator.validate()

        duration_ms = (datetime.now(tz=UTC) - start).total_seconds() * 1000

        if result.correlation_valid:
            return SmokeTestResult(
                name=name,
                passed=True,
                duration_ms=duration_ms,
                message="Trace-log correlation working",
                details={
                    "samples_checked": len(result.sample_correlations),
                },
            )
        return SmokeTestResult(
            name=name,
            passed=False,
            duration_ms=duration_ms,
            message="Trace-log correlation issues found",
            details={
                "errors": result.errors,
                "recommendations": result.recommendations,
            },
        )

    except Exception as e:
        duration_ms = (datetime.now(tz=UTC) - start).total_seconds() * 1000
        return SmokeTestResult(
            name=name,
            passed=False,
            duration_ms=duration_ms,
            error=str(e),
        )


async def _test_prometheus_scrapes(prometheus_url: str) -> SmokeTestResult:
    """Test Prometheus is scraping all targets."""
    start = datetime.now(tz=UTC)
    name = "Prometheus Scrapes"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{prometheus_url}/api/v1/targets")

            duration_ms = (datetime.now(tz=UTC) - start).total_seconds() * 1000

            if response.status_code == 200:
                data = response.json()
                targets = data.get("data", {}).get("activeTargets", [])

                up_targets = [t for t in targets if t.get("health") == "up"]
                down_targets = [t for t in targets if t.get("health") != "up"]

                if len(down_targets) == 0:
                    return SmokeTestResult(
                        name=name,
                        passed=True,
                        duration_ms=duration_ms,
                        message=f"All {len(up_targets)} targets up",
                        details={"up_count": len(up_targets)},
                    )
                return SmokeTestResult(
                    name=name,
                    passed=False,
                    duration_ms=duration_ms,
                    message=f"{len(down_targets)} targets down",
                    details={
                        "up_count": len(up_targets),
                        "down_count": len(down_targets),
                        "down_targets": [t.get("labels", {}).get("job") for t in down_targets],
                    },
                )
            return SmokeTestResult(
                name=name,
                passed=False,
                duration_ms=duration_ms,
                message=f"Prometheus API failed: {response.status_code}",
            )

    except Exception as e:
        duration_ms = (datetime.now(tz=UTC) - start).total_seconds() * 1000
        return SmokeTestResult(
            name=name,
            passed=False,
            duration_ms=duration_ms,
            error=str(e),
        )


async def _test_grafana_datasources(grafana_url: str) -> SmokeTestResult:
    """Test Grafana datasources are configured."""
    start = datetime.now(tz=UTC)
    name = "Grafana Datasources"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{grafana_url}/api/datasources")

            duration_ms = (datetime.now(tz=UTC) - start).total_seconds() * 1000

            if response.status_code == 200:
                datasources = response.json()

                expected = {"prometheus", "loki", "jaeger"}
                found = {ds.get("type") for ds in datasources}

                missing = expected - found

                if not missing:
                    return SmokeTestResult(
                        name=name,
                        passed=True,
                        duration_ms=duration_ms,
                        message=f"All {len(datasources)} datasources configured",
                        details={
                            "datasources": [ds.get("name") for ds in datasources],
                        },
                    )
                return SmokeTestResult(
                    name=name,
                    passed=False,
                    duration_ms=duration_ms,
                    message=f"Missing datasources: {missing}",
                    details={
                        "found": list(found),
                        "missing": list(missing),
                    },
                )
            return SmokeTestResult(
                name=name,
                passed=False,
                duration_ms=duration_ms,
                message=f"Grafana API failed: {response.status_code}",
            )

    except Exception as e:
        duration_ms = (datetime.now(tz=UTC) - start).total_seconds() * 1000
        return SmokeTestResult(
            name=name,
            passed=False,
            duration_ms=duration_ms,
            error=str(e),
        )
