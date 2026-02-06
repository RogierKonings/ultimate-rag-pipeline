"""
Trace-Log Correlation Validation.

Validates that traces and logs are properly correlated.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import structlog

from .loki import LokiValidator
from .otlp import OTLPValidator

logger = structlog.get_logger(__name__)


@dataclass
class CorrelationResult:
    """Result of trace-log correlation check."""

    trace_id: str
    is_correlated: bool
    trace_found: bool
    logs_found: bool
    trace_services: list[str] = field(default_factory=list)
    log_services: list[str] = field(default_factory=list)
    span_count: int = 0
    log_count: int = 0
    missing_log_services: list[str] = field(default_factory=list)
    correlation_method: str = ""  # "label" or "content"
    validation_time: datetime = field(default_factory=datetime.utcnow)
    errors: list[str] = field(default_factory=list)


@dataclass
class TraceLogValidationResult:
    """Full validation result for trace-log correlation."""

    is_valid: bool
    otlp_valid: bool
    loki_valid: bool
    correlation_valid: bool
    sample_correlations: list[CorrelationResult] = field(default_factory=list)
    validation_time: datetime = field(default_factory=datetime.utcnow)
    errors: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


class TraceLogValidator:
    """
    Validates trace-log correlation across the observability stack.

    Checks:
    - Traces exist in Jaeger/Tempo
    - Logs exist in Loki with trace_id labels
    - Both sources have data for the same services
    - Correlation is queryable in Grafana
    """

    def __init__(
        self,
        otlp_validator: OTLPValidator | None = None,
        loki_validator: LokiValidator | None = None,
        jaeger_url: str = "http://jaeger:16686",
        loki_url: str = "http://loki:3100",
        expected_services: list[str] | None = None,
    ):
        """
        Initialize trace-log validator.

        Args:
            otlp_validator: Pre-configured OTLP validator
            loki_validator: Pre-configured Loki validator
            jaeger_url: Jaeger query endpoint
            loki_url: Loki query endpoint
            expected_services: Services that should have both traces and logs
        """
        self.expected_services = expected_services or [
            "ingestion-service",
            "retrieval-service",
            "orchestrator-service",
            "llm-gateway",
        ]

        self.otlp_validator = otlp_validator or OTLPValidator(
            jaeger_url=jaeger_url,
            expected_services=self.expected_services,
        )

        self.loki_validator = loki_validator or LokiValidator(
            loki_url=loki_url,
            expected_services=self.expected_services,
        )

    async def validate(self) -> TraceLogValidationResult:
        """
        Run full trace-log correlation validation.

        Returns:
            TraceLogValidationResult with status of all checks
        """
        errors = []
        recommendations = []

        # Validate OTLP
        otlp_result = await self.otlp_validator.validate()
        otlp_valid = otlp_result.is_valid

        if not otlp_valid:
            errors.extend(otlp_result.errors)

        # Validate Loki
        loki_result = await self.loki_validator.validate()
        loki_valid = loki_result.is_valid

        if not loki_valid:
            errors.extend(loki_result.errors)

        # Check trace_id labeling
        if not loki_result.trace_correlation_enabled:
            recommendations.append(
                "Enable trace_id label extraction in Promtail/OTEL log pipeline",
            )

        # Sample correlation checks
        sample_correlations = []
        correlation_valid = True

        # Get recent trace IDs to test correlation
        trace_ids = await self._get_recent_trace_ids()

        for trace_id in trace_ids[:3]:  # Test up to 3 traces
            correlation = await self.validate_correlation(trace_id)
            sample_correlations.append(correlation)

            if not correlation.is_correlated:
                correlation_valid = False

        if not correlation_valid:
            recommendations.append(
                "Ensure trace context is propagated to logging framework",
            )

        return TraceLogValidationResult(
            is_valid=otlp_valid and loki_valid and correlation_valid,
            otlp_valid=otlp_valid,
            loki_valid=loki_valid,
            correlation_valid=correlation_valid,
            sample_correlations=sample_correlations,
            errors=errors,
            recommendations=recommendations,
        )

    async def validate_correlation(
        self,
        trace_id: str,
        expected_services: list[str] | None = None,
    ) -> CorrelationResult:
        """
        Validate correlation for a specific trace.

        Args:
            trace_id: The trace ID to check
            expected_services: Services expected to have both traces and logs

        Returns:
            CorrelationResult with detailed status
        """
        expected = expected_services or self.expected_services
        errors = []

        # Check trace exists
        trace_result = await self.otlp_validator.validate_trace_propagation(
            trace_id,
            expected,
        )

        trace_found = (
            trace_result.get("valid", False)
            or len(
                trace_result.get("services_found", []),
            )
            > 0
        )
        trace_services = trace_result.get("services_found", [])
        span_count = trace_result.get("span_count", 0)

        if not trace_found:
            errors.append(f"Trace {trace_id} not found in Jaeger/Tempo")

        # Check logs exist
        logs = await self.loki_validator.query_logs_by_trace_id(trace_id)
        logs_found = len(logs) > 0

        log_services = list({log.get("service") for log in logs if log.get("service")})
        log_count = len(logs)

        # Determine correlation method
        correlation_method = "none"
        if logs_found:
            # Check if using label-based correlation
            has_trace_label = any(log.get("trace_id") == trace_id for log in logs)
            correlation_method = "label" if has_trace_label else "content"

        if not logs_found:
            errors.append(f"No logs found for trace {trace_id}")

        # Find missing services
        missing_log_services = [s for s in trace_services if s not in log_services]

        is_correlated = trace_found and logs_found and len(missing_log_services) == 0

        return CorrelationResult(
            trace_id=trace_id,
            is_correlated=is_correlated,
            trace_found=trace_found,
            logs_found=logs_found,
            trace_services=trace_services,
            log_services=log_services,
            span_count=span_count,
            log_count=log_count,
            missing_log_services=missing_log_services,
            correlation_method=correlation_method,
            errors=errors,
        )

    async def _get_recent_trace_ids(self, limit: int = 10) -> list[str]:
        """Get recent trace IDs from Jaeger."""
        import httpx

        trace_ids = []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Query recent traces from orchestrator (usually has most spans)
                response = await client.get(
                    f"{self.otlp_validator.jaeger_url}/api/traces",
                    params={
                        "service": "orchestrator-service",
                        "lookback": "1h",
                        "limit": limit,
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    traces = data.get("data", [])

                    for trace in traces:
                        trace_id = trace.get("traceID")
                        if trace_id:
                            trace_ids.append(trace_id)

        except Exception as e:
            logger.warning(f"Failed to get recent traces: {e}")

        return trace_ids

    async def generate_grafana_explore_url(
        self,
        trace_id: str,
        grafana_url: str = "http://grafana:3000",
    ) -> dict[str, str]:
        """
        Generate Grafana Explore URLs for a trace.

        Args:
            trace_id: The trace ID
            grafana_url: Base Grafana URL

        Returns:
            Dictionary with trace and log URLs
        """
        import urllib.parse

        # Trace URL (Jaeger datasource)
        trace_query = f'{{"traceId":"{trace_id}"}}'
        trace_url = (
            f"{grafana_url}/explore?"
            f"orgId=1&left=%5B%22now-1h%22,%22now%22,%22Jaeger%22,"
            f"{urllib.parse.quote(trace_query)}%5D"
        )

        # Log URL (Loki datasource)
        log_query = f'{{trace_id="{trace_id}"}}'
        log_url = (
            f"{grafana_url}/explore?"
            f"orgId=1&left=%5B%22now-1h%22,%22now%22,%22Loki%22,"
            f'{{"expr":{urllib.parse.quote(f"{log_query}")}}}%5D'
        )

        return {
            "trace_url": trace_url,
            "log_url": log_url,
            "trace_id": trace_id,
        }


async def run_correlation_check(
    trace_id: str | None = None,
    jaeger_url: str = "http://jaeger:16686",
    loki_url: str = "http://loki:3100",
) -> dict[str, Any]:
    """
    Run a quick correlation check.

    Args:
        trace_id: Optional specific trace ID to check
        jaeger_url: Jaeger endpoint
        loki_url: Loki endpoint

    Returns:
        Correlation check results
    """
    validator = TraceLogValidator(
        jaeger_url=jaeger_url,
        loki_url=loki_url,
    )

    if trace_id:
        result = await validator.validate_correlation(trace_id)
        return result.__dict__
    result = await validator.validate()
    return {
        "is_valid": result.is_valid,
        "otlp_valid": result.otlp_valid,
        "loki_valid": result.loki_valid,
        "correlation_valid": result.correlation_valid,
        "sample_count": len(result.sample_correlations),
        "errors": result.errors,
        "recommendations": result.recommendations,
    }
