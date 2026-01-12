"""
Loki Ingestion Validation.

Validates that logs are being ingested into Loki with proper indexing.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class LokiIngestionStatus:
    """Status of log ingestion for a service."""

    service_name: str
    is_ingesting: bool
    log_count_1h: int = 0
    has_trace_id_label: bool = False
    has_span_id_label: bool = False
    sample_logs: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class LokiValidationResult:
    """Result of Loki validation."""

    is_valid: bool
    services: list[LokiIngestionStatus]
    loki_healthy: bool
    total_services: int
    ingesting_services: int
    trace_correlation_enabled: bool
    validation_time: datetime = field(default_factory=datetime.utcnow)
    errors: list[str] = field(default_factory=list)


class LokiValidator:
    """
    Validates Loki log ingestion and indexing.

    Checks:
    - Loki is healthy and accepting logs
    - All services are sending logs
    - trace_id and span_id are indexed as labels
    - JSON logs are parsed correctly
    - Log retention is configured
    """

    def __init__(
        self,
        loki_url: str = "http://loki:3100",
        expected_services: list[str] | None = None,
    ):
        """
        Initialize Loki validator.

        Args:
            loki_url: Loki query endpoint
            expected_services: List of service names that should be sending logs
        """
        self.loki_url = loki_url.rstrip("/")
        self.expected_services = expected_services or [
            "ingestion-service",
            "retrieval-service",
            "orchestrator-service",
            "llm-gateway",
        ]

    async def validate(self) -> LokiValidationResult:
        """
        Run full Loki validation.

        Returns:
            LokiValidationResult with status of all checks
        """
        errors = []
        services = []

        # Check Loki health
        loki_healthy = await self._check_loki_health()
        if not loki_healthy:
            errors.append("Loki is not healthy")

        # Check each service
        trace_correlation_enabled = True
        for service_name in self.expected_services:
            status = await self._check_service_logs(service_name)
            services.append(status)

            if not status.is_ingesting:
                errors.append(f"Service {service_name} is not sending logs")

            if not status.has_trace_id_label:
                trace_correlation_enabled = False

        ingesting_count = sum(1 for s in services if s.is_ingesting)

        return LokiValidationResult(
            is_valid=loki_healthy and ingesting_count == len(self.expected_services),
            services=services,
            loki_healthy=loki_healthy,
            total_services=len(self.expected_services),
            ingesting_services=ingesting_count,
            trace_correlation_enabled=trace_correlation_enabled,
            errors=errors,
        )

    async def _check_loki_health(self) -> bool:
        """Check if Loki is healthy."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.loki_url}/ready")
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"Loki health check failed: {e}")
            return False

    async def _check_service_logs(self, service_name: str) -> LokiIngestionStatus:
        """Check if a service is sending logs to Loki."""
        errors = []
        sample_logs = []
        has_trace_id = False
        has_span_id = False
        log_count = 0

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Query logs from this service
                end_time = datetime.now(tz=UTC)
                start_time = end_time - timedelta(hours=1)

                query = f'{{service="{service_name}"}}'

                response = await client.get(
                    f"{self.loki_url}/loki/api/v1/query_range",
                    params={
                        "query": query,
                        "start": int(start_time.timestamp() * 1e9),
                        "end": int(end_time.timestamp() * 1e9),
                        "limit": 100,
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    results = data.get("data", {}).get("result", [])

                    for stream in results:
                        labels = stream.get("stream", {})
                        values = stream.get("values", [])

                        log_count += len(values)

                        # Check for trace correlation labels
                        if "trace_id" in labels:
                            has_trace_id = True
                        if "span_id" in labels:
                            has_span_id = True

                        # Get sample logs
                        for timestamp, log_line in values[:5]:
                            sample_logs.append({
                                "timestamp": timestamp,
                                "labels": labels,
                                "line": log_line[:500],  # Truncate
                            })

                    if log_count > 0:
                        return LokiIngestionStatus(
                            service_name=service_name,
                            is_ingesting=True,
                            log_count_1h=log_count,
                            has_trace_id_label=has_trace_id,
                            has_span_id_label=has_span_id,
                            sample_logs=sample_logs,
                        )

                    errors.append("No logs found in last hour")

                else:
                    errors.append(f"Loki query failed: {response.status_code}")

        except Exception as e:
            errors.append(f"Failed to query Loki: {str(e)}")

        return LokiIngestionStatus(
            service_name=service_name,
            is_ingesting=False,
            has_trace_id_label=has_trace_id,
            has_span_id_label=has_span_id,
            sample_logs=sample_logs,
            errors=errors,
        )

    async def query_logs_by_trace_id(
        self,
        trace_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Query logs by trace ID.

        Args:
            trace_id: The trace ID to search for
            limit: Maximum number of logs to return

        Returns:
            List of log entries
        """
        logs = []

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                end_time = datetime.now(tz=UTC)
                start_time = end_time - timedelta(hours=24)

                # Try label-based query first (more efficient)
                query = f'{{trace_id="{trace_id}"}}'

                response = await client.get(
                    f"{self.loki_url}/loki/api/v1/query_range",
                    params={
                        "query": query,
                        "start": int(start_time.timestamp() * 1e9),
                        "end": int(end_time.timestamp() * 1e9),
                        "limit": limit,
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    results = data.get("data", {}).get("result", [])

                    for stream in results:
                        labels = stream.get("stream", {})
                        values = stream.get("values", [])

                        for timestamp, log_line in values:
                            logs.append({
                                "timestamp": timestamp,
                                "service": labels.get("service", "unknown"),
                                "trace_id": labels.get("trace_id"),
                                "span_id": labels.get("span_id"),
                                "line": log_line,
                            })

                # If no results with label, try content search
                if not logs:
                    query = f'{{}} |= "{trace_id}"'

                    response = await client.get(
                        f"{self.loki_url}/loki/api/v1/query_range",
                        params={
                            "query": query,
                            "start": int(start_time.timestamp() * 1e9),
                            "end": int(end_time.timestamp() * 1e9),
                            "limit": limit,
                        },
                    )

                    if response.status_code == 200:
                        data = response.json()
                        results = data.get("data", {}).get("result", [])

                        for stream in results:
                            labels = stream.get("stream", {})
                            values = stream.get("values", [])

                            for timestamp, log_line in values:
                                logs.append({
                                    "timestamp": timestamp,
                                    "service": labels.get("service", "unknown"),
                                    "line": log_line,
                                })

        except Exception as e:
            logger.error(f"Failed to query logs by trace_id: {e}")

        # Sort by timestamp
        logs.sort(key=lambda x: x["timestamp"])
        return logs

    async def get_ingestion_stats(self) -> dict[str, Any]:
        """
        Get Loki ingestion statistics.

        Returns:
            Dictionary with ingestion stats
        """
        stats = {
            "streams_total": 0,
            "logs_1h": 0,
            "bytes_1h": 0,
            "services": [],
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Get label values for service
                response = await client.get(
                    f"{self.loki_url}/loki/api/v1/label/service/values",
                )

                if response.status_code == 200:
                    data = response.json()
                    services = data.get("data", [])
                    stats["services"] = services

                # Get series count
                response = await client.get(
                    f"{self.loki_url}/loki/api/v1/series",
                    params={
                        "match[]": "{}",
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    stats["streams_total"] = len(data.get("data", []))

        except Exception as e:
            logger.error(f"Failed to get ingestion stats: {e}")

        return stats

    async def verify_json_parsing(self, service_name: str) -> dict[str, Any]:
        """
        Verify that JSON logs are being parsed correctly.

        Args:
            service_name: Service to check

        Returns:
            Verification result
        """
        result = {
            "service": service_name,
            "json_parsing_working": False,
            "extracted_fields": [],
            "sample_parsed": None,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                end_time = datetime.now(tz=UTC)
                start_time = end_time - timedelta(hours=1)

                # Query with JSON extraction
                query = f'{{service="{service_name}"}} | json'

                response = await client.get(
                    f"{self.loki_url}/loki/api/v1/query_range",
                    params={
                        "query": query,
                        "start": int(start_time.timestamp() * 1e9),
                        "end": int(end_time.timestamp() * 1e9),
                        "limit": 1,
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    results = data.get("data", {}).get("result", [])

                    if results:
                        stream = results[0]
                        labels = stream.get("stream", {})

                        # Check for extracted JSON fields
                        json_fields = [
                            k for k in labels
                            if k not in ["service", "namespace", "pod", "container"]
                        ]

                        result["json_parsing_working"] = len(json_fields) > 0
                        result["extracted_fields"] = json_fields

                        if stream.get("values"):
                            result["sample_parsed"] = {
                                "labels": labels,
                                "line": stream["values"][0][1][:500],
                            }

        except Exception as e:
            result["error"] = str(e)

        return result
