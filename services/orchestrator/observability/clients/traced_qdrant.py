"""
TracedQdrantClient - OpenTelemetry instrumented wrapper for Qdrant.

This module provides a composition-based wrapper around the Qdrant AsyncQdrantClient
that automatically creates OTEL spans for all database operations.

Usage:
    from qdrant_client import AsyncQdrantClient
    from observability.clients.traced_qdrant import TracedQdrantClient

    # Create traced client
    qdrant = AsyncQdrantClient(url="http://localhost:6333")
    traced = TracedQdrantClient(client=qdrant, collection_name="documents")

    # All operations are automatically traced
    results = await traced.query_points(query=[0.1, 0.2, ...], limit=10)
"""

import logging
from typing import Any

from observability.otel.span_names import SpanNames
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

logger = logging.getLogger(__name__)

# Get tracer for this module
tracer = trace.get_tracer(__name__)


class TracedQdrantClient:
    """
    OpenTelemetry-instrumented wrapper for Qdrant AsyncQdrantClient.

    Uses composition to wrap an existing client instance, adding tracing
    to all database operations without modifying the underlying client.

    Attributes:
        _client: The underlying Qdrant client
        _collection_name: Default collection name for operations
    """

    def __init__(
        self,
        client: Any,
        collection_name: str,
    ) -> None:
        """
        Initialize TracedQdrantClient.

        Args:
            client: An AsyncQdrantClient instance to wrap
            collection_name: Default collection name for operations
        """
        self._client = client
        self._collection_name = collection_name

    @property
    def client(self) -> Any:
        """Return the underlying Qdrant client."""
        return self._client

    @property
    def collection_name(self) -> str:
        """Return the default collection name."""
        return self._collection_name

    async def query_points(
        self,
        query: list[float],
        limit: int = 10,
        collection_name: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """
        Search for similar vectors with tracing.

        Args:
            query: Query vector for similarity search
            limit: Maximum number of results to return
            collection_name: Collection to search (defaults to instance collection)
            **kwargs: Additional arguments passed to underlying client

        Returns:
            Search results from Qdrant

        Raises:
            Exception: If the search fails
        """
        effective_collection = collection_name or self._collection_name

        with tracer.start_as_current_span(
            SpanNames.QDRANT_QUERY,
            kind=SpanKind.CLIENT,
        ) as span:
            # Set span attributes
            span.set_attribute("db.system", "qdrant")
            span.set_attribute("db.operation", "query_points")
            span.set_attribute("db.collection", effective_collection)
            span.set_attribute("db.qdrant.limit", limit)
            span.set_attribute("db.qdrant.vector_size", len(query))

            try:
                result = await self._client.query_points(
                    collection_name=effective_collection,
                    query=query,
                    limit=limit,
                    **kwargs,
                )

                # Record result count
                result_count = len(result.points) if hasattr(result, "points") else 0
                span.set_attribute("db.qdrant.result_count", result_count)
                span.set_status(Status(StatusCode.OK))

                return result

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                logger.error(
                    f"Qdrant query_points failed: {e}",
                    extra={
                        "collection": effective_collection,
                        "limit": limit,
                    },
                )
                raise

    async def upsert(
        self,
        points: list[dict[str, Any]],
        collection_name: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """
        Insert or update vectors with tracing.

        Args:
            points: List of points to upsert
            collection_name: Collection to upsert into (defaults to instance collection)
            **kwargs: Additional arguments passed to underlying client

        Returns:
            Upsert response from Qdrant

        Raises:
            Exception: If the upsert fails
        """
        effective_collection = collection_name or self._collection_name

        with tracer.start_as_current_span(
            SpanNames.QDRANT_UPSERT,
            kind=SpanKind.CLIENT,
        ) as span:
            # Set span attributes
            span.set_attribute("db.system", "qdrant")
            span.set_attribute("db.operation", "upsert")
            span.set_attribute("db.collection", effective_collection)
            span.set_attribute("db.qdrant.points_count", len(points))

            try:
                result = await self._client.upsert(
                    collection_name=effective_collection,
                    points=points,
                    **kwargs,
                )

                span.set_status(Status(StatusCode.OK))
                return result

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                logger.error(
                    f"Qdrant upsert failed: {e}",
                    extra={
                        "collection": effective_collection,
                        "points_count": len(points),
                    },
                )
                raise

    async def delete(
        self,
        points_selector: Any,
        collection_name: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """
        Delete vectors with tracing.

        Args:
            points_selector: Selector for points to delete (IDs or filter)
            collection_name: Collection to delete from (defaults to instance collection)
            **kwargs: Additional arguments passed to underlying client

        Returns:
            Delete response from Qdrant

        Raises:
            Exception: If the delete fails
        """
        effective_collection = collection_name or self._collection_name

        with tracer.start_as_current_span(
            SpanNames.QDRANT_DELETE,
            kind=SpanKind.CLIENT,
        ) as span:
            # Set span attributes
            span.set_attribute("db.system", "qdrant")
            span.set_attribute("db.operation", "delete")
            span.set_attribute("db.collection", effective_collection)

            try:
                result = await self._client.delete(
                    collection_name=effective_collection,
                    points_selector=points_selector,
                    **kwargs,
                )

                span.set_status(Status(StatusCode.OK))
                return result

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                logger.error(
                    f"Qdrant delete failed: {e}",
                    extra={"collection": effective_collection},
                )
                raise
