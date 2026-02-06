"""OpenSearch backend for high-volume audit log storage."""

import os
import ssl
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog
from opensearchpy import OpenSearch

from orchestrator.audit.backends.base import AuditBackend
from orchestrator.audit.models import (
    AuditAction,
    AuditLogEntry,
    AuditOutcome,
    AuditQuery,
    AuditSeverity,
    AuditStats,
)

logger = structlog.get_logger(__name__)


class OpenSearchAuditBackend(AuditBackend):
    """
    OpenSearch backend for audit log storage.

    Provides high-volume audit log storage with daily index rotation,
    full-text search, and aggregation support for statistics.

    Index naming convention: {prefix}-{YYYY.MM.DD}
    """

    def __init__(
        self,
        opensearch_url: str | None = None,
        index_prefix: str | None = None,
        username: str | None = None,
        password: str | None = None,
        use_ssl: bool | None = None,
        verify_certs: bool | None = None,
        ca_cert_path: str | None = None,
    ):
        """
        Initialize OpenSearch audit backend.

        Args:
            opensearch_url: OpenSearch URL. Defaults to AUDIT_OPENSEARCH_URL env var
                or http://localhost:9200.
            index_prefix: Index prefix for daily indices. Defaults to
                AUDIT_OPENSEARCH_INDEX_PREFIX env var or 'audit-logs'.
            username: OpenSearch username. Defaults to AUDIT_OPENSEARCH_USERNAME env var.
            password: OpenSearch password. Defaults to AUDIT_OPENSEARCH_PASSWORD env var.
            use_ssl: Enable SSL/TLS. Defaults to AUDIT_OPENSEARCH_USE_SSL env var.
            verify_certs: Verify SSL certificates. Defaults to
                AUDIT_OPENSEARCH_VERIFY_CERTS env var.
            ca_cert_path: Path to CA certificate. Defaults to AUDIT_OPENSEARCH_CA_CERT
                env var.
        """
        self._opensearch_url = opensearch_url or os.getenv(
            "AUDIT_OPENSEARCH_URL", "http://localhost:9200"
        )
        self._index_prefix = index_prefix or os.getenv(
            "AUDIT_OPENSEARCH_INDEX_PREFIX", "audit-logs"
        )

        # Authentication configuration
        self._username = username or os.getenv("AUDIT_OPENSEARCH_USERNAME")
        self._password = password or os.getenv("AUDIT_OPENSEARCH_PASSWORD")

        # SSL configuration
        self._use_ssl = (
            use_ssl
            if use_ssl is not None
            else (os.getenv("AUDIT_OPENSEARCH_USE_SSL", "false").lower() == "true")
        )
        self._verify_certs = (
            verify_certs
            if verify_certs is not None
            else (os.getenv("AUDIT_OPENSEARCH_VERIFY_CERTS", "true").lower() == "true")
        )
        self._ca_cert_path = ca_cert_path or os.getenv("AUDIT_OPENSEARCH_CA_CERT")

        self.__client: OpenSearch | None = None

    def _get_client(self) -> OpenSearch:
        """Lazy-initialize and return the OpenSearch client."""
        if self.__client is None:
            # Build authentication tuple if credentials provided
            http_auth = None
            if self._username and self._password:
                http_auth = (self._username, self._password)

            # Build SSL context
            ssl_context = self._create_ssl_context()

            self.__client = OpenSearch(
                hosts=[self._opensearch_url],
                http_auth=http_auth,
                use_ssl=self._use_ssl,
                verify_certs=self._verify_certs,
                ssl_context=ssl_context,
                ssl_show_warn=False,
                http_compress=True,
                timeout=30,
                max_retries=3,
                retry_on_timeout=True,
            )
        return self.__client

    def _set_client(self, client: OpenSearch | None) -> None:
        """Set the OpenSearch client (for testing)."""
        self.__client = client

    def _create_ssl_context(self) -> ssl.SSLContext | None:
        """
        Create SSL context for secure connections.

        Returns:
            SSL context configured for OpenSearch, or None if SSL disabled.
        """
        if not self._use_ssl:
            return None

        ssl_context = ssl.create_default_context()
        ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2

        # Load CA certificate for server verification
        if self._ca_cert_path and Path(self._ca_cert_path).exists():
            ssl_context.load_verify_locations(self._ca_cert_path)

        # Configure verification based on settings
        if not self._verify_certs:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        return ssl_context

    def _get_index_name(self, timestamp: datetime) -> str:
        """
        Get the index name for a given timestamp.

        Uses daily index rotation with pattern: {prefix}-{YYYY.MM.DD}

        Args:
            timestamp: The timestamp to get the index for.

        Returns:
            Index name string.
        """
        # Ensure we're working with UTC
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        else:
            timestamp = timestamp.astimezone(UTC)

        date_str = timestamp.strftime("%Y.%m.%d")
        return f"{self._index_prefix}-{date_str}"

    def _get_index_mapping(self) -> dict[str, Any]:
        """
        Get the index mapping for audit log indices.

        Returns:
            OpenSearch index mapping configuration.
        """
        return {
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 1,
                "refresh_interval": "5s",
            },
            "mappings": {
                "properties": {
                    # Identity fields
                    "id": {"type": "keyword"},
                    "trace_id": {"type": "keyword"},
                    "span_id": {"type": "keyword"},
                    # Timing
                    "timestamp": {"type": "date"},
                    "duration_ms": {"type": "float"},
                    # Actor
                    "user_id": {"type": "keyword"},
                    "username": {"type": "keyword"},
                    "tenant_id": {"type": "keyword"},
                    "service_name": {"type": "keyword"},
                    "api_key_id": {"type": "keyword"},
                    # Action
                    "action": {"type": "keyword"},
                    "outcome": {"type": "keyword"},
                    "severity": {"type": "keyword"},
                    # Resource
                    "resource_type": {"type": "keyword"},
                    "resource_id": {"type": "keyword"},
                    "resource_name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                    # Request context
                    "client_ip": {"type": "ip"},
                    "user_agent": {"type": "text"},
                    "request_method": {"type": "keyword"},
                    "request_path": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                    "request_id": {"type": "keyword"},
                    # Response
                    "status_code": {"type": "integer"},
                    "error_message": {"type": "text"},
                    "error_code": {"type": "keyword"},
                    # Additional context
                    "details": {"type": "object", "enabled": True},
                    "changes": {"type": "object", "enabled": True},
                    # Tamper evidence
                    "previous_hash": {"type": "keyword"},
                    "entry_hash": {"type": "keyword"},
                },
            },
        }

    def _entry_to_document(self, entry: AuditLogEntry) -> dict[str, Any]:
        """
        Convert an AuditLogEntry to an OpenSearch document.

        Args:
            entry: The audit log entry to convert.

        Returns:
            Dict suitable for OpenSearch indexing.
        """
        doc = {
            "id": str(entry.id),
            "timestamp": entry.timestamp.isoformat(),
            "action": entry.action.value,
            "outcome": entry.outcome.value,
            "severity": entry.severity.value,
        }

        # Add optional fields if present
        if entry.trace_id:
            doc["trace_id"] = entry.trace_id
        if entry.span_id:
            doc["span_id"] = entry.span_id
        if entry.duration_ms is not None:
            doc["duration_ms"] = entry.duration_ms
        if entry.user_id:
            doc["user_id"] = str(entry.user_id)
        if entry.username:
            doc["username"] = entry.username
        if entry.tenant_id:
            doc["tenant_id"] = str(entry.tenant_id)
        if entry.service_name:
            doc["service_name"] = entry.service_name
        if entry.api_key_id:
            doc["api_key_id"] = entry.api_key_id
        if entry.resource_type:
            doc["resource_type"] = entry.resource_type
        if entry.resource_id:
            doc["resource_id"] = entry.resource_id
        if entry.resource_name:
            doc["resource_name"] = entry.resource_name
        if entry.client_ip:
            doc["client_ip"] = entry.client_ip
        if entry.user_agent:
            doc["user_agent"] = entry.user_agent
        if entry.request_method:
            doc["request_method"] = entry.request_method
        if entry.request_path:
            doc["request_path"] = entry.request_path
        if entry.request_id:
            doc["request_id"] = entry.request_id
        if entry.status_code is not None:
            doc["status_code"] = entry.status_code
        if entry.error_message:
            doc["error_message"] = entry.error_message
        if entry.error_code:
            doc["error_code"] = entry.error_code
        if entry.details:
            doc["details"] = entry.details
        if entry.changes:
            doc["changes"] = entry.changes
        if entry.previous_hash:
            doc["previous_hash"] = entry.previous_hash
        if entry.entry_hash:
            doc["entry_hash"] = entry.entry_hash

        return doc

    def _document_to_entry(self, doc: dict[str, Any]) -> AuditLogEntry:
        """
        Convert an OpenSearch document to an AuditLogEntry.

        Args:
            doc: The OpenSearch document.

        Returns:
            AuditLogEntry instance.
        """
        from uuid import UUID as UUIDType

        return AuditLogEntry(
            id=UUIDType(doc["id"]),
            trace_id=doc.get("trace_id"),
            span_id=doc.get("span_id"),
            timestamp=datetime.fromisoformat(doc["timestamp"]),
            duration_ms=doc.get("duration_ms"),
            user_id=UUIDType(doc["user_id"]) if doc.get("user_id") else None,
            username=doc.get("username"),
            tenant_id=UUIDType(doc["tenant_id"]) if doc.get("tenant_id") else None,
            service_name=doc.get("service_name"),
            api_key_id=doc.get("api_key_id"),
            action=AuditAction(doc["action"]),
            outcome=AuditOutcome(doc["outcome"]),
            severity=AuditSeverity(doc["severity"]),
            resource_type=doc.get("resource_type"),
            resource_id=doc.get("resource_id"),
            resource_name=doc.get("resource_name"),
            client_ip=doc.get("client_ip"),
            user_agent=doc.get("user_agent"),
            request_method=doc.get("request_method"),
            request_path=doc.get("request_path"),
            request_id=doc.get("request_id"),
            status_code=doc.get("status_code"),
            error_message=doc.get("error_message"),
            error_code=doc.get("error_code"),
            details=doc.get("details", {}),
            changes=doc.get("changes"),
            previous_hash=doc.get("previous_hash"),
            entry_hash=doc.get("entry_hash"),
        )

    async def _ensure_index_exists(self, index_name: str) -> None:
        """
        Ensure an index exists, creating it if necessary.

        Args:
            index_name: The index name to check/create.
        """
        if not self._get_client().indices.exists(index=index_name):
            try:
                self._get_client().indices.create(
                    index=index_name,
                    body=self._get_index_mapping(),
                )
                logger.info(f"Created audit index: {index_name}")
            except Exception as e:
                # Index may have been created by another process
                if "resource_already_exists_exception" not in str(e).lower():
                    raise

    async def write(self, entry: AuditLogEntry) -> None:
        """
        Write a single audit log entry to OpenSearch.

        Args:
            entry: The audit log entry to persist.

        Raises:
            Exception: If the write operation fails.
        """
        index_name = self._get_index_name(entry.timestamp)
        document = self._entry_to_document(entry)

        await self._ensure_index_exists(index_name)

        self._get_client().index(
            index=index_name,
            id=str(entry.id),
            body=document,
            refresh="false",  # Don't wait for refresh for performance
        )

        logger.debug(f"Indexed audit entry {entry.id} to {index_name}")

    def _build_query_filters(self, query: AuditQuery) -> list[dict[str, Any]]:
        """
        Build OpenSearch filter clauses from an AuditQuery.

        Args:
            query: The audit query parameters.

        Returns:
            List of filter clause dictionaries.
        """
        filters = []

        if query.tenant_id:
            filters.append({"term": {"tenant_id": str(query.tenant_id)}})

        if query.user_id:
            filters.append({"term": {"user_id": str(query.user_id)}})

        if query.actions:
            filters.append({"terms": {"action": [a.value for a in query.actions]}})

        if query.outcomes:
            filters.append({"terms": {"outcome": [o.value for o in query.outcomes]}})

        if query.severities:
            filters.append({"terms": {"severity": [s.value for s in query.severities]}})

        if query.resource_type:
            filters.append({"term": {"resource_type": query.resource_type}})

        if query.resource_id:
            filters.append({"term": {"resource_id": query.resource_id}})

        if query.client_ip:
            filters.append({"term": {"client_ip": query.client_ip}})

        if query.trace_id:
            filters.append({"term": {"trace_id": query.trace_id}})

        # Time range filter
        if query.start_time or query.end_time:
            range_filter: dict[str, Any] = {}
            if query.start_time:
                range_filter["gte"] = query.start_time.isoformat()
            if query.end_time:
                range_filter["lte"] = query.end_time.isoformat()
            filters.append({"range": {"timestamp": range_filter}})

        return filters

    def _get_index_pattern(self, query: AuditQuery) -> str:
        """
        Get the index pattern for a query.

        If time range is specified, creates a more specific pattern.
        Otherwise, uses wildcard to search all indices.

        Args:
            query: The audit query.

        Returns:
            Index pattern string.
        """
        if not query.start_time and not query.end_time:
            return f"{self._index_prefix}-*"

        # For simplicity, use wildcard for now
        # A more optimized version could calculate specific date ranges
        return f"{self._index_prefix}-*"

    async def query(self, query: AuditQuery) -> list[AuditLogEntry]:
        """
        Query audit logs based on filter criteria.

        Args:
            query: Query parameters including filters, pagination, and ordering.

        Returns:
            List of matching audit log entries.

        Raises:
            Exception: If the query operation fails.
        """
        filters = self._build_query_filters(query)
        index_pattern = self._get_index_pattern(query)

        # Build the query body
        bool_query: dict[str, Any] = {"filter": filters} if filters else {}

        # Add full-text search if provided
        if query.search_text:
            bool_query["must"] = [
                {
                    "multi_match": {
                        "query": query.search_text,
                        "fields": [
                            "error_message",
                            "resource_name",
                            "request_path",
                            "user_agent",
                        ],
                        "type": "best_fields",
                    }
                }
            ]

        # Build sort
        sort_order = "desc" if query.order_desc else "asc"
        sort = [{query.order_by: {"order": sort_order}}]

        body = {
            "query": {"bool": bool_query} if bool_query else {"match_all": {}},
            "sort": sort,
            "from": query.offset,
            "size": query.limit,
        }

        response = self._get_client().search(
            index=index_pattern,
            body=body,
            ignore_unavailable=True,  # Ignore missing indices
        )

        entries = []
        for hit in response["hits"]["hits"]:
            try:
                entry = self._document_to_entry(hit["_source"])
                entries.append(entry)
            except Exception as e:
                logger.warning(f"Failed to parse audit entry: {e}")
                continue

        return entries

    async def get_stats(
        self,
        tenant_id: UUID | None,
        start_time: datetime | None,
        end_time: datetime | None,
    ) -> AuditStats:
        """
        Get aggregated statistics for audit logs.

        Args:
            tenant_id: Optional tenant ID to filter by.
            start_time: Optional start of time range.
            end_time: Optional end of time range.

        Returns:
            Statistics about audit logs in the given scope.

        Raises:
            Exception: If the stats operation fails.
        """
        # Build filters
        filters = []
        if tenant_id:
            filters.append({"term": {"tenant_id": str(tenant_id)}})

        if start_time or end_time:
            range_filter: dict[str, Any] = {}
            if start_time:
                range_filter["gte"] = start_time.isoformat()
            if end_time:
                range_filter["lte"] = end_time.isoformat()
            filters.append({"range": {"timestamp": range_filter}})

        # Build aggregation query
        body: dict[str, Any] = {
            "size": 0,  # We only want aggregations, not hits
            "aggs": {
                "by_action": {"terms": {"field": "action", "size": 100}},
                "by_outcome": {"terms": {"field": "outcome", "size": 10}},
                "by_severity": {"terms": {"field": "severity", "size": 10}},
                "unique_users": {"cardinality": {"field": "user_id"}},
                "unique_resources": {"cardinality": {"field": "resource_id"}},
            },
        }

        if filters:
            body["query"] = {"bool": {"filter": filters}}

        index_pattern = f"{self._index_prefix}-*"
        response = self._get_client().search(
            index=index_pattern,
            body=body,
            ignore_unavailable=True,
        )

        # Parse aggregation results
        total = response["hits"]["total"]["value"]
        aggs = response.get("aggregations", {})

        entries_by_action = {
            bucket["key"]: bucket["doc_count"]
            for bucket in aggs.get("by_action", {}).get("buckets", [])
        }

        entries_by_outcome = {
            bucket["key"]: bucket["doc_count"]
            for bucket in aggs.get("by_outcome", {}).get("buckets", [])
        }

        entries_by_severity = {
            bucket["key"]: bucket["doc_count"]
            for bucket in aggs.get("by_severity", {}).get("buckets", [])
        }

        unique_users = int(aggs.get("unique_users", {}).get("value", 0))
        unique_resources = int(aggs.get("unique_resources", {}).get("value", 0))

        return AuditStats(
            total_entries=total,
            entries_by_action=entries_by_action,
            entries_by_outcome=entries_by_outcome,
            entries_by_severity=entries_by_severity,
            unique_users=unique_users,
            unique_resources=unique_resources,
            time_range_start=start_time,
            time_range_end=end_time,
        )

    async def health_check(self) -> bool:
        """
        Check if the backend is healthy and accessible.

        Returns:
            True if the backend is healthy, False otherwise.
        """
        try:
            health = self._get_client().cluster.health()
            return health["status"] in ["green", "yellow"]
        except Exception as e:
            logger.warning(f"Audit OpenSearch health check failed: {e}")
            return False
