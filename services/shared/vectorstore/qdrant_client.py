"""Qdrant Vector Store client wrapper for document embeddings."""

import os
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchValue,
    PointIdsList,
    PointStruct,
)

from shared.config.urls import get_qdrant_url


class QdrantVectorStore:
    """A wrapper around Qdrant client for vector storage operations."""

    def __init__(
        self,
        url: str | None = None,
        collection_name: str | None = None,
        timeout: int = 30,
    ):
        """Initialize Qdrant client.

        Args:
            url: Qdrant server URL. Defaults to QDRANT_URL env var or localhost.
            collection_name: Collection name. Defaults to QDRANT_COLLECTION env var or 'documents'.
            timeout: Request timeout in seconds.
        """
        self.client = QdrantClient(
            url=url or get_qdrant_url(),
            timeout=timeout,
        )
        self.collection_name = collection_name or os.getenv(
            "QDRANT_COLLECTION",
            "documents",
        )

    async def upsert(
        self,
        points: list[dict[str, Any]],
    ) -> None:
        """Upsert vectors with metadata.

        Args:
            points: List of dicts with 'id', 'vector', and 'payload' keys.
        """
        qdrant_points = [
            PointStruct(
                id=p["id"],
                vector=p["vector"],
                payload=p["payload"],
            )
            for p in points
        ]
        self.client.upsert(
            collection_name=self.collection_name,
            points=qdrant_points,
        )

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        filter_conditions: dict[str, Any] | None = None,
        score_threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        """Search for similar vectors.

        Args:
            query_vector: The query embedding vector.
            top_k: Number of results to return.
            filter_conditions: Dict of field->value for filtering.
            score_threshold: Minimum score threshold for results.

        Returns:
            List of dicts with 'id', 'score', and 'payload' keys.
        """
        qdrant_filter = self._build_filter(filter_conditions) if filter_conditions else None

        # Use query_points (replaces deprecated search method)
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=top_k,
            query_filter=qdrant_filter,
            score_threshold=score_threshold,
            with_payload=True,
        )

        return [
            {
                "id": str(hit.id),
                "score": hit.score,
                "payload": hit.payload,
            }
            for hit in response.points
        ]

    async def delete_by_document_id(
        self,
        document_id: str,
        tenant_id: str | None = None,
    ) -> int:
        """Delete all vectors associated with a document.

        Args:
            document_id: The document ID to delete vectors for.
            tenant_id: Optional tenant ID for scoped deletion (recommended for safety).

        Returns:
            Number of points deleted.
        """
        # Build filter conditions
        must_conditions = [
            FieldCondition(
                key="document_id",
                match=MatchValue(value=document_id),
            ),
        ]

        if tenant_id:
            must_conditions.append(
                FieldCondition(
                    key="tenant_id",
                    match=MatchValue(value=tenant_id),
                ),
            )

        # Count existing points before deletion
        count_result = self.client.count(
            collection_name=self.collection_name,
            count_filter=Filter(must=must_conditions),
        )
        count_before = count_result.count

        # Perform deletion
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=Filter(must=must_conditions),
        )

        return count_before

    async def delete_by_ids(self, point_ids: list[str]) -> None:
        """Delete vectors by their IDs.

        Args:
            point_ids: List of point IDs to delete.
        """
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=point_ids,
        )

    def _build_filter(self, conditions: dict[str, Any]) -> Filter:
        """Build Qdrant filter from conditions dict.

        Args:
            conditions: Dict of field->value pairs.

        Returns:
            Qdrant Filter object.
        """
        must = []
        for key, value in conditions.items():
            if isinstance(value, list):
                # For list values, match any value in the list
                must.append(FieldCondition(key=key, match=MatchValue(value=value)))
            else:
                must.append(FieldCondition(key=key, match=MatchValue(value=value)))
        return Filter(must=must)

    def health_check(self) -> bool:
        """Check Qdrant connectivity.

        Returns:
            True if Qdrant is reachable, False otherwise.
        """
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False

    def get_collection_info(self) -> dict[str, Any] | None:
        """Get information about the current collection.

        Returns:
            Collection info dict or None if collection doesn't exist.
        """
        try:
            info = self.client.get_collection(self.collection_name)
            return {
                "name": self.collection_name,
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
                "status": info.status.value,
            }
        except Exception:
            return None

    async def get_existing_chunk_ids(
        self,
        tenant_id: str,
        chunk_ids: list[str],
    ) -> list[str]:
        """Check which chunk IDs exist in Qdrant.

        Used by the reconciliation process to find missing chunks.

        Args:
            tenant_id: The tenant ID to filter by.
            chunk_ids: List of chunk IDs to check.

        Returns:
            List of chunk IDs that exist in Qdrant.
        """
        if not chunk_ids:
            return []

        # Use retrieve to get points by IDs, filtered by tenant
        # Points are stored with chunk_id as the point ID
        result = self.client.retrieve(
            collection_name=self.collection_name,
            ids=chunk_ids,
            with_payload=["tenant_id"],
        )

        # Filter to only include points matching the tenant
        return [
            str(point.id)
            for point in result
            if point.payload and point.payload.get("tenant_id") == tenant_id
        ]

    async def get_all_chunk_ids(
        self,
        tenant_id: str,
        batch_size: int = 100,
    ) -> list[str]:
        """Get all chunk IDs for a tenant.

        Used by the reconciliation process to find orphaned entries.

        Args:
            tenant_id: The tenant ID to filter by.
            batch_size: Number of points to retrieve per scroll batch.

        Returns:
            List of all chunk IDs for the tenant.
        """
        chunk_ids: list[str] = []
        offset = None

        tenant_filter = Filter(
            must=[
                FieldCondition(
                    key="tenant_id",
                    match=MatchValue(value=tenant_id),
                ),
            ],
        )

        while True:
            result = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=tenant_filter,
                limit=batch_size,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )

            points, next_offset = result

            for point in points:
                chunk_ids.append(str(point.id))

            if next_offset is None:
                break
            offset = next_offset

        return chunk_ids

    async def delete_by_chunk_id(self, chunk_id: str, tenant_id: str) -> None:
        """Delete a single point by chunk ID.

        Used by the reconciliation process to clean up orphaned entries.

        Args:
            chunk_id: The chunk ID (point ID) to delete.
            tenant_id: The tenant ID for validation (unused but kept for API consistency).
        """
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=PointIdsList(points=[chunk_id]),
        )
