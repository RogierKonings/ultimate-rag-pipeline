"""
TracedOpenSearchClient - OpenTelemetry instrumented wrapper for OpenSearch.

This module provides a composition-based wrapper around the OpenSearch AsyncOpenSearch
client that automatically creates OTEL spans for all database operations.

Usage:
    from opensearchpy import AsyncOpenSearch
    from observability.clients.traced_opensearch import TracedOpenSearchClient

    # Create traced client
    opensearch = AsyncOpenSearch(hosts=["http://localhost:9200"])
    traced = TracedOpenSearchClient(client=opensearch, index_name="documents")

    # All operations are automatically traced
    results = await traced.search(body={"query": {"match_all": {}}})
"""

from typing import Any

import structlog
from observability.otel.span_names import SpanNames
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

logger = structlog.get_logger(__name__)

# Get tracer for this module
tracer = trace.get_tracer(__name__)


class TracedOpenSearchClient:
    """
    OpenTelemetry-instrumented wrapper for OpenSearch AsyncOpenSearch client.

    Uses composition to wrap an existing client instance, adding tracing
    to all database operations without modifying the underlying client.

    Attributes:
        _client: The underlying OpenSearch client
        _index_name: Default index name for operations
    """

    def __init__(
        self,
        client: Any,
        index_name: str,
    ) -> None:
        """
        Initialize TracedOpenSearchClient.

        Args:
            client: An AsyncOpenSearch instance to wrap
            index_name: Default index name for operations
        """
        self._client = client
        self._index_name = index_name

    @property
    def client(self) -> Any:
        """Return the underlying OpenSearch client."""
        return self._client

    @property
    def index_name(self) -> str:
        """Return the default index name."""
        return self._index_name

    async def search(
        self,
        body: dict[str, Any],
        index: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Execute a search query with tracing.

        Args:
            body: Search query body (DSL query)
            index: Index to search (defaults to instance index)
            **kwargs: Additional arguments passed to underlying client

        Returns:
            Search results from OpenSearch

        Raises:
            Exception: If the search fails
        """
        effective_index = index or self._index_name

        with tracer.start_as_current_span(
            SpanNames.OPENSEARCH_QUERY,
            kind=SpanKind.CLIENT,
        ) as span:
            # Set span attributes
            span.set_attribute("db.system", "opensearch")
            span.set_attribute("db.operation", "search")
            span.set_attribute("db.elasticsearch.index", effective_index)

            try:
                result = await self._client.search(
                    index=effective_index,
                    body=body,
                    **kwargs,
                )

                # Record result count from hits.total.value
                result_count = 0
                if isinstance(result, dict):
                    hits = result.get("hits", {})
                    total = hits.get("total", {})
                    if isinstance(total, dict):
                        result_count = total.get("value", 0)
                    elif isinstance(total, int):
                        result_count = total

                span.set_attribute("db.opensearch.result_count", result_count)
                span.set_status(Status(StatusCode.OK))

                return result

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                logger.error(
                    f"OpenSearch search failed: {e}",
                    extra={
                        "index": effective_index,
                    },
                )
                raise

    async def index(
        self,
        body: dict[str, Any],
        doc_id: str | None = None,
        index: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Index a document with tracing.

        Args:
            body: Document to index
            doc_id: Document ID (optional, auto-generated if not provided)
            index: Index to insert into (defaults to instance index)
            **kwargs: Additional arguments passed to underlying client

        Returns:
            Index response from OpenSearch

        Raises:
            Exception: If the index operation fails
        """
        effective_index = index or self._index_name

        with tracer.start_as_current_span(
            SpanNames.OPENSEARCH_INDEX,
            kind=SpanKind.CLIENT,
        ) as span:
            # Set span attributes
            span.set_attribute("db.system", "opensearch")
            span.set_attribute("db.operation", "index")
            span.set_attribute("db.elasticsearch.index", effective_index)
            if doc_id:
                span.set_attribute("db.elasticsearch.doc_id", doc_id)

            try:
                result = await self._client.index(
                    index=effective_index,
                    body=body,
                    id=doc_id,
                    **kwargs,
                )

                span.set_status(Status(StatusCode.OK))
                return result

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                logger.error(
                    f"OpenSearch index failed: {e}",
                    extra={
                        "index": effective_index,
                        "doc_id": doc_id,
                    },
                )
                raise

    async def bulk(
        self,
        body: list[dict[str, Any]],
        index: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Execute bulk operations with tracing.

        Args:
            body: List of bulk operations
            index: Default index for operations (optional)
            **kwargs: Additional arguments passed to underlying client

        Returns:
            Bulk response from OpenSearch

        Raises:
            Exception: If the bulk operation fails
        """
        effective_index = index or self._index_name

        with tracer.start_as_current_span(
            SpanNames.OPENSEARCH_BULK,
            kind=SpanKind.CLIENT,
        ) as span:
            # Set span attributes
            span.set_attribute("db.system", "opensearch")
            span.set_attribute("db.operation", "bulk")
            if effective_index:
                span.set_attribute("db.elasticsearch.index", effective_index)
            span.set_attribute("db.opensearch.operations_count", len(body) // 2)

            try:
                call_kwargs = {"body": body, **kwargs}
                if index:
                    call_kwargs["index"] = index

                result = await self._client.bulk(**call_kwargs)

                # Record if there were errors
                has_errors = result.get("errors", False) if isinstance(result, dict) else False
                span.set_attribute("db.opensearch.has_errors", has_errors)
                span.set_status(Status(StatusCode.OK))

                return result

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                logger.error(
                    f"OpenSearch bulk failed: {e}",
                    extra={"operations_count": len(body) // 2},
                )
                raise

    async def delete(
        self,
        doc_id: str,
        index: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Delete a document with tracing.

        Args:
            doc_id: Document ID to delete
            index: Index to delete from (defaults to instance index)
            **kwargs: Additional arguments passed to underlying client

        Returns:
            Delete response from OpenSearch

        Raises:
            Exception: If the delete fails
        """
        effective_index = index or self._index_name

        with tracer.start_as_current_span(
            SpanNames.OPENSEARCH_DELETE,
            kind=SpanKind.CLIENT,
        ) as span:
            # Set span attributes
            span.set_attribute("db.system", "opensearch")
            span.set_attribute("db.operation", "delete")
            span.set_attribute("db.elasticsearch.index", effective_index)
            span.set_attribute("db.elasticsearch.doc_id", doc_id)

            try:
                result = await self._client.delete(
                    index=effective_index,
                    id=doc_id,
                    **kwargs,
                )

                span.set_status(Status(StatusCode.OK))
                return result

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                logger.error(
                    f"OpenSearch delete failed: {e}",
                    extra={
                        "index": effective_index,
                        "doc_id": doc_id,
                    },
                )
                raise
